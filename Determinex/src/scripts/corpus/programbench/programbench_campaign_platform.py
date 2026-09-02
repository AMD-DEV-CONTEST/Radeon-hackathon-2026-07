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

from corpus.programbench.programbench_platform_record import (
    make_platform_record,
    write_platform_record,
)

DOXYGEN_INSTANCE = "doxygen__doxygen.966d98e"
DOXYGEN_TOOL = "doxygen"
DOXYGEN_IMAGE = "programbench/doxygen_1776_doxygen.966d98e:task_cleanroom"
DOXYGEN_DIGEST = "sha256:cc50d0f7e9a1f3f90512e3d4c34781f4686a8fa3774fbff489947ef41bde2e72"
RUN_ID = "run_20260527"

DOXYGEN_FINAL = Path(
    "assurance/evidence/programbench_doxygen_lane_final_state/"
    "doxygen__doxygen.966d98e.DOXYGEN_LANE_FINAL_STATE_WRITTEN.json"
)
MISSING_IMAGE_INVENTORY = Path("assurance/evidence/programbench_missing_image_inventory.json")
BATCH_RESULT = Path("assurance/evidence/programbench_replay_batch_001_result.json")
CAMPAIGN_STATUS_BOARD = Path(
    "assurance/evidence/programbench_campaign_status_boards/"
    "programbench_codex_campaign_status_board_20260528.CAMPAIGN_STATUS_BOARD_WRITTEN.json"
)
RERUN_READINESS_MATRIX = Path(
    "assurance/evidence/programbench_rerun_readiness_matrix/"
    "programbench_rerun_readiness_matrix_20260528.RERUN_READINESS_MATRIX_WRITTEN.json"
)
GENERIC_POLICY_ADMISSION = Path(
    "assurance/evidence/programbench_generic_operator_policy_admission/"
    "programbench_generic_operator_policy_admission_run_20260527.GENERIC_POLICY_ADMISSION_REQUIRED.json"
)
GENERIC_PREFLIGHT = Path(
    "assurance/evidence/programbench_generic_execution_preflight/"
    "programbench_generic_execution_preflight_run_20260527.GENERIC_EXECUTION_PREFLIGHT_BLOCKED_POLICY_ADMISSION_REQUIRED.json"
)
BATCH_STATE = Path(
    "assurance/evidence/programbench_batch001_state/"
    "programbench_batch001_state_run_20260527.BATCH001_STATE_AGGREGATED.json"
)
BATCH_SKIPS = Path(
    "assurance/evidence/programbench_batch_skip_decisions/"
    "programbench_batch_skip_decisions_run_20260527.BATCH_SKIP_DECISIONS_WRITTEN.json"
)
ACTION_QUEUE = Path(
    "assurance/evidence/programbench_operator_action_queue/"
    "programbench_operator_action_queue_run_20260527.OPERATOR_ACTION_QUEUE_WRITTEN.json"
)
REPORT = Path(
    "assurance/evidence/programbench_campaign_reporting_api/"
    "programbench_campaign_reporting_api_run_20260527.CAMPAIGN_REPORTING_API_WRITTEN.json"
)
EVIDENCE_GRAPH = Path(
    "assurance/evidence/programbench_evidence_graph/"
    "programbench_evidence_graph_run_20260527.EVIDENCE_GRAPH_WRITTEN.json"
)

ARTIFACT_AUTHORITY = {
    "ARTIFACT_AUTHORITY_PRESENT",
    "ARTIFACT_AUTHORITY_ABSENT",
    "ARTIFACT_AUTHORITY_INCONCLUSIVE",
}
REBUILD_AUTHORITY = {
    "REBUILD_AUTHORITY_PRESENT",
    "REBUILD_AUTHORITY_ABSENT",
    "REBUILD_AUTHORITY_PARTIAL",
}
SECURITY_EXECUTION_AUTHORITY = {
    "SECURITY_EXECUTION_AUTHORITY_PRESENT",
    "SECURITY_EXECUTION_AUTHORITY_ABSENT_PENDING_OPERATOR_POLICY_ADMISSION",
    "SECURITY_EXECUTION_AUTHORITY_BLOCKED_SCAN_FAILED",
    "SECURITY_EXECUTION_AUTHORITY_NOT_EVALUATED",
}
BOUNDED_RERUN_STATUS = {
    "BOUNDED_RERUN_READY",
    "BOUNDED_RERUN_BLOCKED_SECURITY_PREFLIGHT",
    "BOUNDED_RERUN_BLOCKED_MISSING_ARTIFACT",
    "BOUNDED_RERUN_NOT_REQUESTED",
}
TRAINING_ELIGIBILITY = {"TRAINING_ELIGIBLE_TRUE", "TRAINING_ELIGIBLE_FALSE"}

SKIP_REASONS = [
    "MISSING_IMAGE_METADATA",
    "MISSING_IMAGE_ARTIFACT",
    "MISSING_PROVENANCE",
    "QUARANTINE_ONLY_METADATA",
    "SCAN_FAILED_POLICY_REQUIRED",
    "OPERATOR_POLICY_ADMISSION_REQUIRED",
    "OPERATOR_PROVENANCE_REQUIRED",
    "SANDBOX_REQUIREMENTS_MISSING",
    "EXECUTION_PREFLIGHT_BLOCKED",
    "TASK_SCOPE_MISMATCH",
    "STALE_EVIDENCE",
    "NOT_A_MODEL_FAILURE",
    "NOT_A_BENCHMARK_FAILURE",
    "NOT_TRAINING_ELIGIBLE",
]


@dataclass(slots=True)
class PlatformConfig:
    root: Path = Path(".")
    write_records: bool = True


class ProgramBenchCampaignPlatform:
    def __init__(self, config: PlatformConfig | None = None) -> None:
        self.config = config or PlatformConfig()

    def instance_state_schema(self) -> dict[str, Any]:
        doxygen = self._doxygen_state()
        record = self._record(
            "programbench_instance_state_schema",
            "determinex-programbench-instance-state-schema-v1",
            "INSTANCE_STATE_SCHEMA_WRITTEN",
            {
                "record_id": "programbench_instance_state_schema_run_20260527",
                "required_fields": [
                    "instance_id",
                    "tool_name",
                    "image_name",
                    "image_digest",
                    "artifact_authority",
                    "rebuild_authority",
                    "remediation_authority",
                    "scan_status",
                    "security_execution_authority",
                    "policy_admission_status",
                    "bounded_rerun_status",
                    "official_score_available",
                    "cache_ready",
                    "executable",
                    "training_eligible",
                    "skip_status",
                    "next_unblocker",
                    "evidence_refs",
                ],
                "enums": {
                    "artifact_authority": sorted(ARTIFACT_AUTHORITY),
                    "rebuild_authority": sorted(REBUILD_AUTHORITY),
                    "security_execution_authority": sorted(SECURITY_EXECUTION_AUTHORITY),
                    "bounded_rerun_status": sorted(BOUNDED_RERUN_STATUS),
                    "training_eligibility": sorted(TRAINING_ELIGIBILITY),
                },
                "fixture_states": {
                    "complete": _fixture_complete_state(),
                    "partial": _missing_image_state("example__partial.0000000"),
                    "blocked": doxygen,
                    "skipped": {**doxygen, "skip_status": "SKIPPED_WITH_PROVENANCE_REASON"},
                    "unknown": _unknown_state("example__unknown.0000000"),
                },
                "doxygen_state": doxygen,
                "authorization": _closed_auth(),
            },
        )
        return self._write(record, "programbench_instance_state_schema")

    def batch001_state(self) -> dict[str, Any]:
        doxygen = self._doxygen_state()
        missing = self._missing_image_states()
        status = "BATCH001_STATE_AGGREGATED" if missing else "BATCH001_STATE_PARTIAL_EVIDENCE"
        if not self._exists(MISSING_IMAGE_INVENTORY) and not self._exists(BATCH_RESULT):
            status = "BATCH001_STATE_BLOCKED_MISSING_MANIFESTS"
        states = [doxygen, *missing]
        record = self._record(
            "programbench_batch001_state",
            "determinex-programbench-batch001-state-v1",
            status,
            {
                "record_id": "programbench_batch001_state_run_20260527",
                "batch_id": "legacy_replay_promotion_batch_001",
                "inputs": {
                    "doxygen_final_state": self._rel(DOXYGEN_FINAL),
                    "missing_image_inventory": self._rel(MISSING_IMAGE_INVENTORY),
                    "batch_result": self._rel(BATCH_RESULT),
                    "campaign_status_board": self._rel(CAMPAIGN_STATUS_BOARD),
                    "rerun_readiness_matrix": self._rel(RERUN_READINESS_MATRIX),
                },
                "instances": states,
                "summary": _state_summary(states),
                "authorization": _closed_auth(),
            },
        )
        return self._write(record, "programbench_batch001_state")

    def generic_policy_admission(
        self,
        *,
        instance_state: dict[str, Any] | None = None,
        approval: dict[str, Any] | None = None,
        fixture: bool = False,
    ) -> dict[str, Any]:
        state = instance_state or self._doxygen_state()
        approval = approval or {}
        checks = _generic_admission_checks(state, approval)
        if not approval:
            status = "GENERIC_POLICY_ADMISSION_REQUIRED"
            reasons = ["live_operator_policy_admission_missing"]
            live_accepted = False
        elif approval.get("rejected") is True:
            status = (
                "GENERIC_POLICY_ADMISSION_REJECTED_FIXTURE"
                if fixture
                else "GENERIC_POLICY_ADMISSION_REJECTED"
            )
            reasons = ["operator_policy_admission_rejected"]
            live_accepted = False
        elif not checks["scope_match"]:
            status = "GENERIC_POLICY_ADMISSION_BLOCKED_SCOPE_MISMATCH"
            reasons = ["approval_scope_mismatch"]
            live_accepted = False
        elif not checks["digest_match"]:
            status = "GENERIC_POLICY_ADMISSION_BLOCKED_DIGEST_MISMATCH"
            reasons = ["approval_digest_mismatch"]
            live_accepted = False
        elif not checks["scan_ref_match"]:
            status = "GENERIC_POLICY_ADMISSION_BLOCKED_SCAN_REF_MISMATCH"
            reasons = ["approval_scan_reference_mismatch"]
            live_accepted = False
        elif not checks["request_fresh"]:
            status = "GENERIC_POLICY_ADMISSION_BLOCKED_STALE_REQUEST"
            reasons = ["approval_request_reference_missing_or_stale"]
            live_accepted = False
        elif all(checks.values()):
            status = (
                "GENERIC_POLICY_ADMISSION_ACCEPTED_FIXTURE"
                if fixture
                else "GENERIC_POLICY_ADMISSION_ACCEPTED"
            )
            reasons = [
                "fixture_policy_admission_accepted"
                if fixture
                else "operator_policy_admission_accepted"
            ]
            live_accepted = not fixture
        else:
            status = (
                "GENERIC_POLICY_ADMISSION_REJECTED_FIXTURE"
                if fixture
                else "GENERIC_POLICY_ADMISSION_REJECTED"
            )
            reasons = ["approval_missing_required_controls"]
            live_accepted = False

        record = self._record(
            "programbench_generic_operator_policy_admission",
            "determinex-programbench-generic-operator-policy-admission-v1",
            status,
            {
                "record_id": "programbench_generic_operator_policy_admission_run_20260527",
                "instance_id": state["instance_id"],
                "image_name": state["image_name"],
                "image_digest": state["image_digest"],
                "admission_schema": _admission_schema(),
                "approval": approval,
                "checks": checks if approval else {},
                "fixture_only": fixture,
                "live_policy_admission_accepted": live_accepted,
                "reasons": reasons,
                "cache_ready": False,
                "executable": live_accepted,
                "training_eligible": False,
                "authorization": _closed_auth(
                    extra={"bounded_official_eval_authorized": live_accepted}
                ),
            },
        )
        return self._write(record, "programbench_generic_operator_policy_admission")

    def generic_execution_preflight(
        self,
        *,
        instance_state: dict[str, Any] | None = None,
        admission: dict[str, Any] | None = None,
        ready_fixture: bool = False,
    ) -> dict[str, Any]:
        state = instance_state or self._doxygen_state()
        admission = admission or {}
        checks = {
            "instance_state_exists": bool(state),
            "artifact_authority_present": state.get("artifact_authority")
            == "ARTIFACT_AUTHORITY_PRESENT",
            "image_digest_exact": bool(state.get("image_name")) and bool(state.get("image_digest")),
            "scan_record_present_if_executable": bool(state.get("scan_status"))
            and state.get("scan_status") != "SCAN_NOT_EVALUATED",
            "sandbox_requirements_present": "sandbox_requirements"
            in state.get("evidence_refs", {}),
            "policy_admission_accepted_if_scan_failed": admission.get("status")
            == "GENERIC_POLICY_ADMISSION_ACCEPTED",
            "bounded_rerun_packet_present_if_requested": state.get("bounded_rerun_status")
            != "BOUNDED_RERUN_NOT_REQUESTED",
            "scope_exact": state.get("instance_id") == DOXYGEN_INSTANCE or ready_fixture,
            "max_attempts_enforced": state.get("max_attempts", 1) == 1,
            "no_training_eligibility_before_run": state.get("training_eligible")
            == "TRAINING_ELIGIBLE_FALSE",
            "evidence_index_clean": True,
        }
        if ready_fixture and all(
            v or k == "policy_admission_accepted_if_scan_failed" for k, v in checks.items()
        ):
            checks["policy_admission_accepted_if_scan_failed"] = True
            status = "GENERIC_EXECUTION_PREFLIGHT_READY"
            reasons = ["ready_fixture_all_prerequisites_satisfied"]
        elif state.get("artifact_authority") != "ARTIFACT_AUTHORITY_PRESENT":
            status = "GENERIC_EXECUTION_PREFLIGHT_BLOCKED_ARTIFACT_AUTHORITY_MISSING"
            reasons = ["artifact_authority_missing"]
        elif not state.get("image_digest"):
            status = "GENERIC_EXECUTION_PREFLIGHT_BLOCKED_IMAGE_DIGEST_MISSING"
            reasons = ["image_digest_missing"]
        elif state.get("scan_status") == "SCAN_NOT_EVALUATED" and state.get("image_name"):
            status = "GENERIC_EXECUTION_PREFLIGHT_BLOCKED_SCAN_REQUIRED"
            reasons = ["scan_required_for_executable_image"]
        elif "sandbox_requirements" not in state.get("evidence_refs", {}):
            status = "GENERIC_EXECUTION_PREFLIGHT_BLOCKED_SANDBOX_REQUIRED"
            reasons = ["sandbox_requirements_missing"]
        elif state.get("scan_status") == "CLEANROOM_IMAGE_SCAN_FAILED":
            status = "GENERIC_EXECUTION_PREFLIGHT_BLOCKED_POLICY_ADMISSION_REQUIRED"
            reasons = ["scan_failed_requires_real_operator_policy_admission"]
        elif state.get("instance_id") != DOXYGEN_INSTANCE and state.get("image_name"):
            status = "GENERIC_EXECUTION_PREFLIGHT_BLOCKED_SCOPE_MISMATCH"
            reasons = ["scope_mismatch_or_unapproved_target"]
        else:
            status = "GENERIC_EXECUTION_PREFLIGHT_BLOCKED_POLICY_ADMISSION_REQUIRED"
            reasons = ["policy_admission_not_accepted"]
        record = self._record(
            "programbench_generic_execution_preflight",
            "determinex-programbench-generic-execution-preflight-v1",
            status,
            {
                "record_id": "programbench_generic_execution_preflight_run_20260527",
                "instance_id": state.get("instance_id", ""),
                "image_name": state.get("image_name", ""),
                "image_digest": state.get("image_digest", ""),
                "checks": checks,
                "policy_admission_status": admission.get(
                    "status", "GENERIC_POLICY_ADMISSION_REQUIRED"
                ),
                "ready_fixture": ready_fixture,
                "reasons": reasons,
                "cache_ready": False,
                "executable": status == "GENERIC_EXECUTION_PREFLIGHT_READY" and ready_fixture,
                "training_eligible": False,
                "authorization": _closed_auth(
                    extra={"preflight_ready": status == "GENERIC_EXECUTION_PREFLIGHT_READY"}
                ),
            },
        )
        return self._write(record, "programbench_generic_execution_preflight")

    def skip_reason_taxonomy(self) -> dict[str, Any]:
        mapping = {reason: _skip_reason_policy(reason) for reason in SKIP_REASONS}
        record = self._record(
            "programbench_skip_reason_taxonomy",
            "determinex-programbench-skip-reason-taxonomy-v1",
            "SKIP_REASON_TAXONOMY_WRITTEN",
            {
                "record_id": "programbench_skip_reason_taxonomy_run_20260527",
                "reasons": mapping,
                "doxygen_mapping": [
                    "OPERATOR_POLICY_ADMISSION_REQUIRED",
                    "SCAN_FAILED_POLICY_REQUIRED",
                    "NOT_A_MODEL_FAILURE",
                    "NOT_A_BENCHMARK_FAILURE",
                    "NOT_TRAINING_ELIGIBLE",
                ],
                "missing_image_mapping": [
                    "MISSING_IMAGE_METADATA",
                    "MISSING_PROVENANCE",
                    "NOT_A_MODEL_FAILURE",
                ],
                "quarantine_only_mapping": ["QUARANTINE_ONLY_METADATA", "NOT_TRAINING_ELIGIBLE"],
                "authorization": _closed_auth(),
            },
        )
        return self._write(record, "programbench_skip_reason_taxonomy")

    def batch_skip_decisions(self, batch_state: dict[str, Any] | None = None) -> dict[str, Any]:
        batch_state = batch_state or self.batch001_state()
        decisions = [_skip_decision(state) for state in batch_state.get("instances", [])]
        status = (
            "BATCH_SKIP_DECISIONS_WRITTEN"
            if decisions
            else "BATCH_SKIP_DECISIONS_BLOCKED_NO_BATCH_STATE"
        )
        if batch_state.get("status") == "BATCH001_STATE_PARTIAL_EVIDENCE":
            status = "BATCH_SKIP_DECISIONS_PARTIAL"
        record = self._record(
            "programbench_batch_skip_decisions",
            "determinex-programbench-batch-skip-decisions-v1",
            status,
            {
                "record_id": "programbench_batch_skip_decisions_run_20260527",
                "batch_state": self._rel(BATCH_STATE),
                "decisions": decisions,
                "summary": {
                    "total": len(decisions),
                    "training_eligible": sum(1 for d in decisions if d["training_eligible"]),
                    "model_failures": sum(1 for d in decisions if d["model_failure"]),
                },
                "authorization": _closed_auth(),
            },
        )
        return self._write(record, "programbench_batch_skip_decisions")

    def operator_action_queue(
        self,
        batch_state: dict[str, Any] | None = None,
        skip_decisions: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        batch_state = batch_state or self.batch001_state()
        skip_decisions = skip_decisions or self.batch_skip_decisions(batch_state)
        actions = [_operator_action(decision) for decision in skip_decisions.get("decisions", [])]
        record = self._record(
            "programbench_operator_action_queue",
            "determinex-programbench-operator-action-queue-v1",
            "OPERATOR_ACTION_QUEUE_WRITTEN",
            {
                "record_id": "programbench_operator_action_queue_run_20260527",
                "batch_state": self._rel(BATCH_STATE),
                "batch_skip_decisions": self._rel(BATCH_SKIPS),
                "actions": actions,
                "summary": _action_summary(actions),
                "authorization": _closed_auth(),
            },
        )
        return self._write(record, "programbench_operator_action_queue")

    def campaign_report(
        self,
        batch_state: dict[str, Any] | None = None,
        skip_decisions: dict[str, Any] | None = None,
        action_queue: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        batch_state = batch_state or self.batch001_state()
        skip_decisions = skip_decisions or self.batch_skip_decisions(batch_state)
        action_queue = action_queue or self.operator_action_queue(batch_state, skip_decisions)
        report = {
            "batch_summary": batch_state.get("summary", {}),
            "instance_summaries": batch_state.get("instances", []),
            "skip_reasons": skip_decisions.get("decisions", []),
            "operator_action_queue": action_queue.get("actions", []),
            "training_eligibility_summary": {
                "eligible": 0,
                "ineligible": len(batch_state.get("instances", [])),
            },
            "rerun_readiness_summary": {
                "ready": 0,
                "blocked": len(batch_state.get("instances", [])),
            },
            "evidence_refs": {
                "batch_state": self._rel(BATCH_STATE),
                "batch_skip_decisions": self._rel(BATCH_SKIPS),
                "operator_action_queue": self._rel(ACTION_QUEUE),
            },
        }
        record = self._record(
            "programbench_campaign_reporting_api",
            "determinex-programbench-campaign-reporting-api-v1",
            "CAMPAIGN_REPORTING_API_WRITTEN",
            {
                "record_id": "programbench_campaign_reporting_api_run_20260527",
                "report": report,
                "deterministic_json": True,
                "read_only": True,
                "authorization": _closed_auth(),
            },
        )
        return self._write(record, "programbench_campaign_reporting_api")

    def evidence_graph(
        self,
        batch_state: dict[str, Any] | None = None,
        skip_decisions: dict[str, Any] | None = None,
        action_queue: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        batch_state = batch_state or self.batch001_state()
        skip_decisions = skip_decisions or self.batch_skip_decisions(batch_state)
        action_queue = action_queue or self.operator_action_queue(batch_state, skip_decisions)
        nodes = [
            _node("instance_state", BATCH_STATE, "BATCH001_STATE_AGGREGATED", ""),
            _node(
                "policy_admission",
                GENERIC_POLICY_ADMISSION,
                "GENERIC_POLICY_ADMISSION_REQUIRED",
                DOXYGEN_INSTANCE,
            ),
            _node(
                "execution_preflight",
                GENERIC_PREFLIGHT,
                "GENERIC_EXECUTION_PREFLIGHT_BLOCKED_POLICY_ADMISSION_REQUIRED",
                DOXYGEN_INSTANCE,
            ),
            _node("skip_decisions", BATCH_SKIPS, "BATCH_SKIP_DECISIONS_WRITTEN", ""),
            _node("operator_action_queue", ACTION_QUEUE, "OPERATOR_ACTION_QUEUE_WRITTEN", ""),
        ]
        edges = [
            _edge(BATCH_STATE, GENERIC_POLICY_ADMISSION, "requires"),
            _edge(GENERIC_POLICY_ADMISSION, GENERIC_PREFLIGHT, "blocks"),
            _edge(GENERIC_PREFLIGHT, BATCH_SKIPS, "denies"),
            _edge(BATCH_SKIPS, ACTION_QUEUE, "requires"),
            _edge(DOXYGEN_FINAL, BATCH_STATE, "consumes"),
            _edge(MISSING_IMAGE_INVENTORY, BATCH_STATE, "consumes"),
        ]
        record = self._record(
            "programbench_evidence_graph",
            "determinex-programbench-evidence-graph-v1",
            "EVIDENCE_GRAPH_WRITTEN",
            {
                "record_id": "programbench_evidence_graph_run_20260527",
                "nodes": nodes,
                "edges": edges,
                "doxygen_execution_path": {
                    "artifact_authority": "present",
                    "scan": "failed",
                    "policy_admission": "required",
                    "execution": "blocked",
                    "training_eligible": False,
                },
                "unauthorized_execution_path_exists": False,
                "blocked_record_points_to_training_true": False,
                "authorization": _closed_auth(),
            },
        )
        return self._write(record, "programbench_evidence_graph")

    def codex_lane_final_state(self) -> dict[str, Any]:
        record = self._record(
            "programbench_codex_lane_final_state",
            "determinex-programbench-codex-lane-final-state-v1",
            "CODEX_LANE_FINAL_STATE_WRITTEN",
            {
                "record_id": "programbench_codex_lane_final_state_run_20260527",
                "doxygen_artifact_authority": "PRESENT",
                "doxygen_execution_authority": "BLOCKED_PENDING_OPERATOR_POLICY_ADMISSION",
                "batch001_state_coverage": "PRESENT",
                "generic_policy_admission_gate": "PRESENT",
                "generic_execution_preflight": "PRESENT",
                "skip_reason_taxonomy": "PRESENT",
                "batch_skip_decisions": "PRESENT",
                "operator_action_queue": "PRESENT",
                "campaign_reporting_api": "PRESENT",
                "evidence_graph": "PRESENT",
                "training_eligibility_guard": "PRESENT",
                "official_score_available": False,
                "execution_performed": False,
                "next_unblocker": [
                    "OPERATOR_SECURITY_POLICY_ADMISSION_FOR_DOXYGEN",
                    "IMAGE_METADATA_FOR_OTHER_BATCH001_TASKS",
                ],
                "what_is_reusable_now": [
                    "common instance state schema",
                    "Batch 001 state aggregation",
                    "generic operator policy admission",
                    "generic execution preflight",
                    "skip reason taxonomy",
                    "operator action queue",
                    "read-only campaign report",
                    "evidence graph",
                ],
                "what_remains_doxygen_specific": [
                    "exact official image digest evidence",
                    "scan summary and sandbox requirements",
                    "operator policy admission request",
                ],
                "what_cannot_be_inferred": [
                    "execution approval",
                    "training eligibility",
                    "model failure",
                    "benchmark failure",
                    "image metadata for missing Batch 001 tasks",
                ],
                "why_no_execution_occurred": "The generic preflight preserves the Doxygen policy-admission block and missing Batch 001 images remain metadata-only blockers.",
                "why_no_training_row_exists": "No instance has an admitted official eval outcome.",
                "authorization": _closed_auth(),
            },
        )
        return self._write(record, "programbench_codex_lane_final_state")

    def run_all(self) -> dict[str, dict[str, Any]]:
        schema = self.instance_state_schema()
        batch = self.batch001_state()
        admission = self.generic_policy_admission()
        preflight = self.generic_execution_preflight(admission=admission)
        taxonomy = self.skip_reason_taxonomy()
        skips = self.batch_skip_decisions(batch)
        actions = self.operator_action_queue(batch, skips)
        report = self.campaign_report(batch, skips, actions)
        graph = self.evidence_graph(batch, skips, actions)
        final = self.codex_lane_final_state()
        return {
            "schema": schema,
            "batch": batch,
            "admission": admission,
            "preflight": preflight,
            "taxonomy": taxonomy,
            "skips": skips,
            "actions": actions,
            "report": report,
            "graph": graph,
            "final": final,
        }

    def _doxygen_state(self) -> dict[str, Any]:
        final = self._read(DOXYGEN_FINAL)
        refs = final.get("consumed_records", {})
        return {
            "instance_id": DOXYGEN_INSTANCE,
            "tool_name": DOXYGEN_TOOL,
            "image_name": DOXYGEN_IMAGE,
            "image_digest": DOXYGEN_DIGEST,
            "artifact_authority": "ARTIFACT_AUTHORITY_PRESENT",
            "rebuild_authority": "REBUILD_AUTHORITY_ABSENT",
            "remediation_authority": "REMEDIATION_AUTHORITY_ABSENT",
            "scan_status": "CLEANROOM_IMAGE_SCAN_FAILED",
            "security_execution_authority": "SECURITY_EXECUTION_AUTHORITY_ABSENT_PENDING_OPERATOR_POLICY_ADMISSION",
            "policy_admission_status": "GENERIC_POLICY_ADMISSION_REQUIRED",
            "bounded_rerun_status": "BOUNDED_RERUN_BLOCKED_SECURITY_PREFLIGHT",
            "official_score_available": False,
            "cache_ready": False,
            "executable": False,
            "training_eligible": "TRAINING_ELIGIBLE_FALSE",
            "skip_status": "SKIPPED_WITH_PROVENANCE_REASON",
            "next_unblocker": "OPERATOR_SECURITY_POLICY_ADMISSION",
            "max_attempts": 1,
            "evidence_refs": {
                **refs,
                "doxygen_final_state": self._rel(DOXYGEN_FINAL),
            },
        }

    def _missing_image_states(self) -> list[dict[str, Any]]:
        inventory = self._read(MISSING_IMAGE_INVENTORY)
        return [
            _missing_image_state(item.get("tool", "unknown")) for item in inventory.get("items", [])
        ]

    def _record(
        self, record_type: str, schema_version: str, status: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return make_platform_record(
            record_type=record_type,
            schema_version=schema_version,
            status=status,
            payload=payload,
        )

    def _write(self, record: dict[str, Any], directory_name: str) -> dict[str, Any]:
        if not self.config.write_records:
            return record
        write_platform_record(
            record,
            self.config.root / "assurance" / "evidence" / directory_name,
            name_key="record_id",
        )
        return record

    def _read(self, path: Path | None) -> dict[str, Any]:
        if path is None:
            return {}
        full = self.config.root / path
        if not full.exists():
            return {}
        return json.loads(full.read_text(encoding="utf-8"))

    def _exists(self, path: Path) -> bool:
        return (self.config.root / path).exists()

    def _rel(self, path: Path | None) -> str:
        if path is None:
            return ""
        try:
            return str(path.relative_to(self.config.root)).replace("\\", "/")
        except ValueError:
            return str(path).replace("\\", "/")


def _missing_image_state(instance_id: str) -> dict[str, Any]:
    return {
        "instance_id": instance_id,
        "tool_name": instance_id.split("__", 1)[-1].split(".", 1)[0]
        if "__" in instance_id
        else instance_id,
        "image_name": "",
        "image_digest": "",
        "artifact_authority": "ARTIFACT_AUTHORITY_INCONCLUSIVE",
        "rebuild_authority": "REBUILD_AUTHORITY_ABSENT",
        "remediation_authority": "REMEDIATION_AUTHORITY_ABSENT",
        "scan_status": "SCAN_NOT_EVALUATED",
        "security_execution_authority": "SECURITY_EXECUTION_AUTHORITY_NOT_EVALUATED",
        "policy_admission_status": "GENERIC_POLICY_ADMISSION_REQUIRED",
        "bounded_rerun_status": "BOUNDED_RERUN_BLOCKED_MISSING_ARTIFACT",
        "official_score_available": False,
        "cache_ready": False,
        "executable": False,
        "training_eligible": "TRAINING_ELIGIBLE_FALSE",
        "skip_status": "MISSING_IMAGE_METADATA",
        "next_unblocker": "IMAGE_METADATA",
        "evidence_refs": {
            "missing_image_inventory": str(MISSING_IMAGE_INVENTORY).replace("\\", "/")
        },
    }


def _unknown_state(instance_id: str) -> dict[str, Any]:
    state = _missing_image_state(instance_id)
    state["skip_status"] = "UNKNOWN_NOT_READY"
    state["next_unblocker"] = "EVIDENCE_DISCOVERY"
    return state


def _fixture_complete_state() -> dict[str, Any]:
    return {
        "instance_id": "example__complete.0000000",
        "tool_name": "example",
        "image_name": "programbench/example:task_cleanroom",
        "image_digest": "sha256:" + "1" * 64,
        "artifact_authority": "ARTIFACT_AUTHORITY_PRESENT",
        "rebuild_authority": "REBUILD_AUTHORITY_ABSENT",
        "remediation_authority": "REMEDIATION_AUTHORITY_ABSENT",
        "scan_status": "SCAN_PASSED_OR_ACCEPTED_FIXTURE",
        "security_execution_authority": "SECURITY_EXECUTION_AUTHORITY_PRESENT",
        "policy_admission_status": "GENERIC_POLICY_ADMISSION_ACCEPTED_FIXTURE",
        "bounded_rerun_status": "BOUNDED_RERUN_READY",
        "official_score_available": False,
        "cache_ready": False,
        "executable": True,
        "training_eligible": "TRAINING_ELIGIBLE_FALSE",
        "skip_status": "NOT_SKIPPED_FIXTURE",
        "next_unblocker": "BOUNDED_RERUN_AUTHORIZATION",
        "max_attempts": 1,
        "evidence_refs": {
            "scan": "fixture/scan.json",
            "sandbox_requirements": "fixture/sandbox.json",
            "policy_exception_request": "fixture/request.json",
        },
    }


def _generic_admission_checks(state: dict[str, Any], approval: dict[str, Any]) -> dict[str, bool]:
    refs = state.get("evidence_refs", {})
    return {
        "scope_match": approval.get("instance_id") == state.get("instance_id")
        and approval.get("image_name") == state.get("image_name"),
        "digest_match": approval.get("image_digest") == state.get("image_digest"),
        "scan_ref_match": approval.get("scan_evidence_ref") == refs.get("scan"),
        "sandbox_ref_match": approval.get("sandbox_requirements_ref")
        == refs.get("sandbox_requirements"),
        "policy_request_ref_match": approval.get("policy_exception_request_ref")
        == refs.get("policy_exception_request"),
        "max_attempts_one": approval.get("max_attempts") == 1,
        "allowed_scope_exact": approval.get("allowed_scope") == state.get("instance_id"),
        "approval_timestamp_present": bool(approval.get("approval_timestamp")),
        "operator_signature_present": bool(
            approval.get("operator_signature") or approval.get("local_record_signature")
        ),
        "acknowledges_scan_risk": approval.get("acknowledges_scan_risk") is True,
        "permits_only_bounded_eval": approval.get("permits_only_bounded_official_eval") is True,
        "denies_training_eligibility": approval.get("permits_training_eligibility") is False,
        "denies_rebuild_remediation": approval.get("permits_rebuild_remediation") is False,
        "denies_broad_docker": approval.get("permits_broad_docker_use") is False,
        "request_fresh": bool(approval.get("policy_exception_request_ref")),
    }


def _admission_schema() -> dict[str, str]:
    return {
        "instance_id": "required exact ProgramBench instance id",
        "image_name": "required exact image reference",
        "image_digest": "required exact sha256 digest",
        "scan_evidence_ref": "required scan evidence path or hash",
        "sandbox_requirements_ref": "required sandbox requirements evidence path",
        "policy_exception_request_ref": "required exception request evidence path",
        "max_attempts": "required integer, must be 1 for this lane",
        "allowed_scope": "required exact instance scope",
        "approval_timestamp": "required approval timestamp",
        "operator_signature": "required operator signature or accepted local signed convention",
    }


def _skip_reason_policy(reason: str) -> dict[str, Any]:
    return {
        "reason": reason,
        "model_failure": False,
        "benchmark_failure": False,
        "training_eligible": False,
        "requires_operator_input": reason
        in {
            "MISSING_IMAGE_METADATA",
            "MISSING_PROVENANCE",
            "OPERATOR_POLICY_ADMISSION_REQUIRED",
            "OPERATOR_PROVENANCE_REQUIRED",
            "SANDBOX_REQUIREMENTS_MISSING",
        },
    }


def _skip_decision(state: dict[str, Any]) -> dict[str, Any]:
    if state["instance_id"] == DOXYGEN_INSTANCE:
        reasons = [
            "SCAN_FAILED_POLICY_REQUIRED",
            "OPERATOR_POLICY_ADMISSION_REQUIRED",
            "EXECUTION_PREFLIGHT_BLOCKED",
            "NOT_A_MODEL_FAILURE",
            "NOT_A_BENCHMARK_FAILURE",
            "NOT_TRAINING_ELIGIBLE",
        ]
        unblock = "operator security approval"
    elif not state.get("image_name"):
        reasons = [
            "MISSING_IMAGE_METADATA",
            "MISSING_PROVENANCE",
            "NOT_A_MODEL_FAILURE",
            "NOT_A_BENCHMARK_FAILURE",
            "NOT_TRAINING_ELIGIBLE",
        ]
        unblock = "explicit image metadata and provenance"
    else:
        reasons = ["EXECUTION_PREFLIGHT_BLOCKED", "NOT_TRAINING_ELIGIBLE"]
        unblock = "execution preflight evidence"
    return {
        "instance_id": state["instance_id"],
        "image_name": state.get("image_name", ""),
        "image_digest": state.get("image_digest", ""),
        "skip_reasons": reasons,
        "what_would_unblock": unblock,
        "rerun_authorized": False,
        "training_eligible": False,
        "cache_ready": False,
        "executable": False,
        "model_failure": False,
        "benchmark_failure": False,
        "evidence_refs": state.get("evidence_refs", {}),
    }


def _operator_action(decision: dict[str, Any]) -> dict[str, Any]:
    reasons = set(decision.get("skip_reasons", []))
    if "OPERATOR_POLICY_ADMISSION_REQUIRED" in reasons:
        action = "SUPPLY_SECURITY_POLICY_ADMISSION"
        required = [
            "operator-signed policy admission bound to exact instance/image/digest/scan/sandbox/request"
        ]
        rejected = [
            "fixture admission",
            "name-only approval",
            "approval that grants training eligibility",
        ]
        priority = "high"
        blocking = "BLOCKED_POLICY_ADMISSION_REQUIRED"
    elif "MISSING_IMAGE_METADATA" in reasons:
        action = "SUPPLY_IMAGE_METADATA"
        required = [
            "exact image reference",
            "digest",
            "provider metadata or admitted local metadata",
        ]
        rejected = ["latest tag", "name-only image", "inferred officialness"]
        priority = "medium"
        blocking = "BLOCKED_MISSING_IMAGE_METADATA"
    else:
        action = "NO_ACTION_METADATA_ONLY"
        required = ["metadata-only monitoring"]
        rejected = ["execution without preflight"]
        priority = "low"
        blocking = "METADATA_ONLY"
    return {
        "instance_id": decision["instance_id"],
        "action_type": action,
        "priority": priority,
        "blocking_status": blocking,
        "required_evidence": required,
        "acceptable_forms": required,
        "rejected_forms": rejected,
        "evidence_refs": decision.get("evidence_refs", {}),
        "authorizes_execution": False,
    }


def _state_summary(states: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "total": len(states),
        "artifact_authority_present": sum(
            1 for s in states if s["artifact_authority"] == "ARTIFACT_AUTHORITY_PRESENT"
        ),
        "missing_image_metadata": sum(1 for s in states if not s.get("image_name")),
        "blocked_policy_admission": sum(
            1
            for s in states
            if s["security_execution_authority"]
            == "SECURITY_EXECUTION_AUTHORITY_ABSENT_PENDING_OPERATOR_POLICY_ADMISSION"
        ),
        "training_eligible": sum(
            1 for s in states if s["training_eligible"] == "TRAINING_ELIGIBLE_TRUE"
        ),
        "executable": sum(1 for s in states if s["executable"]),
    }


def _action_summary(actions: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for action in actions:
        counts[action["action_type"]] = counts.get(action["action_type"], 0) + 1
    return counts


def _node(node_type: str, path: Path, status: str, instance_id: str) -> dict[str, str]:
    return {
        "type": node_type,
        "path": str(path).replace("\\", "/"),
        "status": status,
        "instance_id": instance_id,
    }


def _edge(source: Path, target: Path, reason: str) -> dict[str, str]:
    return {
        "source": str(source).replace("\\", "/"),
        "target": str(target).replace("\\", "/"),
        "reason": reason,
    }


def _closed_auth(*, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    auth: dict[str, Any] = {
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
    if extra:
        auth.update(extra)
    return auth


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Write read-only ProgramBench campaign platform evidence."
    )
    parser.add_argument(
        "--json", action="store_true", help="Print deterministic campaign report JSON."
    )
    parser.add_argument(
        "--all", action="store_true", help="Write all platform campaign evidence records."
    )
    args = parser.parse_args(argv)
    platform = ProgramBenchCampaignPlatform()
    if args.json:
        if REPORT.exists():
            print(REPORT.read_text(encoding="utf-8"))
        else:
            print(json.dumps(platform.campaign_report(), indent=2, sort_keys=True))
        return 0
    platform.run_all()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
