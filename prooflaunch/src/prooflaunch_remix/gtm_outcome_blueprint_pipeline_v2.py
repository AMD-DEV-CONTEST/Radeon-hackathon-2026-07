from __future__ import annotations

from collections import Counter
import hashlib
import json
import re
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse


OUTCOME_QUEUE_SCHEMA = "ProofLaunchGTMOutcomeReviewQueueV2"
OUTCOME_SET_SCHEMA = "ProofLaunchGTMOutcomeAuditSetV2"
BLUEPRINT_QUEUE_SCHEMA = "ProofLaunchGTMExecutionBlueprintReviewQueueV2"
BLUEPRINT_SET_SCHEMA = "ProofLaunchGTMExecutionBlueprintSetV2"
FAMILY_SCHEMA = "ProofLaunchGTMMechanismFamilyIndexV2"
OUTCOME_TARGET = 10
BLUEPRINT_TARGET = 5
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
BUSINESS_OUTCOME_CATEGORIES = {
    "revenue", "profit", "retention", "orders", "qualified_pipeline", "verified_user_behavior"
}
CAUSAL_METHODS = {"randomized_holdout", "geo_holdout", "time_holdout", "matched_control"}
BLUEPRINT_FIELDS = (
    "applicability", "proof_object", "primary_channel", "reinforcing_channel",
    "measurement_chain", "kill_rule", "forbidden_copy_boundary",
)


class GTMOutcomeBlueprintPipelineError(ValueError):
    pass


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _seal(payload: dict[str, Any]) -> dict[str, Any]:
    payload["content_sha256"] = _digest(payload)
    return payload


def _verify_seal(payload: Mapping[str, Any], schema: str) -> None:
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if payload.get("schema") != schema or supplied != _digest(unsigned):
        raise GTMOutcomeBlueprintPipelineError(f"{schema} seal is invalid")


def _text(row: Mapping[str, Any], field: str, minimum: int = 4) -> str:
    value = str(row.get(field) or "").strip()
    if len(value) < minimum:
        raise GTMOutcomeBlueprintPipelineError(f"{field} is missing or too thin")
    return value


def _validate_surfaces(surfaces: Any) -> list[dict[str, Any]]:
    if not isinstance(surfaces, list) or len(surfaces) < 2:
        raise GTMOutcomeBlueprintPipelineError("at least two independent evidence surfaces are required")
    normalized: list[dict[str, Any]] = []
    for surface in surfaces:
        if not isinstance(surface, Mapping):
            raise GTMOutcomeBlueprintPipelineError("outcome evidence surface is invalid")
        source_url = str(surface.get("source_url") or "")
        source_class = str(surface.get("source_class") or "")
        content_hash = str(surface.get("content_sha256") or "")
        if urlparse(source_url).scheme != "https" or not urlparse(source_url).netloc or not source_class or not SHA256_RE.fullmatch(content_hash):
            raise GTMOutcomeBlueprintPipelineError("outcome evidence surface lacks URL, class, or SHA-256")
        normalized.append({
            "source_url": source_url,
            "source_class": source_class,
            "content_sha256": content_hash,
            "claim_scope": _text(surface, "claim_scope", 8),
        })
    if len({urlparse(row["source_url"]).netloc for row in normalized}) < 2 or len({row["source_class"] for row in normalized}) < 2:
        raise GTMOutcomeBlueprintPipelineError("two independent domains and source classes are required")
    return normalized


def compile_outcome_review_queue(
    candidates: Sequence[Mapping[str, Any]],
    mechanism_audits: Sequence[Mapping[str, Any]],
    drafts: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    candidate_by_id = {str(row.get("case_id")): row for row in candidates}
    mechanism_by_id = {str(row.get("audit_id")): row for row in mechanism_audits}
    valid_mechanisms = {
        key: row for key, row in mechanism_by_id.items()
        if row.get("status") == "mechanism_deep_audited" and row.get("human_review_status") == "approved_for_mechanism_research"
    }
    prepared: list[dict[str, Any]] = []
    seen_cases: set[str] = set()
    for draft in drafts:
        case_id = str(draft.get("case_id") or "")
        mechanism_id = str(draft.get("mechanism_audit_id") or "")
        if case_id in seen_cases or case_id not in candidate_by_id or mechanism_id not in valid_mechanisms or valid_mechanisms[mechanism_id].get("case_id") != case_id:
            raise GTMOutcomeBlueprintPipelineError("outcome draft has duplicate or invalid candidate/mechanism lineage")
        seen_cases.add(case_id)
        category = str(draft.get("outcome_category") or "")
        if category not in BUSINESS_OUTCOME_CATEGORIES:
            raise GTMOutcomeBlueprintPipelineError("outcome category is not a permitted business result")
        attribution = _text(draft, "attribution_method")
        causal_allowed = bool(draft.get("causal_claim_allowed"))
        if causal_allowed and attribution not in CAUSAL_METHODS:
            raise GTMOutcomeBlueprintPipelineError("causal language lacks an eligible design")
        surfaces = _validate_surfaces(draft.get("independent_evidence_surfaces"))
        body = {
            "case_id": case_id,
            "mechanism_audit_id": mechanism_id,
            "outcome_category": category,
            "business_outcome": _text(draft, "business_outcome", 12),
            "baseline": _text(draft, "baseline", 4),
            "measurement_window": _text(draft, "measurement_window", 4),
            "attribution_method": attribution,
            "confidence_grade": _text(draft, "confidence_grade", 4),
            "independent_evidence_surfaces": surfaces,
            "causal_claim_allowed": causal_allowed,
        }
        prepared.append({
            "review_item_id": f"outcome-review:{case_id}",
            "subvertical_id": candidate_by_id[case_id].get("subvertical_id"),
            "status": "pending_named_human_outcome_review",
            "draft": body,
            "draft_sha256": _digest(body),
            "quota_credit": 0,
        })
    selected: list[dict[str, Any]] = []
    per_subvertical = Counter()
    for row in sorted(prepared, key=lambda item: (-len(item["draft"]["independent_evidence_surfaces"]), item["review_item_id"])):
        subvertical_id = str(row["subvertical_id"])
        if per_subvertical[subvertical_id] < OUTCOME_TARGET:
            selected.append(row)
            per_subvertical[subvertical_id] += 1
    return _seal({
        "schema": OUTCOME_QUEUE_SCHEMA,
        "eligible_draft_count": len(prepared),
        "selected_review_item_count": len(selected),
        "items": selected,
        "policy": {
            "maximum_per_subvertical": OUTCOME_TARGET,
            "two_independent_domains_and_classes_required": True,
            "business_result_category_required": True,
            "named_human_review_required": True,
            "queue_grants_outcome_credit": False,
        },
        "truth_boundary": "The queue validates cross-source structure and business-result linkage but grants zero outcome credit before named human inspection.",
    })


def verify_outcome_review_queue(payload: Mapping[str, Any]) -> None:
    _verify_seal(payload, OUTCOME_QUEUE_SCHEMA)
    items = payload.get("items")
    if not isinstance(items, list) or payload.get("selected_review_item_count") != len(items):
        raise GTMOutcomeBlueprintPipelineError("outcome queue aggregate drifted")
    counts = Counter(str(row.get("subvertical_id")) for row in items)
    if any(value > OUTCOME_TARGET for value in counts.values()) or any(row.get("quota_credit") != 0 for row in items):
        raise GTMOutcomeBlueprintPipelineError("outcome queue exceeded selection target or minted credit")


def promote_outcome_reviews(queue: Mapping[str, Any], reviews: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    verify_outcome_review_queue(queue)
    items = {str(row["review_item_id"]): row for row in queue["items"]}
    audits = []
    seen: set[str] = set()
    for review in reviews:
        item_id = str(review.get("review_item_id") or "")
        item = items.get(item_id)
        if item is None or item_id in seen:
            raise GTMOutcomeBlueprintPipelineError("unknown or duplicate outcome review")
        seen.add(item_id)
        if review.get("verdict") != "approved_for_outcome_research":
            continue
        if len(str(review.get("reviewer_name") or "").strip()) < 3 or review.get("draft_sha256") != item["draft_sha256"] or review.get("all_evidence_surfaces_inspected") is not True:
            raise GTMOutcomeBlueprintPipelineError("outcome approval is not named, hash-bound, and source-inspected")
        draft = item["draft"]
        audits.append({
            "outcome_audit_id": f"outcome:{draft['case_id']}",
            "status": "outcome_cross_verified",
            **draft,
            "human_review_status": "approved_for_outcome_research",
            "reviewer_name": str(review["reviewer_name"]).strip(),
            "reviewed_at": review.get("reviewed_at"),
            "review_receipt_sha256": _digest(review),
        })
    return _seal({
        "schema": OUTCOME_SET_SCHEMA,
        "review_queue_sha256": queue["content_sha256"],
        "review_count": len(reviews),
        "promoted_outcome_count": len(audits),
        "outcome_audits": audits,
    })


def compile_blueprint_review_queue(
    candidates: Sequence[Mapping[str, Any]],
    outcome_audits: Sequence[Mapping[str, Any]],
    drafts: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    candidate_by_id = {str(row.get("case_id")): row for row in candidates}
    outcome_by_id = {str(row.get("outcome_audit_id")): row for row in outcome_audits if row.get("status") == "outcome_cross_verified"}
    prepared = []
    seen: set[str] = set()
    for draft in drafts:
        case_id = str(draft.get("case_id") or "")
        outcome_id = str(draft.get("outcome_audit_id") or "")
        if case_id in seen or case_id not in candidate_by_id or outcome_id not in outcome_by_id or outcome_by_id[outcome_id].get("case_id") != case_id:
            raise GTMOutcomeBlueprintPipelineError("blueprint draft has duplicate or invalid outcome lineage")
        seen.add(case_id)
        if draft.get("automatic_publish_or_spend_allowed") is not False:
            raise GTMOutcomeBlueprintPipelineError("blueprint enables external action")
        body = {
            "case_id": case_id,
            "outcome_audit_id": outcome_id,
            **{field: _text(draft, field, 8) for field in BLUEPRINT_FIELDS},
            "execution_steps": list(draft.get("execution_steps") or []),
            "platform_adaptations": list(draft.get("platform_adaptations") or []),
            "automatic_publish_or_spend_allowed": False,
        }
        if len(body["execution_steps"]) < 4 or len(body["platform_adaptations"]) < 2:
            raise GTMOutcomeBlueprintPipelineError("blueprint needs at least four steps and two platform adaptations")
        candidate = candidate_by_id[case_id]
        prepared.append({
            "review_item_id": f"blueprint-review:{case_id}",
            "subvertical_id": candidate.get("subvertical_id"),
            "diversity": {field: candidate.get(field) for field in ("company_scale", "budget_tier", "lifecycle_state", "outcome_type")},
            "status": "pending_named_human_blueprint_review",
            "draft": body,
            "draft_sha256": _digest(body),
            "quota_credit": 0,
        })
    selected = []
    per_subvertical = Counter()
    for row in sorted(prepared, key=lambda item: item["review_item_id"]):
        subvertical_id = str(row["subvertical_id"])
        if per_subvertical[subvertical_id] < BLUEPRINT_TARGET:
            selected.append(row)
            per_subvertical[subvertical_id] += 1
    summaries = []
    for subvertical_id in sorted({str(row["subvertical_id"]) for row in selected}):
        rows = [row for row in selected if row["subvertical_id"] == subvertical_id]
        distinct = {field: len({row["diversity"][field] for row in rows}) for field in ("company_scale", "budget_tier", "lifecycle_state", "outcome_type")}
        diversity_pass = all(value >= 2 for value in distinct.values())
        summaries.append({
            "subvertical_id": subvertical_id,
            "selected_count": len(rows),
            "distinct_dimension_counts": distinct,
            "diversity_pass": diversity_pass,
            "status": "ready_for_named_human_blueprint_review" if len(rows) == 5 and diversity_pass else "blueprint_selection_gap",
        })
    return _seal({
        "schema": BLUEPRINT_QUEUE_SCHEMA,
        "eligible_draft_count": len(prepared),
        "selected_review_item_count": len(selected),
        "items": selected,
        "subvertical_summaries": summaries,
        "policy": {
            "maximum_per_subvertical": BLUEPRINT_TARGET,
            "minimum_distinct_values_per_required_dimension": 2,
            "required_diversity_dimensions": ["company_scale", "budget_tier", "lifecycle_state", "outcome_type"],
            "named_human_review_required": True,
            "queue_grants_blueprint_credit": False,
        },
        "truth_boundary": "Blueprint drafts preserve conditions, steps, measurement and kill rules but are not execution-level evidence before named approval.",
    })


def verify_blueprint_review_queue(payload: Mapping[str, Any]) -> None:
    _verify_seal(payload, BLUEPRINT_QUEUE_SCHEMA)
    items = payload.get("items")
    if not isinstance(items, list) or payload.get("selected_review_item_count") != len(items):
        raise GTMOutcomeBlueprintPipelineError("blueprint queue aggregate drifted")
    counts = Counter(str(row.get("subvertical_id")) for row in items)
    if any(value > BLUEPRINT_TARGET for value in counts.values()) or any(row.get("quota_credit") != 0 for row in items):
        raise GTMOutcomeBlueprintPipelineError("blueprint queue exceeded target or minted credit")


def promote_blueprint_reviews(queue: Mapping[str, Any], reviews: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    verify_blueprint_review_queue(queue)
    items = {str(row["review_item_id"]): row for row in queue["items"]}
    blueprints = []
    seen: set[str] = set()
    for review in reviews:
        item_id = str(review.get("review_item_id") or "")
        item = items.get(item_id)
        if item is None or item_id in seen:
            raise GTMOutcomeBlueprintPipelineError("unknown or duplicate blueprint review")
        seen.add(item_id)
        if review.get("verdict") != "approved_execution_blueprint":
            continue
        if len(str(review.get("reviewer_name") or "").strip()) < 3 or review.get("draft_sha256") != item["draft_sha256"] or review.get("lineage_and_boundaries_inspected") is not True:
            raise GTMOutcomeBlueprintPipelineError("blueprint approval is not named, hash-bound, and inspected")
        draft = item["draft"]
        blueprints.append({
            "blueprint_id": f"blueprint:{draft['case_id']}",
            "status": "execution_case_blueprint",
            **draft,
            "human_review_status": "approved_execution_blueprint",
            "reviewer_name": str(review["reviewer_name"]).strip(),
            "reviewed_at": review.get("reviewed_at"),
            "review_receipt_sha256": _digest(review),
        })
    return _seal({
        "schema": BLUEPRINT_SET_SCHEMA,
        "review_queue_sha256": queue["content_sha256"],
        "review_count": len(reviews),
        "promoted_blueprint_count": len(blueprints),
        "execution_blueprints": blueprints,
    })


def compile_mechanism_family_index(
    blueprints: Sequence[Mapping[str, Any]], assignments: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    blueprint_ids = {str(row.get("blueprint_id") or "") for row in blueprints}
    if "" in blueprint_ids or len(blueprint_ids) != len(blueprints):
        raise GTMOutcomeBlueprintPipelineError("blueprint IDs are invalid")
    families = []
    assigned: list[str] = []
    for raw in assignments:
        family_id = _text(raw, "family_id", 4)
        members = [str(value) for value in raw.get("blueprint_ids") or []]
        if not members or not set(members).issubset(blueprint_ids):
            raise GTMOutcomeBlueprintPipelineError("mechanism family has invalid blueprint members")
        diagnostics = list(raw.get("diagnostic_signals") or [])
        exclusions = list(raw.get("exclusion_signals") or [])
        invariants = list(raw.get("invariant_principles") or [])
        adaptable = list(raw.get("adaptable_variables") or [])
        if len(diagnostics) < 3 or len(exclusions) < 2 or len(invariants) < 2 or len(adaptable) < 3:
            raise GTMOutcomeBlueprintPipelineError("mechanism family lacks diagnostic or adaptation depth")
        families.append({
            "family_id": family_id,
            "blueprint_ids": sorted(members),
            "diagnostic_signals": diagnostics,
            "exclusion_signals": exclusions,
            "invariant_principles": invariants,
            "adaptable_variables": adaptable,
            "forbidden_copying_rule": _text(raw, "forbidden_copying_rule", 12),
            "fixed_formula": False,
        })
        assigned.extend(members)
    if sorted(assigned) != sorted(blueprint_ids):
        raise GTMOutcomeBlueprintPipelineError("every blueprint must belong to exactly one mechanism family")
    return _seal({
        "schema": FAMILY_SCHEMA,
        "blueprint_count": len(blueprints),
        "family_count": len(families),
        "fixed_formula_count": 0,
        "families": sorted(families, key=lambda row: row["family_id"]),
        "selection_contract": "Diagnose signals and exclusions first; adapt variables to the current brief; never reproduce source expression or execute a blueprint as a fixed formula.",
        "truth_boundary": "Mechanism families are diagnostic priors, not guaranteed playbooks or proof of future effects.",
    })


def verify_mechanism_family_index(payload: Mapping[str, Any]) -> None:
    _verify_seal(payload, FAMILY_SCHEMA)
    families = payload.get("families")
    if not isinstance(families, list) or payload.get("family_count") != len(families) or payload.get("fixed_formula_count") != 0:
        raise GTMOutcomeBlueprintPipelineError("mechanism family aggregate drifted")
    members = [member for family in families for member in family.get("blueprint_ids", [])]
    if len(members) != len(set(members)) or payload.get("blueprint_count") != len(members):
        raise GTMOutcomeBlueprintPipelineError("mechanism family membership drifted")


__all__ = [
    "GTMOutcomeBlueprintPipelineError", "compile_blueprint_review_queue",
    "compile_mechanism_family_index", "compile_outcome_review_queue",
    "promote_blueprint_reviews", "promote_outcome_reviews",
    "verify_blueprint_review_queue", "verify_mechanism_family_index",
    "verify_outcome_review_queue",
]
