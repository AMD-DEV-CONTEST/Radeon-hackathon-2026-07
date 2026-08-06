"""Deterministic, fail-closed URDF inspection and robot-port compilation.

The compiler emits a bounded, read-only Genesis runtime probe in addition to
static contracts.  It still does not choose a controller, expand Xacro, train a
policy, or claim that an ACT policy will work.  Safety-critical semantics must
be supplied by an explicit sidecar.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import tempfile
import xml.etree.ElementTree as ET
from itertools import combinations
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .contracts import ContractError


SCHEMA_VERSION = 1
BUNDLE_SCHEMA_VERSION = 2
MAX_URDF_BYTES = 16 * 1024 * 1024
SUPPORTED_JOINT_TYPES = {"fixed", "revolute", "continuous", "prismatic"}
ACTUATED_JOINT_TYPES = {"revolute", "continuous", "prismatic"}
ARM_DOF = {6, 7}
IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]*$")
SIDE_IDS = {"arm", "left", "right"}
QUALITY_STATES = [
    "URDF_ANALYZED",
    "PORT_COMPILED",
    "RUNTIME_PORT_VERIFIED",
    "ROCM_TUNING_MEASURED",
    "DATASET_ADMITTED",
    "ACT_TRAINED",
    "ACT_OPENLOOP_PASS",
    "ACT_CLOSEDLOOP_PASS",
    "AMD_DEPLOYABLE",
]
BUNDLE_FILENAMES = [
    "embodiment-ir.json",
    "morphology-report.json",
    "robot-port-profile.json",
    "genesis-port-spec.json",
    "run-genesis-port.py",
    "lerobot-features.json",
    "act-training.json",
    "rocm-runtime.json",
    "rocm-tuning-plan.json",
    "quality-gates.json",
    "bundle-manifest.json",
]


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _finite_float(raw: str, context: str) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ContractError(f"{context} must be a finite number") from exc
    if not math.isfinite(value):
        raise ContractError(f"{context} must be a finite number")
    return value


def _vector(raw: str | None, length: int, context: str, default: str) -> list[float]:
    values = (raw if raw is not None else default).split()
    if len(values) != length:
        raise ContractError(f"{context} must contain {length} numbers")
    return [_finite_float(value, context) for value in values]


def _required_name(element: ET.Element, context: str) -> str:
    value = element.get("name")
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ContractError(f"{context} name must match {IDENTIFIER.pattern}")
    return value


def _exact_keys(value: Mapping[str, Any], expected: set[str], context: str) -> None:
    actual = set(value)
    if actual != expected:
        raise ContractError(
            f"{context} keys disagree; "
            f"missing={sorted(expected - actual)}, extra={sorted(actual - expected)}"
        )


def _mapping(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError(f"{context} must be an object")
    return value


def _text(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{context} must be a non-empty string")
    return value


def _identifier(value: Any, context: str) -> str:
    result = _text(value, context)
    if not IDENTIFIER.fullmatch(result):
        raise ContractError(f"{context} must match {IDENTIFIER.pattern}")
    return result


def _positive_number(value: Any, context: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractError(f"{context} must be a positive number")
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise ContractError(f"{context} must be a positive number")
    return result


def _positive_int(value: Any, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ContractError(f"{context} must be a positive integer")
    return value


def _unique_strings(value: Any, context: str, *, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list) or (not value and not allow_empty):
        raise ContractError(f"{context} must be a list")
    if not all(isinstance(item, str) and item for item in value):
        raise ContractError(f"{context} must contain non-empty strings")
    if len(value) != len(set(value)):
        raise ContractError(f"{context} contains duplicates")
    return list(value)


def _load_json_object(path: str | Path, context: str) -> dict[str, Any]:
    source = Path(path)
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot load {context}: {exc}") from exc
    if not isinstance(value, dict):
        raise ContractError(f"{context} root must be an object")
    return value


def _longest_common_prefix(left: Sequence[str], right: Sequence[str]) -> int:
    count = 0
    for left_item, right_item in zip(left, right):
        if left_item != right_item:
            break
        count += 1
    return count


def _side_evidence(names: Iterable[str]) -> set[str]:
    tokens = re.split(r"[^a-z0-9]+", " ".join(names).lower())
    found: set[str] = set()
    for token in tokens:
        if token in {"left", "l"}:
            found.add("left")
        elif token in {"right", "r"}:
            found.add("right")
    return found


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _write_json_exclusive(path: Path, value: Any) -> None:
    with path.open("xb") as stream:
        stream.write(_json_bytes(value))


def _validate_mimic_graph(joints: Mapping[str, dict[str, Any]]) -> None:
    mimic_parent: dict[str, str] = {}
    for name, joint in joints.items():
        target = joint["mimic"]["joint"] if joint["mimic"] is not None else None
        if target is None:
            continue
        if target not in joints:
            raise ContractError(f"joint {name} mimics unknown joint {target}")
        if target == name:
            raise ContractError(f"joint {name} cannot mimic itself")
        mimic_parent[name] = target
    for start in sorted(mimic_parent):
        seen: set[str] = set()
        current = start
        while current in mimic_parent:
            if current in seen:
                raise ContractError("cyclic mimic relation")
            seen.add(current)
            current = mimic_parent[current]


def _parse_urdf(source: Path) -> tuple[dict[str, Any], bytes]:
    try:
        data = source.read_bytes()
    except OSError as exc:
        raise ContractError(f"cannot read URDF: {exc}") from exc
    if not data:
        raise ContractError("URDF is empty")
    if len(data) > MAX_URDF_BYTES:
        raise ContractError(f"URDF exceeds {MAX_URDF_BYTES} byte limit")
    upper = data.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise ContractError("DOCTYPE and ENTITY declarations are forbidden")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise ContractError(f"malformed URDF XML: {exc}") from exc
    if root.tag != "robot":
        raise ContractError("URDF root element must be <robot>")
    robot_name = _required_name(root, "robot")

    links: dict[str, dict[str, Any]] = {}
    for element in root.findall("link"):
        name = _required_name(element, "link")
        if name in links:
            raise ContractError(f"duplicate link name: {name}")
        links[name] = {"name": name}
    if not links:
        raise ContractError("URDF must contain at least one link")

    joints: dict[str, dict[str, Any]] = {}
    child_parent: dict[str, str] = {}
    children: dict[str, list[str]] = {name: [] for name in links}
    for element in root.findall("joint"):
        name = _required_name(element, "joint")
        if name in joints:
            raise ContractError(f"duplicate joint name: {name}")
        joint_type = element.get("type")
        if joint_type not in SUPPORTED_JOINT_TYPES:
            raise ContractError(
                f"unsupported joint type for {name}: {joint_type!r}; "
                f"supported={sorted(SUPPORTED_JOINT_TYPES)}"
            )
        parent_element = element.find("parent")
        child_element = element.find("child")
        if parent_element is None or child_element is None:
            raise ContractError(f"joint {name} requires parent and child")
        parent = parent_element.get("link")
        child = child_element.get("link")
        if parent not in links or child not in links:
            raise ContractError(f"joint {name} references an unknown link")
        if parent == child:
            raise ContractError(f"joint {name} cannot connect a link to itself")
        if child in child_parent:
            raise ContractError(
                f"parallel or closed-loop kinematics: link {child} has multiple parents"
            )
        child_parent[child] = parent
        children[parent].append(name)

        origin = element.find("origin")
        axis = element.find("axis")
        limit = element.find("limit")
        mimic = element.find("mimic")
        limit_record: dict[str, float] | None = None
        if joint_type in {"revolute", "prismatic"}:
            if limit is None:
                raise ContractError(f"joint {name} requires limits")
            required_limit = ("lower", "upper", "effort", "velocity")
            if any(limit.get(field) is None for field in required_limit):
                raise ContractError(f"joint {name} limit requires {required_limit}")
            limit_record = {
                field: _finite_float(limit.get(field, ""), f"joint {name} limit {field}")
                for field in required_limit
            }
            if limit_record["lower"] > limit_record["upper"]:
                raise ContractError(f"joint {name} has lower limit above upper limit")
            if limit_record["effort"] <= 0 or limit_record["velocity"] <= 0:
                raise ContractError(f"joint {name} effort and velocity must be positive")
        elif joint_type == "continuous":
            if limit is None or limit.get("effort") is None or limit.get("velocity") is None:
                raise ContractError(f"continuous joint {name} requires effort and velocity")
            limit_record = {
                "effort": _finite_float(limit.get("effort", ""), f"joint {name} effort"),
                "velocity": _finite_float(
                    limit.get("velocity", ""), f"joint {name} velocity"
                ),
            }
            if limit_record["effort"] <= 0 or limit_record["velocity"] <= 0:
                raise ContractError(f"joint {name} effort and velocity must be positive")

        mimic_record: dict[str, Any] | None = None
        if mimic is not None:
            target = mimic.get("joint")
            if not isinstance(target, str) or not target:
                raise ContractError(f"joint {name} mimic requires a target joint")
            mimic_record = {
                "joint": target,
                "multiplier": _finite_float(
                    mimic.get("multiplier", "1"), f"joint {name} mimic multiplier"
                ),
                "offset": _finite_float(
                    mimic.get("offset", "0"), f"joint {name} mimic offset"
                ),
            }

        joints[name] = {
            "name": name,
            "type": joint_type,
            "parent": parent,
            "child": child,
            "origin_xyz": _vector(
                origin.get("xyz") if origin is not None else None,
                3,
                f"joint {name} origin xyz",
                "0 0 0",
            ),
            "origin_rpy": _vector(
                origin.get("rpy") if origin is not None else None,
                3,
                f"joint {name} origin rpy",
                "0 0 0",
            ),
            "axis": (
                _vector(
                    axis.get("xyz") if axis is not None else None,
                    3,
                    f"joint {name} axis",
                    "1 0 0",
                )
                if joint_type != "fixed"
                else None
            ),
            "limit": limit_record,
            "mimic": mimic_record,
        }
        children[parent].append(name)

    # Rebuild because the first append above exists only for topology bookkeeping.
    children = {name: [] for name in links}
    for name, joint in joints.items():
        children[joint["parent"]].append(name)
    for value in children.values():
        value.sort()

    roots = sorted(set(links) - set(child_parent))
    if len(roots) != 1:
        raise ContractError(
            f"URDF must be one connected tree with exactly one root; roots={roots}"
        )
    root_link = roots[0]
    visited: set[str] = set()
    visiting: set[str] = set()

    def visit(link: str) -> None:
        if link in visiting:
            raise ContractError("cyclic URDF topology")
        if link in visited:
            return
        visiting.add(link)
        for joint_name in children[link]:
            visit(joints[joint_name]["child"])
        visiting.remove(link)
        visited.add(link)

    visit(root_link)
    if visited != set(links):
        missing = sorted(set(links) - visited)
        raise ContractError(f"disconnected URDF links: {missing}")
    _validate_mimic_graph(joints)

    parsed = {
        "robot_name": robot_name,
        "root_link": root_link,
        "links": [links[name] for name in sorted(links)],
        "joints": [joints[name] for name in sorted(joints)],
        "children": children,
    }
    return parsed, data


def _path_inventory(parsed: Mapping[str, Any]) -> list[dict[str, Any]]:
    joints = {joint["name"]: joint for joint in parsed["joints"]}
    paths: list[dict[str, Any]] = []

    def walk(link: str, joint_path: list[str], link_path: list[str]) -> None:
        child_joints = parsed["children"][link]
        if not child_joints:
            independent = [
                name
                for name in joint_path
                if joints[name]["type"] in ACTUATED_JOINT_TYPES
                and joints[name]["mimic"] is None
            ]
            paths.append(
                {
                    "end_link": link,
                    "joint_path": list(joint_path),
                    "link_path": list(link_path),
                    "independent_actuated_joints": independent,
                }
            )
            return
        for joint_name in child_joints:
            child = joints[joint_name]["child"]
            walk(child, [*joint_path, joint_name], [*link_path, child])

    walk(parsed["root_link"], [], [parsed["root_link"]])
    unique: dict[tuple[str, ...], dict[str, Any]] = {}
    for item in paths:
        key = tuple(item["independent_actuated_joints"])
        current = unique.get(key)
        if current is None or item["end_link"] < current["end_link"]:
            unique[key] = item
    return [unique[key] for key in sorted(unique)]


def _infer_morphology(parsed: Mapping[str, Any]) -> dict[str, Any]:
    paths = _path_inventory(parsed)
    bimanual: list[dict[str, Any]] = []
    for left, right in combinations(paths, 2):
        left_seq = left["independent_actuated_joints"]
        right_seq = right["independent_actuated_joints"]
        prefix_count = _longest_common_prefix(left_seq, right_seq)
        left_arm = left_seq[prefix_count:]
        right_arm = right_seq[prefix_count:]
        if len(left_arm) not in ARM_DOF or len(right_arm) not in ARM_DOF:
            continue
        left_evidence = _side_evidence([*left_arm, left["end_link"]])
        right_evidence = _side_evidence([*right_arm, right["end_link"]])
        named_opposites = (
            ("left" in left_evidence and "right" in right_evidence)
            or ("right" in left_evidence and "left" in right_evidence)
        )
        arms = [
            {
                "candidate_id": "arm_0",
                "joint_names": left_arm,
                "dof": len(left_arm),
                "end_link": left["end_link"],
                "side_candidates": sorted(left_evidence),
            },
            {
                "candidate_id": "arm_1",
                "joint_names": right_arm,
                "dof": len(right_arm),
                "end_link": right["end_link"],
                "side_candidates": sorted(right_evidence),
            },
        ]
        arms.sort(key=lambda item: item["joint_names"])
        bimanual.append(
            {
                "arm_count": 2,
                "dof_per_arm": [arm["dof"] for arm in arms],
                "arms": arms,
                "shared_actuated_prefix": left_seq[:prefix_count],
                "named_left_right_pair": named_opposites,
                "score": (
                    100 * int(named_opposites)
                    + 10 * int(len(left_arm) == len(right_arm))
                    - prefix_count
                ),
            }
        )
    bimanual.sort(
        key=lambda item: (
            -item["score"],
            item["dof_per_arm"],
            [arm["joint_names"] for arm in item["arms"]],
        )
    )

    single: list[dict[str, Any]] = []
    for path in paths:
        sequence = path["independent_actuated_joints"]
        if len(sequence) in ARM_DOF:
            side = _side_evidence([*sequence, path["end_link"]])
            single.append(
                {
                    "arm_count": 1,
                    "dof_per_arm": [len(sequence)],
                    "arms": [
                        {
                            "candidate_id": "arm",
                            "joint_names": sequence,
                            "dof": len(sequence),
                            "end_link": path["end_link"],
                            "side_candidates": sorted(side),
                        }
                    ],
                    "shared_actuated_prefix": [],
                    "named_left_right_pair": False,
                    "score": 10,
                }
            )
    single.sort(key=lambda item: (item["dof_per_arm"], item["arms"][0]["joint_names"]))

    candidates = [*bimanual, *single]
    selected = candidates[0] if candidates else None
    ambiguous = False
    if selected is not None:
        same_rank = [
            item
            for item in candidates
            if item["arm_count"] == selected["arm_count"]
            and item["score"] == selected["score"]
            and item["dof_per_arm"] == selected["dof_per_arm"]
        ]
        ambiguous = len(same_rank) > 1 or (
            selected["arm_count"] == 2 and not selected["named_left_right_pair"]
        )
    questions: list[str] = []
    blockers: list[str] = []
    if selected is None:
        blockers.append("no supported fixed-base 6/7-DoF arm morphology found")
    elif ambiguous:
        questions.append("confirm selected arm chains and left/right assignment in sidecar")
    questions.extend(
        [
            "provide controller mode and control frequency",
            "provide workspace, joint projection, emergency-stop, and safety rules",
            "provide camera roles and calibration outside the URDF",
            "provide task reset distribution and success predicate",
            "provide gripper open-close convention when a gripper is present",
            "declare source asset redistribution rights separately",
        ]
    )
    confidence = (
        "none"
        if selected is None
        else "high"
        if selected["arm_count"] == 1 or selected["named_left_right_pair"]
        else "medium"
    )
    return {
        "supported": selected is not None,
        "base": "fixed",
        "arm_count": selected["arm_count"] if selected else None,
        "dof_per_arm": selected["dof_per_arm"] if selected else [],
        "selected_candidate": selected,
        "candidate_count": len(candidates),
        "ambiguous": ambiguous,
        "confidence": confidence,
        "questions": questions,
        "blockers": blockers,
    }


def inspect_urdf(path: str | Path) -> dict[str, Any]:
    """Inspect a strict URDF and return a deterministic Embodiment IR."""

    source = Path(path)
    parsed, raw = _parse_urdf(source)
    morphology = _infer_morphology(parsed)
    joints = parsed["joints"]
    movable = [
        joint
        for joint in joints
        if joint["type"] in ACTUATED_JOINT_TYPES and joint["mimic"] is None
    ]
    mimic = [joint for joint in joints if joint["mimic"] is not None]
    ir = {
        "schema_version": SCHEMA_VERSION,
        "kind": "embodiment_ir",
        "source_urdf": {
            "sha256": _sha256_bytes(raw),
            "size_bytes": len(raw),
        },
        "robot": {
            "name": parsed["robot_name"],
            "root_link": parsed["root_link"],
            "fixed_base": True,
            "link_count": len(parsed["links"]),
            "joint_count": len(joints),
            "independent_actuated_joint_count": len(movable),
            "mimic_joint_count": len(mimic),
        },
        "links": [item["name"] for item in parsed["links"]],
        "joints": joints,
        "morphology": morphology,
        "unresolved_semantics": list(morphology["questions"]),
        "claim_boundary": (
            "Static URDF morphology inspection only. Controller, safety, cameras, "
            "gripper convention, task semantics, runtime execution, ACT accuracy, "
            "AMD optimization, and asset rights are not established."
        ),
    }
    return ir


def validate_semantic_sidecar(
    value: Mapping[str, Any], ir: Mapping[str, Any]
) -> dict[str, Any]:
    """Validate explicit execution semantics against the inspected URDF."""

    sidecar = _mapping(value, "semantic sidecar")
    _exact_keys(
        sidecar,
        {
            "schema_version",
            "robot_id",
            "fixed_base",
            "arms",
            "grippers",
            "controller",
            "safety",
            "cameras",
            "asset_rights",
        },
        "semantic sidecar",
    )
    if sidecar["schema_version"] != 1:
        raise ContractError("semantic sidecar schema_version must be 1")
    _identifier(sidecar["robot_id"], "semantic sidecar.robot_id")
    if sidecar["fixed_base"] is not True:
        raise ContractError("MVP requires semantic sidecar.fixed_base=true")
    arms = sidecar["arms"]
    expected_count = ir["morphology"]["arm_count"]
    if not isinstance(arms, list) or len(arms) != expected_count:
        raise ContractError(f"semantic sidecar requires exactly {expected_count} arms")
    available_joint_names = {joint["name"] for joint in ir["joints"]}
    available_links = set(ir["links"])
    selected_candidate = ir["morphology"]["selected_candidate"]
    inferred_chains = {
        tuple(arm["joint_names"]): arm["end_link"]
        for arm in selected_candidate["arms"]
    }
    seen_joint_names: set[str] = set()
    seen_sides: set[str] = set()
    validated_arms: list[dict[str, Any]] = []
    for index, raw_arm in enumerate(arms):
        context = f"semantic sidecar.arms[{index}]"
        arm = _mapping(raw_arm, context)
        _exact_keys(
            arm, {"side", "joint_names", "end_effector_link", "ik_solver"}, context
        )
        side = _text(arm["side"], f"{context}.side")
        if side not in SIDE_IDS:
            raise ContractError(f"{context}.side must be one of {sorted(SIDE_IDS)}")
        if expected_count == 1 and side != "arm":
            raise ContractError("single-arm side must be 'arm'")
        if expected_count == 2 and side not in {"left", "right"}:
            raise ContractError("bimanual sides must be left and right")
        if side in seen_sides:
            raise ContractError("semantic sidecar arm sides must be unique")
        seen_sides.add(side)
        names = _unique_strings(arm["joint_names"], f"{context}.joint_names")
        if len(names) not in ARM_DOF:
            raise ContractError(f"{context} must contain 6 or 7 arm joints")
        unknown = sorted(set(names) - available_joint_names)
        if unknown:
            raise ContractError(f"{context} contains unknown joints: {unknown}")
        overlap = sorted(set(names) & seen_joint_names)
        if overlap:
            raise ContractError(f"arm joint chains overlap: {overlap}")
        seen_joint_names.update(names)
        end_link = _text(arm["end_effector_link"], f"{context}.end_effector_link")
        if end_link not in available_links:
            raise ContractError(f"{context} end-effector link is unknown")
        inferred_end_link = inferred_chains.get(tuple(names))
        if inferred_end_link is None:
            raise ContractError(
                f"{context} joint chain does not match the selected morphology candidate"
            )
        if inferred_end_link != end_link:
            raise ContractError(
                f"{context} end-effector link does not match inferred chain endpoint"
            )
        ik_solver = _text(arm["ik_solver"], f"{context}.ik_solver")
        if ik_solver != "required_not_implemented":
            raise ContractError(
                f"{context}.ik_solver must remain required_not_implemented in MVP"
            )
        validated_arms.append(
            {
                "side": side,
                "joint_names": names,
                "end_effector_link": end_link,
                "ik_solver": ik_solver,
            }
        )
    if expected_count == 2 and seen_sides != {"left", "right"}:
        raise ContractError("bimanual sidecar must declare left and right")
    validated_arms.sort(key=lambda item: item["side"])

    grippers = sidecar["grippers"]
    if not isinstance(grippers, list):
        raise ContractError("semantic sidecar.grippers must be a list")
    validated_grippers: list[dict[str, Any]] = []
    for index, raw_gripper in enumerate(grippers):
        context = f"semantic sidecar.grippers[{index}]"
        gripper = _mapping(raw_gripper, context)
        _exact_keys(
            gripper,
            {"side", "joint_names", "open_value", "closed_value", "force_limit"},
            context,
        )
        side = _text(gripper["side"], f"{context}.side")
        if side not in seen_sides:
            raise ContractError(f"{context}.side has no corresponding arm")
        names = _unique_strings(gripper["joint_names"], f"{context}.joint_names")
        unknown = sorted(set(names) - available_joint_names)
        if unknown:
            raise ContractError(f"{context} contains unknown joints: {unknown}")
        open_value = _finite_input(gripper["open_value"], f"{context}.open_value")
        closed_value = _finite_input(gripper["closed_value"], f"{context}.closed_value")
        if open_value == closed_value:
            raise ContractError(f"{context} open and closed values must differ")
        validated_grippers.append(
            {
                "side": side,
                "joint_names": names,
                "open_value": open_value,
                "closed_value": closed_value,
                "force_limit": _positive_number(
                    gripper["force_limit"], f"{context}.force_limit"
                ),
            }
        )
    if len({item["side"] for item in validated_grippers}) != len(validated_grippers):
        raise ContractError("at most one gripper contract is allowed per arm")
    validated_grippers.sort(key=lambda item: item["side"])

    controller = _mapping(sidecar["controller"], "semantic sidecar.controller")
    _exact_keys(controller, {"mode", "control_hz"}, "semantic sidecar.controller")
    mode = _text(controller["mode"], "semantic sidecar.controller.mode")
    if mode not in {"joint_position", "joint_velocity"}:
        raise ContractError("controller.mode must be joint_position or joint_velocity")
    validated_controller = {
        "mode": mode,
        "control_hz": _positive_number(
            controller["control_hz"], "semantic sidecar.controller.control_hz"
        ),
    }

    safety = _mapping(sidecar["safety"], "semantic sidecar.safety")
    _exact_keys(
        safety,
        {
            "joint_limit_projection",
            "workspace_bounds",
            "emergency_stop",
            "collision_policy",
        },
        "semantic sidecar.safety",
    )
    if safety["joint_limit_projection"] is not True:
        raise ContractError("joint_limit_projection must be true")
    bounds = _mapping(safety["workspace_bounds"], "safety.workspace_bounds")
    _exact_keys(bounds, {"min_xyz", "max_xyz"}, "safety.workspace_bounds")
    minimum = _finite_list(bounds["min_xyz"], 3, "safety.workspace_bounds.min_xyz")
    maximum = _finite_list(bounds["max_xyz"], 3, "safety.workspace_bounds.max_xyz")
    if any(low >= high for low, high in zip(minimum, maximum)):
        raise ContractError("workspace min_xyz must be below max_xyz")
    emergency_stop = _text(safety["emergency_stop"], "safety.emergency_stop")
    collision_policy = _text(safety["collision_policy"], "safety.collision_policy")

    cameras = sidecar["cameras"]
    if not isinstance(cameras, list) or not cameras:
        raise ContractError("semantic sidecar.cameras must be non-empty")
    validated_cameras: list[dict[str, Any]] = []
    for index, raw_camera in enumerate(cameras):
        context = f"semantic sidecar.cameras[{index}]"
        camera = _mapping(raw_camera, context)
        _exact_keys(
            camera, {"role", "calibration_ref", "width", "height"}, context
        )
        validated_cameras.append(
            {
                "role": _identifier(camera["role"], f"{context}.role"),
                "calibration_ref": _text(
                    camera["calibration_ref"], f"{context}.calibration_ref"
                ),
                "width": _positive_int(camera["width"], f"{context}.width"),
                "height": _positive_int(camera["height"], f"{context}.height"),
            }
        )
    roles = [item["role"] for item in validated_cameras]
    if len(roles) != len(set(roles)):
        raise ContractError("camera roles must be unique")
    validated_cameras.sort(key=lambda item: item["role"])

    asset_rights = _text(sidecar["asset_rights"], "semantic sidecar.asset_rights")
    if asset_rights not in {"external_reference_only", "redistribution_authorized"}:
        raise ContractError(
            "asset_rights must be external_reference_only or redistribution_authorized"
        )
    return {
        "schema_version": 1,
        "robot_id": sidecar["robot_id"],
        "fixed_base": True,
        "arms": validated_arms,
        "grippers": validated_grippers,
        "controller": validated_controller,
        "safety": {
            "joint_limit_projection": True,
            "workspace_bounds": {"min_xyz": minimum, "max_xyz": maximum},
            "emergency_stop": emergency_stop,
            "collision_policy": collision_policy,
        },
        "cameras": validated_cameras,
        "asset_rights": asset_rights,
    }


def _finite_input(value: Any, context: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractError(f"{context} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ContractError(f"{context} must be a finite number")
    return result


def _finite_list(value: Any, length: int, context: str) -> list[float]:
    if not isinstance(value, list) or len(value) != length:
        raise ContractError(f"{context} must contain exactly {length} numbers")
    return [_finite_input(item, context) for item in value]


def validate_task_pack(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the task/data/ACT inputs that a URDF cannot supply."""

    task = _mapping(value, "task pack")
    _exact_keys(
        task,
        {
            "schema_version",
            "task_id",
            "description",
            "camera_roles",
            "reset_contract",
            "success_contract",
            "dataset",
            "act",
        },
        "task pack",
    )
    if task["schema_version"] != 1:
        raise ContractError("task pack schema_version must be 1")
    task_id = _identifier(task["task_id"], "task pack.task_id")
    description = _text(task["description"], "task pack.description")
    camera_roles = _unique_strings(task["camera_roles"], "task pack.camera_roles")
    reset_contract = _text(task["reset_contract"], "task pack.reset_contract")
    success_contract = _text(task["success_contract"], "task pack.success_contract")

    dataset = _mapping(task["dataset"], "task pack.dataset")
    _exact_keys(
        dataset,
        {
            "expert_success_fraction",
            "failed_episodes_excluded",
            "unique_seeds_required",
            "coverage_strata",
            "normalization_per_embodiment",
        },
        "task pack.dataset",
    )
    success_fraction = _finite_input(
        dataset["expert_success_fraction"], "task pack.dataset.expert_success_fraction"
    )
    if success_fraction != 1.0:
        raise ContractError("dataset.expert_success_fraction must equal 1.0")
    for field in (
        "failed_episodes_excluded",
        "unique_seeds_required",
        "normalization_per_embodiment",
    ):
        if dataset[field] is not True:
            raise ContractError(f"task pack.dataset.{field} must be true")
    coverage_strata = _unique_strings(
        dataset["coverage_strata"], "task pack.dataset.coverage_strata"
    )

    act = _mapping(task["act"], "task pack.act")
    _exact_keys(
        act,
        {"chunk_size", "policy_call_budget", "training_seed", "evaluation_seeds"},
        "task pack.act",
    )
    evaluation_seeds = act["evaluation_seeds"]
    if not isinstance(evaluation_seeds, list) or len(evaluation_seeds) != 10:
        raise ContractError("task pack.act.evaluation_seeds must contain 10 seeds")
    if (
        not all(isinstance(item, int) and not isinstance(item, bool) for item in evaluation_seeds)
        or len(evaluation_seeds) != len(set(evaluation_seeds))
    ):
        raise ContractError("task pack.act.evaluation_seeds must be 10 unique integers")
    training_seed = act["training_seed"]
    if not isinstance(training_seed, int) or isinstance(training_seed, bool):
        raise ContractError("task pack.act.training_seed must be an integer")
    return {
        "schema_version": 1,
        "task_id": task_id,
        "description": description,
        "camera_roles": camera_roles,
        "reset_contract": reset_contract,
        "success_contract": success_contract,
        "dataset": {
            "expert_success_fraction": 1.0,
            "failed_episodes_excluded": True,
            "unique_seeds_required": True,
            "coverage_strata": coverage_strata,
            "normalization_per_embodiment": True,
        },
        "act": {
            "chunk_size": _positive_int(act["chunk_size"], "task pack.act.chunk_size"),
            "policy_call_budget": _positive_int(
                act["policy_call_budget"], "task pack.act.policy_call_budget"
            ),
            "training_seed": training_seed,
            "evaluation_seeds": list(evaluation_seeds),
        },
    }


def _policy_fields(
    arms: Sequence[Mapping[str, Any]], grippers: Sequence[Mapping[str, Any]]
) -> tuple[list[str], list[str], list[str]]:
    gripper_sides = {item["side"] for item in grippers}
    state: list[str] = []
    action: list[str] = []
    joint_auxiliary: list[str] = []
    for arm in arms:
        prefix = arm["side"]
        state.extend(
            [
                f"{prefix}.ee.position.x",
                f"{prefix}.ee.position.y",
                f"{prefix}.ee.position.z",
                f"{prefix}.ee.quaternion.x",
                f"{prefix}.ee.quaternion.y",
                f"{prefix}.ee.quaternion.z",
                f"{prefix}.ee.quaternion.w",
            ]
        )
        action.extend(
            [
                f"{prefix}.delta_translation.x",
                f"{prefix}.delta_translation.y",
                f"{prefix}.delta_translation.z",
                f"{prefix}.delta_rotation_axis_angle.x",
                f"{prefix}.delta_rotation_axis_angle.y",
                f"{prefix}.delta_rotation_axis_angle.z",
            ]
        )
        if prefix in gripper_sides:
            state.append(f"{prefix}.gripper.normalized")
            action.append(f"{prefix}.gripper.normalized")
        joint_auxiliary.extend(f"{prefix}.joint.{name}.position" for name in arm["joint_names"])
    return state, action, joint_auxiliary


def _generated_genesis_runner() -> str:
    """Return the deterministic, self-contained read-only Genesis probe."""

    return r'''#!/usr/bin/env python3
"""Generated read-only Genesis robot-port probe.

This file is intentionally self-contained.  It verifies the URDF before
importing Genesis, loads a fixed-base robot, maps the compiled arm joints,
steps without issuing commands, and writes one exclusive runtime receipt.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import platform
import sys
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def flatten_finite(value: Any) -> list[float]:
    if hasattr(value, "detach"):
        value = value.detach()
    if hasattr(value, "cpu"):
        value = value.cpu()
    if hasattr(value, "tolist"):
        value = value.tolist()
    result: list[float] = []

    def visit(item: Any) -> None:
        if isinstance(item, (list, tuple)):
            for child in item:
                visit(child)
            return
        number = float(item)
        if not math.isfinite(number):
            raise RuntimeError("robot state contains a non-finite value")
        result.append(number)

    visit(value)
    return result


def load_spec(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("Genesis port spec must be a JSON object")
    if value.get("schema_version") != 2 or value.get("kind") != "genesis_port_spec":
        raise RuntimeError("unsupported Genesis port spec")
    if value.get("fixed_base") is not True:
        raise RuntimeError("only fixed-base ports are admitted")
    if value.get("controller_commands_allowed") is not False:
        raise RuntimeError("runtime probe must prohibit controller commands")
    return value


def genesis_version(gs: Any) -> str:
    for distribution in ("genesis-world", "genesis"):
        try:
            return importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            pass
    return str(getattr(gs, "__version__", "unknown"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--spec",
        type=Path,
        default=Path(__file__).resolve().with_name("genesis-port-spec.json"),
    )
    parser.add_argument("--urdf", type=Path, required=True)
    parser.add_argument("--backend", choices=("cpu", "amdgpu"), required=True)
    parser.add_argument("--steps", type=int, default=2)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.steps < 1 or args.steps > 100:
        raise RuntimeError("--steps must be between 1 and 100")
    if args.output.exists():
        raise RuntimeError(f"refusing to overwrite output: {args.output}")

    spec = load_spec(args.spec.resolve())
    urdf = args.urdf.resolve(strict=True)
    actual_urdf_sha256 = sha256_file(urdf)
    if actual_urdf_sha256 != spec.get("urdf_sha256"):
        raise RuntimeError("URDF SHA-256 disagrees with the compiled port spec")

    torch = None
    device_receipt = {
        "strict_rocm": False,
        "torch_device": "cpu",
        "torch_version": None,
        "hip_version": None,
        "device_count": 0,
        "device_name": "CPU",
    }
    if args.backend == "amdgpu":
        import torch as imported_torch

        torch = imported_torch
        hip_version = getattr(torch.version, "hip", None)
        if not torch.cuda.is_available() or not hip_version:
            raise RuntimeError("strict ROCm runtime is unavailable")
        if torch.cuda.device_count() != 1:
            raise RuntimeError("strict ROCm probe requires exactly one visible GPU")
        device_name = str(torch.cuda.get_device_name(0))
        if "amd" not in device_name.lower() and "radeon" not in device_name.lower():
            raise RuntimeError("visible GPU is not identified as AMD/Radeon")
        device_receipt = {
            "strict_rocm": True,
            "torch_device": "cuda:0",
            "torch_version": str(torch.__version__),
            "hip_version": str(hip_version),
            "device_count": int(torch.cuda.device_count()),
            "device_name": device_name,
        }

    import genesis as gs

    backend = getattr(gs, args.backend, None)
    if backend is None:
        raise RuntimeError(f"Genesis backend is unavailable: {args.backend}")
    gs.init(backend=backend, seed=args.seed, logging_level="warning")
    scene = gs.Scene(
        sim_options=gs.options.SimOptions(dt=float(spec["simulation"]["dt"])),
        show_viewer=False,
    )
    robot = scene.add_entity(gs.morphs.URDF(file=str(urdf), fixed=True))
    scene.build()

    joint_order_by_arm = spec.get("joint_order_by_arm")
    if not isinstance(joint_order_by_arm, dict) or not joint_order_by_arm:
        raise RuntimeError("joint_order_by_arm is missing")
    joint_names: list[str] = []
    arm_sides: list[str] = []
    for side, names in joint_order_by_arm.items():
        if not isinstance(side, str) or not isinstance(names, list) or not names:
            raise RuntimeError("invalid joint_order_by_arm entry")
        arm_sides.append(side)
        joint_names.extend(names)
    if len(joint_names) != len(set(joint_names)):
        raise RuntimeError("arm joint mapping contains duplicates")

    dof_indices: list[int] = []
    for name in joint_names:
        joint = robot.get_joint(name)
        indices = getattr(joint, "dofs_idx_local", None)
        if indices is None or len(indices) != 1:
            raise RuntimeError(f"joint must resolve to exactly one DoF: {name}")
        dof_indices.append(int(indices[0]))
    if len(dof_indices) != len(set(dof_indices)):
        raise RuntimeError("mapped DoF indices are not unique")

    def read_positions() -> list[float]:
        try:
            value = robot.get_dofs_position(dofs_idx_local=dof_indices)
        except TypeError:
            value = robot.get_dofs_position(dof_indices)
        positions = flatten_finite(value)
        if len(positions) != len(dof_indices):
            raise RuntimeError("Genesis returned an unexpected DoF state length")
        return positions

    initial_positions = read_positions()
    for _ in range(args.steps):
        scene.step()
    final_positions = read_positions()

    receipt = {
        "schema_version": 1,
        "kind": "genesis_robot_port_runtime_receipt",
        "status": "runtime_port_verified",
        "robot_id": spec["robot_id"],
        "spec_sha256": sha256_file(args.spec.resolve()),
        "urdf_sha256": actual_urdf_sha256,
        "backend_requested": args.backend,
        "backend_active": args.backend,
        "device": device_receipt,
        "genesis_version": genesis_version(gs),
        "python_version": platform.python_version(),
        "fixed_base": True,
        "headless": True,
        "controller_commands_issued": False,
        "controlled_motion_validated": False,
        "rendering_performed": False,
        "arm_sides": arm_sides,
        "arm_count": len(arm_sides),
        "joint_order": joint_names,
        "mapped_dof_indices": dof_indices,
        "mapped_dof_count": len(dof_indices),
        "steps": args.steps,
        "finite_initial_state": all(math.isfinite(item) for item in initial_positions),
        "finite_final_state": all(math.isfinite(item) for item in final_positions),
        "amd_runtime_claim": args.backend == "amdgpu",
        "claim_boundary": (
            "Read-only fixed-base load, joint mapping, and no-command stepping only; "
            "controller, safety, rendering, data, training, and policy inference "
            "were not validated."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True)
        stream.write("\n")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "error",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        raise SystemExit(2)
'''


def _build_bundle(
    ir: Mapping[str, Any],
    semantics: Mapping[str, Any],
    task: Mapping[str, Any],
) -> dict[str, Any]:
    state_fields, action_fields, joint_auxiliary = _policy_fields(
        semantics["arms"], semantics["grippers"]
    )
    morphology = {
        "schema_version": 1,
        "robot_id": semantics["robot_id"],
        "supported_mvp": True,
        "base": "fixed",
        "arm_count": len(semantics["arms"]),
        "dof_per_arm": [len(arm["joint_names"]) for arm in semantics["arms"]],
        "arms": semantics["arms"],
        "gripper_count": len(semantics["grippers"]),
        "shared_actuated_prefix": (
            ir["morphology"]["selected_candidate"]["shared_actuated_prefix"]
        ),
        "source_urdf_sha256": ir["source_urdf"]["sha256"],
        "claim_boundary": "Static morphology admission; runtime parity is not established.",
    }
    port_profile = {
        "schema_version": 1,
        "profile_id": f"{semantics['robot_id']}-{task['task_id']}-compiled-v1",
        "robot_id": semantics["robot_id"],
        "task_id": task["task_id"],
        "morphology": {
            "base": "fixed",
            "arm_count": len(semantics["arms"]),
            "dof_per_arm": [len(arm["joint_names"]) for arm in semantics["arms"]],
        },
        "controller": semantics["controller"],
        "safety": semantics["safety"],
        "camera_roles": task["camera_roles"],
        "policy_interface": {
            "representation": "per_arm_task_space_delta",
            "state_dimension": len(state_fields),
            "action_dimension": len(action_fields),
            "state_order": state_fields,
            "action_order": action_fields,
            "joint_state_auxiliary_order": joint_auxiliary,
            "native_joint_action_head_reuse_allowed": False,
        },
        "current_promotion_state": "PORT_COMPILED",
        "runtime_admitted": False,
    }
    genesis = {
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "kind": "genesis_port_spec",
        "target_runtime": "Genesis",
        "robot_id": semantics["robot_id"],
        "urdf_sha256": ir["source_urdf"]["sha256"],
        "fixed_base": True,
        "required_backend_for_amd_claim": "amdgpu",
        "allowed_backends": ["cpu", "amdgpu"],
        "joint_order_by_arm": {
            arm["side"]: arm["joint_names"] for arm in semantics["arms"]
        },
        "end_effector_links": {
            arm["side"]: arm["end_effector_link"] for arm in semantics["arms"]
        },
        "simulation": {
            "dt": 0.01,
            "default_steps": 2,
            "maximum_steps": 100,
            "headless": True,
        },
        "runtime_operations": [
            "verify URDF SHA-256 before Genesis import",
            "initialize one explicit Genesis backend",
            "load fixed-base URDF",
            "map compiled arm joint names to unique local DoFs",
            "read finite joint state before and after no-command stepping",
            "write one exclusive runtime receipt",
        ],
        "controller_commands_allowed": False,
        "rendering_allowed": False,
        "controller_contract": semantics["controller"],
        "safety_contract": semantics["safety"],
        "runtime_admitted": False,
        "claim_boundary": (
            "The generated probe validates load and joint mapping only; it does "
            "not validate IK, controller behavior, safety behavior, rendering, "
            "data collection, training, or learned-policy inference."
        ),
    }
    features: dict[str, Any] = {
        "observation.state": {
            "dtype": "float32",
            "shape": [len(state_fields)],
            "names": state_fields,
        },
        "observation.joint_state_auxiliary": {
            "dtype": "float32",
            "shape": [len(joint_auxiliary)],
            "names": joint_auxiliary,
        },
        "action": {
            "dtype": "float32",
            "shape": [len(action_fields)],
            "names": action_fields,
        },
    }
    cameras_by_role = {item["role"]: item for item in semantics["cameras"]}
    if set(task["camera_roles"]) != set(cameras_by_role):
        raise ContractError("task camera roles must exactly match semantic camera roles")
    for role in sorted(cameras_by_role):
        camera = cameras_by_role[role]
        features[f"observation.images.{role}"] = {
            "dtype": "video",
            "shape": [camera["height"], camera["width"], 3],
            "calibration_ref": camera["calibration_ref"],
        }
    lerobot = {
        "schema_version": 1,
        "format": "LeRobotDataset",
        "robot_id": semantics["robot_id"],
        "task_id": task["task_id"],
        "features": features,
        "dataset_admitted": False,
        "admission_requirements": task["dataset"],
    }
    act_training = {
        "schema_version": 1,
        "policy": "ACT",
        "input_state_dimension": len(state_fields),
        "action_dimension": len(action_fields),
        "action_order": action_fields,
        "chunk_size": task["act"]["chunk_size"],
        "policy_call_budget": task["act"]["policy_call_budget"],
        "training_seed": task["act"]["training_seed"],
        "normalization_recomputed_per_embodiment": True,
        "reuse_native_joint_action_head": False,
        "nonfinite_metrics_allowed": False,
        "natural_exit_required": True,
        "checkpoint_and_config_hashes_required": True,
        "loss_is_task_success": False,
        "training_admitted": False,
    }
    rocm = {
        "schema_version": 1,
        "accelerator_vendor": "AMD",
        "software_stack": "ROCm",
        "visible_gpu_count": 1,
        "torch_device": "cuda",
        "required_runtime_checks": [
            "torch.version.hip is non-empty",
            "torch.cuda.is_available() is true",
            "torch.cuda.device_count() equals 1",
            "training and inference receipts include device and package inventory",
        ],
        "performance_evidence_required": [
            "training throughput",
            "peak GPU memory",
            "inference latency p50 p95 p99",
            "policy call budget",
        ],
        "runtime_verified": False,
        "amd_deployable": False,
    }
    rocm_tuning = {
        "schema_version": 1,
        "kind": "rocm_act_shape_tuning_plan",
        "robot_id": semantics["robot_id"],
        "task_id": task["task_id"],
        "workload": "ACT-shaped synthetic forward and backward compute",
        "morphology": {
            "arm_count": len(semantics["arms"]),
            "dof_per_arm": [
                len(arm["joint_names"]) for arm in semantics["arms"]
            ],
            "policy_state_dimension": len(state_fields),
            "policy_action_dimension": len(action_fields),
            "camera_count": len(task["camera_roles"]),
            "act_chunk_size": task["act"]["chunk_size"],
        },
        "benchmark_model": {
            "family": "transformer_encoder_action_head",
            "d_model": 256,
            "nhead": 8,
            "encoder_layers": 2,
            "sequence_length": min(max(task["act"]["chunk_size"], 8), 128),
            "batch_size": 8,
        },
        "protocol": {
            "seed": task["act"]["training_seed"],
            "warmup_iterations": 5,
            "measured_iterations": 20,
            "same_device_comparison_required": True,
            "raw_latency_samples_required": True,
        },
        "profiles": [
            {
                "profile_id": "fp32-baseline",
                "precision": "float32",
                "role": "baseline",
            },
            {
                "profile_id": "bf16-candidate",
                "precision": "bfloat16",
                "role": "candidate",
            },
            {
                "profile_id": "fp16-candidate",
                "precision": "float16",
                "role": "candidate",
            },
        ],
        "admission_thresholds": {
            "cosine_similarity_minimum": 0.999,
            "maximum_absolute_error": 0.05,
            "minimum_inference_or_training_speedup_fraction": 0.05,
            "finite_outputs_required": True,
        },
        "maximum_promotion_state": "ROCM_TUNING_MEASURED",
        "amd_deployable": False,
        "claim_boundary": (
            "Synthetic ACT-shape microbenchmark only; results do not establish "
            "dataset quality, ACT accuracy, task success, or end-to-end training."
        ),
    }
    quality = {
        "schema_version": 1,
        "state_ladder": QUALITY_STATES,
        "current_state": "PORT_COMPILED",
        "runtime_port_gate": {
            "fixed_base_load_required": True,
            "joint_mapping_required": True,
            "finite_no_command_step_required": True,
            "controlled_motion_required": False,
            "passed": False,
        },
        "rocm_tuning_gate": {
            "strict_rocm_device_required": True,
            "same_device_fp32_baseline_required": True,
            "precision_candidate_optional": True,
            "microbenchmark_is_not_act_accuracy": True,
            "passed": False,
        },
        "dataset_gate": {
            "expert_success_fraction": 1.0,
            "failed_episodes_excluded": True,
            "unique_seeds_required": True,
            "coverage_strata_required": True,
            "normalization_recomputed_per_embodiment": True,
            "passed": False,
        },
        "training_gate": {
            "nonfinite_metrics_allowed": False,
            "natural_exit_required": True,
            "checkpoint_and_config_hashes_required": True,
            "loss_is_task_success": False,
            "passed": False,
        },
        "openloop_gate": {
            "finite_actions_required": True,
            "correct_order_and_units_required": True,
            "fixed_limit_projection_required": True,
            "latency_p50_p95_p99_required": True,
            "declared_policy_call_budget_required": True,
            "passed": False,
        },
        "closedloop_gate": {
            "g1_trials": 1,
            "g2_trials": 2,
            "g3_trials": 10,
            "g3_minimum_successes": 6,
            "g3_minimum_success_fraction": 0.6,
            "g3_maximum_safety_failures": 0,
            "competitive_target_successes": 8,
            "competitive_target_success_fraction": 0.8,
            "g4_trials": 30,
            "g4_allowed_only_after_g3_pass": True,
            "evaluation_seeds": task["act"]["evaluation_seeds"],
            "passed": False,
        },
        "existing_mantis_baseline": {
            "successes": 0,
            "trials": 10,
            "safety_failures": 2,
            "status": "ACT_OPENLOOP_PASS_ONLY",
            "amd_deployable": False,
        },
        "amd_deployable": False,
    }
    return {
        "embodiment-ir.json": dict(ir),
        "morphology-report.json": morphology,
        "robot-port-profile.json": port_profile,
        "genesis-port-spec.json": genesis,
        "run-genesis-port.py": _generated_genesis_runner(),
        "lerobot-features.json": lerobot,
        "act-training.json": act_training,
        "rocm-runtime.json": rocm,
        "rocm-tuning-plan.json": rocm_tuning,
        "quality-gates.json": quality,
    }


def compile_port_bundle(
    urdf_path: str | Path,
    semantic_sidecar_path: str | Path,
    task_pack_path: str | Path,
    output_directory: str | Path,
) -> dict[str, Any]:
    """Compile the exact eleven-file robot port bundle without overwriting."""

    output = Path(output_directory)
    if output.exists():
        raise ContractError(f"output path already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    ir = inspect_urdf(urdf_path)
    if not ir["morphology"]["supported"]:
        raise ContractError("URDF morphology is outside the supported MVP boundary")
    semantics = validate_semantic_sidecar(
        _load_json_object(semantic_sidecar_path, "semantic sidecar"), ir
    )
    task = validate_task_pack(_load_json_object(task_pack_path, "task pack"))
    bundle = _build_bundle(ir, semantics, task)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{output.name}.partial-", dir=output.parent)
    )
    try:
        for filename in BUNDLE_FILENAMES[:-1]:
            target = staging / filename
            if filename == "run-genesis-port.py":
                with target.open("x", encoding="utf-8", newline="\n") as stream:
                    stream.write(bundle[filename])
            else:
                _write_json_exclusive(target, bundle[filename])
        manifest_files = [
            {
                "path": filename,
                "sha256": _sha256_file(staging / filename),
                "size_bytes": (staging / filename).stat().st_size,
            }
            for filename in BUNDLE_FILENAMES[:-1]
        ]
        manifest = {
            "schema_version": BUNDLE_SCHEMA_VERSION,
            "kind": "rocm_native_robot_port_bundle",
            "files": manifest_files,
            "file_count_excluding_manifest": len(manifest_files),
            "deterministic": True,
            "source_urdf_sha256": ir["source_urdf"]["sha256"],
            "current_state": "PORT_COMPILED",
            "claim_boundary": (
                "Generated runtime and tuning plans are unverified until their "
                "exclusive receipts pass; ACT accuracy and AMD deployability "
                "are not established."
            ),
        }
        _write_json_exclusive(staging / "bundle-manifest.json", manifest)
        if sorted(path.name for path in staging.iterdir()) != sorted(BUNDLE_FILENAMES):
            raise ContractError("internal bundle file set disagrees")
        os.rename(staging, output)
        return manifest
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def verify_bundle(path: str | Path) -> dict[str, Any]:
    """Independently verify the exact file set and manifest hashes."""

    root = Path(path)
    if not root.is_dir():
        raise ContractError(f"bundle is not a directory: {root}")
    actual = sorted(item.name for item in root.iterdir())
    if actual != sorted(BUNDLE_FILENAMES):
        raise ContractError(
            f"bundle file set disagrees; expected={sorted(BUNDLE_FILENAMES)}, "
            f"actual={actual}"
        )
    manifest = _load_json_object(root / "bundle-manifest.json", "bundle manifest")
    _exact_keys(
        manifest,
        {
            "schema_version",
            "kind",
            "files",
            "file_count_excluding_manifest",
            "deterministic",
            "source_urdf_sha256",
            "current_state",
            "claim_boundary",
        },
        "bundle manifest",
    )
    if (
        manifest["schema_version"] != BUNDLE_SCHEMA_VERSION
        or manifest["kind"] != "rocm_native_robot_port_bundle"
        or manifest["file_count_excluding_manifest"] != 10
        or manifest["deterministic"] is not True
        or manifest["current_state"] != "PORT_COMPILED"
    ):
        raise ContractError("bundle manifest metadata disagrees")
    files = manifest["files"]
    if not isinstance(files, list) or len(files) != 10:
        raise ContractError("bundle manifest must list ten payload files")
    expected_paths = BUNDLE_FILENAMES[:-1]
    actual_paths = [item.get("path") for item in files if isinstance(item, dict)]
    if actual_paths != expected_paths:
        raise ContractError("bundle manifest path order or set disagrees")
    for item in files:
        _exact_keys(item, {"path", "sha256", "size_bytes"}, "bundle manifest file")
        target = root / item["path"]
        if _sha256_file(target) != item["sha256"]:
            raise ContractError(f"bundle hash mismatch: {item['path']}")
        if target.stat().st_size != item["size_bytes"]:
            raise ContractError(f"bundle size mismatch: {item['path']}")
    return {
        "valid": True,
        "file_count": 11,
        "payload_file_count": 10,
        "current_state": "PORT_COMPILED",
        "source_urdf_sha256": manifest["source_urdf_sha256"],
    }
