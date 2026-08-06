from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence

from .gtm_all_subvertical_unified_review_v2 import validate_unified_review_intake
from .gtm_barn2_candidate_admission_v2 import compile_barn2_candidate_admission, verify_barn2_candidate_admission
from .gtm_buffer_candidate_admission_v2 import compile_buffer_candidate_admission, verify_buffer_candidate_admission
from .gtm_emailoctopus_candidate_admission_v2 import compile_emailoctopus_candidate_admission, verify_emailoctopus_candidate_admission
from .gtm_flodesk_candidate_admission_v2 import compile_flodesk_candidate_admission, verify_flodesk_candidate_admission
from .gtm_parqet_candidate_admission_v2 import compile_parqet_candidate_admission, verify_parqet_candidate_admission
from .gtm_postbridge_candidate_admission_v2 import compile_postbridge_candidate_admission, verify_postbridge_candidate_admission
from .gtm_spendbase_candidate_admission_v2 import compile_spendbase_candidate_admission, verify_spendbase_candidate_admission


SCHEMA = "ProofLaunchGTMSevenCaseBatchAdmissionV2"


class GTMSevenCaseBatchAdmissionError(ValueError):
    pass


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


SPECS = (
    ("EmailOctopus", compile_emailoctopus_candidate_admission, verify_emailoctopus_candidate_admission),
    ("Buffer", compile_buffer_candidate_admission, verify_buffer_candidate_admission),
    ("Flodesk", compile_flodesk_candidate_admission, verify_flodesk_candidate_admission),
    ("Post Bridge", compile_postbridge_candidate_admission, verify_postbridge_candidate_admission),
    ("Parqet", compile_parqet_candidate_admission, verify_parqet_candidate_admission),
    ("Spendbase", compile_spendbase_candidate_admission, verify_spendbase_candidate_admission),
    ("Barn2", compile_barn2_candidate_admission, verify_barn2_candidate_admission),
)


def compile_seven_case_batch_admission(intake: Mapping[str, Any], ledger: Mapping[str, Any], dossiers: Mapping[str, Mapping[str, Any]], proposals: Mapping[str, Mapping[str, Any]], existing_candidates: Sequence[Mapping[str, Any]] = ()) -> dict[str, Any]:
    validate_unified_review_intake(intake, ledger)
    expected_companies = {row[0] for row in SPECS}
    if set(dossiers) != expected_companies or set(proposals) != expected_companies:
        raise GTMSevenCaseBatchAdmissionError("the seven-case evidence set is incomplete")
    records = intake.get("records", [])
    expected_packets = {proposals[name]["review_packet_id"] for name, _, _ in SPECS}
    observed_packets = {row.get("review_packet_id") for row in records}
    if len(records) != 7 or observed_packets != expected_packets:
        raise GTMSevenCaseBatchAdmissionError("batch intake must contain exactly the seven bound review packets")
    reviewer_names = {row.get("reviewer_name") for row in records}
    if len(reviewer_names) != 1 or None in reviewer_names or "" in reviewer_names:
        raise GTMSevenCaseBatchAdmissionError("one named reviewer must own the complete seven-case inspection")

    staged = list(existing_candidates)
    admissions: list[dict[str, Any]] = []
    for company, compiler, verifier in SPECS:
        proposal = proposals[company]
        record = next(row for row in records if row["review_packet_id"] == proposal["review_packet_id"])
        single_intake = {"schema": intake["schema"], "review_ledger_sha256": intake["review_ledger_sha256"], "created_at": intake["created_at"], "review_count": 1, "records": [record], "automatic_promotion_allowed": False, "formal_candidate_quota_credit": 0}
        admission = compiler(single_intake, ledger, dossiers[company], proposal, staged)
        verifier(admission)
        staged.append(admission["candidate"])
        admissions.append(admission)

    payload = {
        "schema": SCHEMA, "source_batch_intake_sha256": _digest(intake), "candidate_count": len(admissions),
        "formal_candidate_quota_credit": sum(row["formal_candidate_quota_credit"] for row in admissions),
        "reviewer_names": sorted(reviewer_names), "admissions": admissions,
        "truth_boundary": "All seven named-human records and all seven case-specific admission contracts pass before any registry write. This receipt grants seven credits only when the caller atomically commits all seven candidates.",
    }
    payload["content_sha256"] = _digest(payload)
    return payload


def verify_seven_case_batch_admission(payload: Mapping[str, Any]) -> None:
    unsigned = dict(payload); supplied = unsigned.pop("content_sha256", None)
    if payload.get("schema") != SCHEMA or supplied != _digest(unsigned):
        raise GTMSevenCaseBatchAdmissionError("seven-case batch admission seal is invalid")
    admissions = payload.get("admissions")
    if not isinstance(admissions, list) or len(admissions) != 7 or payload.get("candidate_count") != 7 or payload.get("formal_candidate_quota_credit") != 7:
        raise GTMSevenCaseBatchAdmissionError("seven-case batch count or quota credit drifted")
    verifiers = {
        "ProofLaunchGTMEmailOctopusCaseCandidateAdmissionV2": verify_emailoctopus_candidate_admission,
        "ProofLaunchGTMBufferCaseCandidateAdmissionV2": verify_buffer_candidate_admission,
        "ProofLaunchGTMFlodeskCaseCandidateAdmissionV2": verify_flodesk_candidate_admission,
        "ProofLaunchGTMPostBridgeCaseCandidateAdmissionV2": verify_postbridge_candidate_admission,
        "ProofLaunchGTMParqetCaseCandidateAdmissionV2": verify_parqet_candidate_admission,
        "ProofLaunchGTMSpendbaseCaseCandidateAdmissionV2": verify_spendbase_candidate_admission,
        "ProofLaunchGTMBarn2CaseCandidateAdmissionV2": verify_barn2_candidate_admission,
    }
    schemas = [row.get("schema") for row in admissions]
    if set(schemas) != set(verifiers):
        raise GTMSevenCaseBatchAdmissionError("seven-case batch contains the wrong admission set")
    for admission in admissions:
        verifiers[admission["schema"]](admission)


__all__ = ["GTMSevenCaseBatchAdmissionError", "compile_seven_case_batch_admission", "verify_seven_case_batch_admission"]
