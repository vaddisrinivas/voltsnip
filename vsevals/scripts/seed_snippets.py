#!/usr/bin/env python3
"""Push fixture snippets from vsevals/snippets/ to the VoltSnip backend.

Usage
-----
    # Push to local Docker backend (default)
    python vsevals/scripts/seed_snippets.py

    # Push to a specific base URL
    python vsevals/scripts/seed_snippets.py --base-url https://voltsnip-api.thetechcruise.com

    # Dry-run (print what would be sent, no network calls)
    python vsevals/scripts/seed_snippets.py --dry-run

    # Push a different snippets directory
    python vsevals/scripts/seed_snippets.py --snippets-dir path/to/snippets

The backend is idempotent: posting a snippet with an identical canonical_key or
identical content returns the existing record rather than creating a duplicate.
Running this script multiple times is safe.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_SNIPPETS_DIR = Path(__file__).parent.parent / "snippets" / "bug22_generic"
CREATE_ENDPOINT = "/api/v1/snippets/"

# Fields accepted by SnippetCreate (backend schema)
_ALLOWED_FIELDS = {"title", "description", "language", "tags", "kind", "canonical_key", "code", "source"}


def _load_snippet_files(snippets_dir: Path) -> list[tuple[Path, dict]]:
    """Load all .json files from the snippets directory."""
    files = sorted(snippets_dir.glob("*.json"))
    if not files:
        print(f"[warn] No JSON files found in {snippets_dir}", file=sys.stderr)
        return []
    results = []
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            results.append((f, data))
        except json.JSONDecodeError as exc:
            print(f"[skip] {f.name}: JSON parse error — {exc}", file=sys.stderr)
    return results


def _build_payload(raw: dict) -> dict:
    """Filter raw fixture dict to only the fields the API accepts."""
    return {k: v for k, v in raw.items() if k in _ALLOWED_FIELDS}


def _post_snippet(base_url: str, payload: dict) -> tuple[int, dict]:
    """POST a snippet to the backend; returns (status_code, response_dict)."""
    url = base_url.rstrip("/") + CREATE_ENDPOINT
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    gateway_secret = os.environ.get("VOLTSNIP_GATEWAY_SECRET")
    if gateway_secret:
        headers["X-Gateway-Secret"] = gateway_secret
    req = urllib.request.Request(
        url,
        data=body,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            err_body = json.loads(exc.read().decode("utf-8"))
        except Exception:
            err_body = {"detail": str(exc)}
        return exc.code, err_body


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed VoltSnip fixture snippets")
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"Backend base URL (default: {DEFAULT_BASE_URL})",
    )
    parser.add_argument(
        "--snippets-dir",
        type=Path,
        default=DEFAULT_SNIPPETS_DIR,
        help=f"Directory containing fixture .json files (default: {DEFAULT_SNIPPETS_DIR})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print payloads but do not make any network requests",
    )
    args = parser.parse_args()

    snippets_dir: Path = args.snippets_dir.resolve()
    if not snippets_dir.is_dir():
        print(f"[error] Snippets directory not found: {snippets_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"📂  Loading snippets from: {snippets_dir}")
    entries = _load_snippet_files(snippets_dir)
    if not entries:
        sys.exit(0)

    print(f"📦  Found {len(entries)} snippet file(s)")
    print(f"🌐  Target: {args.base_url}")
    if args.dry_run:
        print("🔍  Dry-run mode — no requests will be sent\n")

    ok = skipped = failed = 0

    for file_path, raw in entries:
        payload = _build_payload(raw)
        canonical = payload.get("canonical_key", "<no canonical_key>")

        if args.dry_run:
            print(f"  [dry-run] {file_path.name}")
            print(f"            canonical_key: {canonical}")
            print(f"            payload keys:  {list(payload.keys())}")
            ok += 1
            continue

        status, resp = _post_snippet(args.base_url, payload)

        if status in (200, 201):
            snippet_id = resp.get("id", "?")
            is_new = status == 201
            label = "created" if is_new else "exists "
            print(f"  ✅  [{label}] {file_path.name}  →  {snippet_id}  ({canonical})")
            ok += 1
        elif status == 409:
            # Unlikely given content-hash dedup, but handle gracefully
            print(f"  ⏭️   [conflict] {file_path.name}  ({canonical})")
            skipped += 1
        else:
            detail = resp.get("detail", resp)
            print(f"  ❌  [HTTP {status}] {file_path.name}  ({canonical}): {detail}", file=sys.stderr)
            failed += 1

    print()
    print(f"{'🔍 Dry-run ' if args.dry_run else ''}Done: {ok} OK, {skipped} skipped, {failed} failed")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
