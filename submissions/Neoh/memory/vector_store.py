import logging
import os
import pickle
from typing import List, Dict, Any, Optional
import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)


class VectorStore:
    def __init__(
        self,
        index_path: str = "./data/faiss_index",
        embedding_model: str = "all-MiniLM-L6-v2",
        dimension: int = 384,
    ):
        self.index_path = index_path
        self.embedding_model = embedding_model
        self.dimension = dimension
        self.index: Optional[faiss.Index] = None
        self.documents: List[Dict[str, Any]] = []
        self.model: Optional[SentenceTransformer] = None
        
        os.makedirs(index_path, exist_ok=True)
        self._init_model()
        self._load_or_create_index()

    def _init_model(self):
        try:
            logger.info(f"Loading embedding model: {self.embedding_model}")
            self.model = SentenceTransformer(self.embedding_model)
            logger.info("Embedding model loaded successfully")
        except Exception as e:
            logger.error(f"Failed to load embedding model: {str(e)}")
            raise

    def _load_or_create_index(self):
        index_file = os.path.join(self.index_path, "index.faiss")
        docs_file = os.path.join(self.index_path, "documents.pkl")

        if os.path.exists(index_file) and os.path.exists(docs_file):
            try:
                logger.info(f"Loading existing index from {index_file}")
                self.index = faiss.read_index(index_file)
                
                with open(docs_file, "rb") as f:
                    self.documents = pickle.load(f)
                
                logger.info(f"Loaded {len(self.documents)} documents")
            except Exception as e:
                logger.error(f"Failed to load index: {str(e)}")
                self._create_new_index()
        else:
            self._create_new_index()

    def _create_new_index(self):
        logger.info("Creating new FAISS index")
        self.index = faiss.IndexFlatL2(self.dimension)
        self.documents = []

    def _embed_texts(self, texts: List[str]) -> np.ndarray:
        if not self.model:
            raise RuntimeError("Embedding model not initialized")
        
        embeddings = self.model.encode(texts, show_progress_bar=False)
        return embeddings.astype(np.float32)

    def add_documents(self, documents: List[Dict[str, Any]]):
        if not self.index:
            raise RuntimeError("FAISS index not initialized")

        texts = [doc["content"] for doc in documents]
        embeddings = self._embed_texts(texts)
        
        self.index.add(embeddings)
        self.documents.extend(documents)
        
        logger.info(f"Added {len(documents)} documents to index")
        self._save_index()

    def search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        if not self.index or not self.model:
            raise RuntimeError("Index or model not initialized")

        if len(self.documents) == 0:
            return []

        query_embedding = self._embed_texts([query])[0:1]
        distances, indices = self.index.search(query_embedding, top_k)

        results = []
        for i in range(len(indices[0])):
            idx = indices[0][i]
            if idx >= 0 and idx < len(self.documents):
                results.append({
                    "content": self.documents[idx]["content"],
                    "metadata": self.documents[idx].get("metadata", {}),
                    "distance": float(distances[0][i]),
                })

        return results

    def _save_index(self):
        index_file = os.path.join(self.index_path, "index.faiss")
        docs_file = os.path.join(self.index_path, "documents.pkl")

        try:
            faiss.write_index(self.index, index_file)
            
            with open(docs_file, "wb") as f:
                pickle.dump(self.documents, f)
            
            logger.info(f"Index saved to {index_file}")
        except Exception as e:
            logger.error(f"Failed to save index: {str(e)}")
            raise

    def get_document_count(self) -> int:
        return len(self.documents)

    def clear(self):
        self._create_new_index()
        self._save_index()
        logger.info("Index cleared")