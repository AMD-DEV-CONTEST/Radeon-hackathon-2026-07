import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

from privateops.agent import PrivateOpsAgent
from privateops.models import ToolResult
from privateops.server import build_agent_from_env, create_app, create_http_server


class ConfiguredTestProvider:
    name = "configured-test-model"

    def complete(self, prompt, evidence, memory, execution_context=None):
        return "已配置模型回答"


class ServerContractTests(unittest.TestCase):
    def test_chat_requires_a_configured_model_provider(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            knowledge = root / "knowledge"
            knowledge.mkdir()
            agent = PrivateOpsAgent(knowledge_dir=knowledge, state_dir=root / "state", workspace_dir=root)
            server = create_http_server(create_app(agent), port=0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                request = urllib.request.Request(
                    f"http://127.0.0.1:{server.server_address[1]}/api/chat",
                    data=json.dumps({"prompt": "review local evidence"}).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(request)
                self.assertEqual(caught.exception.code, 409)
                self.assertEqual(json.loads(caught.exception.read())["error"]["code"], "provider_required")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_live_api_deletes_exact_audit_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            knowledge = root / "knowledge"
            knowledge.mkdir()
            agent = PrivateOpsAgent(knowledge_dir=knowledge, state_dir=root / "state", workspace_dir=root)
            first = agent.ask("first disposable audit").audit_id
            second = agent.ask("second retained audit").audit_id
            server = create_http_server(create_app(agent), port=0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_address[1]}"
            try:
                request = urllib.request.Request(base + f"/api/audit/{first}", method="DELETE")
                deleted = json.loads(urllib.request.urlopen(request).read())
                audit = json.loads(urllib.request.urlopen(base + "/api/audit").read())

                self.assertEqual(deleted, {"deleted": first})
                self.assertEqual([entry["audit_id"] for entry in audit["entries"]], [second])

                malformed = urllib.request.Request(base + "/api/audit/not-valid", method="DELETE")
                with self.assertRaises(urllib.error.HTTPError) as invalid:
                    urllib.request.urlopen(malformed)
                self.assertEqual(invalid.exception.code, 400)

                missing = urllib.request.Request(base + "/api/audit/audit-000000000000", method="DELETE")
                with self.assertRaises(urllib.error.HTTPError) as unknown:
                    urllib.request.urlopen(missing)
                self.assertEqual(unknown.exception.code, 404)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_startup_query_returns_observed_system_tool_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            knowledge = root / "knowledge"
            knowledge.mkdir()
            agent = PrivateOpsAgent(knowledge_dir=knowledge, state_dir=root / "state", workspace_dir=root)
            agent.provider = ConfiguredTestProvider()

            class FakeInspector:
                def collect(self, name):
                    return ToolResult(
                        name,
                        "completed",
                        "Observed 1 Windows startup entry.",
                        {"entries": [{"name": "RealUpdater", "source": "registry"}], "count": 1, "truncated": False},
                    )

            agent.tools.system_inspector = FakeInspector()
            server = create_http_server(create_app(agent), port=0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                request = urllib.request.Request(
                    f"http://127.0.0.1:{server.server_address[1]}/api/chat",
                    data=json.dumps({"prompt": "查看一下本机的开机自启有啥？", "response_language": "zh-CN"}, ensure_ascii=False).encode("utf-8"),
                    headers={"Content-Type": "application/json; charset=utf-8"},
                    method="POST",
                )
                chat = json.loads(urllib.request.urlopen(request).read().decode("utf-8"))
                audit = json.loads(urllib.request.urlopen(
                    f"http://127.0.0.1:{server.server_address[1]}/api/audit"
                ).read().decode("utf-8"))

                self.assertEqual(chat["tool_results"][0]["name"], "startup_inventory")
                self.assertEqual(chat["tool_results"][0]["output"]["entries"][0]["name"], "RealUpdater")
                self.assertEqual(audit["entries"][0]["tool_results"][0]["name"], "startup_inventory")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_app_exposes_page_and_api_routes(self):
        app = create_app()
        routes = {route.path for route in app.routes}

        self.assertIn("/", routes)
        self.assertIn("/api/health", routes)
        self.assertIn("/api/chat", routes)
        self.assertIn("/api/search", routes)
        self.assertIn("/api/memory", routes)
        self.assertIn("/api/permission", routes)
        self.assertIn("/api/rocm-profile", routes)
        self.assertIn("/api/rocm-evidence", routes)
        self.assertIn("/api/audit", routes)
        self.assertIn("/api/status", routes)
        self.assertIn("/api/confirm", routes)
        self.assertIn("/api/benchmarks", routes)
        self.assertIn("/api/audit/export", routes)
        self.assertIn("/api/benchmarks/export.csv", routes)
        self.assertIn("/api/provider/test", routes)
        self.assertIn("/api/provider/config", routes)

    @patch("privateops.server.RadeonEvidenceStore.summary")
    def test_live_rocm_evidence_route_is_read_only(self, summary):
        summary.return_value = {
            "available": True,
            "verification": "verified",
            "instance_id": "u-safe-test",
            "metrics": {"latency_ms": 1511.072},
        }
        server = create_http_server(create_app(), port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            body = urllib.request.urlopen(
                f"http://127.0.0.1:{server.server_address[1]}/api/rocm-evidence"
            ).read().decode("utf-8")
            payload = json.loads(body)

            self.assertTrue(payload["available"])
            self.assertEqual(payload["instance_id"], "u-safe-test")
            lowered = body.lower()
            self.assertNotIn("api_key", lowered)
            self.assertNotIn("credential", lowered)
            self.assertNotIn("token", lowered)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_build_agent_from_env_enables_rocm_provider(self):
        with patch.dict(
            "os.environ",
            {
                "PRIVATEOPS_PROVIDER_MODE": "rocm-local",
                "PRIVATEOPS_MODEL_ENDPOINT": "http://127.0.0.1:8000/v1/chat/completions",
            },
            clear=True,
        ):
            agent = build_agent_from_env()

        self.assertEqual(agent.provider.name, "openai-compatible-rocm")

    def test_live_api_supports_status_chat_exports_and_stable_json_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            knowledge = root / "knowledge"
            knowledge.mkdir()
            (knowledge / "proof.md").write_text("PrivateOps uses local evidence and audit controls.", encoding="utf-8")
            agent = PrivateOpsAgent(knowledge_dir=knowledge, state_dir=root / "state", workspace_dir=root)
            agent.provider = ConfiguredTestProvider()
            server = create_http_server(create_app(agent), port=0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_address[1]}"
            try:
                status = json.loads(urllib.request.urlopen(base + "/api/status").read())
                self.assertEqual(status["provider_mode"], "development")
                self.assertFalse(status["competition_eligible"])
                self.assertEqual(status["agent_framework"], "LangChain Core")
                self.assertEqual(status["core_inference_location"], "same-instance loopback")

                request = urllib.request.Request(
                    base + "/api/chat",
                    data=json.dumps({"prompt": "review local evidence", "response_language": "zh-CN"}).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                chat = json.loads(urllib.request.urlopen(request).read())
                self.assertTrue(chat["audit_id"].startswith("audit-"))
                self.assertEqual(len(chat["plan"]), 3)
                self.assertEqual(chat["answer"], "已配置模型回答")

                audit = json.loads(urllib.request.urlopen(base + "/api/audit/export").read())
                self.assertEqual(audit["schema_version"], "1.0")

                malformed = urllib.request.Request(
                    base + "/api/chat",
                    data=b"{bad",
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(malformed)
                self.assertEqual(caught.exception.code, 400)
                error = json.loads(caught.exception.read())
                self.assertEqual(error["error"]["code"], "invalid_json")

                oversized = urllib.request.Request(
                    base + "/api/chat",
                    data=b"x" * 1_048_577,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with self.assertRaises(urllib.error.HTTPError) as too_large:
                    urllib.request.urlopen(oversized)
                self.assertEqual(too_large.exception.code, 413)
                self.assertEqual(json.loads(too_large.exception.read())["error"]["code"], "payload_too_large")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_provider_failure_returns_stable_502_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            knowledge = root / "knowledge"
            knowledge.mkdir()
            agent = PrivateOpsAgent(knowledge_dir=knowledge, state_dir=root / "state", workspace_dir=root)

            class FailingProvider:
                name = "failing-local-model"

                def complete(self, prompt, evidence, memory, execution_context=None):
                    raise OSError("model server unavailable")

            agent.provider = FailingProvider()
            server = create_http_server(create_app(agent), port=0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                request = urllib.request.Request(
                    f"http://127.0.0.1:{server.server_address[1]}/api/chat",
                    data=json.dumps({"prompt": "review evidence"}).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(request)
                self.assertEqual(caught.exception.code, 502)
                self.assertEqual(json.loads(caught.exception.read())["error"]["code"], "provider_unavailable")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
