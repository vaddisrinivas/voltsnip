# Codex vs ClaudeCode Parity Audit (vsevals)

Audit date: 2026-03-13

## Verdict

For tool-enabled agent variants (P3/P4/P5/P6), Codex and ClaudeCode are aligned on the main harness plumbing (same prompting/paths/artifacts), but **not strict behavioral parity**:

- Same task/variant prompt payloads.
- Same resolved `repo_root` passed from runner.
- Same sidecar file materialization strategy (both always use per-run tmpdir).
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
7. Context-surface guide delivery (CLAUDE.md auto-load vs AGENTS.md).

## Evidence (Code References)

- Runner resolves one `repo_root` and passes it to both providers:
  - `vsevals/vsevals/runner.py:189-192`
  - `vsevals/vsevals/runner.py:413-431`
- Repo-root resolution algorithm:
  - `vsevals/vsevals/runner.py:719-730`
- ClaudeCode builder:
  - `vsevals/vsevals/providers/claudecode.py:295-425`
  - Always uses `cwd=tmpdir` (per-run `tempfile.mkdtemp`) regardless of tool mode (`388-399`).
  - Writes sidecars into tmpdir for all variants (`396-399`).
  - P4: `skills/voltsnip-guide/SKILL.md` written; `--plugin-dir <tmpdir>` added; `Skill` tool allowed.
  - P5/P6: CLAUDE.md included in sidecar files; Claude Code auto-loads it at startup.
  - Uses direct VoltSnip MCP config (no harness proxy).
- Codex builder:
  - `vsevals/vsevals/providers/codex.py:260-415`
  - Always uses `cwd=tmpdir` (per-run `tempfile.mkdtemp`) regardless of tool mode (`305-316`).
  - Writes sidecars into tmpdir for all variants (`313-316`).
  - P4: `skills/voltsnip-guide/SKILL.md` mapped to `.agents/skills/voltsnip-guide/SKILL.md`; Codex auto-discovers at startup.
  - P5/P6: AGENTS.md included in sidecar files; Codex reads it automatically.
  - Uses per-run `HarnessMCPServer` + `mcp_servers.voltsnip.command=curl` for VoltSnip access and filesystem tools.
  - Sets `-C <workspace>` explicitly.
- Shared timeout policy:
  - ClaudeCode: `vsevals/vsevals/providers/claudecode.py:515`
  - Codex: `vsevals/vsevals/providers/codex.py:513`

## Context-Surface Guide Delivery (P4/P5/P6)

Each context surface variant writes guide files as sidecars into tmpdir. Delivery per provider:

| Variant | Guide file(s) written | ClaudeCode mechanism | Codex mechanism |
|---|---|---|---|
| P4 (`skills_md_no_keys`) | `skills/voltsnip-guide/SKILL.md` + `SKILL.md` (cwd fallback) | `--plugin-dir <tmpdir>` loads skill; `Skill` tool allowed | `skills/` mapped to `.agents/skills/voltsnip-guide/SKILL.md`; auto-discovered |
| P5 (`agents_md_no_keys`) | AGENTS.md + CLAUDE.md | CLAUDE.md auto-loaded at startup | AGENTS.md read automatically |
| P6 (`skills_agents_md_no_keys`) | SKILL.md + AGENTS.md + CLAUDE.md (`@SKILL.md\n@AGENTS.md`) | CLAUDE.md `@`-imports both files separately at startup | AGENTS.md auto-read at startup; SKILL.md accessible via `read_file` tool |

Both providers receive equivalent guide content. ClaudeCode uses CLAUDE.md `@`-import syntax to load each guide as a distinct document. Codex auto-reads AGENTS.md and can access SKILL.md via tool if needed.

## Parity Matrix

| Concern | ClaudeCode | Codex | Parity |
|---|---|---|---|
| Repo-root source | From runner `repo_root_str` | From runner `repo_root_str` | Yes |
| Working dir (all modes) | `cwd=tmpdir` (per-run) | `cwd=tmpdir` (per-run) + `-C tmpdir` | Yes |
| Sidecar placement | Writes to tmpdir (all modes) | Writes to tmpdir (all modes) | Yes |
| Guide delivery (P4) | `--plugin-dir` + `Skill` tool allowed | `.agents/skills/` auto-discovered | Intent-equivalent (both on-demand) |
| Guide delivery (P5/P6) | CLAUDE.md auto-loaded at startup | AGENTS.md auto-read | Intent-equivalent |
| VoltSnip access path | Direct MCP URL (`--mcp-config`) | Local Harness MCP proxy via `curl` | Intent-equivalent |
| Filesystem tool access | Native CLI tools (`Read/Glob/Grep`) allowlisted; scoped to tmpdir | Harness MCP `read_file/glob_files/grep_files` (`fs_root=tmpdir`) | Intent-equivalent |
| Shell execution surface (tool-enabled) | `Bash` explicitly disallowed (`_DISALLOWED_TOOLS`) | No equivalent per-tool disallowlist; constrained by sandbox only | No |
| Timeout for tool-enabled calls | `max(600, llm_timeout*2)` | `max(600, llm_timeout*2)` | Yes |
| Raw subprocess artifacts | stdout/stderr persisted to run dir | stdout/stderr persisted to run dir | Yes |
| Cleanup | sidecars tmpdir removed | sidecars tmpdir removed + MCP server stopped | Yes |

## Important Non-1:1 Differences

These are expected architectural differences:

1. **Tool gating mechanism:**
   - ClaudeCode uses `--allowedTools/--disallowedTools`.
   - Codex uses sandbox mode + MCP server config (no fine-grained tool deny list like ClaudeCode).
2. **VoltSnip integration path:**
   - ClaudeCode points directly to VoltSnip MCP endpoint.
   - Codex talks to a local harness MCP server that forwards to VoltSnip + exposes filesystem tools.
3. **Workspace scoping:**
   - Codex explicitly receives `-C <tmpdir>`.
   - ClaudeCode relies on subprocess `cwd`.
4. **Execution behavior in practice:**
   - Codex can depend on shell exploration (`cat`, `rg`, `find`, etc.) within sandbox constraints.
   - ClaudeCode tool-enabled path explicitly blocks `Bash` and steers to `Read/Glob/Grep` + VoltSnip MCP tools.
5. **Guide delivery filename:**
   - ClaudeCode auto-loads `CLAUDE.md` from cwd at startup.
   - Codex auto-reads `AGENTS.md` from cwd.
   - Both files contain identical guide content for a given variant (P6: both files contain the full concatenated skills+agents guide).
6. **Reasoning effort:**
   - ClaudeCode: `--effort <value>` (low | medium | high | max).
   - Codex: `-c model_reasoning_effort=<value>`.
   - Both apply when `cfg.reasoning_effort` is set; value is passed through directly.

## Shared Gap (Not a Codex-vs-Claude Mismatch)

`max_tool_turns` is passed from runner to both providers but is not currently enforced inside either subprocess provider path:

- runner passes it:
  - `vsevals/vsevals/runner.py:418`
  - `vsevals/vsevals/runner.py:427`
- provider signatures accept it:
  - `vsevals/vsevals/providers/claudecode.py:510`
  - `vsevals/vsevals/providers/codex.py:508`
- but neither provider currently applies that value in command args or loop control.

This is a common control-plane gap affecting both providers equally, so it does not create asymmetry by itself.

## Bottom Line

If your requirement is strict command-line or tool-surface identity, parity is not 1:1.
If your requirement is only shared wiring (same prompts/repo_root/sidecars/artifacts/guide content), current setup is aligned, but keep the shell-surface asymmetry in mind when interpreting results.
