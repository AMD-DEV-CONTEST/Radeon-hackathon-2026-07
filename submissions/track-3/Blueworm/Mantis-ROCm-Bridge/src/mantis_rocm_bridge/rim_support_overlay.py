"""Non-overwriting local-only Mantis rim-support primitive materialization."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from .contracts import ContractError
from .urdf_audit import audit_urdf


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _numeric_vector(value: Any, length: int, label: str) -> list[float]:
    if (
        not isinstance(value, list)
        or len(value) != length
        or not all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in value)
    ):
        raise ContractError(f"{label} must contain {length} numeric values")
    return [float(item) for item in value]


def validate_overlay_shape(plan: dict[str, Any]) -> None:
    if plan.get("schema_version") != 1 or plan.get("status") != "local_prototype_ready":
        raise ContractError("rim-support overlay plan schema or status changed")
    geometry = plan.get("geometry")
    source = plan.get("source_asset")
    materialization = plan.get("materialization")
    licensing = plan.get("licensing")
    if not all(isinstance(item, dict) for item in (geometry, source, materialization, licensing)):
        raise ContractError("rim-support overlay plan sections must be objects")
    links = geometry.get("target_links")
    if (
        not isinstance(links, list)
        or not links
        or len(links) != len(set(links))
        or not all(isinstance(link, str) and link for link in links)
    ):
        raise ContractError("rim-support target_links must be non-empty and unique")
    def validate_primitive(primitive: dict[str, Any], label: str) -> None:
        if primitive.get("shape") != "box":
            raise ContractError(f"{label} currently supports box primitives only")
        size = _numeric_vector(primitive.get("size_xyz_m"), 3, f"{label} size")
        _numeric_vector(primitive.get("origin_xyz_m"), 3, f"{label} origin")
        _numeric_vector(primitive.get("origin_rpy_rad"), 3, f"{label} orientation")
        per_link_rpy = primitive.get("per_link_origin_rpy_rad")
        if per_link_rpy is not None:
            if not isinstance(per_link_rpy, dict) or set(per_link_rpy) != set(links):
                raise ContractError(
                    f"{label} per-link orientations must cover exactly the target links"
                )
            for link_name, orientation in per_link_rpy.items():
                _numeric_vector(
                    orientation,
                    3,
                    f"{label} per-link orientation for {link_name}",
                )
        rgba = _numeric_vector(primitive.get("color_rgba"), 4, f"{label} color")
        if min(size) <= 0.0 or any(value < 0.0 or value > 1.0 for value in rgba):
            raise ContractError(f"{label} size or color is outside its valid range")
        for field in ("collision_name", "visual_name"):
            if not isinstance(primitive.get(field), str) or not primitive[field]:
                raise ContractError(f"{label} {field} must be a non-empty string")

    validate_primitive(geometry, "rim-support")
    additional = geometry.get("additional_primitives", [])
    if not isinstance(additional, list) or not all(
        isinstance(primitive, dict) for primitive in additional
    ):
        raise ContractError("rim-support additional_primitives must be a list of objects")
    for index, primitive in enumerate(additional):
        validate_primitive(primitive, f"rim-support additional primitive {index}")
    collision_names = [geometry["collision_name"]] + [
        primitive["collision_name"] for primitive in additional
    ]
    visual_names = [geometry["visual_name"]] + [
        primitive["visual_name"] for primitive in additional
    ]
    if len(collision_names) != len(set(collision_names)) or len(visual_names) != len(
        set(visual_names)
    ):
        raise ContractError("rim-support primitive names must be unique")
    if source.get("required_distribution_allowed") is not False:
        raise ContractError("rim-support source must retain the unresolved distribution boundary")
    if licensing.get("materialized_output_distribution_allowed") is not False:
        raise ContractError("rim-support materialization must remain local-only")
    if materialization.get("overwrite_allowed") is not False:
        raise ContractError("rim-support materialization must be non-overwriting")


def materialize_rim_support_overlay(
    input_root: str | Path,
    output_root: str | Path,
    plan: dict[str, Any],
    *,
    acknowledge_unresolved_license_for_local_use: bool = False,
) -> dict[str, Any]:
    validate_overlay_shape(plan)
    if not acknowledge_unresolved_license_for_local_use:
        raise ContractError(
            "rim-support materialization requires acknowledgement of the unresolved "
            "Mantis license for local-only use"
        )
    source_root = Path(input_root)
    destination = Path(output_root)
    if destination.exists():
        raise ContractError(f"output already exists and will not be overwritten: {destination}")
    parent_manifest_path = source_root / "manifest.json"
    if not parent_manifest_path.is_file():
        raise ContractError("rim-support input has no parent manifest")
    if _sha256(parent_manifest_path) != plan["source_asset"]["manifest_sha256"]:
        raise ContractError("rim-support parent manifest hash mismatch")
    parent = json.loads(parent_manifest_path.read_text(encoding="utf-8"))
    if parent.get("distribution_allowed") is not False:
        raise ContractError("rim-support input unexpectedly changed distribution status")
    if parent.get("license_status") != plan["source_asset"]["required_license_status"]:
        raise ContractError("rim-support parent license status changed")
    parent_urdf = source_root / plan["source_asset"]["output_urdf"]
    if not parent_urdf.is_file() or _sha256(parent_urdf) != plan["source_asset"]["output_urdf_sha256"]:
        raise ContractError("rim-support parent URDF hash mismatch")

    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f".{destination.name}.staging-", dir=destination.parent
    ) as stage_name:
        stage = Path(stage_name)
        shutil.copytree(source_root, stage, dirs_exist_ok=True)
        shutil.copy2(stage / "manifest.json", stage / "parent_manifest.json")
        try:
            robot = ET.parse(parent_urdf).getroot()
        except (OSError, ET.ParseError) as exc:
            raise ContractError(f"cannot parse rim-support parent URDF: {exc}") from exc
        robot.set("name", plan["materialization"]["output_robot_name"])
        geometry = plan["geometry"]
        primitives = [geometry, *geometry.get("additional_primitives", [])]
        for link_name in geometry["target_links"]:
            links = robot.findall(f"./link[@name='{link_name}']")
            if len(links) != 1:
                raise ContractError(f"rim-support target link is missing or repeated: {link_name}")
            link = links[0]
            for primitive in primitives:
                names = {primitive["collision_name"], primitive["visual_name"]}
                if any(child.get("name") in names for child in list(link)):
                    raise ContractError(f"rim-support overlay already exists on {link_name}")
                xyz = " ".join(str(value) for value in primitive["origin_xyz_m"])
                size = " ".join(str(value) for value in primitive["size_xyz_m"])
                rgba = " ".join(str(value) for value in primitive["color_rgba"])
                per_link_rpy = primitive.get("per_link_origin_rpy_rad", {})
                rpy_values = per_link_rpy.get(link_name, primitive["origin_rpy_rad"])
                rpy = " ".join(str(value) for value in rpy_values)
                collision = ET.SubElement(
                    link,
                    "collision",
                    {"name": primitive["collision_name"]},
                )
                ET.SubElement(collision, "origin", {"xyz": xyz, "rpy": rpy})
                collision_geometry = ET.SubElement(collision, "geometry")
                ET.SubElement(collision_geometry, "box", {"size": size})
                visual = ET.SubElement(
                    link,
                    "visual",
                    {"name": primitive["visual_name"]},
                )
                ET.SubElement(visual, "origin", {"xyz": xyz, "rpy": rpy})
                visual_geometry = ET.SubElement(visual, "geometry")
                ET.SubElement(visual_geometry, "box", {"size": size})
                material = ET.SubElement(
                    visual,
                    "material",
                    {"name": "competition_rim_support"},
                )
                ET.SubElement(material, "color", {"rgba": rgba})

        ET.indent(robot, space="  ")
        output_urdf = stage / plan["materialization"]["output_urdf"]
        output_urdf.parent.mkdir(parents=True, exist_ok=True)
        ET.ElementTree(robot).write(output_urdf, encoding="utf-8", xml_declaration=True)

        gripper_rows = parent.get("structural_audit", {}).get("physical_gripper_joints", [])
        gripper_joints = [row.get("name") for row in gripper_rows if isinstance(row, dict)]
        selected_joints = list(parent.get("selected_joint_order", []))
        if not gripper_joints or not selected_joints:
            raise ContractError("rim-support parent manifest lacks joint audit data")
        arm_joints = [name for name in selected_joints if name not in set(gripper_joints)]
        audit = audit_urdf(output_urdf, arm_joints, gripper_joints, output_urdf.parent)
        if not audit["genesis_import_gate_pass"]:
            raise ContractError(f"rim-support output failed structural audit: {audit['issues']}")
        audit["urdf"] = plan["materialization"]["output_urdf"]

        output_files = sorted(
            path.relative_to(stage).as_posix()
            for path in stage.rglob("*")
            if path.is_file() and path.name != "manifest.json"
        )
        manifest = {
            "schema_version": 1,
            "overlay_id": plan["overlay_id"],
            "materialized": True,
            "distribution_allowed": False,
            "license_status": "upstream_unresolved_local_overlay_only",
            "parent_manifest_sha256": _sha256(stage / "parent_manifest.json"),
            "parent_output_urdf_sha256": plan["source_asset"]["output_urdf_sha256"],
            "overlay_plan_canonical_sha256": _canonical_sha256(plan),
            "overlay_geometry": geometry,
            "output_urdf": plan["materialization"]["output_urdf"],
            "output_urdf_sha256": _sha256(output_urdf),
            "output_sha256": {relative: _sha256(stage / relative) for relative in output_files},
            "structural_audit": audit,
            "evidence_boundary": plan["gates"]["claim_boundary"],
        }
        (stage / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.rename(stage, destination)
    return manifest
