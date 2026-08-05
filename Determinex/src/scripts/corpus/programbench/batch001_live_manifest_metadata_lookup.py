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

from corpus.programbench.batch001_live_manifest_metadata_record import (
    make_live_manifest_metadata_record,
    write_live_manifest_metadata_record,
)
from corpus.programbench.programbench_campaign_platform import ACTION_QUEUE, DOXYGEN_INSTANCE
from corpus.programbench.safe_registry_manifest_client import (
    SafeRegistryManifestClient,
    client_lock_record,
)

DERIVATION_RECORD = Path(
    "assurance/evidence/programbench_batch001_image_name_derivation/"
    "programbench_batch001_image_name_derivation_run_20260528.IMAGE_NAME_DERIVATION_WRITTEN.json"
)
MANIFEST_PLAN_RECORD = Path(
    "assurance/evidence/programbench_batch001_exact_manifest_metadata_plan/"
    "programbench_batch001_exact_manifest_metadata_plan_run_20260528.EXACT_MANIFEST_METADATA_PLAN_WRITTEN.json"
)
PRIORITY_RECORD = Path(
    "assurance/evidence/programbench_batch001_unblock_priority/"
    "programbench_batch001_unblock_priority_run_20260528.BATCH001_UNBLOCK_PRIORITY_WRITTEN.json"
)
LIVE_LOOKUP_RECORD = Path(
    "assurance/evidence/programbench_batch001_live_manifest_metadata_lookup/"
    "programbench_batch001_live_manifest_metadata_lookup_run_20260528.BATCH001_LIVE_MANIFEST_LOOKUP_COMPLETED.json"
)
DIGEST_ADMISSION_RECORD = Path(
    "assurance/evidence/programbench_batch001_metadata_digest_admission/"
    "programbench_batch001_metadata_digest_admission_run_20260528.BATCH001_METADATA_DIGEST_ADMITTED.json"
)
POST_LOOKUP_STATE_RECORD = Path(
    "assurance/evidence/programbench_batch001_post_lookup_state_refresh/"
    "programbench_batch001_post_lookup_state_refresh_run_20260528.BATCH001_POST_LOOKUP_STATE_REFRESH_WRITTEN.json"
)
IMPORT_SCAN_PLAN_RECORD = Path(
    "assurance/evidence/programbench_batch001_import_scan_planning/"
    "programbench_batch001_import_scan_planning_run_20260528.BATCH001_IMPORT_SCAN_PLAN_WRITTEN.json"
)
OPERATOR_PACKET_REFRESH_RECORD = Path(
    "assurance/evidence/programbench_batch001_operator_packet_refresh_after_lookup/"
    "programbench_batch001_operator_packet_refresh_after_lookup_run_20260528.BATCH001_OPERATOR_PACKET_REFRESH_AFTER_LOOKUP_WRITTEN.json"
)
FINAL_STATE_RECORD = Path(
    "assurance/evidence/programbench_batch001_lookup_campaign_final_state/"
    "programbench_batch001_lookup_campaign_final_state_run_20260528.BATCH001_LOOKUP_CAMPAIGN_FINAL_STATE_WRITTEN.json"
)
OPERATOR_METADATA_REQUEST_RECORD = Path(
    "assurance/evidence/programbench_batch001_operator_image_metadata_request_packet/"
    "programbench_batch001_operator_image_metadata_request_packet_run_20260528.OPERATOR_IMAGE_METADATA_REQUEST_PACKETS_WRITTEN.json"
)


@dataclass(slots=True)
class Batch001LiveManifestLookupConfig:
    root: Path = Path(".")
    write_records: bool = True
    live_lookup: bool = True
    client: SafeRegistryManifestClient | None = None


class ProgramBenchBatch001LiveManifestLookupCampaign:
    def __init__(self, config: Batch001LiveManifestLookupConfig | None = None) -> None:
        self.config = config or Batch001LiveManifestLookupConfig()

    def safe_registry_manifest_client(self) -> dict[str, Any]:
        return self._write(client_lock_record(), "programbench_safe_registry_manifest_client")

    def live_manifest_metadata_lookup(self) -> dict[str, Any]:
        plans = self._read(MANIFEST_PLAN_RECORD).get("plans", [])
        client = self.config.client or SafeRegistryManifestClient()
        results: list[dict[str, Any]] = []
        for plan in plans:
            if plan.get("provider") != "docker_hub_official":
                result = _lookup_blocked(
                    plan,
                    "REGISTRY_MANIFEST_LOOKUP_BLOCKED_UNADMITTED_PROVIDER",
                    "provider_not_admitted",
                )
            elif not self.config.live_lookup:
                result = _lookup_blocked(
                    plan,
                    "REGISTRY_MANIFEST_LOOKUP_BLOCKED_NETWORK_DISABLED",
                    "live_lookup_disabled",
                )
            else:
                result = client.lookup(str(plan.get("image_name") or ""))
            results.append(_target_lookup_row(plan, result))
        status = _lookup_status(results)
        record = self._record(
            "programbench_batch001_live_manifest_metadata_lookup",
            "determinex-programbench-batch001-live-manifest-metadata-lookup-v1",
            status,
            {
                "record_id": "programbench_batch001_live_manifest_metadata_lookup_run_20260528",
                "inputs": {
                    "image_name_derivation": _rel(DERIVATION_RECORD),
                    "exact_manifest_metadata_plan": _rel(MANIFEST_PLAN_RECORD),
                    "safe_registry_manifest_client": "assurance/evidence/programbench_safe_registry_manifest_client/programbench_safe_registry_manifest_client_run_20260528.SAFE_REGISTRY_MANIFEST_CLIENT_WRITTEN.json",
                },
                "results": results,
                "summary": _lookup_summary(results),
                "metadata_only": True,
                "docker_pull_performed": False,
                "layer_downloaded": False,
                "image_imported": False,
                "docker_run_performed": False,
                "programbench_rerun_performed": False,
                "cache_ready": False,
                "executable": False,
                "training_eligible": False,
                "authorization": _closed_auth(),
            },
        )
        return self._write(record, "programbench_batch001_live_manifest_metadata_lookup")

    def metadata_digest_admission(self, lookup: dict[str, Any] | None = None) -> dict[str, Any]:
        lookup = lookup or self._read_or_build(
            LIVE_LOOKUP_RECORD, self.live_manifest_metadata_lookup
        )
        lookup_ref = _record_ref(
            "programbench_batch001_live_manifest_metadata_lookup",
            "programbench_batch001_live_manifest_metadata_lookup_run_20260528",
            lookup.get("status", "BATCH001_LIVE_MANIFEST_LOOKUP_COMPLETED"),
        )
        admissions = [_admission(row, lookup_ref) for row in lookup.get("results", [])]
        admitted = [
            row for row in admissions if row["status"] == "BATCH001_METADATA_DIGEST_ADMITTED"
        ]
        if admitted and len(admitted) == len(admissions):
            status = "BATCH001_METADATA_DIGEST_ADMITTED"
        elif admitted:
            status = "BATCH001_METADATA_DIGEST_ADMISSION_PARTIAL"
        else:
            status = "BATCH001_METADATA_DIGEST_ADMISSION_NONE"
        record = self._record(
            "programbench_batch001_metadata_digest_admission",
            "determinex-programbench-batch001-metadata-digest-admission-v1",
            status,
            {
                "record_id": "programbench_batch001_metadata_digest_admission_run_20260528",
                "input_live_lookup": lookup_ref,
                "admissions": admissions,
                "summary": {
                    "digests_admitted_metadata_only": len(admitted),
                    "blocked_no_digest": sum(
                        1
                        for row in admissions
                        if row["status"] == "BATCH001_METADATA_DIGEST_ADMISSION_BLOCKED_NO_DIGEST"
                    ),
                },
                "cache_ready": False,
                "executable": False,
                "training_eligible": False,
                "authorization": _closed_auth(),
            },
        )
        return self._write(record, "programbench_batch001_metadata_digest_admission")

    def post_lookup_state_refresh(self, admission: dict[str, Any] | None = None) -> dict[str, Any]:
        admission = admission or self._read_or_build(
            DIGEST_ADMISSION_RECORD, self.metadata_digest_admission
        )
        priority_rows = self._read(PRIORITY_RECORD).get("ranked_unblock_list", [])
        admitted = {
            row["instance_id"]: row
            for row in admission.get("admissions", [])
            if row["status"] == "BATCH001_METADATA_DIGEST_ADMITTED"
        }
        rows = [_state_row(row, admitted.get(row.get("instance_id", ""))) for row in priority_rows]
        record = self._record(
            "programbench_batch001_post_lookup_state_refresh",
            "determinex-programbench-batch001-post-lookup-state-refresh-v1",
            "BATCH001_POST_LOOKUP_STATE_REFRESH_WRITTEN",
            {
                "record_id": "programbench_batch001_post_lookup_state_refresh_run_20260528",
                "input_digest_admission": _record_ref(
                    "programbench_batch001_metadata_digest_admission",
                    "programbench_batch001_metadata_digest_admission_run_20260528",
                    admission.get("status", "BATCH001_METADATA_DIGEST_ADMISSION_NONE"),
                ),
                "rows": rows,
                "summary": {
                    "metadata_only_digest_admitted": len(admitted),
                    "operator_metadata_still_required": sum(
                        1
                        for row in rows
                        if row["new_blocker"] == "OPERATOR_IMAGE_METADATA_REQUIRED"
                    ),
                    "artifact_import_and_scan_required": sum(
                        1
                        for row in rows
                        if row["new_blocker"] == "ARTIFACT_IMPORT_AND_SCAN_REQUIRED"
                    ),
                },
                "doxygen_preserved": _doxygen_preserved(rows),
                "cache_ready": False,
                "executable": False,
                "training_eligible": False,
                "authorization": _closed_auth(),
            },
        )
        return self._write(record, "programbench_batch001_post_lookup_state_refresh")

    def import_scan_planning(self, admission: dict[str, Any] | None = None) -> dict[str, Any]:
        admission = admission or self._read_or_build(
            DIGEST_ADMISSION_RECORD, self.metadata_digest_admission
        )
        plans = [_import_scan_plan(row) for row in admission.get("admissions", [])]
        applicable = [row for row in plans if row["status"] == "BATCH001_IMPORT_SCAN_PLAN_WRITTEN"]
        status = (
            "BATCH001_IMPORT_SCAN_PLAN_WRITTEN"
            if applicable
            else "BATCH001_IMPORT_SCAN_PLAN_NOT_APPLICABLE"
        )
        record = self._record(
            "programbench_batch001_import_scan_planning",
            "determinex-programbench-batch001-import-scan-planning-v1",
            status,
            {
                "record_id": "programbench_batch001_import_scan_planning_run_20260528",
                "input_digest_admission": _record_ref(
                    "programbench_batch001_metadata_digest_admission",
                    "programbench_batch001_metadata_digest_admission_run_20260528",
                    admission.get("status", "BATCH001_METADATA_DIGEST_ADMISSION_NONE"),
                ),
                "plans": plans,
                "summary": {
                    "plans_written": len(applicable),
                    "blocked_no_digest": sum(
                        1
                        for row in plans
                        if row["status"] == "BATCH001_IMPORT_SCAN_PLAN_BLOCKED_NO_DIGEST"
                    ),
                },
                "import_performed": False,
                "scan_performed": False,
                "execution_authorized": False,
                "authorization": _closed_auth(),
            },
        )
        return self._write(record, "programbench_batch001_import_scan_planning")

    def operator_packet_refresh_after_lookup(
        self,
        admission: dict[str, Any] | None = None,
        state_refresh: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        admission = admission or self._read_or_build(
            DIGEST_ADMISSION_RECORD, self.metadata_digest_admission
        )
        state_refresh = state_refresh or self._read_or_build(
            POST_LOOKUP_STATE_RECORD, self.post_lookup_state_refresh
        )
        admitted = {
            row["instance_id"]
            for row in admission.get("admissions", [])
            if row["status"] == "BATCH001_METADATA_DIGEST_ADMITTED"
        }
        packets = []
        for row in state_refresh.get("rows", []):
            instance_id = row["instance_id"]
            if instance_id == DOXYGEN_INSTANCE:
                packets.append(
                    _packet_template(
                        "security_policy_admission",
                        row,
                        "Doxygen remains blocked by policy admission.",
                    )
                )
            elif instance_id in admitted:
                packets.append(
                    _packet_template(
                        "artifact_import_provenance",
                        row,
                        "Import provenance is required before scan.",
                    )
                )
                packets.append(
                    _packet_template(
                        "scanner_admission",
                        row,
                        "Approved scan evidence is required before execution policy review.",
                    )
                )
            elif row.get("current_metadata_target") is True:
                packets.append(
                    _packet_template(
                        "image_metadata_submission", row, "Exact manifest digest remains required."
                    )
                )
        record = self._record(
            "programbench_batch001_operator_packet_refresh_after_lookup",
            "determinex-programbench-batch001-operator-packet-refresh-after-lookup-v1",
            "BATCH001_OPERATOR_PACKET_REFRESH_AFTER_LOOKUP_WRITTEN",
            {
                "record_id": "programbench_batch001_operator_packet_refresh_after_lookup_run_20260528",
                "inputs": {
                    "post_lookup_state_refresh": _record_ref(
                        "programbench_batch001_post_lookup_state_refresh",
                        "programbench_batch001_post_lookup_state_refresh_run_20260528",
                        state_refresh.get("status", "BATCH001_POST_LOOKUP_STATE_REFRESH_WRITTEN"),
                    ),
                    "previous_action_queue": _rel(ACTION_QUEUE),
                },
                "packet_templates": packets,
                "summary": _count_by(packets, "packet_type"),
                "all_packets_template_only": all(packet["template_only"] for packet in packets),
                "approvals_granted": 0,
                "execution_authorized": False,
                "training_eligible": False,
                "authorization": _closed_auth(),
            },
        )
        return self._write(record, "programbench_batch001_operator_packet_refresh_after_lookup")

    def lookup_campaign_final_state(
        self,
        lookup: dict[str, Any] | None = None,
        admission: dict[str, Any] | None = None,
        state_refresh: dict[str, Any] | None = None,
        import_plan: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        lookup = lookup or self._read_or_build(
            LIVE_LOOKUP_RECORD, self.live_manifest_metadata_lookup
        )
        admission = admission or self._read_or_build(
            DIGEST_ADMISSION_RECORD, self.metadata_digest_admission
        )
        state_refresh = state_refresh or self._read_or_build(
            POST_LOOKUP_STATE_RECORD, self.post_lookup_state_refresh
        )
        import_plan = import_plan or self._read_or_build(
            IMPORT_SCAN_PLAN_RECORD, self.import_scan_planning
        )
        summary = {
            "targets_attempted": lookup.get("summary", {}).get("targets_attempted", 0),
            "manifests_found": lookup.get("summary", {}).get("manifests_found", 0),
            "digests_admitted_metadata_only": admission.get("summary", {}).get(
                "digests_admitted_metadata_only", 0
            ),
            "not_found": lookup.get("summary", {}).get("not_found", 0),
            "blocked_by_policy": lookup.get("summary", {}).get("blocked_by_policy", 0),
            "rate_limited": lookup.get("summary", {}).get("rate_limited", 0),
            "provider_errors": lookup.get("summary", {}).get("provider_errors", 0),
            "still_need_operator_metadata": state_refresh.get("summary", {}).get(
                "operator_metadata_still_required", 0
            ),
            "now_need_import_scan": import_plan.get("summary", {}).get("plans_written", 0),
            "execution_performed": False,
            "training_rows_written": False,
        }
        record = self._record(
            "programbench_batch001_lookup_campaign_final_state",
            "determinex-programbench-batch001-lookup-campaign-final-state-v1",
            "BATCH001_LOOKUP_CAMPAIGN_FINAL_STATE_WRITTEN",
            {
                "record_id": "programbench_batch001_lookup_campaign_final_state_run_20260528",
                "inputs": {
                    "safe_registry_manifest_client": "assurance/evidence/programbench_safe_registry_manifest_client/programbench_safe_registry_manifest_client_run_20260528.SAFE_REGISTRY_MANIFEST_CLIENT_WRITTEN.json",
                    "live_manifest_metadata_lookup": _record_ref(
                        "programbench_batch001_live_manifest_metadata_lookup",
                        "programbench_batch001_live_manifest_metadata_lookup_run_20260528",
                        lookup.get("status", "BATCH001_LIVE_MANIFEST_LOOKUP_COMPLETED"),
                    ),
                    "metadata_digest_admission": _record_ref(
                        "programbench_batch001_metadata_digest_admission",
                        "programbench_batch001_metadata_digest_admission_run_20260528",
                        admission.get("status", "BATCH001_METADATA_DIGEST_ADMISSION_NONE"),
                    ),
                    "post_lookup_state_refresh": _record_ref(
                        "programbench_batch001_post_lookup_state_refresh",
                        "programbench_batch001_post_lookup_state_refresh_run_20260528",
                        state_refresh.get("status", "BATCH001_POST_LOOKUP_STATE_REFRESH_WRITTEN"),
                    ),
                    "import_scan_planning": _record_ref(
                        "programbench_batch001_import_scan_planning",
                        "programbench_batch001_import_scan_planning_run_20260528",
                        import_plan.get("status", "BATCH001_IMPORT_SCAN_PLAN_NOT_APPLICABLE"),
                    ),
                    "operator_packet_refresh": _rel(OPERATOR_PACKET_REFRESH_RECORD),
                },
                "summary": summary,
                "per_target_summary": _per_target_summary(lookup, state_refresh),
                "next_recommended_codex_rung": (
                    "PROGRAMBENCH_BATCH001_OPERATOR_IMAGE_METADATA_REQUEST_PACKET_LOCK_001"
                    if summary["still_need_operator_metadata"]
                    else "PROGRAMBENCH_BATCH001_ARTIFACT_IMPORT_REQUEST_PACKET_LOCK_001"
                ),
                "authorization": _closed_auth(),
            },
        )
        return self._write(record, "programbench_batch001_lookup_campaign_final_state")

    def operator_image_metadata_request_packet(
        self, state_refresh: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        state_refresh = state_refresh or self._read_or_build(
            POST_LOOKUP_STATE_RECORD, self.post_lookup_state_refresh
        )
        packets = [
            _metadata_request_packet(row)
            for row in state_refresh.get("rows", [])
            if row.get("current_metadata_target") is True
            and row.get("new_blocker") == "OPERATOR_IMAGE_METADATA_REQUIRED"
        ]
        record = self._record(
            "programbench_batch001_operator_image_metadata_request_packet",
            "determinex-programbench-batch001-operator-image-metadata-request-packet-v1",
            "OPERATOR_IMAGE_METADATA_REQUEST_PACKETS_WRITTEN",
            {
                "record_id": "programbench_batch001_operator_image_metadata_request_packet_run_20260528",
                "input_post_lookup_state_refresh": _rel(POST_LOOKUP_STATE_RECORD),
                "packets": packets,
                "summary": {"packets_written": len(packets)},
                "all_packets_template_only": True,
                "approvals_granted": 0,
                "execution_authorized": False,
                "training_eligible": False,
                "authorization": _closed_auth(),
            },
        )
        return self._write(record, "programbench_batch001_operator_image_metadata_request_packet")

    def run_all(self) -> dict[str, dict[str, Any]]:
        client_record = self.safe_registry_manifest_client()
        lookup = self.live_manifest_metadata_lookup()
        admission = self.metadata_digest_admission(lookup)
        state = self.post_lookup_state_refresh(admission)
        import_plan = self.import_scan_planning(admission)
        packets = self.operator_packet_refresh_after_lookup(admission, state)
        final = self.lookup_campaign_final_state(lookup, admission, state, import_plan)
        metadata_requests = self.operator_image_metadata_request_packet(state)
        return {
            "client": client_record,
            "lookup": lookup,
            "admission": admission,
            "state": state,
            "import_plan": import_plan,
            "packets": packets,
            "final": final,
            "metadata_requests": metadata_requests,
        }

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
        return make_live_manifest_metadata_record(
            record_type=record_type,
            schema_version=schema_version,
            status=status,
            payload=payload,
        )

    def _write(self, record: dict[str, Any], directory_name: str) -> dict[str, Any]:
        if self.config.write_records:
            write_live_manifest_metadata_record(
                record, self.config.root / "assurance" / "evidence" / directory_name
            )
        return record


def _target_lookup_row(plan: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    return {
        "instance_id": plan.get("instance_id", ""),
        "exact_image_repo": result.get("repository") or _repo(plan.get("image_name", "")),
        "exact_tag": result.get("tag") or "task_cleanroom",
        "image_name": plan.get("image_name", ""),
        "provider": plan.get("provider", "docker_hub_official"),
        "lookup_attempted": result.get("status")
        not in {"REGISTRY_MANIFEST_LOOKUP_BLOCKED_UNADMITTED_PROVIDER"},
        "lookup_status": result.get("status", ""),
        "digest": result.get("digest", ""),
        "media_type": result.get("media_type", ""),
        "schema_version": result.get("schema_version"),
        "platforms": result.get("platforms", []),
        "manifest_body_hash": result.get("manifest_body_hash", ""),
        "manifest_summary_hash": result.get("manifest_summary_hash", ""),
        "lookup_error": result.get("error", ""),
        "http_status": result.get("http_status", 0),
        "metadata_only": True,
        "cache_ready": False,
        "executable": False,
        "training_eligible": False,
        "docker_pull_performed": False,
        "layer_downloaded": False,
        "image_imported": False,
        "docker_run_performed": False,
        "evidence_refs": {"manifest_plan": _rel(MANIFEST_PLAN_RECORD)},
    }


def _lookup_blocked(plan: dict[str, Any], status: str, error: str) -> dict[str, Any]:
    return {
        "status": status,
        "repository": _repo(plan.get("image_name", "")),
        "tag": plan.get("tag", "task_cleanroom"),
        "error": error,
    }


def _lookup_status(results: list[dict[str, Any]]) -> str:
    if not results:
        return "BATCH001_LIVE_MANIFEST_LOOKUP_BLOCKED_PROVIDER_POLICY"
    found = sum(1 for row in results if row["lookup_status"] == "REGISTRY_MANIFEST_METADATA_FOUND")
    if found == len(results):
        return "BATCH001_LIVE_MANIFEST_LOOKUP_COMPLETED"
    if found:
        return "BATCH001_LIVE_MANIFEST_LOOKUP_PARTIAL"
    if all(row["lookup_status"] == "REGISTRY_MANIFEST_METADATA_NOT_FOUND" for row in results):
        return "BATCH001_LIVE_MANIFEST_LOOKUP_ALL_NOT_FOUND"
    if all(
        row["lookup_status"] == "REGISTRY_MANIFEST_LOOKUP_BLOCKED_NETWORK_DISABLED"
        for row in results
    ):
        return "BATCH001_LIVE_MANIFEST_LOOKUP_BLOCKED_NETWORK_DISABLED"
    return "BATCH001_LIVE_MANIFEST_LOOKUP_PARTIAL"


def _lookup_summary(results: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "targets_attempted": len(results),
        "manifests_found": sum(
            1 for row in results if row["lookup_status"] == "REGISTRY_MANIFEST_METADATA_FOUND"
        ),
        "not_found": sum(
            1 for row in results if row["lookup_status"] == "REGISTRY_MANIFEST_METADATA_NOT_FOUND"
        ),
        "blocked_by_policy": sum(
            1
            for row in results
            if "BLOCKED" in row["lookup_status"]
            and row["lookup_status"] != "REGISTRY_MANIFEST_LOOKUP_BLOCKED_NETWORK_DISABLED"
        ),
        "blocked_network_disabled": sum(
            1
            for row in results
            if row["lookup_status"] == "REGISTRY_MANIFEST_LOOKUP_BLOCKED_NETWORK_DISABLED"
        ),
        "rate_limited": sum(
            1 for row in results if row["lookup_status"] == "REGISTRY_MANIFEST_LOOKUP_RATE_LIMITED"
        ),
        "provider_errors": sum(
            1
            for row in results
            if row["lookup_status"] == "REGISTRY_MANIFEST_LOOKUP_PROVIDER_ERROR"
        ),
    }


def _admission(row: dict[str, Any], lookup_ref: str) -> dict[str, Any]:
    digest = str(row.get("digest") or "")
    if digest.startswith("sha256:"):
        status = "BATCH001_METADATA_DIGEST_ADMITTED"
        authority = "metadata_only_present"
    else:
        status = "BATCH001_METADATA_DIGEST_ADMISSION_BLOCKED_NO_DIGEST"
        authority = "inconclusive"
    return {
        "instance_id": row.get("instance_id", ""),
        "image_name": row.get("image_name", ""),
        "digest": digest,
        "provider": row.get("provider", ""),
        "exact_lookup_evidence_ref": lookup_ref,
        "artifact_authority": authority,
        "status": status,
        "scan_required_before_execution": status == "BATCH001_METADATA_DIGEST_ADMITTED",
        "import_required_before_scan": status == "BATCH001_METADATA_DIGEST_ADMITTED",
        "cache_ready": False,
        "executable": False,
        "training_eligible": False,
    }


def _state_row(priority: dict[str, Any], admission: dict[str, Any] | None) -> dict[str, Any]:
    instance_id = priority.get("instance_id", "")
    current_target = (
        priority.get("estimated_difficulty") == "EASY_METADATA_ONLY"
        and instance_id != DOXYGEN_INSTANCE
    )
    if instance_id == DOXYGEN_INSTANCE:
        blocker = "OPERATOR_SECURITY_POLICY_ADMISSION"
        next_unblocker = "OPERATOR_SECURITY_POLICY_ADMISSION"
        authority = "ARTIFACT_AUTHORITY_PRESENT"
        metadata_status = "PRESENT"
        image = priority.get("image_name", "")
        digest = priority.get("image_digest", "")
    elif admission:
        blocker = "ARTIFACT_IMPORT_AND_SCAN_REQUIRED"
        next_unblocker = "ARTIFACT_IMPORT_AND_SCAN_REQUIRED"
        authority = "ARTIFACT_AUTHORITY_METADATA_ONLY_PRESENT"
        metadata_status = "PRESENT"
        image = admission.get("image_name", "")
        digest = admission.get("digest", "")
    else:
        blocker = "OPERATOR_IMAGE_METADATA_REQUIRED"
        next_unblocker = "OPERATOR_IMAGE_METADATA_REQUIRED"
        authority = priority.get("artifact_authority_status", "ARTIFACT_AUTHORITY_INCONCLUSIVE")
        metadata_status = (
            "MISSING" if current_target else priority.get("image_metadata_status", "UNKNOWN")
        )
        image = priority.get("image_name", "")
        digest = priority.get("image_digest", "")
    return {
        "instance_id": instance_id,
        "current_metadata_target": current_target,
        "previous_blocker": priority.get("current_blocker", priority.get("next_unblocker", "")),
        "new_blocker": blocker,
        "artifact_authority_status": authority,
        "metadata_status": metadata_status,
        "image_name": image,
        "image_digest": digest,
        "scan_import_required": blocker == "ARTIFACT_IMPORT_AND_SCAN_REQUIRED",
        "operator_metadata_still_required": blocker == "OPERATOR_IMAGE_METADATA_REQUIRED",
        "next_unblocker": next_unblocker,
        "cache_ready": False,
        "executable": False,
        "training_eligible": False,
    }


def _doxygen_preserved(rows: list[dict[str, Any]]) -> bool:
    row = next((item for item in rows if item.get("instance_id") == DOXYGEN_INSTANCE), {})
    return (
        row.get("artifact_authority_status") == "ARTIFACT_AUTHORITY_PRESENT"
        and row.get("new_blocker") == "OPERATOR_SECURITY_POLICY_ADMISSION"
        and row.get("executable") is False
        and row.get("training_eligible") is False
    )


def _import_scan_plan(admission: dict[str, Any]) -> dict[str, Any]:
    digest = str(admission.get("digest") or "")
    if not digest.startswith("sha256:"):
        return {
            "instance_id": admission.get("instance_id", ""),
            "image_name": admission.get("image_name", ""),
            "digest": "",
            "status": "BATCH001_IMPORT_SCAN_PLAN_BLOCKED_NO_DIGEST",
            "no_execution_authorized": True,
        }
    instance_id = str(admission.get("instance_id") or "")
    return {
        "instance_id": instance_id,
        "image_name": admission.get("image_name", ""),
        "digest": digest,
        "import_needed": True,
        "artifact_tar_path_expected": f"assurance/artifacts/programbench/{_safe(instance_id)}.task_cleanroom.tar",
        "scan_required": True,
        "approved_scanner_required": True,
        "security_decision_required_after_scan": True,
        "policy_admission_required_if_scan_fails": True,
        "status": "BATCH001_IMPORT_SCAN_PLAN_WRITTEN",
        "import_performed": False,
        "scan_performed": False,
        "no_execution_authorized": True,
    }


def _packet_template(packet_type: str, row: dict[str, Any], note: str) -> dict[str, Any]:
    return {
        "schema_version": "determinex-programbench-operator-packet-template-v1",
        "packet_type": packet_type,
        "template_only": True,
        "approval_status": "TEMPLATE_NOT_APPROVAL",
        "instance_id": row.get("instance_id", ""),
        "image_name": row.get("image_name", ""),
        "image_digest": row.get("image_digest", ""),
        "required_evidence": _required_evidence(packet_type),
        "acceptable_forms": ["operator-signed JSON packet", "locally signed evidence record"],
        "rejected_forms": [
            "latest tag",
            "name-only reference",
            "fixture approval",
            "execution authorization",
        ],
        "operator_identity": "<operator_identity>",
        "operator_signature": "<operator_signature>",
        "timestamp": "<iso8601_timestamp>",
        "note": note,
        "authorizes_execution": False,
        "training_eligible": False,
    }


def _metadata_request_packet(row: dict[str, Any]) -> dict[str, Any]:
    packet = _packet_template(
        "image_metadata_submission",
        row,
        "Safe exact live lookup did not admit a digest; operator metadata is required.",
    )
    packet["required_evidence"] = [
        "exact image reference matching the derived ProgramBench name",
        "immutable manifest digest",
        "DockerHub manifest metadata summary or signed operator metadata evidence",
    ]
    return packet


def _required_evidence(packet_type: str) -> list[str]:
    mapping = {
        "security_policy_admission": [
            "operator policy admission bound to exact scan and sandbox records"
        ],
        "artifact_import_provenance": [
            "artifact source",
            "digest",
            "import manifest",
            "operator signature",
        ],
        "scanner_admission": ["approved scanner identity", "scanner version", "scan evidence"],
        "image_metadata_submission": [
            "exact image reference",
            "immutable digest",
            "provider manifest evidence",
        ],
    }
    return mapping.get(packet_type, ["operator signed evidence"])


def _per_target_summary(
    lookup: dict[str, Any], state_refresh: dict[str, Any]
) -> list[dict[str, Any]]:
    state_by_id = {row["instance_id"]: row for row in state_refresh.get("rows", [])}
    rows = []
    for item in lookup.get("results", []):
        state = state_by_id.get(item.get("instance_id", ""), {})
        rows.append(
            {
                "instance_id": item.get("instance_id", ""),
                "image": item.get("image_name", ""),
                "lookup_status": item.get("lookup_status", ""),
                "digest": item.get("digest", ""),
                "next_unblocker": state.get("next_unblocker", "OPERATOR_IMAGE_METADATA_REQUIRED"),
            }
        )
    return rows


def _repo(image: str) -> str:
    image = str(image)
    if ":" in image.rsplit("/", 1)[-1]:
        return image.rsplit(":", 1)[0]
    return image


def _count_by(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        value = str(item.get(key, ""))
        counts[value] = counts.get(value, 0) + 1
    return counts


def _hash_json(data: Any) -> str:
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
    )


def _safe(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-._" else "_" for ch in value)[:140]


def _rel(path: Path) -> str:
    return str(path).replace("\\", "/")


def _record_ref(directory: str, record_id: str, status: str) -> str:
    return f"assurance/evidence/{directory}/{record_id}.{status}.json"


def _closed_auth() -> dict[str, bool]:
    return {
        "docker_execution_authorized": False,
        "docker_pull_authorized": False,
        "layer_download_authorized": False,
        "image_import_authorized": False,
        "programbench_rerun_authorized": False,
        "rebuild_authorized": False,
        "remediation_authorized": False,
        "policy_exception_granted": False,
        "training_rows_written": False,
        "training_eligible": False,
        "cache_ready": False,
        "executable": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run exact Batch001 ProgramBench manifest metadata lookup campaign."
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--no-live-lookup", action="store_true")
    args = parser.parse_args(argv)
    campaign = ProgramBenchBatch001LiveManifestLookupCampaign(
        Batch001LiveManifestLookupConfig(
            write_records=not args.no_write, live_lookup=not args.no_live_lookup
        )
    )
    records = campaign.run_all()
    if args.json:
        print(json.dumps(records, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
