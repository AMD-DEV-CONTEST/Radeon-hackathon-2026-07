from __future__ import annotations

from uuid import uuid4

from cortex.core.article import ArticleType, MemoryArticle, Scope
from cortex.node.node import CortexNode
from cortex.node.query import QueryResult
from cortex.sdk.exceptions import map_node_error
from cortex.sdk.provenance import ProvenanceHelpers


class CortexClient:
    """Synchronous thin façade over CortexNode for agent code.

    Builds MemoryArticle + Provenance, forwards to node.publish / query / derive.
    Never re-implements node logic.
    """

    def __init__(self, node: CortexNode):
        self._node = node

    @property
    def node(self) -> CortexNode:
        return self._node

    def _build_provenance(self):
        return ProvenanceHelpers._build_provenance(self._node)

    def _publish_typed(
        self,
        *,
        content: str,
        payload: dict,
        scope: Scope,
        type: ArticleType,
        cites: list[str] | None = None,
    ) -> str:
        article = MemoryArticle(
            id=str(uuid4()),
            content=content,
            payload=payload,
            scope=scope,
            type=type,
            provenance=self._build_provenance(),
            agent_signature=b"",
            cites=list(cites) if cites else [],
        )
        try:
            return self._node.publish(article)
        except Exception as exc:
            raise map_node_error(exc) from exc

    def publish_finding(
        self,
        content: str,
        payload: dict,
        scope: Scope = Scope.PRIVATE,
        type: ArticleType = ArticleType.FINDING,
    ) -> str:
        return self._publish_typed(
            content=content, payload=payload, scope=scope, type=type
        )

    def publish_insight(
        self,
        content: str,
        payload: dict,
        scope: Scope = Scope.PRIVATE,
        cites: list[str] | None = None,
    ) -> str:
        return self._publish_typed(
            content=content, payload=payload, scope=scope,
            type=ArticleType.INSIGHT, cites=cites,
        )

    def publish_warning(self, content, payload, scope=Scope.PRIVATE) -> str:
        return self._publish_typed(
            content=content, payload=payload, scope=scope, type=ArticleType.WARNING
        )

    def publish_procedure(self, content, payload, scope=Scope.PRIVATE) -> str:
        return self._publish_typed(
            content=content, payload=payload, scope=scope, type=ArticleType.PROCEDURE
        )

    def publish_precedent(self, content, payload, scope=Scope.PRIVATE) -> str:
        return self._publish_typed(
            content=content, payload=payload, scope=scope, type=ArticleType.PRECEDENT
        )

    def search(
        self,
        query_text: str,
        topics: set[str] | None = None,
        scopes: set[str] | None = None,
        top_k: int = 5,
        min_trust: float = 0.3,
        deadline_ms: int = 5000,
    ) -> list[QueryResult]:
        try:
            return self._node.query(
                query_text=query_text,
                topic_filter=list(topics) if topics else None,
                scope_filter=list(scopes) if scopes else None,
                top_k=top_k,
                min_trust=min_trust,
                deadline_ms=deadline_ms,
            )
        except Exception as exc:
            raise map_node_error(exc) from exc

    def compose_insight(
        self,
        content: str,
        payload: dict,
        scope: Scope,
        sources: list[str] | None = None,
    ) -> str:
        article = MemoryArticle(
            id=str(uuid4()),
            content=content,
            payload=payload,
            scope=scope,
            type=ArticleType.INSIGHT,
            provenance=self._build_provenance(),
            agent_signature=b"",
            cites=list(sources) if sources else [],
        )
        try:
            return self._node.derive(article, list(sources) if sources else [])
        except Exception as exc:
            raise map_node_error(exc) from exc
