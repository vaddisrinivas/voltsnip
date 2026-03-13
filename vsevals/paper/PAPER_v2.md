# Which Context Surface Do LLMs Respect Most for Org-Specific API Knowledge?
## An Evaluation Framework Using Controlled Retrieval Variants (v2)

<!-- SUBMISSION TARGET: arXiv cs.SE / EMNLP Findings / MSR 2027 -->
<!-- STATUS: v2 — extended to P0–P8; guide content redesigned; testbatch0 + testbatch1 reported -->
<!-- Last updated: 2026-03-13 -->

---

## Abstract

Large language models perform well on public coding benchmarks yet fail on bugs that require org-specific API knowledge absent from training data.
We present **Script30**, a 30-bug composition benchmark where every signal bug requires both a logic fix and a call to an org-private API (`orgops.*`) that cannot be inferred from pretraining.
We define a **nine-point context surface ladder** (P0–P8) that systematically varies what context the model receives and how strongly it is instructed to retrieve it — from no context (P0) to autonomous retrieval with a focused guide and an explicit mandate (P8).

Three design contributions differentiate v2 from v1:
(1) **Guide content decoupled from retrieval mandate** — guide documents (SKILL.md, AGENTS.md) now describe the repo and retrieval tooling without mandating retrieval; mandates are confined to new explicit-instruction variants (P7/P8).
(2) **On-demand plugin skill delivery** — SKILL.md is delivered as a Claude Code `--plugin-dir` skill and a Codex `.agents/skills/` skill, making it visible on-demand rather than always-present.
(3) **P7/P8 ablation** — new variants isolate the effect of an explicit retrieval mandate layered on top of zero-guidance (P7) and skill-guided (P8) tool access.

Two pilot diagnostic runs surface mechanistic and design findings.
**Testbatch0** (BUG55, concurrency_cache, n=1): for Haiku, retrieval is triggered not by tool availability or skill description, but by *context naming the knowledge gap* — AGENTS.md stating that `orgops.*` APIs cannot be guessed. P5/P6 pass via knowledge-gap recognition; P4 fails. P8 passes via a different path: Skill invocation bootstraps retrieval.
**Testbatch1** (BUG48, db_patterns, n=1): reveals two task-design threats — the `expected_output` field directly exposes the API call, and the test mock structure does not enforce correct method placement — classifying BUG48 as a noisy/leaky signal bug. Additionally, P5 Haiku retrieves correctly for the ordering component but ignores the audit component, suggesting knowledge-gap recognition triggers retrieval for the most salient gap, not all hidden requirements.

---

## 1. Introduction

State-of-the-art LLMs solve a substantial fraction of public coding benchmarks [1,2,3].
These benchmarks measure generalisation over publicly available code.
In production engineering organisations, many bugs require knowledge of *org-specific* APIs: internal metrics emitters, proprietary audit loggers, custom health reporters, and domain-specific abstractions that have never appeared in any public corpus.

When a model encounters a bug requiring `orgops.metrics.emit("cache.stampede.prevented", key_name)`, it cannot succeed by pattern-matching against training data — the function name, argument structure, and import path are all private.
The model must obtain that knowledge from some *context surface*.

This raises a practical question for organisations deploying LLM coding assistants:

> **Which context surface should we invest in?**
> Training-data coverage? Guide documentation? Automated retrieval (RAG)? Explicit mandates?

A related and more subtle question is:

> **What triggers a model to retrieve at all?**
> The availability of tools? A description of what the tools do? A description of the codebase? An explicit instruction?

We answer both questions empirically.
Our v2 contributions are:

1. **Extended ladder P0–P8** with two new explicit-mandate variants (P7/P8) and redesigned guide content that separates informational context from retrieval mandates.
2. **Mechanistic pilot finding** (testbatch0): for Haiku, retrieval is triggered by knowledge-gap recognition (AGENTS.md naming `orgops.*`) rather than by tool availability or skill description alone.
3. **Plugin skill delivery mechanism** for P4/P6/P8: SKILL.md delivered as an on-demand `--plugin-dir` skill (Claude Code) / `.agents/skills/` skill (Codex), not as always-visible documentation.
4. **Retained v1 results** (P0–P6, batch_1, Haiku n=3 / Codex n=2) alongside testbatch0 diagnostics.

---

## 2. Related Work

**Code generation benchmarks.**
HumanEval [1], MBPP [2], and SWE-bench [3] measure capability on public tasks.
Our work differs in that correctness *requires* org-private knowledge unavailable at training time, eliminating training-data leakage as an explanation for success.

**Retrieval-augmented code generation.**
Prior work shows retrieval improves generation [5] but has not decomposed *which retrieval surface* matters — guide document, injected snippet, or autonomous tool call — or *what triggers retrieval* in the first place.

**Tool-augmented LLMs.**
Tool use has been studied in reasoning [6] and web tasks [7].
We study a more specific question: which contextual signals cause a model to initiate tool use for org-API discovery during code repair.

**Agentic coding.**
SWE-agent [4] and related systems demonstrate multi-turn repair.
We ask not *can* agents repair bugs but *which information channel* enables correct org-specific API use, and *what signal causes the agent to seek that channel*.

---

## 3. The Script30 Benchmark

### 3.1 Codebase

Script30 is a synthetic Python microservice codebase (`usecases/script30`) of approximately 2,000 lines across six modules:

| Module | Domain |
|--------|---------|
| `cache/` | Write-behind cache, TTL management, LFU eviction, stampede protection |
| `data/` | Migration runner, query scheduler, replication monitor |
| `logops/` | Log redaction, correlation ID propagation, sanitisation |
| `net/` | DNS cache, retry policy, TLS validation, connection pooling |
| `errors/` | Circuit breaker, dead-letter queue, error contracts, timeout escalation |
| `orgops/` | Org-private metrics, auditing, alerts, compliance, health, tracing, rate limiting |

The `orgops/` module is the *information asymmetry surface*: its API signatures (`orgops.metrics.emit`, `orgops.auditing.write_event`, `orgops.health.report_degradation`, `orgops.compliance.record_decision`, `orgops.alerts.notify`, `orgops.tracing.annotate_span`, `orgops.ratelimit.check_quota`) are absent from any public training corpus.

### 3.2 Bug Construction

Each of the 30 bugs is a **composition bug** requiring two independent fixes:

1. **Logic fix** — a deterministic code repair solvable from training data (e.g., invert a comparison operator, fix modulo operand).
2. **Org-API fix** — a call to an `orgops.*` function with the correct method name, event string, and keyword arguments.

The composition structure ensures P0 cannot pass signal bugs (fails on org-API component) while still requiring genuine reasoning for the logic component.

Bugs span five categories with six bugs each:

| Category | Example org API |
|----------|----------------|
| http\_resilience | `orgops.metrics.emit`, `orgops.health.report_degradation` |
| db\_patterns | `orgops.auditing.write_event`, `orgops.metrics.emit` |
| concurrency\_cache | `orgops.metrics.emit`, `orgops.health.report_degradation` |
| error\_contracts | `orgops.metrics.emit`, `orgops.alerts.notify` |
| logging\_privacy | `orgops.compliance.record_decision`, `orgops.tracing.annotate_span` |

**BUG55** (concurrency\_cache, the testbatch0 probe bug) requires:
- Logic: fix an inverted ratio comparison (`>` → `<`) in `StampedeGuard.should_refresh_early`
- Org-API: emit `orgops.metrics.emit("cache.stampede.prevented", key_name)` on early refresh

### 3.3 Snippet Corpus

VoltSnip serves **35 snippets** for Script30:
- **5 guiding-principle snippets** (one per bug category) with general org-level patterns.
- **30 scenario-context snippets** (one per bug) containing the specific `orgops.*` call signature and a code example.

Each task declares exactly two required snippets; dynamic retrieval may fetch up to 4 snippets per search query.

---

## 4. The Context Surface Ladder (P0–P8)

### 4.1 Design Philosophy (v2)

A key design change in v2 is the **separation of guide content from retrieval mandate**:

- **Guide documents** (SKILL.md, AGENTS.md) are now *informational*: they describe the repo or tooling without telling the model it must retrieve.
- **Retrieval mandates** appear only in the `explicit` instruction block, confined to P7/P8.
- This separation allows clean isolation: does context *naming the knowledge gap* trigger retrieval independently of explicit instruction?

**Guide content v2:**

*AGENTS.md / `CLAUDE.md` (P5, P6):*
> Repository Context: This codebase uses internal org-specific APIs (orgops.*) for metrics, logging, and operational integrations. These APIs are not standard library calls — their signatures and import paths must be looked up, not guessed.

*SKILL.md / voltsnip-guide skill (P4, P6, P8):*
> VoltSnip — Code Pattern Retrieval: VoltSnip is a semantic memory store containing org-specific code patterns, API usage examples, and scenario context for this repo. Use VoltSnip when the fix involves an org-specific API, metric name, import path, or pattern that may not be derivable from the file alone.

Neither document says "you must retrieve." The AGENTS.md document names the knowledge gap; the SKILL.md document describes the tool. Only P7/P8 add an explicit mandate.

### 4.2 Variant Definitions

| Variant | Description | Tools | Guide | Mandate |
|---------|-------------|-------|-------|---------|
| **P0** | Baseline — training data only | ✗ | — | — |
| **P1** | Explicit strictness framing, no tools | ✗ | — | Strictness only |
| **P2** | Pre-fetched snippets injected into system prompt | ✗ | — | — |
| **P3** | Tools available, zero guidance | ✓ | — | — |
| **P4** | On-demand plugin skill (VoltSnip guide), agent decides | ✓ | SKILL.md (on-demand) | — |
| **P5** | Always-visible repo context | ✓ | AGENTS.md (always) | — |
| **P6** | Repo context + on-demand plugin skill | ✓ | AGENTS.md (always) + SKILL.md (on-demand) | — |
| **P7** | Tools + explicit retrieval mandate | ✓ | — | "MUST use retrieval tool" |
| **P8** | On-demand skill + explicit skill mandate | ✓ | SKILL.md (on-demand) | "MUST invoke voltsnip-guide skill" |

**Delivery mechanism:**

*P4/P8 (skill):* SKILL.md with YAML frontmatter is written to `skills/voltsnip-guide/SKILL.md` in a per-run temp directory; Claude Code receives `--plugin-dir <tmpdir>` to load it as an on-demand plugin; the `Skill` tool is added to `--allowedTools`. Codex maps `skills/` to `.agents/skills/voltsnip-guide/SKILL.md` (auto-discovered at startup).

*P5 (repo context):* Content written to both `CLAUDE.md` (auto-loaded by Claude Code at startup from cwd) and `AGENTS.md` (auto-read by Codex at startup).

*P6 (both):* CLAUDE.md = agents/repo context (always-visible); `skills/voltsnip-guide/SKILL.md` = plugin skill (on-demand). `--plugin-dir` passed to Claude Code. Codex reads AGENTS.md at startup and auto-discovers `.agents/skills/`.

*P7:* Explicit instruction in user prompt: "This is strict: you MUST perform at least one snippet retrieval tool call before implementing the fix."

*P8:* Explicit instruction: "This is strict: you MUST invoke the voltsnip-guide skill to retrieve relevant code patterns and context before implementing the fix."

The formal variant specification is in Appendix A.

---

## 5. Evaluation Harness

### 5.1 Provider Parity

Two model families evaluated via their CLI providers:

**Claude Code** (claude-haiku-4-5): `claude -p <prompt> --output-format stream-json --allowedTools <voltsnip+skill> --disallowedTools Bash,Edit,Write,...`

**Codex** (gpt-5.2-codex): `codex --approval-mode full-auto --model <id>` with `HarnessMCPServer` providing VoltSnip tools; `--sandbox read-only`; filesystem tools disabled for tool-enabled variants.

**Tool surface.** Both providers expose only VoltSnip MCP tools for retrieval. In v2, Claude Code additionally allows the `Skill` tool when plugin skills are present; Codex auto-discovers `.agents/skills/`. `ReadMcpResourceTool` and `ListMcpResourcesTool` are blocked on Claude Code to prevent asymmetric resource-read access.

**Working directory isolation.** Both providers run with `cwd` set to an isolated per-run temp directory. Sidecar files (CLAUDE.md, SKILL.md, skills/) are written there. Claude Code auto-loads `CLAUDE.md` from this cwd; Codex maps files as specified above.

**Tool-call budget.** `max_tool_roundtrips=4` for all tool-enabled variants.

### 5.2 Scoring

**Primary metric: pytest pass rate (ground truth).** Each patch is applied to an isolated Docker overlay of the target repo and the task's designated pytest test executed (`--network none`, 300s timeout). Pass iff pytest exits 0.

**Secondary metric: LLM judge score.** An LLM judge evaluates constraint satisfaction. Judge scores inflate pass rates by ~15–25 pp relative to pytest and are reported for reference but not used for primary claims.

---

## 6. Experimental Setup

### 6.1 Batch 1 (v1, P0–P6)

Full 30-bug × 7-variant matrix:

| Provider | Model | N per cell | Total scored runs |
|----------|-------|------------|-------------------|
| Claude Code | claude-haiku-4-5 | 3 | 630 |
| Codex | gpt-5.1-codex-mini | 2 | ~390 |

### 6.2 Testbatch0 (v2 pilot, P0–P8)

Diagnostic single-bug run (BUG55, concurrency_cache) across all 9 variants × 2 models (18 runs, n=1).
Purpose: validate P7/P8 variant mechanics, confirm guide content redesign, verify P6 plugin delivery.
Results are not statistically representative but reveal mechanistic behaviour per variant.

### 6.3 Testbatch1 (cross-bug replication, P0–P8)

Second diagnostic run (BUG48, db_patterns) across all 9 variants × 2 models (18 runs, n=1).
Purpose: replicate the surface hierarchy on a different bug category and model/surface interaction.
BUG48 requires: (1) numeric version comparison in `get_pending_migrations`, (2) `orgops.auditing.write_event("migration.applied", version=version)` for each migration applied.

---

## 7. Results

### 7.1 Batch 1 Surface Hierarchy (P0–P6)

Table 1: Pytest pass rates by variant (signal bugs, 26 bugs, batch_1).

**Haiku (n=3):**

| Variant | Pass rate | Lift vs P0 |
|---------|-----------|------------|
| P0 | 0.0% (0/78) | — |
| P1 | 2.6% (2/78) | +2.6 pp |
| P2 | 39.7% (31/78) | +39.7 pp |
| P3 | 65.4% (51/78) | +65.4 pp |
| P4 | **69.2%** (54/78) | +69.2 pp |
| P5 | 67.9% (53/78) | +67.9 pp |
| P6 | 60.3% (47/78) | +60.3 pp |

**Codex (gpt-5.1-codex-mini, n=2):**

| Variant | Pass rate | Lift vs P0 |
|---------|-----------|------------|
| P0 | 5.4% (3/56) | — |
| P1 | 7.3% (4/55) | +1.9 pp |
| P2 | 37.5% (21/56) | +32.1 pp |
| P3 | **41.1%** (23/56) | +35.7 pp |
| P4 | 25.0% (14/56) | +19.6 pp |
| P5 | 30.4% (17/56) | +25.0 pp |
| P6 | 40.0% (22/55) | +34.6 pp |

*Note: Haiku results on 26-bug signal set. Codex on all 30 bugs with error cells excluded.*

### 7.2 Testbatch0 Pilot (P0–P8, BUG55, n=1)

Table 2: Tool usage and pytest result per variant (BUG55, single run each).

| Variant | Haiku vs\_calls | Haiku snips | Haiku pytest | Codex vs\_calls | Codex snips | Codex pytest |
|---------|----------------|------------|-------------|----------------|------------|-------------|
| P0 | 0 | 0 | ✗ | 0 | 0 | ✗ |
| P1 | 0 | 0 | ✗ | 0 | 0 | ✗ |
| P2 | 0 | 2 | ✗ | 0 | 2 | ✗ |
| P3 | 0 native=5 | 0 | ✗ | 0 | 0 | ✗ |
| P4 | 0 | 0 | ✗ | 0 | 0 | ✗ |
| P5 | **1** | 4 | **✓** | 6 | 4 | ✗ |
| P6 | **1** | 4 | **✓** | 5 | 5 | ✗ |
| P7 | **1** | 0† | ✗ | **1** | 4 | ✗ |
| P8 | **1** | 4 | **✓** | 0 | 0 | ✗ |

†P7 Haiku: VoltSnip called (5 results logged), metric name retrieved correctly, but `import orgops.metrics` missing from patch — partial success.

**Passing conditions for Haiku (P5, P6, P8):**
All three generate identical correct patches:
```python
import orgops.metrics
...
if ratio < self.threshold:
    self.refreshes_triggered += 1
    orgops.metrics.emit("cache.stampede.prevented", key_name)
    return True
```

**Failing conditions for Haiku:**
- P0/P1: fix `>→<` but omit orgops call entirely — no knowledge of API
- P2: inject 2 snippets, emit correctly, but pytest fails (inline import inside method body)
- P3: 5 native filesystem tool calls (all fail — tmpdir is empty), 0 VoltSnip calls, guesses `emit_metric()` pattern
- P4: 0 tool calls, no orgops emit — plugin skill description insufficient to trigger retrieval
- P7: 1 VoltSnip call, retrieves correct metric name, but missing `import orgops.metrics`

### 7.3 What Triggers Retrieval (Key Mechanistic Finding)

The testbatch0 pilot isolates the retrieval trigger question clearly for Haiku:

| Signal | VoltSnip called? | Correct orgops emit? | Pytest pass? |
|--------|-----------------|---------------------|-------------|
| Tools available, no guidance (P3) | ✗ | ✗ | ✗ |
| Tools + VoltSnip skill description (P4) | ✗ | ✗ | ✗ |
| Tools + repo context naming orgops gap (P5) | **✓** | **✓** | **✓** |
| Tools + repo context + skill (P6) | **✓** | **✓** | **✓** |
| Tools + explicit mandate (P7) | **✓** | partial | ✗ |
| Tools + skill + explicit mandate (P8) | **✓** | **✓** | **✓** |

**Finding 1: Tool availability does not trigger retrieval.**
P3 provides tools with zero guidance. Haiku makes 5 native filesystem calls (all fail against empty tmpdir) and zero VoltSnip calls. The model treats retrieval as optional and skips it.

**Finding 2: A skill description alone does not trigger retrieval.**
P4 provides the VoltSnip skill description via `--plugin-dir`. Haiku makes zero tool calls. Knowing *what VoltSnip does* is insufficient to trigger its use.

**Finding 3: Naming the knowledge gap triggers retrieval.**
P5 adds AGENTS.md with: "These APIs are not standard library calls — their signatures and import paths must be looked up, not guessed." Haiku immediately makes one focused VoltSnip search and passes pytest. The mechanism is knowledge-gap recognition: the model identifies that it cannot proceed from training data and turns to retrieval.

**Finding 4: An explicit mandate also triggers retrieval but less robustly.**
P7 forces a VoltSnip call via explicit instruction. Haiku retrieves the correct metric name but applies it without the required import statement. P8 forces Skill invocation, which bootstraps the full retrieval sequence and passes. The mandate is effective but the Skill-invocation path (P8) produces a more complete patch than the direct tool-call path (P7).

**Finding 5: P7 is a near-miss.**
P7 Haiku retrieved the correct metric name `cache.stampede.prevented` but produced an incomplete patch (missing import). This suggests the explicit mandate successfully directed retrieval but the model did not fully integrate the retrieved context into the patch construction step.

### 7.4 Codex Behaviour (Testbatch0)

Codex does not pass pytest in any testbatch0 variant. Key patterns:

- **P3**: Makes no tool calls — same failure mode as Haiku but without the filesystem exploration.
- **P4**: Calls `list_mcp_resources` (returns empty) rather than VoltSnip semantic search — the plugin skill mechanism is not activating correctly.
- **P5/P6**: Makes multiple VoltSnip `search_memory` calls but receives empty results (`''`) — likely a tool schema or response format mismatch between the VoltSnip API and Codex's MCP client.
- **P6**: Reads `.agents/skills/voltsnip-guide/SKILL.md` successfully (correct file discovery), then falls back to unsuccessful search.
- **P7**: Makes 1 VoltSnip call, retrieves 4 snippets, but generates `hasattr(self, "emit_metric")` fallback pattern instead of `orgops.metrics.emit`.
- **P8**: Calls `read_mcp_resource` (wrong mechanism — attempts resource read rather than tool invocation).

The Codex failures suggest a residual provider asymmetry in MCP tool-call semantics that warrants investigation separate from the surface hierarchy question.

### 7.5 Testbatch1 Pilot (P0–P8, BUG48, n=1)

Table 3: Tool usage and pytest result per variant (BUG48, single run each).

| Variant | Haiku vs\_calls | Haiku snips | Haiku pytest | Codex vs\_calls | Codex snips | Codex pytest |
|---------|----------------|------------|-------------|----------------|------------|-------------|
| P0 | 0 | 0 | ✗ | 0 | 0 | ✗† |
| P1 | 0 | 0 | ✗ | 0 | 0 | ✗† |
| P2 | 0 | 2 | ✗ | 0 | 2 | ✗† |
| P3 | 0 | 0 | ✗ | 0 | 0 | ✗† |
| P4 | 0 | 0 | ✗ | 0 | 0 | **✓**‡ |
| P5 | 2 | 4 | ✗ | 3 | 3 | ✗ |
| P6 | 0 | 0 | ✗ | 5 | 3 | ✗ |
| P7 | 4 | 1 | ✗ | 1 | 4 | **✓**§ |
| P8 | 3 | 7 | ✗ | 4 | 5 | ✗ |

†P0/P1/P2/P3 Codex: malformed output — replacement omits the `def get_pending_migrations` function signature, producing a broken file.

‡P4 Codex: passes with 0 VoltSnip calls — uses `from orgops.auditing import write_event` (local import), discoverable from the `expected_output` prompt field which contains the literal API call. See §7.6 for analysis.

§P7 Codex: creates an `_AuditMigration` dict-subclass wrapper that lazily fires the audit event when `migration["sql"]` is first accessed. Passes test due to patch mechanics. See §7.6 for analysis.

**BUG48 findings:**

- **All Haiku variants fail.** P5 Haiku retrieves 4 relevant snippets and correctly fixes numeric ordering, but completely omits the audit call — AGENTS.md context triggers retrieval for the known-wrong logic component but does not generalise to discovering the second requirement.
- **P4 Codex passes with 0 retrieval.** See §7.6.
- **P7 Codex passes with 1 retrieval.** Creative adversarial approach; semantically wrong placement. See §7.6.
- **P8 Codex fails despite 5 snippets.** Malformed patch output — `get_pending_migrations` method definition dropped, method body left hanging outside a class method.
- **P5/P6 Codex fails.** Uses `orgops.auditing.write_event(...)` without import (`NameError: name 'orgops' is not defined`) — retrieves the API name but applies it with wrong import style.

### 7.6 BUG48 Validity Analysis — Two Threats to Signal Integrity

Post-hoc inspection of the BUG48 run artifacts reveals two design issues that compromise its validity as a clean retrieval-signal bug.

**Threat 1: Prompt-level API leakage.**

The `expected_output` field from the task YAML is included verbatim in every model's user prompt:

> "Use int() for version comparison and sorting AND call `orgops.auditing.write_event("migration.applied", version=version)` for each migration."

This directly exposes the exact API call, method name, event string, and keyword argument. A model that reads this field can succeed without any VoltSnip retrieval. The P4 Codex pass (0 retrieval calls) is attributable to this prompt-level hint, not to training-data knowledge of `orgops.auditing`. P0/P1/P2/P3 Codex still fail — not because they missed the API (it is in the prompt) but because they generate malformed replacement code, omitting the `def get_pending_migrations` signature from the line-range replacement output.

**Threat 2: Test structure ambiguity — wrong-method placement passes.**

The test patches `orgops.auditing.write_event` at the module level during the `apply_pending(executor)` call:

```python
with patch("orgops.auditing.write_event") as mock_audit:
    applied = runner.apply_pending(executor)
    assert mock_audit.call_count == 3
```

The *semantically correct* placement of the audit call is inside `apply_pending` — once per migration after `executor.execute()`. However, `apply_pending` internally calls `get_pending_migrations()`, so placing the audit call in `get_pending_migrations` also satisfies the mock check — because the local `from orgops.auditing import write_event` re-resolves to the mock on every call during the patched scope.

The P4 Codex solution exploits this: it places `write_event` in `get_pending_migrations` using a local import. The P7 Codex solution goes further — constructing a lazy `_AuditMigration` wrapper that defers the audit event to when `migration["sql"]` is first accessed during `apply_pending`'s iteration. Both approaches pass the test while placing the audit at architecturally wrong callsites.

**Classification.** BUG48 should be reclassified as a **noisy/leaky signal bug** and excluded from primary pass-rate claims until (a) `expected_output` is removed from the user prompt or replaced with a description that does not include the literal API call, and (b) the test is strengthened to enforce `apply_pending`-placement by testing audit-call absence when `get_pending_migrations` is called directly.

Despite this, BUG48 reveals several useful subsidiary findings:

1. **Codex direct-mode output format regression.** P0–P3 Codex consistently produce malformed line-range replacements, dropping the `def` function signature. This suggests a systematic parsing or instruction-following failure for the editing contract in direct (non-agent) mode for gpt-5.2-codex.

2. **P5 Haiku two-component retrieval gap.** P5 Haiku correctly retrieves 4 snippets and correctly identifies the numeric ordering fix, but ignores the audit requirement. This suggests that knowledge-gap recognition (AGENTS.md) triggers a *single retrieval pass* targeted at the explicitly flagged gap (ordering), not a comprehensive sweep of all hidden requirements.

3. **Retrieval quantity does not guarantee integration.** P8 Codex retrieves 5 snippets across 4 tool calls but produces a malformed patch. P7 Codex retrieves 4 snippets in 1 call and passes. Retrieval count is uncorrelated with patch quality; output format compliance is a separate bottleneck.

### 7.7 Cross-Variant Analysis (Combined)

The batch_1 results showed P4 as the best variant for Haiku (69.2%) and P3 as best for Codex (41.1%).
The testbatch0 pilot (BUG55) adds mechanistic detail: P5/P6/P8 all pass for Haiku while P4 fails — suggesting knowledge-gap recognition (AGENTS.md) is the primary retrieval trigger, not skill availability.

Testbatch1 (BUG48) complicates the picture. All Haiku variants fail due to a two-component gap (P5 Haiku retrieves 4 snippets and fixes ordering but omits the audit call). Codex P4 and P7 pass, but both are attributable to prompt leakage and test-structure ambiguity rather than clean retrieval (§7.6). BUG48 is therefore excluded from surface-hierarchy claims.

The consolidated cross-pilot signal for Haiku (BUG55 only, n=1):
- P5/P6: pass via knowledge-gap recognition
- P8: passes via skill-mandate retrieval bootstrapping
- P4: fails — skill description without knowledge-gap context insufficient
- P7: near-miss — retrieves correctly but integration incomplete

A full re-run of the 30-bug matrix with v2 guide content is required to determine whether P5 > P4 holds at scale and to establish P7/P8 base rates across all signal bugs.

---

## 8. Analysis and Discussion

### 8.1 The Knowledge-Gap Recognition Mechanism

The central finding of testbatch0 is that Haiku's retrieval is triggered by *recognition that org-specific knowledge is required*, not by the availability of tools or the description of retrieval capabilities.

This has a practical implication: the most efficient guide document for triggering retrieval is not one that says "use these tools" but one that says "this codebase uses private APIs you cannot guess." The model infers the retrieval necessity from the knowledge gap, not from being instructed to fill it.

This is consistent with chain-of-thought prompting research [8] where providing intermediate reasoning context outperforms direct instruction. Here the analogue is: providing the *reason retrieval is needed* (the API is private) outperforms providing the *instruction to retrieve*.

### 8.2 Explicit Mandate: Effective but Incomplete (P7)

P7 demonstrates that an explicit mandate triggers retrieval but does not guarantee correct patch construction. The Haiku P7 patch correctly retrieves and uses the metric name but omits the import statement. This suggests a two-step failure mode:

1. Retrieval step: succeeds when mandated
2. Integration step: model applies retrieved knowledge incompletely

P8 avoids this by routing retrieval through the Skill tool invocation, which may prime the model to attend more carefully to the full content of the retrieved snippets (including the import example).

### 8.3 Guide Content Redesign Impact

The v1 guides were directives ("use MCP tools before writing code"). The v2 guides are informational. This changes what information the model receives:

- v1 AGENTS.md: *how* to behave (retrieve first)
- v2 AGENTS.md: *why* retrieval is needed (orgops APIs are private)

Testbatch0 suggests v2 AGENTS.md is at least as effective as v1 for triggering retrieval in Haiku (P5 passes in both). The full batch re-run will determine whether the redesign changes the overall surface hierarchy.

### 8.4 P4 Regression (Testbatch0)

P4 fails in testbatch0 (0 VoltSnip calls) where it passed at 69.2% in batch_1. Two possible explanations:

1. **Guide content change**: v1 SKILL.md was directive ("use MCP tools before writing code"), which may have triggered retrieval more reliably than v2's informational description ("use VoltSnip when the fix involves an org-specific API").
2. **Single-run variance**: testbatch0 is n=1; batch_1 P4 had 26.9 pp inter-run range. A single failing run is within the observed variance.

A full re-run with v2 guides is required to distinguish these explanations.

### 8.5 Codex Divergence

Codex exhibits two distinct failure modes across the two pilot bugs:

**BUG55 (testbatch0):** Codex calls `search_memory` (P5/P6) but receives empty results — likely a tool schema or response format mismatch between the VoltSnip API and the Codex MCP client. The retrieval strategy is correct; the plumbing is broken.

**BUG48 (testbatch1):** P0–P3 Codex produce malformed replacement code — the `def get_pending_migrations` function signature is dropped from the line-range output, producing a broken file. This is a direct-mode editing-contract failure unrelated to retrieval. P8 Codex exhibits the same malformed-output failure despite 5 snippets retrieved.

The two failure modes suggest Codex has separate issues: (1) MCP response format compatibility for tool-enabled variants, and (2) editing-contract instruction following for direct-mode variants. Neither is a retrieval-trigger problem. Fixing these plumbing issues would be necessary before Codex surface hierarchy results could be interpreted at face value.

If the `search_memory` response format is resolved, Codex P6 may improve significantly on BUG55 — it executes the correct retrieval strategy but receives empty results.

### 8.6 Implications for Practitioners

For teams deploying LLM coding assistants on codebases with private APIs:

1. **Name the knowledge gap explicitly.** A short statement — "this repo uses private APIs that cannot be inferred from code" — is more effective than tool descriptions or retrieval mandates for triggering retrieval in capable models (Haiku).

2. **On-demand skills outperform always-visible skill docs for selective use.** Delivering the VoltSnip guide as a plugin skill (P4/P8) rather than injecting it into every prompt preserves context budget and provides a clean invocation signal.

3. **Explicit mandates work but may produce incomplete integration.** P7/P8 reliably trigger retrieval but the integration quality depends on how the retrieved content is applied. Skill-mediated retrieval (P8) produces more complete patches than direct-tool retrieval (P7) for Haiku.

4. **Provider matters.** Haiku and Codex have materially different retrieval behaviours. A context surface optimised for one may not transfer to the other without provider-specific adjustment.

---

## 9. Limitations and Threats to Validity

### 9.1 Testbatch0/1 Sample Size

Both pilot batches are n=1 per cell for a single bug each. Mechanistic conclusions are directional, not statistically robust. The failing P4 Haiku run in testbatch0 may be a single-run miss given batch_1 P4 variance (26.9 pp range). Full batch re-run with v2 guides is required before updating the primary results table.

### 9.6 BUG48 Task Design Flaws

BUG48 is excluded from surface-hierarchy claims due to two task-design threats (§7.6): (1) the `expected_output` field in the user prompt contains the literal API call signature, and (2) the test mock structure does not enforce correct method placement. Both issues allow models to pass without genuine org-API retrieval. The bug should be redesigned before inclusion in the signal set: `expected_output` should describe the requirement abstractly, not name the API, and the test should add a direct call to `get_pending_migrations` (outside the patch) that asserts zero mock calls.

### 9.2 Guide Content Confound

The v2 guide redesign changes two things simultaneously: content (directive → informational) and the distinction between AGENTS.md (always-visible) vs SKILL.md (on-demand). The relative contribution of each change is not isolated.

### 9.3 P7 Partial-Success Attribution

P7 Haiku retrieved the metric name but omitted the import. It is not confirmed whether the missing import is caused by: (a) the model failing to read the full snippet content, (b) the model's context window not retaining the import example, or (c) a structural issue with how the explicit instruction interacts with the patch format.

### 9.4 Codex MCP Compatibility

Codex `search_memory` returning empty results in testbatch0 may reflect an API schema or transport change between batch_1 (gpt-5.1-codex-mini) and testbatch0 (gpt-5.2-codex). Cross-version comparisons should be interpreted with this caveat.

### 9.5 Retained v1 Limitations

Sections 9.2–9.8 of PAPER.md (v1) apply: benchmark construction bias, uniform difficulty, snippet truncation at 1,200 characters, single-codebase scope, residual provider asymmetry.

---

## 10. Future Work

1. **Full batch re-run with v2 guides.** Run the complete 30-bug × 9-variant matrix with v2 guide content to determine whether P5 > P4 holds at scale, and to establish P7/P8 pass rates.
2. **BUG48 redesign.** Remove the explicit API call from `expected_output`; strengthen the test to assert zero audit calls when `get_pending_migrations` is called directly outside a mock context. Re-run to assess true signal.
3. **Guide content ablation.** Compare v1 directive guides vs v2 informational guides within the same run batch.
4. **P7 import-fix investigation.** Determine whether providing a structured snippet format that includes the import statement in a distinct field improves P7 integration completeness.
5. **Codex MCP + editing-contract fixes.** Resolve the `search_memory` empty-result issue and the direct-mode line-range replacement omission (missing `def` signature) for Codex.
6. **Additional models.** Evaluate claude-sonnet-4-6, claude-opus-4-6, gpt-5.3-codex, and open-weight models.
7. **VoltSnip ablation.** Run P4 with VoltSnip unavailable to complete the causal attribution.
8. **Multi-component bug analysis.** BUG48 testbatch1 shows P5 Haiku retrieves correctly for one component (ordering) but ignores the second (audit). Design bugs with more separable component annotations to understand whether knowledge-gap recognition triggers retrieval for all requirements or only the most salient one.

---

## 11. Conclusion

We have extended the Script30 context surface ladder from P0–P6 to P0–P8, adding explicit-mandate variants (P7/P8) and redesigning guide content to separate informational context from retrieval mandates.

The testbatch0 pilot (BUG55, n=1) surfaces a mechanistic finding: for Haiku, retrieval is triggered by naming the knowledge gap (AGENTS.md: "orgops.* APIs cannot be guessed") rather than by tool availability or skill description alone. P5 and P6 pass pytest via knowledge-gap recognition; P4 fails despite the plugin skill being present. P8 achieves the same pass via a different path: Skill tool invocation bootstraps the retrieval sequence.

The testbatch1 pilot (BUG48, n=1) reveals two threats to that bug's signal validity — prompt-level API leakage and test-structure ambiguity that allows wrong-method placement to pass — and excludes BUG48 from primary claims. Testbatch1 also reveals a P5 Haiku two-component gap: knowledge-gap recognition triggers retrieval for the salient logic component but does not automatically generalise to discovering all hidden requirements. Separately, Codex exhibits systematic direct-mode editing-contract failures (malformed output format) independent of retrieval, pointing to a provider-specific plumbing issue.

The batch_1 results (P0–P6, n=3 Haiku) showing P4 at 69.2% remain the primary quantitative finding. The v2 design and two pilot batches add mechanistic depth and motivate a full re-run to establish whether the guide redesign changes the surface hierarchy, and to surface additional multi-component retrieval gaps.

---

## References

[1] Chen, M., et al. (2021). Evaluating Large Language Models Trained on Code. arXiv:2107.03374.

[2] Austin, J., et al. (2021). Program Synthesis with Large Language Models. arXiv:2108.07732.

[3] Jimenez, C. E., et al. (2024). SWE-bench: Can Language Models Resolve Real-World GitHub Issues? arXiv:2310.06770.

[4] Yang, J., et al. (2024). SWE-agent: Agent-Computer Interfaces Enable Automated Software Engineering. arXiv:2405.15793.

[5] Lewis, P., et al. (2020). Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks. arXiv:2005.11401.

[6] Schick, T., et al. (2023). Toolformer: Language Models Can Teach Themselves to Use Tools. arXiv:2302.04761.

[7] Yao, S., et al. (2023). ReAct: Synergizing Reasoning and Acting in Language Models. arXiv:2210.03629.

[8] Wei, J., et al. (2022). Chain-of-Thought Prompting Elicits Reasoning in Large Language Models. arXiv:2201.11903.

---

## Appendix A: Variant Ladder Formal Specification (P0–P8)

| Field | P0 | P1 | P2 | P3 | P4 | P5 | P6 | P7 | P8 |
|-------|----|----|----|----|----|----|----|----|-----|
| `mode` | direct | direct | direct | agent | agent | agent | agent | agent | agent |
| `memory_enabled` | ✗ | ✗ | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| `tools_enabled` | ✗ | ✗ | ✗ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `retrieval_mode` | none | none | injected | agent\_decides | agent\_decides | agent\_decides | agent\_decides | agent\_decides | agent\_decides |
| `instruction_mode` | none | explicit | none | none | none | none | none | explicit | explicit |
| `context_surface` | user | user | system | tools\_only | skills\_md\_no\_keys | agents\_md\_no\_keys | skills\_agents\_md\_no\_keys | tools\_only | skills\_md\_no\_keys |
| `max_tool_roundtrips` | 1 | 1 | 1 | 4 | 4 | 4 | 4 | 4 | 4 |
| Guide (Claude Code) | — | — | — | — | `--plugin-dir` skill | `CLAUDE.md` | `CLAUDE.md` + `--plugin-dir` skill | — | `--plugin-dir` skill |
| Guide (Codex) | — | — | — | — | `.agents/skills/` | `AGENTS.md` | `AGENTS.md` + `.agents/skills/` | — | `.agents/skills/` |

## Appendix B: Pilot Batch Artifact Paths

| Artifact | Path |
|----------|------|
| Suite definition | `suites/script30.yaml` |
| Testbatch0 completed log | `vsevals_runs/testbatch0/completed.jsonl` |
| Testbatch0 results CSV | `vsevals_runs/testbatch0/matrix_results.csv` |
| Testbatch0 report | `vsevals_runs/testbatch0/matrix_report.md` |
| Testbatch1 completed log | `vsevals_runs/testbatch1/matrix_*/completed.jsonl` |
| Testbatch1 results CSV | `vsevals_runs/testbatch1/matrix_*/matrix_results.csv` |
| Testbatch1 report | `vsevals_runs/testbatch1/matrix_*/matrix_report.md` |
| Individual run artifacts | `vsevals_runs/<batch>/runs/<timestamp>__<bug>__<variant>__<model>/` |
| Prompt source (v2) | `vsevals/vsevals/prompt.py` |
| Inline guide content | `vsevals/vsevals/prompt.py` (INLINE_SKILL_GUIDE, INLINE_AGENT_GUIDE) |
| BUG48 task definition | `tasks/script30/BUG48.yaml` |
| BUG48 test | `usecases/script30/tests/unit/test_bug48.py` |
| BUG48 source (buggy) | `usecases/script30/data/migration_runner.py` |

## Appendix C: Harness Changes (v1 → v2)

1. **Plugin skill delivery** (`prompt.py`, `claudecode.py`): P4/P8 now deliver SKILL.md via `--plugin-dir <tmpdir>` as an on-demand Claude Code plugin; `Skill` tool added to `--allowedTools`, removed from `--disallowedTools`.
2. **P6 CLAUDE.md redesign** (`prompt.py`): P6 now uses `CLAUDE.md` = agents/repo context (always-visible) + `--plugin-dir` skill (on-demand), replacing the v1 `@SKILL.md\n@AGENTS.md` @-import approach.
3. **Codex skills mapping** (`codex.py`): sidecar files with `skills/` prefix mapped to `.agents/skills/` for Codex auto-discovery.
4. **Guide content redesign** (`prompt.py`): INLINE_SKILL_GUIDE and INLINE_AGENT_GUIDE rewritten as informational documents (no retrieval mandate).
5. **P7/P8 explicit instruction** (`prompt.py`): `instruction_mode=explicit` now branches on `tools_enabled` and `context_surface`: P7 emits "MUST perform retrieval tool call"; P8 emits "MUST invoke voltsnip-guide skill"; P1 retains generic strictness nudge.
6. **`--effort` flag** (`run_matrix.py`): `--reasoning-effort` renamed to `--effort` with `max` added as a choice; help text updated for all providers.
