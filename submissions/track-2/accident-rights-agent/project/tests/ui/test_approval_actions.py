from __future__ import annotations

import pytest

from app.rights.approval import HumanApprovalManager
from app.schemas.rights import HumanApprovalState
from app.ui.view_models import approval_summary_html, approval_view


def test_policy_gate_block_disables_approve(golden_ui_runtime):
    state = {
        **golden_ui_runtime.state,
        "policy_gate": {
            **golden_ui_runtime.state["policy_gate"],
            "decision": "block",
            "blocking_issues": ["TEST-BLOCK"],
        },
    }
    view = approval_view(state)
    assert view["can_approve"] is False
    assert "TEST-BLOCK" in view["blocked_reasons"]


def test_unapproved_document_remains_draft(golden_ui_runtime):
    view = approval_view(golden_ui_runtime.state)
    assert view["display_document_status"] == "draft"
    assert golden_ui_runtime.state["document_status"] == "draft"


def test_approval_summary_keeps_the_safety_boundary_visible(golden_ui_runtime):
    rendered = approval_summary_html(golden_ui_runtime.state)

    assert "人工批准与安全门" in rendered
    assert "系统不会自动提交或发送" in rendered
    assert "Policy Gate" in rendered
    assert len(rendered) < 10_000


def test_document_change_invalidates_previous_approval(golden_ui_runtime):
    approval = HumanApprovalState.model_validate(
        golden_ui_runtime.state["approval_state"]
    )
    changed = HumanApprovalManager.invalidate_if_changed(
        approval,
        document_version=approval.document_version + 1,
        inputs_hash="a" * 64,
    )
    assert changed.state.value == "pending"
    assert changed.invalidation_reason


def test_blocking_draft_cannot_be_approved(golden_ui_runtime):
    with pytest.raises(ValueError, match="blocking fields"):
        golden_ui_runtime.workflows.decide_approval(
            golden_ui_runtime.thread_id,
            decision="approved",
            approver="test-reviewer",
            comments="attempted approval",
        )
