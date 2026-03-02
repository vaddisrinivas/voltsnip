# P6 Deep Dive

## 1. Intent

`P6` is the combined-guidance, tool-enabled no-key variant.

It stacks both guidance surfaces while keeping retrieval discovery burden on the model.

This is the "maximum guidance without explicit key leakage" condition.

## 2. Canonical config shape

```yaml
id: P6
mode: agent
memory_enabled: false
tools_enabled: true
retrieval_mode: agent_decides
instruction_mode: none
context_surface: skills_agents_md_no_keys
max_tool_roundtrips: 4
include_oracle: false
```

## 3. Retrieval and execution behavior

Operationally equivalent to `P2/P4/P5` in tool mechanics:

- no prefetch memory
- model must retrieve context through tools
- provider-specific tool loop semantics unchanged

Only guidance surface changes.

## 4. Context surface specifics

For `skills_agents_md_no_keys`, prompt builder writes:

- `SKILL.md` loaded from static skills doc
- `CLAUDE.md` loaded from static agents doc
- `AGENTS.md` loaded from static agents doc

No key hints are injected.

## 5. Why P6 exists

`P6` checks whether combined guidance yields additive gains over single-guide variants.

It can reveal:

- guidance synergy,
- guidance overload,
- model/provider sensitivity to multiple sidecar channels.

## 6. Artifact expectations

- all three sidecars should be present in `prompt.sidecar_files`
- tool traces and snippet back-fill behavior same as other tool variants

## 7. Common failure patterns

- conflicting or redundant guidance interpretation
- sidecar overload causing noisy tool behavior
- limited improvement over single-guide variants despite more context

## 8. Metrics to monitor

Primary comparisons:

- `P6` vs `P4`
- `P6` vs `P5`
- `P6` vs `P2`

Watch both quality and efficiency:

- overall/pass scores
- tool call counts and error rates
- snippet utilization signal
- pytest pass deltas

## 9. Interpretation guidance

Potential outcomes:

- `P6` best: combined guidance is additive
- `P6` ~= best of (`P4`,`P5`): one guide dominates
- `P6` worse: guidance overload/interference

Always stratify by provider family because sidecar/tool behavior is not perfectly symmetric across `claudecode`, `codex`, `openai`, and `anthropic` paths.

