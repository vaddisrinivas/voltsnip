# vsevals Harness README

This document is the authoritative operator and implementation guide for the `vsevals` evaluation harness in this repository.

It is intentionally detailed and written from current code behavior (`vsevals/vsevals/*.py`), not from historical assumptions.

## 1. What this harness does

`vsevals` evaluates code-fix performance across controlled hypothesis variants (`P0..P6`) by running a matrix of:

- task (`BUGxx`)
- variant (`P0..P6`)
- model (`openai:*`, `anthropic:*`, `claudecode:*`, `codex:*`, `mock:*`)

For each cell it can:

1. load task + variant config,
2. optionally retrieve VoltSnip context,
3. build prompts and optional sidecar files,
4. run the target model/provider,
5. parse normalized JSON output (`{"code": ..., "comments": ...}`),
6. score with an LLM judge,
7. optionally apply patch and execute pytest in Docker,
8. write complete artifacts + CSV/report rows.

## 2. Ground rules and scope

The harness is designed for reproducible comparative experiments, not interactive coding.

Key properties:

- single core execution path in `run_one()`
- variant behavior is declarative in suite YAML (`mode`, `memory_enabled`, `tools_enabled`, `context_surface`, etc.)
- prompt assembly is centralized in `prompt.py`
- provider routing is centralized in `dispatch.py`
- all run output is materialized to disk in structured artifacts

## 3. Package layout

```text
vsevals/
├── pyproject.toml
├── suite.yaml / suites/*.yaml
├── tasks/
├── snippets/
├── usecases/
├── scripts/
└── vsevals/
    ├── models.py
    ├── loader.py
    ├── prompt.py
    ├── client.py
    ├── dispatch.py
    ├── harness_tools.py
    ├── harness_mcp.py
    ├── patching.py
    ├── pytest_runner.py
    ├── scorer.py
    ├── runner.py
    └── providers/
        ├── openai.py
        ├── anthropic_provider.py
        ├── claudecode.py
        ├── codex.py
        └── mock.py
```

## 4. Variant system (`P0..P6`)

The harness evaluates seven hypothesis variants.

Quick table:

| Variant | Mode | Memory Prefetch | Tools | Context Surface |
|---|---|---|---|---|
| P0 | direct | no | no | `user` |
| P1 | direct | no | no | `user` + explicit instruction mode |
| P2 | agent | no | yes | `tools_only` |
| P3 | agent (declared) | yes | no | `system` |
| P4 | agent | no | yes | `skills_md_no_keys` |
| P5 | agent | no | yes | `agents_md_no_keys` |
| P6 | agent | no | yes | `skills_agents_md_no_keys` |

Deep dives:

- `docs/variants/README_P0.md`
- `docs/variants/README_P1.md`
- `docs/variants/README_P2.md`
- `docs/variants/README_P3.md`
- `docs/variants/README_P4.md`
- `docs/variants/README_P5.md`
- `docs/variants/README_P6.md`

## 5. End-to-end execution lifecycle

`run_one()` in `vsevals/runner.py` is the canonical pipeline.

### 5.1 Load and resolve inputs

- suite loaded via `loader.load_suite()`
- task and variant selected from suite maps
- config merged from `RunConfig` defaults + CLI overrides
- repo root resolved from (first non-empty):
  - explicit `--repo-root`
  - `task.task.repo_root`
  - `suite.suite.default_repo_root`

### 5.2 Build retrieval client (if needed)

A `VoltSnipClient` is created only when variant needs memory or tools.

If preflight to VoltSnip base URL fails, run errors before model call for such variants.

### 5.3 Optional prefetch of snippets

If `variant.memory_enabled == true`, harness prefetches `task.voltsnip.required_snippets` before model call.

Important:

- this is oracle key-based retrieval for injected-memory variants
- no semantic search is done in this prefetch stage

### 5.4 Prompt assembly

`prompt.build_prompt()` generates:

- `system_prompt`
- `user_prompt`
- optional sidecars (`SKILL.md`, `AGENTS.md`, `CLAUDE.md`) depending on context surface

Prompt always includes strict output contract requiring JSON with `code` and `comments`.

### 5.5 Provider call

If variant is tool-enabled agent (`mode=agent` and `tools_enabled=true`), path goes through `_run_agent()`.

Otherwise it is single-call path via `dispatch.call_llm()`.

### 5.6 Parse and normalize model output

Provider returns `LLMResult` with:

- parsed payload
- token usage
- raw output
- provider-specific subprocess/API raw captures

### 5.7 Scoring

If `skip_scoring=false` and run status is `ok`, `scorer.score_one()` executes judge scoring.

### 5.8 Optional patch + pytest

If `auto_apply_patch=true`:

- patch is applied to an overlay copy of repo,
- test container is started,
- pytest command from task runs in container,
- overlay and container are torn down.

### 5.9 Artifact materialization

Harness writes:

- full run dump (`full_dump.json`)
- summary dump (`summary_dump.json`)
- prompt snapshot (`prompt.json`)
- generated code/comments text files
- raw provider stdout/stderr / API response payloads (when available)
- optional `pytest.stdout.txt` / `pytest.stderr.txt`

## 6. Prompt and context surfaces

All variants inherit a shared base system contract:

- output must be strict JSON object
- line-range tasks must return replacement only (not full file)
- deterministic minimal edits preferred

Context surfaces:

- `system`: snippet context + keys + repo policy injected in system prompt
- `user`: snippet context + keys + repo policy injected in user prompt
- `tools_only`: no snippet injection, no sidecar guidance, tools enabled
- `skills_md_no_keys`: static skill guide sidecar(s), no canonical keys injected
- `agents_md_no_keys`: static agent guide sidecar(s), no canonical keys injected
- `skills_agents_md_no_keys`: both static guides, no key injection

No-key surfaces intentionally suppress direct key hints in prompt/sidecars.

## 7. Provider behaviors and tool paths

### 7.1 OpenAI (`openai:*`)

- no tools: Chat Completions path
- tools: Responses API with MCP (`tools=[{"type":"mcp", ...}]`)
- MCP URL must be publicly reachable; localhost is rejected in provider code

### 7.2 Anthropic (`anthropic:*`)

- uses Anthropic SDK message loop
- tool calls are executed by Python tool handlers in-process
- `max_tool_turns` is enforced here by loop bound

### 7.3 Claude Code (`claudecode:*`)

- subprocess `claude -p --output-format stream-json`
- cwd: clean per-run tmpdir (isolated per cell; never repo_root)
- tool-enabled runs use:
  - `--mcp-config` pointing to VoltSnip MCP URL
  - `--allowedTools mcp__voltsnip__*` (VoltSnip read tools only)
  - `--disallowedTools` includes `Read`, `Glob`, `Grep`, `Bash`, `Edit`, `Write`, and all other native tools
- no-tools runs: `--allowedTools ""` with the same disallow list — no tool access at all
- sidecar files (`CLAUDE.md`, `AGENTS.md`, `SKILL.md`) written to tmpdir per variant; auto-loaded by the subprocess

### 7.4 Codex (`codex:*`)

- subprocess `codex exec --json --ephemeral --skip-git-repo-check`
- cwd: clean per-run tmpdir (isolated per cell; never repo_root)
- sandbox policy: `--sandbox read-only` for **all** variants (tool-enabled and no-tools alike)
- tool-enabled runs start local `HarnessMCPServer` (VoltSnip-only, `include_fs_tools=False`) and configure MCP via `-c mcp_servers.voltsnip.*`
- no-tools runs: `-c mcp_servers={}` to clear any globally configured MCP servers
- sidecar files (`AGENTS.md`, `SKILL.md`) written to tmpdir per variant; auto-loaded by the subprocess

### 7.5 Mock (`mock:*`)

- deterministic echo stub for local harness sanity

### 7.6 ClaudeCode vs Codex: tool surface parity

Both providers enforce the same accessible information surface:

- **Tools**: VoltSnip MCP read tools only (`search_memory`, `get_snippet_by_canonical_key`, etc.)
- **Filesystem**: no file-read tools; `Read/Glob/Grep` disallowed for claudecode; codex shell is `read-only` sandbox in a tmpdir that contains no orgops source
- **cwd**: clean per-run tmpdir for both — permanent repo fixtures (`AGENTS.md`, `SKILL.md`) are not visible
- **Sidecar guidance**: injected per variant via files written to tmpdir; absent for P0/P1/P2/P3

Remaining mechanical difference: claudecode enforces the boundary via `--allowedTools`/`--disallowedTools` flags; codex enforces it via `--sandbox read-only` + explicit MCP config. The accessible surface is identical.

## 8. Tool budget semantics

`variant.max_tool_roundtrips` is passed through orchestration.

Current enforcement status:

- anthropic SDK tool loop: enforced by loop bound and handler path
- subprocess providers (`claudecode`, `codex`): not natively enforced by CLI flags in current setup
- openai Responses MCP path: no explicit harness-side loop cap in provider implementation

So budget is currently a strong contract for anthropic handler path, and a soft/intent contract elsewhere.

## 9. Scoring model

Scoring is implemented in `scorer.py`.

Two endpoints:

1. constraint-binary (preferred)
2. legacy-weighted fallback when no explicit constraints available

### 9.1 Constraint-binary mode

- each `OracleConstraint` receives verdict from judge
- per-constraint satisfaction:
  - `expected=true`: satisfied when verdict true
  - `expected=false`: satisfied when verdict false
- overall score = `passed_constraints / total_constraints`
- pass gate uses `constraint_pass_threshold` (default 0.70)

### 9.2 Legacy weighted mode

When constraints are absent:

- hidden requirements: 40%
- success indicators: 30%
- failure modes (inverted): 20%
- evaluation criteria: 10%

### 9.3 Ensemble judge behavior

`scoring_judge_model` can be `modelA+modelB+...`.

Merge logic:

- expected-positive checks: lenient (`any true`)
- expected-negative/failure checks: strict (`all true` before inversion)

### 9.4 Note on `scoring_match_mode`

The scorer currently evaluates with judge verdicts; lexical-only keyword matching is not the primary scoring path in current code. Treat the mode field as experimental/config plumbing unless explicitly validated for your branch.

## 10. Patch + pytest execution model

When enabled (`auto_apply_patch=true`):

1. derive patched full file (line-range aware)
2. copy repository to temp overlay
3. write patched target in overlay
4. start Docker test container mounted to overlay
5. execute task `test_command`
6. capture stdout/stderr + counts
7. always cleanup container and overlay

This avoids mutating working tree under evaluation.

## 11. Artifacts and matrix outputs

### 11.1 Per-run directory

Each run writes a timestamped run directory under matrix `runs/`.

Typical files:

- `full_dump.json`
- `summary_dump.json`
- `prompt.json`
- `score_result.json` (if scoring executed)
- `generated_code.txt`
- `generated_comments.txt`
- `patched_<target>.py` (if pytest phase used patching)
- `subprocess.stdout.<provider>.jsonl` (subprocess providers)
- `subprocess.stderr.<provider>.txt` (subprocess providers)
- `llm_response.<provider>.json` (SDK/API providers)
- `pytest.stdout.txt` / `pytest.stderr.txt` (if pytest ran)

### 11.2 Matrix directory

`run_matrix.py` writes:

- `completed.jsonl` (incremental completion ledger)
- `matrix_results.csv`
- `matrix_summary.json`
- `matrix_report.md`
- `runs/` subdirectory with all run artifacts

## 12. Core CLIs and scripts

### 12.1 Single-cell runner

```bash
vseval \
  --task BUG41 \
  --variant P4 \
  --model codex:gpt-5.3-codex \
  --suite /absolute/path/to/vsevals/suites/script30.yaml \
  --output-dir /absolute/path/to/vsevals_runs
```

### 12.2 Matrix runner

```bash
uv run --project vsevals python vsevals/scripts/run_matrix.py \
  --suite /absolute/path/to/vsevals/suites/script30.yaml \
  --models claudecode:claude-sonnet-4-6,codex:gpt-5.3-codex \
  --variants P0,P1,P2,P3,P4,P5,P6 \
  --tasks BUG41,BUG42 \
  --output-dir /absolute/path/to/vsevals_runs \
  --workers 2 \
  --provider-concurrency 2
```

### 12.3 Post-processing helpers

- `scripts/run_pytest_phase.py`: run pytest phase over existing matrix outputs
- `scripts/rescore_pytest.py`: rerun pytest scoring selectively
- `scripts/matrix_insights.py`: aggregate/inspect matrix metrics
- `scripts/validate_artifacts.py`: artifact integrity checks
- `scripts/interactive_debug_runner.py`: interactive run inspection with debug tracing

## 13. Environment prerequisites

Minimum:

- Python >= 3.12
- dependencies from `vsevals/pyproject.toml`
- VoltSnip service reachable for memory/tool variants

Provider-specific:

- `openai:*`: `OPENAI_API_KEY`
- `anthropic:*`: `ANTHROPIC_API_KEY`
- `claudecode:*`: Claude CLI auth configured
- `codex:*`: Codex CLI auth configured

Pytest phase:

- Docker daemon available
- valid test image and workdir for selected usecase

## 14. Reproducibility and comparability checklist

Before comparing model/variant deltas:

1. lock identical task list and suite file hash
2. keep same judge model (or same ensemble spec)
3. keep same `constraint_pass_threshold`
4. keep same VoltSnip backend URL and corpus snapshot
5. compare only on cells with complete artifacts and no run errors
6. check provider asymmetry effects (especially Codex shell surface)

## 15. Known caveats

- Tool budget caps are not uniformly hard-enforced for every provider path.
- Provider tool surfaces are intentionally similar but not identical.
- Public MCP reachability requirement for OpenAI tool mode can invalidate localhost-only setups.
- Some wrapper scripts may carry legacy assumptions; validate script flags against current Python parsers before long runs.

## 16. Variant docs map

Use this order for reading:

1. `docs/variants/README.md`
2. `docs/variants/README_P0.md`
3. `docs/variants/README_P1.md`
4. `docs/variants/README_P2.md`
5. `docs/variants/README_P3.md`
6. `docs/variants/README_P4.md`
7. `docs/variants/README_P5.md`
8. `docs/variants/README_P6.md`

