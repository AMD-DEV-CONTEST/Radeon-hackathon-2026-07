#!/usr/bin/env python3
"""Merge a task LoRA into DM05 and save a standalone Hugging Face checkpoint."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path

BASE_AUXILIARY_FILES = (
    "generation_config.json",
    "preprocessor_config.json",
)
ADAPTER_RUNTIME_FILES = (
    "chat_template.jinja",
    "norm_stats.json",
    "processor_config.json",
    "tokenizer.json",
    "tokenizer_config.json",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--opendm-root", type=Path, required=True)
    parser.add_argument("--base-model", type=Path, required=True)
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--chunk-size", type=int, default=16)
    parser.add_argument("--max-shard-size", default="5GB")
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(16 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def copy_if_present(source_dir: Path, output_dir: Path, filename: str) -> None:
    source = source_dir / filename
    if source.is_file():
        shutil.copy2(source, output_dir / filename)


def validate_output(output_dir: Path, expected_chunk_size: int) -> dict[str, object]:
    from safetensors import safe_open  # pylint: disable=import-outside-toplevel

    weight_files = sorted(output_dir.glob("*.safetensors"))
    if not weight_files:
        raise RuntimeError("No safetensors weights were written")

    tensor_count = 0
    adapter_keys: list[str] = []
    for weight_file in weight_files:
        with safe_open(weight_file, framework="pt", device="cpu") as reader:
            keys = list(reader.keys())
        tensor_count += len(keys)
        adapter_keys.extend(
            key for key in keys if "lora_" in key or "modules_to_save" in key
        )
    if adapter_keys:
        raise RuntimeError(
            "Merged checkpoint still contains adapter-only keys: "
            + ", ".join(adapter_keys[:10])
        )

    required = (
        "config.json",
        "norm_stats.json",
        "processor_config.json",
        "tokenizer.json",
        "tokenizer_config.json",
    )
    missing = [
        filename for filename in required if not (output_dir / filename).is_file()
    ]
    if missing:
        raise RuntimeError(f"Merged checkpoint is missing runtime files: {missing}")

    with (output_dir / "config.json").open(encoding="utf-8") as stream:
        config = json.load(stream)
    if config.get("chunk_size") != expected_chunk_size:
        raise RuntimeError(
            "Unexpected chunk_size in merged config: "
            f"expected {expected_chunk_size}, got {config.get('chunk_size')!r}"
        )

    return {
        "weight_files": [path.name for path in weight_files],
        "tensor_count": tensor_count,
        "weight_bytes": sum(path.stat().st_size for path in weight_files),
    }


def main() -> None:
    args = parse_args()
    import torch  # pylint: disable=import-outside-toplevel
    from peft import PeftModel  # pylint: disable=import-outside-toplevel

    opendm_root = args.opendm_root.resolve()
    base_model = args.base_model.resolve()
    adapter = args.adapter.resolve()
    output_dir = args.output_dir.resolve()

    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"Refusing to overwrite non-empty output: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(opendm_root))

    from opendm.model.dm05.dm05_arch import (  # pylint: disable=import-outside-toplevel
        DM05Config,
        DM05ForConditionalGeneration,
    )

    started_at = time.time()
    config = DM05Config.from_pretrained(base_model)
    config.chunk_size = args.chunk_size
    config.vlm_config.vision_config._attn_implementation = "sdpa"

    print(f"Loading DM05 base model from {base_model}", flush=True)
    base = DM05ForConditionalGeneration.from_pretrained(
        base_model,
        config=config,
        torch_dtype=torch.bfloat16,
        low_cpu_mem_usage=True,
    )
    print(f"Loading LoRA adapter from {adapter}", flush=True)
    peft_model = PeftModel.from_pretrained(base, adapter)
    print("Merging adapter with safe_merge=True", flush=True)
    merged = peft_model.merge_and_unload(safe_merge=True)
    merged.config.chunk_size = args.chunk_size

    print(f"Saving standalone checkpoint to {output_dir}", flush=True)
    merged.save_pretrained(
        output_dir,
        safe_serialization=True,
        max_shard_size=args.max_shard_size,
    )
    for filename in BASE_AUXILIARY_FILES:
        copy_if_present(base_model, output_dir, filename)
    for filename in ADAPTER_RUNTIME_FILES:
        copy_if_present(adapter, output_dir, filename)

    validation = validate_output(output_dir, args.chunk_size)
    weight_hashes = {
        path.name: sha256(path) for path in sorted(output_dir.glob("*.safetensors"))
    }
    manifest = {
        "format": "dm05-merged-checkpoint-v1",
        "base_model": str(base_model),
        "base_model_sha256": sha256(base_model / "model.safetensors"),
        "adapter": str(adapter),
        "adapter_sha256": sha256(adapter / "adapter_model.safetensors"),
        "torch_dtype": "bfloat16",
        "chunk_size": args.chunk_size,
        "safe_merge": True,
        "elapsed_seconds": round(time.time() - started_at, 3),
        "validation": validation,
        "weight_sha256": weight_hashes,
    }
    with (output_dir / "merge_manifest.json").open("w", encoding="utf-8") as stream:
        json.dump(manifest, stream, ensure_ascii=True, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps(manifest, indent=2, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
