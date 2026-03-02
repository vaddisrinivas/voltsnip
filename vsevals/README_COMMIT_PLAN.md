# Commit Plan: Script30 Consistency + Provider Parity

## Commit A (pytest infra fixes from this run series)

Use this commit if you want to include the pytest rerun/rescore reliability fixes.

Files:
- `vsevals/scripts/rescore_pytest.py`
- `vsevals/scripts/run_pytest_phase.py`
- `vsevals/vsevals/pytest_runner.py`

Suggested commands:
```bash
git add \
  vsevals/scripts/rescore_pytest.py \
  vsevals/scripts/run_pytest_phase.py \
  vsevals/vsevals/pytest_runner.py

git commit -m "Fix pytest rescore container parity and command execution"
```

## Commit B (script30 data/config consistency + codex/claude parity)

Files:
- `vsevals/tasks/script30/BUG43.yaml`
- `vsevals/tasks/script30/BUG45.yaml`
- `vsevals/tasks/script30/BUG46.yaml`
- `vsevals/tasks/script30/BUG48.yaml`
- `vsevals/tasks/script30/BUG59.yaml`
- `vsevals/tasks/script30/BUG60.yaml`
- `vsevals/tasks/script30/BUG61.yaml`
- `vsevals/tasks/script30/BUG65.yaml`
- `vsevals/tasks/script30/BUG68.yaml`
- `vsevals/skills/concurrency_cache.md`
- `vsevals/skills/db_patterns.md`
- `vsevals/skills/error_contracts.md`
- `vsevals/skills/http_resilience.md`
- `vsevals/skills/logging_privacy.md`
- `vsevals/agents/concurrency_cache.md`
- `vsevals/agents/db_patterns.md`
- `vsevals/agents/error_contracts.md`
- `vsevals/agents/http_resilience.md`
- `vsevals/agents/logging_privacy.md`
- `vsevals/vsevals/__init__.py`
- `vsevals/vsevals/models.py`
- `vsevals/vsevals/prompt.py`
- `vsevals/vsevals/runner.py`
- `vsevals/vsevals/dispatch.py`
- `vsevals/vsevals/harness_mcp.py`
- `vsevals/vsevals/providers/codex.py`
- `vsevals/vsevals/providers/claudecode.py`

Suggested commands:
```bash
git add \
  vsevals/tasks/script30/BUG43.yaml \
  vsevals/tasks/script30/BUG45.yaml \
  vsevals/tasks/script30/BUG46.yaml \
  vsevals/tasks/script30/BUG48.yaml \
  vsevals/tasks/script30/BUG59.yaml \
  vsevals/tasks/script30/BUG60.yaml \
  vsevals/tasks/script30/BUG61.yaml \
  vsevals/tasks/script30/BUG65.yaml \
  vsevals/tasks/script30/BUG68.yaml \
  vsevals/skills/concurrency_cache.md \
  vsevals/skills/db_patterns.md \
  vsevals/skills/error_contracts.md \
  vsevals/skills/http_resilience.md \
  vsevals/skills/logging_privacy.md \
  vsevals/agents/concurrency_cache.md \
  vsevals/agents/db_patterns.md \
  vsevals/agents/error_contracts.md \
  vsevals/agents/http_resilience.md \
  vsevals/agents/logging_privacy.md \
  vsevals/vsevals/__init__.py \
  vsevals/vsevals/models.py \
  vsevals/vsevals/prompt.py \
  vsevals/vsevals/runner.py \
  vsevals/vsevals/dispatch.py \
  vsevals/vsevals/harness_mcp.py \
  vsevals/vsevals/providers/codex.py \
  vsevals/vsevals/providers/claudecode.py

git commit -m "Align script30 snippet keys and enforce codex/claude retrieval parity"
```

## Optional docs commit

Files:
- `vsevals/README_COMMIT_PLAN.md`
- `vsevals/README_VALIDATION.md`
- `vsevals/scripts/README_INTERACTIVE_DEBUG_RUNNER.md`

```bash
git add \
  vsevals/README_COMMIT_PLAN.md \
  vsevals/README_VALIDATION.md \
  vsevals/scripts/README_INTERACTIVE_DEBUG_RUNNER.md
git commit -m "Add commit and validation runbooks for script30 fixes"
```

## Commit C (analysis utilities + standalone interactive debugger)

Files:
- `vsevals/scripts/matrix_insights.py`
- `vsevals/scripts/validate_artifacts.py`
- `vsevals/scripts/run_scale.sh`
- `vsevals/scripts/run_cross_eval.sh`
- `vsevals/scripts/interactive_debug_runner.py`
- `vsevals/scripts/README_INTERACTIVE_DEBUG_RUNNER.md`
- `vsevals/skills.md`

Suggested commands:
```bash
git add \
  vsevals/scripts/matrix_insights.py \
  vsevals/scripts/validate_artifacts.py \
  vsevals/scripts/run_scale.sh \
  vsevals/scripts/run_cross_eval.sh \
  vsevals/scripts/interactive_debug_runner.py \
  vsevals/scripts/README_INTERACTIVE_DEBUG_RUNNER.md \
  vsevals/skills.md

git commit -m "Make analysis scripts variant-agnostic and add interactive debug runner"
```

## Do not commit (generated/noisy)

Avoid adding these unless you intentionally want large artifacts in git:
- `vsevals/vsevals_runs/`
- `vsevals/vsevals_runs_clean/`
- `vsevals_runs/`
- `vsevals_archived/`
- `.claude/`
- `voltsnip-evals/` (if this is local/external workspace content)
