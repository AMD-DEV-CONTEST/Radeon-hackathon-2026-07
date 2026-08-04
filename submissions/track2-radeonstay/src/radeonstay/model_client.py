from __future__ import annotations

import json
import math
import threading
import time
from dataclasses import dataclass
from typing import Any

import httpx

from .config import Settings


class ModelClientError(RuntimeError):
    """Raised when the local model service cannot satisfy a request."""


@dataclass(frozen=True, slots=True)
class ChatResult:
    content: str
    elapsed_ms: float
    model: str
    usage: dict[str, Any]
    raw: dict[str, Any]


class LocalModelClient:
    """Minimal OpenAI-compatible client restricted to a local model endpoint."""

    backend_name = "llama.cpp-rocm"

    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        settings.validate_private_model_endpoint()
        self.settings = settings
        self._client = client or httpx.Client(
            base_url=f"{settings.model_base_url}/",
            timeout=httpx.Timeout(settings.model_timeout_seconds),
            headers={"Authorization": f"Bearer {settings.model_api_key}"},
            trust_env=False,
        )
        self._trace_state = threading.local()

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
            response = self._client.get("models")
            response.raise_for_status()
            payload = response.json()
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
            "model": self.settings.model_name,
            "thinking_enabled": self.settings.model_enable_thinking,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            "advertised_model_count": len(advertised_models),
            "target_model_advertised": True,
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
            "response_format": response_format,
            "json_schema_name": json_schema_name if json_schema is not None else None,
            "thinking_enabled": self.settings.model_enable_thinking,
            "schema_constrained": json_schema is not None,
        }

        started = time.perf_counter()
        try:
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
                raise ModelClientError(
                    "Local model failed JSON validation after one repair attempt"
                ) from repair_exc
            return parsed, repair
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
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("No JSON object found")
    parsed = json.loads(text[start : end + 1])
    if not isinstance(parsed, dict):
        raise TypeError("Expected a JSON object")
    return parsed
