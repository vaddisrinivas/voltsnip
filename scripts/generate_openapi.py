#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND_PATH = ROOT / "backend"
SPEC_PATHS = [
    ROOT / "voltsnip-skill" / "references" / "openapi-spec.json",
    ROOT / ".agent" / "skills" / "voltsnip" / "references" / "openapi-spec.json",
]


def main() -> int:
    os.environ.setdefault(
        "DATABASE_URL",
        "postgresql+asyncpg://postgres:postgres@localhost:5432/postgres",
    )
    sys.path.insert(0, str(BACKEND_PATH))
    try:
        from app.main import app  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise SystemExit(f"Failed to import FastAPI app: {exc}")

    spec = app.openapi()
    payload = json.dumps(spec, indent=2, ensure_ascii=True)

    for path in SPEC_PATHS:
        if path.parent.exists():
            path.write_text(payload + "\n", encoding="utf-8")
            print(f"Wrote OpenAPI spec: {path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
