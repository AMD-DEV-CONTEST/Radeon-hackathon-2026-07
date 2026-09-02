"""
fix_retrain_engineer.py — Clean Engineer v9 retrain (disk-efficient)
=====================================================================
Base  : Qwen2.5-Coder-1.5B-Instruct  (~3 GB fp16 in HF cache)
Data  : all /workspace/data/*.jsonl   (672 samples combined)
Key   : fp16 torch_dtype, NO BitsAndBytesConfig
Disk strategy:
  - Combined JSONL → /tmp (not /workspace)
  - Adapter → /tmp/eng_adapter  (small: ~75 MB)
  - Merged model → /tmp/eng_merged  (RAM only, ~3 GB, deleted after GGUF)
  - GGUF overwrites the corrupted one in-place at OUT_GGUF
  - /tmp is container-local tmpfs, not counted against /workspace quota

Stage markers (grep STAGE in retrain.log):
  STAGE[1/6] env-check
  STAGE[2/6] load-model
  STAGE[3/6] load-data
  STAGE[4/6] train
  STAGE[5/6] merge
  STAGE[6/6] gguf
"""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

# Reduce memory fragmentation
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"

# ── paths — everything temp goes to /tmp, only GGUF lands in /workspace ────────
BASE_MODEL = "Qwen/Qwen2.5-Coder-1.5B-Instruct"
DATA_DIR = Path("/workspace/data")
OUT_ADAPTER = Path("/tmp/eng_adapter")  # ~75 MB — tmpfs, free
OUT_MERGED = Path("/tmp/eng_merged")  # ~3 GB  — tmpfs, free
OUT_GGUF = Path(
    "/workspace/outputs/determinex-engineer-v9/determinex-engineer-v9.gguf"
)  # overwrite in-place
LLAMA_CPP_DIR = Path("/workspace/llama.cpp")
TRAIN_FILE = Path("/tmp/combined_engineer.jsonl")  # /tmp, not /workspace

# ── hyper-params ──────────────────────────────────────────────────────────────
EPOCHS = 3
MAX_SEQ = 1024
BATCH_SIZE = 1
GRAD_ACCUM = 8
LR = 2e-4
LORA_R = 16
LORA_ALPHA = 32
LORA_DROP = 0.05


# ── helpers ───────────────────────────────────────────────────────────────────
def stage(n, label):
    print(f"\n{'=' * 60}", flush=True)
    print(f"STAGE[{n}/6] {label}", flush=True)
    print(f"{'=' * 60}", flush=True)


def run(cmd, **kw):
    print(f"  $ {' '.join(str(c) for c in cmd)}", flush=True)
    result = subprocess.run(cmd, **kw)
    if result.returncode != 0:
        print(f"  [ERROR] Exit {result.returncode}", flush=True)
        sys.exit(result.returncode)
    return result


def check_tmp_space():
    st = os.statvfs("/tmp")
    free_gb = st.f_bavail * st.f_frsize / 1e9
    print(f"  /tmp free: {free_gb:.1f} GB", flush=True)
    if free_gb < 5:
        print("  [WARN] /tmp has less than 5 GB — cleaning up...", flush=True)
        for p in [OUT_ADAPTER, OUT_MERGED]:
            if p.exists():
                shutil.rmtree(p)
                print(f"  Removed {p}", flush=True)


# ══════════════════════════════════════════════════════════════════════════════
# STAGE 1 — Environment check
# ══════════════════════════════════════════════════════════════════════════════
stage(1, "env-check")

import torch

print(f"  PyTorch   : {torch.__version__}", flush=True)
print(f"  CUDA avail: {torch.cuda.is_available()}", flush=True)
if torch.cuda.is_available():
    print(f"  GPU       : {torch.cuda.get_device_name(0)}", flush=True)
    total_vram = torch.cuda.get_device_properties(0).total_memory / 1e9
    print(f"  VRAM      : {total_vram:.1f} GB", flush=True)

for pkg in ["transformers", "peft", "datasets", "accelerate"]:
    try:
        __import__(pkg)
        print(f"  {pkg}: OK", flush=True)
    except ImportError:
        print(f"  Installing {pkg}...", flush=True)
        run(["pip", "install", "-q", pkg])

if not LLAMA_CPP_DIR.exists():
    print("  Cloning llama.cpp...", flush=True)
    run(
        [
            "git",
            "clone",
            "--depth",
            "1",
            "https://github.com/ggerganov/llama.cpp",
            str(LLAMA_CPP_DIR),
        ]
    )
    run(["pip", "install", "-q", "-r", str(LLAMA_CPP_DIR / "requirements.txt")])
else:
    print(f"  llama.cpp : {LLAMA_CPP_DIR} (exists)", flush=True)

check_tmp_space()

# ══════════════════════════════════════════════════════════════════════════════
# STAGE 2 — Load base model (fp16, NO BitsAndBytes)
# ══════════════════════════════════════════════════════════════════════════════
stage(2, "load-model")

from peft import LoraConfig, TaskType, get_peft_model
from transformers import AutoModelForCausalLM, AutoTokenizer

print(f"  Base model: {BASE_MODEL}", flush=True)
tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL, trust_remote_code=True)
if tokenizer.pad_token is None:
    tokenizer.pad_token = tokenizer.eos_token
tokenizer.padding_side = "right"

# KEY FIX: fp16, NO BitsAndBytesConfig
model = AutoModelForCausalLM.from_pretrained(
    BASE_MODEL,
    torch_dtype=torch.float16,
    device_map="auto",
    trust_remote_code=True,
)
model.config.use_cache = False
model.enable_input_require_grads()
model.gradient_checkpointing_enable()
print(f"  Model loaded: {sum(p.numel() for p in model.parameters()) / 1e6:.1f}M params", flush=True)

lora_config = LoraConfig(
    task_type=TaskType.CAUSAL_LM,
    r=LORA_R,
    lora_alpha=LORA_ALPHA,
    lora_dropout=LORA_DROP,
    target_modules=["q_proj", "v_proj", "k_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    bias="none",
)
model = get_peft_model(model, lora_config)
model.print_trainable_parameters()

# ══════════════════════════════════════════════════════════════════════════════
# STAGE 3 — Load + preprocess data
# ══════════════════════════════════════════════════════════════════════════════
stage(3, "load-data")

all_samples = []
for f in sorted(DATA_DIR.glob("*.jsonl")):
    if f.name.startswith("_"):
        continue
    with open(f, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                all_samples.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    print(f"  Loaded: {f.name}", flush=True)

print(f"  Total samples: {len(all_samples)}", flush=True)

# Write to /tmp — NOT /workspace
with open(TRAIN_FILE, "w", encoding="utf-8") as fh:
    for s in all_samples:
        fh.write(json.dumps(s) + "\n")
print(f"  Combined → {TRAIN_FILE} (in /tmp)", flush=True)

from datasets import load_dataset

raw = load_dataset("json", data_files=str(TRAIN_FILE), split="train")


def format_sample(sample):
    # Guard: Arrow schema null-fills missing columns across mixed-format files.
    # When distilled files (no "messages" key) are combined with gap_v3 files
    # (have "messages" as list), Arrow adds messages=null to distilled rows.
    if "messages" in sample and sample["messages"] is not None:
        parts = []
        for msg in sample["messages"]:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            parts.append(f"<|im_start|>{role}\n{content}<|im_end|>")
        text = "\n".join(parts)
    elif (
        "user" in sample
        and sample["user"] is not None
        and "assistant" in sample
        and sample["assistant"] is not None
    ):
        # Flat format used by distilled files: {system, user, assistant, ...}
        sys_text = sample.get("system") or ""
        usr_text = sample["user"]
        ast_text = sample["assistant"]
        parts = []
        if sys_text:
            parts.append(f"<|im_start|>system\n{sys_text}<|im_end|>")
        parts.append(f"<|im_start|>user\n{usr_text}<|im_end|>")
        parts.append(f"<|im_start|>assistant\n{ast_text}<|im_end|>")
        text = "\n".join(parts)
    elif "instruction" in sample and "output" in sample:
        inst = sample["instruction"]
        inp = sample.get("input", "")
        out = sample["output"]
        if inp:
            text = f"<|im_start|>user\n{inst}\n\n{inp}<|im_end|>\n<|im_start|>assistant\n{out}<|im_end|>"
        else:
            text = f"<|im_start|>user\n{inst}<|im_end|>\n<|im_start|>assistant\n{out}<|im_end|>"
    else:
        text = sample.get("text", str(sample))
    return {"text": text}


formatted = raw.map(format_sample, remove_columns=raw.column_names)
print(f"  Formatted {len(formatted)} samples", flush=True)


def tokenize(sample):
    result = tokenizer(
        sample["text"],
        truncation=True,
        max_length=MAX_SEQ,
        padding="max_length",
    )
    result["labels"] = result["input_ids"][:]
    return result


tokenized = formatted.map(tokenize, batched=False, num_proc=4, remove_columns=["text"])
print("  Tokenized OK", flush=True)

# ══════════════════════════════════════════════════════════════════════════════
# STAGE 4 — Train
# ══════════════════════════════════════════════════════════════════════════════
stage(4, "train")

from transformers import DataCollatorForLanguageModeling, Trainer, TrainingArguments

OUT_ADAPTER.mkdir(parents=True, exist_ok=True)

training_args = TrainingArguments(
    output_dir=str(OUT_ADAPTER),
    num_train_epochs=EPOCHS,
    per_device_train_batch_size=BATCH_SIZE,
    gradient_accumulation_steps=GRAD_ACCUM,
    gradient_checkpointing=True,
    learning_rate=LR,
    fp16=True,
    bf16=False,
    logging_steps=10,
    save_strategy="epoch",
    save_total_limit=1,
    report_to="none",
    dataloader_num_workers=2,
    warmup_ratio=0.05,
    lr_scheduler_type="cosine",
    optim="adamw_torch",
    remove_unused_columns=False,
    label_names=["labels"],
    ddp_find_unused_parameters=False,
)

data_collator = DataCollatorForLanguageModeling(tokenizer=tokenizer, mlm=False)

trainer = Trainer(
    model=model,
    args=training_args,
    train_dataset=tokenized,
    data_collator=data_collator,
    tokenizer=tokenizer,
)

print(f"  Training {len(tokenized)} samples × {EPOCHS} epochs...", flush=True)
t0 = time.time()
trainer.train()
elapsed = time.time() - t0
print(f"  Training done in {elapsed / 60:.1f} min", flush=True)

trainer.save_model(str(OUT_ADAPTER))
tokenizer.save_pretrained(str(OUT_ADAPTER))
print(f"  Adapter saved → {OUT_ADAPTER}", flush=True)

# Free GPU VRAM before merge
del model, trainer
if torch.cuda.is_available():
    torch.cuda.empty_cache()

# ══════════════════════════════════════════════════════════════════════════════
# STAGE 5 — Merge adapter → full fp16 model (in /tmp)
# ══════════════════════════════════════════════════════════════════════════════
stage(5, "merge")

from peft import PeftModel

print("  Loading base for merge (CPU)...", flush=True)
base_for_merge = AutoModelForCausalLM.from_pretrained(
    BASE_MODEL,
    torch_dtype=torch.float16,
    device_map="cpu",
    trust_remote_code=True,
)

print("  Loading adapter...", flush=True)
merged_model = PeftModel.from_pretrained(base_for_merge, str(OUT_ADAPTER))

print("  Merging weights...", flush=True)
merged_model = merged_model.merge_and_unload()

OUT_MERGED.mkdir(parents=True, exist_ok=True)
print(f"  Saving merged fp16 → {OUT_MERGED} (in /tmp)", flush=True)
merged_model.save_pretrained(str(OUT_MERGED), safe_serialization=True)
tokenizer.save_pretrained(str(OUT_MERGED))

del merged_model, base_for_merge
print("  Merge complete", flush=True)

# ══════════════════════════════════════════════════════════════════════════════
# STAGE 6 — Convert to GGUF q8_0, overwrite corrupted GGUF in-place
# ══════════════════════════════════════════════════════════════════════════════
stage(6, "gguf")

convert_script = LLAMA_CPP_DIR / "convert_hf_to_gguf.py"
if not convert_script.exists():
    convert_script = LLAMA_CPP_DIR / "convert.py"

# Delete the corrupted GGUF first to reclaim its 2.9 GB
if OUT_GGUF.exists():
    print(f"  Removing corrupted GGUF ({OUT_GGUF.stat().st_size / 1e6:.0f} MB)...", flush=True)
    OUT_GGUF.unlink()

OUT_GGUF.parent.mkdir(parents=True, exist_ok=True)

print(f"  Converting {OUT_MERGED} → q8_0 → {OUT_GGUF}", flush=True)
run(
    [
        "python3",
        str(convert_script),
        str(OUT_MERGED),
        "--outtype",
        "q8_0",
        "--outfile",
        str(OUT_GGUF),
    ]
)

if OUT_GGUF.exists():
    size_mb = OUT_GGUF.stat().st_size / 1e6
    print(f"  GGUF ready: {OUT_GGUF}  ({size_mb:.0f} MB)", flush=True)
else:
    print(f"  [ERROR] GGUF not found at {OUT_GGUF}", flush=True)
    sys.exit(1)

# Cleanup /tmp
print("  Cleaning /tmp...", flush=True)
shutil.rmtree(OUT_ADAPTER, ignore_errors=True)
shutil.rmtree(OUT_MERGED, ignore_errors=True)
TRAIN_FILE.unlink(missing_ok=True)

print("\n" + "=" * 60, flush=True)
print("RETRAIN COMPLETE", flush=True)
print(f"  GGUF : {OUT_GGUF}", flush=True)
print(
    f'  SCP  : scp -i ~/.ssh/id_runpod -P <PORT> root@<POD_IP>:{OUT_GGUF} "${{DETERMINEX_MODELS_DIR:-~/determinex-models}}/determinex-engineer-v9.gguf"',
    flush=True,
)
print("=" * 60, flush=True)
