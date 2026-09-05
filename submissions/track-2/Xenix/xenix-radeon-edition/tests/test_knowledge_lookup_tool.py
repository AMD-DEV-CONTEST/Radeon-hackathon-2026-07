from pathlib import Path

from xenix.config import ensure_app_dirs, get_app_paths
from xenix.services.agent.knowledge_tool import register_knowledge_lookup_tool
from xenix.services.knowledge_service import (
    KnowledgeRetrievalUnavailable,
    KnowledgeService,
)
from xenix.services.llm import (
    AgentToolRegistry,
    ToolExecutionContext,
    ToolFailure,
    ToolSuccess,
)
from xenix.services.storage import StorageBootstrapService
from tests.knowledge_test_support import seed_knowledge_text


def _registry(
    monkeypatch,
    tmp_path: Path,
) -> tuple[AgentToolRegistry, KnowledgeService]:
    monkeypatch.setenv("XENIX_APP_HOME", str(tmp_path / "xenix-home"))
    paths = ensure_app_dirs(get_app_paths())
    context = StorageBootstrapService().initialize(paths)
    service = KnowledgeService(context.session_factory)
    registry = AgentToolRegistry()
    register_knowledge_lookup_tool(registry, service)
    return registry, service


def _invoke_service(service, arguments: dict) -> ToolSuccess | ToolFailure:
    registry = AgentToolRegistry()
    register_knowledge_lookup_tool(registry, service)
    return registry.invoke(
        tool_name="knowledge.lookup",
        provider_name="knowledge_lookup",
        arguments=arguments,
        context=ToolExecutionContext(thread_id="thread-1"),
    )


def test_lookup_tool_returns_one_minimal_value_for_auto_and_keyword(
    monkeypatch,
    tmp_path: Path,
) -> None:
    registry, service = _registry(monkeypatch, tmp_path)
    seed_knowledge_text(
        service,
        title="华东备货规则",
        text="雨具目标库存为三周平均销量，补货量扣除现有库存。",
    )

    outcomes = [
        registry.invoke(
            tool_name="knowledge.lookup",
            provider_name="knowledge_lookup",
            arguments=arguments,
            context=ToolExecutionContext(thread_id="thread-1"),
        )
        for arguments in (
            {"query": "雨具补货"},
            {"query": "雨具补货", "mode": "keyword"},
        )
    ]

    expected = {
        "mode": "keyword",
        "results": [
            {
                "source": "华东备货规则",
                "location": "passage 1",
                "excerpt": "雨具目标库存为三周平均销量，补货量扣除现有库存。",
            }
        ],
    }
    assert all(isinstance(outcome, ToolSuccess) for outcome in outcomes)
    assert [
        outcome.value for outcome in outcomes if isinstance(outcome, ToolSuccess)
    ] == [expected, expected]


def test_lookup_tool_exposes_unavailable_semantic_mode_without_hidden_fallback() -> None:
    class _NeverLookup:
        def retrieve(self, _query: str, **_kwargs):
            raise KnowledgeRetrievalUnavailable(
                requested_mode="semantic",
                available_modes=["keyword"],
            )

    outcome = _invoke_service(
        _NeverLookup(),
        {"query": "雨季规则", "mode": "semantic"},
    )

    assert isinstance(outcome, ToolFailure)
    assert outcome.code == "knowledge_retrieval_mode_unavailable"
    assert outcome.details == {
        "requested_mode": "semantic",
        "available_modes": ["keyword"],
    }
    assert outcome.retryable is False
