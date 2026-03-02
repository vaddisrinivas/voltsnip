#!/usr/bin/env python3
"""Interactive single-cell debug runner for vsevals.

Features:
- Interactive selection for task (bug), variant, and model.
- Optional debugpy listener and wait-for-client mode.
- Runtime tracing of key harness stages without modifying harness code.
- Provider-specific launch visibility for claudecode/codex subprocess calls.
- Post-run summary of tool calls and inferred file exploration.

This script is intentionally separate from the core harness.
"""

from __future__ import annotations

import argparse
import json
import logging
import shlex
import sys
import textwrap
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

# Ensure local package import works when run from repo root.
HERE = Path(__file__).resolve().parent.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from vsevals.loader import load_suite
from vsevals.models import RunConfig, SuiteTask, ToolTrace
from vsevals.runner import run_one
import vsevals.runner as runner_mod
import vsevals.providers.claudecode as claudecode_provider
import vsevals.providers.codex as codex_provider

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    HAS_RICH = True
except Exception:
    HAS_RICH = False


@dataclass
class TraceState:
    run_dir: str | None = None
    prompt_snapshots: list[dict[str, Any]] = field(default_factory=list)
    provider_invocations: list[dict[str, Any]] = field(default_factory=list)
    stage_messages: list[str] = field(default_factory=list)


class UI:
    def __init__(self) -> None:
        self.console = Console() if HAS_RICH else None

    def hr(self, title: str = "") -> None:
        if HAS_RICH:
            self.console.rule(f"[bold cyan]{title}[/bold cyan]" if title else "")
        else:
            bar = "=" * 96
            if title:
                print(f"\n{bar}\n{title}\n{bar}")
            else:
                print(f"\n{bar}")

    def info(self, msg: str) -> None:
        if HAS_RICH:
            self.console.print(f"[cyan]INFO[/cyan] {msg}")
        else:
            print(f"INFO {msg}")

    def ok(self, msg: str) -> None:
        if HAS_RICH:
            self.console.print(f"[green]OK[/green] {msg}")
        else:
            print(f"OK {msg}")

    def warn(self, msg: str) -> None:
        if HAS_RICH:
            self.console.print(f"[yellow]WARN[/yellow] {msg}")
        else:
            print(f"WARN {msg}")

    def err(self, msg: str) -> None:
        if HAS_RICH:
            self.console.print(f"[red]ERR[/red] {msg}")
        else:
            print(f"ERR {msg}")

    def step(self, label: str, detail: str = "") -> None:
        if detail:
            self.info(f"[{label}] {detail}")
        else:
            self.info(f"[{label}]")

    def show_text(self, title: str, text: str) -> None:
        if HAS_RICH:
            self.console.print(Panel.fit(text, title=title, border_style="blue"))
        else:
            print(f"\n[{title}]\n{text}\n")

    def show_table(self, title: str, columns: list[str], rows: list[list[str]]) -> None:
        if HAS_RICH:
            table = Table(title=title, show_lines=False)
            for col in columns:
                table.add_column(col)
            for row in rows:
                table.add_row(*row)
            self.console.print(table)
        else:
            print(f"\n{title}")
            print(" | ".join(columns))
            print("-" * 96)
            for row in rows:
                print(" | ".join(row))


def _pick_from_list(ui: UI, title: str, items: list[tuple[str, str]], default_index: int = 0) -> str:
    ui.hr(title)
    rows: list[list[str]] = []
    for idx, (key, label) in enumerate(items, start=1):
        rows.append([str(idx), key, label])
    ui.show_table(title, ["#", "ID", "Description"], rows)

    default_num = str(default_index + 1)
    while True:
        raw = input(f"Select {title} [default {default_num}]: ").strip()
        if not raw:
            raw = default_num
        if raw.isdigit():
            i = int(raw)
            if 1 <= i <= len(items):
                return items[i - 1][0]
        ui.warn(f"Invalid selection: {raw!r}. Enter a number between 1 and {len(items)}")


def _ask_bool(prompt: str, default: bool) -> bool:
    suffix = "Y/n" if default else "y/N"
    raw = input(f"{prompt} [{suffix}]: ").strip().lower()
    if not raw:
        return default
    if raw in {"y", "yes", "1", "true"}:
        return True
    if raw in {"n", "no", "0", "false"}:
        return False
    return default


def _ask_int(prompt: str, default: int, min_value: int | None = None) -> int:
    while True:
        raw = input(f"{prompt} [default {default}]: ").strip()
        if not raw:
            return default
        if raw.isdigit():
            val = int(raw)
            if min_value is None or val >= min_value:
                return val
        print(f"Invalid integer: {raw!r}")


def _ask_optional_str(prompt: str, default: str | None = None) -> str | None:
    suffix = f" [default {default}]" if default else ""
    raw = input(f"{prompt}{suffix}: ").strip()
    if not raw:
        return default
    return raw


def _tool_schema_names(tool_schemas: list[dict[str, Any]] | None) -> list[str]:
    if not tool_schemas:
        return []
    names: list[str] = []
    for item in tool_schemas:
        fn = (item or {}).get("function") or {}
        name = fn.get("name")
        if isinstance(name, str):
            names.append(name)
    return names


def _extract_file_intents(tool_traces: list[ToolTrace]) -> tuple[list[str], list[str], list[str]]:
    paths: list[str] = []
    patterns: list[str] = []
    memory_ops: list[str] = []

    path_keys = ("path", "file_path", "filepath", "file", "target_file")
    patt_keys = ("pattern", "glob", "query", "intent", "regex")

    for trace in tool_traces:
        name = trace.tool_name or ""
        args = trace.tool_args or {}
        if isinstance(args, dict):
            for k in path_keys:
                v = args.get(k)
                if isinstance(v, str) and v.strip():
                    paths.append(v.strip())
            for k in patt_keys:
                v = args.get(k)
                if isinstance(v, str) and v.strip():
                    patterns.append(v.strip())

        lname = name.lower()
        if "search_memory" in lname or "semantic_search" in lname or "snippet" in lname or "canonical" in lname:
            memory_ops.append(name)

    def _uniq(seq: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for s in seq:
            if s not in seen:
                seen.add(s)
                out.append(s)
        return out

    return _uniq(paths), _uniq(patterns), _uniq(memory_ops)


def _event_type_counts(jsonl_path: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    if not jsonl_path.exists():
        return counts
    for ln in jsonl_path.read_text(encoding="utf-8", errors="replace").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            obj = json.loads(ln)
        except Exception:
            continue
        et = obj.get("type") or obj.get("event") or "unknown"
        et = str(et)
        counts[et] = counts.get(et, 0) + 1
    return counts


@contextmanager
def install_runtime_tracing(ui: UI, state: TraceState):
    patches: list[tuple[Any, str, Any]] = []

    def patch_attr(obj: Any, attr: str, wrapper_factory: Callable[[Any], Any]) -> None:
        if not hasattr(obj, attr):
            return
        orig = getattr(obj, attr)
        wrapped = wrapper_factory(orig)
        setattr(obj, attr, wrapped)
        patches.append((obj, attr, orig))

    def wrap_make_artifact_paths(orig):
        def _wrapped(*args, **kwargs):
            out = orig(*args, **kwargs)
            state.run_dir = out.run_dir
            ui.step("ARTIFACTS", f"Run directory: {out.run_dir}")
            return out

        return _wrapped

    def wrap_make_client(orig):
        def _wrapped(*args, **kwargs):
            variant = kwargs.get("variant") if "variant" in kwargs else (args[0] if args else None)
            cfg = kwargs.get("cfg") if "cfg" in kwargs else (args[1] if len(args) > 1 else None)
            vname = getattr(variant, "id", "?")
            base = getattr(cfg, "voltsnip_base_url", None)
            ui.step("VOLTSNIP", f"Client setup for variant={vname} base_url={base or 'default'}")
            client = orig(*args, **kwargs)
            ui.step("VOLTSNIP", "Client ready" if client else "Client not required")
            return client

        return _wrapped

    def wrap_retrieve_snippets(orig):
        def _wrapped(*args, **kwargs):
            task = kwargs.get("task")
            required = list(getattr(getattr(task, "voltsnip", None), "required_snippets", []) or [])
            ui.step("SNIPPETS", f"Pre-fetch start. Required keys: {len(required)}")
            out = orig(*args, **kwargs)
            ui.step("SNIPPETS", f"Pre-fetch complete. Retrieved: {len(out)}")
            return out

        return _wrapped

    def wrap_build_prompt(orig):
        def _wrapped(*args, **kwargs):
            bundle = orig(*args, **kwargs)
            sidecar_names = sorted((bundle.sidecar_files or {}).keys())
            ui.step(
                "PROMPT",
                f"context_surface={bundle.context_surface} system_chars={len(bundle.system_prompt)} "
                f"user_chars={len(bundle.user_prompt)} sidecars={sidecar_names}",
            )
            state.prompt_snapshots.append(
                {
                    "context_surface": bundle.context_surface,
                    "system_chars": len(bundle.system_prompt),
                    "user_chars": len(bundle.user_prompt),
                    "sidecar_files": sidecar_names,
                    "visible_sections": list(bundle.visible_sections or []),
                    "system_preview": bundle.system_prompt[:1000],
                    "user_preview": bundle.user_prompt[:1000],
                }
            )
            return bundle

        return _wrapped

    def wrap_call_llm(orig):
        def _wrapped(*args, **kwargs):
            model_name = kwargs.get("model_name", "")
            tool_names = _tool_schema_names(kwargs.get("tool_schemas"))
            ui.step(
                "DISPATCH",
                f"model={model_name} tools_enabled={bool(tool_names)} max_tool_turns={kwargs.get('max_tool_turns')}",
            )
            if tool_names:
                ui.step("DISPATCH", f"tool schemas: {tool_names}")
            t0 = time.perf_counter()
            out = orig(*args, **kwargs)
            dt_ms = int((time.perf_counter() - t0) * 1000)
            ui.step(
                "DISPATCH",
                f"response latency={dt_ms}ms parsed_tool_traces={len(out.tool_traces)} "
                f"raw_output_chars={len(out.raw_output)}",
            )
            return out

        return _wrapped

    def wrap_build_claudecode_invocation(orig):
        def _wrapped(*args, **kwargs):
            inv = orig(*args, **kwargs)
            state.provider_invocations.append(
                {
                    "provider": "claudecode",
                    "cmd": list(inv.cmd),
                    "cwd": inv.cwd,
                    "timeout": inv.timeout,
                }
            )
            ui.step("CLAUDECODE", f"cwd={inv.cwd or '<none>'} timeout={inv.timeout}s")
            ui.step("CLAUDECODE", f"cmd: {shlex.join(inv.cmd)}")
            return inv

        return _wrapped

    def wrap_build_codex_invocation(orig):
        def _wrapped(*args, **kwargs):
            inv = orig(*args, **kwargs)
            state.provider_invocations.append(
                {
                    "provider": "codex",
                    "cmd": list(inv.cmd),
                    "cwd": inv.cwd,
                    "timeout": inv.timeout,
                }
            )
            ui.step("CODEX", f"cwd={inv.cwd or '<none>'} timeout={inv.timeout}s")
            ui.step("CODEX", f"cmd: {shlex.join(inv.cmd)}")
            return inv

        return _wrapped

    def wrap_execute_claudecode(orig):
        def _wrapped(*args, **kwargs):
            ui.step("CLAUDECODE", "subprocess launch")
            out = orig(*args, **kwargs)
            ui.step("CLAUDECODE", f"subprocess complete returncode={out.returncode}")
            return out

        return _wrapped

    def wrap_execute_codex(orig):
        def _wrapped(*args, **kwargs):
            ui.step("CODEX", "subprocess launch")
            out = orig(*args, **kwargs)
            ui.step("CODEX", f"subprocess complete returncode={out.returncode}")
            return out

        return _wrapped

    patch_attr(runner_mod, "_make_artifact_paths", wrap_make_artifact_paths)
    patch_attr(runner_mod, "_make_client", wrap_make_client)
    patch_attr(runner_mod, "_retrieve_snippets", wrap_retrieve_snippets)
    patch_attr(runner_mod, "build_prompt", wrap_build_prompt)
    patch_attr(runner_mod, "call_llm", wrap_call_llm)

    patch_attr(claudecode_provider, "_build_claudecode_invocation", wrap_build_claudecode_invocation)
    patch_attr(codex_provider, "_build_codex_invocation", wrap_build_codex_invocation)
    patch_attr(claudecode_provider, "_execute_claudecode", wrap_execute_claudecode)
    patch_attr(codex_provider, "_execute_codex", wrap_execute_codex)

    try:
        yield
    finally:
        for obj, attr, orig in reversed(patches):
            setattr(obj, attr, orig)


def _default_suite_path(root: Path) -> Path:
    candidates = [
        root / "suites" / "script30.yaml",
        root / "suite.yaml",
    ]
    for c in candidates:
        if c.exists():
            return c
    raise FileNotFoundError("Could not find suite YAML (expected suites/script30.yaml or suite.yaml)")


def _render_preflight(ui: UI, task: SuiteTask, variant: Any, model_name: str, cfg: RunConfig, suite_path: Path) -> None:
    rows = [
        ["Suite", str(suite_path)],
        ["Task", f"{task.task.id} ({task.task.category})"],
        ["Task name", task.task.name],
        ["Variant", f"{variant.id} | mode={variant.mode} tools={variant.tools_enabled} memory={variant.memory_enabled} surface={variant.context_surface}"],
        ["Model", model_name],
        ["Target", str(task.task.target_file or "<none>")],
        ["Line range", f"{task.task.line_start}-{task.task.line_end}" if task.task.line_start else "full-file"],
        ["Test command", str(task.task.test_command or "<none>")],
        ["Config", f"scoring={'off' if cfg.skip_scoring else cfg.scoring_match_mode} pytest={'on' if cfg.auto_apply_patch else 'off'} llm_timeout={cfg.llm_timeout_seconds}s max_tokens={cfg.max_tokens}"],
        ["VoltSnip URL", str(cfg.voltsnip_base_url or "default")],
    ]
    ui.show_table("Run Plan", ["Field", "Value"], rows)


def _summarize_run(ui: UI, run_result: Any, trace_state: TraceState) -> None:
    ui.hr("Run Summary")

    score_val = None
    if getattr(run_result, "score", None) is not None:
        score_val = f"{run_result.score.overall_score:.3f}"

    pytest_txt = "not-run"
    if getattr(run_result, "pytest_result", None) is not None:
        py = run_result.pytest_result
        if py.ran:
            pytest_txt = f"ran pass={py.passed} exit={py.exit_code}"
        else:
            pytest_txt = f"skipped ({py.error or 'unknown'})"

    rows = [
        ["Run ID", run_result.run_id],
        ["Status", run_result.status],
        ["Run dir", run_result.artifacts.run_dir],
        ["Latency", f"{run_result.summary_metrics.latency_ms} ms"],
        ["Score", score_val or "not-scored"],
        ["Tool traces", str(len(run_result.tool_traces))],
        ["Retrieved snippets", str(len(run_result.retrieved_snippets))],
        ["Pytest", pytest_txt],
    ]
    ui.show_table("Outcome", ["Metric", "Value"], rows)

    if trace_state.prompt_snapshots:
        latest = trace_state.prompt_snapshots[0]
        sys_preview = latest["system_preview"]
        usr_preview = latest["user_preview"]
        ui.show_text("System Prompt Preview (first 1000 chars)", sys_preview)
        ui.show_text("User Prompt Preview (first 1000 chars)", usr_preview)

    if run_result.tool_traces:
        trows: list[list[str]] = []
        for i, t in enumerate(run_result.tool_traces, start=1):
            args_json = json.dumps(t.tool_args or {}, ensure_ascii=False)
            if len(args_json) > 120:
                args_json = args_json[:117] + "..."
            trows.append([
                str(i),
                t.tool_name or "",
                str(t.duration_ms or ""),
                "yes" if not t.error else "no",
                args_json,
            ])
        ui.show_table("Tool Trace Timeline", ["#", "Tool", "ms", "ok", "Args"], trows)

    file_paths, patterns, memory_ops = _extract_file_intents(run_result.tool_traces)
    if file_paths:
        ui.show_text("Files Looked At (from tool args)", "\n".join(file_paths[:80]))
    if patterns:
        ui.show_text("Search Patterns / Queries", "\n".join(patterns[:80]))
    if memory_ops:
        ui.show_text("Memory Tool Ops", "\n".join(memory_ops[:80]))

    run_dir = Path(run_result.artifacts.run_dir)
    provider = run_result.summary_metrics.model_provider
    if provider in {"claudecode", "codex"}:
        jsonl = run_dir / f"subprocess.stdout.{provider}.jsonl"
        counts = _event_type_counts(jsonl)
        if counts:
            rows = [[k, str(v)] for k, v in sorted(counts.items(), key=lambda x: (-x[1], x[0]))]
            ui.show_table(f"{provider} JSONL Event Types", ["type", "count"], rows)

    artifact_rows = []
    for name in [
        "prompt.json",
        "full_dump.json",
        "summary_dump.json",
        "generated_code.txt",
        "generated_comments.txt",
        "score_result.json",
        "pytest.stdout.txt",
        "pytest.stderr.txt",
        "subprocess.stdout.claudecode.jsonl",
        "subprocess.stdout.codex.jsonl",
    ]:
        p = run_dir / name
        if p.exists():
            artifact_rows.append([name, str(p)])
    if artifact_rows:
        ui.show_table("Artifacts", ["File", "Path"], artifact_rows)


def _enable_debugpy(ui: UI, port: int, wait_for_client: bool) -> None:
    import debugpy

    debugpy.listen(("0.0.0.0", port))
    ui.ok(f"debugpy listening on 0.0.0.0:{port}")
    if wait_for_client:
        ui.info("Waiting for debugger client to attach...")
        debugpy.wait_for_client()
        ui.ok("Debugger attached")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Interactive single-run debugger for vsevals")
    parser.add_argument("--suite", default=None, help="Path to suite YAML (default: suites/script30.yaml if present)")
    parser.add_argument("--output-dir", default=None, help="Output root for run artifacts")
    parser.add_argument("--task", default=None, help="Task id to preselect (e.g., BUG55)")
    parser.add_argument("--variant", default=None, help="Variant id to preselect (e.g., P6)")
    parser.add_argument("--model", default=None, help="Model to preselect (e.g., codex:gpt-5.3-codex)")
    parser.add_argument("--voltsnip-url", default=None, help="Override VoltSnip base URL")
    parser.add_argument("--repo-root", default=None, help="Override repo root for this run")
    parser.add_argument("--skip-scoring", action="store_true", default=False, help="Skip LLM scoring")
    parser.add_argument("--run-pytest", action="store_true", default=False, help="Run patch+pytest phase")
    parser.add_argument("--pytest-timeout", type=int, default=300, help="Pytest timeout seconds")
    parser.add_argument("--llm-timeout", type=int, default=300, help="LLM timeout seconds")
    parser.add_argument("--max-tokens", type=int, default=None, help="Max output tokens")
    parser.add_argument("--debugpy", action="store_true", default=False, help="Enable debugpy listener")
    parser.add_argument("--debugpy-port", type=int, default=5678, help="debugpy listen port")
    parser.add_argument("--wait-for-debugger", action="store_true", default=False, help="Wait for debugger client")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING"], help="Python logging level")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    ui = UI()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%H:%M:%S",
    )

    root = Path(__file__).resolve().parent.parent
    suite_path = Path(args.suite).expanduser().resolve() if args.suite else _default_suite_path(root)
    output_root = Path(args.output_dir).expanduser().resolve() if args.output_dir else (root / "vsevals_runs" / "interactive_debug")
    output_root.mkdir(parents=True, exist_ok=True)

    if args.debugpy:
        _enable_debugpy(ui, args.debugpy_port, args.wait_for_debugger)

    ui.hr("Load Suite")
    ui.info(f"Suite: {suite_path}")
    suite = load_suite(str(suite_path))
    ui.ok(f"Loaded suite. tasks={len(suite.tasks)} variants={len(suite.variants)} models={len(suite.models)}")

    task_id = args.task
    if not task_id:
        task_items = [
            (
                t.task.id,
                f"{t.task.name} | category={t.task.category} | file={t.task.target_file}",
            )
            for t in sorted(suite.tasks, key=lambda x: x.task.id)
        ]
        task_id = _pick_from_list(ui, "Task (Bug)", task_items, default_index=0)

    variant_id = args.variant
    if not variant_id:
        var_items = [
            (
                v.id,
                f"mode={v.mode} tools={v.tools_enabled} memory={v.memory_enabled} surface={v.context_surface}",
            )
            for v in suite.variants
        ]
        default_idx = next((i for i, (k, _) in enumerate(var_items) if k == "P6"), 0)
        variant_id = _pick_from_list(ui, "Variant", var_items, default_index=default_idx)

    model_name = args.model
    if not model_name:
        model_items = [(m, m) for m in suite.model_names]
        default_idx = next((i for i, (k, _) in enumerate(model_items) if k.startswith("codex:")), 0)
        model_name = _pick_from_list(ui, "Model", model_items, default_index=default_idx)

    task = suite.task_map[task_id]
    variant = suite.variant_map[variant_id]

    skip_scoring = args.skip_scoring
    run_pytest = args.run_pytest

    if not args.skip_scoring:
        skip_scoring = not _ask_bool("Run scoring phase?", default=True)
    if not args.run_pytest:
        run_pytest = _ask_bool("Run patch+pytest phase?", default=False)

    llm_timeout = args.llm_timeout if args.llm_timeout else _ask_int("LLM timeout seconds", default=300, min_value=10)
    pytest_timeout = args.pytest_timeout if args.pytest_timeout else _ask_int("Pytest timeout seconds", default=300, min_value=1)

    voltsnip_url = args.voltsnip_url
    if voltsnip_url is None:
        voltsnip_url = _ask_optional_str("VoltSnip URL override (blank = harness default)", default=None)

    max_tokens = args.max_tokens
    if max_tokens is None:
        mt = _ask_optional_str("Max output tokens (blank = model default)", default=None)
        max_tokens = int(mt) if mt and mt.isdigit() else None

    cfg = RunConfig(
        voltsnip_base_url=voltsnip_url,
        skip_scoring=skip_scoring,
        auto_apply_patch=run_pytest,
        pytest_timeout_seconds=pytest_timeout,
        llm_timeout_seconds=llm_timeout,
        max_tokens=max_tokens,
    )

    _render_preflight(ui, task, variant, model_name, cfg, suite_path)
    if not _ask_bool("Proceed with run?", default=True):
        ui.warn("Aborted by user")
        return

    trace_state = TraceState()

    ui.hr("Execution")
    run_result = None
    with install_runtime_tracing(ui, trace_state):
        run_result = run_one(
            task_id=task_id,
            variant_id=variant_id,
            model_name=model_name,
            suite_path=str(suite_path),
            output_dir=str(output_root),
            repo_root=args.repo_root,
            cfg=cfg,
        )

    _summarize_run(ui, run_result, trace_state)


if __name__ == "__main__":
    main()
