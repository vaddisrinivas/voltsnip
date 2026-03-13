#!/usr/bin/env python3
"""
Toggle VoltSnip snippet visibility for ablation experiments.

Hides all snippets (is_hidden=True) so that tool calls return empty results,
then restores them after the ablation run.

Usage:
  # Hide all snippets (pre-ablation)
  uv run python3 scripts/ablation_snippets.py hide

  # Restore all snippets (post-ablation)
  uv run python3 scripts/ablation_snippets.py restore

  # Check current state
  uv run python3 scripts/ablation_snippets.py status

  # Override DB URL (default: postgresql://user:password@127.0.0.1:5432/voltsnip)
  uv run python3 scripts/ablation_snippets.py hide --db-url postgresql://...

The script uses the sync psycopg2 driver directly (no async, no ORM).
"""

from __future__ import annotations

import argparse
import os
import sys

try:
    import psycopg2
except ImportError:
    print("psycopg2 not installed. Run: uv pip install psycopg2-binary")
    sys.exit(1)

DEFAULT_DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://user:password@127.0.0.1:5432/voltsnip",
)


def get_conn(db_url: str):
    return psycopg2.connect(db_url)


def status(db_url: str) -> None:
    conn = get_conn(db_url)
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM snippets WHERE is_hidden = false")
        visible = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM snippets WHERE is_hidden = true")
        hidden = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM snippets")
        total = cur.fetchone()[0]
    conn.close()
    print(f"Total: {total}  |  Visible: {visible}  |  Hidden: {hidden}")


def hide(db_url: str) -> None:
    conn = get_conn(db_url)
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE snippets SET is_hidden = true, hidden_reason = 'ablation' "
            "WHERE is_hidden = false"
        )
        count = cur.rowcount
    conn.commit()
    conn.close()
    print(f"Hidden {count} snippets (reason='ablation')")


def restore(db_url: str) -> None:
    conn = get_conn(db_url)
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE snippets SET is_hidden = false, hidden_reason = null "
            "WHERE hidden_reason = 'ablation'"
        )
        count = cur.rowcount
    conn.commit()
    conn.close()
    print(f"Restored {count} snippets")


def main():
    parser = argparse.ArgumentParser(description="Toggle snippet visibility for ablation")
    parser.add_argument("action", choices=["hide", "restore", "status"])
    parser.add_argument("--db-url", default=DEFAULT_DB_URL, help="PostgreSQL connection URL")
    args = parser.parse_args()

    if args.action == "status":
        status(args.db_url)
    elif args.action == "hide":
        hide(args.db_url)
        status(args.db_url)
    elif args.action == "restore":
        restore(args.db_url)
        status(args.db_url)


if __name__ == "__main__":
    main()
