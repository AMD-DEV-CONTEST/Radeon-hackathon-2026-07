"""Held-out novel-view rendering evaluation (numpy-only).

Renders a reconstruction from held-out GT cameras and compares against the
GT images with PSNR / SSIM / silhouette IoU:

- Point clouds are rendered with a z-buffer splat, mirroring
  few-view-plant's `render_points` so held-out PSNR stays comparable.
- Gaussians (Splatt3R / FreeSplatter) are rendered with EWA splatting:
  project the mean, rotate the covariance into the camera frame, then
  alpha-composite the 2D Gaussians front-to-back. Colors are the DC term of
  the stored SH (Lambertian), so view-dependent effects are not captured.

The pipeline is intentionally CPU-only: evaluation runs offline and must not
drag CUDA renderer builds into the repo. Rendering uses the GT cameras and
intrinsics from `transforms/original/transforms.json` (evaluation-time
metadata only; the inference path never depends on it).
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import correlate
from scipy.spatial.transform import Rotation

SH_C0 = 0.28209479177387814  # 1 / (2 * sqrt(pi)), DC SH basis value
SH_C1 = 0.4886025119029199  # sqrt(3 / (4 * pi)), degree-1 SH basis value


def sh_rest_to_rgb(
    sh_dc: np.ndarray,
    sh_rest: np.ndarray,
    dirs: np.ndarray,
) -> np.ndarray:
    """Decode degree-1 view-dependent RGB from stored SH coefficients.

    `sh_dc` is the raw DC term (M, 3), `sh_rest` the rest coefficients in the
    channel-major (M, 3, 3) layout written by ``write_gaussian_splat_ply``,
    and `dirs` the unnormalized world-space view directions (M, 3). The
    formula matches gsplat's ``spherical_harmonics`` degree-1 kernel: with
    coefficients ``coeffs = [DC, Y11, Y10, Y1-1]`` per channel,
    ``rgb = C0 * DC + C1 * (-Y11 * y + Y10 * z - Y1-1 * x)`` on the
    normalized direction. Returns linear RGB clamped to [0, 1].
    """
    sh_dc = np.asarray(sh_dc, dtype=np.float64)
    sh_rest = np.asarray(sh_rest, dtype=np.float64)
    if sh_dc.shape != (len(sh_dc), 3) or sh_rest.shape != (len(sh_dc), 3, 3):
        raise ValueError(
            f"sh_dc {sh_dc.shape} / sh_rest {sh_rest.shape} must be (M, 3) / "
            "(M, 3, 3) with matching M"
        )
    dirs = np.asarray(dirs, dtype=np.float64)
    if dirs.shape != sh_dc.shape:
        raise ValueError(f"dirs {dirs.shape} must match sh_dc {sh_dc.shape}")
    norm = np.linalg.norm(dirs, axis=1, keepdims=True)
    direction = dirs / np.clip(norm, 1e-12, None)
    # coeffs (M, 4, 3): slot 0 = DC, slots 1..3 = rest (k), channel last.
    coeffs = np.concatenate([sh_dc[:, None, :], sh_rest.transpose(0, 2, 1)], axis=1)
    # gsplat evaluates the SH basis and then shifts the result by 0.5 before
    # clamping (see gsplat.rendering).  Omitting the shift makes a zero-rest
    # degree-1 decode equal ``rgb - 0.5`` instead of the stored DC colour,
    # turning nearly every dark-green plant channel black.
    rgb = (
        0.5
        + SH_C0 * coeffs[:, 0]
        + SH_C1
        * (
            -coeffs[:, 1] * direction[:, 1:2]
            + coeffs[:, 2] * direction[:, 2:3]
            - coeffs[:, 3] * direction[:, 0:1]
        )
    )
    return np.clip(rgb, 0.0, 1.0)


_OPENGL_TO_CV = np.diag([1.0, -1.0, -1.0, 1.0])  # 180° about x in camera frame


def sh_dc_to_rgb(sh_dc: np.ndarray) -> np.ndarray:
    """Decode a stored SH DC term to sRGB, inverse of RGB2SH(rgb) = (rgb - 0.5) / C0.

    Both FreeSplatter (freesplatter/models/model.py) and Splatt3R store the DC
    term in that convention, so the decode adds 0.5 back before clamping.
    """
    values = np.asarray(sh_dc, dtype=np.float64) * SH_C0 + 0.5
    return np.clip(values, 0.0, 1.0)


@dataclass(frozen=True, slots=True)
class RenderResult:
    rgb: np.ndarray  # uint8 (H, W, 3)
    depth: np.ndarray  # float32 (H, W)
    covered: np.ndarray  # bool (H, W)
    visible_points: int
    input_points: int
    alpha: np.ndarray | None = None  # float32 (H, W) coverage map, when known


class RenderingEvaluationError(ValueError):
    pass


def scale_intrinsics(
    intrinsics: np.ndarray,
    *,
    source_hw: tuple[int, int],
    target_hw: tuple[int, int],
) -> np.ndarray:
    """Rescale a pinhole K from source to target resolution."""
    matrix = np.asarray(intrinsics, dtype=np.float64)
    if matrix.shape != (3, 3):
        raise RenderingEvaluationError("intrinsics must have shape [3,3]")
    source_h, source_w = source_hw
    target_h, target_w = target_hw
    if min(source_h, source_w, target_h, target_w) <= 0:
        raise RenderingEvaluationError("image dimensions must be positive")
    scaled = matrix.copy()
    scaled[0] *= target_w / source_w
    scaled[1] *= target_h / source_h
    return scaled


def load_plantdreamer_cameras(
    dataset_root: str | Path, scene: str, view_ids: Sequence[str]
) -> dict[str, tuple[np.ndarray, np.ndarray, tuple[int, int]]]:
    """Per-view (camera_to_world, intrinsics, original_hw) from transforms.json.

    The stored c2w and intrinsics follow the COLMAP / OpenCV convention
    after a 180° frame flip: PlantDreamer's transforms.json stores OpenGL-style
    poses (camera looks along -z, y up), so the camera frame is rotated to the
    OpenCV convention (looks along +z, y down) before returning.
    """
    root = Path(dataset_root) / scene
    transforms_path = root / "transforms" / "original" / "transforms.json"
    if not transforms_path.is_file():
        raise RenderingEvaluationError(f"missing transforms file: {transforms_path}")
    document = json.loads(transforms_path.read_text())
    cameras: dict[str, tuple[np.ndarray, np.ndarray, tuple[int, int]]] = {}
    for frame in document["frames"]:
        view_id = Path(frame["file_path"]).stem
        if view_id not in set(view_ids):
            continue
        c2w = np.asarray(frame["transform_matrix"], dtype=np.float64)
        intrinsics = np.asarray(
            [
                [frame["fl_x"], 0.0, frame["cx"]],
                [0.0, frame["fl_y"], frame["cy"]],
                [0.0, 0.0, 1.0],
            ],
            dtype=np.float64,
        )
        original_hw = (int(frame["h"]), int(frame["w"]))
        cameras[view_id] = (c2w @ _OPENGL_TO_CV, intrinsics, original_hw)
    missing = set(view_ids) - set(cameras)
    if missing:
        raise RenderingEvaluationError(f"missing cameras for views: {sorted(missing)}")
    return cameras


def load_view_target(
    dataset_root: str | Path,
    scene: str,
    view_id: str,
    resolution: int,
) -> tuple[np.ndarray, np.ndarray]:
    """GT RGB (resized bilinear) and binary mask for one held-out view."""
    root = Path(dataset_root) / scene
    rgb_path = root / "images" / "rgb" / f"{view_id}.png"
    mask_path = root / "images" / "mask" / f"{view_id}.png.png"
    if not rgb_path.is_file() or not mask_path.is_file():
        raise RenderingEvaluationError(
            f"held-out view is incomplete: {view_id} ({rgb_path}, {mask_path})"
        )
    rgb = np.asarray(
        Image.open(rgb_path)
        .convert("RGB")
        .resize((resolution, resolution), Image.Resampling.BILINEAR)
    )
    mask = (
        np.asarray(
            Image.open(mask_path)
            .convert("L")
            .resize((resolution, resolution), Image.Resampling.NEAREST)
        )
        >= 128
    )
    return rgb, mask


def select_heldout_views(
    all_cameras: Mapping[str, tuple[np.ndarray, np.ndarray, tuple[int, int]]],
    exclude: Sequence[str],
    count: int,
    *,
    seed: int = 0,
) -> list[str]:
    """Farthest-point sample on camera positions (angular spread)."""
    excluded = set(exclude)
    candidates = [view_id for view_id in all_cameras if view_id not in excluded]
    if count <= 0:
        return []
    if len(candidates) < count:
        raise RenderingEvaluationError(
            f"need {count} held-out views, only {len(candidates)} available"
        )
    positions = np.stack([all_cameras[view_id][0][:3, 3] for view_id in candidates])
    positions /= np.linalg.norm(positions, axis=1, keepdims=True)
    generator = np.random.default_rng(seed)
    chosen = [int(generator.integers(len(candidates)))]
    for _ in range(count - 1):
        distances = np.linalg.norm(positions - positions[chosen[-1]], axis=1)
        distances[chosen] = -np.inf
        chosen.append(int(np.argmax(distances)))
    return [candidates[index] for index in chosen]


def render_points(
    points: np.ndarray,
    colors: np.ndarray,
    camera_to_world_cv: np.ndarray,
    intrinsics: np.ndarray,
    output_hw: tuple[int, int],
    *,
    splat_radius: int = 1,
) -> RenderResult:
    """Z-buffer splat rendering, mirroring few-view-plant's render_points."""
    vertices = np.asarray(points, dtype=np.float64)
    rgb_values = np.asarray(colors, dtype=np.uint8)
    pose = np.asarray(camera_to_world_cv, dtype=np.float64)
    matrix = np.asarray(intrinsics, dtype=np.float64)
    if vertices.ndim != 2 or vertices.shape[1] != 3:
        raise RenderingEvaluationError("points must have shape [N,3]")
    if rgb_values.shape != (len(vertices), 3):
        raise RenderingEvaluationError("colors must have shape [N,3]")
    if pose.shape != (4, 4) or matrix.shape != (3, 3):
        raise RenderingEvaluationError("camera matrices have invalid shapes")
    if splat_radius < 0:
        raise RenderingEvaluationError("splat radius must be non-negative")
    height, width = output_hw
    if height <= 0 or width <= 0:
        raise RenderingEvaluationError("render dimensions must be positive")

    world_to_camera = np.linalg.inv(pose)
    camera = vertices @ world_to_camera[:3, :3].T + world_to_camera[:3, 3]
    finite = np.isfinite(camera).all(axis=1) & (camera[:, 2] > 1e-8)
    point_ids = np.flatnonzero(finite)
    camera = camera[finite]
    projection = camera @ matrix.T
    pixels = np.rint(projection[:, :2] / projection[:, 2:3]).astype(np.int64)

    flat_hits: list[np.ndarray] = []
    depth_hits: list[np.ndarray] = []
    point_hits: list[np.ndarray] = []
    for y_offset in range(-splat_radius, splat_radius + 1):
        for x_offset in range(-splat_radius, splat_radius + 1):
            x = pixels[:, 0] + x_offset
            y = pixels[:, 1] + y_offset
            inside = (x >= 0) & (x < width) & (y >= 0) & (y < height)
            flat_hits.append(y[inside] * width + x[inside])
            depth_hits.append(camera[inside, 2])
            point_hits.append(point_ids[inside])

    rgb = np.zeros((height, width, 3), dtype=np.uint8)
    depth = np.full((height, width), np.inf, dtype=np.float32)
    visible_points = 0
    if flat_hits and any(len(hits) for hits in flat_hits):
        flat = np.concatenate(flat_hits)
        depths = np.concatenate(depth_hits)
        owners = np.concatenate(point_hits)
        order = np.lexsort((depths, flat))
        ordered_flat = flat[order]
        first = np.ones(len(order), dtype=bool)
        first[1:] = ordered_flat[1:] != ordered_flat[:-1]
        chosen_order = order[first]
        chosen_flat = flat[chosen_order]
        chosen_owners = owners[chosen_order]
        depth.reshape(-1)[chosen_flat] = depths[chosen_order]
        rgb.reshape(-1, 3)[chosen_flat] = rgb_values[chosen_owners]
        visible_points = len(np.unique(chosen_owners))
    return RenderResult(
        rgb=rgb,
        depth=depth,
        covered=np.isfinite(depth),
        visible_points=visible_points,
        input_points=len(vertices),
    )


def _quaternion_rotation(quaternions_xyzw: np.ndarray) -> np.ndarray:
    """(M, 4) quaternions (x, y, z, w) to (M, 3, 3) rotations (3DGS convention)."""
    x, y, z, w = np.asarray(quaternions_xyzw, dtype=np.float64).T
    rotations = np.empty((len(x), 3, 3), dtype=np.float64)
    rotations[:, 0, 0] = 1.0 - 2.0 * (y * y + z * z)
    rotations[:, 0, 1] = 2.0 * (x * y - w * z)
    rotations[:, 0, 2] = 2.0 * (x * z + w * y)
    rotations[:, 1, 0] = 2.0 * (x * y + w * z)
    rotations[:, 1, 1] = 1.0 - 2.0 * (x * x + z * z)
    rotations[:, 1, 2] = 2.0 * (y * z - w * x)
    rotations[:, 2, 0] = 2.0 * (x * z - w * y)
    rotations[:, 2, 1] = 2.0 * (y * z + w * x)
    rotations[:, 2, 2] = 1.0 - 2.0 * (x * x + y * y)
    return rotations


def gaussian_covariances(
    scales: np.ndarray, quaternions_xyzw: np.ndarray
) -> np.ndarray:
    """(M, 3) activated scales + (M, 4) quaternions -> (M, 3, 3) covariances."""
    rotations = _quaternion_rotation(quaternions_xyzw)
    return np.einsum("nij,nj,nkj->nik", rotations, scales**2, rotations)


def decode_ply_quaternions_xyzw(
    values: np.ndarray, comments: Sequence[str]
) -> np.ndarray:
    """Decode project PLY rotations, including legacy pre-standard exports."""
    quaternions = np.asarray(values)
    if any(comment.strip() == "quaternion_order wxyz" for comment in comments):
        return quaternions[:, [1, 2, 3, 0]]
    # Files written before the order marker used the project's legacy xyzw
    # layout. Keeping this fallback makes existing experiment outputs readable.
    return quaternions


def transform_gaussians_sim3(
    means: np.ndarray,
    covariances: np.ndarray,
    scales: np.ndarray,
    quaternions_xyzw: np.ndarray,
    matrix: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Apply one Sim3 consistently to Gaussian centers and anisotropy."""
    linear = np.asarray(matrix, dtype=np.float64)[:3, :3]
    scale = float(np.cbrt(np.linalg.det(linear)))
    if not np.isfinite(scale) or scale <= 0.0:
        raise RenderingEvaluationError("Gaussian Sim3 must have positive scale")
    rotation = linear / scale
    transformed_means = (
        np.asarray(means, dtype=np.float64) @ linear.T
        + np.asarray(matrix, dtype=np.float64)[:3, 3]
    )
    transformed_covariances = np.einsum(
        "ij,njk,lk->nil",
        linear,
        np.asarray(covariances, dtype=np.float64),
        linear,
    )
    transformed_scales = np.asarray(scales, dtype=np.float64) * scale
    local_rotations = Rotation.from_quat(quaternions_xyzw).as_matrix()
    transformed_quaternions = Rotation.from_matrix(
        rotation[None] @ local_rotations
    ).as_quat()
    return (
        transformed_means,
        transformed_covariances,
        transformed_scales,
        transformed_quaternions,
    )


def transform_cameras_sim3(
    camera_to_world: np.ndarray, matrix: np.ndarray
) -> np.ndarray:
    """Transform camera poses by Sim3 while keeping rotations orthonormal."""
    cameras = np.asarray(camera_to_world, dtype=np.float64)
    linear = np.asarray(matrix, dtype=np.float64)[:3, :3]
    scale = float(np.cbrt(np.linalg.det(linear)))
    if not np.isfinite(scale) or scale <= 0.0:
        raise RenderingEvaluationError("camera Sim3 must have positive scale")
    rotation = linear / scale
    result = np.tile(np.eye(4, dtype=np.float64), (len(cameras), 1, 1))
    result[:, :3, :3] = rotation @ cameras[:, :3, :3]
    result[:, :3, 3] = cameras[:, :3, 3] @ linear.T + matrix[:3, 3]
    return result


def render_gaussians(
    means: np.ndarray,
    covariances: np.ndarray,
    colors: np.ndarray,
    opacities: np.ndarray,
    camera_to_world_cv: np.ndarray,
    intrinsics: np.ndarray,
    output_hw: tuple[int, int],
    *,
    near: float = 1e-4,
    tile_sigma: float = 3.0,
) -> RenderResult:
    """EWA splat rendering with front-to-back alpha compositing.

    `colors` are linear RGB in [0, 1]; `opacities` are sigmoid-activated in
    [0, 1]. The output RGB is written on a black background.
    """
    values = np.asarray(means, dtype=np.float64)
    covs = np.asarray(covariances, dtype=np.float64)
    rgb_values = np.clip(np.asarray(colors, dtype=np.float64), 0.0, 1.0)
    alphas = np.clip(np.asarray(opacities, dtype=np.float64), 0.0, 1.0)
    pose = np.asarray(camera_to_world_cv, dtype=np.float64)
    matrix = np.asarray(intrinsics, dtype=np.float64)
    if values.ndim != 2 or values.shape[1] != 3:
        raise RenderingEvaluationError("means must have shape [N,3]")
    if covs.shape != (len(values), 3, 3):
        raise RenderingEvaluationError("covariances must have shape [N,3,3]")
    if rgb_values.shape != (len(values), 3) or alphas.shape != (len(values),):
        raise RenderingEvaluationError("colors/opacities shapes must match means")
    if pose.shape != (4, 4) or matrix.shape != (3, 3):
        raise RenderingEvaluationError("camera matrices have invalid shapes")
    height, width = output_hw
    if height <= 0 or width <= 0:
        raise RenderingEvaluationError("render dimensions must be positive")

    world_to_camera = np.linalg.inv(pose)
    rotation = world_to_camera[:3, :3]
    camera = values @ rotation.T + world_to_camera[:3, 3]
    keep = (
        np.isfinite(camera).all(axis=1)
        & np.isfinite(covs).all(axis=(1, 2))
        & (camera[:, 2] > near)
        & (alphas > 0.0)
    )
    if not keep.any():
        return RenderResult(
            rgb=np.zeros((height, width, 3), dtype=np.uint8),
            depth=np.full((height, width), np.inf, dtype=np.float32),
            covered=np.zeros((height, width), dtype=bool),
            visible_points=0,
            input_points=len(values),
        )
    camera = camera[keep]
    covs = covs[keep]
    rgb_values = rgb_values[keep]
    alphas = alphas[keep]

    depth = camera[:, 2]
    fx, fy = matrix[0, 0], matrix[1, 1]
    cx, cy = matrix[0, 2], matrix[1, 2]
    u = fx * camera[:, 0] / depth + cx
    v = fy * camera[:, 1] / depth + cy
    cov_camera = np.einsum("ij,njk,lk->nil", rotation, covs, rotation)
    jacobian = np.zeros((len(camera), 2, 3), dtype=np.float64)
    jacobian[:, 0, 0] = fx / depth
    jacobian[:, 0, 2] = -fx * camera[:, 0] / depth**2
    jacobian[:, 1, 1] = fy / depth
    jacobian[:, 1, 2] = -fy * camera[:, 1] / depth**2
    cov2d = np.einsum("nij,njk,nlk->nil", jacobian, cov_camera, jacobian)
    # Epsilon keeps degenerate (point-like) splats renderable.
    cov2d = cov2d + np.eye(2, dtype=np.float64) * 1e-8
    inv_cov2d = np.linalg.inv(cov2d)
    eigen = np.linalg.eigvalsh(cov2d)
    radius = tile_sigma * np.sqrt(np.maximum(eigen[:, 1], 0.0))
    radius = np.minimum(np.maximum(radius, 0.75), max(height, width))

    rgb = np.zeros((height, width, 3), dtype=np.float64)
    transmittance = np.ones((height, width), dtype=np.float64)
    depth_out = np.full((height, width), np.inf, dtype=np.float64)
    visible_points = 0
    for index in np.argsort(depth):  # back to front
        x0 = max(math.floor(u[index] - radius[index]), 0)
        y0 = max(math.floor(v[index] - radius[index]), 0)
        x1 = min(math.ceil(u[index] + radius[index]), width - 1)
        y1 = min(math.ceil(v[index] + radius[index]), height - 1)
        if x0 > x1 or y0 > y1:
            continue
        ys, xs = np.mgrid[y0 : y1 + 1, x0 : x1 + 1]
        dx = xs - u[index]
        dy = ys - v[index]
        a, b, c = (
            inv_cov2d[index, 0, 0],
            inv_cov2d[index, 0, 1],
            inv_cov2d[index, 1, 1],
        )
        exponent = 0.5 * (a * dx * dx + 2.0 * b * dx * dy + c * dy * dy)
        alpha = alphas[index] * np.exp(-exponent)
        tile = (slice(y0, y1 + 1), slice(x0, x1 + 1))
        rgb[tile] += (
            alpha[..., None] * transmittance[tile][..., None] * rgb_values[index]
        )
        transmittance[tile] *= 1.0 - alpha
        depth_out[tile] = np.minimum(depth_out[tile], depth[index])
        if np.count_nonzero(alpha > 0.01) > 0:
            visible_points += 1

    covered = transmittance < 0.999
    return RenderResult(
        rgb=np.clip(np.rint(rgb * 255.0), 0, 255).astype(np.uint8),
        depth=depth_out.astype(np.float32),
        covered=covered,
        visible_points=visible_points,
        input_points=len(values),
        alpha=(1.0 - transmittance).astype(np.float32),
    )


def render_gaussians_gsplat(
    means: np.ndarray,
    scales: np.ndarray,
    quats: np.ndarray,
    colors: np.ndarray,
    opacities: np.ndarray,
    camera_to_world_cv: np.ndarray,
    intrinsics: np.ndarray,
    output_hw: tuple[int, int],
    *,
    device: str = "cuda",
) -> RenderResult:
    """GPU Gaussian render via gsplat (opt-in; the default eval stays CPU).

    Matches the EWA splatting path on the same splats: PLY quats are stored
    (x, y, z, w) and gsplat expects (w, x, y, z); colors are the decoded SH DC
    term in [0, 1]; viewmats are the inverse of the OpenCV-convention
    camera-to-world matrices, exactly as gs-refine feeds the rasterizer.
    """
    values = np.asarray(means, dtype=np.float64)
    scale_values = np.asarray(scales, dtype=np.float64)
    quat_values = np.asarray(quats, dtype=np.float64)
    rgb_values = np.clip(np.asarray(colors, dtype=np.float64), 0.0, 1.0)
    alphas = np.clip(np.asarray(opacities, dtype=np.float64), 0.0, 1.0)
    pose = np.asarray(camera_to_world_cv, dtype=np.float64)
    matrix = np.asarray(intrinsics, dtype=np.float64)
    height, width = output_hw
    if (
        values.ndim != 2
        or values.shape[1] != 3
        or scale_values.shape != (len(values), 3)
        or quat_values.shape != (len(values), 4)
        or rgb_values.shape != (len(values), 3)
        or alphas.shape != (len(values),)
    ):
        raise RenderingEvaluationError("gaussian arrays have incompatible shapes")
    if pose.shape != (4, 4) or matrix.shape != (3, 3):
        raise RenderingEvaluationError("camera matrices have invalid shapes")
    if len(values) == 0:
        return RenderResult(
            rgb=np.zeros((height, width, 3), dtype=np.uint8),
            depth=np.full((height, width), np.inf, dtype=np.float32),
            covered=np.zeros((height, width), dtype=bool),
            visible_points=0,
            input_points=0,
        )
    try:
        import torch
        from gsplat import rasterization
    except ImportError as exc:  # pragma: no cover - gpu extra only
        raise RenderingEvaluationError(
            "gsplat renderer needs the gpu extra (torch + gsplat)"
        ) from exc
    quats_gsplat = quat_values[:, [3, 0, 1, 2]]  # (x, y, z, w) -> (w, x, y, z)
    quats_gsplat = quats_gsplat / np.linalg.norm(quats_gsplat, axis=1, keepdims=True)
    viewmat = np.linalg.inv(pose)
    with torch.no_grad():
        means_t = torch.from_numpy(values.astype(np.float32))[None].to(device)
        quats_t = torch.from_numpy(quats_gsplat.astype(np.float32))[None].to(device)
        scales_t = torch.from_numpy(scale_values.astype(np.float32))[None].to(device)
        opacities_t = torch.from_numpy(alphas.astype(np.float32))[None].to(device)
        colors_t = torch.from_numpy(rgb_values.astype(np.float32))[None].to(device)
        viewmats_t = torch.from_numpy(viewmat.astype(np.float32))[None, None].to(device)
        intrinsics_t = torch.from_numpy(matrix.astype(np.float32))[None, None].to(
            device
        )
        rgb, alpha, _ = rasterization(
            means_t,
            quats_t,
            scales_t,
            opacities_t,
            colors_t,
            viewmats_t,
            intrinsics_t,
            width,
            height,
            render_mode="RGB",
        )
        rgb_np = rgb[0, 0].cpu().numpy()
        alpha_np = alpha[0, 0, ..., 0].cpu().numpy()
    covered = alpha_np > 1e-3
    return RenderResult(
        rgb=np.clip(np.rint(rgb_np * 255.0), 0, 255).astype(np.uint8),
        depth=np.full((height, width), np.inf, dtype=np.float32),
        covered=covered,
        visible_points=len(values),
        input_points=len(values),
        alpha=alpha_np.astype(np.float32),
    )


def render_gaussians_2dgs_gsplat(
    means: np.ndarray,
    scales: np.ndarray,
    quats: np.ndarray,
    colors: np.ndarray,
    opacities: np.ndarray,
    camera_to_world_cv: np.ndarray,
    intrinsics: np.ndarray,
    output_hw: tuple[int, int],
    *,
    device: str = "cuda",
) -> RenderResult:
    """GPU 2D Gaussian surfel render via gsplat's native rasterizer.

    This deliberately mirrors :func:`render_gaussians_gsplat` so an exported
    flattened 2DGS PLY can be evaluated without approximating its disks as
    thin 3D ellipsoids. PLY stores quaternions as xyzw; gsplat expects wxyz.
    """
    values = np.asarray(means, dtype=np.float64)
    scale_values = np.asarray(scales, dtype=np.float64)
    quat_values = np.asarray(quats, dtype=np.float64)
    rgb_values = np.clip(np.asarray(colors, dtype=np.float64), 0.0, 1.0)
    alphas = np.clip(np.asarray(opacities, dtype=np.float64), 0.0, 1.0)
    pose = np.asarray(camera_to_world_cv, dtype=np.float64)
    matrix = np.asarray(intrinsics, dtype=np.float64)
    height, width = output_hw
    if (
        values.ndim != 2
        or values.shape[1] != 3
        or scale_values.shape != (len(values), 3)
        or quat_values.shape != (len(values), 4)
        or rgb_values.shape != (len(values), 3)
        or alphas.shape != (len(values),)
    ):
        raise RenderingEvaluationError("gaussian arrays have incompatible shapes")
    if pose.shape != (4, 4) or matrix.shape != (3, 3):
        raise RenderingEvaluationError("camera matrices have invalid shapes")
    if len(values) == 0:
        return RenderResult(
            rgb=np.zeros((height, width, 3), dtype=np.uint8),
            depth=np.full((height, width), np.inf, dtype=np.float32),
            covered=np.zeros((height, width), dtype=bool),
            visible_points=0,
            input_points=0,
        )
    try:
        import torch
        from gsplat import rasterization_2dgs
    except ImportError as exc:  # pragma: no cover - gpu extra only
        raise RenderingEvaluationError(
            "2DGS renderer needs the gpu extra (torch + gsplat)"
        ) from exc
    quats_gsplat = quat_values[:, [3, 0, 1, 2]]
    quats_gsplat = quats_gsplat / np.linalg.norm(quats_gsplat, axis=1, keepdims=True)
    viewmat = np.linalg.inv(pose)
    with torch.no_grad():
        means_t = torch.from_numpy(values.astype(np.float32))[None].to(device)
        quats_t = torch.from_numpy(quats_gsplat.astype(np.float32))[None].to(device)
        scales_t = torch.from_numpy(scale_values.astype(np.float32))[None].to(device)
        opacities_t = torch.from_numpy(alphas.astype(np.float32))[None].to(device)
        # RGB+ED concatenates per-camera depths inside gsplat, so colors need
        # the matching [..., C, N, 3] layout even for a single camera.
        colors_t = torch.from_numpy(rgb_values.astype(np.float32))[None, None].to(
            device
        )
        viewmats_t = torch.from_numpy(viewmat.astype(np.float32))[None, None].to(device)
        intrinsics_t = torch.from_numpy(matrix.astype(np.float32))[None, None].to(
            device
        )
        render = rasterization_2dgs(
            means_t,
            quats_t,
            scales_t,
            opacities_t,
            colors_t,
            viewmats_t,
            intrinsics_t,
            width,
            height,
            render_mode="RGB+ED",
            distloss=False,
            packed=False,
        )
        rgb_np = render[0][0, 0, ..., :3].cpu().numpy()
        alpha_np = render[1][0, 0, ..., 0].cpu().numpy()
    covered = alpha_np > 1e-3
    return RenderResult(
        rgb=np.clip(np.rint(rgb_np * 255.0), 0, 255).astype(np.uint8),
        depth=np.full((height, width), np.inf, dtype=np.float32),
        covered=covered,
        visible_points=len(values),
        input_points=len(values),
        alpha=alpha_np.astype(np.float32),
    )


def _gaussian_window(size: int = 11, sigma: float = 1.5) -> np.ndarray:
    coords = np.arange(size, dtype=np.float64) - (size - 1) / 2.0
    window = np.exp(-(coords**2) / (2.0 * sigma**2))
    return np.outer(window, window) / np.sum(window)


def ssim(
    image_a: np.ndarray,
    image_b: np.ndarray,
    *,
    data_range: float = 255.0,
) -> float:
    """Mean SSIM over channels with an 11x11 Gaussian window."""
    a = np.asarray(image_a, dtype=np.float64)
    b = np.asarray(image_b, dtype=np.float64)
    if a.ndim == 2:
        a = a[..., None]
        b = b[..., None]
    if a.shape != b.shape or a.ndim != 3 or a.shape[2] not in (1, 3):
        raise RenderingEvaluationError("SSIM inputs must be matching HxWx[1|3] images")
    c1 = (0.01 * data_range) ** 2
    c2 = (0.03 * data_range) ** 2
    window = _gaussian_window()[..., None]

    def _filter(values: np.ndarray) -> np.ndarray:
        return correlate(values, window, mode="reflect")

    mu_a = _filter(a)
    mu_b = _filter(b)
    sigma_a2 = _filter(a * a) - mu_a * mu_a
    sigma_b2 = _filter(b * b) - mu_b * mu_b
    sigma_ab = _filter(a * b) - mu_a * mu_b
    numerator = (2.0 * mu_a * mu_b + c1) * (2.0 * sigma_ab + c2)
    denominator = (mu_a * mu_a + mu_b * mu_b + c1) * (sigma_a2 + sigma_b2 + c2)
    return float(np.mean(numerator / denominator))


def _mse_psnr(prediction: np.ndarray, target: np.ndarray) -> float:
    mse = float(
        np.mean((prediction.astype(np.float64) - target.astype(np.float64)) ** 2)
    )
    if mse == 0.0:
        return math.inf
    return float(10.0 * math.log10(255.0**2 / mse))


def render_metrics(
    render: RenderResult,
    target_rgb: np.ndarray,
    target_mask: np.ndarray,
    *,
    minimum_covered: int = 1_000,
    background_rgb: np.ndarray | None = None,
) -> dict[str, float | int | str | None]:
    """Aggregate PSNR / SSIM / silhouette metrics for one held-out view.

    PSNR follows few-view-plant and is computed on the intersection of the
    rendered foreground and the GT mask; SSIM is full-frame (standard for
    novel-view synthesis). When ``background_rgb`` is given and the renderer
    exposes an alpha map, the RGB is alpha-composited over that background
    before metric computation (standard 3DGS evaluation practice; the splat
    renderers write on black, which would otherwise dominate full-frame
    metrics against bright studio backgrounds). Composited variants are
    reported under ``*_bg`` keys alongside the black-background legacy values.
    """
    rgb = np.asarray(target_rgb, dtype=np.uint8)
    mask = np.asarray(target_mask, dtype=bool)
    if rgb.shape != (*render.covered.shape, 3) or mask.shape != render.covered.shape:
        raise RenderingEvaluationError("render targets have incompatible shapes")
    if minimum_covered < 0:
        raise RenderingEvaluationError("minimum coverage must be non-negative")
    intersection_mask = render.covered & mask
    intersection = int(np.count_nonzero(intersection_mask))
    union = int(np.count_nonzero(render.covered | mask))
    foreground = int(np.count_nonzero(mask))
    result: dict[str, float | int | str | None] = {
        "silhouette_iou": intersection / union if union else 1.0,
        "foreground_coverage": intersection / max(foreground, 1),
        "visible_point_fraction": render.visible_points / max(render.input_points, 1),
        "covered_foreground_pixels": intersection,
        "ssim": ssim(render.rgb, rgb),
        "psnr_full": _mse_psnr(render.rgb, rgb),
    }
    if background_rgb is not None and render.alpha is not None:
        alpha = np.clip(np.asarray(render.alpha, dtype=np.float64), 0.0, 1.0)
        background = np.asarray(background_rgb, dtype=np.float64)
        composited = render.rgb.astype(np.float64) * alpha[..., None] + background[
            None, None, :
        ] * (1.0 - alpha[..., None])
        composited = np.clip(np.rint(composited), 0, 255).astype(np.uint8)
        result["ssim_bg"] = ssim(composited, rgb)
        result["psnr_full_bg"] = _mse_psnr(composited, rgb)
    else:
        result["ssim_bg"] = result["ssim"]
        result["psnr_full_bg"] = result["psnr_full"]
    if intersection < minimum_covered:
        result["psnr"] = None
        result["psnr_reason"] = "insufficient_rendered_foreground"
        result["psnr_bg"] = None
        return result
    result["psnr"] = _mse_psnr(render.rgb[intersection_mask], rgb[intersection_mask])
    if background_rgb is not None and render.alpha is not None:
        alpha = np.clip(np.asarray(render.alpha, dtype=np.float64), 0.0, 1.0)
        background = np.asarray(background_rgb, dtype=np.float64)
        composited = render.rgb.astype(np.float64) * alpha[..., None] + background[
            None, None, :
        ] * (1.0 - alpha[..., None])
        composited = np.clip(np.rint(composited), 0, 255).astype(np.uint8)
        result["psnr_bg"] = _mse_psnr(
            composited[intersection_mask], rgb[intersection_mask]
        )
    else:
        result["psnr_bg"] = result["psnr"]
    result["psnr_reason"] = ""
    return result
