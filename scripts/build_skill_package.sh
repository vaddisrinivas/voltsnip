#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
DIST="$ROOT/dist/skills"
SKILL_DIR="$ROOT/voltsnip-skill"

mkdir -p "$DIST"

(
  cd "$SKILL_DIR"
  npm pack --pack-destination "$DIST"
)
