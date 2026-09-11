"""Fail-closed self-improvement orchestration for simulated robot rollouts.

The module never mutates a production checkpoint. It creates a prioritized
replay manifest, keeps holdout episodes immutable, and emits a promotion
decision only after the candidate clears the same independent campaign.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
import json
from pathlib import Path
from typing import Any, Iterable

from .failure_analysis import diagnose_episode
from .metrics import wilson_interval


FAILURE_PRIORITY = {
    "force_safety_abort": 5.0,
    "parcel_drop": 4.0,
    "grasp_lost_during_lift": 3.5,
    "grasp_verification_failure": 3.0,
    "approach_timeout": 2.5,
    "placement_failure": 2.0,
    "post_lift_failure": 2.0,
    "unclassified_failure": 1.0,
}


@dataclass(frozen=True)
class ReplayItem:
    episode_index: int
    profile_id: str
    failure_mode: str
    priority: float
    reason: str
    max_contact_force_n: float
    source_summary: str


def build_failure_replay_manifest(
    summary: dict[str, Any],
    *,
    source_summary: str = "unknown",
    holdout_episode_ids: Iterable[int] = (),
    force_threshold_n: float = 35.0,
) -> dict[str, Any]:
    """Rank failed rollouts for the next fixed-budget improvement cycle."""

    holdout = {int(value) for value in holdout_episode_ids}
    episodes = summary.get("episodes")
    if not isinstance(episodes, list):
        raise ValueError("summary must contain an episodes list")
    diagnoses = [
        diagnose_episode(episode, force_threshold_n)
        for episode in episodes
        if isinstance(episode, dict)
    ]
    items = []
    for diagnosis in diagnoses:
        episode_index = int(diagnosis["episode_index"])
        if bool(diagnosis["success"]) or episode_index in holdout:
            continue
        mode = str(diagnosis["primary_failure_mode"])
        factor_bonus = 0.0
        if diagnosis.get("max_contact_force_n", 0.0) >= force_threshold_n * 0.8:
            factor_bonus += 0.5
        items.append(
            ReplayItem(
                episode_index=episode_index,
                profile_id=str(diagnosis["profile_id"]),
                failure_mode=mode,
                priority=FAILURE_PRIORITY.get(mode, 1.0) + factor_bonus,
                reason=str(diagnosis["terminal_reason"]),
                max_contact_force_n=float(diagnosis["max_contact_force_n"]),
                source_summary=source_summary,
            )
        )
    items.sort(key=lambda item: (-item.priority, item.episode_index))
    return {
        "schema_version": 1,
        "protocol": "failure-replay-self-improvement-v1",
        "holdout_episode_ids": sorted(holdout),
        "force_threshold_n": force_threshold_n,
        "items": [asdict(item) for item in items],
        "counts_by_failure_mode": {
            mode: sum(item.failure_mode == mode for item in items)
            for mode in sorted({item.failure_mode for item in items})
        },
    }


def write_failure_replay_manifest(
    summary_path: str | Path,
    output_path: str | Path,
    *,
    holdout_episode_ids: Iterable[int] = (),
    force_threshold_n: float = 35.0,
) -> Path:
    summary_path = Path(summary_path)
    output_path = Path(output_path)
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    manifest = build_failure_replay_manifest(
        summary,
        source_summary=str(summary_path),
        holdout_episode_ids=holdout_episode_ids,
        force_threshold_n=force_threshold_n,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return output_path


def promotion_gate(
    baseline_summary: dict[str, Any],
    candidate_summary: dict[str, Any],
    *,
    target_success_rate: float = 0.80,
    min_delta: float = 0.02,
) -> dict[str, Any]:
    """Return an auditable checkpoint promotion decision."""

    baseline = _success_stats(baseline_summary)
    candidate = _success_stats(candidate_summary)
    if not 0.0 < target_success_rate <= 1.0:
        raise ValueError("target_success_rate must be in (0, 1]")
    if min_delta < 0.0:
        raise ValueError("min_delta must be non-negative")
    delta = candidate["rate"] - baseline["rate"]
    promoted = (
        candidate["trials"] > 0
        and candidate["rate"] >= target_success_rate
        and delta >= min_delta
        and candidate["wilson_low"] >= baseline["wilson_low"]
    )
    return {
        "protocol": "checkpoint-promotion-gate-v1",
        "target_success_rate": target_success_rate,
        "min_delta": min_delta,
        "promoted": promoted,
        "baseline": baseline,
        "candidate": candidate,
        "reason": "candidate clears target and non-inferiority gate" if promoted else "candidate remains in quarantine",
    }


def _success_stats(summary: dict[str, Any]) -> dict[str, Any]:
    episodes = summary.get("episodes")
    if not isinstance(episodes, list):
        raise ValueError("summary must contain an episodes list")
    successes = sum(
        bool(episode.get("result", {}).get("success"))
        for episode in episodes
        if isinstance(episode, dict)
    )
    trials = len(episodes)
    low, high = wilson_interval(successes, trials)
    return {
        "successes": successes,
        "trials": trials,
        "rate": successes / trials if trials else 0.0,
        "wilson_low": low,
        "wilson_high": high,
    }
