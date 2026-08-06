from __future__ import annotations

import json
from typing import Any

from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from langchain_core.tools import Tool

from cortex.core.article import Scope as CoreScope
from cortex.sdk.client import CortexClient
from cortex.sdk.exceptions import map_node_error


def _docs_to_json(docs: list[Document]) -> str:
    return json.dumps(
        [
            {"page_content": d.page_content, "metadata": d.metadata}
            for d in docs
        ]
    )


_SCOPE_MAP = {
    "PUBLIC": CoreScope.PUBLIC,
    "PRIVATE": CoreScope.PRIVATE,
    "public": CoreScope.PUBLIC,
    "private": CoreScope.PRIVATE,
}


class CortexRetriever(BaseRetriever):
    """LangChain retriever that queries a CortexNode's memory fabric.

    Maps each QueryResult to a LangChain Document with article_id / trust /
    org / type metadata.
    """

    node: Any
    top_k: int = 5
    min_trust: float = 0.3
    topics: set[str] | None = None
    scopes: set[str] | None = None

    def _get_relevant_documents(
        self,
        query: str,
        *,
        run_manager: CallbackManagerForRetrieverRun,
    ) -> list[Document]:
        try:
            results = self.node.query(
                query_text=query,
                topic_filter=self.topics,
                scope_filter=self.scopes,
                top_k=self.top_k,
                min_trust=self.min_trust,
                deadline_ms=5000,
            )
        except Exception as exc:
            raise map_node_error(exc) from exc

        docs: list[Document] = []
        for r in results:
            docs.append(
                Document(
                    page_content=r.article.content,
                    metadata={
                        "article_id": r.article_id,
                        "trust": r.trust_score,
                        "org": r.article.provenance.producer_org,
                        "type": r.article.type.value,
                    },
                )
            )
        return docs

    def as_tool(
        self,
        name: str = "cortex_search",
        description: str = (
            "Search the Cortex agent memory fabric for findings, insights, "
            "and precedents across trusted peers."
        ),
    ) -> Tool:
        retriever_self = self

        def _run(query: str, **kwargs) -> str:
            docs = retriever_self._get_relevant_documents(
                query, run_manager=None
            )
            return _docs_to_json(docs)

        return Tool(name=name, description=description, func=_run)


class CortexPublishTool(Tool):
    """LangChain Tool that lets an agent publish a FINDING to Cortex.

    _run(content, payload_json, scope) parses JSON payload, enforces the
    2000-char content cap (Design D5), and delegates to CortexClient.
    """

    name: str = "cortex_publish"
    description: str = (
        "Publish a security finding to the Cortex memory fabric. "
        "Args: content (<=2000 chars natural language), "
        "payload_json (JSON dict of structured fields), "
        "scope ('PUBLIC' or 'PRIVATE')."
    )

    def __init__(self, node):
        super().__init__(
            name="cortex_publish",
            description=(
                "Publish a security finding to the Cortex memory fabric. "
                "Args: content (<=2000 chars natural language), "
                "payload_json (JSON dict of structured fields), "
                "scope ('PUBLIC' or 'PRIVATE')."
            ),
            func=self._run,
        )
        object.__setattr__(self, "_client", CortexClient(node))
        object.__setattr__(self, "_node", node)

    def _run(self, content: str, payload_json: str, scope: str) -> str:
        if len(content) > 2000:
            raise ValueError("content must be <=2000 chars (Design D5)")
        payload = json.loads(payload_json)
        scope_obj = _SCOPE_MAP.get(scope, CoreScope.PRIVATE)
        return self._client.publish_finding(
            content=content, payload=payload, scope=scope_obj
        )
