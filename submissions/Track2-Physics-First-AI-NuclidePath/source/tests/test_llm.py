import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import pytest

from nuclear_agent.llm import LocalPlanner, OpenAICompatibleClient


class FakeClient:
    def __init__(self, response):
        self.response = response
        self.messages = None

    def chat(self, messages):
        self.messages = messages
        return self.response


def test_local_planner_requests_only_safe_plan_steps():
    client = FakeClient('["validate_input", "environment_agent", "synthesize_report"]')
    planner = LocalPlanner(client)

    plan = planner.plan({"scenario_id": "demo"})

    assert plan == ["validate_input", "environment_agent", "synthesize_report"]
    assert client.messages[0]["role"] == "system"
    assert "must not" in client.messages[0]["content"]


def test_local_planner_rejects_non_json_or_non_list_output():
    with pytest.raises(ValueError, match="JSON list"):
        LocalPlanner(FakeClient("not-json")).plan({})

    with pytest.raises(ValueError, match="JSON list"):
        LocalPlanner(FakeClient('{"plan": []}')).plan({})


def test_openai_compatible_client_extracts_chat_content():
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers["Content-Length"])
            request = json.loads(self.rfile.read(length))
            assert request["model"] == "test-model"
            assert self.path == "/v1/chat/completions"
            body = json.dumps({"choices": [{"message": {"content": '["validate_input"]'}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = OpenAICompatibleClient(
            f"http://127.0.0.1:{server.server_port}/v1",
            model="test-model",
        )
        assert client.chat([{"role": "user", "content": "hello"}]) == '["validate_input"]'
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_openai_compatible_client_rejects_nonlocal_or_userinfo_urls():
    for url in (
        "https://example.org/v1",
        "http://user:secret@127.0.0.1:8000/v1",
        "http://@127.0.0.1:8000/v1",
        "http://:@127.0.0.1:8000/v1",
    ):
        with pytest.raises(ValueError):
            OpenAICompatibleClient(url, model="test-model")


def test_openai_compatible_client_does_not_follow_redirects_with_credentials():
    received_authorization = []

    class TargetHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            received_authorization.append(self.headers.get("Authorization"))
            body = json.dumps(
                {"choices": [{"message": {"content": '["validate_input"]'}}]}
            ).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            pass

    target = ThreadingHTTPServer(("127.0.0.1", 0), TargetHandler)

    class RedirectHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.send_response(302)
            self.send_header(
                "Location", f"http://127.0.0.1:{target.server_port}/captured"
            )
            self.end_headers()

        def log_message(self, format, *args):
            pass

    redirect = ThreadingHTTPServer(("127.0.0.1", 0), RedirectHandler)
    threads = [
        Thread(target=target.serve_forever, daemon=True),
        Thread(target=redirect.serve_forever, daemon=True),
    ]
    for thread in threads:
        thread.start()
    try:
        client = OpenAICompatibleClient(
            f"http://127.0.0.1:{redirect.server_port}/v1",
            model="test-model",
            api_key="test-only-placeholder",
        )
        with pytest.raises(RuntimeError, match="local LLM request failed"):
            client.chat([{"role": "user", "content": "hello"}])
        assert received_authorization == []
    finally:
        redirect.shutdown()
        target.shutdown()
        for thread in threads:
            thread.join(timeout=2)
