from __future__ import annotations

from typing import Any

from app.services.rag import ChromaRAGService


class ResearchAgent:
    def __init__(self, rag: ChromaRAGService) -> None:
        self.rag = rag

    def run(self, query: str, document_ids: list[str] | None = None) -> dict[str, Any]:
        results = self.rag.query(query, document_ids=document_ids or [])
        citations = []
        summary_lines = []
        for item in results:
            metadata = item["metadata"]
            snippet = item["content"][:240]
            citations.append(
                {
                    "document_id": metadata.get("document_id", "unknown"),
                    "filename": metadata.get("filename", "unknown"),
                    "page": metadata.get("page"),
                    "snippet": snippet,
                }
            )
            summary_lines.append(
                f"- {metadata.get('filename', 'document')} page {metadata.get('page', '?')}: {snippet}"
            )
        return {
            "summary": "\n".join(summary_lines) if summary_lines else "No relevant local document evidence found.",
            "citations": citations,
        }
