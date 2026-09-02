#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from corpus.programbench.infra_failure_triage import InfraFailureTriageStatus
from corpus.programbench.infra_failure_triage_record import verify_infra_failure_triage_record
from corpus.programbench.operator_artifact_admission_record import (
    make_operator_artifact_admission_record,
    write_operator_artifact_admission_record,
)


class OperatorArtifactAdmissionStatus(str, Enum):
    OPERATOR_ARTIFACT_ADMISSION_READY = "OPERATOR_ARTIFACT_ADMISSION_READY"
    OPERATOR_ARTIFACT_ADMISSION_ACCEPTED = "OPERATOR_ARTIFACT_ADMISSION_ACCEPTED"
    OPERATOR_ARTIFACT_ADMISSION_REJECTED = "OPERATOR_ARTIFACT_ADMISSION_REJECTED"
    OPERATOR_ARTIFACT_BLOCKED_NO_TRIAGE = "OPERATOR_ARTIFACT_BLOCKED_NO_TRIAGE"
    OPERATOR_ARTIFACT_BLOCKED_SCOPE_MISMATCH = "OPERATOR_ARTIFACT_BLOCKED_SCOPE_MISMATCH"
    OPERATOR_ARTIFACT_BLOCKED_IMAGE_MISMATCH = "OPERATOR_ARTIFACT_BLOCKED_IMAGE_MISMATCH"
    OPERATOR_ARTIFACT_BLOCKED_NO_DIGEST = "OPERATOR_ARTIFACT_BLOCKED_NO_DIGEST"
    OPERATOR_ARTIFACT_BLOCKED_FLOATING_TAG = "OPERATOR_ARTIFACT_BLOCKED_FLOATING_TAG"
    OPERATOR_ARTIFACT_BLOCKED_NO_PROVENANCE = "OPERATOR_ARTIFACT_BLOCKED_NO_PROVENANCE"
    OPERATOR_ARTIFACT_BLOCKED_PUBLIC_UNTRUSTED_DIRECT_HYDRATION = (
        "OPERATOR_ARTIFACT_BLOCKED_PUBLIC_UNTRUSTED_DIRECT_HYDRATION"
    )
    OPERATOR_ARTIFACT_HYDRATION_CANDIDATE = "OPERATOR_ARTIFACT_HYDRATION_CANDIDATE"
    OPERATOR_ARTIFACT_NOT_EXECUTABLE = "OPERATOR_ARTIFACT_NOT_EXECUTABLE"


REQUIRED_CLAIM_FIELDS = (
    "image_reference",
    "source_type",
    "source_url_or_registry",
    "tag",
    "operator_id",
    "intended_scope",
    "related_triage_record",
    "admission_reason",
)


@dataclass(slots=True)
class OperatorArtifactAdmissionConfig:
    root: Path = Path(".")
    output_dir: Path = Path("assurance/evidence/programbench_operator_artifact_admissions")


class ProgramBenchOperatorArtifactAdmission:
    def __init__(self, config: OperatorArtifactAdmissionConfig | None = None) -> None:
        self.config = config or OperatorArtifactAdmissionConfig()

    def admit(self, triage_record_path: Path, operator_claim: dict[str, Any]) -> dict[str, Any]:
        triage_path = self._resolve(triage_record_path)
        if not triage_path.is_file():
            return self._write_blocked(
                OperatorArtifactAdmissionStatus.OPERATOR_ARTIFACT_BLOCKED_NO_TRIAGE.value,
                triage_path,
                {},
                operator_claim,
                ["triage_record_missing"],
            )
        triage = _read_json(triage_path)
        if not verify_infra_failure_triage_record(triage):
            return self._write_blocked(
                OperatorArtifactAdmissionStatus.OPERATOR_ARTIFACT_BLOCKED_NO_TRIAGE.value,
                triage_path,
                triage,
                operator_claim,
                ["triage_record_signature_invalid"],
            )
        if (
            str(triage.get("failure_type") or "")
            != InfraFailureTriageStatus.MISSING_CLEANROOM_IMAGE.value
        ):
            return self._write_blocked(
                OperatorArtifactAdmissionStatus.OPERATOR_ARTIFACT_BLOCKED_NO_TRIAGE.value,
                triage_path,
                triage,
                operator_claim,
                ["triage_failure_type_not_missing_cleanroom_image"],
            )
        if (
            str(triage.get("source_status") or "")
            != InfraFailureTriageStatus.IMAGE_RECOVERY_REQUIRES_OPERATOR.value
        ):
            return self._write_blocked(
                OperatorArtifactAdmissionStatus.OPERATOR_ARTIFACT_BLOCKED_NO_TRIAGE.value,
                triage_path,
                triage,
                operator_claim,
                ["triage_source_status_does_not_require_operator_recovery"],
            )

        missing = [field for field in REQUIRED_CLAIM_FIELDS if not operator_claim.get(field)]
        if missing:
            return self._write_blocked(
                OperatorArtifactAdmissionStatus.OPERATOR_ARTIFACT_BLOCKED_NO_PROVENANCE.value,
                triage_path,
                triage,
                operator_claim,
                [f"missing_required_claim_field:{field}" for field in missing],
            )

        image = str(triage.get("missing_image") or "")
        if str(operator_claim.get("image_reference") or "") != image:
            return self._write_blocked(
                OperatorArtifactAdmissionStatus.OPERATOR_ARTIFACT_BLOCKED_IMAGE_MISMATCH.value,
                triage_path,
                triage,
                operator_claim,
                ["operator_image_reference_does_not_match_triage_missing_image"],
            )

        if not _scope_matches(triage, operator_claim):
            return self._write_blocked(
                OperatorArtifactAdmissionStatus.OPERATOR_ARTIFACT_BLOCKED_SCOPE_MISMATCH.value,
                triage_path,
                triage,
                operator_claim,
                ["operator_intended_scope_does_not_match_authorized_triage_scope"],
            )

        tag = str(operator_claim.get("tag") or "")
        digest = str(operator_claim.get("digest") or "")
        revision = str(operator_claim.get("immutable_revision") or "")
        if _is_floating_tag(tag) and not digest:
            return self._write_blocked(
                OperatorArtifactAdmissionStatus.OPERATOR_ARTIFACT_BLOCKED_FLOATING_TAG.value,
                triage_path,
                triage,
                operator_claim,
                ["floating_tag_without_digest_blocked"],
            )
        if not _has_pin(digest, revision):
            return self._write_blocked(
                OperatorArtifactAdmissionStatus.OPERATOR_ARTIFACT_BLOCKED_NO_DIGEST.value,
                triage_path,
                triage,
                operator_claim,
                ["sha256_digest_or_immutable_revision_required"],
            )
        if not _has_provenance(operator_claim):
            return self._write_blocked(
                OperatorArtifactAdmissionStatus.OPERATOR_ARTIFACT_BLOCKED_NO_PROVENANCE.value,
                triage_path,
                triage,
                operator_claim,
                ["license_or_provenance_notes_required"],
            )
        if _public_untrusted_direct_hydration(operator_claim):
            return self._write_blocked(
                OperatorArtifactAdmissionStatus.OPERATOR_ARTIFACT_BLOCKED_PUBLIC_UNTRUSTED_DIRECT_HYDRATION.value,
                triage_path,
                triage,
                operator_claim,
                ["public_untrusted_direct_hydration_blocked"],
            )

        record = make_operator_artifact_admission_record(
            status=OperatorArtifactAdmissionStatus.OPERATOR_ARTIFACT_ADMISSION_ACCEPTED.value,
            triage_record=_rel(self.config.root, triage_path),
            image_reference=image,
            target=dict(triage.get("target") or {}),
            admission_statuses=[
                OperatorArtifactAdmissionStatus.OPERATOR_ARTIFACT_ADMISSION_READY.value,
                OperatorArtifactAdmissionStatus.OPERATOR_ARTIFACT_ADMISSION_ACCEPTED.value,
                OperatorArtifactAdmissionStatus.OPERATOR_ARTIFACT_HYDRATION_CANDIDATE.value,
                OperatorArtifactAdmissionStatus.OPERATOR_ARTIFACT_NOT_EXECUTABLE.value,
            ],
            operator_claim=_normalize_claim(operator_claim),
            reasons=[],
            hydration_candidate=True,
            executable=False,
        )
        path = write_operator_artifact_admission_record(
            record, self._resolve(self.config.output_dir)
        )
        return {"record_path": str(path), "record": record}

    def _write_blocked(
        self,
        status: str,
        triage_path: Path,
        triage: dict[str, Any],
        operator_claim: dict[str, Any],
        reasons: list[str],
    ) -> dict[str, Any]:
        record = make_operator_artifact_admission_record(
            status=status,
            triage_record=_rel(self.config.root, triage_path),
            image_reference=str(
                operator_claim.get("image_reference") or triage.get("missing_image") or ""
            ),
            target=dict(triage.get("target") or {}),
            admission_statuses=[
                OperatorArtifactAdmissionStatus.OPERATOR_ARTIFACT_ADMISSION_REJECTED.value,
                status,
                OperatorArtifactAdmissionStatus.OPERATOR_ARTIFACT_NOT_EXECUTABLE.value,
            ],
            operator_claim=_normalize_claim(operator_claim),
            reasons=reasons,
            hydration_candidate=False,
            executable=False,
        )
        path = write_operator_artifact_admission_record(
            record, self._resolve(self.config.output_dir)
        )
        return {"record_path": str(path), "record": record}

    def _resolve(self, path: Path) -> Path:
        return path if path.is_absolute() else self.config.root / path


def _scope_matches(triage: dict[str, Any], claim: dict[str, Any]) -> bool:
    target = triage.get("target") if isinstance(triage.get("target"), dict) else {}
    intended = claim.get("intended_scope") if isinstance(claim.get("intended_scope"), dict) else {}
    for key in ("tool", "candidate_id"):
        if str(intended.get(key) or "") != str(target.get(key) or ""):
            return False
    rerun_scope = (
        triage.get("evidence", {}).get("rerun_scope")
        if isinstance(triage.get("evidence"), dict)
        else {}
    )
    if isinstance(rerun_scope, dict) and intended.get("max_attempts") is not None:
        return int(intended.get("max_attempts") or 0) == int(rerun_scope.get("max_attempts") or 0)
    return True


def _is_floating_tag(tag: str) -> bool:
    return tag.strip().lower() in {"latest", "main", "master", ""}


def _has_pin(digest: str, revision: str) -> bool:
    if digest.startswith("sha256:") and len(digest) > len("sha256:"):
        return True
    return bool(revision and revision not in {"main", "master", "latest"} and len(revision) >= 7)


def _has_provenance(claim: dict[str, Any]) -> bool:
    return bool(
        str(claim.get("license_provenance_notes") or "").strip()
        or str(claim.get("provenance_notes") or "").strip()
    )


def _public_untrusted_direct_hydration(claim: dict[str, Any]) -> bool:
    source_type = str(claim.get("source_type") or "").lower()
    trust_level = str(claim.get("trust_level") or "").lower()
    requested_use = str(claim.get("requested_use") or "").lower()
    if source_type != "public_untrusted" and trust_level != "public_untrusted":
        return False
    return requested_use in {"direct_hydration", "hydration_ready", "execute"} or bool(
        claim.get("direct_hydration")
    )


def _normalize_claim(claim: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "image_reference",
        "source_type",
        "source_url_or_registry",
        "digest",
        "immutable_revision",
        "tag",
        "created_at_or_published_at",
        "license_provenance_notes",
        "provenance_notes",
        "operator_id",
        "intended_scope",
        "related_triage_record",
        "admission_reason",
        "trust_level",
        "requested_use",
        "direct_hydration",
    }
    return {key: claim.get(key) for key in sorted(allowed) if key in claim}


def _read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    return data if isinstance(data, dict) else {}


def _rel(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Admit operator-supplied ProgramBench artifact provenance."
    )
    parser.add_argument("triage_record", type=Path)
    parser.add_argument("operator_claim", type=Path)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("assurance/evidence/programbench_operator_artifact_admissions"),
    )
    args = parser.parse_args()
    claim = _read_json(args.operator_claim)
    result = ProgramBenchOperatorArtifactAdmission(
        OperatorArtifactAdmissionConfig(root=args.root, output_dir=args.output_dir)
    ).admit(args.triage_record, claim)
    print(json.dumps(result["record"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
