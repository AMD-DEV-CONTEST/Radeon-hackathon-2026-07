#!/usr/bin/env python3
"""Compare a PI0.5 action-fidelity candidate with the frozen B2 control."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
from pathlib import Path
import re
import statistics
from typing import Any


SCREEN_PROTOCOL = "pi05-three-mode-hidden-input-screen-v2"
PANEL_ROLE = "training_distribution_development"
CONTROL_CONTRACT = "pi05_absolute_v1"
CANDIDATE_CONTRACT = "pi05_incremental_se3_v1"
PROTOCOL = "pi05-paired-action-fidelity-ablation-v1"
STAGE_WEIGHTED_PROTOCOL = "pi05-paired-stage-weighted-action-fidelity-ablation-v1"
STAGE_WEIGHTED_CANDIDATE = "B3-SW"
STAGE_WEIGHTING_FACTOR = "task_stage_flow_loss_weight"
STAGE_WEIGHTING_SCOPE = "flow_loss_only_before_auxiliary_losses_v1"
MODE_FLOW_WEIGHTED_PROTOCOL = (
    "pi05-paired-stage-mode-weighted-action-fidelity-ablation-v1"
)
MODE_FLOW_WEIGHTED_CANDIDATE = "B3-SWM"
MODE_FLOW_WEIGHTING_FACTOR = "target_grasp_mode_flow_loss_weight"
MODE_FLOW_WEIGHTING_SCOPE = (
    "target_grasp_mode_flow_loss_only_before_auxiliary_losses_v1"
)
POSITION_SCALE_M = 0.06
ORIENTATION_SCALE_RAD = 0.60
BOOTSTRAP_ALPHA = 0.05
SIGN_TEST_ALPHA = 0.05
TOLERANCE = 1e-12


def _comparison_design(config: dict[str, Any] | None) -> dict[str, Any]:
    """Resolve the immutable action contracts and promotion gates for one ablation."""

    if config is None or config.get("candidate") == "B3":
        return {
            "candidate": "B3",
            "control_contract": CONTROL_CONTRACT,
            "candidate_contract": CANDIDATE_CONTRACT,
            "protocol": PROTOCOL,
            "require_sign_test": True,
            "enforce_earliest_passing": False,
        }
    if config.get("candidate") == STAGE_WEIGHTED_CANDIDATE:
        factor = config.get("isolated_factor") or {}
        weights = factor.get("treatment")
        if factor.get("name") != STAGE_WEIGHTING_FACTOR:
            raise ValueError("B3-SW preregistration has the wrong isolated factor")
        if factor.get("scope") != STAGE_WEIGHTING_SCOPE:
            raise ValueError("B3-SW preregistration has the wrong weighting scope")
        if (
            not isinstance(weights, list)
            or len(weights) != 6
            or any(
                not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or float(value) <= 0.0
                for value in weights
            )
        ):
            raise ValueError("B3-SW preregistration has invalid stage weights")
        return {
            "candidate": STAGE_WEIGHTED_CANDIDATE,
            "control_contract": CONTROL_CONTRACT,
            "candidate_contract": CONTROL_CONTRACT,
            "protocol": STAGE_WEIGHTED_PROTOCOL,
            "require_sign_test": False,
            "enforce_earliest_passing": True,
        }
    if config.get("candidate") == MODE_FLOW_WEIGHTED_CANDIDATE:
        factor = config.get("isolated_factor") or {}
        weights = factor.get("treatment")
        normalizer = factor.get("joint_population_normalizer")
        if factor.get("name") != MODE_FLOW_WEIGHTING_FACTOR:
            raise ValueError("B3-SWM preregistration has the wrong isolated factor")
        if factor.get("scope") != MODE_FLOW_WEIGHTING_SCOPE:
            raise ValueError("B3-SWM preregistration has the wrong weighting scope")
        if (
            not isinstance(weights, list)
            or len(weights) != 3
            or any(
                not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or float(value) <= 0.0
                for value in weights
            )
            or not isinstance(normalizer, (int, float))
            or not math.isfinite(float(normalizer))
            or float(normalizer) <= 0.0
        ):
            raise ValueError("B3-SWM preregistration has invalid mode flow weights")
        return {
            "candidate": MODE_FLOW_WEIGHTED_CANDIDATE,
            "control_contract": CONTROL_CONTRACT,
            "candidate_contract": CONTROL_CONTRACT,
            "protocol": MODE_FLOW_WEIGHTED_PROTOCOL,
            "require_sign_test": False,
            "enforce_earliest_passing": True,
        }
    raise ValueError("unsupported action-fidelity candidate preregistration")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return payload


def _read_screen(path: Path, expected_contract: str) -> dict[str, Any]:
    payload = _read_json(path)
    if payload.get("protocol") != SCREEN_PROTOCOL:
        raise ValueError(f"unexpected screen protocol: {path}")
    if payload.get("observation_panel_role") != PANEL_ROLE:
        raise ValueError(f"screen is not the frozen development panel: {path}")
    if payload.get("action_contract") != expected_contract:
        raise ValueError(
            f"expected {expected_contract} action contract in screen: {path}"
        )
    seeds = payload.get("sample_seeds")
    if not isinstance(seeds, list) or not seeds:
        raise ValueError(f"screen has no common-random-number seed panel: {path}")
    if payload.get("sampling_seed_protocol") != (
        "common-random-numbers-per-observation-v1"
    ):
        raise ValueError(f"screen has the wrong sampling protocol: {path}")
    return payload


def _checkpoint_step(payload: dict[str, Any]) -> int:
    for part in reversed(Path(str(payload.get("checkpoint", ""))).parts):
        if re.fullmatch(r"[0-9]{6}", part):
            return int(part)
    raise ValueError("screen checkpoint path has no six-digit training step")


def _row_key(row: dict[str, Any]) -> tuple[str, int]:
    mode = str(row.get("expected_mode", ""))
    try:
        index = int(row["dataset_index"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("screen row has no valid dataset_index") from exc
    if not mode:
        raise ValueError("screen row has no expected_mode")
    return mode, index


def _rows_by_key(payload: dict[str, Any], expected_count: int) -> dict[tuple[str, int], dict[str, Any]]:
    rows = payload.get("modes")
    if not isinstance(rows, list) or len(rows) != expected_count:
        raise ValueError(f"screen must contain exactly {expected_count} observation rows")
    keyed: dict[tuple[str, int], dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("screen observation row must be an object")
        key = _row_key(row)
        if key in keyed:
            raise ValueError(f"duplicate observation row: {key}")
        keyed[key] = row
    return keyed


def _normalized_pose_error(row: dict[str, Any]) -> tuple[float, float, float]:
    metrics = row.get("action_fidelity")
    if not isinstance(metrics, dict) or metrics.get("finite") is not True:
        raise ValueError(f"finite action fidelity is missing for observation {_row_key(row)}")
    try:
        position = float(metrics["median_maximum_arm_position_l2_m"])
        orientation = float(metrics["median_maximum_arm_orientation_error_rad"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(
            f"pose fidelity endpoint is missing for observation {_row_key(row)}"
        ) from exc
    if not all(math.isfinite(value) and value >= 0.0 for value in (position, orientation)):
        raise ValueError(f"pose fidelity endpoint is invalid for observation {_row_key(row)}")
    normalized = max(position / POSITION_SCALE_M, orientation / ORIENTATION_SCALE_RAD)
    return position, orientation, normalized


def _exact_sign_test_pvalue(improvements: list[float]) -> tuple[int, int, float]:
    non_ties = [value for value in improvements if abs(value) > TOLERANCE]
    positive = sum(value > 0.0 for value in non_ties)
    n = len(non_ties)
    if n == 0:
        return 0, 0, 1.0
    tail = sum(math.comb(n, count) for count in range(positive, n + 1))
    return positive, n, tail / (2**n)


def _exact_bootstrap_lower_bound(
    improvements: list[float], alpha: float = BOOTSTRAP_ALPHA
) -> tuple[float, int]:
    if not improvements:
        raise ValueError("at least one paired improvement is required")
    n = len(improvements)
    means = sorted(
        sum(improvements[index] for index in resample) / n
        for resample in itertools.product(range(n), repeat=n)
    )
    rank = max(0, math.ceil(alpha * len(means)) - 1)
    return means[rank], len(means)


def _paired_effect_size(improvements: list[float]) -> float | None:
    if len(improvements) < 2:
        return None
    standard_deviation = statistics.stdev(improvements)
    if standard_deviation <= TOLERANCE:
        return None
    return statistics.fmean(improvements) / standard_deviation


def _validate_pairing(
    control: dict[str, Any], candidate: dict[str, Any], expected_count: int
) -> tuple[dict[tuple[str, int], dict[str, Any]], dict[tuple[str, int], dict[str, Any]]]:
    control_seeds = tuple(int(seed) for seed in control["sample_seeds"])
    candidate_seeds = tuple(int(seed) for seed in candidate["sample_seeds"])
    if candidate_seeds != control_seeds:
        raise ValueError("control and candidate seed panels do not match")
    control_rows = _rows_by_key(control, expected_count)
    candidate_rows = _rows_by_key(candidate, expected_count)
    if set(candidate_rows) != set(control_rows):
        raise ValueError("control and candidate observation panels do not match")
    for key in control_rows:
        control_row = control_rows[key]
        candidate_row = candidate_rows[key]
        if candidate_row.get("stage") != control_row.get("stage"):
            raise ValueError(f"stage mismatch for paired observation {key}")
        if candidate_row.get("observable_object_context") != control_row.get(
            "observable_object_context"
        ):
            raise ValueError(f"object-context mismatch for paired observation {key}")
    return control_rows, candidate_rows


def compare_action_fidelity(
    control_path: Path,
    candidate_paths: list[Path],
    *,
    selected_candidate_path: Path | None = None,
    preregistered_config_path: Path | None = None,
    expected_count: int = 6,
) -> dict[str, Any]:
    if expected_count < 1:
        raise ValueError("expected_count must be positive")
    if not candidate_paths:
        raise ValueError("at least one candidate screen is required")
    control_path = control_path.resolve()
    resolved_candidates = [path.resolve() for path in candidate_paths]
    if len(set(resolved_candidates)) != len(resolved_candidates):
        raise ValueError("candidate screen paths must be unique")
    config = None
    config_sha256 = None
    if preregistered_config_path is not None:
        preregistered_config_path = preregistered_config_path.resolve()
        config = _read_json(preregistered_config_path)
        config_sha256 = _sha256(preregistered_config_path)
    design = _comparison_design(config)
    if selected_candidate_path is not None:
        selected_candidate_path = selected_candidate_path.resolve()
        if selected_candidate_path not in resolved_candidates:
            raise ValueError("selected candidate is not in the candidate screen panel")
    elif not design["enforce_earliest_passing"]:
        if len(resolved_candidates) != 1:
            raise ValueError("selected_candidate_path is required for multiple candidates")
        selected_candidate_path = resolved_candidates[0]

    control = _read_screen(control_path, design["control_contract"])
    if config is not None:
        factor = config.get("isolated_factor") or {}
        if design["candidate"] == "B3" and factor.get("treatment") != "incremental_se3_v1":
            raise ValueError("preregistered config does not bind incremental SE(3)")
        control_config = config.get("control") or {}
        if control_config.get("screen_sha256") != _sha256(control_path):
            raise ValueError("control screen does not match the preregistered hash")
        if design["candidate"] == "B3":
            if control_config.get("action_contract") != CONTROL_CONTRACT:
                raise ValueError("preregistered control action contract is invalid")
            paired_config = config.get("paired_units") or {}
            if int(paired_config.get("count", -1)) != expected_count:
                raise ValueError("preregistered paired-unit count does not match")
            if tuple(int(seed) for seed in paired_config.get("sample_seeds", ())) != tuple(
                int(seed) for seed in control["sample_seeds"]
            ):
                raise ValueError("control seeds do not match the preregistered panel")
            control_rows_for_config = _rows_by_key(control, expected_count)
            ordered_control_keys = sorted(
                control_rows_for_config, key=lambda item: (item[1], item[0])
            )
            if [key[1] for key in ordered_control_keys] != [
                int(index) for index in paired_config.get("dataset_indices", ())
            ]:
                raise ValueError("control indices do not match the preregistered panel")
            if [key[0] for key in ordered_control_keys] != [
                str(mode) for mode in paired_config.get("expected_modes", ())
            ]:
                raise ValueError("control modes do not match the preregistered panel")
            endpoint_config = config.get("primary_endpoint") or {}
            if float(endpoint_config.get("position_scale_m", math.nan)) != POSITION_SCALE_M:
                raise ValueError("preregistered position scale does not match")
            if float(endpoint_config.get("orientation_scale_rad", math.nan)) != ORIENTATION_SCALE_RAD:
                raise ValueError("preregistered orientation scale does not match")
        else:
            if config.get("frozen_before_candidate_training") is not True:
                raise ValueError(
                    f"{design['candidate']} preregistration was not frozen before training"
                )
            expected_control = (
                "B2"
                if design["candidate"] == STAGE_WEIGHTED_CANDIDATE
                else STAGE_WEIGHTED_CANDIDATE
            )
            if control_config.get("name") != expected_control:
                raise ValueError(
                    f"{design['candidate']} preregistration has the wrong control"
                )
            selection = config.get("selection") or {}
            if selection.get("rule") != (
                "earliest checkpoint passing the complete six-observation route "
                "and action-fidelity development gate"
            ):
                raise ValueError(
                    f"{design['candidate']} preregistration has the wrong selection rule"
                )
            promotion = config.get("promotion_gate") or {}
            if int(promotion.get("paired_action_fidelity_units", -1)) != expected_count:
                raise ValueError(
                    f"{design['candidate']} paired-unit count does not match"
                )
            if promotion.get("zero_paired_pose_error_regressions") is not True:
                raise ValueError(
                    f"{design['candidate']} zero-regression gate is not frozen"
                )
            if promotion.get("mean_normalized_pose_error_improvement_strictly_positive") is not True:
                raise ValueError(
                    f"{design['candidate']} positive-mean gate is not frozen"
                )
            if float(
                promotion.get(
                    "one_sided_95pct_bootstrap_lower_bound_minimum", math.nan
                )
            ) != 0.0:
                raise ValueError(
                    f"{design['candidate']} bootstrap threshold does not match"
                )

    comparisons = []
    for candidate_path in resolved_candidates:
        candidate = _read_screen(candidate_path, design["candidate_contract"])
        control_rows, candidate_rows = _validate_pairing(
            control, candidate, expected_count
        )
        paired_rows = []
        improvements = []
        for key in sorted(control_rows, key=lambda item: (item[1], item[0])):
            control_position, control_orientation, control_endpoint = (
                _normalized_pose_error(control_rows[key])
            )
            candidate_position, candidate_orientation, candidate_endpoint = (
                _normalized_pose_error(candidate_rows[key])
            )
            improvement = control_endpoint - candidate_endpoint
            improvements.append(improvement)
            paired_rows.append(
                {
                    "expected_mode": key[0],
                    "dataset_index": key[1],
                    "control_position_error_m": control_position,
                    "candidate_position_error_m": candidate_position,
                    "control_orientation_error_rad": control_orientation,
                    "candidate_orientation_error_rad": candidate_orientation,
                    "control_normalized_pose_error": control_endpoint,
                    "candidate_normalized_pose_error": candidate_endpoint,
                    "normalized_pose_error_improvement": improvement,
                }
            )
        lower_bound, bootstrap_count = _exact_bootstrap_lower_bound(improvements)
        positive, non_ties, sign_pvalue = _exact_sign_test_pvalue(improvements)
        zero_regressions = all(value >= -TOLERANCE for value in improvements)
        gates = {
            "zero_paired_regressions": zero_regressions,
            "positive_mean_improvement": statistics.fmean(improvements) > TOLERANCE,
            "one_sided_95pct_bootstrap_lower_bound_nonnegative": (
                lower_bound >= -TOLERANCE
            ),
        }
        if design["require_sign_test"]:
            gates["one_sided_exact_sign_test_p_le_0_05"] = (
                sign_pvalue <= SIGN_TEST_ALPHA
            )
        else:
            gates["complete_route_and_action_fidelity_screen_passed"] = (
                candidate.get("status") == "passed"
            )
        comparisons.append(
            {
                "candidate_screen": str(candidate_path),
                "candidate_screen_sha256": _sha256(candidate_path),
                "checkpoint": candidate.get("checkpoint"),
                "step": _checkpoint_step(candidate),
                "screen_status": candidate.get("status"),
                "selected": False,
                "paired_observations": expected_count,
                "improved_observations": sum(value > TOLERANCE for value in improvements),
                "tied_observations": sum(abs(value) <= TOLERANCE for value in improvements),
                "regressed_observations": sum(value < -TOLERANCE for value in improvements),
                "mean_normalized_pose_error_improvement": statistics.fmean(improvements),
                "median_normalized_pose_error_improvement": statistics.median(improvements),
                "paired_standardized_mean_effect_dz": _paired_effect_size(improvements),
                "exact_sign_test": {
                    "alternative": "candidate_has_lower_error",
                    "positive_improvements": positive,
                    "non_tied_pairs": non_ties,
                    "one_sided_p_value": sign_pvalue,
                },
                "exact_enumerated_percentile_bootstrap": {
                    "statistic": "mean paired normalized-pose-error improvement",
                    "resamples": bootstrap_count,
                    "one_sided_confidence_level": 0.95,
                    "lower_bound": lower_bound,
                },
                "promotion_gates": gates,
                "promotion_passed": all(gates.values()),
                "paired_rows": paired_rows,
            }
        )

    comparisons.sort(key=lambda item: int(item["step"]))
    if config is not None:
        if design["candidate"] == "B3":
            candidate_config = config.get("candidate_panel") or {}
            if candidate_config.get("action_contract") != CANDIDATE_CONTRACT:
                raise ValueError("preregistered candidate action contract is invalid")
            expected_steps = [
                int(step) for step in candidate_config.get("checkpoint_steps", ())
            ]
            bootstrap_config = (config.get("confirmatory_analysis") or {}).get(
                "bootstrap"
            ) or {}
            if int(bootstrap_config.get("resamples", -1)) != expected_count**expected_count:
                raise ValueError("preregistered bootstrap count does not match")
            promotion_config = config.get("promotion_gate") or {}
            if float(
                promotion_config.get(
                    "one_sided_95pct_bootstrap_lower_bound_minimum", math.nan
                )
            ) != 0.0:
                raise ValueError("preregistered bootstrap promotion threshold does not match")
            if float(
                promotion_config.get("one_sided_exact_sign_test_maximum_p", math.nan)
            ) != SIGN_TEST_ALPHA:
                raise ValueError("preregistered sign-test threshold does not match")
        else:
            expected_steps = [
                int(step)
                for step in (config.get("selection") or {}).get(
                    "checkpoint_steps", ()
                )
            ]
        if [item["step"] for item in comparisons] != expected_steps:
            raise ValueError("candidate steps do not match the preregistered panel")

    if design["enforce_earliest_passing"]:
        eligible = [item for item in comparisons if item["promotion_passed"]]
        expected_selected_path = (
            Path(str(eligible[0]["candidate_screen"])) if eligible else None
        )
        if (
            selected_candidate_path is not None
            and selected_candidate_path != expected_selected_path
        ):
            raise ValueError(
                "selected candidate is not the earliest checkpoint passing the frozen gates"
            )
        selected_candidate_path = expected_selected_path
    assert selected_candidate_path is not None or design["enforce_earliest_passing"]
    for item in comparisons:
        item["selected"] = (
            selected_candidate_path is not None
            and Path(str(item["candidate_screen"])) == selected_candidate_path
        )
    selected = next((item for item in comparisons if item["selected"]), None)
    promoted = selected is not None and selected["promotion_passed"]
    return {
        "schema_version": 1,
        "protocol": design["protocol"],
        "candidate": design["candidate"],
        "status": "promoted" if promoted else "not_promoted",
        "control_screen": str(control_path),
        "control_screen_sha256": _sha256(control_path),
        "control_checkpoint": control.get("checkpoint"),
        "control_action_contract": design["control_contract"],
        "candidate_action_contract": design["candidate_contract"],
        "observation_panel_role": PANEL_ROLE,
        "sample_seeds": [int(seed) for seed in control["sample_seeds"]],
        "endpoint": {
            "name": "maximum_normalized_median_arm_pose_error",
            "definition": "max(position_error_m/0.06, orientation_error_rad/0.60)",
            "position_scale_m": POSITION_SCALE_M,
            "orientation_scale_rad": ORIENTATION_SCALE_RAD,
            "direction": "lower_is_better",
        },
        "selected_candidate_screen": (
            str(selected_candidate_path) if selected_candidate_path is not None else None
        ),
        "selected_candidate_step": selected["step"] if selected is not None else None,
        "selected_candidate_promotion_passed": bool(promoted),
        "comparisons": comparisons,
        "preregistered_config": (
            str(preregistered_config_path)
            if preregistered_config_path is not None
            else None
        ),
        "preregistered_config_sha256": config_sha256,
        "claim_boundary": (
            "Paired offline action-fidelity ablation on six training-distribution "
            "observations. Diffusion samples are repeated measurements, not independent "
            "replicates. This result is not closed-loop parcel success."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--control", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, action="append", required=True)
    parser.add_argument("--selected-candidate", type=Path)
    parser.add_argument("--preregistered-config", type=Path)
    parser.add_argument("--expected-count", type=int, default=6)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-promotion", action="store_true")
    args = parser.parse_args()
    try:
        payload = compare_action_fidelity(
            args.control,
            args.candidate,
            selected_candidate_path=args.selected_candidate,
            preregistered_config_path=args.preregistered_config,
            expected_count=args.expected_count,
        )
    except ValueError as exc:
        parser.error(str(exc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_name(f".{args.output.name}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(args.output)
    print(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False))
    if args.require_promotion and payload["status"] != "promoted":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
