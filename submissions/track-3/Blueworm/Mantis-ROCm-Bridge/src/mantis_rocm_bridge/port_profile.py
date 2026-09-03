"""Pure, read-only robot-port profile validation and stage planning."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from .contracts import ContractError


SCHEMA_VERSION = 1
PROFILE_KINDS = {"template", "reference", "synthetic_fixture"}
PORT_MODES = {
    "same_robot_new_scene",
    "new_robot_same_task",
    "new_robot_new_scene",
}
STAGE_STATES = {"complete", "ready", "blocked", "deferred"}
STAGE_OUTCOMES = {"pass", "negative", "not_run", "not_applicable"}
PROMOTION_STATES = {
    "allows_downstream",
    "blocks_downstream",
    "pending",
    "not_applicable",
}
REFERENCE_KINDS = {
    "config",
    "document",
    "receipt",
    "source",
    "asset_manifest",
    "test_fixture",
}
BLOCKER_SEVERITIES = {"critical", "high", "medium", "low"}
_ID_RE = re.compile(r"^[a-z][a-z0-9_.-]*$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def load_port_profile(path: str | Path) -> dict[str, Any]:
    """Load and structurally validate one schema-v1 robot-port profile."""

    profile_path = Path(path)
    try:
        payload = json.loads(profile_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(
            f"cannot load robot-port profile {profile_path}: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise ContractError("robot-port profile root must be an object")
    validate_port_profile(payload)
    return payload


def _exact_keys(value: Mapping[str, Any], expected: set[str], context: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ContractError(f"{context} keys disagree; missing={missing}, extra={extra}")


def _object(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError(f"{context} must be an object")
    return value


def _identifier(value: Any, context: str) -> str:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise ContractError(f"{context} must match {_ID_RE.pattern}")
    return value


def _text(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{context} must be a non-empty string")
    return value


def _positive_int(value: Any, context: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ContractError(f"{context} must be a positive integer")
    return value


def _positive_number(value: Any, context: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ContractError(f"{context} must be a positive number")
    return float(value)


def _fraction(value: Any, context: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractError(f"{context} must be a number from 0 to 1")
    result = float(value)
    if result < 0 or result > 1:
        raise ContractError(f"{context} must be a number from 0 to 1")
    return result


def _optional_nonnegative_int(value: Any, context: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ContractError(f"{context} must be null or a non-negative integer")
    return value


def _unique_strings(
    value: Any,
    context: str,
    *,
    allow_empty: bool = False,
) -> list[str]:
    if not isinstance(value, list) or (not value and not allow_empty):
        suffix = " (empty allowed)" if allow_empty else ""
        raise ContractError(f"{context} must be a list of strings{suffix}")
    if not all(isinstance(item, str) and item for item in value):
        raise ContractError(f"{context} must contain non-empty strings")
    if len(value) != len(set(value)):
        raise ContractError(f"{context} contains duplicates")
    return value


def _optional_ref(value: Any, context: str) -> str | None:
    if value is None:
        return None
    return _identifier(value, context)


def _validate_endpoint(endpoint: Any, context: str) -> dict[str, Any]:
    item = _object(endpoint, context)
    _exact_keys(
        item,
        {
            "robot_id",
            "task_id",
            "simulator",
            "policy_state_dimension",
            "policy_action_dimension",
            "physical_state_dimension",
            "physical_action_dimension",
            "policy_state_order",
            "policy_action_order",
            "physical_state_order",
            "physical_action_order",
            "observation_keys",
            "camera_roles",
            "control_hz",
            "action_representation",
        },
        context,
    )
    _identifier(item["robot_id"], f"{context}.robot_id")
    _identifier(item["task_id"], f"{context}.task_id")
    _text(item["simulator"], f"{context}.simulator")
    policy_state = _positive_int(
        item["policy_state_dimension"], f"{context}.policy_state_dimension"
    )
    policy_action = _positive_int(
        item["policy_action_dimension"], f"{context}.policy_action_dimension"
    )
    physical_state = _positive_int(
        item["physical_state_dimension"], f"{context}.physical_state_dimension"
    )
    physical_action = _positive_int(
        item["physical_action_dimension"], f"{context}.physical_action_dimension"
    )
    policy_state_order = _unique_strings(
        item["policy_state_order"], f"{context}.policy_state_order"
    )
    policy_action_order = _unique_strings(
        item["policy_action_order"], f"{context}.policy_action_order"
    )
    physical_state_order = _unique_strings(
        item["physical_state_order"], f"{context}.physical_state_order"
    )
    physical_action_order = _unique_strings(
        item["physical_action_order"], f"{context}.physical_action_order"
    )
    if len(policy_state_order) != policy_state:
        raise ContractError(
            f"{context}.policy_state_order length must match policy_state_dimension"
        )
    if len(policy_action_order) != policy_action:
        raise ContractError(
            f"{context}.policy_action_order length must match policy_action_dimension"
        )
    if len(physical_state_order) != physical_state:
        raise ContractError(
            f"{context}.physical_state_order length must match "
            "physical_state_dimension"
        )
    if len(physical_action_order) != physical_action:
        raise ContractError(
            f"{context}.physical_action_order length must match "
            "physical_action_dimension"
        )
    _unique_strings(item["observation_keys"], f"{context}.observation_keys")
    _unique_strings(item["camera_roles"], f"{context}.camera_roles", allow_empty=True)
    _positive_number(item["control_hz"], f"{context}.control_hz")
    _text(item["action_representation"], f"{context}.action_representation")
    return item


def _validate_relative_reference_path(value: Any, context: str) -> str:
    raw = _text(value, context)
    path = PurePosixPath(raw)
    if path.is_absolute() or raw.startswith("~"):
        raise ContractError(f"{context} must be project-relative")
    if not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ContractError(f"{context} contains an unsafe path component")
    return raw


def validate_port_profile(profile: Mapping[str, Any]) -> None:
    """Validate one profile without reading referenced files or changing state."""

    if not isinstance(profile, Mapping):
        raise ContractError("robot-port profile must be an object")
    _exact_keys(
        profile,
        {
            "schema_version",
            "profile_id",
            "profile_kind",
            "description",
            "port_mode",
            "source",
            "target",
            "adapters",
            "controller",
            "safety",
            "data",
            "policy",
            "evaluation",
            "task",
            "runtime",
            "assets",
            "references",
            "blockers",
            "stages",
            "claim_boundary",
        },
        "profile",
    )
    if profile["schema_version"] != SCHEMA_VERSION:
        raise ContractError(f"profile.schema_version must be {SCHEMA_VERSION}")
    _identifier(profile["profile_id"], "profile.profile_id")
    if profile["profile_kind"] not in PROFILE_KINDS:
        raise ContractError("profile.profile_kind is unsupported")
    _text(profile["description"], "profile.description")
    if profile["port_mode"] not in PORT_MODES:
        raise ContractError("profile.port_mode is unsupported")

    source = _validate_endpoint(profile["source"], "profile.source")
    target = _validate_endpoint(profile["target"], "profile.target")

    adapters = _object(profile["adapters"], "profile.adapters")
    _exact_keys(
        adapters,
        {
            "joint_mapping_ref",
            "state_adapter_ref",
            "action_adapter_ref",
            "gripper_adapter_ref",
            "camera_map_ref",
            "control_resampling_ref",
        },
        "profile.adapters",
    )
    adapter_refs = {
        _optional_ref(value, f"profile.adapters.{key}")
        for key, value in adapters.items()
        if value is not None
    }

    controller = _object(profile["controller"], "profile.controller")
    _exact_keys(
        controller,
        {
            "source_type",
            "target_type",
            "command_semantics",
            "target_control_contract_ref",
        },
        "profile.controller",
    )
    _text(controller["source_type"], "profile.controller.source_type")
    _text(controller["target_type"], "profile.controller.target_type")
    _text(
        controller["command_semantics"],
        "profile.controller.command_semantics",
    )
    controller_ref = _optional_ref(
        controller["target_control_contract_ref"],
        "profile.controller.target_control_contract_ref",
    )

    safety = _object(profile["safety"], "profile.safety")
    _exact_keys(
        safety,
        {"contract_ref", "admission_rule", "zero_violation_required"},
        "profile.safety",
    )
    safety_ref = _optional_ref(
        safety["contract_ref"], "profile.safety.contract_ref"
    )
    _text(safety["admission_rule"], "profile.safety.admission_rule")
    if not isinstance(safety["zero_violation_required"], bool):
        raise ContractError(
            "profile.safety.zero_violation_required must be a boolean"
        )

    data = _object(profile["data"], "profile.data")
    _exact_keys(
        data,
        {"dataset_format", "export_contract_ref", "admission_contract_ref"},
        "profile.data",
    )
    _text(data["dataset_format"], "profile.data.dataset_format")
    data_refs = {
        ref
        for ref in (
            _optional_ref(
                data["export_contract_ref"], "profile.data.export_contract_ref"
            ),
            _optional_ref(
                data["admission_contract_ref"],
                "profile.data.admission_contract_ref",
            ),
        )
        if ref is not None
    }

    policy = _object(profile["policy"], "profile.policy")
    _exact_keys(
        policy,
        {
            "family",
            "training_contract_ref",
            "openloop_contract_ref",
            "closedloop_contract_ref",
            "hardware_runtime_ref",
        },
        "profile.policy",
    )
    _text(policy["family"], "profile.policy.family")
    policy_refs = {
        ref
        for key in (
            "training_contract_ref",
            "openloop_contract_ref",
            "closedloop_contract_ref",
            "hardware_runtime_ref",
        )
        if (
            ref := _optional_ref(
                policy[key],
                f"profile.policy.{key}",
            )
        )
        is not None
    }

    evaluation = _object(profile["evaluation"], "profile.evaluation")
    _exact_keys(
        evaluation,
        {
            "protocol_ref",
            "case_ids",
            "minimum_success_fraction",
            "recorded_successes",
            "recorded_trials",
            "outcome_evidence_ref",
        },
        "profile.evaluation",
    )
    evaluation_refs = {
        ref
        for ref in (
            _optional_ref(
                evaluation["protocol_ref"],
                "profile.evaluation.protocol_ref",
            ),
            _optional_ref(
                evaluation["outcome_evidence_ref"],
                "profile.evaluation.outcome_evidence_ref",
            ),
        )
        if ref is not None
    }
    _unique_strings(
        evaluation["case_ids"], "profile.evaluation.case_ids", allow_empty=True
    )
    _fraction(
        evaluation["minimum_success_fraction"],
        "profile.evaluation.minimum_success_fraction",
    )
    recorded_successes = _optional_nonnegative_int(
        evaluation["recorded_successes"],
        "profile.evaluation.recorded_successes",
    )
    recorded_trials = _optional_nonnegative_int(
        evaluation["recorded_trials"],
        "profile.evaluation.recorded_trials",
    )
    if (recorded_successes is None) != (recorded_trials is None):
        raise ContractError(
            "profile.evaluation recorded_successes and recorded_trials "
            "must both be null or both be integers"
        )
    if recorded_trials is not None:
        if recorded_trials == 0:
            raise ContractError(
                "profile.evaluation.recorded_trials must be positive when recorded"
            )
        if recorded_successes is not None and recorded_successes > recorded_trials:
            raise ContractError(
                "profile.evaluation.recorded_successes cannot exceed recorded_trials"
            )

    task = _object(profile["task"], "profile.task")
    _exact_keys(
        task,
        {
            "task_id",
            "same_task_required",
            "source_contract_ref",
            "target_contract_ref",
            "success_protocol",
        },
        "profile.task",
    )
    task_id = _identifier(task["task_id"], "profile.task.task_id")
    if not isinstance(task["same_task_required"], bool):
        raise ContractError("profile.task.same_task_required must be a boolean")
    task_refs = {
        ref
        for ref in (
            _optional_ref(task["source_contract_ref"], "profile.task.source_contract_ref"),
            _optional_ref(task["target_contract_ref"], "profile.task.target_contract_ref"),
        )
        if ref is not None
    }
    _text(task["success_protocol"], "profile.task.success_protocol")
    if task_id != target["task_id"]:
        raise ContractError("profile.task.task_id must match profile.target.task_id")
    if task["same_task_required"] and source["task_id"] != target["task_id"]:
        raise ContractError(
            "profile.task.same_task_required=true cannot change task_id"
        )
    if profile["port_mode"] == "new_robot_same_task":
        if not task["same_task_required"]:
            raise ContractError("new_robot_same_task requires same_task_required=true")
        if source["robot_id"] == target["robot_id"]:
            raise ContractError("new_robot_same_task requires different robot_id values")
    elif profile["port_mode"] == "same_robot_new_scene":
        if source["robot_id"] != target["robot_id"]:
            raise ContractError("same_robot_new_scene requires matching robot_id values")
    elif source["robot_id"] == target["robot_id"]:
        raise ContractError("new_robot_new_scene requires different robot_id values")

    runtime = _object(profile["runtime"], "profile.runtime")
    _exact_keys(
        runtime,
        {
            "primary_simulator",
            "primary_backend",
            "amd_rocm_required",
            "amd_runtime_contract_ref",
            "persistent_root",
        },
        "profile.runtime",
    )
    _text(runtime["primary_simulator"], "profile.runtime.primary_simulator")
    _text(runtime["primary_backend"], "profile.runtime.primary_backend")
    if not isinstance(runtime["amd_rocm_required"], bool):
        raise ContractError("profile.runtime.amd_rocm_required must be a boolean")
    runtime_ref = _optional_ref(
        runtime["amd_runtime_contract_ref"],
        "profile.runtime.amd_runtime_contract_ref",
    )
    persistent_root = _text(runtime["persistent_root"], "profile.runtime.persistent_root")
    if runtime["amd_rocm_required"] and not persistent_root.startswith("/"):
        raise ContractError(
            "ROCm-required profile.runtime.persistent_root must be absolute"
        )

    assets = _object(profile["assets"], "profile.assets")
    _exact_keys(
        assets,
        {"strategy", "robot_asset_redistributable", "asset_refs"},
        "profile.assets",
    )
    if assets["strategy"] not in {
        "externalized",
        "licensed_vendored",
        "mixed",
        "synthetic",
    }:
        raise ContractError("profile.assets.strategy is unsupported")
    if not isinstance(assets["robot_asset_redistributable"], bool):
        raise ContractError(
            "profile.assets.robot_asset_redistributable must be a boolean"
        )
    asset_refs = set(
        _unique_strings(
            assets["asset_refs"], "profile.assets.asset_refs", allow_empty=True
        )
    )
    if (
        assets["strategy"] == "externalized"
        and assets["robot_asset_redistributable"]
    ):
        raise ContractError("externalized robot asset cannot be redistributable")

    references_raw = profile["references"]
    if not isinstance(references_raw, list):
        raise ContractError("profile.references must be a list")
    reference_ids: set[str] = set()
    for index, raw in enumerate(references_raw):
        context = f"profile.references[{index}]"
        reference = _object(raw, context)
        _exact_keys(
            reference,
            {"id", "path", "kind", "required", "sha256"},
            context,
        )
        ref_id = _identifier(reference["id"], f"{context}.id")
        if ref_id in reference_ids:
            raise ContractError(f"duplicate profile reference id: {ref_id}")
        reference_ids.add(ref_id)
        _validate_relative_reference_path(reference["path"], f"{context}.path")
        if reference["kind"] not in REFERENCE_KINDS:
            raise ContractError(f"{context}.kind is unsupported")
        if not isinstance(reference["required"], bool):
            raise ContractError(f"{context}.required must be a boolean")
        digest = reference["sha256"]
        if digest is not None and (
            not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest)
        ):
            raise ContractError(f"{context}.sha256 must be null or lowercase SHA-256")

    declared_refs = (
        set(adapter_refs)
        | data_refs
        | policy_refs
        | evaluation_refs
        | task_refs
        | asset_refs
    )
    for section_ref in (controller_ref, safety_ref):
        if section_ref is not None:
            declared_refs.add(section_ref)
    if runtime_ref is not None:
        declared_refs.add(runtime_ref)
    unknown_declared_refs = sorted(declared_refs - reference_ids)
    if unknown_declared_refs:
        raise ContractError(
            f"profile sections reference unknown IDs: {unknown_declared_refs}"
        )

    blockers_raw = profile["blockers"]
    if not isinstance(blockers_raw, list):
        raise ContractError("profile.blockers must be a list")
    blocker_ids: set[str] = set()
    blockers_by_id: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(blockers_raw):
        context = f"profile.blockers[{index}]"
        blocker = _object(raw, context)
        _exact_keys(
            blocker,
            {"id", "severity", "scope", "blocks_stages", "description"},
            context,
        )
        blocker_id = _identifier(blocker["id"], f"{context}.id")
        if blocker_id in blocker_ids:
            raise ContractError(f"duplicate profile blocker id: {blocker_id}")
        blocker_ids.add(blocker_id)
        blockers_by_id[blocker_id] = blocker
        if blocker["severity"] not in BLOCKER_SEVERITIES:
            raise ContractError(f"{context}.severity is unsupported")
        _text(blocker["scope"], f"{context}.scope")
        _unique_strings(blocker["blocks_stages"], f"{context}.blocks_stages")
        _text(blocker["description"], f"{context}.description")

    stages_raw = profile["stages"]
    if not isinstance(stages_raw, list) or not stages_raw:
        raise ContractError("profile.stages must be a non-empty list")
    stage_ids: list[str] = []
    stages_by_id: dict[str, dict[str, Any]] = {}
    seen_stages: set[str] = set()
    used_evidence_refs: set[str] = set()
    for index, raw in enumerate(stages_raw):
        context = f"profile.stages[{index}]"
        stage = _object(raw, context)
        _exact_keys(
            stage,
            {
                "id",
                "label",
                "state",
                "outcome",
                "promotion",
                "depends_on",
                "blocker_ids",
                "evidence_refs",
                "claim_boundary",
            },
            context,
        )
        stage_id = _identifier(stage["id"], f"{context}.id")
        if stage_id in seen_stages:
            raise ContractError(f"duplicate profile stage id: {stage_id}")
        _text(stage["label"], f"{context}.label")
        if stage["state"] not in STAGE_STATES:
            raise ContractError(f"{context}.state is unsupported")
        if stage["outcome"] not in STAGE_OUTCOMES:
            raise ContractError(f"{context}.outcome is unsupported")
        if stage["promotion"] not in PROMOTION_STATES:
            raise ContractError(f"{context}.promotion is unsupported")
        dependencies = _unique_strings(
            stage["depends_on"], f"{context}.depends_on", allow_empty=True
        )
        unknown_dependencies = sorted(set(dependencies) - seen_stages)
        if unknown_dependencies:
            raise ContractError(
                f"{context} dependencies must refer to earlier stages: "
                f"{unknown_dependencies}"
            )
        local_blockers = _unique_strings(
            stage["blocker_ids"], f"{context}.blocker_ids", allow_empty=True
        )
        unknown_blockers = sorted(set(local_blockers) - blocker_ids)
        if unknown_blockers:
            raise ContractError(f"{context} has unknown blockers: {unknown_blockers}")
        evidence_refs = _unique_strings(
            stage["evidence_refs"], f"{context}.evidence_refs", allow_empty=True
        )
        unknown_evidence = sorted(set(evidence_refs) - reference_ids)
        if unknown_evidence:
            raise ContractError(
                f"{context} has unknown evidence references: {unknown_evidence}"
            )
        used_evidence_refs.update(evidence_refs)
        _text(stage["claim_boundary"], f"{context}.claim_boundary")

        state = stage["state"]
        if state == "complete":
            if stage["outcome"] not in {"pass", "negative"}:
                raise ContractError(f"{context} complete stage needs pass/negative")
            if stage["promotion"] not in {
                "allows_downstream",
                "blocks_downstream",
            }:
                raise ContractError(
                    f"{context} complete stage needs a terminal promotion state"
                )
            if local_blockers:
                raise ContractError(f"{context} complete stage cannot retain blockers")
        elif state == "ready":
            if stage["outcome"] != "not_run" or stage["promotion"] != "pending":
                raise ContractError(f"{context} ready stage must be pending/not_run")
            if local_blockers:
                raise ContractError(f"{context} ready stage cannot retain blockers")
            blocking_dependencies = [
                dependency
                for dependency in dependencies
                if stages_by_id[dependency]["promotion"] != "allows_downstream"
            ]
            if blocking_dependencies:
                raise ContractError(
                    f"{context} ready stage has nonpromoting dependencies: "
                    f"{blocking_dependencies}"
                )
        elif state == "blocked":
            if stage["outcome"] != "not_run" or stage["promotion"] != "pending":
                raise ContractError(f"{context} blocked stage must be pending/not_run")
            if not local_blockers:
                raise ContractError(f"{context} blocked stage must name a blocker")
        else:
            if stage["outcome"] not in {"not_run", "not_applicable"}:
                raise ContractError(
                    f"{context} deferred stage must be not_run/not_applicable"
                )
            if stage["promotion"] not in {"pending", "not_applicable"}:
                raise ContractError(
                    f"{context} deferred stage promotion must be pending/not_applicable"
                )

        stage_ids.append(stage_id)
        seen_stages.add(stage_id)
        stages_by_id[stage_id] = stage

    for blocker_id, blocker in blockers_by_id.items():
        unknown_stages = sorted(set(blocker["blocks_stages"]) - seen_stages)
        if unknown_stages:
            raise ContractError(
                f"profile blocker {blocker_id} names unknown stages: {unknown_stages}"
            )
        for stage_id in blocker["blocks_stages"]:
            if blocker_id not in stages_by_id[stage_id]["blocker_ids"]:
                raise ContractError(
                    f"profile blocker {blocker_id} and stage {stage_id} disagree"
                )
    for stage_id, stage in stages_by_id.items():
        for blocker_id in stage["blocker_ids"]:
            if stage_id not in blockers_by_id[blocker_id]["blocks_stages"]:
                raise ContractError(
                    f"profile stage {stage_id} and blocker {blocker_id} disagree"
                )

    if used_evidence_refs - reference_ids:
        raise ContractError("profile stage evidence references are inconsistent")
    _text(profile["claim_boundary"], "profile.claim_boundary")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _inside_root(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def audit_profile_references(
    profile: Mapping[str, Any],
    project_root: str | Path,
) -> dict[str, Any]:
    """Check required local references without mutating any file or process."""

    validate_port_profile(profile)
    root = Path(project_root).resolve()
    records: list[dict[str, Any]] = []
    for reference in profile["references"]:
        candidate = (root / reference["path"]).resolve()
        inside_root = _inside_root(candidate, root)
        exists = inside_root and candidate.is_file()
        expected_hash = reference["sha256"]
        actual_hash = _sha256_file(candidate) if exists and expected_hash else None
        hash_matches = expected_hash is None or actual_hash == expected_hash
        passed = inside_root and (exists or not reference["required"]) and hash_matches
        records.append(
            {
                "id": reference["id"],
                "path": reference["path"],
                "kind": reference["kind"],
                "required": reference["required"],
                "inside_project_root": inside_root,
                "exists": exists,
                "expected_sha256": expected_hash,
                "actual_sha256": actual_hash,
                "hash_matches": hash_matches,
                "pass": passed,
            }
        )
    return {
        "project_root": str(root),
        "reference_count": len(records),
        "required_reference_count": sum(
            1 for record in records if record["required"]
        ),
        "failed_reference_ids": [
            record["id"] for record in records if not record["pass"]
        ],
        "pass": all(record["pass"] for record in records),
        "references": records,
    }


def build_port_plan(
    profile: Mapping[str, Any],
    project_root: str | Path,
) -> dict[str, Any]:
    """Return a deterministic, read-only stage plan for one validated profile."""

    validate_port_profile(profile)
    audit = audit_profile_references(profile, project_root)
    failed_refs = set(audit["failed_reference_ids"])
    blockers = {item["id"]: item for item in profile["blockers"]}
    stage_records: list[dict[str, Any]] = []
    next_stage_ids: list[str] = []
    for stage in profile["stages"]:
        missing_evidence = sorted(set(stage["evidence_refs"]) & failed_refs)
        effective_state = stage["state"]
        if missing_evidence:
            effective_state = "blocked_missing_reference"
        elif stage["state"] == "ready":
            next_stage_ids.append(stage["id"])
        stage_records.append(
            {
                "id": stage["id"],
                "label": stage["label"],
                "declared_state": stage["state"],
                "effective_state": effective_state,
                "outcome": stage["outcome"],
                "promotion": stage["promotion"],
                "depends_on": list(stage["depends_on"]),
                "blockers": [
                    {
                        "id": blocker_id,
                        "severity": blockers[blocker_id]["severity"],
                        "scope": blockers[blocker_id]["scope"],
                        "description": blockers[blocker_id]["description"],
                    }
                    for blocker_id in stage["blocker_ids"]
                ],
                "missing_evidence_refs": missing_evidence,
                "claim_boundary": stage["claim_boundary"],
            }
        )
    counts = {
        state: sum(1 for stage in stage_records if stage["declared_state"] == state)
        for state in sorted(STAGE_STATES)
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "profile_id": profile["profile_id"],
        "profile_kind": profile["profile_kind"],
        "port_mode": profile["port_mode"],
        "valid": audit["pass"],
        "reference_audit": audit,
        "stage_counts": counts,
        "next_stage_ids": next_stage_ids if audit["pass"] else [],
        "stages": stage_records,
        "claim_boundary": profile["claim_boundary"],
    }


def profile_validation_summary(
    profile: Mapping[str, Any],
    project_root: str | Path,
) -> dict[str, Any]:
    """Return a compact deterministic validation result."""

    validate_port_profile(profile)
    audit = audit_profile_references(profile, project_root)
    return {
        "schema_version": SCHEMA_VERSION,
        "profile_id": profile["profile_id"],
        "profile_kind": profile["profile_kind"],
        "port_mode": profile["port_mode"],
        "source_robot_id": profile["source"]["robot_id"],
        "target_robot_id": profile["target"]["robot_id"],
        "task_id": profile["task"]["task_id"],
        "structural_validation": "PASS",
        "reference_validation": "PASS" if audit["pass"] else "FAIL",
        "failed_reference_ids": audit["failed_reference_ids"],
        "valid": audit["pass"],
        "claim_boundary": profile["claim_boundary"],
    }


__all__ = [
    "SCHEMA_VERSION",
    "audit_profile_references",
    "build_port_plan",
    "load_port_profile",
    "profile_validation_summary",
    "validate_port_profile",
]
