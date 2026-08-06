from pathlib import Path

import pytest

from xenix.config import ensure_app_dirs, get_app_paths
from xenix.services.knowledge_service import (
    KnowledgeRetrievalUnavailable,
    KnowledgeSemanticCandidates,
    KnowledgeSemanticUnavailable,
    KnowledgeService,
)
from xenix.services.storage import StorageBootstrapService
from tests.knowledge_test_support import seed_knowledge_text


class _SemanticSearch:
    def __init__(self) -> None:
        self.unit_ids: list[str] = []
        self.error: Exception | None = None
        self.calls: list[tuple[str, str, int]] = []

    def is_configured(self) -> bool:
        return True

    def search(
        self,
        query: str,
        *,
        library_id: str,
        limit: int,
    ) -> KnowledgeSemanticCandidates:
        self.calls.append((query, library_id, limit))
        if self.error is not None:
            raise self.error
        return KnowledgeSemanticCandidates(
            unit_ids=tuple(self.unit_ids[:limit]),
            corpus_fingerprint="fake-corpus",
            profile_fingerprint="fake-profile",
            generation_id="fake-generation",
        )

    def is_current(
        self,
        _candidates: KnowledgeSemanticCandidates,
        *,
        library_id: str,
    ) -> bool:
        return library_id == "global"


def _service(
    monkeypatch,
    tmp_path: Path,
    *,
    semantic_search=None,
) -> KnowledgeService:
    monkeypatch.setenv("XENIX_APP_HOME", str(tmp_path / "xenix-home"))
    paths = ensure_app_dirs(get_app_paths())
    context = StorageBootstrapService().initialize(paths)
    return KnowledgeService(
        context.session_factory,
        semantic_search=semantic_search,
    )


def test_cjk_keyword_lookup_returns_bounded_source_linked_unit(
    monkeypatch,
    tmp_path: Path,
) -> None:
    service = _service(monkeypatch, tmp_path)
    document = seed_knowledge_text(
        service,
        title="华东雨季备货规则",
        text="8—9 月华东门店仅雨具按 3 周平均销量建立目标库存。\n\n防晒用品沿用常规库存策略。",
    )

    matches = service.lookup("华东雨季雨具备货")

    assert len(matches) == 1
    assert matches[0].document_id == document.id
    assert matches[0].title == "华东雨季备货规则"
    assert "3 周平均销量" in matches[0].quote
    assert matches[0].locator == {"passage": 1}


def test_semantic_mode_recovers_a_lexical_miss(monkeypatch, tmp_path: Path) -> None:
    semantic = _SemanticSearch()
    service = _service(monkeypatch, tmp_path, semantic_search=semantic)
    seed_knowledge_text(
        service,
        title="运营指引",
        text="防水出行品类按照最近三期周均销量设定目标量，并扣减现存数量。",
    )
    unit = service.lookup("防水出行")[0]
    semantic.unit_ids = [unit.unit_id]

    assert service.lookup("雨季商品补货规则") == []
    result = service.retrieve("雨季商品补货规则", mode="semantic")

    assert result.mode == "semantic"
    assert [match.unit_id for match in result.matches] == [unit.unit_id]
    assert semantic.calls == [("雨季商品补货规则", "global", 20)]


def test_auto_falls_back_honestly_but_explicit_semantic_does_not(
    monkeypatch,
    tmp_path: Path,
) -> None:
    semantic = _SemanticSearch()
    semantic.error = KnowledgeSemanticUnavailable()
    service = _service(monkeypatch, tmp_path, semantic_search=semantic)
    seed_knowledge_text(service, title="规则", text="雨具补货使用三周需求。")

    automatic = service.retrieve("雨具补货", mode="auto")

    assert automatic.mode == "keyword"
    assert len(automatic.matches) == 1
    with pytest.raises(KnowledgeRetrievalUnavailable) as error:
        service.retrieve("雨具补货", mode="semantic")
    assert error.value.available_modes == ["keyword"]
