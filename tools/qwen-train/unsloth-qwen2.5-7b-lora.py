"""Train a LoRA on Qwen 2.5 7B using unsloth + an Aki Brain export.

Usage:
    pip install "unsloth[cu121] @ git+https://github.com/unslothai/unsloth.git"
    python unsloth-qwen2.5-7b-lora.py --data brain.jsonl --out ./qwen-aki-lora

This is the small/fast path (single GPU, ~6GB VRAM for 7B LoRA). For
multi-GPU or larger models, prefer the axolotl config in this directory.
"""
import argparse
import json
from pathlib import Path


def _load_jsonl(path: Path):
    rows = []
    with path.open() as f:
        for line in f:
            if not line.strip():
                continue
            obj = json.loads(line)
            inst = (obj.get("instruction") or "").strip()
            ctx = (obj.get("context") or "").strip()
            resp = (obj.get("response") or "").strip()
            # Skip rows with no instruction AND no response (pure context-only
            # journal entries) — they'd produce empty Qwen turns.
            if not inst and not resp:
                continue
            rows.append({"instruction": inst, "input": ctx, "output": resp})
    return rows


def _format_prompt(row):
    """Qwen chat template-ish formatting. Trainer will tokenize this."""
    if row["input"]:
        user = f"{row['instruction']}\n\n{row['input']}".strip()
    else:
        user = row["instruction"]
    return f"<|im_start|>user\n{user}<|im_end|>\n<|im_start|>assistant\n{row['output']}<|im_end|>"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True, help="brain.jsonl path")
    parser.add_argument("--out", default="./qwen-aki-lora")
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--lr", type=float, default=2e-4)
    parser.add_argument("--rank", type=int, default=32)
    parser.add_argument("--max-seq", type=int, default=4096)
    args = parser.parse_args()

    rows = _load_jsonl(Path(args.data))
    if not rows:
        raise SystemExit("no usable rows in dataset")
    print(f"loaded {len(rows)} rows")

    # Heavy deps imported lazily so --help works on a tiny machine.
    from unsloth import FastLanguageModel
    from datasets import Dataset
    from trl import SFTTrainer
    from transformers import TrainingArguments

    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name="Qwen/Qwen2.5-7B-Instruct",
        max_seq_length=args.max_seq,
        load_in_4bit=True,
    )
    model = FastLanguageModel.get_peft_model(
        model,
        r=args.rank,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
        lora_alpha=16,
        lora_dropout=0.05,
        bias="none",
    )

    ds = Dataset.from_list([{"text": _format_prompt(r)} for r in rows])

    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=ds,
        dataset_text_field="text",
        max_seq_length=args.max_seq,
        args=TrainingArguments(
            per_device_train_batch_size=2,
            gradient_accumulation_steps=4,
            warmup_steps=20,
            num_train_epochs=args.epochs,
            learning_rate=args.lr,
            logging_steps=5,
            optim="adamw_8bit",
            output_dir=args.out,
            save_strategy="epoch",
        ),
    )
    trainer.train()
    model.save_pretrained(args.out)
    print(f"LoRA written to {args.out}")


if __name__ == "__main__":
    main()
