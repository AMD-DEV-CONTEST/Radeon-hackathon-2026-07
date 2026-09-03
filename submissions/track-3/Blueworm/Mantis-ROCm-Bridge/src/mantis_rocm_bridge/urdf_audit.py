"""Dependency-free URDF audit focused on Genesis migration hazards."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterable

from .contracts import ContractError


def _numbers(value: str | None) -> list[float] | None:
    if value is None:
        return None
    try:
        return [float(part) for part in value.split()]
    except ValueError as exc:
        raise ContractError(f"invalid numeric URDF attribute: {value}") from exc


def _resolve_mesh(uri: str, package_root: Path | None) -> Path | None:
    if package_root is None:
        return None
    prefix = "package://"
    if uri.startswith(prefix):
        package_and_path = uri[len(prefix) :].split("/", 1)
        if len(package_and_path) != 2:
            return None
        return package_root / package_and_path[1]
    path = Path(uri)
    return path if path.is_absolute() else package_root / path


def audit_urdf(
    urdf_path: str | Path,
    expected_arm_joints: Iterable[str],
    expected_gripper_joints: Iterable[str],
    package_root: str | Path | None = None,
) -> dict[str, Any]:
    urdf_path = Path(urdf_path)
    try:
        root = ET.parse(urdf_path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise ContractError(f"cannot parse URDF {urdf_path}: {exc}") from exc
    if root.tag != "robot":
        raise ContractError("URDF root element must be <robot>")

    links = [element.get("name") for element in root.findall("link")]
    if any(not name for name in links) or len(links) != len(set(links)):
        raise ContractError("URDF link names must be present and unique")

    joints: list[dict[str, Any]] = []
    joint_names: list[str] = []
    child_links: set[str] = set()
    for element in root.findall("joint"):
        name = element.get("name")
        joint_type = element.get("type")
        parent = element.find("parent")
        child = element.find("child")
        if not name or not joint_type or parent is None or child is None:
            raise ContractError("every URDF joint needs name, type, parent, and child")
        parent_name = parent.get("link")
        child_name = child.get("link")
        if not parent_name or not child_name:
            raise ContractError(f"joint {name} has an empty parent or child")
        axis = element.find("axis")
        limit = element.find("limit")
        joint_names.append(name)
        child_links.add(child_name)
        joints.append(
            {
                "name": name,
                "type": joint_type,
                "parent": parent_name,
                "child": child_name,
                "axis": _numbers(axis.get("xyz")) if axis is not None else None,
                "limit": {
                    key: float(limit.get(key))
                    for key in ("lower", "upper", "effort", "velocity")
                    if limit is not None and limit.get(key) is not None
                },
            }
        )
    if len(joint_names) != len(set(joint_names)):
        raise ContractError("URDF joint names must be unique")

    expected_arm = set(expected_arm_joints)
    expected_gripper = set(expected_gripper_joints)
    available = set(joint_names)
    actuated = {joint["name"] for joint in joints if joint["type"] != "fixed"}
    expected_policy_physical = expected_arm | expected_gripper

    mesh_uris = sorted(
        {
            mesh.get("filename")
            for mesh in root.findall(".//mesh")
            if mesh.get("filename") is not None
        }
    )
    package_path = Path(package_root) if package_root is not None else None
    missing_meshes: list[dict[str, str]] = []
    unresolved_meshes: list[str] = []
    for uri in mesh_uris:
        resolved = _resolve_mesh(uri, package_path)
        if resolved is None:
            unresolved_meshes.append(uri)
        elif not resolved.is_file():
            missing_meshes.append({"uri": uri, "resolved_path": str(resolved)})

    missing_arm = sorted(expected_arm - available)
    missing_gripper = sorted(expected_gripper - available)
    uncontrolled = sorted(actuated - expected_policy_physical)
    root_links = sorted(set(links) - child_links)
    issues: list[str] = []
    if len(root_links) != 1:
        issues.append("urdf_must_have_one_root_link")
    if missing_arm:
        issues.append("expected_arm_joints_missing")
    if missing_gripper:
        issues.append("expected_gripper_joints_missing")
    if uncontrolled:
        issues.append("nonpolicy_actuated_joints_present")
    if missing_meshes:
        issues.append("mesh_files_missing")
    if unresolved_meshes:
        issues.append("mesh_paths_unresolved")

    return {
        "schema_version": 1,
        "urdf": str(urdf_path),
        "robot_name": root.get("name"),
        "link_count": len(links),
        "joint_count": len(joints),
        "actuated_joint_count": len(actuated),
        "root_links": root_links,
        "missing_expected_arm_joints": missing_arm,
        "missing_expected_gripper_joints": missing_gripper,
        "uncontrolled_actuated_joints": uncontrolled,
        "physical_gripper_joints": [
            joint for joint in joints if joint["name"] in expected_gripper
        ],
        "mesh_uri_count": len(mesh_uris),
        "missing_meshes": missing_meshes,
        "unresolved_meshes": unresolved_meshes,
        "issues": issues,
        "genesis_import_gate_pass": not issues,
    }

