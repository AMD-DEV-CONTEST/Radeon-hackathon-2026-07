from langchain_huggingface import HuggingFaceEmbeddings

from .config import EMBEDDING_MODEL_NAME

_embedder: HuggingFaceEmbeddings | None = None


def get_embedder() -> HuggingFaceEmbeddings:
    """Lazily construct and cache the embedding model.

    Lazy + cached because loading the model has real startup cost — you
    don't want every CLI invocation (ingest, query, list, delete) to pay
    that cost if it doesn't need embeddings (list/delete don't).
    """
    global _embedder
    if _embedder is None:
        _embedder = HuggingFaceEmbeddings(
            model_name=EMBEDDING_MODEL_NAME,
            encode_kwargs={"normalize_embeddings": True, "batch_size": 32},
        )
    return _embedder