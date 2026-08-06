from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from radeonstay.api import create_api
from radeonstay.config import Settings
from radeonstay.contracts import (
    ActionCard,
    AgentPlan,
    AgentResponse,
    JourneyView,
    PendingAction,
    PlanStep,
    SessionProjection,
    ToolReceipt,
)
from radeonstay.domain import NotFoundError, PermissionDenied, ValidationError
from radeonstay.main import create_application
from radeonstay.model_client import ModelClientError

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class StubService:
    def __init__(self) -> None:
        self.chat_error: Exception | None = None
        self.confirm_error: Exception | None = None
        self.health_error: Exception | None = None
        self.health_payload = {"ok": True}
        self.health_calls = 0
        self.audit_token: str | None = None
        self.chat_response: AgentResponse | None = None
        self.last_confirm = None
        self.last_cancel = None
        self.snapshot_error: Exception | None = None
        self.closed = False

    def health(self):
        self.health_calls += 1
        if self.health_error is not None:
            raise self.health_error
        return dict(self.health_payload)

    def chat(self, request):
        del request
        if self.chat_error is not None:
            raise self.chat_error
        if self.chat_response is not None:
            return self.chat_response
        raise AssertionError("success response is not needed by this API mapping test")

    def confirm(self, request):
        if self.confirm_error is not None:
            raise self.confirm_error
        self.last_confirm = request
        return ToolReceipt(
            step_id="write",
            tool="hotel.hold_booking",
            status="ok",
            summary="confirmed",
        )

    def cancel_action(self, request):
        self.last_cancel = request
        return ToolReceipt(
            step_id="write",
            tool="hotel.hold_booking",
            status="cancelled",
            summary="cancelled without a write",
        )

    def session_snapshot(self, session_id, identity_token):
        del session_id, identity_token
        if self.snapshot_error is not None:
            raise self.snapshot_error
        return JourneyView(phase="ready", active_booking_id="RSV-API-1")

    def session_projection(self, session_id, identity_token):
        journey = self.session_snapshot(session_id, identity_token)
        return SessionProjection(
            journey=journey,
            actions=[
                ActionCard(
                    action_id="checkpoint-api",
                    step_id="restore",
                    tool="journey.signed_checkpoint",
                    title="Restored state",
                    status="succeeded",
                    effect="read",
                    summary="Owner-scoped projection.",
                )
            ],
        )

    def stay_brief(self, session_id, identity_token):
        del session_id, identity_token
        return "<!doctype html><html><body>Owner brief</body></html>"

    def audit_events(self, session_id, identity_token):
        del session_id
        self.audit_token = identity_token
        return []

    def close(self) -> None:
        self.closed = True


class ApiBoundaryTests(unittest.TestCase):
    def test_mounted_application_serves_api_and_gradio_root(self) -> None:
        with TemporaryDirectory() as directory:
            settings = Settings(
                project_root=PROJECT_ROOT,
                model_base_url="http://127.0.0.1:8000/v1",
                model_name="deterministic-test",
                model_api_key="local-only",
                model_timeout_seconds=5.0,
                database_path=Path(directory) / "radeonstay.db",
                policy_dir=PROJECT_ROOT / "data" / "policies",
                audit_secret="mounted-application-audit-secret",
                identity_secret="mounted-application-identity-secret",
                deterministic_mode=True,
                host="127.0.0.1",
                port=7860,
                public_demo_enabled=False,
                ui_username="",
                ui_password="",
            )
            application = create_application(settings)
            with TestClient(application) as client:
                health = client.get("/health")
                live = client.get("/health/live")
                ready = client.get("/health/ready")
                root = client.get("/")

                self.assertEqual(health.status_code, 200)
                self.assertTrue(health.json()["ok"])
                self.assertEqual(live.status_code, 200)
                self.assertEqual(live.json()["status"], "live")
                self.assertEqual(ready.status_code, 200)
                self.assertEqual(ready.json()["status"], "ready")
                self.assertEqual(root.status_code, 200)
                self.assertIn("checks", application.state.startup_preflight)

    def test_liveness_is_independent_and_readiness_fails_with_503(self) -> None:
        service = StubService()
        service.health_payload = {
            "ok": False,
            "database": {"ok": True},
            "model": {"ok": False},
        }
        with TestClient(create_api(service)) as client:
            live = client.get("/health/live")
            self.assertEqual(live.status_code, 200)
            self.assertEqual(service.health_calls, 0)

            ready = client.get("/health/ready")
            legacy = client.get("/health")
            self.assertEqual(ready.status_code, 503)
            self.assertEqual(ready.json()["status"], "not_ready")
            self.assertEqual(legacy.status_code, 503)

    def test_readiness_bounds_unexpected_health_errors(self) -> None:
        service = StubService()
        service.health_error = RuntimeError("private health detail")
        with TestClient(create_api(service)) as client:
            response = client.get("/health/ready")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"], {"type": "RuntimeError"})
        self.assertNotIn("private health detail", response.text)

    def test_audit_identity_is_header_only_and_lifespan_closes_service(self) -> None:
        service = StubService()
        token = "x" * 32
        with TestClient(create_api(service)) as client:
            accepted = client.get(
                "/v1/audit/session-1",
                headers={"X-Identity-Token": token},
            )
            rejected = client.get(
                f"/v1/audit/session-1?identity_token={token}"
            )
            invalid_session = client.get(
                "/v1/audit/not%20a%20session",
                headers={"X-Identity-Token": token},
            )
            self.assertEqual(accepted.status_code, 200)
            self.assertEqual(rejected.status_code, 422)
            self.assertEqual(invalid_session.status_code, 422)
            self.assertEqual(service.audit_token, token)
        self.assertTrue(service.closed)

    def test_domain_permission_and_validation_errors_are_not_500(self) -> None:
        service = StubService()
        payload = {
            "session_id": "session-1",
            "request_id": "request-1",
            "identity_token": "x" * 32,
            "message": "hello",
        }
        with TestClient(create_api(service)) as client:
            service.chat_error = PermissionDenied("session denied")
            denied = client.post("/v1/chat", json=payload)
            self.assertEqual(denied.status_code, 403)

            service.chat_error = ValidationError("bad plan")
            invalid = client.post("/v1/chat", json=payload)
            self.assertEqual(invalid.status_code, 422)

            service.chat_error = ModelClientError("private transport detail")
            unavailable = client.post("/v1/chat", json=payload)
            self.assertEqual(unavailable.status_code, 503)
            self.assertEqual(unavailable.json()["detail"], "Local model is unavailable")

    def test_domain_error_details_are_recursively_redacted_at_http_boundary(self) -> None:
        service = StubService()
        private_key = "must-never-cross-http"
        payload = {
            "session_id": "session-1",
            "request_id": "request-1",
            "identity_token": "i" * 32,
            "message": "hello",
        }
        service.chat_error = PermissionDenied(
            f"request refused: api_key={private_key} Authorization: Bearer bearer-secret"
        )

        with TestClient(create_api(service)) as client:
            response = client.post("/v1/chat", json=payload)

        self.assertEqual(response.status_code, 403)
        self.assertIn("api_key=[REDACTED]", response.text)
        self.assertIn("Bearer [REDACTED]", response.text)
        self.assertNotIn(private_key, response.text)
        self.assertNotIn("bearer-secret", response.text)

    def test_action_only_confirm_cancel_resume_and_brief_endpoints(self) -> None:
        service = StubService()
        token = "i" * 32
        with TestClient(create_api(service)) as client:
            confirmed = client.post(
                "/v1/confirm",
                json={
                    "session_id": "session-1",
                    "identity_token": token,
                    "action_id": "act-1",
                },
            )
            cancelled = client.post(
                "/v1/actions/cancel",
                json={
                    "session_id": "session-1",
                    "identity_token": token,
                    "action_id": "act-2",
                },
            )
            resumed = client.get(
                "/v1/sessions/session-1",
                headers={"X-Identity-Token": token},
            )
            brief = client.get(
                "/v1/sessions/session-1/brief",
                headers={"X-Identity-Token": token},
            )
            projection = client.get(
                "/v1/sessions/session-1/projection",
                headers={"X-Identity-Token": token},
            )

        self.assertEqual(confirmed.status_code, 200)
        self.assertEqual(service.last_confirm.action_id, "act-1")
        self.assertIsNone(service.last_confirm.confirmation_token)
        self.assertEqual(cancelled.status_code, 200)
        self.assertEqual(service.last_cancel.action_id, "act-2")
        self.assertIsNone(service.last_cancel.confirmation_token)
        self.assertEqual(resumed.json()["active_booking_id"], "RSV-API-1")
        self.assertEqual(brief.status_code, 200)
        self.assertIn("Owner brief", brief.text)
        self.assertEqual(projection.status_code, 200)
        self.assertEqual(projection.json()["journey"]["active_booking_id"], "RSV-API-1")
        self.assertEqual(projection.json()["actions"][0]["status"], "succeeded")
        for response in (confirmed, cancelled, resumed, brief, projection):
            self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(
            brief.headers["content-disposition"],
            'attachment; filename="radeonstay-stay-brief.html"',
        )
        self.assertEqual(brief.headers["x-content-type-options"], "nosniff")
        self.assertIn(
            "default-src 'none'",
            brief.headers["content-security-policy"],
        )
        self.assertIn(
            "frame-ancestors 'none'",
            brief.headers["content-security-policy"],
        )

    def test_validation_errors_do_not_echo_identity_or_confirmation_tokens(self) -> None:
        service = StubService()
        identity_token = "identity-secret-19"
        confirmation_token = "confirm-secret-19x"
        with TestClient(create_api(service)) as client:
            invalid_chat = client.post(
                "/v1/chat",
                json={
                    "session_id": "session-1",
                    "request_id": "request-1",
                    "identity_token": identity_token,
                    "message": "hello",
                },
            )
            invalid_confirm = client.post(
                "/v1/confirm",
                json={
                    "session_id": "session-1",
                    "identity_token": "i" * 32,
                    "confirmation_token": confirmation_token,
                },
            )

        for response, secret in (
            (invalid_chat, identity_token),
            (invalid_confirm, confirmation_token),
        ):
            self.assertEqual(response.status_code, 422)
            self.assertEqual(response.headers["cache-control"], "no-store")
            self.assertNotIn(secret, response.text)
            self.assertNotIn(secret, repr(dict(response.headers)))
            errors = response.json()["detail"]
            self.assertTrue(errors)
            self.assertTrue(
                all(set(error) == {"loc", "type", "msg"} for error in errors)
            )
        self.assertNotIn("identity_token", invalid_chat.text)
        self.assertNotIn("confirmation_token", invalid_confirm.text)

    def test_session_snapshot_distinguishes_missing_from_forbidden(self) -> None:
        service = StubService()
        token = "i" * 32
        with TestClient(create_api(service)) as client:
            service.snapshot_error = NotFoundError("session not found")
            missing = client.get(
                "/v1/sessions/missing-session",
                headers={"X-Identity-Token": token},
            )

            service.snapshot_error = PermissionDenied("session denied")
            forbidden = client.get(
                "/v1/sessions/owned-by-another-user",
                headers={"X-Identity-Token": token},
            )

        self.assertEqual(missing.status_code, 404)
        self.assertEqual(forbidden.status_code, 403)
        self.assertEqual(missing.headers["cache-control"], "no-store")
        self.assertEqual(forbidden.headers["cache-control"], "no-store")

    def test_chat_response_contract_has_no_confirmation_capability(self) -> None:
        service = StubService()
        plan = AgentPlan(
            objective="Preview one safe write",
            steps=[
                PlanStep(
                    step_id="write",
                    tool="hotel.hold_booking",
                    reason="preview",
                )
            ],
        )
        service.chat_response = AgentResponse(
            session_id="session-1",
            request_id="request-1",
            answer="Preview ready",
            plan=plan,
            receipts=[
                ToolReceipt(
                    step_id="write",
                    tool="hotel.hold_booking",
                    status="pending_confirmation",
                    summary="safe preview",
                )
            ],
            pending_actions=[
                PendingAction(
                    action_id="act-1",
                    step_id="write",
                    session_id="session-1",
                    tool="hotel.hold_booking",
                    arguments={},
                    preview="safe preview",
                    expires_at="2030-01-01T00:00:00+00:00",
                )
            ],
            model_backend="local-test",
            elapsed_ms=1.0,
        )
        with TestClient(create_api(service)) as client:
            response = client.post(
                "/v1/chat",
                json={
                    "session_id": "session-1",
                    "request_id": "request-1",
                    "identity_token": "i" * 32,
                    "message": "preview",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn('"confirmation_token"', response.text)
        self.assertNotIn('"token"', response.text)
        self.assertNotIn("token", PendingAction.model_fields)
        self.assertEqual(response.json()["pending_actions"][0]["action_id"], "act-1")

    def test_chat_response_recursively_redacts_secrets_embedded_in_text(self) -> None:
        service = StubService()
        secret = "private-value-that-must-not-cross-http"
        plan = AgentPlan(
            objective=f"Reject synthetic_api_key={secret}",
            steps=[
                PlanStep(
                    step_id="refuse",
                    tool="refuse_request",
                    reason=f"Authorization: Bearer {secret}",
                )
            ],
        )
        service.chat_response = AgentResponse(
            session_id="session-1",
            request_id="request-1",
            answer=f"Refused api_key={secret}; private_key={secret}",
            plan=plan,
            receipts=[
                ToolReceipt(
                    step_id="refuse",
                    tool="refuse_request",
                    status="denied",
                    summary=f"password={secret}; ssh_key={secret}",
                    data={
                        "nested": {
                            "private_key": secret,
                            "ssh-key": secret,
                        },
                        "prompt_tokens": 17,
                    },
                )
            ],
            model_backend="local-test",
            elapsed_ms=1.0,
        )

        with TestClient(create_api(service)) as client:
            response = client.post(
                "/v1/chat",
                json={
                    "session_id": "session-1",
                    "request_id": "request-1",
                    "identity_token": "i" * 32,
                    "message": "privacy boundary",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(secret, response.text)
        self.assertGreaterEqual(response.text.count("[REDACTED]"), 8)
        self.assertEqual(response.json()["receipts"][0]["data"]["prompt_tokens"], 17)


if __name__ == "__main__":
    unittest.main()
