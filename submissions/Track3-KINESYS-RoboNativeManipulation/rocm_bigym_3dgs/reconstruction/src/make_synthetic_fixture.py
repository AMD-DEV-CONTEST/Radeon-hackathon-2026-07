#!/usr/bin/env python3
"""Generate a tiny license-free Gaussian room used by CI.

This fixture validates PLY parsing, Sim(3) handling, room-layer export, hashes,
and profile generation. It is not a visual-quality benchmark.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np


DTYPE = np.dtype(
    [
        ("x", "<f4"),
        ("y", "<f4"),
        ("z", "<f4"),
        ("opacity", "<f4"),
        ("scale_0", "<f4"),
        ("scale_1", "<f4"),
        ("scale_2", "<f4"),
        ("rot_0", "<f4"),
        ("rot_1", "<f4"),
        ("rot_2", "<f4"),
        ("rot_3", "<f4"),
        ("f_dc_0", "<f4"),
        ("f_dc_1", "<f4"),
        ("f_dc_2", "<f4"),
    ]
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def room_points() -> np.ndarray:
    xy = np.linspace(-3.0, 3.0, 9)
    z = np.linspace(0.0, 3.0, 7)
    points: list[tuple[float, float, float]] = []
    points.extend((x, y, 0.0) for x in xy for y in xy)
    points.extend((x, y, 3.0) for x in xy for y in xy)
    points.extend((-3.0, y, height) for y in xy for height in z[1:-1])
    points.extend((3.0, y, height) for y in xy for height in z[1:-1])
    points.extend((x, -3.0, height) for x in xy[1:-1] for height in z[1:-1])
    points.extend((x, 3.0, height) for x in xy[1:-1] for height in z[1:-1])
    return np.asarray(points, dtype=np.float32)


def write_ply(path: Path, xyz: np.ndarray) -> None:
    records = np.zeros(len(xyz), dtype=DTYPE)
    records["x"], records["y"], records["z"] = xyz.T
    records["opacity"] = 3.0
    records["scale_0"] = records["scale_1"] = records["scale_2"] = -2.5
    records["rot_0"] = 1.0
    records["f_dc_0"] = 0.2
    records["f_dc_1"] = 0.3
    records["f_dc_2"] = 0.4
    header = [
        "ply",
        "format binary_little_endian 1.0",
        "comment synthetic Apache-2.0 CI fixture",
        f"element vertex {len(records)}",
        *(f"property float {name}" for name in records.dtype.names or ()),
        "end_header",
    ]
    with path.open("wb") as stream:
        stream.write(("\n".join(header) + "\n").encode("ascii"))
        records.tofile(stream)


def main() -> None:
    args = parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    write_ply(args.output / "gaussians.ply", room_points())
    matrices = []
    for angle in np.linspace(0.0, 2.0 * np.pi, 12, endpoint=False):
        matrix = np.eye(4)
        matrix[:3, 3] = [1.1 * np.cos(angle), 1.1 * np.sin(angle), 1.55]
        matrices.append(matrix.tolist())
    (args.output / "camera-path.json").write_text(
        json.dumps({"schema_version": 1, "camtoworlds": matrices}, indent=2) + "\n",
        encoding="utf-8",
    )
    identity = np.eye(4).tolist()
    (args.output / "alignment.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "gaussian_to_mujoco": identity,
                "mujoco_to_gaussian": identity,
                "scale_estimation": {"method": "synthetic identity"},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (args.output / "source.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "status": "complete",
                "dataset": "synthetic-room-ci",
                "scene": "axis-aligned-room",
                "scene_hash": "synthetic",
                "revision": "1",
                "source": "generated locally",
                "license": "Apache-2.0",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
