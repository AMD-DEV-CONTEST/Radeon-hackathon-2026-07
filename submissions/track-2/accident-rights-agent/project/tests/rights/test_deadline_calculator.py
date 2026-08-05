from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.rights.deadline import DeadlineCalculator
from app.rights.delivery_date import DeliveryDateExtractor
from app.schemas.legal import LegalCitation


def _citations(retriever):
    return [
        LegalCitation.from_chunk(chunk, 1.0)
        for chunk in retriever.corpus.list_chunks()
        if chunk.document_id == "CN-RULE-ACCIDENT-PROCEDURE-2017"
    ]


def _delivery(value="2026-07-28"):
    return DeliveryDateExtractor().extract(
        facts=[],
        manual_date=value,
    )


def test_review_deadline_uses_versioned_workday_rule(legal_retriever):
    result = DeadlineCalculator().calculate(
        delivery=_delivery(),
        matter_type="accident_determination_review",
        rule_id="RULE-CN-DEADLINE-ACCIDENT-REVIEW-2017",
        legal_citations=_citations(legal_retriever),
        now=datetime(2026, 7, 29, 12, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    assert result.status.value == "active"
    assert result.due_at.isoformat() == "2026-07-31T23:59:59+08:00"
    assert result.rule_id == "RULE-CN-DEADLINE-ACCIDENT-REVIEW-2017"
    assert result.legal_review_status.value == "not_needed"


def test_deadline_due_soon_and_expired_statuses(legal_retriever):
    calculator = DeadlineCalculator()
    kwargs = {
        "delivery": _delivery(),
        "matter_type": "accident_determination_review",
        "rule_id": "RULE-CN-DEADLINE-ACCIDENT-REVIEW-2017",
        "legal_citations": _citations(legal_retriever),
    }
    due_soon = calculator.calculate(
        **kwargs,
        now=datetime(2026, 7, 31, 12, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    expired = calculator.calculate(
        **kwargs,
        now=datetime(2026, 8, 1, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    assert due_soon.status.value == "due_soon"
    assert expired.status.value == "expired"


def test_unconfirmed_delivery_never_starts_deadline():
    weak = DeliveryDateExtractor().extract(
        facts=[
            {
                "fact_id": "FACT-WEAK",
                "statement": "文书落款日期2026-07-28",
                "predicate": "落款日期",
                "value": "2026-07-28",
                "status": "verified",
                "source_node_ids": ["NODE-WEAK"],
            }
        ]
    )
    result = DeadlineCalculator().calculate(
        delivery=weak,
        matter_type="accident_determination_review",
        rule_id="RULE-CN-DEADLINE-ACCIDENT-REVIEW-2017",
    )
    assert result.status.value == "disputed"
    assert result.due_at is None
