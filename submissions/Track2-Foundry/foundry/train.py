"""LoRA fine-tune of the student on the synthetic dataset.

Backend "peft" is the portable baseline (exercised on CUDA today, runs
unchanged on ROCm because torch exposes HIP as torch.cuda). Backend
"unsloth" is the first choice on the Radeon image — its branch below is
UNEXERCISED until the week-1 gate on granted hardware and must not be
trusted before that run.

Target construction: the prompt is the tokenizer's own chat-template
render (generation prompt included), and the completion is our target
JSON + <|im_end|>. Eval renders the identical prompt, so train and
inference agree by construction rather than by template introspection.
"""

import json
import math
import random
from pathlib import Path

import torch
from torch.utils.data import DataLoader

MIN_FREE_VRAM_GIB = 3.0


def _check_vram():
    free, total = torch.cuda.mem_get_info()
    free_gib, total_gib = free / 2**30, total / 2**30
    if free_gib < MIN_FREE_VRAM_GIB:
        raise RuntimeError(
            f"VRAM check failed: {free_gib:.2f} GiB free of {total_gib:.2f} GiB total, "
            f"need >= {MIN_FREE_VRAM_GIB} GiB. Is the teacher server still running?"
        )
    print(f"vram: {free_gib:.2f} GiB free / {total_gib:.2f} GiB total", flush=True)


def _load_rows(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def _build_examples(rows, tokenizer, max_seq_len, spec):
    from . import task

    im_end = tokenizer.convert_tokens_to_ids("<|im_end|>")
    if im_end is None:
        raise RuntimeError("tokenizer has no <|im_end|> token — wrong student model?")
    examples, dropped = [], 0
    for row in rows:
        prompt_text = tokenizer.apply_chat_template(
            task.student_messages(spec, row[spec.input_field]),
            add_generation_prompt=True,
            enable_thinking=False,
            tokenize=False,
        )
        prompt_ids = tokenizer(prompt_text, add_special_tokens=False)["input_ids"]
        target = tokenizer(
            task.target_text(spec, row),
            add_special_tokens=False,
        )["input_ids"] + [im_end]
        input_ids = prompt_ids + target
        if len(input_ids) > max_seq_len:
            dropped += 1
            continue
        labels = [-100] * len(prompt_ids) + target
        examples.append((input_ids, labels))
    if dropped:
        print(f"train: dropped {dropped} over-length examples", flush=True)
    return examples


def _collate(batch, pad_id):
    max_len = max(len(ids) for ids, _ in batch)
    input_ids, labels, attn = [], [], []
    for ids, lab in batch:
        pad = max_len - len(ids)
        input_ids.append(ids + [pad_id] * pad)
        labels.append(lab + [-100] * pad)
        attn.append([1] * len(ids) + [0] * pad)
    return (
        torch.tensor(input_ids),
        torch.tensor(labels),
        torch.tensor(attn),
    )


def _load_peft_model(cfg, tokenizer):
    from peft import LoraConfig, get_peft_model
    from transformers import AutoModelForCausalLM

    model = AutoModelForCausalLM.from_pretrained(
        cfg["student"]["hf_path"],
        dtype=torch.bfloat16,
        attn_implementation="sdpa",
    ).to(cfg["student"]["device"])
    lora = LoraConfig(
        r=cfg["train"]["lora_r"],
        lora_alpha=cfg["train"]["lora_alpha"],
        lora_dropout=cfg["train"]["lora_dropout"],
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
        task_type="CAUSAL_LM",
    )
    return get_peft_model(model, lora)


def _load_unsloth_model(cfg, tokenizer):
    # UNEXERCISED until the week-1 gate on the granted Radeon image.
    # Mirrors the peft branch: same inputs, same LoRA geometry, same
    # outputs (a peft model the shared loop below can train and merge).
    from unsloth import FastLanguageModel

    model, _ = FastLanguageModel.from_pretrained(
        model_name=str(cfg["student"]["hf_path"]),
        max_seq_length=cfg["train"]["max_seq_len"],
        dtype=torch.bfloat16,
        load_in_4bit=False,
    )
    return FastLanguageModel.get_peft_model(
        model,
        r=cfg["train"]["lora_r"],
        lora_alpha=cfg["train"]["lora_alpha"],
        lora_dropout=cfg["train"]["lora_dropout"],
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
    )


def train(cfg: dict, run_dir: Path) -> dict:
    from transformers import AutoTokenizer

    from .spec import TaskSpec

    torch.manual_seed(cfg["run"]["seed"])
    _check_vram()

    overrides_path = run_dir / "train_overrides.json"
    if overrides_path.exists():
        ov = json.loads(overrides_path.read_text(encoding="utf-8"))
        cfg["train"]["epochs"] = ov.get("epochs", cfg["train"]["epochs"])
        cfg["train"]["lr"] = ov.get("lr", cfg["train"]["lr"])
        print(f"train: overrides applied {ov}", flush=True)

    spec = TaskSpec.load(run_dir / "spec.json")
    tokenizer = AutoTokenizer.from_pretrained(cfg["student"]["hf_path"])
    pad_id = tokenizer.pad_token_id
    if pad_id is None:
        pad_id = tokenizer.eos_token_id

    rows = _load_rows(run_dir / "train.jsonl")
    examples = _build_examples(rows, tokenizer, cfg["train"]["max_seq_len"], spec)

    backend = cfg["train"]["backend"]
    if backend == "peft":
        model = _load_peft_model(cfg, tokenizer)
    elif backend == "unsloth":
        model = _load_unsloth_model(cfg, tokenizer)
    else:
        raise ValueError(f"unknown train backend: {backend}")
    model.print_trainable_parameters()

    bs = cfg["train"]["batch_size"]
    accum = cfg["train"]["grad_accum"]
    epochs = cfg["train"]["epochs"]
    loader = DataLoader(
        examples,
        batch_size=bs,
        shuffle=True,
        generator=torch.Generator().manual_seed(cfg["run"]["seed"]),
        collate_fn=lambda b: _collate(b, pad_id),
    )
    steps_per_epoch = math.ceil(len(loader) / accum)
    total_steps = steps_per_epoch * epochs
    warmup = min(10, total_steps // 10)

    optim = torch.optim.AdamW(
        (p for p in model.parameters() if p.requires_grad), lr=cfg["train"]["lr"]
    )

    def lr_lambda(step):
        if step < warmup:
            return (step + 1) / warmup
        progress = (step - warmup) / max(1, total_steps - warmup)
        return 0.5 * (1 + math.cos(math.pi * progress))

    sched = torch.optim.lr_scheduler.LambdaLR(optim, lr_lambda)

    device = cfg["student"]["device"]
    model.train()
    log_path = run_dir / "train_log.jsonl"
    step, micro = 0, 0
    losses = []
    with open(log_path, "w", encoding="utf-8") as log:
        for epoch in range(epochs):
            for input_ids, labels, attn in loader:
                out = model(
                    input_ids=input_ids.to(device),
                    attention_mask=attn.to(device),
                )
                # Loss only over labeled (target) positions. Passing labels
                # into the HF forward upcasts the full [B,S,vocab] logits to
                # float32 (~2.5GB at vocab 152K) — OOM on 8GB. Our targets
                # are ~25 tokens/example, so gather those rows first.
                logits = out.logits[:, :-1]
                labels_shift = labels[:, 1:].to(device)
                mask = labels_shift != -100
                loss = torch.nn.functional.cross_entropy(
                    logits[mask].float(), labels_shift[mask]
                )
                (loss / accum).backward()
                losses.append(loss.item())
                micro += 1
                if micro % accum == 0:
                    torch.nn.utils.clip_grad_norm_(
                        (p for p in model.parameters() if p.requires_grad), 1.0
                    )
                    optim.step()
                    sched.step()
                    optim.zero_grad()
                    step += 1
                    if step % 10 == 0 or step == total_steps:
                        avg = sum(losses[-10 * accum :]) / len(losses[-10 * accum :])
                        rec = {"step": step, "of": total_steps, "epoch": epoch,
                               "loss": round(avg, 4), "lr": sched.get_last_lr()[0]}
                        print(f"train: {rec}", flush=True)
                        log.write(json.dumps(rec) + "\n")

    adapter_dir = run_dir / "adapter"
    model.save_pretrained(str(adapter_dir))
    merged = model.merge_and_unload()
    merged_dir = run_dir / "merged"
    merged.save_pretrained(str(merged_dir), safe_serialization=True)
    tokenizer.save_pretrained(str(merged_dir))
    print(f"train: adapter -> {adapter_dir}, merged -> {merged_dir}", flush=True)

    return {
        "backend": backend,
        "examples": len(examples),
        "total_steps": total_steps,
        "final_loss": round(sum(losses[-20:]) / min(20, len(losses)), 4),
    }
