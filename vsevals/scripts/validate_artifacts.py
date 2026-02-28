"""Comprehensive artifact validator for vsevals run directories.

Reads EVERY file and cross-validates them against each other.
Does NOT trust summary_dump.json alone — verifies all claims against
the raw subprocess output, full_dump.json, and the patched source files.

Usage
-----
  uv run scripts/validate_artifacts.py vsevals_runs/matrix_20260228T.../
  uv run scripts/validate_artifacts.py vsevals_runs/          # all matrices
  uv run scripts/validate_artifacts.py <single_run_dir>/
  uv run scripts/validate_artifacts.py --fails-only ...       # quiet mode
"""

from __future__ import annotations

import ast
import csv
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ── Colour helpers ───────────────────────────────────────────────────────────

def _tty() -> bool:
    return sys.stdout.isatty()

def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _tty() else text

def green(t: str)  -> str: return _c("32", t)
def yellow(t: str) -> str: return _c("33", t)
def red(t: str)    -> str: return _c("31", t)
def bold(t: str)   -> str: return _c("1",  t)

PASS, FAIL, WARN, SKIP = "PASS", "FAIL", "WARN", "SKIP"


# ── Check / Report ───────────────────────────────────────────────────────────

@dataclass
class Check:
    tag: str
    status: str
    message: str

    def __str__(self) -> str:
        icon = {PASS: "✓", FAIL: "✗", WARN: "!", SKIP: "–"}.get(self.status, "?")
        col  = {PASS: green, FAIL: red, WARN: yellow}.get(self.status, str)
        return col(f"  [{self.tag}] {icon} {self.message}")


@dataclass
class RunReport:
    run_dir: Path
    checks: list[Check] = field(default_factory=list)

    def _add(self, tag: str, status: str, msg: str) -> None:
        self.checks.append(Check(tag, status, msg))

    def ok(self,   tag: str, msg: str) -> None: self._add(tag, PASS, msg)
    def fail(self, tag: str, msg: str) -> None: self._add(tag, FAIL, msg)
    def warn(self, tag: str, msg: str) -> None: self._add(tag, WARN, msg)
    def skip(self, tag: str, msg: str) -> None: self._add(tag, SKIP, msg)

    @property
    def failed(self) -> bool:
        return any(c.status == FAIL for c in self.checks)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _json(path: Path) -> tuple[Any, str | None]:
    raw = _read(path)
    if raw is None:
        return None, "file unreadable"
    try:
        return json.loads(raw), None
    except Exception as exc:
        return None, str(exc)


def _deep_get(obj: Any, *keys: str, default: Any = None) -> Any:
    for k in keys:
        if not isinstance(obj, dict):
            return default
        obj = obj.get(k, default)
    return obj


# ── Per-run validator ────────────────────────────────────────────────────────

_REQUIRED_FILES = [
    "summary_dump.json",
    "full_dump.json",
    "score_result.json",
    "generated_code.txt",
    "generated_comments.txt",
    "prompt.json",
]


def validate_run(run_dir: Path) -> RunReport:  # noqa: C901 – long but intentional
    r = RunReport(run_dir=run_dir)

    # ── [FILE] required files present ────────────────────────────────────────
    missing = [f for f in _REQUIRED_FILES if not (run_dir / f).exists()]
    if missing:
        r.fail("FILE", f"Missing required files: {', '.join(missing)}")
    else:
        r.ok("FILE", "All required files present")

    # ── Load every JSON artifact ──────────────────────────────────────────────
    summary,    e_sum  = _json(run_dir / "summary_dump.json")
    full,       e_full = _json(run_dir / "full_dump.json")
    score_file, e_sc   = _json(run_dir / "score_result.json")
    prompt_file,e_pr   = _json(run_dir / "prompt.json")

    for fname, err in [
        ("summary_dump.json", e_sum),
        ("full_dump.json",    e_full),
        ("score_result.json", e_sc),
        ("prompt.json",       e_pr),
    ]:
        if err:
            r.fail("JSON", f"{fname}: {err}")
        else:
            r.ok("JSON", f"{fname}: valid JSON")

    if full is None:
        r.fail("FULL", "full_dump.json unreadable — cannot run deep checks")
        return r

    # ── [STATUS] ─────────────────────────────────────────────────────────────
    status_full    = full.get("status", "")
    status_summary = (summary or {}).get("status", "")
    if status_full != "ok":
        r.fail("STATUS", f"full_dump status={status_full!r}")
        if full.get("error"):
            r.fail("STATUS", f"  error: {full['error']}")
    else:
        r.ok("STATUS", "status=ok")
    if summary and status_full != status_summary:
        r.fail("STATUS", f"status mismatch: full={status_full!r} vs summary={status_summary!r}")

    # ── [PROMPT] validate prompt.json ─────────────────────────────────────────
    if prompt_file is not None:
        sys_p  = prompt_file.get("system") or prompt_file.get("system_prompt") or ""
        usr_p  = prompt_file.get("user")   or prompt_file.get("user_prompt")   or ""
        if not sys_p.strip():
            r.fail("PROMPT", "system_prompt is empty")
        else:
            r.ok("PROMPT", f"system_prompt present ({len(sys_p)} chars)")
        if not usr_p.strip():
            r.fail("PROMPT", "user_prompt is empty")
        else:
            r.ok("PROMPT", f"user_prompt present ({len(usr_p)} chars)")
        # Line-range warning
        if "Target Lines:" in usr_p:
            if "IMPORTANT:" in usr_p and "Output ONLY" in usr_p:
                r.ok("PROMPT", "Line-range IMPORTANT warning present")
            else:
                r.fail("PROMPT", "Target Lines in prompt but IMPORTANT warning missing")
        else:
            r.ok("PROMPT", "Full-file task — no line-range constraint needed")
        # Cross-check: system prompt in full_dump matches prompt.json
        sys_full = _deep_get(full, "prompt", "system_prompt") or \
                   _deep_get(full, "prompt", "system") or ""
        if sys_full and sys_p and sys_full.strip() != sys_p.strip():
            r.warn("PROMPT", "system_prompt differs between prompt.json and full_dump.json")

    # ── [CODE] generated_code.txt ────────────────────────────────────────────
    code_path = run_dir / "generated_code.txt"
    code_txt  = (_read(code_path) or "").strip()
    if not code_txt:
        r.fail("CODE", "generated_code.txt is empty")
    else:
        r.ok("CODE", f"generated_code.txt: {len(code_txt)} chars, {code_txt.count(chr(10))+1} lines")

    # Cross-check: generated_code.txt == full_dump parsed_output.code
    full_code = (_deep_get(full, "parsed_output", "code") or "").strip()
    if code_txt and full_code:
        if code_txt != full_code:
            r.fail("CODE", "generated_code.txt content differs from full_dump.json parsed_output.code")
        else:
            r.ok("CODE", "generated_code.txt matches full_dump.json parsed_output.code")
    elif full_code and not code_txt:
        r.fail("CODE", "generated_code.txt empty but full_dump.json has parsed_output.code")
    elif code_txt and not full_code:
        r.fail("CODE", "generated_code.txt non-empty but full_dump.json parsed_output.code is empty")

    # ── [COMMENTS] generated_comments.txt ───────────────────────────────────
    comments_path = run_dir / "generated_comments.txt"
    comments_txt  = (_read(comments_path) or "").strip()
    full_comments = (_deep_get(full, "parsed_output", "comments") or "").strip()
    if not comments_txt:
        r.warn("COMMENTS", "generated_comments.txt is empty")
    else:
        r.ok("COMMENTS", f"generated_comments.txt: {comments_txt[:80]!r}")
    if comments_txt and full_comments and comments_txt != full_comments:
        r.fail("COMMENTS", "generated_comments.txt differs from full_dump.json parsed_output.comments")
    elif comments_txt and full_comments:
        r.ok("COMMENTS", "generated_comments.txt matches full_dump.json")

    # ── [PATCH] patched file checks ──────────────────────────────────────────
    patched_files = list(run_dir.glob("patched_*.py"))
    if not patched_files:
        r.skip("PATCH", "No patched_*.py (pytest not run or no target_file)")
    else:
        for pf in patched_files:
            src = _read(pf) or ""
            # Duplicate from __future__
            future_count = src.count("from __future__ import")
            if future_count > 1:
                r.fail("PATCH", f"{pf.name}: duplicate `from __future__` ({future_count}x) — file is corrupted")
            else:
                r.ok("PATCH", f"{pf.name}: no duplicate imports")
            # Valid Python syntax
            try:
                ast.parse(src)
                r.ok("PATCH", f"{pf.name}: valid Python syntax")
            except SyntaxError as exc:
                r.fail("PATCH", f"{pf.name}: SyntaxError line {exc.lineno}: {exc.msg}")
            # generated_code should appear somewhere in the patched file
            if code_txt and code_txt.strip() not in src:
                r.warn("PATCH", f"{pf.name}: generated_code.txt content not found verbatim in patched file")
            elif code_txt:
                r.ok("PATCH", f"{pf.name}: generated_code.txt content present in patched file")

    # ── [PYTEST] pytest results ──────────────────────────────────────────────
    pytest_result = full.get("pytest_result") or (summary or {}).get("pytest_result")
    if pytest_result is None:
        r.skip("PYTEST", "No pytest_result (auto_apply_patch not enabled)")
    else:
        rc   = pytest_result.get("returncode")
        ppass= pytest_result.get("passed")
        ran  = pytest_result.get("ran")
        dur  = pytest_result.get("duration_ms")
        err  = pytest_result.get("error")

        if not ran:
            r.fail("PYTEST", f"pytest did not run — error: {err}")
        elif rc == 0 and ppass:
            r.ok("PYTEST", f"pytest passed  returncode=0  duration_ms={dur}")
        elif rc == 4:
            r.fail("PYTEST", "pytest exit 4 (no tests collected / usage error) — overlay/workdir problem?")
        else:
            r.fail("PYTEST", f"pytest failed  returncode={rc}  passed={ppass}  error={err}")

        # Cross-check with stdout/stderr files
        stdout_txt = _read(run_dir / "pytest.stdout.txt") or ""
        stderr_txt = _read(run_dir / "pytest.stderr.txt") or ""

        if ran and rc == 0:
            if stdout_txt.strip() and "FAILED" not in stdout_txt and "ERROR" not in stdout_txt:
                r.ok("PYTEST", "pytest.stdout.txt contains no failures")
            elif "FAILED" in stdout_txt or "ERROR" in stdout_txt:
                r.fail("PYTEST", f"pytest.stdout.txt contains FAILED/ERROR: {stdout_txt.strip()[:120]!r}")
            else:
                r.warn("PYTEST", "pytest.stdout.txt is empty despite passed=True")

        if stderr_txt.strip():
            r.fail("PYTEST", f"pytest.stderr.txt non-empty: {stderr_txt.strip()[:200]!r}")
        else:
            r.ok("PYTEST", "pytest.stderr.txt empty")

    # ── [SCORE] scoring integrity ────────────────────────────────────────────
    score_full    = full.get("score") or {}
    score_summary = (summary or {}).get("score") or {}

    overall = score_full.get("overall_score")
    passed  = score_full.get("passed")
    threshold = score_full.get("constraint_pass_threshold") or 0.70

    if overall is None:
        r.fail("SCORE", "overall_score missing from full_dump.json score")
    else:
        if not (0.0 <= overall <= 1.0):
            r.fail("SCORE", f"overall_score={overall} out of [0, 1]")
        elif passed and overall < threshold:
            r.fail("SCORE", f"passed=True but score={overall:.3f} < threshold={threshold}")
        elif not passed and overall >= threshold:
            r.warn("SCORE", f"passed=False but score={overall:.3f} >= threshold={threshold}")
        else:
            r.ok("SCORE", f"overall_score={overall:.3f}  passed={passed}  threshold={threshold}")

    # Cross-check: full_dump score == score_result.json
    if score_file is not None:
        sc_overall = score_file.get("overall_score")
        if sc_overall is not None and overall is not None and abs(sc_overall - overall) > 1e-6:
            r.fail("SCORE", f"score_result.json overall={sc_overall:.3f} != full_dump score={overall:.3f}")
        elif sc_overall is not None:
            r.ok("SCORE", "score_result.json overall matches full_dump.json")

    # Cross-check: full_dump score == summary score
    sum_overall = _deep_get(score_summary, "overall_score")
    if sum_overall is not None and overall is not None and abs(sum_overall - overall) > 1e-6:
        r.fail("SCORE", f"summary_dump score={sum_overall:.3f} != full_dump score={overall:.3f}")
    elif sum_overall is not None:
        r.ok("SCORE", "summary_dump.json score matches full_dump.json")

    # Constraint details from score_result.json (most verbose source)
    cused   = (score_file or score_full).get("constraint_scoring_used", False)
    c_pass  = (score_file or score_full).get("constraint_checks_passed")
    c_total = (score_file or score_full).get("constraint_checks_total")
    if c_total is not None:
        r.ok("SCORE", f"constraint_scoring_used={cused}  {c_pass}/{c_total} constraints passed")
    for cr in ((score_file or {}).get("constraint_results") or []):
        cid    = cr.get("id", "?")
        cv     = cr.get("passed")
        reason = (cr.get("judge_reason") or "")[:100]
        lvl    = PASS if cv else FAIL
        r._add("SCORE", lvl, f"  constraint[{cid}]: passed={cv}  reason={reason!r}")

    # ── [STRUC] structured output ─────────────────────────────────────────────
    metrics = full.get("summary_metrics") or full.get("metrics") or (summary or {}).get("metrics") or {}
    attempted = metrics.get("structured_output_attempted")
    succeeded = metrics.get("structured_output_succeeded")
    fallback  = metrics.get("fallback_parser_used")

    if not attempted:
        r.skip("STRUC", "structured_output_attempted=False")
    elif succeeded:
        r.ok("STRUC", "structured_output_succeeded=True")
    else:
        r.fail("STRUC", "structured_output_succeeded=False")

    if fallback is None:
        r.skip("FALLB", "fallback_parser_used field absent")
    elif fallback:
        r.fail("FALLB", "fallback_parser_used=True — model did not produce valid JSON")
    else:
        r.ok("FALLB", "fallback_parser_used=False")

    # ── [SUBPROCESS] raw subprocess JSONL ────────────────────────────────────
    provider = metrics.get("model_provider", "")
    for provider_tag, jsonl_name in [
        ("claudecode", "subprocess.stdout.claudecode.jsonl"),
        ("codex",      "subprocess.stdout.codex.jsonl"),
    ]:
        jsonl_path = run_dir / jsonl_name
        if not jsonl_path.exists():
            if provider == provider_tag:
                r.warn("SUBPROC", f"{jsonl_name} missing for provider={provider!r}")
            continue

        raw_jsonl = _read(jsonl_path) or ""
        if not raw_jsonl.strip():
            r.fail("SUBPROC", f"{jsonl_name} is empty")
            continue

        lines = [ln for ln in raw_jsonl.splitlines() if ln.strip()]
        bad_lines: list[int] = []
        event_types: list[str] = []
        tool_use_count = 0
        result_found = False
        result_text  = ""

        for i, ln in enumerate(lines, 1):
            try:
                obj = json.loads(ln)
                evt = obj.get("type", "")
                event_types.append(evt)
                if evt == "toolUse":
                    tool_use_count += 1
                if evt == "result" and obj.get("subtype") == "success":
                    result_found = True
                    result_text  = obj.get("result", "")
            except Exception:
                bad_lines.append(i)

        if bad_lines:
            r.fail("SUBPROC", f"{jsonl_name}: {len(bad_lines)} non-JSON line(s) at positions {bad_lines[:5]}")
        else:
            r.ok("SUBPROC", f"{jsonl_name}: {len(lines)} lines, all valid JSON")

        unique_events = sorted(set(event_types))
        r.ok("SUBPROC", f"  event types: {unique_events}")

        if result_found:
            r.ok("SUBPROC", f"  result event present ({len(result_text)} chars)")
            # Cross-check: result event text should contain the code (after JSON parse)
            if code_txt and code_txt not in result_text:
                # result may be the raw JSON payload — try parsing it
                try:
                    parsed_result = json.loads(result_text)
                    extracted = (parsed_result.get("code") or "").strip()
                    if extracted and extracted == code_txt:
                        r.ok("SUBPROC", "  result event JSON code matches generated_code.txt")
                    else:
                        r.warn("SUBPROC", "  result event code doesn't match generated_code.txt verbatim")
                except Exception:
                    r.warn("SUBPROC", "  could not cross-check result event against generated_code.txt")
        else:
            r.warn("SUBPROC", f"  no result(subtype=success) event found in {jsonl_name}")

        # Variant tool expectation
        variant_id = full.get("variant_id") or (summary or {}).get("variant_id") or ""
        if variant_id in ("P7", "P8", "P9") and tool_use_count == 0:
            r.warn("SUBPROC", f"  tool variant {variant_id} but tool_use_count=0 (model chose not to use tools)")
        elif tool_use_count > 0:
            r.ok("SUBPROC", f"  tool_use events: {tool_use_count}")

    # ── [TOKENS] token usage ─────────────────────────────────────────────────
    tu = metrics.get("token_usage") or {}
    prompt_tok  = tu.get("prompt_tokens")
    output_tok  = tu.get("completion_tokens")
    cost        = tu.get("cost_usd")
    if prompt_tok is None:
        r.warn("TOKENS", "token_usage.prompt_tokens missing")
    elif prompt_tok == 0 and provider not in ("claudecode", "codex"):
        r.warn("TOKENS", f"prompt_tokens=0 for provider={provider!r}")
    else:
        r.ok("TOKENS", f"prompt={prompt_tok}  completion={output_tok}  cost_usd={cost}")

    # ── [FULL] deep fields in full_dump.json ──────────────────────────────────
    for fkey in ("run_id", "task_id", "variant_id", "model_name", "prompt"):
        if full.get(fkey) is None:
            r.warn("FULL", f"full_dump.json missing field: {fkey!r}")

    # messages (conversation turns)
    msgs = full.get("messages") or []
    if isinstance(msgs, list) and len(msgs) > 0:
        r.ok("FULL", f"messages: {len(msgs)} entries")
    else:
        r.warn("FULL", "messages empty or absent")

    # tool_traces
    tool_traces = full.get("tool_traces") or []
    r.ok("FULL", f"tool_traces: {len(tool_traces)} entries")

    # ── [COMPILE] try ast.parse on generated_code.txt ────────────────────────
    line_start = full.get("task_line_start")
    if code_txt:
        try:
            ast.parse(code_txt)
            r.ok("COMPILE", "generated_code.txt parses as valid Python")
        except SyntaxError as exc:
            if line_start is not None:
                # Partial rewrite — class body without module context won't parse standalone
                r.skip("COMPILE", f"generated_code.txt is a partial rewrite (lines {line_start}+) — standalone parse not applicable")
            else:
                r.fail("COMPILE", f"generated_code.txt SyntaxError line {exc.lineno}: {exc.msg}")

    return r


# ── Matrix-level validator ───────────────────────────────────────────────────

def validate_matrix(matrix_dir: Path) -> list[Check]:
    checks: list[Check] = []

    def ok(tag: str, msg: str)   -> None: checks.append(Check(tag, PASS, msg))
    def fail(tag: str, msg: str) -> None: checks.append(Check(tag, FAIL, msg))
    def warn(tag: str, msg: str) -> None: checks.append(Check(tag, WARN, msg))

    csv_path = matrix_dir / "matrix_results.csv"
    if not csv_path.exists():
        fail("CSV", "matrix_results.csv missing")
        return checks

    try:
        rows = list(csv.DictReader(csv_path.read_text(encoding="utf-8").splitlines()))
    except Exception as exc:
        fail("CSV", f"CSV parse error: {exc}")
        return checks

    if not rows:
        fail("CSV", "matrix_results.csv is empty")
    else:
        ok("CSV", f"matrix_results.csv: {len(rows)} rows")

    runs_dir  = matrix_dir / "runs"
    run_dirs  = sorted(d for d in runs_dir.iterdir() if d.is_dir()) if runs_dir.exists() else []
    if len(rows) != len(run_dirs):
        warn("ROWS", f"CSV rows ({len(rows)}) != run dirs ({len(run_dirs)})")
    else:
        ok("ROWS", f"CSV rows match run dir count ({len(rows)})")

    run_ids = [r.get("run_id", "") for r in rows]
    dupes   = {rid for rid in run_ids if run_ids.count(rid) > 1}
    if dupes:
        fail("UNIQ", f"Duplicate run_ids: {sorted(dupes)}")
    else:
        ok("UNIQ", "All run_ids unique")

    # Use overall_score column (canonical score column in matrix CSV)
    score_col = "overall_score" if rows and "overall_score" in rows[0] else "score"
    bad_scores = []
    for row in rows:
        try:
            s = float(row.get(score_col) or 0)
            if not (0.0 <= s <= 1.0):
                bad_scores.append(f"{row.get('run_id')}: {s}")
        except (ValueError, TypeError):
            bad_scores.append(f"{row.get('run_id')}: unparseable ({row.get(score_col)!r})")
    if bad_scores:
        fail("CSV", f"Scores out of [0,1] in column {score_col!r}: {bad_scores}")
    else:
        ok("CSV", f"All CSV scores ({score_col}) in [0, 1]")

    # CSV overall_score matches full_dump scores
    mismatched = []
    for row in rows:
        rid = row.get("run_id", "")
        run_dir = runs_dir / rid if runs_dir.exists() else None
        if run_dir and (run_dir / "full_dump.json").exists():
            fd, _ = _json(run_dir / "full_dump.json")
            if fd:
                fd_score = _deep_get(fd, "score", "overall_score")
                try:
                    csv_score = float(row.get(score_col) or 0)
                    if fd_score is not None and abs(fd_score - csv_score) > 1e-4:
                        mismatched.append(f"{rid}: csv={csv_score} fd={fd_score}")
                except (ValueError, TypeError):
                    pass
    if mismatched:
        fail("CSV", f"CSV {score_col} doesn't match full_dump scores: {mismatched}")
    else:
        ok("CSV", f"All CSV {score_col} values match full_dump.json")

    # matrix_summary.json
    summary_path = matrix_dir / "matrix_summary.json"
    if summary_path.exists():
        ms, err = _json(summary_path)
        if err:
            fail("MATRIX", f"matrix_summary.json invalid: {err}")
        else:
            ok("MATRIX", "matrix_summary.json valid")
    else:
        warn("MATRIX", "matrix_summary.json missing")

    return checks


# ── Directory resolution ──────────────────────────────────────────────────────

def _find_run_dirs(target: Path) -> tuple[list[Path], list[Path]]:
    """Returns (run_dirs, matrix_dirs)."""
    if not target.exists():
        print(f"ERROR: not found: {target}", file=sys.stderr)
        sys.exit(1)

    if (target / "summary_dump.json").exists():
        return [target], []

    if (target / "runs").exists():
        runs = sorted(d for d in (target / "runs").iterdir() if d.is_dir())
        return runs, [target]

    matrix_dirs: list[Path] = []
    run_dirs:    list[Path] = []
    for d in sorted(target.iterdir()):
        if d.is_dir() and (d / "runs").exists():
            matrix_dirs.append(d)
            run_dirs.extend(sorted(dd for dd in (d / "runs").iterdir() if dd.is_dir()))
    if run_dirs:
        return run_dirs, matrix_dirs

    print(f"ERROR: {target} contains no recognisable run/matrix directories", file=sys.stderr)
    sys.exit(1)


# ── Entrypoint ────────────────────────────────────────────────────────────────

def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Validate vsevals run artifacts")
    ap.add_argument("target", nargs="?", default="vsevals_runs",
                    help="Run dir, matrix dir, or vsevals_runs/ root (default: vsevals_runs/)")
    ap.add_argument("--fails-only", action="store_true",
                    help="Only print FAILs and WARNs (suppress PASS lines)")
    args = ap.parse_args()

    run_dirs, matrix_dirs = _find_run_dirs(Path(args.target))

    total_pass = total_fail = total_warn = 0
    run_reports: list[RunReport] = []

    for rd in run_dirs:
        rep = validate_run(rd)
        run_reports.append(rep)
        nf = sum(1 for c in rep.checks if c.status == FAIL)
        nw = sum(1 for c in rep.checks if c.status == WARN)
        np = sum(1 for c in rep.checks if c.status == PASS)
        total_fail += nf; total_warn += nw; total_pass += np

        icon = red("FAIL") if nf else (yellow("WARN") if nw else green("PASS"))
        print(f"\n{bold(rd.name)}  [{icon}]")
        for c in rep.checks:
            if args.fails_only and c.status == PASS:
                continue
            print(str(c))

    for md in matrix_dirs:
        mcs = validate_matrix(md)
        nf = sum(1 for c in mcs if c.status == FAIL)
        nw = sum(1 for c in mcs if c.status == WARN)
        total_fail += nf; total_warn += nw
        total_pass += sum(1 for c in mcs if c.status == PASS)
        icon = red("FAIL") if nf else (yellow("WARN") if nw else green("PASS"))
        print(f"\n{bold('[MATRIX] ' + md.name)}  [{icon}]")
        for c in mcs:
            if args.fails_only and c.status == PASS:
                continue
            print(str(c))

    n = len(run_reports)
    n_ok  = sum(1 for rp in run_reports if not rp.failed)
    n_bad = n - n_ok
    print(f"\n{'━'*62}")
    print(f"{bold('SUMMARY')}  runs={n}  "
          f"{green(f'ok={n_ok}')}  {red(f'failed={n_bad}')}  "
          f"checks: {green(str(total_pass)+'✓')} {red(str(total_fail)+'✗')} {yellow(str(total_warn)+'!')}")
    print(f"{'━'*62}")

    return 1 if total_fail > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
