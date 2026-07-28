"""
Vector index builder for curated ROCm documentation corpus.

Chunks documents by logical section (not fixed token windows),
embeds them using sentence-transformers, and persists the index.
"""

import json
import os
import re
from pathlib import Path
from typing import Optional

# Try to import vector-store dependencies; fall back gracefully
try:
    from sentence_transformers import SentenceTransformer
    import faiss
    import numpy as np
    _FAISS_AVAILABLE = True
except ImportError:
    _FAISS_AVAILABLE = False

try:
    import chromadb
    _CHROMA_AVAILABLE = True
except ImportError:
    _CHROMA_AVAILABLE = False


DEFAULT_CORPUS_DIR = Path(__file__).parent.parent.parent / "corpus"
DEFAULT_INDEX_DIR = Path(__file__).parent.parent.parent / ".index"
DEFAULT_EMBEDDING_MODEL = "all-MiniLM-L6-v2"  # small, fast, good quality

# Section delimiters — chunk by logical sections, not fixed windows
_SECTION_PATTERNS = [
    r"^#{1,3}\s+",      # Markdown headers
    r"^={3,}",          # RST-style headers
    r"^-{3,}",          # RST-style underlines
    r"^\d+\.\s+[A-Z]",  # Numbered sections
]
_SECTION_RE = re.compile("|".join(_SECTION_PATTERNS), re.MULTILINE)


def build_index(
    corpus_dir: Optional[str] = None,
    index_dir: Optional[str] = None,
    embedding_model: str = DEFAULT_EMBEDDING_MODEL,
    backend: str = "faiss",  # "faiss" or "chroma"
    min_chunk_chars: int = 100,
    max_chunk_chars: int = 2000,
) -> dict:
    """
    Load all .md and .txt files from corpus_dir, chunk by logical section,
    embed, and persist the index.

    Returns:
        {
            "num_chunks": int,
            "index_dir": str,
            "backend": str,
            "error": str | None
        }
    """
    corpus_dir = Path(corpus_dir or DEFAULT_CORPUS_DIR)
    index_dir = Path(index_dir or DEFAULT_INDEX_DIR)
    index_dir.mkdir(parents=True, exist_ok=True)

    if not corpus_dir.exists():
        return _error_result(f"Corpus directory not found: {corpus_dir}")

    # 1. Load all documents
    chunks = _load_and_chunk(corpus_dir, min_chunk_chars, max_chunk_chars)
    if not chunks:
        return _error_result(f"No documents found in {corpus_dir}. Add .md or .txt files first.")

    # 2. Save chunk metadata (always, regardless of backend)
    metadata_path = index_dir / "chunks.json"
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(chunks, f, indent=2, ensure_ascii=False)

    # 3. Embed and store
    if backend == "faiss" and _FAISS_AVAILABLE:
        _build_faiss_index(chunks, index_dir, embedding_model)
    elif backend == "chroma" and _CHROMA_AVAILABLE:
        _build_chroma_index(chunks, index_dir, embedding_model)
    else:
        # Fallback: JSON-only index (TF-IDF-style retrieval at query time)
        backend = "json_tfidf"

    return {
        "num_chunks": len(chunks),
        "index_dir": str(index_dir),
        "backend": backend,
        "error": None,
    }


def _load_and_chunk(
    corpus_dir: Path,
    min_chars: int,
    max_chars: int,
) -> list[dict]:
    """
    Walk corpus_dir, read all .md and .txt files, and split into section chunks.
    Each chunk gets source metadata (file, section title).
    """
    chunks = []
    doc_files = list(corpus_dir.rglob("*.md")) + list(corpus_dir.rglob("*.txt"))

    for doc_path in sorted(doc_files):
        try:
            text = doc_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        doc_chunks = _split_by_section(text, str(doc_path.relative_to(corpus_dir)))
        for chunk in doc_chunks:
            # Filter out too-small or too-large chunks
            if min_chars <= len(chunk["text"]) <= max_chars:
                chunks.append(chunk)
            elif len(chunk["text"]) > max_chars:
                # Split large chunks by paragraph
                for sub in _split_by_paragraph(chunk["text"], max_chars):
                    if len(sub) >= min_chars:
                        chunks.append({
                            "source": chunk["source"],
                            "section": chunk["section"],
                            "text": sub,
                        })

    return chunks


def _split_by_section(text: str, source: str) -> list[dict]:
    """Split a document by section headers."""
    sections = []
    current_title = "Introduction"
    current_parts = []

    for line in text.splitlines(keepends=True):
        if _SECTION_RE.match(line.strip()):
            if current_parts:
                sections.append({
                    "source": source,
                    "section": current_title.strip(),
                    "text": "".join(current_parts).strip(),
                })
            current_title = line.strip().lstrip("#").strip()
            current_parts = []
        else:
            current_parts.append(line)

    if current_parts:
        sections.append({
            "source": source,
            "section": current_title.strip(),
            "text": "".join(current_parts).strip(),
        })

    return [s for s in sections if s["text"]]


def _split_by_paragraph(text: str, max_chars: int) -> list[str]:
    """Further split a large chunk by blank-line-separated paragraphs."""
    paragraphs = re.split(r"\n\s*\n", text)
    result = []
    current = ""
    for para in paragraphs:
        if len(current) + len(para) < max_chars:
            current += "\n\n" + para
        else:
            if current:
                result.append(current.strip())
            current = para
    if current:
        result.append(current.strip())
    return result


def _build_faiss_index(chunks: list[dict], index_dir: Path, model_name: str) -> None:
    """Embed chunks and build a FAISS flat index."""
    model = SentenceTransformer(model_name)
    texts = [c["text"] for c in chunks]
    embeddings = model.encode(texts, show_progress_bar=True, convert_to_numpy=True)

    dim = embeddings.shape[1]
    index = faiss.IndexFlatL2(dim)
    index.add(embeddings.astype(np.float32))

    faiss.write_index(index, str(index_dir / "faiss.index"))
    np.save(str(index_dir / "embeddings.npy"), embeddings)


def _build_chroma_index(chunks: list[dict], index_dir: Path, model_name: str) -> None:
    """Embed chunks and store in ChromaDB."""
    client = chromadb.PersistentClient(path=str(index_dir / "chroma"))
    collection = client.get_or_create_collection(name="rocm_docs")

    texts = [c["text"] for c in chunks]
    ids = [f"chunk_{i}" for i in range(len(chunks))]
    metadatas = [{"source": c["source"], "section": c["section"]} for c in chunks]

    collection.add(documents=texts, ids=ids, metadatas=metadatas)


def _error_result(msg: str) -> dict:
    return {"num_chunks": 0, "index_dir": "", "backend": "", "error": msg}
