"""RAG Pipeline"""

from __future__ import annotations

import os
import logging
from pathlib import Path

from .loader import DocumentLoader
from .splitter import TextSplitter, Chunk
from .vectorstore import VectorStore
from .api_embedder import APIEmbedder

logger = logging.getLogger(__name__)


class RAGPipeline:
    def __init__(self):
        self.vector_store = None
        self.documents = []
        self._initialized = False
        self._embedding_config = {}
        self._config = {}
        self._original_env = {}
        self._file_contents = {}

    def initialize(self, config: dict):
        """Initialize: load knowledge base, build index"""
        knowledge_config = config.get("knowledge", {})
        rag_config = config.get("rag", {})
        self._config = config
        
        self._embedding_config = config.get("rag", {}).get("embedding", {})
        
        knowledge_dir = knowledge_config.get("data_dir", "./data/knowledge_base")
        kb_path = Path(knowledge_dir)
        
        print(f"[RAG] 知识库路径: {kb_path.absolute()}")
        
        if not kb_path.exists():
            print(f"[RAG] 目录不存在: {kb_path}")
            return
        
        loader = DocumentLoader()
        raw_docs = loader.load_directory(str(kb_path))
        raw_docs = [d for d in raw_docs if getattr(d, 'metadata', {}).get('source', '') != 'file_meta.json']
        print(f"[RAG] 加载 {len(raw_docs)} 个原始文档")
        
        if not raw_docs:
            print("[RAG] 无原始文档，等待用户上传文件")
            return
        
        docs = self._normalize_docs(raw_docs)
        
        splitter = TextSplitter(
            chunk_size=rag_config.get("chunk_size", 512),
            chunk_overlap=rag_config.get("chunk_overlap", 128),
        )
        
        chunks: list[Chunk] = splitter.split(docs)
        print(f"[RAG] 分割为 {len(chunks)} 个 chunk")
        
        if not chunks:
            print("[RAG] 无有效 chunk")
            return
        
        embedder = self._create_embedder()
        texts = [c.content for c in chunks]
        
        chunk_dicts = [
            {
                "text": c.content,
                "source": c.metadata.get("source", "unknown"),
                "chunk_index": c.metadata.get("chunk_index", i),
            }
            for i, c in enumerate(chunks)
        ]
        
        embeddings = []
        dim = 384
        if embedder:
            try:
                embeddings = embedder.encode(texts)
                dim = len(embeddings[0]) if embeddings else 384
            except Exception:
                pass
        
        vs_cfg = rag_config.get("vectorstore", {})
        milvus_uri = os.environ.get("MILVUS_URI") or vs_cfg.get("milvus_uri", "")
        self.vector_store = VectorStore(
            dimension=dim,
            milvus_uri=milvus_uri,
            path=vs_cfg.get("path", ""),
        )
        
        if embeddings:
            self.vector_store.add(embeddings, chunk_dicts)
        
        self._initialized = True
        print(f"[RAG] 索引完成: {len(chunks)} chunks")

    def _create_embedder(self):
        cfg = self._embedding_config or {}

        api_url = cfg.get("api_url", "")
        if not api_url:
            return None

        api_key = cfg.get("api_key", "")
        model = cfg.get("model", "text-embedding-3-small")

        return APIEmbedder(
            api_url=api_url,
            api_key=api_key,
            model=model,
        )

    def _reload_from_disk(self):
        """Reload uploaded files into memory"""
        import json
        from pathlib import Path
        
        knowledge_config = self._config.get("knowledge", {}) if self._config else {}
        knowledge_dir = knowledge_config.get("data_dir", "./data/knowledge_base")
        kb_path = Path(knowledge_dir)
        meta_path = kb_path / "file_meta.json"
        
        if not meta_path.exists():
            return
        
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if not meta:
            return
        
        loader = DocumentLoader()
        for file_id, info in meta.items():
            name = info.get("name", "")
            file_path = kb_path / f"{file_id}_{name}"
            if file_path.exists():
                docs = loader.load_file(str(file_path))
                if docs:
                    full_text = "\n".join([d.content if hasattr(d, 'content') else str(d) for d in docs])
                    if full_text.strip() and len(full_text.strip()) >= 5:
                        self._file_contents[file_id] = full_text
                        self._initialized = True
                else:
                    logger.info(f"_reload: skipping {name} - no extractable text")

    def _normalize_docs(self, raw_docs):
        """Normalize to Document objects"""
        from .loader import Document
        
        docs = []
        for d in raw_docs:
            if isinstance(d, dict):
                docs.append(Document(
                    content=d.get("content", str(d)),
                    metadata={"source": d.get("source", "unknown")},
                ))
            elif hasattr(d, 'content'):
                docs.append(d)
            else:
                docs.append(Document(content=str(d), metadata={"source": "unknown"}))
        
        return docs

    def query(self, query_text: str, top_k: int = 5, file_ids: list = None) -> dict:
        """Query the knowledge base, optionally filter by file ID"""
        contexts = []
        sources = []
        
        if file_ids:
            for fid in file_ids:
                content = self._file_contents.get(fid, "")
                if not content:
                    logger.warning(f"query: file_id '{fid}' not found in _file_contents (available: {list(self._file_contents.keys())})")
                    continue
                if self._is_valid_content(content):
                    contexts.append(content)
                    sources.append({"file": fid})
                else:
                    logger.warning(f"query: file_id '{fid}' content failed validation (len={len(content)})")
        
        if not self._initialized:
            if contexts:
                logger.info(f"query: returning {len(contexts)} contexts (from file_contents)")
                return {"contexts": contexts, "sources": sources}
            return {"contexts": [], "sources": []}
        
        if self.vector_store:
            embedder = self._create_embedder()
            if embedder:
                try:
                    q_emb = embedder.encode([query_text])[0]
                    if file_ids:
                        for fid in file_ids:
                            results = self.vector_store.search(q_emb, top_k=top_k, source_filter=fid)
                            for r in results:
                                t = r.get("text", "")
                                if t and t not in contexts and self._is_valid_content(t):
                                    contexts.append(t)
                                    sources.append({"file": r.get("source", fid)})
                    else:
                        results = self.vector_store.search(q_emb, top_k=top_k)
                        for r in results:
                            t = r.get("text", "")
                            if t and self._is_valid_content(t):
                                contexts.append(t)
                                sources.append({"file": r.get("source", "unknown")})
                except Exception:
                    pass
        
        logger.info(f"query: returned {len(contexts)} contexts from {len(file_ids or [])} file_ids")
        return {"contexts": contexts, "sources": sources}
    
    def _is_valid_content(self, content: str) -> bool:
        if not content or len(content.strip()) < 5:
            return False
        replacement_chars = content.count('\ufffd')
        if replacement_chars > len(content) * 0.05:
            return False
        non_printable = sum(1 for ch in content if ord(ch) < 9 or (ord(ch) > 13 and ord(ch) < 32))
        if non_printable > len(content) * 0.2:
            return False
        return True

    def add_file(self, file_path: str, file_id: str) -> dict:
        """Incrementally index a single file. Returns {'ok': bool, 'reason': str}"""
        from .loader import DocumentLoader
        from .splitter import TextSplitter
        
        if not self._embedding_config and self._config:
            self._embedding_config = self._config.get("rag", {}).get("embedding", {})
        
        loader = DocumentLoader()
        docs = loader.load_file(file_path)
        
        if not docs:
            return {"ok": False, "reason": "no_extractable_text", "file_id": file_id}
        
        full_text = "\n".join([d.content if hasattr(d, 'content') else str(d) for d in docs])
        
        if not full_text.strip() or len(full_text.strip()) < 5:
            return {"ok": False, "reason": "insufficient_text", "file_id": file_id}
        
        self._file_contents[file_id] = full_text
        logger.info(f"add_file: stored {file_id} ({len(full_text)} chars)")
        
        embedder = self._create_embedder()
        if not embedder:
            self._initialized = True
            return {"ok": True, "file_id": file_id, "chars": len(full_text)}
        
        rag_config = self._config.get("rag", {}) if self._config else {}
        splitter = TextSplitter(
            chunk_size=rag_config.get("chunk_size", 512),
            chunk_overlap=rag_config.get("chunk_overlap", 128),
        )
        chunks = splitter.split(docs)
        if not chunks:
            self._initialized = True
            return {"ok": True, "file_id": file_id, "chars": len(full_text)}
        
        texts = [c.content for c in chunks]
        
        try:
            embeddings = embedder.encode(texts)
        except Exception:
            self._initialized = True
            return {"ok": True, "file_id": file_id, "chars": len(full_text)}
        
        chunk_dicts = [
            {"text": c.content, "source": file_id, "chunk_index": i}
            for i, c in enumerate(chunks)
        ]
        
        if not self.vector_store:
            dim = len(embeddings[0]) if embeddings else 384
            vs_cfg = rag_config.get("vectorstore", {})
            milvus_uri = os.environ.get("MILVUS_URI") or vs_cfg.get("milvus_uri", "")
            self.vector_store = VectorStore(
                dimension=dim,
                milvus_uri=milvus_uri,
                path=vs_cfg.get("path", ""),
            )
        
        self.vector_store.add(embeddings, chunk_dicts)
        self._initialized = True
        return {"ok": True, "file_id": file_id, "chars": len(full_text)}


# Global singleton
_pipeline = None

def get_rag_pipeline(config=None, original_env=None, force_reset=False):
    global _pipeline
    if _pipeline is not None and not force_reset:
        if config:
            _pipeline._config = config
        return _pipeline
    _pipeline = RAGPipeline()
    if config:
        _pipeline._config = config
    if original_env:
        _pipeline._original_env = original_env
    if config:
        _pipeline.initialize(config)
    _pipeline._reload_from_disk()
    return _pipeline