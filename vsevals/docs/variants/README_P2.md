# P2 Deep Dive

## 1. Intent

`P2` is the raw tool-enabled retrieval baseline.

It turns tools on with no sidecar guidance and no pre-injected snippets. The model must decide:

- whether to retrieve,
- what query/key strategy to use,
- how to combine retrieved context with local code inspection.

This variant isolates unguided retrieval behavior.

## 2. Canonical config shape

```yaml
id: P2
mode: agent
memory_enabled: false
tools_enabled: true
retrieval_mode: agent_decides
instruction_mode: none
context_surface: tools_only
max_tool_roundtrips: 4
include_oracle: false
```

## 3. Execution path in code

`P2` enters `_run_agent()` because `mode=agent` and `tools_enabled=true`.

Behavior by provider:

- `claudecode`/`codex`: subprocess tool loop; traces parsed from JSONL after run
- `openai` tool mode: Responses API with MCP (server-side loop)
- `anthropic` tool mode: SDK loop + Python handlers

No prefetch retrieval occurs before prompt build (`memory_enabled=false`).

## 4. Prompt surface behavior

`context_surface=tools_only`:

- no snippet keys/context injected in user/system prompt
- no sidecar files written
- system receives minimal tool-availability banner only

The model must infer retrieval strategy from task objective + available tools.

## 5. Tool surface details

Requested tool schemas are VoltSnip-focused (`search_memory`, `get_snippet_by_canonical_key` etc.).

Provider realization differs:

- ClaudeCode: native `Read/Glob/Grep` + VoltSnip MCP tools, `Bash` disallowed policy
- Codex: local HarnessMCP tools + shell under sandbox policy
- Anthropic: Python-executed handlers
- OpenAI: remote MCP tool loop via Responses API

## 6. Budget semantics

`max_tool_roundtrips` is exposed in prompt and passed in orchestration.

Practical enforcement differs:

- anthropic handler path enforces loop bounds in-process
- subprocess/server-side loops may not be hard-capped equivalently

Interpret high tool-call counts with provider semantics in mind.

## 7. Retrieved snippet accounting

Because subprocess providers execute tools outside Python handlers, harness back-fills snippets from parsed tool traces (`_merge_tool_snippets`).

This is critical for fair memory usage metrics in `summary_metrics.snippet_count`.

## 8. Artifact expectations

Compared with `P0/P1`:

- non-empty `tool_traces` expected when retrieval actually used
- `prompt_after_tools` may differ due back-filled snippet state
- subprocess providers should emit `subprocess.stdout.<provider>.jsonl`

## 9. What P2 tells you

`P2` answers whether models can self-direct retrieval without curation.

It is useful for diagnosing:

- discovery/query formulation quality,
- unnecessary tool churn,
- failure to retrieve despite tool availability.

## 10. Common failure patterns

- no retrieval calls despite needing memory
- noisy or broad semantic queries that miss canonical snippet
- over-retrieval with low signal integration
- tool transport/provider-specific errors (MCP connectivity, auth, parsing)

## 11. Interpretation guidance

Pair with:

- `P0`/`P1`: net value of enabling tools at all
- `P4`/`P5`/`P6`: value of guidance surfaces on top of tool availability

If `P2` underperforms guided variants significantly, your bottleneck is likely retrieval strategy, not tool presence.

