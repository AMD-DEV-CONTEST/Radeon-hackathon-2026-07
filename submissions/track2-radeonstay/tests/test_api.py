from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from radeonstay.api import create_api
from radeonstay.config import Settings
from radeonstay.domain import PermissionDenied, ValidationError
from radeonstay.main import create_application


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class StubService:
    def __init__(self) -> None:
        self.chat_error: Exception | None = None
        self.confirm_error: Exception | None = None
        self.audit_token: str | None = None
        self.closed = False

    def health(self):
        return {"ok": True}

    def chat(self, request):
        del request
        if self.chat_error is not None:
            raise self.chat_error
        raise AssertionError("success response is not needed by this API mapping test")

    def confirm(self, request):
        del request
        if self.confirm_error is not None:
            raise self.confirm_error
        raise AssertionError("success response is not needed by this API mapping test")

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
            with TestClient(create_application(settings)) as client:
                health = client.get("/health")
                root = client.get("/")

                self.assertEqual(health.status_code, 200)
                self.assertTrue(health.json()["ok"])
                self.assertEqual(root.status_code, 200)

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


if __name__ == "__main__":
    unittest.main()
