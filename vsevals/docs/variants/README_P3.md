# P3 Deep Dive

## 1. Intent

`P3` measures the effect of oracle context injection without interactive tools.

It prefetches required snippets and injects them into prompt context, giving the model high-quality memory up front while keeping tool loops disabled.

This isolates "given the right memory, can the model apply it?".

## 2. Canonical config shape

```yaml
id: P3
mode: agent
memory_enabled: true
tools_enabled: false
retrieval_mode: injected
instruction_mode: none
context_surface: system
max_tool_roundtrips: 4
include_oracle: false
```

## 3. Critical nuance: declared mode vs runtime path

Although `mode=agent`, runtime enters non-tool direct branch because `tools_enabled=false`.

So operationally `P3` is single-call after prefetch + prompt injection.

## 4. Retrieval behavior

Prefetch happens before prompt build via `_retrieve_snippets()`:

- keys source: `task.voltsnip.required_snippets`
- fetch API: `VoltSnipClient.get_by_canonical_keys(...)`
- limits: task/config snippet limit + max chars

No semantic search is used in this stage.

## 5. Prompt surface behavior

`context_surface=system` injects into system prompt:

- snippet bodies (`VoltSnip Context` block)
- guiding snippet keys
- repository policy block

User prompt still contains task metadata/target metadata; memory payload sits in system side.

## 6. Tools and sidecars

- tools disabled
- no sidecars written
- tool traces expected empty

## 7. Artifact expectations

`P3` runs should show:

- `summary_metrics.snippet_count > 0` for tasks with required snippets
- `summary_metrics.tool_call_count = 0`
- injected snippet content visible in `prompt.system`

## 8. What P3 tells you

`P3` is an upper-bound style memory-injection control for non-tool execution.

Useful for:

- separating retrieval quality problems from application quality problems
- estimating gains achievable by perfect retrieval

If `P3` still fails where `P2/P4/P5/P6` also fail, issue is likely model reasoning/application, not retrieval discovery.

## 9. Common failure patterns

- model ignores injected snippet despite presence
- line-range output contract violations
- misapplication of partially relevant snippet
- conflict between injected snippet and task-specific edge case

## 10. Interpretation guidance

Compare:

- `P3 - P0`: pure value of pre-injected memory
- `P2 - P3`: self-directed retrieval vs oracle injection tradeoff

Strong `P3` + weak `P2` indicates retrieval strategy bottleneck.

