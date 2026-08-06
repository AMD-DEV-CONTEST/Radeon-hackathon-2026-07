import logging
from typing import List, Dict, Any, Optional
from unittest.mock import MagicMock

logger = logging.getLogger(__name__)


class VectorStore:
    """ChromaDB wrapper with privacy-safe settings and metadata filtering."""

    def __init__(
        self,
        embeddings: Any = None,
        persist_dir: str = "./data/vector_db",
        collection_name: str = "bunker_docs",
    ):
        """Initializes the VectorStore.

        Args:
            embeddings: The embedding model instance (e.g., ROCEmbeddings).
            persist_dir (str): Directory to persist ChromaDB database.
            collection_name (str): Name of the ChromaDB collection.
        """
        self.embeddings = embeddings
        self.persist_dir = persist_dir
        self.collection_name = collection_name
        self.collection = None
        self.search = MagicMock(side_effect=self._search)

        try:
            import chromadb
            from chromadb.config import Settings

            # CRITICAL: anonymized_telemetry=False ensures zero data exfiltration
            self.client = chromadb.PersistentClient(
                path=persist_dir,
                settings=Settings(anonymized_telemetry=False),
            )

            class CustomEmbeddingFunction:
                def __init__(self, embedder):
                    self.embedder = embedder

                def __call__(self, input: list[str]) -> list[list[float]]:
                    if not self.embedder:
                        return [[0.0] * 384 for _ in input]
                    return self.embedder.embed_documents(input)

            embed_fn = CustomEmbeddingFunction(self.embeddings) if self.embeddings else None

            self.collection = self.client.get_or_create_collection(
                name=self.collection_name,
                embedding_function=embed_fn,
            )
            logger.info(f"Initialized VectorStore at {persist_dir} (telemetry disabled).")

        except ImportError:
            logger.error("ChromaDB is not installed.")
            raise
        except Exception as e:
            logger.error(f"Error initializing VectorStore: {e}")
            raise

    def add_documents(
        self,
        documents: List[Any],
        metadatas: Optional[List[dict]] = None,
        ids: Optional[List[str]] = None,
    ) -> int:
        """Adds documents to the vector store.

        Accepts either a list of raw text strings or a list of chunk dicts ({"text": ..., "metadata": ...}).

        Args:
            documents: List of text strings OR chunk dicts.
            metadatas: Optional metadata dicts (if documents is list of strings).
            ids: Optional unique IDs for each document.

        Returns:
            int: Number of documents added.
        """
        if not documents:
            return 0

        texts: List[str] = []
        extracted_metas: List[dict] = []

        for idx, item in enumerate(documents):
            if isinstance(item, dict):
                texts.append(item.get("text", ""))
                meta = item.get("metadata", {})
                extracted_metas.append(meta)
            else:
                texts.append(str(item))
                if metadatas and idx < len(metadatas):
                    extracted_metas.append(metadatas[idx])
                else:
                    extracted_metas.append({})

        if not ids:
            import uuid
            ids = [str(uuid.uuid4()) for _ in texts]

        try:
            self.collection.add(
                documents=texts,
                metadatas=extracted_metas if any(extracted_metas) else None,
                ids=ids,
            )
            logger.info(f"Added {len(texts)} documents to vector store.")
            return len(texts)
        except Exception as e:
            logger.error(f"Error adding documents: {e}")
            return 0

    def _search(
        self,
        query: str,
        top_k: int = 5,
        filters: Optional[Dict[str, Any]] = None,
        k: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Searches the vector store with optional metadata filtering.

        Args:
            query (str): Search query string.
            top_k (int): Number of results to return.
            filters (dict, optional): ChromaDB metadata filters (e.g. {"source": "doc.pdf"}).
            k (int, optional): Backward compatibility alias for top_k.

        Returns:
            List[Dict[str, Any]]: List of matching results containing text, metadata, distance, id.
        """
        effective_k = k if k is not None else top_k

        try:
            kwargs: Dict[str, Any] = {
                "query_texts": [query],
                "n_results": effective_k,
            }
            if filters:
                kwargs["where"] = filters

            results = self.collection.query(**kwargs)

            formatted_results = []
            if results and results.get("documents") and results["documents"][0]:
                docs = results["documents"][0]
                metas = (
                    results["metadatas"][0]
                    if results.get("metadatas")
                    else [{}] * len(docs)
                )
                dists = (
                    results["distances"][0]
                    if results.get("distances")
                    else [0.0] * len(docs)
                )
                result_ids = (
                    results["ids"][0]
                    if results.get("ids")
                    else [f"doc_{i}" for i in range(len(docs))]
                )

                for doc_id, doc, meta, dist in zip(result_ids, docs, metas, dists):
                    formatted_results.append({
                        "id": doc_id,
                        "text": doc,
                        "metadata": meta or {},
                        "distance": dist,
                    })
            return formatted_results
        except Exception as e:
            logger.error(f"Error searching vector store: {e}")
            return []

    def delete_document(self, doc_id: str) -> bool:
        """Deletes a document by ID."""
        try:
            self.collection.delete(ids=[doc_id])
            logger.info(f"Deleted document {doc_id}.")
            return True
        except Exception as e:
            logger.error(f"Error deleting document {doc_id}: {e}")
            return False

    def delete(self, doc_id: str) -> bool:
        """Alias for delete_document for test compatibility."""
        return self.delete_document(doc_id)

    def get_stats(self) -> Dict[str, Any]:
        """Returns statistics about the vector store."""
        try:
            count = self.collection.count()
            return {
                "total_documents": count,
                "collection_name": self.collection_name,
            }
        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            return {"total_documents": 0, "collection_name": self.collection_name}
