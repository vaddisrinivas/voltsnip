#!/usr/bin/env bash
# run_bug14_parallel.sh
#
# Runs BUG14 across P0..P6a for:
#   1) claudecode model
#   2) codex model
# in parallel, first without pytest, then with pytest on the same matrix dirs.
#
# Usage:
#   cd /Users/srinivasvaddi/moltsnip
#   bash vsevals/scripts/run_bug14_parallel.sh
#
# Optional overrides (env):
#   VOLTSNIP_URL=http://127.0.0.1:8011
#   TASKS=BUG14
#   VARIANTS=P0,P1,P2,P3,P4,P5b,P5a,P6b,P6a
#   CLAUDE_MODEL=claudecode:claude-sonnet-4-6
#   CODEX_MODEL=codex:gpt-5.3-codex
#   (no judge during run — scoring-mode=lexical; judge separately)
#   OUTPUT_DIR=/Users/srinivasvaddi/moltsnip/vsevals_runs
#   RUN_PYTEST=1

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON_BIN="${ROOT_DIR}/backend/.venv/bin/python"
RUNNER="${ROOT_DIR}/vsevals/scripts/run_matrix.py"
SUITE="${SUITE:-${ROOT_DIR}/voltsnip-evals/suite.yaml}"
OUTPUT_DIR="${OUTPUT_DIR:-${ROOT_DIR}/vsevals_runs}"

TASKS="${TASKS:-BUG14}"
VARIANTS="${VARIANTS:-P0,P1,P2,P3,P4,P5b,P5a,P6b,P6a}"
VOLTSNIP_URL="${VOLTSNIP_URL:-http://127.0.0.1:8011}"

CLAUDE_MODEL="${CLAUDE_MODEL:-claudecode:claude-sonnet-4-6}"
CODEX_MODEL="${CODEX_MODEL:-codex:gpt-5.3-codex}"
SCORING_MODE="${SCORING_MODE:-lexical}"  # no LLM judge during matrix run; judge separately
SPACING="${SPACING:-0.5}"
LOG_LEVEL="${LOG_LEVEL:-INFO}"

PYTEST_IMAGE="${PYTEST_IMAGE:-moltsnip-hybrid-pytest:latest}"
PYTEST_TIMEOUT="${PYTEST_TIMEOUT:-300}"
RUN_PYTEST="${RUN_PYTEST:-1}"

[[ -x "${PYTHON_BIN}" ]] || PYTHON_BIN="python3"
mkdir -p "${OUTPUT_DIR}"

STAMP="${STAMP:-$(date -u +%Y%m%dT%H%M%SZ)}"
CLAUDE_DIR="${CLAUDE_DIR:-${OUTPUT_DIR}/matrix_bug14_claudecode_${STAMP}}"
CODEX_DIR="${CODEX_DIR:-${OUTPUT_DIR}/matrix_bug14_codex_${STAMP}}"


run_one_phase_pair() {
  local with_pytest="$1"
  local suffix="$2"

  local -a pytest_args=()
  if [[ "${with_pytest}" == "1" ]]; then
    pytest_args+=(
      --auto-apply-patch
      --pytest-docker-image "${PYTEST_IMAGE}"
      --pytest-timeout "${PYTEST_TIMEOUT}"
    )
  fi

  (
    "${PYTHON_BIN}" "${RUNNER}" \
      --suite "${SUITE}" \
      --models "${CLAUDE_MODEL}" \
      --variants "${VARIANTS}" \
      --tasks "${TASKS}" \
      --voltsnip-url "${VOLTSNIP_URL}" \
      --scoring-mode "${SCORING_MODE}" \
      --spacing "${SPACING}" \
      --log-level "${LOG_LEVEL}" \
      --resume "${CLAUDE_DIR}" \
      "${pytest_args[@]}"
  ) > "${CLAUDE_DIR}.${suffix}.log" 2>&1 &
  local claudepid=$!

  (
    "${PYTHON_BIN}" "${RUNNER}" \
      --suite "${SUITE}" \
      --models "${CODEX_MODEL}" \
      --variants "${VARIANTS}" \
      --tasks "${TASKS}" \
      --voltsnip-url "${VOLTSNIP_URL}" \
      --scoring-mode "${SCORING_MODE}" \
      --spacing "${SPACING}" \
      --log-level "${LOG_LEVEL}" \
      --resume "${CODEX_DIR}" \
      "${pytest_args[@]}"
  ) > "${CODEX_DIR}.${suffix}.log" 2>&1 &
  local codexpid=$!

  wait "${claudepid}"
  wait "${codexpid}"
}

prepare_for_pytest_rerun() {
  local dir="$1"
  if [[ -f "${dir}/matrix_results.csv" ]]; then
    cp "${dir}/matrix_results.csv" "${dir}/matrix_results_no_pytest.csv"
  fi
  if [[ -f "${dir}/matrix_summary.json" ]]; then
    cp "${dir}/matrix_summary.json" "${dir}/matrix_summary_no_pytest.json"
  fi
  if [[ -f "${dir}/matrix_report.md" ]]; then
    cp "${dir}/matrix_report.md" "${dir}/matrix_report_no_pytest.md"
  fi
  rm -f "${dir}/matrix_results.csv" "${dir}/matrix_summary.json" "${dir}/matrix_report.md"
}

echo "[vsevals bug14 parallel]"
echo "  suite:        ${SUITE}"
echo "  tasks:        ${TASKS}"
echo "  variants:     ${VARIANTS}"
echo "  voltsnip_url: ${VOLTSNIP_URL}"
echo "  claudecode:   model=${CLAUDE_MODEL}"
echo "  codex:        model=${CODEX_MODEL}"
echo "  scoring:      ${SCORING_MODE}  (judge separately after run)"
echo "  output_dir:   ${OUTPUT_DIR}"
echo "  matrix_claude:${CLAUDE_DIR}"
echo "  matrix_codex: ${CODEX_DIR}"
echo "  run_pytest:   ${RUN_PYTEST}"

echo
echo "[phase A] no pytest (parallel)"
run_one_phase_pair 0 "no_pytest"
echo "phase A complete"

if [[ "${RUN_PYTEST}" == "1" ]]; then
  echo
  echo "[phase B] pytest (parallel, same matrix dirs)"
  prepare_for_pytest_rerun "${CLAUDE_DIR}"
  prepare_for_pytest_rerun "${CODEX_DIR}"
  run_one_phase_pair 1 "pytest"
  echo "phase B complete"
fi

echo
echo "Done."
echo "  claudecode matrix: ${CLAUDE_DIR}"
echo "  codex matrix:      ${CODEX_DIR}"
