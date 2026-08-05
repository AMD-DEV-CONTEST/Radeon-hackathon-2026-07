"""Print-readiness analysis: scale to physical size, search for the best print
orientation, estimate support volume, sample wall thickness, and score the
result. This is MeshSmith's differentiator — generated meshes usually die on
the slicer, not in the viewer.

Frames: generated GLB meshes are Y-up (glTF convention); printing thinks Z-up.
Everything here works in a Z-up copy; `to_z_up()` does the conversion once.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import trimesh

OVERHANG_DEG = 45.0          # steeper-down than this needs support
BED_CONTACT_MM = 0.6         # faces this close to the bed don't count as overhangs
DEFAULT_MIN_WALL_MM = 1.2    # FDM-safe minimum wall
COMMON_BEDS_MM = {
    "Prusa MK4 / most FDM (250x210x220)": (250, 210, 220),
    "Bambu A1 mini (180x180x180)": (180, 180, 180),
    "Resin 4K (130x80x160)": (130, 80, 160),
}


def to_z_up(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    out = mesh.copy()
    out.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [1, 0, 0]))
    return out


def scale_to_height(mesh: trimesh.Trimesh, height_mm: float) -> trimesh.Trimesh:
    """Uniform scale so the Z extent equals height_mm, sitting on the bed at z=0."""
    out = mesh.copy()
    extents = out.extents
    if extents[2] <= 0:
        return out
    out.apply_scale(height_mm / extents[2])
    out.apply_translation([0, 0, -out.bounds[0][2]])
    return out


def _candidate_up_vectors() -> np.ndarray:
    """26 directions: axes, edge midpoints, corners of a cube — a cheap but
    effective orientation search space."""
    dirs = []
    for x in (-1, 0, 1):
        for y in (-1, 0, 1):
            for z in (-1, 0, 1):
                if (x, y, z) != (0, 0, 0):
                    dirs.append((x, y, z))
    dirs = np.array(dirs, dtype=float)
    return dirs / np.linalg.norm(dirs, axis=1, keepdims=True)


def support_volume_mm3(mesh: trimesh.Trimesh) -> float:
    """Approximate support volume: for each overhang face, the prism between the
    face and the bed (projected area x height)."""
    normals = mesh.face_normals
    threshold = -np.cos(np.radians(OVERHANG_DEG))
    overhang = normals[:, 2] < threshold
    if not overhang.any():
        return 0.0
    centroids = mesh.triangles_center[overhang]
    heights = np.maximum(centroids[:, 2] - mesh.bounds[0][2] - BED_CONTACT_MM, 0.0)
    projected_area = mesh.area_faces[overhang] * np.abs(normals[overhang, 2])
    return float(np.sum(projected_area * heights))


def overhang_area_fraction(mesh: trimesh.Trimesh) -> float:
    normals = mesh.face_normals
    threshold = -np.cos(np.radians(OVERHANG_DEG))
    centroids = mesh.triangles_center
    above_bed = centroids[:, 2] > mesh.bounds[0][2] + BED_CONTACT_MM
    overhang = (normals[:, 2] < threshold) & above_bed
    total = mesh.area
    return float(mesh.area_faces[overhang].sum() / total) if total > 0 else 0.0


def optimize_orientation(mesh: trimesh.Trimesh, height_mm: float) -> tuple[trimesh.Trimesh, dict]:
    """Try 26 candidate up-vectors, keep the orientation with the least support
    volume. The part is scaled ONCE in its natural orientation (so height_mm
    keeps its meaning and every candidate is the same physical object), then
    only rotated. Returns the oriented mesh and a summary dict."""
    scaled = scale_to_height(mesh, height_mm)
    baseline = support_volume_mm3(scaled)

    best_mesh, best_support, best_dir = scaled, baseline, (0.0, 0.0, 1.0)
    for up in _candidate_up_vectors():
        rot = trimesh.geometry.align_vectors(up, [0, 0, 1])
        candidate = scaled.copy()
        candidate.apply_transform(rot)
        candidate.apply_translation([0, 0, -candidate.bounds[0][2]])
        vol = support_volume_mm3(candidate)
        if vol < best_support:
            best_mesh, best_support, best_dir = candidate, vol, tuple(round(float(v), 3) for v in up)

    saved_pct = 0.0 if baseline <= 0 else max(0.0, (baseline - best_support) / baseline * 100)
    return best_mesh, {
        "baseline_support_mm3": round(baseline, 1),
        "best_support_mm3": round(best_support, 1),
        "support_saved_pct": round(saved_pct, 1),
        "chosen_up_vector": best_dir,
    }


def wall_thickness_stats(mesh: trimesh.Trimesh, samples: int = 1200,
                         min_wall_mm: float = DEFAULT_MIN_WALL_MM) -> dict:
    """Sample surface points and ray-cast inward; first exit distance ~= local
    wall thickness. Native trimesh ray casting, capped sample count for speed."""
    try:
        points, face_idx = trimesh.sample.sample_surface(mesh, samples)
        normals = mesh.face_normals[face_idx]
        origins = points - normals * 1e-3
        hits, ray_idx, _ = mesh.ray.intersects_location(origins, -normals, multiple_hits=False)
        if len(hits) == 0:
            return {"measured": 0, "min_mm": None, "p05_mm": None, "thin_fraction": 0.0}
        thickness = np.linalg.norm(hits - origins[ray_idx], axis=1)
        thickness = thickness[(thickness > 1e-3) & np.isfinite(thickness)]
        if len(thickness) == 0:
            return {"measured": 0, "min_mm": None, "p05_mm": None, "thin_fraction": 0.0}
        return {
            "measured": int(len(thickness)),
            "min_mm": round(float(thickness.min()), 2),
            "p05_mm": round(float(np.percentile(thickness, 5)), 2),
            "thin_fraction": round(float((thickness < min_wall_mm).mean()), 3),
        }
    except Exception as exc:  # ray casting can fail on pathological meshes
        return {"measured": 0, "min_mm": None, "p05_mm": None, "thin_fraction": 0.0,
                "error": str(exc)}


def bed_fit(mesh: trimesh.Trimesh) -> dict:
    ext = mesh.extents
    return {
        name: bool(ext[0] <= bx and ext[1] <= by and ext[2] <= bz)
        for name, (bx, by, bz) in COMMON_BEDS_MM.items()
    }


@dataclass
class PrintReport:
    height_mm: float          # requested model height (its own up axis)
    print_height_mm: float    # actual Z height once laid on the bed
    extents_mm: list
    volume_cm3: float | None
    watertight: bool
    orientation: dict = field(default_factory=dict)
    overhang_area_fraction: float = 0.0
    walls: dict = field(default_factory=dict)
    beds: dict = field(default_factory=dict)
    score: int = 0
    verdict: str = ""

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def analyze(mesh_z_up: trimesh.Trimesh, height_mm: float,
            min_wall_mm: float = DEFAULT_MIN_WALL_MM) -> tuple[trimesh.Trimesh, PrintReport]:
    """Full print analysis on a Z-up mesh. Returns (oriented+scaled mesh, report)."""
    oriented, orientation = optimize_orientation(mesh_z_up, height_mm)
    # ray-sample walls on a decimated copy — the thickness field doesn't need
    # full detail, and ray casting scales badly with face count
    from .meshfix import decimate

    sample_mesh = decimate(oriented, 150_000) if len(oriented.faces) > 150_000 else oriented
    walls = wall_thickness_stats(sample_mesh, min_wall_mm=min_wall_mm)
    overhang_frac = overhang_area_fraction(oriented)
    watertight = bool(oriented.is_watertight)

    volume_cm3 = None
    if watertight:
        volume_cm3 = round(float(abs(oriented.volume)) / 1000.0, 1)

    score = 0
    score += 30 if watertight else 0
    if walls.get("measured", 0) == 0:
        score += 12  # walls unmeasured: partial credit, never full marks
    else:
        thin = walls.get("thin_fraction", 1.0)
        score += 25 if thin < 0.02 else (15 if thin < 0.10 else 5)
    score += 25 if overhang_frac < 0.05 else (15 if overhang_frac < 0.20 else 5)
    beds = bed_fit(oriented)
    score += 10 if any(beds.values()) else 0
    score += 10  # single body guaranteed upstream by cleanup

    verdict = ("ready to slice" if score >= 85 else
               "printable with supports / minor fixes" if score >= 60 else
               "needs manual repair")

    report = PrintReport(
        height_mm=height_mm,
        print_height_mm=round(float(oriented.extents[2]), 1),
        extents_mm=[round(float(v), 1) for v in oriented.extents],
        volume_cm3=volume_cm3,
        watertight=watertight,
        orientation=orientation,
        overhang_area_fraction=round(overhang_frac, 3),
        walls=walls,
        beds=beds,
        score=score,
        verdict=verdict,
    )
    return oriented, report
