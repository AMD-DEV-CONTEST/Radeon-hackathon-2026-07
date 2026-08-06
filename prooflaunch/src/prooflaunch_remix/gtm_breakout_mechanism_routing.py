from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence


SCHEMA = "ProofLaunchGTMBreakoutMechanismRoutingV1"


class GTMBreakoutMechanismRoutingError(ValueError):
    pass


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _unique(values: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(values))


def compile_breakout_mechanism_routing(
    sampling_standard: Mapping[str, Any],
    distillation: Mapping[str, Any],
    *,
    vertical_blueprints: Mapping[str, Sequence[str]],
    lifecycle_blueprints: Mapping[str, Sequence[str]],
    platform_blueprints: Mapping[str, Sequence[str]],
    compiled_at: str,
) -> dict[str, Any]:
    valid_blueprints = {item["blueprint_id"] for item in distillation.get("blueprints", [])}
    source_by_blueprint = {item["blueprint_id"]: item["source_team_ids"] for item in distillation.get("blueprints", [])}
    if not valid_blueprints or not compiled_at:
        raise GTMBreakoutMechanismRoutingError("distillation and compiled_at are required")
    routed_ids = {
        blueprint_id
        for mapping in (vertical_blueprints, lifecycle_blueprints, platform_blueprints)
        for values in mapping.values()
        for blueprint_id in values
    }
    if not routed_ids.issubset(valid_blueprints):
        raise GTMBreakoutMechanismRoutingError("routing references an unknown blueprint")

    cell_routes = []
    for cell in sampling_standard.get("segment_market_cells", []):
        vertical = cell["vertical"]
        if vertical not in vertical_blueprints:
            raise GTMBreakoutMechanismRoutingError(f"unmapped vertical: {vertical}")
        lifecycle_routes = {}
        source_teams = []
        for lifecycle in sampling_standard["lifecycle_states"]:
            selected = _unique([*lifecycle_blueprints[lifecycle], *vertical_blueprints[vertical]])[:7]
            lifecycle_routes[lifecycle] = selected
            for blueprint_id in selected:
                source_teams.extend(source_by_blueprint[blueprint_id])
        cell_routes.append(
            {
                "cell_id": cell["cell_id"],
                "business_model": cell["business_model"],
                "market": cell["market"],
                "vertical": vertical,
                "required_subverticals": cell["required_subverticals"],
                "lifecycle_blueprint_routes": lifecycle_routes,
                "bounded_source_team_ids": _unique(source_teams),
                "resource_routing": {
                    "zero_paid": "prefer product, proof, expertise, community, owned-audience, or targeted-earned loops",
                    "low_budget": "add concentrated founder, expert, creator, partner, or live distribution with labor cost measured",
                    "mixed_budget": "amplify only proven organic or sales-assisted mechanisms with incrementality and retention gates",
                    "mature_scaled": "use adaptive pods, retention, category expansion, and portfolio economics; do not transfer scale advantages to cold start",
                },
                "selection_rule": "choose one primary and at most one reinforcing blueprint after diagnosing stage, tension, proof, platform, and resources",
            }
        )

    platform_routes = []
    contract_by_platform = {item["platform"]: item for item in sampling_standard.get("platform_contracts", [])}
    for lane in sampling_standard.get("platform_market_lanes", []):
        platform = lane["platform"]
        if platform not in platform_blueprints or platform not in contract_by_platform:
            raise GTMBreakoutMechanismRoutingError(f"unmapped platform: {platform}")
        selected = list(platform_blueprints[platform])
        platform_routes.append(
            {
                "lane_id": lane["lane_id"],
                "business_model": lane["business_model"],
                "market": lane["market"],
                "platform": platform,
                "blueprint_routes": selected,
                "access_contract": contract_by_platform[platform]["access"],
                "minimum_recent_items": lane["minimum_recent_items"],
                "minimum_distinct_sources": lane["minimum_distinct_sources"],
                "required_measurement": ["qualified attention", "owned or activation event", "retention or pipeline", "conversion or revenue", "resource cost"],
                "source_copy_reuse_allowed": False,
            }
        )

    if len(cell_routes) != 140 or len(platform_routes) != 168:
        raise GTMBreakoutMechanismRoutingError("expected exactly 140 segment-market cells and 168 platform-market lanes")
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "compiled_at": compiled_at,
        "sampling_standard_sha256": sampling_standard.get("content_sha256"),
        "distillation_sha256": distillation.get("content_sha256"),
        "segment_market_route_count": len(cell_routes),
        "platform_market_route_count": len(platform_routes),
        "segment_market_routes": cell_routes,
        "platform_market_routes": platform_routes,
        "truth_boundary": (
            "Routing narrows strategy search; it does not predict a breakout. Every selected mechanism must be regenerated from "
            "the target company's evidence and revalidated on the target platform, market, stage, and resource tier."
        ),
    }
    payload["content_sha256"] = _digest(payload)
    return payload


def verify_breakout_mechanism_routing(payload: Mapping[str, Any]) -> None:
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if payload.get("schema") != SCHEMA or supplied != _digest(unsigned):
        raise GTMBreakoutMechanismRoutingError("mechanism routing digest or schema is invalid")
    if payload.get("segment_market_route_count") != 140 or payload.get("platform_market_route_count") != 168:
        raise GTMBreakoutMechanismRoutingError("mechanism routing coverage drifted")
    if any(route.get("source_copy_reuse_allowed") is not False for route in payload.get("platform_market_routes", [])):
        raise GTMBreakoutMechanismRoutingError("source copy reuse was enabled")
