from __future__ import annotations

from typing import Any

from ..knowledge_service import (
    KnowledgeRetrievalUnavailable,
    KnowledgeService,
)
from ..llm import ToolFailure, ToolSuccess
from ..llm.tooling import AgentTool, ToolExecutionContext
from .tool_inputs import KnowledgeLookupInput

KNOWLEDGE_LOOKUP_TOOL_NAME = "knowledge.lookup"
_RESULT_LIMIT = 5
_MAX_SOURCE_CHARS = 240
_MAX_EXCERPT_CHARS = 1600


def knowledge_lookup_tool(service: KnowledgeService) -> AgentTool[KnowledgeLookupInput]:
    def lookup(
        input_data: KnowledgeLookupInput,
        _context: ToolExecutionContext,
    ) -> ToolSuccess | ToolFailure:
        try:
            result = service.retrieve(
                input_data.query,
                mode=input_data.mode,
                top_k=_RESULT_LIMIT,
            )
        except KnowledgeRetrievalUnavailable as exc:
            return ToolFailure(
                code=exc.error_code or "knowledge_retrieval_mode_unavailable",
                message=str(exc),
                details=dict(exc.error_details),
                repair_hints=tuple(exc.repair_hints),
                retryable=bool(exc.retryable),
            )
        except Exception:
            return ToolFailure(
                code="knowledge_lookup_failed",
                message="Knowledge lookup could not be completed.",
            )

        return ToolSuccess(
            value={
                "mode": result.mode,
                "results": _public_results(result.matches),
            }
        )

    return AgentTool(
        name=KNOWLEDGE_LOOKUP_TOOL_NAME,
        provider_name="knowledge_lookup",
        description=(
            "Search the user's Knowledge Library for business rules, definitions, "
            "assumptions, and experience relevant to the current data task. Ask in "
            "business language; choose a retrieval mode only when useful, and use "
            "returned source excerpts as guidance alongside computed data evidence."
        ),
        input_model=KnowledgeLookupInput,
        implementation=lookup,
    )


def register_knowledge_lookup_tool(registry: Any, service: KnowledgeService) -> None:
    registry.register(knowledge_lookup_tool(service))


def _public_results(matches: list[Any]) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    for match in matches[:_RESULT_LIMIT]:
        excerpt = str(getattr(match, "quote", "")).strip()[:_MAX_EXCERPT_CHARS]
        if not excerpt:
            continue
        result = {
            "source": _public_source(getattr(match, "title", "")),
            "excerpt": excerpt,
        }
        location = _public_location(getattr(match, "locator", None))
        if location is not None:
            result["location"] = location
        results.append(result)
    return results


def _public_source(value: Any) -> str:
    source = str(value).strip()
    looks_like_path = (
        "://" in source
        or "/" in source
        or "\\" in source
        or source.startswith("~")
        or (len(source) >= 2 and source[1] == ":")
    )
    if looks_like_path:
        source = source.split("?", 1)[0].split("#", 1)[0]
        source = source.rstrip("/\\").replace("\\", "/").rsplit("/", 1)[-1].strip()
    if source in {".", "..", "~"}:
        source = ""
    return (source or "Knowledge source")[:_MAX_SOURCE_CHARS]


def _public_location(locator: Any) -> str | None:
    if not isinstance(locator, dict):
        return None
    for key, label in (("page", "page"), ("slide", "slide"), ("passage", "passage")):
        value = locator.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            return f"{label} {value}"
    return None
