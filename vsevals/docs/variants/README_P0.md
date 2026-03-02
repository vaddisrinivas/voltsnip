# P0 Deep Dive

## 1. Intent

`P0` is the pure baseline.

It measures how the model performs on the task using only task-provided prompt/context, without:

- VoltSnip memory prefetch,
- tool-assisted retrieval,
- sidecar workflow guidance.

This is the anchor point for all uplift comparisons.

## 2. Canonical config shape

```yaml
id: P0
mode: direct
memory_enabled: false
tools_enabled: false
retrieval_mode: none
instruction_mode: none
context_surface: user
max_tool_roundtrips: 1
include_oracle: false
```

## 3. Execution path in code

`P0` goes through non-tool path in `run_one()`:

- no `VoltSnipClient` retrieval stage
- `build_prompt(...)` called once
- `dispatch.call_llm(...)` called once with no `tool_schemas`

Because `tools_enabled=false`, `_run_agent()` is not used.

## 4. Prompt surface behavior

`context_surface=user` means any injected contextual blocks (if available) would be in user prompt.

For `P0`, retrieval is disabled (`retrieval_mode=none`), so no snippet keys or snippet body are injected.

Typical visible sections:

- task id/name/objective
- target file, line range, test command (if present)
- context code / expected output (if present)
- execution mode banner (`Direct mode`)
- variant hypothesis text (if populated in suite)

## 5. Tools and memory

- memory prefetch: disabled
- tools: disabled
- tool traces: expected to be empty
- snippet count in summary: expected `0` unless task-level behavior is altered externally

## 6. Artifact expectations

In a healthy `P0` run:

- `prompt.json` exists
- no provider tool traces in `full_dump.json`
- `summary_metrics.tool_call_count = 0`
- `summary_metrics.used_tools = false`
- subprocess/API raw artifact files still depend on provider type

## 7. What P0 tells you

Use `P0` to answer:

- can the model fix this class of bug from raw prompt/context alone?
- how much of final performance is explainable without memory/tools?

If `P0` is already near-ceiling on a bug, memory/tool variants likely show limited uplift.

## 8. Common failure patterns

- model outputs full file when line-range replacement is required
- model returns non-JSON or malformed JSON
- hallucinated imports/paths due lack of retrieval context
- overconfident but semantically wrong fix on org-specific APIs

## 9. Interpretation guidance

Treat `P0` as lower bound for augmentation impact:

- `P3 - P0`: value of oracle context injection without tool interactions
- `P2/P4/P5/P6 - P0`: value of interactive retrieval + guidance surfaces

Always compare on identical task subsets and provider families to avoid attribution errors.

