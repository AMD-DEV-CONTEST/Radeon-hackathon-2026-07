from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping


CONFIG_SCHEMA = "ProofLaunchCodexTextNamedPKSuperChallengerDraftV1"
CANDIDATE_SCHEMA = "ProofLaunchCodexTextNamedPKSuperChallengerV1"
PORTFOLIO_SCHEMA = "ProofLaunchCodexTextNamedPKRowPortfolioV1"
EXPECTED_PRODUCTS = (
    "ChatGPT",
    "Claude",
    "Gemini",
    "Jasper",
    "Copy.ai",
    "Writer",
    "Notion AI",
    "Grammarly",
    "Perplexity",
    "Writesonic",
)
EXPECTED_ASSETS = ("linkedin", "partner_community", "landing_hero", "lifecycle_email")
FORBIDDEN_ASSERTIONS = (
    r"\bguarantee(?:d|s)?\b",
    r"\btop[ -]?1\b",
    r"\bbest[- ]in[- ]class\b",
    r"\b4a[- ]grade\b",
    r"\bproven (?:conversion|pipeline|revenue|virality|superiority)\b",
)


class TextNamedPKChallengerError(ValueError):
    pass


def canonical_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _seal(payload: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    result["content_sha256"] = digest(result)
    return result


def _require_text(value: object, field: str, minimum: int) -> str:
    if not isinstance(value, str) or len(value.strip()) < minimum:
        raise TextNamedPKChallengerError(f"{field} must contain at least {minimum} characters")
    return value.strip()


def compile_candidate(config: Mapping[str, Any]) -> dict[str, Any]:
    if config.get("schema") != CONFIG_SCHEMA:
        raise TextNamedPKChallengerError("challenger config schema drifted")
    brief = config.get("frozen_brief")
    core = config.get("strategic_core")
    assets = config.get("assets")
    stress = config.get("opponent_stress_tests")
    oss = config.get("open_source_modifications")
    if not all(isinstance(value, Mapping) for value in (brief, core, assets, stress)):
        raise TextNamedPKChallengerError("challenger config is incomplete")
    if set(assets) != set(EXPECTED_ASSETS) or tuple(stress) != EXPECTED_PRODUCTS:
        raise TextNamedPKChallengerError("asset or named-product coverage drifted")
    if not isinstance(oss, list) or {row.get("project_id") for row in oss if isinstance(row, Mapping)} != {
        "dspy", "promptfoo", "qwen3_embedding", "cleanlab"
    }:
        raise TextNamedPKChallengerError("open-source modification set drifted")
    claim = _require_text(brief.get("approved_claim"), "approved_claim", 40)
    lengths = {"linkedin": 700, "partner_community": 700, "landing_hero": 180, "lifecycle_email": 500}
    compiled_assets: dict[str, Any] = {}
    all_text: list[str] = []
    for asset_id in EXPECTED_ASSETS:
        asset = dict(assets[asset_id])
        if asset.get("release_state") != "draft_pending_named_human_review":
            raise TextNamedPKChallengerError(f"{asset_id} escaped human review")
        serialized = json.dumps(asset, ensure_ascii=False)
        if len(serialized) < lengths[asset_id] or claim not in serialized:
            raise TextNamedPKChallengerError(f"{asset_id} is too thin or lost the approved claim")
        compiled_assets[asset_id] = asset
        all_text.append(serialized)
    joined = "\n".join(all_text)
    for pattern in FORBIDDEN_ASSERTIONS:
        if re.search(pattern, joined, flags=re.IGNORECASE):
            raise TextNamedPKChallengerError(f"forbidden assertion entered challenger: {pattern}")
    candidate = {
        "schema": CANDIDATE_SCHEMA,
        "authorship": {
            "mode": config.get("authorship_mode"),
            "workspace_model_authorship_asserted": True,
            "flagship_api_inference_observed": False,
            "api_call_count": "not_measured_by_worktree",
        },
        "frozen_brief": dict(brief),
        "strategic_core": dict(core),
        "assets": compiled_assets,
        "opponent_stress_tests": dict(stress),
        "open_source_modifications": [dict(row) for row in oss],
        "asset_count": 4,
        "named_product_target_count": 10,
        "level_1_contract_passed": True,
        "qualified_human_review_count": 0,
        "release_eligible": False,
        "external_publish_executed": False,
        "production_effect_observed": False,
        "truth_boundary": config.get("truth_boundary"),
    }
    return _seal(candidate)


def verify_candidate(candidate: Mapping[str, Any]) -> None:
    if candidate.get("schema") != CANDIDATE_SCHEMA:
        raise TextNamedPKChallengerError("candidate schema drifted")
    unsigned = dict(candidate)
    supplied = unsigned.pop("content_sha256", None)
    if supplied != digest(unsigned):
        raise TextNamedPKChallengerError("candidate seal is invalid")
    if (
        candidate.get("asset_count") != 4
        or candidate.get("named_product_target_count") != 10
        or candidate.get("qualified_human_review_count") != 0
        or candidate.get("release_eligible") is not False
        or candidate.get("external_publish_executed") is not False
        or candidate.get("production_effect_observed") is not False
    ):
        raise TextNamedPKChallengerError("candidate truth boundary drifted")


def compile_row_portfolio(candidate: Mapping[str, Any], ledger: Mapping[str, Any]) -> dict[str, Any]:
    verify_candidate(candidate)
    rows = [row for row in ledger.get("product_pk_rows", []) if row.get("category_id") == "text_content_generation"]
    if tuple(row.get("reference_product") for row in rows) != EXPECTED_PRODUCTS:
        raise TextNamedPKChallengerError("ledger text-product order drifted")
    row_bindings = []
    for row in rows:
        product = row["reference_product"]
        row_bindings.append({
            "reference_product": product,
            "reference_capability": row["reference_capability"],
            "reference_product_url": row["reference_product_url"],
            "same_brief_task": row["same_brief_task"],
            "effect_pk_question": row["effect_pk_question"],
            "quality_axes": list(row["quality_axes"]),
            "opponent_specific_stress_test": candidate["opponent_stress_tests"][product],
            "challenger_candidate_sha256": candidate["content_sha256"],
            "named_product_baseline_present": False,
            "qualified_human_review_count": 0,
            "comparison_status": "awaiting_authorized_named_product_baseline",
            "candidate_won": False,
        })
    payload = {
        "schema": PORTFOLIO_SCHEMA,
        "category_id": "text_content_generation",
        "source_ledger_sha256": ledger.get("content_sha256"),
        "candidate": dict(candidate),
        "row_count": 10,
        "rows": row_bindings,
        "candidate_level_1_pass_count": 10,
        "authorized_named_product_baseline_count": 0,
        "completed_named_product_pk_count": 0,
        "candidate_win_count": 0,
        "qualified_human_review_count": 0,
        "four_a_quality_proven": False,
        "top1_claim_eligible": False,
        "truth_boundary": "One clean-room four-asset challenger is bound to ten named text-product rows. No named-product outputs or human comparisons are present, so no row is complete or won.",
    }
    return _seal(payload)


def verify_row_portfolio(payload: Mapping[str, Any]) -> None:
    if payload.get("schema") != PORTFOLIO_SCHEMA:
        raise TextNamedPKChallengerError("row portfolio schema drifted")
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if supplied != digest(unsigned):
        raise TextNamedPKChallengerError("row portfolio seal is invalid")
    verify_candidate(payload.get("candidate", {}))
    if (
        payload.get("row_count") != 10
        or payload.get("candidate_level_1_pass_count") != 10
        or payload.get("authorized_named_product_baseline_count") != 0
        or payload.get("completed_named_product_pk_count") != 0
        or payload.get("candidate_win_count") != 0
        or payload.get("four_a_quality_proven") is not False
        or payload.get("top1_claim_eligible") is not False
    ):
        raise TextNamedPKChallengerError("row portfolio truth boundary drifted")


__all__ = [
    "CANDIDATE_SCHEMA",
    "CONFIG_SCHEMA",
    "EXPECTED_PRODUCTS",
    "PORTFOLIO_SCHEMA",
    "TextNamedPKChallengerError",
    "compile_candidate",
    "compile_row_portfolio",
    "verify_candidate",
    "verify_row_portfolio",
]
