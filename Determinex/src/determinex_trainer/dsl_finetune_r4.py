"""
dsl_finetune.py — DSL fine-tuning for Determinex agents (Observer / Engineer / Sentinel)
=======================================================================================
Trains one model at a time from its base checkpoint using ALL available training data
(existing curriculum + gap files + dsl_corpus.jsonl). LoRA rank 8 (lower than the gap
retrains' rank 16) to minimise catastrophic forgetting while adding DSL capability.

Run on RunPod (RTX 4090, 24 GB VRAM). Sequence via master_dsl_finetune.sh.

Usage:
  python dsl_finetune.py observer   # Observer v5
  python dsl_finetune.py engineer   # Engineer v10
  python dsl_finetune.py sentinel   # Sentinel v4 (DSL)

Stage markers (grep STAGE in retrain.log):
  STAGE[1/6] env-check
  STAGE[2/6] load-model
  STAGE[3/6] load-data
  STAGE[4/6] train
  STAGE[5/6] merge
  STAGE[6/6] gguf

After GGUF is produced, stop here, scp the GGUF to local, run micro_eval.py,
compare delta against baseline, then decide whether to proceed to the next model.
Rollback rules (per plan Gap 5):
  delta >= 0%       → ACCEPT. Proceed to next model.
  delta -1% to 0%   → ACCEPT with note. Negligible regression.
  delta -1% to -3%  → REDUCE LoRA rank to 4, re-run this model.
  delta < -3% at r4 → REJECT. Model does not accept DSL fine-tune.
                      Use Layer 1 DSL without fine-tuning for this model.
"""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"

# ── Model configs ──────────────────────────────────────────────────────────────
_HF_CACHE = Path("/workspace/hf_models")  # pre-fetched by tonight_launch.py

MODELS = {
    "observer": {
        # Switched from gated Llama-3.2-3B → open Qwen2.5-Coder-3B (same size, no token needed)
        "hf_id": str(_HF_CACHE / "qwen3b")
        if (_HF_CACHE / "qwen3b").exists()
        else "Qwen/Qwen2.5-Coder-3B-Instruct",
        "gated": False,
        "out_name": "determinex-3-medium-v1.1",
        "adapter": Path("/tmp/dsl_obs_adapter"),
        "merged": Path("/tmp/dsl_obs_merged"),
        "gguf_dir": Path("/workspace/outputs/determinex-3-medium-v1.1"),
        "train_file": Path("/tmp/dsl_obs_train.jsonl"),
        "disk_note": "Adapter + merged on /tmp (~6 GB needed)",
    },
    "engineer": {
        "hf_id": str(_HF_CACHE / "qwen1.5b")
        if (_HF_CACHE / "qwen1.5b").exists()
        else "Qwen/Qwen2.5-Coder-1.5B-Instruct",
        "gated": False,
        "out_name": "determinex-1-tiny-v1.1",
        "adapter": Path("/tmp/dsl_eng_adapter"),
        "merged": Path("/tmp/dsl_eng_merged"),
        "gguf_dir": Path("/workspace/outputs/determinex-1-tiny-v1.1"),
        "train_file": Path("/tmp/dsl_eng_train.jsonl"),
        "disk_note": "Adapter + merged on /tmp (~3 GB, fits easily)",
    },
    "sentinel": {
        "hf_id": str(_HF_CACHE / "mistral7b")
        if (_HF_CACHE / "mistral7b").exists()
        else "mistralai/Mistral-7B-Instruct-v0.3",
        "gated": False,
        "out_name": "determinex-7-large-v1.1",
        "adapter": Path("/workspace/tmp_dsl_sen_adapter"),
        "merged": Path("/workspace/tmp_dsl_sen_merged"),
        "gguf_dir": Path("/workspace/outputs/determinex-7-large-v1.1"),
        "train_file": Path("/workspace/tmp_dsl_sen_train.jsonl"),
        "disk_note": "Adapter + merged on /workspace — 7B too large for /tmp",
    },
}

DATA_DIR = Path("/workspace/data")  # all .jsonl files here are used
DSL_CORPUS = Path("/workspace/data/dsl_corpus.jsonl")
LLAMA_CPP_DIR = Path("/workspace/llama.cpp")

# ── LoRA hyper-params (DSL fine-tune — rank 8, lower than gap retrain rank 16) ─
LORA_R = 4  # rank 4: Gap 5 rollback — C1-tiny regressed -3% at rank 8
LORA_ALPHA = 8  # alpha = 2 * rank (standard)
LORA_DROP = 0.05
EPOCHS = 3
MAX_SEQ = 512  # DSL packets are short — 512 is ample, saves VRAM
BATCH_SIZE = 2  # can double batch vs gap retrain due to shorter sequences
GRAD_ACCUM = 4
LR = 2e-4


def stage(n, label):
    print(f"\n{'=' * 60}", flush=True)
    print(f"STAGE[{n}/6] {label}", flush=True)
    print(f"{'=' * 60}", flush=True)


def run(cmd, **kwargs):
    print(f"  $ {' '.join(str(c) for c in cmd)}", flush=True)
    result = subprocess.run(cmd, **kwargs)
    if result.returncode != 0:
        print(f"  [FAIL] exit code {result.returncode}", flush=True)
        sys.exit(result.returncode)
    return result


def check_dsl_corpus():
    """Verify dsl_corpus.jsonl exists and has enough pairs."""
    if not DSL_CORPUS.exists():
        print(f"\n[ERROR] DSL corpus not found: {DSL_CORPUS}")
        print("  Upload dsl_corpus.jsonl to /workspace/data/ before running.")
        print("  scp -P PORT -i ~/.ssh/id_runpod scripts/dsl_corpus.jsonl root@POD:data/")
        sys.exit(1)
    count = sum(1 for _ in open(DSL_CORPUS))
    print(f"  DSL corpus: {count} examples at {DSL_CORPUS}")
    if count < 500:
        print(f"  [WARN] Only {count} DSL examples — expected ~2000. Fine-tune may be weak.")
    return count


def build_training_file(cfg: dict) -> int:
    """
    Combine ALL jsonl files in DATA_DIR (curriculum + gap + dsl_corpus) into
    a single training file. This is the same approach as the existing retrain
    scripts — DSL data adds alongside existing training, not replacing it.
    """
    train_file = cfg["train_file"]
    train_file.parent.mkdir(parents=True, exist_ok=True)

    all_examples = []
    sources = sorted(DATA_DIR.glob("*.jsonl"))
    if not sources:
        print(f"  [ERROR] No .jsonl files found in {DATA_DIR}")
        sys.exit(1)

    for src in sources:
        with open(src) as f:
            examples = [json.loads(line) for line in f if line.strip()]
        print(f"  {src.name}: {len(examples)} examples")
        all_examples.extend(examples)

    # Shuffle to interleave DSL data with existing curriculum
    import random

    random.seed(42)
    random.shuffle(all_examples)

    with open(train_file, "w") as f:
        for ex in all_examples:
            f.write(json.dumps(ex) + "\n")

    print(f"  Combined: {len(all_examples)} total examples → {train_file}")
    return len(all_examples)


def train(cfg: dict, model_name: str):
    """Run LoRA fine-tuning via Unsloth + SFTTrainer."""
    import torch
    from datasets import Dataset
    from trl import SFTTrainer

    try:
        from unsloth import FastLanguageModel

        USE_UNSLOTH = True
    except (ImportError, RuntimeError):
        from transformers import AutoModelForCausalLM, AutoTokenizer

        USE_UNSLOTH = False
        print("  [WARN] Unsloth not available — falling back to standard transformers")

    print(f"  Base model : {cfg['hf_id']}", flush=True)
    print(f"  LoRA rank  : {LORA_R}", flush=True)
    print(f"  Epochs     : {EPOCHS}", flush=True)
    print(f"  Max seq    : {MAX_SEQ}", flush=True)

    if USE_UNSLOTH:
        model, tokenizer = FastLanguageModel.from_pretrained(
            model_name=cfg["hf_id"],
            max_seq_length=MAX_SEQ,
            dtype=torch.float16,
            load_in_4bit=False,
        )
        model = FastLanguageModel.get_peft_model(
            model,
            r=LORA_R,
            target_modules=[
                "q_proj",
                "k_proj",
                "v_proj",
                "o_proj",
                "gate_proj",
                "up_proj",
                "down_proj",
            ],
            lora_alpha=LORA_ALPHA,
            lora_dropout=LORA_DROP,
            bias="none",
            use_gradient_checkpointing="unsloth",
            random_state=42,
        )
    else:
        from peft import LoraConfig, get_peft_model

        tokenizer = AutoTokenizer.from_pretrained(cfg["hf_id"])
        model = AutoModelForCausalLM.from_pretrained(
            cfg["hf_id"], torch_dtype=torch.float16, device_map="auto"
        )
        lora_cfg = LoraConfig(
            r=LORA_R,
            lora_alpha=LORA_ALPHA,
            lora_dropout=LORA_DROP,
            target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
            bias="none",
            task_type="CAUSAL_LM",
        )
        model = get_peft_model(model, lora_cfg)

    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    # Load combined training file
    raw = [json.loads(l) for l in open(cfg["train_file"]) if l.strip()]

    def format_example(ex):
        """Apply chat template to messages list. Works for Llama 3, Mistral, Qwen2."""
        msgs = ex.get("messages", [])
        if not msgs:
            return {"text": ""}
        try:
            text = tokenizer.apply_chat_template(msgs, tokenize=False, add_generation_prompt=False)
        except Exception:
            # Fallback: concatenate role: content
            text = "\n".join(f"{m['role'].upper()}: {m['content']}" for m in msgs)
        return {"text": text}

    dataset = Dataset.from_list([format_example(ex) for ex in raw])
    dataset = dataset.filter(lambda x: len(x["text"]) > 10)
    print(f"  Training examples: {len(dataset)}", flush=True)

    # trl 1.2.0: SFTConfig holds dataset_text_field + max_length (renamed from max_seq_length)
    from trl import SFTConfig as _SFTConfig

    training_args = _SFTConfig(
        output_dir=str(cfg["adapter"]),
        num_train_epochs=EPOCHS,
        per_device_train_batch_size=BATCH_SIZE,
        gradient_accumulation_steps=GRAD_ACCUM,
        learning_rate=LR,
        fp16=True,
        logging_steps=10,
        save_strategy="no",
        optim="adamw_8bit" if USE_UNSLOTH else "adamw_torch",
        warmup_ratio=0.05,
        lr_scheduler_type="cosine",
        seed=42,
        report_to="none",
        max_length=MAX_SEQ,
        dataset_text_field="text",
    )
    trainer = SFTTrainer(
        model=model,
        processing_class=tokenizer,
        train_dataset=dataset,
        args=training_args,
    )

    print("  Training...", flush=True)
    trainer.train()
    print("  Training complete.", flush=True)

    # Save adapter
    cfg["adapter"].mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(cfg["adapter"]))
    tokenizer.save_pretrained(str(cfg["adapter"]))
    print(f"  Adapter saved: {cfg['adapter']}", flush=True)

    return model, tokenizer


def merge_and_gguf(cfg: dict, model, tokenizer):
    """Merge LoRA adapter into base, save merged model, convert to GGUF."""
    try:
        merged = model.merge_and_unload()
    except Exception:
        merged = model.merge_and_unload()

    cfg["merged"].mkdir(parents=True, exist_ok=True)
    merged.save_pretrained(str(cfg["merged"]), safe_serialization=True)
    tokenizer.save_pretrained(str(cfg["merged"]))
    print(f"  Merged model saved: {cfg['merged']}", flush=True)

    # Convert to GGUF (q8_0 — lossless enough for eval, manageable size)
    cfg["gguf_dir"].mkdir(parents=True, exist_ok=True)
    gguf_path = cfg["gguf_dir"] / f"{cfg['out_name']}.gguf"
    convert_script = LLAMA_CPP_DIR / "convert_hf_to_gguf.py"
    run(
        [
            "python3",
            str(convert_script),
            str(cfg["merged"]),
            "--outfile",
            str(gguf_path),
            "--outtype",
            "q8_0",
        ]
    )

    # Verify GGUF header
    magic = open(gguf_path, "rb").read(4)
    if magic != b"GGUF":
        print(f"  [FAIL] GGUF header invalid: {magic}")
        sys.exit(1)
    size_gb = gguf_path.stat().st_size / 1e9
    print(f"  GGUF OK: {gguf_path} ({size_gb:.2f} GB)", flush=True)

    # Cleanup merged model to free disk
    shutil.rmtree(cfg["merged"], ignore_errors=True)
    print("  Merged model deleted (disk freed)", flush=True)

    return gguf_path


def print_next_steps(cfg: dict, gguf_path: Path, model_name: str, port: int = 10247):
    """Print exact commands for download, micro_eval, and proceed/rollback decision."""
    local_path = f"${{DETERMINEX_MODELS_DIR:-~/determinex-models}}/versions/{model_name.replace('determinex-', '').split('-v')[0]}/{cfg['out_name'].split('-v')[1].split('-')[0]}-dsl/{cfg['out_name']}.gguf"
    print(
        f"""
{"=" * 60}
  GGUF READY — {cfg["out_name"]}
{"=" * 60}

Next steps (run on LOCAL machine):

1. Download GGUF:
   scp -P {port} -i ~/.ssh/id_runpod \\
     root@POD_IP:{gguf_path} \\
     "{local_path}"

2. Register with Ollama for micro_eval:
   ollama create {cfg["out_name"]} -f Modelfiles/Modelfile.{model_name.split("-")[1]}

3. Run micro_eval (compare against current baseline):
   python scripts/micro_eval.py --model {cfg["out_name"]}
   # Baseline: compare against the PREVIOUS version's score

4. Apply rollback rules (plan Gap 5):
   delta >= 0%            → ACCEPT. Proceed to next model.
   delta -1% to 0%        → ACCEPT with note.
   delta -1% to -3%       → Re-run with LORA_R=4 (edit dsl_finetune.py line ~41)
   delta < -3% at rank 4  → REJECT. Skip DSL fine-tune for this model.

5. If ACCEPTED — proceed to next model on pod.
   If REJECTED — do NOT proceed; note which model rejected DSL fine-tune.

{"=" * 60}
""",
        flush=True,
    )


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in MODELS:
        print("Usage: python dsl_finetune.py {observer|engineer|sentinel}")
        print(f"  observer  → {MODELS['observer']['hf_id']} → {MODELS['observer']['out_name']}")
        print(f"  engineer  → {MODELS['engineer']['hf_id']} → {MODELS['engineer']['out_name']}")
        print(f"  sentinel  → {MODELS['sentinel']['hf_id']} → {MODELS['sentinel']['out_name']}")
        sys.exit(1)

    model_name = sys.argv[1]
    cfg = MODELS[model_name]

    print(f"\n{'=' * 60}", flush=True)
    print(f"  DSL FINE-TUNE: {model_name.upper()} → {cfg['out_name']}", flush=True)
    print(f"  Started: {time.strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
    print(f"  LoRA rank: {LORA_R}  |  Epochs: {EPOCHS}  |  Max seq: {MAX_SEQ}", flush=True)
    print(f"  {cfg['disk_note']}", flush=True)
    print(f"{'=' * 60}", flush=True)

    # STAGE 1 — env check
    stage(1, "env-check")
    run(["nvidia-smi", "--query-gpu=name,memory.total,memory.free", "--format=csv,noheader"])
    if subprocess.run(["df", "-h", "/", "/workspace", "/tmp"], check=False).returncode != 0:
        subprocess.run(["df", "-h", "/"], check=False)
    run(
        [
            "python3",
            "-c",
            "import torch; print('CUDA:', torch.cuda.is_available(), '|', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'N/A')",
        ]
    )
    subprocess.run(["python3", "-c", "import unsloth; print('Unsloth OK')"], check=False)

    # Verify DSL corpus is present
    dsl_count = check_dsl_corpus()

    if cfg["gated"]:
        print(f"\n  [NOTE] {cfg['hf_id']} is a gated model. Ensure HF_TOKEN is set.")
        hf_token = os.environ.get("HF_TOKEN", "")
        if not hf_token:
            print("  [WARN] HF_TOKEN not set — download may fail.")

    # STAGE 2 — load model (implicit in train(), just print disk state)
    stage(2, "load-model")
    print(f"  Model: {cfg['hf_id']}")
    print("  Will download to ~/.cache/huggingface/ (overlay filesystem)")
    r = subprocess.run(["df", "-h", str(Path.home() / ".cache")], check=False)
    if r.returncode != 0:
        subprocess.run(["df", "-h", "/"], check=False)

    # STAGE 3 — build training file
    stage(3, "load-data")
    total_examples = build_training_file(cfg)
    dsl_fraction = dsl_count / total_examples * 100
    print(f"  DSL examples: {dsl_count}/{total_examples} ({dsl_fraction:.1f}% of training set)")

    # STAGE 4 — train
    stage(4, "train")
    model, tokenizer = train(cfg, model_name)

    # STAGE 5 — merge
    stage(5, "merge")
    gguf_path = merge_and_gguf(cfg, model, tokenizer)

    # STAGE 6 — verify GGUF
    stage(6, "gguf")
    size_gb = gguf_path.stat().st_size / 1e9
    print(f"  Output: {gguf_path}")
    print(f"  Size  : {size_gb:.2f} GB")
    magic = open(gguf_path, "rb").read(4)
    print(f"  Magic : {magic} ({'OK' if magic == b'GGUF' else 'CORRUPT'})")

    print_next_steps(cfg, gguf_path, cfg["out_name"])

    print(f"\n  Finished: {time.strftime('%Y-%m-%d %H:%M:%S')}", flush=True)


if __name__ == "__main__":
    main()
