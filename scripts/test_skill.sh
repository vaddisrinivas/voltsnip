#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
SKILL_MD="$ROOT/voltsnip-skill/SKILL.md"
SPEC="$ROOT/voltsnip-skill/references/openapi-spec.json"
CLIENT="$ROOT/voltsnip-skill/scripts/voltsnip_client.py"

if [[ ! -f "$SKILL_MD" ]]; then
  echo "Missing SKILL.md at $SKILL_MD" >&2
  exit 1
fi

if [[ ! -f "$SPEC" ]]; then
  echo "Missing OpenAPI spec at $SPEC" >&2
  exit 1
fi

if [[ ! -f "$CLIENT" ]]; then
  echo "Missing voltsnip_client.py at $CLIENT" >&2
  exit 1
fi

python3 - <<PY
from pathlib import Path
import json

skill_md = Path("$SKILL_MD").read_text(encoding="utf-8")
if not skill_md.startswith("---"):
    raise SystemExit("SKILL.md missing YAML frontmatter")

parts = skill_md.split("---", 2)
if len(parts) < 3:
    raise SystemExit("SKILL.md missing YAML frontmatter end marker")

frontmatter = parts[1].splitlines()
required = {"name": False, "description": False, "license": False, "version": False}
for line in frontmatter:
    stripped = line.strip()
    if stripped.startswith("name:"):
        required["name"] = True
    if stripped.startswith("description:"):
        required["description"] = True
    if stripped.startswith("license:"):
        required["license"] = True
    if stripped.startswith("version:"):
        required["version"] = True

missing = [k for k, v in required.items() if not v]
if missing:
    raise SystemExit(f"SKILL.md frontmatter missing fields: {missing}")

spec = json.loads(Path("$SPEC").read_text(encoding="utf-8"))
if "openapi" not in spec:
    raise SystemExit("OpenAPI spec missing top-level 'openapi' key")

print("Skill validation OK")
PY
