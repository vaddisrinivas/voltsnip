#!/usr/bin/env python3
"""Run an overnight MVPy Colab teacher/train/eval job."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def timestamp() -> str:
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run(cmd: list[str], log_path: Path, cwd: Path = ROOT, env: dict[str, str] | None = None) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    merged = os.environ.copy()
    if env:
        merged.update(env)
    print("$ " + " ".join(cmd), flush=True)
    with log_path.open("a", encoding="utf-8") as log:
        log.write("$ " + " ".join(cmd) + "\n")
        log.flush()
        proc = subprocess.Popen(cmd, cwd=cwd, env=merged, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        assert proc.stdout is not None
        for line in proc.stdout:
            print(line, end="", flush=True)
            log.write(line)
        code = proc.wait()
    if code:
        raise SystemExit(f"command failed ({code}): {' '.join(cmd)}")


def count_jsonl(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open(encoding="utf-8") as fh:
        return sum(1 for line in fh if line.strip())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default="overnight_" + timestamp())
    parser.add_argument("--run-root", type=Path)
    parser.add_argument("--teacher-source", type=Path, default=ROOT / "data/mvpy_research_v2_oodmix/train_qwen.jsonl")
    parser.add_argument("--existing-dir", type=Path, default=ROOT / "data/mvpy_research_mlx_plan_v2")
    parser.add_argument("--mvpy-bin", type=Path, default=Path("/content/mvpy-v0.1"))
    parser.add_argument("--teacher-model", default="gpt-5.3-codex")
    parser.add_argument("--fallback-provider")
    parser.add_argument("--fallback-model")
    parser.add_argument("--easy", type=int, default=100)
    parser.add_argument("--medium", type=int, default=250)
    parser.add_argument("--hard", type=int, default=250)
    parser.add_argument("--teacher-max-tokens", type=int, default=2048)
    parser.add_argument("--repair-turns", type=int, default=2)
    parser.add_argument("--train-steps", type=int, nargs="+", default=[500, 1000])
    parser.add_argument("--rank", type=int, default=16)
    parser.add_argument("--max-seq-length", type=int, default=1024)
    parser.add_argument("--model", default="unsloth/gemma-4-E4B-it")
    parser.add_argument("--prompt-modes", nargs="+", default=["gemma_patterns", "plan_code"])
    parser.add_argument("--max-tokens", type=int, default=384)
    parser.add_argument("--skip-teacher", action="store_true")
    parser.add_argument("--skip-training", action="store_true")
    args = parser.parse_args()

    run_root = args.run_root or (ROOT / "results/colab_runs" / args.run_id)
    run_root.mkdir(parents=True, exist_ok=True)
    logs = run_root / "logs"
    manifest = {
        "run_id": args.run_id,
        "created_utc": timestamp(),
        "teacher_source": str(args.teacher_source),
        "existing_dir": str(args.existing_dir),
        "mvpy_bin": str(args.mvpy_bin),
        "teacher_model": args.teacher_model,
        "limits": {"easy": args.easy, "medium": args.medium, "hard": args.hard},
        "train_steps": args.train_steps,
        "model": args.model,
        "prompt_modes": args.prompt_modes,
        "env": {
            "OPENAI_API_KEY": bool(os.environ.get("OPENAI_API_KEY")),
            "ANTHROPIC_API_KEY": bool(os.environ.get("ANTHROPIC_API_KEY")),
            "HF_TOKEN": bool(os.environ.get("HF_TOKEN")),
            "GH_TOKEN": bool(os.environ.get("GH_TOKEN")),
        },
    }
    write_json(run_root / "manifest.json", manifest)

    teacher_paths: list[Path] = []
    if not args.skip_teacher:
        for band, limit in [("easy", args.easy), ("medium", args.medium), ("hard", args.hard)]:
            if limit <= 0:
                continue
            out = run_root / "teacher" / f"{band}_oracle.jsonl"
            teacher_paths.append(out)
            cmd = [
                sys.executable,
                "colab/mvpy_active_teacher.py",
                "teacher",
                "--dataset",
                str(args.teacher_source),
                "--out",
                str(out),
                "--provider",
                "openai",
                "--model",
                args.teacher_model,
                "--band",
                band,
                "--limit",
                str(limit),
                "--repair-turns",
                str(args.repair_turns),
                "--max-tokens",
                str(args.teacher_max_tokens),
                "--mvpy-bin",
                str(args.mvpy_bin),
                "--oracle",
            ]
            if args.fallback_provider and args.fallback_model:
                cmd += ["--fallback-provider", args.fallback_provider, "--fallback-model", args.fallback_model]
            run(cmd, logs / f"teacher_{band}.log")
            run(
                [
                    sys.executable,
                    "colab/mvpy_colab_plan.py",
                    "verify-teacher",
                    "--accepted",
                    str(out),
                    "--mvpy-bin",
                    str(args.mvpy_bin),
                    "--report",
                    str(run_root / "teacher" / f"{band}_verify.json"),
                ],
                logs / f"teacher_{band}_verify.log",
            )
            run(
                [
                    sys.executable,
                    "colab/mvpy_colab_plan.py",
                    "teacher-report",
                    "--accepted",
                    str(out),
                    "--out",
                    str(run_root / "teacher" / f"{band}_report.json"),
                ],
                logs / f"teacher_{band}_report.log",
            )
    else:
        teacher_paths = sorted((run_root / "teacher").glob("*_oracle.jsonl"))

    sft_dir = run_root / "sft_mixed_plan"
    cmd = [
        sys.executable,
        "colab/mvpy_colab_plan.py",
        "combine-sft",
        "--existing-dir",
        str(args.existing_dir),
        "--out-dir",
        str(sft_dir),
        "--target",
        "plan_code",
        "--teacher-limit",
        "1000000",
    ]
    for path in teacher_paths:
        if path.exists():
            cmd += ["--teacher", str(path)]
    run(cmd, logs / "combine_sft.log")

    summary: dict[str, Any] = {
        "run_id": args.run_id,
        "teacher_rows": {path.name: count_jsonl(path) for path in teacher_paths},
        "sft_train_rows": count_jsonl(sft_dir / "train.jsonl"),
        "sft_valid_rows": count_jsonl(sft_dir / "valid.jsonl"),
        "runs": [],
    }
    write_json(run_root / "summary.json", summary)

    if not args.skip_training:
        for steps in args.train_steps:
            train_dir = run_root / "train" / f"gemma4_e4b_mixed_{steps}"
            run(
                [
                    sys.executable,
                    "colab/train_unsloth_mvpy.py",
                    "--family",
                    "gemma4",
                    "--model",
                    args.model,
                    "--load-in-4bit",
                    "--data-dir",
                    str(sft_dir),
                    "--out-dir",
                    str(train_dir),
                    "--max-seq-length",
                    str(args.max_seq_length),
                    "--max-steps",
                    str(steps),
                    "--rank",
                    str(args.rank),
                    "--save-steps",
                    "100",
                    "--eval-steps",
                    "100",
                    "--run-id",
                    f"{args.run_id}_{steps}",
                ],
                logs / f"train_{steps}.log",
            )
            adapter = train_dir / "adapter"
            for mode in args.prompt_modes:
                pred_base = run_root / "predictions" / f"gemma4_{steps}_{mode}"
                eval_base = run_root / "evals" / f"gemma4_{steps}_{mode}"
                pred_base.mkdir(parents=True, exist_ok=True)
                eval_base.mkdir(parents=True, exist_ok=True)
                for label, dataset, limit in [
                    ("analysis_500", ROOT / "data/mvpy_research_v2_oodmix/analysis_qwen.jsonl", None),
                    ("ood100", ROOT / "data/mvpy_ood_500/ood_stratified_100_qwen.jsonl", None),
                    ("ood500", ROOT / "data/mvpy_ood_500/ood_qwen.jsonl", None),
                    ("holdout_v2_100", ROOT / "data/mvpy_ood_holdout_v2/ood_holdout_v2_stratified_100_qwen.jsonl", None),
                ]:
                    pred = pred_base / f"{label}.jsonl"
                    run(
                        [
                            sys.executable,
                            "colab/predict_unsloth_mvpy.py",
                            "--family",
                            "gemma4",
                            "--model",
                            args.model,
                            "--adapter-path",
                            str(adapter),
                            "--load-in-4bit",
                            "--dataset",
                            str(dataset),
                            "--output",
                            str(pred),
                            "--prompt-mode",
                            mode,
                            "--max-seq-length",
                            str(args.max_seq_length),
                            "--max-tokens",
                            str(args.max_tokens),
                            "--resume",
                        ],
                        logs / f"predict_{steps}_{mode}_{label}.log",
                    )
                    run(
                        [
                            sys.executable,
                            "scripts/eval_mvpy_predictions.py",
                            "--dataset",
                            str(dataset),
                            "--predictions",
                            str(pred),
                            "--mvpy-bin",
                            str(args.mvpy_bin),
                            "--report",
                            str(eval_base / f"{label}.md"),
                            "--json-report",
                            str(eval_base / f"{label}.json"),
                            "--failures-jsonl",
                            str(eval_base / f"{label}_failures.jsonl"),
                            "--taxonomy-json",
                            str(eval_base / f"{label}_taxonomy.json"),
                        ],
                        logs / f"eval_{steps}_{mode}_{label}.log",
                    )
                summary["runs"].append({"steps": steps, "prompt_mode": mode, "adapter": str(adapter)})
                write_json(run_root / "summary.json", summary)

    run(
        [
            sys.executable,
            "colab/mvpy_colab_plan.py",
            "leaderboard",
            "--root",
            str(run_root),
            "--out",
            str(run_root / "leaderboard.md"),
        ],
        logs / "leaderboard.log",
    )
    run(["tar", "-czf", f"/content/{args.run_id}_results.tar.gz", "-C", str(run_root.parent), run_root.name], logs / "tar.log", cwd=ROOT)
    print(json.dumps({"done": True, "run_root": str(run_root), "tar": f"/content/{args.run_id}_results.tar.gz"}, indent=2))


if __name__ == "__main__":
    main()
