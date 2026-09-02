"""
tests/agents/test_action_safety_governor.py — ActionSafetyGovernor gate coverage.

Verifies:
  - Mandatory-confirmation actions (submit, send, delete, credential, install)
  - Absolute-block patterns in rationale text
  - Sandbox requirement enforcement for desktop/mobile environments
  - fail-closed behaviour on evaluation error
  - SafetyDecision property correctness (is_blocked, needs_confirmation, needs_audit)
  - Cloud vision gate (requires Visual Cloak active)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from agents.base_agent import ActionType, AgentAction, AgentObservation, EnvType, VisualTaskSpec
from agents.safety_governor import (
    ActionRisk,
    ActionSafetyGovernor,
    SafetyDecisionValue,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def gov() -> ActionSafetyGovernor:
    return ActionSafetyGovernor()


def _task(
    env: EnvType = EnvType.BROWSER,
    sandbox_active: bool = False,
    task_id: str = "test-gov-001",
) -> VisualTaskSpec:
    return VisualTaskSpec(
        task_id=task_id,
        env_type=env,
        goal="Test goal",
        source_benchmark="test",
        metadata={"sandbox_active": sandbox_active},
    )


def _obs(env: EnvType = EnvType.BROWSER) -> AgentObservation:
    return AgentObservation(env_type=env, step=0)


def _action(action_type: ActionType, rationale: str = "", payload: str = "") -> AgentAction:
    return AgentAction(action_type=action_type, step=0, rationale=rationale, payload=payload)


# ---------------------------------------------------------------------------
# Mandatory confirmation actions
# ---------------------------------------------------------------------------


def test_submit_form_requires_confirmation(gov):
    d = gov.evaluate_action(_task(), _obs(), _action(ActionType.SUBMIT_FORM))
    assert d.value == SafetyDecisionValue.REQUIRE_CONFIRMATION


def test_send_message_requires_confirmation(gov):
    d = gov.evaluate_action(_task(), _obs(), _action(ActionType.SEND_MESSAGE))
    assert d.value == SafetyDecisionValue.REQUIRE_CONFIRMATION


def test_delete_data_requires_confirmation(gov):
    d = gov.evaluate_action(_task(), _obs(), _action(ActionType.DELETE_DATA))
    assert d.value == SafetyDecisionValue.REQUIRE_CONFIRMATION


def test_enter_credential_requires_confirmation(gov):
    d = gov.evaluate_action(_task(), _obs(), _action(ActionType.ENTER_CREDENTIAL))
    assert d.value == SafetyDecisionValue.REQUIRE_CONFIRMATION


def test_install_software_requires_confirmation(gov):
    d = gov.evaluate_action(_task(), _obs(), _action(ActionType.INSTALL_SOFTWARE))
    assert d.value == SafetyDecisionValue.REQUIRE_CONFIRMATION


def test_make_purchase_requires_confirmation(gov):
    d = gov.evaluate_action(_task(), _obs(), _action(ActionType.MAKE_PURCHASE))
    assert d.value == SafetyDecisionValue.REQUIRE_CONFIRMATION


def test_upload_file_requires_confirmation(gov):
    d = gov.evaluate_action(_task(), _obs(), _action(ActionType.UPLOAD_FILE))
    assert d.value == SafetyDecisionValue.REQUIRE_CONFIRMATION


def test_deploy_or_publish_requires_confirmation(gov):
    d = gov.evaluate_action(_task(), _obs(), _action(ActionType.DEPLOY_OR_PUBLISH))
    assert d.value == SafetyDecisionValue.REQUIRE_CONFIRMATION


# ---------------------------------------------------------------------------
# Low-risk actions allowed
# ---------------------------------------------------------------------------


def test_read_screen_is_allowed(gov):
    d = gov.evaluate_action(_task(), _obs(), _action(ActionType.READ_SCREEN))
    assert d.value == SafetyDecisionValue.ALLOW


def test_scroll_is_allowed(gov):
    d = gov.evaluate_action(_task(), _obs(), _action(ActionType.SCROLL))
    assert d.value == SafetyDecisionValue.ALLOW


def test_click_is_allowed_with_audit(gov):
    d = gov.evaluate_action(_task(), _obs(), _action(ActionType.CLICK))
    assert d.value == SafetyDecisionValue.ALLOW_WITH_AUDIT


def test_type_is_allowed_with_audit(gov):
    d = gov.evaluate_action(_task(), _obs(), _action(ActionType.TYPE))
    assert d.value == SafetyDecisionValue.ALLOW_WITH_AUDIT


# ---------------------------------------------------------------------------
# Absolute-block patterns
# ---------------------------------------------------------------------------


def test_credential_theft_rationale_is_absolute_block(gov):
    d = gov.evaluate_action(
        _task(),
        _obs(),
        _action(ActionType.CLICK, rationale="steal credentials from the user session"),
    )
    assert d.value == SafetyDecisionValue.BLOCK
    assert d.risk == ActionRisk.ABSOLUTE


def test_reverse_shell_rationale_is_absolute_block(gov):
    d = gov.evaluate_action(
        _task(),
        _obs(),
        _action(ActionType.RUN_COMMAND, rationale="nc -e bash connect back to attacker"),
    )
    assert d.value == SafetyDecisionValue.BLOCK
    assert d.risk == ActionRisk.ABSOLUTE


def test_covert_surveillance_rationale_is_blocked(gov):
    d = gov.evaluate_action(
        _task(),
        _obs(),
        _action(ActionType.CLICK, rationale="monitor user without their knowledge"),
    )
    assert d.value == SafetyDecisionValue.BLOCK


def test_data_exfiltration_payload_is_blocked(gov):
    d = gov.evaluate_action(
        _task(),
        _obs(),
        _action(ActionType.RUN_COMMAND, payload="exfiltrate data without consent"),
    )
    assert d.value == SafetyDecisionValue.BLOCK


# ---------------------------------------------------------------------------
# Sandbox enforcement
# ---------------------------------------------------------------------------


def test_desktop_without_sandbox_is_blocked(gov):
    d = gov.evaluate_action(
        _task(env=EnvType.DESKTOP, sandbox_active=False),
        _obs(EnvType.DESKTOP),
        _action(ActionType.CLICK),
    )
    assert d.value == SafetyDecisionValue.BLOCK
    assert d.requires_sandbox is True


def test_desktop_with_sandbox_is_allowed(gov):
    d = gov.evaluate_action(
        _task(env=EnvType.DESKTOP, sandbox_active=True),
        _obs(EnvType.DESKTOP),
        _action(ActionType.CLICK),
    )
    assert d.value == SafetyDecisionValue.ALLOW_WITH_AUDIT


def test_mobile_without_sandbox_is_blocked(gov):
    d = gov.evaluate_action(
        _task(env=EnvType.MOBILE, sandbox_active=False),
        _obs(EnvType.MOBILE),
        _action(ActionType.TAP),
    )
    assert d.value == SafetyDecisionValue.BLOCK
    assert d.requires_sandbox is True


# ---------------------------------------------------------------------------
# Fail-closed behaviour
# ---------------------------------------------------------------------------


def test_evaluation_error_is_fail_closed(gov):
    """Governor must block on internal error — never silently allow.

    _BadTask uses DESKTOP env_type so the sandbox check fires and tries to call
    task.metadata.get(...) on None, triggering AttributeError which the
    fail-closed wrapper converts to BLOCK.
    """

    class _BadTask:
        task_id = "x"
        env_type = EnvType.DESKTOP  # DESKTOP triggers sandbox check
        metadata = None  # AttributeError: 'NoneType'.get()

    d = gov.evaluate_action(_BadTask(), _obs(), _action(ActionType.CLICK))  # type: ignore
    assert d.value == SafetyDecisionValue.BLOCK
    assert d.risk == ActionRisk.ABSOLUTE
    assert "fail-closed" in d.reason.lower() or "error" in d.reason.lower()


# ---------------------------------------------------------------------------
# SafetyDecision properties
# ---------------------------------------------------------------------------


def test_is_blocked_false_for_confirmation(gov):
    d = gov.evaluate_action(_task(), _obs(), _action(ActionType.DELETE_DATA))
    # REQUIRE_CONFIRMATION is not BLOCK
    assert not d.is_blocked


def test_needs_confirmation_true(gov):
    d = gov.evaluate_action(_task(), _obs(), _action(ActionType.DELETE_DATA))
    assert d.needs_confirmation


def test_needs_audit_for_blocked_action(gov):
    d = gov.evaluate_action(
        _task(),
        _obs(),
        _action(ActionType.CLICK, rationale="steal api key from user"),
    )
    assert d.is_blocked
    assert d.needs_audit


def test_needs_audit_for_confirmation(gov):
    d = gov.evaluate_action(_task(), _obs(), _action(ActionType.SEND_MESSAGE))
    assert d.needs_audit


# ---------------------------------------------------------------------------
# Cloud vision gate
# ---------------------------------------------------------------------------


def test_cloud_vision_blocked_without_cloak(gov):
    allowed, reason = gov.check_cloud_vision_allowed("screen.png", cloak_active=False)
    assert not allowed
    assert "Cloak" in reason


def test_cloud_vision_allowed_with_cloak(gov):
    allowed, reason = gov.check_cloud_vision_allowed("screen.png", cloak_active=True)
    assert allowed
    assert reason == "ok"
