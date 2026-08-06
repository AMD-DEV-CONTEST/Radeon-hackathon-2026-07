"""
GPU Guardian AI

Purpose:
    Validate local LLM inference on AMD Radeon GPU.

Author:
    Bond

Day:
    3
"""

import time
import torch
from transformers import AutoTokenizer, AutoModelForCausalLM

# --------------------------------------------------
# Configuration
# --------------------------------------------------

MODEL_NAME = "Qwen/Qwen2.5-3B-Instruct"

# --------------------------------------------------
# GPU Information
# --------------------------------------------------

print("=" * 60)
print("GPU Guardian AI - LLM Validation")
print("=" * 60)

print(f"PyTorch Version : {torch.__version__}")
print(f"GPU Available   : {torch.cuda.is_available()}")

if torch.cuda.is_available():
    print(f"GPU Device      : {torch.cuda.get_device_name(0)}")
else:
    print("GPU NOT detected!")
    exit()

print("=" * 60)



print("\nLoading tokenizer...")

start = time.time()

tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)

print(f"Tokenizer loaded in {time.time() - start:.2f} seconds")



print("\nLoading model...")

start = time.time()

model = AutoModelForCausalLM.from_pretrained(
    MODEL_NAME,
    torch_dtype="auto",
    device_map="auto"
)

print(f"Model loaded in {time.time() - start:.2f} seconds")



prompt = """
You are an expert Networking and GPU Infrastructure Engineer.

Explain load balancing in simple words.
"""

print("\nGenerating response...\n")

inputs = tokenizer(prompt, return_tensors="pt").to(model.device)



start = time.time()

outputs = model.generate(
    **inputs,
    max_new_tokens=200,
    temperature=0.7
)

elapsed = time.time() - start


response = tokenizer.decode(
    outputs[0],
    skip_special_tokens=True
)

print("=" * 60)
print(response)
print("=" * 60)

print(f"\nInference Time : {elapsed:.2f} seconds")
