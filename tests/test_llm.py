import io
import json
import unittest
from unittest.mock import patch

from incident_commander.llm import OpenAICompatibleClient
from incident_commander import AIIncidentAnalyzer, Incident
from incident_commander.llm import LLMResult
from pathlib import Path


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class LLMClientTests(unittest.TestCase):
    @patch("urllib.request.urlopen")
    def test_parses_native_tool_call(self, urlopen) -> None:
        urlopen.return_value = FakeResponse(
            json.dumps(
                {
                    "model": "test-model",
                    "choices": [
                        {
                            "message": {
                                "tool_calls": [
                                    {
                                        "function": {
                                            "name": "search_logs",
                                            "arguments": '{"service":"checkout-api","query":"timeout"}',
                                        }
                                    }
                                ]
                            }
                        }
                    ],
                    "usage": {"total_tokens": 12},
                }
            ).encode()
        )
        client = OpenAICompatibleClient(base_url="https://example.test/v1", model="test-model")

        result = client.choose_tool("system", "user", [{"type": "function", "function": {"name": "search_logs"}}])

        sent = json.loads(urlopen.call_args.args[0].data)
        self.assertEqual(sent["tool_choice"], "auto")
        self.assertEqual(result.name, "search_logs")
        self.assertEqual(result.arguments["query"], "timeout")

    @patch("urllib.request.urlopen")
    def test_sends_bearer_token_and_parses_usage(self, urlopen) -> None:
        urlopen.return_value = FakeResponse(
            json.dumps(
                {
                    "model": "test-model",
                    "choices": [{"message": {"content": "ok"}}],
                    "usage": {"total_tokens": 3},
                }
            ).encode()
        )
        client = OpenAICompatibleClient(
            base_url="https://example.test/v1",
            model="test-model",
            api_key="secret",
        )

        result = client.complete("system", "user")

        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), "Bearer secret")
        self.assertEqual(result.content, "ok")
        self.assertEqual(result.usage["total_tokens"], 3)

    def test_hybrid_analyzer_preserves_citations(self) -> None:
        class StubClient:
            def complete(self, system, user, max_tokens=256):
                return LLMResult("Model commander brief.", 12.5, "stub", {"total_tokens": 9})

        sample = Path(__file__).parent.parent / "samples" / "checkout-latency.json"
        incident = Incident.from_dict(json.loads(sample.read_text()))
        report = AIIncidentAnalyzer(StubClient()).analyze(incident)

        self.assertEqual(report.executive_summary, "Model commander brief.")
        self.assertEqual(report.metadata["engine"], "hybrid-radeon-llm")
        self.assertTrue(all(hypothesis.evidence_ids for hypothesis in report.hypotheses))

    def test_hybrid_analyzer_falls_back_on_model_error(self) -> None:
        class FailingClient:
            def complete(self, system, user, max_tokens=256):
                raise RuntimeError("offline")

        sample = Path(__file__).parent.parent / "samples" / "checkout-latency.json"
        incident = Incident.from_dict(json.loads(sample.read_text()))
        report = AIIncidentAnalyzer(FailingClient()).analyze(incident)

        self.assertEqual(report.metadata["engine"], "deterministic-baseline")
        self.assertIn("offline", report.metadata["llm_fallback"])

    @patch("urllib.request.urlopen")
    def test_rejects_empty_model_content(self, urlopen) -> None:
        urlopen.return_value = FakeResponse(
            json.dumps({"choices": [{"message": {"content": None}}]}).encode()
        )
        client = OpenAICompatibleClient(base_url="https://example.test/v1", model="test")
        with self.assertRaisesRegex(RuntimeError, "no user-visible content"):
            client.complete("system", "user")

    @patch("urllib.request.urlopen")
    def test_streaming_records_ttft_content_and_usage(self, urlopen) -> None:
        urlopen.return_value = FakeResponse(
            b'data: {"model":"test-model","choices":[{"delta":{"content":"safe "}}]}\n\n'
            b'data: {"choices":[{"delta":{"content":"rollback"}}]}\n\n'
            b'data: {"choices":[],"usage":{"completion_tokens":2}}\n\n'
            b'data: [DONE]\n\n'
        )
        client = OpenAICompatibleClient(base_url="https://example.test/v1", model="test-model")

        result = client.stream_complete("system", "user")

        request = urlopen.call_args.args[0]
        sent = json.loads(request.data)
        self.assertTrue(sent["stream"])
        self.assertEqual(result.content, "safe rollback")
        self.assertEqual(result.model, "test-model")
        self.assertEqual(result.usage["completion_tokens"], 2)
        self.assertGreaterEqual(result.latency_ms, result.ttft_ms)


if __name__ == "__main__":
    unittest.main()
