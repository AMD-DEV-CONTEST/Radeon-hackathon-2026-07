"""Gaussian-stage backend dispatcher for the release pipeline.

``create_gaussian_stage`` selects the configured backend. The release ships
the gs-refine backend (``gaussians_gsrefine``, photometric refinement of a
point-cloud initialization) and the zero-network pointcloud-gs converter
(``gaussians_pointcloud``). Other feed-forward backends (Splatt3R,
FreeSplatter, AnySplat, point-gs) live in the research repository.
"""

from __future__ import annotations

from sparse_view_plant.config import GaussianConfig


def create_gaussian_stage(config: GaussianConfig):
    """Instantiate the configured Gaussian backend."""
    if config.backend == "pointcloud-gs":
        from sparse_view_plant.gaussians_pointcloud import PointCloudGaussianStage

        return PointCloudGaussianStage.create(config)
    if config.backend == "gs-refine":
        from sparse_view_plant.gaussians_gsrefine import GSRefineStage

        return GSRefineStage.create(config)
    raise ValueError(f"unknown gaussians backend: {config.backend!r}")
