#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from corpus.programbench.batch001_metadata_campaign_record import (
    make_metadata_campaign_record,
    write_metadata_campaign_record,
)
from corpus.programbench.batch001_unblock_priority import DIFFICULTY_ORDER
from corpus.programbench.programbench_campaign_platform import ACTION_QUEUE, DOXYGEN_INSTANCE

PRIORITY_RECORD = Path(
    "assurance/evidence/programbench_batch001_unblock_priority/"
    "programbench_batch001_unblock_priority_run_20260528.BATCH001_UNBLOCK_PRIORITY_WRITTEN.json"
)
DERIVATION_RECORD = Path(
    "assurance/evidence/programbench_batch001_image_name_derivation/"
    "programbench_batch001_image_name_derivation_run_20260528.IMAGE_NAME_DERIVATION_WRITTEN.json"
)
MANIFEST_PLAN_RECORD = Path(
    "assurance/evidence/programbench_batch001_exact_manifest_metadata_plan/"
    "programbench_batch001_exact_manifest_metadata_plan_run_20260528.EXACT_MANIFEST_METADATA_PLAN_WRITTEN.json"
)
SAFE_LOOKUP_RECORD = Path(
    "assurance/evidence/programbench_batch001_safe_manifest_lookup/"
    "programbench_batch001_safe_manifest_lookup_run_20260528.SAFE_MANIFEST_LOOKUP_NOT_SUPPORTED.json"
)
DIGEST_ADMISSION_RECORD = Path(
    "assurance/evidence/programbench_batch001_manifest_digest_admission/"
    "programbench_batch001_manifest_digest_admission_run_20260528.MANIFEST_DIGEST_ADMISSION_BLOCKED_NO_DIGEST.json"
)
STATE_REFRESH_RECORD = Path(
    "assurance/evidence/programbench_batch001_metadata_state_refresh/"
    "programbench_batch001_metadata_state_refresh_run_20260528.BATCH001_METADATA_STATE_NO_CHANGE.json"
)
SCAN_QUEUE_RECORD = Path(
    "assurance/evidence/programbench_batch001_scan_requirements_queue/"
    "programbench_batch001_scan_requirements_queue_run_20260528.SCAN_REQUIREMENTS_BLOCKED_NO_DIGEST.json"
)
ACTION_REFRESH_RECORD = Path(
    "assurance/evidence/programbench_batch001_operator_action_refresh/"
    "programbench_batch001_operator_action_refresh_run_20260528.BATCH001_OPERATOR_ACTION_REFRESH_WRITTEN.json"
)
PRIORITY_REFRESH_RECORD = Path(
    "assurance/evidence/programbench_batch001_unblock_priority_refresh/"
    "programbench_batch001_unblock_priority_refresh_run_20260528.BATCH001_UNBLOCK_PRIORITY_REFRESH_WRITTEN.json"
)
FINAL_STATE_RECORD = Path(
    "assurance/evidence/programbench_batch001_metadata_campaign_final_state/"
    "programbench_batch001_metadata_campaign_final_state_run_20260528.BATCH001_METADATA_CAMPAIGN_FINAL_STATE_WRITTEN.json"
)

INSTANCE_RE = re.compile(
    r"^(?P<owner>[A-Za-z0-9_.-]+)__(?P<repo_sha>[A-Za-z0-9_.-]+\.[0-9a-fA-F]{7,})$"
)


@dataclass(slots=True)
class Batch001MetadataCampaignConfig:
    root: Path = Path(".")
    write_records: bool = True


class ProgramBenchBatch001MetadataCampaign:
    def __init__(self, config: Batch001MetadataCampaignConfig | None = None) -> None:
        self.config = config or Batch001MetadataCampaignConfig()

    def image_name_derivation(self) -> dict[str, Any]:
        targets = self._metadata_targets()
        rows = [derive_image_name(row) for row in targets]
        status = "IMAGE_NAME_DERIVATION_WRITTEN"
        if any(row["status"] == "IMAGE_NAME_DERIVATION_BLOCKED_BAD_INSTANCE_ID" for row in rows):
            status = "IMAGE_NAME_DERIVATION_BLOCKED_BAD_INSTANCE_ID"
        elif any(
            row["status"] == "IMAGE_NAME_DERIVATION_BLOCKED_UNSUPPORTED_PATTERN" for row in rows
        ):
            status = "IMAGE_NAME_DERIVATION_BLOCKED_UNSUPPORTED_PATTERN"
        record = self._record(
            record_type="programbench_batch001_image_name_derivation",
            schema_version="determinex-programbench-batch001-image-name-derivation-v1",
            status=status,
            payload={
                "record_id": "programbench_batch001_image_name_derivation_run_20260528",
                "input_priority_record": _rel(PRIORITY_RECORD),
                "targets": rows,
                "summary": {
                    "targets_considered": len(rows),
                    "image_names_derived": sum(1 for row in rows if row["derived_exact"] is True),
                    "digests_inferred": 0,
                    "artifact_authority_upgraded": 0,
                },
                "does_not_infer_digest": True,
                "does_not_mark_artifact_authority_present": True,
                "authorization": _closed_auth(),
            },
        )
        return self._write(record, "programbench_batch001_image_name_derivation")

    def exact_manifest_metadata_plan(
        self, derivation: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        derivation = derivation or self._read_or_build(
            DERIVATION_RECORD, self.image_name_derivation
        )
        plans = [_manifest_plan(row) for row in derivation.get("targets", [])]
        status = "EXACT_MANIFEST_METADATA_PLAN_WRITTEN"
        if any(
            plan["status"] == "EXACT_MANIFEST_METADATA_PLAN_BLOCKED_NO_IMAGE_NAME" for plan in plans
        ):
            status = "EXACT_MANIFEST_METADATA_PLAN_BLOCKED_NO_IMAGE_NAME"
        record = self._record(
            record_type="programbench_batch001_exact_manifest_metadata_plan",
            schema_version="determinex-programbench-batch001-exact-manifest-metadata-plan-v1",
            status=status,
            payload={
                "record_id": "programbench_batch001_exact_manifest_metadata_plan_run_20260528",
                "input_derivation_record": _rel(DERIVATION_RECORD),
                "plans": plans,
                "summary": {
                    "targets_planned": len(plans),
                    "digests_fabricated": 0,
                    "broad_search_allowed": False,
                    "pull_or_run_allowed": False,
                },
                "authorization": _closed_auth(),
            },
        )
        return self._write(record, "programbench_batch001_exact_manifest_metadata_plan")

    def safe_manifest_lookup(self, plan: dict[str, Any] | None = None) -> dict[str, Any]:
        plan = plan or self._read_or_build(MANIFEST_PLAN_RECORD, self.exact_manifest_metadata_plan)
        results = []
        for item in plan.get("plans", []):
            results.append(
                {
                    "instance_id": item.get("instance_id", ""),
                    "image_name": item.get("image_name", ""),
                    "tag": item.get("tag", "task_cleanroom"),
                    "provider": item.get("provider", "docker_hub_official"),
                    "status": "SAFE_MANIFEST_LOOKUP_NOT_SUPPORTED",
                    "manifest_found": False,
                    "digest": "",
                    "lookup_method": "none_live_lookup_not_implemented_in_existing_provider_path",
                    "raw_metadata_hash": "",
                    "safe_summary": (
                        "Provider registry admits exact DockerHub references, but this repo only has conversion "
                        "for already-supplied manifest metadata; no live retrieval client is implemented."
                    ),
                    "evidence_refs": {"manifest_plan": _rel(MANIFEST_PLAN_RECORD)},
                }
            )
        record = self._record(
            record_type="programbench_batch001_safe_manifest_lookup",
            schema_version="determinex-programbench-batch001-safe-manifest-lookup-v1",
            status="SAFE_MANIFEST_LOOKUP_NOT_SUPPORTED",
            payload={
                "record_id": "programbench_batch001_safe_manifest_lookup_run_20260528",
                "input_manifest_plan": _rel(MANIFEST_PLAN_RECORD),
                "metadata_only_lookup_supported": False,
                "network_operations_executed": False,
                "docker_pull_performed": False,
                "docker_run_performed": False,
                "manifest_lookups_attempted": 0,
                "results": results,
                "fixture_statuses_supported_by_tests": [
                    "SAFE_MANIFEST_LOOKUP_MANIFEST_FOUND",
                    "SAFE_MANIFEST_LOOKUP_MANIFEST_NOT_FOUND",
                    "SAFE_MANIFEST_LOOKUP_BLOCKED_BY_POLICY",
                    "SAFE_MANIFEST_LOOKUP_NOT_SUPPORTED",
                ],
                "authorization": _closed_auth(),
            },
        )
        return self._write(record, "programbench_batch001_safe_manifest_lookup")

    def manifest_digest_admission(self, lookup: dict[str, Any] | None = None) -> dict[str, Any]:
        lookup = lookup or self._read_or_build(SAFE_LOOKUP_RECORD, self.safe_manifest_lookup)
        admissions = [_admit_manifest_digest(row) for row in lookup.get("results", [])]
        admitted = [
            row for row in admissions if row["artifact_authority_result"] == "metadata_only_present"
        ]
        status = (
            "MANIFEST_DIGEST_METADATA_ADMITTED"
            if admitted
            else "MANIFEST_DIGEST_ADMISSION_BLOCKED_NO_DIGEST"
        )
        record = self._record(
            record_type="programbench_batch001_manifest_digest_admission",
            schema_version="determinex-programbench-batch001-manifest-digest-admission-v1",
            status=status,
            payload={
                "record_id": "programbench_batch001_manifest_digest_admission_run_20260528",
                "input_safe_lookup": _rel(SAFE_LOOKUP_RECORD),
                "admissions": admissions,
                "summary": {
                    "metadata_admitted": len(admitted),
                    "blocked_no_digest": sum(
                        1
                        for row in admissions
                        if row["status"] == "MANIFEST_DIGEST_ADMISSION_BLOCKED_NO_DIGEST"
                    ),
                },
                "cache_ready": False,
                "executable": False,
                "training_eligible": False,
                "authorization": _closed_auth(),
            },
        )
        return self._write(record, "programbench_batch001_manifest_digest_admission")

    def metadata_state_refresh(self, admission: dict[str, Any] | None = None) -> dict[str, Any]:
        admission = admission or self._read_or_build(
            DIGEST_ADMISSION_RECORD, self.manifest_digest_admission
        )
        before = self._priority_rows()
        admitted = {
            row["instance_id"]: row
            for row in admission.get("admissions", [])
            if row["artifact_authority_result"] == "metadata_only_present"
        }
        rows = [_state_refresh_row(row, admitted.get(row["instance_id"])) for row in before]
        changed = sum(1 for row in rows if row["changed"] is True)
        status = (
            "BATCH001_METADATA_STATE_REFRESH_WRITTEN"
            if changed
            else "BATCH001_METADATA_STATE_NO_CHANGE"
        )
        record = self._record(
            record_type="programbench_batch001_metadata_state_refresh",
            schema_version="determinex-programbench-batch001-metadata-state-refresh-v1",
            status=status,
            payload={
                "record_id": "programbench_batch001_metadata_state_refresh_run_20260528",
                "input_digest_admission": _rel(DIGEST_ADMISSION_RECORD),
                "rows": rows,
                "doxygen_state_preserved": _doxygen_preserved(before, rows),
                "summary": {
                    "targets_refreshed": len(rows),
                    "changed": changed,
                    "metadata_admitted": len(admitted),
                    "still_missing_metadata": sum(
                        1
                        for row in rows
                        if row["after_state"]["image_metadata_status"] == "MISSING"
                    ),
                },
                "authorization": _closed_auth(),
            },
        )
        return self._write(record, "programbench_batch001_metadata_state_refresh")

    def scan_requirements_queue(self, admission: dict[str, Any] | None = None) -> dict[str, Any]:
        admission = admission or self._read_or_build(
            DIGEST_ADMISSION_RECORD, self.manifest_digest_admission
        )
        admitted = [
            row
            for row in admission.get("admissions", [])
            if row["artifact_authority_result"] == "metadata_only_present"
        ]
        rows = [_scan_requirement(row) for row in admission.get("admissions", [])]
        status = (
            "SCAN_REQUIREMENTS_QUEUE_WRITTEN" if admitted else "SCAN_REQUIREMENTS_BLOCKED_NO_DIGEST"
        )
        record = self._record(
            record_type="programbench_batch001_scan_requirements_queue",
            schema_version="determinex-programbench-batch001-scan-requirements-queue-v1",
            status=status,
            payload={
                "record_id": "programbench_batch001_scan_requirements_queue_run_20260528",
                "input_digest_admission": _rel(DIGEST_ADMISSION_RECORD),
                "items": rows,
                "summary": {
                    "metadata_admitted": len(admitted),
                    "import_required_before_scan": sum(
                        1 for row in rows if row["local_artifact_import_required"] is True
                    ),
                    "blocked_no_digest": sum(
                        1 for row in rows if row["status"] == "SCAN_REQUIREMENTS_BLOCKED_NO_DIGEST"
                    ),
                },
                "no_import_authorized": True,
                "no_scan_executed": True,
                "authorization": _closed_auth(),
            },
        )
        return self._write(record, "programbench_batch001_scan_requirements_queue")

    def operator_action_refresh(
        self, state_refresh: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        state_refresh = state_refresh or self._read_or_build(
            STATE_REFRESH_RECORD, self.metadata_state_refresh
        )
        actions = []
        for row in state_refresh.get("rows", []):
            after = row.get("after_state", {})
            if row["instance_id"] == DOXYGEN_INSTANCE:
                action = _action(
                    row["instance_id"],
                    "SUPPLY_SECURITY_POLICY_ADMISSION",
                    "BLOCKED_POLICY_ADMISSION_REQUIRED",
                )
            elif after.get("image_metadata_status") == "PRESENT" and after.get("image_digest"):
                action = _action(
                    row["instance_id"],
                    "REQUEST_ARTIFACT_IMPORT_AND_SCAN_REVIEW",
                    "BLOCKED_IMPORT_OR_SCAN_REQUIRED",
                )
            else:
                action = _action(
                    row["instance_id"], "SUPPLY_IMAGE_METADATA", "BLOCKED_MISSING_IMAGE_METADATA"
                )
            actions.append(action)
        record = self._record(
            record_type="programbench_batch001_operator_action_refresh",
            schema_version="determinex-programbench-batch001-operator-action-refresh-v1",
            status="BATCH001_OPERATOR_ACTION_REFRESH_WRITTEN",
            payload={
                "record_id": "programbench_batch001_operator_action_refresh_run_20260528",
                "input_state_refresh": _rel(STATE_REFRESH_RECORD),
                "previous_action_queue": _rel(ACTION_QUEUE),
                "actions": actions,
                "summary": _count_by(actions, "action_type"),
                "authorization": _closed_auth(),
            },
        )
        return self._write(record, "programbench_batch001_operator_action_refresh")

    def unblock_priority_refresh(
        self, state_refresh: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        state_refresh = state_refresh or self._read_or_build(
            STATE_REFRESH_RECORD, self.metadata_state_refresh
        )
        refreshed = [_refreshed_priority(row) for row in state_refresh.get("rows", [])]
        refreshed.sort(
            key=lambda row: (
                DIFFICULTY_ORDER.get(row["estimated_difficulty"], 99),
                row["instance_id"],
            )
        )
        for index, row in enumerate(refreshed, start=1):
            row["rank"] = index
        previous = self._priority_rows()
        record = self._record(
            record_type="programbench_batch001_unblock_priority_refresh",
            schema_version="determinex-programbench-batch001-unblock-priority-refresh-v1",
            status="BATCH001_UNBLOCK_PRIORITY_REFRESH_WRITTEN",
            payload={
                "record_id": "programbench_batch001_unblock_priority_refresh_run_20260528",
                "input_state_refresh": _rel(STATE_REFRESH_RECORD),
                "previous_priority_record": _rel(PRIORITY_RECORD),
                "ranked_unblock_list": refreshed,
                "top_3_next_targets": refreshed[:3],
                "comparison": {
                    "previous_top_3": [row["instance_id"] for row in previous[:3]],
                    "refreshed_top_3": [row["instance_id"] for row in refreshed[:3]],
                    "ranking_changed": [row["instance_id"] for row in previous[:3]]
                    != [row["instance_id"] for row in refreshed[:3]],
                    "metadata_admitted": sum(
                        1
                        for row in refreshed
                        if row["image_metadata_status"] == "PRESENT"
                        and row["instance_id"] != DOXYGEN_INSTANCE
                    ),
                },
                "authorization": _closed_auth(),
            },
        )
        return self._write(record, "programbench_batch001_unblock_priority_refresh")

    def final_state(
        self,
        derivation: dict[str, Any] | None = None,
        lookup: dict[str, Any] | None = None,
        admission: dict[str, Any] | None = None,
        scan_queue: dict[str, Any] | None = None,
        priority_refresh: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        derivation = derivation or self._read_or_build(
            DERIVATION_RECORD, self.image_name_derivation
        )
        lookup = lookup or self._read_or_build(SAFE_LOOKUP_RECORD, self.safe_manifest_lookup)
        admission = admission or self._read_or_build(
            DIGEST_ADMISSION_RECORD, self.manifest_digest_admission
        )
        scan_queue = scan_queue or self._read_or_build(
            SCAN_QUEUE_RECORD, self.scan_requirements_queue
        )
        priority_refresh = priority_refresh or self._read_or_build(
            PRIORITY_REFRESH_RECORD, self.unblock_priority_refresh
        )
        summary = {
            "targets_considered": len(derivation.get("targets", [])),
            "image_names_derived": derivation.get("summary", {}).get("image_names_derived", 0),
            "manifest_lookups_attempted": lookup.get("manifest_lookups_attempted", 0),
            "manifest_digests_found": sum(
                1 for row in lookup.get("results", []) if row.get("digest")
            ),
            "metadata_admitted": admission.get("summary", {}).get("metadata_admitted", 0),
            "still_missing_metadata": sum(
                1
                for row in priority_refresh.get("ranked_unblock_list", [])
                if row.get("image_metadata_status") == "MISSING"
            ),
            "now_require_import_or_scan": scan_queue.get("summary", {}).get(
                "import_required_before_scan", 0
            ),
            "now_require_policy_admission": sum(
                1
                for row in priority_refresh.get("ranked_unblock_list", [])
                if row.get("estimated_difficulty") == "HARD_POLICY_ADMISSION_REQUIRED"
            ),
            "doxygen_preserved_blocked_state": True,
            "execution_performed": False,
            "training_rows_written": False,
        }
        record = self._record(
            record_type="programbench_batch001_metadata_campaign_final_state",
            schema_version="determinex-programbench-batch001-metadata-campaign-final-state-v1",
            status="BATCH001_METADATA_CAMPAIGN_FINAL_STATE_WRITTEN",
            payload={
                "record_id": "programbench_batch001_metadata_campaign_final_state_run_20260528",
                "inputs": {
                    "image_name_derivation": _rel(DERIVATION_RECORD),
                    "exact_manifest_metadata_plan": _rel(MANIFEST_PLAN_RECORD),
                    "safe_manifest_lookup": _rel(SAFE_LOOKUP_RECORD),
                    "manifest_digest_admission": _rel(DIGEST_ADMISSION_RECORD),
                    "metadata_state_refresh": _rel(STATE_REFRESH_RECORD),
                    "scan_requirements_queue": _rel(SCAN_QUEUE_RECORD),
                    "operator_action_refresh": _rel(ACTION_REFRESH_RECORD),
                    "priority_refresh": _rel(PRIORITY_REFRESH_RECORD),
                },
                "summary": summary,
                "top_refreshed_next_targets": priority_refresh.get("top_3_next_targets", []),
                "next_recommended_codex_rung": "PROGRAMBENCH_BATCH001_OPERATOR_IMAGE_METADATA_REQUEST_PACKET_LOCK_001",
                "authorization": _closed_auth(),
            },
        )
        return self._write(record, "programbench_batch001_metadata_campaign_final_state")

    def run_all(self) -> dict[str, dict[str, Any]]:
        derivation = self.image_name_derivation()
        plan = self.exact_manifest_metadata_plan(derivation)
        lookup = self.safe_manifest_lookup(plan)
        admission = self.manifest_digest_admission(lookup)
        state = self.metadata_state_refresh(admission)
        scan = self.scan_requirements_queue(admission)
        actions = self.operator_action_refresh(state)
        priority = self.unblock_priority_refresh(state)
        final = self.final_state(derivation, lookup, admission, scan, priority)
        return {
            "derivation": derivation,
            "plan": plan,
            "lookup": lookup,
            "admission": admission,
            "state": state,
            "scan": scan,
            "actions": actions,
            "priority": priority,
            "final": final,
        }

    def _metadata_targets(self) -> list[dict[str, Any]]:
        return [
            row
            for row in self._priority_rows()
            if row.get("estimated_difficulty") == "EASY_METADATA_ONLY"
            and row.get("instance_id") != DOXYGEN_INSTANCE
        ]

    def _priority_rows(self) -> list[dict[str, Any]]:
        return self._read(PRIORITY_RECORD).get("ranked_unblock_list", [])

    def _read_or_build(self, path: Path, builder: Any) -> dict[str, Any]:
        data = self._read(path)
        return data if data else builder()

    def _read(self, path: Path) -> dict[str, Any]:
        full = self.config.root / path
        if not full.exists():
            return {}
        return json.loads(full.read_text(encoding="utf-8"))

    def _record(
        self, *, record_type: str, schema_version: str, status: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return make_metadata_campaign_record(
            record_type=record_type,
            schema_version=schema_version,
            status=status,
            payload=payload,
        )

    def _write(self, record: dict[str, Any], directory_name: str) -> dict[str, Any]:
        if self.config.write_records:
            write_metadata_campaign_record(
                record,
                self.config.root / "assurance" / "evidence" / directory_name,
            )
        return record


def derive_image_name(priority_row: dict[str, Any]) -> dict[str, Any]:
    instance_id = str(priority_row.get("instance_id") or "")
    match = INSTANCE_RE.match(instance_id)
    if not instance_id:
        status = "IMAGE_NAME_DERIVATION_BLOCKED_BAD_INSTANCE_ID"
        image = ""
        confidence = "none"
        exact = False
    elif not match:
        status = "IMAGE_NAME_DERIVATION_BLOCKED_UNSUPPORTED_PATTERN"
        image = ""
        confidence = "none"
        exact = False
    else:
        owner = match.group("owner")
        repo_sha = match.group("repo_sha")
        image = f"programbench/{owner}_1776_{repo_sha}:task_cleanroom"
        status = "IMAGE_NAME_DERIVATION_WRITTEN"
        confidence = "high_for_name_only"
        exact = True
    return {
        "instance_id": instance_id,
        "derived_image_name": image,
        "tag": "task_cleanroom",
        "derivation_rule_used": "owner__repo.sha -> programbench/owner_1776_repo.sha:task_cleanroom",
        "confidence": confidence,
        "derived_exact": exact,
        "status": status,
        "image_digest": "",
        "artifact_authority_status": "ARTIFACT_AUTHORITY_INCONCLUSIVE",
        "cache_ready": False,
        "executable": False,
        "training_eligible": False,
        "evidence_refs": {"priority_record": _rel(PRIORITY_RECORD)},
    }


def classify_safe_manifest_lookup(
    *,
    image_name: str,
    provider: str = "docker_hub_official",
    metadata: dict[str, Any] | None = None,
    supported: bool = False,
    blocked_by_policy: bool = False,
) -> dict[str, Any]:
    if blocked_by_policy:
        return {
            "status": "SAFE_MANIFEST_LOOKUP_BLOCKED_BY_POLICY",
            "digest": "",
            "manifest_found": False,
        }
    if not supported:
        return {
            "status": "SAFE_MANIFEST_LOOKUP_NOT_SUPPORTED",
            "digest": "",
            "manifest_found": False,
        }
    metadata = metadata or {}
    digest = str(metadata.get("manifest_digest") or metadata.get("digest") or "")
    if digest.startswith("sha256:"):
        safe_summary = {
            "image_name": image_name,
            "provider": provider,
            "manifest_digest": digest,
            "metadata_hash": _hash_json(metadata),
        }
        return {
            "status": "SAFE_MANIFEST_LOOKUP_MANIFEST_FOUND",
            "digest": digest,
            "manifest_found": True,
            "safe_summary": safe_summary,
        }
    return {
        "status": "SAFE_MANIFEST_LOOKUP_MANIFEST_NOT_FOUND",
        "digest": "",
        "manifest_found": False,
    }


def _manifest_plan(row: dict[str, Any]) -> dict[str, Any]:
    image = str(row.get("derived_image_name") or "")
    status = (
        "EXACT_MANIFEST_METADATA_PLAN_WRITTEN"
        if image
        else "EXACT_MANIFEST_METADATA_PLAN_BLOCKED_NO_IMAGE_NAME"
    )
    return {
        "instance_id": row.get("instance_id", ""),
        "image_name": image,
        "tag": "task_cleanroom",
        "provider": "docker_hub_official",
        "required_operation": "exact manifest metadata lookup",
        "required_result": "immutable digest",
        "rejected_forms": [
            "latest",
            "name-only",
            "inferred officialness without manifest",
            "public-untrusted direct hydration",
        ],
        "next_gate_if_digest_found": "PROGRAMBENCH_BATCH001_MANIFEST_DIGEST_ADMISSION_LOCK_001",
        "status": status,
        "digest": "",
        "broad_search_allowed": False,
        "pull_or_run_allowed": False,
    }


def _admit_manifest_digest(row: dict[str, Any]) -> dict[str, Any]:
    digest = str(row.get("digest") or "")
    if not digest.startswith("sha256:"):
        status = "MANIFEST_DIGEST_ADMISSION_BLOCKED_NO_DIGEST"
        authority = "inconclusive"
    else:
        status = "MANIFEST_DIGEST_METADATA_ADMITTED"
        authority = "metadata_only_present"
    return {
        "instance_id": row.get("instance_id", ""),
        "image_name": row.get("image_name", ""),
        "digest": digest,
        "provider": row.get("provider", "docker_hub_official"),
        "exact_lookup_evidence_ref": _rel(SAFE_LOOKUP_RECORD),
        "artifact_authority_result": authority,
        "status": status,
        "cache_ready": False,
        "executable": False,
        "training_eligible": False,
    }


def _state_refresh_row(
    priority_row: dict[str, Any], admission: dict[str, Any] | None
) -> dict[str, Any]:
    after = {
        "artifact_authority_status": priority_row.get(
            "artifact_authority_status", "ARTIFACT_AUTHORITY_INCONCLUSIVE"
        ),
        "image_metadata_status": priority_row.get("image_metadata_status", "MISSING"),
        "image_name": priority_row.get("image_name", ""),
        "image_digest": priority_row.get("image_digest", ""),
        "scan_status": priority_row.get("scan_status", "SCAN_NOT_EVALUATED"),
        "security_policy_status": priority_row.get("policy_admission_requirement", "NOT_EVALUATED"),
        "execution_readiness": priority_row.get(
            "bounded_rerun_readiness", "BOUNDED_RERUN_NOT_REQUESTED"
        ),
        "next_unblocker": priority_row.get("next_unblocker", ""),
        "cache_ready": False,
        "executable": False,
        "training_eligible": priority_row.get("training_eligibility", "TRAINING_ELIGIBLE_FALSE"),
    }
    if admission:
        after.update(
            {
                "artifact_authority_status": "ARTIFACT_AUTHORITY_METADATA_ONLY_PRESENT",
                "image_metadata_status": "PRESENT",
                "image_name": admission.get("image_name", ""),
                "image_digest": admission.get("digest", ""),
                "next_unblocker": "ARTIFACT_IMPORT_AND_SCAN_REQUIREMENTS",
            }
        )
    before = {
        "artifact_authority_status": priority_row.get("artifact_authority_status", ""),
        "image_metadata_status": priority_row.get("image_metadata_status", ""),
        "image_name": priority_row.get("image_name", ""),
        "image_digest": priority_row.get("image_digest", ""),
        "next_unblocker": priority_row.get("next_unblocker", ""),
    }
    return {
        "instance_id": priority_row.get("instance_id", ""),
        "before_state": before,
        "after_state": after,
        "missing_fields_remaining": [] if admission else _missing_fields(priority_row),
        "changed": bool(admission),
    }


def _scan_requirement(admission: dict[str, Any]) -> dict[str, Any]:
    has_digest = bool(str(admission.get("digest") or "").startswith("sha256:"))
    return {
        "instance_id": admission.get("instance_id", ""),
        "image_name": admission.get("image_name", ""),
        "image_digest": admission.get("digest", ""),
        "local_artifact_import_required": has_digest,
        "scanner_required": has_digest,
        "approved_scanner_available": True,
        "scan_required_before_hydration_or_execution": has_digest,
        "policy_decision_required_if_scan_fails": has_digest,
        "current_status": "IMPORT_REQUIRED_BEFORE_SCAN"
        if has_digest
        else "SCAN_REQUIREMENTS_BLOCKED_NO_DIGEST",
        "status": "IMPORT_REQUIRED_BEFORE_SCAN"
        if has_digest
        else "SCAN_REQUIREMENTS_BLOCKED_NO_DIGEST",
        "import_authorized": False,
        "scan_executed": False,
        "execution_authorized": False,
    }


def _action(instance_id: str, action_type: str, blocking_status: str) -> dict[str, Any]:
    return {
        "instance_id": instance_id,
        "action_type": action_type,
        "blocking_status": blocking_status,
        "authorizes_execution": False,
        "training_eligible": False,
        "required_evidence": _required_evidence(action_type),
    }


def _required_evidence(action_type: str) -> list[str]:
    if action_type == "SUPPLY_SECURITY_POLICY_ADMISSION":
        return [
            "operator-signed policy admission bound to exact image, digest, scan, sandbox, and request"
        ]
    if action_type == "REQUEST_ARTIFACT_IMPORT_AND_SCAN_REVIEW":
        return [
            "metadata-only digest admission",
            "separate import authorization",
            "approved scanner evidence",
        ]
    return [
        "exact image reference",
        "immutable digest",
        "provider manifest metadata or admitted operator packet",
    ]


def _refreshed_priority(row: dict[str, Any]) -> dict[str, Any]:
    after = row.get("after_state", {})
    if row["instance_id"] == DOXYGEN_INSTANCE:
        difficulty = "HARD_POLICY_ADMISSION_REQUIRED"
        packet = "security_policy_admission"
    elif after.get("image_metadata_status") == "PRESENT":
        difficulty = "MODERATE_SCAN_REQUIRED"
        packet = "artifact_import_provenance_or_scanner_admission"
    else:
        difficulty = "EASY_METADATA_ONLY"
        packet = "image_metadata_submission"
    return {
        "instance_id": row["instance_id"],
        "image_name": after.get("image_name", ""),
        "image_digest": after.get("image_digest", ""),
        "image_metadata_status": after.get("image_metadata_status", "MISSING"),
        "artifact_authority_status": after.get("artifact_authority_status", ""),
        "scan_status": after.get("scan_status", ""),
        "security_policy_status": after.get("security_policy_status", ""),
        "next_unblocker": after.get("next_unblocker", ""),
        "estimated_difficulty": difficulty,
        "exact_operator_packet_needed": packet,
        "cache_ready": False,
        "executable": False,
        "training_eligible": False,
    }


def _doxygen_preserved(
    before_rows: list[dict[str, Any]], refresh_rows: list[dict[str, Any]]
) -> bool:
    before = next((row for row in before_rows if row.get("instance_id") == DOXYGEN_INSTANCE), {})
    after = next(
        (row for row in refresh_rows if row.get("instance_id") == DOXYGEN_INSTANCE), {}
    ).get("after_state", {})
    return (
        before.get("artifact_authority_status") == "ARTIFACT_AUTHORITY_PRESENT"
        and before.get("scan_status") == "CLEANROOM_IMAGE_SCAN_FAILED"
        and after.get("next_unblocker") == "OPERATOR_SECURITY_POLICY_ADMISSION"
        and after.get("executable") is False
    )


def _missing_fields(priority_row: dict[str, Any]) -> list[str]:
    if priority_row.get("instance_id") == DOXYGEN_INSTANCE:
        return ["operator security policy admission"]
    return ["image_name", "image_digest", "provider_manifest", "provenance"]


def _count_by(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        value = str(item.get(key, ""))
        counts[value] = counts.get(value, 0) + 1
    return counts


def _hash_json(data: dict[str, Any]) -> str:
    raw = json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


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
        description="Write Batch001 metadata campaign evidence records."
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)
    records = ProgramBenchBatch001MetadataCampaign(
        Batch001MetadataCampaignConfig(write_records=not args.no_write)
    ).run_all()
    if args.json:
        print(json.dumps(records, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
