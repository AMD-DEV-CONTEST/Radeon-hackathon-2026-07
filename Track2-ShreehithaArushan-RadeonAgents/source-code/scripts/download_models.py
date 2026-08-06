#!/usr/bin/env python3
"""
Download recommended models for RadeonAgents.
"""

import argparse
from pathlib import Path
from huggingface_hub import snapshot_download


RECOMMENDED = {
    "phi3": "microsoft/Phi-3-mini-4k-instruct",
    "llama32-3b": "meta-llama/Llama-3.2-3B-Instruct",
    "qwen2.5-3b": "Qwen/Qwen2.5-3B-Instruct",
}


def main():
    parser = argparse.ArgumentParser(description="Download models for RadeonAgents")
    parser.add_argument(
        "--model",
        default="microsoft/Phi-3-mini-4k-instruct",
        help="Hugging Face model ID or short name (phi3, llama32-3b, qwen2.5-3b)",
    )
    parser.add_argument(
        "--local-dir",
        default=None,
        help="Optional local directory to store the model",
    )
    args = parser.parse_args()

    model_id = RECOMMENDED.get(args.model.lower(), args.model)
    print(f"Downloading: {model_id}")

    local_dir = args.local_dir
    if local_dir is None:
        local_dir = str(Path("./models") / model_id.split("/")[-1])

    path = snapshot_download(
        repo_id=model_id,
        local_dir=local_dir,
        local_dir_use_symlinks=False,
    )
    print(f"Model downloaded to: {path}")
    print("You can now set this path or the original HF ID in config/default.yaml")


if __name__ == "__main__":
    main()
