#!/usr/bin/env bash
# run_scale.sh — scale run using stored-auth CLI providers (no API keys required by default)
#
# Usage:
#   cd /Users/srinivasvaddi/moltsnip
#   bash vsevals/scripts/run_scale.sh
#
# Override any variable before invoking:
#   MODELS="claudecode:claude-sonnet-4-6,codex:gpt-5.2-codex" bash vsevals/scripts/run_scale.sh
#   VARIANTS="P0,P4,P5b,P5a,P6b,P6a" bash vsevals/scripts/run_scale.sh
#
# To add openai/anthropic SDK models (requires API keys):
#   MODELS="claudecode:claude-sonnet-4-6,openai:gpt-5-nano" OPENAI_API_KEY=sk-... bash vsevals/scripts/run_scale.sh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VSEVALS_DIR="${ROOT_DIR}/vsevals"
PYTHON_BIN="${ROOT_DIR}/backend/.venv/bin/python"
[[ -x "${PYTHON_BIN}" ]] || PYTHON_BIN="python3"

# --- Configurable defaults (all stored-auth; no API keys needed) ---
MODELS="${MODELS:-claudecode:claude-sonnet-4-6,claudecode:claude-haiku-4-5,codex:gpt-5.2-codex,codex:gpt-5.3-codex}"
VARIANTS="${VARIANTS:-P0,P1,P2,P3,P4,P5b,P5a,P6b,P6a}"
SUITE="${SUITE:-${ROOT_DIR}/vsevals/suite.yaml}"
OUTPUT_DIR="${OUTPUT_DIR:-${ROOT_DIR}/vsevals_runs}"
SCORING_MODE="${SCORING_MODE:-llm}"
SPACING="${SPACING:-1.25}"
LOG_LEVEL="${LOG_LEVEL:-INFO}"
VOLTSNIP_URL="${VOLTSNIP_URL:-http://127.0.0.1:8011}"

# --- Optional API key warnings (not hard failures) ---
if echo "${MODELS}" | grep -q "openai:" && [[ -z "${OPENAI_API_KEY:-}" ]]; then
  echo "warning: MODELS includes openai: providers but OPENAI_API_KEY is not set — those cells will fail" >&2
fi
if echo "${MODELS}" | grep -q "anthropic:" && [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
  echo "warning: MODELS includes anthropic: providers but ANTHROPIC_API_KEY is not set — those cells will fail" >&2
fi

echo "[vsevals scale run]"
echo "  suite:       ${SUITE}"
echo "  models:      ${MODELS}"
echo "  variants:    ${VARIANTS}"
echo "  scoring:     ${SCORING_MODE}  (judge separately after run)"
echo "  output:      ${OUTPUT_DIR}"
echo "  voltsnip:    ${VOLTSNIP_URL}"

exec "${PYTHON_BIN}" "${VSEVALS_DIR}/scripts/run_matrix.py" \
  --suite     "${SUITE}" \
  --models    "${MODELS}" \
  --variants  "${VARIANTS}" \
  --output-dir "${OUTPUT_DIR}" \
  --scoring-mode "${SCORING_MODE}" \
  --voltsnip-url "${VOLTSNIP_URL}" \
  --spacing   "${SPACING}" \
  --log-level "${LOG_LEVEL}" \
  "$@"
