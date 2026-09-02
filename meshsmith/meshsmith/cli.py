"""Headless CLI — the same pipeline the UI drives, for terminals, benchmarks,
and demo recordings:  python -m meshsmith.cli "a chess knight" --quality high
"""
from __future__ import annotations

import argparse
import json
import sys

from PIL import Image

from .device import device_banner
from .pipeline import MeshSmith
from .presets import MATERIAL_PRESETS, PRESETS


def main(argv=None):
    parser = argparse.ArgumentParser(prog="meshsmith", description=__doc__)
    parser.add_argument("prompt", nargs="?", default=None, help="text prompt")
    parser.add_argument("--image", help="input image path (skips text→image)")
    parser.add_argument("--quality", choices=list(PRESETS), default="standard")
    parser.add_argument("--material", choices=list(MATERIAL_PRESETS), default="clay")
    parser.add_argument("--seed", type=int, default=1234)
    parser.add_argument("--height-mm", type=float, default=80.0)
    parser.add_argument("--out", default="outputs")
    args = parser.parse_args(argv)

    if not args.prompt and not args.image:
        parser.error("give a prompt and/or --image")

    banner = device_banner()
    print(f"MeshSmith · {banner['backend']} · {banner['gpu']} ({banner['vram_gb']} GB)")

    image = Image.open(args.image) if args.image else None
    smith = MeshSmith(output_root=args.out)

    def progress(frac, desc):
        print(f"[{int(frac * 100):3d}%] {desc}", flush=True)

    result = smith.run(
        prompt=args.prompt,
        image=image,
        preset=args.quality,
        seed=args.seed,
        height_mm=args.height_mm,
        material=args.material,
        progress=progress,
    )

    print()
    print(result["timings_markdown"])
    print()
    pr = result["print"]
    print(f"Printability: {pr['score']}/100 — {pr['verdict']}")
    print(f"Artifacts: {result['paths']['dir']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
