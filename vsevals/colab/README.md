# MVPy Colab Active Teacher Setup

Use this when local Mac training is too slow or too constrained.

## What Colab Does

- builds pinned MVPy verifier
- generates teacher `plan -> code` and repair rows
- verifies every accepted row with MVPy
- prepares SFT JSONL
- trains Qwen3.5/Gemma4 with Unsloth
- evaluates OOD500 with the same verifier

## Local Bundle

From `vsevals`:

```bash
python scripts/package_mvpy_colab_bundle.py
```

Upload:

```text
results/mvpy_colab/mvpy_colab_bundle.tar.gz
```

to Colab or Google Drive.

## Secrets

In Colab Secrets, add at least one:

- `OPENAI_API_KEY`
- `ANTHROPIC_API_KEY`

Optional:

- `HF_TOKEN`

## Recommended Runs

Teacher data:

```bash
python colab/mvpy_active_teacher.py teacher \
  --dataset data/mvpy_ood_500/ood_qwen.jsonl \
  --out results/teacher/medium_oracle.jsonl \
  --provider openai \
  --model gpt-5.3-codex \
  --band medium \
  --limit 200 \
  --repair-turns 2 \
  --oracle
```

Prepare SFT:

```bash
python colab/mvpy_active_teacher.py prepare-sft \
  --accepted results/teacher/medium_oracle.jsonl \
  --out-dir results/sft/medium_plan \
  --target plan_code
```

Train Qwen:

```bash
python colab/train_unsloth_mvpy.py \
  --family qwen35 \
  --model unsloth/Qwen3.5-4B \
  --data-dir results/sft/medium_plan \
  --out-dir results/train/qwen35_4b_medium_plan \
  --max-seq-length 1024 \
  --max-steps 300 \
  --rank 16
```

Train Gemma:

```bash
python colab/train_unsloth_mvpy.py \
  --family gemma4 \
  --model unsloth/gemma-4-E4B-it \
  --load-in-4bit \
  --data-dir results/sft/medium_plan \
  --out-dir results/train/gemma4_e4b_medium_plan \
  --max-seq-length 1024 \
  --max-steps 300 \
  --rank 16
```

## Colab MCP

`googlecolab/colab-mcp` is useful as the remote control layer.

It lets a local agent open/connect to a Colab notebook and run cells. It does
not replace Unsloth, PEFT, TRL, or the active-teacher scripts.

MCP server config:

```json
{
  "mcpServers": {
    "colab-mcp": {
      "command": "uvx",
      "args": ["git+https://github.com/googlecolab/colab-mcp"],
      "timeout": 30000
    }
  }
}
```

## Current Local Baseline

- Qwen3.5-0.8B v2: `241/500` exact OOD500
- Gemma4 E4B local MLX/OptiQ: `98/500` exact OOD500
- Gemma4 failure: medium/hard data-processing idioms

Colab target: teacher-plan/repair SFT to teach generators, branchless groupby,
rolling windows, lookup joins, and counter/accumulate patterns.
