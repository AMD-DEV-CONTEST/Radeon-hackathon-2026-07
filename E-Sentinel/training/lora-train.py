#!/usr/bin/env python3
"""E-Sentinel Qwen3-8B FP16 LoRA SFT 训练脚本。

在 AMD 实例（/opt/vllm-env）上运行。数据来自本仓库 training/data/sft/（程序化生成，
完全独立于 105 例 human-gold，见 training/README.md 诚信红线）。

用法：
  python training/lora-train.py \
    --train training/data/sft/train.jsonl \
    --dev   training/data/sft/dev.jsonl \
    --model /workspace/Qwen3-8B \
    --out   /workspace/e-sentinel-lora \
    --epochs 2 --lr 5e-5 --rank 16 --alpha 32

输出：/workspace/e-sentinel-lora/（adapter + config，供 LoRA 合并或 vLLM --lora-modules）
"""

import argparse
import json
import os

from datasets import Dataset
from peft import LoraConfig, get_peft_model
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    Trainer,
    TrainingArguments,
)


def load_chat_examples(path, tokenizer):
    """SFT jsonl（system/user/assistant）→ 训练样本（input_ids + labels）。

    仅对 assistant 部分计算 loss：prompt（system+user）的 label 置 -100。
    """
    with open(path, "r", encoding="utf-8") as f:
        items = [json.loads(l) for l in f if l.strip()]

    examples = []
    for it in items:
        msgs = [
            {"role": "system", "content": it["system"]},
            {"role": "user", "content": it["user"]},
            {"role": "assistant", "content": it["assistant"]},
        ]
        prompt = tokenizer.apply_chat_template(
            msgs[:-1], tokenize=False, add_generation_prompt=True
        )
        full = tokenizer.apply_chat_template(msgs, tokenize=False)
        enc_full = tokenizer(full, truncation=True, max_length=2048)
        enc_prompt = tokenizer(prompt, truncation=True, max_length=2048)

        input_ids = enc_full["input_ids"]
        labels = [-100] * len(enc_prompt["input_ids"]) + input_ids[len(enc_prompt["input_ids"]):]
        # labels 与 input_ids 对齐（截断后）
        labels = (labels + [-100] * 2048)[:2048]
        input_ids = (input_ids + [tokenizer.pad_token_id] * 2048)[:2048]
        examples.append({"input_ids": input_ids, "labels": labels})

    return Dataset.from_list(examples)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", required=True)
    ap.add_argument("--dev", required=True)
    ap.add_argument("--model", default="/workspace/Qwen3-8B")
    ap.add_argument("--out", default="/workspace/e-sentinel-lora")
    ap.add_argument("--epochs", type=float, default=2)
    ap.add_argument("--lr", type=float, default=5e-5)
    ap.add_argument("--rank", type=int, default=16)
    ap.add_argument("--alpha", type=int, default=32)
    ap.add_argument("--batch", type=int, default=1)
    ap.add_argument("--grad-accum", type=int, default=16)
    args = ap.parse_args()

    print(f"[train] 加载模型: {args.model}")
    tokenizer = AutoTokenizer.from_pretrained(args.model, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        args.model,
        dtype="float16",
        device_map="auto",
        trust_remote_code=True,
    )

    lora = LoraConfig(
        r=args.rank,
        lora_alpha=args.alpha,
        lora_dropout=0.05,
        target_modules="all-linear",
        bias="none",
        task_type="CAUSAL_LM",
    )
    model = get_peft_model(model, lora)
    model.enable_input_require_grads()
    model.print_trainable_parameters()

    train_ds = load_chat_examples(args.train, tokenizer)
    dev_ds = load_chat_examples(args.dev, tokenizer)
    print(f"[train] train={len(train_ds)} dev={len(dev_ds)}")

    training_args = TrainingArguments(
        output_dir=args.out,
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch,
        gradient_accumulation_steps=args.grad_accum,
        learning_rate=args.lr,
        lr_scheduler_type="cosine",
        warmup_ratio=0.05,
        fp16=True,
        gradient_checkpointing=True,
        logging_steps=1,
        save_strategy="epoch",
        eval_strategy="steps",
        eval_steps=50,
        report_to=[],
        remove_unused_columns=False,
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_ds,
        eval_dataset=dev_ds,
        processing_class=tokenizer,  # transformers >=5 用 processing_class 替代 tokenizer
    )

    trainer.train()
    trainer.save_model(args.out)
    tokenizer.save_pretrained(args.out)
    print(f"[train] adapter 已保存: {args.out}")


if __name__ == "__main__":
    main()
