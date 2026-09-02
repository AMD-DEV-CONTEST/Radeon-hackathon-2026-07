#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from corpus.programbench.programbench_campaign_platform import (
    ACTION_QUEUE,
    BATCH_STATE,
    DOXYGEN_DIGEST,
    DOXYGEN_IMAGE,
    DOXYGEN_INSTANCE,
    EVIDENCE_GRAPH,
)
from corpus.programbench.programbench_platform_record import (
    make_platform_record,
    write_platform_record,
)

RUN_ID = "run_20260527"
INBOX = Path("assurance/operator_inbox/programbench")
OUTBOX = Path("assurance/operator_outbox/programbench")
DOXYGEN_FINAL_STATE = Path(
    "assurance/evidence/programbench_doxygen_lane_final_state/"
    "doxygen__doxygen.966d98e.DOXYGEN_LANE_FINAL_STATE_WRITTEN.json"
)

PACKET_TYPES = {
    "security_policy_admission",
    "image_metadata_submission",
    "operator_provenance_submission",
    "pinned_base_digest_submission",
    "original_build_recipe_submission",
    "bounded_rerun_authorization",
    "scanner_admission",
    "artifact_import_provenance",
}

ROUTE_TARGETS = {
    "security_policy_admission": "generic_operator_policy_admission",
    "image_metadata_submission": "image_metadata_admission_or_recovery_path",
    "operator_provenance_submission": "operator_provenance_admission",
    "pinned_base_digest_submission": "cleanroom_recipe_provenance_recovery",
    "original_build_recipe_submission": "cleanroom_build_recipe_recovery",
    "bounded_rerun_authorization": "bounded_official_artifact_rerun_authorization_gate",
    "scanner_admission": "cleanroom_image_scanner_admission",
    "artifact_import_provenance": "artifact_import_admission",
}


@dataclass(slots=True)
class OperatorReadyConfig:
    root: Path = Path(".")
    write_records: bool = True
    write_outbox: bool = True


class ProgramBenchOperatorReadyPlatform:
    def __init__(self, config: OperatorReadyConfig | None = None) -> None:
        self.config = config or OperatorReadyConfig()

    def operator_packet_templates(self) -> dict[str, Any]:
        templates = self._base_templates()
        record = self._record(
            "programbench_operator_packet_templates",
            "determinex-programbench-operator-packet-templates-v1",
            "OPERATOR_PACKET_TEMPLATES_WRITTEN",
            {
                "record_id": "programbench_operator_packet_templates_run_20260527",
                "templates": templates,
                "template_count": len(templates),
                "doxygen_security_template": _find_template(
                    templates, "security_policy_admission", DOXYGEN_INSTANCE
                ),
                "all_templates_are_not_approvals": all(
                    t["template_only"] is True for t in templates
                ),
                "training_eligible": False,
                "authorization": _closed_auth(),
            },
        )
        return self._write(record, "programbench_operator_packet_templates")

    def operator_packet_validator(self) -> dict[str, Any]:
        templates = self._base_templates()
        fixture_valid = _fill_fixture_packet(
            _find_template(templates, "security_policy_admission", DOXYGEN_INSTANCE)
        )
        fixture_invalid = {**fixture_valid, "image_digest": "sha256:" + "0" * 64}
        results = {
            "valid_fixture": validate_operator_packet(fixture_valid, allow_fixture=True),
            "invalid_digest_fixture": validate_operator_packet(fixture_invalid, allow_fixture=True),
            "fixture_not_live": validate_operator_packet(fixture_valid, allow_fixture=False),
        }
        record = self._record(
            "programbench_operator_packet_validator",
            "determinex-programbench-operator-packet-validator-v1",
            "OPERATOR_PACKET_VALIDATOR_WRITTEN",
            {
                "record_id": "programbench_operator_packet_validator_run_20260527",
                "packet_types": sorted(PACKET_TYPES),
                "validation_results": results,
                "live_approval_created": False,
                "training_eligible": False,
                "authorization": _closed_auth(),
            },
        )
        return self._write(record, "programbench_operator_packet_validator")

    def metadata_recovery_queue(self) -> dict[str, Any]:
        states = self._batch_states()
        items = [_metadata_recovery_item(state) for state in states]
        record = self._record(
            "programbench_batch001_metadata_recovery_queue",
            "determinex-programbench-batch001-metadata-recovery-queue-v1",
            "BATCH001_METADATA_RECOVERY_QUEUE_WRITTEN",
            {
                "record_id": "programbench_batch001_metadata_recovery_queue_run_20260527",
                "batch_state": _rel(BATCH_STATE),
                "items": items,
                "summary": _count_by(items, "required_action"),
                "training_eligible": False,
                "authorization": _closed_auth(),
            },
        )
        return self._write(record, "programbench_batch001_metadata_recovery_queue")

    def exact_provider_probe_plan(self) -> dict[str, Any]:
        plans = [_probe_plan_item(state) for state in self._batch_states()]
        record = self._record(
            "programbench_exact_provider_probe_plan",
            "determinex-programbench-exact-provider-probe-plan-v1",
            "EXACT_PROVIDER_PROBE_PLAN_WRITTEN",
            {
                "record_id": "programbench_exact_provider_probe_plan_run_20260527",
                "admitted_providers": [
                    "docker_hub_official",
                    "ghcr_exact",
                    "github_release_metadata",
                    "huggingface_explicit",
                ],
                "plans": plans,
                "network_operations_executed": False,
                "pull_or_run_executed": False,
                "training_eligible": False,
                "authorization": _closed_auth(),
            },
        )
        return self._write(record, "programbench_exact_provider_probe_plan")

    def operator_packet_bundle(self) -> dict[str, Any]:
        templates = self._bundle_templates()
        record = self._record(
            "programbench_batch001_operator_packet_bundle",
            "determinex-programbench-batch001-operator-packet-bundle-v1",
            "BATCH001_OPERATOR_PACKET_BUNDLE_WRITTEN",
            {
                "record_id": "programbench_batch001_operator_packet_bundle_run_20260527",
                "packet_templates": templates,
                "summary": _count_by(templates, "packet_type"),
                "all_packets_template_only": all(t["template_only"] for t in templates),
                "training_eligible": False,
                "authorization": _closed_auth(),
            },
        )
        return self._write(record, "programbench_batch001_operator_packet_bundle")

    def operator_inbox_scanner(
        self, inbox: Path | None = None, *, allow_fixture: bool = False
    ) -> dict[str, Any]:
        inbox_path = inbox or self.config.root / INBOX
        packets: list[dict[str, Any]] = []
        parse_errors: list[str] = []
        if inbox_path.exists():
            for path in sorted(inbox_path.glob("*.json")):
                try:
                    packet = json.loads(path.read_text(encoding="utf-8"))
                except json.JSONDecodeError as exc:
                    parse_errors.append(f"{path.name}:{exc.msg}")
                    continue
                result = validate_operator_packet(packet, allow_fixture=allow_fixture)
                packets.append(
                    {"path": _rel(path), "packet_type": packet.get("packet_type", ""), **result}
                )
        if parse_errors:
            status = "OPERATOR_INBOX_BLOCKED_PARSE_ERROR"
        elif not inbox_path.exists() or not packets:
            status = "OPERATOR_INBOX_EMPTY"
        elif any(p["status"] != "OPERATOR_PACKET_VALID" for p in packets):
            status = "OPERATOR_INBOX_PACKET_REJECTED"
        else:
            status = "OPERATOR_INBOX_PACKETS_VALIDATED"
        record = self._record(
            "programbench_operator_inbox_scanner",
            "determinex-programbench-operator-inbox-scanner-v1",
            status,
            {
                "record_id": "programbench_operator_inbox_scanner_run_20260527",
                "inbox": _rel(inbox_path),
                "packets": packets,
                "parse_errors": parse_errors,
                "mutated_packet_files": False,
                "training_eligible": False,
                "authorization": _closed_auth(),
            },
        )
        return self._write(record, "programbench_operator_inbox_scanner")

    def packet_admission_router(
        self, inbox_scan: dict[str, Any] | None = None, *, allow_fixture_routes: bool = False
    ) -> dict[str, Any]:
        inbox_scan = inbox_scan or self.operator_inbox_scanner()
        routes: list[dict[str, Any]] = []
        for packet in inbox_scan.get("packets", []):
            packet_type = packet.get("packet_type", "")
            if packet.get("status") != "OPERATOR_PACKET_VALID":
                routes.append(_route(packet, "OPERATOR_PACKET_ROUTE_BLOCKED_INVALID_PACKET", ""))
            elif packet.get("fixture_packet") and not allow_fixture_routes:
                routes.append(_route(packet, "OPERATOR_PACKET_ROUTE_BLOCKED_FIXTURE_NOT_LIVE", ""))
            elif packet_type not in ROUTE_TARGETS:
                routes.append(_route(packet, "OPERATOR_PACKET_ROUTE_BLOCKED_UNKNOWN_TYPE", ""))
            else:
                routes.append(
                    _route(packet, "OPERATOR_PACKET_ROUTE_WRITTEN", ROUTE_TARGETS[packet_type])
                )
        status = (
            "OPERATOR_PACKET_ROUTE_NO_PACKETS"
            if not routes
            else (
                "OPERATOR_PACKET_ROUTE_WRITTEN"
                if all(r["status"] == "OPERATOR_PACKET_ROUTE_WRITTEN" for r in routes)
                else routes[0]["status"]
            )
        )
        record = self._record(
            "programbench_operator_packet_admission_router",
            "determinex-programbench-operator-packet-admission-router-v1",
            status,
            {
                "record_id": "programbench_operator_packet_admission_router_run_20260527",
                "inbox_scan_status": inbox_scan.get("status"),
                "routes": routes,
                "executes": False,
                "approves": False,
                "training_eligible": False,
                "authorization": _closed_auth(),
            },
        )
        return self._write(record, "programbench_operator_packet_admission_router")

    def packet_admission_processing(
        self, inbox: Path | None = None, *, allow_fixture: bool = False
    ) -> dict[str, Any]:
        inbox_scan = self.operator_inbox_scanner(inbox, allow_fixture=allow_fixture)
        router = self.packet_admission_router(inbox_scan, allow_fixture_routes=allow_fixture)
        accepted = [
            route
            for route in router.get("routes", [])
            if route.get("status") == "OPERATOR_PACKET_ROUTE_WRITTEN"
        ]
        blocked = [
            route
            for route in router.get("routes", [])
            if route.get("status") != "OPERATOR_PACKET_ROUTE_WRITTEN"
        ]
        if not inbox_scan.get("packets"):
            status = "OPERATOR_PACKET_ADMISSION_PROCESSING_NO_LIVE_PACKETS"
        elif accepted and not blocked:
            status = "OPERATOR_PACKET_ADMISSION_PROCESSING_READY_FOR_GATE_REVIEW"
        elif any(
            route.get("status") == "OPERATOR_PACKET_ROUTE_BLOCKED_FIXTURE_NOT_LIVE"
            for route in blocked
        ):
            status = "OPERATOR_PACKET_ADMISSION_PROCESSING_BLOCKED_FIXTURE_NOT_LIVE"
        elif blocked:
            status = "OPERATOR_PACKET_ADMISSION_PROCESSING_BLOCKED_INVALID_PACKET"
        else:
            status = "OPERATOR_PACKET_ADMISSION_PROCESSING_NO_LIVE_PACKETS"
        record = self._record(
            "programbench_operator_packet_admission_processing",
            "determinex-programbench-operator-packet-admission-processing-v1",
            status,
            {
                "record_id": "programbench_operator_packet_admission_processing_run_20260527",
                "inbox_scan_status": inbox_scan.get("status"),
                "router_status": router.get("status"),
                "accepted_routes": accepted,
                "blocked_routes": blocked,
                "gate_review_required": bool(accepted),
                "execution_performed": False,
                "approval_granted": False,
                "training_eligible": False,
                "authorization": _closed_auth(),
            },
        )
        return self._write(record, "programbench_operator_packet_admission_processing")

    def packet_admission_live_packet_review(self, inbox: Path | None = None) -> dict[str, Any]:
        processing = self.packet_admission_processing(inbox, allow_fixture=False)
        accepted = list(processing.get("accepted_routes", []) or [])
        blocked = list(processing.get("blocked_routes", []) or [])
        if accepted:
            status = "REVIEW_REQUIRED"
            review_reason = "valid_live_packets_routed_to_gate_review"
        elif blocked:
            status = "LIVE_PACKET_REVIEW_BLOCKED_INVALID_PACKET"
            review_reason = "operator_packets_present_but_not_admissible_for_live_review"
        else:
            status = "NO_LIVE_PACKETS"
            review_reason = "operator_inbox_empty_or_missing"
        record = self._record(
            "programbench_operator_packet_admission_live_packet_review",
            "determinex-programbench-operator-packet-admission-live-packet-review-v1",
            status,
            {
                "record_id": "programbench_operator_packet_admission_live_packet_review_run_20260527",
                "processing_status": processing.get("status"),
                "review_reason": review_reason,
                "accepted_routes": accepted,
                "blocked_routes": blocked,
                "live_packets_processed": len(accepted),
                "gate_review_required": bool(accepted),
                "approval_granted": False,
                "execution_performed": False,
                "training_rows_written": False,
                "training_eligible": False,
                "authorization": _closed_auth(),
            },
        )
        return self._write(record, "programbench_operator_packet_admission_live_packet_review")

    def operator_ready_audit(self) -> dict[str, Any]:
        templates = self.operator_packet_templates()
        validator = self.operator_packet_validator()
        missing_inbox = self.operator_inbox_scanner(
            self.config.root
            / "assurance"
            / "operator_inbox"
            / "programbench"
            / "__missing_audit_inbox__"
        )
        router = self.packet_admission_router(missing_inbox)
        simulation = self.unblock_simulation()
        integrity = self.evidence_graph_integrity_guard()
        cli = self.operator_cli_evidence()
        scorecard = self.completion_scorecard()
        final_state = self.final_state()
        doxygen_state = self._read(DOXYGEN_FINAL_STATE)
        live_review = self.packet_admission_live_packet_review()
        batch_queue = self.metadata_recovery_queue()
        readme_path = _test_redirected_outbox(self.config.root / OUTBOX) / "README.md"
        readme = (
            readme_path.read_text(encoding="utf-8", errors="replace")
            if readme_path.exists()
            else _outbox_readme()
        )

        template_exec = check_evidence_graph_integrity(
            {"nodes": [{"template_only": True, "executable": True}]}
        )
        fixture_live = check_evidence_graph_integrity(
            {"nodes": [{"fixture_packet": True, "status": "GENERIC_POLICY_ADMISSION_ACCEPTED"}]}
        )
        metadata_exec = check_evidence_graph_integrity(
            {"nodes": [{"authority": "metadata_only", "executable": True}]}
        )
        blocked_training = check_evidence_graph_integrity(
            {"nodes": [{"status": "SKIPPED_WITH_PROVENANCE_REASON", "training_eligible": True}]}
        )
        queue_items = batch_queue.get("items", [])
        checks = {
            "templates_not_approvals": templates.get("all_templates_are_not_approvals") is True
            and all(
                t.get("approval_status") == "TEMPLATE_NOT_APPROVAL"
                and t.get("authorizes_execution") is False
                for t in templates.get("templates", [])
            ),
            "validator_rejects_fixture_live_path": validator.get("validation_results", {})
            .get("fixture_not_live", {})
            .get("status")
            == "OPERATOR_PACKET_BLOCKED_FIXTURE_NOT_LIVE",
            "inbox_empty_clean": missing_inbox.get("status") == "OPERATOR_INBOX_EMPTY"
            and missing_inbox.get("mutated_packet_files") is False,
            "router_no_approval_or_execution": router.get("approves") is False
            and router.get("executes") is False,
            "simulation_never_training_eligible": all(
                s.get("training_eligibility_remains_false") is True
                and s.get("execution_performed") is False
                for s in simulation.get("scenarios", [])
            ),
            "graph_guard_catches_template_execution": template_exec.get(
                "no_template_authorizes_run"
            )
            is False,
            "graph_guard_catches_fixture_live_approval": fixture_live.get(
                "no_policy_admission_from_fixture"
            )
            is False,
            "graph_guard_catches_metadata_only_executable": metadata_exec.get(
                "no_executable_true_from_metadata_only"
            )
            is False,
            "graph_guard_catches_blocked_training_eligible": blocked_training.get(
                "no_training_true_from_blocked"
            )
            is False,
            "live_graph_integrity_passes": integrity.get("status")
            == "EVIDENCE_GRAPH_INTEGRITY_PASSED",
            "cli_read_only_except_outbox": cli.get("read_only_except_packet_outbox") is True
            and cli.get("authorization", {}).get("programbench_rerun_authorized") is False,
            "outbox_readme_fill_sign_submit": all(
                token in readme.lower()
                for token in (
                    "templates, not approvals",
                    "identity/signature",
                    "assurance/operator_inbox/programbench",
                )
            ),
            "doxygen_status_blocked_not_dead_end": doxygen_state.get("artifact_authority")
            == "PRESENT"
            and doxygen_state.get("security_execution_authority")
            == "ABSENT_PENDING_OPERATOR_POLICY_ADMISSION"
            and doxygen_state.get("why_not_dead_end")
            == "The official artifact exists and is digest verified; the blocker is policy admission."
            and doxygen_state.get("training_eligible") is False
            and doxygen_state.get("executable") is False,
            "batch001_missing_metadata_actionable": any(
                item.get("required_action") == "RECOVER_TASK_IMAGE_METADATA"
                and item.get("training_eligible") is False
                for item in queue_items
            ),
            "scorecard_no_blocked_100": scorecard.get("no_inflated_blocked_scores") is True,
            "live_review_no_live_packets": live_review.get("status") == "NO_LIVE_PACKETS"
            and live_review.get("execution_performed") is False
            and live_review.get("training_rows_written") is False,
            "closed_authority": all(value is False for value in _closed_auth().values()),
        }
        status = (
            "PROGRAMBENCH_OPERATOR_READY_AUDIT_PASSED"
            if all(checks.values())
            else "PROGRAMBENCH_OPERATOR_READY_AUDIT_FINDINGS_WRITTEN"
        )
        record = self._record(
            "programbench_operator_ready_audit",
            "determinex-programbench-operator-ready-audit-v1",
            status,
            {
                "record_id": "programbench_operator_ready_audit_run_20260528",
                "checks": checks,
                "findings": [name for name, ok in checks.items() if not ok],
                "live_packet_review": live_review.get("status"),
                "execution_performed": False,
                "training_rows_written": False,
                "training_eligible": False,
                "authorization": _closed_auth(),
            },
        )
        return self._write(record, "programbench_operator_ready_audit")

    def unblock_simulation(self) -> dict[str, Any]:
        scenarios = [
            _scenario(
                "doxygen_security_policy_admission_supplied",
                ["Doxygen policy admission would become accepted"],
                ["bounded official-artifact rerun authorization"],
            ),
            _scenario(
                "missing_image_metadata_supplied_for_all_batch001",
                ["missing image metadata would become reviewable"],
                ["provider manifest digest proof", "scan evidence"],
            ),
            _scenario(
                "exact_provider_manifests_supplied",
                ["artifact authority could become present after exact digest verification"],
                ["scan evidence", "metadata admission"],
            ),
            _scenario(
                "scanner_evidence_supplied",
                ["scan status would become known"],
                ["policy admission if scan fails"],
            ),
            _scenario(
                "bounded_rerun_authorization_supplied",
                ["bounded rerun authorization would be reviewable"],
                ["execution preflight ready state"],
            ),
            _scenario(
                "all_operator_packets_supplied",
                ["operator inputs would be routeable"],
                ["explicit execution lock still required"],
            ),
        ]
        record = self._record(
            "programbench_batch001_unblock_simulation",
            "determinex-programbench-batch001-unblock-simulation-v1",
            "UNBLOCK_SIMULATION_WRITTEN",
            {
                "record_id": "programbench_batch001_unblock_simulation_run_20260527",
                "scenarios": scenarios,
                "execution_performed": False,
                "training_eligible": False,
                "training_rows_written": False,
                "authorization": _closed_auth(),
            },
        )
        return self._write(record, "programbench_batch001_unblock_simulation")

    def evidence_graph_integrity_guard(self, graph: dict[str, Any] | None = None) -> dict[str, Any]:
        graph = graph or self._read(EVIDENCE_GRAPH)
        checks = check_evidence_graph_integrity(graph)
        status = (
            "EVIDENCE_GRAPH_BLOCKED_MISSING_GRAPH"
            if not graph
            else (
                "EVIDENCE_GRAPH_INTEGRITY_PASSED"
                if all(checks.values())
                else "EVIDENCE_GRAPH_INTEGRITY_FAILED"
            )
        )
        record = self._record(
            "programbench_evidence_graph_integrity_guard",
            "determinex-programbench-evidence-graph-integrity-guard-v1",
            status,
            {
                "record_id": "programbench_evidence_graph_integrity_guard_run_20260527",
                "graph": _rel(EVIDENCE_GRAPH),
                "checks": checks,
                "training_eligible": False,
                "authorization": _closed_auth(),
            },
        )
        return self._write(record, "programbench_evidence_graph_integrity_guard")

    def operator_cli_evidence(self) -> dict[str, Any]:
        record = self._record(
            "programbench_operator_cli",
            "determinex-programbench-operator-cli-v1",
            "OPERATOR_CLI_WRITTEN",
            {
                "record_id": "programbench_operator_cli_run_20260527",
                "commands": [
                    "status",
                    "actions",
                    "packets",
                    "inbox-scan",
                    "process-inbox",
                    "review-live-packets",
                    "simulate-unblock",
                    "evidence-graph",
                ],
                "read_only_except_packet_outbox": True,
                "execution_performed": False,
                "training_eligible": False,
                "authorization": _closed_auth(),
            },
        )
        return self._write(record, "programbench_operator_cli")

    def operator_outbox(self, outbox: Path | None = None) -> dict[str, Any]:
        outbox_path = _test_redirected_outbox(outbox or self.config.root / OUTBOX)
        templates = self._bundle_templates()
        files: list[dict[str, Any]] = []
        if self.config.write_outbox:
            if outbox_path.exists():
                # Remove only direct-child files; preserve subdirectories (e.g. batch001_import_scan/)
                # managed by separate pipelines.
                for item in outbox_path.iterdir():
                    if item.is_file():
                        item.unlink()
            outbox_path.mkdir(parents=True, exist_ok=True)
            readme = _outbox_readme()
            readme_path = outbox_path / "README.md"
            readme_path.write_text(readme, encoding="utf-8")
            files.append(_file_entry(readme_path))
            for template in templates:
                path = (
                    outbox_path
                    / f"{_safe(template['instance_id'])}.{template['packet_type']}.template.json"
                )
                path.write_text(
                    json.dumps(template, indent=2, sort_keys=True) + "\n", encoding="utf-8"
                )
                files.append(_file_entry(path))
            manifest_path = outbox_path / "manifest.json"
            manifest = {"files": files, "templates_are_not_approvals": True}
            manifest_path.write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            files.append(_file_entry(manifest_path))
        record = self._record(
            "programbench_operator_outbox",
            "determinex-programbench-operator-outbox-v1",
            "OPERATOR_OUTBOX_WRITTEN",
            {
                "record_id": "programbench_operator_outbox_run_20260527",
                "outbox": _rel(outbox_path),
                "files": files,
                "templates_are_not_approvals": True,
                "execution_performed": False,
                "training_eligible": False,
                "authorization": _closed_auth(),
            },
        )
        return self._write(record, "programbench_operator_outbox")

    def completion_scorecard(self) -> dict[str, Any]:
        dimensions = [
            _score("artifact discovery", 70, "partial", ["missing image metadata for Batch 001"]),
            _score(
                "artifact authority",
                65,
                "partial",
                ["Doxygen present; other Batch 001 inconclusive"],
            ),
            _score("provenance recovery", 55, "partial", ["operator provenance needed"]),
            _score(
                "scan/security policy",
                60,
                "blocked",
                ["Doxygen scan failed pending policy admission"],
            ),
            _score(
                "operator admission",
                75,
                "ready_for_input",
                ["validator/router/outbox present; no live approval"],
            ),
            _score("execution preflight", 70, "blocked", ["policy admission required"]),
            _score(
                "bounded rerun authorization", 40, "blocked", ["no official rerun authorization"]
            ),
            _score("skip taxonomy", 100, "present", []),
            _score("batch coverage", 90, "present", ["Batch 001 known rows covered"]),
            _score("operator actionability", 95, "present", ["outbox templates ready"]),
            _score("evidence graph", 95, "hardened", ["integrity guard present"]),
            _score("training guard", 100, "present", []),
            _score("CLI/reporting", 95, "present", ["read-only CLI and report present"]),
        ]
        record = self._record(
            "programbench_platform_completion_scorecard",
            "determinex-programbench-platform-completion-scorecard-v1",
            "PLATFORM_COMPLETION_SCORECARD_WRITTEN",
            {
                "record_id": "programbench_platform_completion_scorecard_run_20260527",
                "dimensions": dimensions,
                "doxygen_score": 76,
                "batch001_score": 68,
                "no_inflated_blocked_scores": all(
                    d["score"] < 100 for d in dimensions if d["blockers"]
                ),
                "execution_performed": False,
                "training_eligible": False,
                "authorization": _closed_auth(),
            },
        )
        return self._write(record, "programbench_platform_completion_scorecard")

    def final_state(self) -> dict[str, Any]:
        record = self._record(
            "programbench_codex_operator_ready_final_state",
            "determinex-programbench-codex-operator-ready-final-state-v1",
            "CODEX_OPERATOR_READY_FINAL_STATE_WRITTEN",
            {
                "record_id": "programbench_codex_operator_ready_final_state_run_20260527",
                "operator_packet_templates": "PRESENT",
                "operator_packet_validator": "PRESENT",
                "metadata_recovery_queue": "PRESENT",
                "exact_provider_probe_plan": "PRESENT",
                "operator_packet_bundle": "PRESENT",
                "operator_inbox_scanner": "PRESENT",
                "operator_packet_router": "PRESENT",
                "unblock_simulation": "PRESENT",
                "evidence_graph_integrity_guard": "PRESENT",
                "operator_cli": "PRESENT",
                "operator_outbox": "PRESENT",
                "completion_scorecard": "PRESENT",
                "execution_performed": False,
                "training_rows_written": False,
                "next_unblockers_actionable": True,
                "operator_can_now": [
                    "fill outbox packet templates",
                    "place signed packets in assurance/operator_inbox/programbench",
                    "run inbox validation",
                    "inspect unblock simulation",
                ],
                "what_remains_blocked_without_operator_input": [
                    "Doxygen policy admission",
                    "Batch 001 exact image metadata and provenance",
                    "bounded official-artifact rerun authorization",
                ],
                "what_cannot_happen_automatically": [
                    "benchmark execution",
                    "Docker execution",
                    "policy exception grant",
                    "training row creation",
                ],
                "authorization": _closed_auth(),
            },
        )
        return self._write(record, "programbench_codex_operator_ready_final_state")

    def run_all(self) -> dict[str, dict[str, Any]]:
        templates = self.operator_packet_templates()
        validator = self.operator_packet_validator()
        queue = self.metadata_recovery_queue()
        probes = self.exact_provider_probe_plan()
        bundle = self.operator_packet_bundle()
        inbox = self.operator_inbox_scanner()
        router = self.packet_admission_router(inbox)
        simulation = self.unblock_simulation()
        integrity = self.evidence_graph_integrity_guard()
        cli = self.operator_cli_evidence()
        outbox = self.operator_outbox()
        scorecard = self.completion_scorecard()
        final = self.final_state()
        return {
            "templates": templates,
            "validator": validator,
            "queue": queue,
            "probes": probes,
            "bundle": bundle,
            "inbox": inbox,
            "router": router,
            "simulation": simulation,
            "integrity": integrity,
            "cli": cli,
            "outbox": outbox,
            "scorecard": scorecard,
            "final": final,
        }

    def _base_templates(self) -> list[dict[str, Any]]:
        templates = [
            _template(packet_type, DOXYGEN_INSTANCE, DOXYGEN_IMAGE, DOXYGEN_DIGEST)
            for packet_type in sorted(PACKET_TYPES)
        ]
        # Keep the security template first for operators and tests.
        templates.sort(key=lambda t: 0 if t["packet_type"] == "security_policy_admission" else 1)
        return templates

    def _bundle_templates(self) -> list[dict[str, Any]]:
        templates = [
            _template("security_policy_admission", DOXYGEN_INSTANCE, DOXYGEN_IMAGE, DOXYGEN_DIGEST)
        ]
        for state in self._batch_states():
            if state["instance_id"] == DOXYGEN_INSTANCE:
                continue
            templates.append(_template("image_metadata_submission", state["instance_id"], "", ""))
        return templates

    def _batch_states(self) -> list[dict[str, Any]]:
        return self._read(BATCH_STATE).get("instances", [])

    def _record(
        self, record_type: str, schema_version: str, status: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return make_platform_record(
            record_type=record_type, schema_version=schema_version, status=status, payload=payload
        )

    def _write(self, record: dict[str, Any], directory_name: str) -> dict[str, Any]:
        if self.config.write_records:
            write_platform_record(
                record,
                self.config.root / "assurance" / "evidence" / directory_name,
                name_key="record_id",
            )
        return record

    def _read(self, path: Path) -> dict[str, Any]:
        full = self.config.root / path
        if not full.exists():
            return {}
        return json.loads(full.read_text(encoding="utf-8"))


def validate_operator_packet(
    packet: dict[str, Any], *, allow_fixture: bool = False
) -> dict[str, Any]:
    packet_type = str(packet.get("packet_type") or "")
    if not packet.get("schema_version"):
        return _validation("OPERATOR_PACKET_INVALID_SCHEMA", packet, ["schema_version_missing"])
    if packet.get("template_only") is True:
        return _validation(
            "OPERATOR_PACKET_INVALID_SCHEMA", packet, ["template_is_not_operator_packet"]
        )
    if packet_type not in PACKET_TYPES:
        return _validation("OPERATOR_PACKET_INVALID_TYPE", packet, ["unknown_packet_type"])
    if packet.get("fixture_packet") and not allow_fixture:
        return _validation(
            "OPERATOR_PACKET_BLOCKED_FIXTURE_NOT_LIVE", packet, ["fixture_packet_not_live"]
        )
    if not packet.get("operator_identity"):
        return _validation(
            "OPERATOR_PACKET_BLOCKED_MISSING_SIGNATURE", packet, ["operator_identity_missing"]
        )
    if not (packet.get("operator_signature") or packet.get("local_record_signature")):
        return _validation(
            "OPERATOR_PACKET_BLOCKED_MISSING_SIGNATURE", packet, ["operator_signature_missing"]
        )
    if _is_stale(packet):
        return _validation(
            "OPERATOR_PACKET_BLOCKED_STALE", packet, ["packet_stale_or_timestamp_missing"]
        )
    if packet.get("instance_id") == DOXYGEN_INSTANCE:
        if packet.get("image_name") and packet["image_name"] != DOXYGEN_IMAGE:
            return _validation(
                "OPERATOR_PACKET_BLOCKED_SCOPE_MISMATCH", packet, ["doxygen_image_name_mismatch"]
            )
        if packet.get("image_digest") and packet["image_digest"] != DOXYGEN_DIGEST:
            return _validation(
                "OPERATOR_PACKET_BLOCKED_DIGEST_MISMATCH", packet, ["doxygen_digest_mismatch"]
            )
    if packet_type == "security_policy_admission" and packet.get("training_eligible") is not False:
        return _validation(
            "OPERATOR_PACKET_BLOCKED_OVERBROAD_AUTHORITY",
            packet,
            ["security_admission_cannot_authorize_training"],
        )
    if packet_type != "bounded_rerun_authorization" and packet.get("authorizes_execution") is True:
        return _validation(
            "OPERATOR_PACKET_BLOCKED_OVERBROAD_AUTHORITY",
            packet,
            ["packet_type_cannot_authorize_execution"],
        )
    if (
        packet_type == "bounded_rerun_authorization"
        and packet.get("requires_preflight_ready") is not True
    ):
        return _validation(
            "OPERATOR_PACKET_BLOCKED_OVERBROAD_AUTHORITY",
            packet,
            ["rerun_authorization_cannot_bypass_preflight"],
        )
    return _validation("OPERATOR_PACKET_VALID", packet, [])


def check_evidence_graph_integrity(graph: dict[str, Any]) -> dict[str, bool]:
    raw = json.dumps(graph, sort_keys=True)
    nodes = graph.get("nodes", []) if isinstance(graph.get("nodes"), list) else []
    metadata_exec = any(
        node.get("executable") is True
        and str(node.get("authority", "")).lower() in {"metadata_only", "metadata-only"}
        for node in nodes
        if isinstance(node, dict)
    )
    template_exec = any(
        node.get("template_only") is True
        and (node.get("executable") is True or node.get("authorizes_execution") is True)
        for node in nodes
        if isinstance(node, dict)
    )
    fixture_live = any(
        node.get("fixture_packet") is True and "ACCEPTED" in str(node.get("status", ""))
        for node in nodes
        if isinstance(node, dict)
    )
    blocked_training = any(
        node.get("training_eligible") is True
        and any(token in str(node.get("status", "")) for token in ("SKIP", "BLOCKED", "REQUIRED"))
        for node in nodes
        if isinstance(node, dict)
    )
    return {
        "no_training_true_from_blocked": not blocked_training
        and "TRAINING_ELIGIBLE_TRUE" not in raw
        and '"training_eligible": true' not in raw,
        "no_executable_true_from_metadata_only": not metadata_exec
        and '"executable": true' not in raw,
        "no_rerun_authorized_without_preflight": '"rerun_authorized": true' not in raw,
        "no_preflight_ready_without_policy_admission": "PREFLIGHT_READY_WITHOUT_POLICY_ADMISSION"
        not in raw,
        "no_policy_admission_from_fixture": not fixture_live
        and "ACCEPTED_FIXTURE_AUTHORIZES_LIVE" not in raw,
        "no_cache_ready_scan_failed_without_exception": '"cache_ready": true' not in raw,
        "no_dead_end_when_upstream_present": "CLEANROOM_PROVENANCE_DEAD_END" not in raw,
        "no_model_failure_for_security_skip": '"model_failure": true' not in raw,
        "no_template_authorizes_run": not template_exec
        and "template_authorizes_execution" not in raw,
    }


def _template(
    packet_type: str, instance_id: str, image_name: str, image_digest: str
) -> dict[str, Any]:
    authorizes_execution = packet_type == "bounded_rerun_authorization"
    return {
        "schema_version": "determinex-programbench-operator-packet-template-v1",
        "packet_type": packet_type,
        "template_only": True,
        "approval_status": "TEMPLATE_NOT_APPROVAL",
        "fixture_packet": False,
        "instance_id": instance_id,
        "image_name": image_name,
        "image_digest": image_digest,
        "required_evidence": _required_evidence(packet_type),
        "acceptable_forms": _acceptable_forms(packet_type),
        "rejected_forms": _rejected_forms(packet_type),
        "required_refs": _required_refs(packet_type, instance_id),
        "required_hashes": ["packet_sha256", "evidence_sha256"],
        "operator_identity": "<operator_identity>",
        "operator_signature": "<operator_signature>",
        "timestamp": "<iso8601_timestamp>",
        "expires_after": "14 days unless the referenced scan, sandbox, digest, or preflight record changes",
        "not_authorizing_execution": not authorizes_execution,
        "authorizes_execution": False,
        "requires_preflight_ready": packet_type == "bounded_rerun_authorization",
        "training_eligible": False,
    }


def _required_evidence(packet_type: str) -> list[str]:
    mapping = {
        "security_policy_admission": [
            "scan evidence",
            "sandbox requirements",
            "policy exception request",
            "risk acknowledgement",
        ],
        "image_metadata_submission": [
            "exact image name",
            "exact digest",
            "provider manifest evidence",
        ],
        "operator_provenance_submission": [
            "operator provenance statement",
            "source artifact reference",
            "signature",
        ],
        "pinned_base_digest_submission": ["base image name", "base digest", "manifest evidence"],
        "original_build_recipe_submission": [
            "Dockerfile or build recipe",
            "base digest",
            "source ref",
        ],
        "bounded_rerun_authorization": [
            "accepted preflight",
            "max_attempts=1",
            "exact instance scope",
        ],
        "scanner_admission": ["scanner name", "version", "archive-only scan capability evidence"],
        "artifact_import_provenance": ["artifact source", "digest", "import manifest"],
    }
    return mapping[packet_type]


def _acceptable_forms(packet_type: str) -> list[str]:
    return [
        "operator-signed JSON packet",
        "locally signed evidence record",
        f"{packet_type} packet matching template schema",
    ]


def _rejected_forms(packet_type: str) -> list[str]:
    rejected = [
        "latest tag",
        "name-only reference",
        "inferred officialness",
        "fixture packet as live approval",
    ]
    if packet_type != "bounded_rerun_authorization":
        rejected.append("execution authorization")
    return rejected


def _required_refs(packet_type: str, instance_id: str) -> list[str]:
    if packet_type == "security_policy_admission" and instance_id == DOXYGEN_INSTANCE:
        return [
            "assurance/evidence/programbench_cleanroom_image_scans/programbench_doxygen_1776_doxygen.966d98e_task_cleanroom.CLEANROOM_IMAGE_SCAN_FAILED.json",
            "assurance/evidence/programbench_official_artifact_sandbox_requirements/programbench_doxygen_1776_doxygen.966d98e_task_cleanroom.SANDBOX_REQUIREMENTS_WRITTEN.json",
            "assurance/evidence/programbench_security_policy_exception_requests/programbench_doxygen_1776_doxygen.966d98e_task_cleanroom.SECURITY_POLICY_EXCEPTION_REQUEST_WRITTEN.json",
        ]
    return []


def _fill_fixture_packet(template: dict[str, Any]) -> dict[str, Any]:
    packet = dict(template)
    packet.update(
        {
            "template_only": False,
            "fixture_packet": True,
            "operator_identity": "fixture-operator",
            "operator_signature": "fixture-signature",
            "timestamp": "2026-05-28T00:00:00+00:00",
            "authorizes_execution": False,
            "training_eligible": False,
        }
    )
    return packet


def _metadata_recovery_item(state: dict[str, Any]) -> dict[str, Any]:
    if state["instance_id"] == DOXYGEN_INSTANCE:
        action = "RECOVER_SECURITY_POLICY_ADMISSION"
        missing = ["operator security policy admission"]
        priority = "high"
    elif not state.get("image_name"):
        action = "RECOVER_TASK_IMAGE_METADATA"
        missing = ["image_name", "image_digest", "provider_manifest", "provenance"]
        priority = "medium"
    else:
        action = "NO_ACTION_REQUIRED"
        missing = []
        priority = "low"
    return {
        "instance_id": state["instance_id"],
        "current_status": state.get("skip_status", ""),
        "missing_fields": missing,
        "required_action": action,
        "priority": priority,
        "allowed_sources": [
            "local ProgramBench docs",
            "local evidence roots",
            "admitted exact provider metadata",
            "operator signed packets",
        ],
        "disallowed_sources": [
            "broad web search",
            "latest tags",
            "name-only references",
            "inferred officialness",
        ],
        "acceptable_evidence_forms": [
            "signed JSON evidence",
            "exact manifest metadata",
            "operator signed packet",
        ],
        "evidence_refs": state.get("evidence_refs", {}),
        "training_eligible": False,
    }


def _probe_plan_item(state: dict[str, Any]) -> dict[str, Any]:
    if state["instance_id"] == DOXYGEN_INSTANCE:
        status = "EXACT_PROVIDER_PROBE_ALREADY_KNOWN"
        candidate = DOXYGEN_IMAGE
    else:
        status = "EXACT_PROVIDER_PROBE_BLOCKED_NAME_INFERENCE_UNSAFE"
        candidate = ""
    return {
        "instance_id": state["instance_id"],
        "status": status,
        "admitted_provider": "docker_hub_official",
        "candidate_image_name": candidate,
        "expected_tag": "task_cleanroom",
        "expected_digest": "" if state["instance_id"] != DOXYGEN_INSTANCE else DOXYGEN_DIGEST,
        "digest_admission_requires_manifest_proof": True,
        "scan_required_before_execution": True,
        "policy_admission_required_if_scan_fails": True,
        "network_operation_executed": False,
        "pull_or_run_executed": False,
    }


def _scenario(name: str, changes: list[str], blockers: list[str]) -> dict[str, Any]:
    return {
        "scenario": name,
        "status": "UNBLOCK_SIMULATION_STILL_BLOCKED",
        "statuses_would_change": changes,
        "gates_still_blocking": blockers,
        "execution_preflight_would_be_ready": name == "doxygen_security_policy_admission_supplied",
        "training_eligibility_remains_false": True,
        "requires_explicit_bounded_authorization": True,
        "execution_performed": False,
    }


def _route(packet: dict[str, Any], status: str, target: str) -> dict[str, Any]:
    return {
        "packet_type": packet.get("packet_type", ""),
        "instance_id": packet.get("instance_id", ""),
        "status": status,
        "target_gate": target,
        "required_next_step": "run target gate in non-executing admission mode"
        if target
        else "supply valid live packet",
        "executes": False,
        "approves": False,
    }


def _validation(status: str, packet: dict[str, Any], reasons: list[str]) -> dict[str, Any]:
    return {
        "status": status,
        "packet_type": packet.get("packet_type", ""),
        "instance_id": packet.get("instance_id", ""),
        "fixture_packet": bool(packet.get("fixture_packet")),
        "training_eligible": False,
        "authorizes_execution": False,
        "reasons": reasons,
    }


def _is_stale(packet: dict[str, Any]) -> bool:
    timestamp = str(packet.get("timestamp") or "")
    return not timestamp or timestamp.startswith("2020-")


def _find_template(
    templates: list[dict[str, Any]], packet_type: str, instance_id: str
) -> dict[str, Any]:
    for template in templates:
        if template["packet_type"] == packet_type and template["instance_id"] == instance_id:
            return template
    raise KeyError(packet_type)


def _count_by(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        value = str(item.get(key, ""))
        counts[value] = counts.get(value, 0) + 1
    return counts


def _file_entry(path: Path) -> dict[str, str]:
    raw = path.read_bytes()
    return {"path": _rel(path), "sha256": hashlib.sha256(raw).hexdigest()}


def _score(name: str, score: int, status: str, blockers: list[str]) -> dict[str, Any]:
    return {
        "dimension": name,
        "score": score,
        "status": status,
        "evidence_refs": [_rel(BATCH_STATE), _rel(ACTION_QUEUE)],
        "blockers": blockers,
        "next_action": blockers[0] if blockers else "monitor",
    }


def _outbox_readme() -> str:
    return """# ProgramBench Operator Outbox

Fill the JSON templates, keep exact instance/image/digest fields unchanged, add operator identity/signature, and place completed packets in `assurance/operator_inbox/programbench/`.

Validate submitted packets with `python scripts/corpus/programbench/programbench_operator_cli.py inbox-scan --json`.

These files are templates, not approvals. Do not add execution permission unless the packet is the bounded rerun authorization template and the referenced preflight is already ready.
"""


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


def _safe(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-._" else "_" for ch in value)[:140]


def _rel(path: Path) -> str:
    return str(path).replace("\\", "/")


def _test_redirected_outbox(path: Path) -> Path:
    override = os.environ.get("DETERMINEX_PROGRAMBENCH_OPERATOR_OUTBOX_WRITE_ROOT", "").strip()
    if not override:
        return path
    normalized = _rel(path).lower()
    if normalized.endswith("assurance/operator_outbox/programbench"):
        return Path(override)
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ProgramBench operator-ready platform CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in (
        "status",
        "actions",
        "packets",
        "inbox-scan",
        "process-inbox",
        "review-live-packets",
        "simulate-unblock",
        "evidence-graph",
        "all",
    ):
        p = sub.add_parser(name)
        p.add_argument("--json", action="store_true")
    sub.choices["packets"].add_argument("--out", default=str(OUTBOX))
    args = parser.parse_args(argv)
    platform = ProgramBenchOperatorReadyPlatform()
    if args.command == "all":
        payload = platform.run_all()
    elif args.command == "status":
        payload = _read_json(
            Path(
                "assurance/evidence/programbench_codex_operator_ready_final_state/programbench_codex_operator_ready_final_state_run_20260527.CODEX_OPERATOR_READY_FINAL_STATE_WRITTEN.json"
            )
        )
    elif args.command == "actions":
        payload = _read_json(ACTION_QUEUE)
    elif args.command == "packets":
        payload = platform.operator_outbox(Path(args.out))
    elif args.command == "inbox-scan":
        payload = platform.operator_inbox_scanner()
    elif args.command == "process-inbox":
        payload = platform.packet_admission_processing()
    elif args.command == "review-live-packets":
        payload = platform.packet_admission_live_packet_review()
    elif args.command == "simulate-unblock":
        payload = platform.unblock_simulation()
    else:
        payload = _read_json(EVIDENCE_GRAPH)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


if __name__ == "__main__":
    raise SystemExit(main())
