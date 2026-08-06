#!/usr/bin/env python3
"""Run the retrieval smoke cases against the configured Milvus Lite file."""

from __future__ import annotations

from pathlib import Path

import yaml

from xianglens.config import PROJECT_ROOT, Settings
from xianglens.storage.knowledge_store import MilvusKnowledgeStore, create_embedder


def main() -> None:
    settings = Settings()
    embedder = create_embedder(
        settings.embedding_provider,
        settings.embedding_model,
        settings.embedding_dimension,
    )
    store = MilvusKnowledgeStore(settings.milvus_uri, embedder)
    cases_path = Path(PROJECT_ROOT / "data/evaluation/rag_smoke_queries.yaml")
    cases = yaml.safe_load(cases_path.read_text(encoding="utf-8"))
    failures: list[str] = []
    for case in cases:
        cards = store.search(case["query"], case["enabled_packs"], settings.rag_top_k)
        returned_tags = {tag for card in cards for tag in card.tags}
        passed = bool(returned_tags.intersection(case["expected_any_tags"]))
        print(f"{'PASS' if passed else 'FAIL'} {case['id']}: {[card.card_id for card in cards]}")
        if not passed:
            failures.append(case["id"])
    if failures:
        raise SystemExit(f"RAG smoke failures: {', '.join(failures)}")
    print(f"All {len(cases)} RAG smoke queries passed.")


if __name__ == "__main__":
    main()
