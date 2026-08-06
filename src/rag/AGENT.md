# RAG Module — Bunker Maintainer Guide

> **Token-saving guide for AI agents working on `src/rag/`.**

---

## Module Overview

The `src/rag/` module handles local document ingestion, embedding generation, parent-child contextual indexing, hybrid (BM25 + Semantic) retrieval, reranking, and vector storage.

---

## Core Classes

| Class | File | Purpose |
|---|---|---|
| `ROCEmbeddings` | `embeddings.py` | GPU-accelerated embeddings (defaults to `BAAI/bge-large-en-v1.5` with query instruction prefix). |
| `VectorStore` | `vector_store.py` | ChromaDB wrapper with `anonymized_telemetry=False` and metadata filtering support. |
| `DocumentLoader` | `document_loader.py` | Multi-format loader with primary `pdf-inspector` and fallback `PyMuPDF` text extraction. |
| `RecursiveCharacterTextSplitter` | `document_loader.py` | Hierarchy-ordered text chunker (`\n\n`, `\n`, `. `, ` `, `""`). |
| `ParentDocumentStore` | `parent_store.py` | Parent-child document store mapping child snippets to parent context windows. |
| `Reranker` | `reranker.py` | CrossEncoder-based reranking (`cross-encoder/ms-marco-MiniLM-L-6-v2`) with lazy loading and fallback. |
| `BatchIngestor` | `batch_ingest.py` | Incremental ingestion manager with SHA256 manifest tracking and skip logic. |
| `HybridVectorStore` | `hybrid_store.py` | Reciprocal Rank Fusion (RRF) combining semantic vector search and BM25 lexical search. |

---

## Key Invariants & Rules

1. **Zero Data Exfiltration**: ChromaDB MUST keep `anonymized_telemetry=False`.
2. **Local Models Only**: Embeddings (`BAAI/bge-large-en-v1.5`) and Reranker (`cross-encoder/ms-marco-MiniLM-L-6-v2`) run locally via `sentence-transformers`.
3. **Resilient PDF Extraction**: `DocumentLoader` uses `pdf-inspector` first for structured markdown extraction, then falls back to `PyMuPDF` (`fitz`), then to raw reading. Individual corrupt pages are skipped rather than crashing the batch.
4. **BGE Query Prefixing**: `embed_query()` prepends `"Represent this sentence for searching relevant passages: "` when embedding queries with BGE models.
