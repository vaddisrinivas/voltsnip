# P4 Deep Dive

## 1. Intent

`P4` adds static skill-style guidance to tool-enabled retrieval without exposing snippet keys.

It tests whether workflow guidance improves retrieval quality and fix quality compared with unguided tools (`P2`).

## 2. Canonical config shape

```yaml
id: P4
mode: agent
memory_enabled: false
tools_enabled: true
retrieval_mode: agent_decides
instruction_mode: none
context_surface: skills_md_no_keys
max_tool_roundtrips: 4
include_oracle: false
```

## 3. Retrieval and execution behavior

- no prefetch (`memory_enabled=false`)
- tool loop available (`tools_enabled=true`)
- provider-specific tool transport as in `P2`

`P4` differs from `P2` only by guidance surface.

## 4. Context surface specifics

For `skills_md_no_keys`, prompt builder writes sidecars:

- `SKILL.md`
- `CLAUDE.md`
- `AGENTS.md`

All three contain skill guidance text from static `skills.md` file (fallback inline text if missing).

Key property:

- no canonical snippet key list is injected into prompt/sidecars

## 5. Why this matters

The model is encouraged to retrieve context first, but still must discover target memory via queries/tool use rather than direct key lookup.

This approximates practical agent instructions while preserving no-key fairness.

## 6. Artifact expectations

Relative to `P2`:

- sidecar files appear in provider working context during run
- `prompt.sidecar_files` populated in `full_dump.json`
- tool usage may become more targeted if guidance is effective

## 7. Common failure patterns

- model follows guidance text superficially but does not retrieve useful snippets
- over-indexing on generic search terms
- guidance file ignored by provider/model combination
- provider asymmetry: shell-heavy codex behavior vs claudecode built-in tool flow

## 8. Metrics to monitor

- `tool_call_count`, `tool_error_count`
- `voltsnip_tool_call_count`
- `snippet_count` after tool back-fill
- score uplift over `P2` and `P1`

## 9. Interpretation guidance

If `P4` significantly outperforms `P2`, guidance framing itself is helping retrieval discipline.

If `P4 ~= P2`, either:

- guidance is not being consumed effectively, or
- task set is not retrieval-strategy sensitive.

