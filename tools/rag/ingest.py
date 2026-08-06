from pathlib import Path

from .chunker import chunk_documents
from .config import CHUNK_OVERLAP, CHUNK_SIZE, DEFAULT_KB_ID
from .loaders import load_file
from .registry import (
    chunks_as_documents,
    file_hash,
    find_duplicate,
    load_registry,
    register_document,
    remove_document,
    save_registry,
)
from .store import add_chunks, rebuild_index


def ingest_file(
    file_path: str,
    kb_id: str = DEFAULT_KB_ID,
    chunk_size: int = CHUNK_SIZE,
    chunk_overlap: int = CHUNK_OVERLAP,
) -> dict:
    """Ingest a single file: dedup check -> load -> chunk -> embed -> index.

    Returns a dict matching the CLI contract's expected ingest output:
    { "doc_id", "chunks", "kb_id" } — plus a "status" field for visibility.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    registry = load_registry(kb_id)
    hash_value = file_hash(path)

    existing_doc_id = find_duplicate(registry, hash_value)
    if existing_doc_id:
        return {
            "doc_id": existing_doc_id,
            "chunks": registry["documents"][existing_doc_id]["chunks"],
            "kb_id": kb_id,
            "status": "duplicate",
        }

    docs = load_file(path)  # raises ValueError on empty/unsupported files
    chunks = chunk_documents(docs, chunk_size=chunk_size, chunk_overlap=chunk_overlap)

    doc_id = register_document(registry, path.name, hash_value, chunks)
    save_registry(kb_id, registry)
    add_chunks(kb_id, chunks)

    return {"doc_id": doc_id, "chunks": len(chunks), "kb_id": kb_id, "status": "indexed"}


def delete_document(doc_id: str, kb_id: str = DEFAULT_KB_ID) -> bool:
    registry = load_registry(kb_id)
    removed = remove_document(registry, doc_id)
    if not removed:
        return False

    save_registry(kb_id, registry)
    rebuild_index(kb_id, chunks_as_documents(registry))
    return True


def list_documents(kb_id: str = DEFAULT_KB_ID) -> list[dict]:
    registry = load_registry(kb_id)
    return [{"doc_id": doc_id, **meta} for doc_id, meta in registry["documents"].items()]


def reindex_all(
    kb_id: str = DEFAULT_KB_ID,
    chunk_size: int = CHUNK_SIZE,
    chunk_overlap: int = CHUNK_OVERLAP,
) -> dict:
    """Rebuild the vector index from the chunks already stored in the
    registry.
    """
    registry = load_registry(kb_id)
    all_chunks = chunks_as_documents(registry)
    rebuild_index(kb_id, all_chunks)
    return {"status": "started", "kb_id": kb_id, "chunk_count": len(all_chunks)}