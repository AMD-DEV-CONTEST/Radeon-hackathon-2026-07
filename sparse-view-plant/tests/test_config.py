from __future__ import annotations

from pathlib import Path

from sparse_view_plant.config import load_config


def test_load_config_defaults() -> None:
    config = load_config(None)
    assert config.pointcloud.image_resolution == 518
    assert config.pointcloud.device == "cuda"
    assert config.gaussians.enabled is False


def test_load_config_override(tmp_path: Path) -> None:
    path = tmp_path / "pipeline.toml"
    path.write_text(
        "[pointcloud]\n"
        'source_dir = "/tmp/vggt"\n'
        'device = "cpu"\n'
        "confidence_percentile = 10.0\n"
        "[gaussians]\n"
        "enabled = true\n"
        'source_dir = "/tmp/splatt3r"\n',
        encoding="utf-8",
    )
    config = load_config(path)
    assert config.pointcloud.source_dir == "/tmp/vggt"
    assert config.pointcloud.device == "cpu"
    assert config.pointcloud.confidence_percentile == 10.0
    assert config.gaussians.enabled is True
    assert config.gaussians.source_dir == "/tmp/splatt3r"
    # untouched fields keep defaults
    assert config.pointcloud.pixel_limit == 255_000


def test_load_config_gs_refine_fields(tmp_path: Path) -> None:
    path = tmp_path / "refine.toml"
    path.write_text(
        "[gaussians]\n"
        "enabled = true\n"
        'backend = "gs-refine"\n'
        'refine_mask_provider = "birefnet"\n'
        "refine_opacity_max = 0.3\n"
        "refine_scale_max = 0.02\n",
        encoding="utf-8",
    )
    config = load_config(path)
    assert config.gaussians.backend == "gs-refine"
    assert config.gaussians.refine_mask_provider == "birefnet"
    assert config.gaussians.refine_opacity_max == 0.3
    assert config.gaussians.refine_scale_max == 0.02
    assert config.gaussians.refine_export_trim == "maskfree"
    # untouched gs-refine fields keep defaults
    assert config.gaussians.refine_opacity_min == 0.05
    assert config.gaussians.refine_steps == 300


def test_load_config_gs_refine_2dgs_fields(tmp_path: Path) -> None:
    path = tmp_path / "refine_2dgs.toml"
    path.write_text(
        "[gaussians]\n"
        "enabled = true\n"
        'backend = "gs-refine"\n'
        "refine_2dgs = true\n"
        "refine_dist_weight = 0.5\n"
        "refine_normal_weight = 0.01\n"
        "refine_scale_disk = 0.05\n",
        encoding="utf-8",
    )
    config = load_config(path)
    assert config.gaussians.refine_2dgs is True
    assert config.gaussians.refine_dist_weight == 0.5
    assert config.gaussians.refine_normal_weight == 0.01
    assert config.gaussians.refine_scale_disk == 0.05
    assert config.gaussians.refine_2dgs_surface_init is True
    assert config.gaussians.refine_ray_constrained_means is False
    assert config.gaussians.refine_use_pointmap_intrinsics is False
    assert config.gaussians.refine_export_opacity_threshold == 0.0
    # untouched 2DGS fields keep defaults
    assert config.gaussians.refine_scale_max == 1.0


def test_load_config_refine_loss_fields(tmp_path: Path) -> None:
    path = tmp_path / "refine_loss.toml"
    path.write_text(
        "[gaussians]\n"
        "enabled = true\n"
        'backend = "gs-refine"\n'
        "refine_ssim_weight = 0.2\n"
        "refine_lr_anneal = true\n",
        encoding="utf-8",
    )
    config = load_config(path)
    assert config.gaussians.refine_ssim_weight == 0.2
    assert config.gaussians.refine_lr_anneal is True
    # defaults keep existing behavior off
    defaults = load_config(None)
    assert defaults.gaussians.refine_ssim_weight == 0.0
    assert defaults.gaussians.refine_lr_anneal is False


def test_load_config_refine_pose_fields(tmp_path: Path) -> None:
    path = tmp_path / "refine_pose.toml"
    path.write_text(
        "[gaussians]\n"
        "enabled = true\n"
        'backend = "gs-refine"\n'
        "refine_optimize_poses = true\n"
        "refine_pose_lr = 5e-4\n"
        "refine_focal_scale = 1.4\n",
        encoding="utf-8",
    )
    config = load_config(path)
    assert config.gaussians.refine_optimize_poses is True
    assert config.gaussians.refine_pose_lr == 5e-4
    assert config.gaussians.refine_focal_scale == 1.4
    assert load_config(None).gaussians.refine_optimize_poses is False
    assert load_config(None).gaussians.refine_focal_scale == 1.2


def test_load_config_gs_refine_2dgs_defaults_off() -> None:
    config = load_config(None)
    assert config.gaussians.refine_2dgs is False
    assert config.gaussians.refine_dist_weight == 0.1
    assert config.gaussians.refine_normal_weight == 0.0
    assert config.gaussians.refine_scale_disk == 1e-3
    assert config.gaussians.refine_2dgs_surface_init is True


def test_load_config_pointcloud_foreground_fields(tmp_path: Path) -> None:
    path = tmp_path / "vggt.toml"
    path.write_text(
        "[pointcloud]\n"
        "image_resolution = 448\n"
        "foreground_center_radius = 0.7\n"
        "foreground_confidence_percentile = 40.0\n"
        'foreground_provider = "birefnet"\n'
        "plant_fusion_budget_fraction = 0.5\n",
        encoding="utf-8",
    )
    config = load_config(path)
    assert config.pointcloud.image_resolution == 448
    assert config.pointcloud.foreground_center_radius == 0.7
    assert config.pointcloud.foreground_confidence_percentile == 40.0
    assert config.pointcloud.foreground_provider == "birefnet"
    assert config.pointcloud.plant_fusion_budget_fraction == 0.5
    # untouched fields keep defaults
    assert config.pointcloud.device == "cuda"
    assert config.pointcloud.pixel_limit == 255_000
