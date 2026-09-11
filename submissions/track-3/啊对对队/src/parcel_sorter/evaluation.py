from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
import statistics
from typing import Any, Iterable

from .metrics import wilson_interval


@dataclass(frozen=True)
class CheckpointAggregate:
    checkpoint: str
    episode_indices: tuple[int, ...]
    evaluation_manifest_sha256: str
    successes: int
    success_rate: float
    success_rate_ci95_low: float
    success_rate_ci95_high: float
    macro_profile_success_rate: float
    profile_summaries: dict[str, dict[str, float | int]]
    first_attempt_success_rate: float
    recovery_success_rate: float
    drop_rate: float
    safety_threshold_n: float
    safety_violations: int
    safety_violation_rate: float
    mean_duration_seconds: float
    successful_parcels_per_hour: float
    mean_inference_latency_ms: float
    p95_inference_latency_ms: float
    max_contact_force_n: float
    source_files: tuple[str, ...]

    @property
    def episodes(self) -> int:
        return len(self.episode_indices)

    def to_dict(self) -> dict[str, Any]:
        return {"episodes": self.episodes, **asdict(self)}


def aggregate_checkpoint_evaluations(
    records: Iterable[tuple[str, dict[str, Any]]],
    *,
    require_matched_episodes: bool = True,
) -> list[CheckpointAggregate]:
    grouped: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for source, payload in records:
        checkpoint = str(payload.get("checkpoint", "")).strip()
        episodes = payload.get("episodes")
        if not checkpoint or not isinstance(episodes, list):
            raise ValueError(f"{source} is not an ACT evaluation summary")
        grouped.setdefault(checkpoint, []).append((source, payload))

    aggregates = [
        _aggregate_checkpoint(checkpoint, payloads)
        for checkpoint, payloads in grouped.items()
    ]
    if require_matched_episodes and len(aggregates) > 1:
        expected = set(aggregates[0].episode_indices)
        for aggregate in aggregates[1:]:
            actual = set(aggregate.episode_indices)
            if actual != expected:
                missing = sorted(expected - actual)
                extra = sorted(actual - expected)
                raise ValueError(
                    "checkpoint evaluations must use identical episode sets; "
                    f"{aggregate.checkpoint} missing={missing} extra={extra}"
                )
        thresholds = {aggregate.safety_threshold_n for aggregate in aggregates}
        if len(thresholds) != 1:
            raise ValueError(
                "checkpoint evaluations must use the same contact-force safety threshold"
            )
        fingerprints = {
            aggregate.evaluation_manifest_sha256 for aggregate in aggregates
        }
        if len(fingerprints) != 1:
            raise ValueError(
                "checkpoint evaluations must use identical randomized episode samples"
            )
    return sorted(
        aggregates,
        key=lambda item: (
            item.safety_violation_rate,
            -item.macro_profile_success_rate,
            -item.success_rate,
            item.drop_rate,
            item.p95_inference_latency_ms,
            item.max_contact_force_n,
            item.checkpoint,
        ),
    )


def _aggregate_checkpoint(
    checkpoint: str,
    payloads: list[tuple[str, dict[str, Any]]],
) -> CheckpointAggregate:
    seen: set[int] = set()
    episodes: list[dict[str, Any]] = []
    sources: list[str] = []
    safety_thresholds: set[float] = set()

    for source, payload in payloads:
        sources.append(source)
        safety_thresholds.add(_safety_threshold_n(payload))
        for episode in payload["episodes"]:
            episode_index = int(episode["episode_index"])
            if episode_index in seen:
                raise ValueError(
                    f"checkpoint {checkpoint} repeats episode {episode_index} in {source}"
                )
            seen.add(episode_index)
            episodes.append(episode)

    if not episodes:
        raise ValueError(f"checkpoint {checkpoint} has no episodes")
    if len(safety_thresholds) != 1:
        raise ValueError(
            f"checkpoint {checkpoint} was evaluated with multiple contact-force thresholds"
        )

    results = [episode["result"] for episode in episodes]
    count = len(results)
    successes = sum(bool(result["success"]) for result in results)
    success_ci_low, success_ci_high = wilson_interval(successes, count)
    first_attempt = sum(
        bool(result["success"]) and int(result["retries"]) == 0
        for result in results
    )
    retry_results = [result for result in results if int(result["retries"]) > 0]
    recovered = sum(bool(result["success"]) for result in retry_results)
    dropped = sum(bool(result.get("dropped", False)) for result in results)
    duration = sum(float(result["duration_seconds"]) for result in results)
    latencies = sorted(
        float(latency)
        for result in results
        for latency in result.get("inference_latency_ms", ())
    )
    p95_index = max(0, math.ceil(0.95 * len(latencies)) - 1) if latencies else 0
    safety_threshold_n = next(iter(safety_thresholds))
    safety_violations = sum(
        float(result.get("max_contact_force_n", 0.0)) > safety_threshold_n
        for result in results
    )
    profile_summaries = _profile_summaries(episodes)
    evaluation_manifest_sha256 = _evaluation_manifest_sha256(episodes)

    return CheckpointAggregate(
        checkpoint=checkpoint,
        episode_indices=tuple(sorted(seen)),
        evaluation_manifest_sha256=evaluation_manifest_sha256,
        successes=successes,
        success_rate=successes / count,
        success_rate_ci95_low=success_ci_low,
        success_rate_ci95_high=success_ci_high,
        macro_profile_success_rate=statistics.fmean(
            float(summary["success_rate"])
            for summary in profile_summaries.values()
        ),
        profile_summaries=profile_summaries,
        first_attempt_success_rate=first_attempt / count,
        recovery_success_rate=(
            recovered / len(retry_results) if retry_results else 0.0
        ),
        drop_rate=dropped / count,
        safety_threshold_n=safety_threshold_n,
        safety_violations=safety_violations,
        safety_violation_rate=safety_violations / count,
        mean_duration_seconds=duration / count,
        successful_parcels_per_hour=(successes / duration * 3600 if duration else 0.0),
        mean_inference_latency_ms=(statistics.fmean(latencies) if latencies else 0.0),
        p95_inference_latency_ms=(latencies[p95_index] if latencies else 0.0),
        max_contact_force_n=max(
            float(result.get("max_contact_force_n", 0.0)) for result in results
        ),
        source_files=tuple(sorted(sources)),
    )


def _profile_summaries(
    episodes: list[dict[str, Any]],
) -> dict[str, dict[str, float | int]]:
    counts: dict[str, list[bool]] = {}
    for episode in episodes:
        sample = episode.get("sample")
        profile_id = (
            str(sample.get("profile_id", "unknown"))
            if isinstance(sample, dict)
            else str(episode.get("profile_id", "unknown"))
        )
        counts.setdefault(profile_id, []).append(bool(episode["result"]["success"]))

    summaries: dict[str, dict[str, float | int]] = {}
    for profile_id, outcomes in sorted(counts.items()):
        trials = len(outcomes)
        successes = sum(outcomes)
        low, high = wilson_interval(successes, trials)
        summaries[profile_id] = {
            "episodes": trials,
            "successes": successes,
            "success_rate": successes / trials,
            "success_rate_ci95_low": low,
            "success_rate_ci95_high": high,
        }
    return summaries


def _safety_threshold_n(payload: dict[str, Any]) -> float:
    config = payload.get("config")
    if not isinstance(config, dict):
        return 35.0
    task = config.get("task")
    if not isinstance(task, dict):
        return 35.0
    threshold = float(task.get("max_contact_force_n", 35.0))
    if not math.isfinite(threshold) or threshold <= 0:
        raise ValueError("contact-force safety threshold must be finite and positive")
    return threshold


def _evaluation_manifest_sha256(episodes: list[dict[str, Any]]) -> str:
    manifest = [
        {
            "episode_index": int(episode["episode_index"]),
            "sample": episode.get("sample"),
        }
        for episode in sorted(episodes, key=lambda item: int(item["episode_index"]))
    ]
    encoded = json.dumps(
        manifest,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
