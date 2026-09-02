"""
fix_sen_merge_gguf.py — Resume Sentinel retrain from saved adapter
===================================================================
The Stage 4 (train) completed cleanly — adapter at /workspace/tmp_sen_adapter.
The Stage 5 (merge) OOM'd while writing shard 2.
This script reruns Stage 5 + Stage 6 only, starting from the saved adapter.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer

BASE_MODEL = "mistralai/Mistral-7B-Instruct-v0.3"
OUT_ADAPTER = Path("/workspace/tmp_sen_adapter")
OUT_MERGED = Path("/workspace/tmp_sen_merged")
OUT_GGUF = Path("/workspace/outputs/determinex-sentinel-v3/determinex-sentinel-v3.gguf")
LLAMA_CPP_DIR = Path("/workspace/llama.cpp")


def run(cmd):
    print(f"  $ {' '.join(str(c) for c in cmd)}", flush=True)
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print(f"  [ERROR] Exit {result.returncode}", flush=True)
        sys.exit(result.returncode)


# Clean any partial merged dir
if OUT_MERGED.exists():
    print(
        f"Removing partial merged dir ({sum(f.stat().st_size for f in OUT_MERGED.rglob('*') if f.is_file()) / 1e9:.1f} GB)...",
        flush=True,
    )
    shutil.rmtree(OUT_MERGED)

print("=" * 60, flush=True)
print("STAGE[5/6] merge", flush=True)
print("=" * 60, flush=True)

tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL, trust_remote_code=True)

print("Loading base model on CPU...", flush=True)
base_model = AutoModelForCausalLM.from_pretrained(
    BASE_MODEL,
    torch_dtype=torch.float16,
    device_map="cpu",
    trust_remote_code=True,
)

print(f"Loading adapter from {OUT_ADAPTER}...", flush=True)
merged = PeftModel.from_pretrained(base_model, str(OUT_ADAPTER))

print("Merging weights...", flush=True)
merged = merged.merge_and_unload()

OUT_MERGED.mkdir(parents=True, exist_ok=True)
print(f"Saving merged fp16 → {OUT_MERGED}...", flush=True)
merged.save_pretrained(str(OUT_MERGED), safe_serialization=True)
tokenizer.save_pretrained(str(OUT_MERGED))
del merged, base_model
print("Merge complete.", flush=True)

print("=" * 60, flush=True)
print("STAGE[6/6] gguf", flush=True)
print("=" * 60, flush=True)

convert_script = LLAMA_CPP_DIR / "convert_hf_to_gguf.py"
if not convert_script.exists():
    convert_script = LLAMA_CPP_DIR / "convert.py"

if OUT_GGUF.exists():
    print(f"Removing old GGUF ({OUT_GGUF.stat().st_size / 1e6:.0f} MB)...", flush=True)
    OUT_GGUF.unlink()

OUT_GGUF.parent.mkdir(parents=True, exist_ok=True)
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

if not OUT_GGUF.exists():
    print("[ERROR] GGUF not found after conversion", flush=True)
    sys.exit(1)

size_mb = OUT_GGUF.stat().st_size / 1e6
print(f"GGUF ready: {OUT_GGUF}  ({size_mb:.0f} MB)", flush=True)

print("Cleaning workspace tmp dirs...", flush=True)
shutil.rmtree(OUT_MERGED, ignore_errors=True)
shutil.rmtree(OUT_ADAPTER, ignore_errors=True)

print("=" * 60, flush=True)
print("RETRAIN COMPLETE — Sentinel v4 (merge+gguf recovery)", flush=True)
print(f"  GGUF : {OUT_GGUF}", flush=True)
print("=" * 60, flush=True)
