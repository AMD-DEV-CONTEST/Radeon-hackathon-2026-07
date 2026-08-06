import pytest
import os
import json

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
