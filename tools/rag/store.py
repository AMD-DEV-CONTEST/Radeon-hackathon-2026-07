import shutil
from pathlib import Path

from langchain.schema import Document
from langchain_community.vectorstores import FAISS

from .config import kb_dir
from .embeddings import get_embedder

INDEX_DIRNAME = "faiss_index"


def _index_path(kb_id: str) -> Path:
    return kb_dir(kb_id) / INDEX_DIRNAME


def add_chunks(kb_id: str, chunks: list[Document]) -> FAISS:
    """Incrementally add new chunks to an existing index, or create one
    if this is the first ingest for this kb_id. Used on every `ingest`
    call — cheap, since it only embeds the *new* chunks.
    """
    embedder = get_embedder()
    path = _index_path(kb_id)

    if path.exists():
        index = FAISS.load_local(str(path), embedder, allow_dangerous_deserialization=True)
        index.add_documents(chunks)
    else:
        index = FAISS.from_documents(chunks, embedder)

    index.save_local(str(path))
    return index


def rebuild_index(kb_id: str, chunks: list[Document]) -> FAISS | None:
    """Rebuild the index from scratch given the *complete* current chunk
    list for this kb_id.
    """
    path = _index_path(kb_id)
    if not chunks:
        if path.exists():
            shutil.rmtree(path)
        return None

    embedder = get_embedder()
    index = FAISS.from_documents(chunks, embedder)
    index.save_local(str(path))
    return index


def load_index(kb_id: str) -> FAISS | None:
    path = _index_path(kb_id)
    if not path.exists():
        return None
    embedder = get_embedder()
    return FAISS.load_local(str(path), embedder, allow_dangerous_deserialization=True)