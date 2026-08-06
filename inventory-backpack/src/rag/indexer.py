"""Document indexer - based on existing modules"""

from __future__ import annotations

import json
import pickle
from pathlib import Path

from .loader import DocumentLoader
from .splitter import TextSplitter
from .vectorstore import VectorStore
from .api_embedder import APIEmbedder


class DocumentIndexer:
    def __init__(self):
        self.vector_store: VectorStore | None = None
        self.doc_count = 0

    def load_or_build(
        self,
        source_dir: Path,
        vector_store_path: Path,
        chunk_size: int = 512,
        chunk_overlap: int = 128,
    ):
        """Load or build index"""
        # Check existing index
        index_file = vector_store_path / "index.faiss"

        if index_file.exists():
            print(f"[Indexer] 加载已有索引: {vector_store_path}")
            self.vector_store = VectorStore.load(str(vector_store_path))
            self.doc_count = self._load_meta(vector_store_path)
            return

        # Build new index
        print(f"[Indexer] 构建新索引...")
        vector_store_path.mkdir(parents=True, exist_ok=True)

        # Load documents
        loader = DocumentLoader()
        documents = loader.load_from_directory(source_dir)
        print(f"[Indexer] 加载 {len(documents)} 个文档")

        if not documents:
            self.doc_count = 0
            return

        # Split text
        splitter = TextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        chunks = []
        for doc in documents:
            doc_chunks = splitter.split(doc["content"])
            for chunk in doc_chunks:
                chunks.append({
                    "text": chunk,
                    "source": doc.get("source", "unknown"),
                    "metadata": doc.get("metadata", {}),
                })
        
        print(f"[Indexer] 分割为 {len(chunks)} 个 chunk")
        
        # Embed and store
        embedder = APIEmbedder()
        texts = [c["text"] for c in chunks]
        embeddings = embedder.embed(texts)
        
        self.vector_store = VectorStore(
            dimension=len(embeddings[0]) if embeddings else 384
        )
        self.vector_store.add(embeddings, chunks)
        self.vector_store.save(str(vector_store_path))
        
        # Save metadata
        self.doc_count = len(chunks)
        self._save_meta(vector_store_path, self.doc_count)
        
        print(f"[Indexer] 索引完成: {self.doc_count} chunks")

    def _load_meta(self, path: Path) -> int:
        meta_file = path / "meta.json"
        if meta_file.exists():
            with open(meta_file) as f:
                return json.load(f).get("count", 0)
        return 0

    def _save_meta(self, path: Path, count: int):
        with open(path / "meta.json", "w") as f:
            json.dump({"count": count}, f)


class Retriever:
    """Retriever"""
    
    def __init__(self, indexer: DocumentIndexer):
        self.indexer = indexer

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        """Search related documents"""
        if not self.indexer.vector_store:
            return []
        
        from .api_embedder import APIEmbedder
        embedder = APIEmbedder()
        
        query_embedding = embedder.embed([query])[0]
        results = self.indexer.vector_store.search(query_embedding, top_k)
        
        return [
            {
                "text": r["text"],
                "source": r.get("source", "unknown"),
                "score": r.get("score", 0),
            }
            for r in results
        ]