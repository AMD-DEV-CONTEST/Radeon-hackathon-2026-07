"""
ChromaDB vector store management.
"""
import logging
from langchain_community.vectorstores import Chroma
from app.embeddings import get_embedding_function
from config import CHROMA_DIR, COLLECTION_NAME

logger = logging.getLogger(__name__)

_vectorstore = None


def get_vectorstore() -> Chroma:
    """Lazily instantiate and cache the persisted Chroma vector store."""
    global _vectorstore
    
    if _vectorstore is None:
        logger.info(f"Initializing Chroma vector store at '{CHROMA_DIR}'...")
        _vectorstore = Chroma(
            collection_name=COLLECTION_NAME,
            embedding_function=get_embedding_function(),
            persist_directory=CHROMA_DIR,
        )
    
    return _vectorstore