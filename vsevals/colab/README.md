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

In Colab Secrets, add:

- `OPENAI_API_KEY`
- `HF_TOKEN`
- `GH_TOKEN`

Optional:

- `ANTHROPIC_API_KEY`

`GH_TOKEN` is needed only to build private MVPy v0.1 in Colab. Keys are read
from Colab Secrets/environment only; do not put them in Drive.

## Run Shape

Use one run root per experiment:

```bash
export RUN_ID=gemma4_e4b_mixed_500_$(date -u +%Y%m%dT%H%M%SZ)
export RUN_ROOT=results/colab_runs/$RUN_ID
mkdir -p "$RUN_ROOT"
```

Write a manifest first:

```bash
python colab/mvpy_colab_plan.py run-manifest \
  --run-id "$RUN_ID" \
  --out "$RUN_ROOT/manifest.json" \
  --mvpy-bin /content/mvpy-v0.1 \
  --note "Colab T4/L4 MVPy SFT run"
```

Audit datasets before training:

```bash
python colab/mvpy_colab_plan.py audit-data \
  --tokenizer unsloth/gemma-4-E4B-it \
  --max-seq-length 1024 \
  --out-dir "$RUN_ROOT/audit"
```

Build held-out OOD v2 after verifier exists:

```bash
python colab/mvpy_colab_plan.py build-holdout \
  --mvpy-bin /content/mvpy-v0.1 \
  --out-dir data/mvpy_ood_holdout_v2
```

## Recommended Runs

Teacher data:

```bash
python colab/mvpy_active_teacher.py teacher \
  --dataset data/mvpy_ood_holdout_v2/ood_holdout_v2_qwen.jsonl \
  --out "$RUN_ROOT/teacher/medium_oracle_1000.jsonl" \
  --provider openai \
  --model gpt-5.3-codex \
  --fallback-provider anthropic \
  --fallback-model claude-sonnet-4-6 \
  --band medium \
  --limit 1000 \
  --repair-turns 2 \
  --oracle
```

Fallback:

```bash
python colab/mvpy_active_teacher.py teacher \
  --dataset data/mvpy_ood_holdout_v2/ood_holdout_v2_qwen.jsonl \
  --out "$RUN_ROOT/teacher/hard_oracle_1000_claude.jsonl" \
  --provider anthropic \
  --model claude-sonnet-4-6 \
  --band hard \
  --limit 1000 \
  --repair-turns 2 \
  --oracle
```

Verify accepted teacher rows:

```bash
python colab/mvpy_colab_plan.py verify-teacher \
  --accepted "$RUN_ROOT/teacher/medium_oracle_1000.jsonl" \
  --mvpy-bin /content/mvpy-v0.1 \
  --report "$RUN_ROOT/teacher/medium_verify.json"

python colab/mvpy_colab_plan.py teacher-report \
  --accepted "$RUN_ROOT/teacher/medium_oracle_1000.jsonl" \
  --out "$RUN_ROOT/teacher/medium_report.json"
```

Prepare SFT:

```bash
python colab/mvpy_active_teacher.py prepare-sft \
  --accepted "$RUN_ROOT/teacher/medium_oracle_1000.jsonl" \
  --out-dir "$RUN_ROOT/sft/medium_plan" \
  --target plan_code
```

Mixed SFT:

```bash
python colab/mvpy_colab_plan.py combine-sft \
  --existing-dir data/mvpy_research_mlx_plan_v2 \
  --teacher "$RUN_ROOT/teacher/medium_oracle_1000.jsonl" \
  --repair "$RUN_ROOT/teacher/repair_rows_1000.jsonl" \
  --out-dir "$RUN_ROOT/sft/mixed_5k_teacher_repair" \
  --teacher-limit 2000 \
  --repair-limit 1000
```

Train Qwen:

```bash
python colab/train_unsloth_mvpy.py \
  --family qwen35 \
  --model Qwen/Qwen3.5-0.8B \
  --data-dir "$RUN_ROOT/sft/mixed_5k_teacher_repair" \
  --out-dir "$RUN_ROOT/train/qwen35_0_8b_mixed_200" \
  --max-seq-length 1024 \
  --max-steps 200 \
  --save-steps 100 \
  --eval-steps 100 \
  --rank 16 \
  --run-id "$RUN_ID"
```

Train Gemma:

```bash
python colab/train_unsloth_mvpy.py \
  --family gemma4 \
  --model unsloth/gemma-4-E4B-it \
  --load-in-4bit \
  --data-dir "$RUN_ROOT/sft/mixed_5k_teacher_repair" \
  --out-dir "$RUN_ROOT/train/gemma4_e4b_mixed_200" \
  --max-seq-length 1024 \
  --max-steps 200 \
  --save-steps 100 \
  --eval-steps 100 \
  --rank 16 \
  --run-id "$RUN_ID"
```

After eval JSONs are written:

```bash
python colab/mvpy_colab_plan.py leaderboard \
  --root results/colab_runs \
  --root results/mvpy_sft \
  --out results/colab_runs/leaderboard.md
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

## First Run Order

1. Build `/content/mvpy-v0.1`.
2. `audit-data`.
3. 20-step Gemma smoke.
4. Reproduce Qwen3.5-0.8B 200-step on OOD500.
5. Reproduce Gemma4 E4B 200-step on OOD500.
6. Generate 100 medium + 100 hard teacher rows, verify them.
7. Train Gemma4 200-step teacher pilot, eval OOD100.
8. If OOD100 exact improves by `+5` or runtime by `+15`, scale teacher rows and run 200/500/1000 checkpoints.
