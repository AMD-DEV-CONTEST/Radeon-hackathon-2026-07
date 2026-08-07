import logging
import re
from typing import List, Dict, Any, Optional
from .vector_store import VectorStore
from .document_parser import DocumentParser

logger = logging.getLogger(__name__)

# 型号 / 器件编号样式的 token：字母数字混排且含数字，如 LMT75、W25Q128JV、CW32L012、TMP117
_PART_TOKEN = re.compile(r"\b(?=[A-Za-z0-9\-]*\d)(?=[A-Za-z0-9\-]*[A-Za-z])[A-Za-z0-9\-]{4,}\b")


class MemoryManager:
    def __init__(
        self,
        index_path: str = "./data/faiss_index",
        embedding_model: str = "all-MiniLM-L6-v2",
        chunk_size: int = 512,
        chunk_overlap: int = 50,
        top_k: int = 5,
    ):
        self.vector_store = VectorStore(
            index_path=index_path,
            embedding_model=embedding_model,
        )
        self.document_parser = DocumentParser(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        self.top_k = top_k
        self.short_term_memory: List[Dict[str, str]] = []

    def add_document(self, file_path: str, metadata_extra: Optional[Dict[str, Any]] = None) -> int:
        logger.info(f"Processing document: {file_path}")
        documents = self.document_parser.process_file(file_path, metadata_extra=metadata_extra)

        if documents:
            self.vector_store.add_documents(documents)
            logger.info(f"Added {len(documents)} chunks from {file_path}")
            return len(documents)
        return 0

    def add_documents(
        self, file_paths: List[str], metadata_extra: Optional[Dict[str, Any]] = None
    ) -> int:
        total_added = 0
        for file_path in file_paths:
            added = self.add_document(file_path, metadata_extra=metadata_extra)
            total_added += added
        return total_added

    def search(self, query: str, top_k: Optional[int] = None) -> List[Dict[str, Any]]:
        """检索：向量召回 + 型号词混合重排。

        纯向量检索对器件型号这类罕见 token 不敏感（问 LMT75 的供电电压，会被别的
        芯片的电气参数表挤掉）。因此先多召回候选，再按型号词是否出现在正文 / 文件名
        重排，保证问哪颗芯片就答哪颗芯片。
        """
        k = top_k if top_k is not None else self.top_k
        parts = {t.lower() for t in _PART_TOKEN.findall(query)}
        # 有型号词时扩大召回池，给重排留出空间
        pool = k * 6 if parts else k
        results = self.vector_store.search(query, top_k=pool)

        if parts:
            def rerank_score(result: Dict[str, Any]) -> float:
                text = result["content"].lower()
                source = str((result.get("metadata") or {}).get("source", "")).lower()
                score = 0.0
                for part in parts:
                    if part in source:
                        score += 2.0
                    if part in text:
                        score += 1.0
                return score

            results = sorted(results, key=rerank_score, reverse=True)

        return [
            {"content": r["content"], "metadata": r["metadata"]}
            for r in results[:k]
        ]

    def get_context(self, query: str, top_k: Optional[int] = None) -> str:
        results = self.search(query, top_k=top_k)
        
        context_parts = []
        for i, result in enumerate(results):
            context_parts.append(f"[参考文档 {i+1}]\n{result['content']}\n")
        
        return "\n".join(context_parts)

    def add_short_term_memory(self, message: Dict[str, str]):
        self.short_term_memory.append(message)
        
        if len(self.short_term_memory) > 20:
            self.short_term_memory = self.short_term_memory[-20:]

    def get_short_term_memory(self) -> List[Dict[str, str]]:
        return self.short_term_memory.copy()

    def clear_short_term_memory(self):
        self.short_term_memory = []

    def get_document_count(self) -> int:
        return self.vector_store.get_document_count()

    def clear_long_term_memory(self):
        self.vector_store.clear()

    def reset(self):
        self.clear_short_term_memory()
        self.clear_long_term_memory()