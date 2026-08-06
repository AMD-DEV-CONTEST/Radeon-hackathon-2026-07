import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from langchain.schema import Document

from .config import kb_dir

REGISTRY_FILENAME = "registry.json"


def _registry_path(kb_id: str) -> Path:
    return kb_dir(kb_id) / REGISTRY_FILENAME


def _empty_registry() -> dict:
    return {"documents": {}, "chunks": []}


def load_registry(kb_id: str) -> dict:
    path = _registry_path(kb_id)
    if not path.exists():
        return _empty_registry()
    return json.loads(path.read_text(encoding="utf-8"))


def save_registry(kb_id: str, registry: dict) -> None:
    _registry_path(kb_id).write_text(json.dumps(registry, indent=2), encoding="utf-8")


def file_hash(path: Path) -> str:
    """SHA-256 of file contents — used for duplicate-upload detection,
    per the spec's 'duplicate file hash check, skip re-indexing' edge case.
    """
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def find_duplicate(registry: dict, file_hash_value: str) -> str | None:
    for doc_id, meta in registry["documents"].items():
        if meta.get("file_hash") == file_hash_value:
            return doc_id
    return None


def register_document(
    registry: dict, filename: str, file_hash_value: str, chunks: list[Document]
) -> str:
    """Add a new document + its chunks to the registry, tagging every
    chunk with the new doc_id so it can be found and removed later.
    """
    doc_id = str(uuid.uuid4())
    for chunk in chunks:
        chunk.metadata["doc_id"] = doc_id

    registry["documents"][doc_id] = {
        "filename": filename,
        "chunks": len(chunks),
        "file_hash": file_hash_value,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
    }
    registry["chunks"].extend(
        {"text": c.page_content, "metadata": c.metadata} for c in chunks
    )
    return doc_id


def remove_document(registry: dict, doc_id: str) -> bool:
    if doc_id not in registry["documents"]:
        return False
    del registry["documents"][doc_id]
    registry["chunks"] = [
        c for c in registry["chunks"] if c["metadata"].get("doc_id") != doc_id
    ]
    return True


def chunks_as_documents(registry: dict) -> list[Document]:
    """Rehydrate the registry's plain-dict chunks back into LangChain
    Documents — needed to rebuild BM25/FAISS indexes after a delete.
    """
    return [Document(page_content=c["text"], metadata=c["metadata"]) for c in registry["chunks"]]