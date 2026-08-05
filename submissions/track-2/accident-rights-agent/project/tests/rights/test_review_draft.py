from __future__ import annotations

import pytest

from app.rights.approval import HumanApprovalManager
from app.rights.delivery_date import DeliveryDateExtractor
from app.rights.review_draft import ReviewApplicationDraftGenerator
from app.schemas.legal import LegalCitation
from app.schemas.rights import ApprovalDecision, RightsTaskStatus


def _citations(retriever):
    return [
        LegalCitation.from_chunk(chunk, 1.0)
        for chunk in retriever.corpus.list_chunks()
        if chunk.document_id == "CN-RULE-ACCIDENT-PROCEDURE-2017"
    ]


def test_incomplete_review_application_stays_draft_and_cites_facts(legal_retriever):
    draft = ReviewApplicationDraftGenerator().generate(
        case_id="CASE-DRAFT",
        facts=[
            {
                "fact_id": "FACT-DRAFT-001",
                "statement": "碰撞点位于路口机动车道内",
                "status": "verified",
                "source_node_ids": ["NODE-DRAFT-001"],
            },
            {
                "fact_id": "FACT-DRAFT-002",
                "statement": "交警徇私，保证撤销",
                "status": "disputed",
                "source_node_ids": ["NODE-DRAFT-002"],
            },
        ],
        legal_citations=_citations(legal_retriever),
        delivery=DeliveryDateExtractor().extract(
            facts=[], manual_date="2026-07-28"
        ),
    )
    assert draft.status == "draft"
    assert draft.blocking_fields
    assert draft.facts[0].fact_ids == ["FACT-DRAFT-001"]
    assert all("交警徇私" not in item.text for item in draft.facts)
    assert "RISK-BIAS-ACCUSATION" in draft.risk_language_findings


def test_approval_invalidates_after_document_change(legal_retriever):
    draft = ReviewApplicationDraftGenerator().generate(
        case_id="CASE-APPROVAL",
        facts=[
            {
                "fact_id": "FACT-APPROVAL-001",
                "statement": "事故认定书已送达",
                "status": "verified",
                "source_node_ids": ["NODE-APPROVAL-001"],
            }
        ],
        legal_citations=_citations(legal_retriever),
        delivery=DeliveryDateExtractor().extract(
            facts=[], manual_date="2026-07-28"
        ),
        applicant={"name": "测试申请人", "identity_or_role": "机动车驾驶人"},
        challenged_document={"document_number": "TEST-001"},
    )
    pending = HumanApprovalManager.pending_for(draft)
    with pytest.raises(PermissionError):
        HumanApprovalManager.enforce_task_status(
            RightsTaskStatus.SUBMITTED, pending
        )
    approved = HumanApprovalManager.decide(
        pending,
        decision=ApprovalDecision.APPROVED,
        approver="reviewer",
        comments="checked",
        audit_event_id="AUDIT-APPROVAL-1",
        document_version=draft.document_version,
        inputs_hash=draft.inputs_hash,
    )
    HumanApprovalManager.enforce_task_status(
        RightsTaskStatus.SUBMITTED, approved, draft
    )
    invalidated = HumanApprovalManager.invalidate_if_changed(
        approved,
        document_version=2,
        inputs_hash="f" * 64,
    )
    assert invalidated.state.value == "pending"
    assert invalidated.invalidation_reason


def test_expired_approval_has_audited_terminal_state(legal_retriever):
    draft = ReviewApplicationDraftGenerator().generate(
        case_id="CASE-EXPIRED-APPROVAL",
        facts=[
            {
                "fact_id": "FACT-EXPIRED-001",
                "statement": "事故认定书已送达",
                "status": "verified",
                "source_node_ids": ["NODE-EXPIRED-001"],
            }
        ],
        legal_citations=_citations(legal_retriever),
        delivery=DeliveryDateExtractor().extract(
            facts=[], manual_date="2026-07-28"
        ),
        applicant={"name": "测试申请人", "identity_or_role": "机动车驾驶人"},
        challenged_document={"document_number": "TEST-EXPIRED-001"},
    )
    expired = HumanApprovalManager.expire(
        HumanApprovalManager.pending_for(draft),
        actor="system",
        comments="approval window expired",
        audit_event_id="AUDIT-EXPIRED-1",
    )
    assert expired.state is ApprovalDecision.EXPIRED
    assert expired.record.audit_event_id == "AUDIT-EXPIRED-1"
    with pytest.raises(PermissionError):
        HumanApprovalManager.enforce_task_status(
            RightsTaskStatus.SENT, expired, draft
        )
