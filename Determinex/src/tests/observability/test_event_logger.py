"""
tests/observability/test_event_logger.py — Structured event emission tests.

Verifies:
  - emit() returns a DeterminexEvent with correct fields
  - to_json() produces valid JSON with event_type as string value
  - All required events in the schema are represented
  - Convenience wrappers set the correct event_type and result
  - emit() is fail-silent on filesystem errors (non-blocking guarantee)
  - DeterminexEvent.to_dict() has no Python enum values (JSON-serializable)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from observability.event_logger import (
    emit,
    emit_baseline,
    emit_cloak_applied,
    emit_cloak_failed,
    emit_corpus_rejected,
    emit_corpus_written,
    emit_license_rejected,
    emit_task_accepted,
    emit_task_denied,
)
from observability.event_schema import DeterminexEvent, EventType

# ---------------------------------------------------------------------------
# DeterminexEvent shape
# ---------------------------------------------------------------------------


def test_event_has_trace_id():
    evt = DeterminexEvent(event_type=EventType.TASK_ACCEPTED)
    assert evt.trace_id  # non-empty UUID


def test_event_has_timestamp():
    evt = DeterminexEvent(event_type=EventType.BASELINE_STARTED)
    assert "T" in evt.timestamp  # ISO format


def test_two_events_have_different_trace_ids():
    e1 = DeterminexEvent(event_type=EventType.TASK_ACCEPTED)
    e2 = DeterminexEvent(event_type=EventType.TASK_ACCEPTED)
    assert e1.trace_id != e2.trace_id


def test_to_dict_has_string_event_type():
    evt = DeterminexEvent(event_type=EventType.CORPUS_ROW_WRITTEN)
    d = evt.to_dict()
    assert d["event_type"] == "corpus.row_written"
    assert isinstance(d["event_type"], str)


def test_to_json_is_valid_json():
    evt = DeterminexEvent(event_type=EventType.COMPILE_PASS, task_id="t1", language="rust")
    raw = evt.to_json()
    parsed = json.loads(raw)
    assert parsed["event_type"] == "compile.pass"
    assert parsed["task_id"] == "t1"
    assert parsed["language"] == "rust"


def test_to_dict_has_no_enum_values():
    evt = DeterminexEvent(event_type=EventType.CLOAK_APPLIED, result="applied")
    d = evt.to_dict()
    for v in d.values():
        assert not isinstance(v, EventType), f"Found raw enum in to_dict(): {v!r}"


# ---------------------------------------------------------------------------
# EventType completeness
# ---------------------------------------------------------------------------


def test_event_type_has_task_lifecycle_events():
    assert EventType.TASK_ACCEPTED in EventType
    assert EventType.TASK_DENIED in EventType


def test_event_type_has_baseline_events():
    assert EventType.BASELINE_STARTED in EventType
    assert EventType.BASELINE_COMPLETED in EventType
    assert EventType.BASELINE_FAILED in EventType


def test_event_type_has_corpus_events():
    assert EventType.CORPUS_ROW_WRITTEN in EventType
    assert EventType.CORPUS_ROW_REJECTED in EventType


def test_event_type_has_cloak_events():
    assert EventType.CLOAK_APPLIED in EventType
    assert EventType.CLOAK_FAILED in EventType


def test_event_type_has_gate_events():
    assert EventType.LICENSE_REJECTED in EventType
    assert EventType.SUPPLY_CHAIN_REJECTED in EventType


def test_event_type_has_action_events():
    assert EventType.ACTION_ALLOWED in EventType
    assert EventType.ACTION_CONFIRMATION_REQUIRED in EventType
    assert EventType.ACTION_BLOCKED in EventType


# ---------------------------------------------------------------------------
# emit() returns correct DeterminexEvent
# ---------------------------------------------------------------------------


def test_emit_returns_determinex_event(tmp_path):
    with patch("observability.event_logger._audit_dir", return_value=tmp_path):
        evt = emit(EventType.TASK_ACCEPTED, task_id="t1", language="python")
    assert isinstance(evt, DeterminexEvent)
    assert evt.event_type == EventType.TASK_ACCEPTED
    assert evt.task_id == "t1"
    assert evt.language == "python"


def test_emit_writes_jsonl_line(tmp_path):
    with patch("observability.event_logger._audit_dir", return_value=tmp_path):
        emit(EventType.CORPUS_ROW_WRITTEN, task_id="corpus-001", language="rust")
    # Find the log file written today
    logs = list(tmp_path.glob("*.jsonl"))
    assert logs, "No JSONL log file created"
    lines = logs[0].read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["event_type"] == "corpus.row_written"
    assert parsed["task_id"] == "corpus-001"


def test_emit_multiple_events_appends(tmp_path):
    with patch("observability.event_logger._audit_dir", return_value=tmp_path):
        emit(EventType.BASELINE_STARTED, task_id="t1")
        emit(EventType.BASELINE_COMPLETED, task_id="t1", result="pass")
        emit(EventType.CORPUS_ROW_WRITTEN, task_id="t1")
    logs = list(tmp_path.glob("*.jsonl"))
    lines = logs[0].read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3


def test_emit_is_fail_silent_on_bad_path():
    """emit() must not raise even if the log directory is unwritable."""
    with patch(
        "observability.event_logger._today_log_path",
        return_value=Path("/nonexistent/dir/events.jsonl"),
    ):
        evt = emit(EventType.TASK_ACCEPTED, task_id="silent-test")
    # Must return the event even though write failed
    assert evt.task_id == "silent-test"


# ---------------------------------------------------------------------------
# Convenience wrappers
# ---------------------------------------------------------------------------


def test_emit_task_accepted(tmp_path):
    with patch("observability.event_logger._audit_dir", return_value=tmp_path):
        evt = emit_task_accepted("t1", "go")
    assert evt.event_type == EventType.TASK_ACCEPTED
    assert evt.result == "accepted"


def test_emit_task_denied(tmp_path):
    with patch("observability.event_logger._audit_dir", return_value=tmp_path):
        evt = emit_task_denied("t2", "go", reason="license_not_green")
    assert evt.event_type == EventType.TASK_DENIED
    assert evt.result == "denied"
    assert evt.reason == "license_not_green"


def test_emit_baseline_pass(tmp_path):
    with patch("observability.event_logger._audit_dir", return_value=tmp_path):
        evt = emit_baseline("t3", "rust", passed=True, verifier="cargo test")
    assert evt.event_type == EventType.BASELINE_COMPLETED
    assert evt.result == "pass"


def test_emit_baseline_fail(tmp_path):
    with patch("observability.event_logger._audit_dir", return_value=tmp_path):
        evt = emit_baseline("t4", "python", passed=False)
    assert evt.event_type == EventType.BASELINE_FAILED
    assert evt.result == "fail"


def test_emit_corpus_written(tmp_path):
    with patch("observability.event_logger._audit_dir", return_value=tmp_path):
        evt = emit_corpus_written("t5", "typescript")
    assert evt.event_type == EventType.CORPUS_ROW_WRITTEN


def test_emit_corpus_rejected(tmp_path):
    with patch("observability.event_logger._audit_dir", return_value=tmp_path):
        evt = emit_corpus_rejected("t6", "java", reason="tampered_signature")
    assert evt.event_type == EventType.CORPUS_ROW_REJECTED
    assert evt.reason == "tampered_signature"


def test_emit_license_rejected(tmp_path):
    with patch("observability.event_logger._audit_dir", return_value=tmp_path):
        evt = emit_license_rejected("t7", "GPL-3.0", "red")
    assert evt.event_type == EventType.LICENSE_REJECTED
    assert "GPL" in evt.reason


def test_emit_cloak_applied(tmp_path):
    with patch("observability.event_logger._audit_dir", return_value=tmp_path):
        evt = emit_cloak_applied("t8", identifier_count=142)
    assert evt.event_type == EventType.CLOAK_APPLIED
    assert evt.metadata["identifier_count"] == 142


def test_emit_cloak_failed(tmp_path):
    with patch("observability.event_logger._audit_dir", return_value=tmp_path):
        evt = emit_cloak_failed("t9", reason="AST parse failed")
    assert evt.event_type == EventType.CLOAK_FAILED
    assert "AST" in evt.reason
