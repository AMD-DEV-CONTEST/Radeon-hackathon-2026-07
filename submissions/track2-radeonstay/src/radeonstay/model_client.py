from __future__ import annotations

import hashlib
import hmac
import json
import math
import threading
import time
from dataclasses import dataclass, replace
from typing import Any, Protocol

import httpx

from .config import Settings
from .runtime_binding import RuntimeBindingResult, verify_runtime_instance


class ModelClientError(RuntimeError):
    """Raised when the local model service cannot satisfy a request."""


class ModelResponseValidationError(ModelClientError):
    """Raised when transport succeeded but bounded response repair did not."""


@dataclass(frozen=True, slots=True)
class ChatResult:
    content: str
    elapsed_ms: float
    model: str
    usage: dict[str, Any]
    raw: dict[str, Any]
    syntax_repaired: bool = False


class ModelClient(Protocol):
    """Shared contract for local and Radeon Cloud inference providers."""

    backend_name: str
    provider_name: str
    local_only: bool
    settings: Settings

    def start_trace(self) -> None: ...

    def finish_trace(self) -> list[dict[str, Any]]: ...

    def mark_last_trace_error(
        self,
        error: Exception,
        *,
        validation_stage: str = "response_parse",
    ) -> None: ...

    def record_last_trace_validation(
        self,
        *,
        validation_stage: str,
        validation_ok: bool,
        outcome: str,
    ) -> None: ...

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
    ) -> ChatResult: ...

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
    ) -> tuple[dict[str, Any], ChatResult]: ...

    def health(self) -> dict[str, Any]: ...

    def close(self) -> None: ...


class LocalModelClient:
    """Minimal OpenAI-compatible client restricted to a local model endpoint."""

    backend_name = "llama.cpp-rocm"
    provider_name = "local_llamacpp"
    local_only = True

    def __init__(
        self,
        settings: Settings,
        client: httpx.Client | None = None,
        *,
        runtime_proof: dict[str, Any] | None = None,
    ) -> None:
        settings.validate_private_model_endpoint()
        self.settings = settings
        self._client = client or httpx.Client(
            base_url=f"{settings.model_base_url}/",
            timeout=httpx.Timeout(settings.model_timeout_seconds),
            headers={"Authorization": f"Bearer {settings.model_api_key}"},
            trust_env=False,
        )
        self._trace_state = threading.local()
        self._runtime_proof = dict(runtime_proof or {})

    def runtime_binding_result(self) -> RuntimeBindingResult:
        return verify_runtime_instance(
            self.settings,
            runtime_proof=self._runtime_proof,
        )

    def _require_request_configuration_binding(
        self,
        *,
        schema_constrained: bool,
    ) -> tuple[str, bool]:
        """Fail closed when an accepted profile differs from the actual request."""

        actual = {
            "thinking_enabled": self.settings.model_enable_thinking,
            "schema_constrained": schema_constrained,
            "fused_plan_evidence": self.settings.fused_plan_evidence,
        }
        # Record the request that would actually be sent, including local
        # unconstrained callers. A bound competition profile still differs and
        # fails closed before the HTTP request when schema_constrained is false.
        actual_sha256 = hashlib.sha256(
            json.dumps(
                actual,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("ascii")
        ).hexdigest()
        expected = self._runtime_proof.get("request_configuration_sha256")
        bound = isinstance(expected, str) and hmac.compare_digest(
            expected,
            actual_sha256,
        )
        if self.settings.runtime_proof_required and not bound:
            raise ModelClientError(
                "Local model request configuration differs from accepted ROCm proof"
            )
        if isinstance(expected, str) and not bound:
            raise ModelClientError(
                "Local model request configuration differs from bound runtime proof"
            )
        return actual_sha256, bound

    @staticmethod
    def _require_runtime_binding(result: RuntimeBindingResult) -> None:
        if result.configured and not result.valid:
            raise ModelClientError("Local model process binding validation failed")

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
        """Mark a successful transport call whose local response parsing failed."""

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
        """Attach bounded plan-validation metadata without retaining model content."""

        calls = getattr(self._trace_state, "calls", None)
        if not calls:
            return
        calls[-1]["validation_stage"] = validation_stage[:80]
        calls[-1]["validation_ok"] = bool(validation_ok)
        calls[-1]["validation_outcome"] = outcome[:80]

    def _record_call(
        self,
        result: ChatResult,
        trace_fields: dict[str, Any],
    ) -> None:
        prompt_tokens = result.usage.get("prompt_tokens")
        completion_tokens = result.usage.get("completion_tokens")
        effective_rate: float | None = None
        if (
            isinstance(completion_tokens, int)
            and completion_tokens > 0
            and result.elapsed_ms > 0
        ):
            effective_rate = round(completion_tokens * 1000 / result.elapsed_ms, 6)
        server_timings = result.raw.get("timings")
        safe_server_timings = (
            {
                str(key)[:80]: value
                for key, value in server_timings.items()
                if isinstance(key, str)
                and type(value) in {int, float}
                and math.isfinite(float(value))
                and float(value) >= 0
            }
            if isinstance(server_timings, dict)
            else {}
        )
        server_decode_rate = next(
            (
                float(safe_server_timings[key])
                for key in (
                    "decode_tokens_per_second",
                    "predicted_per_second",
                    "tokens_per_second",
                )
                if key in safe_server_timings
            ),
            None,
        )
        ttft_ms = next(
            (
                float(safe_server_timings[key])
                for key in ("ttft_ms", "time_to_first_token_ms")
                if key in safe_server_timings
            ),
            None,
        )
        self._append_trace(
            {
                "ok": True,
                "model": result.model,
                "elapsed_ms": result.elapsed_ms,
                "prompt_tokens": prompt_tokens if isinstance(prompt_tokens, int) else None,
                "completion_tokens": (
                    completion_tokens if isinstance(completion_tokens, int) else None
                ),
                "effective_output_tokens_per_second": effective_rate,
                "server_decode_tokens_per_second": server_decode_rate,
                "server_timings": safe_server_timings,
                "ttft_ms": ttft_ms,
                **trace_fields,
            }
        )

    def _record_failure(
        self,
        started: float,
        error: Exception,
        trace_fields: dict[str, Any],
    ) -> None:
        self._append_trace(
            {
                "ok": False,
                "model": self.settings.model_name,
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
                "prompt_tokens": None,
                "completion_tokens": None,
                "effective_output_tokens_per_second": None,
                "server_decode_tokens_per_second": None,
                "server_timings": {},
                "ttft_ms": None,
                "error_type": type(error).__name__,
                **trace_fields,
            }
        )

    def close(self) -> None:
        self._client.close()

    def health(self) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            request_configuration_sha256_value, request_configuration_bound = (
                self._require_request_configuration_binding(
                    schema_constrained=True,
                )
            )
            binding_before = self.runtime_binding_result()
            self._require_runtime_binding(binding_before)
            response = self._client.get(
                "models",
                timeout=min(5.0, self.settings.model_timeout_seconds),
            )
            response.raise_for_status()
            payload = response.json()
            binding_after = self.runtime_binding_result()
            self._require_runtime_binding(binding_after)
            if (
                binding_before.configured
                and binding_before.manifest_sha256
                != binding_after.manifest_sha256
            ):
                raise ModelClientError(
                    "Local model process binding changed during health check"
                )
        except ModelClientError:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            raise ModelClientError(f"Local model health check failed: {exc}") from exc
        models = payload.get("data") if isinstance(payload, dict) else None
        advertised_models: set[str] = set()
        if isinstance(models, list):
            advertised_models = {
                item["id"]
                for item in models
                if isinstance(item, dict) and isinstance(item.get("id"), str)
            }
        if self.settings.model_name not in advertised_models:
            raise ModelClientError(
                "Local model endpoint does not advertise the configured model"
            )
        return {
            "ok": True,
            "backend": self.backend_name,
            "provider": self.provider_name,
            "local_only": self.local_only,
            "synthetic_only": False,
            "bonus_candidate": False,
            "model": self.settings.model_name,
            "thinking_enabled": self.settings.model_enable_thinking,
            "fused_plan_evidence": bool(
                getattr(self.settings, "fused_plan_evidence", False)
            ),
            "request_configuration_sha256": request_configuration_sha256_value,
            "request_configuration_bound": request_configuration_bound,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            "advertised_model_count": len(advertised_models),
            "target_model_advertised": True,
            "network_boundary": "local/private model endpoint only",
            **binding_after.public_report(),
        }

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
            raise ValueError("json_schema_name must contain only letters, numbers, _ or -")
        if trace_attempt < 1:
            raise ValueError("trace_attempt must be positive")
        if not isinstance(max_tokens, int) or isinstance(max_tokens, bool) or max_tokens < 1:
            raise ValueError("max_tokens must be a positive integer")

        request: dict[str, Any] = {
            "model": self.settings.model_name,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
            "chat_template_kwargs": {
                "enable_thinking": self.settings.model_enable_thinking,
            },
        }
        response_format = "text"
        if json_schema is not None:
            response_format = "json_schema"
            request["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": json_schema_name,
                    "strict": True,
                    "schema": json_schema,
                },
            }
        elif json_mode:
            response_format = "json_object"
            request["response_format"] = {"type": "json_object"}

        trace_fields = {
            "purpose": trace_purpose[:80],
            "attempt": trace_attempt,
            "max_tokens": max_tokens,
            "response_format": response_format,
            "json_schema_name": json_schema_name if json_schema is not None else None,
            "thinking_enabled": self.settings.model_enable_thinking,
            "schema_constrained": json_schema is not None,
            "fused_plan_evidence": bool(
                getattr(self.settings, "fused_plan_evidence", False)
            ),
        }

        started = time.perf_counter()
        try:
            request_configuration_sha256_value, request_configuration_bound = (
                self._require_request_configuration_binding(
                    schema_constrained=json_schema is not None,
                )
            )
            trace_fields.update(
                {
                    "request_configuration_sha256": (
                        request_configuration_sha256_value
                    ),
                    "request_configuration_bound": request_configuration_bound,
                }
            )
            binding_before = self.runtime_binding_result()
            trace_fields.update(binding_before.public_report())
            self._require_runtime_binding(binding_before)
            response = self._client.post("chat/completions", json=request)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise TypeError("Local model response must be a JSON object")
            content = payload["choices"][0]["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise ModelClientError("Local model returned an empty response")
            response_model = str(payload.get("model", self.settings.model_name))
            if response_model != self.settings.model_name:
                raise ModelClientError("Local model response used an unexpected model alias")
            usage = payload.get("usage") or {}
            if not isinstance(usage, dict):
                raise TypeError("Local model usage must be a JSON object")
            result = ChatResult(
                content=content.strip(),
                elapsed_ms=round((time.perf_counter() - started) * 1000, 3),
                model=response_model,
                usage=dict(usage),
                raw=payload,
            )
            binding_after = self.runtime_binding_result()
            trace_fields.update(binding_after.public_report())
            self._require_runtime_binding(binding_after)
            if (
                binding_before.configured
                and binding_before.manifest_sha256
                != binding_after.manifest_sha256
            ):
                trace_fields["process_binding_valid"] = False
                raise ModelClientError(
                    "Local model process binding changed during inference"
                )
        except ModelClientError as exc:
            self._record_failure(started, exc, trace_fields)
            raise
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            self._record_failure(started, exc, trace_fields)
            raise ModelClientError(f"Local model request failed: {exc}") from exc
        self._record_call(result, trace_fields)
        return result

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
                    "Local model returned invalid JSON for a bounded repair response"
                ) from exc
            repair = self.chat(
                [
                    {
                        "role": "system",
                        "content": (
                            "Return only one valid JSON object. Preserve the original meaning; "
                            "do not add markdown or commentary."
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
                    "Local model failed JSON validation after one repair attempt"
                ) from repair_exc
            return parsed, replace(repair, syntax_repaired=True)
        return parsed, result


def _parse_json_object(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise TypeError("Expected a JSON object")
    return parsed
