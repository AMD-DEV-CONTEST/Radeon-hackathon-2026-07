from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence


SCHEMA = "ProofLaunchGTMMechanismReviewQueueV2"
PROMOTED_SCHEMA = "ProofLaunchGTMMechanismAuditSetV2"
REQUIRED_DRAFT_FIELDS = (
    "problem",
    "insight",
    "strategy",
    "creative_system",
    "distribution",
    "conversion_path",
    "resource_inputs",
    "brand_advantage",
    "competitive_alternative_explanation",
    "nontransferable_conditions",
)


class GTMMechanismReviewQueueError(ValueError):
    pass


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def compile_mechanism_review_queue(
    candidate_corpus: Mapping[str, Any], drafts: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    candidates = {str(row["case_id"]): row for row in candidate_corpus.get("candidates", [])}
    if not candidates:
        raise GTMMechanismReviewQueueError("candidate corpus is empty")
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for draft in drafts:
        case_id = str(draft.get("case_id", ""))
        if case_id not in candidates or case_id in seen:
            raise GTMMechanismReviewQueueError(f"unknown or duplicate candidate draft: {case_id}")
        seen.add(case_id)
        for field in REQUIRED_DRAFT_FIELDS:
            value = draft.get(field)
            if not isinstance(value, str) or len(value.strip()) < 24:
                raise GTMMechanismReviewQueueError(f"{case_id}.{field} is too thin")
        candidate = candidates[case_id]
        draft_body = {
            "case_id": case_id,
            **{field: draft[field].strip() for field in REQUIRED_DRAFT_FIELDS},
            "evidence_receipt_sha256s": [row["content_sha256"] for row in candidate["source_receipts"]],
            "source_candidate_sha256": _digest(candidate),
        }
        rows.append(
            {
                "review_item_id": f"review:{case_id}",
                "status": "pending_human_review",
                "quota_credit": 0,
                "draft": draft_body,
                "draft_sha256": _digest(draft_body),
                "required_review": {
                    "reviewer_must_be_named": True,
                    "reviewer_must_inspect_exact_source_receipts": True,
                    "questions": [
                        "Does every mechanism statement follow from the captured sources without copying expression?",
                        "Are resource scope, brand advantage, timing, and nontransferable conditions explicit?",
                        "Is at least one serious alternative explanation preserved?",
                        "Would a target-industry operator understand what to test and what not to transfer?",
                        "Does approval cover mechanism research only, not causality, publishing, spend, or memory promotion?",
                    ],
                    "allowed_verdicts": ["approved_for_mechanism_research", "repair", "reject"],
                },
            }
        )
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "candidate_corpus_sha256": candidate_corpus.get("content_sha256"),
        "review_item_count": len(rows),
        "pending_human_review_count": len(rows),
        "mechanism_quota_credit": 0,
        "items": rows,
        "truth_boundary": "AI-authored mechanism drafts have zero deep-audit credit until a named reviewer approves the exact sealed draft and sources.",
    }
    payload["content_sha256"] = _digest(payload)
    return payload


def promote_approved_mechanisms(
    queue: Mapping[str, Any], reviews: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    items = {str(row["review_item_id"]): row for row in queue.get("items", [])}
    promoted: list[dict[str, Any]] = []
    seen: set[str] = set()
    for review in reviews:
        review_item_id = str(review.get("review_item_id", ""))
        item = items.get(review_item_id)
        if item is None or review_item_id in seen:
            raise GTMMechanismReviewQueueError(f"unknown or duplicate review: {review_item_id}")
        seen.add(review_item_id)
        if review.get("verdict") != "approved_for_mechanism_research":
            continue
        reviewer = str(review.get("reviewer_name", "")).strip()
        if len(reviewer) < 3 or review.get("draft_sha256") != item["draft_sha256"]:
            raise GTMMechanismReviewQueueError(f"{review_item_id} lacks a named hash-bound approval")
        if review.get("source_receipts_inspected") is not True:
            raise GTMMechanismReviewQueueError(f"{review_item_id} did not inspect source receipts")
        draft = item["draft"]
        promoted.append(
            {
                "audit_id": f"mechanism:{draft['case_id']}",
                "case_id": draft["case_id"],
                "status": "mechanism_deep_audited",
                **{field: draft[field] for field in REQUIRED_DRAFT_FIELDS},
                "evidence_receipt_sha256s": draft["evidence_receipt_sha256s"],
                "human_review_status": "approved_for_mechanism_research",
                "reviewer_name": reviewer,
                "reviewed_at": review.get("reviewed_at"),
                "review_receipt_sha256": _digest(review),
            }
        )
    payload: dict[str, Any] = {
        "schema": PROMOTED_SCHEMA,
        "review_queue_sha256": queue.get("content_sha256"),
        "review_count": len(reviews),
        "promoted_mechanism_count": len(promoted),
        "mechanism_audits": promoted,
    }
    payload["content_sha256"] = _digest(payload)
    return payload


def verify_mechanism_review_queue(payload: Mapping[str, Any]) -> None:
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if payload.get("schema") != SCHEMA or supplied != _digest(unsigned):
        raise GTMMechanismReviewQueueError("mechanism review queue seal is invalid")
    items = payload.get("items")
    if not isinstance(items, list) or payload.get("review_item_count") != len(items):
        raise GTMMechanismReviewQueueError("mechanism review queue count drifted")
    if payload.get("mechanism_quota_credit") != 0 or any(
        row.get("status") != "pending_human_review" or row.get("quota_credit") != 0 for row in items
    ):
        raise GTMMechanismReviewQueueError("unreviewed draft received mechanism credit")


__all__ = [
    "GTMMechanismReviewQueueError",
    "compile_mechanism_review_queue",
    "promote_approved_mechanisms",
    "verify_mechanism_review_queue",
]
