# VoltSnip Evals (vsevals) -- Experiment Design and Methodology

## Abstract

VoltSnip Evals is a controlled research harness that measures how much AI coding assistants benefit from semantic code snippet retrieval when solving real-world bugs. The experiment compares five frontier coding agents across seven escalating context/tool configurations, using 40 purpose-built bug-fixing tasks stratified into three difficulty tiers. The central research question is: **Does access to VoltSnip's snippet retrieval meaningfully improve AI bug-fixing accuracy, and under what conditions is the improvement most pronounced?**

The experimental design isolates the causal contribution of snippet retrieval by constructing hard-tier tasks whose correct solutions depend on project-specific constants that exist only in VoltSnip's snippet store. Models without retrieval access must guess these values and will almost certainly fail.

---

## 1. Research Questions

- **RQ1 (Primary):** Does VoltSnip tool access produce a statistically significant accuracy lift on tasks requiring project-specific knowledge?
- **RQ2:** Among tool-enabled variants, does richer context guidance (SKILL.md, AGENTS.md, or both) improve retrieval behavior and downstream accuracy?
- **RQ3:** Is there a ceiling effect on easy tasks where all models already succeed regardless of context?
- **RQ4:** How do medium-difficulty reasoning tasks respond to tool availability versus injected memory?

---

## 2. Task Design

### 2.1 Task Corpus

40 bug-fixing tasks (BUG01--BUG40) target a synthetic Python library (`orgops`) spanning five functional categories:

| Category | Domain | Example Patterns |
|---|---|---|
| `http_resilience` | HTTP client reliability | Retry logic, circuit breakers, exponential backoff, timeout handling |
| `error_contracts` | Error handling contracts | Exception mapping, cause chain preservation, schema compliance |
| `logging_privacy` | Structured logging and privacy | Field redaction, request context propagation, PII hashing |
| `db_patterns` | Database access patterns | Session lifecycle, bulk inserts, row locking, batch sizing |
| `concurrency_cache` | Concurrency and caching | Thread isolation, TTL caching, stampede prevention, eviction policies |

Each task is defined in a YAML file (`tasks/bug22/BUGxx.yaml`) containing:
- **Visible fields:** task ID, name, description, category, difficulty, target file, line range, test command, user prompt, context code, and expected output.
- **VoltSnip configuration:** required snippet keys and retrieval limits.
- **Oracle:** hidden requirements, success indicators, failure modes, evaluation criteria, and binary constraints for the LLM judge.

### 2.2 Difficulty Tiers

**Easy (BUG01--BUG22):**
Standard patterns that frontier models know from pretraining. The correct fix is straightforward and does not require external knowledge. Expected P0 (raw baseline) pass rate: 95%+. These tasks establish a ceiling and validate that the harness itself is not artificially inflating or deflating scores.

**Medium (BUG23--BUG32):**
Harder reasoning patterns. The correct fix requires deeper understanding of language semantics (exception type hierarchies, cause chain preservation, concurrent data structure design) but does not require project-specific constants. Expected P0 failure rate: 25--35%. These tasks test whether tool access and guidance improve reasoning.

**Hard (BUG33--BUG40):**
The correct fix requires project-specific constants from `orgops.policy.standards` that exist only in VoltSnip snippets. Without retrieval access, models must guess constant values and will almost certainly use incorrect values. Examples of required constants:

- `standards.MAX_BACKOFF_SECONDS` (30.0)
- `standards.CIRCUIT_HALF_OPEN_MAX_PROBES` (2)
- `standards.LOG_HMAC_SALT` ("vs-log-v1")

These tasks are designed to produce a clear, measurable lift signal for VoltSnip retrieval.

### 2.3 Test Codebase

All tasks target the `usecases/hybrid-example/` directory, a synthetic Python project structured as:

```
usecases/hybrid-example/
  orgops/
    http/               # HTTP client, retry policy, circuit breaker
    errors/             # Error mapping, exception schemas
    logging/            # Structured logging, field redaction, PII handling
    db/                 # Session management, bulk operations
    policy/standards.py # Project-specific constants (key to hard bugs)
  service/              # Service layer (cache, models)
  tests/unit/           # Pytest test files (one per category)
```

The file `orgops/policy/standards.py` contains the project-mandated constants. For hard-tier tasks, the model must retrieve these values from VoltSnip snippets rather than from the local file (which is intentionally incomplete or absent in the evaluation context).

---

## 3. Variant Ladder (P0--P6)

Seven hypothesis variants test escalating levels of context provision and tool access. Each variant is defined in `suite.yaml` with a unique combination of mode, tool availability, retrieval strategy, and context surface.

| Variant | Mode | Tools | Memory | Context Surface | Max Roundtrips | Purpose |
|---|---|---|---|---|---|---|
| P0 | direct | no | no | user | 1 | Raw baseline: direct prompt, no memory, no tools |
| P1 | direct | no | no | user | 1 | Baseline + explicit instruction tone |
| P2 | agent | yes | no | tools_only | 4 | Tools only -- raw tool use, zero guidance |
| P3 | agent | no | yes | system (injected) | 4 | Memory injected into system prompt (implicit) |
| P4 | agent | yes | no | skills_md_no_keys | 4 | SKILL.md surface + tools (no key hints) |
| P5 | agent | yes | no | agents_md_no_keys | 4 | AGENTS.md surface + tools (no key hints) |
| P6 | agent | yes | no | skills_agents_md_no_keys | 4 | Full surface: SKILL.md + AGENTS.md + tools (no key hints) |

### 3.1 Variant Design Rationale

- **P0 vs P1** isolates the effect of explicit instruction phrasing on baseline performance.
- **P2** gives the model raw tool access with zero guidance about what to search for or how to use VoltSnip. This tests whether models spontaneously discover and use retrieval tools.
- **P3** injects relevant snippet content directly into the system prompt, bypassing retrieval entirely. This tests the value of the information itself, independent of the retrieval mechanism.
- **P4** provides a SKILL.md sidecar that teaches the model how to use VoltSnip tools (API endpoints, search patterns) but does not reveal which specific snippet keys are relevant. The model must decide what to search for based on the task description.
- **P5** provides an AGENTS.md sidecar (workflow-oriented guidance) instead of SKILL.md.
- **P6** combines both SKILL.md and AGENTS.md, providing the richest guidance without pre-baking key hints.

### 3.2 No-Keys Design

All tool-enabled variants (P2, P4--P6) use "no-keys" surfaces. The sidecar templates strip snippet key lists so the model must decide what to search for based on the task description alone. This prevents the experiment from trivially gifting the answer and tests genuine retrieval behavior.

### 3.3 Sidecar File Mechanism

For subprocess-based providers (Claude Code, Codex), sidecar files are written to the working directory before invocation:
- `CLAUDE.md` -- auto-loaded by Claude Code from cwd
- `AGENTS.md` -- auto-loaded by Codex from cwd
- `SKILL.md` -- loaded as a skill reference

The prompt builder (`vsevals/prompt.py`) resolves category-specific templates (e.g., `skills/http_resilience.md`) with a fallback to generic templates (`skills.md`).

---

## 4. Models Under Test

| Model Identifier | Provider | Runtime |
|---|---|---|
| `claudecode:claude-haiku-4-5` | Anthropic | Claude Code subprocess |
| `claudecode:claude-sonnet-4-6` | Anthropic | Claude Code subprocess |
| `claudecode:claude-opus-4-6` | Anthropic | Claude Code subprocess |
| `codex:gpt-5.2-codex` | OpenAI | Codex CLI subprocess |
| `codex:gpt-5.3-codex` | OpenAI | Codex CLI subprocess |

All models use stored OAuth authentication (no API keys needed at invocation). The subprocess providers (`vsevals/providers/claudecode.py`, `vsevals/providers/codex.py`) parse JSONL event streams to extract token usage, tool traces, and cost estimates.

---

## 5. Scoring

### 5.1 Dual Verification

Each run is scored by two independent verification methods:

1. **LLM Judge** -- semantic evaluation of generated code against oracle criteria.
2. **Docker pytest** -- functional validation that runs the patched code against the project's test suite inside an isolated Docker container.

### 5.2 LLM Judge Scoring

**Primary endpoint: Constraint binary scoring.**

When a task defines explicit `constraints` in its oracle, each constraint is independently judged as pass/fail by an LLM judge. The overall score is:

```
overall = passed_constraints / total_constraints
```

Pass threshold: `overall >= 0.70`.

Each constraint includes:
- `id`: unique identifier
- `check`: what to verify
- `judge_prompt`: the decision rule for the judge
- `expected`: whether `true` means pass (default) or `false` means pass (for failure-mode checks)
- `voltsnip_key`: which snippet contains the knowledge needed (for analysis)
- `trap_baseline`: expected P0 pass rate (for calibration)

**Fallback endpoint: Legacy weighted scoring.**

When no explicit constraints are defined, the scorer synthesizes binary constraints from legacy oracle dimensions and applies dimension weights:

| Dimension | Weight |
|---|---|
| hidden_requirements | 40% |
| success_indicators | 30% |
| failure_modes | 20% |
| evaluation_criteria | 10% |

Pass requires: `overall >= 0.70`.

### 5.3 Ensemble Judges

The judge model specification supports `+`-delimited ensembles (e.g., `openai:gpt-5.2+anthropic:claude-opus-4-6`). All judges are called in parallel and verdicts are merged with type-aware voting:

- **Expected=true constraints** (positive checks): LENIENT -- any judge returning `true` yields `true`. This avoids false failures caused by one noisy judge missing a valid implementation.
- **Expected=false constraints** (failure-mode checks): STRICT -- all judges must agree the failure is present. This prevents false accusations of failure from a single unreliable judge.

### 5.4 Judge Prompt Variants

The scorer supports ablation over judge prompt formatting via `judge_prompt_variant`:

| Variant | Format Example | Purpose |
|---|---|---|
| `verdict-true` | `{"verdict":true,"reason":"..."}` | Single true example (anchoring study) |
| `verdict-false` | `{"verdict":false,"reason":"..."}` | Single false example (anchoring study) |
| `none` | `{"verdict":<bool>,"reason":"<explanation>"}` | Abstract placeholder, no concrete anchor |
| `both` (default) | Both true and false examples | Balanced, corrected prompt |
| `pre-67f6ed0` | Single false with verbose reason | Historical baseline comparison |

### 5.5 Docker Pytest Validation

Generated code is applied to the test codebase inside a `moltsnip-pytest` Docker container. The process:

1. Materialize an overlay copy of the repository (excluding `.git`).
2. Write the generated code to the target file at the specified line range.
3. Run `docker run --rm -v overlay:/workspace ...` with the task's test command.
4. Capture exit code, stdout, and stderr.

---

## 6. Hypotheses

**H1 (Primary -- Hard bugs):**
For hard-tier bugs (BUG33--BUG40), variants with VoltSnip tool access (P2, P4--P6) will significantly outperform no-tool variants (P0, P1, P3), because the correct constant values are only available via VoltSnip retrieval.

**H2 (Medium bugs):**
For medium-tier bugs (BUG23--BUG32), tool variants will show moderate improvement over baseline, as retrieval provides useful patterns even when the core fix is reasoning-dependent.

**H3 (Ceiling effect):**
For easy-tier bugs (BUG01--BUG22), all variants will score similarly regardless of context provision, demonstrating a ceiling effect where pretraining knowledge is sufficient.

**H4 (Context surface monotonicity):**
Among tool variants, richer context surfaces will show monotonic improvement: P6 > P5 > P4 > P2. The additional guidance helps models know when and how to retrieve, producing better search queries and more effective use of retrieved snippets.

### 6.1 Primary Metric

The **VoltSnip lift** is defined as the accuracy delta between P0 (raw baseline) and P6 (full context surface with tools) on hard-tier bugs. This is the headline metric for demonstrating the value of snippet retrieval.

---

## 7. Execution Pipeline

### 7.1 Snippet Seeding

Before running experiments, fixture snippets must be seeded to the VoltSnip backend:

```bash
python vsevals/scripts/seed_snippets.py --base-url http://localhost:8000
```

Snippets are stored in `vsevals/snippets/bug22_generic/` as JSON files. Each has a `canonical_key` for idempotent upsert. Re-running the seed script is safe.

### 7.2 Phase 1: Matrix Execution

The matrix runner (`scripts/run_matrix.py`) executes all (task x variant x model) combinations:

```bash
python vsevals/scripts/run_matrix.py \
  --suite vsevals/suite.yaml \
  --models claudecode:claude-haiku-4-5 \
  --workers 6 \
  --judge-model "openai:gpt-5.2+anthropic:claude-opus-4-6" \
  --tasks BUG23,BUG24,BUG25,BUG26,BUG27,BUG28,BUG29,BUG30,BUG31,BUG32,BUG33,BUG34,BUG35,BUG36,BUG37,BUG38,BUG39,BUG40
```

Key flags:
- `--workers N`: parallel execution slots
- `--provider-concurrency N`: per-provider throttle (prevents rate limiting)
- `--judge-model`: LLM judge specification (supports ensemble with `+`)
- `--no-scoring`: skip LLM judge in Phase 1 (score later via rescore)
- `--resume DIR`: resume an incomplete matrix run
- `--variants`: comma-separated variant filter
- `--spacing`: minimum seconds between API calls

### 7.3 Phase 2: Docker Pytest Validation

After matrix execution, run functional validation:

```bash
python vsevals/scripts/run_pytest_phase.py \
  --matrix-dir ./vsevals_runs/matrix_TIMESTAMP \
  --suite vsevals/suite.yaml \
  --workers 4
```

This patches each run's generated code into a Docker container and runs the relevant test. Results are written back into each run's `full_dump.json` as the `pytest_result` field.

### 7.4 Phase 2b: Rescoring

To re-score existing runs with a different judge model or prompt variant:

```bash
python vsevals/scripts/rescore_scoring.py \
  --matrix-dir ./vsevals_runs/matrix_TIMESTAMP \
  --judge-model "openai:gpt-5-mini" \
  --judge-prompt-variant both
```

### 7.5 Analysis and Reporting

```bash
python vsevals/scripts/matrix_insights.py ./vsevals_runs/matrix_TIMESTAMP
```

This generates:
- `matrix_results.csv` -- tabular results (task, variant, model, score, passed, tokens, latency, cost)
- `matrix_report.md` -- human-readable summary
- `matrix_summary.json` -- reproducibility metadata (SHA256 of suite + tasks, git commit)
- `matrix_failure_triage.md` -- failure analysis
- `index.html` -- interactive dashboard

---

## 8. Artifacts

Each individual run produces a directory: `{timestamp}__{task}__{variant}__{model}/`

| Artifact | Contents |
|---|---|
| `full_dump.json` | Complete execution trace: prompt bundle, messages, tool traces, scores, token usage, timings, pytest results, judge audit trail |
| `summary_dump.json` | Compact metrics summary (latency, tokens, cost, pass/fail) |
| `generated_code.txt` | Raw model output (code field) |
| `generated_comments.txt` | Model's explanation (comments field) |

Matrix runs aggregate into `matrix_{timestamp}/` directories containing the CSV, reports, and dashboard.

---

## 9. Repository Structure

```
vsevals/
  suite.yaml                          # Task/variant/model matrix definition
  tasks/bug22/BUG01-BUG40.yaml       # Task definitions with oracle criteria
  snippets/bug22_generic/             # Fixture snippets (seeded to VoltSnip)
  skills.md                           # Generic SKILL.md template
  agents.md                           # Generic AGENTS.md template
  skills/                             # Category-specific SKILL.md templates
  agents/                             # Category-specific AGENTS.md templates
  scripts/
    run_matrix.py                     # Phase 1: Matrix runner (parallel execution)
    run_pytest_phase.py               # Phase 2: Docker pytest validation
    rescore_scoring.py                # Phase 2b: Re-score with different judge
    seed_snippets.py                  # Push snippets to VoltSnip API
    matrix_insights.py                # Analysis and reporting
    build_matrix_csv.py               # CSV construction utilities
    validate_artifacts.py             # Artifact integrity checks
  vsevals/
    runner.py                         # Single-cell runner (run_one entry point)
    models.py                         # Data models (RunConfig, RunResult, ScoreResult, etc.)
    prompt.py                         # Prompt builder (build_prompt entry point)
    scorer.py                         # Scoring pipeline (score_one entry point)
    loader.py                         # Suite YAML loader
    dispatch.py                       # LLM dispatch (model routing, tool loop, cost)
    client.py                         # VoltSnip API client
    patching.py                       # Code patching utilities
    pytest_runner.py                  # Docker pytest execution
    providers/
      claudecode.py                   # Claude Code subprocess provider
      codex.py                        # Codex CLI subprocess provider
      openai.py                       # OpenAI SDK provider (direct API)
      anthropic_provider.py           # Anthropic SDK provider (direct API)
      mock.py                         # Mock provider for testing
    exporters/
      concurrency.py                  # Provider throttling
      csv_mapper.py                   # CSV export utilities
      scoreboard.py                   # Terminal scoreboard
      report_writer.py                # Markdown report generation
  usecases/hybrid-example/            # The test codebase with injected bugs
    orgops/
      http/                           # HTTP client, retry, circuit breaker
      errors/                         # Error mapping, schemas
      logging/                        # Structured logging, redaction, PII
      db/                             # DB session management, bulk ops
      policy/standards.py             # Project-specific constants
    service/                          # Service layer (cache, models)
    tests/unit/                       # Pytest test files (one per category)
```

---

## 10. Key Design Decisions

### 10.1 Hard bugs require VoltSnip

The 8 hard-tier bugs use project-specific constants from `orgops.policy.standards` that only exist in VoltSnip snippets. Models cannot infer these values from pretraining. This is the foundation of the lift measurement: without retrieval, the model guesses; with retrieval, it gets the correct value.

### 10.2 Medium bugs test reasoning, not knowledge

The 10 medium-tier bugs require deeper reasoning (exception cause chains, concurrent data structure semantics, error type hierarchies) but do not require external knowledge. This isolates whether tool access improves reasoning quality, separate from the knowledge-injection effect measured by hard bugs.

### 10.3 No-keys surfaces prevent trivial solutions

Tool-enabled variants strip snippet key lists from sidecar templates. The model must formulate search queries from the task description alone, testing genuine retrieval behavior rather than key-lookup shortcuts.

### 10.4 Idempotent seeding

All snippets have canonical keys. Re-running the seed script is safe and will not create duplicates. This ensures reproducibility across environments.

### 10.5 Docker isolation

Tests run inside `moltsnip-pytest` Docker containers with the codebase mounted as a volume. This guarantees consistent Python versions, dependencies, and execution environments across runs, preventing environmental variance from contaminating results.

### 10.6 Dual verification (LLM judge + pytest)

Two independent scoring methods catch different failure modes. The LLM judge evaluates semantic correctness (did the model understand the fix?) while Docker pytest validates functional correctness (does the patched code actually pass the tests?). Disagreements between the two are diagnostic signals.

### 10.7 Ensemble judges reduce noise

Single small-model judges (e.g., gpt-5-mini) exhibit format-example bias and occasional hallucination. The ensemble with type-aware merging (LENIENT for positive checks, STRICT for failure checks) produces more reliable verdicts without inflating false positives.

### 10.8 Constraint trap baselines

Each constraint includes a `trap_baseline` field: the expected pass rate under P0 (no tools, no memory). This enables calibration -- if a supposedly hard constraint passes at 80% under P0, the task design is flawed rather than the retrieval being unnecessary.

---

## 11. Expected Outcomes

**Easy bugs (BUG01--BUG22):**
Flat accuracy across all variants. All models pass most or all tasks regardless of context provision. This validates the scoring pipeline and establishes a performance ceiling.

**Medium bugs (BUG23--BUG32):**
Moderate lift from P0 to P2 (tools help with reasoning by surfacing relevant patterns). P3 (injected memory) may perform comparably to tool variants since the relevant knowledge is general rather than project-specific. Expected lift: 10--20 percentage points over baseline.

**Hard bugs (BUG33--BUG40):**
Large lift from P0/P1 to P4/P5/P6 (VoltSnip retrieval is necessary for correct constant values). P0 and P1 should fail most hard bugs because the model must guess project-specific constants. P3 (injected memory) may partially help if the injected snippets contain the needed constants. P4--P6 (tool access with guidance) should show the strongest results because the model can actively retrieve the specific snippet containing the required value. Expected lift: 40--60+ percentage points over baseline.

**The VoltSnip lift** -- the delta between P0 and P6 on hard bugs -- is the primary headline metric.

---

## 12. Environment and Prerequisites

### Required Software

- Python 3.12+
- Docker (for pytest validation)
- Claude Code CLI (for `claudecode:*` models)
- Codex CLI (for `codex:*` models)
- VoltSnip backend (local Docker or production URL)

### Environment Variables

| Variable | Purpose |
|---|---|
| `OPENAI_API_KEY` | OpenAI API access (for judge models) |
| `ANTHROPIC_API_KEY` | Anthropic API access (for judge models) |

Subprocess providers (claudecode, codex) use stored OAuth and do not require explicit API keys.

### Quick Start

```bash
# 1. Seed snippets
python vsevals/scripts/seed_snippets.py --base-url http://localhost:8000

# 2. Run a smoke test with mock provider
python vsevals/scripts/run_matrix.py \
  --suite vsevals/suite.yaml \
  --models mock:echo \
  --tasks BUG01 \
  --variants P0

# 3. Run a single model across all hard tasks
python vsevals/scripts/run_matrix.py \
  --suite vsevals/suite.yaml \
  --models claudecode:claude-haiku-4-5 \
  --workers 6 \
  --judge-model "openai:gpt-5.2+anthropic:claude-opus-4-6" \
  --tasks BUG33,BUG34,BUG35,BUG36,BUG37,BUG38,BUG39,BUG40

# 4. Docker pytest validation
python vsevals/scripts/run_pytest_phase.py \
  --matrix-dir ./vsevals_runs/matrix_TIMESTAMP \
  --suite vsevals/suite.yaml \
  --workers 4

# 5. Generate analysis
python vsevals/scripts/matrix_insights.py ./vsevals_runs/matrix_TIMESTAMP
```

---

## 13. Cost Model

The harness tracks per-run cost estimates based on published model pricing. Costs are computed from token usage:

```
cost = (prompt_tokens * input_rate + completion_tokens * output_rate) / 1,000,000
```

Prompt cache hits receive a discount (50% for OpenAI, 90% for Anthropic). Cost data is recorded in `full_dump.json` and aggregated in matrix CSVs for budget tracking.

---

## 14. Reproducibility

Each matrix run records:
- SHA256 hash of `suite.yaml` and all task YAML files
- Git commit hash at execution time
- Full judge audit trail (exact prompt sent to judge, raw response received)
- Complete tool traces with timestamps
- Token usage and cost per run

This metadata is stored in `matrix_summary.json` and enables independent verification of any published result.
