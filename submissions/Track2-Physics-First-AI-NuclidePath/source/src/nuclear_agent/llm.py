"""Local LLM planner adapter with a strict, physics-preserving boundary."""

from __future__ import annotations

import ipaddress
import json
from typing import Any, Mapping, Protocol
from urllib.parse import urlparse


class ChatClient(Protocol):
    def chat(self, messages: list[dict[str, str]]) -> str: ...


_SYSTEM_PROMPT = """You are the planning component of a nuclear emergency response prototype.
Return ONLY a JSON list of safe plan step strings.
Allowed steps are: validate_input, environment_agent, synthesize_report.
You must not calculate or invent physical values, modify user parameters, control equipment,
or recommend operational actions. Numerical results come only from deterministic tools.
"""


def validate_local_base_url(value: str) -> str:
    """Accept only credential-free HTTP(S) loopback endpoints."""
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("LLM base URL must be an HTTP(S) URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("LLM base URL must not contain credentials")
    if parsed.query or parsed.fragment:
        raise ValueError("LLM base URL must not contain a query or fragment")
    try:
        parsed.port
    except ValueError as exc:
        raise ValueError("LLM base URL has an invalid port") from exc
    if parsed.hostname != "localhost":
        try:
            is_loopback = ipaddress.ip_address(parsed.hostname).is_loopback
        except ValueError as exc:
            raise ValueError("LLM base URL must use localhost or a loopback IP") from exc
        if not is_loopback:
            raise ValueError("LLM base URL must use localhost or a loopback IP")
    return value.rstrip("/")


class OpenAICompatibleClient:
    """Small dependency-free client for local vLLM/OpenAI-compatible endpoints."""

    def __init__(self, base_url: str, model: str, api_key: str | None = None, timeout_s: float = 60.0) -> None:
        self.base_url = validate_local_base_url(base_url)
        self.model = model
        self.api_key = api_key
        self.timeout_s = timeout_s

    def chat(self, messages: list[dict[str, str]]) -> str:
        import urllib.error
        import urllib.request

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None

        body = json.dumps(
            {"model": self.model, "messages": messages, "temperature": 0}
        ).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            opener = urllib.request.build_opener(NoRedirect)
            with opener.open(request, timeout=self.timeout_s) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError(f"local LLM request failed: {exc}") from exc
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("local LLM response has no chat content") from exc
        if not isinstance(content, str):
            raise RuntimeError("local LLM chat content must be a string")
        return content


class LocalPlanner:
    """Converts an OpenAI-compatible local chat response into a safe plan."""

    def __init__(self, client: ChatClient) -> None:
        self.client = client

    def plan(self, payload: Mapping[str, Any]) -> list[str]:
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": "Create the execution plan for this scenario JSON:\n"
                + json.dumps(dict(payload), sort_keys=True),
            },
        ]
        raw = self.client.chat(messages)
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("planner output must be a JSON list") from exc
        if not isinstance(parsed, list) or not all(isinstance(step, str) for step in parsed):
            raise ValueError("planner output must be a JSON list")
        return parsed
