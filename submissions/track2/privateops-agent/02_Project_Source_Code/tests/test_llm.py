import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from privateops.llm import DeterministicProvider, OpenAICompatibleProvider


class CompletionHandler(BaseHTTPRequestHandler):
    request_payload = {}
    response_body = json.dumps(
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "这是模型动态生成的回答。",
                    }
                }
            ]
        },
        ensure_ascii=False,
    ).encode("utf-8")

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        type(self).request_payload = json.loads(self.rfile.read(length).decode("utf-8"))
        data = type(self).response_body
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format, *args):
        pass


class ProviderRequestTests(unittest.TestCase):
    def test_deterministic_provider_uses_successful_tool_observations_without_rag(self):
        answer = DeterministicProvider().complete(
            "查看开机自启。\n\n请用中文回答。",
            [],
            {},
            {
                "tool_results": [
                    {
                        "name": "startup_inventory",
                        "status": "completed",
                        "summary": "Observed 8 startup entries.",
                        "output": {"count": 8},
                    }
                ]
            },
        )

        self.assertNotIn("未找到匹配的本地证据", answer)
        self.assertIn("startup_inventory", answer)
        self.assertIn("8", answer)

    def setUp(self):
        CompletionHandler.response_body = json.dumps(
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "这是模型动态生成的回答。",
                        }
                    }
                ]
            },
            ensure_ascii=False,
        ).encode("utf-8")

    def test_no_evidence_prompt_allows_general_reasoning(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), CompletionHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            provider = OpenAICompatibleProvider(
                endpoint=f"http://127.0.0.1:{server.server_address[1]}/v1/chat/completions",
                model="Qwen/Qwen2.5-7B-Instruct",
            )

            answer = provider.complete(
                "Configure startup for my application.\n\n请用中文回答。",
                [],
                {},
                {"permission": {"level": "confirm"}, "tool_results": []},
            )

            self.assertEqual(answer, "这是模型动态生成的回答。")
            messages = CompletionHandler.request_payload["messages"]
            self.assertTrue(
                messages[0]["content"].startswith(
                    "你必须只用简体中文回答，不得使用英文。"
                )
            )
            self.assertIn("general knowledge", messages[0]["content"])
            self.assertIn("Observed tool results are facts", messages[0]["content"])
            self.assertIn("Never claim that this computer was inspected", messages[0]["content"])
            self.assertIn("Do not infer missing or hidden items", messages[0]["content"])
            self.assertIn("Do not guess software purpose or safety from its name", messages[0]["content"])
            self.assertIn("confirm", messages[1]["content"])
            self.assertIn("请用中文回答。", messages[1]["content"])
            self.assertTrue(
                messages[1]["content"].endswith(
                    "Mandatory output language: Respond entirely in Simplified Chinese."
                )
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_system_tool_context_places_no_guessing_rule_next_to_observations(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), CompletionHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            provider = OpenAICompatibleProvider(
                endpoint=f"http://127.0.0.1:{server.server_address[1]}/v1/chat/completions",
                model="Qwen/Qwen2.5-7B-Instruct",
            )
            provider.complete(
                "查看开机自启。\n\n请用中文回答。",
                [],
                {},
                {
                    "permission": {"level": "safe"},
                    "tool_results": [
                        {
                            "name": "startup_inventory",
                            "status": "completed",
                            "output": {"entries": [{"name": "UnknownApp"}]},
                        }
                    ],
                },
            )

            user_content = CompletionHandler.request_payload["messages"][1]["content"]
            self.assertIn("Do not add a purpose, identity, safety, or risk description", user_content)
            self.assertIn("purpose and safety were not verified", user_content)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def _complete_with_response(self, response_body):
        CompletionHandler.response_body = response_body
        server = ThreadingHTTPServer(("127.0.0.1", 0), CompletionHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            provider = OpenAICompatibleProvider(
                endpoint=f"http://127.0.0.1:{server.server_address[1]}/v1/chat/completions",
                model="Qwen/Qwen2.5-7B-Instruct",
            )
            return provider.complete("Explain the result.", [], {}, {})
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_invalid_json_is_reported_as_stable_provider_failure(self):
        with self.assertRaisesRegex(OSError, "Model provider returned an invalid completion"):
            self._complete_with_response(b"not-json")

    def test_missing_choices_is_reported_as_stable_provider_failure(self):
        with self.assertRaisesRegex(OSError, "Model provider returned an invalid completion"):
            self._complete_with_response(json.dumps({"model": "Qwen"}).encode("utf-8"))

    def test_empty_message_is_reported_as_stable_provider_failure(self):
        response = {"choices": [{"message": {"role": "assistant", "content": "  "}}]}
        with self.assertRaisesRegex(OSError, "Model provider returned an invalid completion"):
            self._complete_with_response(json.dumps(response).encode("utf-8"))


if __name__ == "__main__":
    unittest.main()
