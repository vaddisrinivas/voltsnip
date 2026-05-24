#!/usr/bin/env python3
"""Colab orchestration helpers for MVPy SFT runs.

This stays stdlib-only so it can run before GPU packages install.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PINNED_MVPY_COMMIT = "671aecf"
DEFAULT_RUN_ROOT = ROOT / "results" / "colab_runs"


def read_jsonl(path: Path):
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def timestamp() -> str:
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())


def percentile(values: list[int], pct: float) -> int:
    if not values:
        return 0
    values = sorted(values)
    idx = min(len(values) - 1, int(round((len(values) - 1) * pct)))
    return values[idx]


def row_program_hash(row: dict[str, Any]) -> str | None:
    if row.get("program_sha256"):
        return str(row["program_sha256"])
    if row.get("mvpy"):
        return sha256_text(row["mvpy"])
    if row.get("target_text"):
        return sha256_text(row["target_text"])
    return None


def prompt_text(row: dict[str, Any]) -> str:
    if row.get("prompt_raw"):
        return str(row["prompt_raw"])
    if row.get("messages"):
        return "\n".join(str(msg.get("content", "")) for msg in row["messages"] if msg.get("role") != "assistant")
    return ""


def load_dataset_stats(path: Path) -> dict[str, Any]:
    rows = list(read_jsonl(path))
    ids = [row.get("id") for row in rows]
    program_hashes = [h for row in rows if (h := row_program_hash(row))]
    prompt_hashes = [sha256_text(prompt_text(row)) for row in rows]
    categories = Counter(str(row.get("category", "unknown")) for row in rows)
    bands = Counter(str(row.get("difficulty_band", "unknown")) for row in rows)
    features = Counter(feature for row in rows for feature in row.get("features", []))
    return {
        "path": str(path),
        "rows": len(rows),
        "unique_ids": len(set(ids)),
        "duplicate_ids": len(ids) - len(set(ids)),
        "program_hashes": set(program_hashes),
        "prompt_hashes": set(prompt_hashes),
        "categories": dict(sorted(categories.items())),
        "bands": dict(sorted(bands.items())),
        "top_features": dict(features.most_common(30)),
    }


def message_to_text(row: dict[str, Any], tokenizer: Any | None) -> str:
    messages = row.get("messages", [])
    if tokenizer is not None:
        try:
            return tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=False)
        except Exception:
            pass
    return "\n".join(f"{msg.get('role', '')}: {msg.get('content', '')}" for msg in messages)


def sequence_report(sft_dir: Path, tokenizer_name: str | None, max_seq_length: int) -> dict[str, Any]:
    tokenizer = None
    tokenizer_error = None
    if tokenizer_name:
        try:
            from transformers import AutoTokenizer

            tokenizer = AutoTokenizer.from_pretrained(tokenizer_name, trust_remote_code=True)
        except Exception as exc:  # pragma: no cover - depends on Colab packages.
            tokenizer_error = repr(exc)
    report: dict[str, Any] = {
        "sft_dir": str(sft_dir),
        "tokenizer": tokenizer_name,
        "tokenizer_error": tokenizer_error,
        "max_seq_length": max_seq_length,
        "splits": {},
    }
    for split in ["train", "valid", "test"]:
        path = sft_dir / f"{split}.jsonl"
        if not path.exists():
            continue
        lengths: list[int] = []
        rows = 0
        for row in read_jsonl(path):
            rows += 1
            text = message_to_text(row, tokenizer)
            if tokenizer is not None:
                lengths.append(len(tokenizer.encode(text, add_special_tokens=False)))
            else:
                lengths.append(len(text))
        report["splits"][split] = {
            "rows": rows,
            "length_unit": "tokens" if tokenizer is not None else "chars",
            "p50": percentile(lengths, 0.50),
            "p95": percentile(lengths, 0.95),
            "max": max(lengths) if lengths else 0,
            "over_max_seq_length": sum(1 for value in lengths if value > max_seq_length),
        }
    return report


def command_audit_data(args: argparse.Namespace) -> None:
    out_dir = args.out_dir or (DEFAULT_RUN_ROOT / f"audit_{timestamp()}")
    out_dir.mkdir(parents=True, exist_ok=True)
    train = load_dataset_stats(args.train_source)
    eval_sets = {path.name: load_dataset_stats(path) for path in args.eval_set}
    leaks = {}
    for path in args.eval_set:
        leaked = []
        for row in read_jsonl(path):
            program = str(row.get("mvpy") or row.get("target_text") or "")
            prompt = prompt_text(row)
            long_lines = [line.strip() for line in program.splitlines() if len(line.strip()) >= 24]
            if program.strip() and program.strip() in prompt:
                leaked.append({"id": row.get("id"), "kind": "full_program"})
            elif any(line in prompt for line in long_lines):
                leaked.append({"id": row.get("id"), "kind": "program_line"})
        leaks[path.name] = leaked[:20]
    overlaps = {}
    for name, stats in eval_sets.items():
        overlaps[name] = {
            "program_hash_overlap": len(train["program_hashes"] & stats["program_hashes"]),
            "prompt_hash_overlap": len(train["prompt_hashes"] & stats["prompt_hashes"]),
        }
    report = {
        "created_utc": timestamp(),
        "train_source": {k: v for k, v in train.items() if not isinstance(v, set)},
        "eval_sets": {name: {k: v for k, v in stats.items() if not isinstance(v, set)} for name, stats in eval_sets.items()},
        "overlaps_with_train": overlaps,
        "eval_prompt_leak_samples": leaks,
        "sequence_report": sequence_report(args.sft_dir, args.tokenizer, args.max_seq_length),
    }
    (out_dir / "audit_data.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (out_dir / "audit_data.md").write_text(render_audit(report), encoding="utf-8")
    print(json.dumps({"out_dir": str(out_dir), "ok": True}, indent=2))


def render_audit(report: dict[str, Any]) -> str:
    lines = ["# MVPy Colab Data Audit", ""]
    train = report["train_source"]
    lines += [
        f"- Train rows: {train['rows']}",
        f"- Train duplicate IDs: {train['duplicate_ids']}",
        "",
        "| Eval Set | Rows | Program Hash Overlap | Prompt Hash Overlap | Leak Samples |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for name, stats in report["eval_sets"].items():
        overlap = report["overlaps_with_train"][name]
        leaks = len(report["eval_prompt_leak_samples"][name])
        lines.append(
            f"| `{name}` | {stats['rows']} | {overlap['program_hash_overlap']} | "
            f"{overlap['prompt_hash_overlap']} | {leaks} |"
        )
    lines += ["", "| Split | Rows | Unit | p50 | p95 | Max | Over Limit |", "| --- | ---: | --- | ---: | ---: | ---: | ---: |"]
    for split, vals in report["sequence_report"]["splits"].items():
        lines.append(
            f"| `{split}` | {vals['rows']} | {vals['length_unit']} | {vals['p50']} | "
            f"{vals['p95']} | {vals['max']} | {vals['over_max_seq_length']} |"
        )
    return "\n".join(lines) + "\n"


def load_hashes(paths: list[Path]) -> set[str]:
    hashes: set[str] = set()
    for path in paths:
        if not path.exists():
            continue
        files = sorted(path.rglob("*.jsonl")) if path.is_dir() else [path]
        for file in files:
            for row in read_jsonl(file):
                if h := row_program_hash(row):
                    hashes.add(h)
    return hashes


def command_build_holdout(args: argparse.Namespace) -> None:
    spec = importlib.util.spec_from_file_location("mvpy_generate_ood", ROOT / "scripts/generate_mvpy_ood.py")
    if spec is None or spec.loader is None:
        raise SystemExit("cannot load scripts/generate_mvpy_ood.py")
    gen = importlib.util.module_from_spec(spec)
    sys.modules["mvpy_generate_ood"] = gen
    spec.loader.exec_module(gen)

    mvpy = args.mvpy_bin
    if not mvpy.exists():
        raise SystemExit(f"missing verifier: {mvpy}")
    exclude = load_hashes(args.exclude)
    used: set[str] = set()
    rows: list[dict[str, Any]] = []
    plan = {"easy": args.easy, "medium": args.medium, "hard": args.hard}
    for band, count in plan.items():
        made = 0
        idx = args.start_index
        while made < count:
            case = gen.make_case(f"mvpy_holdout_v2_{len(rows) + 1:05d}", band, idx)
            idx += 1
            digest = sha256_text(case.program)
            if digest in exclude or digest in used:
                continue
            gen.validate(case, mvpy)
            row = gen.dataset_row(case, digest, mvpy)
            row["id"] = case.id
            row["split"] = "ood_holdout_v2"
            rows.append(row)
            used.add(digest)
            made += 1
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(args.out_dir / "ood_holdout_v2_qwen.jsonl", rows)
    write_jsonl(args.out_dir / "analysis_qwen.jsonl", rows)
    strat = [row for row in rows if row["difficulty_band"] == "easy"][:20]
    strat += [row for row in rows if row["difficulty_band"] == "medium"][:40]
    strat += [row for row in rows if row["difficulty_band"] == "hard"][:40]
    write_jsonl(args.out_dir / "ood_holdout_v2_stratified_100_qwen.jsonl", strat)
    manifest = {
        "dataset_id": "mvpy_ood_holdout_v2_realworld_analytics_500",
        "created_utc": timestamp(),
        "count": len(rows),
        "split_plan": plan,
        "start_index": args.start_index,
        "excluded_program_hashes": len(exclude),
        "sha_disjoint_from_excludes": True,
        "verifier_commit": PINNED_MVPY_COMMIT,
        "verifier_binary": str(mvpy),
        "verifier_sha256": sha256_file(mvpy),
        "categories_by_band": {
            band: sorted({row["category"] for row in rows if row["difficulty_band"] == band})
            for band in plan
        },
    }
    (args.out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))


def convert_teacher_row(row: dict[str, Any], target: str) -> dict[str, Any]:
    try:
        from colab.mvpy_active_teacher import MVPY_SPEC
    except ModuleNotFoundError:
        from mvpy_active_teacher import MVPY_SPEC

    if target == "plan_code":
        assistant = row.get("teacher_text") or f"```mvpy\n{row['mvpy']}\n```"
    else:
        assistant = row["mvpy"]
    return {
        "id": row["id"],
        "messages": [
            {"role": "system", "content": MVPY_SPEC},
            {"role": "user", "content": row["prompt_raw"]},
            {"role": "assistant", "content": assistant},
        ],
        "source": row.get("teacher", {}).get("model", "teacher"),
        "program_sha256": sha256_text(row["mvpy"]),
    }


def command_combine_sft(args: argparse.Namespace) -> None:
    existing_train = list(read_jsonl(args.existing_dir / "train.jsonl"))[: args.existing_limit]
    existing_valid = list(read_jsonl(args.existing_dir / "valid.jsonl"))
    add_train: list[dict[str, Any]] = []
    add_valid: list[dict[str, Any]] = []
    for path, limit, source in [
        *[(path, args.teacher_limit, "teacher") for path in args.teacher],
        *[(path, args.repair_limit, "repair") for path in args.repair],
    ]:
        if not path.exists():
            continue
        rows = list(read_jsonl(path))[:limit]
        converted = [convert_teacher_row(row, args.target) | {"source": source} for row in rows]
        split = max(1, int(len(converted) * (1 - args.valid_fraction))) if converted else 0
        add_train.extend(converted[:split])
        add_valid.extend(converted[split:] or converted[-1:])
    seen = set()
    train_rows = []
    for row in [*existing_train, *add_train]:
        key = row.get("program_sha256") or sha256_text(json.dumps(row.get("messages", []), sort_keys=True))
        if key in seen:
            continue
        seen.add(key)
        train_rows.append(row)
    valid_rows = [*existing_valid, *add_valid]
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(args.out_dir / "train.jsonl", train_rows)
    write_jsonl(args.out_dir / "valid.jsonl", valid_rows)
    manifest = {
        "created_utc": timestamp(),
        "existing_dir": str(args.existing_dir),
        "existing_train_rows": len(existing_train),
        "teacher_paths": [str(path) for path in args.teacher],
        "repair_paths": [str(path) for path in args.repair],
        "train_rows": len(train_rows),
        "valid_rows": len(valid_rows),
        "target": args.target,
        "train_sha256": sha256_file(args.out_dir / "train.jsonl"),
        "valid_sha256": sha256_file(args.out_dir / "valid.jsonl"),
    }
    (args.out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))


def command_verify_teacher(args: argparse.Namespace) -> None:
    ok = 0
    bad = 0
    rejects = []
    for row in read_jsonl(args.accepted):
        code = row.get("mvpy", "")
        with tempfile.TemporaryDirectory(prefix="mvpy_teacher_verify_") as td:
            src = Path(td) / f"{row.get('id', 'row')}.mvpy"
            src.write_text(code, encoding="utf-8")
            proc = subprocess.run([str(args.mvpy_bin), str(src)], capture_output=True, text=True, timeout=args.timeout)
            stdout, stderr = proc.stdout, proc.stderr
        if proc.returncode == 0 and stdout == row.get("stdout", ""):
            ok += 1
        else:
            bad += 1
            rejects.append({"id": row.get("id"), "exit": proc.returncode, "stdout": stdout, "stderr": stderr})
    report = {"path": str(args.accepted), "ok": ok, "bad": bad, "rejects_sample": rejects[:20]}
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


def token_count(usage: Any, names: list[str]) -> int:
    if not isinstance(usage, dict):
        return 0
    total = 0
    for name in names:
        value = usage.get(name)
        if isinstance(value, int):
            total += value
    details = usage.get("input_tokens_details") or usage.get("output_tokens_details")
    if isinstance(details, dict):
        for name in names:
            value = details.get(name)
            if isinstance(value, int):
                total += value
    return total


def command_teacher_report(args: argparse.Namespace) -> None:
    accepted_rows = list(read_jsonl(args.accepted)) if args.accepted.exists() else []
    reject_path = args.rejects or args.accepted.with_suffix(".rejects.jsonl")
    rejected_rows = list(read_jsonl(reject_path)) if reject_path.exists() else []
    provider_counts = Counter()
    input_tokens = 0
    output_tokens = 0
    attempts = 0
    for row in [*accepted_rows, *rejected_rows]:
        for attempt in row.get("attempts", []):
            attempts += 1
            provider_counts[f"{attempt.get('provider', 'unknown')}:{attempt.get('model', 'unknown')}"] += 1
            usage = attempt.get("usage")
            input_tokens += token_count(usage, ["input_tokens", "prompt_tokens"])
            output_tokens += token_count(usage, ["output_tokens", "completion_tokens"])
    dollars = (input_tokens / 1_000_000 * args.input_cost_per_mtok) + (
        output_tokens / 1_000_000 * args.output_cost_per_mtok
    )
    report = {
        "accepted": len(accepted_rows),
        "rejected": len(rejected_rows),
        "attempts": attempts,
        "provider_attempts": dict(sorted(provider_counts.items())),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "estimated_dollars": round(dollars, 6),
        "cost_per_accepted": round(dollars / len(accepted_rows), 6) if accepted_rows else None,
        "accepted_path": str(args.accepted),
        "rejects_path": str(reject_path),
    }
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


def eval_json_summary(path: Path) -> dict[str, Any] | None:
    try:
        obj = json.loads(path.read_text())
    except Exception:
        return None
    if "total" not in obj:
        return None
    manifest_path = path.parent / "manifest.json"
    manifest = {}
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text())
        except Exception:
            manifest = {}
    return {
        "path": str(path),
        "run": path.parent.name,
        "model": manifest.get("model") or path.parent.name,
        "dataset": path.stem.removeprefix("eval_"),
        "total": obj.get("total", 0),
        "exact_ok": obj.get("exact_ok", 0),
        "exact_rate": obj.get("exact_rate", 0.0),
        "runtime_ok": obj.get("runtime_ok", 0),
        "runtime_rate": obj.get("runtime_rate", 0.0),
        "static_core11_rate": obj.get("static_core11_rate"),
    }


def command_leaderboard(args: argparse.Namespace) -> None:
    rows = []
    for root in args.root:
        if not root.exists():
            continue
        for path in root.rglob("eval*.json"):
            if row := eval_json_summary(path):
                rows.append(row)
    rows.sort(key=lambda row: (row["exact_rate"], row["exact_ok"], row["runtime_rate"]), reverse=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render_leaderboard(rows), encoding="utf-8")
    json_out = args.out.with_suffix(".json")
    json_out.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"rows": len(rows), "out": str(args.out), "json": str(json_out)}, indent=2))


def render_leaderboard(rows: list[dict[str, Any]]) -> str:
    lines = [
        "# MVPy Colab Leaderboard",
        "",
        "| Rank | Model/Run | Eval | Rows | Exact | Exact % | Runtime | Runtime % | Static % |",
        "| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for idx, row in enumerate(rows, 1):
        static = row["static_core11_rate"]
        static_text = "" if static is None else f"{static:.1%}"
        lines.append(
            f"| {idx} | `{row['model']}` | `{row['dataset']}` | {row['total']} | {row['exact_ok']} | "
            f"{row['exact_rate']:.1%} | {row['runtime_ok']} | {row['runtime_rate']:.1%} | {static_text} |"
        )
    return "\n".join(lines) + "\n"


def command_run_manifest(args: argparse.Namespace) -> None:
    args.out.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "run_id": args.run_id,
        "created_utc": timestamp(),
        "cwd": str(Path.cwd()),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "gpu": gpu_name(),
        "mvpy_bin": str(args.mvpy_bin) if args.mvpy_bin else None,
        "mvpy_bin_sha256": sha256_file(args.mvpy_bin) if args.mvpy_bin and args.mvpy_bin.exists() else None,
        "mvpy_commit": PINNED_MVPY_COMMIT,
        "env_flags": {
            "OPENAI_API_KEY": bool(os.environ.get("OPENAI_API_KEY")),
            "ANTHROPIC_API_KEY": bool(os.environ.get("ANTHROPIC_API_KEY")),
            "HF_TOKEN": bool(os.environ.get("HF_TOKEN")),
            "GH_TOKEN": bool(os.environ.get("GH_TOKEN")),
        },
        "notes": args.note,
    }
    args.out.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))


def gpu_name() -> str:
    if not shutil.which("nvidia-smi"):
        return "none"
    proc = subprocess.run(
        ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip() or "unknown"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    audit = sub.add_parser("audit-data")
    audit.add_argument("--train-source", type=Path, default=ROOT / "data/mvpy_research_v2_oodmix/train_qwen.jsonl")
    audit.add_argument("--sft-dir", type=Path, default=ROOT / "data/mvpy_research_mlx_plan_v2")
    audit.add_argument("--eval-set", type=Path, action="append", default=[
        ROOT / "data/mvpy_ood_500/ood_stratified_100_qwen.jsonl",
        ROOT / "data/mvpy_ood_500/ood_qwen.jsonl",
    ])
    audit.add_argument("--tokenizer")
    audit.add_argument("--max-seq-length", type=int, default=1024)
    audit.add_argument("--out-dir", type=Path)
    audit.set_defaults(func=command_audit_data)

    holdout = sub.add_parser("build-holdout")
    holdout.add_argument("--out-dir", type=Path, default=ROOT / "data/mvpy_ood_holdout_v2")
    holdout.add_argument("--mvpy-bin", type=Path, default=Path("/content/mvpy-v0.1"))
    holdout.add_argument("--exclude", type=Path, action="append", default=[
        ROOT / "data/mvpy_research_v2_oodmix",
        ROOT / "data/mvpy_ood_500",
    ])
    holdout.add_argument("--easy", type=int, default=100)
    holdout.add_argument("--medium", type=int, default=200)
    holdout.add_argument("--hard", type=int, default=200)
    holdout.add_argument("--start-index", type=int, default=20000)
    holdout.set_defaults(func=command_build_holdout)

    combine = sub.add_parser("combine-sft")
    combine.add_argument("--existing-dir", type=Path, default=ROOT / "data/mvpy_research_mlx_plan_v2")
    combine.add_argument("--teacher", type=Path, action="append", default=[])
    combine.add_argument("--repair", type=Path, action="append", default=[])
    combine.add_argument("--out-dir", type=Path, required=True)
    combine.add_argument("--existing-limit", type=int, default=5000)
    combine.add_argument("--teacher-limit", type=int, default=2000)
    combine.add_argument("--repair-limit", type=int, default=1000)
    combine.add_argument("--valid-fraction", type=float, default=0.05)
    combine.add_argument("--target", choices=["code", "plan_code"], default="plan_code")
    combine.set_defaults(func=command_combine_sft)

    verify = sub.add_parser("verify-teacher")
    verify.add_argument("--accepted", type=Path, required=True)
    verify.add_argument("--mvpy-bin", type=Path, default=Path("/content/mvpy-v0.1"))
    verify.add_argument("--timeout", type=int, default=5)
    verify.add_argument("--report", type=Path)
    verify.set_defaults(func=command_verify_teacher)

    teacher_report = sub.add_parser("teacher-report")
    teacher_report.add_argument("--accepted", type=Path, required=True)
    teacher_report.add_argument("--rejects", type=Path)
    teacher_report.add_argument("--input-cost-per-mtok", type=float, default=0.0)
    teacher_report.add_argument("--output-cost-per-mtok", type=float, default=0.0)
    teacher_report.add_argument("--out", type=Path)
    teacher_report.set_defaults(func=command_teacher_report)

    board = sub.add_parser("leaderboard")
    board.add_argument("--root", type=Path, action="append", default=[
        ROOT / "results/colab_runs",
        ROOT / "results/mvpy_sft",
    ])
    board.add_argument("--out", type=Path, default=ROOT / "results/colab_runs/leaderboard.md")
    board.set_defaults(func=command_leaderboard)

    manifest = sub.add_parser("run-manifest")
    manifest.add_argument("--run-id", required=True)
    manifest.add_argument("--out", type=Path, required=True)
    manifest.add_argument("--mvpy-bin", type=Path)
    manifest.add_argument("--note", action="append", default=[])
    manifest.set_defaults(func=command_run_manifest)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
