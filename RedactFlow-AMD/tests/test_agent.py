from pathlib import Path

from app.agent import RedactFlowAgent
from app.store import Store


def build_agent(tmp_path: Path) -> RedactFlowAgent:
    store = Store(tmp_path / "test.db")
    store.put_document(
        "doc1",
        "release.txt",
        "August rollback note. Contact ops@example.com or 13800138000.",
    )
    return RedactFlowAgent(store)


def test_execution_pauses_without_permissions(tmp_path: Path) -> None:
    agent = build_agent(tmp_path)
    plan = agent.create_plan("Prepare the August rollback release")
    result = agent.execute(plan.id, set())
    assert result.status == "blocked"
    assert set(result.blocked_tools) == {"redact_documents", "write_audit_memory"}
    assert result.redacted_documents == {}


def test_execution_completes_with_explicit_permissions(tmp_path: Path) -> None:
    agent = build_agent(tmp_path)
    plan = agent.create_plan("Prepare the August rollback release")
    result = agent.execute(plan.id, {"redact_documents", "write_audit_memory"})
    assert result.status == "completed"
    assert "[EMAIL]" in result.redacted_documents["release.txt"]
    assert result.evidence[0].document_id == "doc1"

