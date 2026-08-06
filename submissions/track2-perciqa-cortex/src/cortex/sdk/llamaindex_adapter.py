from __future__ import annotations

from typing import Any

from llama_index.core.readers.base import BaseReader
from llama_index.core.schema import Document as LIDocument

from cortex.sdk.exceptions import map_node_error
from cortex.sdk.langchain_adapter import CortexRetriever


class CortexReader(BaseReader):
    """LlamaIndex BaseReader that pulls QueryResults from a CortexNode."""

    def __init__(
        self,
        node: Any = None,
        top_k: int = 5,
        min_trust: float = 0.3,
        topics: set[str] | None = None,
        scopes: set[str] | None = None,
        retriever: CortexRetriever | None = None,
    ):
        self.node = node
        self.top_k = top_k
        self.min_trust = min_trust
        self.topics = topics
        self.scopes = scopes
        self._retriever = retriever

    @classmethod
    def from_retriever(cls, retriever: CortexRetriever) -> CortexReader:
        return cls(
            node=retriever.node,
            top_k=retriever.top_k,
            min_trust=retriever.min_trust,
            topics=retriever.topics,
            scopes=retriever.scopes,
            retriever=retriever,
        )

    def load_data(
        self,
        query: str | None = None,
        **kwargs: Any,
    ) -> list[LIDocument]:
        if self._retriever is not None:
            try:
                docs = self._retriever._get_relevant_documents(
                    query or "", run_manager=None
                )
            except Exception as exc:
                raise map_node_error(exc) from exc
            return [
                LIDocument(text=d.page_content, metadata=dict(d.metadata))
                for d in docs
            ]
        try:
            results = self.node.query(
                query_text=query or "",
                topic_filter=list(self.topics) if self.topics else None,
                scope_filter=list(self.scopes) if self.scopes else None,
                top_k=self.top_k,
                min_trust=self.min_trust,
                deadline_ms=5000,
            )
        except Exception as exc:
            raise map_node_error(exc) from exc
        out = []
        for r in results:
            out.append(
                LIDocument(
                    text=r.article.content,
                    metadata={
                        "article_id": r.article_id,
                        "trust": r.trust_score,
                        "org": r.article.provenance.producer_org,
                        "type": r.article.type.value,
                    },
                )
            )
        return out
