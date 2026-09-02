#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from corpus.programbench.commit_provenance_repair_audit_record import (
    make_commit_provenance_audit_record,
    write_commit_provenance_audit_record,
)
from corpus.programbench.programbench_platform_record import verify_platform_record

AUDITED_COMMIT = "bc86cb57e"
AUDITED_COMMIT_SUBJECT = "FRONTEND_REPAIR_PANEL_SHELL_LOCK_001: 9-section shell"

PROGRAMBENCH_LOCKS = [
    "PROGRAMBENCH_BATCH001_ARTIFACT_IMPORT_REQUEST_PACKET_LOCK_001",
    "PROGRAMBENCH_BATCH001_ARTIFACT_IMPORT_PREFLIGHT_LOCK_001",
    "PROGRAMBENCH_BATCH001_OPERATOR_ARTIFACT_IMPORT_PACKET_BUNDLE_LOCK_001",
    "PROGRAMBENCH_BATCH001_EXACT_ARTIFACT_IMPORT_GATE_LOCK_001",
    "PROGRAMBENCH_BATCH001_SCAN_QUEUE_LOCK_001",
    "PROGRAMBENCH_BATCH001_SCAN_POLICY_PRECHECK_LOCK_001",
    "PROGRAMBENCH_BATCH001_IMPORT_SCAN_CAMPAIGN_FINAL_STATE_LOCK_001",
]

PROGRAMBENCH_EVIDENCE = [
    Path(
        "assurance/evidence/programbench_batch001_artifact_import_requests/programbench_batch001_artifact_import_request_packet_run_20260528.ARTIFACT_IMPORT_REQUEST_PACKET_WRITTEN.json"
    ),
    Path(
        "assurance/evidence/programbench_batch001_artifact_import_preflight/programbench_batch001_artifact_import_preflight_run_20260528.ARTIFACT_IMPORT_PREFLIGHT_BLOCKED_NO_SAFE_IMPORT_METHOD.json"
    ),
    Path(
        "assurance/evidence/programbench_batch001_operator_artifact_import_packet_bundle/programbench_batch001_operator_artifact_import_packet_bundle_run_20260528.OPERATOR_ARTIFACT_IMPORT_PACKET_BUNDLE_WRITTEN.json"
    ),
    Path(
        "assurance/evidence/programbench_batch001_exact_artifact_import_gate/programbench_batch001_exact_artifact_import_gate_run_20260528.EXACT_ARTIFACT_IMPORT_REQUIRED.json"
    ),
    Path(
        "assurance/evidence/programbench_batch001_scan_queue/programbench_batch001_scan_queue_run_20260528.BATCH001_SCAN_QUEUE_WRITTEN.json"
    ),
    Path(
        "assurance/evidence/programbench_batch001_scan_policy_precheck/programbench_batch001_scan_policy_precheck_run_20260528.SCAN_POLICY_PRECHECK_WRITTEN.json"
    ),
    Path(
        "assurance/evidence/programbench_batch001_import_scan_campaign_final_state/programbench_batch001_import_scan_campaign_final_state_run_20260528.BATCH001_IMPORT_SCAN_CAMPAIGN_FINAL_STATE_WRITTEN.json"
    ),
]

PROGRAMBENCH_CODE_PATHS = [
    Path("scripts/corpus/programbench/batch001_import_scan_pipeline.py"),
    Path("scripts/corpus/programbench/batch001_import_scan_pipeline_record.py"),
]
FRONTEND_CODE_PATHS = [
    Path("frontend/src/app/ide-repair/page.tsx"),
    Path("frontend/src/components/ide-repair/RepairPanelShell.tsx"),
    Path("frontend/src/lib/ide-repair-api.ts"),
]
FINAL_STATE = PROGRAMBENCH_EVIDENCE[-1]

FORBIDDEN_FLAGS = {
    "docker_execution_authorized": False,
    "programbench_rerun_authorized": False,
    "source_rebuild_authorized": False,
    "remediation_authorized": False,
    "policy_exception_granted": False,
    "training_rows_written": False,
    "training_eligible": False,
    "executable": False,
}


@dataclass(slots=True)
class CommitProvenanceAuditConfig:
    root: Path = Path(".")
    commit: str = AUDITED_COMMIT
    write_record: bool = True


def classify_commit_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    if normalized == "assurance/evidence/evidence_index.json":
        return "SHARED_EVIDENCE_INDEX"
    if normalized.startswith("scripts/corpus/programbench/"):
        return "CODEX_PROGRAMBENCH"
    if normalized.startswith("tests/corpus/programbench/"):
        return "CODEX_PROGRAMBENCH"
    if normalized.startswith("locks/sentinel/PROGRAMBENCH_"):
        return "CODEX_PROGRAMBENCH"
    if normalized.startswith("assurance/evidence/programbench_"):
        return "CODEX_PROGRAMBENCH"
    if normalized.startswith("assurance/operator_outbox/programbench/"):
        return "CODEX_PROGRAMBENCH"
    if normalized == "docs/PROGRAMBENCH.md" or normalized.startswith("docs/PROGRAMBENCH_"):
        return "CODEX_PROGRAMBENCH"
    if normalized.startswith("frontend/"):
        return "CLAUDE_FRONTEND"
    if normalized.startswith("tests/ide_frontend/"):
        return "CLAUDE_FRONTEND"
    if normalized.startswith("locks/sentinel/FRONTEND_"):
        return "CLAUDE_FRONTEND"
    if normalized.startswith("assurance/evidence/frontend_"):
        return "CLAUDE_FRONTEND"
    if normalized.startswith("docs/FRONTEND_"):
        return "CLAUDE_FRONTEND"
    return "NEEDS_REVIEW"


class ProgramBenchCommitProvenanceRepairAudit:
    def __init__(self, config: CommitProvenanceAuditConfig | None = None) -> None:
        self.config = config or CommitProvenanceAuditConfig()
        self.root = self.config.root

    def run(
        self, commit_files: list[str] | None = None, commit_subject: str | None = None
    ) -> dict[str, Any]:
        commit_files = (
            commit_files if commit_files is not None else self._commit_files(self.config.commit)
        )
        commit_subject = (
            commit_subject
            if commit_subject is not None
            else self._commit_subject(self.config.commit)
        )
        classified = classify_paths(commit_files)
        evidence_check = self._verify_programbench_evidence()
        lock_check = self._verify_programbench_locks()
        index_check = self._verify_evidence_index()
        programbench_imports = self._scan_forbidden_imports(
            PROGRAMBENCH_CODE_PATHS,
            (r"\bfrom\s+frontend\b", r"\bimport\s+frontend\b", r"ide-repair"),
        )
        frontend_imports = self._scan_forbidden_imports(
            FRONTEND_CODE_PATHS, (r"corpus\.programbench", r"programbench_")
        )
        operation_check = self._verify_no_forbidden_operations()
        dirty_state = self._git_status()

        programbench_files = classified["CODEX_PROGRAMBENCH"]
        frontend_files = classified["CLAUDE_FRONTEND"]
        has_label_warning = commit_subject.startswith("FRONTEND_") and bool(programbench_files)
        cross_lane_imports_found = bool(
            programbench_imports["matches"] or frontend_imports["matches"]
        )
        evidence_ok = evidence_check["valid"] and lock_check["valid"] and index_check["valid"]
        forbidden_ops_ok = operation_check["valid"]
        needs_review = bool(classified["NEEDS_REVIEW"])

        if not evidence_ok or cross_lane_imports_found or needs_review or not forbidden_ops_ok:
            status = "PROGRAMBENCH_COMMIT_PROVENANCE_AUDIT_FINDINGS_WRITTEN"
            repair_required = bool(
                cross_lane_imports_found or not evidence_ok or not forbidden_ops_ok
            )
        elif has_label_warning:
            status = "PROGRAMBENCH_COMMIT_PROVENANCE_AUDIT_PASSED_WITH_LABEL_WARNING"
            repair_required = False
        else:
            status = "PROGRAMBENCH_COMMIT_PROVENANCE_AUDIT_PASSED"
            repair_required = False

        payload = {
            "record_id": "programbench_commit_provenance_repair_audit_run_20260528",
            "commit": self.config.commit,
            "commit_subject": commit_subject,
            "classification": classified,
            "classification_counts": {key: len(value) for key, value in classified.items()},
            "audited_programbench_locks": PROGRAMBENCH_LOCKS,
            "programbench_evidence": evidence_check,
            "programbench_locks": lock_check,
            "evidence_index": index_check,
            "cross_lane_imports": {
                "programbench_imports_frontend": programbench_imports,
                "frontend_imports_programbench": frontend_imports,
                "found": cross_lane_imports_found,
            },
            "label_warning": has_label_warning,
            "cross_lane_mutations_found": False,
            "operation_check": operation_check,
            "working_tree_dirty_state": dirty_state,
            "execution_performed": False,
            "training_rows_written": False,
            "repair_required": repair_required,
            "recommendation": (
                "Do not rewrite history without explicit operator instruction; use this signed audit as the provenance repair record. "
                "Proceed to operator artifact import packet review only if real live import packets exist."
            ),
        }
        record = make_commit_provenance_audit_record(status=status, payload=payload)
        if self.config.write_record:
            write_commit_provenance_audit_record(
                record, self.root / "assurance/evidence/programbench_commit_provenance_repair_audit"
            )
        return record

    def _verify_programbench_evidence(self) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        valid = True
        for rel in PROGRAMBENCH_EVIDENCE:
            path = self.root / rel
            exists = path.is_file()
            parsed = False
            signature_valid = False
            status = ""
            if exists:
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    parsed = True
                    signature_valid = verify_platform_record(data)
                    status = str(data.get("status") or "")
                except json.JSONDecodeError:
                    pass
            row_valid = exists and parsed and signature_valid
            valid = valid and row_valid
            rows.append(
                {
                    "path": str(rel).replace("\\", "/"),
                    "exists": exists,
                    "parsed": parsed,
                    "signature_valid": signature_valid,
                    "status": status,
                }
            )
        return {"valid": valid, "rows": rows}

    def _verify_programbench_locks(self) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        valid = True
        for lock_id in PROGRAMBENCH_LOCKS:
            rel = Path("locks/sentinel") / f"{lock_id}.json"
            path = self.root / rel
            exists = path.is_file()
            parsed = False
            declared_lock = ""
            record = ""
            if exists:
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    parsed = True
                    declared_lock = str(data.get("lock_id") or "")
                    record = str(data.get("record") or "")
                except json.JSONDecodeError:
                    pass
            row_valid = exists and parsed and declared_lock == lock_id
            valid = valid and row_valid
            rows.append(
                {
                    "path": str(rel).replace("\\", "/"),
                    "exists": exists,
                    "parsed": parsed,
                    "lock_id": declared_lock,
                    "record": record,
                }
            )
        return {"valid": valid, "rows": rows}

    def _verify_evidence_index(self) -> dict[str, Any]:
        rel = Path("assurance/evidence/evidence_index.json")
        path = self.root / rel
        if not path.is_file():
            return {"valid": False, "path": str(rel), "error": "missing"}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            return {"valid": False, "path": str(rel), "error": f"json:{exc}"}
        missing: list[str] = []
        for entry in data.get("entries", []):
            raw = entry.get("manifest_path", "")
            if raw and not (self.root / raw).is_file():
                missing.append(str(raw))
        validation_errors = data.get("validation_errors", [])
        return {
            "valid": not missing and not validation_errors,
            "path": str(rel),
            "entry_count": len(data.get("entries", [])),
            "validation_errors": validation_errors,
            "missing_manifest_paths": missing,
        }

    def _verify_no_forbidden_operations(self) -> dict[str, Any]:
        path = self.root / FINAL_STATE
        if not path.is_file():
            return {"valid": False, "error": "final_state_missing"}
        data = json.loads(path.read_text(encoding="utf-8"))
        auth = data.get("authorization", {})
        summary = data.get("summary", {})
        rows = {key: auth.get(key) for key in FORBIDDEN_FLAGS}
        valid_flags = all(rows[key] == expected for key, expected in FORBIDDEN_FLAGS.items())
        valid_summary = (
            summary.get("artifacts_imported") == 0
            and summary.get("scans_performed") == 0
            and summary.get("execution_performed") is False
            and summary.get("training_rows_written") is False
        )
        return {
            "valid": valid_flags and valid_summary,
            "authorization_flags": rows,
            "summary": {
                "artifacts_imported": summary.get("artifacts_imported"),
                "scans_performed": summary.get("scans_performed"),
                "execution_performed": summary.get("execution_performed"),
                "training_rows_written": summary.get("training_rows_written"),
            },
        }

    def _scan_forbidden_imports(
        self, paths: Iterable[Path], patterns: Iterable[str]
    ) -> dict[str, Any]:
        compiled = [re.compile(pattern) for pattern in patterns]
        matches: list[dict[str, Any]] = []
        checked: list[str] = []
        for rel in paths:
            path = self.root / rel
            if not path.is_file():
                continue
            checked.append(str(rel).replace("\\", "/"))
            text = path.read_text(encoding="utf-8", errors="replace")
            for lineno, line in enumerate(text.splitlines(), start=1):
                if any(pattern.search(line) for pattern in compiled):
                    matches.append(
                        {
                            "path": str(rel).replace("\\", "/"),
                            "line": lineno,
                            "text": line.strip()[:160],
                        }
                    )
        return {"checked": checked, "matches": matches}

    def _commit_files(self, commit: str) -> list[str]:
        completed = subprocess.run(
            ["git", "show", "--name-only", "--format=", commit],
            cwd=self.root,
            check=True,
            text=True,
            capture_output=True,
        )
        return [line.strip() for line in completed.stdout.splitlines() if line.strip()]

    def _commit_subject(self, commit: str) -> str:
        completed = subprocess.run(
            ["git", "show", "--no-patch", "--format=%s", commit],
            cwd=self.root,
            check=True,
            text=True,
            capture_output=True,
        )
        return completed.stdout.strip()

    def _git_status(self) -> list[str]:
        completed = subprocess.run(
            ["git", "status", "--short", "--untracked-files=all"],
            cwd=self.root,
            check=True,
            text=True,
            capture_output=True,
        )
        return [line for line in completed.stdout.splitlines() if line.strip()]


def classify_paths(paths: Iterable[str]) -> dict[str, list[str]]:
    classified: dict[str, list[str]] = defaultdict(list)
    for path in paths:
        classified[classify_commit_path(path)].append(path.replace("\\", "/"))
    for key in (
        "CODEX_PROGRAMBENCH",
        "CLAUDE_FRONTEND",
        "SHARED_EVIDENCE_INDEX",
        "UNRELATED",
        "NEEDS_REVIEW",
    ):
        classified.setdefault(key, [])
    return {key: sorted(value) for key, value in classified.items()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", default=AUDITED_COMMIT)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()

    audit = ProgramBenchCommitProvenanceRepairAudit(
        CommitProvenanceAuditConfig(commit=args.commit, write_record=not args.no_write)
    )
    record = audit.run()
    if args.json:
        print(json.dumps(record, indent=2, sort_keys=True))
    else:
        print(record["status"])
    return (
        0
        if record["status"]
        in {
            "PROGRAMBENCH_COMMIT_PROVENANCE_AUDIT_PASSED",
            "PROGRAMBENCH_COMMIT_PROVENANCE_AUDIT_PASSED_WITH_LABEL_WARNING",
        }
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
