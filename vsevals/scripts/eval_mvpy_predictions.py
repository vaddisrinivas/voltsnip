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
    parser.add_argument("--failures-jsonl", type=Path)
    parser.add_argument("--taxonomy-json", type=Path)
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
            static = static_core11_check(code)
            if static["ok"]:
                stats["static_core11_ok"] += 1
            else:
                stats["static_core11_fail"] += 1
                for reason in static["reasons"]:
                    stats[f"static:{reason}"] += 1
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
                failures.append({"id": row_id, "kind": "timeout", "static": static})
                continue
            if proc.returncode == 0:
                stats["runtime_ok"] += 1
            else:
                stats["runtime_error"] += 1
                failures.append({"id": row_id, "kind": "runtime_error", "stderr": proc.stderr[:500], "static": static})
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
                    "static": static,
                })
    taxonomy = build_taxonomy(failures, stats)
    summary = {
        "total": stats["total"],
        "missing": stats["missing"],
        "empty": stats["empty"],
        "static_core11_ok": stats["static_core11_ok"],
        "static_core11_fail": stats["static_core11_fail"],
        "static_core11_rate": rate(stats["static_core11_ok"], stats["total"]),
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
        "taxonomy": taxonomy,
        "failures_sample": failures[:50],
    }
    if args.json_report:
        args.json_report.parent.mkdir(parents=True, exist_ok=True)
        args.json_report.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    text = render_report(summary)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text, encoding="utf-8")
    if args.failures_jsonl:
        args.failures_jsonl.parent.mkdir(parents=True, exist_ok=True)
        with args.failures_jsonl.open("w", encoding="utf-8") as fh:
            for failure in failures:
                fh.write(json.dumps(failure, ensure_ascii=False) + "\n")
    if args.taxonomy_json:
        args.taxonomy_json.parent.mkdir(parents=True, exist_ok=True)
        args.taxonomy_json.write_text(json.dumps(taxonomy, indent=2) + "\n", encoding="utf-8")
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
        f"- Static core11 pass: {summary['static_core11_rate']:.2%}",
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


def static_core11_check(code: str) -> dict:
    reasons: list[str] = []
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return {"ok": False, "reasons": ["syntax_error"]}
    allowed = (
        ast.Module,
        ast.Assign,
        ast.Expr,
        ast.FunctionDef,
        ast.arguments,
        ast.arg,
        ast.Nonlocal,
        ast.Return,
        ast.Raise,
        ast.Try,
        ast.ExceptHandler,
        ast.While,
        ast.Yield,
        ast.Call,
        ast.Name,
        ast.Constant,
        ast.Load,
        ast.Store,
    )
    for node in ast.walk(tree):
        if not isinstance(node, allowed):
            reasons.append(type(node).__name__)
            continue
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if not isinstance(target, ast.Name):
                    reasons.append("non_name_assignment")
        elif isinstance(node, ast.FunctionDef):
            if node.decorator_list:
                reasons.append("decorator")
            if node.returns is not None:
                reasons.append("return_annotation")
            if node.args.posonlyargs or node.args.kwonlyargs or node.args.kw_defaults or node.args.defaults or node.args.vararg or node.args.kwarg:
                reasons.append("complex_arguments")
        elif isinstance(node, ast.Try):
            if node.orelse or node.finalbody:
                reasons.append("try_else_finally")
            for handler in node.handlers:
                if handler.type is not None or handler.name is not None:
                    reasons.append("typed_except")
        elif isinstance(node, ast.Call):
            if node.keywords:
                reasons.append("keyword_call")
            if not isinstance(node.func, ast.Name):
                reasons.append("non_name_call")
        elif isinstance(node, ast.Constant):
            if not (isinstance(node.value, int) or node.value is None):
                reasons.append(f"constant_{type(node.value).__name__}")
    unique = sorted(set(reasons))
    return {"ok": not unique, "reasons": unique}


def build_taxonomy(failures: list[dict], stats: Counter) -> dict:
    by_kind = Counter(failure["kind"] for failure in failures)
    stderr_classes = Counter()
    static_reasons = Counter()
    for failure in failures:
        stderr = failure.get("stderr", "")
        if "parse error" in stderr:
            stderr_classes["parse_error"] += 1
        elif "undefined name" in stderr:
            stderr_classes["undefined_name"] += 1
        elif "expects int" in stderr:
            stderr_classes["type_error_expects_int"] += 1
        elif "not callable" in stderr:
            stderr_classes["not_callable"] += 1
        elif stderr:
            stderr_classes["other_runtime"] += 1
        for reason in failure.get("static", {}).get("reasons", []):
            static_reasons[reason] += 1
    return {
        "failure_kinds": dict(sorted(by_kind.items())),
        "stderr_classes": dict(sorted(stderr_classes.items())),
        "static_reasons": dict(sorted(static_reasons.items())),
        "static_counter_keys": {
            key.removeprefix("static:"): value
            for key, value in sorted(stats.items())
            if key.startswith("static:")
        },
    }


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
