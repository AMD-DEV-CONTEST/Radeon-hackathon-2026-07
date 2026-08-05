"""Basic smoke tests — expand as orchestrator logic is implemented."""
from src.orchestrator.memory import ConversationMemory
from src.orchestrator.permissions import PermissionManager


def test_memory_appends_and_trims():
    mem = ConversationMemory(max_turns=2)
    mem.add("user", "hello")
    mem.add("assistant", "hi")
    mem.add("user", "second question")
    assert len(mem.as_messages()) == 2


def test_permission_redaction():
    pm = PermissionManager()
    data = {"src_ip": "10.0.0.5", "severity": "high"}
    redacted = pm.redact(data, role="trainee")
    assert redacted["src_ip"] == "[redacted]"
    assert redacted["severity"] == "high"
