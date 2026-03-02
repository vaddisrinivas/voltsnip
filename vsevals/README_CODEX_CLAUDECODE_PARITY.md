# Codex vs ClaudeCode Parity Audit (vsevals)

Audit date: 2026-03-02

## Verdict

For tool-enabled agent variants (P2/P4/P5/P6), Codex and ClaudeCode are aligned on the main harness plumbing (same prompting/paths/artifacts), but **not strict behavioral parity**:

- Same task/variant prompt payloads.
- Same resolved `repo_root` passed from runner.
- Same sidecar file materialization strategy.
- Same timeout policy for tool-enabled subprocess calls.
- Same artifact persistence model (stdout/stderr + parsed tool traces).

They are **not byte-for-byte 1:1** (different CLIs require different flags/plumbing), and there is one meaningful skew risk: Codex can rely on shell under sandbox constraints, while ClaudeCode tool-enabled mode explicitly disallows `Bash`.

## Scope Checked

1. Runner routing and `repo_root` resolution.
2. Provider invocation construction (`claudecode.py`, `codex.py`).
3. Tool transport path (direct VoltSnip MCP vs HarnessMCP proxy).
4. Sidecar write/cleanup behavior.
5. Timeout and subprocess artifact behavior.
6. No-tools invocation behavior.

## Evidence (Code References)

- Runner resolves one `repo_root` and passes it to both providers:
  - `vsevals/vsevals/runner.py:189-192`
  - `vsevals/vsevals/runner.py:413-431`
- Repo-root resolution algorithm:
  - `vsevals/vsevals/runner.py:719-730`
- ClaudeCode builder:
  - `vsevals/vsevals/providers/claudecode.py:269-414`
  - Uses `cwd=repo_root` when `repo_root and tool_schemas` (`370-375`).
  - Writes sidecars into repo root in tool-enabled runs (`375-379`).
  - Uses direct VoltSnip MCP config (`346-359`).
- Codex builder:
  - `vsevals/vsevals/providers/codex.py:251-373`
  - Uses `cwd=repo_root` when `repo_root and tool_schemas` (`327-333`).
  - Writes sidecars into repo root in tool-enabled runs (`329-333`).
  - Uses per-run `HarnessMCPServer` + `mcp_servers.voltsnip.command=curl` (`274-288`).
  - Sets `-C <workspace>` explicitly (`354-355`).
- Shared timeout policy:
  - ClaudeCode: `vsevals/vsevals/providers/claudecode.py:486`
  - Codex: `vsevals/vsevals/providers/codex.py:451`

## Parity Matrix

| Concern | ClaudeCode | Codex | Parity |
|---|---|---|---|
| Repo-root source | From runner `repo_root_str` | From runner `repo_root_str` | Yes |
| Tool-enabled working dir | `cwd=repo_root` | `cwd=repo_root` + `-C repo_root` | Yes |
| Sidecar placement (tool-enabled) | Writes to repo root | Writes to repo root | Yes |
| Sidecar placement (no-tools) | Temp dir fallback | Temp dir fallback | Yes |
| VoltSnip access path | Direct MCP URL (`--mcp-config`) | Local Harness MCP proxy via `curl` | Intent-equivalent |
| Filesystem tool access | Native CLI tools (`Read/Glob/Grep`) allowlisted | Harness MCP tools are available, but codex may also use shell commands | Partial |
| Shell execution surface (tool-enabled) | `Bash` explicitly disallowed (`_DISALLOWED_TOOLS`) | No equivalent per-tool disallowlist; constrained by sandbox only | No |
| Timeout for tool-enabled calls | `max(600, llm_timeout*2)` | `max(600, llm_timeout*2)` | Yes |
| Raw subprocess artifacts | stdout/stderr persisted to run dir | stdout/stderr persisted to run dir | Yes |
| Cleanup | sidecars + temp files removed | sidecars + temp files + MCP server stopped | Yes |

## Important Non-1:1 Differences

These are expected architectural differences:

1. Tool gating mechanism:
   - ClaudeCode uses `--allowedTools/--disallowedTools`.
   - Codex uses sandbox mode + MCP server config (no fine-grained tool deny list like ClaudeCode).
2. VoltSnip integration path:
   - ClaudeCode points directly to VoltSnip MCP endpoint.
   - Codex talks to a local harness MCP server that forwards to VoltSnip + exposes filesystem tools.
3. Workspace scoping:
   - Codex explicitly receives `-C <repo_root>`.
   - ClaudeCode relies on subprocess `cwd`.
4. Execution behavior in practice:
   - Codex can depend on shell exploration (`cat`, `rg`, `find`, etc.) within sandbox constraints.
   - ClaudeCode tool-enabled path explicitly blocks `Bash` and steers to `Read/Glob/Grep` + VoltSnip MCP tools.

## Shared Gap (Not a Codex-vs-Claude Mismatch)

`max_tool_turns` is passed from runner to both providers but is not currently enforced inside either subprocess provider path:

- runner passes it:
  - `vsevals/vsevals/runner.py:418`
  - `vsevals/vsevals/runner.py:427`
- provider signatures accept it:
  - `vsevals/vsevals/providers/claudecode.py:481`
  - `vsevals/vsevals/providers/codex.py:446`
- but neither provider currently applies that value in command args or loop control.

This is a common control-plane gap affecting both providers equally, so it does not create asymmetry by itself.

## Runtime Sanity Check Performed

I executed invocation-build checks (no live model call) and observed:

- tool-enabled:
  - both providers use `cwd == repo_root`
  - both write sidecars into repo root
  - ClaudeCode includes `--mcp-config`
  - Codex includes `mcp_servers.voltsnip.command=curl` and `-C`
- no-tools:
  - both fall back to temp sidecar working dirs
  - Codex sets `--sandbox read-only` and clears MCP servers

## Bottom Line

If your requirement is strict command-line or tool-surface identity, parity is not 1:1.  
If your requirement is only shared wiring (same prompts/repo_root/sidecars/artifacts), current setup is aligned, but keep the shell-surface asymmetry in mind when interpreting results.
