#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from corpus.programbench.artifact_source_escalation_record import (
    make_artifact_source_escalation_record,
    write_artifact_source_escalation_record,
)
from corpus.programbench.infra_failure_triage import InfraFailureTriageStatus
from corpus.programbench.infra_failure_triage_record import verify_infra_failure_triage_record
from corpus.programbench.operator_artifact_admission import OperatorArtifactAdmissionStatus
from corpus.programbench.operator_artifact_admission_record import (
    verify_operator_artifact_admission_record,
)


class ArtifactSourceEscalationStatus(str, Enum):
    ARTIFACT_SOURCE_ESCALATION_READY = "ARTIFACT_SOURCE_ESCALATION_READY"
    ARTIFACT_SOURCE_ESCALATION_WRITTEN = "ARTIFACT_SOURCE_ESCALATION_WRITTEN"
    ARTIFACT_SOURCE_ESCALATION_BLOCKED_NO_TRIAGE = "ARTIFACT_SOURCE_ESCALATION_BLOCKED_NO_TRIAGE"
    ARTIFACT_SOURCE_ESCALATION_BLOCKED_NOT_OPERATOR_RECOVERY = (
        "ARTIFACT_SOURCE_ESCALATION_BLOCKED_NOT_OPERATOR_RECOVERY"
    )
    ARTIFACT_SOURCE_ESCALATION_NOT_REQUIRED_REAL_ADMISSION_EXISTS = (
        "ARTIFACT_SOURCE_ESCALATION_NOT_REQUIRED_REAL_ADMISSION_EXISTS"
    )
    MISSING_REAL_PROVENANCE = "MISSING_REAL_PROVENANCE"
    OPERATOR_CHECKLIST_GENERATED = "OPERATOR_CHECKLIST_GENERATED"
    FIXTURE_ADMISSION_IGNORED = "FIXTURE_ADMISSION_IGNORED"
    NO_HYDRATION_AUTHORIZED = "NO_HYDRATION_AUTHORIZED"
    NO_EXECUTION_AUTHORIZED = "NO_EXECUTION_AUTHORIZED"


REQUIRED_PROVENANCE_FIELDS = [
    "image_reference",
    "digest or immutable_revision",
    "source registry/source location",
    "tag",
    "license/provenance notes",
    "operator_id",
    "intended_scope.tool",
    "intended_scope.candidate_id",
    "related_triage_record",
    "admission_reason",
]

ACCEPTED_FORMS = [
    "local image tar with sha256 digest and source/provenance notes",
    "registry reference pinned by digest",
    "official ProgramBench build recipe with reproducible hash",
    "signed internal cache record",
]

REJECTED_FORMS = [
    "latest tag",
    "name-only image",
    "pulled from Docker Hub without digest/provenance",
    "unverified public image",
    "fixture admission record",
    "quarantine-only artifact",
]


@dataclass(slots=True)
class ArtifactSourceEscalationConfig:
    root: Path = Path(".")
    output_dir: Path = Path("assurance/evidence/programbench_artifact_source_escalations")
    admission_roots: list[Path] = field(
        default_factory=lambda: [
            Path("assurance/evidence/programbench_operator_artifact_admissions")
        ]
    )


class ProgramBenchArtifactSourceEscalation:
    def __init__(self, config: ArtifactSourceEscalationConfig | None = None) -> None:
        self.config = config or ArtifactSourceEscalationConfig()

    def escalate(self, triage_record_path: Path) -> dict[str, Any]:
        triage_path = self._resolve(triage_record_path)
        if not triage_path.is_file():
            return self._write_blocked(
                triage_path,
                {},
                [ArtifactSourceEscalationStatus.ARTIFACT_SOURCE_ESCALATION_BLOCKED_NO_TRIAGE.value],
            )
        triage = _read_json(triage_path)
        if not verify_infra_failure_triage_record(triage):
            return self._write_blocked(
                triage_path,
                triage,
                [ArtifactSourceEscalationStatus.ARTIFACT_SOURCE_ESCALATION_BLOCKED_NO_TRIAGE.value],
                ["triage_record_signature_invalid"],
            )
        if (
            str(triage.get("failure_type") or "")
            != InfraFailureTriageStatus.MISSING_CLEANROOM_IMAGE.value
        ):
            return self._write_blocked(
                triage_path,
                triage,
                [ArtifactSourceEscalationStatus.ARTIFACT_SOURCE_ESCALATION_BLOCKED_NO_TRIAGE.value],
                ["triage_failure_type_not_missing_cleanroom_image"],
            )
        if (
            str(triage.get("source_status") or "")
            != InfraFailureTriageStatus.IMAGE_RECOVERY_REQUIRES_OPERATOR.value
        ):
            return self._write_blocked(
                triage_path,
                triage,
                [
                    ArtifactSourceEscalationStatus.ARTIFACT_SOURCE_ESCALATION_BLOCKED_NOT_OPERATOR_RECOVERY.value
                ],
                ["triage_source_status_does_not_require_operator_recovery"],
            )

        admissions = self._find_admissions(str(triage.get("missing_image") or ""))
        real_admissions = [row for row in admissions if not _is_fixture_admission(row)]
        statuses = [
            ArtifactSourceEscalationStatus.ARTIFACT_SOURCE_ESCALATION_READY.value,
            ArtifactSourceEscalationStatus.OPERATOR_CHECKLIST_GENERATED.value,
            ArtifactSourceEscalationStatus.NO_HYDRATION_AUTHORIZED.value,
            ArtifactSourceEscalationStatus.NO_EXECUTION_AUTHORIZED.value,
        ]
        reasons: list[str] = []
        if real_admissions:
            statuses.append(
                ArtifactSourceEscalationStatus.ARTIFACT_SOURCE_ESCALATION_NOT_REQUIRED_REAL_ADMISSION_EXISTS.value
            )
            reasons.append("real_operator_admission_exists_use_hydration_gate_next")
        else:
            statuses.append(ArtifactSourceEscalationStatus.MISSING_REAL_PROVENANCE.value)
            reasons.append("no_real_operator_admission_found")
        if any(_is_fixture_admission(row) for row in admissions):
            statuses.append(ArtifactSourceEscalationStatus.FIXTURE_ADMISSION_IGNORED.value)
            reasons.append("fixture_admission_ignored_for_real_hydration")

        record = make_artifact_source_escalation_record(
            status=ArtifactSourceEscalationStatus.ARTIFACT_SOURCE_ESCALATION_WRITTEN.value,
            triage_record=_rel(self.config.root, triage_path),
            missing_image=str(triage.get("missing_image") or ""),
            target=dict(triage.get("target") or {}),
            escalation_statuses=statuses,
            required_provenance_fields=REQUIRED_PROVENANCE_FIELDS,
            accepted_forms=ACCEPTED_FORMS,
            rejected_forms=REJECTED_FORMS,
            operator_checklist=_operator_checklist(str(triage.get("missing_image") or ""), triage),
            discovered_admissions=[_compact_admission(row) for row in admissions],
            reasons=reasons,
            hydration_authorized=False,
            executable=False,
        )
        path = write_artifact_source_escalation_record(
            record, self._resolve(self.config.output_dir)
        )
        return {"record_path": str(path), "record": record}

    def _write_blocked(
        self,
        triage_path: Path,
        triage: dict[str, Any],
        statuses: list[str],
        reasons: list[str] | None = None,
    ) -> dict[str, Any]:
        record = make_artifact_source_escalation_record(
            status=statuses[0],
            triage_record=_rel(self.config.root, triage_path),
            missing_image=str(triage.get("missing_image") or ""),
            target=dict(triage.get("target") or {}),
            escalation_statuses=statuses
            + [
                ArtifactSourceEscalationStatus.NO_HYDRATION_AUTHORIZED.value,
                ArtifactSourceEscalationStatus.NO_EXECUTION_AUTHORIZED.value,
            ],
            reasons=reasons or [],
            hydration_authorized=False,
            executable=False,
        )
        path = write_artifact_source_escalation_record(
            record, self._resolve(self.config.output_dir)
        )
        return {"record_path": str(path), "record": record}

    def _find_admissions(self, image: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for root in self.config.admission_roots:
            resolved = self._resolve(root)
            if not resolved.exists():
                continue
            for path in sorted(resolved.rglob("*.json")):
                data = _read_json_silent(path)
                if not isinstance(data, dict):
                    continue
                if str(data.get("record_type") or "") != "programbench_operator_artifact_admission":
                    continue
                if str(data.get("image_reference") or "") != image:
                    continue
                if (
                    str(data.get("status") or "")
                    != OperatorArtifactAdmissionStatus.OPERATOR_ARTIFACT_ADMISSION_ACCEPTED.value
                ):
                    continue
                if verify_operator_artifact_admission_record(data):
                    out.append(data)
        return out

    def _resolve(self, path: Path) -> Path:
        return path if path.is_absolute() else self.config.root / path


def _operator_checklist(image: str, triage: dict[str, Any]) -> list[str]:
    target = triage.get("target") if isinstance(triage.get("target"), dict) else {}
    return [
        f"Supply exact image_reference: {image}",
        "Supply sha256 digest or immutable revision.",
        "Supply source registry/source location.",
        "Supply tag without relying on latest/floating semantics.",
        "Supply license/provenance notes.",
        f"Set intended_scope.tool to {target.get('tool', '')}.",
        f"Set intended_scope.candidate_id to {target.get('candidate_id', '')}.",
        f"Reference triage record: {triage.get('packet_id', '')}",
        "Run PROGRAMBENCH_OPERATOR_ARTIFACT_ADMISSION_LOCK_001 before hydration.",
    ]


def _is_fixture_admission(record: dict[str, Any]) -> bool:
    claim = record.get("operator_claim") if isinstance(record.get("operator_claim"), dict) else {}
    operator_id = str(claim.get("operator_id") or "")
    source = str(claim.get("source_url_or_registry") or "")
    reason = str(claim.get("admission_reason") or "").lower()
    notes = str(claim.get("license_provenance_notes") or "").lower()
    return (
        operator_id == "lock_fixture"
        or source.startswith("fixture://")
        or "fixture" in reason
        or "fixture" in notes
    )


def _compact_admission(record: dict[str, Any]) -> dict[str, Any]:
    claim = record.get("operator_claim") if isinstance(record.get("operator_claim"), dict) else {}
    return {
        "status": str(record.get("status") or ""),
        "image_reference": str(record.get("image_reference") or ""),
        "operator_id": str(claim.get("operator_id") or ""),
        "source_url_or_registry": str(claim.get("source_url_or_registry") or ""),
        "digest_present": bool(str(claim.get("digest") or "").startswith("sha256:")),
        "fixture": _is_fixture_admission(record),
        "hydration_candidate": bool(record.get("hydration_candidate")),
        "executable": bool(record.get("executable")),
        "training_eligible": bool(record.get("training_eligible")),
    }


def _read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    return data if isinstance(data, dict) else {}


def _read_json_silent(path: Path) -> dict[str, Any]:
    try:
        return _read_json(path)
    except Exception:
        return {}


def _rel(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate a ProgramBench artifact source escalation checklist."
    )
    parser.add_argument("triage_record", type=Path)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("assurance/evidence/programbench_artifact_source_escalations"),
    )
    args = parser.parse_args()
    result = ProgramBenchArtifactSourceEscalation(
        ArtifactSourceEscalationConfig(root=args.root, output_dir=args.output_dir)
    ).escalate(args.triage_record)
    print(json.dumps(result["record"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
