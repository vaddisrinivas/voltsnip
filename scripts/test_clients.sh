#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
PY_OUT="$ROOT/clients/python"
TS_OUT="$ROOT/clients/npm"

if [[ ! -d "$PY_OUT" ]]; then
  echo "Python client not found at $PY_OUT" >&2
  exit 1
fi

if [[ ! -d "$TS_OUT" ]]; then
  echo "TypeScript client not found at $TS_OUT" >&2
  exit 1
fi

python3 - <<PY
from pathlib import Path

pkg_root = Path("$PY_OUT").resolve()
if not pkg_root.exists():
    raise SystemExit("Python client directory missing")

expected = [
    pkg_root / "voltsnip_client" / "__init__.py",
    pkg_root / "voltsnip_client" / "api_client.py",
    pkg_root / "voltsnip_client" / "configuration.py",
]

missing = [str(p) for p in expected if not p.exists()]
if missing:
    raise SystemExit(f"Python client missing expected files: {missing}")

print("Python client structure OK")
PY

python3 - <<PY
from pathlib import Path

ts_root = Path("$TS_OUT").resolve()
if not ts_root.exists():
    raise SystemExit("TypeScript client directory missing")

expected = [
    ts_root / "package.json",
    ts_root / "tsconfig.json",
    ts_root / "src" / "index.ts",
    ts_root / "src" / "runtime.ts",
]

missing = [str(p) for p in expected if not p.exists()]
if missing:
    raise SystemExit(f"TypeScript client missing expected files: {missing}")

print("TypeScript client structure OK")
PY
