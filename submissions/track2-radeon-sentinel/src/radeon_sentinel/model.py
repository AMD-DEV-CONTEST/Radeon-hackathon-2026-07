"""Model clients for offline tests and OpenAI-compatible Radeon endpoints."""

import json
from typing import Any, Dict, Optional, Protocol, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class ModelClient(Protocol):
    def generate(
        self,
        messages: Sequence[Dict[str, str]],
        temperature: float = 0.1,
    ) -> str:
        ...


class MockModelClient:
    """Deterministic model used for tests and offline development."""

    def generate(
        self,
        messages: Sequence[Dict[str, str]],
        temperature: float = 0.1,
    ) -> str:
        del temperature
        prompt = messages[-1]["content"] if messages else ""
        incident = prompt
        if "INCIDENT QUERY\n" in prompt:
            incident = prompt.split("INCIDENT QUERY\n", 1)[1].split(
                "\n\nRUNBOOK EVIDENCE", 1
            )[0]
        incident = incident.lower()
        if "dependency" in incident or "upstream" in incident:
            cause = "an upstream dependency failure"
        elif "config" in incident:
            cause = "configuration drift"
        else:
            cause = "resource saturation or request timeout"
        return (
            "The local evidence points to "
            f"{cause}. Review the cited runbook and diagnostic results, "
            "then approve the simulated remediation only after validating "
            "the affected service and rollback path."
        )


class OpenAICompatibleModelClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "",
        timeout_seconds: int = 60,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    def generate(
        self,
        messages: Sequence[Dict[str, str]],
        temperature: float = 0.1,
    ) -> str:
        endpoint = self._chat_completions_endpoint()
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": list(messages),
            "temperature": temperature,
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        request = Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                result = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            raise RuntimeError(
                f"Model endpoint returned HTTP {error.code}"
            ) from error
        except URLError as error:
            raise RuntimeError("Model endpoint could not be reached") from error

        try:
            content: Optional[str] = result["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise RuntimeError(
                "Model endpoint returned an unexpected response"
            ) from error
        if not content:
            raise RuntimeError("Model endpoint returned an empty response")
        return content.strip()

    def _chat_completions_endpoint(self) -> str:
        if self.base_url.endswith("/chat/completions"):
            return self.base_url
        return f"{self.base_url}/chat/completions"
