from nexus.ingestion.chunker import chunk_text

def test_chunker_overlap():
    text = "a" * 2500
    chunks = chunk_text(text, chunk_size=1000, overlap=100)
    assert len(chunks) == 3
    assert chunks[0][-100:] == chunks[1][:100]
