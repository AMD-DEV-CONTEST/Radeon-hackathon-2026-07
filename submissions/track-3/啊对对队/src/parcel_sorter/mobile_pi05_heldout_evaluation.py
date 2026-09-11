"""One-shot held-out routing evaluation for a frozen PI0.5 checkpoint."""

from __future__ import annotations

from collections import Counter
from typing import Any, Mapping, Sequence

from .metrics import wilson_interval
from .mobile_pi05_contract import PI05_GRASP_MODES


def summarize_pi05_heldout_routing(
    evaluations: Sequence[Mapping[str, Any]],
    panel: Mapping[str, Any],
) -> dict[str, Any]:
    panel_episodes = {
        str(item["episode_id"]): item for item in panel.get("episodes", ())
    }
    episode_ids = [str(item.get("episode_id") or "") for item in evaluations]
    errors: list[str] = []
    if set(episode_ids) != set(panel_episodes) or len(episode_ids) != len(
        set(episode_ids)
    ):
        errors.append("episode_panel_mismatch")
    correct = 0
    mode_counts: Counter[str] = Counter()
    mode_correct: Counter[str] = Counter()
    sample_seeds = None
    for item in evaluations:
        episode_id = str(item.get("episode_id") or "")
        panel_episode = panel_episodes.get(episode_id)
        if panel_episode is None:
            continue
        expected = str(panel_episode.get("grasp_mode"))
        predicted = str(item.get("predicted_grasp_mode"))
        mode_counts[expected] += 1
        if predicted == expected:
            correct += 1
            mode_correct[expected] += 1
        else:
            errors.append(f"{episode_id}:mode_correct")
        requirements = {
            "mode_input_hidden": bool(item.get("mode_input_hidden")),
            "three_or_more_samples": int(item.get("sample_count", 0)) >= 3,
            "finite": bool(item.get("finite")),
            "material_residual": bool(item.get("material_residual")),
            "no_expert_fallback": not bool(item.get("fallback_to_expert")),
            "pi05_policy": item.get("policy_type") == "pi05",
            "capture_integrity_passed": bool(item.get("capture_integrity_passed")),
        }
        errors.extend(
            f"{episode_id}:{name}" for name, passed in requirements.items() if not passed
        )
        seeds = tuple(int(value) for value in item.get("sample_seeds", ()))
        if sample_seeds is None:
            sample_seeds = seeds
        elif seeds != sample_seeds:
            errors.append(f"{episode_id}:sampling_seed_panel_mismatch")
    for mode in PI05_GRASP_MODES:
        expected_count = sum(
            str(item.get("grasp_mode")) == mode
            for item in panel_episodes.values()
        )
        if mode_counts[mode] != expected_count:
            errors.append(f"{mode}:coverage")
    trials = len(panel_episodes)
    interval = wilson_interval(correct, trials) if trials else (0.0, 0.0)
    return {
        "schema_version": 1,
        "protocol": "pi05-heldout-routing-evaluation-v1",
        "status": "passed" if not errors and correct == trials else "failed",
        "errors": errors,
        "error_count": len(errors),
        "checkpoint_selection_allowed": False,
        "episodes": trials,
        "correct_episodes": correct,
        "accuracy": correct / trials if trials else 0.0,
        "wilson_95": list(interval),
        "sample_seeds": list(sample_seeds or ()),
        "per_mode": {
            mode: {
                "episodes": mode_counts[mode],
                "correct": mode_correct[mode],
                "accuracy": (
                    mode_correct[mode] / mode_counts[mode]
                    if mode_counts[mode]
                    else 0.0
                ),
            }
            for mode in PI05_GRASP_MODES
        },
        "evaluations": [dict(item) for item in evaluations],
        "claim_boundary": (
            "One-shot held-out grasp-mode routing and residual sanity only; this is "
            "not closed-loop grasp, transport, placement, or 105-episode success. "
            "The panel cannot be reused for checkpoint selection or tuning."
        ),
    }
