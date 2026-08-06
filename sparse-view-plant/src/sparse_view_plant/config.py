"""Pipeline configuration loaded from TOML."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class PointCloudConfig:
    """Configuration for the feed-forward point-cloud stage (VGGT)."""

    source_dir: str = ""  # vggt: clone of https://github.com/facebookresearch/vggt
    ckpt_path: str = (
        ""  # vggt: local checkpoint dir with model.safetensors ("" -> env or error)
    )
    image_resolution: int = (
        518  # vggt: inference resolution (518 official; 448 tested on T10 16GB)
    )
    device: str = "cuda"
    pixel_limit: int = 255_000
    confidence_percentile: float = 20.0
    foreground_center_radius: float = 0.7
    foreground_confidence_percentile: float = 40.0
    foreground_provider: str = "maskfree"  # pointcloud: maskfree | birefnet
    plant_fusion_budget_fraction: float = 1.0  # <1: conflict-aware point budget


@dataclass(frozen=True, slots=True)
class GaussianConfig:
    """Configuration for the feed-forward Gaussian stage.

    ``backend`` selects the Gaussian stage: ``gs-refine`` (default;
    per-scene photometric refinement of the point-cloud-initialized
    Gaussians, all attributes including means optimized directly with
    gsplat) or ``pointcloud-gs`` (no network: wraps the saved prediction
    as a Gaussian PLY). Fields beyond the shared ones are backend-specific
    and ignored by the other backends.
    """

    enabled: bool = False
    backend: str = "gs-refine"
    source_dir: str = ""
    model_id: str = "brandonsmart/splatt3r_v1.0"
    filename: str = "epoch=19-step=1200.ckpt"
    image_size: int = 512
    device: str = "cuda"
    pair_mode: str = "widest-baseline"  # splatt3r: use frontend poses for the pair
    ckpt_path: str = ""  # freesplatter: local checkpoint instead of Hub
    opacity_confidence_gate: float = 6.0  # point-gs: fold confidence into opacity
    scale_factor: float = 0.35  # point-gs: shrink splat scales (tighter silhouette)
    freesplatter_config: str = "configs/freesplatter-object-2dgs.yaml"
    estimate_poses: bool = False  # freesplatter: also recover input cameras
    num_views: int = 3  # freesplatter: views fed to the pose-free model
    refine_steps: int = 300  # gs-refine: photometric optimization steps
    refine_lr: float = 2e-3  # gs-refine: base AdamW learning rate
    refine_resolution: int = 256  # gs-refine: supervision render resolution
    refine_views: int = 0  # gs-refine: views per step (0 = all input views)
    refine_bg_weight: float = 0.5  # gs-refine: background L1 weight
    refine_alpha_weight: float = 0.1  # gs-refine: alpha-vs-mask weight
    refine_max_points: int = 400_000  # gs-refine: Gaussian count cap
    refine_keep_fraction: float = 0.8  # gs-refine: top-confidence keep
    refine_freeze_means: bool = False  # gs-refine: keep frontend means fixed
    refine_ray_constrained_means: bool = (
        False  # gs-refine: restrict pointmap means to their source camera rays
    )
    refine_freeze_opacity: bool = (
        False  # gs-refine: keep confidence-mapped opacity fixed
    )
    refine_opacity_reg: float = 0.0  # gs-refine: L2 pull of opacity toward confidence
    refine_means_reg: float = (
        0.0  # gs-refine: L2 pull of means toward the frontend init
    )
    refine_scale_floor: float = (
        0.0  # gs-refine: min scale as a fraction of init density scale
    )
    refine_mask_provider: str = (
        "maskfree"  # gs-refine: maskfree | birefnet foreground masks
    )
    refine_init_provider: str = (
        "none"  # gs-refine: none | maskfree | birefnet init point trim
    )
    refine_opacity_min: float = (
        0.05  # gs-refine: low end of the confidence->opacity ramp
    )
    refine_opacity_max: float = (
        0.9  # gs-refine: high end of the confidence->opacity ramp
    )
    refine_scale_max: float = 1.0  # gs-refine: upper clamp on world-unit scale
    refine_export_trim: str = "maskfree"  # gs-refine: none | maskfree | birefnet | birefnet-proj 2D export trim
    refine_export_opacity_threshold: float = (
        0.0  # gs-refine: omit learned low-opacity splats from the exported PLY
    )
    refine_export_density_trim: bool = (
        False  # gs-refine: additionally drop splats far from the point cloud
    )
    refine_export_density_threshold: float = (
        0.02  # gs-refine: density-trim world-unit NN distance to the point cloud
    )
    refine_export_density_sigma: float = (
        0.0  # gs-refine: smooth density falloff (world units); 0 = binary trim
    )
    refine_export_trim_position: bool = (
        False  # gs-refine: evaluate export trim at each splat's current mean
    )
    refine_2dgs: bool = False  # gs-refine: use gsplat 2DGS surfel rasterization
    refine_sh_degree: int = (
        0  # gs-refine: SH degree for view-dependent colors (0 = DC only)
    )
    refine_dist_weight: float = (
        0.1  # gs-refine 2DGS: depth distortion (distloss) weight
    )
    refine_normal_weight: float = (
        0.0  # gs-refine 2DGS: normal consistency weight (0 = off)
    )
    refine_scale_disk: float = (
        1e-3  # gs-refine 2DGS: init third scale = density scale * this fraction
    )
    refine_2dgs_surface_init: bool = (
        True  # gs-refine 2DGS: initialize disks from frontend pointmap tangents
    )
    refine_focal_scale: float = (
        1.2  # gs-refine: assumed focal = this * resolution (supervision K)
    )
    refine_use_pointmap_intrinsics: bool = (
        False  # gs-refine: recover per-view K from frontend pointmap correspondences
    )
    refine_optimize_poses: bool = (
        False  # gs-refine: refine the frontend cameras under the photometric loss
    )
    refine_pose_lr: float = 2e-4  # gs-refine: per-camera pose-delta learning rate
    refine_ssim_weight: float = (
        0.0  # gs-refine: lerp weight for (1 - SSIM) in the photometric loss
    )
    refine_lr_anneal: bool = (
        False  # gs-refine: linearly decay the learning rate to zero
    )
    refine_densify: bool = (
        False  # gs-refine: 3DGS-style adaptive densification (clone/split/prune)
    )
    refine_densify_from: int = (
        100  # gs-refine: first densify step (0-based); grads accumulate before this
    )
    refine_densify_until: int = (
        1000  # gs-refine: last densify step (0-based; may exceed refine_steps)
    )
    refine_densify_every: int = (
        50  # gs-refine: densify interval in steps (within from..until)
    )
    refine_densify_grad2d: float = (
        2e-4  # gs-refine: view-space mean-gradient threshold for clone/split
    )
    refine_densify_prune_opa: float = (
        0.005  # gs-refine: opacity threshold for pruning low-opacity splats
    )
    refine_densify_split_scale: float = 0.01  # gs-refine: max-scale threshold (world units): smaller -> clone, larger -> split
    refine_densify_max_points: int = (
        600_000  # gs-refine: hard Gaussian cap after each densify pass
    )
    refine_densify_reset_every: int = (
        0  # gs-refine: opacity reset interval (0 = disabled, e.g. 3000 like 3DGS)
    )


@dataclass(frozen=True, slots=True)
class PipelineConfig:
    pointcloud: PointCloudConfig = field(default_factory=PointCloudConfig)
    gaussians: GaussianConfig = field(default_factory=GaussianConfig)


_PC_DEFAULTS: dict[str, Any] = {
    "source_dir": "",
    "ckpt_path": "",
    "image_resolution": 518,
    "device": "cuda",
    "pixel_limit": 255_000,
    "confidence_percentile": 20.0,
    "foreground_center_radius": 0.7,
    "foreground_confidence_percentile": 40.0,
    "foreground_provider": "maskfree",
    "plant_fusion_budget_fraction": 1.0,
}

_GS_DEFAULTS: dict[str, Any] = {
    "enabled": False,
    "backend": "gs-refine",
    "source_dir": "",
    "model_id": "brandonsmart/splatt3r_v1.0",
    "filename": "epoch=19-step=1200.ckpt",
    "image_size": 512,
    "device": "cuda",
    "pair_mode": "widest-baseline",
    "ckpt_path": "",
    "opacity_confidence_gate": 6.0,
    "scale_factor": 0.35,
    "freesplatter_config": "configs/freesplatter-object-2dgs.yaml",
    "estimate_poses": False,
    "num_views": 3,
    "refine_steps": 300,
    "refine_lr": 2e-3,
    "refine_resolution": 256,
    "refine_views": 0,
    "refine_bg_weight": 0.5,
    "refine_alpha_weight": 0.1,
    "refine_max_points": 400_000,
    "refine_keep_fraction": 0.8,
    "refine_freeze_means": False,
    "refine_ray_constrained_means": False,
    "refine_freeze_opacity": False,
    "refine_opacity_reg": 0.0,
    "refine_means_reg": 0.0,
    "refine_scale_floor": 0.0,
    "refine_mask_provider": "maskfree",
    "refine_opacity_min": 0.05,
    "refine_opacity_max": 0.9,
    "refine_scale_max": 1.0,
    "refine_export_trim": "maskfree",
    "refine_export_opacity_threshold": 0.0,
    "refine_export_density_trim": False,
    "refine_export_density_threshold": 0.02,
    "refine_export_density_sigma": 0.0,
    "refine_export_trim_position": False,
    "refine_2dgs": False,
    "refine_sh_degree": 0,
    "refine_dist_weight": 0.1,
    "refine_normal_weight": 0.0,
    "refine_scale_disk": 1e-3,
    "refine_2dgs_surface_init": True,
    "refine_ssim_weight": 0.0,
    "refine_lr_anneal": False,
    "refine_focal_scale": 1.2,
    "refine_use_pointmap_intrinsics": False,
    "refine_optimize_poses": False,
    "refine_pose_lr": 2e-4,
    "refine_densify": False,
    "refine_densify_from": 100,
    "refine_densify_until": 1000,
    "refine_densify_every": 50,
    "refine_densify_grad2d": 2e-4,
    "refine_densify_prune_opa": 0.005,
    "refine_densify_split_scale": 0.01,
    "refine_densify_max_points": 600_000,
    "refine_densify_reset_every": 0,
}


def _section(
    raw: dict[str, Any], name: str, defaults: dict[str, Any]
) -> dict[str, Any]:
    section = raw.get(name)
    if section is None:
        return dict(defaults)
    if not isinstance(section, dict):
        raise TypeError(f"config section [{name}] must be a table")
    return {**defaults, **{k: v for k, v in section.items() if isinstance(k, str)}}


def load_config(path: str | Path | None) -> PipelineConfig:
    """Load pipeline config from TOML, falling back to field defaults."""
    if path is None:
        return PipelineConfig()
    with Path(path).open("rb") as fh:
        raw = tomllib.load(fh)
    pc = _section(raw, "pointcloud", _PC_DEFAULTS)
    gc = _section(raw, "gaussians", _GS_DEFAULTS)
    return PipelineConfig(
        pointcloud=PointCloudConfig(
            source_dir=str(pc["source_dir"]),
            ckpt_path=str(pc["ckpt_path"]),
            device=str(pc["device"]),
            pixel_limit=int(pc["pixel_limit"]),
            confidence_percentile=float(pc["confidence_percentile"]),
            image_resolution=int(pc["image_resolution"]),
            foreground_center_radius=float(pc["foreground_center_radius"]),
            foreground_confidence_percentile=float(
                pc["foreground_confidence_percentile"]
            ),
            foreground_provider=str(pc["foreground_provider"]),
            plant_fusion_budget_fraction=float(pc["plant_fusion_budget_fraction"]),
        ),
        gaussians=GaussianConfig(
            enabled=bool(gc["enabled"]),
            backend=str(gc["backend"]),
            source_dir=str(gc["source_dir"]),
            model_id=str(gc["model_id"]),
            filename=str(gc["filename"]),
            image_size=int(gc["image_size"]),
            device=str(gc["device"]),
            pair_mode=str(gc["pair_mode"]),
            ckpt_path=str(gc["ckpt_path"]),
            opacity_confidence_gate=float(gc["opacity_confidence_gate"]),
            scale_factor=float(gc["scale_factor"]),
            freesplatter_config=str(gc["freesplatter_config"]),
            estimate_poses=bool(gc["estimate_poses"]),
            num_views=int(gc["num_views"]),
            refine_steps=int(gc["refine_steps"]),
            refine_lr=float(gc["refine_lr"]),
            refine_resolution=int(gc["refine_resolution"]),
            refine_views=int(gc["refine_views"]),
            refine_bg_weight=float(gc["refine_bg_weight"]),
            refine_alpha_weight=float(gc["refine_alpha_weight"]),
            refine_max_points=int(gc["refine_max_points"]),
            refine_keep_fraction=float(gc["refine_keep_fraction"]),
            refine_freeze_means=bool(gc["refine_freeze_means"]),
            refine_ray_constrained_means=bool(gc["refine_ray_constrained_means"]),
            refine_freeze_opacity=bool(gc["refine_freeze_opacity"]),
            refine_opacity_reg=float(gc["refine_opacity_reg"]),
            refine_means_reg=float(gc["refine_means_reg"]),
            refine_scale_floor=float(gc["refine_scale_floor"]),
            refine_mask_provider=str(gc["refine_mask_provider"]),
            refine_opacity_min=float(gc["refine_opacity_min"]),
            refine_opacity_max=float(gc["refine_opacity_max"]),
            refine_scale_max=float(gc["refine_scale_max"]),
            refine_export_trim=str(gc["refine_export_trim"]),
            refine_export_opacity_threshold=float(
                gc["refine_export_opacity_threshold"]
            ),
            refine_export_density_trim=bool(gc["refine_export_density_trim"]),
            refine_export_density_threshold=float(
                gc["refine_export_density_threshold"]
            ),
            refine_export_density_sigma=float(gc["refine_export_density_sigma"]),
            refine_export_trim_position=bool(gc["refine_export_trim_position"]),
            refine_2dgs=bool(gc["refine_2dgs"]),
            refine_sh_degree=int(gc["refine_sh_degree"]),
            refine_dist_weight=float(gc["refine_dist_weight"]),
            refine_normal_weight=float(gc["refine_normal_weight"]),
            refine_scale_disk=float(gc["refine_scale_disk"]),
            refine_2dgs_surface_init=bool(gc["refine_2dgs_surface_init"]),
            refine_ssim_weight=float(gc["refine_ssim_weight"]),
            refine_lr_anneal=bool(gc["refine_lr_anneal"]),
            refine_focal_scale=float(gc["refine_focal_scale"]),
            refine_use_pointmap_intrinsics=bool(gc["refine_use_pointmap_intrinsics"]),
            refine_optimize_poses=bool(gc["refine_optimize_poses"]),
            refine_pose_lr=float(gc["refine_pose_lr"]),
            refine_densify=bool(gc["refine_densify"]),
            refine_densify_from=int(gc["refine_densify_from"]),
            refine_densify_until=int(gc["refine_densify_until"]),
            refine_densify_every=int(gc["refine_densify_every"]),
            refine_densify_grad2d=float(gc["refine_densify_grad2d"]),
            refine_densify_prune_opa=float(gc["refine_densify_prune_opa"]),
            refine_densify_split_scale=float(gc["refine_densify_split_scale"]),
            refine_densify_max_points=int(gc["refine_densify_max_points"]),
            refine_densify_reset_every=int(gc["refine_densify_reset_every"]),
        ),
    )
