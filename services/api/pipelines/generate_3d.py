from pathlib import Path

import numpy as np
import trimesh
import warnings
from PIL import Image

from adapters.factory import get_image_provider, get_3d_provider
from models import SessionLocal, GenerationJob, JobStatus
from storage import result_path


image_provider = get_image_provider()
three_d_provider = get_3d_provider()


def update_job_status(job_id: str, status: JobStatus, **kwargs):
    db = SessionLocal()
    try:
        job = db.query(GenerationJob).filter(GenerationJob.id == job_id).first()
        if job:
            job.status = status.value
            for key, value in kwargs.items():
                setattr(job, key, value)
            db.commit()
    finally:
        db.close()


def _relative_to_cwd(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(path)


def _scale_to_print_size(mesh: trimesh.Trimesh, target_height_mm: float) -> trimesh.Trimesh:
    """Scale a normalized mesh so its height (Y-axis) matches target_height_mm.

    The mesh is centered on X/Y, translated so its bottom sits at Z=0, and
    scaled uniformly so the print-ready orientation matches real-world mm.
    """
    bounds = mesh.bounding_box.bounds
    extents = mesh.bounding_box.extents

    # Use the Y-axis as the height axis. If extents are zero, return as-is.
    height = float(extents[1])
    if height <= 1e-6:
        return mesh

    scale = target_height_mm / height
    mesh.apply_scale(scale)

    # Re-center on X/Y and put the bottom on the build plate (Z=0).
    bounds = mesh.bounding_box.bounds
    center_x = (bounds[0][0] + bounds[1][0]) / 2.0
    center_y = (bounds[0][1] + bounds[1][1]) / 2.0
    z_min = bounds[0][2]
    mesh.apply_translation((-center_x, -center_y, -z_min))
    return mesh


def _apply_planar_texture(mesh: trimesh.Trimesh, image_path: Path) -> trimesh.Trimesh:
    """Bake an image as a front-projection texture onto the mesh (XY-plane UV).

    This is a simple fallback when the native texture pipeline (Hunyuan3D-2 Paint)
    cannot run on ROCm. The sides/back will show stretched color, but the front
    will match the reference image.
    """
    try:
        img = Image.open(image_path).convert("RGB")
    except Exception as exc:
        warnings.warn(f"Could not load texture image {image_path}: {exc}")
        return mesh

    bounds = mesh.bounds
    xmin, xmax = float(bounds[0][0]), float(bounds[1][0])
    ymin, ymax = float(bounds[0][1]), float(bounds[1][1])
    x_range = max(xmax - xmin, 1e-6)
    y_range = max(ymax - ymin, 1e-6)

    uv = np.array([
        [(v[0] - xmin) / x_range, (v[1] - ymin) / y_range]
        for v in mesh.vertices
    ], dtype=np.float32)

    material = trimesh.visual.material.SimpleMaterial(image=img)
    mesh.visual = trimesh.visual.TextureVisuals(uv=uv, material=material)
    return mesh


def _postprocess_mesh(mesh_path: Path, postprocess_params: dict) -> dict:
    """Scale mesh to print size, optionally bake texture, export, and return print report."""
    mesh = trimesh.load(mesh_path, force="mesh")
    mesh = _scale_to_print_size(mesh, float(postprocess_params.get("target_height_mm", 80.0)))

    texture_image = postprocess_params.get("texture_image_path")
    if texture_image:
        mesh = _apply_planar_texture(mesh, Path(texture_image))

    mesh.export(mesh_path)

    bounds = mesh.bounding_box.bounds
    dimensions = [float(bounds[1][i] - bounds[0][i]) for i in range(3)]
    volume = float(mesh.volume) if mesh.is_watertight else 0.0
    is_watertight = bool(mesh.is_watertight)

    return {
        "volume_cm3": round(volume / 1000.0, 2),
        "dimensions_mm": [round(d, 2) for d in dimensions],
        "wall_thickness_mm": float(postprocess_params.get("wall_thickness_mm", 2.0)),
        "target_height_mm": float(postprocess_params.get("target_height_mm", 80.0)),
        "is_watertight": is_watertight,
        "unit": "mm",
    }


def run_generate_3d_pipeline(
    job_id: str,
    input_image_path: str,
    style: str,
    prompt: str,
    postprocess_params: dict | None = None,
):
    """End-to-end pipeline: single image -> style transfer -> 3D -> postprocess."""
    postprocess_params = postprocess_params or {}

    try:
        input_path = Path(input_image_path)
        if not input_path.is_absolute():
            input_path = Path.cwd() / input_path

        update_job_status(job_id, JobStatus.PREPROCESSING)

        # 1. Apply the requested style to the reference image (image-to-image).
        update_job_status(job_id, JobStatus.GENERATING_MULTIVIEW, status_message="Applying style transfer")
        styled_image = image_provider.generate_image_from_image(
            image=input_path,
            prompt=prompt,
        )

        # 2. Generate multi-view renders from the styled front view.
        update_job_status(job_id, JobStatus.GENERATING_MULTIVIEW, status_message="Generating multi-view images")
        multiview_images = image_provider.generate_multiview_from_image(
            image=styled_image,
            prompt=prompt,
            num_views=4,
        )
        if not multiview_images:
            multiview_images = [styled_image]

        # 3. Generate a 3D mesh from the multi-view reference images.
        update_job_status(job_id, JobStatus.GENERATING_3D, status_message="Generating 3D mesh")
        result_mesh = result_path(job_id, "model.glb")
        mesh_asset = three_d_provider.generate_3d_from_images(
            images=multiview_images,
            prompt=prompt,
            style=style,
            output_path=result_mesh,
        )

        # 3. Post-process and compute print metrics.
        update_job_status(job_id, JobStatus.POSTPROCESSING, status_message="Scaling, texturing and computing print metrics")
        if not mesh_asset.mesh_path.exists():
            result_mesh.write_text("{}\n")  # empty GLB placeholder

        postprocess_params["texture_image_path"] = str(styled_image)
        print_report = _postprocess_mesh(mesh_asset.mesh_path, postprocess_params)

        update_job_status(
            job_id,
            JobStatus.COMPLETED,
            result_model_path=_relative_to_cwd(mesh_asset.mesh_path),
            result_preview_path=_relative_to_cwd(styled_image),
            multiview_image_paths=[_relative_to_cwd(p) for p in multiview_images],
            print_report=print_report,
        )
    except Exception as exc:
        update_job_status(job_id, JobStatus.FAILED, error_message=str(exc))
        raise
