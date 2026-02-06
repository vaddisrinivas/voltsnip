#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"

chmod +x "$ROOT/.githooks/pre-commit"

# Configure git to use repo-local hooks
if git config core.hooksPath "$ROOT/.githooks"; then
  echo "Configured core.hooksPath to $ROOT/.githooks"
else
  echo "Failed to configure core.hooksPath" >&2
  exit 1
fi
