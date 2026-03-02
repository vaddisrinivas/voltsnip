# Variant Deep-Dive Index (`P0..P6`)

This folder contains detailed behavior docs for every hypothesis variant.

## Read order

1. `README_P0.md` — baseline direct generation
2. `README_P1.md` — baseline with explicit instruction strength
3. `README_P2.md` — tools-only retrieval with no sidecar guidance
4. `README_P3.md` — oracle snippet injection without tools
5. `README_P4.md` — skill guidance sidecars + tools (no key hints)
6. `README_P5.md` — agent guidance sidecars + tools (no key hints)
7. `README_P6.md` — combined skill+agent guidance + tools (no key hints)

## Why these docs exist

The harness keeps prompt/template/tool behavior in code paths that can look similar at a high level but differ in critical details:

- whether snippets are prefetched vs retrieved interactively
- whether keys are visible in prompt
- whether sidecar files are generated and where
- whether provider path is SDK-native vs subprocess
- whether tool usage can be budget-limited in-process

These docs make those differences explicit for experiment design and interpretation.

## Common terminology

- `memory_enabled`: prefetch required snippets before model call.
- `tools_enabled`: provider receives a tool surface (MCP or SDK handlers).
- `retrieval_mode`:
  - `none`: no retrieval path.
  - `injected`: prefetch snippets and inject context.
  - `agent_decides`: no prefetch; model may retrieve with tools.
- `context_surface`: where guidance/context is placed (`system`, `user`, sidecars, or tool banner).

## Shared output contract across all variants

All variants use the same base system output shape:

```json
{"code": "<string>", "comments": "<string>"}
```

Line-range tasks must return replacement text only for the specified span.

