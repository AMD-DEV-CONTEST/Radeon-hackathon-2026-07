import os
import json
import hashlib
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


class BatchIngestor:
    """Batch document ingestion pipeline with incremental resume support."""

    def __init__(
        self,
        document_loader: Any,
        vector_store: Any,
        parent_store: Optional[Any] = None,
        manifest_path: str = "./data/ingestion_manifest.json",
    ):
        """Initializes the BatchIngestor.

        Args:
            document_loader: DocumentLoader instance.
            vector_store: VectorStore instance.
            parent_store: Optional ParentDocumentStore instance.
            manifest_path: Path to store ingestion manifest.
        """
        self.document_loader = document_loader
        self.vector_store = vector_store
        self.parent_store = parent_store
        self.manifest_path = manifest_path
        self._manifest: Dict[str, Dict[str, Any]] = self._load_manifest()

    def _load_manifest(self) -> Dict[str, Dict[str, Any]]:
        """Loads manifest file from disk."""
        if os.path.exists(self.manifest_path):
            try:
                with open(self.manifest_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading manifest from {self.manifest_path}: {e}")
                return {}
        return {}

    def _save_manifest(self) -> None:
        """Saves manifest file to disk."""
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self.manifest_path)), exist_ok=True)
            with open(self.manifest_path, "w", encoding="utf-8") as f:
                json.dump(self._manifest, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving manifest to {self.manifest_path}: {e}")

    def _compute_file_hash(self, file_path: str) -> str:
        """Computes SHA256 hash of a file."""
        hasher = hashlib.sha256()
        try:
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    hasher.update(chunk)
            return hasher.hexdigest()
        except Exception:
            return ""

    def ingest_file(self, file_path: str, force: bool = False) -> Dict[str, Any]:
        """Ingests a single file if it is new or modified.

        Args:
            file_path: Path to the file.
            force: If True, re-indexes even if unchanged.

        Returns:
            Dict summary of operation ("status": "indexed"|"skipped"|"failed", "chunks_added": int).
        """
        path = Path(file_path)
        if not path.exists() or not path.is_file():
            return {"status": "failed", "reason": "file_not_found", "chunks_added": 0}

        abs_path = str(path.resolve())
        stat = path.stat()
        file_size = stat.st_size
        mtime = stat.st_mtime
        file_hash = self._compute_file_hash(abs_path)

        entry = self._manifest.get(abs_path)

        # Check if unchanged
        if (
            not force
            and entry
            and entry.get("status") == "indexed"
            and entry.get("hash") == file_hash
            and entry.get("size") == file_size
        ):
            logger.info(f"Skipping unchanged file: {file_path}")
            return {"status": "skipped", "file": file_path, "chunks_added": 0}

        try:
            if self.parent_store and path.suffix.lower() in {".txt", ".md", ".pdf", ".docx"}:
                with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
                    raw_text = f.read()
                chunks = self.parent_store.process_and_store_parent_child(
                    text=raw_text,
                    source=abs_path,
                    document_loader=self.document_loader,
                )
            else:
                chunks = self.document_loader.load_file(abs_path)

            if chunks:
                count = self.vector_store.add_documents(chunks)
            else:
                count = 0

            self._manifest[abs_path] = {
                "file_path": abs_path,
                "size": file_size,
                "mtime": mtime,
                "hash": file_hash,
                "status": "indexed",
                "chunks_count": count,
                "error": None,
            }
            self._save_manifest()
            logger.info(f"Successfully ingested {file_path} ({count} chunks).")
            return {"status": "indexed", "file": file_path, "chunks_added": count}

        except Exception as e:
            logger.error(f"Error ingesting file {file_path}: {e}")
            self._manifest[abs_path] = {
                "file_path": abs_path,
                "size": file_size,
                "mtime": mtime,
                "hash": file_hash,
                "status": "failed",
                "chunks_count": 0,
                "error": str(e),
            }
            self._save_manifest()
            return {"status": "failed", "file": file_path, "error": str(e), "chunks_added": 0}

    def ingest_directory(self, dir_path: str, recursive: bool = True) -> Dict[str, Any]:
        """Ingests all supported files in a directory.

        Args:
            dir_path: Directory path.
            recursive: Whether to scan subdirectories.

        Returns:
            Dict summary: {"indexed": int, "skipped": int, "failed": int, "total_chunks": int}.
        """
        path = Path(dir_path)
        if not path.is_dir():
            logger.error(f"Directory not found: {dir_path}")
            return {"indexed": 0, "skipped": 0, "failed": 0, "total_chunks": 0}

        pattern = "**/*" if recursive else "*"
        supported = self.document_loader.SUPPORTED_EXTENSIONS

        stats = {"indexed": 0, "skipped": 0, "failed": 0, "total_chunks": 0}

        for file_path in path.glob(pattern):
            if file_path.is_file() and file_path.suffix.lower() in supported:
                res = self.ingest_file(str(file_path))
                status = res.get("status", "failed")
                stats[status] = stats.get(status, 0) + 1
                stats["total_chunks"] += res.get("chunks_added", 0)

        return stats
