# Validation README: Script30 Consistency + Provider Parity

Run these from repo root:

```bash
cd /Users/srinivasvaddi/moltsnip
```

## 1) Syntax / import sanity

```bash
uv run --project vsevals python -m py_compile \
  vsevals/vsevals/prompt.py \
  vsevals/vsevals/runner.py \
  vsevals/vsevals/models.py \
  vsevals/vsevals/dispatch.py \
  vsevals/vsevals/harness_mcp.py \
  vsevals/vsevals/providers/codex.py \
  vsevals/vsevals/providers/claudecode.py \
  vsevals/vsevals/pytest_runner.py \
  vsevals/scripts/matrix_insights.py \
  vsevals/scripts/validate_artifacts.py \
  vsevals/scripts/interactive_debug_runner.py \
  vsevals/scripts/rescore_pytest.py \
  vsevals/scripts/run_pytest_phase.py
```

Expected: no output and exit code 0.

## 2) Suite/task integrity (BUG41..BUG70)

```bash
uv run --project vsevals python - <<'PY'
from pathlib import Path
import yaml, json
root = Path('/Users/srinivasvaddi/moltsnip/vsevals')
suite = yaml.safe_load((root/'suites'/'script30.yaml').read_text())
paths = [(root/'suites'/p).resolve() for p in suite['task_files']]
keys = {json.loads(p.read_text()).get('canonical_key') for p in (root/'snippets'/'script30').glob('*.json')}
keys.discard(None)
issues = []
for tp in paths:
    d = yaml.safe_load(tp.read_text())
    row = d['tasks'][0]
    t = row['task']
    v = row['voltsnip']
    tid = t['id']
    cat = t['category']
    target = root/'usecases'/'script30'/t['target_file']
    req = v.get('required_snippets') or []
    if not target.exists():
        issues.append(f"{tid}: missing target {target}")
    if any(k not in keys for k in req):
        missing = [k for k in req if k not in keys]
        issues.append(f"{tid}: missing snippets {missing}")
    expected_cat = f"voltsnip/script30/category/{cat}/guiding_principle/v1"
    if expected_cat not in req:
        issues.append(f"{tid}: missing category key {expected_cat}")
print('issue_count=', len(issues))
for x in issues:
    print(x)
PY
```

Expected: `issue_count= 0`.

## 3) Variant loading sanity

```bash
uv run --project vsevals python - <<'PY'
from vsevals.loader import load_suite
s = load_suite('/Users/srinivasvaddi/moltsnip/vsevals/suites/script30.yaml')
print('variants=', [v.id for v in s.variants])
print('tasks=', len(s.tasks))
PY
```

Expected:
- `variants= ['P0', 'P1', 'P2', 'P3', 'P4', 'P5', 'P6']`
- `tasks= 30`

## 4) Prompt no-key behavior sanity (P4/P5/P6)

```bash
uv run --project vsevals python - <<'PY'
from vsevals.loader import load_suite
from vsevals.prompt import build_prompt
s = load_suite('/Users/srinivasvaddi/moltsnip/vsevals/suites/script30.yaml')
t = s.task_map['BUG41']
for vid in ['P4','P5','P6']:
    v = s.variant_map[vid]
    pb = build_prompt(task=t, variant=v, retrieved_snippets=[], repo_policy_text=None, target_file_content=None)
    print(vid, 'listed_key_phrase_in_user=', 'listed Guiding Snippet Keys' in pb.user_prompt)
PY
```

Expected for each of `P4/P5/P6`: `listed_key_phrase_in_user= False`.

## 5) Codex/Claude provider parity sanity

```bash
uv run --project vsevals python - <<'PY'
from pathlib import Path
from vsevals.models import RunConfig
from vsevals.providers.codex import _build_codex_invocation
from vsevals.providers.claudecode import _build_claudecode_invocation
cfg = RunConfig()
repo = '/Users/srinivasvaddi/moltsnip/vsevals/usecases/script30'
schemas = [{'type':'function','function':{'name':'search_memory','parameters':{'type':'object','properties':{'query':{'type':'string'}}}}}]
cinv = _build_claudecode_invocation(model_id='claude-haiku-4-5', combined_prompt='hi', cfg=cfg, tool_schemas=schemas, sidecar_files={'AGENTS.md':'x'}, timeout=10, repo_root=repo)
co = _build_codex_invocation(model_id='gpt-5.3-codex', combined_prompt='hi', cfg=cfg, tool_schemas=schemas, sidecar_files={'AGENTS.md':'x'}, timeout=10, run_dir=Path('/tmp'), repo_root=repo)
print('claude_has_search_memory=', any('mcp__voltsnip__search_memory' in x for x in cinv.cmd))
print('claude_has_get_by_key=', any('mcp__voltsnip__get_snippet_by_canonical_key' in x for x in cinv.cmd))
print('codex_uses_voltsnip_server_label=', any('mcp_servers.voltsnip.command=curl' in x for x in co.cmd))
print('codex_uses_harness_server_label=', any('mcp_servers.harness.command=curl' in x for x in co.cmd))
cinv.cleanup(); co.cleanup()
PY
```

Expected:
- `claude_has_search_memory= True`
- `claude_has_get_by_key= True`
- `codex_uses_voltsnip_server_label= True`
- `codex_uses_harness_server_label= False`

## 6) Optional smoke test for pytest rerun path

If you want to verify the fixed pytest runner path quickly:

```bash
uv run --project vsevals python vsevals/scripts/rescore_pytest.py \
  --matrix-dir /Users/srinivasvaddi/moltsnip/vsevals/vsevals_runs_clean/matrix_20260302T050545698715Z \
  --suite /Users/srinivasvaddi/moltsnip/vsevals/suites/script30.yaml \
  --tasks BUG41 \
  --variants P3 \
  --force \
  --pytest-docker-image moltsnip-hybrid-pytest:latest \
  --workers 1 \
  --log-level INFO
```

Expected: one row rescored; pytest executes in docker without `pytest not found` path failure.

## 7) Interactive runner smoke test (standalone script)

```bash
cd /Users/srinivasvaddi/moltsnip/vsevals
printf 'n\n\n\ny\n' | uv run scripts/interactive_debug_runner.py \
  --suite suites/script30.yaml \
  --task BUG41 \
  --variant P0 \
  --model mock:echo \
  --skip-scoring \
  --log-level INFO
```

Expected:
- Prints stage-by-stage trace (`ARTIFACTS`, `VOLTSNIP`, `PROMPT`, `DISPATCH`).
- Produces run artifacts under `vsevals_runs/interactive_debug/`.
- Exits `status=ok` with no harness file modifications.
