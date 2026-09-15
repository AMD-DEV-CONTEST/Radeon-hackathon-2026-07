"""Bake scaled copies of YCB objects into a new dataset directory.

Only geometry is scaled:
  - textured.obj : each `v x y z` vertex line is scaled (UV `vt`, normals `vn`,
    faces `f`, and the material references `mtllib`/`usemtl` are copied verbatim).
  - collision.ply: vertices scaled via trimesh (faces unchanged).
  - material / texture files: copied verbatim (UVs are scale-invariant, so the
    original textures map perfectly onto the scaled mesh).

This keeps the original dataset untouched and produces a parallel dataset whose
object subdirectories keep the same names (e.g. 013_apple), so the rest of the
pipeline (setup_assets, YCB_LAYOUT, grasp profiles) can use them unchanged.

Usage:
    uv run python scale_ycb.py --scale 0.8 013_apple 017_orange
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import trimesh

# Dev-only utility: source/destination YCB datasets are NOT shipped with the demo. They
# are resolved relative to the dir *containing* the repo during development; override with
# --src/--dst when running elsewhere.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_SRC = _REPO_ROOT.parent / "mani_skill_dataset"
DEFAULT_DST = _REPO_ROOT.parent / "mani_skill_dataset_scaled"

# Files copied byte-for-byte (materials + textures). UVs are unaffected by scaling.
COPY_VERBATIM = ("textured.mtl", "material_0.mtl", "material_0.png", "texture_map.png")


def _scale_obj_textlines(src: Path, dst: Path, scale: float) -> None:
    """Copy an OBJ line by line, scaling only geometric vertex (`v `) coordinates."""
    with open(src) as fin, open(dst, "w") as fout:
        for line in fin:
            # `v ` is a geometry vertex; `vt`/`vn` start with different prefixes.
            if line.startswith("v "):
                parts = line.split()
                x, y, z = (float(parts[1]) * scale, float(parts[2]) * scale, float(parts[3]) * scale)
                fout.write(f"v {x:.8f} {y:.8f} {z:.8f}\n")
            else:
                fout.write(line)


def _scale_ply(src: Path, dst: Path, scale: float) -> None:
    mesh = trimesh.load(src, process=False)
    mesh.apply_scale(scale)
    mesh.export(dst)


def rescale_object(name: str, scale: float, src_root: Path, dst_root: Path) -> None:
    src = src_root / name
    dst = dst_root / name
    if not src.is_dir():
        raise FileNotFoundError(f"Missing source object directory: {src}")
    dst.mkdir(parents=True, exist_ok=True)

    _scale_obj_textlines(src / "textured.obj", dst / "textured.obj", scale)
    _scale_ply(src / "collision.ply", dst / "collision.ply", scale)
    for fname in COPY_VERBATIM:
        if (src / fname).exists():
            shutil.copy(src / fname, dst / fname)

    # Report resulting bounding box for sanity.
    m = trimesh.load(dst / "textured.obj", process=False, force="mesh")
    lo, hi = m.bounds
    size = hi - lo
    print(f"  {name}: scaled by {scale} -> size=({size[0]:.4f}, {size[1]:.4f}, {size[2]:.4f}) m")


def main() -> None:
    parser = argparse.ArgumentParser(description="Bake scaled copies of YCB objects.")
    parser.add_argument("objects", nargs="+", help="Object directory names, e.g. 013_apple 017_orange")
    parser.add_argument("--scale", type=float, required=True, help="Uniform scale factor (e.g. 0.8).")
    parser.add_argument("--src", type=Path, default=DEFAULT_SRC, help="Source dataset root.")
    parser.add_argument("--dst", type=Path, default=DEFAULT_DST, help="Destination dataset root.")
    args = parser.parse_args()

    print(f"[scale_ycb] src={args.src} dst={args.dst} scale={args.scale}")
    for name in args.objects:
        rescale_object(name, args.scale, args.src, args.dst)
    print(f"[scale_ycb] done -> {args.dst}")


if __name__ == "__main__":
    main()
