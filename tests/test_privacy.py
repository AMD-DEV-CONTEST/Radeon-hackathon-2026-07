import pytest
import os
import json
import types
from unittest.mock import patch

import dspy

from src.privacy import AuditLogger, DataFlowMonitor, DataEncryptor

@pytest.fixture
def audit_logger(tmp_path):
    log_file = tmp_path / "audit.log"
    return AuditLogger(log_file=str(log_file))

def test_audit_logger_log_event(audit_logger, tmp_path):
    """log() writes to file"""
    audit_logger.log("test_event", {"key": "value"})
    log_content = (tmp_path / "audit.log").read_text()
    assert "test_event" in log_content
    assert "value" in log_content

def test_audit_logger_log_inference(audit_logger, tmp_path):
    """log_inference creates correct event type"""
    audit_logger.log_inference("Qwen", 100, 50, 0.5)
    events = audit_logger.get_recent_events(1)
    assert events[0]["event_type"] == "inference"
    assert events[0]["details"]["model"] == "Qwen"

def test_audit_logger_log_tool_call(audit_logger):
    """log_tool_call records tool name"""
    audit_logger.log_tool_call("file_read", {"path": "a.txt"}, "Success")
    events = audit_logger.get_recent_events(1)
    assert events[0]["event_type"] == "tool_call"
    assert events[0]["details"]["tool_name"] == "file_read"

def test_audit_logger_get_stats(audit_logger):
    """get_stats returns dict with required fields"""
    audit_logger.log_inference("M1", 10, 10, 0.1)
    stats = audit_logger.get_stats()
    assert "total_events" in stats
    assert stats["total_events"] == 1

def test_audit_logger_get_recent_events(audit_logger):
    """returns list of N most recent events"""
    for i in range(5):
        audit_logger.log(f"event_{i}", {})
    recent = audit_logger.get_recent_events(3)
    assert len(recent) == 3
    assert recent[0]["event_type"] == "event_4"

@pytest.fixture
def data_flow_monitor():
    return DataFlowMonitor()

def test_data_flow_monitor_record_event(data_flow_monitor):
    """record_event increments counters"""
    data_flow_monitor.record_event("local", 100)
    assert data_flow_monitor.stats["local"]["bytes"] == 100
    assert data_flow_monitor.stats["local"]["count"] == 1

def test_data_flow_monitor_local_percentage(data_flow_monitor):
    """local_percentage = local/(local+external)*100"""
    data_flow_monitor.record_event("local", 80)
    data_flow_monitor.record_event("external", 20)
    assert data_flow_monitor.get_local_percentage() == 80.0

def test_data_flow_monitor_listener(data_flow_monitor):
    """listener called on new event"""
    called = []
    data_flow_monitor.add_listener(lambda e: called.append(e))
    data_flow_monitor.record_event("local", 10)
    assert len(called) == 1

def test_data_flow_monitor_get_status_fields(data_flow_monitor):
    """get_current_status has all required keys"""
    data_flow_monitor.record_event("local", 10)
    status = data_flow_monitor.get_current_status()
    assert "local_percentage" in status
    assert "total_bytes_processed" in status
    assert "alerts" in status

@pytest.fixture
def encryptor(tmp_path):
    key_file = tmp_path / "secret.key"
    return DataEncryptor(key_file=str(key_file))

def test_data_encryptor_encrypt_decrypt(encryptor):
    """encrypt then decrypt returns original string"""
    original = "sensitive data"
    encrypted = encryptor.encrypt(original)
    assert encrypted != original
    decrypted = encryptor.decrypt(encrypted)
    assert decrypted == original

def test_data_encryptor_key_generated(tmp_path):
    """generates key file if missing"""
    key_file = tmp_path / "new.key"
    assert not key_file.exists()
    enc = DataEncryptor(key_file=str(key_file))
    assert key_file.exists()
    assert len(key_file.read_bytes()) > 0


# ---------------------------------------------------------------------------
# Inference telemetry: local vs external vs failed
# ---------------------------------------------------------------------------


def test_is_local_backend_classification():
    """vllm/ollama/local_secondary are local; radeon_api/failed are not."""
    from src.privacy.telemetry import (
        BACKEND_VLLM,
        BACKEND_OLLAMA,
        BACKEND_LOCAL_SECONDARY,
        BACKEND_RADEON_API,
        BACKEND_FAILED,
        is_local_backend,
    )

    assert is_local_backend(BACKEND_VLLM) is True
    assert is_local_backend(BACKEND_OLLAMA) is True
    assert is_local_backend(BACKEND_LOCAL_SECONDARY) is True
    assert is_local_backend(BACKEND_RADEON_API) is False
    assert is_local_backend(BACKEND_FAILED) is False
    assert is_local_backend(None) is True


def test_audit_logger_inference_stats_local_external_failed(tmp_path):
    """get_stats groups inferences into local/external/failed buckets."""
    audit = AuditLogger(log_path=str(tmp_path / "audit.jsonl"))
    audit.log_inference("Qwen", 10, 5, "vllm")
    audit.log_inference("Qwen", 10, 5, "ollama")
    audit.log_inference("Qwen", 10, 5, "local_secondary")
    audit.log_inference("Qwen", 10, 5, "radeon_api")
    audit.log_inference("Qwen", 0, 0, "failed")

    stats = audit.get_stats()
    assert stats["inference_count"] == 5
    assert stats["local_inferences"] == 3
    assert stats["external_inferences"] == 1
    assert stats["failed_inferences"] == 1
    assert stats["inferences_by_backend"] == {
        "vllm": 1,
        "ollama": 1,
        "local_secondary": 1,
        "radeon_api": 1,
        "failed": 1,
    }
    assert stats["inference_local_percentage"] == 60.0


def test_telemetry_local_inference_increments_local_counters(tmp_path):
    """A vllm (local) inference increments local counts on both sinks."""
    from src.privacy.telemetry import InferenceTelemetry

    monitor = DataFlowMonitor()
    audit = AuditLogger(log_path=str(tmp_path / "audit.jsonl"))
    tel = InferenceTelemetry()
    tel.configure(audit_logger=audit, data_flow_monitor=monitor, backend="vllm")

    tel.record_inference(model="Qwen", prompt_tokens=10, completion_tokens=5)

    counts = monitor.get_current_status()["inference_counts"]
    assert counts["local"] == 1
    assert counts["external"] == 0
    assert counts["failed"] == 0
    assert monitor.stats["local"]["bytes"] > 0
    assert monitor.stats["external"]["bytes"] == 0

    stats = audit.get_stats()
    assert stats["local_inferences"] == 1
    assert stats["external_inferences"] == 0


def test_telemetry_radeon_api_increments_external_counters(tmp_path):
    """A radeon_api (external) inference increments external counts."""
    from src.privacy.telemetry import InferenceTelemetry

    monitor = DataFlowMonitor()
    audit = AuditLogger(log_path=str(tmp_path / "audit.jsonl"))
    tel = InferenceTelemetry()
    tel.configure(audit_logger=audit, data_flow_monitor=monitor, backend="radeon_api")

    tel.record_inference(model="Qwen", prompt_tokens=10, completion_tokens=5)

    counts = monitor.get_current_status()["inference_counts"]
    assert counts["external"] == 1
    assert counts["local"] == 0
    assert monitor.stats["external"]["bytes"] > 0
    assert monitor.stats["local"]["bytes"] == 0

    stats = audit.get_stats()
    assert stats["external_inferences"] == 1
    assert stats["local_inferences"] == 0
    assert stats["inferences_by_backend"]["radeon_api"] == 1


def test_telemetry_failed_inference_never_local(tmp_path):
    """A failed inference never counts as local."""
    from src.privacy.telemetry import InferenceTelemetry

    monitor = DataFlowMonitor()
    audit = AuditLogger(log_path=str(tmp_path / "audit.jsonl"))
    tel = InferenceTelemetry()
    tel.configure(audit_logger=audit, data_flow_monitor=monitor)

    tel.record_inference(model="Qwen", error=RuntimeError("boom"))

    counts = monitor.get_current_status()["inference_counts"]
    assert counts["failed"] == 1
    assert counts["local"] == 0
    assert counts["external"] == 0

    stats = audit.get_stats()
    assert stats["failed_inferences"] == 1
    assert stats["local_inferences"] == 0
    assert stats["inferences_by_backend"]["failed"] == 1


def _fake_completion_response(text: str):
    """Build an OpenAI chat-completion-shaped object for a mocked LM forward."""
    from src import dspy_runtime

    message = types.SimpleNamespace(content=text, tool_calls=None)
    choice = types.SimpleNamespace(message=message, finish_reason="stop", logprobs=None)
    return types.SimpleNamespace(
        choices=[choice],
        model=dspy_runtime.BUNKER_LM.model,
        usage={"prompt_tokens": 5, "completion_tokens": 4, "total_tokens": 9},
        cache_hit=False,
        _hidden_params={},
    )


def test_telemetry_lm_wrapper_records_local_inference(tmp_path):
    """A real DSPy LM call (through _TelemetryLM.forward) is audited as local."""
    from src import dspy_runtime

    monitor = DataFlowMonitor()
    audit = AuditLogger(log_path=str(tmp_path / "audit.jsonl"))
    dspy_runtime.configure_telemetry(audit_logger=audit, data_flow_monitor=monitor)
    fake = _fake_completion_response("42")

    try:
        with patch.object(dspy.LM, "forward", return_value=fake):
            result = dspy_runtime.BUNKER_LM(prompt="2+2")
        assert str(result[0]).strip() == "42"

        counts = monitor.get_current_status()["inference_counts"]
        assert counts["local"] == 1
        assert counts["external"] == 0
        assert counts["failed"] == 0

        stats = audit.get_stats()
        assert stats["local_inferences"] == 1
        assert stats["inferences_by_backend"].get("vllm") == 1
    finally:
        dspy_runtime.configure_telemetry()


def test_telemetry_lm_wrapper_records_external_backend(tmp_path):
    """With the radeon_api backend configured, LM calls are external."""
    from src import dspy_runtime

    monitor = DataFlowMonitor()
    audit = AuditLogger(log_path=str(tmp_path / "audit.jsonl"))
    dspy_runtime.configure_telemetry(
        audit_logger=audit,
        data_flow_monitor=monitor,
        backend="radeon_api",
    )
    fake = _fake_completion_response("42")

    try:
        with patch.object(dspy.LM, "forward", return_value=fake):
            dspy_runtime.BUNKER_LM(prompt="2+2")

        counts = monitor.get_current_status()["inference_counts"]
        assert counts["external"] == 1
        assert counts["local"] == 0

        stats = audit.get_stats()
        assert stats["external_inferences"] == 1
        assert stats["inferences_by_backend"].get("radeon_api") == 1
    finally:
        dspy_runtime.configure_telemetry()
        dspy_runtime.configure_telemetry(backend="vllm")


def test_data_flow_monitor_inference_counts_by_locality():
    """get_current_status exposes per-locality inference counts."""
    from src.privacy.telemetry import InferenceTelemetry

    monitor = DataFlowMonitor()
    tel = InferenceTelemetry()
    tel.configure(data_flow_monitor=monitor, backend="vllm")

    tel.record_inference(model="Qwen", prompt_tokens=10, completion_tokens=5)
    tel.configure(backend="radeon_api")
    tel.record_inference(model="Qwen", prompt_tokens=10, completion_tokens=5)
    tel.record_inference(model="Qwen", error=RuntimeError("down"))

    status = monitor.get_current_status()
    assert status["inference_counts"] == {"local": 1, "external": 1, "failed": 1}


# ---------------------------------------------------------------------------
# PrivacyDashboard: real local vs external (no hardcoded assumptions)
# ---------------------------------------------------------------------------


def test_dashboard_fully_local_when_all_inferences_local(tmp_path):
    """All-local audit history yields a 100% local dashboard."""
    from src.privacy.dashboard import PrivacyDashboard

    audit = AuditLogger(log_path=str(tmp_path / "audit.jsonl"))
    audit.log_inference("Qwen", 10, 5, "vllm")
    monitor = DataFlowMonitor()
    dashboard = PrivacyDashboard(audit_logger=audit, data_flow_monitor=monitor)

    data = dashboard.get_dashboard_data()
    assert data["local_inference_pct"] == 100.0
    assert data["local_inferences"] == 1
    assert data["external_inferences"] == 0
    assert data["failed_inferences"] == 0
    assert data["radeon_api_inferences"] == 0
    assert data["total_inferences"] == 1
    assert data["is_fully_local"] is True


def test_dashboard_reflects_model_manager_fallback_stats(tmp_path):
    """Dashboard reports model_manager backend counters and audit breakdown."""
    from src.config import InferenceConfig
    from src.inference.model_manager import ModelManager
    from src.privacy.dashboard import PrivacyDashboard

    audit = AuditLogger(log_path=str(tmp_path / "audit.jsonl"))
    monitor = DataFlowMonitor()
    mm = ModelManager(InferenceConfig(), audit_logger=audit, data_flow_monitor=monitor)

    audit.log_inference("Qwen", 10, 5, "vllm")
    audit.log_inference("Qwen", 10, 5, "radeon_api")
    mm._record_inference("vllm", "Qwen", 10, 5)
    mm._record_inference("radeon_api", "Qwen", 10, 5)

    dashboard = PrivacyDashboard(audit_logger=audit, data_flow_monitor=monitor, model_manager=mm)
    data = dashboard.get_dashboard_data()

    fallback = data["fallback_stats"]
    assert fallback["vllm"] == 1
    assert fallback["local_secondary"] == 0
    assert fallback["radeon_api"] == 1
    assert fallback["failed"] == 0
    assert fallback["local_count"] == 1
    assert fallback["external_count"] == 1
    assert fallback["failed_count"] == 0

    assert data["local_inferences"] == 1
    assert data["external_inferences"] == 1
    assert data["radeon_api_inferences"] == 1
    assert data["local_inference_pct"] == 50.0
    assert data["is_fully_local"] is False


def test_dashboard_marks_not_fully_local_on_external_or_failed(tmp_path):
    """An external or failed inference breaks the '100% local' claim."""
    from src.privacy.dashboard import PrivacyDashboard

    audit = AuditLogger(log_path=str(tmp_path / "audit.jsonl"))
    audit.log_inference("Qwen", 10, 5, "vllm")
    audit.log_inference("Qwen", 0, 0, "failed")
    monitor = DataFlowMonitor()
    dashboard = PrivacyDashboard(audit_logger=audit, data_flow_monitor=monitor)

    data = dashboard.get_dashboard_data()
    assert data["failed_inferences"] == 1
    assert data["local_inferences"] == 1
    assert data["local_inference_pct"] == 50.0
    assert data["is_fully_local"] is False
    assert "Not fully local" in dashboard.get_formatted_status()


def test_tool_events_still_recorded_after_inferences(tmp_path):
    """Tool events keep flowing alongside inference telemetry."""
    from src.privacy.telemetry import InferenceTelemetry

    monitor = DataFlowMonitor()
    audit = AuditLogger(log_path=str(tmp_path / "audit.jsonl"))
    tel = InferenceTelemetry()
    tel.configure(audit_logger=audit, data_flow_monitor=monitor, backend="vllm")

    tel.record_inference(model="Qwen", prompt_tokens=10, completion_tokens=5)
    monitor.record_event(
        event_type="tool_call",
        source="dspy_agent",
        destination="local_tool:file_read",
        bytes_count=7,
        is_local=True,
        metadata={"tool": "file_read", "approved": True},
    )
    audit.log_tool_call("file_read", {"path": "a.txt"}, "Success")

    status = monitor.get_current_status()
    tool_events = {
        e["metadata"].get("tool")
        for e in status["recent_events"]
        if e["event_type"] == "tool_call"
    }
    assert "file_read" in tool_events
    assert status["inference_counts"]["local"] == 1

    stats = audit.get_stats()
    assert stats["inference_count"] == 1
    assert stats["tool_call_count"] == 1
    assert stats["total_events"] == 2
