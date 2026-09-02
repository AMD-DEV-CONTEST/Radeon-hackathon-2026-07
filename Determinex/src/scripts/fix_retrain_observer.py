"""
fix_retrain_observer.py — Observer v5 retrain (gap-targeted)
=============================================================
Base  : meta-llama/Llama-3.2-3B-Instruct  (~6 GB fp16 in HF cache)
Data  : all /workspace/data/*.jsonl  (includes gap_v3_arc_mutex + gap_v4_observer_specific)
Key   : fp16 torch_dtype, NO BitsAndBytesConfig
        Uses tokenizer.apply_chat_template() for correct Llama 3 formatting

Gap files that must be on pod before running:
  /workspace/data/gap_v3_arc_mutex.jsonl        (12 examples — arc_mutex collect-then-join)
  /workspace/data/gap_v4_observer_specific.jsonl (14 examples — refcell rename, first_even, go_panic fmt)

Disk strategy:
  - Combined JSONL → /tmp (not /workspace)
  - Adapter → /tmp/obs_adapter  (~75 MB)
  - Merged model → /tmp/obs_merged  (~6 GB, deleted after GGUF)
  - GGUF overwrites in-place at OUT_GGUF
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

os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"

BASE_MODEL = "meta-llama/Llama-3.2-3B-Instruct"
DATA_DIR = Path("/workspace/data")
OUT_ADAPTER = Path("/tmp/obs_adapter")
OUT_MERGED = Path("/tmp/obs_merged")
OUT_GGUF = Path("/workspace/outputs/determinex-observer-v4/determinex-observer-v4.gguf")
LLAMA_CPP_DIR = Path("/workspace/llama.cpp")
TRAIN_FILE = Path("/tmp/combined_observer.jsonl")

EPOCHS = 3
MAX_SEQ = 1024
BATCH_SIZE = 1
GRAD_ACCUM = 8
LR = 2e-4
LORA_R = 16
LORA_ALPHA = 32
LORA_DROP = 0.05


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
    if free_gb < 8:
        print("  [WARN] /tmp has less than 8 GB — cleaning up...", flush=True)
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

with open(TRAIN_FILE, "w", encoding="utf-8") as fh:
    for s in all_samples:
        fh.write(json.dumps(s) + "\n")
print(f"  Combined → {TRAIN_FILE} (in /tmp)", flush=True)

from datasets import load_dataset

raw = load_dataset("json", data_files=str(TRAIN_FILE), split="train")


def format_sample(sample):
    """
    Normalize mixed JSON formats into the model's native chat template.
    Uses tokenizer.apply_chat_template() so Llama 3 formatting is correct.
    Handles: messages[] format, flat {system,user,assistant} format,
             instruction/output format, Arrow null-filling from mixed schemas.
    """
    messages = None

    if "messages" in sample and sample["messages"] is not None:
        messages = [
            {"role": msg.get("role", "user"), "content": msg.get("content", "")}
            for msg in sample["messages"]
        ]
    elif (
        "user" in sample
        and sample["user"] is not None
        and "assistant" in sample
        and sample["assistant"] is not None
    ):
        messages = []
        sys_text = sample.get("system") or ""
        if sys_text:
            messages.append({"role": "system", "content": sys_text})
        messages.append({"role": "user", "content": sample["user"]})
        messages.append({"role": "assistant", "content": sample["assistant"]})
    elif "instruction" in sample and "output" in sample:
        inp = sample.get("input", "")
        user_content = f"{sample['instruction']}\n\n{inp}" if inp else sample["instruction"]
        messages = [
            {"role": "user", "content": user_content},
            {"role": "assistant", "content": sample["output"]},
        ]

    if messages is not None:
        text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=False)
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
# STAGE 6 — Convert to GGUF q8_0, overwrite in-place
# ══════════════════════════════════════════════════════════════════════════════
stage(6, "gguf")

convert_script = LLAMA_CPP_DIR / "convert_hf_to_gguf.py"
if not convert_script.exists():
    convert_script = LLAMA_CPP_DIR / "convert.py"

if OUT_GGUF.exists():
    print(f"  Removing old GGUF ({OUT_GGUF.stat().st_size / 1e6:.0f} MB)...", flush=True)
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

print("  Cleaning /tmp...", flush=True)
shutil.rmtree(OUT_ADAPTER, ignore_errors=True)
shutil.rmtree(OUT_MERGED, ignore_errors=True)
TRAIN_FILE.unlink(missing_ok=True)

print("\n" + "=" * 60, flush=True)
print("RETRAIN COMPLETE — Observer v5", flush=True)
print(f"  GGUF : {OUT_GGUF}", flush=True)
print(
    f'  SCP  : scp -i ~/.ssh/id_runpod -P <PORT> root@<POD_IP>:{OUT_GGUF} "${{DETERMINEX_MODELS_DIR:-~/determinex-models}}/determinex-observer-v4.gguf"',
    flush=True,
)
print("=" * 60, flush=True)
