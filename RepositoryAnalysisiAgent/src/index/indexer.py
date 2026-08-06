"""Full indexing pipeline: file traversal, parsing, embedding, storage.

Supports incremental indexing via SHA256 hash tracking.
Maintains a symbol table for find_references lookups.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..config import Config
from .parser import CodeParser, CodeChunk, Symbol
from .embeddings import EmbeddingModel
from .vector_store import VectorStore

logger = logging.getLogger(__name__)


@dataclass
class IndexStats:
    files_indexed: int = 0
    files_skipped: int = 0
    chunks_created: int = 0
    elapsed_seconds: float = 0.0
    errors: list[str] = field(default_factory=list)


class SymbolTable:
    """In-memory symbol table for find_references lookups.

    Maps symbol names to lists of (file_path, start_line) where they're defined.
    """

    def __init__(self) -> None:
        # name -> list of (file_path, start_line, end_line, kind)
        self._definitions: dict[str, list[tuple[str, int, int, str]]] = {}
        # name -> list of (file_path, line_number) where they're referenced
        self._references: dict[str, list[tuple[str, int]]] = {}

    def add_definition(self, name: str, file_path: str, start: int, end: int, kind: str) -> None:
        self._definitions.setdefault(name, []).append((file_path, start, end, kind))

    def add_reference(self, name: str, file_path: str, line: int) -> None:
        self._references.setdefault(name, []).append((file_path, line))

    def find_references(self, name: str) -> list[dict[str, Any]]:
        """Find all references to a symbol name (heuristic, not precise call graph)."""
        results: list[dict[str, Any]] = []
        for file_path, line in self._references.get(name, []):
            results.append({
                "file_path": file_path,
                "line": line,
                "type": "reference",
            })
        for file_path, start, end, kind in self._definitions.get(name, []):
            results.append({
                "file_path": file_path,
                "line": start,
                "end_line": end,
                "type": "definition",
                "kind": kind,
            })
        return results

    def all_symbol_names(self) -> list[str]:
        return sorted(self._definitions.keys())

    def clear(self) -> None:
        self._definitions.clear()
        self._references.clear()


class Indexer:
    """Coordinates the full indexing pipeline for a repository."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.parser = CodeParser()
        self.embedding_model = EmbeddingModel(config.embedding)
        self.vector_store = VectorStore(config.index.persist_dir)
        self.symbol_table = SymbolTable()
        self._hash_cache_path = Path(config.index.persist_dir) / "hash_cache.json"
        self._hash_cache: dict[str, str] = {}
        self._load_hash_cache()
        self._is_indexing = False
        self._last_stats: IndexStats | None = None

    def index_repository(
        self,
        repo_path: str | Path,
        force: bool = False,
    ) -> IndexStats:
        """Index a repository. Returns statistics."""
        repo_path = Path(repo_path).resolve()
        stats = IndexStats()
        import time
        t0 = time.time()

        self._is_indexing = True
        self.config.repo_root = repo_path

        if force:
            self.vector_store.clear()
            self.symbol_table.clear()
            self._hash_cache.clear()

        # Discover files
        files = self._discover_files(repo_path)
        logger.info("Discovered %d files to index in %s", len(files), repo_path)

        # Filter unchanged files (incremental)
        if not force:
            files_to_index = []
            for f in files:
                rel = str(f.relative_to(repo_path))
                current_hash = self._file_hash(f)
                if self._hash_cache.get(rel) != current_hash:
                    files_to_index.append(f)
                else:
                    stats.files_skipped += 1
            files = files_to_index
        else:
            # Clean up deleted files from store
            for f in files:
                rel = str(f.relative_to(repo_path))
                if rel in self._hash_cache:
                    self._hash_cache.pop(rel, None)

        if not files:
            logger.info("No files to index (all up to date)")
            stats.elapsed_seconds = time.time() - t0
            self._is_indexing = False
            self._last_stats = stats
            return stats

        # Parse + chunk all files
        all_chunks: list[CodeChunk] = []
        for f in files:
            try:
                rel = str(f.relative_to(repo_path))
                chunks = self.parser.parse_file(f)
                # Normalize file paths to relative
                for chunk in chunks:
                    chunk.file_path = rel
                all_chunks.extend(chunks)
                stats.files_indexed += 1

                # Build symbol table
                for sym in self.parser.get_symbols(f):
                    self.symbol_table.add_definition(
                        sym.name, rel, sym.start_line, sym.end_line, sym.kind
                    )

            except Exception as e:
                stats.errors.append(f"{f}: {e}")
                logger.error("Error parsing %s: %s", f, e)

        # Build reference index (heuristic: scan for symbol name occurrences)
        self._build_references(repo_path, files)

        # Embed and store
        if all_chunks:
            logger.info("Embedding %d chunks from %d files", len(all_chunks), stats.files_indexed)
            batch_size = self.config.embedding.batch_size
            for i in range(0, len(all_chunks), batch_size):
                batch = all_chunks[i:i + batch_size]
                try:
                    embeddings = self.embedding_model.embed([c.content for c in batch])
                    self.vector_store.add_chunks(batch, embeddings)
                    stats.chunks_created += len(batch)
                except Exception as e:
                    stats.errors.append(f"Embedding batch {i}: {e}")
                    logger.error("Embedding error: %s", e)

        # Update hash cache
        for f in files:
            rel = str(f.relative_to(repo_path))
            self._hash_cache[rel] = self._file_hash(f)
        self._save_hash_cache()

        stats.elapsed_seconds = time.time() - t0
        self._is_indexing = False
        self._last_stats = stats

        logger.info(
            "Indexing complete: %d files, %d chunks, %.1fs, %d errors",
            stats.files_indexed, stats.chunks_created,
            stats.elapsed_seconds, len(stats.errors),
        )
        return stats

    def search(
        self,
        query: str,
        top_k: int = 20,
    ) -> list[dict[str, Any]]:
        """Semantic search returning ranked results from the vector store."""
        embedding = self.embedding_model.embed_query(query)
        return self.vector_store.query(embedding, top_k=top_k)

    @property
    def is_indexing(self) -> bool:
        return self._is_indexing

    @property
    def last_stats(self) -> IndexStats | None:
        return self._last_stats

    @property
    def chunk_count(self) -> int:
        return self.vector_store.count()

    def _discover_files(self, repo_path: Path) -> list[Path]:
        """Walk the repository and return files to index."""
        exclude_dirs = set(self.config.index.exclude_dirs)
        extensions = set(self.config.index.supported_extensions)
        sensitive = self.config.index.sensitive_patterns

        files: list[Path] = []
        for path in repo_path.rglob("*"):
            if not path.is_file():
                continue

            # Check directory exclusions
            try:
                rel = path.relative_to(repo_path)
            except ValueError:
                continue
            if any(part in exclude_dirs for part in rel.parts):
                continue

            # Check extension
            if path.suffix not in extensions:
                continue

            # Check sensitive patterns
            if any(fnmatch.fnmatch(path.name, pat) for pat in sensitive):
                continue

            files.append(path)

        return sorted(files)

    def _file_hash(self, path: Path) -> str:
        """Compute SHA256 hash of file content."""
        try:
            content = path.read_bytes()
            return hashlib.sha256(content).hexdigest()
        except OSError:
            return ""

    def _build_references(self, repo_path: Path, files: list[Path]) -> None:
        """Build heuristic reference index by scanning for symbol names in source."""
        symbol_names = self.symbol_table.all_symbol_names()
        if not symbol_names:
            return

        for f in files:
            try:
                lines = f.read_text(encoding="utf-8", errors="replace").split("\n")
                rel = str(f.relative_to(repo_path))
                for line_num, line in enumerate(lines, 1):
                    for name in symbol_names:
                        if name in line:
                            self.symbol_table.add_reference(name, rel, line_num)
            except OSError:
                continue

    def _load_hash_cache(self) -> None:
        if self._hash_cache_path.exists():
            try:
                self._hash_cache = json.loads(self._hash_cache_path.read_text())
            except (json.JSONDecodeError, OSError):
                self._hash_cache = {}

    def _save_hash_cache(self) -> None:
        self._hash_cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._hash_cache_path.write_text(json.dumps(self._hash_cache, indent=2))
