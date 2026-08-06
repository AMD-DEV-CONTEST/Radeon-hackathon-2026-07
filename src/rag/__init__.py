"""RAG (Retrieval-Augmented Generation) package for Bunker."""

from .embeddings import ROCEmbeddings
from .vector_store import VectorStore
from .document_loader import DocumentLoader, RecursiveCharacterTextSplitter
from .parent_store import ParentDocumentStore
from .reranker import Reranker
from .batch_ingest import BatchIngestor
from .hybrid_store import HybridVectorStore
from .multihop_rag import (
    AppendNotes,
    BunkerGroundingError,
    BunkerMultiHopRAG,
    DEFAULT_ARTIFACT_PATH,
    GenerateQuery,
    GroundedAnswer,
    extract_citations,
    load_bunker_rag_program,
    make_chromadb_search,
)

__all__ = [
    "ROCEmbeddings",
    "VectorStore",
    "DocumentLoader",
    "RecursiveCharacterTextSplitter",
    "ParentDocumentStore",
    "Reranker",
    "BatchIngestor",
    "HybridVectorStore",
    "BunkerMultiHopRAG",
    "BunkerGroundingError",
    "make_chromadb_search",
    "extract_citations",
    "load_bunker_rag_program",
    "DEFAULT_ARTIFACT_PATH",
    "GenerateQuery",
    "AppendNotes",
    "GroundedAnswer",
]
