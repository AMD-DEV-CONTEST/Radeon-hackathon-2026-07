#!/usr/bin/env python3
"""Build the deterministic 21-profile, five-repeat mobile evaluation campaign."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import tomllib
from typing import Any

from parcel_sorter.mobile_grasp_routing import route_mobile_grasp


QUANTILES = (0.1, 0.3, 0.5, 0.7, 0.9)
OFFSETS_M = ((0.0, 0.0), (0.01, 0.0), (-0.01, 0.0), (0.0, 0.01), (0.0, -0.01))
YAWS_RAD = (0.0, -0.12, 0.12, -0.25, 0.25)


def _lerp(low: float, high: float, quantile: float) -> float:
    return float(low) + (float(high) - float(low)) * quantile


def build_campaign(catalog_path: Path) -> dict[str, Any]:
    catalog = tomllib.loads(catalog_path.read_text(encoding="utf-8"))
    profiles = list(catalog.get("parcel_profiles", ()))
    episodes: list[dict[str, Any]] = []
    for profile in profiles:
        shape = str(profile["shape"])
        orientation = str(profile["orientation_mode"])
        for repeat, (quantile, offset, yaw) in enumerate(
            zip(QUANTILES, OFFSETS_M, YAWS_RAD, strict=True), start=1
        ):
            size = [
                _lerp(low, high, quantile)
                for low, high in zip(
                    profile["dimensions_min_m"],
                    profile["dimensions_max_m"],
                    strict=True,
                )
            ]
            if shape == "cylinder":
                diameter_indices = (0, 1) if orientation == "upright" else (1, 2)
                diameter = sum(size[index] for index in diameter_indices) / 2.0
                for index in diameter_indices:
                    size[index] = diameter
            mass_kg = _lerp(profile["mass_kg_min"], profile["mass_kg_max"], quantile)
            handling_class = str(profile["handling_class"])
            route = route_mobile_grasp(
                shape=shape,
                orientation_mode=orientation,
                size_m=size,
                mass_kg=mass_kg,
                handling_class=handling_class,
            )
            episodes.append(
                {
                    "episode_id": f"{profile['profile_id']}-r{repeat}",
                    "profile": profile["profile_id"],
                    "shape": shape,
                    "orientation_mode": orientation,
                    "yaw_rad": yaw,
                    "handling_class": handling_class,
                    "grasp_mode": route.mode,
                    "minimum_sealed_cups": route.minimum_sealed_cups,
                    "cooperative_cradle": route.cooperative_cradle,
                    "grasp_route_reason": route.reason,
                    "size_m": size,
                    "mass_kg": mass_kg,
                    "friction": _lerp(
                        profile["friction_min"], profile["friction_max"], quantile
                    ),
                    "offset_m": list(offset),
                    "task_text": (
                        f"Pick and transport the {profile['profile_id']} parcel to the "
                        "marked destination using physical contact."
                    ),
                }
            )
    return {
        "schema_version": 1,
        "collection_id": "catalog-v2-five-repeat-v1",
        "source_catalog": str(catalog_path),
        "sampling": {
            "repeats_per_profile": 5,
            "quantiles": list(QUANTILES),
            "offsets_m": [list(item) for item in OFFSETS_M],
            "yaw_rad": list(YAWS_RAD),
        },
        "episodes": episodes,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=Path("configs/catalog_v2.toml"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = build_campaign(args.catalog)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps({"profiles": len(payload["episodes"]) // 5, "episodes": len(payload["episodes"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
