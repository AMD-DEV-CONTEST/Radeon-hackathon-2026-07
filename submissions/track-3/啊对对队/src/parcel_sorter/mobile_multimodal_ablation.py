"""Paired offline selection gate for mobile RGB and RGB-D SmolVLA checkpoints."""

from __future__ import annotations

from typing import Any


POLICIES = ("raw_vla", "safety_clipped_vla", "harness_lite")


def compare_mobile_modalities(
    rgb: dict[str, Any],
    rgbd: dict[str, Any],
    *,
    maximum_latency_ratio: float = 1.25,
) -> dict[str, Any]:
    """Select RGB-D only when paired Harness error improves without regressions."""

    if maximum_latency_ratio < 1.0:
        raise ValueError("maximum latency ratio must be at least one")
    for name, payload in (("rgb", rgb), ("rgbd", rgbd)):
        if not str(payload.get("status", "")).startswith("passed_offline_action"):
            raise ValueError(f"{name} offline evaluation did not pass")
        if not payload.get("stages"):
            raise ValueError(f"{name} offline evaluation contains no stages")

    same_dataset = rgb.get("dataset_root") == rgbd.get("dataset_root")
    rgb_keys = _sample_keys(rgb)
    rgbd_keys = _sample_keys(rgbd)
    same_samples = rgb_keys == rgbd_keys
    rows: dict[str, Any] = {}
    for policy in POLICIES:
        baseline = rgb["offline_ablation"][policy]
        candidate = rgbd["offline_ablation"][policy]
        rgb_mae = float(baseline["mean_mae"])
        rgbd_mae = float(candidate["mean_mae"])
        rows[policy] = {
            "rgb_mean_mae": rgb_mae,
            "rgbd_mean_mae": rgbd_mae,
            "absolute_delta": rgbd_mae - rgb_mae,
            "relative_delta": (rgbd_mae / rgb_mae - 1.0) if rgb_mae else None,
            "rgb_envelope_pass_count": int(baseline["envelope_pass_count"]),
            "rgbd_envelope_pass_count": int(candidate["envelope_pass_count"]),
        }

    rgb_latency = float(rgb["latency_ms"]["mean"])
    rgbd_latency = float(rgbd["latency_ms"]["mean"])
    latency_ratio = rgbd_latency / rgb_latency
    checks = {
        "same_dataset": same_dataset,
        "same_paired_samples": same_samples,
        "harness_mae_improved": rows["harness_lite"]["absolute_delta"] < 0.0,
        "harness_envelope_not_worse": (
            rows["harness_lite"]["rgbd_envelope_pass_count"]
            >= rows["harness_lite"]["rgb_envelope_pass_count"]
        ),
        "latency_ratio_within_limit": latency_ratio <= maximum_latency_ratio,
    }
    selected = all(checks.values())
    return {
        "schema_version": 1,
        "protocol": "mobile-smolvla-rgb-rgbd-paired-offline-gate-v1",
        "status": "rgbd_selected" if selected else "rgb_retained",
        "rgbd_selected": selected,
        "closed_loop_campaign_authorized": selected,
        "checks": checks,
        "samples": len(rgb_keys),
        "metrics": rows,
        "latency_ms": {
            "rgb_mean": rgb_latency,
            "rgbd_mean": rgbd_latency,
            "ratio": latency_ratio,
            "maximum_allowed_ratio": maximum_latency_ratio,
        },
        "claim_boundary": (
            "paired train-dataset offline action ablation; not closed-loop task success "
            "or unseen-scene generalization"
        ),
    }


def _sample_keys(payload: dict[str, Any]) -> tuple[tuple[Any, ...], ...]:
    return tuple(
        (
            int(item["episode_index"]),
            str(item["stage"]),
            int(item["frame_index"]),
            int(item["seed"]),
        )
        for item in payload["stages"]
    )
