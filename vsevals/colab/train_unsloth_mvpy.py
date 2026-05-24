#!/usr/bin/env python3
"""Colab Unsloth SFT runner for MVPy message JSONL datasets."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
from pathlib import Path
import time


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def jsonl_count(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open(encoding="utf-8") as fh:
        return sum(1 for line in fh if line.strip())


def package_versions(names: list[str]) -> dict[str, str]:
    versions = {}
    for name in names:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = "not-installed"
    return versions


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="unsloth/Qwen3.5-4B")
    parser.add_argument("--family", choices=["qwen35", "gemma4"], default="qwen35")
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--max-seq-length", type=int, default=1024)
    parser.add_argument("--max-steps", type=int, default=300)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--grad-accum", type=int, default=4)
    parser.add_argument("--lr", type=float, default=2e-4)
    parser.add_argument("--rank", type=int, default=16)
    parser.add_argument("--load-in-4bit", action="store_true")
    parser.add_argument("--save-steps", type=int, default=100)
    parser.add_argument("--eval-steps", type=int, default=100)
    parser.add_argument("--warmup-steps", type=int, default=5)
    parser.add_argument("--weight-decay", type=float, default=0.001)
    parser.add_argument("--seed", type=int, default=3407)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--report-json", type=Path, default=None)
    args = parser.parse_args()

    import torch
    from datasets import load_dataset

    started = time.time()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    if args.family == "gemma4":
        from unsloth import FastModel
        from unsloth.chat_templates import get_chat_template, train_on_responses_only
        from trl import SFTConfig, SFTTrainer

        model, tokenizer = FastModel.from_pretrained(
            model_name=args.model,
            dtype=None,
            max_seq_length=args.max_seq_length,
            load_in_4bit=args.load_in_4bit,
            full_finetuning=False,
        )
        model = FastModel.get_peft_model(
            model,
            finetune_vision_layers=False,
            finetune_language_layers=True,
            finetune_attention_modules=True,
            finetune_mlp_modules=True,
            r=args.rank,
            lora_alpha=args.rank,
            lora_dropout=0,
            bias="none",
            random_state=args.seed,
        )
        tokenizer = get_chat_template(tokenizer, chat_template="gemma-4-thinking")
        instruction_part = "<|turn>user\n"
        response_part = "<|turn>model\n"
    else:
        from unsloth import FastVisionModel
        from unsloth.chat_templates import train_on_responses_only
        from trl import SFTConfig, SFTTrainer

        model, tokenizer = FastVisionModel.from_pretrained(
            args.model,
            load_in_4bit=args.load_in_4bit,
            use_gradient_checkpointing="unsloth",
            max_seq_length=args.max_seq_length,
        )
        model = FastVisionModel.get_peft_model(
            model,
            finetune_vision_layers=False,
            finetune_language_layers=True,
            finetune_attention_modules=True,
            finetune_mlp_modules=True,
            r=args.rank,
            lora_alpha=args.rank,
            lora_dropout=0,
            bias="none",
            random_state=args.seed,
            use_rslora=False,
            loftq_config=None,
        )
        instruction_part = "<|im_start|>user\n"
        response_part = "<|im_start|>assistant\n"

    files = {
        "train": str(args.data_dir / "train.jsonl"),
        "validation": str(args.data_dir / "valid.jsonl"),
    }
    dataset = load_dataset("json", data_files=files)

    def format_rows(batch):
        texts = [
            tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=False).removeprefix("<bos>")
            for messages in batch["messages"]
        ]
        return {"text": texts}

    dataset = dataset.map(format_rows, batched=True, remove_columns=dataset["train"].column_names)
    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=dataset["train"],
        eval_dataset=dataset["validation"],
        args=SFTConfig(
            dataset_text_field="text",
            per_device_train_batch_size=args.batch_size,
            gradient_accumulation_steps=args.grad_accum,
            warmup_steps=args.warmup_steps,
            max_steps=args.max_steps,
            learning_rate=args.lr,
            logging_steps=1,
            eval_steps=args.eval_steps,
            save_steps=args.save_steps,
            optim="adamw_8bit",
            weight_decay=args.weight_decay,
            lr_scheduler_type="linear",
            seed=args.seed,
            report_to="none",
            output_dir=str(args.out_dir / "trainer"),
        ),
    )
    trainer = train_on_responses_only(
        trainer,
        instruction_part=instruction_part,
        response_part=response_part,
    )

    print("gpu", torch.cuda.get_device_name(0) if torch.cuda.is_available() else "none")
    stats = trainer.train()
    model.save_pretrained(args.out_dir / "adapter")
    tokenizer.save_pretrained(args.out_dir / "adapter")
    finished = time.time()

    report = {
        "run_id": args.run_id or args.out_dir.name,
        "model": args.model,
        "family": args.family,
        "data_dir": str(args.data_dir),
        "out_dir": str(args.out_dir),
        "max_seq_length": args.max_seq_length,
        "max_steps": args.max_steps,
        "batch_size": args.batch_size,
        "grad_accum": args.grad_accum,
        "lr": args.lr,
        "rank": args.rank,
        "load_in_4bit": args.load_in_4bit,
        "save_steps": args.save_steps,
        "eval_steps": args.eval_steps,
        "seed": args.seed,
        "train_rows": jsonl_count(args.data_dir / "train.jsonl"),
        "valid_rows": jsonl_count(args.data_dir / "valid.jsonl"),
        "train_sha256": file_sha256(args.data_dir / "train.jsonl") if (args.data_dir / "train.jsonl").exists() else None,
        "valid_sha256": file_sha256(args.data_dir / "valid.jsonl") if (args.data_dir / "valid.jsonl").exists() else None,
        "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "none",
        "cuda_available": bool(torch.cuda.is_available()),
        "torch_version": getattr(torch, "__version__", "unknown"),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "packages": package_versions(["unsloth", "trl", "transformers", "peft", "bitsandbytes", "datasets"]),
        "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started)),
        "finished_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(finished)),
        "elapsed_sec": round(finished - started, 3),
        "trainer_metrics": stats.metrics,
        "log_history": trainer.state.log_history,
    }
    report_path = args.report_json or (args.out_dir / "manifest.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
