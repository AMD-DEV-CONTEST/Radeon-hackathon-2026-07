"""Deterministic episode-evidence parsing and promotion summaries."""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from .contracts import ContractError


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SAFETY_FAILURES = {
    "collision_safety",
    "joint_limit_safety",
    "workspace_safety",
}


def load_episode_jsonl(path: str | Path) -> list[dict[str, Any]]:
    path = Path(path)
    episodes: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ContractError(f"cannot read episode file {path}: {exc}") from exc
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            episode = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ContractError(f"invalid JSON at {path}:{line_number}: {exc}") from exc
        if not isinstance(episode, dict):
            raise ContractError(f"episode at {path}:{line_number} must be an object")
        episodes.append(episode)
    if not episodes:
        raise ContractError(f"episode file is empty: {path}")
    return episodes


def validate_episodes(
    episodes: Iterable[dict[str, Any]],
    failure_taxonomy: Iterable[str],
    expected_seeds: Iterable[int] | None = None,
) -> list[dict[str, Any]]:
    episodes = list(episodes)
    allowed_failures = set(failure_taxonomy)
    seeds: list[int] = []
    protocol: str | None = None
    checkpoint_sha256: str | None = None
    for index, episode in enumerate(episodes):
        context = f"episode[{index}]"
        seed = episode.get("seed")
        if not isinstance(seed, int) or seed < 0:
            raise ContractError(f"{context}.seed must be a non-negative integer")
        seeds.append(seed)
        success = episode.get("success")
        if not isinstance(success, bool):
            raise ContractError(f"{context}.success must be boolean")
        steps = episode.get("policy_steps")
        if not isinstance(steps, int) or steps < 0:
            raise ContractError(f"{context}.policy_steps must be a non-negative integer")
        failure = episode.get("failure_stage")
        if success and failure is not None:
            raise ContractError(f"{context} is successful but has failure_stage")
        if not success and failure not in allowed_failures:
            raise ContractError(f"{context}.failure_stage is not in the frozen taxonomy")
        score = episode.get("graded_score")
        if not isinstance(score, (int, float)) or isinstance(score, bool) or not 0 <= score <= 1:
            raise ContractError(f"{context}.graded_score must be in [0, 1]")
        this_protocol = episode.get("protocol")
        if not isinstance(this_protocol, str) or not this_protocol:
            raise ContractError(f"{context}.protocol must be a non-empty string")
        if protocol is None:
            protocol = this_protocol
        elif protocol != this_protocol:
            raise ContractError("all episodes in one evidence file must use one protocol")
        this_hash = episode.get("checkpoint_sha256")
        if not isinstance(this_hash, str) or not _SHA256.fullmatch(this_hash):
            raise ContractError(f"{context}.checkpoint_sha256 must be a lowercase SHA-256")
        if checkpoint_sha256 is None:
            checkpoint_sha256 = this_hash
        elif checkpoint_sha256 != this_hash:
            raise ContractError("all episodes in one evidence file must use one checkpoint")
    if len(seeds) != len(set(seeds)):
        raise ContractError("episode seeds must be unique")
    if expected_seeds is not None and set(seeds) != set(expected_seeds):
        missing = sorted(set(expected_seeds) - set(seeds))
        extra = sorted(set(seeds) - set(expected_seeds))
        raise ContractError(f"episode seeds disagree with protocol; missing={missing}, extra={extra}")
    return episodes


def wilson_interval(successes: int, total: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if total <= 0:
        raise ContractError("Wilson interval requires at least one episode")
    proportion = successes / total
    denominator = 1 + z * z / total
    center = (proportion + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(
        proportion * (1 - proportion) / total + z * z / (4 * total * total)
    ) / denominator
    return max(0.0, center - margin), min(1.0, center + margin)


def summarize_episodes(episodes: Iterable[dict[str, Any]]) -> dict[str, Any]:
    episodes = list(episodes)
    if not episodes:
        raise ContractError("cannot summarize zero episodes")
    successes = sum(episode["success"] for episode in episodes)
    lower, upper = wilson_interval(successes, len(episodes))
    failures = Counter(
        episode["failure_stage"] for episode in episodes if episode["failure_stage"] is not None
    )
    safety_failures = sum(failures[name] for name in _SAFETY_FAILURES)
    return {
        "protocol": episodes[0]["protocol"],
        "checkpoint_sha256": episodes[0]["checkpoint_sha256"],
        "episodes": len(episodes),
        "successes": successes,
        "success_rate": successes / len(episodes),
        "success_rate_wilson_95": [lower, upper],
        "mean_graded_score": sum(float(episode["graded_score"]) for episode in episodes)
        / len(episodes),
        "safety_failures": safety_failures,
        "failure_counts": dict(sorted(failures.items())),
        "seeds": sorted(episode["seed"] for episode in episodes),
    }


def evaluate_promotion(summary: dict[str, Any], rule: dict[str, Any]) -> dict[str, Any]:
    checks: dict[str, bool] = {}
    if "minimum_success_rate" in rule:
        checks["minimum_success_rate"] = summary["success_rate"] >= rule["minimum_success_rate"]
    if "minimum_successes" in rule:
        checks["minimum_successes"] = summary["successes"] >= rule["minimum_successes"]
    if "required_episodes" in rule:
        checks["required_episodes"] = summary["episodes"] == rule["required_episodes"]
    if "maximum_safety_failures" in rule:
        checks["maximum_safety_failures"] = (
            summary["safety_failures"] <= rule["maximum_safety_failures"]
        )
    return {"passed": bool(checks) and all(checks.values()), "checks": checks}

