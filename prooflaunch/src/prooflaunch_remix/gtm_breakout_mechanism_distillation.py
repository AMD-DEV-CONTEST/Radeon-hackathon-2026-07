from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence


SCHEMA = "ProofLaunchGTMBreakoutMechanismDistillationV1"


class GTMBreakoutMechanismDistillationError(ValueError):
    pass


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def compile_breakout_mechanism_distillation(
    quality_seed: Mapping[str, Any],
    blueprints: Sequence[Mapping[str, Any]],
    *,
    compiled_at: str,
) -> dict[str, Any]:
    team_by_id = {team["team_id"]: team for team in quality_seed.get("teams", [])}
    if not compiled_at or not blueprints or not team_by_id:
        raise GTMBreakoutMechanismDistillationError("quality seed, blueprints, and compiled_at are required")
    normalized = []
    seen = set()
    for raw in blueprints:
        blueprint = dict(raw)
        blueprint_id = str(blueprint.get("blueprint_id", ""))
        if not blueprint_id or blueprint_id in seen:
            raise GTMBreakoutMechanismDistillationError(f"missing or duplicate blueprint id: {blueprint_id}")
        seen.add(blueprint_id)
        source_ids = blueprint.get("source_team_ids", [])
        if not source_ids or any(team_id not in team_by_id for team_id in source_ids):
            raise GTMBreakoutMechanismDistillationError(f"unknown source team: {blueprint_id}")
        if any(team_by_id[team_id]["promotion_status"] != "mechanism_distillation_ready" for team_id in source_ids):
            raise GTMBreakoutMechanismDistillationError(f"outcome-only team entered mechanism distillation: {blueprint_id}")
        required = {
            "strategic_question",
            "transfer_pattern",
            "b2b_application",
            "b2c_application",
            "resource_fit",
            "platform_adaptations",
            "outcome_chain",
            "minimum_instrumentation",
            "kill_rules",
            "evidence_limit",
        }
        if any(not blueprint.get(key) for key in required):
            raise GTMBreakoutMechanismDistillationError(f"incomplete blueprint: {blueprint_id}")
        blueprint["source_team_names"] = [team_by_id[team_id]["team_name"] for team_id in source_ids]
        blueprint["copy_reuse_allowed"] = False
        blueprint["automatic_publish_or_spend_allowed"] = False
        normalized.append(blueprint)
    normalized.sort(key=lambda item: item["blueprint_id"])
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "compiled_at": compiled_at,
        "quality_seed_sha256": quality_seed.get("content_sha256"),
        "blueprint_count": len(normalized),
        "blueprints": normalized,
        "top_level_control_loop": [
            "diagnose business model, category, lifecycle stage, buyer or user tension, geography, and available resources",
            "establish a comparable baseline for qualified attention, activation, retention, monetization, and resource cost",
            "select one primary mechanism and at most one reinforcing mechanism; do not average every playbook together",
            "create a product- or evidence-native proof object before producing platform copy",
            "translate the proof object into platform-native hooks, formats, interaction mechanics, and owned-audience capture",
            "run the smallest truthful test that can reach a qualified audience without unauthorized publishing or spend",
            "measure the full attention-to-revenue chain and separate organic, paid, partner, affiliate, creator, and owned contributions",
            "retain only human-approved learning; stop, revise, or scale according to precommitted kill and promotion rules",
        ],
        "budget_policy": {
            "zero_budget_is_required": False,
            "cold_start_window_months": [6, 12],
            "priority": "capital efficiency and mechanism repeatability at a comparable stage",
            "accepted_paths": [
                "zero-paid proof and community compounding",
                "low-budget product-led or founder-led distribution",
                "mixed-budget amplification after organic proof",
                "capital-efficient sales-assisted expansion with explicit unit economics",
            ],
        },
        "truth_boundary": (
            "These are abstract, testable mechanism hypotheses distilled from evidence-labeled cases. They are not guarantees, "
            "campaign copy, or instructions to impersonate a source brand. A mechanism must re-earn promotion in the target "
            "industry, stage, market, and platform using the full outcome chain."
        ),
    }
    payload["content_sha256"] = _digest(payload)
    return payload


def verify_breakout_mechanism_distillation(payload: Mapping[str, Any]) -> None:
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if payload.get("schema") != SCHEMA or supplied != _digest(unsigned):
        raise GTMBreakoutMechanismDistillationError("mechanism distillation digest or schema is invalid")
    if payload.get("blueprint_count") != len(payload.get("blueprints", [])):
        raise GTMBreakoutMechanismDistillationError("mechanism blueprint count drifted")
    if any(blueprint.get("copy_reuse_allowed") is not False for blueprint in payload.get("blueprints", [])):
        raise GTMBreakoutMechanismDistillationError("source copy reuse was enabled")
    if any(blueprint.get("automatic_publish_or_spend_allowed") is not False for blueprint in payload.get("blueprints", [])):
        raise GTMBreakoutMechanismDistillationError("automatic external action was enabled")
