from __future__ import annotations

from app.rights.delivery_date import DeliveryDateExtractor


def _fact(statement, predicate, value, fact_id="FACT-DATE-001", status="verified"):
    return {
        "fact_id": fact_id,
        "statement": statement,
        "predicate": predicate,
        "value": value,
        "status": status,
        "source_node_ids": [f"NODE-{fact_id}"],
    }


def test_explicit_delivery_date_is_extracted_deterministically():
    result = DeliveryDateExtractor().extract(
        facts=[
            _fact(
                "送达回执记载事故认定书送达日期为2026-07-28",
                "送达回执日期",
                "2026-07-28",
            )
        ]
    )
    assert result.status.value == "confirmed"
    assert result.extracted_date.isoformat() == "2026-07-28"
    assert result.extraction_method == "deterministic_fact_date_parser"


def test_document_issue_date_is_not_used_as_delivery_date():
    result = DeliveryDateExtractor().extract(
        facts=[_fact("事故认定书落款日期2026-07-28", "落款日期", "2026-07-28")]
    )
    assert result.status.value == "weak_evidence"
    assert result.extracted_date is None
    assert result.requires_human_confirmation is True


def test_conflicting_delivery_dates_are_disputed_without_selection():
    result = DeliveryDateExtractor().extract(
        facts=[
            _fact(
                "送达回执日期2026-07-28",
                "送达回执日期",
                "2026-07-28",
                "FACT-DATE-001",
            ),
            _fact(
                "电子送达时间2026-07-29",
                "电子送达时间",
                "2026-07-29",
                "FACT-DATE-002",
            ),
        ]
    )
    assert result.status.value == "disputed"
    assert result.extracted_date is None
    assert len(result.alternatives) == 2
