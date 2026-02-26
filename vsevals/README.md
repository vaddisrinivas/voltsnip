# vsevals — Simplified VoltSnip Evaluation Harness

A clean, research-reproducible harness for measuring how well LLMs fix bugs
with and without VoltSnip memory/tool augmentation.

## Design principles

- **One flow, easy to read**: `run_one()` in `runner.py` is the only entry point.
  Read it top-to-bottom to understand the entire execution path.
- **No LangChain**: native OpenAI + Anthropic SDK only (plus `claude -p` subprocess for claudecode).
- **No C0/C1 controls**: only P0–P6a hypothesis variants.
- **No god files**: each concern lives in its own module (~100–350 lines each).

## Package layout

```
vsevals/
├── models.py         — all Pydantic data models (SuiteConfig, RunResult, ScoreResult …)
├── loader.py         — load suite YAML + task files
├── prompt.py         — build_prompt(task, variant) → PromptBundle
├── client.py         — VoltSnipClient (HTTP fetch/search with retry)
├── dispatch.py       — call_llm() for openai / anthropic / claudecode / mock
├── scorer.py         — score_one() — constraint binary or legacy weighted
├── runner.py         — run_one(), run_p0()…run_p6a(), artifacts
├── patching.py       — materialize_overlay / apply_rewrite (targeted or full-file)
├── pytest_runner.py  — run_pytest_in_docker() — overlay → Docker → PytestResult
├── skills.md         — P5a/P5b context template (skills_md surface, loaded by prompt.py)
└── agents.md         — P6a/P6b context template (agents_md surface, loaded by prompt.py)
scripts/
├── run_matrix.py — matrix CLI (task × variant × model)
└── run_scale.sh  — convenience wrapper for scale runs
```

## Variants (P0–P6a)

| ID  | Mode   | Memory | Tools | Instruction | Context surface   | Purpose                                      |
|-----|--------|--------|-------|-------------|-------------------|----------------------------------------------|
| P0  | direct | ✗      | ✗     | none        | user              | Baseline: raw task                           |
| P1  | direct | ✗      | ✗     | explicit    | user              | Baseline + explicit instruction              |
| P2  | agent  | ✓      | ✗     | none        | system            | Memory injected (implicit)                   |
| P3  | agent  | ✓      | ✗     | explicit    | system            | Memory injected (explicit instruction)       |
| P4  | agent  | ✗      | ✓     | none        | tools_only        | Tools only — no docs, model decides          |
| P5b | agent  | ✗      | ✓     | none        | skills_md_no_keys | Skill docs (no keys) — model decides what to fetch |
| P5a | agent  | ✗      | ✓     | none        | skills_md         | Skill docs + specific keys — knows what to fetch   |
| P6b | agent  | ✗      | ✓     | none        | agents_md         | Agents.md sidecar + keys, no pre-fetch       |
| P6a | agent  | ✓      | ✓     | none        | agents_md         | Full: agents.md + pre-fetched snippets       |

## Quick start

```bash
# Install (from repo root)
cd /Users/srinivasvaddi/moltsnip
pip install -e vsevals/[llm]

# Single run
vseval --task BUG01 --variant P0 --model openai:gpt-5-nano \
       --suite voltsnip-evals/suite.yaml --output-dir ./vsevals_runs

# Full matrix — claudecode (no ANTHROPIC_API_KEY needed)
MODELS="claudecode:claude-sonnet-4-6,openai:gpt-5-mini" \
  bash vsevals/scripts/run_scale.sh

# Resume interrupted matrix
python vsevals/scripts/run_matrix.py \
  --suite voltsnip-evals/suite.yaml \
  --models claudecode:claude-sonnet-4-6 \
  --resume ./vsevals_runs/matrix_20260225T...
```

## Scoring

**Constraint binary** (default when task has `constraints:` in YAML):
- Each constraint is judged pass/fail by the judge model.
- `overall = passed / total`. Default threshold = 0.70.

**Legacy weighted** (fallback):
- `40% hidden + 30% success + 20% failure_modes + 10% criteria`
- Pass if `overall ≥ 0.70 AND hidden ≥ 0.50 AND failure ≥ 0.60`

Judge model is set with `--judge-model` (default: `openai:gpt-5-mini`).
Use `--judge-model claudecode:claude-haiku-4-5` to run entirely without API keys.

## Providers

| Prefix        | Auth                     | P0–P3 (no tools)      | P4–P6a (tool variants)         |
|--------------|--------------------------|----------------------|-------------------------------|
| `openai:`    | `OPENAI_API_KEY`         | Chat Completions API | Responses API + native MCP    |
| `anthropic:` | `ANTHROPIC_API_KEY`      | Messages API         | Messages API + SDK tool loop  |
| `claudecode:`| Claude Code stored auth  | `claude -p` single   | `claude -p --mcp-config`      |
| `codex:`     | Codex CLI stored auth    | `codex exec` single  | `codex exec` + MCP via `-c`   |
| `mock:`      | none                     | echo stub            | echo stub                     |

**openai P4–P6a**: `dispatch.py` calls `client.responses.create()` with
`{"type": "mcp", "server_url": "{voltsnip_base_url}/mcp"}`. OpenAI handles the
tool loop server-side — the **backend must be publicly accessible** (not localhost).

**claudecode P4–P6a**: writes a temporary `--mcp-config` JSON pointing at the
same MCP endpoint and calls `claude -p --mcp-config <tmp>`. Claude Code handles
the tool loop natively — localhost works. Cannot run inside a Claude Code session.

**codex P4–P6a**: injects VoltSnip MCP per-run via
`-c 'mcp_servers.voltsnip.url="..."'` and `-c 'mcp_servers.voltsnip.enabled=true'`
without modifying `~/.codex/config.toml`. Codex CLI handles the tool loop natively
— localhost works. Run from a plain terminal (not inside Claude Code).

## Output artifacts

Each run produces a timestamped directory under `--output-dir`:
```
vsevals_runs/matrix_20260225T.../
├── matrix_summary.json    ← matrix-level summary (pass rate, timing, model info)
├── matrix_results.csv     ← one row per cell (120+ columns for hypothesis analysis)
├── matrix_report.md       ← human-readable markdown table
└── runs/
    └── 20260225T...BUG01__P0__openai_gpt-5-nano/
        ├── full_dump.json         ← complete RunResult (all fields)
        ├── summary_dump.json      ← lightweight summary
        ├── generated_code.txt     ← extracted code block
        ├── generated_comments.txt ← extracted comments
        └── generated_rewrite.txt  ← full rewrite (same as code block)
```


### How to run

# Full run — all variants, all 22 tasks, then pytest
./vsevals/scripts/run_cross_eval.sh

# Quick smoke test — P0 only, BUG01
./vsevals/scripts/run_cross_eval.sh --variants P0 --tasks BUG01

# P0–P3 only (no backend needed for tools)
./vsevals/scripts/run_cross_eval.sh --variants P0,P1,P2,P3

# Skip pytest (just code-gen + scoring)
./vsevals/scripts/run_cross_eval.sh --no-pytest

# Custom backend URL
./vsevals/scripts/run_cross_eval.sh --voltsnip-url https://voltsnip-api.thetechcruise.com
