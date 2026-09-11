"""Auditable curriculum, holdout, and promotion gates for mobile SmolVLA."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import random
from typing import Any, Iterable

from .metrics import wilson_interval


PROFILE_RANGES: dict[str, dict[str, tuple[float, float] | tuple[tuple[float, float], ...]]] = {
    "small_carton": {
        "size_m": ((0.17, 0.225), (0.105, 0.135), (0.16, 0.205)),
        "mass_kg": (0.25, 0.58),
        "friction": (0.40, 0.95),
    },
    "flat_mailer": {
        "size_m": ((0.20, 0.25), (0.13, 0.17), (0.06, 0.10)),
        "mass_kg": (0.18, 0.40),
        "friction": (0.30, 0.90),
    },
    "electronics_box": {
        "size_m": ((0.15, 0.20), (0.09, 0.12), (0.10, 0.15)),
        "mass_kg": (0.22, 0.45),
        "friction": (0.25, 0.75),
    },
    "medium_carton": {
        "size_m": ((0.22, 0.26), (0.13, 0.17), (0.17, 0.215)),
        "mass_kg": (0.50, 0.76),
        "friction": (0.40, 1.00),
    },
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_replay_from_campaign_audit(audit: dict[str, Any]) -> dict[str, Any]:
    """Turn failed audit runs into bridges while consuming the old holdout."""

    runs = audit.get("runs")
    if not isinstance(runs, list) or not runs:
        raise ValueError("campaign audit must contain non-empty runs")
    items = []
    for run in runs:
        if not isinstance(run, dict) or bool(run.get("success")):
            continue
        parameters = dict(run.get("parameters") or {})
        episode_id = str(run.get("episode_id") or parameters.get("episode_id") or "")
        if not episode_id:
            raise ValueError("failed audit run has no episode_id")
        mass_kg = float(parameters.get("mass_kg") or 0.0)
        if mass_kg <= 0.0:
            raise ValueError(f"failed audit run has invalid mass: {episode_id}")
        failure_stage = str(run.get("failure_stage") or "unclassified")
        suction = run.get("suction") or {}
        bridge = {
            **parameters,
            "episode_id": f"bridge-{episode_id}",
            "mass_kg": round(max(0.05, mass_kg * 0.90), 4),
            "source_failure_episode_id": episode_id,
        }
        items.append(
            {
                "episode_id": episode_id,
                "profile": str(run.get("profile") or parameters.get("profile") or "unknown"),
                "failure_stage": failure_stage,
                "priority": _failure_priority(failure_stage, mass_kg),
                "max_contact_force_n": float(suction.get("max_contact_force_n") or 0.0),
                "parameters": parameters,
                "curriculum_bridge": bridge,
            }
        )
    items.sort(key=lambda item: (-float(item["priority"]), str(item["episode_id"])))
    return {
        "schema_version": 1,
        "protocol": "mobile-failure-replay-curriculum-v2",
        "source_campaign_consumed_for_development": True,
        "source_collection_summary_sha256": audit.get("collection_summary_sha256"),
        "items": items,
        "claim_boundary": (
            "the source campaign is development evidence after failure inspection and "
            "must never be reused as a holdout for the resulting checkpoint"
        ),
    }


def build_curriculum_config(
    base_config: dict[str, Any], replay: dict[str, Any], *, cycle_id: str
) -> dict[str, Any]:
    base_episodes = base_config.get("episodes")
    if not isinstance(base_episodes, list) or not base_episodes:
        raise ValueError("base training config must contain episodes")
    episodes = [dict(item) for item in base_episodes]
    existing_ids = {str(item.get("episode_id")) for item in episodes}
    for item in replay.get("items", ()):
        bridge = dict(item["curriculum_bridge"])
        bridge_id = str(bridge.get("episode_id") or "")
        if not bridge_id or bridge_id in existing_ids:
            raise ValueError(f"bridge episode_id must be unique: {bridge_id!r}")
        existing_ids.add(bridge_id)
        episodes.append(bridge)
    if len(episodes) == len(base_episodes):
        raise ValueError("failure replay produced no curriculum bridge")
    return {
        "schema_version": 1,
        "collection_id": f"mobile-suction-{cycle_id}-curriculum",
        "split": "training_successes_only",
        "source_collection_id": base_config.get("collection_id"),
        "episodes": episodes,
    }


def build_frozen_holdout_config(
    *, cycle_id: str, trials: int = 100, seed: int = 20260728
) -> dict[str, Any]:
    if trials < 100:
        raise ValueError("promotion holdout must contain at least 100 trials")
    return build_randomized_mobile_campaign_config(
        campaign_id=f"mobile-suction-{cycle_id}-holdout",
        episode_prefix=f"{cycle_id}-holdout",
        split="frozen_before_training_do_not_train",
        trials=trials,
        seed=seed,
    )


def build_randomized_mobile_campaign_config(
    *,
    campaign_id: str,
    episode_prefix: str,
    split: str,
    trials: int,
    seed: int,
) -> dict[str, Any]:
    """Freeze a balanced parameter campaign without reading task outcomes."""

    if not campaign_id.strip() or not episode_prefix.strip() or not split.strip():
        raise ValueError("campaign identifiers and split must be non-empty")
    if trials < len(PROFILE_RANGES) or trials % len(PROFILE_RANGES) != 0:
        raise ValueError("trials must be a positive multiple of the profile count")
    rng = random.Random(seed)
    profiles = tuple(PROFILE_RANGES)
    episodes = []
    for index in range(trials):
        profile = profiles[index % len(profiles)]
        ranges = PROFILE_RANGES[profile]
        size_ranges = ranges["size_m"]
        assert isinstance(size_ranges, tuple)
        size_m = [round(rng.uniform(*axis), 5) for axis in size_ranges]
        mass_range = ranges["mass_kg"]
        friction_range = ranges["friction"]
        assert isinstance(mass_range, tuple) and isinstance(friction_range, tuple)
        episodes.append(
            {
                "episode_id": f"{episode_prefix}-{index:03d}",
                "profile": profile,
                "size_m": size_m,
                "mass_kg": round(rng.uniform(*mass_range), 4),
                "friction": round(rng.uniform(*friction_range), 4),
                "offset_m": [round(rng.uniform(-0.012, 0.012), 5) for _ in range(2)],
            }
        )
    return {
        "schema_version": 1,
        "collection_id": campaign_id,
        "split": split,
        "seed": seed,
        "episodes": episodes,
    }


def validate_split_isolation(
    training_config: dict[str, Any], holdout_config: dict[str, Any]
) -> dict[str, Any]:
    training = list(training_config.get("episodes") or ())
    holdout = list(holdout_config.get("episodes") or ())
    if len(holdout) < 100:
        raise ValueError("frozen holdout must contain at least 100 episodes")
    train_ids = {str(item.get("episode_id")) for item in training}
    holdout_ids = {str(item.get("episode_id")) for item in holdout}
    if len(train_ids) != len(training) or len(holdout_ids) != len(holdout):
        raise ValueError("training and holdout episode ids must be unique")
    overlap = sorted(train_ids & holdout_ids)
    if overlap:
        raise ValueError(f"training/holdout episode id overlap: {overlap[:3]}")
    train_signatures = {_episode_signature(item) for item in training}
    holdout_signatures = {_episode_signature(item) for item in holdout}
    parameter_overlap = train_signatures & holdout_signatures
    if parameter_overlap:
        raise ValueError("training and holdout contain identical physical parameters")
    profile_counts = {
        profile: sum(str(item.get("profile")) == profile for item in holdout)
        for profile in PROFILE_RANGES
    }
    if any(count == 0 for count in profile_counts.values()):
        raise ValueError("frozen holdout must cover every supported mobile profile")
    return {
        "status": "passed",
        "training_episodes": len(training),
        "holdout_episodes": len(holdout),
        "profile_counts": profile_counts,
        "episode_id_overlap": 0,
        "physical_parameter_overlap": 0,
    }


def promotion_gate(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    *,
    target_success_rate: float = 0.80,
    noninferiority_margin: float = 0.05,
) -> dict[str, Any]:
    """Require task, safety, VLA actuation, and single-Radeon evidence."""

    for name, audit in (("baseline", baseline), ("candidate", candidate)):
        if audit.get("status") != "passed":
            raise ValueError(f"{name} campaign audit did not pass")
        if int(audit.get("trials") or 0) < 100:
            raise ValueError(f"{name} campaign must contain at least 100 trials")
    trials = int(candidate["trials"])
    successes = int(candidate["successes"])
    baseline_rate = float(baseline["success_rate"])
    candidate_rate = float(candidate["success_rate"])
    candidate_wilson = wilson_interval(successes, trials)
    baseline_wilson = tuple(float(value) for value in baseline["wilson_95"])
    checks = {
        "target_success_rate": candidate_rate >= target_success_rate,
        "point_estimate_noninferiority": candidate_rate + noninferiority_margin >= baseline_rate,
        "wilson_noninferiority": candidate_wilson[0] + noninferiority_margin >= baseline_wilson[0],
        "zero_force_violations": int(candidate.get("force_violation_count") or 0) == 0,
        "vla_actuated_every_run": int(candidate.get("vla_actuated_run_count") or 0) == trials,
        "single_radeon_rocm_every_run": int(
            candidate.get("single_radeon_rocm_run_count") or 0
        ) == trials,
    }
    return {
        "schema_version": 1,
        "protocol": "mobile-smolvla-promotion-gate-v1",
        "promoted": all(checks.values()),
        "checks": checks,
        "baseline": {
            "successes": int(baseline["successes"]),
            "trials": int(baseline["trials"]),
            "success_rate": baseline_rate,
            "wilson_95": list(baseline_wilson),
        },
        "candidate": {
            "successes": successes,
            "trials": trials,
            "success_rate": candidate_rate,
            "wilson_95": list(candidate_wilson),
            "force_violation_count": int(candidate.get("force_violation_count") or 0),
        },
        "claim_boundary": (
            "promotion changes only an auditable checkpoint pointer; active episode "
            "weights are never modified"
        ),
    }


def validate_paired_campaigns(
    baseline: dict[str, Any], candidate: dict[str, Any]
) -> dict[str, Any]:
    """Prove that baseline and candidate used the same ordered physical trials."""

    baseline_runs = list(baseline.get("runs") or ())
    candidate_runs = list(candidate.get("runs") or ())
    if not baseline_runs or not candidate_runs:
        raise ValueError("paired campaign audits must contain runs")
    baseline_signatures = [_run_physical_signature(run) for run in baseline_runs]
    candidate_signatures = [_run_physical_signature(run) for run in candidate_runs]
    if baseline_signatures != candidate_signatures:
        raise ValueError("baseline and candidate physical parameter sequences differ")
    if len(set(candidate_signatures)) != len(candidate_signatures):
        raise ValueError("paired campaign contains duplicate physical signatures")
    return {
        "status": "passed",
        "physical_parameter_sequences_equal": True,
        "paired_trials": len(candidate_signatures),
        "unique_physical_signatures": len(set(candidate_signatures)),
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _failure_priority(stage: str, mass_kg: float) -> float:
    stage_priority = {
        "force_safety_abort": 6.0,
        "lift_success": 4.5,
        "placement_success": 3.5,
        "release_success": 3.0,
    }.get(stage, 2.0)
    return stage_priority + min(1.0, max(0.0, mass_kg - 0.40) / 0.25)


def _episode_signature(item: dict[str, Any]) -> tuple[Any, ...]:
    values: Iterable[Any] = (
        str(item.get("profile")),
        *(round(float(value), 6) for value in item.get("size_m", ())),
        round(float(item.get("mass_kg") or math.nan), 6),
        round(float(item.get("friction") or math.nan), 6),
        *(round(float(value), 6) for value in item.get("offset_m", ())),
    )
    return tuple(values)


def _run_physical_signature(run: dict[str, Any]) -> tuple[Any, ...]:
    parameters = run.get("parameters") or {}
    return _episode_signature(
        {
            "profile": run.get("profile") or parameters.get("profile"),
            "size_m": parameters.get("size_m", ()),
            "mass_kg": parameters.get("mass_kg"),
            "friction": parameters.get("friction"),
            "offset_m": parameters.get("offset_m", ()),
        }
    )
