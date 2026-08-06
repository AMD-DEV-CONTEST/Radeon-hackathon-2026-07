from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence

from .gtm_all_subvertical_unified_review_v2 import validate_unified_review_intake
from .gtm_buffer_candidate_admission_v2 import (
    compile_buffer_candidate_admission,
    verify_buffer_candidate_admission,
)
from .gtm_emailoctopus_candidate_admission_v2 import (
    compile_emailoctopus_candidate_admission,
    verify_emailoctopus_candidate_admission,
)
from .gtm_flodesk_candidate_admission_v2 import (
    compile_flodesk_candidate_admission,
    verify_flodesk_candidate_admission,
)
from .gtm_postbridge_candidate_admission_v2 import (
    compile_postbridge_candidate_admission,
    verify_postbridge_candidate_admission,
)


SCHEMA = "ProofLaunchGTMFourCaseBatchAdmissionV2"


class GTMFourCaseBatchAdmissionError(ValueError):
    pass


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def compile_four_case_batch_admission(
    intake: Mapping[str, Any],
    ledger: Mapping[str, Any],
    dossiers: Mapping[str, Mapping[str, Any]],
    proposals: Mapping[str, Mapping[str, Any]],
    existing_candidates: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    validate_unified_review_intake(intake, ledger)
    specs = (
        ("EmailOctopus", compile_emailoctopus_candidate_admission, verify_emailoctopus_candidate_admission),
        ("Buffer", compile_buffer_candidate_admission, verify_buffer_candidate_admission),
        ("Flodesk", compile_flodesk_candidate_admission, verify_flodesk_candidate_admission),
        ("Post Bridge", compile_postbridge_candidate_admission, verify_postbridge_candidate_admission),
    )
    if set(dossiers) != {row[0] for row in specs} or set(proposals) != {row[0] for row in specs}:
        raise GTMFourCaseBatchAdmissionError("the four-case evidence set is incomplete")
    records = intake.get("records", [])
    expected_packet_ids = {proposals[name]["review_packet_id"] for name, _, _ in specs}
    observed_packet_ids = {row.get("review_packet_id") for row in records}
    if len(records) != 4 or observed_packet_ids != expected_packet_ids:
        raise GTMFourCaseBatchAdmissionError("batch intake must contain exactly the four bound review packets")

    staged = list(existing_candidates)
    admissions: list[dict[str, Any]] = []
    for company, compiler, verifier in specs:
        proposal = proposals[company]
        record = next(row for row in records if row["review_packet_id"] == proposal["review_packet_id"])
        single_intake = {
            "schema": intake["schema"],
            "review_ledger_sha256": intake["review_ledger_sha256"],
            "created_at": intake["created_at"],
            "review_count": 1,
            "records": [record],
            "automatic_promotion_allowed": False,
            "formal_candidate_quota_credit": 0,
        }
        admission = compiler(single_intake, ledger, dossiers[company], proposal, staged)
        verifier(admission)
        staged.append(admission["candidate"])
        admissions.append(admission)

    payload = {
        "schema": SCHEMA,
        "source_batch_intake_sha256": _digest(intake),
        "candidate_count": len(admissions),
        "formal_candidate_quota_credit": sum(row["formal_candidate_quota_credit"] for row in admissions),
        "reviewer_names": sorted({row["reviewer_name"] for row in admissions}),
        "admissions": admissions,
        "truth_boundary": (
            "All four named-human records and all four case-specific admission contracts passed before any registry "
            "write. This receipt grants four credits only when the caller atomically commits all four candidates."
        ),
    }
    payload["content_sha256"] = _digest(payload)
    return payload


def verify_four_case_batch_admission(payload: Mapping[str, Any]) -> None:
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if payload.get("schema") != SCHEMA or supplied != _digest(unsigned):
        raise GTMFourCaseBatchAdmissionError("four-case batch admission seal is invalid")
    admissions = payload.get("admissions")
    if not isinstance(admissions, list) or len(admissions) != 4:
        raise GTMFourCaseBatchAdmissionError("four-case batch admission count drifted")
    if payload.get("candidate_count") != 4 or payload.get("formal_candidate_quota_credit") != 4:
        raise GTMFourCaseBatchAdmissionError("four-case batch quota credit drifted")
    verifiers = {
        "ProofLaunchGTMEmailOctopusCaseCandidateAdmissionV2": verify_emailoctopus_candidate_admission,
        "ProofLaunchGTMBufferCaseCandidateAdmissionV2": verify_buffer_candidate_admission,
        "ProofLaunchGTMFlodeskCaseCandidateAdmissionV2": verify_flodesk_candidate_admission,
        "ProofLaunchGTMPostBridgeCaseCandidateAdmissionV2": verify_postbridge_candidate_admission,
    }
    schemas = [row.get("schema") for row in admissions]
    if set(schemas) != set(verifiers):
        raise GTMFourCaseBatchAdmissionError("four-case batch contains the wrong admission set")
    for admission in admissions:
        verifiers[admission["schema"]](admission)


__all__ = [
    "GTMFourCaseBatchAdmissionError",
    "compile_four_case_batch_admission",
    "verify_four_case_batch_admission",
]
