"""Bounded, local-only Ollama AnalysisProvider implementation."""

from __future__ import annotations

import http.client
import json
import math
import re
import socket
import time
from typing import Any, Mapping
from urllib.parse import urlsplit

from ..exceptions import (
    ProviderInputError,
    ProviderOutputError,
    ProviderTransportError,
)
from ..knowledge.models import KnowledgeContext
from ..models import AnalysisResult, Event
from ..skill import SkillContext
from .base import analysis_system_instructions, format_analysis_reasoning

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
_MODEL_PATTERN = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9._/-]*(?::[A-Za-z0-9][A-Za-z0-9._-]*)?"
)
_DIGEST_PATTERN = re.compile(r"(?:sha256:)?[a-fA-F0-9]{64}")
_SAFE_ATTACHMENT_REFERENCE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,199}")
_REQUIRED_OUTPUT_FIELDS = frozenset(
    {
        "issue_summary",
        "possible_causes",
        "recommended_actions",
        "severity",
        "confidence",
        "evidence_used",
        "limitations",
        "requires_human_review",
    }
)
_SEVERITIES = frozenset({"low", "medium", "high", "critical"})
_READ_CHUNK_BYTES = 64 * 1024

ANALYSIS_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "issue_summary": {"type": "string", "minLength": 1, "maxLength": 500},
        "possible_causes": {
            "type": "array",
            "minItems": 1,
            "maxItems": 5,
            "items": {"type": "string", "minLength": 1, "maxLength": 500},
        },
        "recommended_actions": {
            "type": "array",
            "minItems": 1,
            "maxItems": 5,
            "items": {"type": "string", "minLength": 1, "maxLength": 500},
        },
        "severity": {"type": "string", "enum": sorted(_SEVERITIES)},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "evidence_used": {
            "type": "array",
            "minItems": 1,
            "maxItems": 8,
            "items": {"type": "string", "minLength": 1, "maxLength": 500},
        },
        "limitations": {
            "type": "array",
            "minItems": 1,
            "maxItems": 8,
            "items": {"type": "string", "minLength": 1, "maxLength": 500},
        },
        "requires_human_review": {"const": True},
    },
    "required": sorted(_REQUIRED_OUTPUT_FIELDS),
}

class OllamaAnalysisProvider:
    """Call a loopback Ollama `/api/generate` endpoint once per analysis."""

    prompt_version = "ollama-industrial-analysis-v4"

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        connect_timeout_seconds: float = 5.0,
        total_timeout_seconds: float = 60.0,
        max_prompt_bytes: int = 65_536,
        max_request_bytes: int = 131_072,
        max_response_bytes: int = 1_048_576,
        model_digest: str | None = None,
        keep_alive: str = "5m",
        num_ctx: int | None = None,
    ):
        parsed = urlsplit(base_url)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in _LOOPBACK_HOSTS
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "base_url must be an unauthenticated HTTP loopback URL"
            )
        if parsed.path not in ("", "/"):
            raise ValueError("base_url must not contain an API path")
        if (
            not isinstance(model, str)
            or len(model) > 200
            or _MODEL_PATTERN.fullmatch(model) is None
        ):
            raise ValueError("model must be an explicit valid Ollama model tag")
        if not isinstance(connect_timeout_seconds, (int, float)) or not (
            0 < float(connect_timeout_seconds) <= 300
        ):
            raise ValueError("connect timeout must be between 0 and 300 seconds")
        if not isinstance(total_timeout_seconds, (int, float)) or not (
            0 < float(total_timeout_seconds) <= 1800
        ):
            raise ValueError("total timeout must be between 0 and 1800 seconds")
        if float(connect_timeout_seconds) > float(total_timeout_seconds):
            raise ValueError("connect timeout must not exceed total timeout")
        if (
            not isinstance(max_prompt_bytes, int)
            or isinstance(max_prompt_bytes, bool)
            or not 4_096 <= max_prompt_bytes <= 1_048_576
        ):
            raise ValueError(
                "max_prompt_bytes must be between 4096 and 1048576"
            )
        if (
            not isinstance(max_request_bytes, int)
            or isinstance(max_request_bytes, bool)
            or not max_prompt_bytes <= max_request_bytes <= 2_097_152
        ):
            raise ValueError(
                "max_request_bytes must be at least max_prompt_bytes "
                "and at most 2097152"
            )
        if (
            not isinstance(max_response_bytes, int)
            or isinstance(max_response_bytes, bool)
            or not 256 <= max_response_bytes <= 4 * 1024 * 1024
        ):
            raise ValueError(
                "max_response_bytes must be between 256 and 4194304"
            )
        if model_digest is not None and (
            not isinstance(model_digest, str)
            or _DIGEST_PATTERN.fullmatch(model_digest) is None
        ):
            raise ValueError("model_digest must be a full SHA-256 digest")
        if (
            not isinstance(keep_alive, str)
            or not keep_alive
            or len(keep_alive) > 32
            or any(character.isspace() for character in keep_alive)
        ):
            raise ValueError("keep_alive must be a short Ollama duration value")
        if num_ctx is not None and (
            not isinstance(num_ctx, int)
            or isinstance(num_ctx, bool)
            or not 256 <= num_ctx <= 1_048_576
        ):
            raise ValueError("num_ctx must be between 256 and 1048576")

        self.base_url = base_url.rstrip("/")
        self.model = model
        self.connect_timeout_seconds = float(connect_timeout_seconds)
        self.total_timeout_seconds = float(total_timeout_seconds)
        self.max_prompt_bytes = max_prompt_bytes
        self.max_request_bytes = max_request_bytes
        self.max_response_bytes = max_response_bytes
        self.model_digest = (
            model_digest.lower() if model_digest is not None else None
        )
        self.keep_alive = keep_alive
        self.num_ctx = num_ctx
        self.provider_id = f"ollama:{model}"
        self._host = parsed.hostname
        self._port = parsed.port or 80

    def analyze(self, event: Event) -> AnalysisResult:
        """Make one non-streaming request and strictly validate its output."""

        return self._analyze(
            event,
            skill_context=None,
            knowledge_context=None,
        )

    def analyze_with_context(
        self,
        event: Event,
        knowledge_context: KnowledgeContext,
    ) -> AnalysisResult:
        """Analyze one Event with explicit structured knowledge context."""

        if not isinstance(knowledge_context, KnowledgeContext):
            raise ProviderInputError(
                "Knowledge context has an invalid type.",
                code="invalid_knowledge_context",
            )
        return self._analyze(
            event,
            skill_context=None,
            knowledge_context=knowledge_context,
        )

    def analyze_with_contexts(
        self,
        event: Event,
        skill_context: SkillContext,
        knowledge_context: KnowledgeContext,
    ) -> AnalysisResult:
        """Analyze with explicit bounded Skill and Knowledge contexts."""

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
        return self._analyze(
            event,
            skill_context=skill_context,
            knowledge_context=knowledge_context,
        )

    def _analyze(
        self,
        event: Event,
        *,
        skill_context: SkillContext | None,
        knowledge_context: KnowledgeContext | None,
    ) -> AnalysisResult:
        request_body = self._build_request(
            event,
            knowledge_context,
            skill_context=skill_context,
        )
        response_body = self._post_generate(request_body)
        output = self._extract_model_output(response_body)
        return self._to_analysis_result(output)

    def _build_request(
        self,
        event: Event,
        knowledge_context: KnowledgeContext | None = None,
        *,
        skill_context: SkillContext | None = None,
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
        skill_prompt = ""
        if skill_context is not None:
            skill_prompt = (
                "\nSkill Context (bounded scenario guidance):\n"
                + json.dumps(
                    skill_context.to_prompt_payload(),
                    ensure_ascii=False,
                    allow_nan=False,
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
        knowledge_prompt = ""
        if knowledge_context is not None and knowledge_context.documents:
            knowledge_prompt = (
                "\nEnterprise Knowledge Context (quoted reference data):\n"
                + json.dumps(
                    knowledge_context.to_prompt_payload(),
                    ensure_ascii=False,
                    allow_nan=False,
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
        prompt = (
            analysis_system_instructions()
            + "\nIncident Event:\n"
            + json.dumps(
                event_payload,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + skill_prompt
            + knowledge_prompt
            + "\nOutput JSON Schema:\n"
            + json.dumps(
                ANALYSIS_OUTPUT_SCHEMA,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        options: dict[str, Any] = {
            "temperature": 0,
            "num_predict": 1024,
        }
        if self.num_ctx is not None:
            options["num_ctx"] = self.num_ctx
        prompt_bytes = prompt.encode("utf-8")
        if len(prompt_bytes) > self.max_prompt_bytes:
            raise ProviderInputError(
                "Event projection exceeded the configured prompt size limit.",
                code="prompt_too_large",
            )
        payload = {
            "model": self.model,
            "prompt": prompt,
            "format": ANALYSIS_OUTPUT_SCHEMA,
            "stream": False,
            "think": False,
            "keep_alive": self.keep_alive,
            "options": options,
        }
        request_body = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(request_body) > self.max_request_bytes:
            raise ProviderInputError(
                "Ollama request exceeded the configured request size limit.",
                code="request_too_large",
            )
        return request_body

    def _post_generate(self, body: bytes) -> bytes:
        connection = http.client.HTTPConnection(
            self._host,
            self._port,
            timeout=self.connect_timeout_seconds,
        )
        started = time.monotonic()
        try:
            connection.request(
                "POST",
                "/api/generate",
                body=body,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json; charset=utf-8",
                },
            )
            self._apply_remaining_timeout(connection, started)
            response = connection.getresponse()
            if not 200 <= response.status < 300:
                raise ProviderTransportError(
                    f"Ollama returned HTTP status {response.status}.",
                    code="http_error",
                )
            declared_length = response.getheader("Content-Length")
            if declared_length is not None:
                try:
                    if int(declared_length) > self.max_response_bytes:
                        raise ProviderTransportError(
                            "Ollama response exceeded the configured size limit.",
                            code="response_too_large",
                        )
                except ValueError:
                    pass

            chunks: list[bytes] = []
            received = 0
            while True:
                self._apply_remaining_timeout(connection, started)
                remaining_bytes = self.max_response_bytes - received + 1
                chunk = response.read(min(_READ_CHUNK_BYTES, remaining_bytes))
                if not chunk:
                    break
                chunks.append(chunk)
                received += len(chunk)
                if received > self.max_response_bytes:
                    raise ProviderTransportError(
                        "Ollama response exceeded the configured size limit.",
                        code="response_too_large",
                    )
            return b"".join(chunks)
        except ProviderTransportError:
            raise
        except (socket.timeout, TimeoutError) as exc:
            raise ProviderTransportError(
                "Ollama request timed out.",
                code="timeout",
            ) from exc
        except (
            ConnectionError,
            OSError,
            http.client.HTTPException,
        ) as exc:
            raise ProviderTransportError(
                "Ollama request could not be completed.",
                code="connection_error",
            ) from exc
        finally:
            connection.close()

    def _apply_remaining_timeout(
        self,
        connection: http.client.HTTPConnection,
        started: float,
    ) -> None:
        remaining = self.total_timeout_seconds - (time.monotonic() - started)
        if remaining <= 0:
            raise ProviderTransportError(
                "Ollama request timed out.",
                code="timeout",
            )
        if connection.sock is not None:
            connection.sock.settimeout(remaining)

    @staticmethod
    def _extract_model_output(response_body: bytes) -> Mapping[str, Any]:
        try:
            envelope = json.loads(response_body.decode("utf-8"))
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
            RecursionError,
        ) as exc:
            raise ProviderOutputError(
                "Ollama response was not valid UTF-8 JSON.",
                code="invalid_response_json",
            ) from exc
        if not isinstance(envelope, dict):
            raise ProviderOutputError(
                "Ollama response envelope must be a JSON object.",
                code="invalid_response_envelope",
            )
        if envelope.get("done") is not True:
            raise ProviderOutputError(
                "Ollama response did not report completed generation.",
                code="incomplete_response",
            )
        generated = envelope.get("response")
        if not isinstance(generated, str):
            raise ProviderOutputError(
                "Ollama response did not contain generated text.",
                code="missing_generated_text",
            )
        try:
            output = json.loads(generated)
        except (json.JSONDecodeError, RecursionError) as exc:
            raise ProviderOutputError(
                "Model output was not valid JSON.",
                code="invalid_model_json",
            ) from exc
        if not isinstance(output, dict):
            raise ProviderOutputError(
                "Model output must be a JSON object.",
                code="invalid_model_schema",
            )
        return output

    def _to_analysis_result(
        self, output: Mapping[str, Any]
    ) -> AnalysisResult:
        keys = frozenset(output)
        missing = sorted(_REQUIRED_OUTPUT_FIELDS - keys)
        extra = sorted(keys - _REQUIRED_OUTPUT_FIELDS)
        if missing or extra:
            parts = []
            if missing:
                parts.append("missing fields: " + ", ".join(missing))
            if extra:
                parts.append("unexpected fields: " + ", ".join(extra))
            raise ProviderOutputError(
                "Model output schema violation (" + "; ".join(parts) + ").",
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
                "severity must be low, medium, high, or critical.",
                code="invalid_model_schema",
            )
        confidence = output["confidence"]
        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not math.isfinite(float(confidence))
            or not 0.0 <= float(confidence) <= 1.0
        ):
            raise ProviderOutputError(
                "confidence must be a finite number between 0 and 1.",
                code="invalid_model_schema",
            )
        if output["requires_human_review"] is not True:
            raise ProviderOutputError(
                "requires_human_review must be true.",
                code="human_review_required",
            )

        reasoning_summary = format_analysis_reasoning(
            possible_causes,
            recommended_actions,
            limitations,
        )
        evidence = [f"evidence_used={value}" for value in evidence_used]
        evidence.extend(
            f"possible_cause={value}" for value in possible_causes
        )
        evidence.extend(
            f"suggested_human_action={value}"
            for value in recommended_actions
        )
        evidence.extend(f"limitation={value}" for value in limitations)
        evidence.append(f"model_tag={self.model}")
        if self.model_digest is not None:
            evidence.append(f"model_digest={self.model_digest}")

        model_identity = self.provider_id
        if self.model_digest is not None:
            model_identity += f"@{self.model_digest}"
        return AnalysisResult(
            detected_issue=issue_summary,
            decision_type="ai_assisted_incident_analysis",
            reasoning_summary=reasoning_summary,
            evidence=evidence,
            model_or_rule=model_identity,
            confidence=float(confidence),
            requires_human_review=True,
            severity=severity.upper(),
        )


def _require_string(value: Any, field: str, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > maximum
        or any(character == "\x00" for character in value)
    ):
        raise ProviderOutputError(
            f"{field} must be a non-empty string of at most {maximum} characters.",
            code="invalid_model_schema",
        )
    return value.strip()


def _require_string_list(
    value: Any,
    field: str,
    minimum: int,
    maximum: int,
) -> list[str]:
    if (
        not isinstance(value, list)
        or not minimum <= len(value) <= maximum
    ):
        raise ProviderOutputError(
            f"{field} must contain between {minimum} and {maximum} items.",
            code="invalid_model_schema",
        )
    return [
        _require_string(item, f"{field} item", 500)
        for item in value
    ]
