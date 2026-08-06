import os
from pathlib import Path

# All knowledge-base data lives under this root. Override with an env var
# so Docker/production can point it at a mounted volume.
DATA_ROOT = Path(os.environ.get("EDUMANIM_DATA_ROOT", "./data"))
KB_ROOT = DATA_ROOT / "kb_store"
DEFAULT_KB_ID = "default"

# Local, CPU-friendly models. Swap via env var if you want to try a bigger one.
EMBEDDING_MODEL_NAME = os.environ.get(
    "EDUMANIM_EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
)
RERANKER_MODEL_NAME = os.environ.get(
    "EDUMANIM_RERANK_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2"
)

# Chunking defaults (token-based, matches the embedding model's tokenizer)
CHUNK_SIZE = 512
CHUNK_OVERLAP = 50

# Retrieval defaults
DEFAULT_TOP_K = 5
FUSION_K_CONSTANT = 60  # reciprocal rank fusion constant


def kb_dir(kb_id: str) -> Path:
    """Return (and create if needed) the on-disk folder for a given kb_id."""
    d = KB_ROOT / kb_id
    d.mkdir(parents=True, exist_ok=True)
    return d