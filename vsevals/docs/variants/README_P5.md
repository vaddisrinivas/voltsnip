# P5 Deep Dive

## 1. Intent

`P5` evaluates agent-oriented workflow guidance (via AGENTS sidecar) with tools enabled and no key hints.

Compared with `P4`, this is a guidance-surface substitution experiment:

- `P4`: skill-style guidance document
- `P5`: agent-style workflow guidance document

## 2. Canonical config shape

```yaml
id: P5
mode: agent
memory_enabled: false
tools_enabled: true
retrieval_mode: agent_decides
instruction_mode: none
context_surface: agents_md_no_keys
max_tool_roundtrips: 4
include_oracle: false
```

## 3. Retrieval and execution behavior

Like `P2/P4`:

- no prefetch memory
- live tool path available
- provider-specific loop semantics unchanged

The experimental delta is in sidecar instruction framing.

## 4. Context surface specifics

For `agents_md_no_keys`, prompt builder writes:

- `CLAUDE.md`
- `AGENTS.md`

Both are loaded from static `agents.md` content (fallback inline if absent).

No snippet keys are injected into prompt or sidecars.

## 5. Guidance semantics

Agent guidance emphasizes:

- retrieve context first,
- inspect code with read/search tools,
- apply minimal fix,
- avoid redundant calls.

It is intentionally static and no-key.

## 6. Artifact expectations

- populated `prompt.sidecar_files` with AGENTS/CLAUDE docs
- tool traces present for successful retrieval usage
- snippet back-fill in subprocess providers same as `P2/P4`

## 7. Common failure patterns

- retrieval skipped despite available tools
- agent workflow text followed but with poor query precision
- excessive shell exploration (especially codex path) with low memory signal

## 8. Metrics to monitor

Compare with `P4` on same tasks/models:

- `tool_budget_utilization`
- `tool_success_rate`
- `voltsnip_tool_call_count`
- score / pass rate deltas

## 9. Interpretation guidance

`P5 > P4` implies agent-style framing is more actionable than skill-style framing for your model/provider mix.

`P5 < P4` implies the opposite, or indicates provider-specific sidecar consumption differences.

