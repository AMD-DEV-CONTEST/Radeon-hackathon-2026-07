"""Session 7: cross-simulator replication (MuJoCo) -- one-time asset prep.

Decomposes the bowl's collision mesh into convex pieces via coacd (the SAME tool
Genesis's own asset pipeline already uses internally for this project's meshes --
not a new dependency, not a Genesis-specific technique). Only the bowl needs this:
its concavity is functionally load-bearing (the object must rest INSIDE it for
success detection to mean anything), whereas banana/lemon/plum are already close
enough to convex that a single mesh geom (MuJoCo auto-hulls it) is a fair, simple,
undistorted approximation -- using coacd there too would just add complexity without
changing the physics in any way that matters for this task.

Writes decomposed OBJ pieces to mujoco_repl/assets/<name>_hull_<i>.obj, cached (skips
recomputation if already present).
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT.parent.parent) not in sys.path:
    sys.path.insert(0, str(_ROOT.parent.parent))

import numpy as np  # noqa: E402
import trimesh  # noqa: E402

_ASSETS_ROOT = _ROOT.parent.parent.parent / "assets" / "ycb"
_OUT_DIR = _ROOT / "assets"

NEEDS_DECOMPOSITION = ["024_bowl"]
SINGLE_HULL_OK = ["011_banana", "014_lemon", "018_plum", "013_apple"]


def decompose(name: str, threshold: float = 0.08) -> list[Path]:
    import coacd

    out_paths = sorted(_OUT_DIR.glob(f"{name}_hull_*.obj"))
    if out_paths:
        return out_paths

    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    src = _ASSETS_ROOT / name / "collision.ply"
    m = trimesh.load(src, force="mesh")
    mesh = coacd.Mesh(m.vertices, m.faces)
    parts = coacd.run_coacd(mesh, threshold=threshold)
    print(f"{name}: decomposed into {len(parts)} convex pieces")

    out_paths = []
    for i, (verts, faces) in enumerate(parts):
        piece = trimesh.Trimesh(vertices=verts, faces=faces)
        out_path = _OUT_DIR / f"{name}_hull_{i}.obj"
        piece.export(out_path)
        out_paths.append(out_path)
    return out_paths


def single_hull_obj(name: str) -> Path:
    """For near-convex objects: convert collision.ply -> .obj once and cache (this
    MuJoCo build has no PLY decoder -- OBJ works natively). MuJoCo auto-hulls a
    single mesh geom to its convex hull."""
    out_path = _OUT_DIR / f"{name}_collision.obj"
    if out_path.exists():
        return out_path
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    m = trimesh.load(_ASSETS_ROOT / name / "collision.ply", force="mesh")
    m.export(out_path)
    return out_path


if __name__ == "__main__":
    for name in NEEDS_DECOMPOSITION:
        decompose(name)
    print("done")
