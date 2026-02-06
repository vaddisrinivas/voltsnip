#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

echo "[precommit] Checking tooling"
"$ROOT/scripts/check_tooling.sh"

echo "[precommit] Syncing versions"
python3 "$ROOT/scripts/sync_versions.py"

echo "[precommit] Running backend tests"
"$ROOT/scripts/ci_check.sh"

echo "[precommit] Generating OpenAPI spec"
uv run --project "$ROOT/backend" python "$ROOT/scripts/generate_openapi.py"

echo "[precommit] Generating clients"
"$ROOT/scripts/generate_clients.sh"

echo "[precommit] Building skill npm package"
"$ROOT/scripts/build_skill_package.sh"

echo "[precommit] Building docker image"
"$ROOT/scripts/build_backend_image.sh"

echo "[precommit] Testing clients"
"$ROOT/scripts/test_clients.sh"

echo "[precommit] Testing skill"
"$ROOT/scripts/test_skill.sh"

echo "[precommit] Testing docker image run"
"$ROOT/scripts/test_docker_image.sh"

echo "[precommit] Staging generated artifacts"

paths=(
  "VERSION"
  "backend/pyproject.toml"
  "voltsnip-skill/SKILL.md"
  "voltsnip-skill/package.json"
  "voltsnip-skill/references/openapi-spec.json"
  "clients/python"
  "clients/npm"
)

for path in "${paths[@]}"; do
  if [[ -e "$path" ]]; then
    git add "$path"
  fi
done

echo "[precommit] Done"
