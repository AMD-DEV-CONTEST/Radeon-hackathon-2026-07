"""Qwen structured-output fallback for the Shidu research pipeline."""

from __future__ import annotations

import http.client
import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field as dataclass_field
from typing import Any, Literal

from creative_hub.shidu.glm_research_transport import (
    GlmRateLimitError,
    GlmResearchTransportError,
    StructuredModelClient,
)
from creative_hub.shidu.provider_trace import (
    StructuredProviderTrace,
    StructuredProviderTraceSink,
    structured_provider_request_digest,
    structured_provider_response_digest,
)


# The current Shidu development deployment uses the China (Beijing) Token Plan
# endpoint approved for its GLM-429 fallback smoke path.  Keep the host fixed so
# neither prompts nor runtime configuration can redirect model traffic.
QWEN_RESEARCH_HOST = "token-plan.cn-beijing.maas.aliyuncs.com"
QWEN_RESEARCH_PATH = "/compatible-mode/v1/chat/completions"
QWEN_RESEARCH_MODEL = "qwen3.7-plus"
RATE_LIMIT_FAILOVER_PROVIDER_ID = "zhipu-to-aliyun"
MAX_QWEN_RESPONSE_BYTES = 1_000_000
MAX_QWEN_INPUT_CHARS = 80_000


@dataclass(frozen=True, slots=True)
class QwenStructuredModelClient:
    """Bounded Model Studio client compatible with the structured GLM adapter."""

    api_key: str = dataclass_field(repr=False)
    provider_id: str = dataclass_field(default="aliyun", init=False)
    model_id: str = QWEN_RESEARCH_MODEL
    timeout_seconds: float = 120.0
    max_attempts: int = 2
    retry_base_seconds: float = 0.5
    _connection_factory: Callable[..., Any] | None = dataclass_field(
        default=None, repr=False
    )
    _sleeper: Callable[[float], None] = dataclass_field(
        default=time.sleep, repr=False
    )

    def __post_init__(self) -> None:
        if (
            not isinstance(self.api_key, str)
            or not self.api_key.strip()
            or len(self.api_key) > 4_096
            or any(ord(character) < 33 or ord(character) == 127 for character in self.api_key)
        ):
            raise ValueError("Qwen API key is invalid")
        if self.model_id != QWEN_RESEARCH_MODEL:
            raise ValueError("Qwen research model is not application-owned")
        if not 1.0 <= float(self.timeout_seconds) <= 240.0:
            raise ValueError("Qwen timeout is invalid")
        if type(self.max_attempts) is not int or not 1 <= self.max_attempts <= 3:
            raise ValueError("Qwen attempt limit is invalid")
        if not 0.0 <= float(self.retry_base_seconds) <= 5.0:
            raise ValueError("Qwen retry delay is invalid")

    def complete(
        self,
        *,
        system_prompt: str,
        input_payload: Mapping[str, Any],
        response_schema: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        input_json = json.dumps(
            dict(input_payload), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        schema_json = json.dumps(
            dict(response_schema), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        if len(input_json) + len(schema_json) > MAX_QWEN_INPUT_CHARS:
            raise GlmResearchTransportError("Qwen research input is too large")
        body = json.dumps(
            {
                "model": self.model_id,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            system_prompt
                            + "\nOnly return one JSON object matching this exact schema: "
                            + schema_json
                        ),
                    },
                    {"role": "user", "content": input_json},
                ],
                "enable_thinking": False,
                "stream": False,
                "temperature": 0.1,
                "response_format": {"type": "json_object"},
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")

        raw = b""
        for attempt in range(1, self.max_attempts + 1):
            factory = self._connection_factory or http.client.HTTPSConnection
            connection = factory(
                QWEN_RESEARCH_HOST,
                443,
                timeout=float(self.timeout_seconds),
            )
            try:
                connection.request(
                    "POST",
                    QWEN_RESEARCH_PATH,
                    body=body,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                )
                response = connection.getresponse()
                raw = response.read(MAX_QWEN_RESPONSE_BYTES + 1)
                status = int(response.status)
            except (OSError, TimeoutError, http.client.HTTPException):
                if attempt == self.max_attempts:
                    raise GlmResearchTransportError(
                        "Qwen research service is unavailable"
                    ) from None
                self._sleeper(self.retry_base_seconds * (2 ** (attempt - 1)))
                continue
            finally:
                connection.close()
            if status == 429 or 500 <= status <= 599:
                if attempt == self.max_attempts:
                    raise GlmResearchTransportError(
                        "Qwen research request failed"
                    ) from None
                self._sleeper(self.retry_base_seconds * (2 ** (attempt - 1)))
                continue
            if not 200 <= status < 300:
                raise GlmResearchTransportError("Qwen research request failed")
            break

        if len(raw) > MAX_QWEN_RESPONSE_BYTES:
            raise GlmResearchTransportError("Qwen research response is too large")
        try:
            envelope = json.loads(raw.decode("utf-8"))
            content = envelope["choices"][0]["message"]["content"]
            decoded = json.loads(content)
        except (KeyError, IndexError, TypeError, UnicodeError, json.JSONDecodeError):
            raise GlmResearchTransportError(
                "Qwen research response is invalid"
            ) from None
        if not isinstance(decoded, dict):
            raise GlmResearchTransportError("Qwen research output is not an object")
        return decoded


@dataclass(frozen=True, slots=True)
class RateLimitFailoverStructuredModelClient:
    """Use Qwen only when the primary GLM client reports HTTP 429."""

    primary: StructuredModelClient
    fallback: StructuredModelClient
    trace_sink: StructuredProviderTraceSink | None = dataclass_field(
        default=None, repr=False
    )
    provider_id: str = dataclass_field(
        default=RATE_LIMIT_FAILOVER_PROVIDER_ID, init=False
    )
    model_id: str = dataclass_field(init=False)

    def __post_init__(self) -> None:
        primary_provider_id = str(getattr(self.primary, "provider_id", "")).strip()
        fallback_provider_id = str(getattr(self.fallback, "provider_id", "")).strip()
        primary_id = str(getattr(self.primary, "model_id", "")).strip()
        fallback_id = str(getattr(self.fallback, "model_id", "")).strip()
        if not primary_provider_id or not fallback_provider_id:
            raise ValueError("structured model failover provider IDs are invalid")
        if not primary_id or not fallback_id:
            raise ValueError("structured model failover IDs are invalid")
        if primary_provider_id != "zhipu":
            raise ValueError("structured model primary provider must be zhipu")
        if (
            fallback_provider_id != "aliyun"
            or fallback_id != QWEN_RESEARCH_MODEL
        ):
            raise ValueError(
                "structured model fallback provider or model is not application-owned"
            )
        if self.trace_sink is not None and not callable(
            getattr(self.trace_sink, "record", None)
        ):
            raise ValueError("structured model trace sink is invalid")
        object.__setattr__(
            self,
            "model_id",
            f"rate-limit-failover:{primary_id}->{fallback_id}",
        )

    def complete(
        self,
        *,
        system_prompt: str,
        input_payload: Mapping[str, Any],
        response_schema: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        request_digest = structured_provider_request_digest(
            system_prompt=system_prompt,
            input_payload=input_payload,
            response_schema=response_schema,
        )
        try:
            response = self.primary.complete(
                system_prompt=system_prompt,
                input_payload=input_payload,
                response_schema=response_schema,
            )
        except GlmRateLimitError:
            response = self.fallback.complete(
                system_prompt=system_prompt,
                input_payload=input_payload,
                response_schema=response_schema,
            )
            self._record_success(
                actual=self.fallback,
                request_digest=request_digest,
                response=response,
                fallback_reason="glm_http_429",
            )
            return response
        self._record_success(
            actual=self.primary,
            request_digest=request_digest,
            response=response,
            fallback_reason=None,
        )
        return response

    def _record_success(
        self,
        *,
        actual: StructuredModelClient,
        request_digest: str,
        response: Mapping[str, Any],
        fallback_reason: Literal["glm_http_429"] | None,
    ) -> None:
        if self.trace_sink is None:
            return
        self.trace_sink.record(
            StructuredProviderTrace(
                requested_provider_id=self.primary.provider_id,
                requested_model_id=self.primary.model_id,
                actual_provider_id=actual.provider_id,
                actual_model_id=actual.model_id,
                request_digest=request_digest,
                response_digest=structured_provider_response_digest(response),
                fallback_reason=fallback_reason,
            )
        )


__all__ = [
    "QWEN_RESEARCH_HOST",
    "QWEN_RESEARCH_MODEL",
    "QWEN_RESEARCH_PATH",
    "RATE_LIMIT_FAILOVER_PROVIDER_ID",
    "QwenStructuredModelClient",
    "RateLimitFailoverStructuredModelClient",
]
