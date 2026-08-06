from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping


CONFIG_SCHEMA = "ProofLaunchCodexCreativeAlphaFlightbookDraftV1"
OUTPUT_SCHEMA = "ProofLaunchCreativeAlphaFlightbookV1"
EXPECTED_SURFACES = {
    "linkedin", "tiktok", "reddit", "youtube", "instagram", "x",
    "google_search", "bing_search", "chatgpt_answers", "claude_answers",
    "gemini_answers", "perplexity_answers", "copilot_answers",
}


class CreativeAlphaFlightbookError(ValueError):
    pass


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _candidate_map(receipt: Mapping[str, Any], business_model: str) -> dict[str, dict[str, Any]]:
    if receipt.get("business_model") != business_model or receipt.get("accepted_surface_count") != 13:
        raise CreativeAlphaFlightbookError(f"{business_model} receipt coverage drifted")
    if receipt.get("external_publish_executed") is not False or receipt.get("production_effect_observed") is not False:
        raise CreativeAlphaFlightbookError(f"{business_model} external-effect boundary drifted")
    candidates = receipt.get("accepted_candidates", [])
    mapped = {row.get("surface_id"): dict(row) for row in candidates}
    if set(mapped) != EXPECTED_SURFACES or len(candidates) != len(mapped):
        raise CreativeAlphaFlightbookError(f"{business_model} surface set drifted")
    if any(row.get("external_publish_executed") is not False or row.get("winner_selected") is not False for row in mapped.values()):
        raise CreativeAlphaFlightbookError(f"{business_model} candidate authority drifted")
    if len({row.get("content_sha256") for row in mapped.values()}) != 13:
        raise CreativeAlphaFlightbookError(f"{business_model} duplicate surface candidate detected")
    return mapped


def compile_flightbook(
    config: Mapping[str, Any],
    *,
    b2b_receipt: Mapping[str, Any],
    b2c_receipt: Mapping[str, Any],
    human_kernel: Mapping[str, Any],
    source_bindings: list[dict[str, Any]],
) -> dict[str, Any]:
    if config.get("schema") != CONFIG_SCHEMA:
        raise CreativeAlphaFlightbookError("creative-alpha config schema drifted")
    cases = config.get("cases")
    if not isinstance(cases, Mapping) or set(cases) != {"b2b", "b2c"}:
        raise CreativeAlphaFlightbookError("B2B/B2C case coverage drifted")
    b2b = _candidate_map(b2b_receipt, "b2b")
    b2c = _candidate_map(b2c_receipt, "b2c")
    coverage = human_kernel.get("coverage", {})
    if coverage.get("role_count") != 22 or coverage.get("professional_skill_card_count") != 220:
        raise CreativeAlphaFlightbookError("human capability coverage drifted")
    if coverage.get("professional_axis_count") != 2200 or coverage.get("unconventional_edge_play_card_count") != 26:
        raise CreativeAlphaFlightbookError("10x detail or edge-play coverage drifted")
    playbooks = human_kernel.get("surface_operating_system", {}).get("playbooks", [])
    edge_cards = human_kernel.get("surface_operating_system", {}).get("unconventional_edge_play_contract", {}).get("cards", [])
    if {row.get("surface_id") for row in playbooks} != EXPECTED_SURFACES or len(edge_cards) != 26:
        raise CreativeAlphaFlightbookError("surface operating system drifted")
    compiled_cases = []
    for business_model, candidate_map in (("b2b", b2b), ("b2c", b2c)):
        spec = dict(cases[business_model])
        focus = {spec["primary_channel"], spec["secondary_channel"]}
        if len(focus) != 2 or not focus.issubset(EXPECTED_SURFACES):
            raise CreativeAlphaFlightbookError("execution must concentrate on one primary and one secondary channel")
        if business_model == "b2c" and "never_publish" not in spec["case_status"]:
            raise CreativeAlphaFlightbookError("synthetic B2C case lost publication boundary")
        compiled_cases.append({
            "business_model": business_model,
            **spec,
            "focused_candidates": [candidate_map[spec["primary_channel"]], candidate_map[spec["secondary_channel"]]],
            "owned_compounding_candidates": [candidate_map[surface] for surface in spec["owned_compounding_surfaces"]],
            "full_candidate_library": [candidate_map[surface] for surface in sorted(candidate_map)],
            "candidate_count": 13,
            "external_publish_executed": False,
            "production_effect_observed": False,
        })
    payload = {
        "schema": OUTPUT_SCHEMA,
        "portfolio_rule": config["portfolio_rule"],
        "cases": compiled_cases,
        "creative_intelligence": dict(config["creative_intelligence"]),
        "originality_gate": dict(config["originality_gate"]),
        "team_operating_system": {
            "functional_squad_count": coverage["functional_squad_count"],
            "role_count": coverage["role_count"],
            "professional_skill_card_count": coverage["professional_skill_card_count"],
            "professional_axis_count": coverage["professional_axis_count"],
            "eval_check_count": coverage["eval_check_count"],
            "kpi_binding_count": coverage["kpi_binding_count"],
            "surface_specialist_lens_count": coverage["surface_specialist_lens_count"],
            "role_okrs": human_kernel["role_okrs"],
        },
        "surface_playbooks": playbooks,
        "unconventional_edge_play_cards": edge_cards,
        "self_evolution": dict(config["self_evolution"]),
        "open_source_modifications": list(config["open_source_modifications"]),
        "source_bindings": source_bindings,
        "candidate_count": 26,
        "surface_count_per_case": 13,
        "qualified_human_review_count": 0,
        "completed_named_product_pk_count": 0,
        "candidate_win_count": 0,
        "external_action_executed": False,
        "production_effect_observed": False,
        "truth_boundary": config["truth_boundary"],
    }
    payload["content_sha256"] = _digest(payload)
    return payload


def verify(payload: Mapping[str, Any]) -> None:
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if payload.get("schema") != OUTPUT_SCHEMA or supplied != _digest(unsigned):
        raise CreativeAlphaFlightbookError("creative-alpha seal is invalid")
    if payload.get("candidate_count") != 26 or payload.get("completed_named_product_pk_count") != 0 or payload.get("candidate_win_count") != 0:
        raise CreativeAlphaFlightbookError("creative-alpha comparison boundary drifted")
    if payload.get("external_action_executed") is not False or payload.get("production_effect_observed") is not False:
        raise CreativeAlphaFlightbookError("creative-alpha effect boundary drifted")


__all__ = ["CreativeAlphaFlightbookError", "OUTPUT_SCHEMA", "compile_flightbook", "verify"]
