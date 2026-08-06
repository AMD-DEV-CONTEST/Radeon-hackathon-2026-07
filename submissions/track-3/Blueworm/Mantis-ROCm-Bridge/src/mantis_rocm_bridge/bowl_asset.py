"""License-checked, non-overwriting RoboTwin bowl asset materialization."""

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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_bowl_source(source_root: str | Path, plan: dict[str, Any]) -> dict[str, str]:
    root = Path(source_root)
    if plan.get("status") != "licensed_ready_to_materialize":
        raise ContractError("bowl asset plan is not licensed for materialization")
    source = plan.get("source", {})
    if source.get("license") != "MIT" or not source.get("dataset_revision"):
        raise ContractError("bowl source must have a pinned MIT dataset revision")
    files = plan.get("files")
    if not isinstance(files, dict) or set(files) != {"visual", "collision", "metadata", "license"}:
        raise ContractError("bowl asset plan must define visual, collision, metadata, and license")
    hashes: dict[str, str] = {}
    for role, spec in files.items():
        path = root / spec["path"]
        if not path.is_file():
            raise ContractError(f"bowl source file is missing: {path}")
        digest = _sha256(path)
        if digest != spec.get("sha256"):
            raise ContractError(f"bowl source hash mismatch for {role}")
        hashes[role] = digest
    for role in ("visual", "collision"):
        path = root / files[role]["path"]
        if path.read_bytes()[:4] != b"glTF":
            raise ContractError(f"bowl {role} is not a binary glTF file")
    license_text = (root / files["license"]["path"]).read_text(encoding="utf-8")
    if "MIT License" not in license_text or "Copyright (c) 2025 Tianxing Chen" not in license_text:
        raise ContractError("bowl source license content does not match the frozen MIT attribution")
    metadata = json.loads((root / files["metadata"]["path"]).read_text(encoding="utf-8"))
    if metadata.get("scale") != plan.get("geometry", {}).get("scale_xyz"):
        raise ContractError("bowl metadata scale disagrees with the materialization plan")
    return hashes


def _build_urdf(plan: dict[str, Any]) -> ET.Element:
    physics = plan["source_physics_receipt"]
    scale = " ".join(str(value) for value in plan["geometry"]["scale_xyz"])
    robot = ET.Element("robot", {"name": plan["asset_id"]})
    link = ET.SubElement(robot, "link", {"name": "bowl_link"})
    inertial = ET.SubElement(link, "inertial")
    ET.SubElement(
        inertial,
        "origin",
        {
            "xyz": " ".join(str(value) for value in physics["center_of_mass_xyz_m"]),
            "rpy": " ".join(str(value) for value in physics["principal_frame_rpy_rad"]),
        },
    )
    ET.SubElement(inertial, "mass", {"value": str(physics["mass_kg"])})
    inertia = physics["principal_inertia_kg_m2"]
    ET.SubElement(
        inertial,
        "inertia",
        {
            "ixx": str(inertia[0]),
            "ixy": "0",
            "ixz": "0",
            "iyy": str(inertia[1]),
            "iyz": "0",
            "izz": str(inertia[2]),
        },
    )
    visual = ET.SubElement(link, "visual", {"name": "source_visual"})
    visual_geometry = ET.SubElement(visual, "geometry")
    ET.SubElement(visual_geometry, "mesh", {"filename": "../visual/base3.glb", "scale": scale})
    collision = ET.SubElement(link, "collision", {"name": "source_multiple_convex_collision"})
    collision_geometry = ET.SubElement(collision, "geometry")
    ET.SubElement(
        collision_geometry,
        "mesh",
        {"filename": "../collision/base3.glb", "scale": scale},
    )
    ET.indent(robot, space="  ")
    return robot


def materialize_bowl_asset(
    source_root: str | Path,
    output_root: str | Path,
    plan: dict[str, Any],
) -> dict[str, Any]:
    root = Path(source_root)
    destination = Path(output_root)
    if destination.exists():
        raise ContractError(f"output already exists and will not be overwritten: {destination}")
    hashes = validate_bowl_source(root, plan)
    destination.parent.mkdir(parents=True, exist_ok=True)
    files = plan["files"]
    with tempfile.TemporaryDirectory(prefix=f".{destination.name}.staging-", dir=destination.parent) as name:
        stage = Path(name)
        for directory in ("visual", "collision", "metadata", "urdf", "THIRD_PARTY_LICENSES"):
            (stage / directory).mkdir()
        shutil.copy2(root / files["visual"]["path"], stage / "visual/base3.glb")
        shutil.copy2(root / files["collision"]["path"], stage / "collision/base3.glb")
        shutil.copy2(root / files["metadata"]["path"], stage / "metadata/model_data3.json")
        shutil.copy2(root / files["license"]["path"], stage / "THIRD_PARTY_LICENSES/RoboTwin-MIT.txt")
        urdf_path = stage / plan["materialization"]["output_urdf"]
        ET.ElementTree(_build_urdf(plan)).write(urdf_path, encoding="utf-8", xml_declaration=True)
        output_files = [
            "visual/base3.glb",
            "collision/base3.glb",
            "metadata/model_data3.json",
            "urdf/robotwin_002_bowl_model3.urdf",
            "THIRD_PARTY_LICENSES/RoboTwin-MIT.txt",
        ]
        manifest = {
            "schema_version": 1,
            "asset_id": plan["asset_id"],
            "materialized": True,
            "distribution_allowed": True,
            "source_dataset": plan["source"],
            "source_sha256": hashes,
            "output_sha256": {path: _sha256(stage / path) for path in output_files},
            "output_urdf": plan["materialization"]["output_urdf"],
            "source_physics_receipt": plan["source_physics_receipt"],
        }
        (stage / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.rename(stage, destination)
    return manifest


def materialize_bowl_collision_stl(
    input_root: str | Path,
    output_root: str | Path,
    plan: dict[str, Any],
) -> dict[str, Any]:
    """Expand the pinned multi-convex GLB into explicit STL collision parts."""
    source = Path(input_root)
    destination = Path(output_root)
    if destination.exists():
        raise ContractError(f"output already exists and will not be overwritten: {destination}")
    manifest_path = source / "manifest.json"
    if not manifest_path.is_file():
        raise ContractError("input bowl materialization has no manifest")
    parent_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        parent_manifest.get("materialized") is not True
        or parent_manifest.get("distribution_allowed") is not True
    ):
        raise ContractError("input bowl materialization is not licensed for redistribution")
    expected_source_hashes = {
        role: spec["sha256"] for role, spec in plan["files"].items()
    }
    if parent_manifest.get("source_sha256") != expected_source_hashes:
        raise ContractError("input bowl materialization is not derived from the pinned source")
    parent_outputs = parent_manifest.get("output_sha256", {})
    if not isinstance(parent_outputs, dict) or not parent_outputs:
        raise ContractError("input bowl materialization has no output hash inventory")
    for relative, expected_hash in parent_outputs.items():
        path = source / relative
        if not path.is_file() or _sha256(path) != expected_hash:
            raise ContractError(f"input bowl materialization hash mismatch: {relative}")

    try:
        import trimesh
    except ImportError as exc:
        raise ContractError("STL collision conversion requires trimesh") from exc

    collision_glb = source / "collision/base3.glb"
    scene = trimesh.load(collision_glb, force="scene")
    nodes = sorted(scene.graph.nodes_geometry)
    if len(nodes) != 24:
        raise ContractError(
            f"pinned bowl collision GLB must contain 24 convex parts, got {len(nodes)}"
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f".{destination.name}.staging-", dir=destination.parent
    ) as name:
        stage = Path(name)
        shutil.copytree(source, stage, dirs_exist_ok=True)
        collision_stl = stage / "collision_stl"
        collision_stl.mkdir()
        part_paths: list[str] = []
        part_rows: list[dict[str, Any]] = []
        for index, node in enumerate(nodes):
            transform, geometry_name = scene.graph[node]
            mesh = scene.geometry[geometry_name].copy()
            mesh.apply_transform(transform)
            if len(mesh.vertices) == 0 or len(mesh.faces) == 0:
                raise ContractError(f"empty collision component: {node}")
            relative = f"collision_stl/part_{index:02d}.stl"
            mesh.export(stage / relative, file_type="stl")
            part_paths.append(relative)
            part_rows.append(
                {
                    "part": relative,
                    "source_node": str(node),
                    "source_geometry": str(geometry_name),
                    "vertices": int(len(mesh.vertices)),
                    "faces": int(len(mesh.faces)),
                    "bounds_unscaled": mesh.bounds.tolist(),
                }
            )

        urdf_path = stage / parent_manifest["output_urdf"]
        tree = ET.parse(urdf_path)
        robot = tree.getroot()
        link = robot.find("./link[@name='bowl_link']")
        if link is None:
            raise ContractError("materialized bowl URDF has no bowl_link")
        collisions = list(link.findall("collision"))
        if len(collisions) != 1:
            raise ContractError("materialized bowl URDF must have one source collision")
        source_mesh = collisions[0].find("./geometry/mesh")
        if source_mesh is None or source_mesh.get("filename") != "../collision/base3.glb":
            raise ContractError("materialized bowl URDF collision source changed")
        scale = source_mesh.get("scale")
        for collision in collisions:
            link.remove(collision)
        for index, relative in enumerate(part_paths):
            collision = ET.SubElement(
                link,
                "collision",
                {"name": f"source_convex_collision_part_{index:02d}"},
            )
            geometry = ET.SubElement(collision, "geometry")
            ET.SubElement(
                geometry,
                "mesh",
                {"filename": f"../{relative}", "scale": str(scale)},
            )
        ET.indent(robot, space="  ")
        tree.write(urdf_path, encoding="utf-8", xml_declaration=True)

        output_files = sorted(
            path.relative_to(stage).as_posix()
            for path in stage.rglob("*")
            if path.is_file() and path.name != "manifest.json"
        )
        manifest = {
            "schema_version": 2,
            "asset_id": parent_manifest["asset_id"],
            "materialized": True,
            "distribution_allowed": True,
            "source_dataset": parent_manifest["source_dataset"],
            "source_sha256": parent_manifest["source_sha256"],
            "parent_manifest_sha256": _sha256(manifest_path),
            "collision_representation": "source_multiple_convex_stl_parts",
            "collision_conversion": {
                "source": "collision/base3.glb",
                "source_sha256": _sha256(collision_glb),
                "component_count": len(part_paths),
                "parts": part_rows,
                "scale_xyz": plan["geometry"]["scale_xyz"],
                "trimesh_version": getattr(trimesh, "__version__", "unknown"),
                "intent": "avoid Genesis legacy URDF fallback while preserving source multi-convex components",
            },
            "output_sha256": {path: _sha256(stage / path) for path in output_files},
            "output_urdf": parent_manifest["output_urdf"],
            "source_physics_receipt": parent_manifest["source_physics_receipt"],
        }
        (stage / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.rename(stage, destination)
    return manifest
