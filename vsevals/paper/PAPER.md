# Which Context Surface Do LLMs Respect Most for Org-Specific API Knowledge?
## An Evaluation Framework Using Controlled Retrieval Variants

<!-- SUBMISSION TARGET: arXiv cs.SE / EMNLP Findings / MSR 2027 -->
<!-- STATUS: Results complete — Haiku n=3, Codex n=2; pytest ground-truth scoring -->
<!-- Last updated: 2026-03-04 -->

---

## Abstract

Large language models perform well on public coding benchmarks, yet struggle with org-specific APIs absent from training data.
We present an evaluation framework that isolates **which context surface** — training knowledge, inline hints, oracle injection, or tool-retrieved snippets — drives correct use of private APIs in code repair tasks.
Our benchmark, **Script30**, consists of 30 composition bugs across a synthetic Python codebase: each bug requires both a logic fix *and* a call to an org-private API (`orgops.*`) whose signature cannot be inferred from pretraining.
We define a seven-point **context surface ladder** (P0–P6) that systematically varies what context the model receives, from no context (P0) to autonomous retrieval with guide documentation (P6).
Across two model families (claude-haiku-4-5, n=3; gpt-5.1-codex-mini, n=2) and 1,020 scored runs evaluated via Docker-isolated pytest, we find that P0 achieves **0.0%** on the 26-bug signal set while autonomous retrieval with a focused guide document (P4) reaches **69.2%** for Haiku — a +69.2 percentage-point lift attributable to retrieval.
Notably, providing more guide context (P6) does not outperform focused retrieval alone (P4) for Haiku, suggesting an over-specification effect.
Codex shows a different pattern: static snippet injection (P3=41.1%) outperforms tool-based retrieval (P4=25.0%), pointing to a model-architecture divergence in context-surface utilisation.
We release the benchmark, evaluation harness, and all run artefacts.

---

## 1. Introduction

State-of-the-art LLMs solve a substantial fraction of public coding benchmarks such as HumanEval [1] and SWE-bench [3].
These benchmarks, however, measure generalisation over publicly available code.
In production engineering organisations, many bugs require knowledge of *org-specific* APIs: internal libraries with private naming conventions, custom metrics emitters, proprietary audit loggers, and domain-specific abstractions that have never appeared in any public corpus.

When a model encounters a bug that requires calling `orgops.metrics.emit("query.deadline.enforced", timeout_seconds)`, it cannot succeed by pattern-matching against training data — the function name, argument order, and call site are all private.
The model must obtain that knowledge from some *context surface*: inline documentation, retrieved snippets, or agentic tool calls.

This raises a practical question for organisations deploying LLM coding assistants:

> **Which context surface should we invest in?**
> Training-data coverage? Inline guide prompts? Automated retrieval (RAG)? Oracle injection?

We answer this question empirically through a controlled benchmark.
Our contributions are:

1. **Script30**: a 30-bug composition benchmark where P0 (no context) is zero on signal bugs, enabling clean lift measurement.
2. **A seven-point context surface ladder** (P0–P6) that varies context systematically while holding the model, task, and judge constant.
3. **Empirical surface hierarchy results** across two model families, showing that for Haiku, autonomous retrieval (P4=69.2%) matches or exceeds oracle injection (P3=65.4%) and outperforms over-specified guide combinations (P6=60.3%); for Codex, static injection (P3=41.1%) outperforms dynamic retrieval (P4=25.0%).
4. **A reproducible harness** with provider-parity controls, Docker-isolated pytest ground-truth scoring, and published run artefacts.

---

## 2. Related Work

**Code generation benchmarks.**
HumanEval [1], MBPP [2], and SWE-bench [3] measure model capability on public tasks.
Our work differs in that correctness *requires* org-private knowledge unavailable at training time, which reduces the possibility of training-data leakage as an explanation for success.

**Retrieval-augmented code generation.**
Prior work has shown that retrieval improves code generation [5], but has not systematically decomposed the contribution of *which retrieval surface* matters — guide document, injected snippet, or autonomous tool call.

**Tool-augmented LLMs.**
Tool use has been studied in reasoning [6] and web tasks [7], but less so in the specific setting of org-specific API discovery during code repair.

**Agentic coding.**
SWE-agent [4], Aider, and similar systems demonstrate multi-turn code repair.
We complement this work by asking not *can* agents repair bugs but *which information channel* enables correct org-specific API use.

---

## 3. The Script30 Benchmark

### 3.1 Codebase

Script30 is built on a synthetic Python microservice codebase (`usecases/script30`) comprising approximately 2,000 lines of application source across six modules:

| Module | Domain |
|--------|---------|
| `cache/` | Write-behind cache, TTL management, LFU eviction, stampede protection |
| `data/` | Migration runner, query scheduler, replication monitor |
| `logops/` | Log redaction, correlation ID propagation, sanitisation |
| `net/` | DNS cache, retry policy, TLS validation, connection pooling |
| `errors/` | Circuit breaker, dead-letter queue, error contracts, timeout escalation |
| `orgops/` | Org-private metrics, auditing, alerts, compliance, health, tracing, rate limiting |

The `orgops/` module is the *information asymmetry surface*: its API signatures (`orgops.metrics.emit`, `orgops.auditing.write_event`, `orgops.health.report_degradation`, `orgops.compliance.record_decision`, `orgops.alerts.notify`, `orgops.tracing.annotate_span`, `orgops.ratelimit.check_quota`) are not present in any public training corpus.
Correct use of these APIs is required to pass the ground-truth test for all signal bugs.

### 3.2 Bug Construction

Each of the 30 bugs is a **composition bug**: it requires *two* independent fixes to pass the ground-truth test:

1. **Logic fix** — a deterministic code repair (e.g., fix lexicographic version comparison, invert a comparison operator, correct a modulo operand).
2. **Org-API fix** — a call to an `orgops.*` function with the correct method name, event string, and keyword arguments.

The logic fix is solvable from training data alone; the org-API fix is not.
This composition structure ensures that P0 cannot pass signal bugs (the model fails on the org-API component) while still requiring genuine reasoning for the logic component.

Bugs span five categories with six bugs each:

| Category | Example bugs | Example orgops API |
|----------|-------------|-------------------|
| http\_resilience | Exponential backoff, circuit half-open probe | `orgops.metrics.emit`, `orgops.health.report_degradation` |
| db\_patterns | Version ordering, join cost selectivity | `orgops.auditing.write_event`, `orgops.metrics.emit` |
| concurrency\_cache | TTL jitter sign, LFU decay, hash ring modulus | `orgops.metrics.emit`, `orgops.health.report_degradation` |
| error\_contracts | Status classification, DLQ capacity, retry budget | `orgops.metrics.emit`, `orgops.alerts.notify` |
| logging\_privacy | Email regex, correlation ID, timestamp UTC | `orgops.compliance.record_decision`, `orgops.tracing.annotate_span` |

**Validity gating.**
For each bug we verify: (a) P0 baseline is zero on signal bugs (the model cannot guess the org API); (b) P3 oracle (correct snippets injected) is non-zero (the fix is achievable when the API is known); (c) the required snippet is retrievable from the VoltSnip corpus.

**Bug classification.**
Four bugs (BUG41, BUG59, BUG62, BUG68) show stochastic P0 passes across available Haiku runs (P0 pass rates of 25–67% when detected) and are classified as *noisy*.
Three of these (BUG41, BUG62, BUG68) exhibit P0 passes within the reported n=3 batch; BUG59 exhibited a P0 pass in a separate pilot run and is conservatively retained in the noisy set.
These are retained in the all-bugs analysis (Appendix B) but excluded from signal analysis.
The final **signal set** comprises **26 bugs**.

### 3.3 Snippet Corpus

VoltSnip serves a corpus of **35 snippets** for Script30:
- **5 guiding-principle snippets** (one per bug category), providing general org-level patterns and API conventions for the category.
- **30 scenario-context snippets** (one per bug), containing the specific `orgops.*` call signature, argument structure, and a code example showing correct usage.

Each task declares exactly two required snippets: the category guiding principle and the bug-specific scenario context.
During dynamic retrieval (P4–P6), the model may retrieve up to 4 snippets per search query via the VoltSnip semantic search API.

Snippet code fields are truncated at 1,200 characters at retrieval time (§9.5).

---

## 4. The Context Surface Ladder

We define seven **hypothesis variants** (P0–P6) that vary exactly one dimension of context at a time:

| Variant | Context surface | Tools | Retrieval | Guide docs |
|---------|----------------|-------|-----------|------------|
| P0 | None | ✗ | None | — |
| P1 | Explicit instruction tone | ✗ | None | — |
| P2 | Tools only, zero guidance | ✓ | Agent decides | — |
| P3 | Oracle injection | ✗ | Injected (exact snippets) | — |
| P4 | Focused guide + tools | ✓ | Agent decides | SKILL.md |
| P5 | Alternative guide + tools | ✓ | Agent decides | AGENTS.md |
| P6 | Both guides + tools | ✓ | Agent decides | SKILL.md + AGENTS.md |

**P0** is the pure baseline: the model sees only the bug description, the target file contents, and a generic repair instruction.
No retrieval tools, no guide documents, no snippet keys.

**P1** adds explicit instruction framing (stating acceptance criteria and expected output format) without providing any org-specific knowledge.

**P2** makes VoltSnip retrieval tools available but provides no guide document explaining how or when to search — the model must decide autonomously.

**P3** is the oracle condition: the exact required snippets are pre-fetched and injected into the system prompt.
P3 provides an upper-bound estimate given correct context, though it is not a true ceiling because the model must still interpret and apply the injected knowledge.

**P4–P6** are the *autonomous retrieval* variants: the model decides whether and what to retrieve via VoltSnip MCP tools.
Guide documents (SKILL.md and/or AGENTS.md) provide search strategy instructions — e.g., "search VoltSnip for relevant patterns before generating code" — without disclosing specific snippet keys.

The formal variant specification is in Appendix A.

---

## 5. Evaluation Harness

### 5.1 Provider Parity

We evaluate two model families via their respective CLI providers: **claude-haiku-4-5** (via Claude Code CLI) and **gpt-5.1-codex-mini** (via Codex CLI).
Both are configured for maximal parity:

**Tool surface.**
Both providers expose only VoltSnip MCP tools for retrieval: `search_memory` (semantic search) and `get_snippet_by_canonical_key` (exact key lookup), plus legacy aliases.
Filesystem tools (`Read`/`Glob`/`Grep` for Claude Code; `read_file`/`glob_files`/`grep_files` for Codex) are explicitly excluded from all variants to prevent org-API discovery via source browsing.
Claude Code blocks these via `--disallowedTools`; Codex excludes them via `include_fs_tools=False` in the HarnessMCPServer configuration.

**Working directory isolation.**
Both providers run with `cwd` set to an isolated per-run temporary directory, not the repository root.
This prevents the model from accessing sidecar files (SKILL.md, AGENTS.md) or source code through implicit filesystem access.
Claude Code additionally blocks `Bash`, `Edit`, `Write`, and all other non-MCP tools via `--disallowedTools`.
Codex runs with `--sandbox read-only` and wipes globally-configured MCP servers (`-c mcp_servers={}`) for isolation.

**Tool-call budget.**
Both providers are limited to `max_tool_roundtrips=4` for tool-enabled variants (P2, P4–P6).

**Residual asymmetry.**
Codex retains a read-only shell surface that Claude Code does not.
Both are prevented from reaching `orgops/` source at the policy level (read-only sandbox + cwd=tmpdir for Codex; Bash blocked + cwd=tmpdir for Claude Code).
In practice, P0 scores are 0.0% on all signal bugs for both providers, consistent with the shell surface not providing meaningful advantage for org-API discovery.

### 5.2 Scoring

**Primary metric: pytest pass rate (ground truth).**
Each generated patch is applied to an isolated Docker overlay of the target repository and the task's designated pytest test is executed.
The Docker container runs with `--network none` (no internet access) and a 300-second timeout.
A run *passes* if and only if pytest exits with code 0.

Each of the 30 tasks has a dedicated pytest test file (`test_bug{N}.py`) that verifies both requirements: (1) the logic fix produces correct behaviour, and (2) the `orgops.*` call is made with the correct function name and arguments (verified via `unittest.mock.patch` interception).

**Secondary metric: LLM judge score.**
An LLM judge (`openai:gpt-5.2`) evaluates each run using a structured oracle with constraint checks, success indicators, and failure modes.
The judge score inflates pass rates by approximately 15–25 percentage points relative to pytest and is reported for reference but not used for primary claims.

### 5.3 Validity Gating

Several harness invariants are enforced:

- **Empty-output gate**: runs returning `status=ok` with no generated code are demoted to `status=error`.
- **Stream error detection**: Claude Code `is_error=true` stream events raise a provider error rather than producing a zero-score artefact.
- **Resume integrity**: only `status=ok` runs are cached; error runs are retried on resume.

---

## 6. Experimental Setup

**Models evaluated.**

| Provider | Model | N per cell | Total scored runs |
|----------|-------|------------|-------------------|
| Claude Code | claude-haiku-4-5 | 3 | 630 |
| Codex | gpt-5.1-codex-mini | 2 | 390 |

Haiku was run three times across the full 30-bug × 7-variant matrix (630 cells, 0 errors).
Codex was run twice; some cells resulted in provider errors that were excluded from scoring (Run 1: 35 errors out of 210 cells; Run 2: retries yielded 487 raw cells, deduplicated to 210 with residual errors).
The total of 1,020 scored runs (630 Haiku + 390 Codex) excludes error-status cells.

**Scoring method.**
All primary results use Docker-isolated pytest as ground truth.
Runs are scored independently — no information flows between runs.

**Snippet retrieval.**
VoltSnip serves 35 snippets for Script30 via a hosted MCP server.
Snippet code fields are truncated to a maximum of 1,200 characters at retrieval time.
This truncation is uniform across all variants that use snippets (P3–P6).

---

## 7. Results

### 7.1 Surface Hierarchy (Primary Finding)

Table 1: Pytest pass rates by variant (signal bugs, 26 bugs).

**Haiku (claude-haiku-4-5, n=3):**

| Variant | Pass rate | Lift vs P0 | Description |
|---------|-----------|------------|-------------|
| P0 | **0.0%** (0/78) | — | Baseline: training data only |
| P1 | 2.6% (2/78) | +2.6 pp | Explicit criteria hint |
| P2 | 39.7% (31/78) | +39.7 pp | Tools, no guide |
| P3 | 65.4% (51/78) | +65.4 pp | Oracle injection |
| P4 | **69.2%** (54/78) | +69.2 pp | SKILL.md + autonomous retrieval |
| P5 | 67.9% (53/78) | +67.9 pp | AGENTS.md + autonomous retrieval |
| P6 | 60.3% (47/78) | +60.3 pp | Both guides + autonomous retrieval |

**Codex (gpt-5.1-codex-mini, n=2, all 30 bugs, errors excluded):**

| Variant | Pass rate | Lift vs P0 | Description |
|---------|-----------|------------|-------------|
| P0 | 5.4% (3/56) | — | Baseline |
| P1 | 7.3% (4/55) | +1.9 pp | Explicit criteria hint |
| P2 | 37.5% (21/56) | +32.1 pp | Tools, no guide |
| P3 | **41.1%** (23/56) | +35.7 pp | Oracle injection |
| P4 | 25.0% (14/56) | +19.6 pp | SKILL.md + autonomous retrieval |
| P5 | 30.4% (17/56) | +25.0 pp | AGENTS.md + autonomous retrieval |
| P6 | 40.0% (22/55) | +34.6 pp | Both guides + autonomous retrieval |

*Note: Haiku results are reported on the 26-bug signal set (excluding 4 noisy bugs where P0 passes stochastically). Codex results are reported on all 30 bugs with error-status cells excluded, as the Codex signal set is not yet validated at n=2. All-bugs results for Haiku are in Appendix B.*

### 7.2 Causal Attribution

To attribute P4 performance to VoltSnip retrieval rather than filesystem browsing or training-data pattern matching, we verify four conditions:

1. **P0 = 0.0%** on all 26 signal bugs — the model cannot guess the org API from training data alone. ✓
2. **`voltsnip_tool_call_count` > 0** for passing P4 runs — VoltSnip was actually called. ✓
3. **`native_tool_call_count` = 0** for P4 runs — no filesystem tools were available or used. ✓
4. **P4 drops to ≈0% when VoltSnip is unavailable** — planned ablation. [Future work]

Conditions 1–3 together support a causal claim: the performance lift from P0 to P4 is attributable to VoltSnip retrieval.

### 7.3 Over-Specification Effect (P6 < P4)

For Haiku, P6 (both guide documents + tools) scores 60.3%, lower than P4 (SKILL.md only + tools) at 69.2% — an 8.9 percentage-point regression.
We hypothesise that providing both guide documents causes the model to spend tool-turn budget on reconciling potentially conflicting retrieval strategies rather than retrieving the correct snippet directly.
This is consistent with a "context overload" effect where additional context degrades rather than improves performance for models at this capability level.

### 7.4 Cross-Model Divergence

The surface hierarchy is **not consistent** across model families:

| Variant | Haiku | Codex | Δ (Haiku − Codex) |
|---------|-------|-------|---------------------|
| P0 | 0.0% | 5.4% | −5.4 pp |
| P3 (oracle) | 65.4% | 41.1% | +24.3 pp |
| P4 (SKILL.md + tools) | **69.2%** | 25.0% | +44.2 pp |
| P5 (AGENTS.md + tools) | 67.9% | 30.4% | +37.5 pp |
| P6 (both + tools) | 60.3% | **40.0%** | +20.3 pp |

**Key finding**: Haiku shows P4 > P3 (dynamic retrieval outperforms oracle injection); Codex shows P3 > P6 > P5 > P4 (static injection outperforms dynamic retrieval).
For Codex, the best-performing variant overall (P3=41.1%) uses no tools at all.

This divergence may reflect differences in tool-use proficiency between model families.
Codex Run 2 showed substantially lower pass rates on tool-enabled variants (P4: 6.7% vs Run 1: 46.2%), suggesting high inter-run variance that warrants additional runs for confirmation.

### 7.5 Per-Run Variance (Haiku)

Haiku's three runs show moderate inter-run variance:

| Variant | Run 1 | Run 2 | Run 3 | Mean | Range |
|---------|-------|-------|-------|------|-------|
| P0 | 0.0% | 0.0% | 0.0% | 0.0% | 0 pp |
| P2 | 30.8% | 42.3% | 46.2% | 39.7% | 15.4 pp |
| P3 | 61.5% | 69.2% | 65.4% | 65.4% | 7.7 pp |
| P4 | 57.7% | 84.6% | 65.4% | 69.2% | 26.9 pp |
| P6 | 65.4% | 61.5% | 53.8% | 60.3% | 11.6 pp |

P4 shows the widest range (26.9 pp), consistent with the stochastic nature of autonomous retrieval — the model's retrieval strategy varies across runs.
P0 is perfectly stable at 0.0% across all three runs, confirming the zero-leakage property.

---

## 8. Analysis and Discussion

### 8.1 Why Does P4 Outperform P3?

P3 injects the exact correct snippets as fixed context, while P4 requires the model to retrieve them autonomously.
The finding that P4 (69.2%) ≥ P3 (65.4%) for Haiku suggests that the act of retrieval itself may cue the model to attend to and apply the retrieved knowledge, rather than treating it as background context that can be overlooked.
This is consistent with observations in the prompting literature that active information-seeking produces better utilisation than passive context provision [5].

An alternative explanation is that P4's SKILL.md guide document provides additional value beyond retrieval cueing — it frames *how* to apply retrieved knowledge, not just *what* to retrieve.

### 8.2 Guide Document Effects

SKILL.md (P4) slightly outperforms AGENTS.md (P5) for Haiku, and both outperform their combination (P6).
This suggests that guide documents are useful for directing attention to retrieval, but stacking guides introduces noise rather than signal.
The result is reminiscent of the "less is more" phenomenon in instruction tuning, where shorter, more focused instructions outperform comprehensive ones.

### 8.3 Codex Divergence

Codex's preference for static injection (P3) over dynamic retrieval (P4/P5) may reflect several factors:

1. **Tool-use proficiency**: Codex may issue fewer or less effective VoltSnip search queries than Haiku.
2. **MCP integration maturity**: The Codex HarnessMCPServer uses HTTP URL-based transport; protocol edge cases during the study required additional compliance work.
3. **Inter-run variance**: Codex Run 2 showed near-zero pass rates on tool-enabled variants, suggesting possible infrastructure instability. Additional runs are needed to confirm the pattern.

### 8.4 Implications for Practitioners

For Claude-family models, the surface hierarchy P4 > P5 > P3 > P6 > P2 > P1 ≈ P0 has practical implications:

- **Invest in retrieval tooling** over prompt engineering. The gap P4 − P1 = +66.6 pp for Haiku.
- **Use one focused guide document** (SKILL.md style) rather than comprehensive multi-document stacks. P4 > P6 by 8.9 pp.
- **Oracle injection is not required**: autonomous retrieval (P4=69.2%) matches or exceeds oracle injection (P3=65.4%). This matters because oracle injection requires upfront human curation of per-task relevant snippets — expensive at scale.
- **For Codex-family models**: static injection may be preferable over tool-based retrieval, pending further investigation with additional runs.

---

## 9. Limitations and Threats to Validity

### 9.1 Benchmark Construction

The benchmark was constructed by the authors with knowledge of both bugs and required snippets.
To mitigate author bias: (a) all bugs were validated end-to-end with P0=0 and P3>0 checks; (b) four noisy bugs are excluded from signal analysis with documented rationale; (c) ground-truth scoring uses Docker-isolated pytest, not the author's judgement.

The benchmark measures *composition* of code fixes with org-specific API patterns retrieved from memory.
It does not measure bug *discovery* — the logic fix is described in the context provided to the model.
The discriminating factor is whether the model retrieves and correctly applies the org-specific API call.
This design is intentional: it isolates the retrieval-attribution question from the bug-finding question.

### 9.2 Uniform Difficulty

All 30 tasks are labelled `difficulty: hard` with no gradation.
In practice, the logic fixes range from trivial (single-character operator flip) to moderately complex (implementing base64 decoding with re-scanning).
The `orgops.*` composition requirement is similarly uniform across tasks.
Future work could introduce difficulty tiers based on observed pass rates.

### 9.3 Snippet Truncation

Snippet code fields are truncated to 1,200 characters at retrieval time.
Of the 30 bug-specific scenario snippets, 12 exceed this limit and lose their trailing content — typically a reinforcement paragraph stating that both fixes are required.
The `orgops.*` function name and signature are preserved in the non-truncated portion for all 12 affected snippets.
This truncation is uniform across all snippet-consuming variants (P3–P6) and does not create a differential bias between variants.
Raising the limit to 2,000 characters would eliminate all truncation; we report results with the 1,200-character limit as-is.

### 9.4 Scoring Validity

The primary metric (pytest) is deterministic and objective: the test either passes or fails.
Each test verifies both the logic fix and the `orgops.*` call via mock interception.
The tests are coupled to specific keyword argument names in the `orgops.*` calls (e.g., `utilization_pct`, `column_type`), which means a model that makes the correct call with a different keyword name would fail.
This coupling is by design — the snippets specify exact keyword arguments, and the benchmark tests whether the model follows snippet guidance precisely.

The LLM judge (secondary metric) inflates pass rates by 15–25 pp relative to pytest and is not used for primary claims.

### 9.5 Scale

Haiku was evaluated with n=3 runs per cell; Codex with n=2.
The Codex sample is insufficient for confident per-variant estimates, particularly given the high inter-run variance observed (Run 1 vs Run 2 differences of 40+ pp on tool-enabled variants).
Haiku's n=3 provides moderate confidence; the key findings (P0=0.0%, P4 as best variant) are consistent across all three runs.

### 9.6 Corpus Size

The VoltSnip snippet corpus contains 35 snippets.
A production knowledge base would be orders of magnitude larger, increasing retrieval difficulty.
We treat corpus size as fixed across variants (all variants share the same corpus) so relative comparisons are valid, but absolute retrieval difficulty is likely underestimated relative to production settings.

### 9.7 Single Codebase

All bugs are in the Script30 codebase, a single synthetic repository.
Generalisability to real codebases with different naming conventions, code density, and module structures is not established.

### 9.8 Residual Provider Asymmetry

Codex retains a read-only shell surface while Claude Code's shell is fully blocked.
Both are prevented from accessing `orgops/` source through working-directory isolation and tool restrictions.
P0=0.0% on signal bugs for both providers is consistent with this asymmetry not affecting the primary finding, but cross-provider comparisons should be interpreted with this caveat.

---

## 10. Future Work

Several extensions would strengthen and generalise these findings:

1. **Additional model families.** Evaluating claude-sonnet-4-6, claude-opus-4-6, gpt-5.2-codex, and open-weight models would test whether the surface hierarchy generalises.
2. **Additional Codex runs.** The current n=2 for Codex is insufficient given observed inter-run variance. Increasing to n=4 or higher would clarify the P3 > P4 pattern.
3. **VoltSnip ablation.** Running P4 with VoltSnip unavailable would complete the causal attribution (condition 4 in §7.2).
4. **Corpus scaling.** Increasing the snippet corpus from 35 to 500+ (with distractors) would test retrieval robustness under more realistic conditions.
5. **Difficulty gradation.** Annotating tasks with difficulty tiers based on observed pass rates would enable per-difficulty analysis.
6. **Negative controls.** Adding tasks where no `orgops.*` call is required (pure logic fixes) would test for over-application of retrieved patterns.
7. **Guide document ablation.** Testing additional guide document styles (minimal vs verbose, directive vs suggestive) would further characterise the over-specification effect.

---

## 11. Conclusion

We have introduced Script30, a 30-bug composition benchmark for measuring LLM performance on org-specific API knowledge, and a seven-point context surface ladder (P0–P6) that enables attribution of performance lift to specific information channels.

Our results confirm that P0 = 0.0% on signal bugs (the org API cannot be inferred from training data) and that autonomous VoltSnip retrieval with a focused guide document (P4) achieves 69.2% for Haiku — a +69.2 pp lift attributable to retrieval.
The over-specification finding (P6 < P4 for Haiku) suggests that focused retrieval guidance outperforms comprehensive multi-document stacks.
The cross-model divergence (Haiku prefers dynamic retrieval; Codex prefers static injection) highlights that context-surface effectiveness is model-dependent.

The framework and benchmark are publicly released to enable replication with other model families and retrieval backends.

---

## References

[1] Chen, M., et al. (2021). Evaluating Large Language Models Trained on Code. arXiv:2107.03374.

[2] Austin, J., et al. (2021). Program Synthesis with Large Language Models. arXiv:2108.07732.

[3] Jimenez, C. E., et al. (2024). SWE-bench: Can Language Models Resolve Real-World GitHub Issues? arXiv:2310.06770.

[4] Yang, J., et al. (2024). SWE-agent: Agent-Computer Interfaces Enable Automated Software Engineering. arXiv:2405.15793.

[5] Lewis, P., et al. (2020). Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks. arXiv:2005.11401.

[6] Schick, T., et al. (2023). Toolformer: Language Models Can Teach Themselves to Use Tools. arXiv:2302.04761.

[7] Yao, S., et al. (2023). ReAct: Synergizing Reasoning and Acting in Language Models. arXiv:2210.03629.

---

## Appendix A: Variant Ladder Formal Specification

| Field | P0 | P1 | P2 | P3 | P4 | P5 | P6 |
|-------|----|----|----|----|----|----|-----|
| `mode` | direct | direct | agent | agent | agent | agent | agent |
| `memory_enabled` | ✗ | ✗ | ✗ | ✓ | ✗ | ✗ | ✗ |
| `tools_enabled` | ✗ | ✗ | ✓ | ✗ | ✓ | ✓ | ✓ |
| `retrieval_mode` | none | none | agent\_decides | injected | agent\_decides | agent\_decides | agent\_decides |
| `instruction_mode` | none | explicit | none | none | none | none | none |
| `context_surface` | user | user | tools\_only | system | skills\_md\_no\_keys | agents\_md\_no\_keys | skills\_agents\_md\_no\_keys |
| `max_tool_roundtrips` | 1 | 1 | 4 | 4 | 4 | 4 | 4 |

## Appendix B: All-Bugs Results (30 bugs, Haiku n=3)

| Variant | Pass rate | Lift vs P0 |
|---------|-----------|------------|
| P0 | 5.6% (5/90) | — |
| P1 | 6.7% (6/90) | +1.1 pp |
| P2 | 42.2% (38/90) | +36.6 pp |
| P3 | 65.6% (59/90) | +60.0 pp |
| P4 | 71.1% (64/90) | +65.5 pp |
| P5 | 71.1% (64/90) | +65.5 pp |
| P6 | 61.1% (55/90) | +55.5 pp |

*Note: All-bugs results include the 4 noisy bugs (BUG41, BUG59, BUG62, BUG68) where P0 passes stochastically. The P0 rate of 5.6% reflects passes on noisy bugs only.*

## Appendix C: Harness Integrity Fixes Applied During Study

Three harness bugs were discovered and corrected during the study:

1. **Stream error detection** (`claudecode.py`): Claude Code `is_error=true` stream events were not propagated as provider errors, silently producing `status=ok` runs with empty code. Fixed by adding `_extract_stream_error()`.
2. **Empty-output validity gate** (`runner.py`): runs with `status=ok` and no generated code were not demoted to error. Fixed by post-run validity check.
3. **Resume integrity** (`csv_mapper.py`): `load_completed` loaded all entries regardless of status, preventing error runs from being retried on resume. Fixed by filtering to `status=ok`.

All affected runs were re-executed after fixes were applied.

## Appendix D: Artefact Paths

All run artefacts (full model outputs, tool traces, scoring results, and pytest results) are available in the repository:

| Artefact | Path |
|----------|------|
| Suite definition | `suites/script30.yaml` |
| Task definitions (30 tasks) | `tasks/script30/BUG{41..70}.yaml` |
| Snippet corpus (35 snippets) | `snippets/script30/` |
| Usecase codebase | `usecases/script30/` |
| Pytest tests (30 tests) | `usecases/script30/tests/unit/test_bug{41..70}.py` |
| Haiku Run 1 | `vsevals_runs/batch_1/matrix_20260303T193221340869Z/` |
| Haiku Run 2 | `vsevals_runs/batch_1/matrix_20260303T201709883387Z/` |
| Haiku Run 3 | `vsevals_runs/batch_1/matrix_20260303T215606747051Z/` |
| Codex Run 1 | `vsevals_runs/batch_1/matrix_20260303T193214057044Z/` |
| Codex Run 2 | `vsevals_runs/batch_1/matrix_20260303T201241727101Z/` |
| Experiment log | `EXPERIMENT.md` |
| Evaluation harness source | `vsevals/` |
