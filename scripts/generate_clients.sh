#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
SPEC="$ROOT/voltsnip-skill/references/openapi-spec.json"

if [[ ! -f "$SPEC" ]]; then
  echo "OpenAPI spec not found at $SPEC" >&2
  exit 1
fi

"$ROOT/scripts/openapi-spec-generator.sh" "$SPEC"
