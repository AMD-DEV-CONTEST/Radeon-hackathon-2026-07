"""Run the sparse-view plant reconstruction pipeline.

Input: a folder of unannotated RGB images of one plant.
Outputs: a fused point cloud (PLY), and optionally feed-forward 3D Gaussians
(PLY) from the configured Gaussian backend (gs-refine / pointcloud-gs; see
configs/).

Examples:
    uv run --extra gpu python scripts/run_pipeline.py \
        --images <folder> --output outputs/demo/bean_1
    uv run --extra gpu python scripts/run_pipeline.py \
        --images <folder> --output outputs/demo/bean_1 --stage all \
        --config configs/pipeline.toml

Digital-twin extras (off by default):
    uv run --extra gpu python scripts/run_pipeline.py \
        --images <folder> --output outputs/demo/bean_1 --measure --mesh
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Literal

from sparse_view_plant.config import PipelineConfig, load_config
from sparse_view_plant.evaluation import load_ply_points
from sparse_view_plant.export import (
    write_json,
    write_triangle_mesh_ply,
)
from sparse_view_plant.gaussians import create_gaussian_stage
from sparse_view_plant.images import discover_images
from sparse_view_plant.measure import measure_plant
from sparse_view_plant.meshing import implicit_voxel_mesh, voxel_surface_mesh
from sparse_view_plant.pointcloud import create_pointcloud_stage, save_prediction
from sparse_view_plant.views import sample_candidate_pool, select_diverse_views


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--images", required=True, type=Path, help="folder of input RGB images"
    )
    parser.add_argument("--output", required=True, type=Path, help="output directory")
    parser.add_argument(
        "--config", type=Path, default=None, help="TOML config (defaults are fine)"
    )
    parser.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="SECTION.KEY=VALUE",
        help="override a config field, e.g. gaussians.refine_opacity_max=0.3",
    )
    parser.add_argument(
        "--stage",
        choices=("pointcloud", "gaussians", "all"),
        default="pointcloud",
        help="pointcloud (configured frontend) and/or gaussians (configured GS backend)",
    )
    parser.add_argument(
        "--max-views", type=int, default=None, help="cap input image count"
    )
    parser.add_argument(
        "--select-views",
        action="store_true",
        help="pick the most spread views via a probe frontend pass (wide baseline)",
    )
    parser.add_argument(
        "--candidate-views",
        type=int,
        default=8,
        help="probe pool size for --select-views; when the scene has more "
        "frames, the pool is uniformly subsampled to this size so the probe "
        "covers the whole rotation instead of the first N frames",
    )
    parser.add_argument(
        "--candidate-margin",
        type=int,
        default=0,
        help="drop this many frames at each end of the sequence before the "
        "--select-views probe pool is sampled; turntable start/stop frames "
        "often have worse frontend pose estimates",
    )
    parser.add_argument(
        "--select-seed",
        type=int,
        default=0,
        help="random seed for the --select-views farthest-point sampler "
        "(view-selection variance diagnostic)",
    )
    parser.add_argument(
        "--select-mode",
        choices=["fps", "pca"],
        default="fps",
        help="view-selection spread metric: raw probe directions (fps) or "
        "PCA-fitted rotation angles (pca, closes the blind arc under probe "
        "pose noise)",
    )
    parser.add_argument(
        "--probe-pixel-limit",
        type=int,
        default=120000,
        help="per-image pixel cap for the --select-views probe pass; the probe "
        "only needs camera centres, so a lower limit than the reconstruction "
        "pixel_limit keeps large candidate pools within GPU memory",
    )
    parser.add_argument("--device", default=None, help="override device, e.g. cpu")
    parser.add_argument(
        "--vggt-src",
        default=None,
        help="override VGGT source directory (clone of facebookresearch/vggt)",
    )
    parser.add_argument(
        "--measure",
        action="store_true",
        help="write plant_metrics.json (phenotype measurements) for the point cloud",
    )
    parser.add_argument(
        "--mesh",
        action="store_true",
        help="write mesh.ply from the reconstructed point cloud/Gaussians",
    )
    parser.add_argument(
        "--mesh-method",
        choices=("voxel", "implicit"),
        default="voxel",
        help="voxel is the legacy block surface; implicit uses topology-cleaned "
        "marching tetrahedra (recommended for viewing)",
    )
    parser.add_argument(
        "--mesh-source",
        choices=("auto", "pointcloud", "gaussians"),
        default="auto",
        help="mesh input: pointcloud.ply, opacity-filtered Gaussian means "
        "(better coverage after the gaussians stage), or auto (gaussians when "
        "available)",
    )
    parser.add_argument(
        "--mesh-voxel-fraction",
        type=float,
        default=0.005,
        help="voxel cell size for --mesh as a fraction of the cloud diagonal "
        "(0.005 beats 0.01 for thin plant structures; ~3-5x vertices)",
    )
    parser.add_argument(
        "--mesh-dilate",
        type=int,
        default=1,
        help="binary dilation iterations for --mesh (closes small holes)",
    )
    return parser.parse_args(argv)


def _coerce_config_value(raw: str) -> Any:
    """Parse a --set value as bool / int / float, falling back to str."""
    lowered = raw.strip().lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    for cast in (int, float):
        try:
            return cast(raw)
        except ValueError:
            continue
    return raw


def apply_config_override(config: PipelineConfig, item: str) -> PipelineConfig:
    """Apply one ``--set SECTION.KEY=VALUE`` override via dataclass replace."""
    key, sep, raw = item.partition("=")
    if not sep or "." not in key:
        raise SystemExit(f"--set expects SECTION.KEY=VALUE, got: {item!r}")
    section_name, field = key.split(".", 1)
    value = _coerce_config_value(raw)
    if section_name == "pointcloud":
        return replace(config, pointcloud=replace(config.pointcloud, **{field: value}))
    if section_name == "gaussians":
        return replace(config, gaussians=replace(config.gaussians, **{field: value}))
    raise SystemExit(
        f"--set: unknown section {section_name!r} (expected pointcloud|gaussians)"
    )


def run_pipeline(args: argparse.Namespace) -> int:
    """Execute a parsed pipeline request in the current Python process."""
    config = load_config(args.config)
    for item in args.set:
        config = apply_config_override(config, item)
    if args.device:
        config = replace(
            config,
            pointcloud=replace(config.pointcloud, device=args.device),
            gaussians=replace(config.gaussians, device=args.device),
        )
    if args.vggt_src:
        config = replace(
            config,
            pointcloud=replace(config.pointcloud, source_dir=args.vggt_src),
        )
    # With --select-views on the pointcloud stage the whole sequence is the
    # candidate pool (the probe pass below uniformly subsamples it to
    # --candidate-views before the frontend pose pass; probing 200+ frames in one
    # batch would exceed GPU memory). Other stage combos keep the max-views cap.
    images = discover_images(
        args.images,
        max_views=(
            None
            if args.select_views and args.stage in {"pointcloud", "all"}
            else args.max_views
        ),
    )
    output_dir = args.output
    output_dir.mkdir(parents=True, exist_ok=True)

    results: dict[str, Any] = {
        "run_id": datetime.now(UTC).strftime("%Y%m%d-%H%M%S"),
        "images": [image.path.name for image in images],
        "config": {"pointcloud": args.device or config.pointcloud.device},
        "plant_metrics": None,
        "mesh": None,
    }
    if args.select_views:
        results["select"] = {
            "candidate_views": args.candidate_views,
            "candidate_margin": args.candidate_margin,
            "seed": args.select_seed,
            "probe_pixel_limit": args.probe_pixel_limit,
            "mode": args.select_mode,
        }
    pointcloud_path: str | None = None
    pointcloud_seconds = 0.0
    gaussians_path: str | None = None
    gaussians_seconds = 0.0

    prediction = None
    if args.stage in {"pointcloud", "all"}:
        started = perf_counter()
        stage = create_pointcloud_stage(config.pointcloud)
        if (
            args.select_views
            and args.max_views is not None
            and len(images) > args.max_views
        ):
            pool = images
            if args.candidate_margin:
                trimmed = images[
                    args.candidate_margin : len(images) - args.candidate_margin
                ]
                if len(trimmed) >= args.max_views:
                    pool = trimmed
                    print(
                        f"[pipeline] trimmed {args.candidate_margin} frames at "
                        f"each end -> {len(pool)} candidate frames"
                    )
            candidate_ids = sample_candidate_pool(
                [view.view_id for view in pool], args.candidate_views
            )
            candidates = [view for view in pool if view.view_id in set(candidate_ids)]
            probe_pixel_limit = min(
                config.pointcloud.pixel_limit, args.probe_pixel_limit
            )
            probe = create_pointcloud_stage(
                replace(config.pointcloud, pixel_limit=probe_pixel_limit)
            ).predict(candidates)
            selected = select_diverse_views(
                probe.camera_to_world,
                [view.view_id for view in candidates],
                count=args.max_views,
                seed=args.select_seed,
                regularize_axis=args.select_mode == "pca",
            )
            images = [view for view in images if view.view_id in selected]
            print(
                f"[pipeline] probe pool {len(candidates)}/{len(candidate_ids)} "
                f"frames, selected {len(images)} spread views: "
                f"{[v.view_id for v in images]}"
            )
            results["images"] = [image.path.name for image in images]
        prediction = stage.predict(images)
        model_name = getattr(stage, "model_name", "vggt")
        paths = save_prediction(
            prediction,
            output_dir,
            confidence_percentile=config.pointcloud.confidence_percentile,
            foreground_center_radius=config.pointcloud.foreground_center_radius,
            foreground_confidence_percentile=(
                config.pointcloud.foreground_confidence_percentile
            ),
            foreground_provider=config.pointcloud.foreground_provider,
            plant_fusion_budget_fraction=(
                config.pointcloud.plant_fusion_budget_fraction
            ),
            foreground_images=images,
            device=config.pointcloud.device,
            model_name=model_name,
        )
        pointcloud_seconds = round(perf_counter() - started, 2)
        pointcloud_path = str(paths["pointcloud"])
        results["pointcloud"] = {
            "seconds": pointcloud_seconds,
            "files": {name: str(path) for name, path in paths.items()},
        }
        if args.measure:
            started = perf_counter()
            measurements = measure_plant(
                load_ply_points(paths["pointcloud"]),
                metric_scale=prediction.metric_scale,
            )
            metrics_path = output_dir / "plant_metrics.json"
            write_json(
                metrics_path,
                {"scene": output_dir.name, **asdict(measurements)},
            )
            results["plant_metrics"] = str(metrics_path)
            print(
                f"[pipeline] plant_metrics: {metrics_path} "
                f"({perf_counter() - started:.2f}s)"
            )
    if args.stage in {"gaussians", "all"}:
        if not config.gaussians.enabled:
            raise SystemExit(
                "gaussians stage requested but gaussians.enabled=false in config"
            )
        started = perf_counter()
        stage = create_gaussian_stage(config.gaussians)
        poses = None if prediction is None else prediction.camera_to_world
        ply = stage.reconstruct(images, output_dir, camera_to_world=poses)
        gaussians_seconds = round(perf_counter() - started, 2)
        gaussians_path = str(ply)
        results["gaussians"] = {
            "seconds": gaussians_seconds,
            "backend": config.gaussians.backend,
            "ply": gaussians_path,
        }
    if args.mesh:
        started = perf_counter()
        gaussians_ply = output_dir / "gaussians.ply"
        pointcloud_ply = output_dir / "pointcloud.ply"
        mesh_source = args.mesh_source
        if mesh_source == "auto":
            if gaussians_ply.is_file():
                mesh_source = "gaussians"
            elif pointcloud_ply.is_file():
                mesh_source = "pointcloud"
            else:
                raise SystemExit("--mesh needs gaussians.ply or pointcloud.ply")
        if mesh_source == "gaussians":
            if not gaussians_ply.is_file():
                raise SystemExit("--mesh-source gaussians needs gaussians.ply")
            from scipy.spatial import cKDTree  # ty: ignore[unresolved-import]

            from sparse_view_plant.export import read_gaussian_ply_means_colors

            points, point_colours = read_gaussian_ply_means_colors(gaussians_ply)
        else:
            if not pointcloud_ply.is_file():
                raise SystemExit("--mesh-source pointcloud needs pointcloud.ply")
            points = load_ply_points(pointcloud_ply)
            point_colours = None
        if args.mesh_method == "implicit":
            vertices, faces = implicit_voxel_mesh(
                points,
                voxel_fraction=args.mesh_voxel_fraction,
                closing=args.mesh_dilate,
            )
        else:
            vertices, faces = voxel_surface_mesh(
                points,
                voxel_fraction=args.mesh_voxel_fraction,
                dilate=args.mesh_dilate,
            )
        vertex_colours = None
        if point_colours is not None:
            nearest = cKDTree(points).query(vertices, workers=-1)[1]
            vertex_colours = point_colours[nearest]
        mesh_path = output_dir / "mesh.ply"
        stats = write_triangle_mesh_ply(
            mesh_path, vertices, faces, vertex_colors=vertex_colours
        )
        results["mesh"] = str(mesh_path)
        print(
            f"[pipeline] mesh ({mesh_source}/{args.mesh_method}): {mesh_path} "
            f"({stats['vertices']} vertices, {stats['faces']} faces, "
            f"{perf_counter() - started:.2f}s)"
        )
    write_json(output_dir / "pipeline.json", results)

    print(f"[pipeline] images: {len(images)}")
    if pointcloud_path is not None:
        print(f"[pipeline] pointcloud: {pointcloud_path} ({pointcloud_seconds}s)")
    if gaussians_path is not None:
        print(f"[pipeline] gaussians: {gaussians_path} ({gaussians_seconds}s)")
    return 0


def reconstruct_plant(
    images: Path,
    output: Path,
    *,
    config_path: Path,
    config_overrides: Sequence[str] = (),
    stage: Literal["pointcloud", "gaussians", "all"] = "all",
) -> int:
    """Run the reconstruction pipeline through a Python-first interface."""
    argv = [
        "--images",
        str(images),
        "--output",
        str(output),
        "--stage",
        stage,
        "--config",
        str(config_path),
    ]
    for override in config_overrides:
        argv.extend(("--set", override))
    return run_pipeline(parse_args(argv))


def main(argv: Sequence[str] | None = None) -> int:
    """CLI adapter for :func:`run_pipeline`."""
    return run_pipeline(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
