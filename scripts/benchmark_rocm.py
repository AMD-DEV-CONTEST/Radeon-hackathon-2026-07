#!/usr/bin/env python3
"""Benchmark the ROCm local 2.5D relief pipeline on AMD Radeon GPU.

Usage:
    cd services/api
    source .venv/bin/activate
    export USE_ROCM=true
    python ../../scripts/benchmark_rocm.py --image ../../assets/sample_dog.png --style relief_embossed
"""

import argparse
import json
import time
from pathlib import Path

import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
API_ROOT = REPO_ROOT / "services" / "api"
sys.path.insert(0, str(API_ROOT))
sys.path.insert(0, str(REPO_ROOT))

from adapters.factory import get_image_provider, get_depth_provider, get_3d_provider
from agents.styles import get_style


def get_gpu_memory() -> int | None:
    try:
        import torch

        if torch.cuda.is_available():
            return int(torch.cuda.get_device_properties(0).total_memory / 1024**2)
    except Exception:
        return None
    return None


def main():
    parser = argparse.ArgumentParser(description="Benchmark ROCm local relief pipeline")
    parser.add_argument("--image", required=True, help="Path to input image")
    parser.add_argument("--style", default="relief_embossed", help="Style ID from the catalog")
    parser.add_argument("--output", default=None, help="Output directory for artifacts")
    args = parser.parse_args()

    input_path = Path(args.image)
    if not input_path.exists():
        raise FileNotFoundError(input_path)

    style = get_style(args.style)
    output_dir = Path(args.output) if args.output else API_ROOT / "results" / "benchmark"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Copy input to output dir so providers can write intermediates there
    import shutil

    local_input = output_dir / input_path.name
    shutil.copy2(input_path, local_input)

    prompt = f"{style.style_prompt}, {style.description}"
    postprocess = dict(style.postprocess_params)

    results = {
        "style": args.style,
        "output_mode": style.output_mode,
        "gpu_memory_mb": get_gpu_memory(),
        "stages": {},
    }

    # 1. Style transfer
    t0 = time.time()
    image_provider = get_image_provider()
    styled_image = image_provider.generate_image_from_image(image=local_input, prompt=prompt)
    results["stages"]["style_transfer"] = {
        "seconds": round(time.time() - t0, 2),
        "output": str(styled_image),
    }

    # 2. Depth estimation
    t0 = time.time()
    depth_provider = get_depth_provider()
    depth_map = depth_provider.generate_depth_map(styled_image, invert=postprocess.get("invert", False))
    results["stages"]["depth_estimation"] = {
        "seconds": round(time.time() - t0, 2),
        "output": str(depth_map),
    }

    # 3. Relief mesh generation
    t0 = time.time()
    three_d_provider = get_3d_provider()
    mesh_asset = three_d_provider.generate_3d_from_images(
        images=[depth_map],
        prompt=prompt,
        style=args.style,
        output_path=output_dir / "relief.stl",
        **postprocess,
    )
    results["stages"]["relief_mesh"] = {
        "seconds": round(time.time() - t0, 2),
        "output": str(mesh_asset.mesh_path),
    }

    total = sum(s["seconds"] for s in results["stages"].values())
    results["total_seconds"] = round(total, 2)

    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
