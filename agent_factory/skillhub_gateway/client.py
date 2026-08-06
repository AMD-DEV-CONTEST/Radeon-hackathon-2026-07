from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

from agent_factory.skillhub_gateway.protocol import (
    SkillHubGatewayRunRequest,
    SkillHubGatewayRunResponse,
)


class SkillHubGatewayClientError(RuntimeError):
    pass


class SkillHubGatewayClient:
    def __init__(self, *, base_url: str, timeout_seconds: float = 120.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = SkillHubGatewayRunRequest.model_validate(payload)
        response_payload = self._request_json("POST", "/run", request.model_dump(mode="json"))
        response = SkillHubGatewayRunResponse.model_validate(response_payload)
        return response.result

    def tool_resource_summary(self) -> dict[str, Any]:
        return {
            "mode": "gateway",
            "base_url": self.base_url,
        }

    def _request_json(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(f"{self.base_url}{path}", data=data, headers=headers, method=method)
        try:
            with _NO_PROXY_OPENER.open(request, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise SkillHubGatewayClientError(f"SkillHUB gateway returned HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise SkillHubGatewayClientError(f"SkillHUB gateway is unreachable: {exc.reason}") from exc
        except TimeoutError as exc:
            raise SkillHubGatewayClientError("SkillHUB gateway request timed out") from exc
        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SkillHubGatewayClientError(f"SkillHUB gateway returned invalid JSON: {raw[:200]}") from exc
        if not isinstance(decoded, dict):
            raise SkillHubGatewayClientError("SkillHUB gateway response must be a JSON object")
        return decoded


_NO_PROXY_OPENER = build_opener(ProxyHandler({}))
