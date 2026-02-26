#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# run_cross_eval.sh — Phase 1 + Phase 2 cross-verified eval runner
#
# Runs claudecode and codex in parallel with a cross-judge ensemble
# (claudecode:claude-haiku-4-5 + codex:gpt-5.1-codex), then runs pytest on both.
#
# Usage:
#   ./vsevals/scripts/run_cross_eval.sh [OPTIONS]
#
# Options:
#   --variants      Comma-separated variants  (default: P0,P1,P2,P3,P4,P5b,P5a,P6b,P6a)
#   --tasks         Comma-separated task IDs  (default: all)
#   --voltsnip-url  VoltSnip base URL         (default: http://localhost:8001)
#   --output-dir    Root output directory     (default: ./vsevals_runs)
#   --no-pytest     Skip Phase 2 pytest       (default: pytest runs)
#   --spacing       Seconds between calls     (default: 0.5)
#   --log-level     DEBUG|INFO|WARNING        (default: INFO)
#   --max-tokens    Max output tokens / LLM call (default: model default)
#   --llm-timeout   LLM single-shot timeout in seconds (default: 300)
#                   MCP/tool-loop paths use max(600, timeout*2)
#   --max-tool-roundtrips  Override max tool roundtrips for tool-enabled variants
#                          (default: use suite settings)
#
# Examples:
#   # Full run, all 6 models × all variants
#   ./vsevals/scripts/run_cross_eval.sh
#
#   # Quick smoke test (P0 only, BUG01)
#   ./vsevals/scripts/run_cross_eval.sh --variants P0 --tasks BUG01
#
#   # P0-P3 only (no backend needed for tool variants)
#   ./vsevals/scripts/run_cross_eval.sh --variants P0,P1,P2,P3
#
#   # Skip pytest phase
#   ./vsevals/scripts/run_cross_eval.sh --no-pytest
#
#   # Cap output to 2048 tokens, 60s timeout
#   ./vsevals/scripts/run_cross_eval.sh --max-tokens 2048 --llm-timeout 60
#
#   # Keep tool-enabled variants tight (e.g., 2 tool roundtrips max)
#   ./vsevals/scripts/run_cross_eval.sh --max-tool-roundtrips 2
#
# Models:
#   claudecode: claude-opus-4-6, claude-sonnet-4-6, claude-haiku-4-5
#   codex:      gpt-5.2, gpt-5.3-codex
#               (o3 removed — codex exec exits with "no last agent message" for o3)
#
#   Scoring during run: lexical only — no LLM judge calls.
#   Judge separately after data collection (cross-provider judging keeps bias out of the run).
#
# Prerequisites:
#   - .env at repo root with OPENAI_API_KEY  (or export it; codex: models only)
#   - `claude` CLI available    (for claudecode provider)
#   - `codex` CLI available     (for codex provider)
#   - VoltSnip backend on :8011 (for P2-P6a variants; P0/P1 don't need it)
#   - Docker running            (for Phase 2 pytest)
#
# ⚠️  Must run from a plain terminal — NOT inside a Claude Code session.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── Resolve repo root (script lives in vsevals/scripts/) ──────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
VSEVALS_DIR="$REPO_ROOT/vsevals"
PYTHON="$VSEVALS_DIR/.venv/bin/python3"
SUITE="$VSEVALS_DIR/suite.yaml"

# ── Defaults ──────────────────────────────────────────────────────────────────
VARIANTS="P0,P1,P2,P3,P4,P5b,P5a,P6b,P6a"
TASKS=""
VOLTSNIP_URL="http://localhost:8011"
OUTPUT_DIR="$REPO_ROOT/vsevals_runs"
RUN_PYTEST=true
SPACING="0.5"
LOG_LEVEL="INFO"
MAX_TOKENS=""
LLM_TIMEOUT="300"
MAX_TOOL_ROUNDTRIPS=""

# ── Parse args ────────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --variants)     VARIANTS="$2";      shift 2 ;;
    --tasks)        TASKS="$2";         shift 2 ;;
    --voltsnip-url) VOLTSNIP_URL="$2";  shift 2 ;;
    --output-dir)   OUTPUT_DIR="$2";    shift 2 ;;
    --no-pytest)    RUN_PYTEST=false;   shift   ;;
    --spacing)      SPACING="$2";       shift 2 ;;
    --log-level)    LOG_LEVEL="$2";     shift 2 ;;
    --max-tokens)   MAX_TOKENS="$2";    shift 2 ;;
    --llm-timeout)  LLM_TIMEOUT="$2";   shift 2 ;;
    --max-tool-roundtrips) MAX_TOOL_ROUNDTRIPS="$2"; shift 2 ;;
    -h|--help)      sed -n '2,60p' "$0" | grep '^#' | sed 's/^# \?//'; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

# ── Helpers ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

log()  { echo -e "${CYAN}[$(date +%H:%M:%S)]${RESET} $*"; }
ok()   { echo -e "${GREEN}✓${RESET} $*"; }
warn() { echo -e "${YELLOW}⚠${RESET}  $*"; }
die()  { echo -e "${RED}✗${RESET}  $*" >&2; exit 1; }

# ── Auth helpers ──────────────────────────────────────────────────────────────
ensure_codex_api_auth() {
  local status_raw status_line
  status_raw="$(codex login status 2>&1 || true)"
  status_line="$(printf '%s\n' "$status_raw" | grep -i -m1 '^Logged in using ' || true)"

  if printf '%s\n' "$status_line" | grep -qi 'api key'; then
    ok "Codex CLI already using API key auth"
    return 0
  fi

  if printf '%s\n' "$status_line" | grep -qi 'chatgpt'; then
    warn "Codex CLI currently using ChatGPT credits — switching to API key auth"
  else
    log "Configuring Codex CLI for API key auth"
  fi

  if printf '%s\n' "$OPENAI_API_KEY" | codex login --with-api-key >/dev/null 2>&1; then
    ok "Codex CLI set to API key auth (OPENAI_API_KEY)"
    return 0
  fi

  die "Failed to set Codex CLI API key auth via 'codex login --with-api-key'"
}

# ── Load .env ─────────────────────────────────────────────────────────────────
if [[ -f "$REPO_ROOT/.env" ]]; then
  log "Loading .env from $REPO_ROOT/.env"
  # Export all vars defined in .env (skip comments and blank lines)
  set -a
  # shellcheck disable=SC1090
  source "$REPO_ROOT/.env"
  set +a
  ok "API keys loaded from .env"
elif [[ -f "$REPO_ROOT/vsevals/.env" ]]; then
  log "Loading .env from $REPO_ROOT/vsevals/.env"
  set -a
  # shellcheck disable=SC1090
  source "$REPO_ROOT/vsevals/.env"
  set +a
  ok "API keys loaded from vsevals/.env"
else
  warn ".env not found — relying on exported OPENAI_API_KEY / ANTHROPIC_API_KEY"
fi

# ── Pre-flight checks ─────────────────────────────────────────────────────────
log "${BOLD}Pre-flight checks${RESET}"

# Detect nested Claude Code session (claudecode provider will fail immediately)
if [[ -n "${CLAUDECODE:-}" ]]; then
  die "This script cannot run inside a Claude Code session (CLAUDECODE env var is set).
  Open a plain terminal outside Claude Code and run:
    cd $(pwd) && ./vsevals/scripts/run_cross_eval.sh $*"
fi

[[ -f "$PYTHON" ]]  || die "vsevals venv not found at $PYTHON — run: cd vsevals && uv sync"
[[ -f "$SUITE" ]]   || die "suite.yaml not found at $SUITE"

[[ -n "${OPENAI_API_KEY:-}" ]] || die "OPENAI_API_KEY not set (needed for codex: models)"

command -v claude &>/dev/null || die "'claude' CLI not found — install Claude Code"
command -v codex  &>/dev/null || die "'codex' CLI not found — install Codex CLI"
ensure_codex_api_auth

# Check if backend is reachable (warn only — P0/P1 don't need it)
if curl -sf --max-time 3 "$VOLTSNIP_URL/health" &>/dev/null; then
  ok "VoltSnip backend reachable at $VOLTSNIP_URL"
else
  warn "VoltSnip backend NOT reachable at $VOLTSNIP_URL"
  warn "P2-P6a variants will fail without it. Continuing anyway..."
fi

if $RUN_PYTEST; then
  command -v docker &>/dev/null || { warn "Docker not found — pytest phase will be skipped"; RUN_PYTEST=false; }
fi

mkdir -p "$OUTPUT_DIR"
LOG_DIR="$OUTPUT_DIR/logs"
mkdir -p "$LOG_DIR"

# ── Build common args ─────────────────────────────────────────────────────────
COMMON_ARGS=(
  --suite          "$SUITE"
  --variants       "$VARIANTS"
  --voltsnip-url   "$VOLTSNIP_URL"
  --output-dir     "$OUTPUT_DIR"
  --spacing        "$SPACING"
  --log-level      "$LOG_LEVEL"
  --llm-timeout    "$LLM_TIMEOUT"
)
[[ -n "$TASKS" ]]      && COMMON_ARGS+=(--tasks "$TASKS")
[[ -n "$MAX_TOKENS" ]] && COMMON_ARGS+=(--max-tokens "$MAX_TOKENS")
[[ -n "$MAX_TOOL_ROUNDTRIPS" ]] && COMMON_ARGS+=(--max-tool-roundtrips "$MAX_TOOL_ROUNDTRIPS")

# ── Summary banner ────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}═══════════════════════════════════════════════════════${RESET}"
echo -e "${BOLD}  VoltSnip Cross-Eval Runner${RESET}"
echo -e "${BOLD}═══════════════════════════════════════════════════════${RESET}"
echo -e "  Variants     : $VARIANTS"
echo -e "  Tasks        : ${TASKS:-all (22)}"
echo -e "  VoltSnip URL : $VOLTSNIP_URL"
echo -e "  Output dir   : $OUTPUT_DIR"
echo -e "  Pytest       : $RUN_PYTEST"
echo -e "  Max tokens   : ${MAX_TOKENS:-model default}"
echo -e "  LLM timeout  : ${LLM_TIMEOUT}s  (MCP paths: max(600, ${LLM_TIMEOUT}*2)s)"
echo -e "  Tool rounds  : ${MAX_TOOL_ROUNDTRIPS:-suite defaults}"
echo -e "  Logs         : $LOG_DIR"
echo ""
echo -e "  ${CYAN}claudecode${RESET} models : claude-opus-4-6, claude-sonnet-4-6, claude-haiku-4-5"
echo -e "  ${CYAN}codex${RESET} models     : gpt-5.2, gpt-5.3-codex"
echo -e "  Scoring            : lexical only — no LLM judge during run"
echo -e "                       Run inference/judging separately after data collection"
echo -e "${BOLD}═══════════════════════════════════════════════════════${RESET}"
echo ""

# ── Phase 1: sequential code-gen + scoring ────────────────────────────────────
log "${BOLD}Phase 1 — Sequential code generation + scoring (claudecode → codex)${RESET}"
echo ""

CLAUDECODE_LOG="$LOG_DIR/phase1_claudecode.log"
CODEX_LOG="$LOG_DIR/phase1_codex.log"

# Record start timestamp so we can find the new matrix dirs after
PHASE1_START=$(date +%s)

# -- 1. claudecode (live output to terminal + log) --
log "Starting claudecode (lexical scoring)  →  $CLAUDECODE_LOG"
"$PYTHON" "$VSEVALS_DIR/scripts/run_matrix.py" \
  "${COMMON_ARGS[@]}" \
  --models       claudecode:claude-opus-4-6,claudecode:claude-sonnet-4-6,claudecode:claude-haiku-4-5 \
  --scoring-mode lexical \
  2>&1 | tee "$CLAUDECODE_LOG"
ok "claudecode complete"

echo ""

# -- 2. codex (live output to terminal + log) --
log "Starting codex (lexical scoring)  →  $CODEX_LOG"
"$PYTHON" "$VSEVALS_DIR/scripts/run_matrix.py" \
  "${COMMON_ARGS[@]}" \
  --models       codex:gpt-5.2,codex:gpt-5.3-codex \
  --scoring-mode lexical \
  2>&1 | tee "$CODEX_LOG"
ok "codex complete"

echo ""
ok "Phase 1 complete"

# ── Find the matrix dirs created during Phase 1 ───────────────────────────────
log "Locating matrix output directories..."

# Find dirs newer than PHASE1_START
MATRIX_DIRS=()
while IFS= read -r d; do
  MATRIX_DIRS+=("$d")
done < <(find "$OUTPUT_DIR" -maxdepth 1 -name "matrix_*" -type d \
           -newer <(date -r "$PHASE1_START" +%s 2>/dev/null || echo /dev/null) \
           2>/dev/null | sort || \
         ls -td "$OUTPUT_DIR"/matrix_*/ 2>/dev/null | head -4)

# Fallback: just grab the two most recent (bash 3.2 compatible — no mapfile)
if [[ ${#MATRIX_DIRS[@]} -lt 2 ]]; then
  MATRIX_DIRS=()
  while IFS= read -r d; do
    MATRIX_DIRS+=("$d")
  done < <(ls -td "$OUTPUT_DIR"/matrix_*/ 2>/dev/null | head -2)
fi

if [[ ${#MATRIX_DIRS[@]} -eq 0 ]]; then
  die "No matrix directories found in $OUTPUT_DIR — Phase 1 may have failed"
fi

echo ""
echo -e "${BOLD}Matrix directories created:${RESET}"
for d in "${MATRIX_DIRS[@]}"; do
  # Peek at the model column to label the dir
  MODEL_SAMPLE=$(tail -n +2 "$d/matrix_results.csv" 2>/dev/null | cut -d, -f4 | head -1 || echo "unknown")
  echo -e "  ${CYAN}$d${RESET}  (model sample: $MODEL_SAMPLE)"
done
echo ""

# ── Phase 2: pytest ───────────────────────────────────────────────────────────
if $RUN_PYTEST; then
  log "${BOLD}Phase 2 — pytest (applying patches, running Docker tests)${RESET}"
  echo ""

  PYTEST_PIDS=()
  for dir in "${MATRIX_DIRS[@]}"; do
    dir="${dir%/}"  # strip trailing slash
    basename_dir="$(basename "$dir")"
    PYTEST_LOG="$LOG_DIR/phase2_pytest_${basename_dir}.log"
    log "Starting pytest phase for: $basename_dir  →  $PYTEST_LOG"

    "$PYTHON" "$VSEVALS_DIR/scripts/run_pytest_phase.py" \
      --matrix-dir "$dir" \
      --suite      "$SUITE" \
      --pytest-timeout 300 \
      --log-level  "$LOG_LEVEL" \
      > "$PYTEST_LOG" 2>&1 &

    PYTEST_PIDS+=($!)
    echo -e "  PID: ${YELLOW}${PYTEST_PIDS[-1]}${RESET}"
  done

  echo ""
  log "Waiting for all pytest phases to finish..."
  PYTEST_OK=true
  for pid in "${PYTEST_PIDS[@]}"; do
    if wait "$pid"; then
      ok "pytest worker $pid done"
    else
      warn "pytest worker $pid exited with non-zero status"
      PYTEST_OK=false
    fi
  done

  $PYTEST_OK && ok "Phase 2 complete" || warn "Phase 2 finished with some failures — check logs in $LOG_DIR"
else
  log "Skipping Phase 2 (--no-pytest specified)"
  echo ""
  echo -e "  To run pytest later on each matrix dir:"
  for dir in "${MATRIX_DIRS[@]}"; do
    echo -e "  ${CYAN}python vsevals/scripts/run_pytest_phase.py \\${RESET}"
    echo -e "      --matrix-dir ${dir%/} \\"
    echo -e "      --suite $SUITE"
    echo ""
  done
fi

# ── Final summary ─────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}═══════════════════════════════════════════════════════${RESET}"
echo -e "${BOLD}  Run complete${RESET}"
echo -e "${BOLD}═══════════════════════════════════════════════════════${RESET}"
for dir in "${MATRIX_DIRS[@]}"; do
  dir="${dir%/}"
  echo ""
  echo -e "  ${CYAN}$(basename "$dir")${RESET}"
  if [[ -f "$dir/matrix_summary.json" ]]; then
    python3 -c "
import json, sys
s = json.load(open('$dir/matrix_summary.json'))
print(f'    models     : {s.get(\"models\",\"?\")}'  )
print(f'    total cells: {s.get(\"total_cells\",\"?\")}'  )
print(f'    ok cells   : {s.get(\"ok_cells\",\"?\")}'  )
print(f'    passed     : {s.get(\"passed_cells\",\"?\")}'  )
print(f'    avg score  : {s.get(\"avg_score\",\"?\")}'  )
" 2>/dev/null || echo "    (summary not yet available)"
  fi
  # Token & cost summary from CSV
  if [[ -f "$dir/matrix_results.csv" ]]; then
    python3 -c "
import csv, sys
rows = list(csv.DictReader(open('$dir/matrix_results.csv')))
ok_rows = [r for r in rows if r.get('status') == 'ok']
def _f(v):
    try: return float(v) if v else 0.0
    except: return 0.0
def _i(v):
    try: return int(v) if v else 0
    except: return 0
total_prompt   = sum(_i(r.get('prompt_tokens',''))     for r in ok_rows)
total_complete = sum(_i(r.get('completion_tokens','')) for r in ok_rows)
total_thinking = sum(_i(r.get('thinking_tokens',''))   for r in ok_rows)
total_cost     = sum(_f(r.get('cost_usd',''))          for r in ok_rows)
print(f'    prompt tok : {total_prompt:,}')
print(f'    output tok : {total_complete:,}')
if total_thinking > 0:
    print(f'    think tok  : {total_thinking:,}')
if total_cost > 0:
    print(f'    est. cost  : \${total_cost:.4f} USD')
" 2>/dev/null
  fi
  echo -e "    report     : $dir/matrix_report.md"
  echo -e "    csv        : $dir/matrix_results.csv"
done
echo ""
echo -e "  Logs : $LOG_DIR"
echo -e "${BOLD}═══════════════════════════════════════════════════════${RESET}"
