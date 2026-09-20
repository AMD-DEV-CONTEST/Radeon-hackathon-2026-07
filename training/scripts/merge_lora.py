"""Merge LoRA adapter weights into base model.

After QLoRA fine-tuning, the LoRA adapter must be merged into the
base model weights so it can be served by vLLM without the --enable-lora
flag (which forces V0 engine fallback on ROCm).

Usage:
    /opt/venv/bin/python training/scripts/merge_lora.py \
        --base-model Qwen/Qwen2.5-7B-Instruct \
        --adapter-path models/qwen-trader-lora/final \
        --output-path models/qwen-trader-merged
"""

from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer


def merge_lora(
    base_model_name: str,
    adapter_path: str,
    output_path: str,
) -> str:
    """Merge LoRA adapter into base model.

    Args:
        base_model_name: HuggingFace model name or local path.
        adapter_path: Path to the LoRA adapter directory.
        output_path: Where to save the merged model.

    Returns:
        Path to the merged model directory.
    """
    print(f"[Merge] Loading base model: {base_model_name}")
    print(f"[Merge] ROCm available: {torch.cuda.is_available()}")

    # Load base model in FP16 (no quantization for merge)
    model = AutoModelForCausalLM.from_pretrained(
        base_model_name,
        torch_dtype=torch.float16,
        device_map="auto",
        trust_remote_code=True,
    )

    # Load tokenizer
    tokenizer = AutoTokenizer.from_pretrained(
        base_model_name,
        trust_remote_code=True,
    )

    # Load LoRA adapter
    print(f"[Merge] Loading LoRA adapter: {adapter_path}")
    model = PeftModel.from_pretrained(model, adapter_path)

    # Merge weights
    print("[Merge] Merging LoRA weights...")
    model = model.merge_and_unload()

    # Ensure output directory exists
    os.makedirs(output_path, exist_ok=True)

    # Save merged model
    print(f"[Merge] Saving merged model to {output_path}...")
    model.save_pretrained(output_path, safe_serialization=True)
    tokenizer.save_pretrained(output_path)

    print(f"[Merge] Done! Merged model saved to {output_path}")

    # Verify
    saved_files = list(Path(output_path).glob("*.safetensors"))
    print(f"[Merge] Saved {len(saved_files)} safetensors files")
    if not saved_files:
        saved_files = list(Path(output_path).glob("*.bin"))
        print(f"[Merge] Saved {len(saved_files)} .bin files")

    return output_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Merge LoRA into base model")
    parser.add_argument("--base-model", type=str, default="Qwen/Qwen2.5-7B-Instruct")
    parser.add_argument("--adapter-path", type=str, required=True)
    parser.add_argument("--output-path", type=str, required=True)
    args = parser.parse_args()

    merge_lora(
        base_model_name=args.base_model,
        adapter_path=args.adapter_path,
        output_path=args.output_path,
    )
