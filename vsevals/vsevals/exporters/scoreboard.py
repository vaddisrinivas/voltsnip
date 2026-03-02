"""Live scoreboard for matrix evaluation."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from .csv_mapper import safe_float

LOGGER = logging.getLogger(__name__)

_ANSI_G = "\033[32m"   # green
_ANSI_Y = "\033[33m"   # yellow
_ANSI_R = "\033[31m"   # red
_ANSI_C = "\033[36m"   # cyan
_ANSI_B = "\033[1m"    # bold
_ANSI_D = "\033[2m"    # dim
_ANSI_W = "\033[0m"    # reset

def print_scoreboard(results: list[dict], total_planned: int) -> None:
    """Print a live model x variant pass-rate scoreboard to stdout."""
    if not results:
        return

    # Stable dedup
    models: list[str] = list(dict.fromkeys(r["model_name"] for r in results if r.get("model_name")))
    variants: list[str] = list(dict.fromkeys(r["variant_id"] for r in results if r.get("variant_id")))
    if not models or not variants:
        return

    cell: dict[tuple[str, str], dict[str, Any]] = {}
    for r in results:
        m, v = r.get("model_name", ""), r.get("variant_id", "")
        if not m or not v: continue
        key = (m, v)
        if key not in cell:
            cell[key] = {"ok": 0, "score_sum": 0.0, "err": 0, "count": 0}
        s = cell[key]
        s["count"] += 1
        if r.get("status") == "ok":
            s["ok"] += 1
            s["score_sum"] += safe_float(r.get("overall_score", 0))
        elif r.get("status") == "error":
            s["err"] += 1

    ok_rows = [r for r in results if r.get("status") == "ok"]
    avg_score = sum(safe_float(r.get("overall_score", 0)) for r in ok_rows) / len(ok_rows) if ok_rows else 0.0
    pct_done = len(results) / total_planned * 100 if total_planned else 0.0

    lats = sorted(safe_float(r.get("latency_ms", 0)) for r in ok_rows if r.get("latency_ms") not in ("", None))
    p95 = lats[int(len(lats) * 0.95)] if len(lats) >= 5 else (lats[-1] if lats else 0)
    p95_str = f"{p95/1000:.0f}s" if p95 else "—"

    cov_vals = [safe_float(r["required_snippet_coverage"]) for r in ok_rows if r.get("required_snippet_coverage") not in ("", None)]
    cov_str = f"{sum(cov_vals)/len(cov_vals):.2f}" if cov_vals else "—"

    def _short(name: str) -> str:
        _, _, tail = name.partition(":")
        return tail

    short_models = [_short(m) for m in models]
    model_col_w = max(len(s) for s in short_models) + 1
    var_w = max(5, max(len(v) for v in variants) + 1)
    bar = "█" * int(pct_done / 5) + "░" * (20 - int(pct_done / 5))
    total_w = model_col_w + len(variants) * var_w + 4
    sep = "─" * total_w

    def _color(rate: float) -> str:
        if rate >= 0.70: return _ANSI_G
        if rate >= 0.40: return _ANSI_Y
        return _ANSI_R

    lines = [
        "",
        f"{_ANSI_B}{'━' * total_w}{_ANSI_W}",
        f"  {_ANSI_B}vsevals{_ANSI_W}  {len(results)}/{total_planned} ({pct_done:.0f}%)  {_ANSI_C}[{bar}]{_ANSI_W}  avg {avg_score:.3f}  cov {cov_str}  p95 {p95_str}",
        f"{_ANSI_B}{'━' * total_w}{_ANSI_W}",
        f"  {'':<{model_col_w}}" + "".join(f"{_ANSI_D}{v:^{var_w}}{_ANSI_W}" for v in variants),
        f"  {_ANSI_D}{sep}{_ANSI_W}"
    ]

    for m, short in zip(models, short_models):
        row = f"  {short:<{model_col_w}}"
        for v in variants:
            s = cell.get((m, v))
            if s is None or s["count"] == 0:
                row += f"{_ANSI_D}{'·':^{var_w}}{_ANSI_W}"
            elif s["ok"] == 0:
                row += f"{_ANSI_R}{'err':^{var_w}}{_ANSI_W}"
            else:
                avg = s["score_sum"] / s["ok"]
                row += f"{_color(avg)}{f'{avg:.2f}':^{var_w}}{_ANSI_W}"
        lines.append(row)

    lines.append(f"{_ANSI_B}{'━' * total_w}{_ANSI_W}")
    lines.append("")
    print("\n".join(lines), flush=True)
