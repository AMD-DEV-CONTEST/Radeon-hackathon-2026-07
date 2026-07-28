"""
Unit tests for Aetheris CLI approval modal logic.
Verifies keyboard navigation, verdict evaluation, and cancellation shortcuts.
"""

from aetheris_cli.policy.approval import ApprovalChoice, ApprovalVerdict, handle_approval_key


def test_tab_toggles_choice_without_verdict():
    c, v = handle_approval_key("tab", ApprovalChoice.APPROVE)
    assert c == ApprovalChoice.DENY
    assert v is None

    c2, v2 = handle_approval_key("up", c)
    assert c2 == ApprovalChoice.APPROVE
    assert v2 is None


def test_y_and_n_direct_verdicts():
    _, v1 = handle_approval_key("y", ApprovalChoice.DENY)
    assert v1 == ApprovalVerdict.APPROVE

    _, v2 = handle_approval_key("n", ApprovalChoice.APPROVE)
    assert v2 == ApprovalVerdict.DENY


def test_enter_confirms_highlighted():
    _, v1 = handle_approval_key("enter", ApprovalChoice.APPROVE)
    assert v1 == ApprovalVerdict.APPROVE

    _, v2 = handle_approval_key("enter", ApprovalChoice.DENY)
    assert v2 == ApprovalVerdict.DENY


def test_esc_and_q_cancel():
    _, v1 = handle_approval_key("esc", ApprovalChoice.APPROVE)
    assert v1 == ApprovalVerdict.CANCEL

    _, v2 = handle_approval_key("q", ApprovalChoice.DENY)
    assert v2 == ApprovalVerdict.CANCEL
