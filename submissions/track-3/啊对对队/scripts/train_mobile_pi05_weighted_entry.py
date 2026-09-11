#!/usr/bin/env python3
"""Run LeRobot PI0.5 training with opt-in residual-mode loss weighting."""

from __future__ import annotations

import json
import os

from parcel_sorter.pi05_weighted_loss import (
    PI05_MODE_FLOW_LOSS_WEIGHTING_SCOPE,
    PI05_STAGE_LOSS_WEIGHTING_SCOPE,
    install_pi05_action_loss_weights,
    pi05_absolute_action_weights,
    pi05_incremental_action_weights,
    pi05_residual_action_weights,
)
from parcel_sorter.pi05_action_projection_adapter import (
    PI05_FULL_ACTION_PROJECTION_PROTOCOL,
    install_pi05_full_action_projection_adapter,
)
from parcel_sorter.pi05_state_token_adapter import (
    PI05_STATE_TOKEN_PROTOCOL,
    install_pi05_state_token_adapter,
)
from parcel_sorter.pi05_mode_head_adapter import (
    PI05_MODE_HEAD_POOLING_MASKED_MEAN,
    install_pi05_mode_head_adapter,
    normalize_pi05_mode_head_pooling,
    pi05_mode_head_protocol,
)


def main() -> int:
    sampling_manifest = os.environ.get("MOBILE_PI05_SAMPLING_MANIFEST", "").strip()
    train_stats = os.environ.get("MOBILE_PI05_TRAIN_STATS", "").strip()
    train_stats_manifest = os.environ.get(
        "MOBILE_PI05_TRAIN_STATS_MANIFEST", ""
    ).strip()
    if bool(train_stats) != bool(train_stats_manifest):
        raise ValueError("train stats and train-stats manifest must be provided together")
    if train_stats and not sampling_manifest:
        raise ValueError("train-only stats require the frozen sampling manifest")
    sampling_protocol = None
    sampling_manifest_sha256 = None
    sampler_class = None
    train_stats_factory = None
    if sampling_manifest:
        from parcel_sorter.mobile_stratified_sampler import (
            SAMPLING_PROTOCOL,
            install_stratified_sampler,
            load_sampling_manifest,
        )

        sampling_payload = load_sampling_manifest(sampling_manifest)
        sampler_class = install_stratified_sampler(sampling_manifest)
        sampling_protocol = SAMPLING_PROTOCOL
        sampling_manifest_sha256 = sampling_payload["manifest_sha256"]
    if train_stats:
        from parcel_sorter.mobile_train_stats import install_train_stats_override

        train_stats_factory = install_train_stats_override(
            stats_path=train_stats,
            manifest_path=train_stats_manifest,
            sampling_manifest_path=sampling_manifest,
        )
    mode_weight = float(os.environ["MOBILE_PI05_MODE_LOSS_WEIGHT"])
    action_contract = os.environ.get(
        "MOBILE_PI05_ACTION_CONTRACT", "residual_v1"
    ).strip()
    if action_contract not in {"residual_v1", "absolute_v1", "incremental_se3_v1"}:
        raise ValueError(f"unsupported PI0.5 action contract: {action_contract!r}")
    mode_ce_weight = float(os.environ.get("MOBILE_PI05_MODE_CE_WEIGHT", "0"))
    mode_ce_time_raw = os.environ.get("MOBILE_PI05_MODE_CE_TIME")
    mode_ce_time = float(mode_ce_time_raw) if mode_ce_time_raw is not None else None
    state_token_enabled = os.environ.get("MOBILE_PI05_STATE_TOKEN", "0") == "1"
    full_action_projections = (
        os.environ.get("MOBILE_PI05_FULL_ACTION_PROJECTIONS", "0") == "1"
    )
    mode_head_enabled = os.environ.get("MOBILE_PI05_MODE_HEAD", "0") == "1"
    mode_head_pooling = normalize_pi05_mode_head_pooling(
        os.environ.get(
            "MOBILE_PI05_MODE_HEAD_POOLING", PI05_MODE_HEAD_POOLING_MASKED_MEAN
        )
    )
    mode_head_ce_weight = float(
        os.environ.get("MOBILE_PI05_MODE_HEAD_CE_WEIGHT", "0")
    )
    mode_head_class_weights_raw = os.environ.get(
        "MOBILE_PI05_MODE_HEAD_CLASS_WEIGHTS", ""
    ).strip()
    mode_head_class_weights = (
        tuple(float(value) for value in mode_head_class_weights_raw.split(","))
        if mode_head_class_weights_raw
        else None
    )
    stage_loss_weights_raw = os.environ.get(
        "MOBILE_PI05_STAGE_LOSS_WEIGHTS", ""
    ).strip()
    stage_loss_weights = (
        tuple(float(value) for value in stage_loss_weights_raw.split(","))
        if stage_loss_weights_raw
        else None
    )
    mode_flow_loss_weights_raw = os.environ.get(
        "MOBILE_PI05_MODE_FLOW_LOSS_WEIGHTS", ""
    ).strip()
    mode_flow_loss_weights = (
        tuple(float(value) for value in mode_flow_loss_weights_raw.split(","))
        if mode_flow_loss_weights_raw
        else None
    )
    mode_flow_loss_population_normalizer = float(
        os.environ.get("MOBILE_PI05_MODE_FLOW_LOSS_NORMALIZER", "1")
    )
    if full_action_projections:
        install_pi05_full_action_projection_adapter()
    if state_token_enabled:
        install_pi05_state_token_adapter()
    if mode_head_enabled:
        install_pi05_mode_head_adapter(pooling=mode_head_pooling)
    elif mode_head_pooling != PI05_MODE_HEAD_POOLING_MASKED_MEAN:
        raise ValueError("non-default mode-head pooling requires MOBILE_PI05_MODE_HEAD=1")
    if mode_head_ce_weight > 0.0 and not mode_head_enabled:
        raise ValueError("mode-head CE requires MOBILE_PI05_MODE_HEAD=1")
    if mode_head_class_weights is not None and not mode_head_enabled:
        raise ValueError("mode-head class weights require MOBILE_PI05_MODE_HEAD=1")
    if action_contract == "absolute_v1":
        weights = pi05_absolute_action_weights(mode_weight)
        mode_channel_start = 19
    elif action_contract == "incremental_se3_v1":
        weights = pi05_incremental_action_weights(mode_weight)
        mode_channel_start = 17
    else:
        weights = pi05_residual_action_weights(mode_weight)
        mode_channel_start = 9
    install_pi05_action_loss_weights(
        weights,
        mode_cross_entropy_weight=mode_ce_weight,
        mode_cross_entropy_time=mode_ce_time,
        mode_head_cross_entropy_weight=mode_head_ce_weight,
        mode_head_class_weights=mode_head_class_weights,
        mode_channel_start=mode_channel_start,
        stage_loss_weights=stage_loss_weights,
        mode_flow_loss_weights=mode_flow_loss_weights,
        mode_flow_loss_population_normalizer=(
            mode_flow_loss_population_normalizer
        ),
    )
    print(
        json.dumps(
            {
                "pi05_action_loss_weighting": "enabled",
                "sampling_manifest": sampling_manifest or None,
                "sampling_protocol": sampling_protocol,
                "sampling_manifest_sha256": sampling_manifest_sha256,
                "train_stats": train_stats or None,
                "train_stats_manifest": train_stats_manifest or None,
                "action_contract": action_contract,
                "mode_channel_start": mode_channel_start,
                "mode_loss_weight": mode_weight,
                "mode_cross_entropy_weight": mode_ce_weight,
                "mode_cross_entropy_time": mode_ce_time,
                "state_token_adapter": state_token_enabled,
                "state_token_protocol": (
                    PI05_STATE_TOKEN_PROTOCOL if state_token_enabled else None
                ),
                "full_action_projections": full_action_projections,
                "action_projection_protocol": (
                    PI05_FULL_ACTION_PROJECTION_PROTOCOL
                    if full_action_projections
                    else None
                ),
                "mode_head_adapter": mode_head_enabled,
                "mode_head_protocol": (
                    pi05_mode_head_protocol(mode_head_pooling)
                    if mode_head_enabled
                    else None
                ),
                "mode_head_pooling": mode_head_pooling if mode_head_enabled else None,
                "mode_head_cross_entropy_weight": mode_head_ce_weight,
                "mode_head_class_weights": mode_head_class_weights,
                "action_loss_weights": weights,
                "stage_loss_weights": stage_loss_weights,
                "stage_loss_weighting_scope": (
                    PI05_STAGE_LOSS_WEIGHTING_SCOPE
                    if stage_loss_weights is not None
                    else None
                ),
                "mode_flow_loss_weights": mode_flow_loss_weights,
                "mode_flow_loss_population_normalizer": (
                    mode_flow_loss_population_normalizer
                    if mode_flow_loss_weights is not None
                    else None
                ),
                "mode_flow_loss_weighting_scope": (
                    PI05_MODE_FLOW_LOSS_WEIGHTING_SCOPE
                    if mode_flow_loss_weights is not None
                    else None
                ),
            }
        ),
        flush=True,
    )
    from lerobot.scripts import lerobot_train

    if sampler_class is not None and lerobot_train.EpisodeAwareSampler is not sampler_class:
        raise RuntimeError("parcel stratified sampler was not installed in lerobot_train")
    if (
        train_stats_factory is not None
        and lerobot_train.make_train_eval_datasets is not train_stats_factory
    ):
        raise RuntimeError("parcel train-only stats were not installed in lerobot_train")
    lerobot_train.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
