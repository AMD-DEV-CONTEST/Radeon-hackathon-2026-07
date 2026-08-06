"""
Embedding model setup with ROCm-aware device selection.
"""
import logging
import torch
from langchain_community.embeddings import HuggingFaceEmbeddings
from config import EMBEDDING_MODEL_NAME

logger = logging.getLogger(__name__)

_embedding_function = None


def get_torch_device() -> str:
    """
    Determine the best available device for embeddings.
    
    ROCm note: AMD GPUs are exposed through torch.cuda API on ROCm builds.
    """
    if torch.cuda.is_available():
        try:
            device_name = torch.cuda.get_device_name(0)
        except Exception:
            device_name = "AMD GPU (ROCm)"
        logger.info(f"GPU detected via ROCm/HIP: {device_name}. Using GPU for embeddings.")
        return "cuda"
    
    logger.warning("No ROCm-visible GPU detected. Falling back to CPU.")
    return "cpu"


DEVICE = get_torch_device()


def get_embedding_function() -> HuggingFaceEmbeddings:
    """Lazily instantiate and cache the embedding model."""
    global _embedding_function
    
    if _embedding_function is None:
        logger.info(f"Loading embedding model '{EMBEDDING_MODEL_NAME}' on device '{DEVICE}'...")
        _embedding_function = HuggingFaceEmbeddings(
            model_name=f"sentence-transformers/{EMBEDDING_MODEL_NAME}",
            model_kwargs={"device": DEVICE},
            encode_kwargs={"normalize_embeddings": True},
        )
        logger.info("Embedding model loaded.")
    
    return _embedding_function