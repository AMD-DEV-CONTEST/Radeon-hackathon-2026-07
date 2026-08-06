"""Frontend-prior point-Gaussian head (lightweight appearance fine-tune).

Geometry (means + local-density scales + confidence) comes from the frontend
point cloud and is frozen. A small MLP maps per-point appearance features to
Gaussian attributes (SH DC color, opacity logit, log scale multiplier):

- fused frontend color,
- bilinear-sampled colors from each conditioning view (projected with the
  cameras that produced the cloud),
- frontend confidence,
- log local-density scale.

The features are frame-agnostic (points and cameras are always used in one
consistent frame), so the head trained on GT-aligned caches transfers to the
frontend frame at inference. Rendering uses gsplat's differentiable rasterizer.
"""

from __future__ import annotations

from pathlib import Path

import torch
from torch import nn
from torch.nn import functional as F

SH_C0 = 0.28209479177387814  # 1 / (2 * sqrt(pi)), matches the export convention
CONDITIONING_VIEWS = 3  # number of frontend input views used as appearance context
COND_FOCAL_SCALE = 1.2  # assumed focal = scale * resolution (inference-compatible)
MIN_SCALE = 1e-5
MAX_SCALE = 1.0


def sh_dc_to_rgb(sh_dc: torch.Tensor) -> torch.Tensor:
    """Inverse of RGB2SH(rgb) = (rgb - 0.5) / C0, clamped to [0, 1]."""
    return (sh_dc * SH_C0 + 0.5).clamp(0.0, 1.0)


def confidence_opacity_logits(
    confidence: torch.Tensor,
    *,
    opacity_min: float = 0.05,
    opacity_max: float = 0.95,
) -> torch.Tensor:
    """pointcloud-gs-style opacity logits from frontend confidence (tensor).

    Mirrors `gaussians_pointcloud._opacity_logits`: quantile-scaled linear
    ramp over the 2nd-98th percentile to sigmoid logits. Using this fixed
    mapping (instead of a learned opacity) keeps the rendered silhouette
    tight and matches the exported PLY at inference.

    `opacity_min` / `opacity_max` set the low and high ends of the ramp; the
    defaults match the original mapping (0.05 .. 0.95). Lowering
    `opacity_max` produces a thinner, more transparent splat field, which
    helps gs-refine variants that re-optimize opacity from this prior.
    """
    lo, hi = torch.quantile(confidence, 0.02), torch.quantile(confidence, 0.98)
    span = (hi - lo).clamp_min(1e-6)
    target = opacity_min + (opacity_max - opacity_min) * (
        (confidence - lo) / span
    ).clamp(0.0, 1.0)
    target = target.clamp(1e-3, 1.0 - 1e-3)
    return torch.log(target / (1.0 - target))


@torch.no_grad()
def sample_view_colors(
    points: torch.Tensor,
    images: torch.Tensor,
    poses: torch.Tensor,
    intrinsics: torch.Tensor,
) -> torch.Tensor:
    """Bilinear-sample conditioning images at projected points.

    points: (M, 3) world coords; images: (V, 3, H, W) in [0, 1];
    poses: (V, 4, 4) camera-to-world (OpenCV CV convention);
    intrinsics: (V, 3, 3) pinhole in the same pixel space as `images`.
    Returns (M, V * 3) sampled colors.
    """
    height, width = images.shape[-2:]
    samples: list[torch.Tensor] = []
    for view_index in range(images.shape[0]):
        rotation = poses[view_index, :3, :3]
        translation = poses[view_index, :3, 3]
        camera = (points - translation) @ rotation  # world -> camera (CV)
        z = camera[:, 2].clamp_min(1e-4)
        matrix = intrinsics[view_index]
        u = matrix[0, 0] * camera[:, 0] / z + matrix[0, 2]
        v = matrix[1, 1] * camera[:, 1] / z + matrix[1, 2]
        grid_x = 2.0 * (u + 0.5) / width - 1.0
        grid_y = 2.0 * (v + 0.5) / height - 1.0
        grid = torch.stack([grid_x, grid_y], dim=-1)[None, :, None, :]  # (1,M,1,2)
        sampled = F.grid_sample(
            images[view_index][None],
            grid,
            mode="bilinear",
            padding_mode="border",
            align_corners=False,
        )[0, :, :, 0].T  # (M, 3)
        samples.append(sampled)
    return torch.cat(samples, dim=-1)


def build_features(
    points: torch.Tensor,
    fused_colors: torch.Tensor,
    confidence: torch.Tensor,
    log_scales: torch.Tensor,
    images: torch.Tensor,
    poses: torch.Tensor,
    intrinsics: torch.Tensor,
) -> torch.Tensor:
    """Concatenate per-point appearance features into one (M, F) tensor."""
    sampled = sample_view_colors(points, images, poses, intrinsics)
    return torch.cat(
        [fused_colors, sampled, confidence[:, None], log_scales[:, None]], dim=-1
    )


class PointGaussianHead(nn.Module):
    """MLP from per-point features to Gaussian attributes."""

    def __init__(
        self, view_count: int = 3, hidden: int = 128, color_only: bool = False
    ) -> None:
        super().__init__()
        self.view_count = view_count
        self.color_only = color_only
        in_features = 3 + 3 * view_count + 2
        self.net = nn.Sequential(
            nn.Linear(in_features, hidden),
            nn.ReLU(),
            nn.Linear(hidden, hidden),
            nn.ReLU(),
            nn.Linear(hidden, 3 if color_only else 5),
        )

    def forward(self, features: torch.Tensor) -> dict[str, torch.Tensor]:
        out = self.net(features)
        result = {"sh_dc": out[:, :3]}
        if not self.color_only:
            result["opacity_logit"] = out[:, 3]
            result["log_scale_mult"] = out[:, 4]
        return result


def load_point_gs_head(
    checkpoint: str | Path, device: str = "cpu", hidden: int = 128
) -> PointGaussianHead:
    """Load a point-GS head, auto-detecting the color-only output size."""
    state = torch.load(checkpoint, map_location=device)
    out_features = int(state["net.4.weight"].shape[0])
    head = PointGaussianHead(
        view_count=CONDITIONING_VIEWS, hidden=hidden, color_only=out_features == 3
    )
    head.load_state_dict(state)
    head.to(device).eval()
    return head


class PointGSModel(nn.Module):
    """Frozen frontend geometry + learned appearance, rendered with gsplat."""

    def __init__(self, head: PointGaussianHead) -> None:
        super().__init__()
        self.head = head

    def forward(
        self,
        points: torch.Tensor,
        fused_colors: torch.Tensor,
        confidence: torch.Tensor,
        log_scales: torch.Tensor,
        cond_images: torch.Tensor,
        cond_poses: torch.Tensor,
        cond_intrinsics: torch.Tensor,
        sup_poses: torch.Tensor,
        sup_intrinsics: torch.Tensor,
        height: int,
        width: int,
    ) -> dict[str, torch.Tensor]:
        features = build_features(
            points,
            fused_colors,
            confidence,
            log_scales,
            cond_images,
            cond_poses,
            cond_intrinsics,
        )
        attributes = self.head(features)
        if self.head.color_only:
            scales = (
                torch.exp(log_scales[:, None]).clamp(MIN_SCALE, MAX_SCALE).repeat(1, 3)
            )
            opacities = torch.sigmoid(confidence_opacity_logits(confidence))
        else:
            scales = torch.exp(
                log_scales[:, None] + attributes["log_scale_mult"][:, None]
            )
            scales = scales.clamp(MIN_SCALE, MAX_SCALE).repeat(1, 3)
            opacities = torch.sigmoid(attributes["opacity_logit"])
        quaternions = torch.zeros(len(points), 4, device=points.device)
        quaternions[:, 0] = 1.0  # identity (w, x, y, z)
        colors = sh_dc_to_rgb(attributes["sh_dc"])
        viewmats = torch.linalg.inv(sup_poses)[None]  # (1, V, 4, 4)
        intrinsics = sup_intrinsics[None]  # (1, V, 3, 3)
        rendered, alpha, _ = _rasterize(
            points[None],
            quaternions[None],
            scales[None],
            opacities[None],
            colors[None],
            viewmats,
            intrinsics,
            height,
            width,
        )
        result = {"rgb": rendered, "alpha": alpha, "sh_dc": attributes["sh_dc"]}
        if not self.head.color_only:
            result["opacity_logit"] = attributes["opacity_logit"]
            result["log_scale_mult"] = attributes["log_scale_mult"]
        return result


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
) -> tuple[torch.Tensor, torch.Tensor, object]:
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
    )
