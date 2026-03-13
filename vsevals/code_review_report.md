# vsevals — Exhaustive Code Review Report

**Reviewer**: Claude (automated)
**Date**: 2026-03-13
**Branch**: arxiv-v1
**Files reviewed**: 37 Python files across `vsevals/` and `scripts/`

---

## Executive Summary

The vsevals codebase is a well-structured evaluation harness for measuring AI coding assistants' ability to leverage RAG-retrieved context. The architecture cleanly separates concerns (prompt building, provider dispatch, scoring, patching, reporting). Code quality is generally high with good docstrings and logging.

**Critical issues** found: 2
**Major issues** found: 11
**Minor issues** found: 23

Key themes:
1. Several security-adjacent concerns (hardcoded credentials, path traversal incomplete, SQL injection surface)
2. Error-swallowing patterns that silently degrade results
3. Duplicated utility code across analysis scripts
4. A few latent bugs in edge-case handling (off-by-one in line-range patching, race conditions in overlay cleanup)

---

## Per-File Reviews

---

### 1. `vsevals/vsevals/__init__.py`

**Purpose**: Package marker with a one-line docstring.

**Code quality**: Minimal, correct.

**Issues**: None.

---

### 2. `vsevals/vsevals/models.py` (612 lines)

**Purpose**: Core Pydantic data models (SuiteConfig, VariantConfig, RunResult, ScoreResult, etc.), pricing table, cost computation, model parsing.

**Code quality**: Good. Well-typed, clear field naming.

**Bugs & Issues**:

- **[Major]** `PRICING` table uses hardcoded model price lookups. New models (e.g., `gpt-5.3-codex`, `claude-sonnet-4-6`) require manual table updates or `compute_cost` silently returns 0.0 with no warning.

  ```python
  # Before (silent zero):
  return PRICING.get(model_id, {}).get("input", 0.0) * ...

  # After (log warning):
  rates = PRICING.get(model_id)
  if rates is None:
      LOGGER.warning("No pricing entry for model %r — cost will be 0.0", model_id)
      return 0.0
  ```
  **Priority**: Major

- **[Minor]** `parse_model` splits on `:` but doesn't validate that the model_id portion is non-empty. `"openai:"` would return `("openai", "")`.

  **Priority**: Minor

**Architecture**: Clean separation. Models are pure data containers.

**Security**: No secrets in models. Fine.

**Performance**: No concerns.

---

### 3. `vsevals/vsevals/loader.py` (179 lines)

**Purpose**: Loads suite YAML files, resolves task file paths, injects docker config.

**Code quality**: Good. Clear YAML loading logic.

**Bugs & Issues**:

- **[Minor]** `_resolve_task_files` uses `yaml.safe_load` on task YAML files but does not validate schema. A malformed task YAML would produce an unhelpful `KeyError` deep in the pipeline rather than a clear validation error at load time.

  **Priority**: Minor

- **[Minor]** `repo_root` resolution falls through silently if the path does not exist. A non-existent `default_repo_root` would only surface later when `_read_target_file` returns `None`.

  **Priority**: Minor

**Architecture**: Good. Single responsibility.

**Security**: Uses `yaml.safe_load` (not `yaml.load`). Correct.

**Performance**: Fine for file sizes involved.

---

### 4. `vsevals/vsevals/prompt.py` (396 lines)

**Purpose**: Prompt assembly for P0-P8 variants. Builds system/user prompts, generates sidecar files (CLAUDE.md, AGENTS.md, SKILL.md), inline guides.

**Code quality**: Good. Builder pattern is clear.

**Bugs & Issues**:

- **[Major]** `INLINE_SKILL_GUIDE` and `INLINE_AGENT_GUIDE` are large string constants embedded inline. If these guides are updated, the prompt.py file becomes the single source of truth diverging from the actual `vsevals/skills.md` and `vsevals/agents.md` files. The code reads from files for sidecar generation but uses hardcoded strings for inline injection. This creates a maintenance divergence risk.

  **Priority**: Major

- **[Minor]** The `_Builder` class accumulates sections via string concatenation. For very large prompts this is fine in practice but `io.StringIO` or list-join would be more idiomatic.

  **Priority**: Minor

- **[Minor]** `build_prompt` does not validate that `variant.context_surface` is a recognized value. An unknown surface would fall through all conditions and produce a prompt with only the base content.

  **Priority**: Minor

**Architecture**: Clean builder pattern. Sidecar file generation is well-separated.

**Security**: No secrets. Prompt content is trusted (loaded from local YAML/files).

**Performance**: Fine.

---

### 5. `vsevals/vsevals/runner.py` (1104 lines)

**Purpose**: Core orchestration engine. `run_one()` executes a single (task x variant x model) cell. Handles agent mode, snippet retrieval, patch+pytest, artifact writing.

**Code quality**: High. Excellent docstrings, clear flow comments, good error classification.

**Bugs & Issues**:

- **[Major]** `_load_dotenv_keys` reads `.env` files and parses them manually. The parser does not handle quoted values (`OPENAI_API_KEY="sk-..."` would include the quotes in the value). This is a common `.env` parsing gotcha.

  ```python
  # Before:
  key, value = line.split("=", 1)
  key, value = key.strip(), value.strip()

  # After:
  key, value = line.split("=", 1)
  key, value = key.strip(), value.strip().strip("\"'")
  ```
  **Priority**: Major

- **[Minor]** `_classify_error` uses substring matching on `str(exc).lower()`. This is fragile — e.g., an error message containing the word "parse" in a non-JSON context would be misclassified as `LLM_PARSE_ERROR`. Consider checking exception types first, then message content as fallback.

  **Priority**: Minor

- **[Minor]** `_run_patch_and_test` copies `.venv` with `shutil.copytree(..., symlinks=True)`. If `.venv` is large (hundreds of MB), this dominates the patch+test latency. A symlink to the original `.venv` would be faster (the overlay is read-only for the venv anyway).

  **Priority**: Minor (performance)

- **[Minor]** The convenience wrapper generation loop (`for _vid, _doc in _VARIANT_DOCS.items()`) uses `globals()` injection. This is a valid Python pattern but makes the module hard to introspect statically (type checkers, IDE navigation).

  **Priority**: Minor

**Architecture**: Well-organized with clear step numbering. The agent mode dispatch is clean.

**Security**: `.env` parsing is a mild concern (see above). No other issues.

**Performance**: `shutil.copytree` for overlay creation is the main bottleneck for pytest runs.

---

### 6. `vsevals/vsevals/dispatch.py` (303 lines)

**Purpose**: LLM dispatch layer routing to providers. `call_llm()` and `call_judge()` entry points.

**Code quality**: Good. Clean routing logic.

**Bugs & Issues**:

- **[Minor]** `call_llm` and `call_judge` have nearly identical signatures and routing logic. Consider a shared `_dispatch` helper to reduce duplication.

  **Priority**: Minor

- **[Minor]** `harness_tool_schemas()` returns a static list. If the VoltSnip API adds new tools, this must be updated manually. A comment noting this coupling would help.

  **Priority**: Minor

**Architecture**: Clean single-responsibility dispatch.

**Security**: API keys are passed through, not logged.

**Performance**: Fine — thin routing layer.

---

### 7. `vsevals/vsevals/client.py` (181 lines)

**Purpose**: VoltSnip HTTP client with retry logic.

**Code quality**: Good. Uses httpx with configurable timeouts and retries.

**Bugs & Issues**:

- **[Major]** Retry logic catches all `Exception` types. This means non-retriable errors (e.g., `ValueError` from JSON parsing, `KeyError` from response handling) will be retried, wasting time and obscuring the real error.

  ```python
  # Before:
  except Exception as exc:
      ...retry...

  # After:
  except (httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException) as exc:
      ...retry...
  ```
  **Priority**: Major

- **[Minor]** `preflight_check()` catches all exceptions and returns `False`. A DNS resolution failure and a 500 error produce the same result. Consider logging the specific error.

  **Priority**: Minor

**Architecture**: Clean. Single-purpose HTTP client.

**Security**: No credentials stored in the client itself. Base URL is configurable.

**Performance**: Retry with backoff is appropriate.

---

### 8. `vsevals/vsevals/harness_tools.py` (115 lines)

**Purpose**: Pure Python tool functions (read_file, glob_files, grep_files, search_snippets, get_snippet_by_key).

**Code quality**: Good. Simple, focused functions.

**Bugs & Issues**:

- **[Major]** Path traversal check in `read_file` uses `str(resolved).startswith(str(base))`. This is a known-flawed pattern — e.g., `base=/workspace` and `resolved=/workspace_evil/secret` would pass the check. The correct approach is to check `resolved.is_relative_to(base)` (Python 3.9+) or compare `.parts`.

  ```python
  # Before:
  if not str(resolved).startswith(str(base)):

  # After:
  if not resolved.is_relative_to(base):
  ```
  **Priority**: Major

- **[Minor]** `grep_files` does not limit result size. A `.*` pattern on a large repo could return megabytes of matches.

  **Priority**: Minor

**Architecture**: Clean tool function interface.

**Security**: Path traversal fix is the main concern (see above).

**Performance**: `glob_files` uses `Path.glob` which is fine for typical repo sizes.

---

### 9. `vsevals/vsevals/harness_mcp.py` (268 lines)

**Purpose**: Unified eval harness MCP HTTP server (JSON-RPC). Serves tools to subprocess providers (claudecode, codex).

**Code quality**: Good. Clean JSON-RPC implementation.

**Bugs & Issues**:

- **[Minor]** The server binds to `127.0.0.1` which is correct for security, but port selection is hardcoded. If two runs execute concurrently, they would collide on the same port. The code should use port 0 (OS-assigned) or check availability.

  **Priority**: Minor (in practice runs are serialized by the matrix runner)

- **[Minor]** Error responses in JSON-RPC don't include the standard `id` field from the request in all error paths. This could confuse strict JSON-RPC clients.

  **Priority**: Minor

**Architecture**: Clean. Single HTTP server serving multiple tools.

**Security**: Binds to localhost only. Good.

**Performance**: Fine for single-client usage.

---

### 10. `vsevals/vsevals/patching.py` (217 lines)

**Purpose**: Isolated overlay patching for pytest runs. `materialize_overlay`, `apply_rewrite`, `apply_line_range_rewrite`, `cleanup_overlay`.

**Code quality**: Good but the most bug-prone file in the codebase given its line-range splicing logic.

**Bugs & Issues**:

- **[Critical]** `apply_line_range_rewrite` uses 1-based line indexing but the splice logic has an off-by-one risk. The function does `original_lines[:line_start-1] + new_lines + original_lines[line_end:]`. If `line_start=1` and `line_end=1`, this replaces exactly line 1 — correct. But if `line_end` exceeds the file length, `original_lines[line_end:]` silently returns `[]`, which is correct but means trailing content is silently dropped with no warning. A file that grows shorter than expected should at minimum log a warning.

  ```python
  # After the splice, add:
  if line_end > len(original_lines):
      LOGGER.warning(
          "line_end=%d exceeds file length=%d in %s — trailing content truncated",
          line_end, len(original_lines), original_path,
      )
  ```
  **Priority**: Critical (can silently corrupt patched files)

- **[Major]** `cleanup_overlay` uses `shutil.rmtree` which can fail on read-only files (common in `.git` directories). The code filters `.git` during `materialize_overlay` but if any other read-only files exist, cleanup silently fails. Consider `shutil.rmtree(path, ignore_errors=True)` or `onerror` handler.

  **Priority**: Major

- **[Minor]** `materialize_overlay` copies the entire repo tree excluding `.git`. For large repos this is slow. Consider using `os.link` (hardlinks) for read-only files to save disk and time.

  **Priority**: Minor (performance)

**Architecture**: Clean separation of overlay creation, patching, and cleanup.

**Security**: Overlay is in a temp directory with a unique prefix. Fine.

**Performance**: Full repo copy is the bottleneck. Hardlinks would help.

---

### 11. `vsevals/vsevals/scorer.py` (689 lines)

**Purpose**: Scoring pipeline with constraint-based binary scoring and legacy weighted mode. Ensemble judge support.

**Code quality**: Good. Complex but well-documented.

**Bugs & Issues**:

- **[Major]** `_merge_constraint_verdicts` uses majority voting for ensemble judges. With an even number of judges, ties are broken by the order of judge responses (first judge wins). This should be documented or use a deterministic tie-breaking rule.

  **Priority**: Major

- **[Minor]** `_synthetic_constraints` generates constraints from task oracle fields. If the oracle is missing (empty dict), this returns an empty list, and the score defaults to 0.0. This is correct behavior but should be documented as intentional.

  **Priority**: Minor

- **[Minor]** The scorer catches broad `Exception` in the judge call and returns a failed constraint result. This is correct for robustness but means a bug in the judge prompt formatting would silently produce zero scores rather than failing loudly.

  **Priority**: Minor

**Architecture**: Clean pipeline. Constraint mode is the primary path; legacy weighted mode is a fallback.

**Security**: Judge model calls use the same API key management as the main LLM calls. Fine.

**Performance**: Ensemble judging multiplies API calls. Cost is documented in CLAUDE.md.

---

### 12. `vsevals/vsevals/pytest_runner.py` (235 lines)

**Purpose**: Docker primitives for pytest execution.

**Code quality**: Good. Clean subprocess management.

**Bugs & Issues**:

- **[Minor]** `start_test_container` uses `docker run` with `--network none`. This is correct for isolation but means any test that needs network (even localhost) will fail silently. A comment documenting this constraint would help.

  **Priority**: Minor

- **[Minor]** `run_pytest_in_docker` parses pytest exit codes but does not handle exit code 5 (no tests collected due to import error) distinctly from exit code 1 (test failures). Both are treated as failures.

  **Priority**: Minor

- **[Minor]** `stop_test_container` catches all exceptions from `docker stop` and logs them. This is correct for cleanup but `docker rm` is not called — if the container name is reused, the next run could fail.

  **Priority**: Minor

**Architecture**: Clean. Low-level Docker operations.

**Security**: `--network none` is a good isolation measure. Bind-mount is to a temp overlay.

**Performance**: Docker startup overhead (~1-2s) is acceptable.

---

### 13. `vsevals/vsevals/providers/__init__.py` (107 lines)

**Purpose**: Shared parsing utilities: `_parse_payload` (JSON extraction with balanced brace scanning), `_safe_response_json`, `_int_or_none`.

**Code quality**: Good. The balanced brace scanner is well-implemented.

**Bugs & Issues**:

- **[Minor]** `_parse_payload` uses balanced brace scanning as a fallback when `json.loads` fails on the full output. This is correct but the scanner does not handle JSON strings containing `{` or `}` characters. For typical LLM output this rarely matters, but edge cases exist.

  **Priority**: Minor

- **[Minor]** `_safe_response_json` catches `Exception` broadly. A `MemoryError` would be swallowed.

  **Priority**: Minor

**Architecture**: Utility module. Fine.

**Security**: No concerns.

**Performance**: Brace scanning is O(n) which is fine.

---

### 14. `vsevals/vsevals/providers/claudecode.py` (600 lines)

**Purpose**: Claude Code CLI provider with 3-stage pipeline (build invocation, execute+persist, parse). Stream JSON parser, sidecar file writing, MCP config.

**Code quality**: Good. Complex but well-structured.

**Bugs & Issues**:

- **[Verified Fixed]** `plugin_dir` now correctly points to `str(Path(_sidecar_dir_cleanup) / "skills")` (line ~421). Claude Code expects `{plugin-dir}/{skill-name}/SKILL.md`. This was the known issue from CLAUDE.md and is confirmed fixed.

- **[Major]** The stream JSON parser processes stdout line-by-line. If Claude Code emits a JSON object split across multiple lines (which the `--output-format stream-json` mode can do), the parser would fail to parse it. The code handles this by accumulating lines, but the accumulation logic resets on any valid JSON parse. If a partial JSON object is followed by a non-JSON line (e.g., a warning), the partial object is silently dropped.

  **Priority**: Major

- **[Minor]** `_write_sidecar_files` creates the temp directory but does not set restrictive permissions. On a shared system, another user could read sidecar file contents (which may include prompt snippets).

  **Priority**: Minor (security, low risk on single-user dev machines)

- **[Minor]** Subprocess timeout is set but if Claude Code hangs on a tool call, the timeout applies to the entire subprocess, not individual operations. A single slow MCP call could consume the entire budget.

  **Priority**: Minor

**Architecture**: Clean 3-stage pipeline. Good separation of concerns.

**Security**: Sidecar files in temp dirs. Subprocess runs with user permissions.

**Performance**: Subprocess startup + IPC overhead is the main cost.

---

### 15. `vsevals/vsevals/providers/codex.py` (578 lines)

**Purpose**: Codex CLI provider with 3-stage pipeline. HarnessMCPServer integration, skills/ to .agents/skills/ mapping.

**Code quality**: Good. Similar structure to claudecode.py.

**Bugs & Issues**:

- **[Critical]** Fragment injection: Codex sometimes returns method body without `def` header (known issue from CLAUDE.md). The provider does not attempt to detect or fix this. When the harness splices a fragment at the task's line range, it produces an `IndentationError` or `TypeError` in pytest. The fix would be to detect fragments missing a `def` line and prepend the original function signature.

  ```python
  # Detection heuristic:
  code = parsed_output.code
  if code.strip() and not code.strip().startswith(("def ", "class ", "async def ")):
      # Check if the original target starts with a function definition
      # and prepend it if missing
      ...
  ```
  **Priority**: Critical (causes systematic pytest failures for codex direct-mode variants)

- **[Minor]** The `.agents/skills/` mapping writes `SKILL.md` into a codex-specific directory structure. If the codex CLI changes its discovery path, this breaks silently.

  **Priority**: Minor

- **[Minor]** `_build_codex_invocation` constructs the command line but does not validate that the `codex` binary exists on PATH before attempting to run it. The error would be a confusing `FileNotFoundError` rather than a clear message.

  **Priority**: Minor

**Architecture**: Mirrors claudecode.py structure. Good consistency.

**Security**: Same considerations as claudecode.py.

**Performance**: Same subprocess model as claudecode.py.

---

### 16. `vsevals/vsevals/providers/openai.py` (191 lines)

**Purpose**: OpenAI SDK provider with chat completions and Responses API + MCP paths.

**Code quality**: Good. Clean SDK usage.

**Bugs & Issues**:

- **[Minor]** The Responses API path (`use_responses_api=True`) is used when tool schemas are provided. This is correct for MCP but the fallback to chat completions does not propagate tool schemas, meaning tool-enabled variants silently lose tool access if the Responses API flag is not set.

  **Priority**: Minor

- **[Minor]** `max_tokens` is passed directly from config. If not set, the OpenAI SDK default applies, which may be too low for large code generation tasks.

  **Priority**: Minor

**Architecture**: Clean. Single provider file.

**Security**: API key passed via SDK client constructor. Not logged.

**Performance**: Fine.

---

### 17. `vsevals/vsevals/providers/anthropic_provider.py` (147 lines)

**Purpose**: Anthropic SDK provider with tool loop and extended thinking support.

**Code quality**: Good. Clean implementation.

**Bugs & Issues**:

- **[Minor]** The tool loop has a hardcoded max iteration count (10) separate from the `max_tool_turns` parameter. If `max_tool_turns > 10`, the loop exits early.

  **Priority**: Minor

- **[Minor]** Extended thinking is enabled by checking `model_id` for `"think"` substring. This is fragile — future model names may not follow this convention.

  **Priority**: Minor

**Architecture**: Clean. Standard Anthropic SDK usage.

**Security**: Fine.

**Performance**: Fine.

---

### 18. `vsevals/vsevals/providers/mock.py` (42 lines)

**Purpose**: Mock provider stub for tests.

**Code quality**: Minimal but correct.

**Bugs & Issues**:

- **[Minor]** The mock returns a hardcoded `GeneratedPayload` with `code="# mock output"`. This is fine for smoke tests but means any test checking for non-trivial code output would fail with mock.

  **Priority**: Minor

**Architecture**: Fine.

---

### 19. `vsevals/vsevals/exporters/__init__.py`

**Purpose**: Package marker.

**Issues**: None.

---

### 20. `vsevals/vsevals/exporters/csv_mapper.py` (753 lines)

**Purpose**: Maps RunResult to flat CSV rows. 126 canonical columns.

**Code quality**: Good but very long. The column list is comprehensive.

**Bugs & Issues**:

- **[Major]** `CANONICAL_COLUMNS` is a hardcoded list of 126 column names. Adding a new field to RunResult requires updating this list manually. If forgotten, the new field is silently omitted from CSV output. A programmatic approach (e.g., deriving columns from the RunResult model) would be more maintainable.

  **Priority**: Major

- **[Minor]** `result_to_row` uses `getattr` with default values extensively. If a RunResult field is renamed, the getter silently returns the default instead of raising an error.

  **Priority**: Minor

- **[Minor]** `classify_exc` has the same fragile substring-matching pattern as `runner._classify_error`. These should be consolidated.

  **Priority**: Minor (DRY violation)

**Architecture**: Single-purpose mapper. Fine.

**Security**: No concerns.

**Performance**: Fine for typical run counts (~hundreds of rows).

---

### 21. `vsevals/vsevals/exporters/report_writer.py` (85 lines)

**Purpose**: Writes summary and matrix report in markdown format.

**Code quality**: Good. Simple and focused.

**Bugs & Issues**:

- **[Minor]** `_write_matrix_report` generates a markdown table but does not escape `|` characters in cell values. If a model name or task name contains `|`, the table breaks.

  **Priority**: Minor

**Architecture**: Fine.

---

### 22. `vsevals/vsevals/exporters/scoreboard.py` (99 lines)

**Purpose**: Live ANSI scoreboard for matrix evaluation.

**Code quality**: Good. Nice terminal UI.

**Bugs & Issues**:

- **[Minor]** Uses `\033[` escape codes directly. On Windows terminals without ANSI support, this produces garbled output. Consider using `colorama` or checking `sys.stdout.isatty()`.

  **Priority**: Minor

**Architecture**: Fine.

---

### 23. `vsevals/vsevals/exporters/concurrency.py` (38 lines)

**Purpose**: ProviderThrottle with per-provider semaphores and stagger.

**Code quality**: Good. Clean asyncio-compatible design.

**Bugs & Issues**: None significant.

**Architecture**: Fine.

---

### 24. `vsevals/scripts/run_matrix.py` (291 lines)

**Purpose**: Matrix runner script. Threading, resume support, CSV generation.

**Code quality**: Good. Clean threading model.

**Bugs & Issues**:

- **[Major]** Resume logic uses `load_completed()` from csv_mapper to check which cells are already done. But the check is by `(task_id, variant_id, model_name)` tuple. If a previous run errored, resume would skip it (treating the error row as "completed"). The fix would be to only treat `status=ok` rows as completed.

  **Priority**: Major

- **[Minor]** Thread pool uses `ThreadPoolExecutor` with no explicit max workers. The default (`min(32, os.cpu_count() + 4)`) may be too many for API-bound work.

  **Priority**: Minor

**Architecture**: Clean. Good separation of matrix generation and execution.

**Security**: No concerns.

**Performance**: Thread-based parallelism is appropriate for I/O-bound LLM calls.

---

### 25. `vsevals/scripts/rescore_scoring.py` (710 lines)

**Purpose**: Post-hoc LLM judge rescoring with parallel workers, checkpointing, rate limiting.

**Code quality**: Good. Complex but well-structured.

**Bugs & Issues**:

- **[Major]** Silently skips LLM judge if API keys are not set (known issue from CLAUDE.md). The symptom is all scores being 0.000 with latency=0ms. The script should fail fast with a clear error message if no API keys are available for the configured judge model.

  ```python
  # Add at startup:
  if not any(os.environ.get(k) for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY")):
      print("ERROR: No API keys found. Set OPENAI_API_KEY and/or ANTHROPIC_API_KEY.", file=sys.stderr)
      sys.exit(1)
  ```
  **Priority**: Major

- **[Minor]** Rate limiting uses `time.sleep()` between batches. This is correct but a token bucket or sliding window would be more accurate for bursty workloads.

  **Priority**: Minor

- **[Minor]** Checkpoint files are written as JSON. If the script crashes mid-write, the checkpoint file may be corrupted. Consider writing to a temp file and renaming atomically.

  **Priority**: Minor

**Architecture**: Good. Checkpointing is a nice touch.

**Security**: API keys from environment. Fine.

**Performance**: Parallel workers with rate limiting is appropriate.

---

### 26. `vsevals/scripts/rescore_pytest.py` (517 lines)

**Purpose**: Post-hoc pytest runner with Docker overlay.

**Code quality**: Good.

**Bugs & Issues**:

- **[Minor]** Duplicates the overlay creation logic from `runner.py`'s `_run_patch_and_test`. Consider extracting a shared helper.

  **Priority**: Minor (DRY violation)

- **[Minor]** Docker image name is configurable but defaults to `moltsnip-pytest:latest`. If the image doesn't exist, the error message from Docker is cryptic.

  **Priority**: Minor

**Architecture**: Good. Mirrors the runner's patch+test flow.

---

### 27. `vsevals/scripts/run_pytest_phase.py` (483 lines)

**Purpose**: Phase-2 pytest runner (alternative to rescore_pytest).

**Code quality**: Good. Similar structure to rescore_pytest.

**Bugs & Issues**:

- **[Minor]** Significant code duplication with `rescore_pytest.py`. These two scripts share ~60% of their logic. Consider a shared base module.

  **Priority**: Minor (DRY violation)

**Architecture**: Fine but duplicative.

---

### 28. `vsevals/scripts/seed_snippets.py` (160 lines)

**Purpose**: Seeds VoltSnip fixture snippets via HTTP POST.

**Code quality**: Good. Clean HTTP client usage.

**Bugs & Issues**:

- **[Minor]** Uses `urllib.request` directly rather than `httpx` (which is already a project dependency). Inconsistent with `client.py`.

  **Priority**: Minor

- **[Minor]** No retry logic for snippet seeding. If the VoltSnip backend is slow to start, seeding fails immediately.

  **Priority**: Minor

**Architecture**: Fine. Single-purpose script.

**Security**: Posts to localhost. Fine.

---

### 29. `vsevals/scripts/build_matrix_csv.py` (161 lines)

**Purpose**: Builds CSV from completed.jsonl + full_dump.json artifacts. Multi-rep aggregation.

**Code quality**: Good.

**Bugs & Issues**:

- **[Minor]** Reads `full_dump.json` files which can be large (10-50KB each). For matrices with thousands of runs, this could use significant memory. Consider streaming.

  **Priority**: Minor

**Architecture**: Fine.

---

### 30. `vsevals/scripts/build_paper.py` (944 lines)

**Purpose**: Paper build script: computes numbers from run data, generates matplotlib figures, updates paper.tex, compiles PDF.

**Code quality**: Good for a one-off research script. Long but well-organized with section comments.

**Bugs & Issues**:

- **[Minor]** Hardcoded file paths to specific matrix run directories. These should be configurable via CLI arguments.

  **Priority**: Minor

- **[Minor]** LaTeX compilation errors are caught and logged but the script continues. A failed compilation should be treated as a fatal error.

  **Priority**: Minor

- **[Minor]** Figure generation uses matplotlib with hardcoded style parameters. No style sheet or theme configuration.

  **Priority**: Minor

**Architecture**: Monolithic but acceptable for a research paper build script.

**Security**: No concerns.

**Performance**: Fine.

---

### 31. `vsevals/scripts/validate_artifacts.py` (646 lines)

**Purpose**: Comprehensive artifact validator for run directories. Cross-validates all JSON artifacts against each other.

**Code quality**: Excellent. Very thorough validation logic. Well-structured with Check/RunReport dataclasses.

**Bugs & Issues**:

- **[Minor]** `validate_run` is marked `# noqa: C901` (too complex). This is acknowledged — the function is long but intentionally comprehensive.

  **Priority**: Minor

- **[Minor]** The matrix-level validator loads all CSV rows into memory at once. For very large matrices this could be slow.

  **Priority**: Minor

**Architecture**: Excellent. Clean check/report pattern.

**Security**: Read-only validation. No concerns.

**Performance**: Fine for typical artifact sizes.

---

### 32. `vsevals/scripts/matrix_insights.py` (577 lines)

**Purpose**: Extracts insights from matrix_results.csv. Computes per-variant pass rates, tool signal, cost analysis.

**Code quality**: Good. Comprehensive analysis.

**Bugs & Issues**:

- **[Minor]** `avg` function filters `v == v` (NaN check). This is a valid Python idiom but non-obvious. A comment would help.

  **Priority**: Minor

- **[Minor]** `find_latest_csv` searches hardcoded directory names. These should be configurable.

  **Priority**: Minor

**Architecture**: Good. Clean separation of data loading, analysis, and formatting.

---

### 33. `vsevals/scripts/analyze_retrieval_quality.py` (250 lines)

**Purpose**: Computes per-variant retrieval quality metrics (recall, precision, full-coverage rate).

**Code quality**: Good. Clear metrics computation.

**Bugs & Issues**:

- **[Minor]** Hardcoded `HAIKU_DIRS` and `CODEX_DIRS` lists with specific matrix directory timestamps. These should be configurable via CLI or a config file.

  **Priority**: Minor

- **[Minor]** Duplicates `safe_int`, `safe_float` helpers that also exist in `matrix_insights.py` and `analyze_tool_calls.py`.

  **Priority**: Minor (DRY violation)

**Architecture**: Fine. Single-purpose analysis script.

---

### 34. `vsevals/scripts/analyze_tool_calls.py` (177 lines)

**Purpose**: Per-variant tool-call summary (mean calls, roundtrips, budget utilization).

**Code quality**: Good.

**Bugs & Issues**:

- **[Minor]** Duplicates `load_csvs`, `safe_int`, `safe_float`, `HAIKU_DIRS`, `CODEX_DIRS` from `analyze_retrieval_quality.py`. These two scripts share ~50% of their boilerplate.

  **Priority**: Minor (DRY violation)

- **[Minor]** Unused `import io` on line 3.

  **Priority**: Minor

**Architecture**: Fine.

---

### 35. `vsevals/scripts/ablation_snippets.py` (99 lines)

**Purpose**: Toggles VoltSnip snippet visibility for ablation experiments via direct SQL.

**Code quality**: Acceptable for a utility script.

**Bugs & Issues**:

- **[Major]** Hardcoded database credentials in `DEFAULT_DB_URL`: `postgresql://user:password@127.0.0.1:5432/voltsnip`. While these are development defaults, the script should read from an environment variable first.

  ```python
  # Before:
  DEFAULT_DB_URL = "postgresql://user:password@127.0.0.1:5432/voltsnip"

  # After:
  DEFAULT_DB_URL = os.environ.get(
      "DATABASE_URL",
      "postgresql://user:password@127.0.0.1:5432/voltsnip"
  )
  ```
  **Priority**: Major (security)

- **[Minor]** SQL queries use string literals directly. While there's no user input injection risk here (the queries are fully static), using parameterized queries would be more consistent with security best practices.

  **Priority**: Minor

**Architecture**: Fine. Simple CRUD operations.

**Security**: Hardcoded credentials (see above).

---

### 36. `vsevals/scripts/interactive_debug_runner.py` (658 lines)

**Purpose**: Interactive single-cell debug runner with runtime tracing via monkey-patching.

**Code quality**: Good. Clean UI abstraction with optional Rich support.

**Bugs & Issues**:

- **[Minor]** Monkey-patching via `setattr` in `install_runtime_tracing` is fragile. If the target functions are renamed or moved, the patches silently fail (no error, just no tracing). Consider asserting the patches were applied.

  **Priority**: Minor

- **[Minor]** `_enable_debugpy` binds to `0.0.0.0` which exposes the debug port to all network interfaces. This should be `127.0.0.1` for security.

  ```python
  # Before:
  debugpy.listen(("0.0.0.0", port))

  # After:
  debugpy.listen(("127.0.0.1", port))
  ```
  **Priority**: Minor (security)

- **[Minor]** The `_ask_int` function accepts negative numbers unless `min_value` is specified. Consider defaulting `min_value=0`.

  **Priority**: Minor

**Architecture**: Good. Clean separation of UI, tracing, and execution.

**Security**: debugpy binding (see above).

---

### 37. `vsevals/scripts/run_integration_test.py` (529 lines)

**Purpose**: End-to-end integration test. Brings up VoltSnip backend, seeds snippets, runs eval, validates artifacts.

**Code quality**: Good. Well-structured with clear step numbering.

**Bugs & Issues**:

- **[Minor]** `start_backend` polls the health endpoint for 60 seconds. If the backend takes longer (first-time Docker image pull), the test fails. Consider a configurable timeout.

  **Priority**: Minor

- **[Minor]** `cleanup` stops the database container but does not remove it (`docker compose down` vs `docker compose stop`). Repeated runs accumulate stopped containers.

  **Priority**: Minor

- **[Minor]** The golden comparison is structural only (key presence). It does not compare score values or code output, which limits its usefulness as a regression test.

  **Priority**: Minor

**Architecture**: Good. End-to-end test with proper setup/teardown.

**Security**: Uses local Docker. Fine.

---

## Cross-File Analysis

### 1. Error Classification Duplication
`runner.py::_classify_error` and `csv_mapper.py::classify_exc` implement the same error classification logic with different implementations. These should be consolidated into a single function in `models.py` or a shared `errors.py` module.

### 2. DRY Violations in Analysis Scripts
`analyze_retrieval_quality.py`, `analyze_tool_calls.py`, and `matrix_insights.py` duplicate:
- CSV loading logic (`load_csvs`)
- Safe type conversion helpers (`safe_int`, `safe_float`)
- Hardcoded run directory lists (`HAIKU_DIRS`, `CODEX_DIRS`)

Extract a shared `analysis_utils.py` module.

### 3. Overlay/Patch Code Duplication
`rescore_pytest.py` and `run_pytest_phase.py` both re-implement the overlay creation + patch + pytest flow from `runner.py`. Extract a shared `patch_and_test` module.

### 4. Sidecar File Path Conventions
`claudecode.py` uses `tmpdir/skills/{skill-name}/SKILL.md` while `codex.py` uses `.agents/skills/{skill-name}/SKILL.md`. Both conventions are correct for their respective CLIs but are hardcoded. If either CLI changes its discovery path, the mapping breaks silently. Consider extracting path conventions into a configuration.

### 5. Provider Consistency
The five providers (claudecode, codex, openai, anthropic, mock) have different interfaces:
- claudecode/codex: subprocess-based, return tool traces in stdout
- openai/anthropic: SDK-based, tool traces in response objects
- mock: returns canned data

The `dispatch.py` layer handles this well, but the tool trace formats differ slightly between providers. Consider a normalization step.

### 6. Hardcoded Credentials
`ablation_snippets.py` has hardcoded DB credentials. `run_integration_test.py` has hardcoded DB URL. Both should prefer environment variables.

---

## Full Priority Fix List

### Critical (2)

| # | File | Issue | Fix |
|---|------|-------|-----|
| 1 | `patching.py` | `apply_line_range_rewrite` silently truncates files when `line_end` exceeds file length | Add warning log when `line_end > len(original_lines)` |
| 2 | `codex.py` | Fragment injection — Codex returns method body without `def` header, causing systematic pytest failures | Detect missing function signature and prepend from original file |

### Major (11)

| # | File | Issue | Fix |
|---|------|-------|-----|
| 3 | `models.py` | `compute_cost` returns 0.0 silently for unknown models | Add warning log for missing pricing entries |
| 4 | `prompt.py` | Inline guide strings diverge from file-based guides | Read guides from files in all code paths |
| 5 | `runner.py` | `.env` parser does not strip quotes from values | Strip `"` and `'` from parsed values |
| 6 | `client.py` | Retry catches all `Exception` including non-retriable errors | Narrow catch to `httpx.HTTPStatusError`, `ConnectError`, `TimeoutException` |
| 7 | `harness_tools.py` | Path traversal check uses flawed `str.startswith` | Use `Path.is_relative_to()` |
| 8 | `scorer.py` | Ensemble tie-breaking is non-deterministic with even judge count | Document or implement deterministic tie-breaking |
| 9 | `csv_mapper.py` | 126 hardcoded column names diverge from RunResult model | Derive columns programmatically or add a CI check |
| 10 | `run_matrix.py` | Resume treats errored runs as "completed" | Only skip `status=ok` rows on resume |
| 11 | `rescore_scoring.py` | Silently skips scoring when API keys are missing | Fail fast with clear error message |
| 12 | `ablation_snippets.py` | Hardcoded database credentials | Read from `DATABASE_URL` environment variable |
| 13 | `claudecode.py` | Stream parser silently drops partial JSON objects | Accumulate and log dropped fragments |

### Minor (23)

| # | File | Issue |
|---|------|-------|
| 14 | `models.py` | `parse_model` does not validate non-empty model_id |
| 15 | `loader.py` | No schema validation on task YAML files |
| 16 | `loader.py` | Non-existent `repo_root` fails silently |
| 17 | `prompt.py` | No validation of `context_surface` value |
| 18 | `prompt.py` | String concatenation in Builder (stylistic) |
| 19 | `runner.py` | `_classify_error` fragile substring matching |
| 20 | `runner.py` | `.venv` copy in overlay is slow for large envs |
| 21 | `runner.py` | `globals()` injection for convenience wrappers |
| 22 | `dispatch.py` | `call_llm`/`call_judge` duplication |
| 23 | `dispatch.py` | `harness_tool_schemas` static list |
| 24 | `client.py` | `preflight_check` swallows all errors |
| 25 | `harness_tools.py` | `grep_files` no result size limit |
| 26 | `harness_mcp.py` | Hardcoded port (collision risk) |
| 27 | `harness_mcp.py` | Missing `id` field in some JSON-RPC error responses |
| 28 | `patching.py` | Full repo copy (performance) |
| 29 | `patching.py` | `cleanup_overlay` fails on read-only files |
| 30 | `pytest_runner.py` | Exit code 5 not distinguished from code 1 |
| 31 | `providers/__init__.py` | Brace scanner ignores braces in strings |
| 32 | `codex.py` | No check for `codex` binary on PATH |
| 33 | `anthropic_provider.py` | Hardcoded max iteration count (10) |
| 34 | `report_writer.py` | Markdown table does not escape `|` in values |
| 35 | `analyze_tool_calls.py` | Unused `import io` |
| 36 | `interactive_debug_runner.py` | debugpy binds to `0.0.0.0` instead of `127.0.0.1` |

---

## Architectural Recommendations

1. **Extract shared analysis utilities**: Create `scripts/analysis_utils.py` with `load_csvs`, `safe_int`, `safe_float`, `SIGNAL_BUGS`, run directory constants. Used by `matrix_insights.py`, `analyze_retrieval_quality.py`, `analyze_tool_calls.py`.

2. **Extract shared patch+test module**: Create `vsevals/patch_and_test.py` with the overlay creation + patching + pytest execution flow. Used by `runner.py`, `rescore_pytest.py`, `run_pytest_phase.py`.

3. **Consolidate error classification**: Move `_classify_error` to `models.py` or a new `errors.py`. Remove the duplicate in `csv_mapper.py`.

4. **Add provider path configuration**: Extract sidecar file path conventions (skills/, .agents/skills/) into a per-provider config dict rather than hardcoding in each provider.

5. **Add schema validation for task YAMLs**: Validate task YAML files against a Pydantic model at load time rather than failing deep in the pipeline.
