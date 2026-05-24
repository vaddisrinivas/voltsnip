#!/usr/bin/env python3
"""Evaluate model predictions by compiling/running MVPy."""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import shutil
import subprocess
import tempfile
from collections import Counter
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--predictions", required=True, type=Path)
    parser.add_argument("--mvpy-bin", type=Path, default=None)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--json-report", type=Path)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    mvpy = find_mvpy(args.mvpy_bin)
    expected = {}
    for idx, row in enumerate(read_jsonl(args.dataset)):
        if args.limit is not None and idx >= args.limit:
            break
        expected[row["id"]] = row
    predictions = {row["id"]: row.get("prediction", "") for row in read_jsonl(args.predictions)}

    stats = Counter()
    feature_stats: dict[str, Counter] = {}
    band_stats: dict[str, Counter] = {}
    category_stats: dict[str, Counter] = {}
    failures = []
    with tempfile.TemporaryDirectory(prefix="mvpy_pred_eval_") as td:
        root = Path(td)
        for row_id, row in expected.items():
            stats["total"] += 1
            raw = predictions.get(row_id)
            if raw is None:
                stats["missing"] += 1
                failures.append({"id": row_id, "kind": "missing"})
                continue
            code = extract_mvpy(raw)
            if not code.strip():
                stats["empty"] += 1
                failures.append({"id": row_id, "kind": "empty"})
                continue
            for feature in row.get("features", []):
                feature_stats.setdefault(feature, Counter())["total"] += 1
            band_stats.setdefault(row.get("difficulty_band", "unknown"), Counter())["total"] += 1
            category_stats.setdefault(row.get("category", "unknown"), Counter())["total"] += 1
            src = root / f"{row_id}.mvpy"
            src.write_text(code, encoding="utf-8")
            try:
                proc = subprocess.run([str(mvpy), str(src)], capture_output=True, text=True, timeout=5)
            except subprocess.TimeoutExpired:
                stats["timeout"] += 1
                stats["runtime_error"] += 1
                failures.append({"id": row_id, "kind": "timeout"})
                continue
            if proc.returncode == 0:
                stats["runtime_ok"] += 1
            else:
                stats["runtime_error"] += 1
                failures.append({"id": row_id, "kind": "runtime_error", "stderr": proc.stderr[:500]})
                continue
            if proc.stdout == row["stdout"]:
                stats["exact_ok"] += 1
                for feature in row.get("features", []):
                    feature_stats.setdefault(feature, Counter())["exact_ok"] += 1
                band_stats.setdefault(row.get("difficulty_band", "unknown"), Counter())["exact_ok"] += 1
                category_stats.setdefault(row.get("category", "unknown"), Counter())["exact_ok"] += 1
            else:
                stats["stdout_mismatch"] += 1
                failures.append({
                    "id": row_id,
                    "kind": "stdout_mismatch",
                    "got": proc.stdout,
                    "want": row["stdout"],
                })
    summary = {
        "total": stats["total"],
        "missing": stats["missing"],
        "empty": stats["empty"],
        "runtime_ok": stats["runtime_ok"],
        "runtime_error": stats["runtime_error"],
        "timeout": stats["timeout"],
        "exact_ok": stats["exact_ok"],
        "stdout_mismatch": stats["stdout_mismatch"],
        "exact_rate": rate(stats["exact_ok"], stats["total"]),
        "runtime_rate": rate(stats["runtime_ok"], stats["total"]),
        "features": {
            feature: {
                "total": vals["total"],
                "exact_ok": vals["exact_ok"],
                "exact_rate": rate(vals["exact_ok"], vals["total"]),
            }
            for feature, vals in sorted(feature_stats.items())
        },
        "bands": summarize_group(band_stats),
        "categories": summarize_group(category_stats),
        "failures_sample": failures[:50],
    }
    if args.json_report:
        args.json_report.parent.mkdir(parents=True, exist_ok=True)
        args.json_report.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    text = render_report(summary)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text, encoding="utf-8")
    print(text)


def extract_mvpy(text: str) -> str:
    text = text.strip()
    if not text:
        return ""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE).strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict) and isinstance(parsed.get("code"), str):
            return parsed["code"]
    except Exception:
        pass
    match = re.search(r"```(?:mvpy|mvp|python|text)?\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip() + "\n"
    if "emit_mvpy" in text:
        try:
            expr = ast.parse(text, mode="eval").body
            if isinstance(expr, ast.Call):
                for kw in expr.keywords:
                    if kw.arg == "code" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                        return kw.value.value
        except Exception:
            pass
        match = re.search(r"emit_mvpy\s*\(\s*code\s*=\s*(?P<q>['\"])(?P<body>.*?)(?P=q)\s*\)", text, flags=re.DOTALL)
        if match:
            return bytes(match.group("body"), "utf-8").decode("unicode_escape")
    return text if text.endswith("\n") else text + "\n"


def render_report(summary: dict) -> str:
    lines = [
        "# MVPy Prediction Evaluation",
        "",
        f"- Rows: {summary['total']}",
        f"- Runtime pass: {summary['runtime_rate']:.2%}",
        f"- Exact stdout pass: {summary['exact_rate']:.2%}",
        f"- Missing: {summary['missing']}",
        f"- Empty: {summary['empty']}",
        f"- Runtime errors: {summary['runtime_error']}",
        f"- Timeouts: {summary['timeout']}",
        f"- Stdout mismatches: {summary['stdout_mismatch']}",
        "",
        "| Feature | Rows | Exact | Rate |",
        "| --- | ---: | ---: | ---: |",
    ]
    for feature, vals in summary["features"].items():
        lines.append(f"| `{feature}` | {vals['total']} | {vals['exact_ok']} | {vals['exact_rate']:.2%} |")
    lines.extend(["", "| Band | Rows | Exact | Rate |", "| --- | ---: | ---: | ---: |"])
    for band, vals in summary["bands"].items():
        lines.append(f"| `{band}` | {vals['total']} | {vals['exact_ok']} | {vals['exact_rate']:.2%} |")
    lines.extend(["", "| Category | Rows | Exact | Rate |", "| --- | ---: | ---: | ---: |"])
    for category, vals in summary["categories"].items():
        lines.append(f"| `{category}` | {vals['total']} | {vals['exact_ok']} | {vals['exact_rate']:.2%} |")
    return "\n".join(lines) + "\n"


def read_jsonl(path: Path):
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def find_mvpy(explicit: Path | None) -> Path:
    candidates = [
        explicit,
        Path(os.environ["MVPY_BIN"]) if os.environ.get("MVPY_BIN") else None,
        Path("/tmp/mvpy-v0.1"),
        Path("/Users/srinivasvaddi/Projects/mvpy/mvpy"),
        Path(shutil.which("mvpy")) if shutil.which("mvpy") else None,
    ]
    for candidate in candidates:
        if candidate and candidate.exists():
            return candidate.resolve()
    raise SystemExit("MVPY_BIN not set and no mvpy binary found")


def rate(num: int, den: int) -> float:
    return float(num) / float(den) if den else 0.0


def summarize_group(groups: dict[str, Counter]) -> dict:
    return {
        name: {
            "total": vals["total"],
            "exact_ok": vals["exact_ok"],
            "exact_rate": rate(vals["exact_ok"], vals["total"]),
        }
        for name, vals in sorted(groups.items())
    }


if __name__ == "__main__":
    main()
