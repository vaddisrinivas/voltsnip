#!/usr/bin/env bash
set -euo pipefail

missing=()
for cmd in git python3 uv docker node npm npx curl; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    missing+=("$cmd")
  fi
done

if ((${#missing[@]} > 0)); then
  echo "Missing required tools: ${missing[*]}" >&2
  echo "Install the missing tools and retry." >&2
  exit 1
fi

exit 0
