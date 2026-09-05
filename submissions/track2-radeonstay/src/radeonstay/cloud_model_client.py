from __future__ import annotations

import json
import threading
import time
from dataclasses import replace
from typing import Any

import httpx

from .config import RADEON_CLOUD_FREE_PROVIDER, Settings
from .model_client import (
    ChatResult,
    ModelClientError,
    ModelResponseValidationError,
    _parse_json_object,
)

_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_CAPABILITY_STATUS_CODES = frozenset({400, 404, 415, 422})
_STRUCTURED_MODES = ("json_schema", "json_object", "prompt_json")


class _StructuredOutputUnsupported(ModelClientError):
    """Internal signal used to downgrade only unsupported response formats."""


class RadeonCloudFreeModelClient:
    """Fail-closed client for the allow-listed Radeon Cloud Public Free API.

    The client deliberately does not expose local ROCm/process-binding fields. It
    records only bounded request metadata and never includes the API key in health,
    traces, exceptions, or evidence-facing return values.
    """

    backend_name = "radeon-cloud-free"
    provider_name = RADEON_CLOUD_FREE_PROVIDER
    local_only = False

    def __init__(
        self,
        settings: Settings,
        client: httpx.Client | None = None,
    ) -> None:
        if not settings.uses_radeon_cloud_free or not settings.bonus_demo:
            raise ValueError(
                "RadeonCloudFreeModelClient requires the explicit bonus provider mode"
            )
        settings.validate_radeon_cloud_endpoint()
        self.settings = settings
        self._client = client or httpx.Client(
            base_url=f"{settings.radeon_cloud_base_url}/",
            timeout=httpx.Timeout(settings.model_timeout_seconds),
            headers={"Authorization": f"Bearer {settings.radeon_cloud_api_key}"},
            trust_env=False,
            follow_redirects=False,
        )
        self._trace_state = threading.local()
        self._state_lock = threading.Lock()
        configured_mode = settings.radeon_cloud_structured_mode
        self._structured_mode = (
            "json_schema" if configured_mode == "auto" else configured_mode
        )
        self._last_request: dict[str, Any] = {
            "status": "not_yet_called",
            "ok": None,
        }

    def start_trace(self) -> None:
        self._trace_state.calls = []

    def finish_trace(self) -> list[dict[str, Any]]:
        calls = list(getattr(self._trace_state, "calls", []))
        self._trace_state.calls = []
        return calls

    def _append_trace(self, call: dict[str, Any]) -> None:
        calls = getattr(self._trace_state, "calls", None)
        if calls is None:
            return
        call["sequence"] = len(calls) + 1
        calls.append(call)

    def mark_last_trace_error(
        self,
        error: Exception,
        *,
        validation_stage: str = "response_parse",
    ) -> None:
        calls = getattr(self._trace_state, "calls", None)
        if not calls:
            return
        calls[-1]["ok"] = False
        calls[-1]["error_type"] = type(error).__name__
        calls[-1]["validation_stage"] = validation_stage[:80]
        calls[-1]["validation_ok"] = False

    def record_last_trace_validation(
        self,
        *,
        validation_stage: str,
        validation_ok: bool,
        outcome: str,
    ) -> None:
        calls = getattr(self._trace_state, "calls", None)
        if not calls:
            return
        calls[-1]["validation_stage"] = validation_stage[:80]
        calls[-1]["validation_ok"] = bool(validation_ok)
        calls[-1]["validation_outcome"] = outcome[:80]

    @staticmethod
    def _safe_usage(value: Any) -> dict[str, int]:
        if not isinstance(value, dict):
            return {}
        return {
            key: item
            for key, item in value.items()
            if key in {"prompt_tokens", "completion_tokens", "total_tokens"}
            and isinstance(item, int)
            and not isinstance(item, bool)
            and item >= 0
        }

    def _base_trace_fields(
        self,
        *,
        trace_purpose: str,
        trace_attempt: int,
        max_tokens: int,
        response_format: str,
        json_schema_name: str | None,
    ) -> dict[str, Any]:
        return {
            "provider": self.provider_name,
            "purpose": trace_purpose[:80],
            "attempt": trace_attempt,
            "max_tokens": max_tokens,
            "response_format": response_format,
            "json_schema_name": json_schema_name,
            "thinking_enabled": False,
            "schema_constrained": response_format == "json_schema",
            "fused_plan_evidence": bool(self.settings.fused_plan_evidence),
            "request_configuration_sha256": (
                self.settings.request_configuration_sha256
            ),
            "request_configuration_bound": False,
            "process_binding_valid": False,
            "runtime_proof_eligible": False,
            "local_only": False,
            "synthetic_only": True,
            "bonus_candidate": True,
            "evidence_class": "optional_bonus_public_api",
        }

    def _record_success(
        self,
        result: ChatResult,
        trace_fields: dict[str, Any],
    ) -> None:
        usage = self._safe_usage(result.usage)
        completion_tokens = usage.get("completion_tokens")
        effective_rate = None
        if completion_tokens and result.elapsed_ms > 0:
            effective_rate = round(completion_tokens * 1000 / result.elapsed_ms, 6)
        response_id = result.raw.get("id")
        if not isinstance(response_id, str) or not response_id:
            response_id = None
        self._append_trace(
            {
                "ok": True,
                "model": result.model,
                "elapsed_ms": result.elapsed_ms,
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": completion_tokens,
                "total_tokens": usage.get("total_tokens"),
                "effective_output_tokens_per_second": effective_rate,
                "server_decode_tokens_per_second": None,
                "server_timings": {},
                "ttft_ms": None,
                "response_id": response_id[:128] if response_id else None,
                "http_status": 200,
                **trace_fields,
            }
        )

    def _record_failure(
        self,
        started: float,
        error: Exception,
        trace_fields: dict[str, Any],
        *,
        status_code: int | None = None,
    ) -> None:
        self._append_trace(
            {
                "ok": False,
                "model": self.settings.radeon_cloud_model,
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
                "prompt_tokens": None,
                "completion_tokens": None,
                "total_tokens": None,
                "effective_output_tokens_per_second": None,
                "server_decode_tokens_per_second": None,
                "server_timings": {},
                "ttft_ms": None,
                "response_id": None,
                "http_status": status_code,
                "error_type": type(error).__name__,
                **trace_fields,
            }
        )

    def _update_last_request(
        self,
        *,
        ok: bool,
        status: str,
        elapsed_ms: float,
        http_status: int | None,
        response_id: str | None = None,
    ) -> None:
        with self._state_lock:
            self._last_request = {
                "status": status[:80],
                "ok": ok,
                "elapsed_ms": elapsed_ms,
                "http_status": http_status,
                "response_id": response_id[:128] if response_id else None,
            }

    def _send(
        self,
        request: dict[str, Any],
        trace_fields: dict[str, Any],
        *,
        allow_capability_downgrade: bool,
    ) -> ChatResult:
        started = time.perf_counter()
        status_code: int | None = None
        try:
            response = self._client.post("chat/completions", json=request)
            status_code = response.status_code
            if (
                allow_capability_downgrade
                and status_code in _CAPABILITY_STATUS_CODES
            ):
                error = _StructuredOutputUnsupported(
                    "Radeon Cloud response format is unsupported"
                )
                self._record_failure(
                    started,
                    error,
                    trace_fields,
                    status_code=status_code,
                )
                self._update_last_request(
                    ok=False,
                    status="response_format_unsupported",
                    elapsed_ms=round((time.perf_counter() - started) * 1000, 3),
                    http_status=status_code,
                )
                raise error
            response.raise_for_status()
            if len(response.content) > _MAX_RESPONSE_BYTES:
                raise ValueError("Radeon Cloud response exceeded the size limit")
            content_type = response.headers.get("content-type", "").casefold()
            if content_type and "json" not in content_type:
                raise TypeError("Radeon Cloud response was not JSON")
            payload = response.json()
            if not isinstance(payload, dict):
                raise TypeError("Radeon Cloud response must be a JSON object")
            choices = payload.get("choices")
            if not isinstance(choices, list) or not choices:
                raise TypeError("Radeon Cloud response did not contain choices")
            first_choice = choices[0]
            if not isinstance(first_choice, dict):
                raise TypeError("Radeon Cloud response choice was invalid")
            message = first_choice.get("message")
            if not isinstance(message, dict):
                raise TypeError("Radeon Cloud response message was invalid")
            content = message.get("content")
            if not isinstance(content, str) or not content.strip():
                raise ModelClientError("Radeon Cloud returned an empty response")
            advertised_model = payload.get("model")
            if (
                advertised_model is not None
                and advertised_model != self.settings.radeon_cloud_model
            ):
                raise ModelClientError(
                    "Radeon Cloud response used an unexpected model"
                )
            usage = self._safe_usage(payload.get("usage"))
            result = ChatResult(
                content=content.strip(),
                elapsed_ms=round((time.perf_counter() - started) * 1000, 3),
                model=self.settings.radeon_cloud_model,
                usage=usage,
                raw=payload,
            )
        except _StructuredOutputUnsupported:
            raise
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
            self._record_failure(
                started,
                exc,
                trace_fields,
                status_code=status_code,
            )
            self._update_last_request(
                ok=False,
                status=type(exc).__name__,
                elapsed_ms=elapsed_ms,
                http_status=status_code,
            )
            raise ModelClientError(
                "Radeon Cloud Model API request failed"
            ) from exc
        except ModelClientError as exc:
            elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
            self._record_failure(
                started,
                exc,
                trace_fields,
                status_code=status_code,
            )
            self._update_last_request(
                ok=False,
                status=type(exc).__name__,
                elapsed_ms=elapsed_ms,
                http_status=status_code,
            )
            raise
        self._record_success(result, trace_fields)
        response_id = payload.get("id") if isinstance(payload.get("id"), str) else None
        self._update_last_request(
            ok=True,
            status="succeeded",
            elapsed_ms=result.elapsed_ms,
            http_status=status_code,
            response_id=response_id,
        )
        return result

    @staticmethod
    def _prompt_json_messages(
        messages: list[dict[str, str]],
        json_schema: dict[str, Any] | None,
    ) -> list[dict[str, str]]:
        instruction = (
            "Return exactly one valid JSON object with no markdown or commentary."
        )
        if json_schema is not None:
            instruction += " Match this JSON Schema: " + json.dumps(
                json_schema,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        return [{"role": "system", "content": instruction}, *messages]

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.1,
        max_tokens: int = 800,
        json_mode: bool = False,
        json_schema: dict[str, Any] | None = None,
        json_schema_name: str = "response",
        trace_purpose: str = "chat",
        trace_attempt: int = 1,
    ) -> ChatResult:
        if json_schema is not None and not isinstance(json_schema, dict):
            raise TypeError("json_schema must be a JSON object")
        if not json_schema_name or len(json_schema_name) > 64 or any(
            not (character.isalnum() or character in {"_", "-"})
            for character in json_schema_name
        ):
            raise ValueError("json_schema_name contains unsupported characters")
        if trace_attempt < 1:
            raise ValueError("trace_attempt must be positive")
        if (
            not isinstance(max_tokens, int)
            or isinstance(max_tokens, bool)
            or max_tokens < 1
        ):
            raise ValueError("max_tokens must be a positive integer")

        wants_structured = json_mode or json_schema is not None
        if not wants_structured:
            modes = ("text",)
        else:
            current_index = _STRUCTURED_MODES.index(self._structured_mode)
            modes = _STRUCTURED_MODES[current_index:]

        last_capability_error: _StructuredOutputUnsupported | None = None
        for mode in modes:
            request_messages = messages
            request: dict[str, Any] = {
                "model": self.settings.radeon_cloud_model,
                "messages": request_messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": False,
            }
            if mode == "json_schema" and json_schema is not None:
                request["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": json_schema_name,
                        "strict": True,
                        "schema": json_schema,
                    },
                }
            elif mode in {"json_schema", "json_object"}:
                mode = "json_object"
                request["response_format"] = {"type": "json_object"}
            elif mode == "prompt_json":
                request_messages = self._prompt_json_messages(messages, json_schema)
                request["messages"] = request_messages

            trace_fields = self._base_trace_fields(
                trace_purpose=(
                    trace_purpose
                    if mode == "text"
                    else f"{trace_purpose}.{mode}"
                ),
                trace_attempt=trace_attempt,
                max_tokens=max_tokens,
                response_format=mode,
                json_schema_name=(json_schema_name if json_schema is not None else None),
            )
            try:
                result = self._send(
                    request,
                    trace_fields,
                    allow_capability_downgrade=(
                        wants_structured and mode != "prompt_json"
                    ),
                )
            except _StructuredOutputUnsupported as exc:
                last_capability_error = exc
                next_index = min(
                    _STRUCTURED_MODES.index(mode) + 1,
                    len(_STRUCTURED_MODES) - 1,
                )
                self._structured_mode = _STRUCTURED_MODES[next_index]
                continue
            if mode in _STRUCTURED_MODES:
                self._structured_mode = mode
            return result
        raise ModelClientError(
            "Radeon Cloud structured output negotiation failed"
        ) from last_capability_error

    def chat_json(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.0,
        max_tokens: int = 1000,
        json_schema: dict[str, Any] | None = None,
        json_schema_name: str = "response",
        trace_purpose: str = "json",
        trace_attempt: int = 1,
        allow_syntax_repair: bool = True,
    ) -> tuple[dict[str, Any], ChatResult]:
        result = self.chat(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=True,
            json_schema=json_schema,
            json_schema_name=json_schema_name,
            trace_purpose=trace_purpose,
            trace_attempt=trace_attempt,
        )
        try:
            parsed = _parse_json_object(result.content)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            self.mark_last_trace_error(exc)
            if not allow_syntax_repair:
                raise ModelResponseValidationError(
                    "Radeon Cloud returned invalid JSON for a bounded repair response"
                ) from exc
            repair = self.chat(
                [
                    {
                        "role": "system",
                        "content": (
                            "Return only one valid JSON object. Preserve the original "
                            "meaning; do not add markdown or commentary."
                        ),
                    },
                    {"role": "user", "content": result.content},
                ],
                temperature=0.0,
                max_tokens=max_tokens,
                json_mode=True,
                json_schema=json_schema,
                json_schema_name=json_schema_name,
                trace_purpose=f"{trace_purpose}.syntax_repair",
                trace_attempt=trace_attempt + 1,
            )
            try:
                parsed = _parse_json_object(repair.content)
            except (json.JSONDecodeError, TypeError, ValueError) as repair_exc:
                self.mark_last_trace_error(repair_exc)
                raise ModelResponseValidationError(
                    "Radeon Cloud failed JSON validation after one repair attempt"
                ) from repair_exc
            return parsed, replace(repair, syntax_repaired=True)
        return parsed, result

    def health(self) -> dict[str, Any]:
        with self._state_lock:
            last_request = dict(self._last_request)
            structured_mode = self._structured_mode
        return {
            "ok": True,
            "configured": True,
            "backend": self.backend_name,
            "provider": self.provider_name,
            "model": self.settings.radeon_cloud_model,
            "base_url": self.settings.radeon_cloud_base_url,
            "local_only": False,
            "remote_endpoint": True,
            "synthetic_only": True,
            "bonus_candidate": True,
            "evidence_class": "optional_bonus_public_api",
            "bonus_evidence_eligible": last_request.get("ok") is True,
            "evidence_eligible": False,
            "process_binding_valid": False,
            "request_configuration_bound": False,
            "thinking_enabled": False,
            "fused_plan_evidence": bool(self.settings.fused_plan_evidence),
            "structured_output_mode": structured_mode,
            "last_request": last_request,
            "competition_path": "radeon-cloud-public-free-bonus",
            "hardware_evidence": "not exposed by the shared Public Free endpoint",
            "network_boundary": (
                "remote AMD Radeon Cloud endpoint; synthetic competition data only"
            ),
        }

    def close(self) -> None:
        self._client.close()
