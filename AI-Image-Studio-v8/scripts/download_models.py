# -*- coding: utf-8 -*-
"""One-click model download for AI-Image-Studio v8 (SDXL-based).

Usage:
    export HF_ENDPOINT=https://hf-mirror.com   # faster in mainland China
    python scripts/download_models.py
"""
from __future__ import annotations

import os
import sys

# The xet backend can 401 through mirrors/proxies — force plain HTTP downloads.
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import settings  # noqa: E402

HF_MODELS = [
    ("SDXL base (style / AI background)", settings.sdxl_model_id),
    ("SDXL inpainting (inpaint / outpaint / split fill)", settings.sdxl_inpaint_id),
    ("ControlNet Canny (structure-locked style)", settings.controlnet_id),
    ("BiRefNet (matting)", settings.birefnet_model_id),
    ("LCM-LoRA SDXL (turbo mode)", settings.lcm_lora_id),
    ("Intent LLM (instruction parsing)", settings.intent_model_id),
]

# Only what from_pretrained(variant="fp16") needs — skips fp32 weights, .bin
# duplicates and root-level single-file checkpoints (~30 GB saved).
ALLOW = ["*.json", "*.txt", "*.py", "*.md", "*.fp16.safetensors",
         "model.safetensors", "pytorch_lora_weights.safetensors"]
IGNORE = ["*.bin", "*.msgpack", "*.ckpt", "*.pt", "*.onnx", "sd_xl_*", "vae_1_0/*"]


def main() -> None:
    from huggingface_hub import snapshot_download

    for name, repo in HF_MODELS:
        print(f"\n=== Downloading {name}: {repo}")
        path = snapshot_download(repo_id=repo, allow_patterns=ALLOW,
                                 ignore_patterns=IGNORE)
        print(f"    -> {path}")

    # LaMa is a local file (see README for the one-line curl command)
    if os.path.exists(settings.lama_model_path):
        print(f"\n[skip] LaMa found at {settings.lama_model_path}")
    else:
        print(f"\n[warn] LaMa not found at {settings.lama_model_path}.")
        print("       Download it once with:")
        print('       curl -kL -o models/big-lama.pt "https://hf-mirror.com/'
              'martintomov/big-lama/resolve/main/big-lama.pt"')

    print("\n✅ All downloads complete.")


if __name__ == "__main__":
    main()
