# vsevals — Experiment Context

## What This Project Is

**vsevals** is an evaluation harness measuring whether AI coding assistants can discover and apply org-private API knowledge from a RAG system (VoltSnip) when fixing bugs.

**Core thesis**: Real-world codebases contain proprietary APIs (orgops.*) that cannot be guessed from training data. This benchmark tests whether retrieval-augmented context (VoltSnip snippets) meaningfully improves fix quality across 9 context-surface variants.

**The benchmark family**: script30 — 30 composition bugs across 5 categories:
- `http_resilience` BUG41-46
- `db_patterns` BUG47-52
- `concurrency_cache` BUG53-58
- `error_contracts` BUG59-64
- `logging_privacy` BUG65-70

Each bug requires TWO things: a code/logic fix (guessable) + an org-specific orgops.* API call (unguessable from training data alone).

---

## The 9 Variants (P0–P8) — Context Surface Ladder

| Variant | Mode | Tools | Retrieval | Guidance | Purpose |
|---------|------|-------|-----------|----------|---------|
| P0 | direct | no | none | none | True zero-shot baseline |
| P1 | direct | no | none | explicit instruction | Instruction framing only |
| P2 | direct | no | injected | none | Pre-fetched snippets in system prompt |
| P3 | agent | yes | agent_decides | none | Tools, zero guidance |
| P4 | agent | yes | agent_decides | SKILL.md plugin | On-demand skill guide |
| P5 | agent | yes | agent_decides | AGENTS.md/CLAUDE.md | Always-visible must-search instruction |
| P6 | agent | yes | agent_decides | SKILL.md + AGENTS.md | Maximum context, both guides |
| P7 | agent | yes | agent_decides | explicit instruction | P3 + explicit framing |
| P8 | agent | yes | agent_decides | SKILL.md + explicit | P4 + explicit framing |

**Key rule**: P0/P1/P2 are `mode: direct` — no CWD, no file discovery, no contamination possible.
P3–P8 are `mode: agent` — CWD is an isolated per-run temp dir. Each gets only its intended sidecar files.

---

## Models Under Test

- `claudecode:claude-haiku-4-5` — Claude Code CLI (agentic, file editing)
- `codex:gpt-5.2-codex` — OpenAI Codex (direct completions)
- `claudecode:claude-sonnet-4-6` — (full matrix, not yet run)
- `codex:gpt-5.3-codex` — (full matrix, not yet run)

---

## How to Run

```bash
cd /Users/srinivasvaddi/Projects/moltsnip_root/vsevals

# Single bug, all variants, 2 models
uv run python -m vsevals.run_matrix suites/script30.yaml \
  --bugs BUG59 \
  --output-dir vsevals_runs/testbatch2

# Subset of bugs
uv run python -m vsevals.run_matrix suites/script30.yaml \
  --bugs BUG55,BUG48,BUG59 \
  --output-dir vsevals_runs/testbatch_multi

# Specific variants only
uv run python -m vsevals.run_matrix suites/script30.yaml \
  --bugs BUG59 --variants P4,P6,P8 \
  --output-dir vsevals_runs/debug_skills

# After run: rescore with LLM judge (requires API keys in env)
uv run python scripts/rescore_scoring.py \
  --matrix-dir vsevals_runs/<batch>/matrix_<timestamp>/ \
  --suite suites/script30.yaml \
  --judge-model "openai:gpt-5.2+anthropic:claude-opus-4-6" \
  [--force]   # use --force if previous no-op run already wrote null scores
```

---

## Run Directory Structure

```
vsevals_runs/<batch_name>/
└── matrix_<timestamp>/
    ├── matrix_summary.json        ← aggregate: total/ok/passed/pytest_passed cells
    ├── matrix_results.csv         ← one row per cell, all metrics
    ├── matrix_results__<judge>.csv ← rescored version
    ├── matrix_report.md           ← human-readable summary
    └── runs/
        └── <timestamp>__<bug>__<variant>__<model>/
            ├── full_dump.json     ← COMPLETE run data (everything)
            ├── generated_code.txt ← what the model produced
            ├── prompt.json        ← exact prompt sent
            ├── pytest.stdout.txt  ← test output
            ├── pytest.stderr.txt  ← test errors
            └── subprocess_stdout.jsonl ← Claude Code session log
```

### Key fields in full_dump.json
- `pytest_passed` — boolean, did the code pass the test
- `retrieved_snippets` — list of snippets the agent fetched
- `required_snippet_hit_keys` — which required keys were retrieved
- `tool_traces` — every MCP tool call with args + response
- `parsed_output.code` — the extracted code patch
- `score` / `overall_score` — LLM judge score (0.0 if no-scoring mode)
- `constraint_results` — per-constraint judge verdicts

---

## Key Code Files

| File | Purpose |
|------|---------|
| `vsevals/providers/claudecode.py` | Claude Code CLI provider — builds subprocess command, writes sidecar files |
| `vsevals/providers/codex.py` | Codex provider — file-system based, maps skills/ → .agents/skills/ |
| `vsevals/prompt.py` | Builds sidecar_files dict per variant; reads guides from vsevals/agents.md + vsevals/skills.md |
| `vsevals/scorer.py` | LLM judge — evaluates constraints, calls judge API |
| `vsevals/runner.py` | Orchestrates a single run cell |
| `vsevals/run_matrix.py` | Matrix runner — dispatches all cells |
| `scripts/rescore_scoring.py` | Offline rescorer — re-runs judge on completed runs |
| `scripts/seed_snippets.py` | Seeds snippet fixtures to VoltSnip backend |
| `suites/script30.yaml` | Full variant/model/task definitions |
| `tasks/script30/BUG*.yaml` | Per-bug specs: target_file, line range, oracle, constraints |
| `snippets/script30/*.json` | Snippet fixtures to seed |
| `paper/PAPER_v2.md` | Research paper being written |

---

## Critical Known Issues & Fixes

### 1. --plugin-dir path (FIXED)
`claudecode.py` must pass `tmpdir/skills/` not `tmpdir/` to `--plugin-dir`.
Claude Code expects `{plugin-dir}/{skill-name}/SKILL.md`.
Fixed line: `plugin_dir = str(Path(_sidecar_dir_cleanup) / "skills")`

### 2. Rescore requires API keys in env
`rescore_scoring.py` silently skips LLM judge if OPENAI_API_KEY/ANTHROPIC_API_KEY not set.
Symptom: all scores 0.000, latency=0ms. Fix: export keys before running rescore.

### 3. Codex fragment injection
Codex (P0–P8) sometimes returns method body without `def` header.
Harness splices this at wrong location → IndentationError or TypeError in pytest.
Affects direct-mode variants most. Symptom: pytest.stderr.txt shows IndentationError.

### 4. BUG48 expected_output leakage
BUG48 task YAML's `expected_output` field contains the literal API call.
This leaks into the model prompt, inflating P4/P7 codex scores artificially.
Not a code bug — a benchmark design flaw. Redesign: abstract description only.

### 5. BUG48 test structure ambiguity
`patch("orgops.auditing.write_event")` wraps `apply_pending()` which calls `get_pending_migrations()`.
Placing the audit call in `get_pending_migrations` with a local import accidentally passes
because the mock re-resolves during the patched scope.

---

## Batch Run History

| Batch | Dir | Bug | claudecode passes | codex passes |
|-------|-----|-----|-------------------|--------------|
| testbatch0 | vsevals_runs/testbatch0/ | BUG55 | P5, P6, P8 | 0/9 |
| testbatch1 | vsevals_runs/testbatch1/matrix_20260313T143940894878Z/ | BUG48 | 0/9 | P4, P7 (design flaws) |
| testbatch2 | vsevals_runs/testbatch2/matrix_20260313T155518271339Z/ | BUG59 | P2, P6, P8 | P2 |

---

## Paper

`paper/PAPER_v2.md` — Current draft of the research paper.
- §2 Background: VoltSnip RAG system
- §5 Benchmark design: script30, two-component tasks
- §6 Experimental setup: variants, models, harness
- §7 Results: per-batch tables + validity analyses
- §8 Discussion: model × task asymmetry, codex failure modes
- §9 Threats to validity
- §10 Future work
- §11 Conclusion

---

## Run Review Reports
<!-- RUN REVIEWS APPENDED BELOW — DO NOT EDIT MANUALLY -->

---
## Run Review — BUG59 — 2026-03-13 20:56 UTC
**Matrix dir**: `vsevals_runs/testbatch2/matrix_20260313T155518271339Z`  
**Bugs**: BUG59  
**Models**: claude-haiku-4-5, gpt-5.2-codex  
**Cells**: 18 total, **4 pytest-pass**  

### Pass/Fail Grid (pytest)

| Model | P0 | P1 | P2 | P3 | P4 | P5 | P6 | P7 | P8 |
|-------|-----|-----|-----|-----|-----|-----|-----|-----|-----|
| claude-haiku-4-5 | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ | ✅ | ❌ | ✅ |
| gpt-5.2-codex | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |

### ✅ Passing Cells — Deep Analysis

#### BUG59 / P2 / claude-haiku-4-5
- Variant: pre-injected snippets in system prompt (direct)
- Retrieved snippets: `voltsnip/script30/category/error_contracts/guiding_principle/v1;voltsnip/script30/hard/bug59/scenario_context/v1`
- Required hits: `voltsnip/script30/category/error_contracts/guiding_principle/v1;voltsnip/script30/hard/bug59/scenario_context/v1`
- Tool calls: 0
- Generated code (first 30 lines):
```python
def classify_http_error(status_code: int) -> str:
    """Classify an HTTP status code into an error category.

    Expected categories:
        - "client_error"  for 400-499
        - "server_error"  for 500-599
        - "unknown"       for anything else

    BUG_59: the implementation lumps ALL codes 400-599 into "server_error"
    instead of splitting 4xx (client) from 5xx (server).  Models must
    also emit an "error.mapped" metric via orgops.metrics.emit().
    """
    if 400 <= status_code < 500:
        category = "client_error"
    elif 500 <= status_code < 600:
        category = "server_error"
    else:
        category = "unknown"
    
    import orgops.metrics
    orgops.metrics.emit("error.mapped", status_code)
    
    return category
```

#### BUG59 / P2 / gpt-5.2-codex
- Variant: pre-injected snippets in system prompt (direct)
- Retrieved snippets: `voltsnip/script30/category/error_contracts/guiding_principle/v1;voltsnip/script30/hard/bug59/scenario_context/v1`
- Required hits: `voltsnip/script30/category/error_contracts/guiding_principle/v1;voltsnip/script30/hard/bug59/scenario_context/v1`
- Tool calls: 0
- Generated code (first 30 lines):
```python
def classify_http_error(status_code: int) -> str:
    """Classify an HTTP status code into an error category.

    Expected categories:
        - "client_error"  for 400-499
        - "server_error"  for 500-599
        - "unknown"       for anything else

    BUG_59: the implementation lumps ALL codes 400-599 into "server_error"
    instead of splitting 4xx (client) from 5xx (server).  Models must
    also emit an "error.mapped" metric via orgops.metrics.emit().
    """
    import orgops.metrics

    orgops.metrics.emit("error.mapped", status_code)
    if 400 <= status_code < 500:
        return "client_error"
    if 500 <= status_code < 600:
        return "server_error"
    return "unknown"
```

#### BUG59 / P6 / claude-haiku-4-5
- Variant: SKILL.md + AGENTS.md + tools (agent, max context)
- Retrieved snippets: `voltsnip/script30/hard/bug41/scenario_context/v1;voltsnip/script30/hard/bug59/scenario_context/v1;voltsnip/script30/hard/bug61/scenario_context/v1;voltsnip/script30/hard/bug64/scenario_context/v1`
- Required hits: `voltsnip/script30/hard/bug59/scenario_context/v1`
- Tool calls: 2
- Generated code (first 30 lines):
```python
def classify_http_error(status_code: int) -> str:
    """Classify an HTTP status code into an error category.

    Expected categories:
        - "client_error"  for 400-499
        - "server_error"  for 500-599
        - "unknown"       for anything else

    BUG_59: the implementation lumps ALL codes 400-599 into "server_error"
    instead of splitting 4xx (client) from 5xx (server).  Models must
    also emit an "error.mapped" metric via orgops.metrics.emit().
    """
    import orgops.metrics
    
    if 400 <= status_code < 500:
        category = "client_error"
    elif 500 <= status_code < 600:
        category = "server_error"
    else:
        category = "unknown"
    
    orgops.metrics.emit("error.mapped", status_code)
    return category
```

#### BUG59 / P8 / claude-haiku-4-5
- Variant: SKILL.md + explicit instruction (agent)
- Retrieved snippets: `voltsnip/script30/hard/bug59/scenario_context/v1`
- Required hits: `voltsnip/script30/hard/bug59/scenario_context/v1`
- Tool calls: 3
- Generated code (first 30 lines):
```python
def classify_http_error(status_code: int) -> str:
    """Classify an HTTP status code into an error category.

    Expected categories:
        - "client_error"  for 400-499
        - "server_error"  for 500-599
        - "unknown"       for anything else

    BUG_59: the implementation lumps ALL codes 400-599 into "server_error"
    instead of splitting 4xx (client) from 5xx (server).  Models must
    also emit an "error.mapped" metric via orgops.metrics.emit().
    """
    import orgops.metrics
    
    if 400 <= status_code < 500:
        result = "client_error"
    elif 500 <= status_code < 600:
        result = "server_error"
    else:
        result = "unknown"
    
    orgops.metrics.emit("error.mapped", status_code)
    return result
```

### ❌ Failing Cells — Diagnosis

- **BUG59/P0/claude-haiku-4-5**: BASELINE MISS (expected — no retrieval, no org-API knowledge) (snippet_cov=0.0, tools=0)
- **BUG59/P0/gpt-5.2-codex**: BASELINE MISS (expected — no retrieval, no org-API knowledge) (snippet_cov=0.0, tools=0)
- **BUG59/P1/claude-haiku-4-5**: BASELINE MISS (expected — no retrieval, no org-API knowledge) (snippet_cov=0.0, tools=0)
- **BUG59/P1/gpt-5.2-codex**: BASELINE MISS (expected — no retrieval, no org-API knowledge) (snippet_cov=0.0, tools=0)
- **BUG59/P3/claude-haiku-4-5**: RETRIEVAL MISS — tools used but required snippet not retrieved (snippet_cov=0.0, tools=2)
- **BUG59/P3/gpt-5.2-codex**: RETRIEVAL MISS — zero tool calls despite tools available (snippet_cov=0.0, tools=0)
- **BUG59/P4/claude-haiku-4-5**: RETRIEVAL MISS — zero tool calls despite tools available (snippet_cov=0.0, tools=0)
- **BUG59/P4/gpt-5.2-codex**: RETRIEVAL MISS — zero tool calls despite tools available (snippet_cov=0.0, tools=0)
- **BUG59/P5/claude-haiku-4-5**: INTEGRATION MISS — snippet retrieved but not correctly applied (snippet_cov=0.5, tools=4)
- **BUG59/P5/gpt-5.2-codex**: INTEGRATION MISS — snippet retrieved but not correctly applied (snippet_cov=0.5, tools=4)
- **BUG59/P6/gpt-5.2-codex**: INTEGRATION MISS — snippet retrieved but not correctly applied (snippet_cov=1.0, tools=6)
- **BUG59/P7/claude-haiku-4-5**: RETRIEVAL MISS — tools used but required snippet not retrieved (snippet_cov=0.0, tools=1)
- **BUG59/P7/gpt-5.2-codex**: INTEGRATION MISS — snippet retrieved but not correctly applied (snippet_cov=1.0, tools=1)
- **BUG59/P8/gpt-5.2-codex**: INTEGRATION MISS — snippet retrieved but not correctly applied (snippet_cov=1.0, tools=6)

### 📄 Paper Alignment Notes

- CONFIRMED: BUG59/P2/claude-haiku-4-5 matches paper prediction ✓
- CONFIRMED: BUG59/P2/gpt-5.2-codex matches paper prediction ✓
- CONFIRMED: BUG59/P6/claude-haiku-4-5 matches paper prediction ✓
- CONFIRMED: BUG59/P8/claude-haiku-4-5 matches paper prediction ✓

### 🔧 Recommended Next Steps

- Scores are 0.0 — run `rescore_scoring.py` from a terminal with OPENAI_API_KEY + ANTHROPIC_API_KEY exported. Use `--force` if prior no-op run exists.
- Codex has 2 direct-mode failures — check pytest.stderr.txt for IndentationError (fragment injection). Consider codex.py def-header fix.
- P4/P8 claudecode has 1 zero-tool-call cells — verify --plugin-dir points to tmpdir/skills/ (not tmpdir/).
- Run passed 4 cells. Add to paper §7 results table and update §11 conclusion if this is a new batch.
- Tested: BUG59. To scale up: run full 30-bug matrix with `--bugs BUG41,BUG42,...BUG70`.

---
## Run Review — BUG59 — 2026-03-13 21:08 UTC
**Matrix dir**: `vsevals_runs/testbatch2/matrix_20260313T155518271339Z`  
**Bugs**: BUG59  
**Models**: claude-haiku-4-5, gpt-5.2-codex  
**Cells**: 18 total, **4 pytest-pass**  

### Pass/Fail Grid (pytest)

| Model | P0 | P1 | P2 | P3 | P4 | P5 | P6 | P7 | P8 |
|-------|-----|-----|-----|-----|-----|-----|-----|-----|-----|
| claude-haiku-4-5 | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ | ✅ | ❌ | ✅ |
| gpt-5.2-codex | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |

### ✅ Passing Cells — Deep Analysis

#### BUG59 / P2 / claude-haiku-4-5
- Variant: pre-injected snippets in system prompt (direct)
- Retrieved snippets: `voltsnip/script30/category/error_contracts/guiding_principle/v1;voltsnip/script30/hard/bug59/scenario_context/v1`
- Required hits: `voltsnip/script30/category/error_contracts/guiding_principle/v1;voltsnip/script30/hard/bug59/scenario_context/v1`
- Tool calls: 0
- Generated code (first 30 lines):
```python
def classify_http_error(status_code: int) -> str:
    """Classify an HTTP status code into an error category.

    Expected categories:
        - "client_error"  for 400-499
        - "server_error"  for 500-599
        - "unknown"       for anything else

    BUG_59: the implementation lumps ALL codes 400-599 into "server_error"
    instead of splitting 4xx (client) from 5xx (server).  Models must
    also emit an "error.mapped" metric via orgops.metrics.emit().
    """
    if 400 <= status_code < 500:
        category = "client_error"
    elif 500 <= status_code < 600:
        category = "server_error"
    else:
        category = "unknown"
    
    import orgops.metrics
    orgops.metrics.emit("error.mapped", status_code)
    
    return category
```

#### BUG59 / P2 / gpt-5.2-codex
- Variant: pre-injected snippets in system prompt (direct)
- Retrieved snippets: `voltsnip/script30/category/error_contracts/guiding_principle/v1;voltsnip/script30/hard/bug59/scenario_context/v1`
- Required hits: `voltsnip/script30/category/error_contracts/guiding_principle/v1;voltsnip/script30/hard/bug59/scenario_context/v1`
- Tool calls: 0
- Generated code (first 30 lines):
```python
def classify_http_error(status_code: int) -> str:
    """Classify an HTTP status code into an error category.

    Expected categories:
        - "client_error"  for 400-499
        - "server_error"  for 500-599
        - "unknown"       for anything else

    BUG_59: the implementation lumps ALL codes 400-599 into "server_error"
    instead of splitting 4xx (client) from 5xx (server).  Models must
    also emit an "error.mapped" metric via orgops.metrics.emit().
    """
    import orgops.metrics

    orgops.metrics.emit("error.mapped", status_code)
    if 400 <= status_code < 500:
        return "client_error"
    if 500 <= status_code < 600:
        return "server_error"
    return "unknown"
```

#### BUG59 / P6 / claude-haiku-4-5
- Variant: SKILL.md + AGENTS.md + tools (agent, max context)
- Retrieved snippets: `voltsnip/script30/hard/bug41/scenario_context/v1;voltsnip/script30/hard/bug59/scenario_context/v1;voltsnip/script30/hard/bug61/scenario_context/v1;voltsnip/script30/hard/bug64/scenario_context/v1`
- Required hits: `voltsnip/script30/hard/bug59/scenario_context/v1`
- Tool calls: 2
- Generated code (first 30 lines):
```python
def classify_http_error(status_code: int) -> str:
    """Classify an HTTP status code into an error category.

    Expected categories:
        - "client_error"  for 400-499
        - "server_error"  for 500-599
        - "unknown"       for anything else

    BUG_59: the implementation lumps ALL codes 400-599 into "server_error"
    instead of splitting 4xx (client) from 5xx (server).  Models must
    also emit an "error.mapped" metric via orgops.metrics.emit().
    """
    import orgops.metrics
    
    if 400 <= status_code < 500:
        category = "client_error"
    elif 500 <= status_code < 600:
        category = "server_error"
    else:
        category = "unknown"
    
    orgops.metrics.emit("error.mapped", status_code)
    return category
```

#### BUG59 / P8 / claude-haiku-4-5
- Variant: SKILL.md + explicit instruction (agent)
- Retrieved snippets: `voltsnip/script30/hard/bug59/scenario_context/v1`
- Required hits: `voltsnip/script30/hard/bug59/scenario_context/v1`
- Tool calls: 3
- Generated code (first 30 lines):
```python
def classify_http_error(status_code: int) -> str:
    """Classify an HTTP status code into an error category.

    Expected categories:
        - "client_error"  for 400-499
        - "server_error"  for 500-599
        - "unknown"       for anything else

    BUG_59: the implementation lumps ALL codes 400-599 into "server_error"
    instead of splitting 4xx (client) from 5xx (server).  Models must
    also emit an "error.mapped" metric via orgops.metrics.emit().
    """
    import orgops.metrics
    
    if 400 <= status_code < 500:
        result = "client_error"
    elif 500 <= status_code < 600:
        result = "server_error"
    else:
        result = "unknown"
    
    orgops.metrics.emit("error.mapped", status_code)
    return result
```

### ❌ Failing Cells — Diagnosis

- **BUG59/P0/claude-haiku-4-5**: BASELINE MISS (expected — no retrieval, no org-API knowledge) (snippet_cov=0.0, tools=0)
- **BUG59/P0/gpt-5.2-codex**: BASELINE MISS (expected — no retrieval, no org-API knowledge) (snippet_cov=0.0, tools=0)
- **BUG59/P1/claude-haiku-4-5**: BASELINE MISS (expected — no retrieval, no org-API knowledge) (snippet_cov=0.0, tools=0)
- **BUG59/P1/gpt-5.2-codex**: BASELINE MISS (expected — no retrieval, no org-API knowledge) (snippet_cov=0.0, tools=0)
- **BUG59/P3/claude-haiku-4-5**: RETRIEVAL MISS — tools used but required snippet not retrieved (snippet_cov=0.0, tools=2)
- **BUG59/P3/gpt-5.2-codex**: RETRIEVAL MISS — zero tool calls despite tools available (snippet_cov=0.0, tools=0)
- **BUG59/P4/claude-haiku-4-5**: RETRIEVAL MISS — zero tool calls despite tools available (snippet_cov=0.0, tools=0)
- **BUG59/P4/gpt-5.2-codex**: RETRIEVAL MISS — zero tool calls despite tools available (snippet_cov=0.0, tools=0)
- **BUG59/P5/claude-haiku-4-5**: INTEGRATION MISS — snippet retrieved but not correctly applied (snippet_cov=0.5, tools=4)
- **BUG59/P5/gpt-5.2-codex**: INTEGRATION MISS — snippet retrieved but not correctly applied (snippet_cov=0.5, tools=4)
- **BUG59/P6/gpt-5.2-codex**: INTEGRATION MISS — snippet retrieved but not correctly applied (snippet_cov=1.0, tools=6)
- **BUG59/P7/claude-haiku-4-5**: RETRIEVAL MISS — tools used but required snippet not retrieved (snippet_cov=0.0, tools=1)
- **BUG59/P7/gpt-5.2-codex**: INTEGRATION MISS — snippet retrieved but not correctly applied (snippet_cov=1.0, tools=1)
- **BUG59/P8/gpt-5.2-codex**: INTEGRATION MISS — snippet retrieved but not correctly applied (snippet_cov=1.0, tools=6)

### 📄 Paper Alignment Notes

- CONFIRMED: BUG59/P2/claude-haiku-4-5 matches paper prediction ✓
- CONFIRMED: BUG59/P2/gpt-5.2-codex matches paper prediction ✓
- CONFIRMED: BUG59/P6/claude-haiku-4-5 matches paper prediction ✓
- CONFIRMED: BUG59/P8/claude-haiku-4-5 matches paper prediction ✓

### 🔧 Recommended Next Steps

- Scores are 0.0 — run `rescore_scoring.py` from a terminal with OPENAI_API_KEY + ANTHROPIC_API_KEY exported. Use `--force` if prior no-op run exists.
- Codex has 2 direct-mode failures — check pytest.stderr.txt for IndentationError (fragment injection). Consider codex.py def-header fix.
- P4/P8 claudecode has 1 zero-tool-call cells — verify --plugin-dir points to tmpdir/skills/ (not tmpdir/).
- Run passed 4 cells. Add to paper §7 results table and update §11 conclusion if this is a new batch.
- Tested: BUG59. To scale up: run full 30-bug matrix with `--bugs BUG41,BUG42,...BUG70`.
