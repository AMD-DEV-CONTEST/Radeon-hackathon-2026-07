"""Frozen held-out observation-panel validation for PI0.5."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable

from .mobile_grasp_routing import route_mobile_grasp
from .mobile_pi05_contract import PI05_GRASP_MODES


def physical_context_signature(item: dict[str, Any]) -> tuple[Any, ...]:
    return (
        str(item.get("shape")),
        str(item.get("orientation_mode")),
        *(round(float(value), 6) for value in item.get("size_m", ())),
        round(float(item.get("mass_kg", math.nan)), 6),
    )


def validate_pi05_observation_panel(
    panel: dict[str, Any],
    catalog_profiles: dict[str, dict[str, Any]],
    training_signatures: Iterable[tuple[Any, ...]],
) -> dict[str, Any]:
    episodes = list(panel.get("episodes") or ())
    minimum = int(panel.get("minimum_observations_per_mode") or 0)
    if "do_not_train" not in str(panel.get("split")):
        raise ValueError("held-out observation panel must be marked do_not_train")
    if minimum < 1 or len(episodes) < minimum * len(PI05_GRASP_MODES):
        raise ValueError("held-out panel has insufficient declared mode coverage")
    ids = [str(item.get("episode_id") or "") for item in episodes]
    if any(not value for value in ids) or len(ids) != len(set(ids)):
        raise ValueError("held-out observation episode ids must be non-empty and unique")
    signatures = [physical_context_signature(item) for item in episodes]
    if len(signatures) != len(set(signatures)):
        raise ValueError("held-out observation physical contexts must be unique")
    overlap = set(signatures) & set(training_signatures)
    if overlap:
        raise ValueError("held-out observation panel overlaps a training physical context")
    mode_counts: Counter[str] = Counter()
    profile_counts: Counter[str] = Counter()
    for item in episodes:
        profile_id = str(item.get("profile"))
        if profile_id not in catalog_profiles:
            raise ValueError(f"held-out profile is absent from catalog: {profile_id}")
        profile = catalog_profiles[profile_id]
        size = tuple(float(value) for value in item.get("size_m", ()))
        if len(size) != 3:
            raise ValueError(f"held-out profile has invalid size: {profile_id}")
        if str(item.get("shape")) != str(profile["shape"]) or str(
            item.get("orientation_mode")
        ) != str(profile["orientation_mode"]):
            raise ValueError(f"held-out shape/orientation mismatch: {profile_id}")
        if str(item.get("handling_class")) != str(profile["handling_class"]):
            raise ValueError(f"held-out handling class mismatch: {profile_id}")
        for value, low, high in zip(
            size,
            profile["dimensions_min_m"],
            profile["dimensions_max_m"],
            strict=True,
        ):
            if not float(low) <= value <= float(high):
                raise ValueError(f"held-out size is outside catalog: {profile_id}")
        mass = float(item.get("mass_kg", math.nan))
        if not float(profile["mass_kg_min"]) <= mass <= float(profile["mass_kg_max"]):
            raise ValueError(f"held-out mass is outside catalog: {profile_id}")
        expected = route_mobile_grasp(
            shape=str(profile["shape"]),
            orientation_mode=str(profile["orientation_mode"]),
            size_m=size,
            mass_kg=mass,
            handling_class=str(profile["handling_class"]),
        ).mode
        declared = str(item.get("grasp_mode"))
        if declared != expected:
            raise ValueError(
                f"held-out hidden mode label mismatch: {profile_id}: {declared} != {expected}"
            )
        task_text = str(item.get("task_text") or "").lower()
        if any(mode.lower() in task_text for mode in PI05_GRASP_MODES):
            raise ValueError(f"held-out task text leaks mode label: {profile_id}")
        mode_counts[declared] += 1
        profile_counts[profile_id] += 1
    if any(mode_counts[mode] < minimum for mode in PI05_GRASP_MODES):
        raise ValueError("held-out observation panel lacks balanced mode coverage")
    canonical = json.dumps(
        panel, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return {
        "status": "passed",
        "protocol": "pi05-heldout-observation-panel-audit-v1",
        "panel_sha256": hashlib.sha256(canonical).hexdigest(),
        "episodes": len(episodes),
        "mode_counts": dict(mode_counts),
        "profile_counts": dict(profile_counts),
        "training_physical_context_overlap": 0,
        "unique_physical_contexts": len(set(signatures)),
        "claim_boundary": (
            "configuration and training-context isolation audit only; images must be "
            "collected after freeze and only first pregrasp observations may be probed"
        ),
    }


def load_catalog_profiles(path: str | Path) -> dict[str, dict[str, Any]]:
    import tomllib

    payload = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    return {
        str(item["profile_id"]): dict(item)
        for item in payload.get("parcel_profiles", ())
    }
