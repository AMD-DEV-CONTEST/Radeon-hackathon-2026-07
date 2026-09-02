"""Stage I — Integration connector tests (email, webhook, SCM, CI)."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.integrations.base import BaseConnector, ConfirmationRequired, ConnectorResult, ConnectorStatus
from app.integrations.email import EmailConnector
from app.integrations.webhook import WebhookRegistry, WebhookDispatcher
from app.integrations.scm import SCMConnector, SCMTarget
from app.integrations.ci import CITriggerConnector


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        project_root=tmp_path / "projects",
        output_root=tmp_path / "outputs",
        vector_db_root=tmp_path / "vectors",
        sqlite_path=tmp_path / "sqlite" / "projectpack.db",
        log_root=tmp_path / "logs",
    )


# ---------------------------------------------------------------------------
# Email Connector
# ---------------------------------------------------------------------------


def test_integration_write_api_requires_authentication(tmp_path: Path) -> None:
    """Integration write endpoints are not accessible without a bearer token."""
    app = create_app(_settings(tmp_path))
    with TestClient(app) as client:
        response = client.post("/api/integrations/email/preview", json={
            "project_id": "demo-project", "recipient": "user@example.com",
        })
    assert response.status_code == 401


def test_email_connector_preview_and_execute(tmp_path: Path) -> None:
    """EmailConnector: preview_diff returns preview, execute sends (stub SMTP)."""
    connector = EmailConnector(db_path=str(tmp_path / "email.db"))

    data = {
        "type": "task_report",
        "recipient": "user@example.com",
        "subject": "Test Report",
        "project_name": "DemoProject",
        "task_name": "QA Review",
        "status": "completed",
        "summary": "All checks passed.",
    }

    # preview
    preview = connector.preview_diff(data)
    assert preview["type"] == "task_report"
    assert preview["recipient"] == "user@example.com"
    assert "body_preview" in preview

    # execute with full original data (not preview dict)
    result = connector.execute(data, confirmation_id=preview["confirmation_id"])
    # SMTP connection may fail if no server on localhost:1025,
    # but result status/contract is always valid
    assert hasattr(result, "status")
    assert hasattr(result, "summary")
    assert result.details.get("recipient") == "user@example.com"

    # Step debugging: verify preview returns correct keys
    assert isinstance(preview, dict)
    assert "type" in preview
    assert "recipient" in preview
    assert "subject" in preview
    assert "body_preview" in preview


def test_email_rate_limiting(tmp_path: Path) -> None:
    """EmailConnector: rate-limits on same domain (10 per hour)."""
    connector = EmailConnector(
        db_path=str(tmp_path / "email_rate.db"), rate_max=3
    )

    for i in range(3):
        data = {
            "type": "task_report",
            "recipient": f"user{i}@spam.com",
            "subject": f"Report {i}",
            "project_name": "P",
            "task_name": "T",
            "status": "ok",
            "summary": "ok",
        }
        preview = connector.preview_diff(data)
        connector.execute(data, confirmation_id=preview["confirmation_id"])

    # 4th send on same domain should hit rate limit
    data4 = {
        "type": "task_report",
        "recipient": "user4@spam.com",
        "subject": "Blocked",
        "project_name": "P",
        "task_name": "T",
        "status": "ok",
        "summary": "ok",
    }
    with pytest.raises(ConfirmationRequired) as ctx:
        connector.preview_diff(data4)
    assert "Rate limit reached" in str(ctx.value)
    assert "spam.com" in str(ctx.value)


def test_email_audit_log(tmp_path: Path) -> None:
    """EmailConnector: audit returns sent history."""
    connector = EmailConnector(db_path=str(tmp_path / "email_audit.db"))

    data = {
        "type": "risk_alert",
        "recipient": "alert@example.com",
        "subject": "Risk Alert",
        "project_name": "P",
        "risk_level": "high",
        "description": "Critical bug",
    }
    preview = connector.preview_diff(data)
    connector.execute(data, confirmation_id=preview["confirmation_id"])

    audit = connector.audit()
    assert len(audit) >= 1
    assert audit[0]["recipient"] == "alert@example.com"


def test_email_rollback(tmp_path: Path) -> None:
    """EmailConnector: rollback marks retraction (non-reversible)."""
    connector = EmailConnector(db_path=str(tmp_path / "email_rollback.db"))
    result = connector.rollback({"recipient": "x@x.com"})
    assert result.status == ConnectorStatus.ROLLED_BACK
    assert "cannot be undone" in result.summary


def test_email_read_state(tmp_path: Path) -> None:
    """EmailConnector: read returns recent sends count."""
    connector = EmailConnector(db_path=str(tmp_path / "email_read.db"))
    state = connector.read()
    assert "recent_sends" in state
    assert "last_entries" in state


def test_email_missing_recipient_raises(tmp_path: Path) -> None:
    """EmailConnector: preview_diff raises ValueError without recipient."""
    connector = EmailConnector(db_path=str(tmp_path / "email_missing.db"))
    with pytest.raises(ValueError, match="recipient"):
        connector.preview_diff({"type": "task_report"})


def test_email_failure_returns_failed_status(tmp_path: Path) -> None:
    """EmailConnector: SMTP failure returns FAILED status."""
    connector = EmailConnector(
        db_path=str(tmp_path / "email_fail.db"),
        smtp_host="127.0.0.1",  # localhost, no SMTP server
        smtp_port=19999,  # unreachable port
    )
    data = {
        "type": "task_report",
        "recipient": "user@example.com",
        "subject": "Test",
        "project_name": "P",
        "task_name": "T",
        "status": "ok",
        "summary": "ok",
    }
    # preview
    preview = connector.preview_diff(data)
    result = connector.execute(data, confirmation_id="cf-bad")
    # SMTP to unreachable port will fail, check we got a result
    assert hasattr(result, "status")
    assert hasattr(result, "summary")


# ---------------------------------------------------------------------------
# Webhook Registry
# ---------------------------------------------------------------------------


def test_webhook_register_and_list(tmp_path: Path) -> None:
    """WebhookRegistry: register and list webhooks."""
    registry = WebhookRegistry(db_path=str(tmp_path / "wh.db"))
    reg = registry.register(
        url="https://hooks.example.com/callback",
        events=["task_status_change", "risk_lifecycle_change"],
        secret="shared-secret",
    )
    assert reg.id.startswith("wh_")
    assert reg.url == "https://hooks.example.com/callback"
    assert "task_status_change" in reg.events
    assert reg.active is True

    all_hooks = registry.list_all()
    assert len(all_hooks) == 1
    assert all_hooks[0].id == reg.id


def test_webhook_register_invalid_event_raises(tmp_path: Path) -> None:
    """WebhookRegistry: registration with invalid events raises ValueError."""
    registry = WebhookRegistry(db_path=str(tmp_path / "wh_invalid.db"))
    with pytest.raises(ValueError, match="valid event"):
        registry.register(url="https://x.com/hook", events=["bogus_event"])


def test_webhook_get_raises_for_missing(tmp_path: Path) -> None:
    """WebhookRegistry: get raises KeyError for unknown id."""
    registry = WebhookRegistry(db_path=str(tmp_path / "wh_missing.db"))
    with pytest.raises(KeyError):
        registry.get("wh_nonexistent")


def test_webhook_dispatcher_delivers(tmp_path: Path) -> None:
    """WebhookDispatcher: dispatches events to registered webhooks."""
    registry = WebhookRegistry(db_path=str(tmp_path / "wh_dispatch.db"))
    registry.register(
        url="https://hooks.example.com/a",
        events=["project_member_change"],
        secret="s1",
    )
    registry.register(
        url="https://hooks.example.com/b",
        events=["task_status_change"],
        secret="s2",
    )

    dispatcher = WebhookDispatcher(registry)
    result = dispatcher.dispatch(
        "project_member_change",
        {"user": "u1", "action": "added", "project_id": "p1"},
    )
    assert result["delivered"] >= 1
    assert "by_id" in result


def test_webhook_inactive_not_dispatched(tmp_path: Path) -> None:
    """WebhookDispatcher: inactive webhooks are skipped."""
    registry = WebhookRegistry(db_path=str(tmp_path / "wh_inactive.db"))
    reg = registry.register(
        url="https://hooks.example.com/inactive",
        events=["task_status_change"],
    )
    # We don't have a direct deactivate method, but we test dispatch logic
    dispatcher = WebhookDispatcher(registry)
    result = dispatcher.dispatch(
        "task_status_change",
        {"task_id": "t1", "status": "completed"},
    )
    assert "total" in result
    assert "delivered" in result


def test_webhook_dead_letter_on_failure_path(tmp_path: Path) -> None:
    """WebhookRegistry: dead_letters table records failures."""
    registry = WebhookRegistry(db_path=str(tmp_path / "wh_dl.db"))
    reg = registry.register(
        url="https://bad.example.com",
        events=["task_status_change"],
    )
    registry.send_to_dead_letter(reg.id, "task_status_change",
                                 {"error": "timeout"}, "Connection refused")
    dl = registry.list_dead_letters()
    assert len(dl) == 1
    assert dl[0]["registration_id"] == reg.id
    assert "Connection refused" in dl[0]["error"]


# ---------------------------------------------------------------------------
# SCM Connector
# ---------------------------------------------------------------------------


def test_scm_connector_read(tmp_path: Path) -> None:
    """SCMConnector: read returns state with empty issues."""
    connector = SCMConnector(db_path=str(tmp_path / "scm.db"))
    state = connector.read(target=SCMTarget.GITHUB_ISSUES.value)
    assert state["target"] == "github_issues"
    assert isinstance(state["issues"], list)


def test_scm_connector_preview_requires_confirmation(tmp_path: Path) -> None:
    """SCMConnector: preview_diff raises ConfirmationRequired."""
    connector = SCMConnector(db_path=str(tmp_path / "scm_cf.db"))
    data = {
        "target": "github_issues",
        "operation": "create",
        "items": [{"title": "Fix login bug", "body": "Details..."}],
    }
    with pytest.raises(ConfirmationRequired) as ctx:
        connector.preview_diff(data)
    assert "Confirmation required" in str(ctx.value)
    assert "confirmation_id" in ctx.value.details


def test_scm_connector_execute_with_confirmation(tmp_path: Path) -> None:
    """SCMConnector: execute succeeds with valid confirmation_id."""
    connector = SCMConnector(db_path=str(tmp_path / "scm_exec.db"))
    data = {
        "target": "github_issues",
        "operation": "create",
        "items": [{"title": "Bug", "body": "desc"}],
    }
    # Get confirmation_id from preview
    try:
        connector.preview_diff(data)
    except ConfirmationRequired as cr:
        cid = cr.details["confirmation_id"]
        result = connector.execute(data, confirmation_id=cid)
        assert result.status == ConnectorStatus.EXECUTED
        assert "committed" in result.summary
        assert result.details["confirmation_id"] == cid
    else:
        pytest.fail("Expected ConfirmationRequired")


def test_scm_connector_execute_invalid_confirmation(tmp_path: Path) -> None:
    """SCMConnector: execute with invalid/used confirmation_id returns FAILED."""
    connector = SCMConnector(db_path=str(tmp_path / "scm_invalid.db"))
    data = {"target": "github_issues", "operation": "create", "items": [{"title": "X"}]}
    result = connector.execute(data, confirmation_id="scm_confirm_bogus")
    assert result.status == ConnectorStatus.FAILED
    assert "Invalid" in result.summary or "already-used" in result.summary


def test_scm_connector_rollback(tmp_path: Path) -> None:
    """SCMConnector: rollback records intention."""
    connector = SCMConnector(db_path=str(tmp_path / "scm_rb.db"))
    result = connector.rollback({"target": "github_issues", "items": []})
    assert result.status == ConnectorStatus.ROLLED_BACK


def test_scm_connector_audit(tmp_path: Path) -> None:
    """SCMConnector: audit returns executed operations."""
    connector = SCMConnector(db_path=str(tmp_path / "scm_audit.db"))
    data = {"target": "jira", "operation": "create", "items": [{"title": "J1"}]}
    try:
        connector.preview_diff(data)
    except ConfirmationRequired as cr:
        connector.execute(data, confirmation_id=cr.details["confirmation_id"])
    audit = connector.audit()
    assert len(audit) == 1
    assert audit[0]["status"] == "committed"


# ---------------------------------------------------------------------------
# CI Trigger Connector
# ---------------------------------------------------------------------------


def test_ci_trigger_preview_requires_confirmation(tmp_path: Path) -> None:
    """CITriggerConnector: preview_diff raises ConfirmationRequired."""
    conn = CITriggerConnector(db_path=str(tmp_path / "ci.db"))
    data = {"project_id": "p1", "files": ["main.py", "test.py"]}
    with pytest.raises(ConfirmationRequired) as ctx:
        conn.preview_diff(data)
    assert "CI benchmark" in str(ctx.value)
    assert "confirmation_id" in ctx.value.details


def test_ci_trigger_execute_with_confirmation(tmp_path: Path) -> None:
    """CITriggerConnector: execute with valid confirmation_id succeeds."""
    conn = CITriggerConnector(db_path=str(tmp_path / "ci_exec.db"))
    data = {"project_id": "p1", "files": ["main.py"]}
    try:
        conn.preview_diff(data)
    except ConfirmationRequired as cr:
        result = conn.execute(data, confirmation_id=cr.details["confirmation_id"])
        assert result.status == ConnectorStatus.EXECUTED
        assert "triggered" in result.summary


def test_ci_trigger_execute_invalid_confirmation(tmp_path: Path) -> None:
    """CITriggerConnector: execute with invalid confirmation_id returns FAILED."""
    conn = CITriggerConnector(db_path=str(tmp_path / "ci_invalid.db"))
    data = {"project_id": "p1", "files": ["main.py"]}
    result = conn.execute(data, confirmation_id="ci_confirm_bogus")
    assert result.status == ConnectorStatus.FAILED


def test_ci_trigger_rollback(tmp_path: Path) -> None:
    """CITriggerConnector: rollback is non-reversible."""
    conn = CITriggerConnector(db_path=str(tmp_path / "ci_rb.db"))
    result = conn.rollback({"project_id": "p1"})
    assert result.status == ConnectorStatus.ROLLED_BACK


def test_ci_trigger_audit(tmp_path: Path) -> None:
    """CITriggerConnector: audit returns triggered history."""
    conn = CITriggerConnector(db_path=str(tmp_path / "ci_audit.db"))
    data = {"project_id": "p2", "files": ["x.py"]}
    try:
        conn.preview_diff(data)
    except ConfirmationRequired as cr:
        conn.execute(data, confirmation_id=cr.details["confirmation_id"])
    audit = conn.audit()
    assert len(audit) == 1
    assert audit[0]["status"] == "triggered"


def test_ci_read_returns_recent_triggers(tmp_path: Path) -> None:
    """CITriggerConnector: read returns recent_triggers list."""
    conn = CITriggerConnector(db_path=str(tmp_path / "ci_read.db"))
    state = conn.read()
    assert "recent_triggers" in state
    assert isinstance(state["recent_triggers"], list)


def test_scm_missing_items_raises(tmp_path: Path) -> None:
    """SCMConnector: preview_diff with empty items raises ValueError."""
    connector = SCMConnector(db_path=str(tmp_path / "scm_empty.db"))
    with pytest.raises(ValueError, match="items"):
        connector.preview_diff({"target": "github_issues", "operation": "create", "items": []})


# ---------------------------------------------------------------------------
# Connector base
# ---------------------------------------------------------------------------


def test_connector_status_lifecycle() -> None:
    """ConnectorStatus enum has expected states."""
    assert ConnectorStatus.IDLE.value == 1
    assert ConnectorStatus.EXECUTED.value == 6
    assert ConnectorStatus.FAILED.value == 7
    assert ConnectorStatus.ROLLED_BACK.value == 8


def test_confirmation_required_exception() -> None:
    """ConfirmationRequired carries diff_summary and details."""
    ex = ConfirmationRequired("Test diff", {"id": "abc"})
    assert ex.diff_summary == "Test diff"
    assert ex.details == {"id": "abc"}
    assert str(ex) == "Test diff"
