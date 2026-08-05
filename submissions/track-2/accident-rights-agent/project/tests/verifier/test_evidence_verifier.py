from __future__ import annotations

from app.verifier.evidence import EvidenceCitationVerifier


def test_missing_evidence_and_fact_ids_block(demo_case):
    workspace, case_id = demo_case
    result = EvidenceCitationVerifier().verify(
        state={
            "case_id": case_id,
            "rights_tasks": [
                {
                    "related_fact_ids": ["FACT-DOES-NOT-EXIST"],
                    "related_evidence_ids": ["NODE-DOES-NOT-EXIST"],
                }
            ],
        },
        evidence_export=workspace.store(case_id).export_case(case_id),
    )
    assert result.passed is False
    assert {item.code for item in result.issues} >= {
        "EVIDENCE-FACT-NOT-FOUND",
        "EVIDENCE-ID-NOT-FOUND",
    }


def test_law_id_in_evidence_field_is_blocked_as_type_mismatch(demo_case):
    workspace, case_id = demo_case
    result = EvidenceCitationVerifier().verify(
        state={
            "case_id": case_id,
            "analysis": {
                "evidence_ids": ["LAW-BE8C877F65C1E00AA124"],
                "law_ids": ["LAW-BE8C877F65C1E00AA124"],
            },
        },
        evidence_export=workspace.store(case_id).export_case(case_id),
    )
    assert result.passed is False
    issue = next(
        item
        for item in result.issues
        if item.code == "EVIDENCE-EVIDENCE-ID-TYPE-MISMATCH"
    )
    assert issue.related_ids == ["LAW-BE8C877F65C1E00AA124"]
