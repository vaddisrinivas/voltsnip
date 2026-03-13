#!/usr/bin/env bash
# run_study.sh — Full study runner: n repetitions × 7 variants × 30 bugs × 2 providers.
#
# Usage:
#   cd /path/to/moltsnip_root/vsevals
#   bash scripts/run_study.sh
#
# Resume a specific rep that was interrupted:
#   RESUME_REP_1=vsevals_runs/study_<ts>/rep_1 bash scripts/run_study.sh
#
# Override any variable:
#   MODELS="claudecode:claude-sonnet-4-6,codex:gpt-5.2-codex" N_REPS=1 bash scripts/run_study.sh
#
# Run a single provider for testing:
#   MODELS="claudecode:claude-haiku-4-5" N_REPS=1 VARIANTS="P0,P2,P4" bash scripts/run_study.sh
set -euo pipefail

# ── Config ────────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VSEVALS_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

PYTHON_BIN="${VSEVALS_DIR}/.venv/bin/python"
[[ -x "${PYTHON_BIN}" ]] || PYTHON_BIN="python3"

SUITE="${SUITE:-${VSEVALS_DIR}/suite.yaml}"
MODELS="${MODELS:-claudecode:claude-sonnet-4-6,codex:gpt-5.2-codex}"
VARIANTS="${VARIANTS:-P0,P1,P2,P3,P4,P5,P6}"
N_REPS="${N_REPS:-3}"
WORKERS="${WORKERS:-6}"
PROVIDER_CONCURRENCY="${PROVIDER_CONCURRENCY:-2}"
SPACING="${SPACING:-0.5}"
VOLTSNIP_URL="${VOLTSNIP_URL:-http://127.0.0.1:8011}"
SCORING_MODE="${SCORING_MODE:-hybrid}"
JUDGE_MODEL="${JUDGE_MODEL:-openai:gpt-5.2+anthropic:claude-opus-4-6}"
LOG_LEVEL="${LOG_LEVEL:-INFO}"

# Study root — all rep dirs live under here.
STUDY_TS="$(date -u +%Y%m%dT%H%M%SZ)"
STUDY_DIR="${STUDY_DIR:-${VSEVALS_DIR}/vsevals_runs/study_${STUDY_TS}}"
mkdir -p "${STUDY_DIR}"

# Log file for this study run
STUDY_LOG="${STUDY_DIR}/study.log"

# ── Helpers ───────────────────────────────────────────────────────────────────
log() { echo "[$(date -u +%H:%M:%S)] $*" | tee -a "${STUDY_LOG}"; }
die() { log "ERROR: $*"; exit 1; }

# ── Pre-flight checks ─────────────────────────────────────────────────────────
log "=== VSEvals Full Study ==="
log "  study dir:   ${STUDY_DIR}"
log "  suite:       ${SUITE}"
log "  models:      ${MODELS}"
log "  variants:    ${VARIANTS}"
log "  n_reps:      ${N_REPS}"
log "  workers:     ${WORKERS} (per-rep threading)"
log "  concurrency: ${PROVIDER_CONCURRENCY} (per provider)"
log "  voltsnip:    ${VOLTSNIP_URL}"
log "  scoring:     ${SCORING_MODE}"

[[ -f "${SUITE}" ]] || die "suite not found: ${SUITE}"
"${PYTHON_BIN}" -c "import vsevals" 2>/dev/null || die "vsevals not importable — activate venv first"

# Check VoltSnip is reachable
if ! curl -sf "${VOLTSNIP_URL}/health" >/dev/null 2>&1; then
  log "WARNING: VoltSnip not reachable at ${VOLTSNIP_URL} — P2/P3/P4/P5/P6 tool runs will fail"
fi

# ── Run repetitions ───────────────────────────────────────────────────────────
REP_DIRS=()
FAILED_REPS=()

for rep in $(seq 1 "${N_REPS}"); do
  # Support resuming a specific rep via RESUME_REP_N env var
  resume_var="RESUME_REP_${rep}"
  if [[ -n "${!resume_var:-}" ]]; then
    REP_DIR="${!resume_var}"
    log "rep ${rep}/${N_REPS}: resuming from ${REP_DIR}"
  else
    REP_DIR="${STUDY_DIR}/rep_${rep}"
    mkdir -p "${REP_DIR}"
    log "rep ${rep}/${N_REPS}: starting → ${REP_DIR}"
  fi
  REP_DIRS+=("${REP_DIR}")

  REP_LOG="${REP_DIR}/run.log"

  # Build the run_matrix.py command
  CMD=(
    "${PYTHON_BIN}" "${VSEVALS_DIR}/scripts/run_matrix.py"
    --suite            "${SUITE}"
    --models           "${MODELS}"
    --variants         "${VARIANTS}"
    --matrix-dir       "${REP_DIR}"
    --scoring-mode     "${SCORING_MODE}"
    --judge-model      "${JUDGE_MODEL}"
    --voltsnip-url     "${VOLTSNIP_URL}"
    --workers          "${WORKERS}"
    --provider-concurrency "${PROVIDER_CONCURRENCY}"
    --spacing          "${SPACING}"
    --log-level        "${LOG_LEVEL}"
  )

  # If resuming, pass --resume so completed cells are skipped
  if [[ -f "${REP_DIR}/completed.jsonl" ]]; then
    CMD+=(--resume "${REP_DIR}")
  fi

  log "rep ${rep}: launching (log → ${REP_LOG})"
  log "  cmd: ${CMD[*]}"

  # Run the rep — tee to both study log and per-rep log
  if "${CMD[@]}" 2>&1 | tee -a "${REP_LOG}" >> "${STUDY_LOG}"; then
    log "rep ${rep}/${N_REPS}: DONE ✓"
  else
    log "rep ${rep}/${N_REPS}: FAILED (check ${REP_LOG})"
    FAILED_REPS+=("${rep}")
    # Continue to next rep rather than aborting the whole study
  fi
done

# ── Summary ───────────────────────────────────────────────────────────────────
log ""
log "=== Study complete ==="
log "  study dir: ${STUDY_DIR}"
for i in "${!REP_DIRS[@]}"; do
  rep=$((i + 1))
  dir="${REP_DIRS[$i]}"
  n_ok=0
  n_err=0
  if [[ -f "${dir}/completed.jsonl" ]]; then
    n_ok=$(grep -c '"status":"ok"' "${dir}/completed.jsonl" 2>/dev/null || echo 0)
    n_err=$(grep -c '"status":"error"' "${dir}/completed.jsonl" 2>/dev/null || echo 0)
  fi
  log "  rep ${rep}: ${dir}  (ok=${n_ok} err=${n_err})"
done

if [[ ${#FAILED_REPS[@]} -gt 0 ]]; then
  log "  FAILED reps: ${FAILED_REPS[*]}"
  log "  Resume failed reps with:"
  for rep in "${FAILED_REPS[@]}"; do
    log "    RESUME_REP_${rep}=${STUDY_DIR}/rep_${rep} bash scripts/run_study.sh"
  done
  exit 1
fi

log ""
log "Next step — aggregate CSVs across reps:"
log "  python scripts/build_matrix_csv.py --dirs ${STUDY_DIR}/rep_* --output ${STUDY_DIR}/study_results.csv"
