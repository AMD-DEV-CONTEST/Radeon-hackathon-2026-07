from __future__ import annotations

from dataclasses import dataclass
from typing import Any


TOOL_ENVELOPE_VERSION = "tool_execution_envelope.v0"
RUNTIME_CONTROL_EVIDENCE_KEY = "runtime_control"
RUNTIME_CONTROL_WAIT_ACTION = "wait"


@dataclass(frozen=True, slots=True)
class ToolEnvelopePayload:
    output: dict[str, Any]
    evidence: dict[str, Any]
    summary: str
    execution_status: str
    error: str
    retryable: bool


def tool_envelope(
    output: dict[str, Any] | None = None,
    *,
    evidence: dict[str, Any] | None = None,
    summary: str = "",
    execution_status: str = "completed",
    error: str = "",
    retryable: bool = False,
) -> dict[str, Any]:
    normalized_status = str(execution_status or "").strip()
    if normalized_status not in {"completed", "failed"}:
        raise ValueError("tool envelope execution_status must be completed or failed")
    normalized_error = str(error or "").strip()
    if normalized_status == "failed" and not normalized_error:
        raise ValueError("failed tool envelope requires error")
    if normalized_status == "completed" and normalized_error:
        raise ValueError("completed tool envelope cannot contain error")
    return {
        "version": TOOL_ENVELOPE_VERSION,
        "execution": {
            "status": normalized_status,
            "error": normalized_error,
            "retryable": bool(retryable),
        },
        "output": dict(output or {}),
        "evidence": dict(evidence or {}),
        "summary": summary,
    }


def tool_failure(
    error: str,
    *,
    output: dict[str, Any] | None = None,
    evidence: dict[str, Any] | None = None,
    summary: str = "",
    retryable: bool = False,
) -> dict[str, Any]:
    return tool_envelope(
        output,
        evidence=evidence,
        summary=summary,
        execution_status="failed",
        error=error,
        retryable=retryable,
    )


def is_tool_envelope(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and value.get("version") == TOOL_ENVELOPE_VERSION
        and isinstance(value.get("execution"), dict)
        and isinstance(value.get("output"), dict)
    )


def unpack_tool_envelope(value: dict[str, Any]) -> ToolEnvelopePayload:
    if not is_tool_envelope(value):
        raise ValueError("tool entrypoint must return tool_execution_envelope.v0")
    execution = dict(value.get("execution") or {})
    execution_status = str(execution.get("status") or "").strip()
    error = str(execution.get("error") or "").strip()
    retryable = execution.get("retryable")
    if execution_status not in {"completed", "failed"}:
        raise ValueError("tool envelope execution.status must be completed or failed")
    if not isinstance(retryable, bool):
        raise ValueError("tool envelope execution.retryable must be boolean")
    if execution_status == "failed" and not error:
        raise ValueError("failed tool envelope requires execution.error")
    if execution_status == "completed" and error:
        raise ValueError("completed tool envelope cannot contain execution.error")
    evidence = value.get("evidence")
    return ToolEnvelopePayload(
        output=dict(value.get("output") or {}),
        evidence=dict(evidence) if isinstance(evidence, dict) else {},
        summary=str(value.get("summary") or "").strip(),
        execution_status=execution_status,
        error=error,
        retryable=retryable,
    )


def runtime_wait_evidence(*, status: str, reason: str) -> dict[str, Any]:
    clean_status = str(status or "").strip()
    clean_reason = str(reason or "").strip()
    if not clean_status:
        raise ValueError("runtime wait status is required")
    if not clean_reason:
        raise ValueError("runtime wait reason is required")
    return {
        RUNTIME_CONTROL_EVIDENCE_KEY: {
            "action": RUNTIME_CONTROL_WAIT_ACTION,
            "status": clean_status,
            "reason": clean_reason,
        }
    }


def runtime_wait_control(observations: list[dict[str, Any]]) -> dict[str, str] | None:
    controls: list[dict[str, str]] = []
    for observation in observations:
        evidence = observation.get("evidence") if isinstance(observation, dict) else None
        control = evidence.get(RUNTIME_CONTROL_EVIDENCE_KEY) if isinstance(evidence, dict) else None
        if not isinstance(control, dict) or str(control.get("action") or "").strip() != RUNTIME_CONTROL_WAIT_ACTION:
            continue
        status = str(control.get("status") or "").strip()
        reason = str(control.get("reason") or "").strip()
        if status and reason:
            controls.append({"status": status, "reason": reason})
    if not controls:
        return None
    statuses = {item["status"] for item in controls}
    if len(statuses) != 1:
        raise ValueError(f"conflicting runtime wait statuses: {sorted(statuses)}")
    return controls[-1]
