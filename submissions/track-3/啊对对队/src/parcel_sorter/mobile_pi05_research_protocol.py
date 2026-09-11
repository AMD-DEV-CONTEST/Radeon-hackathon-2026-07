"""Fail-closed research protocol for parcel PI0.5 training and screening."""

from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping

from .mobile_pi05_contract import PI05_GRASP_MODES


PI05_TASK_STAGES = (
    "pregrasp",
    "grasp_approach",
    "lift",
    "transport",
    "place",
    "release",
)
PI05_STAGE_PANEL_PROTOCOL = "pi05-stage-complete-action-panel-v1"
PI05_ACTION_THRESHOLDS_PROTOCOL = "pi05-stage-action-thresholds-v1"
PI05_TINY_OVERFIT_GATE_PROTOCOL = "pi05-tiny-overfit-contract-gate-v1"
PI05_TRAINING_LAUNCH_AUDIT_PROTOCOL = "pi05-training-launch-audit-v1"
PI05_TINY_OVERFIT_ROLE = "tiny_overfit_contract"
PI05_DEVELOPMENT_ROLE = "heldout_action_development"
PI05_TRAINING_ROLES = ("smoke", "tiny_overfit", "candidate")

ACTION_THRESHOLD_FIELDS = (
    "median_position_m",
    "maximum_position_m",
    "median_orientation_rad",
    "maximum_orientation_rad",
    "median_base_velocity",
    "maximum_base_velocity",
    "median_progress_error",
    "minimum_tool_accuracy",
)


def canonical_payload_sha256(payload: Mapping[str, Any], *, hash_field: str) -> str:
    unsigned = {key: value for key, value in payload.items() if key != hash_field}
    canonical = json.dumps(
        unsigned, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_stage_panel(
    payload: Mapping[str, Any], *, expected_role: str | None = None
) -> dict[str, Any]:
    """Validate exact mode/stage coverage and source independence."""

    if payload.get("protocol") != PI05_STAGE_PANEL_PROTOCOL:
        raise ValueError("unexpected PI0.5 stage-panel protocol")
    if payload.get("status") != "frozen":
        raise ValueError("PI0.5 stage panel must be frozen before use")
    role = str(payload.get("role") or "")
    if role not in {PI05_TINY_OVERFIT_ROLE, PI05_DEVELOPMENT_ROLE}:
        raise ValueError("unsupported PI0.5 stage-panel role")
    if expected_role is not None and role != expected_role:
        raise ValueError(f"PI0.5 stage-panel role must be {expected_role}")
    split = str(payload.get("split") or "")
    training_allowed = payload.get("training_data_allowed")
    if role == PI05_TINY_OVERFIT_ROLE:
        if split != "training_contract_subset" or training_allowed is not True:
            raise ValueError("tiny-overfit panel must be an explicit training subset")
    else:
        if "do_not_train" not in split or training_allowed is not False:
            raise ValueError("development action panel must be marked do_not_train")
        if int(payload.get("training_source_overlap_count", -1)) != 0:
            raise ValueError("development action panel overlaps a training source")

    dataset_manifest_sha256 = str(payload.get("dataset_manifest_sha256") or "")
    if not _is_sha256(dataset_manifest_sha256):
        raise ValueError("stage panel has no valid dataset manifest fingerprint")
    minimum_per_cell = int(payload.get("minimum_observations_per_mode_stage") or 0)
    minimum_sources = int(payload.get("minimum_independent_sources_per_mode") or 0)
    required_sources = 1 if role == PI05_TINY_OVERFIT_ROLE else 2
    if minimum_per_cell < 1 or minimum_sources < required_sources:
        raise ValueError("stage panel has insufficient declared replication")

    observations = list(payload.get("observations") or ())
    if not observations:
        raise ValueError("stage panel contains no observations")
    ids: set[str] = set()
    indices: set[int] = set()
    coverage: Counter[tuple[str, str]] = Counter()
    sources_by_mode: dict[str, set[str]] = defaultdict(set)
    episodes: set[int] = set()
    for item in observations:
        observation_id = str(item.get("observation_id") or "")
        if not observation_id or observation_id in ids:
            raise ValueError("stage-panel observation ids must be non-empty and unique")
        ids.add(observation_id)
        dataset_index = int(item.get("dataset_index", -1))
        if dataset_index < 0 or dataset_index in indices:
            raise ValueError("stage-panel dataset indices must be non-negative and unique")
        indices.add(dataset_index)
        episode_index = int(item.get("episode_index", -1))
        if episode_index < 0:
            raise ValueError("stage-panel episode index must be non-negative")
        episodes.add(episode_index)
        source_identity = str(item.get("source_identity") or "")
        if not source_identity:
            raise ValueError("stage-panel observations require source identities")
        if item.get("action_label_available") is not True:
            raise ValueError("stage-panel observations require action labels")
        mode = str(item.get("grasp_mode") or "")
        stage = str(item.get("stage") or "")
        if mode not in PI05_GRASP_MODES or stage not in PI05_TASK_STAGES:
            raise ValueError("stage-panel observation has an invalid mode or stage")
        coverage[(mode, stage)] += 1
        sources_by_mode[mode].add(source_identity)

    missing = [
        f"{mode}:{stage}"
        for mode in PI05_GRASP_MODES
        for stage in PI05_TASK_STAGES
        if coverage[(mode, stage)] < minimum_per_cell
    ]
    if missing:
        raise ValueError(f"stage panel lacks mode/stage coverage: {missing}")
    insufficient_sources = {
        mode: len(sources_by_mode[mode])
        for mode in PI05_GRASP_MODES
        if len(sources_by_mode[mode]) < minimum_sources
    }
    if insufficient_sources:
        raise ValueError(
            f"stage panel lacks independent sources per mode: {insufficient_sources}"
        )

    claimed = str(payload.get("panel_sha256") or "")
    observed = canonical_payload_sha256(payload, hash_field="panel_sha256")
    if claimed != observed:
        raise ValueError("stage-panel fingerprint mismatch")
    return {
        "status": "passed",
        "protocol": "pi05-stage-complete-action-panel-audit-v1",
        "role": role,
        "panel_sha256": claimed,
        "observations": len(observations),
        "episodes": len(episodes),
        "mode_stage_cells": len(coverage),
        "coverage": {
            mode: {stage: coverage[(mode, stage)] for stage in PI05_TASK_STAGES}
            for mode in PI05_GRASP_MODES
        },
        "independent_sources_by_mode": {
            mode: len(sources_by_mode[mode]) for mode in PI05_GRASP_MODES
        },
        "training_source_overlap_count": int(
            payload.get("training_source_overlap_count", 0)
        ),
    }


def independent_source_identity(item: Mapping[str, Any]) -> str:
    """Return the physical/source trajectory identity, rejecting replay ambiguity."""

    explicit = str(item.get("source_identity") or "").strip()
    if explicit:
        return explicit
    source_episode_id = str(
        item.get("source_episode_id") or item.get("episode_id") or ""
    ).strip()
    if source_episode_id:
        return source_episode_id
    source_dataset = str(item.get("source_dataset") or "").strip()
    source_episode_index = item.get("source_episode_index")
    if source_dataset and isinstance(source_episode_index, int):
        return f"{source_dataset}::episode-{source_episode_index}"
    raise ValueError("episode provenance lacks an independent source identity")


def independent_sources_by_mode(
    episode_manifests: Iterable[Mapping[str, Any]],
) -> dict[str, set[str]]:
    """Count independent sources per mode without treating replay copies as samples."""

    result = {mode: set() for mode in PI05_GRASP_MODES}
    for item in episode_manifests:
        identity = independent_source_identity(item)
        modes = tuple(str(mode) for mode in item.get("grasp_modes") or ())
        if not modes:
            raise ValueError("episode provenance has no grasp_modes")
        for mode in modes:
            if mode not in result:
                raise ValueError(f"episode provenance has an invalid grasp mode: {mode}")
            result[mode].add(identity)
    return result


def build_stage_panel(
    observations: Iterable[Mapping[str, Any]],
    *,
    role: str,
    dataset_root: str | Path,
    dataset_manifest_sha256: str,
    minimum_observations_per_mode_stage: int,
    minimum_independent_sources_per_mode: int,
    training_source_identities: Iterable[str] = (),
) -> dict[str, Any]:
    """Freeze a deterministic, stage-complete panel from labeled dataset rows."""

    if role not in {PI05_TINY_OVERFIT_ROLE, PI05_DEVELOPMENT_ROLE}:
        raise ValueError("unsupported PI0.5 stage-panel role")
    if not _is_sha256(dataset_manifest_sha256):
        raise ValueError("invalid dataset manifest fingerprint")
    if minimum_observations_per_mode_stage < 1:
        raise ValueError("minimum observations per cell must be positive")
    required_sources = 1 if role == PI05_TINY_OVERFIT_ROLE else 2
    if minimum_independent_sources_per_mode < required_sources:
        raise ValueError("minimum independent-source count is too small")

    rows = [dict(item) for item in observations]
    rows.sort(
        key=lambda item: (
            PI05_GRASP_MODES.index(str(item.get("grasp_mode"))),
            PI05_TASK_STAGES.index(str(item.get("stage"))),
            str(item.get("source_identity")),
            int(item.get("episode_index", -1)),
            int(item.get("dataset_index", -1)),
        )
    )
    by_cell: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        mode = str(row.get("grasp_mode") or "")
        stage = str(row.get("stage") or "")
        if mode not in PI05_GRASP_MODES or stage not in PI05_TASK_STAGES:
            raise ValueError("candidate observation has an invalid mode or stage")
        by_cell[(mode, stage)].append(row)

    selected: list[dict[str, Any]] = []
    for mode in PI05_GRASP_MODES:
        available_sources = sorted(
            {
                str(item.get("source_identity") or "")
                for stage in PI05_TASK_STAGES
                for item in by_cell[(mode, stage)]
            }
        )
        if len(available_sources) < minimum_independent_sources_per_mode:
            raise ValueError(f"insufficient independent sources for {mode}")
        rotation = available_sources[:minimum_independent_sources_per_mode]
        for stage_index, stage in enumerate(PI05_TASK_STAGES):
            candidates = by_cell[(mode, stage)]
            if len(candidates) < minimum_observations_per_mode_stage:
                raise ValueError(f"insufficient observations for {mode}:{stage}")
            preferred = rotation[stage_index % len(rotation)]
            ordered = sorted(
                candidates,
                key=lambda item: (
                    str(item.get("source_identity")) != preferred,
                    str(item.get("source_identity")),
                    int(item.get("dataset_index", -1)),
                ),
            )
            selected.extend(ordered[:minimum_observations_per_mode_stage])

    training_sources = {str(value) for value in training_source_identities}
    selected_sources = {str(item.get("source_identity") or "") for item in selected}
    overlap = selected_sources & training_sources
    if role == PI05_DEVELOPMENT_ROLE and overlap:
        raise ValueError("development panel overlaps training sources")
    payload: dict[str, Any] = {
        "schema_version": 1,
        "protocol": PI05_STAGE_PANEL_PROTOCOL,
        "status": "frozen",
        "role": role,
        "split": (
            "training_contract_subset"
            if role == PI05_TINY_OVERFIT_ROLE
            else "heldout_action_development_do_not_train"
        ),
        "training_data_allowed": role == PI05_TINY_OVERFIT_ROLE,
        "dataset_root": str(Path(dataset_root).resolve()),
        "dataset_manifest_sha256": dataset_manifest_sha256,
        "minimum_observations_per_mode_stage": minimum_observations_per_mode_stage,
        "minimum_independent_sources_per_mode": minimum_independent_sources_per_mode,
        "training_source_overlap_count": len(overlap),
        "observations": selected,
    }
    payload["panel_sha256"] = canonical_payload_sha256(
        payload, hash_field="panel_sha256"
    )
    validate_stage_panel(payload, expected_role=role)
    return payload


def validate_action_thresholds(
    payload: Mapping[str, Any], *, panel_role: str
) -> dict[str, Any]:
    """Validate a stage-specific threshold profile for its declared role."""

    if payload.get("protocol") != PI05_ACTION_THRESHOLDS_PROTOCOL:
        raise ValueError("unexpected PI0.5 action-threshold protocol")
    status = str(payload.get("status") or "")
    if panel_role == PI05_TINY_OVERFIT_ROLE:
        if status != "contract_test":
            raise ValueError("tiny-overfit thresholds must be a contract-test profile")
    elif panel_role == PI05_DEVELOPMENT_ROLE:
        if status != "calibrated" or payload.get("deployment_calibrated") is not True:
            raise ValueError("development thresholds require contact calibration")
        evidence = payload.get("calibration_evidence") or {}
        if int(evidence.get("independent_successful_trajectories", 0)) < 2:
            raise ValueError("contact calibration lacks independent successful trajectories")
        hashes = list(evidence.get("source_summary_sha256") or ())
        if not hashes or any(not _is_sha256(str(value)) for value in hashes):
            raise ValueError("contact calibration lacks source-summary fingerprints")
    else:
        raise ValueError("unsupported threshold panel role")

    by_stage = payload.get("by_stage") or {}
    if set(by_stage) != set(PI05_TASK_STAGES):
        raise ValueError("action thresholds must cover every task stage")
    for stage in PI05_TASK_STAGES:
        values = by_stage[stage]
        if set(values) != set(ACTION_THRESHOLD_FIELDS):
            raise ValueError(f"action thresholds are incomplete for stage {stage}")
        for field in ACTION_THRESHOLD_FIELDS:
            value = values[field]
            if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise ValueError(f"action threshold is non-finite: {stage}:{field}")
            if field == "minimum_tool_accuracy":
                if not 0.0 <= float(value) <= 1.0:
                    raise ValueError("tool accuracy threshold must be in [0, 1]")
            elif float(value) <= 0.0:
                raise ValueError("action-error thresholds must be positive")
        if float(values["median_position_m"]) > float(values["maximum_position_m"]):
            raise ValueError("median position threshold exceeds maximum threshold")
        if float(values["median_orientation_rad"]) > float(
            values["maximum_orientation_rad"]
        ):
            raise ValueError("median orientation threshold exceeds maximum threshold")
        if float(values["median_base_velocity"]) > float(
            values["maximum_base_velocity"]
        ):
            raise ValueError("median base threshold exceeds maximum threshold")

    claimed = str(payload.get("thresholds_sha256") or "")
    observed = canonical_payload_sha256(payload, hash_field="thresholds_sha256")
    if claimed != observed:
        raise ValueError("action-threshold fingerprint mismatch")
    return {
        "status": "passed",
        "protocol": "pi05-stage-action-threshold-audit-v1",
        "thresholds_sha256": claimed,
        "panel_role": panel_role,
        "deployment_calibrated": payload.get("deployment_calibrated") is True,
    }


def thresholds_for_stage(
    payload: Mapping[str, Any], stage: str
) -> dict[str, float]:
    if stage not in PI05_TASK_STAGES:
        raise ValueError(f"unknown PI0.5 task stage: {stage}")
    values = (payload.get("by_stage") or {}).get(stage) or {}
    return {field: float(values[field]) for field in ACTION_THRESHOLD_FIELDS}


def validate_tiny_overfit_gate(
    payload: Mapping[str, Any],
    *,
    dataset_manifest_sha256: str | None = None,
    action_contract: str | None = None,
) -> dict[str, Any]:
    """Validate evidence that the complete action pipeline can overfit a tiny set."""

    if payload.get("protocol") != PI05_TINY_OVERFIT_GATE_PROTOCOL:
        raise ValueError("unexpected PI0.5 tiny-overfit gate protocol")
    if payload.get("status") != "passed":
        raise ValueError("PI0.5 tiny-overfit contract has not passed")
    required = {
        "panel_role": PI05_TINY_OVERFIT_ROLE,
        "routing_error_count": 0,
        "action_fidelity_error_count": 0,
        "structural_error_count": 0,
        "mode_stage_cells": len(PI05_GRASP_MODES) * len(PI05_TASK_STAGES),
    }
    for field, value in required.items():
        if payload.get(field) != value:
            raise ValueError(f"tiny-overfit gate mismatch: {field}")
    for field in (
        "panel_sha256",
        "thresholds_sha256",
        "checkpoint_sha256",
        "training_contract_sha256",
        "dataset_manifest_sha256",
        "screen_sha256",
    ):
        if not _is_sha256(str(payload.get(field) or "")):
            raise ValueError(f"tiny-overfit gate lacks fingerprint: {field}")
    if (
        dataset_manifest_sha256 is not None
        and payload.get("dataset_manifest_sha256") != dataset_manifest_sha256
    ):
        raise ValueError("tiny-overfit gate dataset fingerprint mismatch")
    if action_contract is not None and payload.get("action_contract") != action_contract:
        raise ValueError("tiny-overfit gate action contract mismatch")
    claimed = str(payload.get("gate_sha256") or "")
    observed = canonical_payload_sha256(payload, hash_field="gate_sha256")
    if claimed != observed:
        raise ValueError("tiny-overfit gate fingerprint mismatch")
    return {
        "status": "passed",
        "protocol": "pi05-tiny-overfit-contract-gate-audit-v1",
        "gate_sha256": claimed,
        "checkpoint_sha256": payload["checkpoint_sha256"],
    }


def build_training_launch_audit(
    *,
    training_role: str,
    action_contract: str,
    dataset_manifest_sha256: str,
    requested_training_steps: int,
    scheduler_warmup_steps: int,
    scheduler_decay_steps: int,
    stage_panel: Mapping[str, Any] | None = None,
    action_thresholds: Mapping[str, Any] | None = None,
    tiny_overfit_gate: Mapping[str, Any] | None = None,
    independent_source_counts: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    """Build the fail-closed audit that must pass before a trainer is invoked."""

    if training_role not in PI05_TRAINING_ROLES:
        raise ValueError("unsupported PI0.5 training role")
    if action_contract not in {"residual_v1", "absolute_v1", "incremental_se3_v1"}:
        raise ValueError("unsupported PI0.5 action contract")
    if not _is_sha256(dataset_manifest_sha256):
        raise ValueError("training launch lacks a dataset manifest fingerprint")
    if requested_training_steps < 1:
        raise ValueError("training step budget must be positive")
    if not 0 <= scheduler_warmup_steps <= requested_training_steps:
        raise ValueError("scheduler warmup must be within the training budget")
    if scheduler_decay_steps != requested_training_steps:
        raise ValueError("scheduler decay must equal the requested training budget")

    panel_sha256 = None
    thresholds_sha256 = None
    tiny_gate_sha256 = None
    if training_role == "smoke":
        if requested_training_steps > 2:
            raise ValueError("smoke training is limited to two optimizer steps")
        if any(value is not None for value in (stage_panel, action_thresholds, tiny_overfit_gate)):
            raise ValueError("smoke training cannot consume promotion evidence")
    elif training_role == "tiny_overfit":
        if action_contract != "absolute_v1":
            raise ValueError("tiny-overfit contract requires absolute_v1")
        if stage_panel is None or action_thresholds is None:
            raise ValueError("tiny-overfit training requires a frozen panel and thresholds")
        validate_stage_panel(stage_panel, expected_role=PI05_TINY_OVERFIT_ROLE)
        expected_rows = len(PI05_GRASP_MODES) * len(PI05_TASK_STAGES)
        if len(tuple(stage_panel.get("observations") or ())) != expected_rows:
            raise ValueError(
                f"tiny-overfit training requires exactly {expected_rows} observations"
            )
        validate_action_thresholds(
            action_thresholds, panel_role=PI05_TINY_OVERFIT_ROLE
        )
        if stage_panel.get("dataset_manifest_sha256") != dataset_manifest_sha256:
            raise ValueError("tiny-overfit panel does not match the training dataset")
        panel_sha256 = str(stage_panel["panel_sha256"])
        thresholds_sha256 = str(action_thresholds["thresholds_sha256"])
    else:
        if action_contract != "absolute_v1":
            raise ValueError("candidate training requires expert-independent absolute_v1")
        if tiny_overfit_gate is None:
            raise ValueError("candidate training requires a passed tiny-overfit gate")
        validate_tiny_overfit_gate(tiny_overfit_gate, action_contract=action_contract)
        counts = {
            mode: int((independent_source_counts or {}).get(mode, 0))
            for mode in PI05_GRASP_MODES
        }
        insufficient = {mode: count for mode, count in counts.items() if count < 2}
        if insufficient:
            raise ValueError(
                f"candidate dataset lacks independent sources per mode: {insufficient}"
            )
        tiny_gate_sha256 = str(tiny_overfit_gate["gate_sha256"])

    payload: dict[str, Any] = {
        "schema_version": 1,
        "protocol": PI05_TRAINING_LAUNCH_AUDIT_PROTOCOL,
        "status": "passed",
        "training_role": training_role,
        "action_contract": action_contract,
        "dataset_manifest_sha256": dataset_manifest_sha256,
        "requested_training_steps": requested_training_steps,
        "scheduler_warmup_steps": scheduler_warmup_steps,
        "scheduler_decay_steps": scheduler_decay_steps,
        "stage_panel_sha256": panel_sha256,
        "action_thresholds_sha256": thresholds_sha256,
        "tiny_overfit_gate_sha256": tiny_gate_sha256,
        "independent_source_counts_by_mode": (
            dict(independent_source_counts or {})
            if training_role == "candidate"
            else None
        ),
    }
    payload["audit_sha256"] = canonical_payload_sha256(
        payload, hash_field="audit_sha256"
    )
    return payload


def validate_training_launch_audit(
    payload: Mapping[str, Any],
    *,
    expected_training_role: str | None = None,
    dataset_manifest_sha256: str | None = None,
) -> dict[str, Any]:
    if payload.get("protocol") != PI05_TRAINING_LAUNCH_AUDIT_PROTOCOL:
        raise ValueError("unexpected PI0.5 training-launch protocol")
    if payload.get("status") != "passed":
        raise ValueError("PI0.5 training launch has not passed")
    role = str(payload.get("training_role") or "")
    if expected_training_role is not None and role != expected_training_role:
        raise ValueError("PI0.5 training-launch role mismatch")
    if dataset_manifest_sha256 is not None and payload.get(
        "dataset_manifest_sha256"
    ) != dataset_manifest_sha256:
        raise ValueError("PI0.5 training-launch dataset fingerprint mismatch")
    claimed = str(payload.get("audit_sha256") or "")
    if claimed != canonical_payload_sha256(payload, hash_field="audit_sha256"):
        raise ValueError("PI0.5 training-launch fingerprint mismatch")
    return {"status": "passed", "training_role": role, "audit_sha256": claimed}


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)
