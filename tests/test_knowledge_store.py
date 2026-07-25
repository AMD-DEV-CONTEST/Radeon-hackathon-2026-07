import yaml

from xianglens.config import PROJECT_ROOT
from xianglens.storage.knowledge_store import (
    HashingEmbedder,
    InMemoryKnowledgeStore,
    load_knowledge_records,
)


def test_all_rag_smoke_cases_retrieve_expected_tags() -> None:
    records = load_knowledge_records(
        PROJECT_ROOT / "data/knowledge/cards.yaml",
        PROJECT_ROOT / "data/knowledge/sources.yaml",
    )
    store = InMemoryKnowledgeStore(records, HashingEmbedder())
    cases = yaml.safe_load(
        (PROJECT_ROOT / "data/evaluation/rag_smoke_queries.yaml").read_text(encoding="utf-8")
    )
    failures = []
    for case in cases:
        cards = store.search(case["query"], case["enabled_packs"], limit=4)
        tags = {tag for card in cards for tag in card.tags}
        if not tags.intersection(case["expected_any_tags"]):
            failures.append(case["id"])
    assert failures == []


def test_card_schema_and_count() -> None:
    records = load_knowledge_records(
        PROJECT_ROOT / "data/knowledge/cards.yaml",
        PROJECT_ROOT / "data/knowledge/sources.yaml",
    )
    assert len(records) == 32
    assert len({record.card_id for record in records}) == 32
