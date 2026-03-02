# P1 Deep Dive

## 1. Intent

`P1` isolates instruction-strength effects without changing memory/tool availability.

Relative to `P0`, it keeps the same direct/no-tool execution but sets `instruction_mode=explicit`.

This measures whether explicit compliance language alone improves bug-fix reliability.

## 2. Canonical config shape

```yaml
id: P1
mode: direct
memory_enabled: false
tools_enabled: false
retrieval_mode: none
instruction_mode: explicit
context_surface: user
max_tool_roundtrips: 1
include_oracle: false
```

## 3. Execution path in code

`P1` follows the same non-tool direct path as `P0`:

- no prefetch retrieval
- no `_run_agent()`
- single provider call via `dispatch.call_llm(...)`

The only intended delta from `P0` is prompt wording.

## 4. Prompt deltas vs P0

With `instruction_mode=explicit`, prompt builder appends strict language in the user prompt.

For no-key surfaces (and `P1` has no retrieval), the explicit section typically says:

- satisfy acceptance criteria / expected output exactly
- keep output deterministic and minimal

Because retrieval mode is `none`, key-visibility guidance remains absent.

## 5. Tools and memory

- memory prefetch: disabled
- tools: disabled
- tool traces: expected empty
- snippet injection: none

## 6. Artifact expectations

- same artifact envelope as `P0`
- primary difference is prompt text content in `prompt.json`

Useful sanity check:

- compare `prompt.user` of `P0` vs `P1` for same task/model
- verify explicit instruction block appears only in `P1`

## 7. What P1 tells you

`P1` quantifies instruction-following uplift independent of retrieval.

Key interpretation:

- if `P1` beats `P0`, prompt framing alone helps
- if `P1 ~= P0`, failures are likely knowledge/context limitations, not instruction weakness

## 8. Common failure patterns

Even with explicit instructions, models can still fail on:

- org-specific API composition
- hidden behavioral constraints
- long-tail semantic correctness not captured by phrasing

## 9. Interpretation guidance

Use paired comparisons:

- `P1 - P0`: instruction effect baseline
- `P4/P5/P6 - P1`: guidance + retrieval effect over already explicit baseline

Avoid attributing `P1` gains to memory/tool factors since those remain disabled.

