from __future__ import annotations

from datetime import date

from app.rag.corpus import LegalCorpusStore, load_manifest
from app.rag.embeddings import HashEmbeddingProvider
from app.rag.index import LegalVectorIndex


def test_qdrant_local_index_recovers_and_filters_metadata(tmp_path):
    documents, chunks = load_manifest("data/laws/source_manifest.json")
    corpus = LegalCorpusStore(tmp_path / "corpus.sqlite3")
    corpus.replace(documents, chunks)
    path = tmp_path / "qdrant"
    embedding = HashEmbeddingProvider(dimension=128)
    first = LegalVectorIndex(path, embedding)
    first.rebuild(chunks)
    expected_count = first.count()
    first.close()

    reopened = LegalVectorIndex(path, embedding)
    try:
        assert reopened.count() == expected_count == len(chunks)
        hits = reopened.search(
            "事故责任",
            jurisdiction="中华人民共和国",
            document_types={"law", "department_rule"},
            effective_as_of=date(2024, 1, 1),
        )
        by_id = {item.source_id: item for item in chunks}
        assert hits
        assert all(
            by_id[source_id].jurisdiction == "中华人民共和国"
            and by_id[source_id].document_type.value in {"law", "department_rule"}
            and by_id[source_id].effective_date <= date(2024, 1, 1)
            for source_id, _score in hits
        )
    finally:
        reopened.close()
