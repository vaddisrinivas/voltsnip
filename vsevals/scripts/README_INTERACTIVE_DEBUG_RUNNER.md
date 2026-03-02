# Interactive Debug Runner

`interactive_debug_runner.py` is a standalone, single-cell runner for deep debugging.
It does **not** modify harness behavior and is kept separate from matrix automation.

## What it gives you

- Interactive selection of `task` (bug), `variant`, and `model`.
- Optional `debugpy` attach/wait support.
- Live stage tracing while `run_one()` executes.
- Visibility into what gets passed to providers (including claudecode/codex command lines).
- Post-run timeline for tool calls, file/path search hints, and artifact locations.

## Run

From `/Users/srinivasvaddi/moltsnip/vsevals`:

```bash
uv run scripts/interactive_debug_runner.py
```

With explicit selections:

```bash
uv run scripts/interactive_debug_runner.py \
  --suite suites/script30.yaml \
  --task BUG55 \
  --variant P6 \
  --model codex:gpt-5.3-codex
```

With debugpy:

```bash
uv run scripts/interactive_debug_runner.py \
  --debugpy --debugpy-port 5678 --wait-for-debugger
```

## Notes

- Use `uv run` so harness dependencies are available.
- Output artifacts go under `vsevals/vsevals_runs/interactive_debug/` by default.
- For fast dry debugging, skip pytest when prompted.
