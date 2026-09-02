"""Artifact export: game-ready GLB (UV-unwrapped, PBR material preset),
print-ready STL (mm, optimized orientation), OBJ, and human/machine reports.
"""
from __future__ import annotations

import json
from pathlib import Path

import trimesh

from .presets import MATERIAL_PRESETS


def apply_material(mesh: trimesh.Trimesh, preset: str) -> trimesh.Trimesh:
    spec = MATERIAL_PRESETS.get(preset, MATERIAL_PRESETS["clay"])
    out = mesh.copy()
    material = trimesh.visual.material.PBRMaterial(
        baseColorFactor=spec["baseColorFactor"],
        metallicFactor=spec["metallicFactor"],
        roughnessFactor=spec["roughnessFactor"],
    )
    uv = None
    if isinstance(out.visual, trimesh.visual.TextureVisuals) and out.visual.uv is not None:
        uv = out.visual.uv
    out.visual = trimesh.visual.TextureVisuals(uv=uv, material=material)
    return out


def export_glb(mesh: trimesh.Trimesh, path: Path) -> Path:
    mesh.export(path)
    return path


def export_stl(mesh: trimesh.Trimesh, path: Path) -> Path:
    mesh.export(path)
    return path


def export_obj(mesh: trimesh.Trimesh, path: Path) -> Path:
    mesh.export(path)
    return path


def write_reports(out_dir: Path, payload: dict) -> tuple[Path, Path]:
    json_path = out_dir / "report.json"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    md_path = out_dir / "report.md"
    md_path.write_text(_report_markdown(payload), encoding="utf-8")
    return json_path, md_path


def _report_markdown(p: dict) -> str:
    device = p.get("device", {})
    print_r = p.get("print", {})
    cleanup = p.get("cleanup", {})
    walls = print_r.get("walls", {})
    orientation = print_r.get("orientation", {})

    lines = [
        f"# MeshSmith report — {p.get('slug', 'asset')}",
        "",
        f"**Prompt:** {p.get('prompt') or '(image input)'}  ",
        f"**Preset:** {p.get('preset')} · **Seed:** {p.get('seed')}  ",
        f"**Backend:** {device.get('backend')} · **GPU:** {device.get('gpu')} "
        f"({device.get('vram_gb')} GB)",
        "",
        "## Printability",
        f"- Score: **{print_r.get('score')}/100** — {print_r.get('verdict')}",
        f"- Watertight: {print_r.get('watertight')}",
        f"- Model height as requested: {print_r.get('height_mm')} mm · "
        f"laid on the bed it stands {print_r.get('print_height_mm')} mm tall",
        f"- Bounding box on bed (mm): {print_r.get('extents_mm')} · "
        f"Volume: {print_r.get('volume_cm3')} cm³",
        f"- Overhang area needing support: {round(100 * print_r.get('overhang_area_fraction', 0), 1)}%",
        f"- Auto-orientation saved {orientation.get('support_saved_pct', 0)}% support material "
        f"(up vector {orientation.get('chosen_up_vector')})",
        f"- Wall thickness: min {walls.get('min_mm')} mm, 5th percentile {walls.get('p05_mm')} mm, "
        f"{round(100 * walls.get('thin_fraction', 0), 1)}% of samples under limit",
        "",
        "## Bed fit",
    ]
    for bed, fits in print_r.get("beds", {}).items():
        lines.append(f"- {'✅' if fits else '❌'} {bed}")
    lines += [
        "",
        "## Mesh cleanup",
        f"- Faces: {p.get('raw_faces')} generated → {cleanup.get('faces_after')} repaired "
        f"→ {p.get('game_faces')} in the GLB / {p.get('print_faces')} in the STL",
        f"- Watertight: {cleanup.get('watertight_before')} → {cleanup.get('watertight_after')}",
        f"- Floater components removed: {cleanup.get('components_removed')}",
        "",
        "## Stage timings",
        p.get("timings_markdown", ""),
    ]
    return "\n".join(lines)
