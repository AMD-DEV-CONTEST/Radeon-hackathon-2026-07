from __future__ import annotations

import io
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Mapping

from prooflaunch_remix.v10_contracts import EvidenceClass, V10ContractError
from prooflaunch_remix.v10_submission_api import (
    AgencyEvalRecord,
    AgencyLaunchRequest,
    AgencyRunStore,
    ModelCard,
    make_server,
)


SHA = "a" * 64


def launch_payload(suffix: str = "001") -> dict[str, object]:
    return {
        "request_id": f"request-{suffix}",
        "campaign_id": f"campaign-{suffix}",
        "objective": "Create an evidence-led synthetic launch bundle",
        "required_capabilities": ["strategy", "copy", "safety"],
        "input_artifacts": {"brief": SHA},
        "maximum_actions": 12,
        "maximum_cost_usd": 0,
        "created_at": "2026-07-31T12:00:00Z",
        "human_release_required": True,
        "data_class": "synthetic",
    }


def model_card() -> ModelCard:
    return ModelCard(
        model_id="fixture-model",
        revision="revision-001",
        role="mechanical-test-only",
        capabilities=("schema",),
        limitations=("not neural quality evidence",),
        training_data_manifest_sha256=None,
        evaluation_record_ids=(),
        radeon_execution_evidence=None,
        promotion_status="planned",
        created_at="2026-07-31T12:00:00Z",
    )


def eval_record() -> AgencyEvalRecord:
    return AgencyEvalRecord(
        eval_id="eval-001",
        model_id="fixture-model",
        model_revision="revision-001",
        benchmark_id="fixture-benchmark",
        benchmark_sha256=SHA,
        metrics={"overall": 0.75, "schema": 1.0},
        raw_counts={"passed": 3, "possible": 4},
        evidence_class=EvidenceClass.SIMULATED,
        evidence_locator="fixture://eval",
        observed_at="2026-07-31T12:00:00Z",
        blinded=True,
    )


class SubmissionContractTests(unittest.TestCase):
    def test_launch_request_is_hash_bound_and_requires_human_release(self) -> None:
        request = AgencyLaunchRequest(
            request_id="request-001",
            campaign_id="campaign-001",
            objective="Synthetic launch",
            required_capabilities=("strategy",),
            input_artifacts={"brief": SHA},
            maximum_actions=5,
            maximum_cost_usd=0,
            created_at="2026-07-31T12:00:00Z",
        )
        self.assertEqual(len(request.digest), 64)
        with self.assertRaises(V10ContractError):
            AgencyLaunchRequest(
                **{**request.__dict__, "human_release_required": False}
            )

    def test_model_and_eval_cards_keep_planned_fixture_truth_boundary(self) -> None:
        self.assertEqual(len(model_card().digest), 64)
        self.assertEqual(len(eval_record().digest), 64)
        with self.assertRaises(V10ContractError):
            ModelCard(
                **{
                    **model_card().__dict__,
                    "promotion_status": "promoted",
                }
            )


class SubmissionApiIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp = tempfile.TemporaryDirectory()
        web_root = Path(cls.temp.name)
        (web_root / "index.html").write_text(
            "<!doctype html><title>ProofLaunch API</title>", encoding="utf-8"
        )
        (web_root / "styles.css").write_text("body{color:black}", encoding="utf-8")
        (web_root / "app.js").write_text("document.documentElement.dataset.ready='1'", encoding="utf-8")
        cls.store = AgencyRunStore(
            model_cards=(model_card(),), eval_records=(eval_record(),)
        )
        cls.server = make_server(
            "127.0.0.1", 0, store=cls.store, web_root=web_root
        )
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)
        cls.temp.cleanup()

    @classmethod
    def request(
        cls, method: str, path: str, payload: object | None = None
    ) -> tuple[int, bytes, Mapping[str, str]]:
        body = None
        headers = {}
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            cls.base + path, data=body, method=method, headers=headers
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, response.read(), dict(response.headers)
        except urllib.error.HTTPError as error:
            return error.code, error.read(), dict(error.headers)

    def create_run(self) -> str:
        status, body, _ = self.request(
            "POST", "/v1/runs", launch_payload(self._testMethodName)
        )
        self.assertEqual(status, 201)
        return json.loads(body)["run_id"]

    def test_single_port_serves_ui_create_status_and_idempotency(self) -> None:
        status, body, headers = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"ProofLaunch API", body)
        self.assertIn("text/html", headers["Content-Type"])
        status, _, headers = self.request("GET", "/styles.css")
        self.assertEqual(status, 200)
        self.assertIn("text/css", headers["Content-Type"])
        status, _, headers = self.request("GET", "/app.js")
        self.assertEqual(status, 200)
        self.assertIn("javascript", headers["Content-Type"])
        status, body, _ = self.request("GET", "/workspace/evidence")
        self.assertEqual(status, 200)
        self.assertIn(b"ProofLaunch API", body)
        first = self.create_run()
        second = self.create_run()
        self.assertEqual(first, second)
        status, body, _ = self.request("GET", f"/v1/runs/{first}")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["status"], "awaiting_approval")

    def test_health_truthfully_separates_control_plane_from_radeon_and_model_execution(self) -> None:
        status, body, headers = self.request("GET", "/v1/health")
        self.assertEqual(status, 200)
        self.assertIn("application/json", headers["Content-Type"])
        health = json.loads(body)
        self.assertTrue(health["api_connected"])
        self.assertEqual(health["execution_mode"], "mechanical_fixture_only")
        self.assertFalse(health["radeon_connected"])
        self.assertFalse(health["radeon_metrics_observed"])
        self.assertFalse(health["model_inference_observed"])
        self.assertFalse(health["external_release_enabled"])

    def test_all_workstream_24_control_routes_are_served_by_the_same_port(self) -> None:
        routes = (
            "/control/world-state", "/control/trajectory", "/control/topology",
            "/control/memory", "/control/distillation", "/control/training",
            "/control/audit", "/control/repair", "/control/human-gate",
            "/control/images", "/control/videos", "/control/landing",
            "/control/email", "/control/ledger", "/control/performance",
        )
        for route in routes:
            with self.subTest(route=route):
                status, body, headers = self.request("GET", route)
                self.assertEqual(status, 200)
                self.assertIn("text/html", headers["Content-Type"])
                self.assertIn(b"ProofLaunch API", body)

    def test_sse_stream_exposes_ordered_run_events(self) -> None:
        run_id = self.create_run()
        status, body, headers = self.request("GET", f"/v1/runs/{run_id}/events")
        self.assertEqual(status, 200)
        self.assertIn("text/event-stream", headers["Content-Type"])
        self.assertIn(b"event: run_created", body)
        self.assertIn(b"id: 1", body)

    def test_bundle_is_blocked_until_human_approval_then_is_auditable_zip(self) -> None:
        run_id = self.create_run()
        status, _, _ = self.request("GET", f"/v1/runs/{run_id}/bundle")
        self.assertEqual(status, 409)
        status, body, _ = self.request(
            "POST",
            f"/v1/runs/{run_id}/approvals",
            {
                "decision": "approve",
                "approver": "human-reviewer",
                "decided_at": "2026-07-31T12:30:00Z",
                "reason": "synthetic fixture mechanics approved",
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["status"], "bundle_ready")
        status, body, headers = self.request("GET", f"/v1/runs/{run_id}/bundle")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "application/zip")
        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            self.assertEqual(
                set(archive.namelist()),
                {"request.json", "run.json", "events.jsonl", "evidence-ledger.json"},
            )
            ledger = json.loads(archive.read("evidence-ledger.json"))
            self.assertFalse(ledger["external_release_executed"])

    def test_model_cards_and_eval_leaderboard_are_evidence_labeled(self) -> None:
        status, body, _ = self.request("GET", "/v1/model-cards")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["model_cards"][0]["promotion_status"], "planned")
        status, body, _ = self.request("GET", "/v1/evals/leaderboard")
        self.assertEqual(status, 200)
        row = json.loads(body)["leaderboard"][0]
        self.assertEqual(row["evidence_class"], "simulated")
        self.assertTrue(row["blinded"])

    def test_invalid_launch_and_unknown_run_fail_closed(self) -> None:
        invalid = launch_payload(self._testMethodName)
        invalid["human_release_required"] = False
        status, _, _ = self.request("POST", "/v1/runs", invalid)
        self.assertEqual(status, 400)
        invalid["human_release_required"] = "false"
        status, _, _ = self.request("POST", "/v1/runs", invalid)
        self.assertEqual(status, 400)
        status, _, _ = self.request("GET", "/v1/runs/run-000000000000000000000000")
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
