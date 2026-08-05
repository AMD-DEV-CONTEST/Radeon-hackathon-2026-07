"""Mesh cleanup + LOD generation: the step that turns a raw generated mesh into
an asset another tool will actually accept. All CPU-side (trimesh /
fast-simplification / xatlas), so it behaves identically on any GPU vendor.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import trimesh


@dataclass
class CleanupReport:
    watertight_before: bool
    watertight_after: bool
    components_before: int
    components_removed: int
    faces_before: int
    faces_after: int
    holes_filled: bool

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def clean(mesh: trimesh.Trimesh, keep_component_fraction: float = 0.02) -> tuple[trimesh.Trimesh, CleanupReport]:
    """Deduplicate, drop tiny floater components, fill small holes, fix winding."""
    faces_before = len(mesh.faces)
    watertight_before = bool(mesh.is_watertight)

    mesh = mesh.copy()
    mesh.merge_vertices()
    mesh.update_faces(mesh.nondegenerate_faces())
    mesh.update_faces(mesh.unique_faces())
    mesh.remove_unreferenced_vertices()

    components = mesh.split(only_watertight=False)
    removed = 0
    if len(components) > 1:
        biggest = max(c.area for c in components)
        keep = [c for c in components if c.area >= keep_component_fraction * biggest]
        removed = len(components) - len(keep)
        mesh = trimesh.util.concatenate(keep) if len(keep) > 1 else keep[0]

    holes_filled = False
    if not mesh.is_watertight:
        holes_filled = bool(mesh.fill_holes())

    trimesh.repair.fix_normals(mesh)

    report = CleanupReport(
        watertight_before=watertight_before,
        watertight_after=bool(mesh.is_watertight),
        components_before=len(components),
        components_removed=removed,
        faces_before=faces_before,
        faces_after=len(mesh.faces),
        holes_filled=holes_filled,
    )
    return mesh, report


def decimate(mesh: trimesh.Trimesh, target_faces: int) -> trimesh.Trimesh:
    """Quadric decimation to ~target_faces (no-op if already smaller)."""
    if len(mesh.faces) <= target_faces:
        return mesh.copy()
    import fast_simplification

    reduction = 1.0 - (target_faces / len(mesh.faces))
    v, f = fast_simplification.simplify(
        np.asarray(mesh.vertices, dtype=np.float32),
        np.asarray(mesh.faces, dtype=np.int32),
        target_reduction=float(np.clip(reduction, 0.0, 0.99)),
    )
    out = trimesh.Trimesh(vertices=v, faces=f)
    out.merge_vertices()
    trimesh.repair.fix_normals(out)
    return out


def unwrap_uvs(mesh: trimesh.Trimesh) -> trimesh.Trimesh | None:
    """xatlas UV unwrap (run on the decimated mesh — atlas time grows fast with
    face count). Returns a new mesh with per-vertex UVs, or None on failure."""
    try:
        import xatlas

        vmapping, indices, uvs = xatlas.parametrize(
            np.asarray(mesh.vertices, dtype=np.float32),
            np.asarray(mesh.faces, dtype=np.uint32),
        )
        out = trimesh.Trimesh(
            vertices=np.asarray(mesh.vertices)[vmapping],
            faces=indices.reshape(-1, 3),
            process=False,
        )
        out.visual = trimesh.visual.TextureVisuals(uv=uvs)
        return out
    except Exception:
        return None
