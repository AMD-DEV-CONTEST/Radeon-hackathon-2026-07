import os
import json
import uuid
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


class ParentDocumentStore:
    """Simple persistent local store for parent documents/contexts."""

    def __init__(
        self,
        storage_path: Optional[str] = None,
        store_path: Optional[str] = None,
    ):
        """Initializes the ParentDocumentStore.

        Args:
            storage_path: File path to save parent documents JSON.
            store_path: Backward-compatible alias for storage_path.
        """
        resolved_path = storage_path or store_path or "./data/vector_db/parent_store.json"
        self.store_path = resolved_path
        self.storage_path = resolved_path
        self._parents: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        """Loads parent documents from disk if file exists."""
        if os.path.exists(self.store_path):
            try:
                with open(self.store_path, "r", encoding="utf-8") as f:
                    self._parents = json.load(f)
            except Exception as e:
                logger.error(f"Error loading parent store from {self.store_path}: {e}")
                self._parents = {}
        else:
            self._parents = {}

    def save(self) -> None:
        """Persists parent documents to disk."""
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self.store_path)), exist_ok=True)
            with open(self.store_path, "w", encoding="utf-8") as f:
                json.dump(self._parents, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving parent store to {self.store_path}: {e}")

    def add_parent(self, parent_id: str, text: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        """Adds a single parent document entry.

        Args:
            parent_id: Unique identifier for the parent text.
            text: Large parent text/context.
            metadata: Metadata associated with parent.

        Returns:
            The parent_id.
        """
        self._parents[parent_id] = {
            "parent_id": parent_id,
            "text": text,
            "metadata": metadata or {},
        }
        self.save()
        return parent_id

    def get_parent(self, parent_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves a parent document by ID.

        Args:
            parent_id: Unique identifier.

        Returns:
            Dict containing parent text and metadata, or None if not found.
        """
        return self._parents.get(parent_id)

    def process_and_store_parent_child(
        self,
        text: str,
        source: str,
        document_loader: Any,
        parent_chunk_size: int = 1536,
        child_chunk_size: int = 384,
    ) -> List[Dict[str, Any]]:
        """Processes document text into parent and child chunks.

        Creates large parent chunks and smaller child chunks linking to parent_id.

        Args:
            text: Full raw text of document or section.
            source: Source identifier/file path.
            document_loader: Instance of DocumentLoader.
            parent_chunk_size: Size for parent chunks.
            child_chunk_size: Size for child chunks.

        Returns:
            List of child chunk dicts ready for insertion into VectorStore.
        """
        if not text or not text.strip():
            return []

        # Split into parent chunks
        parent_splitter = type(document_loader.splitter)(
            chunk_size=parent_chunk_size, chunk_overlap=100
        )
        child_splitter = type(document_loader.splitter)(
            chunk_size=child_chunk_size, chunk_overlap=document_loader.chunk_overlap
        )

        parent_texts = parent_splitter.split_text(text)
        filename = Path(source).name if source else "unknown"

        all_child_chunks: List[Dict[str, Any]] = []

        for p_idx, p_text in enumerate(parent_texts):
            p_id = f"{uuid.uuid4().hex[:12]}_p{p_idx}"
            p_meta = {
                "source": source,
                "filename": filename,
                "parent_index": p_idx,
            }
            self.add_parent(p_id, p_text, p_meta)

            child_texts = child_splitter.split_text(p_text)
            for c_idx, c_text in enumerate(child_texts):
                all_child_chunks.append({
                    "text": c_text,
                    "metadata": {
                        "source": source,
                        "filename": filename,
                        "parent_id": p_id,
                        "child_index": c_idx,
                    }
                })

        return all_child_chunks

    def enrich_results_with_parent(self, search_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Enriches search results (child hits) with parent text/context if parent_id exists.

        Args:
            search_results: List of search result dicts.

        Returns:
            Search results with 'parent_text' and 'parent_context' attached when available.
        """
        enriched = []
        for result in search_results:
            res_copy = dict(result)
            meta = res_copy.get("metadata", {})
            parent_id = meta.get("parent_id")

            if parent_id:
                parent_doc = self.get_parent(parent_id)
                if parent_doc:
                    res_copy["parent_text"] = parent_doc["text"]
                    res_copy["parent_context"] = parent_doc["text"]
            enriched.append(res_copy)
        return enriched
