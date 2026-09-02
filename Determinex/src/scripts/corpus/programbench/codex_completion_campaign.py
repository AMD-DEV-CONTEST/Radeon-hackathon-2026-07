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

from corpus.programbench.codex_completion_campaign_record import (
    make_campaign_record,
    write_campaign_record,
)

INSTANCE_ID = "doxygen__doxygen.966d98e"
IMAGE = "programbench/doxygen_1776_doxygen.966d98e:task_cleanroom"
DIGEST = "sha256:cc50d0f7e9a1f3f90512e3d4c34781f4686a8fa3774fbff489947ef41bde2e72"

ROOT_CAUSE = Path(
    "assurance/evidence/programbench_root_cause_packets/doxygen_real_bounded_rerun_20260527.json"
)
REAL_RERUN = Path(
    "assurance/evidence/programbench_real_bounded_reruns/doxygen_real_bounded_rerun_20260527.REAL_BOUNDED_RERUN_INFRA_FAILURE.json"
)
UPSTREAM_RECHECK = Path(
    "assurance/evidence/programbench_upstream_artifact_authority_recheck/programbench_doxygen_1776_doxygen.966d98e_task_cleanroom.UPSTREAM_ARTIFACT_AUTHORITY_RECHECK_COMPLETED.json"
)
SECURITY_DECISION = Path(
    "assurance/evidence/programbench_official_artifact_security_decisions/programbench_doxygen_1776_doxygen.966d98e_task_cleanroom.OFFICIAL_ARTIFACT_SECURITY_DECISION_WRITTEN.json"
)
SCAN = Path(
    "assurance/evidence/programbench_cleanroom_image_scans/programbench_doxygen_1776_doxygen.966d98e_task_cleanroom.CLEANROOM_IMAGE_SCAN_FAILED.json"
)
TRIAGE = Path(
    "assurance/evidence/programbench_cleanroom_image_scan_triage/programbench_doxygen_1776_doxygen.966d98e_task_cleanroom.CLEANROOM_IMAGE_SCAN_TRIAGED.json"
)
IMPORT = Path(
    "assurance/evidence/programbench_cleanroom_image_import/programbench_doxygen_1776_doxygen.966d98e_task_cleanroom.CLEANROOM_IMAGE_IMPORT_SCAN_UNAVAILABLE.json"
)
HYDRATION = Path(
    "assurance/evidence/programbench_cleanroom_image_hydration/programbench_doxygen_1776_doxygen.966d98e_task_cleanroom.CLEANROOM_IMAGE_SCAN_FAILED.json"
)
REBUILD_DECISION = Path(
    "assurance/evidence/programbench_rebuild_provenance_quarantine_decisions/programbench_doxygen_1776_doxygen.966d98e_task_cleanroom.REBUILD_QUARANTINE_DECISION_PARTIAL_ONLY.json"
)
OPERATOR_REQUEST = Path(
    "assurance/evidence/programbench_operator_provenance_requests/programbench_doxygen_1776_doxygen.966d98e_task_cleanroom.OPERATOR_PROVENANCE_REQUEST_PACKET_WRITTEN.json"
)
ALTERNATE = Path(
    "assurance/evidence/programbench_alternate_cleanroom_image_provenance/programbench_doxygen_1776_doxygen.966d98e_task_cleanroom.ALTERNATE_CLEANROOM_PROVENANCE_NOT_FOUND.json"
)
MANIFEST = Path(
    "assurance/evidence/programbench_dockerhub_manifest_provenance/programbench_doxygen_1776_doxygen.966d98e_task_cleanroom.EXACT_REMOTE_MANIFEST_FOUND.json"
)


@dataclass(slots=True)
class CampaignConfig:
    root: Path = Path(".")


class ProgramBenchCodexCompletionCampaign:
    def __init__(self, config: CampaignConfig | None = None) -> None:
        self.config = config or CampaignConfig()

    def sandbox_requirements(self) -> dict[str, Any]:
        upstream = self._read(UPSTREAM_RECHECK)
        decision = self._read(SECURITY_DECISION)
        scan = self._read(SCAN)
        triage = self._read(TRIAGE)
        status = "SANDBOX_REQUIREMENTS_WRITTEN"
        reasons: list[str] = []
        if upstream.get("upstream_benchmark_artifact_authority") != "PRESENT":
            status = "SANDBOX_REQUIREMENTS_BLOCKED_MISSING_UPSTREAM_AUTHORITY"
            reasons.append("upstream_artifact_authority_not_present")
        elif scan.get("status") != "CLEANROOM_IMAGE_SCAN_FAILED":
            status = "SANDBOX_REQUIREMENTS_BLOCKED_SCAN_RECORD_MISSING"
            reasons.append("scan_failed_record_missing")
        elif upstream.get("instance_id") != INSTANCE_ID or upstream.get("image_digest") != DIGEST:
            status = "SANDBOX_REQUIREMENTS_BLOCKED_SCOPE_MISMATCH"
            reasons.append("doxygen_scope_or_digest_mismatch")
        else:
            reasons.append("official_artifact_authority_present_scan_failed_execution_blocked")

        record = self._record(
            "programbench_official_artifact_sandbox_requirements",
            "determinex-programbench-official-artifact-sandbox-requirements-v1",
            status,
            {
                "instance_id": INSTANCE_ID,
                "image_reference": IMAGE,
                "image_digest": DIGEST,
                "upstream_authority_recheck": self._rel(UPSTREAM_RECHECK),
                "official_artifact_security_decision": self._rel(SECURITY_DECISION),
                "scan_record": self._rel(SCAN),
                "scan_triage_record": self._rel(TRIAGE),
                "official_artifact_authority": upstream.get(
                    "upstream_benchmark_artifact_authority"
                ),
                "rebuild_provenance_authority": upstream.get("rebuild_provenance_authority"),
                "remediation_authority": upstream.get("remediation_authority"),
                "execution_security_policy": decision.get("decision"),
                "scan_summary": _scan_summary(scan),
                "dominant_risk_category": _dominant_risk(triage),
                "sandbox_requirements": _sandbox_requirements(),
                "authorization": _closed_auth(
                    extra={"sandbox_requirements_written": status == "SANDBOX_REQUIREMENTS_WRITTEN"}
                ),
                "cache_ready": False,
                "executable": False,
                "training_eligible": False,
                "reasons": reasons,
            },
        )
        return self._write(record, "programbench_official_artifact_sandbox_requirements")

    def policy_exception_request(self, sandbox_path: Path) -> dict[str, Any]:
        sandbox = self._read(sandbox_path)
        upstream = self._read(UPSTREAM_RECHECK)
        scan = self._read(SCAN)
        triage = self._read(TRIAGE)
        rebuild = self._read(REBUILD_DECISION)
        status = "SECURITY_POLICY_EXCEPTION_REQUEST_WRITTEN"
        reasons: list[str] = []
        if sandbox.get("status") != "SANDBOX_REQUIREMENTS_WRITTEN":
            status = "SECURITY_POLICY_EXCEPTION_REQUEST_BLOCKED_MISSING_SANDBOX_REQUIREMENTS"
            reasons.append("sandbox_requirements_missing_or_blocked")
        elif upstream.get("upstream_benchmark_artifact_authority") != "PRESENT":
            status = "SECURITY_POLICY_EXCEPTION_REQUEST_BLOCKED_NO_UPSTREAM_AUTHORITY"
            reasons.append("upstream_artifact_authority_not_present")
        elif scan.get("status") != "CLEANROOM_IMAGE_SCAN_FAILED":
            status = "SECURITY_POLICY_EXCEPTION_REQUEST_BLOCKED_SCAN_RECORD_MISSING"
            reasons.append("scan_failed_record_missing")
        else:
            reasons.append("operator_policy_exception_required_before_any_execution")

        record = self._record(
            "programbench_security_policy_exception_request",
            "determinex-programbench-security-policy-exception-request-v1",
            status,
            {
                "instance_id": INSTANCE_ID,
                "image_reference": IMAGE,
                "image_digest": DIGEST,
                "official_upstream_artifact_authority_basis": self._rel(UPSTREAM_RECHECK),
                "official_artifact_security_decision": self._rel(SECURITY_DECISION),
                "sandbox_requirements": self._rel(sandbox_path),
                "scan_record": self._rel(SCAN),
                "scan_triage_record": self._rel(TRIAGE),
                "rebuild_quarantine_decision": self._rel(REBUILD_DECISION),
                "operator_provenance_request_packet": self._rel(OPERATOR_REQUEST),
                "scan_summary": _scan_summary(scan),
                "dominant_risk_category": _dominant_risk(triage),
                "rebuild_provenance_authority": upstream.get("rebuild_provenance_authority"),
                "remediation_authority": upstream.get("remediation_authority"),
                "benchmark_fidelity_justification": "Official upstream task_cleanroom image may be required for byte-exact ProgramBench fidelity; rebuilding or remediating without original recipe/base provenance risks changing the benchmark artifact.",
                "human_operator_approval_required": True,
                "allowed_next_step_if_approved": "policy_admission_review",
                "prohibited_by_this_request": [
                    "execution",
                    "hydration",
                    "programbench_rerun",
                    "training_eligibility",
                    "cache_ready",
                    "executable",
                ],
                "authorization": _closed_auth(
                    extra={
                        "exception_request_written": status
                        == "SECURITY_POLICY_EXCEPTION_REQUEST_WRITTEN"
                    }
                ),
                "cache_ready": False,
                "executable": False,
                "training_eligible": False,
                "reasons": reasons,
            },
        )
        return self._write(record, "programbench_security_policy_exception_requests")

    def policy_admission_gate(
        self, request_path: Path, sandbox_path: Path, approval_path: Path | None = None
    ) -> dict[str, Any]:
        request = self._read(request_path)
        sandbox = self._read(sandbox_path)
        approval = self._read(approval_path) if approval_path else {}
        status = "SECURITY_POLICY_ADMISSION_REQUIRED"
        reasons = ["real_operator_policy_approval_missing"]
        accepted = False
        fixture = bool(approval.get("fixture_approval"))
        if request.get("status") != "SECURITY_POLICY_EXCEPTION_REQUEST_WRITTEN":
            status = "SECURITY_POLICY_ADMISSION_BLOCKED_STALE_REQUEST"
            reasons = ["policy_exception_request_missing_or_not_written"]
        elif approval:
            checks = _approval_checks(approval, request, sandbox)
            if all(checks.values()):
                status = (
                    "SECURITY_POLICY_ADMISSION_ACCEPTED_FIXTURE"
                    if fixture
                    else "SECURITY_POLICY_ADMISSION_ACCEPTED"
                )
                reasons = [
                    "fixture_policy_approval_accepted"
                    if fixture
                    else "operator_policy_approval_accepted"
                ]
                accepted = not fixture
            elif approval.get("image_digest") and approval.get("image_digest") != DIGEST:
                status = "SECURITY_POLICY_ADMISSION_BLOCKED_DIGEST_MISMATCH"
                reasons = ["approval_digest_mismatch"]
            elif approval.get("image_reference") and approval.get("image_reference") != IMAGE:
                status = "SECURITY_POLICY_ADMISSION_BLOCKED_SCOPE_MISMATCH"
                reasons = ["approval_scope_mismatch"]
            else:
                status = (
                    "SECURITY_POLICY_ADMISSION_REJECTED_FIXTURE"
                    if fixture
                    else "SECURITY_POLICY_ADMISSION_REJECTED"
                )
                reasons = ["approval_missing_required_acknowledgements"]
        record = self._record(
            "programbench_security_policy_admission_gate",
            "determinex-programbench-security-policy-admission-gate-v1",
            status,
            {
                "instance_id": INSTANCE_ID,
                "image_reference": IMAGE,
                "image_digest": DIGEST,
                "policy_exception_request": self._rel(request_path),
                "sandbox_requirements": self._rel(sandbox_path),
                "approval_record": self._rel(approval_path) if approval_path else "",
                "approval_checks": _approval_checks(approval, request, sandbox) if approval else {},
                "live_policy_admission_accepted": accepted,
                "fixture_only": fixture,
                "authorization": _closed_auth(extra={"policy_admission_accepted": accepted}),
                "cache_ready": False,
                "executable": False,
                "training_eligible": False,
                "reasons": reasons,
            },
        )
        return self._write(record, "programbench_security_policy_admissions")

    def execution_preflight(
        self, sandbox_path: Path, request_path: Path, admission_path: Path
    ) -> dict[str, Any]:
        upstream = self._read(UPSTREAM_RECHECK)
        sandbox = self._read(sandbox_path)
        admission = self._read(admission_path)
        packet = self._read(ROOT_CAUSE)
        imported = self._read(IMPORT)
        evidence_index = self._read(Path("assurance/evidence/evidence_index.json"))
        ready = (
            upstream.get("upstream_benchmark_artifact_authority") == "PRESENT"
            and sandbox.get("status") == "SANDBOX_REQUIREMENTS_WRITTEN"
            and admission.get("status") == "SECURITY_POLICY_ADMISSION_ACCEPTED"
            and packet.get("rerun_scope", {}).get("tool") == INSTANCE_ID
            and packet.get("rerun_scope", {}).get("max_attempts") == 1
            and imported.get("observed_digest") == DIGEST
            and evidence_index.get("validation_errors") == []
        )
        if ready:
            status = "OFFICIAL_ARTIFACT_PREFLIGHT_READY"
            reasons = ["all_execution_prerequisites_satisfied"]
        elif admission.get("status") in {
            "SECURITY_POLICY_ADMISSION_REQUIRED",
            "SECURITY_POLICY_ADMISSION_ACCEPTED_FIXTURE",
        }:
            status = "OFFICIAL_ARTIFACT_PREFLIGHT_BLOCKED_POLICY_ADMISSION_REQUIRED"
            reasons = ["real_policy_admission_required"]
        elif upstream.get("execution_security_policy") == "BLOCKED_SCAN_FAILED":
            status = "OFFICIAL_ARTIFACT_PREFLIGHT_BLOCKED_SCAN_FAILED_NO_EXCEPTION"
            reasons = ["scan_failed_without_real_exception"]
        elif packet.get("rerun_scope", {}).get("tool") != INSTANCE_ID:
            status = "OFFICIAL_ARTIFACT_PREFLIGHT_BLOCKED_SCOPE_MISMATCH"
            reasons = ["root_cause_packet_scope_mismatch"]
        elif imported.get("observed_digest") != DIGEST:
            status = "OFFICIAL_ARTIFACT_PREFLIGHT_BLOCKED_DIGEST_MISMATCH"
            reasons = ["artifact_import_digest_mismatch"]
        else:
            status = "OFFICIAL_ARTIFACT_PREFLIGHT_BLOCKED_POLICY_ADMISSION_REQUIRED"
            reasons = ["policy_admission_not_accepted"]
        record = self._record(
            "programbench_official_artifact_execution_preflight",
            "determinex-programbench-official-artifact-execution-preflight-v1",
            status,
            {
                "instance_id": INSTANCE_ID,
                "image_reference": IMAGE,
                "image_digest": DIGEST,
                "upstream_authority_recheck": self._rel(UPSTREAM_RECHECK),
                "official_artifact_security_decision": self._rel(SECURITY_DECISION),
                "sandbox_requirements": self._rel(sandbox_path),
                "policy_exception_request": self._rel(request_path),
                "policy_admission_gate": self._rel(admission_path),
                "root_cause_packet": self._rel(ROOT_CAUSE),
                "artifact_import": self._rel(IMPORT),
                "checks": {
                    "upstream_artifact_authority_present": upstream.get(
                        "upstream_benchmark_artifact_authority"
                    )
                    == "PRESENT",
                    "target_image_digest_exact": upstream.get("image_digest") == DIGEST,
                    "scan_record_present": self._exists(SCAN),
                    "sandbox_requirements_present": sandbox.get("status")
                    == "SANDBOX_REQUIREMENTS_WRITTEN",
                    "policy_admission_accepted": admission.get("status")
                    == "SECURITY_POLICY_ADMISSION_ACCEPTED",
                    "bounded_rerun_packet_present": self._exists(ROOT_CAUSE),
                    "scope_exact": packet.get("rerun_scope", {}).get("tool") == INSTANCE_ID,
                    "max_attempts_one": packet.get("rerun_scope", {}).get("max_attempts") == 1,
                    "no_richgo_or_other_target": "richgo" not in json.dumps(packet).lower(),
                    "artifact_local_import_present": bool(imported.get("artifact_import_path")),
                    "evidence_index_clean": evidence_index.get("validation_errors") == [],
                    "training_eligible": False,
                },
                "authorization": _closed_auth(extra={"preflight_ready": ready}),
                "cache_ready": False,
                "executable": False,
                "training_eligible": False,
                "reasons": reasons,
            },
        )
        return self._write(record, "programbench_official_artifact_execution_preflight")

    def task_skip(self, preflight_path: Path) -> dict[str, Any]:
        preflight = self._read(preflight_path)
        if not preflight:
            status = "TASK_SKIP_BLOCKED_MISSING_PREFLIGHT"
            reason = "MISSING_PREFLIGHT"
        elif preflight.get("status") == "OFFICIAL_ARTIFACT_PREFLIGHT_READY":
            status = "TASK_SKIP_BLOCKED_PREFLIGHT_READY"
            reason = "PREFLIGHT_READY"
        elif preflight.get("instance_id") != INSTANCE_ID:
            status = "TASK_SKIP_BLOCKED_SCOPE_MISMATCH"
            reason = "SCOPE_MISMATCH"
        else:
            status = "TASK_SKIP_WITH_PROVENANCE_REASON_WRITTEN"
            reason = "POLICY_ADMISSION_REQUIRED_FOR_SCAN_FAILED_OFFICIAL_ARTIFACT"
        record = self._record(
            "programbench_task_skip_with_provenance_reason",
            "determinex-programbench-task-skip-with-provenance-reason-v1",
            status,
            {
                "instance_id": INSTANCE_ID,
                "image_reference": IMAGE,
                "image_digest": DIGEST,
                "official_artifact_preflight": self._rel(preflight_path),
                "skip_reason": reason,
                "why_not_model_failure": "The candidate was not evaluated because security policy blocks the official artifact before ProgramBench execution.",
                "why_not_benchmark_failure": "The benchmark artifact authority is present; the blocker is local security admission, not missing upstream artifact authority.",
                "why_not_training_row": "No official eval outcome was produced under an admitted execution policy.",
                "evidence_that_would_unblock": [
                    "operator security policy admission",
                    "accepted sandbox/policy gate",
                    "fresh preflight ready record",
                ],
                "current_blocker_owner": "operator security approval",
                "rerun_authorized": False,
                "authorization": _closed_auth(),
                "cache_ready": False,
                "executable": False,
                "training_eligible": False,
                "reasons": [reason.lower()],
            },
        )
        return self._write(record, "programbench_task_skips")

    def final_state(
        self,
        sandbox_path: Path,
        request_path: Path,
        admission_path: Path,
        preflight_path: Path,
        skip_path: Path,
    ) -> dict[str, Any]:
        consumed = {
            "root_cause_packet": self._rel(ROOT_CAUSE),
            "real_bounded_rerun": self._rel(REAL_RERUN),
            "manifest_provenance": self._rel(MANIFEST),
            "import": self._rel(IMPORT),
            "scan": self._rel(SCAN),
            "scan_triage": self._rel(TRIAGE),
            "hydration": self._rel(HYDRATION),
            "rebuild_decision": self._rel(REBUILD_DECISION),
            "operator_request": self._rel(OPERATOR_REQUEST),
            "alternate_provenance": self._rel(ALTERNATE),
            "upstream_authority_recheck": self._rel(UPSTREAM_RECHECK),
            "official_security_decision": self._rel(SECURITY_DECISION),
            "sandbox_requirements": self._rel(sandbox_path),
            "policy_exception_request": self._rel(request_path),
            "policy_admission_gate": self._rel(admission_path),
            "execution_preflight": self._rel(preflight_path),
            "task_skip": self._rel(skip_path),
        }
        record = self._record(
            "programbench_doxygen_lane_final_state",
            "determinex-programbench-doxygen-lane-final-state-v1",
            "DOXYGEN_LANE_FINAL_STATE_WRITTEN",
            {
                "instance_id": INSTANCE_ID,
                "image_reference": IMAGE,
                "image_digest": DIGEST,
                "consumed_records": consumed,
                "artifact_authority": "PRESENT",
                "rebuild_authority": "ABSENT",
                "remediation_authority": "ABSENT",
                "security_execution_authority": "ABSENT_PENDING_OPERATOR_POLICY_ADMISSION",
                "bounded_rerun_authority": "BLOCKED_BY_SECURITY_PREFLIGHT",
                "official_score_available": False,
                "training_eligible": False,
                "cache_ready": False,
                "executable": False,
                "next_unblocker": "OPERATOR_SECURITY_POLICY_ADMISSION",
                "what_is_proven": [
                    "official upstream artifact authority is present",
                    "exact image and digest are known",
                    "scan failed with critical/high findings",
                    "execution remains blocked",
                    "Doxygen can be skipped cleanly in active campaign reporting",
                ],
                "what_remains_blocked": [
                    "execution",
                    "ProgramBench rerun",
                    "cache readiness",
                    "training eligibility",
                    "rebuild",
                    "remediation",
                ],
                "what_must_not_be_inferred": [
                    "safe to execute",
                    "training row",
                    "model failure",
                    "benchmark artifact dead end",
                ],
                "why_not_dead_end": "The official artifact exists and is digest verified; the blocker is policy admission.",
                "why_not_executable_yet": "Scan-failed official artifact lacks operator policy admission.",
                "why_not_training_data": "No admitted official eval outcome exists.",
                "clean_skip_allowed": True,
                "authorization": _closed_auth(),
                "reasons": ["policy_admission_required_for_scan_failed_official_artifact"],
            },
        )
        return self._write(record, "programbench_doxygen_lane_final_state", name_key="instance_id")

    def status_board(self, final_state_path: Path, skip_path: Path) -> dict[str, Any]:
        final = self._read(final_state_path)
        row = _doxygen_board_row(final, self._rel(final_state_path), self._rel(skip_path))
        record = self._record(
            "programbench_campaign_status_board",
            "determinex-programbench-campaign-status-board-v1",
            "CAMPAIGN_STATUS_BOARD_WRITTEN",
            {
                "board_id": "programbench_codex_campaign_status_board_20260528",
                "entries": [row],
                "summary": {"total": 1, "blocked": 1, "ready": 0, "training_eligible": 0},
                "authorization": _closed_auth(),
                "cache_ready": False,
                "executable": False,
                "training_eligible": False,
                "reasons": ["doxygen_blocked_policy_admission_required"],
            },
        )
        return self._write(record, "programbench_campaign_status_boards", name_key="board_id")

    def training_negative_guard(
        self, final_state_path: Path, skip_path: Path, board_path: Path
    ) -> dict[str, Any]:
        statuses = [
            "TRAINING_ELIGIBILITY_NEGATIVE_GUARD_WRITTEN",
            "TRAINING_ELIGIBILITY_BLOCKED_METADATA_ONLY",
            "TRAINING_ELIGIBILITY_BLOCKED_SECURITY_POLICY",
            "TRAINING_ELIGIBILITY_BLOCKED_PROVENANCE",
            "TRAINING_ELIGIBILITY_BLOCKED_SKIP_REASON",
        ]
        record = self._record(
            "programbench_training_eligibility_negative_guard",
            "determinex-programbench-training-eligibility-negative-guard-v1",
            "TRAINING_ELIGIBILITY_NEGATIVE_GUARD_WRITTEN",
            {
                "guarded_records": [
                    self._rel(UPSTREAM_RECHECK),
                    self._rel(SECURITY_DECISION),
                    self._rel(final_state_path),
                    self._rel(skip_path),
                    self._rel(board_path),
                ],
                "negative_eligibility_reasons": statuses[1:],
                "rules": {
                    "metadata_only_artifact_is_not_training_eligible": True,
                    "scan_failed_artifact_is_not_training_eligible": True,
                    "policy_admission_required_is_not_training_eligible": True,
                    "partial_provenance_is_not_training_eligible": True,
                    "skipped_task_is_not_negative_model_sample": True,
                    "infra_security_provenance_blockers_are_not_model_failures": True,
                },
                "fixture_successful_official_eval_can_be_eligible_after_separate_gate": True,
                "authorization": _closed_auth(),
                "cache_ready": False,
                "executable": False,
                "training_eligible": False,
                "reasons": ["blocked_doxygen_records_remain_training_ineligible"],
            },
        )
        return self._write(
            record, "programbench_training_eligibility_negative_guards", name_key="record_type"
        )

    def readiness_matrix(
        self, board_path: Path, preflight_path: Path, final_state_path: Path
    ) -> dict[str, Any]:
        preflight = self._read(preflight_path)
        final = self._read(final_state_path)
        record = self._record(
            "programbench_rerun_readiness_matrix",
            "determinex-programbench-rerun-readiness-matrix-v1",
            "RERUN_READINESS_MATRIX_WRITTEN",
            {
                "matrix_id": "programbench_rerun_readiness_matrix_20260528",
                "status_board": self._rel(board_path),
                "entries": [
                    {
                        "instance_id": INSTANCE_ID,
                        "root_cause_packet_ready": self._exists(ROOT_CAUSE),
                        "artifact_authority": final.get("artifact_authority"),
                        "image_present": True,
                        "scan_status": "CLEANROOM_IMAGE_SCAN_FAILED",
                        "security_policy_admitted": False,
                        "bounded_rerun_authorized": False,
                        "execution_preflight_ready": preflight.get("status")
                        == "OFFICIAL_ARTIFACT_PREFLIGHT_READY",
                        "official_score_available": False,
                        "training_eligible": False,
                        "next_action": "operator security policy admission",
                        "status": "BLOCKED_POLICY_ADMISSION_REQUIRED",
                    }
                ],
                "authorization": _closed_auth(),
                "cache_ready": False,
                "executable": False,
                "training_eligible": False,
                "reasons": ["doxygen_blocked_by_policy_admission_not_dead_end"],
            },
        )
        return self._write(record, "programbench_rerun_readiness_matrix", name_key="matrix_id")

    def run_all(self) -> dict[str, Any]:
        sandbox = self.sandbox_requirements()
        request = self.policy_exception_request(Path(sandbox["record_path"]))
        approval = _find_live_approval(self.config.root)
        admission = self.policy_admission_gate(
            Path(request["record_path"]), Path(sandbox["record_path"]), approval
        )
        preflight = self.execution_preflight(
            Path(sandbox["record_path"]),
            Path(request["record_path"]),
            Path(admission["record_path"]),
        )
        skip = self.task_skip(Path(preflight["record_path"]))
        final = self.final_state(
            Path(sandbox["record_path"]),
            Path(request["record_path"]),
            Path(admission["record_path"]),
            Path(preflight["record_path"]),
            Path(skip["record_path"]),
        )
        board = self.status_board(Path(final["record_path"]), Path(skip["record_path"]))
        guard = self.training_negative_guard(
            Path(final["record_path"]), Path(skip["record_path"]), Path(board["record_path"])
        )
        matrix = self.readiness_matrix(
            Path(board["record_path"]), Path(preflight["record_path"]), Path(final["record_path"])
        )
        return {
            "sandbox_requirements": sandbox,
            "policy_exception_request": request,
            "policy_admission_gate": admission,
            "execution_preflight": preflight,
            "task_skip": skip,
            "final_state": final,
            "status_board": board,
            "training_negative_guard": guard,
            "readiness_matrix": matrix,
        }

    def _record(
        self, record_type: str, schema_version: str, status: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return make_campaign_record(
            record_type=record_type, schema_version=schema_version, status=status, payload=payload
        )

    def _write(
        self, record: dict[str, Any], dirname: str, *, name_key: str = "image_reference"
    ) -> dict[str, Any]:
        path = write_campaign_record(
            record, self.config.root / "assurance" / "evidence" / dirname, name_key=name_key
        )
        return {"record_path": str(path), "record": record}

    def _read(self, path: Path | None) -> dict[str, Any]:
        if path is None:
            return {}
        resolved = path if path.is_absolute() else self.config.root / path
        try:
            data = json.loads(resolved.read_text(encoding="utf-8", errors="replace"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _exists(self, path: Path) -> bool:
        return (self.config.root / path).is_file()

    def _rel(self, path: Path | None) -> str:
        if path is None:
            return ""
        resolved = path if path.is_absolute() else self.config.root / path
        try:
            return resolved.resolve().relative_to(self.config.root.resolve()).as_posix()
        except ValueError:
            return resolved.as_posix()


def _scan_summary(scan: dict[str, Any]) -> dict[str, int]:
    summary = scan.get("findings_summary") if isinstance(scan.get("findings_summary"), dict) else {}
    return {
        "critical": int(summary.get("critical") or 0),
        "high": int(summary.get("high") or 0),
        "medium": int(summary.get("medium") or 0),
        "low": int(summary.get("low") or 0),
        "total": int(summary.get("total") or 0),
    }


def _dominant_risk(triage: dict[str, Any]) -> str:
    category = (
        triage.get("category_summary") if isinstance(triage.get("category_summary"), dict) else {}
    )
    return str(category.get("dominant_category") or "language_runtime")


def _sandbox_requirements() -> dict[str, Any]:
    return {
        "network": "none",
        "host_docker_socket_mounted": False,
        "privileged_container": False,
        "broad_host_mounts": False,
        "read_only_artifact_input_mounts_where_possible": True,
        "bounded_temporary_workspace": True,
        "explicit_output_directory_required": True,
        "resource_limits": {
            "cpu_limit": "required_or_document_unavailable",
            "memory_limit": "required_or_document_unavailable",
            "process_timeout_seconds": 3600,
            "disk_output_bound": "required_where_supported",
        },
        "environment_sanitization": True,
        "deterministic_command_capture": True,
        "stdout_capture": True,
        "stderr_capture": True,
        "signed_preflight_record_required": True,
        "signed_post_run_record_required_if_executed": True,
        "max_attempts": 1,
        "instance_scope": INSTANCE_ID,
        "image_digest": DIGEST,
        "training_eligibility_remains_false": True,
    }


def _closed_auth(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    auth: dict[str, Any] = {
        "docker_pull_authorized": False,
        "docker_execution_authorized": False,
        "hydration_authorized": False,
        "programbench_rerun_authorized": False,
        "rebuild_authorized": False,
        "remediation_authorized": False,
        "cache_ready": False,
        "executable": False,
        "training_eligible": False,
    }
    if extra:
        auth.update(extra)
    return auth


def _approval_checks(
    approval: dict[str, Any], request: dict[str, Any], sandbox: dict[str, Any]
) -> dict[str, bool]:
    return {
        "exact_image": approval.get("image_reference") == IMAGE,
        "exact_digest": approval.get("image_digest") == DIGEST,
        "scan_record_or_summary_hash_referenced": bool(
            approval.get("scan_record") or approval.get("scan_summary_hash")
        ),
        "sandbox_requirements_referenced": approval.get("sandbox_requirements")
        == sandbox.get("record_signature")
        or bool(approval.get("sandbox_requirements_record")),
        "operator_signed_or_locally_signed": bool(
            approval.get("operator_signature") or approval.get("record_signature")
        ),
        "scan_risk_acknowledged": approval.get("acknowledges_scan_risk") is True,
        "bounded_official_eval_only": approval.get(
            "permits_only_bounded_official_artifact_evaluation"
        )
        is True,
        "no_training_eligibility": approval.get("permits_training_eligibility") is False,
        "no_rebuild_or_remediation": approval.get("permits_rebuild_remediation") is False,
        "no_broad_docker_use": approval.get("permits_broad_docker_use") is False,
        "no_other_instances": approval.get("permits_other_programbench_instances") is False,
    }


def _find_live_approval(root: Path) -> Path | None:
    approval_dir = root / "assurance" / "evidence" / "programbench_security_policy_approvals"
    if not approval_dir.is_dir():
        return None
    candidates = sorted(p for p in approval_dir.glob("*.json") if p.is_file())
    return candidates[0] if candidates else None


def _doxygen_board_row(final: dict[str, Any], final_path: str, skip_path: str) -> dict[str, Any]:
    return {
        "instance_id": INSTANCE_ID,
        "artifact_authority": final.get("artifact_authority", "PRESENT"),
        "image_reference": IMAGE,
        "image_digest": DIGEST,
        "image_digest_status": "EXACT_DIGEST_VERIFIED",
        "scan_status": "CLEANROOM_IMAGE_SCAN_FAILED",
        "security_policy_status": "BLOCKED_POLICY_ADMISSION_REQUIRED",
        "rerun_status": "SKIPPED_WITH_PROVENANCE_REASON",
        "official_score_status": "OFFICIAL_SCORE_UNAVAILABLE",
        "training_eligibility": False,
        "next_unblocker": "OPERATOR_SECURITY_POLICY_ADMISSION",
        "status": "SKIPPED_WITH_PROVENANCE_REASON",
        "evidence_pointer": final_path,
        "skip_evidence": skip_path,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run non-executing ProgramBench Codex completion campaign rungs."
    )
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument(
        "--all", action="store_true", help="Write all safe non-executing campaign records."
    )
    args = parser.parse_args()
    campaign = ProgramBenchCodexCompletionCampaign(CampaignConfig(root=args.root))
    result = campaign.run_all()
    print(json.dumps({k: v["record_path"] for k, v in result.items()}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
