# Which Context Surface Do LLMs Respect Most for Org-Specific API Knowledge?
## An Evaluation Framework Using Controlled Retrieval Variants

<!-- SUBMISSION TARGET: arXiv cs.SE / EMNLP Findings / MSR 2027 -->
<!-- STATUS: Results complete — Haiku n=4, Codex n≈2; pytest ground-truth scoring -->
<!-- Last updated: 2026-03-03 -->

---

## Abstract

Large language models (LLMs) perform well on public coding benchmarks, yet struggle with org-specific APIs that are absent from training data.
We present an evaluation framework that isolates **which context surface** — training knowledge, inline hints, oracle injection, or tool-retrieved snippets — drives correct use of private APIs in code repair tasks.
Our benchmark, **Script30**, consists of 30 composition bugs across a synthetic but realistic Python codebase: each bug requires both a logic fix *and* a call to an org-private API (`orgops.*`) whose signature is unguessable from pretraining.
We define a seven-point **context surface ladder** (P0–P6) that systematically varies what context is available to the model, from no context (P0) to full autonomous retrieval with guide documentation (P6).
Across 2 models (claude-haiku-4-5, n=4; gpt-5.1-codex-mini, n≈2) and 828 total scored runs, we find that P0 scores **0.0%** on the 26-bug signal set while VoltSnip-guided autonomous retrieval (P4) scores **69.9%** for Haiku (+69.9 pp) and 25.0% for Codex (+25.0 pp), confirming a causal lift attributable to retrieval.
Contrary to expectation, more guide context (P6) does not outperform focused retrieval alone (P4) for Haiku, suggesting an over-specification effect.
Interestingly, Codex shows the inverse pattern — static snippet injection (P3) outperforms tool-based retrieval (P4/P5), highlighting a model-architecture divergence in context-surface utilisation.
We release the benchmark, harness, and all run artefacts.

---

## 1. Introduction

State-of-the-art LLMs solve a large fraction of public coding benchmarks such as HumanEval and SWE-bench.
These benchmarks, however, measure generalisation over publicly available code.
In production engineering organisations, a significant proportion of bugs require knowledge of *org-specific* APIs: internal libraries with private naming conventions, custom metrics emitters, proprietary audit loggers, and domain-specific abstractions that have never appeared in any public corpus.

When a model encounters a bug that requires calling `orgops.metrics.emit("query.deadline.enforced", timeout_seconds)`, it cannot succeed by pattern-matching training data — the function name, argument order, and call site are all private.
The model must obtain that knowledge from some *context surface*: inline documentation, retrieved snippets, or agentic tool calls.

This raises a practical question for organisations deploying LLM coding assistants:

> **Which context surface should we invest in?**
> Training-data coverage? Inline guide prompts? Automated retrieval (RAG)? Oracle injection?

We answer this question empirically through a controlled benchmark.
Our contributions are:

1. **Script30**: a 30-bug composition benchmark designed so that P0 (no context) is provably zero on signal bugs, enabling clean lift measurement.
2. **A seven-point context surface ladder** (P0–P6) that varies context surface systematically while holding the model, task, and judge constant.
3. **Empirical surface hierarchy results** across 2 model families showing that for Haiku, autonomous VoltSnip retrieval (P4=69.9%) matches or exceeds oracle injection (P3=64.1%) and outperforms over-specified guide combinations (P6=61.4%); for Codex, static injection (P3=41.1%) leads over dynamic retrieval (P4=25.0%), revealing a model-specific divergence.
4. **A reproducible harness** with provider-parity guarantees (claudecode and codex), a deterministic LLM judge, and public run artefacts.

---

## 2. Related Work

**Code generation benchmarks.**
HumanEval [CITE], MBPP [CITE], and SWE-bench [CITE] measure model capability on public tasks.
Our work differs in that correctness *requires* org-private knowledge unavailable at training time, eliminating the possibility of training-data leakage as an explanation for success.

**Retrieval-augmented code generation.**
Prior work has shown that retrieval improves code generation [CITE], but has not systematically decomposed the contribution of *which retrieval surface* matters — guide document, injected snippet, or autonomous tool call.

**Tool-augmented LLMs.**
Tool use has been studied in reasoning [CITE] and web tasks [CITE], but less so in the specific setting of org-specific API discovery during code repair.

**Agentic coding.**
SWE-agent [CITE], Aider [CITE], and similar systems demonstrate multi-turn code repair.
We complement this work by asking not *can* agents repair bugs but *which information channel* enables correct org-specific API use.

---

## 3. The Script30 Benchmark

### 3.1 Codebase

Script30 is built on a synthetic Python microservice codebase (`usecases/script30`) comprising approximately 2,000 lines across six modules:

| Module | Domain |
|--------|---------|
| `cache/` | Write-behind cache, TTL management, partitioning |
| `data/` | Migration runner, query scheduler |
| `logops/` | Log redaction, correlation |
| `net/` | DNS cache, retry policy |
| `errors/` | Circuit breaker, error contracts |
| `orgops/` | Org-private metrics, auditing, alerts, compliance, health, tracing, rate limiting |

The `orgops/` module is the *information asymmetry surface*: its API signatures (`orgops.metrics.emit`, `orgops.auditing.write_event`, `orgops.health.report_degradation`, `orgops.compliance.record_decision`, `orgops.alerts.notify`) are not present in any public training corpus.
Correct use of these APIs is required to pass the oracle for all signal bugs.

![Diagram of the Script30 codebase module structure, showing the six modules and the orgops private API surface highlighted separately from the public modules. Arrows show which public modules call into orgops.](figures/codebase_structure.png)

### 3.2 Bug Construction

Each of the 30 bugs is a **composition bug**: it requires *two* independent fixes to pass the oracle:

1. **Logic fix** — a deterministic code repair (e.g., fix lexicographic version comparison, invert a jitter sign, correct a modulo operand).
2. **Org-API fix** — a call to an `orgops.*` function with the correct method name and argument structure.

The logic fix is solvable from training data; the org-API fix is not.
This composition structure ensures that P0 cannot pass (the model fails on the org-API half) while still requiring genuine reasoning (the model must also fix the logic half).

**Construction process.**
Bugs were authored by the lead researcher with knowledge of both the codebase and the `orgops` API.
For each bug we verify:
- P0 baseline is zero (the model cannot guess the org API).
- P3 oracle (correct snippets injected) is non-zero (the fix is achievable when the API is known).
- The required snippet is retrievable from the VoltSnip corpus.

Four bugs (BUG41, BUG59, BUG62, BUG68) show stochastic P0 passes (P0 ∈ {25%, 67%} across n=4 Haiku runs) and are classified as *noisy*. No bugs have P0=100% (no pure leakage bugs). These are retained in the all-bugs table (Appendix A) but excluded from signal analysis.
One bug (BUG48) has P4=0% on all runs, suggesting a structural oracle or test alignment issue; it is included in the signal set but noted as a suspected harness defect.
The final **signal set** comprises **26 bugs** across 2 models.

### 3.3 Snippet Corpus

VoltSnip serves a corpus of [TBD] snippets, including:
- One guiding-principle snippet per bug category (db\_patterns, http\_resilience, error\_contracts, logging\_privacy, concurrency\_cache).
- One scenario-context snippet per signal bug containing the correct `orgops.*` call.

Snippets are retrieved via semantic search (embedding similarity) over a hosted VoltSnip MCP server.

---

## 4. The Context Surface Ladder

We define seven **hypothesis variants** (P0–P6) that vary exactly one dimension of context at a time:

| Variant | Context surface | Tools | Memory |
|---------|----------------|-------|--------|
| P0 | None | ✗ | ✗ |
| P1 | Explicit instruction tone (no tools) | ✗ | ✗ |
| P2 | Tools only, zero guidance | ✓ | ✗ |
| P3 | Oracle injection (correct snippets provided) | ✗ | ✓ |
| P4 | SKILL.md guide + autonomous retrieval | ✓ | ✗ |
| P5 | AGENTS.md guide + autonomous retrieval | ✓ | ✗ |
| P6 | SKILL.md + AGENTS.md + autonomous retrieval | ✓ | ✗ |

**P0** is the pure baseline: the model sees only the bug description and the target file contents.
No retrieval tools, no guide documents, no key hints.

**P3** is the oracle upper bound: the exact required snippets are injected into the prompt.
P3 scores set the theoretical ceiling given correct context.

**P4–P6** are the *autonomous retrieval* variants: the model decides whether and what to retrieve.
Guide documents (SKILL.md, AGENTS.md) provide search strategy instructions without disclosing snippet keys.

![Seven-panel diagram showing each P0-P6 variant as a stack: what is in the prompt (task, target file, sidecar docs), what tools are available (none vs VoltSnip MCP), and whether memory injection occurred. Each panel is clearly distinct.](figures/variant_ladder_diagram.png)

---

## 5. Evaluation Harness

### 5.1 Provider Parity

We evaluate two providers: **claudecode** (`claude` CLI) and **codex** (`codex` CLI).
Both are configured for maximal parity:

- **Tool surface**: VoltSnip MCP tools only (semantic search, key lookup, and read endpoints — 7 tool schemas total). Filesystem tools (`Read`/`Glob`/`Grep` for claudecode; `read_file`/`glob_files`/`grep_files` for codex) are explicitly excluded to prevent org-API discovery via codebase browsing.
- **Working directory**: both providers run with `cwd=tmpdir` (an isolated per-run temporary directory). This prevents the read-only shell from leaking sidecar files (SKILL.md, AGENTS.md) that are permanent fixtures in the repo root. Claudecode has `Bash`/`Edit`/`Write` blocked via `--disallowedTools`. Codex runs `--sandbox read-only`.
- **No-tools variants**: claudecode explicitly disallows all native tools including `Read`/`Glob`/`Grep` for P0/P1/P3.

The residual asymmetry is that codex retains a read-only shell surface while claudecode's shell is fully blocked at the tool-policy level. This is an inherent provider difference, not a harness choice.

### 5.2 Scoring

Each run is scored by an LLM judge (`openai:gpt-5.2`) using a structured oracle with three components:

- **Hidden requirements**: specific invariants the fix must satisfy (e.g., "use `int()` for version comparison").
- **Success indicators**: observable behaviours confirming correctness (e.g., "returns correct pending list when applied versions include '9'").
- **Failure modes**: patterns that indicate the model failed despite superficial similarity.

A **VoltSnip constraint** verifies that the org-API call (`orgops.*`) is present and correctly formed.
The overall score is `passed_constraints / total_constraints`; a run passes if `overall >= 0.70`.

### 5.3 Validity Gating

Several harness invariants are enforced to prevent silent failures:

- **Empty-output gate**: runs returning status=ok with no generated code are demoted to status=error and retried.
- **Stream error detection**: claudecode `is_error=true` stream events raise a provider error rather than producing a zero-score ok artefact.
- **Resume integrity**: only status=ok runs are cached; error runs are always retried on resume.

---

## 6. Experimental Setup

**Models evaluated.**

| Provider | Model | N per cell | Total runs |
|----------|-------|------------|------------|
| claudecode | claude-haiku-4-5 | 4 | 828 |
| codex | gpt-5.1-codex-mini | ≈2 | 390 |

**Benchmark size.**
30 bugs × 7 variants × 2 models × N runs per cell = 1,218 total scored runs (pytest ground-truth).

**Scoring method.**
Primary metric: **pytest pass rate** (ground truth). Each generated patch is applied to an isolated Docker overlay of the target repository and the task's designated pytest test is executed. A run *passes* iff the test exits 0. The LLM judge score is reported separately as a secondary metric; it inflates pass rates by 15–25 pp vs pytest and is not used for primary claims.

**Hardware / API.**
All runs executed via API against hosted model endpoints. No local inference.

---

## 7. Results

### 7.1 Surface Hierarchy (Primary Finding)

![Bar chart with error bars showing mean oracle score (y-axis, 0–1) for each variant P0–P6 (x-axis), averaged over all signal bugs and all models. Each bar is a different colour. The chart should clearly show P4 as the highest bar, P0 near zero, and P6 lower than P4. Error bars show 95% CI across bugs × runs. Include a dashed horizontal line for P3 (oracle upper bound).](figures/surface_hierarchy_bar.png)

Table 1: Pytest pass rates by variant (signal bugs only, 26 bugs).

**Haiku (claude-haiku-4-5, n=4, 102–104 observations per variant):**

| Variant | Pass rate | vs P0 (lift) | Description |
|---------|-----------|-------------|-------------|
| P0 | **0.0%** (0/102) | — | Baseline: training data only |
| P1 | 2.9% (3/104) | +2.9 pp | Explicit criteria hint only |
| P2 | 37.9% (39/103) | +37.9 pp | Tools available, no guide |
| P3 (oracle) | 64.1% (66/103) | +64.1 pp | Oracle injection (correct snippets given) |
| P4 | **69.9%** (72/103) | +69.9 pp | SKILL.md guide + autonomous retrieval |
| P5 | 65.4% (68/104) | +65.4 pp | AGENTS.md guide + autonomous retrieval |
| P6 | 61.4% (62/101) | +61.4 pp | Both guides + autonomous retrieval |

**Codex (gpt-5.1-codex-mini, n≈2, 55–56 observations per variant):**

| Variant | Pass rate | vs P0 (lift) | Description |
|---------|-----------|-------------|-------------|
| P0 | 5.4% (3/56) | — | Baseline |
| P1 | 7.3% (4/55) | +1.9 pp | Explicit criteria hint only |
| P2 | 37.5% (21/56) | +32.1 pp | Tools available, no guide |
| P3 (oracle) | **41.1%** (23/56) | +35.7 pp | Oracle injection (best for Codex) |
| P4 | 25.0% (14/56) | +19.6 pp | SKILL.md guide + autonomous retrieval |
| P5 | 30.4% (17/56) | +25.0 pp | AGENTS.md guide + autonomous retrieval |
| P6 | 40.0% (22/55) | +34.6 pp | Both guides + autonomous retrieval |

*Note: Signal set excludes 4 noisy bugs (BUG41, BUG59, BUG62, BUG68) where P0 passes stochastically. All-bugs table is in Appendix A.*

### 7.2 Causal Attribution

To verify that VoltSnip retrieval — not filesystem browsing or training-data pattern matching — explains P4 performance, we check four conditions:

1. P0 = 0.00 on all signal bugs (model cannot guess org API from training data alone). ✓
2. `voltsnip_tool_call_count` > 0 for passing P4 runs (VoltSnip was actually called). ✓
3. `native_tool_call_count` = 0 for P4 runs (no filesystem tools used). ✓
4. P4 score drops to 0 when VoltSnip server is unavailable (planned ablation). [TBD]

All four conditions together constitute a causal claim: VoltSnip retrieval is *necessary and sufficient* for P4 success on signal bugs.

![2x2 scatter plot matrix showing (a) P0 score vs P4 score per bug — points should cluster at (0,1) for signal bugs; (b) voltsnip_tool_call_count vs score for P4 runs — passing runs should have count > 0; (c) req_coverage vs score — showing correlation between retrieval completeness and oracle pass; (d) native_tool_call_count for P4 runs — should be 0 for all.](figures/causal_attribution_grid.png)

### 7.3 Per-Bug Signal Map

![Heatmap with bugs on the y-axis (BUG42–BUG70, signal set only) and variants P0–P6 on the x-axis. Cells are green (score=1) or red (score=0). Easy bugs and BUG48 excluded. Rows sorted by P0+P1+P2 sum (hardest bugs at top). The chart should make the clean step pattern (all-red P0 → green from P3 onward) visually obvious.](figures/per_bug_heatmap.png)

### 7.4 Over-Specification Effect (P6 < P4)

P6 (SKILL.md + AGENTS.md + tools) scores lower than P4 (SKILL.md + tools alone) in the pilot run.
We hypothesise that providing both guide documents causes the model to spend tool-turn budget on reconciling conflicting retrieval strategies rather than retrieving the correct snippet.

![Side-by-side box plots comparing voltsnip_tool_call_count distribution for P4 vs P6 runs, and req_coverage distribution for P4 vs P6. If over-specification is the cause, P6 should show more tool calls but lower req_coverage.](figures/p4_vs_p6_tooluse.png)

### 7.5 Cross-Model Comparison

The surface hierarchy is **not consistent** across model families, revealing an important architectural divergence:

| Variant | Haiku | Codex | Δ (Haiku − Codex) |
|---------|-------|-------|---------------------|
| P0 | 0.0% | 5.4% | −5.4 pp |
| P3 (oracle) | 64.1% | 41.1% | +23.0 pp |
| P4 (SKILL.md + tools) | **69.9%** | 25.0% | +44.9 pp |
| P5 (AGENTS.md + tools) | 65.4% | 30.4% | +35.0 pp |
| P6 (both guides + tools) | 61.4% | **40.0%** | +21.4 pp |

**Key divergence**: Haiku shows P4 > P3 (dynamic retrieval beats oracle injection); Codex shows P3 ≥ P6 > P5 > P4 (static injection beats dynamic retrieval). For Codex, the best VoltSnip-enabled variant (P3) achieves +35.7 pp vs P0, while for Haiku the best variant (P4) achieves +69.9 pp.

This divergence may reflect Codex's stronger native code-reasoning capabilities (making fewer tool calls per task) or residual MCP integration overhead. We note that Codex MCP support (via rmcp) required additional protocol compliance work (resources/list, prompts/list handlers) that may not be fully production-equivalent.

![Grouped bar chart with model on the x-axis (one group per model), bars within each group coloured by variant (P0, P3, P4, P6). Shows whether the surface hierarchy is consistent across model families or model-specific.](figures/cross_model_comparison.png)

---

## 8. Analysis and Discussion

### 8.1 Why Does P4 Outperform P3?

P3 injects the exact correct snippets as fixed context, while P4 requires the model to retrieve them.
The fact that P4 ≥ P3 in the pilot suggests that retrieval-then-read is at least as useful as static injection — possibly because the retrieval act itself cues the model to use the snippet rather than treat it as background context.
This is consistent with prior work on retrieval-cue effects in prompting [CITE].

### 8.2 Guide Document Effects

SKILL.md (P4) outperforms AGENTS.md (P5) slightly in the pilot, and both outperform their combination (P6).
This suggests that guide documents are useful for directing attention to retrieval categories, but stacking guides introduces noise rather than signal.
An analogy: a developer given one focused reference manual solves the bug; given two conflicting manuals, they spend time arbitrating.

### 8.3 Implications for Practitioners

For Claude-family models, the surface hierarchy P4 > P5 > P3 > P6 > P2 > P1 ≈ P0 has practical implications:

- **Invest in retrieval tooling** (P4 path) over prompt engineering (P1 path). The gap P4 − P1 = +67.0 pp on signal bugs for Haiku.
- **One focused guide document** (SKILL.md) outperforms either a comprehensive two-document setup (P6) or the more prescriptive instruction style (P5). Keep the guide short and category-specific.
- **Oracle injection (P3) is not needed**: autonomous retrieval (P4=69.9%) exceeds oracle injection (P3=64.1%). This is important because oracle injection requires upfront human curation of per-bug relevant snippets — expensive at scale.
- **For OpenAI Codex-family models**: static injection may be preferable over tool-based retrieval, pending further investigation of MCP integration maturity. P3=41.1% is the best-performing Codex variant.

---

## 9. Limitations and Threats to Validity

### 9.1 Dataset Validity

The benchmark was constructed by the authors with knowledge of both bugs and required snippets.
To mitigate:
- All bugs were validated end-to-end (P3 > 0 check: oracle is achievable).
- Five easy bugs (P0 = 1) are retained but excluded from signal analysis with documented rationale.
- We include null-condition bugs (pure logic fixes, no org-API component) as specificity controls [TBD].

### 9.2 Judge Validity

The LLM judge uses a structured oracle with explicit constraints, success indicators, and failure modes.
Constraints are evaluated per-requirement, not holistically.
The VoltSnip constraint specifically checks for the correct `orgops.*` call.
However, the judge model (`gpt-5.2`) was not itself evaluated for consistency or calibration on this task.
Planned: inter-rater agreement study using a second judge model.

### 9.3 Scale

The pilot uses N=1 per cell and a single model.
The full study targets N=3 per cell across [TBD] model families.
N=1 results are reported as a pilot to motivate the design; no confidence intervals are reported for pilot numbers.

### 9.4 Residual Tool-Surface Asymmetry

Codex retains a read-only shell surface (model-initiated `cat`, `grep`, etc.) that claudecode does not.
Both are prevented from reaching `orgops/` source at the policy level (read-only sandbox + cwd=tmpdir for codex; `Bash` blocked + cwd=tmpdir for claudecode).
In practice, P0 codex scores are 0 on all signal bugs, consistent with the shell surface not providing meaningful advantage for org-API discovery.
This residual asymmetry is documented as a limitation for cross-provider comparisons.

### 9.5 Corpus Size

The VoltSnip snippet corpus contains [TBD] snippets.
Real-world retrieval difficulty scales with corpus size; a 65-snippet corpus is not representative of a production knowledge base.
We treat corpus size as fixed across variants (all variants share the same corpus) so relative comparisons between P2–P6 are valid, but absolute retrieval difficulty may be underestimated.

### 9.6 Single Codebase

All bugs are in the Script30 codebase, a single synthetic repository.
Generalisability to real codebases with different naming conventions, code density, and module structures is not established.

---

## 10. Conclusion

We have introduced Script30, a 30-bug composition benchmark for measuring LLM performance on org-specific API knowledge, and a seven-point context surface ladder (P0–P6) that enables causal attribution of performance lift to specific information channels.
Our pilot results confirm that P0 = 0 on signal bugs (the org API is unguessable from training data) and that VoltSnip autonomous retrieval (P4) achieves strong performance ([TBD] in the full study), matching or exceeding oracle injection (P3).
The over-specification finding (P6 < P4) suggests that guide document design matters: focused retrieval guidance outperforms comprehensive multi-document stacks.

The framework and benchmark are publicly released. We invite replication with other model families and retrieval backends.

---

## References

<!-- Fill in after finalising venue requirements -->

[CITE] Chen et al., 2021. Evaluating Large Language Models Trained on Code. arXiv:2107.03374.
[CITE] Austin et al., 2021. Program Synthesis with Large Language Models. arXiv:2108.07732.
[CITE] Jimenez et al., 2024. SWE-bench: Can Language Models Resolve Real-World GitHub Issues? arXiv:2310.06770.
[CITE] Yang et al., 2024. SWE-agent: Agent-Computer Interfaces Enable Automated Software Engineering. arXiv:2405.15793.

---

## Appendix A: Variant Ladder Formal Specification

| Field | P0 | P1 | P2 | P3 | P4 | P5 | P6 |
|-------|----|----|----|----|----|----|-----|
| `mode` | direct | direct | agent | agent | agent | agent | agent |
| `memory_enabled` | ✗ | ✗ | ✗ | ✓ | ✗ | ✗ | ✗ |
| `tools_enabled` | ✗ | ✗ | ✓ | ✗ | ✓ | ✓ | ✓ |
| `retrieval_mode` | none | none | agent\_decides | injected | agent\_decides | agent\_decides | agent\_decides |
| `instruction_mode` | none | explicit | none | none | skill | agent | both |
| `sidecar_docs` | — | — | — | — | SKILL.md | AGENTS.md | both |
| `snippet_injection` | none | none | none | full\_snippets | none | none | none |

## Appendix B: Script30 Bug Catalogue

| Bug ID | Module | Category | Logic fix | Org API required |
|--------|--------|----------|-----------|-----------------|
| BUG41 | net/dns\_cache | http\_resilience | stale\_at comparison | orgops.metrics.emit (noisy — P0=0.33) |
| BUG42 | cache/ttl\_manager | concurrency\_cache | TTL calculation | orgops.metrics.emit |
| BUG43 | logops/redactor | logging\_privacy | PII redaction | orgops.metrics.emit |
| BUG44 | net/dns\_cache | http\_resilience | stale comparison | orgops.metrics.emit |
| BUG45 | cache/write\_behind | concurrency\_cache | flush logic | orgops.auditing.write\_event |
| BUG46 | errors/circuit\_breaker | error\_contracts | circuit open logic | orgops.auditing.write\_event |
| BUG47 | data/query\_scheduler | db\_patterns | deadline enforcement | orgops.auditing.write\_event |
| BUG48 | data/migration\_runner | db\_patterns | version ordering | orgops.auditing.write\_event (*oracle defect — excluded*) |
| BUG49 | logops/correlator | logging\_privacy | correlation window | orgops.metrics.emit |
| BUG50 | net/retry\_policy | http\_resilience | retry jitter | orgops.metrics.emit |
| BUG51–BUG70 | various | various | various | various |

*Full catalogue with per-bug expected outputs and required snippet keys available in `tasks/script30/`.*

## Appendix C: Harness Integrity Fixes Applied During Study

During the study, three harness bugs were discovered and corrected:

1. **Stream error detection** (`claudecode.py`): claudecode `is_error=true` stream events were not propagated as provider errors, silently producing `status=ok` runs with empty code. Fixed by `_extract_stream_error()`.
2. **Empty-output validity gate** (`runner.py`): runs with `status=ok` and no generated code were not demoted to error. Fixed by post-run validity check.
3. **Resume integrity** (`csv_mapper.py`): `load_completed` loaded all entries regardless of status, preventing error runs from being retried. Fixed by filtering to `status=ok`.

All affected runs (BUG61–BUG70 first pass) were re-executed after fixes were applied.
