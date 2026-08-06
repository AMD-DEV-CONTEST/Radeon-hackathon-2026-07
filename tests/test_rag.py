import os
import json
import pytest
from unittest.mock import MagicMock, patch

from src.rag import (
    ROCEmbeddings,
    VectorStore,
    DocumentLoader,
    RecursiveCharacterTextSplitter,
    ParentDocumentStore,
    Reranker,
    BatchIngestor,
    HybridVectorStore,
)


# --- 1. ROCEmbeddings Tests ---

@patch("torch.cuda.is_available", return_value=False)
@patch("sentence_transformers.SentenceTransformer")
def test_roc_embeddings_bge_default(mock_st, mock_cuda):
    """Default model is BAAI/bge-large-en-v1.5 and adds query prefix"""
    mock_st.return_value.encode.return_value = [0.1, 0.2, 0.3]
    embeddings = ROCEmbeddings()
    assert embeddings.model_name == "BAAI/bge-large-en-v1.5"
    assert embeddings.device == "cpu"

    result = embeddings.embed_query("what is revenue?")
    assert isinstance(result, list)
    # Ensure query prefix was used
    mock_st.return_value.encode.assert_called_with(
        "Represent this sentence for searching relevant passages: what is revenue?",
        convert_to_numpy=True
    )


# --- 2. RecursiveCharacterTextSplitter Tests ---

def test_recursive_character_text_splitter_boundaries():
    """Recursive chunking respects paragraph/sentence boundaries"""
    splitter = RecursiveCharacterTextSplitter(chunk_size=30, chunk_overlap=0)
    text = "Paragraph one here.\n\nParagraph two here is longer."
    chunks = splitter.split_text(text)
    assert len(chunks) >= 2
    assert "Paragraph one here." in chunks[0]
    assert "Paragraph two" in chunks[1]


# --- 3. DocumentLoader & PDF Parsing Tests ---

def test_document_loader_pdf_parsing_fallback(tmp_path):
    """PDF loading falls back gracefully when pdf-inspector / PyMuPDF fail or succeed"""
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 test content")

    loader = DocumentLoader()

    with patch.object(loader, "_extract_pdf_pages", return_value=[{"text": "Page 1 content", "page": 1}]):
        chunks = loader.load_file(str(pdf_path))
        assert len(chunks) > 0
        assert chunks[0]["metadata"]["page"] == 1
        assert chunks[0]["metadata"]["filename"] == "sample.pdf"
        assert chunks[0]["metadata"]["file_type"] == ".pdf"


def test_document_loader_txt_loading(tmp_path):
    """DocumentLoader loads and chunks .txt files"""
    f = tmp_path / "doc.txt"
    f.write_text("Hello world.\n\nSecond paragraph content.")
    loader = DocumentLoader(chunk_size=50, chunk_overlap=5)
    chunks = loader.load_file(str(f))
    assert len(chunks) > 0
    assert chunks[0]["metadata"]["filename"] == "doc.txt"


# --- 4. VectorStore Metadata Filtering Tests ---

@pytest.fixture
def mock_vector_store():
    with patch("chromadb.PersistentClient"):
        store = VectorStore(collection_name="test_collection")
        store.collection = MagicMock()
        return store


def test_vector_store_metadata_filtering(mock_vector_store):
    """Metadata filter is passed into ChromaDB query"""
    mock_vector_store.collection.query.return_value = {
        "documents": [["filtered content"]],
        "metadatas": [[{"source": "report.pdf"}]],
        "distances": [[0.1]],
        "ids": [["doc_1"]]
    }

    results = mock_vector_store.search("query", top_k=2, filters={"source": "report.pdf"})
    assert len(results) == 1
    assert results[0]["metadata"]["source"] == "report.pdf"
    mock_vector_store.collection.query.assert_called_once_with(
        query_texts=["query"],
        n_results=2,
        where={"source": "report.pdf"}
    )


# --- 5. Parent Document Retriever Pattern Tests ---

def test_parent_document_store(tmp_path):
    """ParentDocumentStore stores parents and enriches child hits with parent context"""
    store_file = tmp_path / "parent_store.json"
    parent_store = ParentDocumentStore(storage_path=str(store_file))

    parent_id = parent_store.add_parent("p123", "Full parent context window paragraph text.")

    child_results = [
        {
            "id": "c1",
            "text": "child snippet",
            "metadata": {"parent_id": parent_id, "source": "doc.pdf"}
        }
    ]

    enriched = parent_store.enrich_results_with_parent(child_results)
    assert len(enriched) == 1
    assert "parent_text" in enriched[0]
    assert enriched[0]["parent_text"] == "Full parent context window paragraph text."


# --- 6. Reranker Tests ---

def test_reranker_scoring_and_fallback():
    """Reranker calculates rerank_score and falls back to original top_k when model unavailable"""
    reranker = Reranker()

    candidates = [
        {"text": "Apple pie recipe"},
        {"text": "Quantum computing tutorial"},
    ]

    # Test fallback path when model fails/unavailable
    with patch.object(reranker, "_load_model", return_value=None):
        results = reranker.rerank("quantum", candidates, top_k=1)
        assert len(results) == 1
        assert results[0]["text"] == "Apple pie recipe"

    # Test active model path with mock
    mock_model = MagicMock()
    mock_model.predict.return_value = [0.1, 0.95]
    with patch.object(reranker, "_load_model", return_value=mock_model):
        results = reranker.rerank("quantum", candidates, top_k=2)
        assert len(results) == 2
        assert results[0]["text"] == "Quantum computing tutorial"
        assert results[0]["rerank_score"] == 0.95


# --- 7. Batch Ingestion Tests ---

def test_batch_ingestor_resume_and_skipping(tmp_path):
    """BatchIngestor ingests files, updates manifest, and skips unchanged files"""
    manifest_file = tmp_path / "manifest.json"
    doc_file = tmp_path / "test_file.txt"
    doc_file.write_text("Unique batch ingestion text.")

    loader = DocumentLoader()
    vstore = MagicMock()
    vstore.add_documents.return_value = 1

    ingestor = BatchIngestor(
        document_loader=loader,
        vector_store=vstore,
        manifest_path=str(manifest_file)
    )

    # First run -> ingests
    res1 = ingestor.ingest_file(str(doc_file))
    assert res1["status"] == "indexed"
    assert res1["chunks_added"] == 1

    # Second run -> skips
    res2 = ingestor.ingest_file(str(doc_file))
    assert res2["status"] == "skipped"
    assert res2["chunks_added"] == 0


# --- 8. Hybrid Search Tests ---

def test_hybrid_vector_store_search(mock_vector_store):
    """HybridVectorStore combines BM25 and semantic results"""
    mock_vector_store.search.return_value = [
        {"text": "Vector result one", "metadata": {"source": "a.txt"}, "distance": 0.2}
    ]

    hybrid = HybridVectorStore(vector_store=mock_vector_store)
    corpus = [
        {"text": "Vector result one", "metadata": {"source": "a.txt"}},
        {"text": "BM25 keyword match result", "metadata": {"source": "b.txt"}},
    ]
    hybrid.index_documents(corpus)

    results = hybrid.search("keyword match", top_k=2)
    assert len(results) > 0
    assert any("BM25 keyword match result" in r["text"] for r in results)
