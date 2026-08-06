"""Train a Qwen3 ClaimCourt LoRA adapter on a local ROCm GPU."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import time
from pathlib import Path

import torch
from peft import LoraConfig, get_peft_model
from torch.utils.data import DataLoader, Dataset
from transformers import AutoModelForCausalLM, AutoTokenizer


class ChatDataset(Dataset):
    def __init__(self, rows: list[dict[str, object]], tokenizer: AutoTokenizer, max_length: int) -> None:
        self.items: list[dict[str, list[int]]] = []
        for row in rows:
            messages = row["messages"]
            prompt_ids = tokenizer.apply_chat_template(
                messages[:-1], tokenize=True, add_generation_prompt=True
            )
            input_ids = tokenizer.apply_chat_template(
                messages, tokenize=True, add_generation_prompt=False
            )
            if input_ids[: len(prompt_ids)] != prompt_ids:
                raise ValueError("Chat template prompt is not a prefix of the training record")
            if len(input_ids) > max_length:
                raise ValueError(
                    f"Training record has {len(input_ids)} tokens, exceeding --max-length {max_length}"
                )
            labels = [-100] * len(prompt_ids) + input_ids[len(prompt_ids) :]
            self.items.append({
                "input_ids": input_ids,
                "attention_mask": [1] * len(input_ids),
                "labels": labels,
            })

    def __len__(self) -> int:
        return len(self.items)

    def __getitem__(self, index: int) -> dict[str, list[int]]:
        return self.items[index]


def collate(batch: list[dict[str, list[int]]], pad_token_id: int) -> dict[str, torch.Tensor]:
    max_length = max(len(item["input_ids"]) for item in batch)
    input_ids, masks, labels = [], [], []
    for item in batch:
        padding = max_length - len(item["input_ids"])
        input_ids.append(item["input_ids"] + [pad_token_id] * padding)
        masks.append(item["attention_mask"] + [0] * padding)
        labels.append(item["labels"] + [-100] * padding)
    return {
        "input_ids": torch.tensor(input_ids, dtype=torch.long),
        "attention_mask": torch.tensor(masks, dtype=torch.long),
        "labels": torch.tensor(labels, dtype=torch.long),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--learning-rate", type=float, default=2e-4)
    parser.add_argument("--max-length", type=int, default=1024)
    parser.add_argument("--gradient-accumulation", type=int, default=8)
    parser.add_argument("--validation-fraction", type=float, default=0.125)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    if not 0.0 < args.validation_fraction < 0.5:
        raise ValueError("--validation-fraction must be between 0 and 0.5")
    torch.manual_seed(args.seed)
    random.seed(args.seed)
    tokenizer = AutoTokenizer.from_pretrained(args.model, trust_remote_code=True)
    tokenizer.pad_token = tokenizer.pad_token or tokenizer.eos_token
    rows = [json.loads(line) for line in args.data.read_text(encoding="utf-8").splitlines() if line]
    random.Random(args.seed).shuffle(rows)
    validation_count = max(1, round(len(rows) * args.validation_fraction))
    validation_rows = rows[:validation_count]
    training_rows = rows[validation_count:]
    training_dataset = ChatDataset(training_rows, tokenizer, args.max_length)
    validation_dataset = ChatDataset(validation_rows, tokenizer, args.max_length)
    generator = torch.Generator().manual_seed(args.seed)
    loader = DataLoader(
        training_dataset,
        batch_size=1,
        shuffle=True,
        generator=generator,
        collate_fn=lambda batch: collate(batch, tokenizer.pad_token_id),
    )
    validation_loader = DataLoader(
        validation_dataset,
        batch_size=1,
        shuffle=False,
        collate_fn=lambda batch: collate(batch, tokenizer.pad_token_id),
    )

    model = AutoModelForCausalLM.from_pretrained(
        args.model,
        torch_dtype=torch.bfloat16,
        trust_remote_code=True,
        low_cpu_mem_usage=True,
    ).to("cuda")
    model.config.use_cache = False
    model.enable_input_require_grads()
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    lora = LoraConfig(
        r=16,
        lora_alpha=32,
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    )
    model = get_peft_model(model, lora)
    optimizer = torch.optim.AdamW((parameter for parameter in model.parameters() if parameter.requires_grad), lr=args.learning_rate)

    started = time.perf_counter()
    losses: list[float] = []
    validation_losses: list[float] = []
    args.output.mkdir(parents=True, exist_ok=True)
    best_validation_loss = float("inf")
    torch.cuda.reset_peak_memory_stats()
    for epoch in range(args.epochs):
        model.train()
        optimizer.zero_grad(set_to_none=True)
        epoch_losses: list[float] = []
        for step, batch in enumerate(loader, start=1):
            batch = {key: value.to("cuda") for key, value in batch.items()}
            with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                loss = model(**batch).loss / args.gradient_accumulation
            loss.backward()
            if step % args.gradient_accumulation == 0 or step == len(loader):
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                optimizer.step()
                optimizer.zero_grad(set_to_none=True)
            value = float(loss.detach()) * args.gradient_accumulation
            losses.append(value)
            epoch_losses.append(value)

        model.eval()
        epoch_validation_losses: list[float] = []
        with torch.no_grad():
            for batch in validation_loader:
                batch = {key: value.to("cuda") for key, value in batch.items()}
                with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                    epoch_validation_losses.append(float(model(**batch).loss.detach()))
        validation_loss = sum(epoch_validation_losses) / len(epoch_validation_losses)
        validation_losses.append(validation_loss)
        training_loss = sum(epoch_losses) / len(epoch_losses)
        print(
            f"epoch={epoch + 1} train_loss={training_loss:.4f} validation_loss={validation_loss:.4f}",
            flush=True,
        )
        if validation_loss < best_validation_loss:
            best_validation_loss = validation_loss
            model.save_pretrained(args.output)
            tokenizer.save_pretrained(args.output)

    torch.cuda.synchronize()
    metrics = {
        "base_model": str(args.model),
        "dataset_sha256": hashlib.sha256(args.data.read_bytes()).hexdigest(),
        "training_examples": len(training_dataset),
        "validation_examples": len(validation_dataset),
        "epochs": args.epochs,
        "lora_rank": 16,
        "final_training_loss": losses[-1],
        "validation_losses": validation_losses,
        "best_validation_loss": best_validation_loss,
        "elapsed_seconds": round(time.perf_counter() - started, 2),
        "gpu": torch.cuda.get_device_name(0),
        "hip": torch.version.hip,
        "peak_vram_bytes": torch.cuda.max_memory_allocated(),
        "seed": args.seed,
    }
    (args.output / "training_metrics.json").write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
