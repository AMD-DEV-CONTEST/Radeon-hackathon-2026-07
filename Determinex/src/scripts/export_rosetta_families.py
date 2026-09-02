#!/usr/bin/env python3
"""export_rosetta_families.py -- split the combined rosetta_vN.pt checkpoint into the
small per-family `family_<arch>.pt` files the dynamic registry (registry/registry.json +
rosetta/determinex_registry.py) expects to download and load via
RosettaStone.load_family_extension().

Each output file is self-contained: one architecture's encoder + decoder state dicts,
its input dimension, the shared d_rosetta hub dimension, the source version, and a
tensor-content sha256 (same scheme as the combined checkpoint's own embedded hash --
see determinex_rosetta.py's _compute_weights_sha256) that load_family_extension()
verifies before activating it.

Usage:
    python scripts/export_rosetta_families.py --source T:/determinex-models/rosetta/rosetta_v1.pt \
        --output-dir T:/determinex-models/rosetta/families

Prints, for each family, the exact "sha256" line to paste into registry/registry.json
(the plain whole-FILE byte hash the registry CLIENT verifies -- a different, additional
check from the embedded tensor-content hash inside the file).
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from determinex_rosetta import _compute_weights_sha256  # noqa: E402

# Families the registry actually expects AND that exist in the trained checkpoint.
# "gemma" is in registry/registry.json but was never trained into rosetta_v1.pt --
# deliberately excluded here rather than fabricated. "mistral" is trained but not
# yet in the registry's families list -- exported anyway since the data exists and
# costs nothing to have ready; not registered in registry.json unless asked.
EXPORTABLE_FAMILIES = ["llama", "qwen2", "qwen2_3b", "qwen2_1b5", "deepseek2", "phi3", "mistral"]


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, help="Path to the combined rosetta_vN.pt")
    parser.add_argument(
        "--output-dir", required=True, help="Directory to write family_<arch>.pt files into"
    )
    parser.add_argument(
        "--families",
        default=",".join(EXPORTABLE_FAMILIES),
        help="Comma-separated arch keys to export (must exist in the source checkpoint)",
    )
    args = parser.parse_args()

    import torch

    source = Path(args.source).expanduser()
    out_dir = Path(args.output_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)

    ckpt = torch.load(str(source), map_location="cpu", weights_only=False)
    dims = ckpt.get("dims", {})
    d_rosetta = int(ckpt.get("d_rosetta", 4096))
    version = ckpt.get("version", "unknown")

    requested = [f.strip() for f in args.families.split(",") if f.strip()]
    results: list[tuple[str, str, int]] = []  # (arch, file_sha256, size_bytes)

    for arch in requested:
        enc_key, dec_key = f"{arch}_encoder", f"{arch}_decoder"
        if enc_key not in ckpt or dec_key not in ckpt:
            print(f"SKIP {arch}: not present in {source} (no {enc_key}/{dec_key})", file=sys.stderr)
            continue
        dim = dims.get(arch)
        if dim is None:
            print(f"SKIP {arch}: no dim recorded in checkpoint 'dims'", file=sys.stderr)
            continue

        family_ckpt = {
            "arch": arch,
            "dim": int(dim),
            enc_key: ckpt[enc_key],
            dec_key: ckpt[dec_key],
            "d_rosetta": d_rosetta,
            "version": version,
        }
        family_ckpt["sha256"] = _compute_weights_sha256(family_ckpt)

        dest = out_dir / f"family_{arch}.pt"
        torch.save(family_ckpt, str(dest))

        sha = file_sha256(dest)
        size_kb = dest.stat().st_size // 1024
        results.append((arch, sha, size_kb))
        print(f"wrote {dest} ({size_kb} KB)")

    print()
    print(
        "# Paste into registry/registry.json (whole-FILE sha256, verified by the registry client):"
    )
    for arch, sha, size_kb in results:
        print(f'  "{arch}": sha256={sha}  size_kb={size_kb}')

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
