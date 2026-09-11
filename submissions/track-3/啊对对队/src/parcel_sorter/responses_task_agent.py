"""OpenAI-compatible Responses client for bounded task-level robot planning.

The model may choose a grasp family and recovery strategy. It never receives
or emits joint, Cartesian, tool, or servo commands; the existing Harness Agent
validator enforces that boundary after every network response.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
import time
from typing import Any, Callable, Mapping
from urllib import error, request

from .harness_agent import (
    AgentIdentity,
    TASK_DIRECTIVE_PROTOCOL,
    validate_task_directive,
)


Transport = Callable[[str, Mapping[str, str], bytes, float], Mapping[str, Any]]


TASK_DIRECTIVE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "protocol",
        "directive_id",
        "agent_id",
        "goal",
        "grasp_mode",
        "recovery_strategy",
        "memory_refs",
        "rationale",
    ],
    "properties": {
        "schema_version": {"type": "integer", "const": 1},
        "protocol": {"type": "string", "const": TASK_DIRECTIVE_PROTOCOL},
        "directive_id": {"type": "string", "minLength": 1},
        "agent_id": {"type": "string", "minLength": 1},
        "goal": {"type": "string", "minLength": 1},
        "grasp_mode": {
            "type": "string",
            "enum": ["top", "side", "cradle", "auto"],
        },
        "recovery_strategy": {
            "type": "string",
            "enum": [
                "hold",
                "reobserve",
                "retry_same_mode",
                "reroute_grasp_mode",
                "return_to_safe_pose",
                "abort_episode",
            ],
        },
        "memory_refs": {"type": "array", "items": {"type": "string"}},
        "rationale": {"type": "string"},
    },
}


@dataclass(frozen=True)
class ResponsesClientConfig:
    base_url: str
    model: str = "gpt-5.6-luna"
    api_key_env: str = "OPENAI_API_KEY"
    timeout_s: float = 90.0
    fallback_timeout_s: float | None = None
    reasoning_effort: str = "xhigh"
    max_output_tokens: int = 512
    fallback_model: str | None = None
    primary_attempts: int = 2

    def __post_init__(self) -> None:
        if not self.base_url.startswith("https://"):
            raise ValueError("Responses base_url must use HTTPS")
        if not self.model.strip() or not self.api_key_env.strip():
            raise ValueError("Responses model and api_key_env are required")
        if (
            self.timeout_s <= 0
            or (self.fallback_timeout_s is not None and self.fallback_timeout_s <= 0)
            or self.max_output_tokens < 64
        ):
            raise ValueError("Responses timeout and output budget must be positive")
        if self.primary_attempts not in {1, 2, 3}:
            raise ValueError("primary_attempts must be in [1, 3]")
        if self.reasoning_effort not in {
            "low",
            "medium",
            "high",
            "xhigh",
            "max",
        }:
            raise ValueError("unsupported reasoning effort")

    @property
    def responses_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/responses"


class ResponsesTaskAgentError(RuntimeError):
    """Fail-closed error raised when no valid directive is available."""


class OpenAICompatibleResponsesTaskAgent:
    """TaskAgentAdapter backed by an OpenAI-compatible Responses endpoint."""

    def __init__(
        self,
        identity: AgentIdentity,
        config: ResponsesClientConfig,
        *,
        transport: Transport | None = None,
    ) -> None:
        if identity.role != "task_agent":
            raise ValueError("Responses planner requires a task_agent identity")
        if identity.model != config.model:
            raise ValueError("Agent identity model must match the primary model")
        self.identity = identity
        self.config = config
        self._transport = transport or _urlopen_transport
        self.last_trace: dict[str, Any] | None = None

    def plan(self, observation: Mapping[str, Any]) -> Mapping[str, Any]:
        api_key = os.environ.get(self.config.api_key_env, "").strip()
        if not api_key:
            raise ResponsesTaskAgentError(
                f"missing API credential in {self.config.api_key_env}"
            )

        models = [self.config.model] * self.config.primary_attempts
        if self.config.fallback_model:
            models.append(self.config.fallback_model)
        failures: list[dict[str, str]] = []
        for attempt, model in enumerate(models, start=1):
            started = time.perf_counter()
            try:
                timeout_s = (
                    self.config.fallback_timeout_s
                    if model != self.config.model
                    and self.config.fallback_timeout_s is not None
                    else self.config.timeout_s
                )
                response = self._transport(
                    self.config.responses_url,
                    {
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                        "User-Agent": "parcel-sorter-agent/1.0",
                    },
                    json.dumps(
                        self._request_payload(observation, model=model),
                        separators=(",", ":"),
                        allow_nan=False,
                    ).encode("utf-8"),
                    timeout_s,
                )
                raw_directive = json.loads(_extract_output_text(response))
                if not isinstance(raw_directive, Mapping):
                    raise ValueError("task directive root must be an object")
                directive = validate_task_directive(
                    raw_directive, task_agent=self.identity
                )
                # plan_task_with_agent performs the authoritative outer validation
                # and adds derived audit fields. Return only model-owned fields so
                # the two validation layers remain composable.
                directive.pop("authority", None)
                self.last_trace = {
                    "status": "passed",
                    "requested_model": self.config.model,
                    "actual_model": str(response.get("model") or model),
                    "fallback_used": model != self.config.model,
                    "attempt": attempt,
                    "latency_ms": (time.perf_counter() - started) * 1000.0,
                    "response_id": str(response.get("id") or ""),
                }
                return directive
            except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                failures.append(
                    {
                        "model": model,
                        "error": type(exc).__name__,
                        "detail": str(exc)[:240],
                    }
                )

        self.last_trace = {
            "status": "failed_closed",
            "requested_model": self.config.model,
            "attempts": failures,
        }
        raise ResponsesTaskAgentError(
            "no model returned a valid high-level task directive"
        )

    def _request_payload(
        self, observation: Mapping[str, Any], *, model: str
    ) -> dict[str, Any]:
        instructions = (
            "You are a bounded task-level robot planner. Return one JSON object "
            "matching the supplied schema. Choose only a grasp_mode and a recovery "
            "strategy from the allowed values. Never emit robot actions, poses, "
            "joint targets, tool commands, safety overrides, or checkpoint changes."
            f" Set agent_id exactly to {self.identity.agent_id!r}, protocol exactly "
            f"to {TASK_DIRECTIVE_PROTOCOL!r}, schema_version to 1, and create a "
            "non-empty directive_id tied to the episode."
        )
        return {
            "model": model,
            "store": False,
            "instructions": instructions,
            "input": json.dumps(observation, sort_keys=True, allow_nan=False),
            "reasoning": {"effort": self.config.reasoning_effort},
            "max_output_tokens": self.config.max_output_tokens,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "parcel_task_directive",
                    "strict": True,
                    "schema": TASK_DIRECTIVE_SCHEMA,
                }
            },
        }


def _extract_output_text(payload: Mapping[str, Any]) -> str:
    direct = payload.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    fragments: list[str] = []
    output = payload.get("output")
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, Mapping):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if isinstance(part, Mapping) and isinstance(part.get("text"), str):
                    fragments.append(str(part["text"]))
    text = "".join(fragments).strip()
    if not text:
        raise ValueError("Responses payload contains no output text")
    return text


def _urlopen_transport(
    url: str,
    headers: Mapping[str, str],
    body: bytes,
    timeout_s: float,
) -> Mapping[str, Any]:
    outbound = request.Request(url, data=body, headers=dict(headers), method="POST")
    try:
        with request.urlopen(outbound, timeout=timeout_s) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        raise OSError(f"Responses endpoint returned HTTP {exc.code}") from exc
    except error.URLError as exc:
        raise OSError("Responses endpoint request failed") from exc
    if not isinstance(payload, Mapping):
        raise ValueError("Responses payload root must be an object")
    return payload
