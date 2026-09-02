"""
merge_adapter.py — Determinex LoRA Merger

Loads the base model in FP16 (bypassing 4-bit quantization limits), attaching the trained LoRA adapter,
and saving the merged FP16 model to disk for llama.cpp / Ollama conversion.
"""

import os
from pathlib import Path

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer

BASE_MODEL = "unsloth/Llama-3.2-3B-Instruct-bnb-4bit"

# Use unsloth's base model (not 4-bit quantized)
TRUE_BASE_MODEL = "unsloth/Llama-3.2-3B-Instruct"
_ROOT = Path(os.environ.get("DETERMINEX_ROOT", Path(__file__).parent.parent))
LORA_PATH = str(
    _ROOT / "scripts" / "fine_tuning" / "outputs" / "determinex-engineer-v5" / "lora_adapter"
)
OUT_PATH = str(_ROOT / "scripts" / "fine_tuning" / "outputs" / "determinex-engineer-v5" / "merged")

print(f"Loading true base model in FP16: {TRUE_BASE_MODEL}...")
tokenizer = AutoTokenizer.from_pretrained(TRUE_BASE_MODEL)

model = AutoModelForCausalLM.from_pretrained(
    TRUE_BASE_MODEL,
    torch_dtype=torch.float16,
    device_map="cpu",  # Merge on CPU to save VRAM
)

print(f"Loading LoRA adapter from {LORA_PATH}...")
peft_model = PeftModel.from_pretrained(model, LORA_PATH)

print("Merging weights...")
merged_model = peft_model.merge_and_unload()

print(f"Saving merged FP16 model to {OUT_PATH}...")
merged_model.save_pretrained(OUT_PATH)
tokenizer.save_pretrained(OUT_PATH)

print("Merge complete! Ready for Ollama import.")
print()
print("  Next step — register with Ollama:")
print(f"    echo 'FROM {OUT_PATH}' > Modelfile.engineer.v5")
print("    ollama create determinex-student:v5trained -f Modelfile.engineer.v5")
