#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from corpus.programbench.batch001_unblock_priority_record import (
    make_priority_record,
    write_priority_record,
)
from corpus.programbench.operator_ready_platform import DOXYGEN_FINAL_STATE
from corpus.programbench.programbench_campaign_platform import (
    ACTION_QUEUE,
    CAMPAIGN_STATUS_BOARD,
    DOXYGEN_INSTANCE,
    EVIDENCE_GRAPH,
    RERUN_READINESS_MATRIX,
)

BATCH_STATE = Path(
    "assurance/evidence/programbench_batch001_state/"
    "programbench_batch001_state_run_20260527.BATCH001_STATE_AGGREGATED.json"
)
METADATA_RECOVERY_QUEUE = Path(
    "assurance/evidence/programbench_batch001_metadata_recovery_queue/"
    "programbench_batch001_metadata_recovery_queue_run_20260527.BATCH001_METADATA_RECOVERY_QUEUE_WRITTEN.json"
)
EXACT_PROVIDER_PROBE_PLAN = Path(
    "assurance/evidence/programbench_exact_provider_probe_plan/"
    "programbench_exact_provider_probe_plan_run_20260527.EXACT_PROVIDER_PROBE_PLAN_WRITTEN.json"
)

DIFFICULTY_ORDER = {
    "EASY_METADATA_ONLY": 10,
    "EASY_PROVIDER_MANIFEST": 20,
    "MODERATE_SCAN_REQUIRED": 30,
    "HARD_PROVENANCE_MISSING": 40,
    "HARD_POLICY_ADMISSION_REQUIRED": 50,
    "BLOCKED_UNKNOWN": 90,
}

ACTION_TO_PACKET = {
    "SUPPLY_SECURITY_POLICY_ADMISSION": "security_policy_admission",
    "SUPPLY_IMAGE_METADATA": "image_metadata_submission",
    "SUPPLY_OPERATOR_PROVENANCE": "operator_provenance_submission",
    "SUPPLY_PINNED_BASE_DIGEST": "pinned_base_digest_submission",
    "SUPPLY_ORIGINAL_BUILD_RECIPE": "original_build_recipe_submission",
    "INSTALL_APPROVED_SCANNER": "scanner_admission",
    "REVIEW_SCAN_POLICY": "security_policy_admission",
    "AUTHORIZE_BOUNDED_RERUN": "bounded_rerun_authorization",
}


@dataclass(slots=True)
class PriorityConfig:
    root: Path = Path(".")
    write_records: bool = True


class ProgramBenchBatch001UnblockPriority:
    def __init__(self, config: PriorityConfig | None = None) -> None:
        self.config = config or PriorityConfig()

    def build(self) -> dict[str, Any]:
        batch_state = self._read(BATCH_STATE)
        states = batch_state.get("instances", [])
        metadata_queue = _by_id(self._read(METADATA_RECOVERY_QUEUE).get("items", []))
        probe_plan = _by_id(self._read(EXACT_PROVIDER_PROBE_PLAN).get("plans", []))
        actions = _by_id(self._read(ACTION_QUEUE).get("actions", []))

        ranked = [
            _priority_row(
                state,
                metadata_queue.get(state.get("instance_id", ""), {}),
                probe_plan.get(state.get("instance_id", ""), {}),
                actions.get(state.get("instance_id", ""), {}),
            )
            for state in states
        ]
        ranked.sort(
            key=lambda row: (DIFFICULTY_ORDER[row["estimated_difficulty"]], row["rank_tiebreaker"])
        )
        for index, row in enumerate(ranked, start=1):
            row["rank"] = index
            row.pop("rank_tiebreaker", None)

        top_targets = ranked[:3]
        summary = {
            "total_instances": len(ranked),
            "difficulty_counts": _count_by(ranked, "estimated_difficulty"),
            "top_3_instance_ids": [row["instance_id"] for row in top_targets],
            "any_target_can_proceed_without_security_policy_admission": any(
                row["can_proceed_without_security_policy_admission_for_next_step"] for row in ranked
            ),
            "any_target_has_lower_scan_security_burden_than_doxygen": any(
                row["lower_scan_security_burden_than_doxygen"] for row in ranked
            ),
            "doxygen_recommendation": "PAUSE_UNTIL_OPERATOR_SECURITY_POLICY_ADMISSION",
            "top_recommended_next_codex_action": (
                "Request or admit exact image metadata submission packets for the top missing-metadata Batch001 targets; "
                "do not execute them until manifest, scan, policy, and bounded-rerun gates close."
            ),
        }
        record = make_priority_record(
            status="BATCH001_UNBLOCK_PRIORITY_WRITTEN",
            payload={
                "record_id": "programbench_batch001_unblock_priority_run_20260528",
                "inputs": {
                    "batch001_state_aggregator": _rel(BATCH_STATE),
                    "metadata_recovery_queue": _rel(METADATA_RECOVERY_QUEUE),
                    "exact_provider_probe_plan": _rel(EXACT_PROVIDER_PROBE_PLAN),
                    "operator_action_queue": _rel(ACTION_QUEUE),
                    "campaign_status_board": _rel(CAMPAIGN_STATUS_BOARD),
                    "rerun_readiness_matrix": _rel(RERUN_READINESS_MATRIX),
                    "evidence_graph": _rel(EVIDENCE_GRAPH),
                    "doxygen_final_state": _rel(DOXYGEN_FINAL_STATE),
                },
                "ranked_unblock_list": ranked,
                "top_3_safest_next_targets": top_targets,
                "summary": summary,
                "safety_closure": {
                    "execution_performed": False,
                    "docker_run_performed": False,
                    "docker_pull_performed": False,
                    "programbench_rerun_performed": False,
                    "policy_exception_granted": False,
                    "training_rows_written": False,
                    "training_eligible": False,
                    "cache_ready": False,
                    "executable": False,
                },
                "authorization": _closed_auth(),
            },
        )
        if self.config.write_records:
            write_priority_record(
                record,
                self.config.root
                / "assurance"
                / "evidence"
                / "programbench_batch001_unblock_priority",
            )
        return record

    def _read(self, path: Path) -> dict[str, Any]:
        full = self.config.root / path
        if not full.exists():
            return {}
        return json.loads(full.read_text(encoding="utf-8"))


def _priority_row(
    state: dict[str, Any],
    recovery_item: dict[str, Any],
    probe: dict[str, Any],
    action: dict[str, Any],
) -> dict[str, Any]:
    instance_id = state.get("instance_id", "")
    is_doxygen = instance_id == DOXYGEN_INSTANCE
    image_metadata_status = (
        "PRESENT" if state.get("image_name") and state.get("image_digest") else "MISSING"
    )
    provider_manifest_status = _provider_manifest_status(probe)
    scan_status = state.get("scan_status", "SCAN_NOT_EVALUATED")
    required_action = recovery_item.get("required_action") or _required_action_from_state(state)
    current_blocker = _current_blocker(state, required_action)
    estimated_difficulty = _estimate_difficulty(state, required_action, probe)
    exact_operator_packet = ACTION_TO_PACKET.get(
        action.get("action_type", ""), _packet_for_required_action(required_action)
    )
    can_proceed_without_policy = (
        exact_operator_packet in {"image_metadata_submission", "operator_provenance_submission"}
        and not is_doxygen
    )
    lower_burden = not is_doxygen and scan_status == "SCAN_NOT_EVALUATED"
    return {
        "instance_id": instance_id,
        "tool_name": state.get("tool_name", ""),
        "image_name": state.get("image_name", ""),
        "image_digest": state.get("image_digest", ""),
        "current_blocker": current_blocker,
        "artifact_authority_status": state.get(
            "artifact_authority", "ARTIFACT_AUTHORITY_INCONCLUSIVE"
        ),
        "image_metadata_status": image_metadata_status,
        "provider_manifest_status": provider_manifest_status,
        "scan_status": scan_status,
        "policy_admission_requirement": _policy_requirement(state, probe),
        "bounded_rerun_readiness": state.get("bounded_rerun_status", "BOUNDED_RERUN_NOT_REQUESTED"),
        "training_eligibility": state.get("training_eligible", "TRAINING_ELIGIBLE_FALSE"),
        "next_unblocker": state.get("next_unblocker", ""),
        "estimated_difficulty": estimated_difficulty,
        "exact_operator_packet_needed": exact_operator_packet,
        "operator_action_type": action.get("action_type", ""),
        "why_easier_or_harder_than_doxygen": _relative_to_doxygen(
            is_doxygen, estimated_difficulty, provider_manifest_status
        ),
        "can_proceed_without_security_policy_admission_for_next_step": can_proceed_without_policy,
        "lower_scan_security_burden_than_doxygen": lower_burden,
        "execution_authorized": False,
        "training_rows_written": False,
        "evidence_refs": {
            "state": state.get("evidence_refs", {}),
            "recovery_queue": recovery_item.get("evidence_refs", {}),
            "operator_action": action.get("evidence_refs", {}),
        },
        "rank_tiebreaker": instance_id,
    }


def _estimate_difficulty(state: dict[str, Any], required_action: str, probe: dict[str, Any]) -> str:
    if state.get("scan_status") == "CLEANROOM_IMAGE_SCAN_FAILED":
        return "HARD_POLICY_ADMISSION_REQUIRED"
    if required_action == "RECOVER_SECURITY_POLICY_ADMISSION":
        return "HARD_POLICY_ADMISSION_REQUIRED"
    if required_action == "RECOVER_OPERATOR_PROVENANCE":
        return "HARD_PROVENANCE_MISSING"
    if not state.get("image_name"):
        return "EASY_METADATA_ONLY"
    if probe.get("status") not in {"", "EXACT_PROVIDER_PROBE_ALREADY_KNOWN"}:
        return "EASY_PROVIDER_MANIFEST"
    if state.get("scan_status") == "SCAN_NOT_EVALUATED":
        return "MODERATE_SCAN_REQUIRED"
    return "BLOCKED_UNKNOWN"


def _provider_manifest_status(probe: dict[str, Any]) -> str:
    status = probe.get("status", "")
    if status == "EXACT_PROVIDER_PROBE_ALREADY_KNOWN":
        return "VERIFIED_BY_EXISTING_EXACT_MANIFEST"
    if status == "EXACT_PROVIDER_PROBE_BLOCKED_NAME_INFERENCE_UNSAFE":
        return "MISSING_NAME_INFERENCE_UNSAFE"
    if not status:
        return "MISSING_NOT_PLANNED"
    return status


def _policy_requirement(state: dict[str, Any], probe: dict[str, Any]) -> str:
    if state.get("scan_status") == "CLEANROOM_IMAGE_SCAN_FAILED":
        return "REQUIRED_BEFORE_EXECUTION"
    if probe.get("policy_admission_required_if_scan_fails"):
        return "CONDITIONAL_IF_SCAN_FAILS"
    return "NOT_EVALUATED"


def _required_action_from_state(state: dict[str, Any]) -> str:
    if state.get("scan_status") == "CLEANROOM_IMAGE_SCAN_FAILED":
        return "RECOVER_SECURITY_POLICY_ADMISSION"
    if not state.get("image_name"):
        return "RECOVER_TASK_IMAGE_METADATA"
    return "NO_ACTION_REQUIRED"


def _current_blocker(state: dict[str, Any], required_action: str) -> str:
    if required_action == "RECOVER_SECURITY_POLICY_ADMISSION":
        return "SCAN_FAILED_OPERATOR_SECURITY_POLICY_ADMISSION_REQUIRED"
    if required_action == "RECOVER_TASK_IMAGE_METADATA":
        return "MISSING_IMAGE_METADATA_AND_PROVIDER_MANIFEST"
    if required_action == "RECOVER_OPERATOR_PROVENANCE":
        return "OPERATOR_PROVENANCE_REQUIRED"
    return state.get("next_unblocker", "UNKNOWN")


def _packet_for_required_action(required_action: str) -> str:
    return {
        "RECOVER_SECURITY_POLICY_ADMISSION": "security_policy_admission",
        "RECOVER_TASK_IMAGE_METADATA": "image_metadata_submission",
        "RECOVER_PROVIDER_MANIFEST": "image_metadata_submission",
        "RECOVER_LOCAL_IMAGE_DIGEST": "image_metadata_submission",
        "RECOVER_REPLAY_VERIFIER_METADATA": "image_metadata_submission",
        "RECOVER_OPERATOR_PROVENANCE": "operator_provenance_submission",
    }.get(required_action, "operator_evidence_packet")


def _relative_to_doxygen(is_doxygen: bool, difficulty: str, provider_manifest_status: str) -> str:
    if is_doxygen:
        return "Baseline: artifact authority and digest are proven, but scan failure makes execution depend on real operator security policy admission."
    if difficulty == "EASY_METADATA_ONLY":
        return (
            "Easier for the next Codex step because it needs exact image metadata/provenance before any scan or policy exception; "
            "harder for execution because provider manifest and scan evidence are still absent."
        )
    if difficulty == "EASY_PROVIDER_MANIFEST":
        return f"Easier than Doxygen if exact provider manifest evidence is supplied; current provider status is {provider_manifest_status}."
    if difficulty == "MODERATE_SCAN_REQUIRED":
        return "Potentially easier than Doxygen only if the later scan passes; no execution is authorized before scan evidence."
    return "Harder than Doxygen because provenance or authority is less complete than Doxygen's official artifact chain."


def _by_id(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(item.get("instance_id", "")): item for item in items}


def _count_by(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        value = str(item.get(key, ""))
        counts[value] = counts.get(value, 0) + 1
    return counts


def _closed_auth() -> dict[str, bool]:
    return {
        "docker_execution_authorized": False,
        "docker_pull_authorized": False,
        "programbench_rerun_authorized": False,
        "rebuild_authorized": False,
        "remediation_authorized": False,
        "policy_exception_granted": False,
        "training_rows_written": False,
        "training_eligible": False,
        "cache_ready": False,
        "executable": False,
    }


def _rel(path: Path) -> str:
    return str(path).replace("\\", "/")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Write the ProgramBench Batch001 unblock priority record."
    )
    parser.add_argument("--json", action="store_true", help="Print the priority record JSON.")
    parser.add_argument("--no-write", action="store_true", help="Do not write signed evidence.")
    args = parser.parse_args(argv)
    record = ProgramBenchBatch001UnblockPriority(
        PriorityConfig(write_records=not args.no_write)
    ).build()
    if args.json:
        print(json.dumps(record, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
