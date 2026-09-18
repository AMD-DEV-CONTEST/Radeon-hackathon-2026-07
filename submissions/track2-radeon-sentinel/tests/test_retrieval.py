from pathlib import Path

from radeon_sentinel.retrieval import LocalRetriever


ROOT = Path(__file__).parents[1]


def test_retrieval_ranks_relevant_runbook() -> None:
    retriever = LocalRetriever.from_directory(ROOT / "demo_data/runbooks")

    results = retriever.search(
        "api latency timeout queue saturation", top_k=2
    )

    assert results
    assert results[0].source == "api-latency.md"
    assert "timeout" in results[0].excerpt.lower()


def test_empty_query_returns_no_evidence() -> None:
    retriever = LocalRetriever.from_directory(ROOT / "demo_data/runbooks")

    assert retriever.search("  ") == []


def test_retrieval_ignores_hidden_and_non_utf8_files(
    tmp_path: Path,
) -> None:
    runbooks = tmp_path / "runbooks"
    runbooks.mkdir()
    (runbooks / "valid.md").write_text(
        "Checkout latency is caused by queue saturation.",
        encoding="utf-8",
    )
    (runbooks / "._valid.md").write_bytes(b"\xa3AppleDouble metadata")
    (runbooks / "invalid.md").write_bytes(b"\xff\xfe\x00\x00")

    retriever = LocalRetriever.from_directory(runbooks)

    assert [document.source for document in retriever.documents] == [
        "valid.md"
    ]
    assert retriever.search("checkout latency")
