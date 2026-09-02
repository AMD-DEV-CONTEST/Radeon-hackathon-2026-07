"""RAG pipeline — document import, chunking, indexing, and retrieval."""

from app.rag.manifest import (
    SourceFile,
    ContentChunk,
    ParsedDocument,
    ImportResult,
    compute_sha256,
    build_source_file,
    build_rejected_source_file,
)
from app.rag.scanner import ScannedSourceEntry, scan_source_dir, scan_source_entries, is_path_safe
from app.rag.parsers import (
    parse_file,
    parse_markdown,
    parse_txt,
    parse_pdf,
    parse_docx,
    parse_xlsx,
    import_project,
)
from app.rag.chunker import split_document
from app.rag.embedder import HashEmbedder, LLMEmbedder, create_embedder
from app.rag.indexer import ProjectIndex
from app.rag.qa_service import (
    NO_EVIDENCE_MSG,
    QABenchmark,
    QAResult,
    QAService,
)
from app.rag.retriever import Retriever

__all__ = [
    # manifest
    "SourceFile",
    "ContentChunk",
    "ParsedDocument",
    "ImportResult",
    "compute_sha256",
    "build_source_file",
    "build_rejected_source_file",
    # scanner
    "scan_source_dir",
    "scan_source_entries",
    "ScannedSourceEntry",
    "is_path_safe",
    # parsers
    "parse_file",
    "parse_markdown",
    "parse_txt",
    "parse_pdf",
    "parse_docx",
    "parse_xlsx",
    "import_project",
    # chunker (Phase B)
    "split_document",
    # embedder (Phase B)
    "HashEmbedder",
    "LLMEmbedder",
    "create_embedder",
    # indexer (Phase B)
    "ProjectIndex",
    # retriever (Phase B)
    "Retriever",
    # QA service (Phase B)
    "NO_EVIDENCE_MSG",
    "QABenchmark",
    "QAResult",
    "QAService",
]
