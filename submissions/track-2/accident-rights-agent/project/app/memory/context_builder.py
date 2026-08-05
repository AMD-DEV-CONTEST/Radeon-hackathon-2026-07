"""Task-scoped context construction with measurable compression."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Sequence

from app.memory.protected_fields import (
    assert_protected_fields_preserved,
    collect_protected_fields,
    protected_set,
)
from app.memory.store import CaseMemoryStore
from app.rag.embeddings import tokenize
from app.schemas.legal import LegalCitation
from app.schemas.memory import CaseCapsule, ContextBundle


def estimate_tokens(value: Any) -> int:
    text = (
        value
        if isinstance(value, str)
        else json.dumps(value, ensure_ascii=False, sort_keys=True)
    )
    # Conservative multilingual approximation used for before/after metrics.
    return max(1, (len(text) + 1) // 2)


def relevance(query: str, value: Any) -> float:
    query_tokens = set(tokenize(query))
    candidate = json.dumps(value, ensure_ascii=False, sort_keys=True)
    candidate_tokens = set(tokenize(candidate))
    return len(query_tokens & candidate_tokens) / max(1, len(query_tokens))


BASE_WORKFLOW_KEYS = {
    "case_id",
    "thread_id",
    "current_node",
    "progress",
    "route",
    "approval_status",
    "document_status",
    "branch_reason",
    "rights_branch_reason",
    "human_action_required",
    "protected_fields_valid",
}

TASK_WORKFLOW_KEYS: tuple[tuple[tuple[str, ...], set[str]], ...] = (
    (
        ("车辆", "属性", "参数"),
        {
            "intake_assessment",
            "missing_evidence",
            "evidence_summary",
            "vehicle_classification",
        },
    ),
    (
        ("责任", "原因力", "违法", "赔偿"),
        {
            "missing_evidence",
            "vehicle_classification",
            "vehicle_nature_result",
            "violation_matrix",
            "causation_matrix",
            "liability_hypotheses",
        },
    ),
    (
        ("权益", "期限", "复核", "鉴定", "批准"),
        {
            "missing_evidence",
            "vehicle_classification",
            "liability_hypotheses",
            "responsibility_probabilities",
            "delivery_date_result",
            "deadlines",
            "rights_tasks",
            "approval_state",
        },
    ),
)


def task_workflow_state(task: str, state: Mapping[str, Any]) -> dict[str, Any]:
    selected = set(BASE_WORKFLOW_KEYS)
    for markers, keys in TASK_WORKFLOW_KEYS:
        if any(marker in task for marker in markers):
            selected.update(keys)
    return {
        key: state[key]
        for key in sorted(selected)
        if key in state and state[key] not in (None, "", [], {})
    }


def _fact_score(task: str, fact: dict[str, Any]) -> tuple[float, float, str]:
    status = str(fact.get("status", ""))
    status_bonus = 1.0 if status == "disputed" else 0.0
    confidence = float(fact.get("confidence", 0.0) or 0.0)
    return (relevance(task, fact) + status_bonus, confidence, str(fact.get("fact_id", "")))


class ContextBuilder:
    def __init__(self, memory_store: CaseMemoryStore):
        self.memory_store = memory_store

    def build(
        self,
        *,
        task: str,
        capsule: CaseCapsule,
        facts: Sequence[dict[str, Any]],
        citations: Sequence[LegalCitation],
        top_k_facts: int = 8,
        top_k_citations: int = 4,
        node_name: str = "unknown",
        workflow_state: Mapping[str, Any] | None = None,
        full_history: Sequence[dict[str, Any]] | None = None,
    ) -> ContextBundle:
        state = dict(workflow_state or {})
        history = list(full_history or [])
        before = {
            "capsule": capsule.model_dump(mode="json"),
            "facts": list(facts),
            "citations": [
                item.model_dump(mode="json") for item in citations
            ],
            "workflow_state": state,
            "history": history,
        }
        selected_facts = sorted(
            facts, key=lambda item: _fact_score(task, item), reverse=True
        )[:top_k_facts]
        citation_query = task + " " + " ".join(
            str(item.get("statement", "")) for item in selected_facts
        )
        selected_citations = sorted(
            citations,
            key=lambda item: relevance(
                citation_query, item.model_dump(mode="json")
            ),
            reverse=True,
        )[:top_k_citations]
        protected = collect_protected_fields(before)
        protected_values: dict[str, list[str]] = {}
        for item in protected:
            protected_values.setdefault(item.kind.value, []).append(item.value)
        selected_fact_ids = {
            str(item.get("fact_id")) for item in selected_facts if item.get("fact_id")
        }
        scoped_capsule = capsule.model_copy(
            update={
                "confirmed_facts": [
                    item
                    for item in capsule.confirmed_facts
                    if str(item.get("fact_id")) in selected_fact_ids
                ],
                "disputed_facts": [
                    item
                    for item in capsule.disputed_facts
                    if str(item.get("fact_id")) in selected_fact_ids
                ],
                "citations": list(selected_citations),
            }
        )
        evidence_ids = sorted(
            {
                str(evidence_id)
                for item in selected_facts
                for evidence_id in item.get("source_node_ids", [])
            }
        )
        after = {
            "capsule": scoped_capsule.model_dump(mode="json"),
            "facts": selected_facts,
            "citations": [
                item.model_dump(mode="json") for item in selected_citations
            ],
            "evidence_ids": evidence_ids,
            "workflow_state": task_workflow_state(task, state),
            # The kind-keyed mirror makes values such as document versions and
            # approval states independently discoverable by the fail-closed
            # validator after task-scoped context selection. Source paths stay
            # in the audit-only ContextBundle field and do not consume prompt
            # tokens.
            "protected_values": {
                kind: sorted(set(values))
                for kind, values in protected_values.items()
            },
        }
        assert_protected_fields_preserved(before, after)
        before_protected = protected_set(before)
        retained = len(before_protected & protected_set(after))
        retention = retained / max(1, len(before_protected))
        bundle = ContextBundle(
            case_id=self.memory_store.case_id,
            task=task,
            capsule=scoped_capsule,
            facts=list(selected_facts),
            citations=list(selected_citations),
            evidence_ids=evidence_ids,
            workflow_state=after["workflow_state"],
            protected_values={
                kind: sorted(set(values))
                for kind, values in protected_values.items()
            },
            before_token_count=estimate_tokens(before),
            after_token_count=estimate_tokens(after),
            protected_fields=protected,
            protected_field_retention=retention,
            full_history_items=len(history),
        )
        self.memory_store.record_working_context(
            node_name,
            bundle.model_dump(mode="json"),
            before_tokens=bundle.before_token_count,
            after_tokens=bundle.after_token_count,
        )
        return bundle
