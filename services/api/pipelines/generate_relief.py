from pathlib import Path

from adapters.factory import get_image_provider, get_depth_provider, get_3d_provider
from models import SessionLocal, GenerationJob, JobStatus
from storage import result_path


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


def run_generate_relief_pipeline(
    job_id: str,
    input_image_path: str,
    style: str,
    prompt: str,
    postprocess_params: dict,
):
    """End-to-end pipeline: single image -> local style transfer -> local depth -> 2.5D relief mesh -> export.

    The style transfer and depth estimation steps run on AMD ROCm when available.
    The mesh generation is CPU-based (trimesh/numpy) and does not require GPU VRAM.
    """
    try:
        input_path = Path(input_image_path)
        if not input_path.is_absolute():
            input_path = Path.cwd() / input_path

        update_job_status(job_id, JobStatus.PREPROCESSING)

        # 1. Local style transfer on ROCm (or CPU fallback)
        update_job_status(job_id, JobStatus.GENERATING_MULTIVIEW, status_message="Applying style transfer")
        image_provider = get_image_provider()
        styled_image = image_provider.generate_image_from_image(
            image=input_path,
            prompt=prompt,
        )

        # 2. Local monocular depth estimation on ROCm
        update_job_status(job_id, JobStatus.GENERATING_MULTIVIEW, status_message="Estimating depth map")
        depth_provider = get_depth_provider()
        invert = postprocess_params.get("invert", False)
        depth_map = depth_provider.generate_depth_map(styled_image, invert=invert)

        # 3. Generate 2.5D relief mesh from depth map
        update_job_status(job_id, JobStatus.GENERATING_3D, status_message="Building relief mesh")
        result_mesh = result_path(job_id, "relief.stl")
        three_d_provider = get_3d_provider(output_mode="relief_2d5")
        mesh_asset = three_d_provider.generate_3d_from_images(
            images=[depth_map, styled_image],
            prompt=prompt,
            style=style,
            output_path=result_mesh,
            **postprocess_params,
        )

        # 4. Post-process / print readiness check
        update_job_status(job_id, JobStatus.POSTPROCESSING)

        # Compute simple print metrics from the mesh (GLB is the textured variant, STL is also exported).
        try:
            import trimesh
            mesh = trimesh.load(mesh_asset.mesh_path, force="mesh")
            bounds = mesh.bounding_box.bounds
            dimensions = [float(bounds[1][i] - bounds[0][i]) for i in range(3)]
            volume = float(mesh.volume) if mesh.is_watertight else 0.0
            is_watertight = bool(mesh.is_watertight)
        except Exception as exc:
            dimensions = [0.0, 0.0, 0.0]
            volume = 0.0
            is_watertight = False

        update_job_status(
            job_id,
            JobStatus.COMPLETED,
            result_model_path=_relative_to_cwd(mesh_asset.mesh_path),
            result_preview_path=_relative_to_cwd(styled_image),
            multiview_image_paths=[_relative_to_cwd(styled_image), _relative_to_cwd(depth_map)],
            print_report={
                "volume_cm3": volume / 1000.0,
                "dimensions_mm": [round(d, 2) for d in dimensions],
                "base_thickness_mm": postprocess_params.get("base_thickness_mm", 3.0),
                "relief_height_mm": postprocess_params.get("relief_height_mm", 4.0),
                "invert": invert,
                "shape": postprocess_params.get("shape", "rectangular"),
                "is_watertight": is_watertight,
            },
        )
    except Exception as exc:
        update_job_status(job_id, JobStatus.FAILED, error_message=str(exc))
        raise
