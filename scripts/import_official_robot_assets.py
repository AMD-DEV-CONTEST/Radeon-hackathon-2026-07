#!/usr/bin/env python3
"""Import official LeKiwi, AmazingHand and Unitree G1 visual assets.

This replaces the old primitive placeholder geometry with upstream,
license-attributed robot models:

* LeKiwi: SIGRobotics-UIUC/LeKiwi (Apache-2.0)
* AmazingHand: pollen-robotics/AmazingHand (Apache-2.0 / CC-BY-4.0 mechanics)
* Unitree G1: unitreerobotics/unitree_ros (BSD-3-Clause)

Expected source checkouts (override with CLI flags):
  /tmp/btx-lekiwi-official
  /tmp/btx-amazinghand-official
  /tmp/btx-unitree-official

AmazingHand ships a detailed MJCF rather than URDF. For the web catalog we
flatten its official right-hand visual meshes at the MJCF zero pose into one
URDF link. This preserves the real CAD appearance without pretending that the
browser preview is already a physically correct closed-chain simulator.
"""
from __future__ import annotations

import argparse
import math
import re
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterable

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
OUT_ROOT = ROOT / "apps" / "realtime" / "static" / "urdf"


def _quat_matrix(wxyz: Iterable[float]) -> np.ndarray:
    w, x, y, z = (float(v) for v in wxyz)
    n = math.sqrt(w * w + x * x + y * y + z * z)
    if n == 0:
        return np.eye(3)
    w, x, y, z = w / n, x / n, y / n, z / n
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )


def _transform(pos: str | None, quat: str | None) -> np.ndarray:
    t = np.eye(4)
    if pos:
        t[:3, 3] = [float(v) for v in pos.split()]
    if quat:
        t[:3, :3] = _quat_matrix(float(v) for v in quat.split())
    return t


def _matrix_to_rpy(r: np.ndarray) -> tuple[float, float, float]:
    """URDF fixed-axis XYZ roll/pitch/yaw from a 3x3 rotation matrix."""
    sy = math.sqrt(r[0, 0] * r[0, 0] + r[1, 0] * r[1, 0])
    singular = sy < 1e-8
    if not singular:
        roll = math.atan2(r[2, 1], r[2, 2])
        pitch = math.atan2(-r[2, 0], sy)
        yaw = math.atan2(r[1, 0], r[0, 0])
    else:
        roll = math.atan2(-r[1, 2], r[1, 1])
        pitch = math.atan2(-r[2, 0], sy)
        yaw = 0.0
    return roll, pitch, yaw


def _fmt(values: Iterable[float]) -> str:
    return " ".join(f"{float(v):.9g}" for v in values)


def _reset_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    (path / "assets").mkdir(parents=True)


def import_lekiwi(source: Path) -> None:
    src_root = source / "URDF"
    src_urdf = src_root / "LeKiwi.urdf"
    if not src_urdf.is_file():
        raise FileNotFoundError(src_urdf)

    out = OUT_ROOT / "lekiwi"
    _reset_dir(out)
    text = src_urdf.read_text(encoding="utf-8")

    # The three omni-wheel STL files are byte-identical (~15 MB each). Point
    # all wheel visuals at one file so the catalog downloads one mesh, not 45 MB.
    wheel_names = re.findall(
        r"meshes/(4-Omni-Directional-Wheel_Single_Body-v1(?:-[12])?\.stl)",
        text,
    )
    canonical_wheel = "4-Omni-Directional-Wheel_Single_Body-v1.stl"
    for wheel_name in set(wheel_names):
        text = text.replace(f"meshes/{wheel_name}", f"assets/{canonical_wheel}")

    refs = sorted(set(re.findall(r'mesh filename="meshes/([^"]+)"', text)))
    text = text.replace('mesh filename="meshes/', 'mesh filename="assets/')
    for name in refs:
        shutil.copy2(src_root / "meshes" / name, out / "assets" / name)
    shutil.copy2(src_root / "meshes" / canonical_wheel, out / "assets" / canonical_wheel)

    # Keep upstream names intact for exact CAD transforms, but add attribution.
    text = text.replace(
        "<robot name=\"LeKiwi\">",
        "<!-- Official CAD export from SIGRobotics-UIUC/LeKiwi (Apache-2.0). -->\n"
        "<robot name=\"LeKiwi\">",
        1,
    )
    (out / "lekiwi.urdf").write_text(text, encoding="utf-8")
    shutil.copy2(source / "LICENSE.txt", out / "LICENSE-UPSTREAM.txt")


def import_g1(source: Path) -> None:
    src_root = source / "robots" / "g1_description"
    src_urdf = src_root / "g1_29dof_rev_1_0.urdf"
    if not src_urdf.is_file():
        raise FileNotFoundError(src_urdf)

    out = OUT_ROOT / "unitree_g1"
    _reset_dir(out)
    text = src_urdf.read_text(encoding="utf-8")
    refs = sorted(set(re.findall(r'mesh filename="meshes/([^"]+)"', text)))
    text = text.replace('mesh filename="meshes/', 'mesh filename="assets/')
    text = text.replace(
        '<robot name="g1_29dof_rev_1_0">',
        "<!-- Official Unitree G1 29-DoF model (BSD-3-Clause). -->\n"
        '<robot name="g1_29dof_rev_1_0">',
        1,
    )
    for name in refs:
        shutil.copy2(src_root / "meshes" / name, out / "assets" / name)
    (out / "unitree_g1.urdf").write_text(text, encoding="utf-8")
    shutil.copy2(source / "LICENSE", out / "LICENSE-UPSTREAM.txt")

    # Ship matching official MJCF for future simulation workflows.
    shutil.copy2(src_root / "g1_29dof_rev_1_0.xml", out / "unitree_g1.mjcf.xml")


def import_amazing_hand(source: Path) -> None:
    mjcf_root = (
        source
        / "Demo"
        / "AHSimulation"
        / "AHSimulation"
        / "AH_Right"
        / "mjcf"
    )
    src_xml = mjcf_root / "robot.xml"
    if not src_xml.is_file():
        raise FileNotFoundError(src_xml)

    out = OUT_ROOT / "amazing_hand"
    _reset_dir(out)
    root = ET.parse(src_xml).getroot()

    materials = {
        m.attrib["name"]: m.attrib.get("rgba", "0.75 0.75 0.78 1")
        for m in root.findall("./asset/material")
        if "name" in m.attrib
    }
    mesh_files = {
        (m.attrib.get("name") or Path(m.attrib["file"]).stem): m.attrib["file"]
        for m in root.findall("./asset/mesh")
        if "file" in m.attrib
    }

    visuals: list[tuple[str, np.ndarray, str]] = []

    def visit_body(body: ET.Element, parent_tf: np.ndarray) -> None:
        body_tf = parent_tf @ _transform(body.attrib.get("pos"), body.attrib.get("quat"))
        for geom in body.findall("geom"):
            if geom.attrib.get("type") != "mesh" or geom.attrib.get("class") != "visual":
                continue
            mesh_key = geom.attrib.get("mesh")
            mesh_file = mesh_files.get(mesh_key or "")
            if not mesh_file:
                continue
            geom_tf = body_tf @ _transform(geom.attrib.get("pos"), geom.attrib.get("quat"))
            rgba = materials.get(geom.attrib.get("material", ""), "0.75 0.75 0.78 1")
            visuals.append((mesh_file, geom_tf, rgba))
        for child in body.findall("body"):
            visit_body(child, body_tf)

    for top in root.findall("./worldbody/body"):
        visit_body(top, np.eye(4))

    # Copy each referenced official STL once.
    for mesh_file in sorted({v[0] for v in visuals}):
        shutil.copy2(mjcf_root / "assets" / mesh_file, out / "assets" / mesh_file)

    robot = ET.Element("robot", {"name": "amazing_hand_official_zero_pose"})
    robot.append(
        ET.Comment(
            "Official AmazingHand right-hand MJCF visual meshes flattened at "
            "zero pose; Pollen Robotics (Apache-2.0 / CC-BY-4.0 mechanics)."
        )
    )
    link = ET.SubElement(robot, "link", {"name": "amazing_hand"})
    for index, (mesh_file, tf, rgba) in enumerate(visuals):
        visual = ET.SubElement(link, "visual", {"name": f"visual_{index:03d}"})
        ET.SubElement(
            visual,
            "origin",
            {
                "xyz": _fmt(tf[:3, 3]),
                "rpy": _fmt(_matrix_to_rpy(tf[:3, :3])),
            },
        )
        geometry = ET.SubElement(visual, "geometry")
        ET.SubElement(geometry, "mesh", {"filename": f"assets/{mesh_file}"})
        material = ET.SubElement(visual, "material", {"name": f"mat_{index:03d}"})
        ET.SubElement(material, "color", {"rgba": rgba})

    ET.indent(robot, space="  ")
    xml = '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(
        robot, encoding="unicode"
    )
    (out / "amazing_hand.urdf").write_text(xml, encoding="utf-8")
    shutil.copy2(src_xml, out / "amazing_hand.mjcf.xml")
    shutil.copy2(source / "LICENSE", out / "LICENSE-UPSTREAM.txt")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--lekiwi", type=Path, default=Path("/tmp/btx-lekiwi-official")
    )
    parser.add_argument(
        "--amazing-hand",
        type=Path,
        default=Path("/tmp/btx-amazinghand-official"),
    )
    parser.add_argument(
        "--unitree", type=Path, default=Path("/tmp/btx-unitree-official")
    )
    args = parser.parse_args()

    import_lekiwi(args.lekiwi)
    import_amazing_hand(args.amazing_hand)
    import_g1(args.unitree)
    for name in ("lekiwi", "amazing_hand", "unitree_g1"):
        path = OUT_ROOT / name
        size_mb = sum(p.stat().st_size for p in path.rglob("*") if p.is_file()) / 2**20
        print(f"{name}: {size_mb:.1f} MB")


if __name__ == "__main__":
    main()
