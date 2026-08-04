from __future__ import annotations

from datetime import UTC, datetime

import pytest

from policyseal.audit.chain import AuditChain
from policyseal.audit.models import AuditEventType
from policyseal.audit.sanitizer import AuditPayloadError


def _clock() -> datetime:
    return datetime(2026, 8, 2, 0, 0, tzinfo=UTC)


def test_middle_event_tampering_is_detected() -> None:
    chain = AuditChain.in_memory(clock=_clock)
    chain.append("task_created", {"task_id": "t1"})
    chain.append("source_viewed", {"task_id": "t1"})
    chain.unsafe_replace_payload_for_test(0, {"task_id": "changed"})

    result = chain.verify()

    assert result.valid is False
    assert result.first_invalid_index == 0


def test_audit_payload_rejects_raw_secrets() -> None:
    chain = AuditChain.in_memory(clock=_clock)

    result = chain.try_append("decision", {"raw_value": "secret"})

    assert result.accepted is False
    assert chain.events == ()


@pytest.mark.parametrize(
    "payload",
    [
        {"source_text": "full source"},
        {"prompt": "hidden model prompt"},
        {"hidden_reasoning": "private reasoning"},
        {"credentials": "demo-password"},
        {"unknown_field": "value"},
    ],
)
def test_forbidden_and_unknown_payload_fields_fail_closed(payload: dict[str, str]) -> None:
    chain = AuditChain.in_memory(clock=_clock)

    with pytest.raises(AuditPayloadError):
        chain.append(AuditEventType.DECISION, payload)


def test_valid_chain_links_canonical_events_without_payload_order_dependence() -> None:
    first = AuditChain.in_memory(clock=_clock)
    second = AuditChain.in_memory(clock=_clock)
    event_id = "audit-event-0001"
    first.append(
        AuditEventType.DECISION,
        {
            "region_id": "region-1",
            "action": "remove",
            "category": "credential_secret",
            "rule_ids": ["PS-DOCX-RESPONDER-CREDENTIAL"],
        },
        event_id=event_id,
        actor="policyseal",
        task_id="task-1",
        revision_id="revision-1",
        policy_sha256="a" * 64,
    )
    second.append(
        AuditEventType.DECISION,
        {
            "rule_ids": ["PS-DOCX-RESPONDER-CREDENTIAL"],
            "category": "credential_secret",
            "action": "remove",
            "region_id": "region-1",
        },
        event_id=event_id,
        actor="policyseal",
        task_id="task-1",
        revision_id="revision-1",
        policy_sha256="a" * 64,
    )

    assert first.events[0].event_hash == second.events[0].event_hash
    assert first.verify().valid is True


def test_changing_previous_hash_or_event_order_is_detected() -> None:
    chain = AuditChain.in_memory(clock=_clock)
    chain.append("task_created", {"task_id": "task-1"}, event_id="event-1")
    chain.append("source_viewed", {"task_id": "task-1"}, event_id="event-2")

    chain.unsafe_swap_events_for_test(0, 1)

    assert chain.verify().valid is False


def test_payload_contains_only_sanitized_structured_values() -> None:
    chain = AuditChain.in_memory(clock=_clock)
    event = chain.append(
        AuditEventType.EXPORTED,
        {
            "export_kind": "business_file",
            "output_sha256": "b" * 64,
            "decision_count": 12,
        },
    )

    serialized = event.canonical_bytes().decode("ascii")
    assert "business_file" in serialized
    assert "source_text" not in serialized
    assert "secret" not in serialized
