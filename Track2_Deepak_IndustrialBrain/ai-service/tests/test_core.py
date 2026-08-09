from app.extraction import extract_entities, classify_document
from app.index_store import embedding, chunk_pages


def test_entity_extraction():
    text = "On 12-Jun-2025 Pump P-101 showed high vibration at 8.2 mm/s and bearing wear."
    entities = extract_entities(text)
    assert "P-101" in entities["asset_tags"]
    assert "bearing wear" in entities["failures"]


def test_embedding_is_normalized():
    vector = embedding("pump bearing vibration")
    norm = sum(x * x for x in vector) ** 0.5
    assert abs(norm - 1.0) < 0.0001


def test_chunks_keep_page():
    chunks = chunk_pages([{"page": 3, "text": "A " * 1000}], size=200, overlap=20)
    assert len(chunks) > 1
    assert all(item["page"] == 3 for item in chunks)


def test_document_classification():
    assert classify_document("inspection.pdf", "pump data") == "Inspection Report"

