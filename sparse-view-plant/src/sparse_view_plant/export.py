"""PLY / JSON writers for pipeline outputs (numpy-only, no mesh dependencies)."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np


def write_point_cloud_ply(
    path: str | Path,
    points: np.ndarray,
    *,
    colors: np.ndarray | None = None,
    confidence: np.ndarray | None = None,
    keep_confidence_fraction: float | None = None,
) -> dict[str, int]:
    """Write a binary little-endian PLY with xyz + rgb (+ confidence).

    `keep_confidence_fraction` retains only the top fraction of points by
    confidence (e.g. 0.8 keeps the 80% most confident points). When it is
    given, `confidence` must also be provided.
    """
    pts = np.asarray(points, dtype=np.float32)
    if pts.ndim != 2 or pts.shape[1] != 3:
        raise ValueError(f"points must have shape (M, 3), got {pts.shape}")
    rgb = None if colors is None else np.asarray(colors, dtype=np.float32)
    conf = None if confidence is None else np.asarray(confidence, dtype=np.float32)
    if rgb is not None and rgb.shape != pts.shape:
        raise ValueError(f"colors must match points shape {pts.shape}, got {rgb.shape}")
    if conf is not None and conf.shape != (pts.shape[0],):
        raise ValueError(
            f"confidence must have shape {(pts.shape[0],)}, got {conf.shape}"
        )
    if keep_confidence_fraction is not None:
        if conf is None:
            raise ValueError("keep_confidence_fraction requires confidence")
        if not 0.0 < keep_confidence_fraction <= 1.0:
            raise ValueError(
                f"keep_confidence_fraction must be in (0, 1], got {keep_confidence_fraction}"
            )
        threshold = np.quantile(conf, 1.0 - keep_confidence_fraction)
        keep = conf >= threshold
        pts = pts[keep]
        rgb = None if rgb is None else rgb[keep]
        conf = conf[keep]

    properties = ["x", "y", "z"]
    if rgb is not None:
        properties += ["red", "green", "blue"]
    if conf is not None:
        properties.append("confidence")

    # Interleave fields with the exact dtypes declared in the header. A naive
    # `np.column_stack` would promote the uchar RGB columns to float32, which
    # desynchronizes the reader from the file layout.
    fields = [("x", "<f4"), ("y", "<f4"), ("z", "<f4")]
    if rgb is not None:
        fields += [("red", "u1"), ("green", "u1"), ("blue", "u1")]
    if conf is not None:
        fields.append(("confidence", "<f4"))
    record = np.empty(pts.shape[0], dtype=fields)
    record["x"] = pts[:, 0]
    record["y"] = pts[:, 1]
    record["z"] = pts[:, 2]
    if rgb is not None:
        record["red"] = np.clip(np.rint(rgb[:, 0] * 255.0), 0, 255).astype(np.uint8)
        record["green"] = np.clip(np.rint(rgb[:, 1] * 255.0), 0, 255).astype(np.uint8)
        record["blue"] = np.clip(np.rint(rgb[:, 2] * 255.0), 0, 255).astype(np.uint8)
    if conf is not None:
        record["confidence"] = conf
    record = np.ascontiguousarray(record)

    with Path(path).open("wb") as fh:
        fh.write(b"ply\nformat binary_little_endian 1.0\n")
        fh.write(f"element vertex {pts.shape[0]}\n".encode("ascii"))
        for prop in properties:
            kind = "uchar" if prop in {"red", "green", "blue"} else "float"
            fh.write(f"property {kind} {prop}\n".encode("ascii"))
        fh.write(b"end_header\n")
        fh.write(record.tobytes())
    return {"points": int(pts.shape[0])}


def write_json(path: str | Path, payload: Mapping[str, Any]) -> None:
    """Atomically write a JSON document."""
    target = Path(path)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(target)


def write_gaussian_splat_ply(
    path: str | Path,
    means: np.ndarray,
    covariances: np.ndarray,
    sh_dc: np.ndarray,
    opacities: np.ndarray,
    *,
    normals: np.ndarray | None = None,
    sh_rest: np.ndarray | None = None,
) -> dict[str, int]:
    """Write Gaussians in the standard 3DGS PLY layout used by Splatt3R.

    Attributes: x y z, nx ny nz, f_dc_0..2, opacity (raw logits),
    f_rest_0..8 (SH coefficients beyond DC, zeros when ``sh_rest`` is None),
    scale_0..2 (log), rot_0..3 (standard 3DGS quaternion w x y z).
    `normals` (optional) fills the nx/ny/nz columns — 2DGS-style surfels carry
    their disk normal there; it defaults to zeros like 3DGS. `sh_rest` is the
    (M, 3, 3) degree-1 rest coefficients, stored as f_rest_0..8 in standard
    3DGS slot order (channel-major: [c][k] -> f_rest_{3*c + k}).
    """
    pts = np.asarray(means, dtype=np.float32)
    cov = np.asarray(covariances, dtype=np.float32)
    sh = np.asarray(sh_dc, dtype=np.float32)
    op = np.asarray(opacities, dtype=np.float32)
    count = pts.shape[0]
    if pts.shape != (count, 3):
        raise ValueError(f"means must have shape (M, 3), got {pts.shape}")
    if cov.shape != (count, 3, 3):
        raise ValueError(f"covariances must have shape (M, 3, 3), got {cov.shape}")
    if sh.shape != (count, 3):
        raise ValueError(f"sh_dc must have shape (M, 3), got {sh.shape}")
    if op.shape != (count, 1):
        raise ValueError(f"opacities must have shape (M, 1), got {op.shape}")
    if normals is not None:
        normals = np.asarray(normals, dtype=np.float32)
        if normals.shape != (count, 3):
            raise ValueError(f"normals must have shape (M, 3), got {normals.shape}")
    rest = None
    if sh_rest is not None:
        rest = np.asarray(sh_rest, dtype=np.float32)
        if rest.shape != (count, 3, 3):
            raise ValueError(f"sh_rest must have shape (M, 3, 3), got {rest.shape}")
        rest = rest.reshape(count, 9)

    rotations_xyzw, scales = _covariance_to_quaternion_scale(cov)
    rotations = rotations_xyzw[:, [3, 0, 1, 2]]
    normals = np.zeros_like(pts) if normals is None else normals
    # Degenerate (rank-deficient) covariances can carry exactly-zero scales;
    # floor them so the log-scale PLY columns stay finite.
    scales = np.maximum(scales, 1e-10)
    rest = np.zeros((count, 9), dtype=np.float32) if rest is None else rest
    attributes = np.concatenate(
        [pts, normals, sh, rest, op, np.log(scales), rotations], axis=-1
    )
    properties = [
        "x",
        "y",
        "z",
        "nx",
        "ny",
        "nz",
        "f_dc_0",
        "f_dc_1",
        "f_dc_2",
        "f_rest_0",
        "f_rest_1",
        "f_rest_2",
        "f_rest_3",
        "f_rest_4",
        "f_rest_5",
        "f_rest_6",
        "f_rest_7",
        "f_rest_8",
        "opacity",
        "scale_0",
        "scale_1",
        "scale_2",
        "rot_0",
        "rot_1",
        "rot_2",
        "rot_3",
    ]
    with Path(path).open("wb") as fh:
        fh.write(b"ply\nformat binary_little_endian 1.0\n")
        fh.write(b"comment quaternion_order wxyz\n")
        fh.write(f"element vertex {count}\n".encode("ascii"))
        fh.writelines(f"property float {prop}\n".encode("ascii") for prop in properties)
        fh.write(b"end_header\n")
        fh.write(attributes.astype(np.float32).tobytes())
    return {"gaussians": count}


def _covariance_to_quaternion_scale(
    covariances: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Decompose (M, 3, 3) covariance matrices into (M, 4) quaternions xyzw
    and (M, 3) scales via symmetric eigendecomposition.

    Covariances are symmetric PSD by construction (R diag(scale^2) R^T), so
    `np.linalg.eigh` recovers the rotation exactly, while `np.linalg.svd`
    does not guarantee U == V for general symmetric matrices (and therefore
    U @ V^T is not the covariance's rotation).
    """
    eigenvalues, eigenvectors = np.linalg.eigh(covariances)
    scales = np.sqrt(np.maximum(eigenvalues, 0.0))
    # eigh returns an orthogonal Q; flip a column so the stored rotation has
    # determinant +1 (a reflection renders identically but is not a quaternion).
    rotation = eigenvectors
    reflections = np.linalg.det(rotation) < 0
    if reflections.any():
        rotation = rotation.copy()
        rotation[reflections, :, 0] *= -1.0
    quaternions = _rotation_matrix_to_quaternion(rotation)
    return (
        quaternions.astype(np.float32),
        scales.astype(np.float32),
    )


def _rotation_matrix_to_quaternion(matrices: np.ndarray) -> np.ndarray:
    """Rotation matrices (M, 3, 3) -> quaternions (M, 4) in x y z w order.

    Uses Shepperd's method and matches scipy's `Rotation.as_quat()`
    convention so the output is compatible with 3DGS readers.
    """
    m = np.asarray(matrices, dtype=np.float64)
    result = np.empty((m.shape[0], 4), dtype=np.float64)
    trace = np.trace(m, axis1=1, axis2=2)
    positive = trace > 0
    if positive.any():
        s = np.sqrt(trace[positive] + 1.0) * 2.0
        result[positive, 0] = (m[positive, 2, 1] - m[positive, 1, 2]) / s
        result[positive, 1] = (m[positive, 0, 2] - m[positive, 2, 0]) / s
        result[positive, 2] = (m[positive, 1, 0] - m[positive, 0, 1]) / s
        result[positive, 3] = 0.25 * s
    for axis in range(3):
        diagonal = np.diagonal(m, axis1=1, axis2=2)
        mask = ~positive & (np.argmax(diagonal, axis=1) == axis)
        if not mask.any():
            continue
        mm = m[mask]
        s = 2.0 * np.sqrt(
            1.0
            + mm[:, axis, axis]
            - mm[:, (axis + 1) % 3, (axis + 1) % 3]
            - mm[:, (axis + 2) % 3, (axis + 2) % 3]
        )
        result[mask, axis] = 0.25 * s
        result[mask, (axis + 1) % 3] = (
            mm[:, (axis + 1) % 3, axis] + mm[:, axis, (axis + 1) % 3]
        ) / s
        result[mask, (axis + 2) % 3] = (
            mm[:, (axis + 2) % 3, axis] + mm[:, axis, (axis + 2) % 3]
        ) / s
        result[mask, 3] = (
            mm[:, (axis + 2) % 3, (axis + 1) % 3]
            - mm[:, (axis + 1) % 3, (axis + 2) % 3]
        ) / s
    return result


def write_triangle_mesh_ply(
    path: str | Path,
    vertices: np.ndarray,
    faces: np.ndarray,
    *,
    vertex_colors: np.ndarray | None = None,
) -> dict[str, int]:
    """Write a binary little-endian PLY with vertices, faces, and normals.

    `faces` is (F, 3) int64 indices into `vertices`. Vertex normals are
    computed as the area-weighted average of incident face normals so the
    mesh renders with flat-ish shading in standard viewers.
    """
    import plyfile

    pts = np.asarray(vertices, dtype=np.float64)
    tris = np.asarray(faces, dtype=np.int64)
    if pts.ndim != 2 or pts.shape[1] != 3:
        raise ValueError(f"vertices must have shape (V, 3), got {pts.shape}")
    if tris.ndim != 2 or tris.shape[1] != 3:
        raise ValueError(f"faces must have shape (F, 3), got {tris.shape}")
    if len(tris) and (tris.min() < 0 or tris.max() >= len(pts)):
        raise ValueError("face indices out of range")
    colours = (
        None if vertex_colors is None else np.asarray(vertex_colors, dtype=np.uint8)
    )
    if colours is not None and colours.shape != pts.shape:
        raise ValueError(f"vertex_colors must match vertices, got {colours.shape}")

    normals = np.zeros_like(pts)
    for tri in tris:
        a, b, c = (pts[index] for index in tri)
        normal = np.cross(b - a, c - a)
        normals[tri] += normal
    norms = np.linalg.norm(normals, axis=1, keepdims=True)
    normals = np.divide(normals, norms, out=normals, where=norms > 0.0)

    property_names = ["x", "y", "z", "nx", "ny", "nz"]
    property_types = ["f8"] * 6
    if colours is not None:
        property_names += ["red", "green", "blue"]
        property_types += ["u1"] * 3
    vertex_data = np.zeros(
        len(pts),
        dtype=[(name, kind) for name, kind in zip(property_names, property_types)],
    )
    vertex_data["x"], vertex_data["y"], vertex_data["z"] = (
        pts[:, 0],
        pts[:, 1],
        pts[:, 2],
    )
    vertex_data["nx"], vertex_data["ny"], vertex_data["nz"] = (
        normals[:, 0],
        normals[:, 1],
        normals[:, 2],
    )
    if colours is not None:
        vertex_data["red"], vertex_data["green"], vertex_data["blue"] = (
            colours[:, 0],
            colours[:, 1],
            colours[:, 2],
        )
    vertex_element = plyfile.PlyElement.describe(vertex_data, "vertex")
    face_data = np.zeros(len(tris), dtype=[("vertex_indices", "i4", (3,))])
    face_data["vertex_indices"] = tris
    face_element = plyfile.PlyElement.describe(face_data, "face")
    plyfile.PlyData([vertex_element, face_element], text=False).write(str(path))
    return {"vertices": len(pts), "faces": len(tris)}


def read_gaussian_ply_means(
    path: str | Path, opacity_threshold: float = 0.5
) -> np.ndarray:
    """Read (x, y, z) means from a Gaussian PLY, opacity-filtered.

    Shared by the pipeline mesh path (`--mesh-source gaussians`) and the
    evaluation scripts so the Gaussian-means view is consistent everywhere.
    """
    import plyfile

    vertices = plyfile.PlyData.read(str(path))["vertex"]
    means = np.stack(
        [
            np.asarray(vertices["x"]),
            np.asarray(vertices["y"]),
            np.asarray(vertices["z"]),
        ],
        axis=1,
    ).astype(np.float64)
    if "opacity" in vertices.properties:
        logits = np.asarray(vertices["opacity"], dtype=np.float64)
        means = means[1.0 / (1.0 + np.exp(-logits)) > opacity_threshold]
    return means


def read_gaussian_ply_means_colors(
    path: str | Path, opacity_threshold: float = 0.5
) -> tuple[np.ndarray, np.ndarray]:
    """Read opacity-filtered Gaussian means and their SH-DC RGB colours."""
    import plyfile

    vertices = plyfile.PlyData.read(str(path))["vertex"]
    means = np.stack(
        [np.asarray(vertices[axis]) for axis in ("x", "y", "z")], axis=1
    ).astype(np.float64)
    sh_dc = np.stack(
        [np.asarray(vertices[f"f_dc_{axis}"]) for axis in range(3)], axis=1
    ).astype(np.float64)
    colours = np.clip(0.5 + 0.28209479177387814 * sh_dc, 0.0, 1.0)
    if "opacity" in vertices.properties:
        logits = np.asarray(vertices["opacity"], dtype=np.float64)
        keep = 1.0 / (1.0 + np.exp(-logits)) > opacity_threshold
        means, colours = means[keep], colours[keep]
    return means, np.rint(colours * 255.0).astype(np.uint8)
