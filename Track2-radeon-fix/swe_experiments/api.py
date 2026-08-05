"""OpenAI-compatible API helpers for Track 2 experiments.

The module keeps provider probing and accounting separate from the agent
controller.  It deliberately never prints or serializes API keys.  Hosted
providers vary in which OpenAI-compatible features they implement, so every
probe is independent and reports a capability rather than failing the whole
experiment.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, Mapping, Sequence
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .actions import ACTION_SCHEMA, parse_json_object


def _value(value: Any, name: str, default: Any = None) -> Any:
    if value is None:
        return default
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def extract_usage(response: Any) -> dict[str, int]:
    """Normalize OpenAI usage objects and mappings to token counters."""
    usage = _value(response, "usage") or {}
    prompt = _value(usage, "prompt_tokens", 0) or 0
    completion = _value(usage, "completion_tokens", 0) or 0
    total = _value(usage, "total_tokens", None)
    try:
        prompt = int(prompt)
        completion = int(completion)
        total = int(total) if total is not None else prompt + completion
    except (TypeError, ValueError):
        return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    return {
        "input_tokens": max(0, prompt),
        "output_tokens": max(0, completion),
        "total_tokens": max(0, total),
    }


def add_usage(total: dict[str, int], response: Any) -> dict[str, int]:
    """Add a response's usage to an aggregate counter and return its usage."""
    current = extract_usage(response)
    for key in ("input_tokens", "output_tokens", "total_tokens"):
        total[key] = int(total.get(key, 0)) + current[key]
    return current


def estimate_cost_usd(
    usage: Mapping[str, int],
    input_usd_per_million: float | None = None,
    output_usd_per_million: float | None = None,
) -> float | None:
    """Estimate cost when the user supplied provider pricing.

    Pricing is intentionally opt-in: aggregators and private endpoints often
    have negotiated rates that cannot be inferred from a model name.
    """
    if input_usd_per_million is None:
        input_usd_per_million = _float_env("TRACK2_INPUT_USD_PER_1M")
    if output_usd_per_million is None:
        output_usd_per_million = _float_env("TRACK2_OUTPUT_USD_PER_1M")
    if input_usd_per_million is None and output_usd_per_million is None:
        return None
    return round(
        usage.get("input_tokens", 0) / 1_000_000 * (input_usd_per_million or 0)
        + usage.get("output_tokens", 0) / 1_000_000 * (output_usd_per_million or 0),
        8,
    )


def _float_env(name: str) -> float | None:
    value = os.getenv(name)
    if not value:
        return None
    try:
        parsed = float(value)
    except ValueError:
        return None
    return parsed if parsed >= 0 else None


def redact_base_url(value: str) -> str:
    """Remove URL credentials and query secrets before writing metadata."""
    try:
        parts = urlsplit(value)
        username = parts.username
        hostname = parts.hostname or ""
        host = hostname
        if parts.port:
            host += f":{parts.port}"
        netloc = f"{username}:REDACTED@{host}" if username else host
        safe_query = [
            (key, "REDACTED" if any(token in key.lower() for token in ("key", "token", "secret", "auth")) else val)
            for key, val in parse_qsl(parts.query, keep_blank_values=True)
        ]
        return urlunsplit((parts.scheme, netloc, parts.path, urlencode(safe_query), ""))
    except Exception:
        return "<redacted-url>"


def redact_secret(value: Any, secret: str | None) -> str:
    """Bound and redact a provider error before it reaches logs/artifacts."""
    text = str(value)[:1000]
    return text.replace(secret, "<redacted>") if secret else text


@dataclass(frozen=True)
class APIConfig:
    """Credentials and endpoint settings resolved without exposing secrets."""

    base_url: str
    api_key: str
    model: str
    timeout: float = 60.0

    @classmethod
    def from_env(
        cls,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float = 60.0,
    ) -> "APIConfig":
        resolved_base = (
            base_url
            or os.getenv("TRACK2_BASE_URL")
            or os.getenv("OPENAI_BASE_URL")
            or "https://api.openai.com/v1"
        )
        resolved_key = api_key or os.getenv("TRACK2_API_KEY") or os.getenv("OPENAI_API_KEY") or ""
        resolved_model = model or os.getenv("TRACK2_MODEL") or os.getenv("OPENAI_MODEL") or ""
        return cls(resolved_base.rstrip("/"), resolved_key, resolved_model, timeout)

    def validate(self) -> None:
        missing = []
        if not self.base_url:
            missing.append("base_url")
        if not self.api_key:
            missing.append("api_key (TRACK2_API_KEY)")
        if not self.model:
            missing.append("model (TRACK2_MODEL)")
        if missing:
            raise ValueError("Missing API settings: " + ", ".join(missing))


def _headers(response: Any) -> dict[str, str]:
    raw = getattr(getattr(response, "_response", None), "headers", None)
    if raw is None:
        return {}
    # Keep only rate-limit metadata; never copy authorization or arbitrary
    # provider headers into experiment artifacts.
    return {
        str(key): str(value)
        for key, value in raw.items()
        if "ratelimit" in str(key).lower() or "rate-limit" in str(key).lower()
    }


def _result(ok: bool, elapsed_ms: float, **fields: Any) -> dict[str, Any]:
    result = {"ok": ok, "latency_ms": round(elapsed_ms, 2)}
    result.update(fields)
    return result


class APIProbe:
    """Run small, bounded capability probes against an OpenAI-compatible API."""

    def __init__(self, config: APIConfig, client: Any | None = None) -> None:
        config.validate()
        self.config = config
        if client is None:
            from openai import OpenAI

            client = OpenAI(base_url=config.base_url, api_key=config.api_key, timeout=config.timeout)
        self.client = client

    def _chat(self, *, messages: list[dict[str, Any]], **kwargs: Any) -> tuple[Any, float]:
        started = time.perf_counter()
        response = self.client.chat.completions.create(
            model=self.config.model,
            messages=messages,
            timeout=self.config.timeout,
            **kwargs,
        )
        return response, (time.perf_counter() - started) * 1000

    def _run(self, name: str, callback) -> dict[str, Any]:
        try:
            value = callback()
            value["probe"] = name
            return value
        except Exception as exc:
            # Provider exception strings can contain request IDs or URLs, but
            # not credentials in normal OpenAI clients.  Keep them bounded and
            # do not include request bodies.
            return {"probe": name, "ok": False, "error": redact_secret(exc, self.config.api_key)}

    def probe_models(self) -> dict[str, Any]:
        started = time.perf_counter()
        response = self.client.models.list()
        models = _value(response, "data", []) or []
        model_ids = [str(_value(item, "id", "")) for item in models[:100]]
        declared_context = {
            str(_value(item, "id", "")): _value(
                item,
                "context_length",
                _value(item, "max_context_length", _value(item, "max_model_len", None)),
            )
            for item in models[:100]
            if _value(item, "context_length", _value(item, "max_context_length", _value(item, "max_model_len", None)))
            is not None
        }
        return _result(
            True,
            (time.perf_counter() - started) * 1000,
            model_count=len(models),
            model_ids=model_ids,
            declared_context_lengths=declared_context,
            rate_limit_headers=_headers(response),
        )

    def probe_basic(self) -> dict[str, Any]:
        response, elapsed = self._chat(
            messages=[{"role": "user", "content": "Reply with the single word OK."}],
            max_tokens=4,
            temperature=0,
        )
        content = _value(_value(response, "choices", [None])[0], "message", {})
        return _result(
            True,
            elapsed,
            response_text=str(_value(content, "content", ""))[:200],
            usage=extract_usage(response),
            rate_limit_headers=_headers(response),
        )

    def probe_tools(self) -> dict[str, Any]:
        tool = {
            "type": "function",
            "function": {
                "name": "track2_probe",
                "description": "Return a probe marker.",
                "parameters": {
                    "type": "object",
                    "properties": {"value": {"type": "string"}},
                    "required": ["value"],
                    "additionalProperties": False,
                },
            },
        }
        response, elapsed = self._chat(
            messages=[{"role": "user", "content": "Call track2_probe with value=ok."}],
            tools=[tool],
            tool_choice={"type": "function", "function": {"name": "track2_probe"}},
            max_tokens=32,
            temperature=0,
        )
        message = _value(_value(response, "choices", [None])[0], "message", {})
        tool_calls = _value(message, "tool_calls", []) or []
        return _result(
            True,
            elapsed,
            tool_call_count=len(tool_calls),
            tool_call_names=[str(_value(_value(call, "function", {}), "name", "")) for call in tool_calls],
            usage=extract_usage(response),
            rate_limit_headers=_headers(response),
        )

    def probe_json(self) -> dict[str, Any]:
        response, elapsed = self._chat(
            messages=[
                {
                    "role": "system",
                    "content": 'Return only JSON with the shape {"ok": true}.',
                },
                {"role": "user", "content": "Return the probe object."},
            ],
            max_tokens=16,
            temperature=0,
        )
        message = _value(_value(response, "choices", [None])[0], "message", {})
        content = str(_value(message, "content", "") or "")
        try:
            parsed = parse_json_object(content)
            valid = parsed.get("ok") is True
            parse_error = None if valid else "JSON object missing ok=true"
        except Exception as exc:
            valid = False
            parse_error = str(exc)
        return _result(
            True,
            elapsed,
            valid_json=valid,
            response_text=content[:500],
            parse_error=parse_error,
            usage=extract_usage(response),
            rate_limit_headers=_headers(response),
        )

    def probe_native_json_mode(self) -> dict[str, Any]:
        """Probe the common OpenAI ``response_format`` JSON mode separately."""
        response, elapsed = self._chat(
            messages=[{"role": "user", "content": "Return an object with ok=true."}],
            response_format={"type": "json_object"},
            max_tokens=16,
            temperature=0,
        )
        message = _value(_value(response, "choices", [None])[0], "message", {})
        content = str(_value(message, "content", "") or "")
        try:
            parsed = parse_json_object(content)
            valid = parsed.get("ok") is True
            parse_error = None if valid else "JSON object missing ok=true"
        except Exception as exc:
            valid = False
            parse_error = str(exc)
        return _result(
            True,
            elapsed,
            valid_json=valid,
            response_text=content[:500],
            parse_error=parse_error,
            usage=extract_usage(response),
            rate_limit_headers=_headers(response),
        )

    def probe_structured_output(self) -> dict[str, Any]:
        response, elapsed = self._chat(
            messages=[
                {
                    "role": "user",
                    "content": (
                        'Return exactly this valid action JSON: '
                        '{"action":"finish","reason":"probe"}. '
                        "Do not add any explanation."
                    ),
                }
            ],
            max_tokens=128,
            temperature=0,
            extra_body={"structured_outputs": {"json": ACTION_SCHEMA}},
        )
        message = _value(_value(response, "choices", [None])[0], "message", {})
        content = str(_value(message, "content", "") or "")
        try:
            parse_json_object(content)
            valid = True
        except Exception:
            valid = False
        return _result(
            True,
            elapsed,
            valid_json=valid,
            response_text=content[:500],
            usage=extract_usage(response),
            rate_limit_headers=_headers(response),
        )

    def probe_context_limit(self, sizes: Sequence[int]) -> dict[str, Any]:
        """Find the largest accepted approximate input size with tiny outputs."""
        attempts: list[dict[str, Any]] = []
        largest: int | None = None
        for size in sorted({int(item) for item in sizes if int(item) > 0}):
            # Four characters per token is deliberately conservative.  This
            # is a capability estimate, not a tokenizer-accurate benchmark.
            content = "x " * (size * 2)
            started = time.perf_counter()
            try:
                response = self.client.chat.completions.create(
                    model=self.config.model,
                    messages=[{"role": "user", "content": content}],
                    max_tokens=1,
                    temperature=0,
                    timeout=self.config.timeout,
                )
                elapsed = (time.perf_counter() - started) * 1000
                largest = size
                attempts.append({"size": size, "ok": True, "latency_ms": round(elapsed, 2), "usage": extract_usage(response)})
            except Exception as exc:
                attempts.append({"size": size, "ok": False, "error": redact_secret(exc, self.config.api_key)[:500]})
                break
        return {"ok": largest is not None, "largest_accepted_size": largest, "attempts": attempts}

    def run(self, *, include_models: bool = True, context_sizes: Sequence[int] = ()) -> dict[str, Any]:
        probes: dict[str, Any] = {}
        if include_models:
            probes["models"] = self._run("models", self.probe_models)
        probes["basic_chat"] = self._run("basic_chat", self.probe_basic)
        probes["tool_calling"] = self._run("tool_calling", self.probe_tools)
        probes["json_prompt"] = self._run("json_prompt", self.probe_json)
        probes["json_response_format"] = self._run(
            "json_response_format", self.probe_native_json_mode
        )
        probes["structured_outputs"] = self._run("structured_outputs", self.probe_structured_output)
        if context_sizes:
            probes["context_limit"] = self._run(
                "context_limit", lambda: self.probe_context_limit(context_sizes)
            )
        return {
            "base_url": redact_base_url(self.config.base_url),
            "model": self.config.model,
            "api_key_configured": bool(self.config.api_key),
            "probes": probes,
        }
