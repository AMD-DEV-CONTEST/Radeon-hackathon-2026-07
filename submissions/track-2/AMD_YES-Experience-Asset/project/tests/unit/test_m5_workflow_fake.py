from __future__ import annotations

from uuid import uuid4

from app.experience_asset.application.m5.workflow_fake import (
    M5IsolatedWorkflowFake,
)
from app.experience_asset.domain.enums import TerminalState
from tests.fixtures.m5 import complete_context


def test_clean_context_reaches_a_sanitized_isolated_success_path() -> None:
    outcome = M5IsolatedWorkflowFake().run(
        complete_context(include_sensitive_tags=False),
        command_id=uuid4(),
    )

    assert outcome.terminal is TerminalState.SUCCEEDED
    assert outcome.state.last_node == "terminalize_m5_run"
    assert outcome.state.selected_edge == "terminalize_m5_run:END"
    assert outcome.state.route_matrix_hash is not None
    assert outcome.state.privacy_review_hash is not None
    assert outcome.state.finding_codes == []
    assert outcome.state.safe_message == "Route readiness and privacy review were verified."
    assert outcome.persisted is False
    assert outcome.trace == (
        "START",
        "load_m5_context:ready",
        "evaluate_m5_routes:evaluated",
        "review_m5_privacy:resolved_or_empty",
        "wait_m5_approval:no_final_draft",
        "verify_m5_state:verified",
        "terminalize_m5_run:END",
    )


def test_open_privacy_findings_stop_for_user_input_without_exposing_content() -> None:
    outcome = M5IsolatedWorkflowFake().run(complete_context(), command_id=uuid4())

    assert outcome.terminal is TerminalState.NEEDS_USER_INPUT
    assert outcome.state.last_node == "terminalize_m5_run"
    assert outcome.state.selected_edge == "terminalize_m5_run:END"
    assert outcome.state.finding_codes == ["HEALTH_BODY", "IDENTITY"]
    assert outcome.state.safe_message == (
        "Privacy decisions are required before external routes can be approved."
    )
    assert outcome.state.retryable is False
    assert outcome.trace[-3:] == (
        "review_m5_privacy:open_findings",
        "wait_m5_privacy_resolution:pause",
        "terminalize_m5_run:END",
    )


def test_unready_input_never_reaches_route_or_privacy_policy() -> None:
    outcome = M5IsolatedWorkflowFake().run(
        complete_context(readiness=False),
        command_id=uuid4(),
    )

    assert outcome.terminal is TerminalState.NEEDS_USER_INPUT
    assert outcome.state.route_matrix_hash is None
    assert outcome.state.privacy_review_hash is None
    assert outcome.state.finding_codes == ["M5_INPUT_NOT_READY"]
    assert outcome.trace == (
        "START",
        "load_m5_context:not_ready_or_stale",
        "terminalize_m5_run:END",
    )


def test_privacy_failure_is_safe_and_a_new_command_can_retry() -> None:
    workflow = M5IsolatedWorkflowFake()
    failed = workflow.run(
        complete_context(include_sensitive_tags=False),
        command_id=uuid4(),
        privacy_failure_code="MODEL_UNAVAILABLE",
    )

    assert failed.terminal is TerminalState.MODEL_UNAVAILABLE
    assert failed.state.last_node == "terminalize_m5_run"
    assert failed.state.finding_codes == ["MODEL_UNAVAILABLE"]
    assert failed.state.retryable is True
    assert failed.state.safe_message == (
        "Privacy review did not complete. No external approval was granted."
    )
    assert failed.trace[-2:] == (
        "review_m5_privacy:safe_failure",
        "terminalize_m5_run:END",
    )

    retried = workflow.run(
        complete_context(include_sensitive_tags=False),
        command_id=uuid4(),
    )
    assert retried.terminal is TerminalState.SUCCEEDED
    assert retried.state.command_id != failed.state.command_id
    assert retried.persisted is False
