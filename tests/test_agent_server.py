import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from incident_commander.agent import InvestigationService
from incident_commander.analyzer import IncidentAnalyzer
from incident_commander.server import Handler
from incident_commander.store import SessionStore


SAMPLE = Path(__file__).parent.parent / "samples" / "checkout-latency.json"


class OfflineClient:
    def choose_tool(self, *args, **kwargs):
        raise RuntimeError("offline")

    def complete(self, *args, **kwargs):
        raise RuntimeError("offline")


class AgentAPITests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        Handler.analyzer = IncidentAnalyzer()
        Handler.agent_service = InvestigationService(
            SessionStore(Path(self.temp.name)),
            client=OfflineClient(),
            runtime={"mode": "offline-safe", "degraded": False},
        )
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def request(self, method: str, path: str, payload: dict | None = None) -> tuple[int, dict]:
        data = None if payload is None else json.dumps(payload).encode()
        request = urllib.request.Request(
            self.base_url + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code, json.load(exc)

    def test_create_get_and_next_routes_use_success_envelope(self) -> None:
        incident = json.loads(SAMPLE.read_text(encoding="utf-8"))
        status, created = self.request(
            "POST", "/api/investigations", {"request_id": "api-create", "incident": incident}
        )
        investigation = created["investigation"]

        self.assertEqual(status, 200)
        self.assertEqual(created["schema_version"], 1)
        status, advanced = self.request(
            "POST",
            f"/api/investigations/{investigation['id']}/next",
            {"request_id": "api-next", "expected_version": investigation["version"]},
        )
        self.assertEqual(status, 200)
        self.assertEqual(advanced["investigation"]["version"], 2)
        status, fetched = self.request("GET", f"/api/investigations/{investigation['id']}")
        self.assertEqual(status, 200)
        self.assertEqual(fetched["investigation"]["version"], 2)

    def test_version_conflict_returns_structured_409(self) -> None:
        incident = json.loads(SAMPLE.read_text(encoding="utf-8"))
        _, created = self.request("POST", "/api/investigations", {"request_id": "conflict-create", "incident": incident})
        investigation = created["investigation"]

        status, error = self.request(
            "POST",
            f"/api/investigations/{investigation['id']}/next",
            {"request_id": "conflict-next", "expected_version": 99},
        )

        self.assertEqual(status, 409)
        self.assertEqual(error["code"], "version_conflict")

    def test_messages_and_decisions_are_available_over_http(self) -> None:
        incident = json.loads(SAMPLE.read_text(encoding="utf-8"))
        _, response = self.request("POST", "/api/investigations", {"request_id": "flow-create", "incident": incident})
        investigation = response["investigation"]
        for index in range(4):
            _, response = self.request(
                "POST",
                f"/api/investigations/{investigation['id']}/next",
                {"request_id": f"flow-next-{index}", "expected_version": investigation["version"]},
            )
            investigation = response["investigation"]

        status, response = self.request(
            "POST",
            f"/api/investigations/{investigation['id']}/messages",
            {"request_id": "flow-message", "expected_version": investigation["version"], "content": "Why not expand the pool?"},
        )
        self.assertEqual(status, 200)
        investigation = response["investigation"]
        action = investigation["proposed_actions"][0]
        status, response = self.request(
            "POST",
            f"/api/investigations/{investigation['id']}/actions/{action['id']}/decision",
            {"request_id": "flow-decision", "expected_version": investigation["version"], "decision": "approved"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(response["investigation"]["proposed_actions"][0]["approval_status"], "approved")


if __name__ == "__main__":
    unittest.main()
