"""Prepare a physically valid Genesis RACE drone asset.

Genesis 1.2.3 stores each massless propeller's arm offset in its inertial
origin while leaving the corresponding fixed joint at the body origin.
Genesis collapses those massless inertial offsets, so all four thrust forces
are applied at the vehicle center and cannot generate roll or pitch torque.

This module moves the four offsets to the fixed joints and keeps a
content-addressed, self-contained copy of the asset for the simulator.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

EXPECTED_PROP_OFFSETS = {
    "prop0": (0.0850, 0.0675, 0.0),
    "prop1": (-0.0850, 0.0675, 0.0),
    "prop2": (-0.0850, -0.0675, 0.0),
    "prop3": (0.0850, -0.0675, 0.0),
}


class RacerAssetError(ValueError):
    """Raised when the source asset does not match the audited RACE layout."""


def _parse_xyz(value: str | None, *, label: str) -> tuple[float, float, float]:
    if value is None:
        raise RacerAssetError(f"{label} is missing xyz")
    try:
        xyz = tuple(float(component) for component in value.split())
    except ValueError as exc:
        raise RacerAssetError(f"{label} has invalid xyz: {value!r}") from exc
    if len(xyz) != 3:
        raise RacerAssetError(f"{label} must contain three xyz values")
    return xyz


def _same_xyz(
    actual: tuple[float, float, float],
    expected: tuple[float, float, float],
    *,
    tolerance: float = 1e-9,
) -> bool:
    return all(abs(left - right) <= tolerance for left, right in zip(actual, expected))


def patch_racer_urdf(source_xml: bytes) -> bytes:
    """Move audited propeller offsets from massless links to fixed joints."""

    try:
        root = ET.fromstring(source_xml)
    except ET.ParseError as exc:
        raise RacerAssetError("source RACE URDF is not valid XML") from exc
    if root.tag != "robot" or root.attrib.get("name") != "racer":
        raise RacerAssetError("source asset is not the Genesis RACE URDF")

    for propeller, expected_offset in EXPECTED_PROP_OFFSETS.items():
        link_name = f"{propeller}_link"
        joint_name = f"{propeller}_joint"
        link = root.find(f"./link[@name='{link_name}']")
        joint = root.find(f"./joint[@name='{joint_name}']")
        if link is None or joint is None:
            raise RacerAssetError(f"source asset is missing {link_name} or {joint_name}")
        if joint.attrib.get("type") != "fixed":
            raise RacerAssetError(f"{joint_name} must be fixed")

        child = joint.find("child")
        if child is None or child.attrib.get("link") != link_name:
            raise RacerAssetError(f"{joint_name} must attach {link_name}")
        mass = link.find("./inertial/mass")
        inertial_origin = link.find("./inertial/origin")
        if mass is None or float(mass.attrib.get("value", "nan")) != 0.0:
            raise RacerAssetError(f"{link_name} must be massless")
        if inertial_origin is None:
            raise RacerAssetError(f"{link_name} is missing its inertial origin")

        actual_offset = _parse_xyz(
            inertial_origin.attrib.get("xyz"),
            label=f"{link_name} inertial origin",
        )
        if not _same_xyz(actual_offset, expected_offset):
            raise RacerAssetError(
                f"{link_name} offset {actual_offset} does not match "
                f"audited offset {expected_offset}"
            )

        joint_origin = joint.find("origin")
        if joint_origin is None:
            joint_origin = ET.SubElement(joint, "origin")
        else:
            existing = _parse_xyz(
                joint_origin.attrib.get("xyz", "0 0 0"),
                label=f"{joint_name} origin",
            )
            if not _same_xyz(existing, (0.0, 0.0, 0.0)):
                raise RacerAssetError(f"{joint_name} already has unexpected offset {existing}")
        joint_origin.set("rpy", "0 0 0")
        joint_origin.set("xyz", " ".join(f"{value:g}" for value in expected_offset))
        inertial_origin.set("xyz", "0 0 0")

    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def prepare_corrected_racer_urdf(
    source_path: str | Path,
    *,
    cache_root: str | Path | None = None,
) -> Path:
    """Create and return a content-addressed corrected RACE URDF.

    Relative mesh files are copied beside the generated URDF, which keeps the
    asset portable and avoids modifying the installed Genesis package.
    """

    source = Path(source_path).resolve()
    if not source.is_file():
        raise FileNotFoundError(f"RACE URDF does not exist: {source}")
    source_xml = source.read_bytes()
    patched_xml = patch_racer_urdf(source_xml)
    digest = hashlib.sha256(source_xml).hexdigest()[:16]
    root = (
        Path(cache_root)
        if cache_root is not None
        else Path(tempfile.gettempdir()) / "flightguard-genesis-assets"
    )
    output_dir = root / digest
    output_dir.mkdir(parents=True, exist_ok=True)

    parsed = ET.fromstring(source_xml)
    for mesh in parsed.findall(".//mesh"):
        filename = mesh.attrib.get("filename")
        if not filename:
            continue
        relative = Path(filename)
        if relative.is_absolute() or ".." in relative.parts:
            raise RacerAssetError(f"unsafe RACE mesh path: {filename!r}")
        mesh_source = (source.parent / relative).resolve()
        if not mesh_source.is_file():
            raise FileNotFoundError(f"RACE mesh does not exist: {mesh_source}")
        mesh_target = output_dir / relative.name
        if not mesh_target.is_file() or mesh_target.read_bytes() != mesh_source.read_bytes():
            shutil.copyfile(mesh_source, mesh_target)

    output = output_dir / "racer_flightguard.urdf"
    if not output.is_file() or output.read_bytes() != patched_xml:
        file_descriptor, temporary_name = tempfile.mkstemp(
            dir=output_dir,
            prefix=".racer_flightguard.",
            suffix=".tmp",
        )
        try:
            with os.fdopen(file_descriptor, "wb") as temporary:
                temporary.write(patched_xml)
            os.replace(temporary_name, output)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)
    return output
