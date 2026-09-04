from __future__ import annotations

import pytest

from app.memory.protected_fields import (
    ProtectedFieldLoss,
    assert_protected_fields_preserved,
    protected_set,
)


def test_all_required_protected_kinds_are_preserved():
    payload = {
        "served_date": "2026-07-28",
        "deadline": "2026-07-31",
        "amount": "￥12500",
        "liability_ratio": "60%",
        "vehicle_id": "沪A12345",
        "party_role": "被保险机动车驾驶人",
        "evidence_id": "NODE-ABC-001",
        "fact_id": "FACT-ABC-001",
        "law_id": "LAW-ABC-001",
        "document_version": "公安部令第146号",
        "approval_status": "pending",
    }
    assert_protected_fields_preserved(payload, payload)
    kinds = {kind for kind, _value in protected_set(payload)}
    assert kinds == {
        "date",
        "deadline",
        "amount",
        "liability_ratio",
        "vehicle_id",
        "party_role",
        "evidence_id",
        "fact_id",
        "law_id",
        "document_version",
        "approval_status",
    }


def test_protected_field_loss_blocks_downstream():
    before = {
        "deadline": "2026-07-31",
        "amount": "￥12500",
        "evidence_id": "NODE-ABC-001",
        "law_id": "LAW-ABC-001",
        "approval_status": "pending",
    }
    with pytest.raises(ProtectedFieldLoss):
        assert_protected_fields_preserved(before, {"summary": "字段已省略"})
