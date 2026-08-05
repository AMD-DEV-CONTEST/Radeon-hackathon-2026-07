"""
scripts/observability/event_logger.py — Structured JSON event logger.

Writes DeterminexEvent records to a daily JSONL log file under the configured
audit directory. One event per line. Safe for concurrent writers (atomic
line-level writes via os.fsync()).

Usage (from any pipeline stage):
    from observability.event_logger import emit, EventType

    emit(EventType.BASELINE_STARTED, task_id="t1", language="rust")
    emit(EventType.CORPUS_ROW_WRITTEN, task_id="t1", result="pass")

Live tail (show the factory working):
    tail -f T:/determinex_audit/events/2026-05-27.jsonl
  or
    determinex status --live   (future CLI surface)

The emit() call is non-blocking and fail-silent: a filesystem failure never
propagates to the pipeline caller. The factory must not stop because the
event log is full.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from observability.event_schema import DeterminexEvent, EventType

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_DEFAULT_AUDIT_DIR = Path(os.environ.get("DETERMINEX_AUDIT_DIR", "T:/determinex_audit/events"))

_FALLBACK_AUDIT_DIR = Path(os.environ.get("DETERMINEX_ROOT", ".")) / "logs" / "events"


def _audit_dir() -> Path:
    """Return the configured audit directory, falling back to logs/events/."""
    d = _DEFAULT_AUDIT_DIR
    if not d.exists():
        try:
            d.mkdir(parents=True, exist_ok=True)
            return d
        except OSError:
            pass
    if d.exists():
        return d
    # Fallback: local logs/events/
    _FALLBACK_AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    return _FALLBACK_AUDIT_DIR


def _today_log_path() -> Path:
    date_str = datetime.now(UTC).strftime("%Y-%m-%d")
    return _audit_dir() / f"{date_str}.jsonl"


# ---------------------------------------------------------------------------
# Core emit
# ---------------------------------------------------------------------------


def emit(
    event_type: EventType,
    *,
    task_id: str = "",
    session_id: str = "",
    language: str = "",
    verifier: str = "",
    result: str = "",
    reason: str = "",
    duration_ms: float = 0.0,
    trace_id: str = "",
    metadata: dict[str, Any] | None = None,
) -> DeterminexEvent:
    """
    Emit a structured event to the daily JSONL log.

    Non-blocking. Filesystem failures are logged but never propagated —
    a full disk must not stop the factory.

    Returns the DeterminexEvent (useful for tests and in-process subscribers).
    """
    evt = DeterminexEvent(
        event_type=event_type,
        task_id=task_id,
        session_id=session_id,
        language=language,
        verifier=verifier,
        result=result,
        reason=reason,
        duration_ms=duration_ms,
        metadata=metadata or {},
    )
    if trace_id:
        evt.trace_id = trace_id

    line = evt.to_json() + "\n"

    try:
        log_path = _today_log_path()
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())
    except OSError as exc:
        log.warning("[observability] Failed to write event %s: %s", event_type.value, exc)

    # Also emit to Python logging for console visibility
    log.debug("[event] %s", evt.to_json())

    return evt


# ---------------------------------------------------------------------------
# Convenience wrappers
# ---------------------------------------------------------------------------


def emit_task_accepted(task_id: str, language: str, reason: str = "") -> DeterminexEvent:
    return emit(
        EventType.TASK_ACCEPTED,
        task_id=task_id,
        language=language,
        result="accepted",
        reason=reason,
    )


def emit_task_denied(task_id: str, language: str, reason: str) -> DeterminexEvent:
    return emit(
        EventType.TASK_DENIED, task_id=task_id, language=language, result="denied", reason=reason
    )


def emit_baseline(
    task_id: str, language: str, passed: bool, verifier: str = "", duration_ms: float = 0.0
) -> DeterminexEvent:
    etype = EventType.BASELINE_COMPLETED if passed else EventType.BASELINE_FAILED
    return emit(
        etype,
        task_id=task_id,
        language=language,
        verifier=verifier,
        result="pass" if passed else "fail",
        duration_ms=duration_ms,
    )


def emit_corpus_written(task_id: str, language: str) -> DeterminexEvent:
    return emit(EventType.CORPUS_ROW_WRITTEN, task_id=task_id, language=language, result="written")


def emit_corpus_rejected(task_id: str, language: str, reason: str) -> DeterminexEvent:
    return emit(
        EventType.CORPUS_ROW_REJECTED,
        task_id=task_id,
        language=language,
        result="rejected",
        reason=reason,
    )


def emit_license_rejected(task_id: str, spdx: str, bucket: str) -> DeterminexEvent:
    return emit(EventType.LICENSE_REJECTED, task_id=task_id, reason=f"{spdx}:{bucket}")


def emit_cloak_applied(task_id: str, identifier_count: int) -> DeterminexEvent:
    return emit(
        EventType.CLOAK_APPLIED,
        task_id=task_id,
        result="applied",
        metadata={"identifier_count": identifier_count},
    )


def emit_cloak_failed(task_id: str, reason: str) -> DeterminexEvent:
    return emit(EventType.CLOAK_FAILED, task_id=task_id, result="failed", reason=reason)
