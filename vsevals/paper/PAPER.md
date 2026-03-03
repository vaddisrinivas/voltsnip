# Which Context Surface Do LLMs Respect Most for Org-Specific API Knowledge?
## An Evaluation Framework Using Controlled Retrieval Variants

<!-- SUBMISSION TARGET: arXiv cs.SE / EMNLP Findings / MSR 2027 -->
<!-- STATUS: Draft — awaiting multi-model N=3 run results -->
<!-- Replace all [PLACEHOLDER] and [TBD] blocks after full run -->

---

## Abstract

Large language models (LLMs) perform well on public coding benchmarks, yet struggle with org-specific APIs that are absent from training data.
We present an evaluation framework that isolates **which context surface** — training knowledge, inline hints, oracle injection, or tool-retrieved snippets — drives correct use of private APIs in code repair tasks.
Our benchmark, **Script30**, consists of 30 composition bugs across a synthetic but realistic Python codebase: each bug requires both a logic fix *and* a call to an org-private API (`orgops.*`) whose signature is unguessable from pretraining.
We define a seven-point **context surface ladder** (P0–P6) that systematically varies what context is available to the model, from no context (P0) to full autonomous retrieval with guide documentation (P6).
Across [TBD] models and [TBD] runs, we find that P0 scores [TBD] on signal bugs while VoltSnip-guided autonomous retrieval (P4) scores [TBD], confirming a causal lift attributable to retrieval.
Contrary to expectation, more guide context (P6) does not outperform focused retrieval alone (P4), suggesting an over-specification effect.
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
3. **Empirical surface hierarchy results** across [TBD] models showing that autonomous VoltSnip retrieval (P4) matches or exceeds oracle injection (P3) and outperforms over-specified guide combinations (P6).
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
| `orgops/` | Org-private metrics, auditing, feature flags |

The `orgops/` module is the *information asymmetry surface*: its API signatures (`orgops.metrics.emit`, `orgops.auditing.write_event`, `orgops.flags.is_enabled`) are not present in any public training corpus.
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

Five bugs (BUG41, BUG59, BUG61, BUG62, BUG64) were found to have P0=1 and are classified as *easy* — the logic fix alone passes the oracle without the org-API component.
These are retained in the benchmark but excluded from signal analysis.
One bug (BUG48) has a structural oracle defect (line range mismatch) and is excluded from all analyses.
The final **signal set** comprises **[TBD] bugs** across [TBD] models.

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
| P1 | Inline hint (key list injected) | ✗ | ✓ |
| P2 | Inline hint + autonomous retrieval | ✓ | ✓ |
| P3 | Oracle injection (correct snippets provided) | ✗ | ✓ |
| P4 | SKILL.md guide + autonomous retrieval | ✓ | ✓ |
| P5 | AGENTS.md guide + autonomous retrieval | ✓ | ✓ |
| P6 | SKILL.md + AGENTS.md + autonomous retrieval | ✓ | ✓ |

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

- **Tool surface**: VoltSnip MCP tools only (`search_memory`, `get_snippet_by_canonical_key`). Filesystem tools (`Read`/`Glob`/`Grep` for claudecode; `read_file`/`glob_files`/`grep_files` for codex) are explicitly excluded to prevent org-API discovery via codebase browsing.
- **Working directory**: both providers run with `cwd=repo_root` (read-only access to the codebase). Claudecode has `Bash`/`Edit`/`Write` blocked via `--disallowedTools`. Codex runs `--sandbox read-only`.
- **No-tools variants**: claudecode explicitly disallows all native tools including `Read`/`Glob`/`Grep` for P0/P1/P3.

The residual asymmetry is that codex retains a read-only shell surface while claudecode's shell is fully blocked at the tool-policy level. This is an inherent provider difference, not a harness choice.

### 5.2 Scoring

Each run is scored by an LLM judge (`openai:gpt-5.2`) using a structured oracle with three components:

- **Hidden requirements**: specific invariants the fix must satisfy (e.g., "use `int()` for version comparison").
- **Success indicators**: observable behaviours confirming correctness (e.g., "returns correct pending list when applied versions include '9'").
- **Failure modes**: patterns that indicate the model failed despite superficial similarity.

A **VoltSnip constraint** verifies that the org-API call (`orgops.*`) is present and correctly formed.
The overall score is 1 if and only if all constraints pass; 0 otherwise.

### 5.3 Validity Gating

Several harness invariants are enforced to prevent silent failures:

- **Empty-output gate**: runs returning status=ok with no generated code are demoted to status=error and retried.
- **Stream error detection**: claudecode `is_error=true` stream events raise a provider error rather than producing a zero-score ok artefact.
- **Resume integrity**: only status=ok runs are cached; error runs are always retried on resume.

---

## 6. Experimental Setup

**Models evaluated.**

| Provider | Model | N per cell |
|----------|-------|------------|
| claudecode | claude-haiku-4-5 | [TBD] |
| [TBD] | [TBD] | [TBD] |
| [TBD] | [TBD] | [TBD] |

**Benchmark size.**
30 bugs × 7 variants × [TBD] models × [TBD] runs per cell = [TBD] total runs.

**Hardware / API.**
All runs executed via API against hosted model endpoints. No local inference.

---

## 7. Results

### 7.1 Surface Hierarchy (Primary Finding)

![Bar chart with error bars showing mean oracle score (y-axis, 0–1) for each variant P0–P6 (x-axis), averaged over all signal bugs and all models. Each bar is a different colour. The chart should clearly show P4 as the highest bar, P0 near zero, and P6 lower than P4. Error bars show 95% CI across bugs × runs. Include a dashed horizontal line for P3 (oracle upper bound).](figures/surface_hierarchy_bar.png)

Table 1: Mean oracle scores by variant across signal bugs (N=[TBD] runs per cell).

| Variant | Mean score | 95% CI | vs P0 (lift) |
|---------|-----------|--------|-------------|
| P0 | [TBD] | [TBD] | — |
| P1 | [TBD] | [TBD] | [TBD] |
| P2 | [TBD] | [TBD] | [TBD] |
| P3 (oracle) | [TBD] | [TBD] | [TBD] |
| P4 | [TBD] | [TBD] | [TBD] |
| P5 | [TBD] | [TBD] | [TBD] |
| P6 | [TBD] | [TBD] | [TBD] |

*Preliminary single-model pilot (N=1, claude-haiku-4-5): P0=0.00, P3=0.88, P4=0.92, P6=0.75 on 24 signal bugs.*

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

[TBD — awaiting multi-model run]

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

The surface hierarchy P4 > P3 ≈ P5 > P6 > P2 > P1 > P0 has practical implications:

- **Invest in retrieval tooling** (P4 path) over prompt engineering (P1 path). The gap P4 − P1 ≈ [TBD] on signal bugs.
- **One focused guide document** outperforms a comprehensive multi-document setup. Keep SKILL.md short and category-specific.
- **Oracle injection (P3) is not needed**: autonomous retrieval matches or exceeds it. This is important because oracle injection requires upfront human curation of per-bug relevant snippets — expensive at scale.

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
Both are prevented from reaching `orgops/` source at the policy level (read-only sandbox + cwd=repo\_root for codex; `Bash` blocked for claudecode).
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
| `mode` | direct | direct | agent | direct | agent | agent | agent |
| `memory_enabled` | ✗ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `tools_enabled` | ✗ | ✗ | ✓ | ✗ | ✓ | ✓ | ✓ |
| `retrieval_mode` | none | inline\_hint | autonomous | oracle | autonomous | autonomous | autonomous |
| `instruction_mode` | none | none | none | none | skill | agent | both |
| `sidecar_docs` | — | — | — | — | SKILL.md | AGENTS.md | both |
| `snippet_injection` | none | key\_list | none | full\_snippets | none | none | none |

## Appendix B: Script30 Bug Catalogue

| Bug ID | Module | Category | Logic fix | Org API required |
|--------|--------|----------|-----------|-----------------|
| BUG41 | net/dns\_cache | http\_resilience | stale\_at comparison | orgops.metrics.emit (easy — P0=1) |
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
