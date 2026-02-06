#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
SPEC_PATH="${1:-$ROOT/voltsnip-skill/references/openapi-spec.json}"
VERSION="$(cat "$ROOT/VERSION")"

PY_OUT="$ROOT/clients/python"
TS_OUT="$ROOT/clients/npm"

if [[ -n "${OPENAPI_SPEC_GENERATOR:-}" ]]; then
  GENERATOR=("$OPENAPI_SPEC_GENERATOR")
elif command -v openapi-generator-cli >/dev/null 2>&1; then
  GENERATOR=("openapi-generator-cli")
else
  GENERATOR=("npx" "-y" "@openapitools/openapi-generator-cli")
fi

rm -rf "$PY_OUT" "$TS_OUT"
mkdir -p "$PY_OUT" "$TS_OUT"

"${GENERATOR[@]}" generate \
  -i "$SPEC_PATH" \
  -g python \
  -o "$PY_OUT" \
  --additional-properties=packageName=voltsnip_client,projectName=voltsnip-client,packageVersion="$VERSION"

"${GENERATOR[@]}" generate \
  -i "$SPEC_PATH" \
  -g typescript-fetch \
  -o "$TS_OUT" \
  --additional-properties=npmName=@vaddisrinivas/voltsnip-client,npmVersion="$VERSION",supportsES6=true,typescriptThreePlus=true

exit 0
