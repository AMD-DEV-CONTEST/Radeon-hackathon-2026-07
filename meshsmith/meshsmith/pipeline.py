"""The MeshSmith pipeline: prompt/image -> image -> cutout -> mesh -> cleanup
-> LOD/UV -> print analysis -> exports. Models load lazily and unload after
use when VRAM is tight, so the pipeline fits 16 GB cards as well as 48 GB ones.
"""
from __future__ import annotations

import re
import time
from pathlib import Path

import trimesh
from PIL import Image

from . import meshfix, printcheck, exporter
from .device import device_banner, pick_device, preflight
from .imagegen import ImageGenerator
from .matting import Matting
from .presets import PRESETS, Preset
from .shapegen import ShapeGenerator
from .timing import RunTimings

KEEP_MODELS_LOADED_MIN_VRAM_GB = 30.0


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "asset").lower()).strip("-")
    return slug[:40] or "asset"


class MeshSmith:
    def __init__(self, output_root: str | Path = "outputs"):
        preflight()
        self.device = pick_device()
        self.banner = device_banner(self.device)
        self.output_root = Path(output_root)
        self.imagegen = ImageGenerator(self.device)
        self.matting = Matting()
        self.shapegen = ShapeGenerator(self.device)
        self.keep_loaded = self.banner["vram_gb"] >= KEEP_MODELS_LOADED_MIN_VRAM_GB

    def run(
        self,
        prompt: str | None = None,
        image: Image.Image | None = None,
        preset: str | Preset = "standard",
        seed: int = 1234,
        height_mm: float = 80.0,
        material: str = "clay",
        min_wall_mm: float = printcheck.DEFAULT_MIN_WALL_MM,
        progress=None,
    ) -> dict:
        """Run the full pipeline. Returns a dict of artifact paths + reports."""
        if not prompt and image is None:
            raise ValueError("Provide a text prompt, an input image, or both.")
        preset = PRESETS[preset] if isinstance(preset, str) else preset
        timings = RunTimings()
        notify = progress or (lambda frac, desc: None)

        slug = _slugify(prompt or "image-input")
        out_dir = self.output_root / f"{time.strftime('%Y%m%d-%H%M%S')}_{slug}"
        out_dir.mkdir(parents=True, exist_ok=True)

        # 1. text -> image (skipped when the user supplies an image)
        if image is None:
            notify(0.05, "Generating concept image (SDXL-Turbo)")
            with timings.stage("Text → image (SDXL-Turbo)", self.device):
                image = self.imagegen.generate(
                    prompt, size=preset.image_size, steps=preset.image_steps, seed=seed
                )
            if not self.keep_loaded:
                self.imagegen.unload()
        image.convert("RGB").save(out_dir / "concept.png")

        # 2. background removal
        notify(0.25, "Cutting out subject")
        with timings.stage("Background removal (u2net)", self.device):
            cutout = self.matting.cut_out(image)
        cutout.save(out_dir / "cutout.png")

        # 3. image -> mesh
        notify(0.35, f"Generating 3D shape (Hunyuan3D, {preset.name})")
        with timings.stage(f"Image → 3D (Hunyuan3D {preset.name})", self.device):
            raw_mesh = self.shapegen.generate(cutout, preset, seed)
        if not self.keep_loaded:
            self.shapegen.unload()
        raw_faces = len(raw_mesh.faces)

        # 4. cleanup
        notify(0.65, "Repairing mesh")
        with timings.stage("Mesh cleanup & repair", self.device):
            clean_mesh, cleanup_report = meshfix.clean(raw_mesh)

        # 5. game-ready GLB: decimate + UV unwrap + material
        notify(0.75, "Building game-ready GLB")
        with timings.stage("Decimate + UV unwrap", self.device):
            game_mesh = meshfix.decimate(clean_mesh, preset.target_faces)
            unwrapped = meshfix.unwrap_uvs(game_mesh)
            if unwrapped is not None:
                game_mesh = unwrapped
            game_mesh = exporter.apply_material(game_mesh, material)

        # 6. print path. Decimate to a print budget FIRST, then analyse: a slicer
        # cannot use 2M faces (a 100 MB+ STL) and the printer cannot resolve them,
        # so the report describes exactly the mesh that gets exported.
        notify(0.85, "Print analysis & auto-orientation")
        with timings.stage("Print analysis + orientation", self.device):
            print_mesh = meshfix.decimate(clean_mesh, preset.print_target_faces)
            # Decimation can expose latent non-manifold edges in a generated mesh,
            # and a non-watertight STL is exactly what a slicer chokes on. Repair,
            # then refuse to ship anything worse than what we started with.
            if not print_mesh.is_watertight:
                print_mesh, _ = meshfix.clean(print_mesh)
            if clean_mesh.is_watertight and not print_mesh.is_watertight:
                print_mesh = clean_mesh
            z_up = printcheck.to_z_up(print_mesh)
            oriented, print_report = printcheck.analyze(z_up, height_mm, min_wall_mm)

        # 7. exports
        notify(0.95, "Exporting artifacts")
        with timings.stage("Export GLB/STL/OBJ", self.device):
            glb_path = exporter.export_glb(game_mesh, out_dir / f"{slug}.glb")
            stl_path = exporter.export_stl(oriented, out_dir / f"{slug}_print.stl")
            obj_path = exporter.export_obj(game_mesh, out_dir / f"{slug}.obj")

        payload = {
            "slug": slug,
            "prompt": prompt,
            "preset": preset.name,
            "seed": seed,
            "material": material,
            "device": self.banner,
            "raw_faces": raw_faces,
            "game_faces": len(game_mesh.faces),
            "print_faces": len(oriented.faces),
            "cleanup": cleanup_report.as_dict(),
            "print": print_report.as_dict(),
            "timings": timings.as_dict(),
            "timings_markdown": timings.as_markdown(),
        }
        report_json, report_md = exporter.write_reports(out_dir, payload)

        payload["paths"] = {
            "dir": str(out_dir),
            "concept": str(out_dir / "concept.png"),
            "cutout": str(out_dir / "cutout.png"),
            "glb": str(glb_path),
            "stl": str(stl_path),
            "obj": str(obj_path),
            "report_json": str(report_json),
            "report_md": str(report_md),
        }
        notify(1.0, "Done")
        return payload
