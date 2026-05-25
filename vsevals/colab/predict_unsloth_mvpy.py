#!/usr/bin/env python3
"""Generate MVPy predictions from a Colab Unsloth LoRA adapter."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any


STRICT_SYSTEM_PROMPT = (
    "You write only runnable MVPy v0.1 code. Hard rules: no Python operators "
    "like + - *; use add/sub/mul. No if, for, strings, lists, tuples, dicts, "
    "imports, unpacking, len, range, modulo, or tuple returns. Builtins "
    "add/sub/mul/eq/lt take exactly two arguments. Return only one complete "
    "MVPy program."
)

PLAN_SYSTEM_PROMPT = (
    "You write MVPy v0.1. First write a short structured solve plan, then write "
    "the final runnable MVPy program in one ```mvpy fenced block. MVPy allows "
    "only integer literals, names, positional calls, assignment, def, nonlocal, "
    "return, raise, bare try/except, while, yield, and builtins "
    "print/add/sub/mul/eq/lt/next. Do not use operators, if, for, strings, "
    "lists, tuples, dicts, imports, or tuple returns."
)

GEMMA_PATTERN_PROMPT = """You write MVPy v0.1 programs only.
MVPy syntax is Python-like, not Lisp.
Use calls like add(1, 2), never (add 1 2).
Use print(x), never (print x).
Do not use +, -, *, if, for, lists, tuples, strings, imports, len, range, modulo, or unpacking.
Builtins are only print/add/sub/mul/eq/lt/next. No gt, div, ge, le, and, or.
Every add/sub/mul/eq/lt call has exactly two arguments.
For greater-than breach flag, use lt(limit, value).
For rates 2/8/1, multiply prompt by 2, output by 8, cached by 1.

Example task: Make an API quota projection: limit 100, used 40, incoming 70. Print projected usage, remaining quota, and breach flag.
Answer:
limit = 100
used = 40
incoming = 70
projected = add(used, incoming)
print(projected)
remaining = sub(limit, projected)
print(remaining)
breach = lt(limit, projected)
print(breach)

Example task: Implement a tiny groupby. Six rows have groups cycling 0,1,2 and amounts start at 5 step 2. Print sums for groups 0,1,2.
Answer:
group = 0
amount = 5
remaining = 6
sum0 = 0
sum1 = 0
sum2 = 0
while remaining:
    sum0 = add(sum0, mul(eq(group, 0), amount))
    sum1 = add(sum1, mul(eq(group, 1), amount))
    sum2 = add(sum2, mul(eq(group, 2), amount))
    group = add(group, 1)
    group = sub(group, mul(eq(group, 3), 3))
    amount = add(amount, 2)
    remaining = sub(remaining, 1)
print(sum0)
print(sum1)
print(sum2)

Example task: Implement a rolling-window helper. Five values start at 10 step 4. Sum every 3-value window, then print exhausted next().
Answer:
def values():
    value = 10
    remaining = 5
    while remaining:
        yield value
        value = add(value, 4)
        remaining = sub(remaining, 1)
stream = values()
a = next(stream)
b = next(stream)
remaining = 3
total = 0
while remaining:
    c = next(stream)
    window = add(add(a, b), c)
    total = add(total, window)
    a = b
    b = c
    remaining = sub(remaining, 1)
print(total)
print(next(stream))

Task:
"""


def iter_jsonl(path: Path):
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def build_messages(mode: str, task: str) -> list[dict[str, str]]:
    if mode == "gemma_patterns":
        return [{"role": "user", "content": GEMMA_PATTERN_PROMPT + task + "\nAnswer:\n"}]
    if mode == "strict_code":
        return [{"role": "system", "content": STRICT_SYSTEM_PROMPT}, {"role": "user", "content": task}]
    if mode == "plan_code":
        return [{"role": "system", "content": PLAN_SYSTEM_PROMPT}, {"role": "user", "content": task}]
    raise ValueError(mode)


def apply_chat_template(tokenizer: Any, messages: list[dict[str, str]], enable_thinking: bool) -> str:
    kwargs = {"add_generation_prompt": True, "tokenize": False}
    if not enable_thinking:
        kwargs["enable_thinking"] = False
    try:
        return tokenizer.apply_chat_template(messages, **kwargs)
    except TypeError:
        kwargs.pop("enable_thinking", None)
        return tokenizer.apply_chat_template(messages, **kwargs)


def load_model(args: argparse.Namespace):
    import torch

    if args.family == "gemma4":
        from unsloth import FastModel
        from unsloth.chat_templates import get_chat_template

        first_name = str(args.adapter_path) if args.prefer_adapter_load and args.adapter_path else args.model
        try:
            model, tokenizer = FastModel.from_pretrained(
                model_name=first_name,
                dtype=None,
                max_seq_length=args.max_seq_length,
                load_in_4bit=args.load_in_4bit,
                full_finetuning=False,
            )
        except Exception:
            if not args.adapter_path:
                raise
            from peft import PeftModel

            model, tokenizer = FastModel.from_pretrained(
                model_name=args.model,
                dtype=None,
                max_seq_length=args.max_seq_length,
                load_in_4bit=args.load_in_4bit,
                full_finetuning=False,
            )
            model = PeftModel.from_pretrained(model, str(args.adapter_path))
        tokenizer = get_chat_template(tokenizer, chat_template="gemma-4-thinking")
    else:
        from peft import PeftModel
        from transformers import AutoModelForCausalLM, AutoTokenizer

        tokenizer = AutoTokenizer.from_pretrained(args.adapter_path or args.model, trust_remote_code=True)
        model = AutoModelForCausalLM.from_pretrained(
            args.model,
            device_map="auto",
            torch_dtype=torch.float16,
            load_in_4bit=args.load_in_4bit,
            trust_remote_code=True,
        )
        if args.adapter_path:
            model = PeftModel.from_pretrained(model, str(args.adapter_path))
    model.eval()
    return model, tokenizer


def generate_one(model: Any, tokenizer: Any, prompt: str, args: argparse.Namespace) -> str:
    import torch

    previous_side = getattr(tokenizer, "truncation_side", "right")
    tokenizer.truncation_side = args.truncation_side
    inputs = tokenizer(
        prompt,
        return_tensors="pt",
        truncation=True,
        max_length=args.max_seq_length,
    )
    tokenizer.truncation_side = previous_side
    if torch.cuda.is_available():
        inputs = {key: value.to("cuda") for key, value in inputs.items()}
    kwargs = {
        "max_new_tokens": args.max_tokens,
        "pad_token_id": tokenizer.eos_token_id,
    }
    if args.temperature > 0:
        kwargs.update({"do_sample": True, "temperature": args.temperature, "top_p": args.top_p})
    else:
        kwargs.update({"do_sample": False})
    with torch.inference_mode():
        output = model.generate(**inputs, **kwargs)
    prompt_len = inputs["input_ids"].shape[-1]
    return tokenizer.decode(output[0][prompt_len:], skip_special_tokens=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--family", choices=["gemma4", "qwen35"], default="gemma4")
    parser.add_argument("--model", default="unsloth/gemma-4-E4B-it")
    parser.add_argument("--adapter-path", type=Path)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--prompt-mode", choices=["gemma_patterns", "plan_code", "strict_code"], default="gemma_patterns")
    parser.add_argument("--max-seq-length", type=int, default=1024)
    parser.add_argument("--max-tokens", type=int, default=384)
    parser.add_argument("--truncation-side", choices=["left", "right"], default="left")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--top-p", type=float, default=0.95)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--load-in-4bit", action="store_true")
    parser.add_argument("--enable-thinking", action="store_true")
    parser.add_argument("--prefer-adapter-load", action="store_true")
    args = parser.parse_args()

    model, tokenizer = load_model(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if args.resume and args.output.exists():
        done = {row["id"] for row in iter_jsonl(args.output)}
    started = time.time()
    count = 0
    mode = "a" if args.resume else "w"
    with args.output.open(mode, encoding="utf-8") as out:
        for row in iter_jsonl(args.dataset):
            if args.limit is not None and count >= args.limit:
                break
            if row["id"] in done:
                continue
            prompt = apply_chat_template(tokenizer, build_messages(args.prompt_mode, row["prompt_raw"]), args.enable_thinking)
            prediction = generate_one(model, tokenizer, prompt, args)
            out.write(json.dumps({"id": row["id"], "prediction": prediction}, ensure_ascii=False) + "\n")
            out.flush()
            count += 1
            if count % 25 == 0:
                print(json.dumps({"generated": count, "elapsed_sec": round(time.time() - started, 1)}), flush=True)
    print(json.dumps({"generated": count, "elapsed_sec": round(time.time() - started, 1), "output": str(args.output)}))


if __name__ == "__main__":
    main()
