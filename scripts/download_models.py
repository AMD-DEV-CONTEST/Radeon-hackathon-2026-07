#!/usr/bin/env python3
"""Pre-download HuggingFace checkpoints used by the ROCm local pipeline."""

import os
import sys
from pathlib import Path

# Allow importing the backend package from the repo root.
REPO_ROOT = Path(__file__).resolve().parent.parent
API_ROOT = REPO_ROOT / "services" / "api"
MODELS_DIR = API_ROOT / "models" / "hf_cache"

sys.path.insert(0, str(API_ROOT))
sys.path.insert(0, str(REPO_ROOT))


def main():
    os.makedirs(MODELS_DIR, exist_ok=True)
    os.environ.setdefault("HF_HOME", str(MODELS_DIR))

    print(f"Cache directory: {MODELS_DIR}")

    print("Downloading Stable Diffusion v1.5 ...")
    from diffusers import StableDiffusionImg2ImgPipeline

    StableDiffusionImg2ImgPipeline.from_pretrained(
        "runwayml/stable-diffusion-v1-5",
        cache_dir=str(MODELS_DIR),
        torch_dtype="auto",
        safety_checker=None,
    )

    print("Downloading Depth Anything V2 Small ...")
    from transformers import pipeline

    pipeline(
        "depth-estimation",
        model="depth-anything/Depth-Anything-V2-Small-hf",
        cache_dir=str(MODELS_DIR),
        device=-1,
    )

    print("Done.")
    print(f"Models cached at: {MODELS_DIR}")


if __name__ == "__main__":
    main()
