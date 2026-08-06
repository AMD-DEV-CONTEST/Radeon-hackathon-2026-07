from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from .gtm_wave1_discovery_leads_v2 import verify_wave1_discovery_leads


SCHEMA = "ProofLaunchGTMCaseClassificationQueueV2"


class GTMCaseClassificationQueueError(ValueError):
    pass


TASK_TEMPLATES = (
    ("source_claim_binding", "P0", "Bind exact claim excerpts and locators from the captured source.", "At least one exact source locator is bound to each proposed mechanism and outcome statement; unsupported statements are removed."),
    ("entity_resolution", "P0", "Resolve company, brand, product, domain, regional account, and alias identity.", "A stable entity key is produced with alias and ownership evidence; ambiguity remains manual-review only."),
    ("episode_identity", "P0", "Resolve the distinct campaign or GTM motion and eliminate cross-platform mirrors.", "Company, product, motion, primary market, observed start, and observed end produce one stable episode key."),
    ("observed_period", "P0", "Resolve evidence-backed observed start and end dates.", "Both dates are source-bound; publication date is not substituted for the performance window without explicit evidence."),
    ("budget_and_resources", "P0", "Resolve paid media, labor, tooling, creator, channel, production, and founder-time scope.", "A V2 budget bucket is supported by disclosed components; unknown spend remains unresolved and receives zero credit."),
    ("company_scale", "P1", "Resolve company scale during the observed episode.", "Small, mid-market, or enterprise/mass-brand classification is tied to dated headcount, revenue, distribution, or equivalent evidence."),
    ("lifecycle_state", "P1", "Resolve pre-PMF, launch, growth, or mature state during the episode.", "Lifecycle classification follows observed-period evidence rather than present-day company status."),
    ("market_and_language", "P1", "Resolve primary quota market and the English-market operating context.", "One V2 market bucket is selected with evidence; multi-market is used only when no single primary market explains the episode."),
    ("platform_set", "P1", "Resolve the platforms that materially executed the motion.", "Platforms are source-bound and distinguish primary, reinforcing, owned, earned, and paid roles without adding unsupported channels."),
    ("recency_bucket", "P1", "Resolve the 3–6, 6–12, 12–24 month, or historical-mechanism bucket.", "Bucket follows the observed outcome window relative to the frozen research cutoff and cannot be inferred from page freshness alone."),
    ("outcome_classification", "P1", "Resolve outcome type, baseline, measurement window, and result summary.", "Recent breakout, durable repeat, failed/stalled, mature control, or turnaround is supported by a bounded baseline and result window."),
    ("independent_outcome_surface", "P2", "Find an independent or first-party outcome surface beyond the vendor case page.", "A second evidence surface corroborates the business or behavioral outcome, or the lead remains candidate-ineligible with a precise gap."),
)


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def compile_case_classification_queue(discovery: Mapping[str, Any]) -> dict[str, Any]:
    verify_wave1_discovery_leads(discovery)
    items: list[dict[str, Any]] = []
    for lead in discovery["records"]:
        for order, (task_type, priority, instruction, acceptance) in enumerate(TASK_TEMPLATES, start=1):
            items.append({
                "work_item_id": f"classify:{lead['lead_id']}:{task_type}",
                "lead_id": lead["lead_id"],
                "company": lead["company"],
                "provisional_subvertical_id": lead["provisional_subvertical_id"],
                "source_url": lead["source_url"],
                "source_capture_sha256": lead["capture_content_sha256"],
                "task_type": task_type,
                "priority": priority,
                "priority_rank": {"P0": 0, "P1": 1, "P2": 2}[priority],
                "lead_task_order": order,
                "status": "open",
                "instruction": instruction,
                "acceptance_criteria": acceptance,
                "required_output": {
                    "value": "typed value or unresolved",
                    "source_receipt_sha256s": "one or more hashes when resolved",
                    "exact_locators": "one or more locators when resolved",
                    "reviewer_note": "reasoning summary without hidden chain-of-thought",
                    "confidence": "high, medium, low, or unresolved",
                },
                "automatic_completion_allowed": False,
                "quota_credit": 0,
            })
    items.sort(key=lambda row: (row["priority_rank"], row["provisional_subvertical_id"], row["lead_id"], row["lead_task_order"]))
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "source_discovery_sha256": discovery["content_sha256"],
        "lead_count": discovery["lead_count"],
        "tasks_per_lead": len(TASK_TEMPLATES),
        "work_item_count": len(items),
        "status_counts": {"open": len(items), "complete": 0, "blocked": 0},
        "priority_counts": {
            priority: sum(row["priority"] == priority for row in items) for priority in ("P0", "P1", "P2")
        },
        "items": items,
        "promotion_policy": {
            "work_item_completion_grants_case_credit": False,
            "all_required_case_fields_and_identity_must_resolve_before_candidate_review": True,
            "independent_surface_missing_may_remain_explicit_gap": True,
            "automatic_human_review_substitution_allowed": False,
        },
        "truth_boundary": "This is an execution queue, not evidence of completed classification or case eligibility.",
    }
    payload["content_sha256"] = _digest(payload)
    return payload


def verify_case_classification_queue(payload: Mapping[str, Any]) -> None:
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if payload.get("schema") != SCHEMA or supplied != _digest(unsigned):
        raise GTMCaseClassificationQueueError("classification queue seal is invalid")
    items = payload.get("items")
    expected = int(payload.get("lead_count", 0)) * len(TASK_TEMPLATES)
    if not isinstance(items, list) or payload.get("tasks_per_lead") != len(TASK_TEMPLATES) or len(items) != expected:
        raise GTMCaseClassificationQueueError("classification queue cardinality drifted")
    if payload.get("work_item_count") != len(items):
        raise GTMCaseClassificationQueueError("classification work item count drifted")
    ids = [row.get("work_item_id") for row in items]
    if len(ids) != len(set(ids)):
        raise GTMCaseClassificationQueueError("classification work items are duplicated")
    by_lead: dict[str, set[str]] = {}
    for row in items:
        by_lead.setdefault(str(row.get("lead_id")), set()).add(str(row.get("task_type")))
        if row.get("quota_credit") != 0 or row.get("automatic_completion_allowed") is not False:
            raise GTMCaseClassificationQueueError("open classification work minted credit or bypassed review")
    required_types = {row[0] for row in TASK_TEMPLATES}
    if any(types != required_types for types in by_lead.values()):
        raise GTMCaseClassificationQueueError("a lead lacks one or more classification task types")


__all__ = [
    "GTMCaseClassificationQueueError",
    "TASK_TEMPLATES",
    "compile_case_classification_queue",
    "verify_case_classification_queue",
]
