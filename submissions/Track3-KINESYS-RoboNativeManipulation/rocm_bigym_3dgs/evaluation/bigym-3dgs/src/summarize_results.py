#!/usr/bin/env python3
"""Create a compact, machine-readable acceptance summary from evaluator output."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Any


def summarize(
    results: dict[str, Any],
    expected_episodes: int,
    human_visual_review: str = "pending",
    recording_validation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if human_visual_review not in {"pending", "passed", "failed"}:
        raise ValueError("human_visual_review must be pending, passed, or failed")
    episodes = results.get("episodes", [])
    failures = Counter(
        episode.get("failure_reason") or "unclassified"
        for episode in episodes
        if not episode.get("success")
    )
    structural_pass = (
        results.get("status") == "benchmark_complete"
        and results.get("n_episodes") == expected_episodes
        and len(episodes) == expected_episodes
    )
    visual_shell_pass = bool(
        results.get("visual_shell", {}).get("strict")
        and results.get("visual_shell", {}).get("runtime_passed")
    )
    policy_pass = (
        int(results.get("policy_requests", 0)) > 0
        and results.get("policy_latency_ms", {}).get("p50") is not None
    )
    recording = results.get("recording")
    recording_pass = bool(
        results.get("schema_version", 1) < 2
        or (
            isinstance(recording, dict)
            and recording.get("mode") == "full"
            and recording.get("episodes_terminal") == expected_episodes
            and recording.get("episodes_interrupted") == 0
            and isinstance(recording_validation, dict)
            and recording_validation.get("status") == "recording_valid"
            and recording_validation.get("expected_episodes") == expected_episodes
        )
    )
    human_visual_pass = human_visual_review == "passed"
    return {
        "schema_version": 2,
        "status": (
            "evaluation_complete"
            if structural_pass and visual_shell_pass and policy_pass and recording_pass
            else "evaluation_failed"
        ),
        "task": results.get("task"),
        "episodes": expected_episodes,
        "successes": int(results.get("successes", 0)),
        "success_rate": float(results.get("success_rate", 0.0)),
        "policy_requests": int(results.get("policy_requests", 0)),
        "policy_latency_ms": results.get("policy_latency_ms"),
        "failure_categories": dict(sorted(failures.items())),
        "gates": {
            "episode_structure": structural_pass,
            "policy_requests": policy_pass,
            "strict_visual_shell_runtime": visual_shell_pass,
            "full_evaluation_recording": recording_pass,
            "human_visual_review": human_visual_pass,
        },
        "human_visual_review_status": human_visual_review,
        "recording_validation_status": (
            recording_validation.get("status")
            if isinstance(recording_validation, dict)
            else "not_provided"
        ),
        "claim_boundary": (
            "evaluation execution, full trajectory recording and human three-camera visual "
            "review are complete"
            if human_visual_pass and recording_pass
            else "evaluation execution is structurally complete; full-recording and visual "
            "publication gates must both pass before the run is accepted"
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-episodes", type=int, required=True)
    parser.add_argument("--recording-validation", type=Path)
    parser.add_argument(
        "--human-visual-review",
        choices=("pending", "passed", "failed"),
        default="pending",
    )
    args = parser.parse_args()
    results = json.loads(args.results.read_text(encoding="utf-8"))
    validation_bytes = (
        args.recording_validation.read_bytes()
        if args.recording_validation is not None
        else None
    )
    recording_validation = (
        json.loads(validation_bytes.decode("utf-8"))
        if validation_bytes is not None
        else None
    )
    summary = summarize(
        results,
        args.expected_episodes,
        args.human_visual_review,
        recording_validation,
    )
    summary["recording_validation_sha256"] = (
        hashlib.sha256(validation_bytes).hexdigest()
        if validation_bytes is not None
        else None
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    if summary["status"] != "evaluation_complete":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
