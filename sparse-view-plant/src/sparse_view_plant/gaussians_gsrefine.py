"""gs-refine backend: per-scene photometric refinement of frontend Gaussians.

Unlike point-gs (frozen frontend geometry + a trained appearance head), this
backend optimizes a standard 3DGS model **directly**, initialized from the
frontend point cloud: means = points, scales = local density, opacity =
confidence logits, colors = fused point RGB (SH DC). All attributes —
including the means — move under mask-weighted photometric loss against the
input views, so gradients can pull the cloud toward the observed surface and
tighten the silhouette.

Deployed path (no GT/calibration): supervision renders the input views with
the frontend-estimated cameras. Intrinsics either use the legacy synthetic
focal (`refine_focal_scale * resolution`) or are recovered from saved
pointmap pixel/3D correspondences (`refine_use_pointmap_intrinsics`).
Per-view foreground masks weight the L1 loss; the mask provider is
configurable (`refine_mask_provider`: mask-free central ellipse + confidence
quantile, or BiRefNet salient foreground) and the confidence->opacity ramp
endpoints are tunable (`refine_opacity_min` / `refine_opacity_max`). A few
hundred steps on Tesla T10 cost ~30-60s, i.e. a lightweight refinement stage
on top of the frontend prior.

Setting `refine_2dgs = true` switches the rasterizer to gsplat's
`rasterization_2dgs` (2DGS surfels, https://arxiv.org/abs/2403.17888): the
third scale is initialized thin (flat disks, `refine_scale_disk`), quaternions
become trainable so disks can align with the observed surface, and the depth
distortion (`refine_dist_weight`) plus optional normal-consistency
(`refine_normal_weight`) regularizers are added to the photometric loss.
Exported PLY normals then carry the surfel disk normals (2DGS convention).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any, cast

import numpy as np
import torch
from PIL import Image
from scipy.spatial import KDTree

from sparse_view_plant.config import GaussianConfig
from sparse_view_plant.evaluation import load_ply_points
from sparse_view_plant.export import (
    _rotation_matrix_to_quaternion,
    write_gaussian_splat_ply,
)
from sparse_view_plant.foreground import foreground_masks, grid_trim_mask
from sparse_view_plant.gaussians_pointcloud import density_scales
from sparse_view_plant.images import InputImage, load_rgb_np
from sparse_view_plant.point_gs import SH_C0, confidence_opacity_logits
from sparse_view_plant.pointcloud import find_prediction_npz
from sparse_view_plant.rendering import gaussian_covariances

MIN_SCALE = 1e-5
MAX_SCALE = 1.0
PER_PARAM_LR = {
    "means": 1.0,
    "log_scales": 5.0,
    "opacity_logit": 10.0,
    "sh_dc": 5.0,
    "sh_rest": 5.0,  # SH degree-1 view-dependent color coefficients
    "quats": 5.0,  # 2DGS variant only: surfel orientations are trained
}  # multipliers on the configured base learning rate


def pointmap_surfel_frames(
    points: np.ndarray,
    patch_hw: tuple[int, int] | np.ndarray,
    camera_to_world: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Estimate surface-aligned 2DGS frames from a frontend world pointmap.

    Returns ``(quaternions_wxyz, pixel_spacing_xy, normals, valid)`` for every
    flattened pointmap cell.  The first two local axes follow the pointmap's
    image-space tangents and the third axis is the surfel disk normal, flipped
    toward its source camera.  This preserves thin leaf orientation instead
    of asking a short 2DGS refinement to recover it from random rotations.
    """
    height, width = int(patch_hw[0]), int(patch_hw[1])
    cameras = np.asarray(camera_to_world, dtype=np.float64)
    if min(height, width) < 2:
        raise ValueError("pointmap surfel initialization needs a grid of at least 2x2")
    values = np.asarray(points, dtype=np.float64)
    view_count = len(cameras)
    if values.shape != (view_count * height * width, 3):
        raise ValueError("pointmap points, patch_hw, and cameras do not agree")
    grid = values.reshape(view_count, height, width, 3)
    tangent_x = np.gradient(grid, axis=2).reshape(-1, 3)
    tangent_y_raw = np.gradient(grid, axis=1).reshape(-1, 3)
    spacing = np.stack(
        [np.linalg.norm(tangent_x, axis=1), np.linalg.norm(tangent_y_raw, axis=1)],
        axis=1,
    )
    normals = np.cross(tangent_x, tangent_y_raw)
    normal_length = np.linalg.norm(normals, axis=1)
    tangent_length = np.linalg.norm(tangent_x, axis=1)
    valid = (
        np.isfinite(values).all(axis=1)
        & np.isfinite(spacing).all(axis=1)
        & np.isfinite(normals).all(axis=1)
        & (normal_length > 1e-10)
        & (tangent_length > 1e-10)
        & (spacing[:, 1] > 1e-10)
    )

    normal_unit = np.zeros_like(normals)
    tangent_x_unit = np.zeros_like(tangent_x)
    normal_unit[valid] = normals[valid] / normal_length[valid, None]
    tangent_x_unit[valid] = tangent_x[valid] / tangent_length[valid, None]
    per_view = height * width
    source_view = np.arange(len(values)) // per_view
    to_camera = cameras[source_view, :3, 3] - values
    flip = valid & (np.sum(normal_unit * to_camera, axis=1) < 0.0)
    normal_unit[flip] *= -1.0
    tangent_y = np.cross(normal_unit, tangent_x_unit)
    tangent_y_length = np.linalg.norm(tangent_y, axis=1)
    valid &= tangent_y_length > 1e-10
    tangent_y[valid] /= tangent_y_length[valid, None]

    rotations = np.broadcast_to(np.eye(3), (len(values), 3, 3)).copy()
    rotations[valid, :, 0] = tangent_x_unit[valid]
    rotations[valid, :, 1] = tangent_y[valid]
    rotations[valid, :, 2] = normal_unit[valid]
    quaternions_xyzw = _rotation_matrix_to_quaternion(rotations)
    quaternions_wxyz = quaternions_xyzw[:, [3, 0, 1, 2]].astype(np.float32)
    return (
        quaternions_wxyz,
        spacing.astype(np.float32),
        normal_unit.astype(np.float32),
        valid,
    )


def pointmap_source_rays(
    points: np.ndarray,
    flat_indices: np.ndarray,
    patch_hw: tuple[int, int] | np.ndarray,
    camera_to_world: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Return source camera origins and unit rays for selected pointmap cells."""
    height, width = int(patch_hw[0]), int(patch_hw[1])
    cameras = np.asarray(camera_to_world, dtype=np.float64)
    values = np.asarray(points, dtype=np.float64)
    indices = np.asarray(flat_indices, dtype=np.int64)
    per_view = height * width
    source_views = indices // per_view
    if values.shape != (len(indices), 3) or np.any(source_views >= len(cameras)):
        raise ValueError("selected points, pointmap cells, and cameras do not agree")
    origins = cameras[source_views, :3, 3]
    directions = values - origins
    lengths = np.linalg.norm(directions, axis=1)
    if not np.isfinite(directions).all() or np.any(lengths <= 1e-10):
        raise ValueError("pointmap source rays contain invalid or zero-length rays")
    directions /= lengths[:, None]
    return origins.astype(np.float32), directions.astype(np.float32)


def _rasterize(
    means: torch.Tensor,
    quats: torch.Tensor,
    scales: torch.Tensor,
    opacities: torch.Tensor,
    colors: torch.Tensor,
    viewmats: torch.Tensor,
    intrinsics: torch.Tensor,
    height: int,
    width: int,
    *,
    sh_degree: int = 0,
) -> tuple[torch.Tensor, torch.Tensor, dict[str, Any]]:
    from gsplat import rasterization

    return rasterization(
        means,
        quats,
        scales,
        opacities,
        colors,
        viewmats,
        intrinsics,
        width,
        height,
        render_mode="RGB",
        sh_degree=sh_degree if sh_degree > 0 else None,
        packed=False,
    )


def _rasterize_2dgs(
    means: torch.Tensor,
    quats: torch.Tensor,
    scales: torch.Tensor,
    opacities: torch.Tensor,
    colors: torch.Tensor,
    viewmats: torch.Tensor,
    intrinsics: torch.Tensor,
    height: int,
    width: int,
    *,
    distloss: bool,
) -> tuple[
    torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor, dict[str, Any]
]:
    """gsplat 2DGS surfel rasterization -> (rgb, alpha, dist, normals, surf_normals, meta).

    Returns the rendered colors/alphas, the depth-distortion map (distloss
    regularizer, zeros when ``distloss`` is False), the surfel normals, and
    the normals derived from the rendered depth (normal-consistency target).
    """
    from gsplat import rasterization_2dgs

    render = rasterization_2dgs(
        means,
        quats,
        scales,
        opacities,
        colors,
        viewmats,
        intrinsics,
        width,
        height,
        # distloss is only defined when depth is rendered (RGB+ED = RGB +
        # expected depth); the extra depth channel is unused downstream.
        render_mode="RGB+ED",
        distloss=distloss,
        packed=False,
    )
    # rasterization_2dgs -> (colors, alphas, normals, normals_from_depth,
    #                         distort, median_depth, meta); with RGB+ED the
    # colors tensor carries an extra depth channel we don't need here.
    return render[0][..., :3], render[1], render[4], render[2], render[3], render[6]


def _ssim_loss(
    pred: torch.Tensor, target: torch.Tensor, window_size: int = 11
) -> torch.Tensor:
    """Differentiable SSIM (3DGS-style 11x11 Gaussian window), mean over all.

    ``pred`` / ``target``: (N, 3, H, W) float images in [0, 1]. Returns the
    mean structural similarity in [0, 1] (1 = identical).
    """
    if window_size % 2 == 0:
        window_size += 1
    radius = window_size // 2
    coords = torch.arange(window_size, device=pred.device, dtype=pred.dtype) - radius
    gauss = torch.exp(-(coords**2) / (2.0 * 1.5**2))
    gauss = gauss / gauss.sum()
    window = (gauss[:, None] * gauss[None, :]).view(1, 1, window_size, window_size)
    window = window.repeat(pred.shape[1], 1, 1, 1)

    def conv(x: torch.Tensor) -> torch.Tensor:
        return torch.nn.functional.conv2d(
            x, window, padding=radius, groups=pred.shape[1]
        )

    mu1, mu2 = conv(pred), conv(target)
    sigma1_sq = conv(pred * pred) - mu1 * mu1
    sigma2_sq = conv(target * target) - mu2 * mu2
    sigma12 = conv(pred * target) - mu1 * mu2
    c1 = 0.01**2
    c2 = 0.03**2
    ssim_map = ((2.0 * mu1 * mu2 + c1) * (2.0 * sigma12 + c2)) / (
        (mu1 * mu1 + mu2 * mu2 + c1) * (sigma1_sq + sigma2_sq + c2)
    )
    return ssim_map.mean()


def _quat_normalize(q: torch.Tensor) -> torch.Tensor:
    return torch.nn.functional.normalize(q, dim=-1)


def _quat_mul(a: torch.Tensor, b: torch.Tensor) -> torch.Tensor:
    """Hamilton product of wxyz quaternions (batched)."""
    aw, ax, ay, az = a.unbind(-1)
    bw, bx, by, bz = b.unbind(-1)
    return torch.stack(
        [
            aw * bw - ax * bx - ay * by - az * bz,
            aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw,
        ],
        dim=-1,
    )


def _quat_rotation_matrix(q: torch.Tensor) -> torch.Tensor:
    """(V, 4) wxyz quaternions -> (V, 3, 3) rotation matrices."""
    w, x, y, z = _quat_normalize(q).unbind(-1)
    return torch.stack(
        [
            1.0 - 2.0 * (y * y + z * z),
            2.0 * (x * y - w * z),
            2.0 * (x * z + w * y),
            2.0 * (x * y + w * z),
            1.0 - 2.0 * (x * x + z * z),
            2.0 * (y * z - w * x),
            2.0 * (x * z - w * y),
            2.0 * (y * z + w * x),
            1.0 - 2.0 * (x * x + y * y),
        ],
        dim=-1,
    ).reshape(-1, 3, 3)


def _optimized_viewmats(
    pose_rot_delta: torch.Tensor,
    pose_trans_delta: torch.Tensor,
    pose_rotation: torch.Tensor,
    pose_translation: torch.Tensor,
) -> torch.Tensor:
    """Compose per-camera SE(3) deltas with the frontend poses -> (1, V, 4, 4)."""
    rotation = _quat_mul(_quat_normalize(pose_rot_delta), pose_rotation)
    translation = pose_translation + pose_trans_delta
    viewmats = torch.eye(4, device=rotation.device)[None].repeat(
        rotation.shape[0], 1, 1
    )
    viewmats[:, :3, :3] = _quat_rotation_matrix(rotation)
    viewmats[:, :3, 3] = translation
    return torch.linalg.inv(viewmats)[None]


def _densify_once(
    config: GaussianConfig,
    params: dict[str, torch.nn.Parameter],
    optimizers: dict[str, torch.optim.Optimizer],
    state: dict[str, torch.Tensor],
    step: int,
    device: str | torch.device,
) -> dict[str, int]:
    """One 3DGS-style clone/split/prune pass using gsplat's densification ops.

    Splats whose accumulated view-space position gradient exceeds
    ``refine_densify_grad2d`` are cloned (max scale <= split_scale) or split
    (larger); splats below ``refine_densify_prune_opa`` opacity are pruned,
    and the total count is capped at ``refine_densify_max_points`` (lowest
    opacity dropped first). The ops replace the Parameter objects in
    ``params`` and rewire the optimizers, so callers must re-read their local
    references from ``params`` afterwards. ``state`` (grad2d/count/
    flat_indices) is kept aligned by the same index math.
    """
    from gsplat.strategy.ops import duplicate, remove, split

    n_before = len(params["means"])
    mean_grad = state["grad2d"] / state["count"].clamp_min(1.0)
    is_grad_high = mean_grad > config.refine_densify_grad2d
    max_scale = torch.exp(params["scales"]).max(dim=-1).values
    is_small = max_scale <= config.refine_densify_split_scale
    dup_mask = is_grad_high & is_small
    n_dup = int(dup_mask.sum().item())
    if n_dup > 0:
        duplicate(params, optimizers, state, mask=dup_mask)
    split_mask = is_grad_high & ~is_small
    n_split = int(split_mask.sum().item())
    if n_split > 0:
        # splats added by cloning must not be split in the same pass
        split_mask = torch.cat(
            [split_mask, torch.zeros(n_dup, dtype=torch.bool, device=device)]
        )
        split(params, optimizers, state, mask=split_mask)
    prune_mask = (
        torch.sigmoid(params["opacities"].flatten()) < config.refine_densify_prune_opa
    )
    n_now = len(params["means"])
    if n_now > config.refine_densify_max_points:
        excess = n_now - config.refine_densify_max_points
        _, lowest = torch.topk(params["opacities"].flatten(), k=excess, largest=False)
        prune_mask[lowest] = True
    n_prune = int(prune_mask.sum().item())
    if n_prune > 0:
        remove(params, optimizers, state, mask=prune_mask)
    if (
        config.refine_densify_reset_every > 0
        and step % config.refine_densify_reset_every == 0
    ):
        # 3DGS-style opacity reset: cap high opacities so over-confident
        # splats can be re-learned instead of saturating the silhouette.
        from gsplat.strategy.ops import reset_opa

        reset_opa(
            params,
            optimizers,
            state,
            value=config.refine_densify_prune_opa * 2.0,
        )
    state["grad2d"].zero_()
    state["count"].zero_()
    return {
        "dup": n_dup,
        "split": n_split,
        "prune": n_prune,
        "before": n_before,
        "after": len(params["means"]),
    }


@dataclass(frozen=True, slots=True)
class GSRefineStage:
    """Per-scene refinement of frontend-initialized Gaussians (no GT needed)."""

    config: GaussianConfig

    @classmethod
    def create(cls, config: GaussianConfig) -> GSRefineStage:
        return cls(config)

    def reconstruct(
        self,
        images: Sequence[InputImage],
        output_dir: str | Path,
        *,
        camera_to_world: np.ndarray | None = None,
    ) -> Path:
        del camera_to_world  # poses come from the saved frontend prediction
        root = Path(output_dir)
        npz_path = find_prediction_npz(root)
        if npz_path is None:
            raise RuntimeError(
                "gs-refine backend needs a *_prediction.npz in the output "
                "directory; run with --stage all (or pointcloud first)"
            )
        payload = np.load(npz_path)
        points = np.asarray(payload["points"], dtype=np.float32)
        raw_points = points
        colors = np.asarray(payload["colors"], dtype=np.float32)
        confidence = np.asarray(payload["confidence"], dtype=np.float32)
        poses = np.asarray(payload["camera_to_world"], dtype=np.float32)
        # Per-view grid layout is only needed by the patch-aligned mask/trim
        # providers (maskfree); merged or externally produced clouds (e.g.
        # cross-frontend fused predictions) may not store it.
        patch_hw = (
            np.asarray(payload["patch_hw"]) if "patch_hw" in payload.files else None
        )
        view_count = poses.shape[0]
        keep_fraction = self.config.refine_keep_fraction
        flat_indices = np.arange(len(points))
        if self.config.refine_init_provider != "none":
            init_mask = (
                grid_trim_mask(
                    self.config.refine_init_provider,
                    images,
                    confidence=np.asarray(payload["confidence"], dtype=np.float32),
                    patch_hw=patch_hw,
                    view_count=view_count,
                    device=self.config.device,
                )
                .reshape(-1)
                .astype(bool)
            )
            if init_mask.shape != (len(points),):
                raise ValueError(
                    f"init trim mask shape {init_mask.shape} does not match "
                    f"{len(points)} points"
                )
            points, colors, confidence, flat_indices = (
                points[init_mask],
                colors[init_mask],
                confidence[init_mask],
                flat_indices[init_mask],
            )
            print(
                f"[gs-refine] init trim ({self.config.refine_init_provider}): "
                f"{points.shape[0]} points"
            )
        if keep_fraction < 1.0:
            threshold = np.quantile(confidence, 1.0 - keep_fraction)
            keep = confidence >= threshold
            points, colors, confidence, flat_indices = (
                points[keep],
                colors[keep],
                confidence[keep],
                flat_indices[keep],
            )
        if len(points) > self.config.refine_max_points:
            indices = np.sort(
                np.random.default_rng(0).choice(
                    len(points), self.config.refine_max_points, replace=False
                )
            )
            points, colors, confidence, flat_indices = (
                points[indices],
                colors[indices],
                confidence[indices],
                flat_indices[indices],
            )

        device = self.config.device
        resolution = self.config.refine_resolution
        mask_started = perf_counter()
        print(
            f"[gs-refine] computing {self.config.refine_mask_provider} "
            f"foreground masks for {view_count} views…"
        )
        masks = foreground_masks(
            self.config.refine_mask_provider,
            images,
            resolution=resolution,
            confidence=np.asarray(payload["confidence"], dtype=np.float32),
            patch_hw=patch_hw,
            view_count=view_count,
            device=device,
        )
        print(
            f"[gs-refine] masks ready ({view_count}×{resolution}², "
            f"{perf_counter() - mask_started:.1f}s)"
        )
        sup_images = []
        for view in images:
            rgb = load_rgb_np(view.path)
            resized = Image.fromarray(rgb).resize(
                (resolution, resolution), Image.Resampling.BILINEAR
            )
            sup_images.append(np.asarray(resized).astype(np.float32) / 255.0)
        sup_images = (
            torch.from_numpy(np.stack(sup_images)).permute(0, 3, 1, 2).to(device)
        )
        sup_masks = torch.from_numpy(masks).to(device)
        if (
            self.config.refine_use_pointmap_intrinsics
            and patch_hw is not None
            and "local_points" in payload.files
        ):
            from sparse_view_plant.plant_fusion import estimate_pointmap_intrinsics

            intrinsics_np = estimate_pointmap_intrinsics(
                np.asarray(payload["local_points"], dtype=np.float32),
                (int(patch_hw[0]), int(patch_hw[1])),
            )
            intrinsics_np[:, 0, :] *= resolution / int(patch_hw[1])
            intrinsics_np[:, 1, :] *= resolution / int(patch_hw[0])
            intrinsics = torch.from_numpy(intrinsics_np).float().to(device)
        else:
            focal = self.config.refine_focal_scale * resolution
            center = resolution / 2.0
            intrinsics = (
                torch.from_numpy(
                    np.tile(
                        np.asarray(
                            [
                                [focal, 0.0, center],
                                [0.0, focal, center],
                                [0.0, 0.0, 1.0],
                            ]
                        ),
                        (view_count, 1, 1),
                    )
                )
                .float()
                .to(device)
            )
        poses_t = torch.from_numpy(np.ascontiguousarray(poses)).to(device)
        viewmats = torch.linalg.inv(poses_t)[None]  # (1, V, 4, 4)
        intrinsics_b = intrinsics[None]  # (1, V, 3, 3)

        surfel_quaternions: np.ndarray | None = None
        surfel_spacing: np.ndarray | None = None
        surfel_valid: np.ndarray | None = None
        if (
            self.config.refine_2dgs
            and self.config.refine_2dgs_surface_init
            and patch_hw is not None
        ):
            surfel_started = perf_counter()
            print("[gs-refine] computing surface-aligned 2DGS frames…")
            all_quaternions, all_spacing, _, all_valid = pointmap_surfel_frames(
                raw_points, patch_hw, poses
            )
            print(
                f"[gs-refine] 2DGS frames ready "
                f"({int(all_valid.sum())}/{len(all_valid)} valid, "
                f"{perf_counter() - surfel_started:.1f}s)"
            )
            surfel_quaternions = all_quaternions[flat_indices]
            surfel_spacing = all_spacing[flat_indices]
            surfel_valid = all_valid[flat_indices]

        source_ray_directions: torch.Tensor | None = None
        if self.config.refine_ray_constrained_means:
            if patch_hw is None:
                raise ValueError(
                    "refine_ray_constrained_means needs a frontend pointmap init"
                )
            if self.config.refine_densify:
                raise ValueError(
                    "refine_ray_constrained_means is incompatible with densification"
                )
            _, ray_directions = pointmap_source_rays(
                points, flat_indices, patch_hw, poses
            )
            source_ray_directions = torch.from_numpy(ray_directions).to(device)

        means_init = torch.from_numpy(np.ascontiguousarray(points)).to(device)
        means = torch.nn.Parameter(means_init.clone())
        density = torch.from_numpy(density_scales(points).astype(np.float32)).to(device)
        scales = density[:, None].repeat(1, 3).clone()
        if self.config.refine_2dgs:
            if surfel_spacing is not None and surfel_valid is not None:
                spacing = torch.from_numpy(surfel_spacing).to(device)
                valid = torch.from_numpy(surfel_valid).to(device)
                # A half-pixel sigma gives adjacent surfels enough overlap
                # without the multi-pixel blur of the old k-NN scale.
                tangent_scales = torch.minimum(0.6 * spacing, density[:, None])
                edge_consistent = (spacing < 4.0 * density[:, None]).all(dim=1)
                valid &= edge_consistent
                scales[valid, :2] = tangent_scales[valid]
            # 2DGS surfels are flat disks: the third scale (the disk-normal
            # direction) starts much smaller than the in-plane scales.
            scales[:, 2] = torch.maximum(
                scales[:, 2] * self.config.refine_scale_disk,
                torch.tensor(MIN_SCALE, device=device),
            )
        log_scales = torch.nn.Parameter(
            torch.log(scales.clamp(MIN_SCALE, MAX_SCALE)).clamp(
                torch.log(torch.tensor(MIN_SCALE, device=device)),
                torch.log(torch.tensor(MAX_SCALE, device=device)),
            )
        )
        init_opacity_logits = confidence_opacity_logits(
            torch.from_numpy(confidence).to(device),
            opacity_min=self.config.refine_opacity_min,
            opacity_max=self.config.refine_opacity_max,
        ).float()
        sh_dc = torch.nn.Parameter(
            ((torch.from_numpy(colors).to(device) - 0.5) / SH_C0).float()
        )
        opacity_logit = torch.nn.Parameter(init_opacity_logits.clone())
        if self.config.refine_2dgs and self.config.refine_sh_degree > 0:
            raise ValueError(
                "refine_sh_degree > 0 is not supported with refine_2dgs: the "
                "2DGS rasterizer broadcasts per-view RGB colors and has no SH path"
            )
        # SH degree-1 rest coefficients, initialized to zero (DC-only colors
        # from the fused point cloud) so view-dependent terms grow only where
        # the photometric loss needs them.
        sh_rest = torch.nn.Parameter(
            torch.zeros(len(means), 3, 3, device=device, dtype=torch.float32)
        )
        if self.config.refine_2dgs:
            if surfel_quaternions is not None and surfel_valid is not None:
                initial = torch.from_numpy(surfel_quaternions).to(device)
                valid = torch.from_numpy(surfel_valid).to(device)
                initial[~valid] = torch.tensor([1.0, 0.0, 0.0, 0.0], device=device)
                quaternions = torch.nn.Parameter(initial)
            else:
                # Legacy ablation/fallback when the frontend has no pointmap
                # layout: let the short optimization discover disk normals.
                quaternions = torch.nn.Parameter(
                    torch.rand(
                        (len(means), 4),
                        device=device,
                        generator=torch.Generator(device=device).manual_seed(0),
                    )
                )
        else:
            # frozen Parameter (no optimizer entry): the densify ops treat
            # every dict entry uniformly, so identity quats stay Parameters
            quaternions = torch.zeros(len(means), 4, device=device)
            quaternions[:, 0] = 1.0  # fixed identity (w, x, y, z)
            quaternions = torch.nn.Parameter(quaternions, requires_grad=False)

        if self.config.refine_freeze_means:
            means.requires_grad_(False)
        if self.config.refine_freeze_opacity:
            opacity_logit.requires_grad_(False)
        base_lr = self.config.refine_lr
        if self.config.refine_optimize_poses:
            from sparse_view_plant.export import _rotation_matrix_to_quaternion

            base_xyzw = _rotation_matrix_to_quaternion(
                poses_t[:, :3, :3].detach().cpu().numpy()
            )  # (V, 4) x y z w
            pose_rotation = (
                torch.from_numpy(
                    np.stack(
                        [
                            base_xyzw[:, 3],
                            base_xyzw[:, 0],
                            base_xyzw[:, 1],
                            base_xyzw[:, 2],
                        ],
                        axis=-1,
                    )
                )
                .float()
                .to(device)
            )  # wxyz constants
            pose_translation = poses_t[:, :3, 3].clone()
            pose_rot_delta = torch.nn.Parameter(
                torch.zeros(view_count, 4, device=device)
            )
            pose_rot_delta.data[:, 0] = 1.0  # identity wxyz
            pose_trans_delta = torch.nn.Parameter(
                torch.zeros(view_count, 3, device=device)
            )
        # Per-parameter optimizers (instead of one AdamW with groups): the
        # densification ops below replace parameter objects and rewire each
        # optimizer's param groups, which needs one optimizer per tensor.
        # Pose deltas are per-camera and live in their own optimizers outside
        # the Gaussian dict so clone/split/prune never index them.
        gauss_params: dict[str, torch.nn.Parameter] = {
            "means": means,
            "scales": log_scales,
            "opacities": opacity_logit,
            "quats": quaternions,
            "sh_dc": sh_dc,
        }
        if self.config.refine_sh_degree > 0:
            gauss_params["sh_rest"] = sh_rest
        _DENSIFY_LR = {
            "means": PER_PARAM_LR["means"],
            "scales": PER_PARAM_LR["log_scales"],
            "opacities": PER_PARAM_LR["opacity_logit"],
            "quats": PER_PARAM_LR["quats"],
            "sh_dc": PER_PARAM_LR["sh_dc"],
            "sh_rest": PER_PARAM_LR["sh_rest"],
        }
        gauss_optimizers: dict[str, torch.optim.AdamW] = {}
        for name, param in gauss_params.items():
            if not param.requires_grad:
                continue
            gauss_optimizers[name] = torch.optim.AdamW(
                [
                    {
                        "params": [param],
                        "lr": base_lr * _DENSIFY_LR[name],
                        "lr_0": base_lr * _DENSIFY_LR[name],
                    }
                ]
            )
        pose_optimizers: list[torch.optim.AdamW] = []
        if self.config.refine_optimize_poses:
            pose_optimizers.extend(
                [
                    torch.optim.AdamW(
                        [
                            {
                                "params": [pose_rot_delta],
                                "lr": self.config.refine_pose_lr,
                                "lr_0": self.config.refine_pose_lr,
                            }
                        ]
                    ),
                    torch.optim.AdamW(
                        [
                            {
                                "params": [pose_trans_delta],
                                "lr": self.config.refine_pose_lr,
                                "lr_0": self.config.refine_pose_lr,
                            }
                        ]
                    ),
                ]
            )
        all_optimizers = [*gauss_optimizers.values(), *pose_optimizers]

        # 3DGS-style adaptive densification: accumulate the view-space mean
        # gradient magnitude of every visible splat, then every
        # refine_densify_every steps clone high-gradient small splats, split
        # high-gradient large ones, and prune low-opacity splats. Uses
        # gsplat's densification ops directly so optimizer state stays in
        # sync; the flat_indices origin-cell bookkeeping rides inside the ops
        # state and is kept aligned by the same index math.
        densify_state: dict[str, torch.Tensor] | None = None
        if (
            self.config.refine_densify
            and not self.config.refine_freeze_means
            and self.config.refine_densify_max_points > 0
        ):
            densify_state = {
                "grad2d": torch.zeros(len(means), device=device),
                "count": torch.zeros(len(means), device=device),
                # float so the ops can cat/index it like the other state;
                # the origin-cell indices are exact ints below 2^24.
                "flat_indices": torch.from_numpy(
                    np.asarray(flat_indices, dtype=np.float32)
                ).to(device),
            }

        scale_floor = self.config.refine_scale_floor
        if scale_floor > 0.0:
            lower_scale = torch.log((scales * scale_floor).clamp(MIN_SCALE, MAX_SCALE))
            lower_scale = lower_scale.to(device)
        else:
            lower_scale = torch.log(torch.tensor(MIN_SCALE, device=device))
        upper_scale = torch.log(
            torch.tensor(min(MAX_SCALE, self.config.refine_scale_max), device=device)
        )
        views_per_step = self.config.refine_views
        rng = np.random.default_rng(0)
        steps = self.config.refine_steps
        trace_rows: list[dict[str, float | int]] = []
        for step in range(steps):
            if views_per_step and views_per_step < view_count:
                selected = np.sort(
                    rng.choice(view_count, views_per_step, replace=False)
                )
            else:
                selected = np.arange(view_count)
            step_viewmats = (
                _optimized_viewmats(
                    pose_rot_delta, pose_trans_delta, pose_rotation, pose_translation
                )
                if self.config.refine_optimize_poses
                else viewmats
            )
            colors = ((sh_dc * SH_C0 + 0.5).clamp(0.0, 1.0))[None]
            if self.config.refine_2dgs:
                rgb, alpha, dist, normals, normals_surf, meta = _rasterize_2dgs(
                    means[None],
                    quaternions[None],
                    torch.exp(log_scales)[None],
                    torch.sigmoid(opacity_logit)[None],
                    # depth rendering requires per-camera colors [.., C, N, D];
                    # broadcast the shared RGB across the selected views.
                    colors[None].expand(1, len(selected), -1, -1),
                    step_viewmats[:, selected],
                    intrinsics_b[:, selected],
                    resolution,
                    resolution,
                    distloss=self.config.refine_dist_weight > 0.0,
                )
            elif self.config.refine_sh_degree > 0:
                # gsplat SH layout: (B, N, 3, K) coefficients with
                # K = (degree + 1)^2; degree 1 stacks DC + 3 rest terms.
                shs = torch.cat([sh_dc[:, None], sh_rest], dim=1)[None]
                rgb, alpha, meta = _rasterize(
                    means[None],
                    quaternions[None],
                    torch.exp(log_scales)[None],
                    torch.sigmoid(opacity_logit)[None],
                    shs,
                    step_viewmats[:, selected],
                    intrinsics_b[:, selected],
                    resolution,
                    resolution,
                    sh_degree=self.config.refine_sh_degree,
                )
            else:
                rgb, alpha, meta = _rasterize(
                    means[None],
                    quaternions[None],
                    torch.exp(log_scales)[None],
                    torch.sigmoid(opacity_logit)[None],
                    colors,
                    step_viewmats[:, selected],
                    intrinsics_b[:, selected],
                    resolution,
                    resolution,
                )
            if densify_state is not None:
                # means2d is a non-leaf; retain its grad for the densify
                # view-space gradient accumulation below.
                meta["means2d"].retain_grad()
            gt = sup_images[selected].permute(0, 2, 3, 1)  # (V,H,W,3)
            mask = sup_masks[selected]  # (V,H,W)
            difference = (rgb[0] - gt).abs()
            foreground = (
                difference * mask[:, :, :, None]
            ).sum() / mask.sum().clamp_min(1.0)
            background = (difference * (1.0 - mask)[:, :, :, None]).sum() / (
                1.0 - mask
            ).sum().clamp_min(1.0)
            alpha_loss = (alpha[0, ..., 0] - mask).abs().mean()
            photo = foreground + self.config.refine_bg_weight * background
            if self.config.refine_ssim_weight > 0.0:
                ssim = _ssim_loss(rgb[0].permute(0, 3, 1, 2), gt.permute(0, 3, 1, 2))
                photo = (
                    1.0 - self.config.refine_ssim_weight
                ) * photo + self.config.refine_ssim_weight * (1.0 - ssim)
            loss = photo + self.config.refine_alpha_weight * alpha_loss
            if self.config.refine_2dgs and self.config.refine_dist_weight > 0.0:
                # 2DGS depth distortion: pushes each ray's depth to concentrate
                # on a single surface, thinning floaters and tightening leaves.
                loss = loss + self.config.refine_dist_weight * dist.mean()
            if self.config.refine_2dgs and self.config.refine_normal_weight > 0.0:
                # 2DGS normal consistency: rendered surfel normals vs normals
                # derived from depth, masked by rendered alpha.
                n_surf = normals_surf[0] * alpha[0].detach()
                normal_error = (1.0 - (normals[0] * n_surf).sum(dim=-1)).mean()
                loss = loss + self.config.refine_normal_weight * normal_error
            if (
                self.config.refine_opacity_reg > 0.0
                and opacity_logit.shape == init_opacity_logits.shape
            ):
                # the shape guard skips the reg once densification has grown
                # the splat count past the frontend-initialized one
                loss = (
                    loss
                    + self.config.refine_opacity_reg
                    * torch.nn.functional.mse_loss(opacity_logit, init_opacity_logits)
                )
            if (
                self.config.refine_means_reg > 0.0
                and not self.config.refine_freeze_means
                and means.shape == means_init.shape
            ):
                loss = (
                    loss
                    + self.config.refine_means_reg
                    * torch.nn.functional.mse_loss(means, means_init)
                )
            for opt in all_optimizers:
                opt.zero_grad()
            loss.backward()
            if densify_state is not None:
                # Accumulate the view-space mean-position gradient magnitude
                # per visible (view, splat) observation, normalized to
                # [-1, 1] screen space like the 3DGS densification. The
                # running mean (grad2d / count) is therefore a per-view
                # average, matching the single-view-per-step semantics the
                # gsplat gradient threshold is calibrated for, no matter how
                # many input views are rendered per step. Counting every
                # visible observation (not only splats visible in ALL views)
                # lets thin structures seen from one or two views grow too,
                # instead of biasing growth to silhouette splats.
                grads = meta["means2d"].grad.clone()
                grads[..., 0] *= resolution / 2.0
                grads[..., 1] *= resolution / 2.0
                visible = (meta["radii"][0] > 0).any(dim=-1)  # (V, N)
                gs_ids = torch.where(visible)[1]
                densify_state["grad2d"].index_add_(
                    0, gs_ids, grads[0][visible].norm(dim=-1)
                )
                densify_state["count"].index_add_(
                    0, gs_ids, torch.ones_like(gs_ids, dtype=torch.float32)
                )
                if (
                    step >= self.config.refine_densify_from
                    and step < self.config.refine_densify_until
                    and step % self.config.refine_densify_every == 0
                ):
                    result = _densify_once(
                        self.config,
                        gauss_params,
                        # dict invariance: widen AdamW -> Optimizer for the
                        # gsplat ops signature
                        cast(dict[str, torch.optim.Optimizer], gauss_optimizers),
                        densify_state,
                        step,
                        device,
                    )
                    # The ops replaced the Parameter objects in gauss_params;
                    # re-sync the local references and the origin-cell indices.
                    means = gauss_params["means"]
                    log_scales = gauss_params["scales"]
                    opacity_logit = gauss_params["opacities"]
                    quaternions = gauss_params["quats"]
                    sh_dc = gauss_params["sh_dc"]
                    if self.config.refine_sh_degree > 0:
                        sh_rest = gauss_params["sh_rest"]
                    flat_indices = densify_state["flat_indices"].long().cpu().numpy()
                    if len(means) != len(flat_indices):
                        raise RuntimeError(
                            "densify desynced flat_indices: "
                            f"{len(means)} splats vs {len(flat_indices)} cells"
                        )
                    print(
                        f"[gs-refine] densify step {step + 1}: "
                        f"dup {result['dup']} split {result['split']} "
                        f"prune {result['prune']} "
                        f"({result['before']} -> {result['after']} splats)"
                    )
            if self.config.refine_lr_anneal:
                scale = 1.0 - step / steps
                for opt in all_optimizers:
                    for group in opt.param_groups:
                        group["lr"] = group["lr_0"] * scale
            for opt in all_optimizers:
                opt.step()
            with torch.no_grad():
                if source_ray_directions is not None:
                    # Photometric gradients may correct VGGT depth, but may
                    # not break the originating pixel-to-surface evidence by
                    # drifting sideways into a neighboring leaf/background.
                    displacement = means - means_init
                    ray_depth_delta = (displacement * source_ray_directions).sum(
                        dim=-1, keepdim=True
                    )
                    means.copy_(means_init + ray_depth_delta * source_ray_directions)
                log_scales.clamp_(lower_scale, upper_scale)
                opacity_logit.clamp_(-15.0, 15.0)
            if step % 10 == 0 or step == steps - 1:
                print(
                    f"[gs-refine] step {step + 1}/{steps} loss={loss.item():.4f} "
                    f"fg={foreground.item():.4f} bg={background.item():.4f} "
                    f"alpha={alpha_loss.item():.4f}"
                )
                with torch.no_grad():
                    trace_rows.append(
                        {
                            "step": int(step) + 1,
                            "loss": float(loss.item()),
                            "foreground": float(foreground.item()),
                            "background": float(background.item()),
                            "alpha": float(alpha_loss.item()),
                            "splats": len(means),
                            "mean_opacity": float(
                                torch.sigmoid(opacity_logit).mean().item()
                            ),
                            "mean_scale": float(torch.exp(log_scales).mean().item()),
                        }
                    )

        # Persistent per-step loss/opacity trace so crash detection (or a
        # human) can inspect the refinement trajectory without re-running.
        (root / "refine_trace.json").write_text(
            json.dumps(
                {
                    "config": {
                        "steps": steps,
                        "resolution": resolution,
                        "views_per_step": views_per_step or view_count,
                        "mask_provider": self.config.refine_mask_provider,
                        "bg_weight": self.config.refine_bg_weight,
                        "alpha_weight": self.config.refine_alpha_weight,
                        "2dgs": self.config.refine_2dgs,
                        "ray_constrained_means": self.config.refine_ray_constrained_means,
                        "pointmap_intrinsics": self.config.refine_use_pointmap_intrinsics,
                        "densify": self.config.refine_densify,
                    },
                    "rows": trace_rows,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        export_trim = self.config.refine_export_trim
        if export_trim == "birefnet-proj":
            # Grid-free export trim for clouds without a per-view pointmap
            # layout (e.g. cross-frontend fused predictions: no patch_hw /
            # flat_indices). Projects each splat's CURRENT mean into every
            # view and keeps it when it lands inside the BiRefNet foreground
            # mask in at least one view.
            from sparse_view_plant.foreground import birefnet_masks

            proj_res = 256
            proj_masks = birefnet_masks(images, device=device, resolution=proj_res)
            grid_h = grid_w = proj_res
            focal = self.config.refine_focal_scale * grid_h
            center = grid_h / 2.0
            rot = viewmats[0, :, :3, :3]  # (V, 3, 3) world -> camera
            trans = viewmats[0, :, :3, 3]  # (V, 3)
            cam = torch.einsum("vij,nj->vni", rot, means) + trans[:, None, :]
            depth = cam[..., 2].detach().cpu().numpy()
            u = focal * cam[..., 0].detach().cpu().numpy() / depth + center
            v = focal * cam[..., 1].detach().cpu().numpy() / depth + center
            in_front = depth > 0
            in_bounds = (
                (u >= 0.0)
                & (u < grid_w - 1e-3)
                & (v >= 0.0)
                & (v < grid_h - 1e-3)
                & in_front
            )
            uu = np.clip(np.floor(u), 0, grid_w - 1).astype(np.int64)
            vv = np.clip(np.floor(v), 0, grid_h - 1).astype(np.int64)
            sample = proj_masks[np.arange(view_count)[:, None], vv, uu]
            keep_splats = np.any(in_bounds & (sample > 0.5), axis=0)
            print(
                f"[gs-refine] export trim ({export_trim}): keeping "
                f"{keep_splats.mean():.1%} of {len(means)} splats"
            )
        elif export_trim != "none":
            grid_trim = grid_trim_mask(
                export_trim,
                images,
                confidence=np.asarray(payload["confidence"], dtype=np.float32),
                patch_hw=patch_hw,
                view_count=view_count,
                device=device,
            )
            if self.config.refine_export_trim_position:
                # Intersect the origin-cell trim with a position check:
                # project each splat's CURRENT mean into every view and keep
                # it when it lands inside the foreground mask in at least one
                # view. The origin-cell mask alone keeps splats that started
                # foreground even after they wander out (documented root
                # cause of the fat silhouette); the position check cuts that
                # leakage while still excluding background-init splats that
                # drifted onto the silhouette (position-only kept 68% and
                # hurt geometry/rendering, 2026-08-05).
                grid_h, grid_w = grid_trim.shape[-2:]
                focal = self.config.refine_focal_scale * grid_h
                center = grid_h / 2.0
                rot = viewmats[0, :, :3, :3]  # (V, 3, 3) world -> camera
                trans = viewmats[0, :, :3, 3]  # (V, 3)
                cam = torch.einsum("vij,nj->vni", rot, means) + trans[:, None, :]
                depth = cam[..., 2].detach().cpu().numpy()
                u = focal * cam[..., 0].detach().cpu().numpy() / depth + center
                v = focal * cam[..., 1].detach().cpu().numpy() / depth + center
                in_front = depth > 0
                in_bounds = (
                    (u >= 0.0)
                    & (u < grid_w - 1e-3)
                    & (v >= 0.0)
                    & (v < grid_h - 1e-3)
                    & in_front
                )
                uu = np.clip(np.floor(u), 0, grid_w - 1).astype(np.int64)
                vv = np.clip(np.floor(v), 0, grid_h - 1).astype(np.int64)
                sample = grid_trim[np.arange(view_count)[:, None], vv, uu]
                position_keep = np.any(in_bounds & (sample > 0.5), axis=0)
                origin_keep = grid_trim.reshape(-1)[flat_indices] > 0
                keep_splats = origin_keep & position_keep
                print(
                    f"[gs-refine] export trim ({export_trim}, origin∩position): "
                    f"keeping {keep_splats.mean():.1%} of {len(means)} splats "
                    f"(origin {origin_keep.mean():.1%} ∩ position "
                    f"{position_keep.mean():.1%})"
                )
            else:
                grid_trim = grid_trim.reshape(-1)
                keep_splats = grid_trim[flat_indices] > 0
                print(
                    f"[gs-refine] export trim ({export_trim}): keeping "
                    f"{keep_splats.mean():.1%} of {len(flat_indices)} splats"
                )
        else:
            keep_splats = None
        if self.config.refine_export_density_trim:
            # 3D density trim: drop surviving splats whose mean is far from
            # the deployed frontend foreground cloud (which carries the strong
            # geometry). Applied after the 2D grid trim; validated +IoU/+PSNR
            # on bean/kale/mint at 0.02-0.03 world units on the already-trimmed
            # export. The reference cloud is the stage-1 pointcloud.ply, or
            # the raw npz points with the top-confidence fraction when the PLY
            # is missing.
            density_path = root / "pointcloud.ply"
            if density_path.is_file():
                reference = np.asarray(load_ply_points(density_path), dtype=np.float32)
            else:
                raw_points = np.asarray(payload["points"], dtype=np.float32)
                raw_conf = np.asarray(payload["confidence"], dtype=np.float32)
                cutoff = np.quantile(raw_conf, 1.0 - 0.3)
                reference = raw_points[raw_conf >= cutoff]
            all_means = means.detach().cpu().numpy().astype(np.float32)
            distances, _ = KDTree(reference).query(all_means, k=1)
            sigma = self.config.refine_export_density_sigma
            if sigma > 0.0:
                # Smooth density falloff: keep every splat but attenuate its
                # opacity as exp(-d^2 / 2 sigma^2) in the distance to the
                # deployed cloud. Hard binary trimming removes floaters but
                # also punches holes in the foreground; the smooth variant
                # fades far splats (the eval opacity>0.05 filter then drops
                # them) while preserving near-cloud coverage.
                p = 1.0 / (1.0 + np.exp(-opacity_logit.detach().cpu().numpy()))
                falloff = np.exp(-0.5 * (distances / float(sigma)) ** 2)
                p_new = np.clip(p * falloff, 1e-7, 1.0 - 1e-7)
                new_logits = np.log(p_new / (1.0 - p_new)).astype(np.float32)
                opacity_logit.data = torch.from_numpy(new_logits).to(
                    opacity_logit.device
                )
                print(
                    f"[gs-refine] export trim (density, ref {len(reference)} pts, "
                    f"sigma {sigma}): mean falloff {falloff.mean():.2f}, "
                    f"{np.mean(p_new < 0.05):.1%} of splats below the "
                    "eval opacity filter"
                )
            else:
                density_keep = distances <= float(
                    self.config.refine_export_density_threshold
                )
                keep_splats = (
                    keep_splats & density_keep
                    if keep_splats is not None
                    else density_keep
                )
                print(
                    f"[gs-refine] export trim (density, ref {len(reference)} pts, "
                    f"thr {self.config.refine_export_density_threshold}): keeping "
                    f"{keep_splats.mean():.1%} of {len(all_means)} splats"
                )

        opacity_threshold = self.config.refine_export_opacity_threshold
        if opacity_threshold > 0.0:
            if not 0.0 < opacity_threshold < 1.0:
                raise ValueError("refine_export_opacity_threshold must be in (0, 1)")
            opacity_keep = (
                torch.sigmoid(opacity_logit).detach().cpu().numpy() >= opacity_threshold
            )
            keep_splats = (
                keep_splats & opacity_keep if keep_splats is not None else opacity_keep
            )
            print(
                f"[gs-refine] export opacity >= {opacity_threshold}: keeping "
                f"{keep_splats.mean():.1%} of {len(opacity_keep)} splats"
            )

        with torch.no_grad():
            export_scales = torch.exp(log_scales).clamp(MIN_SCALE, MAX_SCALE)
            if self.config.refine_2dgs:
                export_scales_np = export_scales.cpu().numpy().astype(np.float32)
                # gsplat quats are (w, x, y, z); covariances expect (x, y, z, w).
                quats_wxyz = (
                    torch.nn.functional.normalize(quaternions, dim=-1).cpu().numpy()
                )
                quats_np = quats_wxyz[:, [1, 2, 3, 0]].astype(np.float32)
            else:
                # isotropic scales are stored as (N, 3) equal columns
                export_scales_np = export_scales.cpu().numpy().astype(np.float32)
                quats_np = np.tile(
                    np.asarray([0.0, 0.0, 0.0, 1.0]), (len(export_scales_np), 1)
                )
            if keep_splats is not None:
                export_scales_np = export_scales_np[keep_splats]
                quats_np = quats_np[keep_splats]
            covariances = gaussian_covariances(export_scales_np, quats_np)
            if self.config.refine_2dgs:
                # 2DGS PLY convention: normals = surfel disk normals, i.e. the
                # third column of each splat's world rotation.
                x, y, z, w = quats_np.T
                normals = np.stack(
                    [
                        2.0 * (x * z + w * y),
                        2.0 * (y * z - w * x),
                        1.0 - 2.0 * (x * x + y * y),
                    ],
                    axis=-1,
                ).astype(np.float32)
            else:
                normals = None
            opacity_np = (
                opacity_logit.detach().cpu().numpy()[:, None].astype(np.float32)
            )
            sh_dc_np = sh_dc.detach().cpu().numpy().astype(np.float32)
            means_np = means.detach().cpu().numpy().astype(np.float32)
            sh_rest_np = None
            if self.config.refine_sh_degree > 0:
                sh_rest_np = sh_rest.detach().cpu().numpy().astype(np.float32)
            if keep_splats is not None:
                opacity_np = opacity_np[keep_splats]
                sh_dc_np = sh_dc_np[keep_splats]
                means_np = means_np[keep_splats]
                if sh_rest_np is not None:
                    sh_rest_np = sh_rest_np[keep_splats]
        ply_path = root / "gaussians.ply"
        write_gaussian_splat_ply(
            ply_path,
            means=means_np,
            covariances=covariances,
            sh_dc=sh_dc_np,
            opacities=opacity_np,
            normals=normals,
            sh_rest=sh_rest_np,
        )
        return ply_path
