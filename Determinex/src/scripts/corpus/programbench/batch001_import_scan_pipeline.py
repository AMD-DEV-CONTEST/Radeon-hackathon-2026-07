#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from corpus.programbench.batch001_import_scan_pipeline_record import (
    make_import_scan_pipeline_record,
    write_import_scan_pipeline_record,
)

DIGEST_ADMISSION_RECORD = Path(
    "assurance/evidence/programbench_batch001_metadata_digest_admission/"
    "programbench_batch001_metadata_digest_admission_run_20260528.BATCH001_METADATA_DIGEST_ADMITTED.json"
)
LIVE_LOOKUP_RECORD = Path(
    "assurance/evidence/programbench_batch001_live_manifest_metadata_lookup/"
    "programbench_batch001_live_manifest_metadata_lookup_run_20260528.BATCH001_LIVE_MANIFEST_LOOKUP_COMPLETED.json"
)
LOOKUP_FINAL_RECORD = Path(
    "assurance/evidence/programbench_batch001_lookup_campaign_final_state/"
    "programbench_batch001_lookup_campaign_final_state_run_20260528.BATCH001_LOOKUP_CAMPAIGN_FINAL_STATE_WRITTEN.json"
)
IMPORT_REQUEST_RECORD = Path(
    "assurance/evidence/programbench_batch001_artifact_import_requests/"
    "programbench_batch001_artifact_import_request_packet_run_20260528.ARTIFACT_IMPORT_REQUEST_PACKET_WRITTEN.json"
)
IMPORT_PREFLIGHT_RECORD = Path(
    "assurance/evidence/programbench_batch001_artifact_import_preflight/"
    "programbench_batch001_artifact_import_preflight_run_20260528.ARTIFACT_IMPORT_PREFLIGHT_BLOCKED_NO_SAFE_IMPORT_METHOD.json"
)
OPERATOR_IMPORT_PACKET_RECORD = Path(
    "assurance/evidence/programbench_batch001_operator_artifact_import_packet_bundle/"
    "programbench_batch001_operator_artifact_import_packet_bundle_run_20260528.OPERATOR_ARTIFACT_IMPORT_PACKET_BUNDLE_WRITTEN.json"
)
IMPORT_GATE_RECORD = Path(
    "assurance/evidence/programbench_batch001_exact_artifact_import_gate/"
    "programbench_batch001_exact_artifact_import_gate_run_20260528.EXACT_ARTIFACT_IMPORT_REQUIRED.json"
)
SCAN_QUEUE_RECORD = Path(
    "assurance/evidence/programbench_batch001_scan_queue/"
    "programbench_batch001_scan_queue_run_20260528.BATCH001_SCAN_QUEUE_WRITTEN.json"
)
SCAN_POLICY_RECORD = Path(
    "assurance/evidence/programbench_batch001_scan_policy_precheck/"
    "programbench_batch001_scan_policy_precheck_run_20260528.SCAN_POLICY_PRECHECK_WRITTEN.json"
)
FINAL_STATE_RECORD = Path(
    "assurance/evidence/programbench_batch001_import_scan_campaign_final_state/"
    "programbench_batch001_import_scan_campaign_final_state_run_20260528.BATCH001_IMPORT_SCAN_CAMPAIGN_FINAL_STATE_WRITTEN.json"
)


@dataclass(slots=True)
class Batch001ImportScanConfig:
    root: Path = Path(".")
    write_records: bool = True
    write_outbox: bool = True
    local_safe_import_method: str = ""
    scanner_available: bool = True


class ProgramBenchBatch001ImportScanPipeline:
    def __init__(self, config: Batch001ImportScanConfig | None = None) -> None:
        self.config = config or Batch001ImportScanConfig()

    def artifact_import_request_packet(self) -> dict[str, Any]:
        packets = [_import_request(row) for row in self._admitted_rows()]
        status = (
            "ARTIFACT_IMPORT_REQUEST_PACKET_WRITTEN"
            if all(
                packet["status"] == "ARTIFACT_IMPORT_REQUEST_PACKET_WRITTEN" for packet in packets
            )
            else "ARTIFACT_IMPORT_REQUEST_BLOCKED_NO_DIGEST"
        )
        record = self._record(
            "programbench_batch001_artifact_import_request_packet",
            "determinex-programbench-batch001-artifact-import-request-packet-v1",
            status,
            {
                "record_id": "programbench_batch001_artifact_import_request_packet_run_20260528",
                "input_metadata_digest_admission": _rel(DIGEST_ADMISSION_RECORD),
                "packets": packets,
                "summary": {
                    "import_requests_written": sum(
                        1
                        for p in packets
                        if p["status"] == "ARTIFACT_IMPORT_REQUEST_PACKET_WRITTEN"
                    )
                },
                "import_performed": False,
                "docker_pull_performed": False,
                "docker_run_performed": False,
                "training_eligible": False,
                "authorization": _closed_auth(),
            },
        )
        return self._write(record, "programbench_batch001_artifact_import_requests")

    def artifact_import_preflight(
        self, request_record: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        request_record = request_record or self._read_or_build(
            IMPORT_REQUEST_RECORD, self.artifact_import_request_packet
        )
        rows = [
            _preflight_row(
                packet, self.config.local_safe_import_method, self.config.scanner_available
            )
            for packet in request_record.get("packets", [])
        ]
        if rows and all(row["status"] == "ARTIFACT_IMPORT_PREFLIGHT_READY" for row in rows):
            status = "ARTIFACT_IMPORT_PREFLIGHT_READY"
        elif any(
            row["status"] == "ARTIFACT_IMPORT_PREFLIGHT_BLOCKED_DIGEST_MISSING" for row in rows
        ):
            status = "ARTIFACT_IMPORT_PREFLIGHT_BLOCKED_DIGEST_MISSING"
        elif any(
            row["status"] == "ARTIFACT_IMPORT_PREFLIGHT_BLOCKED_SCAN_UNAVAILABLE" for row in rows
        ):
            status = "ARTIFACT_IMPORT_PREFLIGHT_BLOCKED_SCAN_UNAVAILABLE"
        else:
            status = "ARTIFACT_IMPORT_PREFLIGHT_BLOCKED_NO_SAFE_IMPORT_METHOD"
        record = self._record(
            "programbench_batch001_artifact_import_preflight",
            "determinex-programbench-batch001-artifact-import-preflight-v1",
            status,
            {
                "record_id": "programbench_batch001_artifact_import_preflight_run_20260528",
                "input_import_request": _record_ref(
                    "programbench_batch001_artifact_import_requests",
                    "programbench_batch001_artifact_import_request_packet_run_20260528",
                    request_record.get("status", "ARTIFACT_IMPORT_REQUEST_PACKET_WRITTEN"),
                ),
                "rows": rows,
                "summary": _preflight_summary(rows),
                "import_performed": False,
                "execution_performed": False,
                "training_eligible": False,
                "authorization": _closed_auth(),
            },
        )
        return self._write(record, "programbench_batch001_artifact_import_preflight")

    def operator_artifact_import_packet_bundle(
        self, preflight: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        preflight = preflight or self._read_or_build(
            IMPORT_PREFLIGHT_RECORD, self.artifact_import_preflight
        )
        templates = [
            _operator_import_template(row)
            for row in preflight.get("rows", [])
            if row["status"] != "ARTIFACT_IMPORT_PREFLIGHT_READY"
        ]
        outbox_manifest = (
            self._write_operator_import_outbox(templates)
            if self.config.write_records and self.config.write_outbox
            else {}
        )
        record = self._record(
            "programbench_batch001_operator_artifact_import_packet_bundle",
            "determinex-programbench-batch001-operator-artifact-import-packet-bundle-v1",
            "OPERATOR_ARTIFACT_IMPORT_PACKET_BUNDLE_WRITTEN",
            {
                "record_id": "programbench_batch001_operator_artifact_import_packet_bundle_run_20260528",
                "input_preflight": _record_ref(
                    "programbench_batch001_artifact_import_preflight",
                    "programbench_batch001_artifact_import_preflight_run_20260528",
                    preflight.get(
                        "status", "ARTIFACT_IMPORT_PREFLIGHT_BLOCKED_NO_SAFE_IMPORT_METHOD"
                    ),
                ),
                "templates": templates,
                "outbox_manifest": outbox_manifest,
                "summary": {"operator_import_packets_written": len(templates)},
                "all_templates_not_approvals": all(
                    t["approval_status"] == "TEMPLATE_NOT_APPROVAL" for t in templates
                ),
                "approvals_granted": 0,
                "execution_authorized": False,
                "training_eligible": False,
                "authorization": _closed_auth(),
            },
        )
        return self._write(record, "programbench_batch001_operator_artifact_import_packet_bundle")

    def exact_artifact_import_gate(
        self, live_packets: list[dict[str, Any]] | None = None, *, allow_fixture: bool = False
    ) -> dict[str, Any]:
        expected = {row["instance_id"]: row for row in self._admitted_rows()}
        packets = live_packets or []
        decisions = [
            evaluate_import_packet(
                packet,
                expected.get(str(packet.get("instance_id") or ""), {}),
                allow_fixture=allow_fixture,
            )
            for packet in packets
        ]
        if not decisions:
            status = "EXACT_ARTIFACT_IMPORT_REQUIRED"
        elif all(decision["status"] == "EXACT_ARTIFACT_IMPORT_ACCEPTED" for decision in decisions):
            status = "EXACT_ARTIFACT_IMPORT_ACCEPTED"
        elif any(
            decision["status"] == "EXACT_ARTIFACT_IMPORT_BLOCKED_FIXTURE_NOT_LIVE"
            for decision in decisions
        ):
            status = "EXACT_ARTIFACT_IMPORT_BLOCKED_FIXTURE_NOT_LIVE"
        elif any(
            decision["status"] == "EXACT_ARTIFACT_IMPORT_BLOCKED_DIGEST_MISMATCH"
            for decision in decisions
        ):
            status = "EXACT_ARTIFACT_IMPORT_BLOCKED_DIGEST_MISMATCH"
        elif any(
            decision["status"] == "EXACT_ARTIFACT_IMPORT_BLOCKED_FILE_HASH_MISSING"
            for decision in decisions
        ):
            status = "EXACT_ARTIFACT_IMPORT_BLOCKED_FILE_HASH_MISSING"
        else:
            status = "EXACT_ARTIFACT_IMPORT_REJECTED"
        record = self._record(
            "programbench_batch001_exact_artifact_import_gate",
            "determinex-programbench-batch001-exact-artifact-import-gate-v1",
            status,
            {
                "record_id": "programbench_batch001_exact_artifact_import_gate_run_20260528",
                "input_metadata_digest_admission": _rel(DIGEST_ADMISSION_RECORD),
                "decisions": decisions,
                "live_packets_processed": len(packets),
                "fixture_packets_allowed": allow_fixture,
                "executable": False,
                "cache_ready": False,
                "training_eligible": False,
                "scan_required": True,
                "authorization": _closed_auth(),
            },
        )
        return self._write(record, "programbench_batch001_exact_artifact_import_gate")

    def scan_queue(self, gate: dict[str, Any] | None = None) -> dict[str, Any]:
        gate = gate or self._read_or_build(IMPORT_GATE_RECORD, self.exact_artifact_import_gate)
        accepted = {
            row.get("instance_id")
            for row in gate.get("decisions", [])
            if row.get("status") == "EXACT_ARTIFACT_IMPORT_ACCEPTED"
        }
        items = [
            _scan_queue_item(row, accepted, self.config.scanner_available)
            for row in self._admitted_rows()
        ]
        record = self._record(
            "programbench_batch001_scan_queue",
            "determinex-programbench-batch001-scan-queue-v1",
            "BATCH001_SCAN_QUEUE_WRITTEN",
            {
                "record_id": "programbench_batch001_scan_queue_run_20260528",
                "input_import_gate": _record_ref(
                    "programbench_batch001_exact_artifact_import_gate",
                    "programbench_batch001_exact_artifact_import_gate_run_20260528",
                    gate.get("status", "EXACT_ARTIFACT_IMPORT_REQUIRED"),
                ),
                "items": items,
                "summary": _count_by(items, "status"),
                "scan_performed": False,
                "execution_performed": False,
                "training_eligible": False,
                "authorization": _closed_auth(),
            },
        )
        return self._write(record, "programbench_batch001_scan_queue")

    def scan_policy_precheck(self) -> dict[str, Any]:
        record = self._record(
            "programbench_batch001_scan_policy_precheck",
            "determinex-programbench-batch001-scan-policy-precheck-v1",
            "SCAN_POLICY_PRECHECK_WRITTEN",
            {
                "record_id": "programbench_batch001_scan_policy_precheck_run_20260528",
                "critical_threshold": 0,
                "high_threshold": 0,
                "fail_policy": "any critical or high finding blocks execution pending security decision",
                "warning_policy": "medium and low findings require triage before admission",
                "policy_exception_request_route": "PROGRAMBENCH_SECURITY_POLICY_EXCEPTION_REQUEST_LOCK_001 or Batch001 equivalent",
                "sandbox_requirements_route": "PROGRAMBENCH_OFFICIAL_ARTIFACT_SANDBOX_REQUIREMENTS_LOCK_001 or Batch001 equivalent",
                "operator_admission_route": "generic operator policy admission after scan/security decision",
                "scan_pass_implies_execution": False,
                "scan_fail_routes_to_security_decision": True,
                "automatic_execution_after_scan": False,
                "training_eligible": False,
                "authorization": _closed_auth(),
            },
        )
        return self._write(record, "programbench_batch001_scan_policy_precheck")

    def final_state(
        self,
        requests: dict[str, Any] | None = None,
        preflight: dict[str, Any] | None = None,
        operator_packets: dict[str, Any] | None = None,
        gate: dict[str, Any] | None = None,
        scan_queue: dict[str, Any] | None = None,
        scan_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        requests = requests or self._read_or_build(
            IMPORT_REQUEST_RECORD, self.artifact_import_request_packet
        )
        preflight = preflight or self._read_or_build(
            IMPORT_PREFLIGHT_RECORD, self.artifact_import_preflight
        )
        operator_packets = operator_packets or self._read_or_build(
            OPERATOR_IMPORT_PACKET_RECORD, self.operator_artifact_import_packet_bundle
        )
        gate = gate or self._read_or_build(IMPORT_GATE_RECORD, self.exact_artifact_import_gate)
        scan_queue = scan_queue or self._read_or_build(SCAN_QUEUE_RECORD, self.scan_queue)
        scan_policy = scan_policy or self._read_or_build(
            SCAN_POLICY_RECORD, self.scan_policy_precheck
        )
        summary = {
            "metadata_admitted_targets": len(self._admitted_rows()),
            "import_requests_written": requests.get("summary", {}).get(
                "import_requests_written", 0
            ),
            "import_preflight_ready": preflight.get("summary", {}).get("ready", 0),
            "import_preflight_blocked": preflight.get("summary", {}).get("blocked", 0),
            "operator_import_packets_written": operator_packets.get("summary", {}).get(
                "operator_import_packets_written", 0
            ),
            "artifact_import_gate_ready": gate.get("status")
            in {"EXACT_ARTIFACT_IMPORT_REQUIRED", "EXACT_ARTIFACT_IMPORT_ACCEPTED"},
            "scan_queue_entries": len(scan_queue.get("items", [])),
            "scan_policy_precheck": scan_policy.get("status", ""),
            "artifacts_imported": 0,
            "scans_performed": 0,
            "execution_performed": False,
            "training_rows_written": False,
            "next_unblockers": _next_unblockers(preflight),
        }
        record = self._record(
            "programbench_batch001_import_scan_campaign_final_state",
            "determinex-programbench-batch001-import-scan-campaign-final-state-v1",
            "BATCH001_IMPORT_SCAN_CAMPAIGN_FINAL_STATE_WRITTEN",
            {
                "record_id": "programbench_batch001_import_scan_campaign_final_state_run_20260528",
                "inputs": {
                    "lookup_campaign_final_state": _rel(LOOKUP_FINAL_RECORD),
                    "artifact_import_request_packet": _record_ref(
                        "programbench_batch001_artifact_import_requests",
                        "programbench_batch001_artifact_import_request_packet_run_20260528",
                        requests.get("status", "ARTIFACT_IMPORT_REQUEST_PACKET_WRITTEN"),
                    ),
                    "artifact_import_preflight": _record_ref(
                        "programbench_batch001_artifact_import_preflight",
                        "programbench_batch001_artifact_import_preflight_run_20260528",
                        preflight.get(
                            "status", "ARTIFACT_IMPORT_PREFLIGHT_BLOCKED_NO_SAFE_IMPORT_METHOD"
                        ),
                    ),
                    "operator_artifact_import_packet_bundle": _record_ref(
                        "programbench_batch001_operator_artifact_import_packet_bundle",
                        "programbench_batch001_operator_artifact_import_packet_bundle_run_20260528",
                        operator_packets.get(
                            "status", "OPERATOR_ARTIFACT_IMPORT_PACKET_BUNDLE_WRITTEN"
                        ),
                    ),
                    "exact_artifact_import_gate": _record_ref(
                        "programbench_batch001_exact_artifact_import_gate",
                        "programbench_batch001_exact_artifact_import_gate_run_20260528",
                        gate.get("status", "EXACT_ARTIFACT_IMPORT_REQUIRED"),
                    ),
                    "scan_queue": _record_ref(
                        "programbench_batch001_scan_queue",
                        "programbench_batch001_scan_queue_run_20260528",
                        scan_queue.get("status", "BATCH001_SCAN_QUEUE_WRITTEN"),
                    ),
                    "scan_policy_precheck": _record_ref(
                        "programbench_batch001_scan_policy_precheck",
                        "programbench_batch001_scan_policy_precheck_run_20260528",
                        scan_policy.get("status", "SCAN_POLICY_PRECHECK_WRITTEN"),
                    ),
                },
                "summary": summary,
                "per_target_next_action": _per_target_next_action(scan_queue),
                "next_recommended_codex_rung": "PROGRAMBENCH_BATCH001_OPERATOR_ARTIFACT_IMPORT_PACKET_REVIEW_LOCK_001",
                "authorization": _closed_auth(),
            },
        )
        return self._write(record, "programbench_batch001_import_scan_campaign_final_state")

    def run_all(self) -> dict[str, dict[str, Any]]:
        requests = self.artifact_import_request_packet()
        preflight = self.artifact_import_preflight(requests)
        operator_packets = self.operator_artifact_import_packet_bundle(preflight)
        gate = self.exact_artifact_import_gate()
        queue = self.scan_queue(gate)
        policy = self.scan_policy_precheck()
        final = self.final_state(requests, preflight, operator_packets, gate, queue, policy)
        return {
            "requests": requests,
            "preflight": preflight,
            "operator_packets": operator_packets,
            "gate": gate,
            "scan_queue": queue,
            "scan_policy": policy,
            "final": final,
        }

    def _admitted_rows(self) -> list[dict[str, Any]]:
        return [
            row
            for row in self._read(DIGEST_ADMISSION_RECORD).get("admissions", [])
            if row.get("status") == "BATCH001_METADATA_DIGEST_ADMITTED"
        ]

    def _read_or_build(self, path: Path, builder: Any) -> dict[str, Any]:
        data = self._read(path)
        return data if data else builder()

    def _read(self, path: Path) -> dict[str, Any]:
        full = self.config.root / path
        if not full.exists():
            return {}
        return json.loads(full.read_text(encoding="utf-8"))

    def _record(
        self, record_type: str, schema_version: str, status: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return make_import_scan_pipeline_record(
            record_type=record_type,
            schema_version=schema_version,
            status=status,
            payload=payload,
        )

    def _write(self, record: dict[str, Any], directory_name: str) -> dict[str, Any]:
        if self.config.write_records:
            write_import_scan_pipeline_record(
                record, self.config.root / "assurance" / "evidence" / directory_name
            )
        return record

    def _write_operator_import_outbox(self, templates: list[dict[str, Any]]) -> dict[str, Any]:
        outbox = (
            self.config.root
            / "assurance"
            / "operator_outbox"
            / "programbench"
            / "batch001_import_scan"
        )
        outbox.mkdir(parents=True, exist_ok=True)
        readme = outbox / "README.md"
        readme.write_text(
            "# Batch001 Artifact Import Packet Templates\n\n"
            "These files are templates, not approvals. Fill the artifact path, file sha256, source notes, "
            "operator identity, and operator signature. Place completed packets in "
            "`assurance/operator_inbox/programbench/` for validation.\n\n"
            "Do not add execution permission. Every accepted artifact still requires scan evidence before "
            "any security or rerun decision.\n",
            encoding="utf-8",
        )
        entries = [_file_entry(readme)]
        for template in templates:
            path = (
                outbox
                / f"{_safe(template['instance_id'])}.artifact_import_provenance.template.json"
            )
            path.write_text(json.dumps(template, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            entries.append(_file_entry(path))
        manifest = {
            "schema_version": "determinex-programbench-batch001-artifact-import-outbox-v1",
            "template_count": len(templates),
            "templates_are_not_approvals": True,
            "execution_authorized": False,
            "training_eligible": False,
            "entries": entries,
        }
        manifest_path = outbox / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        entries.append(_file_entry(manifest_path))
        return {"path": _rel(manifest_path), "template_count": len(templates), "entries": entries}


def evaluate_import_packet(
    packet: dict[str, Any], expected: dict[str, Any], *, allow_fixture: bool = False
) -> dict[str, Any]:
    instance_id = str(packet.get("instance_id") or "")
    if packet.get("fixture_packet") and not allow_fixture:
        return _gate_decision(
            "EXACT_ARTIFACT_IMPORT_BLOCKED_FIXTURE_NOT_LIVE",
            instance_id,
            packet,
            ["fixture_packet_not_live"],
        )
    if not expected or instance_id != expected.get("instance_id"):
        return _gate_decision(
            "EXACT_ARTIFACT_IMPORT_BLOCKED_SCOPE_MISMATCH", instance_id, packet, ["scope_mismatch"]
        )
    if packet.get("image_name") != expected.get("image_name"):
        return _gate_decision(
            "EXACT_ARTIFACT_IMPORT_BLOCKED_SCOPE_MISMATCH",
            instance_id,
            packet,
            ["image_name_mismatch"],
        )
    if packet.get("manifest_digest") != expected.get("digest"):
        return _gate_decision(
            "EXACT_ARTIFACT_IMPORT_BLOCKED_DIGEST_MISMATCH",
            instance_id,
            packet,
            ["manifest_digest_mismatch"],
        )
    if not str(packet.get("artifact_file_sha256") or "").startswith("sha256:"):
        return _gate_decision(
            "EXACT_ARTIFACT_IMPORT_BLOCKED_FILE_HASH_MISSING",
            instance_id,
            packet,
            ["artifact_file_sha256_missing"],
        )
    if packet.get("authorizes_execution") is True or packet.get("training_eligible") is True:
        return _gate_decision(
            "EXACT_ARTIFACT_IMPORT_REJECTED", instance_id, packet, ["overbroad_authority"]
        )
    return _gate_decision("EXACT_ARTIFACT_IMPORT_ACCEPTED", instance_id, packet, [])


def fixture_import_packet(
    row: dict[str, Any], *, digest: str | None = None, include_hash: bool = True
) -> dict[str, Any]:
    return {
        "schema_version": "determinex-programbench-operator-artifact-import-v1",
        "packet_type": "artifact_import_provenance",
        "fixture_packet": True,
        "instance_id": row.get("instance_id", ""),
        "image_name": row.get("image_name", ""),
        "manifest_digest": digest or row.get("digest", ""),
        "artifact_path": f"assurance/artifacts/programbench/{_safe(row.get('instance_id', ''))}.task_cleanroom.tar",
        "artifact_file_sha256": "sha256:" + "a" * 64 if include_hash else "",
        "provider": row.get("provider", "docker_hub_official"),
        "authorizes_execution": False,
        "training_eligible": False,
        "operator_identity": "fixture",
        "operator_signature": "fixture",
    }


def _import_request(row: dict[str, Any]) -> dict[str, Any]:
    digest = str(row.get("digest") or "")
    status = (
        "ARTIFACT_IMPORT_REQUEST_PACKET_WRITTEN"
        if digest.startswith("sha256:")
        else "ARTIFACT_IMPORT_REQUEST_BLOCKED_NO_DIGEST"
    )
    instance_id = str(row.get("instance_id") or "")
    return {
        "schema_version": "determinex-programbench-artifact-import-request-v1",
        "packet_type": "artifact_import_request",
        "status": status,
        "template_only": True,
        "approval_status": "REQUEST_NOT_IMPORT",
        "instance_id": instance_id,
        "image_name": row.get("image_name", ""),
        "exact_digest": digest,
        "registry_provider": row.get("provider", "docker_hub_official"),
        "manifest_lookup_evidence_ref": _rel(LIVE_LOOKUP_RECORD),
        "metadata_digest_admission_evidence_ref": _rel(DIGEST_ADMISSION_RECORD),
        "requested_import_mode": {
            "exact_digest_artifact_import_only": True,
            "no_run": True,
            "no_pull_by_tag": True,
            "no_latest": True,
            "no_layer_execution": True,
            "no_programbench": True,
        },
        "expected_quarantine_target_path": f"assurance/artifacts/programbench/{_safe(instance_id)}.task_cleanroom.tar",
        "required_post_import_digest_verification": True,
        "required_scanner_before_execution": True,
        "training_eligible": False,
        "authorizes_execution": False,
    }


def _preflight_row(
    packet: dict[str, Any], local_safe_import_method: str, scanner_available: bool
) -> dict[str, Any]:
    digest = str(packet.get("exact_digest") or "")
    if not digest.startswith("sha256:"):
        status = "ARTIFACT_IMPORT_PREFLIGHT_BLOCKED_DIGEST_MISSING"
        reason = "digest_missing"
    elif not scanner_available:
        status = "ARTIFACT_IMPORT_PREFLIGHT_BLOCKED_SCAN_UNAVAILABLE"
        reason = "scanner_unavailable"
    elif local_safe_import_method in {
        "operator_supplied_tar",
        "exact_digest_registry_quarantine_import",
    }:
        status = "ARTIFACT_IMPORT_PREFLIGHT_READY"
        reason = "safe_import_method_available"
    else:
        status = "ARTIFACT_IMPORT_PREFLIGHT_BLOCKED_NO_SAFE_IMPORT_METHOD"
        reason = "only operator packet or later gated import can supply artifact"
    return {
        "instance_id": packet.get("instance_id", ""),
        "image_name": packet.get("image_name", ""),
        "digest": digest,
        "provider": packet.get("registry_provider", ""),
        "status": status,
        "reason": reason,
        "metadata_only_digest_admission_exists": digest.startswith("sha256:"),
        "import_method_available": bool(local_safe_import_method),
        "import_method": local_safe_import_method or "",
        "method_does_not_run_containers": local_safe_import_method
        in {"operator_supplied_tar", "exact_digest_registry_quarantine_import"},
        "method_uses_tag_only_pull": False,
        "observed_digest_verifiable": local_safe_import_method
        in {"operator_supplied_tar", "exact_digest_registry_quarantine_import"},
        "quarantine_path_available": True,
        "scanner_available": scanner_available,
        "execution_performed": False,
        "training_eligible": False,
    }


def _operator_import_template(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "determinex-programbench-operator-artifact-import-template-v1",
        "packet_type": "artifact_import_provenance",
        "template_only": True,
        "approval_status": "TEMPLATE_NOT_APPROVAL",
        "instance_id": row.get("instance_id", ""),
        "image_name": row.get("image_name", ""),
        "exact_manifest_digest": row.get("digest", ""),
        "local_artifact_tar_path": f"assurance/artifacts/programbench/{_safe(row.get('instance_id', ''))}.task_cleanroom.tar",
        "artifact_file_sha256": "<sha256:...>",
        "source_registry_provenance_notes": "<registry/source notes>",
        "digest_binding_to_manifest_required": True,
        "operator_identity": "<operator_identity>",
        "operator_signature": "<operator_signature>",
        "authorizes_execution": False,
        "scan_required_after_admission": True,
        "training_eligible": False,
    }


def _scan_queue_item(
    row: dict[str, Any], accepted: set[Any], scanner_available: bool
) -> dict[str, Any]:
    imported = row.get("instance_id") in accepted
    if imported and scanner_available:
        status = "SCAN_READY_FOR_IMPORTED_ARTIFACT"
        next_action = "run approved scanner in separate scan lock"
    elif imported:
        status = "SCAN_BLOCKED_NO_SCANNER"
        next_action = "supply approved scanner evidence"
    else:
        status = "SCAN_PENDING_ARTIFACT_IMPORT"
        next_action = "supply exact artifact import provenance"
    return {
        "instance_id": row.get("instance_id", ""),
        "digest": row.get("digest", ""),
        "artifact_import_status": "ACCEPTED" if imported else "REQUIRED",
        "scan_status": "NOT_SCANNED",
        "scanner_required": True,
        "scanner_available": scanner_available,
        "status": status,
        "next_action": next_action,
        "scan_performed": False,
        "execution_performed": False,
        "training_eligible": False,
    }


def _gate_decision(
    status: str, instance_id: str, packet: dict[str, Any], reasons: list[str]
) -> dict[str, Any]:
    return {
        "instance_id": instance_id,
        "status": status,
        "artifact_path": packet.get("artifact_path", ""),
        "artifact_file_sha256": packet.get("artifact_file_sha256", ""),
        "executable": False,
        "cache_ready": False,
        "training_eligible": False,
        "scan_required": True,
        "reasons": reasons,
    }


def _preflight_summary(rows: list[dict[str, Any]]) -> dict[str, int]:
    ready = sum(1 for row in rows if row["status"] == "ARTIFACT_IMPORT_PREFLIGHT_READY")
    return {"ready": ready, "blocked": len(rows) - ready, **_count_by(rows, "status")}


def _next_unblockers(preflight: dict[str, Any]) -> list[str]:
    if preflight.get("status") == "ARTIFACT_IMPORT_PREFLIGHT_READY":
        return ["EXACT_ARTIFACT_IMPORT_GATE_REVIEW", "SCAN_QUEUE"]
    return [
        "OPERATOR_ARTIFACT_IMPORT_PACKET",
        "EXACT_ARTIFACT_IMPORT_GATE_REVIEW",
        "SCAN_QUEUE_AFTER_IMPORT",
    ]


def _per_target_next_action(scan_queue: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for item in scan_queue.get("items", []):
        rows.append(
            {
                "instance_id": item.get("instance_id", ""),
                "digest": item.get("digest", ""),
                "import_status": item.get("artifact_import_status", ""),
                "scan_status": item.get("status", ""),
                "next_unblocker": item.get("next_action", ""),
            }
        )
    return rows


def _count_by(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        value = str(item.get(key, ""))
        counts[value] = counts.get(value, 0) + 1
    return counts


def _file_entry(path: Path) -> dict[str, str]:
    raw = path.read_bytes()
    return {"path": _rel(path), "sha256": "sha256:" + hashlib.sha256(raw).hexdigest()}


def _safe(value: Any) -> str:
    return "".join(ch if ch.isalnum() or ch in "-._" else "_" for ch in str(value))[:140]


def _rel(path: Path) -> str:
    return str(path).replace("\\", "/")


def _record_ref(directory: str, record_id: str, status: str) -> str:
    return f"assurance/evidence/{directory}/{record_id}.{status}.json"


def _closed_auth() -> dict[str, bool]:
    return {
        "docker_execution_authorized": False,
        "programbench_rerun_authorized": False,
        "source_rebuild_authorized": False,
        "remediation_authorized": False,
        "policy_exception_granted": False,
        "training_rows_written": False,
        "training_eligible": False,
        "cache_ready": False,
        "executable": False,
    }


def hash_packet(packet: dict[str, Any]) -> str:
    raw = json.dumps(packet, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Write Batch001 import/scan planning campaign evidence."
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--safe-import-method", default="")
    parser.add_argument("--scanner-unavailable", action="store_true")
    args = parser.parse_args(argv)
    campaign = ProgramBenchBatch001ImportScanPipeline(
        Batch001ImportScanConfig(
            write_records=not args.no_write,
            local_safe_import_method=args.safe_import_method,
            scanner_available=not args.scanner_unavailable,
        )
    )
    records = campaign.run_all()
    if args.json:
        print(json.dumps(records, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
