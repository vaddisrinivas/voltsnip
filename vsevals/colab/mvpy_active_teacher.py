#!/usr/bin/env python3
"""Colab-side MVPy active teacher + verifier tooling."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
from typing import Any


MVPY_SPEC = """MVPy v0.1 core11 syntax:
- integer literals, names, positional calls
- assignment, def, nonlocal, return, raise, bare try/except, while, yield
- builtins only: print, add, sub, mul, eq, lt, next
- no + - * / %, no if/for, no lists/tuples/dicts/strings/imports/range/len
Idioms:
- greater-than flag: lt(limit, value)
- modulo 3 after increment: x = sub(x, mul(eq(x, 3), 3))
- modulo 4 after increment: x = sub(x, mul(lt(3, x), 4))
- branchless bucket sum: sum0 = add(sum0, mul(eq(bucket, 0), amount))
- branchless select: out = add(mul(flag, new), mul(sub(1, flag), old))
- generator: def values(): while remaining: yield value ...
Return one runnable MVPy program.
"""


def read_jsonl(path: Path):
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def existing_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {row["id"] for row in read_jsonl(path)}


def extract_code(text: str) -> str:
    fenced = re.findall(r"```(?:mvpy|python|text)?\s*(.*?)```", text, flags=re.S | re.I)
    if fenced:
        text = fenced[-1]
    lines = []
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line:
            lines.append("")
            continue
        lowered = line.lstrip().lower()
        if lowered.startswith(("plan:", "answer:", "code:", "explanation:", "```")):
            continue
        if "<|channel>" in line or "<think>" in line or "</think>" in line:
            continue
        lines.append(line)
    return "\n".join(lines).strip() + "\n"


def run_cmd(cmd: list[str], cwd: Path | None = None, timeout: int | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, timeout=timeout, text=True, capture_output=True)


def run_mvpy(code: str, mvpy_bin: Path, timeout: int = 5) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="mvpy_teacher_") as td:
        path = Path(td) / "candidate.mvpy"
        path.write_text(code, encoding="utf-8")
        proc = run_cmd([str(mvpy_bin), str(path)], timeout=timeout)
    return {
        "exit": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "ok": proc.returncode == 0,
    }


def dump_usage(usage: Any) -> dict[str, Any] | None:
    if usage is None:
        return None
    if hasattr(usage, "model_dump"):
        return usage.model_dump()
    if hasattr(usage, "__dict__"):
        return dict(usage.__dict__)
    return {"raw": repr(usage)}


def call_openai(model: str, prompt: str, max_tokens: int) -> dict[str, Any]:
    from openai import OpenAI

    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    response = client.responses.create(
        model=model,
        input=prompt,
        temperature=0,
        max_output_tokens=max_tokens,
    )
    return {"text": response.output_text, "usage": dump_usage(getattr(response, "usage", None))}


def call_anthropic(model: str, prompt: str, max_tokens: int) -> dict[str, Any]:
    import anthropic

    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        temperature=0,
        messages=[{"role": "user", "content": prompt}],
    )
    return {
        "text": "\n".join(block.text for block in response.content if getattr(block, "type", "") == "text"),
        "usage": dump_usage(getattr(response, "usage", None)),
    }


def call_teacher(provider: str, model: str, prompt: str, max_tokens: int) -> dict[str, Any]:
    if provider == "openai":
        return call_openai(model, prompt, max_tokens)
    if provider == "anthropic":
        return call_anthropic(model, prompt, max_tokens)
    raise ValueError(provider)


def build_teacher_prompt(row: dict[str, Any], attempt: dict[str, Any] | None, oracle: bool) -> str:
    if attempt is None:
        extra = ""
    else:
        result = attempt["result"]
        extra = f"""
Previous code failed.

Bad code:
```mvpy
{attempt["code"]}
```

Verifier exit: {result["exit"]}
stdout:
{result["stdout"]}
stderr:
{result["stderr"]}
"""
    want = f"\nExpected stdout:\n{row.get('stdout', '')}\n" if oracle else ""
    return f"""{MVPY_SPEC}

Task:
{row["prompt_raw"]}
{want}
{extra}

Write:
1. a short plan with state variables and loop invariant
2. final code in one ```mvpy fenced block
"""


def command_env_report(_: argparse.Namespace) -> None:
    print("python", os.sys.version)
    print("cwd", Path.cwd())
    print("OPENAI_API_KEY", "set" if os.environ.get("OPENAI_API_KEY") else "missing")
    print("ANTHROPIC_API_KEY", "set" if os.environ.get("ANTHROPIC_API_KEY") else "missing")
    for cmd in (["nvidia-smi"], ["go", "version"]):
        if shutil.which(cmd[0]):
            proc = run_cmd(cmd)
            print(proc.stdout or proc.stderr)


def command_build_verifier(args: argparse.Namespace) -> None:
    root = args.workdir / "mvpy"
    clone_repo = args.repo
    token = os.environ.get("GH_TOKEN")
    if token and args.repo.startswith("https://github.com/"):
        clone_repo = args.repo.replace("https://github.com/", f"https://x-access-token:{token}@github.com/", 1)
    if not root.exists():
        run = run_cmd(["git", "clone", clone_repo, str(root)], timeout=120)
        if run.returncode:
            raise SystemExit(run.stderr)
    if args.commit:
        run_cmd(["git", "fetch", "--all"], cwd=root, timeout=120)
        run = run_cmd(["git", "checkout", args.commit], cwd=root, timeout=120)
        if run.returncode:
            raise SystemExit(run.stderr)
    out = args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    run = run_cmd(["go", "build", "-o", str(out), "./cmd/mvpy"], cwd=root, timeout=180)
    if run.returncode:
        raise SystemExit(run.stderr)
    print(json.dumps({"mvpy_bin": str(out), "repo": args.repo, "commit": args.commit}, indent=2))


def command_teacher(args: argparse.Namespace) -> None:
    done = existing_ids(args.out)
    reject_path = args.out.with_suffix(".rejects.jsonl")
    accepted = 0
    seen = 0
    for row in read_jsonl(args.dataset):
        if row["id"] in done:
            continue
        if args.band and row.get("difficulty_band") != args.band:
            continue
        if args.category and row.get("category") != args.category:
            continue
        if seen < args.start:
            seen += 1
            continue
        if args.limit is not None and accepted >= args.limit:
            break
        seen += 1
        attempts = []
        previous = None
        for turn in range(args.repair_turns + 1):
            prompt = build_teacher_prompt(row, previous, oracle=args.oracle)
            provider = args.provider
            model = args.model
            try:
                response = call_teacher(provider, model, prompt, args.max_tokens)
            except Exception as exc:
                if not args.fallback_provider or not args.fallback_model:
                    raise
                provider = args.fallback_provider
                model = args.fallback_model
                response = call_teacher(provider, model, prompt, args.max_tokens)
                response["fallback_from"] = {"provider": args.provider, "model": args.model, "error": repr(exc)}
            text = response["text"]
            code = extract_code(text)
            result = run_mvpy(code, args.mvpy_bin, timeout=args.timeout)
            attempt = {
                "turn": turn,
                "provider": provider,
                "model": model,
                "usage": response.get("usage"),
                "fallback_from": response.get("fallback_from"),
                "text": text,
                "code": code,
                "result": result,
            }
            attempts.append(attempt)
            if result["exit"] == 0 and result["stdout"] == row.get("stdout", ""):
                append_jsonl(
                    args.out,
                    {
                        "id": row["id"],
                        "prompt_raw": row["prompt_raw"],
                        "stdout": row.get("stdout", ""),
                        "category": row.get("category"),
                        "difficulty_band": row.get("difficulty_band"),
                        "features": row.get("features", []),
                        "mvpy": code,
                        "teacher_text": text,
                        "attempts": attempts,
                        "teacher": {"provider": provider, "model": model, "oracle": args.oracle},
                        "verifier": {"binary": str(args.mvpy_bin), "exit": result["exit"]},
                    },
                )
                accepted += 1
                print(json.dumps({"accepted": accepted, "id": row["id"], "turn": turn}), flush=True)
                break
            previous = attempt
        else:
            append_jsonl(reject_path, {"id": row["id"], "attempts": attempts, "row": row})
            print(json.dumps({"rejected": row["id"], "last": attempts[-1]["result"]}), flush=True)
        if args.sleep:
            time.sleep(args.sleep)


def command_prepare_sft(args: argparse.Namespace) -> None:
    rows = list(read_jsonl(args.accepted))
    if not rows:
        raise SystemExit("no rows")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    split = max(1, int(len(rows) * (1 - args.valid_fraction)))
    train, valid = rows[:split], rows[split:] or rows[-1:]

    def convert(row: dict[str, Any]) -> dict[str, Any]:
        if args.target == "plan_code":
            assistant = row.get("teacher_text") or f"```mvpy\n{row['mvpy']}\n```"
        else:
            assistant = row["mvpy"]
        return {
            "id": row["id"],
            "messages": [
                {"role": "system", "content": MVPY_SPEC},
                {"role": "user", "content": row["prompt_raw"]},
                {"role": "assistant", "content": assistant},
            ],
        }

    for name, part in (("train", train), ("valid", valid)):
        with (args.out_dir / f"{name}.jsonl").open("w", encoding="utf-8") as fh:
            for row in part:
                fh.write(json.dumps(convert(row), ensure_ascii=False) + "\n")
    print(json.dumps({"out_dir": str(args.out_dir), "train": len(train), "valid": len(valid)}, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    env = sub.add_parser("env-report")
    env.set_defaults(func=command_env_report)

    build = sub.add_parser("build-verifier")
    build.add_argument("--repo", default="https://github.com/vaddisrinivas/mvpy.git")
    build.add_argument("--commit", default="671aecf")
    build.add_argument("--workdir", type=Path, default=Path("/content"))
    build.add_argument("--out", type=Path, default=Path("/content/mvpy-v0.1"))
    build.set_defaults(func=command_build_verifier)

    teacher = sub.add_parser("teacher")
    teacher.add_argument("--dataset", type=Path, required=True)
    teacher.add_argument("--out", type=Path, required=True)
    teacher.add_argument("--mvpy-bin", type=Path, default=Path("/content/mvpy-v0.1"))
    teacher.add_argument("--provider", choices=["openai", "anthropic"], default="openai")
    teacher.add_argument("--model", default="gpt-5.3-codex")
    teacher.add_argument("--fallback-provider", choices=["openai", "anthropic"])
    teacher.add_argument("--fallback-model")
    teacher.add_argument("--limit", type=int)
    teacher.add_argument("--start", type=int, default=0)
    teacher.add_argument("--band")
    teacher.add_argument("--category")
    teacher.add_argument("--repair-turns", type=int, default=2)
    teacher.add_argument("--max-tokens", type=int, default=2048)
    teacher.add_argument("--timeout", type=int, default=5)
    teacher.add_argument("--sleep", type=float, default=0)
    teacher.add_argument("--oracle", action="store_true")
    teacher.set_defaults(func=command_teacher)

    prep = sub.add_parser("prepare-sft")
    prep.add_argument("--accepted", type=Path, required=True)
    prep.add_argument("--out-dir", type=Path, required=True)
    prep.add_argument("--target", choices=["code", "plan_code"], default="plan_code")
    prep.add_argument("--valid-fraction", type=float, default=0.1)
    prep.set_defaults(func=command_prepare_sft)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
