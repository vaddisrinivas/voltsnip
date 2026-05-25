#!/usr/bin/env python3
"""Resume Gemma4 MVPy Colab evals and write a compact leaderboard.

Designed for flaky Colab T4 sessions:
- uploads the LoRA adapter to a private Hugging Face repo when possible
- resumes prediction JSONL files
- evaluates after each dataset so partial work is useful
- writes small reports under results/colab_runs/<run_id>
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import tarfile
import time
from pathlib import Path


DATASETS = {
    "ood100": "data/mvpy_ood_500/ood_stratified_100_qwen.jsonl",
    "holdout_v2_100": "data/mvpy_ood_holdout_v2/ood_holdout_v2_stratified_100_qwen.jsonl",
    "ood500": "data/mvpy_ood_500/ood_qwen.jsonl",
    "analysis_500": "data/mvpy_research_v2_oodmix/analysis_qwen.jsonl",
}


def run(cmd: list[str], *, allow_fail: bool = False) -> int:
    print("$ " + " ".join(shlex.quote(part) for part in cmd), flush=True)
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    proc = subprocess.run(cmd, env=env)
    if proc.returncode and not allow_fail:
        raise SystemExit(proc.returncode)
    return proc.returncode


def read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def upload_adapter_private(adapter: Path, run_dir: Path, repo_name: str) -> dict:
    status = {"attempted": False, "ok": False, "repo_id": None, "error": None}
    token = os.environ.get("HF_TOKEN")
    if not token or not adapter.exists():
        status["error"] = "HF_TOKEN missing or adapter missing"
        return status
    status["attempted"] = True
    try:
        from huggingface_hub import HfApi

        api = HfApi(token=token)
        user = api.whoami(token=token)["name"]
        repo_id = f"{user}/{repo_name}"
        api.create_repo(repo_id=repo_id, repo_type="model", private=True, exist_ok=True)
        api.upload_folder(
            repo_id=repo_id,
            repo_type="model",
            folder_path=str(adapter),
            path_in_repo="adapter",
            commit_message="Upload MVPy Gemma4 adapter",
        )
        manifest = run_dir / "manifest.json"
        if manifest.exists():
            api.upload_file(
                repo_id=repo_id,
                repo_type="model",
                path_or_fileobj=str(manifest),
                path_in_repo="manifest.json",
                commit_message="Upload MVPy run manifest",
            )
        status.update({"ok": True, "repo_id": repo_id})
    except Exception as exc:  # pragma: no cover - Colab-only path
        status["error"] = type(exc).__name__ + ": " + str(exc)[:400]
    return status


def eval_one(args: argparse.Namespace, mode: str, label: str, data: str) -> dict:
    run_dir = Path("results/colab_runs") / args.run_id
    pred = run_dir / "predictions" / f"gemma4_500_{mode}" / f"{label}.jsonl"
    eval_dir = run_dir / "evals" / f"gemma4_500_{mode}"
    pred.parent.mkdir(parents=True, exist_ok=True)
    eval_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    print(json.dumps({"phase": "predict", "mode": mode, "label": label, "data": data, "max_tokens": args.max_tokens}), flush=True)
    rc = run(
        [
            sys.executable,
            "colab/predict_unsloth_mvpy.py",
            "--family",
            "gemma4",
            "--model",
            args.model,
            "--adapter-path",
            str(args.adapter),
            "--load-in-4bit",
            "--dataset",
            data,
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
        allow_fail=args.allow_fail,
    )
    if rc:
        return {"mode": mode, "label": label, "predict_rc": rc}

    print(json.dumps({"phase": "eval", "mode": mode, "label": label}), flush=True)
    rc = run(
        [
            sys.executable,
            "scripts/eval_mvpy_predictions.py",
            "--dataset",
            data,
            "--predictions",
            str(pred),
            "--mvpy-bin",
            args.mvpy_bin,
            "--report",
            str(eval_dir / f"{label}.md"),
            "--json-report",
            str(eval_dir / f"{label}.json"),
            "--failures-jsonl",
            str(eval_dir / f"{label}_failures.jsonl"),
            "--taxonomy-json",
            str(eval_dir / f"{label}_taxonomy.json"),
        ],
        allow_fail=args.allow_fail,
    )
    summary = read_json(eval_dir / f"{label}.json")
    summary.update(
        {
            "mode": mode,
            "label": label,
            "data": data,
            "predict_rc": 0,
            "eval_rc": rc,
            "elapsed_sec": round(time.time() - t0, 1),
            "prediction_file": str(pred),
            "eval_json": str(eval_dir / f"{label}.json"),
        }
    )
    print(json.dumps({"done": label, "mode": mode, "exact": summary.get("exact_ok"), "total": summary.get("total"), "runtime": summary.get("runtime_ok")}), flush=True)
    return summary


def write_leaderboard(run_dir: Path, rows: list[dict]) -> None:
    write_json(run_dir / "leaderboard.json", {"rows": rows})
    lines = [
        "# MVPy Colab Leaderboard",
        "",
        "| Mode | Set | Exact | Runtime | Static | Notes |",
        "| --- | --- | ---: | ---: | ---: | --- |",
    ]
    for row in rows:
        total = row.get("total") or 0
        exact = f"{row.get('exact_ok', 0)}/{total}"
        runtime = f"{row.get('runtime_ok', 0)}/{total}"
        static = f"{row.get('static_core11_ok', 0)}/{total}"
        note = "ok" if not row.get("predict_rc") and not row.get("eval_rc") else f"rc {row.get('predict_rc')}/{row.get('eval_rc')}"
        lines.append(f"| `{row.get('mode')}` | `{row.get('label')}` | {exact} | {runtime} | {static} | {note} |")
    (run_dir / "leaderboard.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def tar_results(run_id: str) -> None:
    src = Path("results/colab_runs") / run_id
    out = Path("/content") / f"{run_id}_partial_results.tar.gz"
    if not src.exists():
        return
    with tarfile.open(out, "w:gz") as tar:
        tar.add(src, arcname=f"colab_runs/{run_id}")
    print(json.dumps({"tar": str(out), "bytes": out.stat().st_size}), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--mvpy-bin", default="/content/mvpy-v0.1")
    parser.add_argument("--model", default="unsloth/gemma-4-E4B-it")
    parser.add_argument("--max-seq-length", type=int, default=1024)
    parser.add_argument("--max-tokens", type=int, default=128)
    parser.add_argument("--modes", nargs="+", default=["gemma_patterns", "plan_code"])
    parser.add_argument("--sets", nargs="+", default=["ood100", "holdout_v2_100", "ood500"])
    parser.add_argument("--upload-hf", action="store_true")
    parser.add_argument("--allow-fail", action="store_true")
    args = parser.parse_args()

    os.chdir("/content/moltsnip/vsevals")
    run_dir = Path("results/colab_runs") / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        run_dir / "resume_eval_manifest.json",
        {
            "run_id": args.run_id,
            "adapter": str(args.adapter),
            "max_seq_length": args.max_seq_length,
            "max_tokens": args.max_tokens,
            "modes": args.modes,
            "sets": args.sets,
            "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
    )

    if args.upload_hf:
        status = upload_adapter_private(args.adapter, run_dir, f"mvpy-gemma4-e4b-mixed-500-{args.run_id}")
        write_json(run_dir / "hf_upload.json", status)
        print(json.dumps({"hf_upload": {k: v for k, v in status.items() if k != "error"}, "error": status.get("error")}), flush=True)

    rows: list[dict] = []
    for label in args.sets:
        data = DATASETS[label]
        for mode in args.modes:
            try:
                rows.append(eval_one(args, mode, label, data))
            finally:
                write_leaderboard(run_dir, rows)
                tar_results(args.run_id)
    write_leaderboard(run_dir, rows)
    tar_results(args.run_id)


if __name__ == "__main__":
    main()
