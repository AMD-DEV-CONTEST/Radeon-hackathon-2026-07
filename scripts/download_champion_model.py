"""Download the recommended local judge model with Hugging Face resume support."""

from __future__ import annotations

import argparse
from pathlib import Path

from huggingface_hub import snapshot_download


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="Qwen/Qwen3-14B")
    parser.add_argument("--output", type=Path, default=Path("models/Qwen3-14B"))
    args = parser.parse_args()
    snapshot_download(
        repo_id=args.model,
        local_dir=args.output,
        allow_patterns=[
            "config.json",
            "generation_config.json",
            "model.safetensors.index.json",
            "model-*.safetensors",
            "tokenizer.json",
            "tokenizer_config.json",
            "special_tokens_map.json",
            "vocab.json",
            "merges.txt",
        ],
        local_dir_use_symlinks=False,
    )
    print(f"Downloaded {args.model} to {args.output.resolve()}")


if __name__ == "__main__":
    main()
