from app.rag import chunk_text, search, tokenize


def test_tokenize_supports_english_and_chinese() -> None:
    assert tokenize("Private 文档 2026") == ["private", "文", "档", "2026"]


def test_chunk_text_overlaps() -> None:
    chunks = chunk_text("a" * 1400, size=600, overlap=100)
    assert len(chunks) == 3
    assert chunks[0][-100:] == chunks[1][:100]


def test_search_returns_grounded_hit() -> None:
    documents = [
        {"id": "one", "name": "release.txt", "content": "The rollback rehearsal happens in August."},
        {"id": "two", "name": "menu.txt", "content": "Lunch includes noodles."},
    ]
    hits = search("August rollback", documents)
    assert hits[0]["document_id"] == "one"
    assert "rollback" in hits[0]["excerpt"]

