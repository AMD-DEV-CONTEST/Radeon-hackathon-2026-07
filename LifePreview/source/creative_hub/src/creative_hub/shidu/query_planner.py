"""Validated query planning with no provider or tool-selection authority."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from creative_hub.shidu.schemas import Book


class QueryPlanError(ValueError):
    pass


@dataclass(frozen=True)
class QueryPlan:
    queries: tuple[str, ...]
    evidence_gaps: tuple[str, ...] = ()


class QueryPlanningModel(Protocol):
    def plan(self, book: Book) -> object: ...


def _validated_strings(
    value: object,
    *,
    label: str,
    maximum_items: int,
    maximum_length: int,
) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise QueryPlanError(f"{label} must be a sequence")
    if len(value) > maximum_items:
        raise QueryPlanError(f"{label} contains too many items")
    result: list[str] = []
    seen: set[str] = set()
    for raw in value:
        if not isinstance(raw, str):
            raise QueryPlanError(f"{label} must contain only strings")
        item = " ".join(raw.split())
        if not item or len(item) > maximum_length:
            raise QueryPlanError(f"{label} contains an invalid item")
        folded = item.casefold()
        if folded not in seen:
            result.append(item)
            seen.add(folded)
    return tuple(result)


class QueryPlanner:
    """Accepts only queries and gaps; extra tool/provider fields fail closed."""

    def __init__(
        self,
        model: QueryPlanningModel | Callable[[Book], object] | None = None,
    ) -> None:
        self._model = model

    def plan(self, book: Book) -> QueryPlan:
        payload = self._call_model(book) if self._model is not None else self._default(book)
        if isinstance(payload, QueryPlan):
            raw_queries: object = payload.queries
            raw_gaps: object = payload.evidence_gaps
        elif isinstance(payload, Mapping):
            if set(payload) != {"queries", "evidence_gaps"}:
                raise QueryPlanError("planner output contains unsupported fields")
            raw_queries = payload["queries"]
            raw_gaps = payload["evidence_gaps"]
        else:
            raise QueryPlanError("planner output is invalid")
        queries = _validated_strings(
            raw_queries,
            label="queries",
            maximum_items=20,
            maximum_length=70,
        )
        if not queries:
            raise QueryPlanError("planner must return at least one query")
        gaps = _validated_strings(
            raw_gaps,
            label="evidence_gaps",
            maximum_items=20,
            maximum_length=500,
        )
        return QueryPlan(queries=queries, evidence_gaps=gaps)

    def _call_model(self, book: Book) -> object:
        model = self._model
        if callable(model):
            return model(book)
        if model is not None and callable(getattr(model, "plan", None)):
            return model.plan(book)
        raise QueryPlanError("planner model is not callable")

    @staticmethod
    def _default(book: Book) -> Mapping[str, Any]:
        title = " ".join(str(book.title).split())
        author = " ".join(str(book.author).split())
        if not title:
            raise QueryPlanError("book title is required for query planning")
        attribution = f" {author}" if author else ""
        return {
            "queries": [
                f'"{title}"{attribution} 原文 全文',
                f'"{title}"{attribution} 剧情 书评 解读',
                f'"{title}" gutenberg.org OR archive.org',
                f'"{title}" site:.edu 人物 生平 学术',
            ],
            "evidence_gaps": [
                "independent primary/reference source",
                "scholarly context",
                "critical reception",
            ],
        }


__all__ = ["QueryPlan", "QueryPlanError", "QueryPlanner", "QueryPlanningModel"]
