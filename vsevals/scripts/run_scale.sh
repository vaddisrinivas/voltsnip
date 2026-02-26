#!/usr/bin/env bash
# run_scale.sh — scale run using claudecode + openai, no ANTHROPIC_API_KEY required
#
# Usage:
#   cd /Users/srinivasvaddi/moltsnip
#   bash vsevals/scripts/run_scale.sh
#
# Override any variable before invoking:
#   MODELS="claudecode:claude-sonnet-4-6,openai:gpt-5-nano" bash vsevals/scripts/run_scale.sh
#   VARIANTS="P0,P4,P5b,P5a,P6b,P6a" bash vsevals/scripts/run_scale.sh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VSEVALS_DIR="${ROOT_DIR}/vsevals"
PYTHON_BIN="${ROOT_DIR}/backend/.venv/bin/python"
[[ -x "${PYTHON_BIN}" ]] || PYTHON_BIN="python3"

# --- Configurable defaults ---
MODELS="${MODELS:-claudecode:claude-sonnet-4-6,claudecode:claude-haiku-4-5,openai:gpt-5-mini,openai:gpt-5-nano}"
VARIANTS="${VARIANTS:-P0,P1,P2,P3,P4,P5b,P5a,P6b,P6a}"
SUITE="${SUITE:-${ROOT_DIR}/voltsnip-evals/suite_arxiv.yaml}"
OUTPUT_DIR="${OUTPUT_DIR:-${ROOT_DIR}/vsevals_runs}"
SCORING_MODE="${SCORING_MODE:-lexical}"  # no LLM judge during matrix run; judge separately
SPACING="${SPACING:-1.25}"
LOG_LEVEL="${LOG_LEVEL:-INFO}"
VOLTSNIP_URL="${VOLTSNIP_URL:-http://127.0.0.1:8001}"

# Require OPENAI_API_KEY if any openai: models are requested
if echo "${MODELS}" | grep -q "openai:" && [[ -z "${OPENAI_API_KEY:-}" ]]; then
  echo "error: OPENAI_API_KEY required for openai: models (MODELS=${MODELS})" >&2
  exit 1
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
