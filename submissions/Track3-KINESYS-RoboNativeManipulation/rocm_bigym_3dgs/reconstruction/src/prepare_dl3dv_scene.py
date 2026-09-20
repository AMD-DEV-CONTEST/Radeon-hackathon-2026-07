#!/usr/bin/env python3
"""Safely extract a DL3DV scene and normalize it for gsplat's COLMAP parser."""

from __future__ import annotations

import argparse
import json
import math
import shutil
import struct
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.spatial.transform import Rotation


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    return parser.parse_args()


def safe_extract(archive: Path, destination: Path) -> None:
    root = destination.resolve()
    root.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as source:
        bad = source.testzip()
        if bad:
            raise RuntimeError(f"ZIP CRC validation failed: {bad}")
        for member in source.infolist():
            target = (root / member.filename).resolve()
            if root != target and root not in target.parents:
                raise RuntimeError(f"unsafe ZIP member: {member.filename!r}")
            source.extract(member, root)


def find_scene_root(root: Path) -> Path:
    candidates: list[Path] = []
    for directory in [root, *sorted(path for path in root.rglob("*") if path.is_dir())]:
        if (directory / "transforms.json").is_file():
            candidates.append(directory)
        if (directory / "sparse").is_dir() and any(
            child.is_dir() or child.suffix in {".bin", ".txt"}
            for child in (directory / "sparse").iterdir()
        ):
            candidates.append(directory)
    unique = sorted(set(candidates), key=lambda path: (len(path.parts), str(path)))
    if not unique:
        raise RuntimeError("no Nerfstudio transforms.json or COLMAP sparse model found")
    return unique[0]


def find_image_root(scene: Path, transforms: dict | None = None) -> Path:
    if transforms:
        for frame in transforms.get("frames", []):
            file_path = str(frame.get("file_path", "")).lstrip("./")
            if file_path:
                candidate = scene / Path(file_path).parts[0]
                if candidate.is_dir():
                    return candidate
    candidates = [
        directory
        for directory in scene.iterdir()
        if directory.is_dir()
        and directory.name.lower().startswith(("image", "rgb", "frame"))
    ]
    for candidate in sorted(candidates):
        if any(
            path.suffix.lower() in {".jpg", ".jpeg", ".png"}
            for path in candidate.rglob("*")
        ):
            return candidate
    raise RuntimeError("cannot locate source image directory")


def has_colmap_model(scene: Path) -> tuple[bool, Path | None]:
    for candidate in (scene / "sparse" / "0", scene / "sparse"):
        if not candidate.is_dir():
            continue
        cameras = (candidate / "cameras.bin").is_file() or (
            candidate / "cameras.txt"
        ).is_file()
        images = (candidate / "images.bin").is_file() or (
            candidate / "images.txt"
        ).is_file()
        points = (candidate / "points3D.bin").is_file() or (
            candidate / "points3D.txt"
        ).is_file()
        if cameras and images and points:
            return True, candidate
    return False, None


def quote_name(name: str) -> str:
    if "\n" in name or "\r" in name:
        raise RuntimeError(f"unsafe image name: {name!r}")
    return name


def parse_ply_points(path: Path) -> tuple[np.ndarray, np.ndarray]:
    try:
        from plyfile import PlyData
    except ImportError as exc:
        raise RuntimeError("plyfile is required to convert Nerfstudio sparse points") from exc
    data = PlyData.read(str(path))["vertex"].data
    names = set(data.dtype.names or ())
    points = np.column_stack([data["x"], data["y"], data["z"]]).astype(np.float64)
    if {"red", "green", "blue"}.issubset(names):
        colors = np.column_stack([data["red"], data["green"], data["blue"]]).astype(
            np.uint8
        )
    else:
        colors = np.full((len(points), 3), 180, dtype=np.uint8)
    finite = np.isfinite(points).all(axis=1)
    return points[finite], colors[finite]


def resolve_frame_path(
    scene: Path,
    frame: dict,
    image_root: Path | None = None,
) -> Path:
    raw_path = Path(str(frame["file_path"]).lstrip("./"))
    candidates = [scene / raw_path]
    if image_root is not None:
        relative_image_path = (
            Path(*raw_path.parts[1:]) if len(raw_path.parts) > 1 else raw_path
        )
        candidates.extend(
            [
                image_root / relative_image_path,
                image_root / raw_path.name,
            ]
        )
    actual = next((candidate for candidate in candidates if candidate.is_file()), None)
    if actual is None:
        for candidate_base in candidates:
            for suffix in (".jpg", ".jpeg", ".png"):
                candidate = candidate_base.with_suffix(suffix)
                if candidate.is_file():
                    actual = candidate
                    break
            if actual is not None:
                break
    if actual is None:
        raise RuntimeError(f"missing image referenced by transforms: {raw_path}")
    return actual


def frame_projection(
    frame: dict,
    intrinsic: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    c2w = np.asarray(frame["transform_matrix"], dtype=np.float64)
    if c2w.shape != (4, 4) or not np.isfinite(c2w).all():
        raise RuntimeError("invalid camera transform")
    c2w_cv = c2w.copy()
    c2w_cv[:3, 1:3] *= -1.0
    w2c = np.linalg.inv(c2w_cv)
    return intrinsic @ w2c[:3, :], c2w_cv[:3, 3]


def triangulate_sparse_points(
    scene: Path,
    image_root: Path,
    transforms: dict,
    frames: list[dict],
    width: int,
    height: int,
    fx: float,
    fy: float,
    cx: float,
    cy: float,
) -> tuple[np.ndarray, np.ndarray, dict[str, object]]:
    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError(
            "opencv-python-headless is required to triangulate DL3DV sparse points"
        ) from exc

    max_dimension = 1280
    image_scale = min(1.0, max_dimension / max(width, height))
    scaled_width = max(1, round(width * image_scale))
    scaled_height = max(1, round(height * image_scale))
    intrinsic = np.array(
        [
            [fx * image_scale, 0.0, cx * image_scale],
            [0.0, fy * image_scale, cy * image_scale],
            [0.0, 0.0, 1.0],
        ],
        dtype=np.float64,
    )
    distortion = np.array(
        [
            float(transforms.get("k1", 0.0) or 0.0),
            float(transforms.get("k2", 0.0) or 0.0),
            float(transforms.get("p1", 0.0) or 0.0),
            float(transforms.get("p2", 0.0) or 0.0),
        ],
        dtype=np.float64,
    )
    sift = cv2.SIFT_create(
        nfeatures=3000,
        contrastThreshold=0.02,
        edgeThreshold=12,
    )
    matcher = cv2.BFMatcher(cv2.NORM_L2)
    frame_offset = 4
    pair_stride = 2
    point_batches: list[np.ndarray] = []
    color_batches: list[np.ndarray] = []
    pairs_attempted = 0
    pairs_used = 0
    matches_after_ratio = 0
    points_before_voxel = 0

    def load_image(frame: dict) -> tuple[np.ndarray, np.ndarray]:
        path = resolve_frame_path(scene, frame, image_root)
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if image is None:
            raise RuntimeError(f"OpenCV cannot read source image: {path}")
        if image.shape[1] != scaled_width or image.shape[0] != scaled_height:
            image = cv2.resize(
                image,
                (scaled_width, scaled_height),
                interpolation=cv2.INTER_AREA,
            )
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        return image, gray

    for first_index in range(0, len(frames) - frame_offset, pair_stride):
        second_index = first_index + frame_offset
        pairs_attempted += 1
        first_color, first_gray = load_image(frames[first_index])
        _, second_gray = load_image(frames[second_index])
        keypoints_a, descriptors_a = sift.detectAndCompute(first_gray, None)
        keypoints_b, descriptors_b = sift.detectAndCompute(second_gray, None)
        if descriptors_a is None or descriptors_b is None:
            continue
        nearest = matcher.knnMatch(descriptors_a, descriptors_b, k=2)
        good = [
            match
            for match, alternate in nearest
            if match.distance < 0.72 * alternate.distance
        ]
        if len(good) < 30:
            continue
        matches_after_ratio += len(good)
        points_a = np.asarray(
            [keypoints_a[match.queryIdx].pt for match in good],
            dtype=np.float64,
        )
        points_b = np.asarray(
            [keypoints_b[match.trainIdx].pt for match in good],
            dtype=np.float64,
        )
        _, inliers = cv2.findFundamentalMat(
            points_a,
            points_b,
            cv2.FM_RANSAC,
            1.5,
            0.999,
        )
        if inliers is None:
            continue
        inlier_mask = inliers.reshape(-1).astype(bool)
        points_a = points_a[inlier_mask]
        points_b = points_b[inlier_mask]
        if len(points_a) < 25:
            continue
        points_a_ideal = cv2.undistortPoints(
            points_a.reshape(-1, 1, 2),
            intrinsic,
            distortion,
            P=intrinsic,
        ).reshape(-1, 2)
        points_b_ideal = cv2.undistortPoints(
            points_b.reshape(-1, 1, 2),
            intrinsic,
            distortion,
            P=intrinsic,
        ).reshape(-1, 2)
        projection_a, center_a = frame_projection(frames[first_index], intrinsic)
        projection_b, center_b = frame_projection(frames[second_index], intrinsic)
        homogeneous = cv2.triangulatePoints(
            projection_a,
            projection_b,
            points_a_ideal.T,
            points_b_ideal.T,
        )
        valid_w = np.abs(homogeneous[3]) > 1e-10
        world = np.full((len(points_a), 3), np.nan, dtype=np.float64)
        world[valid_w] = (
            homogeneous[:3, valid_w] / homogeneous[3:4, valid_w]
        ).T

        def project(projection: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
            projected_h = (
                projection
                @ np.column_stack([world, np.ones(len(world), dtype=np.float64)]).T
            ).T
            depth = projected_h[:, 2]
            pixels = projected_h[:, :2] / projected_h[:, 2:3]
            return pixels, depth

        reprojection_a, depth_a = project(projection_a)
        reprojection_b, depth_b = project(projection_b)
        error_a = np.linalg.norm(reprojection_a - points_a_ideal, axis=1)
        error_b = np.linalg.norm(reprojection_b - points_b_ideal, axis=1)
        ray_a = world - center_a
        ray_b = world - center_b
        ray_a_norm = np.linalg.norm(ray_a, axis=1)
        ray_b_norm = np.linalg.norm(ray_b, axis=1)
        cosine = np.sum(ray_a * ray_b, axis=1) / np.maximum(
            ray_a_norm * ray_b_norm,
            1e-12,
        )
        angle = np.arccos(np.clip(cosine, -1.0, 1.0))
        valid = (
            np.isfinite(world).all(axis=1)
            & np.isfinite(reprojection_a).all(axis=1)
            & np.isfinite(reprojection_b).all(axis=1)
            & (depth_a > 0.05)
            & (depth_b > 0.05)
            & (depth_a < 30.0)
            & (depth_b < 30.0)
            & (error_a < 2.5)
            & (error_b < 2.5)
            & (angle > math.radians(0.75))
        )
        if valid.sum() < 20:
            continue
        pairs_used += 1
        accepted_points = world[valid]
        accepted_pixels = np.rint(points_a[valid]).astype(np.int64)
        accepted_pixels[:, 0] = np.clip(
            accepted_pixels[:, 0], 0, first_color.shape[1] - 1
        )
        accepted_pixels[:, 1] = np.clip(
            accepted_pixels[:, 1], 0, first_color.shape[0] - 1
        )
        accepted_colors = first_color[
            accepted_pixels[:, 1],
            accepted_pixels[:, 0],
            ::-1,
        ]
        point_batches.append(accepted_points)
        color_batches.append(accepted_colors)
        points_before_voxel += len(accepted_points)

    if not point_batches:
        raise RuntimeError("known-pose feature triangulation produced no sparse points")
    points = np.concatenate(point_batches, axis=0)
    colors = np.concatenate(color_batches, axis=0).astype(np.uint8)
    voxel_size = 0.02
    voxel_keys = np.floor(points / voxel_size).astype(np.int64)
    _, unique_indices = np.unique(voxel_keys, axis=0, return_index=True)
    unique_indices.sort()
    points = points[unique_indices]
    colors = colors[unique_indices]
    maximum_points = 500_000
    if len(points) > maximum_points:
        keep = np.linspace(0, len(points) - 1, maximum_points, dtype=np.int64)
        points = points[keep]
        colors = colors[keep]
    if len(points) < 10_000:
        raise RuntimeError(
            "known-pose feature triangulation produced too few points: "
            f"{len(points)}"
        )
    report = {
        "method": "known_pose_sift_triangulation",
        "pairs_attempted": pairs_attempted,
        "pairs_used": pairs_used,
        "matches_after_ratio": matches_after_ratio,
        "points_before_voxel": points_before_voxel,
        "points_after_voxel": len(points),
        "voxel_size": voxel_size,
        "maximum_points": maximum_points,
        "working_resolution": [scaled_width, scaled_height],
    }
    return points, colors, report


def convert_nerfstudio_to_colmap(scene: Path, transforms: dict, image_root: Path) -> Path:
    frames = transforms.get("frames", [])
    if len(frames) < 50:
        raise RuntimeError(f"too few Nerfstudio frames: {len(frames)}")
    declared_width = int(transforms.get("w") or 0)
    declared_height = int(transforms.get("h") or 0)
    first_path = resolve_frame_path(scene, frames[0], image_root)
    with Image.open(first_path) as image:
        actual_width, actual_height = image.size
    width = declared_width or actual_width
    height = declared_height or actual_height
    fx = float(transforms.get("fl_x") or transforms.get("fl_y") or 0.0)
    fy = float(transforms.get("fl_y") or fx)
    cx = float(transforms.get("cx", width / 2.0))
    cy = float(transforms.get("cy", height / 2.0))
    if (width, height) != (actual_width, actual_height):
        scale_x = actual_width / width
        scale_y = actual_height / height
        fx *= scale_x
        fy *= scale_y
        cx *= scale_x
        cy *= scale_y
        width = actual_width
        height = actual_height
    if min(fx, fy, width, height) <= 0:
        raise RuntimeError("Nerfstudio transforms lacks valid intrinsics")
    model = scene / "sparse" / "0"
    model.mkdir(parents=True, exist_ok=True)
    (model / "cameras.txt").write_text(
        "# Camera list with one line of data per camera:\n"
        "#   CAMERA_ID, MODEL, WIDTH, HEIGHT, PARAMS[]\n"
        f"1 PINHOLE {width} {height} {fx:.12g} {fy:.12g} {cx:.12g} {cy:.12g}\n",
        encoding="utf-8",
    )
    image_lines = [
        "# Image list with two lines of data per image:",
        "#   IMAGE_ID, QW, QX, QY, QZ, TX, TY, TZ, CAMERA_ID, NAME",
        "#   POINTS2D[] as (X, Y, POINT3D_ID)",
    ]
    image_records: list[
        tuple[int, np.ndarray, np.ndarray, str]
    ] = []
    for image_id, frame in enumerate(frames, 1):
        c2w = np.asarray(frame["transform_matrix"], dtype=np.float64)
        if c2w.shape != (4, 4) or not np.isfinite(c2w).all():
            raise RuntimeError(f"invalid transform at frame {image_id}")
        # Nerfstudio camera matrices use OpenGL/Blender axes.  COLMAP uses
        # OpenCV axes, so flip camera Y/Z before inversion.
        c2w_cv = c2w.copy()
        c2w_cv[:3, 1:3] *= -1.0
        w2c = np.linalg.inv(c2w_cv)
        quaternion_xyzw = Rotation.from_matrix(w2c[:3, :3]).as_quat()
        quaternion = quaternion_xyzw[[3, 0, 1, 2]]
        translation = w2c[:3, 3]
        actual = resolve_frame_path(scene, frame, image_root)
        name = quote_name(str(actual.relative_to(image_root)))
        values = [*quaternion.tolist(), *translation.tolist()]
        image_lines.append(
            f"{image_id} "
            + " ".join(f"{value:.17g}" for value in values)
            + f" 1 {name}"
        )
        image_lines.append("")
        image_records.append((image_id, quaternion, translation, name))
    (model / "images.txt").write_text(
        "\n".join(image_lines) + "\n", encoding="utf-8"
    )

    ply_hint = transforms.get("ply_file_path")
    ply_candidates = []
    if ply_hint:
        ply_candidates.append(scene / str(ply_hint).lstrip("./"))
    ply_candidates.extend(
        [
            scene / "sparse_pc.ply",
            scene / "point_cloud.ply",
            scene / "points3D.ply",
        ]
    )
    point_path = next((path for path in ply_candidates if path.is_file()), None)
    if point_path is None:
        points, colors, initialization = triangulate_sparse_points(
            scene,
            image_root,
            transforms,
            frames,
            width,
            height,
            fx,
            fy,
            cx,
            cy,
        )
    else:
        points, colors = parse_ply_points(point_path)
        initialization = {
            "method": "source_sparse_ply",
            "source": str(point_path),
            "points_after_voxel": len(points),
        }
    if len(points) < 10_000:
        raise RuntimeError(f"too few sparse points: {len(points)}")
    with (model / "points3D.txt").open("w", encoding="utf-8") as output:
        output.write(
            "# 3D point list with one line of data per point:\n"
            "#   POINT3D_ID, X, Y, Z, R, G, B, ERROR, TRACK[]\n"
        )
        for point_id, (point, color) in enumerate(zip(points, colors), 1):
            output.write(
                f"{point_id} {point[0]:.17g} {point[1]:.17g} {point[2]:.17g} "
                f"{int(color[0])} {int(color[1])} {int(color[2])} 0.0\n"
            )
    with (model / "cameras.bin").open("wb") as output:
        output.write(struct.pack("<Q", 1))
        output.write(struct.pack("<iiQQ", 1, 1, width, height))
        output.write(struct.pack("<dddd", fx, fy, cx, cy))
    with (model / "images.bin").open("wb") as output:
        output.write(struct.pack("<Q", len(image_records)))
        for image_id, quaternion, translation, name in image_records:
            output.write(struct.pack("<i", image_id))
            output.write(struct.pack("<dddd", *quaternion.tolist()))
            output.write(struct.pack("<ddd", *translation.tolist()))
            output.write(struct.pack("<i", 1))
            output.write(name.encode("utf-8") + b"\x00")
            output.write(struct.pack("<Q", 0))
    with (model / "points3D.bin").open("wb") as output:
        output.write(struct.pack("<Q", len(points)))
        for point_id, (point, color) in enumerate(zip(points, colors), 1):
            output.write(
                struct.pack(
                    "<QdddBBBdQ",
                    point_id,
                    float(point[0]),
                    float(point[1]),
                    float(point[2]),
                    int(color[0]),
                    int(color[1]),
                    int(color[2]),
                    0.0,
                    0,
                )
            )
    (model / "sparse-initialization.json").write_text(
        json.dumps(initialization, indent=2) + "\n",
        encoding="utf-8",
    )
    return model


def normalize_layout(scene: Path, output: Path) -> dict:
    transforms_path = scene / "transforms.json"
    transforms = (
        json.loads(transforms_path.read_text(encoding="utf-8"))
        if transforms_path.is_file()
        else None
    )
    image_root = find_image_root(scene, transforms)
    ready, model = has_colmap_model(scene)
    conversion = "native_colmap"
    if not ready:
        if transforms is None:
            raise RuntimeError("scene has neither complete COLMAP nor Nerfstudio transforms")
        model = convert_nerfstudio_to_colmap(scene, transforms, image_root)
        conversion = "nerfstudio_to_colmap_text_and_binary"
    assert model is not None

    dataset = output / "dataset"
    dataset.mkdir(parents=True, exist_ok=True)
    target_images = dataset / "images"
    target_sparse = dataset / "sparse" / "0"
    if target_images.exists() or target_images.is_symlink():
        target_images.unlink()
    if target_sparse.exists() or target_sparse.is_symlink():
        target_sparse.unlink()
    target_images.symlink_to(image_root.resolve(), target_is_directory=True)
    target_sparse.parent.mkdir(parents=True, exist_ok=True)
    target_sparse.symlink_to(model.resolve(), target_is_directory=True)
    images = [
        path
        for path in image_root.rglob("*")
        if path.suffix.lower() in {".jpg", ".jpeg", ".png"}
    ]
    sample_shapes = []
    for path in images[:: max(1, len(images) // 12)][:12]:
        with Image.open(path) as image:
            image.verify()
            sample_shapes.append([image.width, image.height])
    return {
        "scene_root": str(scene),
        "dataset_root": str(dataset),
        "image_root": str(image_root),
        "colmap_model": str(model),
        "conversion": conversion,
        "sparse_initialization": json.loads(
            (model / "sparse-initialization.json").read_text(encoding="utf-8")
        )
        if (model / "sparse-initialization.json").is_file()
        else {"method": "native_colmap"},
        "images": len(images),
        "sample_shapes": sample_shapes,
    }


def main() -> None:
    args = parse_args()
    if args.output.exists():
        shutil.rmtree(args.output)
    args.output.mkdir(parents=True)
    extracted = args.output / "extracted"
    safe_extract(args.archive, extracted)
    scene = find_scene_root(extracted)
    report = {
        "schema_version": 1,
        "status": "passed",
        **normalize_layout(scene, args.output),
    }
    if report["images"] < 50:
        raise RuntimeError(f"too few images after extraction: {report['images']}")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report))


if __name__ == "__main__":
    main()
