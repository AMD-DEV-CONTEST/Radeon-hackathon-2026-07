"""Build a non-overwriting fixed-base Mantis asset from an external URDF package."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterable

from .contracts import ContractError
from .urdf_audit import audit_urdf


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _relative(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return path.name


def _parse_source(source_urdf: Path) -> ET.Element:
    try:
        root = ET.parse(source_urdf).getroot()
    except (OSError, ET.ParseError) as exc:
        raise ContractError(f"cannot parse source URDF {source_urdf}: {exc}") from exc
    if root.tag != "robot":
        raise ContractError("source URDF root must be <robot>")
    return root


def _named_elements(root: ET.Element, tag: str) -> dict[str, ET.Element]:
    result: dict[str, ET.Element] = {}
    for element in root.findall(tag):
        name = element.get("name")
        if not name or name in result:
            raise ContractError(f"source URDF has missing or duplicate {tag} name")
        result[name] = element
    return result


def _resolve_mesh(uri: str, package_root: Path) -> Path:
    prefix = "package://"
    if uri.startswith(prefix):
        package_and_path = uri[len(prefix) :].split("/", 1)
        if len(package_and_path) != 2:
            raise ContractError(f"malformed package mesh URI: {uri}")
        relative = Path(package_and_path[1])
    else:
        candidate = Path(uri)
        if candidate.is_absolute():
            if not candidate.is_file():
                raise ContractError(f"mesh file does not exist: {candidate}")
            return candidate
        relative = candidate

    full_mesh = package_root / "meshes_full" / relative.name
    declared_mesh = package_root / relative
    for candidate in (full_mesh, declared_mesh):
        if candidate.is_file():
            return candidate
    raise ContractError(
        f"mesh URI cannot be resolved from package root: {uri}; "
        f"checked {full_mesh} and {declared_mesh}"
    )


def _selection(
    source_root: ET.Element,
    root_link: str,
    selected_joint_order: Iterable[str],
) -> tuple[list[ET.Element], list[ET.Element]]:
    links = _named_elements(source_root, "link")
    joints = _named_elements(source_root, "joint")
    if root_link not in links:
        raise ContractError(f"fixed-base root link is absent: {root_link}")

    selected_links = [copy.deepcopy(links[root_link])]
    available_parents = {root_link}
    selected_joints: list[ET.Element] = []
    for joint_name in selected_joint_order:
        if joint_name not in joints:
            raise ContractError(f"selected joint is absent: {joint_name}")
        joint = joints[joint_name]
        parent = joint.find("parent")
        child = joint.find("child")
        if parent is None or child is None or not parent.get("link") or not child.get("link"):
            raise ContractError(f"selected joint has incomplete topology: {joint_name}")
        parent_name = parent.get("link")
        child_name = child.get("link")
        if parent_name not in available_parents:
            raise ContractError(
                f"selected_joint_order is not topological at {joint_name}; missing parent {parent_name}"
            )
        if child_name not in links or child_name in available_parents:
            raise ContractError(f"selected joint has invalid or repeated child link: {joint_name}")
        selected_joints.append(copy.deepcopy(joint))
        selected_links.append(copy.deepcopy(links[child_name]))
        available_parents.add(child_name)
    return selected_links, selected_joints


def plan_fixed_base_asset(
    source_urdf: str | Path,
    package_root: str | Path,
    root_link: str,
    selected_joint_order: Iterable[str],
    robot_name: str,
) -> dict[str, Any]:
    source_path = Path(source_urdf)
    package_path = Path(package_root)
    joint_order = list(selected_joint_order)
    if not source_path.is_file() or not package_path.is_dir():
        raise ContractError("source URDF and package root must exist")
    if not joint_order or len(joint_order) != len(set(joint_order)):
        raise ContractError("selected_joint_order must be non-empty and unique")

    source_root = _parse_source(source_path)
    selected_links, selected_joints = _selection(source_root, root_link, joint_order)
    mesh_sources: dict[str, Path] = {}
    mesh_uses = 0
    for link in selected_links:
        for mesh in link.findall(".//mesh"):
            uri = mesh.get("filename")
            if not uri:
                raise ContractError("selected link contains a mesh without filename")
            resolved = _resolve_mesh(uri, package_path)
            destination_name = resolved.name
            previous = mesh_sources.get(destination_name)
            if previous is not None and previous.resolve() != resolved.resolve():
                raise ContractError(f"mesh basename collision: {destination_name}")
            mesh_sources[destination_name] = resolved
            mesh_uses += 1

    limits: dict[str, dict[str, Any]] = {}
    for joint in selected_joints:
        limit = joint.find("limit")
        axis = joint.find("axis")
        limits[joint.get("name")] = {
            "type": joint.get("type"),
            "axis": axis.get("xyz") if axis is not None else None,
            "lower": float(limit.get("lower")) if limit is not None and limit.get("lower") else None,
            "upper": float(limit.get("upper")) if limit is not None and limit.get("upper") else None,
            "effort": float(limit.get("effort")) if limit is not None and limit.get("effort") else None,
            "velocity": float(limit.get("velocity")) if limit is not None and limit.get("velocity") else None,
        }

    return {
        "schema_version": 1,
        "profile": "fixed_base_bimanual",
        "robot_name": robot_name,
        "source_urdf": _relative(source_path, package_path),
        "source_urdf_sha256": _sha256(source_path),
        "root_link": root_link,
        "selected_joint_order": joint_order,
        "selected_joint_count": len(selected_joints),
        "selected_link_count": len(selected_links),
        "unique_mesh_count": len(mesh_sources),
        "mesh_use_count": mesh_uses,
        "mesh_sources": {
            name: _relative(path, package_path) for name, path in sorted(mesh_sources.items())
        },
        "joint_limits": limits,
        "excluded_joint_count": len(source_root.findall("joint")) - len(selected_joints),
        "license_status": "unresolved_local_generation_only",
    }


def materialize_fixed_base_asset(
    source_urdf: str | Path,
    package_root: str | Path,
    output_root: str | Path,
    root_link: str,
    selected_joint_order: Iterable[str],
    physical_gripper_joints: Iterable[str],
    robot_name: str,
    *,
    acknowledge_unresolved_license_for_local_use: bool = False,
) -> dict[str, Any]:
    if not acknowledge_unresolved_license_for_local_use:
        raise ContractError(
            "materialization is disabled until the operator explicitly acknowledges "
            "the unresolved upstream license for local-only use"
        )
    source_path = Path(source_urdf)
    package_path = Path(package_root)
    destination = Path(output_root)
    if destination.exists():
        raise ContractError(f"output already exists and will not be overwritten: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)

    joint_order = list(selected_joint_order)
    gripper_joints = list(physical_gripper_joints)
    plan = plan_fixed_base_asset(source_path, package_path, root_link, joint_order, robot_name)
    source_root = _parse_source(source_path)
    selected_links, selected_joints = _selection(source_root, root_link, joint_order)

    with tempfile.TemporaryDirectory(prefix=f".{destination.name}.staging-", dir=destination.parent) as stage_name:
        stage = Path(stage_name)
        urdf_dir = stage / "urdf"
        mesh_dir = stage / "meshes"
        urdf_dir.mkdir()
        mesh_dir.mkdir()

        output_robot = ET.Element("robot", {"name": robot_name})
        for material in source_root.findall("material"):
            output_robot.append(copy.deepcopy(material))
        copied_meshes: dict[str, str] = {}
        for link in selected_links:
            for mesh in link.findall(".//mesh"):
                uri = mesh.get("filename")
                resolved = _resolve_mesh(uri, package_path)
                target = mesh_dir / resolved.name
                if not target.exists():
                    shutil.copy2(resolved, target)
                copied_meshes[resolved.name] = _sha256(target)
                mesh.set("filename", f"../meshes/{resolved.name}")
            output_robot.append(link)
        for joint in selected_joints:
            output_robot.append(joint)

        ET.indent(output_robot, space="  ")
        output_urdf = urdf_dir / "mantis_fixed_base.urdf"
        ET.ElementTree(output_robot).write(output_urdf, encoding="utf-8", xml_declaration=True)

        joint_limits_path = stage / "joint_limits.json"
        joint_limits_path.write_text(
            json.dumps(plan["joint_limits"], indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        audit = audit_urdf(
            output_urdf,
            [name for name in joint_order if name not in set(gripper_joints)],
            gripper_joints,
            urdf_dir,
        )
        if not audit["genesis_import_gate_pass"]:
            raise ContractError(f"generated asset failed structural audit: {audit['issues']}")
        # The audit runs inside the atomic staging directory. Persist a portable
        # path instead of leaking a temporary path that disappears after rename.
        audit["urdf"] = "urdf/mantis_fixed_base.urdf"

        manifest = {
            **plan,
            "materialized": True,
            "distribution_allowed": False,
            "license_acknowledgement": "operator_acknowledged_unresolved_license_for_local_use",
            "output_urdf": "urdf/mantis_fixed_base.urdf",
            "output_urdf_sha256": _sha256(output_urdf),
            "joint_limits_sha256": _sha256(joint_limits_path),
            "mesh_sha256": dict(sorted(copied_meshes.items())),
            "structural_audit": audit,
        }
        (stage / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.rename(stage, destination)
    return manifest
