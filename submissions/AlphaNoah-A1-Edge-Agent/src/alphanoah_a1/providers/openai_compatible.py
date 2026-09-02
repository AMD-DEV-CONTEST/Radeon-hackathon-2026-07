"""Bounded OpenAI-compatible chat-completions analysis adapter."""

from __future__ import annotations

import http.client
import json
import math
import re
import socket
from typing import Any, Mapping
from urllib.parse import urlsplit

from ..exceptions import (
    ProviderInputError,
    ProviderOutputError,
    ProviderTransportError,
)
from ..knowledge.models import KnowledgeContext
from ..models import AnalysisResult, Event
from ..provider_config import ProviderKind
from ..skill import SkillContext
from .base import analysis_system_instructions, format_analysis_reasoning
from .ollama import ANALYSIS_OUTPUT_SCHEMA

_REQUIRED_OUTPUT_FIELDS = frozenset(ANALYSIS_OUTPUT_SCHEMA["required"])
_SEVERITIES = frozenset({"low", "medium", "high", "critical"})
_READ_CHUNK_BYTES = 64 * 1024
_MODEL_PATTERN = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9._/-]*(?::[A-Za-z0-9][A-Za-z0-9._-]*)?"
)
_SAFE_ATTACHMENT_REFERENCE = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9._:-]{0,199}"
)
class OpenAICompatibleAnalysisProvider:
    """Call one configured OpenAI-compatible `/chat/completions` endpoint."""

    prompt_version = "openai-compatible-industrial-analysis-v2"

    def __init__(
        self,
        *,
        endpoint: str,
        model: str,
        provider_kind: ProviderKind = ProviderKind.OPENAI_COMPATIBLE,
        api_key: str = "",
        timeout_seconds: float = 60.0,
        max_prompt_bytes: int = 65_536,
        max_request_bytes: int = 131_072,
        max_response_bytes: int = 1_048_576,
    ):
        parsed = urlsplit(endpoint)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "endpoint must be an HTTP(S) URL without credentials"
            )
        if (
            not isinstance(model, str)
            or _MODEL_PATTERN.fullmatch(model) is None
        ):
            raise ValueError("model must be an explicit model identifier")
        try:
            kind = ProviderKind(provider_kind)
        except (TypeError, ValueError) as exc:
            raise ValueError("provider kind is invalid") from exc
        if kind not in {
            ProviderKind.VLLM,
            ProviderKind.OPENAI_COMPATIBLE,
        }:
            raise ValueError("provider kind must be vllm or openai_compatible")
        if not isinstance(api_key, str) or "\x00" in api_key:
            raise ValueError("API key must be text")
        if not 0 < float(timeout_seconds) <= 1_800:
            raise ValueError("timeout must be between 0 and 1800 seconds")
        if not 4_096 <= max_prompt_bytes <= 1_048_576:
            raise ValueError("prompt limit is invalid")
        if not max_prompt_bytes <= max_request_bytes <= 2_097_152:
            raise ValueError("request limit is invalid")
        if not 256 <= max_response_bytes <= 4 * 1024 * 1024:
            raise ValueError("response limit is invalid")

        self.endpoint = endpoint.rstrip("/")
        self.model = model
        self.provider_kind = kind
        self.provider_id = f"{kind.value}:{model}"
        self.timeout_seconds = float(timeout_seconds)
        self.max_prompt_bytes = max_prompt_bytes
        self.max_request_bytes = max_request_bytes
        self.max_response_bytes = max_response_bytes
        self._api_key = api_key
        self._parsed_endpoint = parsed

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(provider_id={self.provider_id!r}, "
            f"endpoint={self.endpoint!r})"
        )

    def analyze(self, event: Event) -> AnalysisResult:
        return self._analyze(event, None, None)

    def analyze_with_context(
        self,
        event: Event,
        knowledge_context: KnowledgeContext,
    ) -> AnalysisResult:
        if not isinstance(knowledge_context, KnowledgeContext):
            raise ProviderInputError(
                "Knowledge context has an invalid type.",
                code="invalid_knowledge_context",
            )
        return self._analyze(event, None, knowledge_context)

    def analyze_with_contexts(
        self,
        event: Event,
        skill_context: SkillContext,
        knowledge_context: KnowledgeContext,
    ) -> AnalysisResult:
        if not isinstance(skill_context, SkillContext):
            raise ProviderInputError(
                "Skill context has an invalid type.",
                code="invalid_skill_context",
            )
        if not isinstance(knowledge_context, KnowledgeContext):
            raise ProviderInputError(
                "Knowledge context has an invalid type.",
                code="invalid_knowledge_context",
            )
        return self._analyze(event, skill_context, knowledge_context)

    def _analyze(
        self,
        event: Event,
        skill_context: SkillContext | None,
        knowledge_context: KnowledgeContext | None,
    ) -> AnalysisResult:
        request = self._build_request(event, skill_context, knowledge_context)
        response = self._post_chat_completions(request)
        output = self._extract_output(response)
        return self._to_analysis_result(output)

    def _build_request(
        self,
        event: Event,
        skill_context: SkillContext | None,
        knowledge_context: KnowledgeContext | None,
    ) -> bytes:
        event_payload = {
            "event_id": event.event_id,
            "event_type": event.event_type,
            "source": event.source,
            "location": event.location,
            "asset_id": event.asset_id,
            "description": event.description,
            "attachment_references": [
                reference
                for reference in event.attachments
                if _SAFE_ATTACHMENT_REFERENCE.fullmatch(reference) is not None
            ],
        }
        user_payload: dict[str, Any] = {"event": event_payload}
        if skill_context is not None:
            user_payload["skill_context"] = skill_context.to_prompt_payload()
        if knowledge_context is not None:
            user_payload["knowledge_context"] = (
                knowledge_context.to_prompt_payload()
            )
        user_payload["output_schema"] = ANALYSIS_OUTPUT_SCHEMA
        prompt = json.dumps(
            user_payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        if len(prompt.encode("utf-8")) > self.max_prompt_bytes:
            raise ProviderInputError(
                "Event projection exceeded the configured prompt size limit.",
                code="prompt_too_large",
            )
        body = json.dumps(
            {
                "model": self.model,
                "messages": [
                    {
                        "role": "system",
                        "content": analysis_system_instructions(),
                    },
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0,
                "stream": False,
                "response_format": {"type": "json_object"},
            },
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(body) > self.max_request_bytes:
            raise ProviderInputError(
                "Provider request exceeded the configured size limit.",
                code="request_too_large",
            )
        return body

    def _post_chat_completions(self, body: bytes) -> bytes:
        parsed = self._parsed_endpoint
        connection_type = (
            http.client.HTTPSConnection
            if parsed.scheme == "https"
            else http.client.HTTPConnection
        )
        connection = connection_type(
            parsed.hostname,
            parsed.port,
            timeout=self.timeout_seconds,
        )
        path = parsed.path.rstrip("/") + "/chat/completions"
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json; charset=utf-8",
        }
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        try:
            connection.request("POST", path, body=body, headers=headers)
            response = connection.getresponse()
            if not 200 <= response.status < 300:
                raise ProviderTransportError(
                    f"Provider returned HTTP status {response.status}.",
                    code=(
                        "authentication_error"
                        if response.status in {401, 403}
                        else "http_error"
                    ),
                )
            chunks: list[bytes] = []
            received = 0
            while True:
                chunk = response.read(
                    min(
                        _READ_CHUNK_BYTES,
                        self.max_response_bytes - received + 1,
                    )
                )
                if not chunk:
                    break
                chunks.append(chunk)
                received += len(chunk)
                if received > self.max_response_bytes:
                    raise ProviderTransportError(
                        "Provider response exceeded the configured size limit.",
                        code="response_too_large",
                    )
            return b"".join(chunks)
        except ProviderTransportError:
            raise
        except (socket.timeout, TimeoutError) as exc:
            raise ProviderTransportError(
                "Provider request timed out.",
                code="timeout",
            ) from exc
        except (
            ConnectionError,
            OSError,
            http.client.HTTPException,
        ) as exc:
            raise ProviderTransportError(
                "Provider request could not be completed.",
                code="connection_error",
            ) from exc
        finally:
            connection.close()

    @staticmethod
    def _extract_output(response_body: bytes) -> Mapping[str, Any]:
        try:
            envelope = json.loads(response_body.decode("utf-8"))
            choices = envelope["choices"]
            content = choices[0]["message"]["content"]
            output = json.loads(content)
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
            KeyError,
            IndexError,
            TypeError,
            RecursionError,
        ) as exc:
            raise ProviderOutputError(
                "Provider response did not contain valid structured output.",
                code="invalid_response_json",
            ) from exc
        if not isinstance(output, Mapping):
            raise ProviderOutputError(
                "Model output must be a JSON object.",
                code="invalid_model_schema",
            )
        return output

    def _to_analysis_result(
        self,
        output: Mapping[str, Any],
    ) -> AnalysisResult:
        keys = frozenset(output)
        if keys != _REQUIRED_OUTPUT_FIELDS:
            raise ProviderOutputError(
                "Model output did not match the exact analysis schema.",
                code="invalid_model_schema",
            )
        issue_summary = _require_string(
            output["issue_summary"], "issue_summary", 500
        )
        possible_causes = _require_string_list(
            output["possible_causes"], "possible_causes", 1, 5
        )
        recommended_actions = _require_string_list(
            output["recommended_actions"], "recommended_actions", 1, 5
        )
        evidence_used = _require_string_list(
            output["evidence_used"], "evidence_used", 1, 8
        )
        limitations = _require_string_list(
            output["limitations"], "limitations", 1, 8
        )
        severity = output["severity"]
        if not isinstance(severity, str) or severity not in _SEVERITIES:
            raise ProviderOutputError(
                "severity is invalid.",
                code="invalid_model_schema",
            )
        confidence = output["confidence"]
        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not math.isfinite(float(confidence))
            or not 0 <= float(confidence) <= 1
        ):
            raise ProviderOutputError(
                "confidence is invalid.",
                code="invalid_model_schema",
            )
        if output["requires_human_review"] is not True:
            raise ProviderOutputError(
                "requires_human_review must be true.",
                code="human_review_required",
            )
        reasoning = format_analysis_reasoning(
            possible_causes,
            recommended_actions,
            limitations,
        )
        evidence = [f"evidence_used={value}" for value in evidence_used]
        evidence.extend(f"possible_cause={value}" for value in possible_causes)
        evidence.extend(
            f"suggested_human_action={value}"
            for value in recommended_actions
        )
        evidence.extend(f"limitation={value}" for value in limitations)
        evidence.append(f"model_tag={self.model}")
        return AnalysisResult(
            detected_issue=issue_summary,
            decision_type="ai_assisted_incident_analysis",
            reasoning_summary=reasoning,
            evidence=evidence,
            model_or_rule=self.provider_id,
            confidence=float(confidence),
            requires_human_review=True,
            severity=severity.upper(),
        )


def _require_string(value: object, field: str, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > maximum
        or "\x00" in value
    ):
        raise ProviderOutputError(
            f"{field} is invalid.",
            code="invalid_model_schema",
        )
    return value.strip()


def _require_string_list(
    value: object,
    field: str,
    minimum: int,
    maximum: int,
) -> list[str]:
    if (
        not isinstance(value, list)
        or not minimum <= len(value) <= maximum
    ):
        raise ProviderOutputError(
            f"{field} is invalid.",
            code="invalid_model_schema",
        )
    return [
        _require_string(item, f"{field} item", 500)
        for item in value
    ]
