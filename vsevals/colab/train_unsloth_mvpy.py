#!/usr/bin/env python3
"""Colab Unsloth SFT runner for MVPy message JSONL datasets."""

from __future__ import annotations

import argparse
from pathlib import Path


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
    args = parser.parse_args()

    import torch
    from datasets import load_dataset
    from trl import SFTConfig, SFTTrainer

    if args.family == "gemma4":
        from unsloth import FastModel
        from unsloth.chat_templates import get_chat_template, train_on_responses_only

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
            random_state=3407,
        )
        tokenizer = get_chat_template(tokenizer, chat_template="gemma-4-thinking")
        instruction_part = "<|turn>user\n"
        response_part = "<|turn>model\n"
    else:
        from unsloth import FastVisionModel
        from unsloth.chat_templates import train_on_responses_only

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
            random_state=3407,
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
            warmup_steps=5,
            max_steps=args.max_steps,
            learning_rate=args.lr,
            logging_steps=1,
            eval_steps=50,
            save_steps=50,
            optim="adamw_8bit",
            weight_decay=0.001,
            lr_scheduler_type="linear",
            seed=3407,
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
    args.out_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(args.out_dir / "adapter")
    tokenizer.save_pretrained(args.out_dir / "adapter")
    print(stats.metrics)


if __name__ == "__main__":
    main()
