# Qwen training scaffold

Aki's Brain exports a JSONL dataset of `{instruction, context, response,
signals}` rows. This directory holds reference configs for turning that
dataset into a fine-tuned Qwen 2.5 model.

Nothing in this directory is auto-run by the platform. Training is an
offline operation done by an operator with a GPU.

## Step 1 — export from Brain

In the web UI, sign in as an admin and curl the export endpoint:

```bash
curl -H "Authorization: Bearer $CLERK_JWT" \
  -o brain.jsonl \
  "$API_URL/v1/brain/export?kinds=job_summary,aki_journal"
```

`brain.jsonl` is one JSON object per line:

```json
{
  "instruction": "Post a job for a senior Rust engineer, then screen the resumes that come in over the next 48 hours",
  "context": "",
  "response": "Posted to LinkedIn, Greenhouse, and our careers page... 17 applications, 4 forwarded to hiring manager...",
  "signals": {"kind": "job_summary", "cost_usd": 0.42, ...}
}
```

## Step 2 — pick a trainer

Two options, both work fine. Both ingest JSONL directly.

### Option A: axolotl

```bash
git clone https://github.com/OpenAccess-AI-Collective/axolotl
cd axolotl
pip install -e .[flash-attn,deepspeed]

# from THIS repo:
cp ../aki/tools/qwen-train/axolotl-qwen2.5-7b-lora.yaml ./config.yaml
# edit `datasets:` to point at your brain.jsonl
accelerate launch -m axolotl.cli.train config.yaml
```

### Option B: unsloth (faster on a single GPU)

```bash
pip install "unsloth[cu121] @ git+https://github.com/unslothai/unsloth.git"
python tools/qwen-train/unsloth-qwen2.5-7b-lora.py --data brain.jsonl
```

## Step 3 — evaluate

Use the labeled recall set in `services/api/tests/brain/recall.yml` to
verify the new model recovers the right Brain sources for known queries.
Threshold: recall@10 >= 0.85 on the held-out half before promoting the
model into the per-dept Hermes runtime.

## Step 4 — deploy

When the LoRA is ready, push the adapter and the base model to whichever
inference host you're using (vLLM, TGI, Modal), then point a department at
the new model:

```sql
update departments set hermes_model_name = 'qwen2.5-7b-aki-v1'
where organization_id = '…' and slug = 'engineering';
```

The agent_runtime picks this up on the next cold-start.

## What this scaffold doesn't do

- No training infra in-repo. We don't manage GPUs.
- No automatic export → train → deploy. Operator-in-the-loop by design.
- No data-redaction step. Add PII scrubbing on `brain.jsonl` if your org's
  privacy review requires it before sending to a hosted trainer.
