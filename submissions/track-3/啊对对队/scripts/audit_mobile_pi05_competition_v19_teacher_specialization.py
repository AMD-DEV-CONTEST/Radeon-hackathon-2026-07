#!/usr/bin/env python3
"""Generate and audit the frozen V19 three-case expert-teacher collection."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


PROTOCOL = "pi05-competition-v19-expert-teacher-specialization-preregistration-v1"
COLLECTION_PROTOCOL = "pi05-competition-v19-deterministic-expert-teacher-collection-v1"
AUDIT_PROTOCOL = "pi05-competition-v19-expert-teacher-admission-audit-v1"
TRAINING_SEED = 11
RUNTIME_SEED = 2026080206
INFERENCE_SEEDS = (20260727, 20260728, 20260729)
PANEL_SHA256 = "28df60fb02d9afadbd396621672bdeaa03515a3d007e3411f2f1953eb576a0b0"
TEACHER_EPISODE_COUNT = 3
MAX_EPISODE_BYTES = 25_000_000


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _payload_sha256(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _write_json_new(path: Path, payload: Mapping[str, Any]) -> None:
    path = path.resolve()
    if path.exists():
        raise FileExistsError(f"immutable output already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def audit_preregistration(
    preregistration: Mapping[str, Any],
    source_smoke: Mapping[str, Any],
    deployment_preregistration: Mapping[str, Any],
    *,
    source_smoke_sha256: str,
    deployment_preregistration_sha256: str,
) -> dict[str, Any]:
    errors: list[str] = []
    source_contract = preregistration.get("source_smoke_plan") or {}
    frozen = preregistration.get("frozen_deployment_contract") or {}
    collection = preregistration.get("collection_contract") or {}
    training = preregistration.get("training_contract") or {}
    source_episodes = list(source_smoke.get("episodes") or ())
    source_ids = [str(item.get("episode_id") or "") for item in source_episodes]

    if preregistration.get("protocol") != PROTOCOL:
        errors.append("preregistration_protocol_mismatch")
    if preregistration.get("status") not in {
        "frozen_before_collection",
        "frozen_after_collection_before_training",
    }:
        errors.append("preregistration_not_frozen")
    if str(source_contract.get("sha256") or "") != source_smoke_sha256:
        errors.append("source_smoke_sha256_mismatch")
    if source_smoke.get("collection_id") != source_contract.get("collection_id"):
        errors.append("source_smoke_collection_id_mismatch")
    if source_smoke.get("status") != "frozen_before_execution":
        errors.append("source_smoke_not_frozen")
    required_ids = list(map(str, source_contract.get("required_evaluation_case_ids") or ()))
    if source_ids != required_ids or len(source_ids) != TEACHER_EPISODE_COUNT:
        errors.append("source_smoke_episode_order_mismatch")
    if any(
        int(item.get("session_index", -1))
        != int(source_contract.get("required_session_index", -2))
        for item in source_episodes
    ):
        errors.append("source_smoke_session_mismatch")
    if any(
        int(item.get("seed", -1))
        != int(source_contract.get("required_runtime_seed", -2))
        for item in source_episodes
    ):
        errors.append("source_smoke_runtime_seed_mismatch")

    if str(frozen.get("sha256") or "") != deployment_preregistration_sha256:
        errors.append("deployment_preregistration_sha256_mismatch")
    fixed = deployment_preregistration.get("fixed_contract") or {}
    if int(frozen.get("training_seed", -1)) != TRAINING_SEED:
        errors.append("training_seed_mismatch")
    if int(fixed.get("training_seed", -1)) != TRAINING_SEED:
        errors.append("inherited_training_seed_mismatch")
    if int(training.get("seed", -1)) != TRAINING_SEED:
        errors.append("training_contract_seed_mismatch")
    if int(frozen.get("runtime_seed", -1)) != RUNTIME_SEED:
        errors.append("runtime_seed_mismatch")
    if int(fixed.get("runtime_seed", -1)) != RUNTIME_SEED:
        errors.append("inherited_runtime_seed_mismatch")
    if tuple(frozen.get("inference_seeds") or ()) != INFERENCE_SEEDS:
        errors.append("inference_seeds_mismatch")
    if tuple(fixed.get("inference_seeds") or ()) != INFERENCE_SEEDS:
        errors.append("inherited_inference_seeds_mismatch")
    if str(frozen.get("frozen_panel_sha256") or "") != PANEL_SHA256:
        errors.append("frozen_panel_sha256_mismatch")
    if str(fixed.get("frozen_panel_sha256") or "") != PANEL_SHA256:
        errors.append("inherited_frozen_panel_sha256_mismatch")
    if int(frozen.get("frozen_panel_observations", 0)) != 12:
        errors.append("frozen_panel_size_mismatch")
    if int(collection.get("teacher_episode_count", 0)) != TEACHER_EPISODE_COUNT:
        errors.append("teacher_episode_count_mismatch")
    required_successes = int(collection.get("required_verified_successes", 0))
    if not 2 <= required_successes <= TEACHER_EPISODE_COUNT:
        errors.append("teacher_success_gate_mismatch")
    viable_subset = preregistration.get("viable_subset_admission") or {}
    if required_successes < TEACHER_EPISODE_COUNT:
        required_subset = list(viable_subset.get("required_success_episode_ids") or ())
        allowed_failures = list(viable_subset.get("allowed_failure_telemetry") or ())
        if (
            len(required_subset) != required_successes
            or len(allowed_failures) != TEACHER_EPISODE_COUNT - required_successes
        ):
            errors.append("viable_subset_admission_mismatch")
    if collection.get("system_control_class") != "deterministic_expert_teacher":
        errors.append("teacher_control_class_mismatch")
    if collection.get("collector_policy_mode") != "shadow":
        errors.append("collector_policy_mode_mismatch")
    for key in ("policy_checkpoint_allowed", "vla_policy_service_allowed", "audit_only"):
        if collection.get(key) is not False:
            errors.append(f"collection_contract_{key}_must_be_false")
    if collection.get("wrist_rgbd") is not False:
        errors.append("wrist_rgbd_changes_observation_contract")
    if collection.get("policy_visual_modality") != "rgbd":
        errors.append("policy_visual_modality_mismatch")
    if collection.get("record_media_all_episodes") is not True:
        errors.append("all_episode_media_must_be_recorded")
    if collection.get("prune_rejected_dataset_payloads") is not True:
        errors.append("rejected_dataset_payloads_must_be_pruned")
    if int(collection.get("expert_reference_count_per_episode", -1)) != 1:
        errors.append("expert_reference_count_mismatch")
    if int(collection.get("expert_fallback_count_per_episode", -1)) != 0:
        errors.append("expert_fallback_count_mismatch")
    if int(collection.get("pure_vla_action_runs_per_episode", -1)) != 0:
        errors.append("pure_vla_action_count_mismatch")
    if training.get("confirmation_data_allowed") is not False:
        errors.append("confirmation_data_must_remain_forbidden")
    if training.get("failed_teacher_trajectories_allowed") is not False:
        errors.append("failed_teacher_data_must_remain_forbidden")
    if training.get("expert_teacher_data_counted_as_pure_vla") is not False:
        errors.append("expert_teacher_pure_vla_credit_must_be_false")

    return {
        "status": "passed" if not errors else "failed",
        "errors": errors,
        "error_count": len(errors),
        "source_episode_count": len(source_episodes),
        "source_episode_ids": source_ids,
        "training_seed": training.get("seed"),
        "runtime_seed": frozen.get("runtime_seed"),
        "inference_seeds": list(frozen.get("inference_seeds") or ()),
        "frozen_panel_sha256": frozen.get("frozen_panel_sha256"),
        "deployment_fixed_contract_sha256": _payload_sha256(fixed),
        "deployment_immutability_checks_sha256": _payload_sha256(
            deployment_preregistration.get("immutability_checks") or {}
        ),
        "deployment_promotion_gates_sha256": _payload_sha256(
            deployment_preregistration.get("promotion_gates") or {}
        ),
    }


def build_teacher_collection_config(
    preregistration: Mapping[str, Any], source_smoke: Mapping[str, Any]
) -> dict[str, Any]:
    episodes = []
    for source in source_smoke.get("episodes") or ():
        source_id = str(source["episode_id"])
        teacher = dict(source)
        teacher.update(
            {
                "episode_id": f"v19-expert-teacher-{source_id}",
                "evaluation_case_id": source_id,
                "teacher_for_evaluation_case_id": source_id,
                "source_evaluation_case_sha256": _payload_sha256(source),
                "split": "competition_specialization_train",
                "demonstration_provenance": "high_quality_deterministic_expert_candidate",
                "system_control_class": "deterministic_expert_teacher",
                "pure_vla_eligible": False,
                "pure_vla_action_runs": 0,
                "expert_reference_allowed": True,
                "expert_reference_used": True,
                "expert_reference_count": 1,
                "expert_fallback_allowed": False,
                "expert_fallback_count": 0,
                "oracle_pose_allowed": True,
                "exact_goal_coordinate_input_allowed": True,
                "external_stage_input_allowed": True,
                "agent_skill_selection_required": False,
                "dataset_admission_allowed": False,
                "conditional_training_admission": "only_after_passed_v19_teacher_admission_audit",
            }
        )
        episodes.append(teacher)
    return {
        "schema_version": 1,
        "collection_id": "pi05-competition-v19-session08-expert-teacher-3",
        "protocol": COLLECTION_PROTOCOL,
        "status": "frozen_generated_collection_plan",
        "source_smoke_collection_id": source_smoke.get("collection_id"),
        "source_smoke_plan_sha256": preregistration["source_smoke_plan"]["sha256"],
        "selection_rule": "all three source cases in immutable frozen source order",
        "planned_attempts": TEACHER_EPISODE_COUNT,
        "target_successes": TEACHER_EPISODE_COUNT,
        "dataset_admission_allowed": False,
        "training_seed": TRAINING_SEED,
        "runtime_seed": RUNTIME_SEED,
        "system_control_class": "deterministic_expert_teacher",
        "pure_vla_success_credit": 0,
        "admission_policy": (
            "All three expert episodes must pass the V19 collector, safety, media, "
            "dataset, and attribution audit before any derived training dataset is built."
        ),
        "episodes": episodes,
    }


def audit_collection(
    expected_config: Mapping[str, Any],
    collection_summary: Mapping[str, Any],
    dataset_audit: Mapping[str, Any],
    *,
    collector_config_sha256: str,
    collector_script_sha256: str,
    viable_subset_admission: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    errors: list[str] = []
    expected_episodes = list(expected_config.get("episodes") or ())
    expected_ids = [str(item["episode_id"]) for item in expected_episodes]
    viable_subset_admission = viable_subset_admission or {}
    required_success_ids = list(
        map(
            str,
            viable_subset_admission.get("required_success_episode_ids")
            or expected_ids,
        )
    )
    allowed_failures = {
        str(item["episode_id"]): item
        for item in viable_subset_admission.get("allowed_failure_telemetry", ())
    }
    if (
        len(required_success_ids) < 2
        or len(required_success_ids) + len(allowed_failures) != len(expected_ids)
        or set(required_success_ids).intersection(allowed_failures)
        or set(required_success_ids).union(allowed_failures) != set(expected_ids)
    ):
        raise ValueError("viable subset must partition all three teacher episodes")
    results = list(collection_summary.get("results") or ())
    result_ids = [str(item.get("episode_id") or "") for item in results]
    runtime = collection_summary.get("runtime_contract") or {}

    if collection_summary.get("collection_id") != expected_config.get("collection_id"):
        errors.append("collection_id_mismatch")
    if str(runtime.get("config_sha256") or "") != collector_config_sha256:
        errors.append("collector_config_sha256_mismatch")
    if str(runtime.get("collector_sha256") or "") != collector_script_sha256:
        errors.append("collector_script_sha256_mismatch")
    if runtime.get("policy_mode") != "shadow":
        errors.append("collector_not_in_expert_shadow_mode")
    if collection_summary.get("checkpoint_selection") is not None:
        errors.append("vla_checkpoint_was_supplied")
    if collection_summary.get("persistent_policy_service") is not False:
        errors.append("vla_policy_service_was_supplied")
    if collection_summary.get("goal_verdict_required") is not False:
        errors.append("vla_goal_verdict_was_enabled")
    if collection_summary.get("grasp_mode_verdict_required") is not False:
        errors.append("vla_grasp_verdict_was_enabled")
    if collection_summary.get("policy_visual_modality") != "rgbd":
        errors.append("collector_visual_modality_mismatch")
    if collection_summary.get("status") != "passed":
        errors.append("collector_status_not_passed")
    count_fields = {
        "requested_episodes": TEACHER_EPISODE_COUNT,
        "completed_episodes": TEACHER_EPISODE_COUNT,
        "unattempted_episodes": 0,
        "successful_episodes": len(required_success_ids),
        "failed_episodes": len(allowed_failures),
    }
    for field, expected in count_fields.items():
        if int(collection_summary.get(field, -1)) != expected:
            errors.append(f"collector_{field}_mismatch")
    if result_ids != expected_ids:
        errors.append("collector_result_order_mismatch")
    if list(map(str, collection_summary.get("successful_episode_order") or ())) != required_success_ids:
        errors.append("collector_success_order_mismatch")
    if set(map(str, collection_summary.get("media_episode_ids") or ())) != set(expected_ids):
        errors.append("teacher_media_coverage_mismatch")
    if collection_summary.get("merge_error") is not None:
        errors.append("teacher_dataset_merge_failed")
    if not collection_summary.get("merged_dataset_root"):
        errors.append("merged_teacher_dataset_missing")

    expected_by_id = {str(item["episode_id"]): item for item in expected_episodes}
    accepted_ids: list[str] = []
    for result in results:
        episode_id = str(result.get("episode_id") or "")
        parameters = result.get("parameters") or {}
        media = result.get("media") or {}
        if parameters != expected_by_id.get(episode_id):
            errors.append(f"collector_parameters_mismatch:{episode_id}")
        if episode_id in allowed_failures:
            failure = allowed_failures[episode_id]
            failure_checks = {
                "return_code": int(result.get("return_code", 0))
                == int(failure.get("return_code", 2)),
                "success": result.get("success") is False,
                "failure_stage": result.get("failure_stage")
                == failure.get("failure_stage"),
                "safety": result.get("safety_violation") is False,
                "no_dataset": result.get("dataset_saved") is False
                and int(result.get("frames") or 0) == 0
                and int(result.get("dataset_bytes") or 0) == 0,
                "not_bc_label": (result.get("recovery_label") or {}).get(
                    "verified_success"
                )
                is False,
            }
            for name, passed in failure_checks.items():
                if not passed:
                    errors.append(f"allowed_failure_{name}_mismatch:{episode_id}")
            continue
        checks = {
            "return_code": result.get("return_code") == 0,
            "success": result.get("success") is True,
            "failure_stage": result.get("failure_stage") is None,
            "lift_success": result.get("lift_success") is True,
            "transport_success": result.get("transport_success") is True,
            "placed_before_release": result.get("placed_before_release") is True,
            "released": result.get("released") is True,
            "place_force_safety_abort": result.get("place_force_safety_abort") is False,
            "release_force_safety_abort": result.get("release_force_safety_abort") is False,
            "safety_violation": result.get("safety_violation") is False,
            "dataset_saved": result.get("dataset_saved") is True,
            "dataset_storage_format": result.get("dataset_storage_format") == "video",
            "dataset_frames": int(result.get("frames") or 0) > 0,
            "dataset_bytes": 0 < int(result.get("dataset_bytes") or 0) <= MAX_EPISODE_BYTES,
            "verified_success": (result.get("recovery_label") or {}).get(
                "verified_success"
            )
            is True,
            "summary_present": bool(result.get("summary")),
            "log_present": bool(result.get("log")),
            "video_requested": media.get("video_requested") is True,
            "video_saved": media.get("video_saved") is True
            and bool(media.get("video_path")),
            "snapshot_requested": media.get("snapshot_requested") is True,
            "snapshot_saved": media.get("snapshot_saved") is True
            and bool(media.get("snapshot_path")),
            "no_expert_fallback": int(parameters.get("expert_fallback_count", -1)) == 0,
            "not_pure_vla": parameters.get("pure_vla_eligible") is False
            and int(parameters.get("pure_vla_action_runs", -1)) == 0,
            "expert_teacher_attributed": parameters.get("expert_reference_used") is True
            and int(parameters.get("expert_reference_count", 0)) == 1,
        }
        for name, passed in checks.items():
            if not passed:
                errors.append(f"episode_{name}_failed:{episode_id}")
        if all(checks.values()):
            accepted_ids.append(episode_id)

    if dataset_audit.get("status") != "passed" or dataset_audit.get(
        "errors"
    ) not in ([], ()):
        errors.append("general_mobile_dataset_audit_failed")
    if int(dataset_audit.get("episodes", 0)) != len(required_success_ids):
        errors.append("dataset_audit_episode_count_mismatch")
    if dataset_audit.get("policy_modality") != "rgbd":
        errors.append("dataset_audit_visual_modality_mismatch")
    if dataset_audit.get("privileged_state_in_policy") is not False:
        errors.append("privileged_state_leakage")
    if dataset_audit.get("storage_format") != "video":
        errors.append("dataset_storage_not_video")
    if int(dataset_audit.get("fps", 0)) != 30:
        errors.append("dataset_fps_mismatch")
    merged = collection_summary.get("merged_dataset_root")
    audited = dataset_audit.get("dataset_root")
    if merged and audited and Path(str(merged)).resolve() != Path(str(audited)).resolve():
        errors.append("dataset_audit_root_mismatch")

    passed = not errors and accepted_ids == required_success_ids
    return {
        "status": "passed" if passed else "failed",
        "decision": (
            f"admit_{len(required_success_ids)}_expert_teacher_episodes"
            if passed
            else "reject_all_teacher_episodes"
        ),
        "training_admission_allowed": passed,
        "errors": errors,
        "error_count": len(errors),
        "accepted_episode_ids": accepted_ids if passed else [],
        "failure_telemetry_episode_ids": sorted(allowed_failures) if passed else [],
        "rejected_episode_ids": [] if passed else expected_ids,
        "expert_teacher_episode_count": len(accepted_ids) if passed else 0,
        "expert_reference_count": len(accepted_ids) if passed else 0,
        "expert_fallback_count": 0 if passed else None,
        "pure_vla_action_runs": 0,
        "pure_vla_success_credit": 0,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preregistration", type=Path, required=True)
    parser.add_argument("--source-smoke", type=Path, required=True)
    parser.add_argument("--deployment-preregistration", type=Path, required=True)
    parser.add_argument("--collector-config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--collection-summary", type=Path)
    parser.add_argument("--dataset-audit", type=Path)
    args = parser.parse_args(argv)
    if (args.collection_summary is None) != (args.dataset_audit is None):
        parser.error("collection summary and dataset audit must be supplied together")

    preregistration = _load_json(args.preregistration)
    source_smoke = _load_json(args.source_smoke)
    deployment = _load_json(args.deployment_preregistration)
    preflight = audit_preregistration(
        preregistration,
        source_smoke,
        deployment,
        source_smoke_sha256=_sha256(args.source_smoke),
        deployment_preregistration_sha256=_sha256(
            args.deployment_preregistration
        ),
    )
    expected_config = build_teacher_collection_config(preregistration, source_smoke)
    if preflight["status"] != "passed":
        payload = {
            "schema_version": 1,
            "protocol": AUDIT_PROTOCOL,
            "status": "failed",
            "phase": "preflight",
            "preflight": preflight,
            "training_admission_allowed": False,
        }
        _write_json_new(args.output, payload)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 2

    if args.collector_config.exists():
        if _load_json(args.collector_config) != expected_config:
            raise ValueError("existing collector config differs from frozen generated plan")
    else:
        _write_json_new(args.collector_config, expected_config)

    collection = None
    if args.collection_summary is not None:
        collector_script = Path(__file__).resolve().with_name(
            "collect_mobile_suction_dataset_rocm.py"
        )
        collection = audit_collection(
            expected_config,
            _load_json(args.collection_summary),
            _load_json(args.dataset_audit),
            collector_config_sha256=_sha256(args.collector_config),
            collector_script_sha256=_sha256(collector_script),
            viable_subset_admission=preregistration.get(
                "viable_subset_admission"
            ),
        )
    passed = collection is None or collection["status"] == "passed"
    payload = {
        "schema_version": 1,
        "protocol": AUDIT_PROTOCOL,
        "status": "ready_for_expert_collection" if collection is None else collection["status"],
        "phase": "preflight" if collection is None else "post_collection_admission",
        "preregistration": str(args.preregistration.resolve()),
        "preregistration_sha256": _sha256(args.preregistration),
        "source_smoke": str(args.source_smoke.resolve()),
        "source_smoke_sha256": _sha256(args.source_smoke),
        "deployment_preregistration": str(args.deployment_preregistration.resolve()),
        "deployment_preregistration_sha256": _sha256(
            args.deployment_preregistration
        ),
        "collector_config": str(args.collector_config.resolve()),
        "collector_config_sha256": _sha256(args.collector_config),
        "preflight": preflight,
        "collection": collection,
        "training_admission_allowed": bool(
            collection and collection["training_admission_allowed"]
        ),
        "expert_teacher_data_counted_as_pure_vla": False,
        "source_cases_evaluation_contaminated_after_training": True,
        "claim_boundary": (
            "Expert teacher data gate only. These rollouts receive zero pure-VLA "
            "success credit and the three source cases cannot be reused for evaluation."
        ),
    }
    _write_json_new(args.output, payload)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
