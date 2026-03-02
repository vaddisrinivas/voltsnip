#!/usr/bin/env python3
"""Build matrix_results.csv from completed.jsonl + full_dump.json artifacts.

Run this after a matrix run (or partial run) to produce / refresh the CSV:

    python vsevals/scripts/build_matrix_csv.py --matrix-dir ./vsevals_runs/matrix_20250101T000000Z

The script reads completed.jsonl, loads each run's full_dump.json, calls
row_from_dump(), and writes matrix_results.csv.  It never touches the LLM
or any live services — it is a pure offline post-processing step.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from pathlib import Path

_here = Path(__file__).resolve().parent.parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))

from vsevals.exporters.csv_mapper import CANONICAL_COLUMNS, row_from_dump

LOGGER = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Build matrix_results.csv from run artifacts.")
    p.add_argument("--matrix-dir", required=True, help="Path to a matrix run directory.")
    p.add_argument("--output", default=None, help="Output CSV path (default: <matrix-dir>/matrix_results.csv).")
    p.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING"])
    return p


def main() -> None:
    args = build_parser().parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    matrix_dir = Path(args.matrix_dir).expanduser().resolve()
    if not matrix_dir.is_dir():
        sys.exit(f"matrix-dir not found: {matrix_dir}")

    completed_path = matrix_dir / "completed.jsonl"
    if not completed_path.exists():
        sys.exit(f"completed.jsonl not found in {matrix_dir}")

    entries = []
    with completed_path.open(encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError as exc:
                LOGGER.warning("line %d: invalid JSON — skipping (%s)", lineno, exc)

    LOGGER.info("loaded %d completed entries from completed.jsonl", len(entries))

    output_path = Path(args.output) if args.output else matrix_dir / "matrix_results.csv"
    rows: list[dict] = []
    errors = 0

    for entry in entries:
        run_dir = entry.get("run_dir", "")
        dump_path = Path(run_dir) / "full_dump.json" if run_dir else None

        if dump_path and dump_path.exists():
            try:
                row = row_from_dump(dump_path)
                # Carry forward metadata that isn't in full_dump.json
                for key in ("task_spec_hash", "variant_spec_hash"):
                    if key in entry and key not in row:
                        row[key] = entry[key]
                rows.append(row)
                continue
            except Exception as exc:
                LOGGER.warning(
                    "could not parse %s: %s — falling back to minimal entry", dump_path, exc
                )
                errors += 1
        else:
            if run_dir:
                LOGGER.warning("full_dump.json missing for run_dir=%s", run_dir)
            errors += 1

        # Fallback: minimal row so the cell is still counted
        rows.append({
            "task_id": entry.get("task_id", ""),
            "variant_id": entry.get("variant_id", ""),
            "model_name": entry.get("model_name", ""),
            "status": entry.get("status", "error"),
            "task_spec_hash": entry.get("task_spec_hash"),
            "variant_spec_hash": entry.get("variant_spec_hash"),
        })

    _write_csv(output_path, rows)
    LOGGER.info(
        "wrote %d rows to %s (%d fallback/error entries)", len(rows), output_path, errors
    )


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        LOGGER.warning("no rows to write")
        return

    all_keys: list[str] = list(CANONICAL_COLUMNS)
    extra = sorted({k for row in rows for k in row if k not in set(all_keys)})
    fieldnames = all_keys + extra

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})


if __name__ == "__main__":
    main()
