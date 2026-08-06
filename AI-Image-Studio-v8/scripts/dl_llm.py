import os
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
from huggingface_hub import snapshot_download
p = snapshot_download(
    "Qwen/Qwen2.5-1.5B-Instruct",
    allow_patterns=["*.json", "*.txt", "*.py", "*.safetensors", "tokenizer*"])
print("LLM_PATH", p)
