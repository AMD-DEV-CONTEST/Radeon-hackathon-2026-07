#!/usr/bin/env python3
"""Run and optionally capture one strict scripted Mantis stack-bowls G1 episode.

The three bowls remain in one Genesis scene.  Each transport weld is activated
only after a real left-clamp-to-bowl contact is observed and is deleted before
release.  Capture artifacts are written only after the complete strict
three-bowl episode succeeds.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import math
import os
from pathlib import Path
from typing import Any, Sequence

from mantis_rocm_bridge.camera_mounts import genesis_wrist_mounts
from mantis_rocm_bridge.contracts import load_json, validate_contract_pair
from mantis_rocm_bridge.episode_state import EpisodeStageTracker
from mantis_rocm_bridge.genesis_capture import PolicyCaptureClock, genesis_rgb_array
from mantis_rocm_bridge.genesis_smoke import (
    BACKENDS,
    physical_pose,
    resolve_backend,
    sha256_file,
)
from mantis_rocm_bridge.ops import begin_run, finish_run
from mantis_rocm_bridge.release_retreat_boundary_trace import (
    TARGET_PAIR as RELEASE_RETREAT_BOUNDARY_TARGET_PAIR,
    WORK_PACKAGE_ID as RELEASE_RETREAT_BOUNDARY_WORK_PACKAGE,
    write_boundary_trace_exclusive,
)
from mantis_rocm_bridge.retreat_failure_telemetry import (
    WORK_PACKAGE_ID as RETREAT_FAILURE_TELEMETRY_WORK_PACKAGE,
    write_failure_telemetry_exclusive,
)
from mantis_rocm_bridge.stack_bowls import (
    StackStabilityTracker,
    evaluate_strict_target_frame,
)
from mantis_rocm_bridge.stack_bowls_env import (
    arm_dof_names,
    arm_for_bowl_x,
    sample_source_reset_poses,
    validate_genesis_scene_contract,
)
from mantis_rocm_bridge.candidate_isolation import CANDIDATE_ISOLATION_VERSION
from mantis_rocm_bridge.two_stage_plan import (
    ReplayPlan,
    ReplayPlanStep,
    plan_needs_reprobe,
    validate_candidate_tuple,
    validate_finite_offset,
    validate_ordered_poses,
)


ROOT = Path(__file__).resolve().parents[1]
SIDES = ("left", "right")

#: The single canonical G1 seed.  The task-pack ``g1_smoke`` set must be
#: exactly ``[1]``; only this seed may be labeled canonical G1.  Other seeds
#: are future training-data portability runs.
G1_CANONICAL_SEED = 1
G3_LEFT_IK_MATRIX_SEED = 1039
G3_LEFT_IK_MATRIX_CANDIDATES = (
    "fixed_position_reorient_v1_negative_control",
    "coupled_lateral_slerp",
    "coupled_descent_slerp",
    "coupled_lateral_descent_slerp",
)
G3_LEFT_DYNAMIC_ORIENTATION_SCHEDULES = (
    "fixed_position_reorient_v1",
    "coupled_descent_slerp",
)
G3_CORRECTED_EXPERT_WORK_PACKAGE = "WP-G3-CORR-010"
G3_CORRECTED_EXPERT_DIAGNOSTIC_SEEDS = (1285, 1290, 1295, 1298)
G3_CORRECTED_EXPERT_COLLECTION_SEEDS = (
    1251,
    1254,
    1255,
    1256,
    1266,
    1281,
    1299,
    1301,
    1302,
    1313,
    1316,
    1323,
    1360,
    1362,
    1375,
    1376,
)
G3_LEVEL1_RELEASE_WORK_PACKAGE = "WP-G3-CORR-011"
G3_LEVEL1_RELEASE_DIAGNOSTIC_SEEDS = (
    1423,
    1430,
    1463,
    1469,
    1477,
    1480,
    1503,
    1509,
)
G3_LEVEL1_SUPPORT_CONTACT_WORK_PACKAGE = "WP-G3-CORR-012"
G3_LEVEL1_SUPPORT_CONTACT_DIAGNOSTIC_SEEDS = (
    1602,
    1610,
    1613,
    1622,
    1630,
    1635,
    1658,
    1667,
)
G3_RETREAT_FAILURE_TELEMETRY_SEED = 1630
G3_RELEASE_RETREAT_BOUNDARY_SEED = 1630


def right_grasp_candidates(base_grasp_z: float, calibrated_forward_offset: float) -> list[tuple[float, float]]:
    """Return exactly six deterministic (forward_offset, z) grasp candidates.

    The order is fixed: current behavior first, then a monotone midpoint toward
    calibrated, then calibrated at same z, then the same three offsets at exactly
    0.02 m lower z.

    Args:
        base_grasp_z: Base TCP z height in meters (must be finite numeric, not bool).
        calibrated_forward_offset: Calibrated forward offset in meters (must be
            finite numeric, not bool, negative, and at least as forward as -0.03).

    Returns:
        Six (forward_offset, z) tuples in the prescribed order:
        1. (-0.03, base_z-0.04) - current behavior
        2. (midpoint, base_z-0.04) - monotone midpoint toward calibrated
        3. (calibrated, base_z-0.04) - calibrated offset
        4. (-0.03, base_z-0.06) - current at lower tier
        5. (midpoint, base_z-0.06) - midpoint at lower tier
        6. (calibrated, base_z-0.06) - calibrated at lower tier

    Raises:
        ValueError: If inputs are not finite numeric or calibrated is invalid.
    """
    for name, value in (("base_grasp_z", base_grasp_z), ("calibrated_forward_offset", calibrated_forward_offset)):
        if isinstance(value, bool):
            raise ValueError(f"{name} must be numeric, not bool")
        if not isinstance(value, (int, float)):
            raise ValueError(f"{name} must be numeric, got {type(value).__name__}")
        if not math.isfinite(value):
            raise ValueError(f"{name} must be finite, got {value}")

    if not (calibrated_forward_offset < 0):
        raise ValueError(f"calibrated_forward_offset must be negative, got {calibrated_forward_offset}")
    if not (calibrated_forward_offset <= -0.03):
        raise ValueError(f"calibrated_forward_offset must be at least as forward as -0.03, got {calibrated_forward_offset}")

    base_z = float(base_grasp_z)
    calibrated = float(calibrated_forward_offset)
    current_forward = -0.03
    upper_z = base_z - 0.04
    lower_z = base_z - 0.06

    midpoint = (current_forward + calibrated) / 2.0

    return [
        (current_forward, upper_z),
        (midpoint, upper_z),
        (calibrated, upper_z),
        (current_forward, lower_z),
        (midpoint, lower_z),
        (calibrated, lower_z),
    ]


def right_grasp_pose_candidates(base_grasp_z: float, calibrated_forward_offset: float, finger_forward_extent_m: float) -> list[tuple[float, float, float]]:
    """Return exactly nine deterministic (x_offset, forward_offset, z) grasp pose candidates.

    Reuses right_grasp_candidates for Y/Z offsets and adds X-compensated upper-tier candidates.
    This is global robot geometry, not seed-specific.

    Args:
        base_grasp_z: Base TCP z height in meters (must be finite numeric, not bool).
        calibrated_forward_offset: Calibrated forward offset in meters (must be
            finite numeric, not bool, negative, and at least as forward as -0.03).
        finger_forward_extent_m: Finger forward extent in meters (must be finite numeric,
            not bool, and satisfy 0 < extent <= 0.10).

    Returns:
        Nine (x_offset, forward_offset, z) tuples in the prescribed order:
        1. (0.0, -0.03, base_z-0.04) - current behavior, no X offset
        2. (0.0, midpoint, base_z-0.04) - midpoint, no X offset
        3. (0.0, calibrated, base_z-0.04) - calibrated, no X offset
        4. (0.0, -0.03, base_z-0.06) - current at lower tier, no X offset
        5. (0.0, midpoint, base_z-0.06) - midpoint at lower tier, no X offset
        6. (0.0, calibrated, base_z-0.06) - calibrated at lower tier, no X offset
        7. (finger_forward_extent_m, -0.03, base_z-0.04) - X-compensated current
        8. (finger_forward_extent_m, midpoint, base_z-0.04) - X-compensated midpoint
        9. (finger_forward_extent_m, calibrated, base_z-0.04) - X-compensated calibrated

    Raises:
        ValueError: If inputs are not finite numeric, calibrated is invalid, or finger extent is invalid.
    """
    # Validate finger_forward_extent_m
    if isinstance(finger_forward_extent_m, bool):
        raise ValueError("finger_forward_extent_m must be numeric, not bool")
    if not isinstance(finger_forward_extent_m, (int, float)):
        raise ValueError(f"finger_forward_extent_m must be numeric, got {type(finger_forward_extent_m).__name__}")
    if not math.isfinite(finger_forward_extent_m):
        raise ValueError(f"finger_forward_extent_m must be finite, got {finger_forward_extent_m}")
    if not (0.0 < finger_forward_extent_m <= 0.10):
        raise ValueError(f"finger_forward_extent_m must satisfy 0 < extent <= 0.10, got {finger_forward_extent_m}")

    # Get the six (forward_offset, z) candidates from the existing helper
    yz_candidates = right_grasp_candidates(base_grasp_z, calibrated_forward_offset)

    # Extract forward offsets for upper tier (candidates 0-2) for X-compensated candidates
    current_forward = yz_candidates[0][0]  # -0.03
    midpoint = yz_candidates[1][0]        # midpoint
    calibrated = yz_candidates[2][0]      # calibrated
    upper_z = yz_candidates[0][1]         # base_z - 0.04

    finger_extent = float(finger_forward_extent_m)

    # Build nine (x_offset, forward_offset, z) candidates
    candidates: list[tuple[float, float, float]] = []

    # First six: existing Y/Z candidates with x_offset=0.0
    for forward_offset, z in yz_candidates:
        candidates.append((0.0, forward_offset, z))

    # Last three: X-compensated upper-tier candidates
    candidates.append((finger_extent, current_forward, upper_z))
    candidates.append((finger_extent, midpoint, upper_z))
    candidates.append((finger_extent, calibrated, upper_z))

    return candidates


#: Canonical number of right-hand grasp pose candidates returned by
#: ``right_grasp_pose_candidates``. The probe search order below is defined
#: for exactly this many candidates.
RIGHT_GRASP_CANDIDATE_COUNT = 9

#: Probe-only right-hand candidate index visit order. This preserves the
#: original stable candidate indices while trying upper X-compensated poses
#: before the lower-Z tier.
RIGHT_PROBE_CANDIDATE_SEARCH_ORDER = (0, 1, 2, 6, 7, 8, 3, 4, 5)


def right_probe_candidate_search_order(num_candidates: int) -> list[int]:
    """Return the probe-only right-hand candidate index search order.

    Online mode keeps the canonical ``0..8`` order and replay mode executes
    only its planned stable index. Probe mode visits upper non-X candidates,
    then upper X-compensated candidates, then the lower-Z tier.
    """
    if isinstance(num_candidates, bool):
        raise ValueError("num_candidates must be an int, not bool")
    if not isinstance(num_candidates, int):
        raise ValueError(
            f"num_candidates must be an int, got {type(num_candidates).__name__}"
        )
    if num_candidates != RIGHT_GRASP_CANDIDATE_COUNT:
        raise ValueError(
            f"num_candidates must be exactly {RIGHT_GRASP_CANDIDATE_COUNT} to match "
            f"right_grasp_pose_candidates, got {num_candidates}"
        )
    order = list(RIGHT_PROBE_CANDIDATE_SEARCH_ORDER)
    if sorted(order) != list(range(RIGHT_GRASP_CANDIDATE_COUNT)):
        raise ValueError(
            "RIGHT_PROBE_CANDIDATE_SEARCH_ORDER must be a permutation of "
            f"range({RIGHT_GRASP_CANDIDATE_COUNT}): got {order}"
        )
    return order


def right_xy_correction(measured_xy: tuple[float, float], target_xy: tuple[float, float], tolerance_m: float) -> tuple[float, float] | None:
    """Return a two-axis correction target or None if within tolerance.

    No correction is returned only when both absolute errors are strictly below
    the tolerance. Otherwise, return the target-measured error vector.

    Args:
        measured_xy: (x, y) measured position in meters (must be length-2 numeric sequence).
        target_xy: (x, y) target position in meters (must be length-2 numeric sequence).
        tolerance_m: Per-axis tolerance in meters (must be positive numeric, not bool).

    Returns:
        None if both |target[i] - measured[i]| < tolerance_m, otherwise
        (target_x - measured_x, target_y - measured_y).

    Raises:
        ValueError: If inputs are invalid (wrong type, wrong length, non-finite, or non-positive tolerance).
    """
    # Validate tolerance_m separately (scalar)
    if isinstance(tolerance_m, bool):
        raise ValueError("tolerance_m must be numeric, not bool")
    if not isinstance(tolerance_m, (int, float)):
        raise ValueError(f"tolerance_m must be numeric, got {type(tolerance_m).__name__}")
    if not math.isfinite(tolerance_m):
        raise ValueError(f"tolerance_m must be finite, got {tolerance_m}")
    if not (tolerance_m > 0):
        raise ValueError(f"tolerance_m must be positive, got {tolerance_m}")

    # Validate measured_xy and target_xy are length-2 sequences
    for name, seq in (("measured_xy", measured_xy), ("target_xy", target_xy)):
        if not hasattr(seq, "__len__"):
            raise ValueError(f"{name} must be a sequence, got {type(seq).__name__}")
        if len(seq) != 2:
            raise ValueError(f"{name} must have length 2, got {len(seq)}")
        try:
            for i, value in enumerate(seq):
                if isinstance(value, bool):
                    raise ValueError(f"{name}[{i}] must be numeric, not bool")
                if not isinstance(value, (int, float)):
                    raise ValueError(f"{name}[{i}] must be numeric, got {type(value).__name__}")
                if not math.isfinite(value):
                    raise ValueError(f"{name}[{i}] must be finite, got {value}")
        except TypeError:
            raise ValueError(f"{name} must be iterable with numeric elements")

    mx, my = map(float, measured_xy)
    tx, ty = map(float, target_xy)
    tol = float(tolerance_m)

    error_x = tx - mx
    error_y = ty - my

    if abs(error_x) < tol and abs(error_y) < tol:
        return None

    return (error_x, error_y)


def capture_npz_name(seed: int) -> str:
    """Return the per-seed capture artifact filename for ``seed``."""
    return f"episode_seed_{int(seed)}.npz"


def is_canonical_g1_seed(seed: int) -> bool:
    """True only for the single canonical G1 seed.

    A strict scripted episode that succeeds on any other seed is a
    training-data portability run and must never be labeled canonical G1.
    """
    return int(seed) == G1_CANONICAL_SEED


def validate_g1_smoke_contract(task: dict[str, Any]) -> None:
    """Raise if the frozen ``g1_smoke`` task-pack seed set drifts.

    The canonical G1 contract requires ``g1_smoke`` to be exactly ``[1]``.
    Any drift is a hard error for both canonical and portability runs.
    """
    seed_set = task.get("evaluation", {}).get("seed_sets", {}).get("g1_smoke")
    if seed_set != [G1_CANONICAL_SEED]:
        raise RuntimeError(
            "strict G1 seed contract changed: "
            f"g1_smoke={seed_set!r}, expected [{G1_CANONICAL_SEED}]"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("mantis_urdf", type=Path)
    parser.add_argument("bowl_asset_root", type=Path)
    parser.add_argument("--ops-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--backend", choices=BACKENDS, required=True)
    parser.add_argument(
        "--generation-mode",
        choices=("online", "probe", "replay"),
        default="online",
        help=(
            "Generation mode: online (default current behavior), "
            "probe (diagnostic calibration with larger horizon), "
            "replay (deterministic replay from probe plan)"
        ),
    )
    parser.add_argument(
        "--replay-plan",
        type=Path,
        help=(
            "Path to replay_plan.json for replay mode. "
            "Required and only valid for generation-mode=replay."
        ),
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=G1_CANONICAL_SEED,
        help=(
            "positive integer episode seed; seed 1 is the unchanged canonical "
            "G1 gate, any other seed is a training-data portability run that is "
            "not labeled canonical G1. "
            "Seed 1 is forbidden in probe mode to protect canonical semantics."
        ),
    )
    parser.add_argument(
        "--probe-max-policy-steps",
        type=int,
        default=2400,
        help=(
            "Maximum policy steps for probe mode (default 2400, must be positive "
            "and >= task max 1200). Only applies to generation-mode=probe."
        ),
    )
    parser.add_argument(
        "--transition-ik-matrix-only",
        action="store_true",
        help=(
            "After completing bowl level 1 in probe mode, evaluate the frozen "
            "consecutive-left IK candidate matrix without commanding candidate "
            "motions or advancing the physics clock, then terminate."
        ),
    )
    parser.add_argument(
        "--transition-ik-matrix-contract",
        type=Path,
        default=ROOT / "configs/g3-left-interbowl-clearance-ik-matrix-v2.json",
    )
    parser.add_argument(
        "--consecutive-left-orientation-schedule",
        choices=G3_LEFT_DYNAMIC_ORIENTATION_SCHEDULES,
        default=G3_LEFT_DYNAMIC_ORIENTATION_SCHEDULES[0],
        help=(
            "Select the consecutive-left dynamic orientation schedule. "
            "The non-default schedule requires its frozen R3 contract."
        ),
    )
    parser.add_argument(
        "--consecutive-left-dynamic-contract",
        type=Path,
        default=(
            ROOT
            / "configs/g3-left-interbowl-coupled-descent-dynamic-v3.json"
        ),
    )
    parser.add_argument(
        "--corrected-expert-contract",
        type=Path,
        help=(
            "Frozen WP-G3-CORR-010 corrected-expert contract. It extends the "
            "accepted R3 schedule to the predeclared diagnostic and collection "
            "seeds without changing the schedule itself."
        ),
    )
    parser.add_argument(
        "--corrected-expert-authorization",
        type=Path,
        help=(
            "Machine-readable user authorization overlay for gated "
            "WP-G3-CORR-010 execution. Required with --corrected-expert-contract."
        ),
    )
    parser.add_argument(
        "--level1-release-diagnostic-contract",
        type=Path,
        help=(
            "Frozen instrumentation-only level-1 release observability "
            "contract (WP-G3-CORR-011 or WP-G3-CORR-012)."
        ),
    )
    parser.add_argument(
        "--level1-release-diagnostic-authorization",
        type=Path,
        help=(
            "Machine-readable user authorization overlay for gated "
            "level-1 release observability execution. Required with the "
            "diagnostic contract."
        ),
    )
    parser.add_argument(
        "--failure-telemetry-contract",
        type=Path,
        help=(
            "Frozen WP-G3-CORR-014 first-safety-failure telemetry contract. "
            "Requires the matching authorization and WP-G3-CORR-012 inputs."
        ),
    )
    parser.add_argument(
        "--failure-telemetry-authorization",
        type=Path,
        help=(
            "Machine-readable user authorization for WP-G3-CORR-014. "
            "Required with --failure-telemetry-contract."
        ),
    )
    parser.add_argument(
        "--release-retreat-boundary-contract",
        type=Path,
        help=(
            "Frozen WP-G3-CORR-015 cached release-to-retreat boundary "
            "contact contract. Requires its authorization and all "
            "WP-G3-CORR-014 inputs."
        ),
    )
    parser.add_argument(
        "--release-retreat-boundary-authorization",
        type=Path,
        help=(
            "Machine-readable user authorization for WP-G3-CORR-015. "
            "Required with --release-retreat-boundary-contract."
        ),
    )
    parser.add_argument("--capture", action="store_true")
    parser.add_argument("--transport-duration-s", type=float, default=2.0)
    parser.add_argument("--cartesian-waypoints", type=int, default=8)
    parser.add_argument(
        "--scene-contract",
        type=Path,
        default=ROOT / "configs/stack-bowls-genesis-v1.json",
    )
    parser.add_argument(
        "--camera-contract",
        type=Path,
        default=ROOT / "configs/camera-extrinsics-v1.json",
    )
    parser.add_argument(
        "--port",
        type=Path,
        default=ROOT / "configs/mantis-port-config.json",
    )
    parser.add_argument(
        "--source-task",
        type=Path,
        default=ROOT / "configs/source-task-stack-bowls-three.json",
    )
    parser.add_argument(
        "--task",
        type=Path,
        default=ROOT / "configs/task-pack-v1.json",
    )
    return parser


def validate_corrected_expert_execution_contract(
    contract: dict[str, Any],
    authorization: dict[str, Any],
    *,
    planning_contract_sha256: str,
    seed: int,
    generation_mode: str,
    capture: bool,
    backend: str,
    cuda_visible_devices: str | None,
) -> str:
    """Validate one WP-G3-CORR-010 invocation and return its frozen phase.

    The planning contract remains immutable and planning-only. A separate
    user-stated authorization overlay enables the already-frozen gate order.
    This validator deliberately rejects online execution, GPU exposure,
    unlisted seeds, diagnostic capture, and replay without capture.
    """

    if contract.get("work_package_id") != G3_CORRECTED_EXPERT_WORK_PACKAGE:
        raise RuntimeError("corrected-expert work-package drift")
    variable = contract.get("single_primary_variable", {})
    if variable.get("baseline") != "fixed_position_reorient_v1":
        raise RuntimeError("corrected-expert baseline schedule drift")
    if variable.get("candidate") != "coupled_descent_slerp":
        raise RuntimeError("corrected-expert candidate schedule drift")
    policy = contract.get("seed_policy", {})
    diagnostic = policy.get("diagnostic_panel", {})
    collection = policy.get("collection_panel", {})
    if tuple(diagnostic.get("seeds_in_order", ())) != (
        G3_CORRECTED_EXPERT_DIAGNOSTIC_SEEDS
    ):
        raise RuntimeError("corrected-expert diagnostic seed-order drift")
    if tuple(collection.get("seeds_in_order", ())) != (
        G3_CORRECTED_EXPERT_COLLECTION_SEEDS
    ):
        raise RuntimeError("corrected-expert collection seed-order drift")
    if (
        diagnostic.get("backend") != "cpu"
        or diagnostic.get("cuda_visible_devices") != ""
        or diagnostic.get("capture") is not False
        or diagnostic.get("retry_count") != 0
    ):
        raise RuntimeError("corrected-expert diagnostic isolation drift")
    if (
        collection.get("backend") != "cpu"
        or collection.get("cuda_visible_devices") != ""
        or collection.get("retry_count") != 0
    ):
        raise RuntimeError("corrected-expert collection isolation drift")
    if backend != "cpu" or cuda_visible_devices != "":
        raise RuntimeError("corrected-expert execution requires isolated CPU")
    if generation_mode not in {"probe", "replay"}:
        raise RuntimeError("corrected-expert execution forbids online mode")

    if authorization.get("work_package_id") != G3_CORRECTED_EXPERT_WORK_PACKAGE:
        raise RuntimeError("corrected-expert authorization work-package drift")
    if authorization.get("planning_contract_sha256") != planning_contract_sha256:
        raise RuntimeError("corrected-expert authorization contract hash drift")
    if authorization.get("authorization_status") != (
        "AUTHORIZED_GATED_EXECUTION"
    ):
        raise RuntimeError("corrected-expert execution is not authorized")
    if authorization.get("authorization_provenance", {}).get("kind") != (
        "user_stated"
    ):
        raise RuntimeError("corrected-expert authorization provenance drift")
    actions = authorization.get("authorized_actions", {})
    if actions.get("export_dataset") is not False or actions.get("train") is not False:
        raise RuntimeError("corrected-expert export/training boundary drift")

    if seed in G3_CORRECTED_EXPERT_DIAGNOSTIC_SEEDS:
        if actions.get("run_diagnostic_panel_after_code_gate_acceptance") is not True:
            raise RuntimeError("corrected-expert diagnostic is not authorized")
        if generation_mode != "probe" or capture:
            raise RuntimeError(
                "corrected-expert diagnostic requires probe mode without capture"
            )
        return "diagnostic"
    if seed in G3_CORRECTED_EXPERT_COLLECTION_SEEDS:
        if actions.get("run_collection_after_diagnostic_acceptance") is not True:
            raise RuntimeError("corrected-expert collection is not authorized")
        if generation_mode == "probe" and capture:
            raise RuntimeError("corrected-expert probe forbids capture")
        if generation_mode == "replay" and not capture:
            raise RuntimeError("corrected-expert replay requires capture")
        return "collection_probe" if generation_mode == "probe" else "collection_capture"
    raise RuntimeError("seed is outside frozen corrected-expert panels")


def validate_level1_release_execution_contract(
    contract: dict[str, Any],
    authorization: dict[str, Any],
    *,
    planning_contract_sha256: str,
    seed: int,
    generation_mode: str,
    capture: bool,
    backend: str,
    cuda_visible_devices: str | None,
) -> str:
    """Validate one instrumentation-only level-1 release invocation."""

    work_package_id = contract.get("work_package_id")
    variable = contract.get("single_primary_variable", {})
    if work_package_id == G3_LEVEL1_RELEASE_WORK_PACKAGE:
        expected_baseline = "position_only_pre_release_post_release_placed"
        expected_candidate = "relative_pose_and_contact_trace_v1"
        expected_seeds = G3_LEVEL1_RELEASE_DIAGNOSTIC_SEEDS
        required_action = "run_observability_panel_after_code_gate_acceptance"
        phase = "level1_release_observability"
    elif work_package_id == G3_LEVEL1_SUPPORT_CONTACT_WORK_PACKAGE:
        expected_baseline = "relative_pose_and_robot_contact_trace_v1"
        expected_candidate = "relative_pose_robot_and_support_contact_trace_v2"
        expected_seeds = G3_LEVEL1_SUPPORT_CONTACT_DIAGNOSTIC_SEEDS
        required_action = "run_support_contact_panel_after_code_gate_acceptance"
        phase = "level1_support_contact_observability"
        api = contract.get("genesis_contact_api", {})
        if (
            api.get("method") != "RigidEntity.get_contacts(with_entity=...)"
            or api.get("query")
            != "selected_bowl.get_contacts(with_entity=supporting_bowl)"
            or api.get("query_advances_physics") is not False
            or api.get(
                "same_step_weld_registration_or_deletion_comparison_is_instantaneous"
            )
            is not False
            or api.get("admissible_primary_snapshots")
            != ["final_pre_release", "immediate_post_release"]
        ):
            raise RuntimeError("level1 support-contact API semantics drift")
    else:
        raise RuntimeError("level1-release work-package drift")
    if variable.get("baseline") != expected_baseline:
        raise RuntimeError("level1-release observability baseline drift")
    if variable.get("candidate") != expected_candidate:
        raise RuntimeError("level1-release observability candidate drift")
    panel = contract.get("diagnostic_panel", {})
    if tuple(panel.get("seeds_in_order", ())) != expected_seeds:
        raise RuntimeError("level1-release diagnostic seed-order drift")
    if panel.get("pattern") != ["right", "left", "left"]:
        raise RuntimeError("level1-release source-pattern drift")
    if (
        panel.get("backend") != "cpu"
        or panel.get("cuda_visible_devices") != ""
        or panel.get("capture") is not False
        or panel.get("retry_count") != 0
        or panel.get("serial") is not True
    ):
        raise RuntimeError("level1-release diagnostic isolation drift")
    frozen = contract.get("frozen_invariants", {})
    if frozen.get("orientation_schedule_id") != "coupled_descent_slerp":
        raise RuntimeError("level1-release orientation schedule drift")
    if frozen.get("capture") is not False or frozen.get("retry_count") != 0:
        raise RuntimeError("level1-release capture/retry boundary drift")
    if backend != "cpu" or cuda_visible_devices != "":
        raise RuntimeError("level1-release execution requires isolated CPU")
    if generation_mode != "probe" or capture:
        raise RuntimeError(
            "level1-release diagnostic requires probe mode without capture"
        )
    if seed not in expected_seeds:
        raise RuntimeError("seed is outside frozen level1-release panel")

    if authorization.get("work_package_id") != work_package_id:
        raise RuntimeError("level1-release authorization work-package drift")
    if authorization.get("planning_contract_sha256") != planning_contract_sha256:
        raise RuntimeError("level1-release authorization contract hash drift")
    if authorization.get("authorization_status") != (
        "AUTHORIZED_GATED_EXECUTION"
    ):
        raise RuntimeError("level1-release execution is not authorized")
    if authorization.get("authorization_provenance", {}).get("kind") != (
        "user_stated"
    ):
        raise RuntimeError("level1-release authorization provenance drift")
    actions = authorization.get("authorized_actions", {})
    if actions.get(required_action) is not True:
        raise RuntimeError("level1-release observability panel is not authorized")
    forbidden = (
        "change_controller",
        "run_source_collection",
        "export_dataset",
        "train",
    )
    if any(actions.get(name) is not False for name in forbidden):
        raise RuntimeError("level1-release mutation/collection boundary drift")
    if tuple(authorization.get("diagnostic_seed_order", ())) != expected_seeds:
        raise RuntimeError("level1-release authorization seed-order drift")
    return phase


def validate_retreat_failure_telemetry_execution_contract(
    contract: dict[str, Any],
    authorization: dict[str, Any],
    *,
    planning_contract_sha256: str,
    level1_contract_sha256: str,
    level1_authorization_sha256: str,
    seed: int,
    generation_mode: str,
    capture: bool,
    backend: str,
    cuda_visible_devices: str | None,
) -> str:
    """Validate the single-attempt WP-G3-CORR-014 invocation."""

    if contract.get("work_package_id") != (
        RETREAT_FAILURE_TELEMETRY_WORK_PACKAGE
    ):
        raise RuntimeError("failure-telemetry work-package drift")
    if contract.get("status") != "PLANNED_FROZEN_NOT_EXECUTED":
        raise RuntimeError("failure-telemetry planning status drift")
    variable = contract.get("single_primary_variable", {})
    if (
        variable.get("baseline")
        != "failure_kind_stage_and_pair_only"
        or variable.get("candidate") != "cached_collision_time_state_v1"
    ):
        raise RuntimeError("failure-telemetry primary-variable drift")
    run = contract.get("diagnostic_run", {})
    if (
        run.get("seeds_in_order") != [G3_RETREAT_FAILURE_TELEMETRY_SEED]
        or run.get("attempt_count") != 1
        or run.get("backend") != "cpu"
        or run.get("cuda_visible_devices") != ""
        or run.get("serial") is not True
        or run.get("retry_count") != 0
        or run.get("capture") is not False
        or run.get("stop_on_safety_failure") is not True
        or run.get("stop_on_infrastructure_failure") is not True
        or run.get("no_physics_step_after_first_detected_failure") is not True
        or run.get("fresh_paths_only") is not True
        or run.get("no_overwrite") is not True
    ):
        raise RuntimeError("failure-telemetry run isolation drift")
    telemetry = contract.get("telemetry_contract", {})
    if (
        telemetry.get("artifact_name") != "failure_telemetry.json"
        or telemetry.get("numeric_requirements", {}).get(
            "commanded_qpos_length"
        )
        != 18
        or telemetry.get("numeric_requirements", {}).get(
            "robot_qpos_length"
        )
        != 18
        or telemetry.get("numeric_requirements", {}).get(
            "observer_step_delta"
        )
        != 0
    ):
        raise RuntimeError("failure-telemetry schema drift")
    entry = contract.get("entry_evidence", {})
    if (
        entry.get("predecessor_support_contact_contract_sha256")
        != level1_contract_sha256
        or entry.get("predecessor_support_contact_authorization_sha256")
        != level1_authorization_sha256
    ):
        raise RuntimeError("failure-telemetry predecessor binding drift")
    if (
        seed != G3_RETREAT_FAILURE_TELEMETRY_SEED
        or generation_mode != "probe"
        or capture
        or backend != "cpu"
        or cuda_visible_devices != ""
    ):
        raise RuntimeError("failure-telemetry invocation isolation drift")

    if authorization.get("work_package_id") != (
        RETREAT_FAILURE_TELEMETRY_WORK_PACKAGE
    ):
        raise RuntimeError("failure-telemetry authorization package drift")
    if authorization.get("planning_contract_sha256") != (
        planning_contract_sha256
    ):
        raise RuntimeError("failure-telemetry authorization hash drift")
    if authorization.get("authorization_status") != (
        "AUTHORIZED_GATED_EXECUTION"
    ):
        raise RuntimeError("failure-telemetry execution is not authorized")
    if authorization.get("authorization_provenance", {}).get("kind") != (
        "user_stated"
    ):
        raise RuntimeError("failure-telemetry authorization provenance drift")
    actions = authorization.get("authorized_actions", {})
    if (
        actions.get("create_versioned_instrumentation_code") is not True
        or actions.get("create_tests_and_receipts") is not True
        or actions.get("run_seed1630_once_after_code_gate_acceptance")
        is not True
    ):
        raise RuntimeError("failure-telemetry required action is not authorized")
    forbidden = (
        "change_controller",
        "change_task_or_physics",
        "run_source_collection",
        "export_dataset",
        "train",
        "run_on_amd_rocm",
        "operate_real_hardware",
        "stop_other_users_processes",
        "contact_external_parties",
        "open_github_pull_request",
        "publish",
    )
    if any(actions.get(name) is not False for name in forbidden):
        raise RuntimeError("failure-telemetry forbidden action drift")
    constraints = authorization.get("execution_constraints", {})
    if (
        constraints.get("host") != "mantis-4090"
        or constraints.get("backend") != "cpu"
        or constraints.get("cuda_visible_devices") != ""
        or constraints.get("serial") is not True
        or constraints.get("seeds_in_order")
        != [G3_RETREAT_FAILURE_TELEMETRY_SEED]
        or constraints.get("attempt_count") != 1
        or constraints.get("retry_count") != 0
        or constraints.get("capture") is not False
        or constraints.get("fresh_paths_only") is not True
        or constraints.get("no_overwrite") is not True
        or constraints.get("stop_on_safety_failure") is not True
        or constraints.get("stop_on_infrastructure_failure") is not True
        or constraints.get("no_physics_step_after_first_detected_failure")
        is not True
        or constraints.get("preserve_v129_immutable") is not True
    ):
        raise RuntimeError("failure-telemetry authorization constraint drift")
    return "seed1630_retreat_failure_telemetry"


def validate_release_retreat_boundary_execution_contract(
    contract: dict[str, Any],
    authorization: dict[str, Any],
    *,
    planning_contract_sha256: str,
    failure_contract_sha256: str,
    failure_authorization_sha256: str,
    seed: int,
    generation_mode: str,
    capture: bool,
    backend: str,
    cuda_visible_devices: str | None,
) -> str:
    """Validate the single-attempt WP-G3-CORR-015 invocation."""

    if contract.get("work_package_id") != (
        RELEASE_RETREAT_BOUNDARY_WORK_PACKAGE
    ):
        raise RuntimeError("boundary-trace work-package drift")
    if contract.get("status") != "PLANNED_FROZEN_NOT_EXECUTED":
        raise RuntimeError("boundary-trace planning status drift")
    variable = contract.get("single_primary_variable", {})
    if (
        variable.get("baseline")
        != "first-failure collision-time telemetry only"
        or variable.get("candidate")
        != "cached_release_retreat_boundary_contact_trace_v1"
    ):
        raise RuntimeError("boundary-trace primary-variable drift")
    run = contract.get("diagnostic_run", {})
    if (
        run.get("seeds_in_order") != [G3_RELEASE_RETREAT_BOUNDARY_SEED]
        or run.get("attempt_count") != 1
        or run.get("backend") != "cpu"
        or run.get("cuda_visible_devices") != ""
        or run.get("serial") is not True
        or run.get("retry_count") != 0
        or run.get("capture") is not False
        or run.get("stop_on_safety_failure") is not True
        or run.get("stop_on_infrastructure_failure") is not True
        or run.get("no_physics_step_after_first_detected_failure") is not True
        or run.get("fresh_paths_only") is not True
        or run.get("no_overwrite") is not True
    ):
        raise RuntimeError("boundary-trace run isolation drift")
    trace = contract.get("boundary_trace_contract", {})
    if (
        trace.get("artifact_name")
        != "release_retreat_boundary_trace.json"
        or trace.get("target_pair")
        != RELEASE_RETREAT_BOUNDARY_TARGET_PAIR
        or trace.get("selected_bowl") != "bowl3"
        or trace.get("supporting_nonselected_bowl") != "bowl2"
        or trace.get("active_side") != "left"
        or trace.get("ordered_snapshot_labels")
        != [
            "final_pre_release",
            "immediate_post_release",
            "pre_retreat",
            "retreat_step_1",
            "retreat_step_2",
        ]
        or trace.get("numeric_requirements", {}).get(
            "commanded_qpos_length"
        )
        != 18
        or trace.get("numeric_requirements", {}).get(
            "robot_qpos_length"
        )
        != 18
        or trace.get("numeric_requirements", {}).get(
            "observer_policy_step_delta"
        )
        != 0
        or trace.get("numeric_requirements", {}).get(
            "observer_physics_step_delta"
        )
        != 0
    ):
        raise RuntimeError("boundary-trace schema drift")
    entry = contract.get("entry_evidence", {})
    frozen = contract.get("frozen_source_identity", {})
    if (
        entry.get("predecessor_planning_contract_sha256")
        != failure_contract_sha256
        or entry.get("predecessor_execution_authorization_sha256")
        != failure_authorization_sha256
        or frozen.get("failure_telemetry_contract_sha256")
        != failure_contract_sha256
        or frozen.get("failure_telemetry_authorization_sha256")
        != failure_authorization_sha256
        or frozen.get("core_source_sha256")
        != "4bc3284423d30dac332e2f529fea42ab6ad28622d3bfa7f6ad4068beeeb7d046"
    ):
        raise RuntimeError("boundary-trace predecessor binding drift")
    if (
        seed != G3_RELEASE_RETREAT_BOUNDARY_SEED
        or generation_mode != "probe"
        or capture
        or backend != "cpu"
        or cuda_visible_devices != ""
    ):
        raise RuntimeError("boundary-trace invocation isolation drift")

    if authorization.get("work_package_id") != (
        RELEASE_RETREAT_BOUNDARY_WORK_PACKAGE
    ):
        raise RuntimeError("boundary-trace authorization package drift")
    if authorization.get("planning_contract_sha256") != (
        planning_contract_sha256
    ):
        raise RuntimeError("boundary-trace authorization hash drift")
    if authorization.get("authorization_status") != (
        "AUTHORIZED_GATED_EXECUTION"
    ):
        raise RuntimeError("boundary-trace execution is not authorized")
    if authorization.get("authorization_provenance", {}).get("kind") != (
        "user_stated"
    ):
        raise RuntimeError("boundary-trace authorization provenance drift")
    actions = authorization.get("authorized_actions", {})
    if (
        actions.get("create_versioned_observer_code") is not True
        or actions.get("create_tests_and_receipts") is not True
        or actions.get("run_seed1630_once_after_code_gate_acceptance")
        is not True
    ):
        raise RuntimeError("boundary-trace required action is not authorized")
    forbidden = (
        "change_controller",
        "change_safety_predicate_or_threshold",
        "change_task_or_physics",
        "run_source_collection",
        "export_dataset",
        "train",
        "run_on_amd_rocm",
        "operate_real_hardware",
        "stop_other_users_processes",
        "contact_external_parties",
        "open_github_pull_request",
        "publish",
    )
    if any(actions.get(name) is not False for name in forbidden):
        raise RuntimeError("boundary-trace forbidden action drift")
    constraints = authorization.get("execution_constraints", {})
    if (
        constraints.get("host") != "mantis-4090"
        or constraints.get("backend") != "cpu"
        or constraints.get("cuda_visible_devices") != ""
        or constraints.get("serial") is not True
        or constraints.get("seeds_in_order")
        != [G3_RELEASE_RETREAT_BOUNDARY_SEED]
        or constraints.get("attempt_count") != 1
        or constraints.get("retry_count") != 0
        or constraints.get("capture") is not False
        or constraints.get("fresh_paths_only") is not True
        or constraints.get("no_overwrite") is not True
        or constraints.get("stop_on_safety_failure") is not True
        or constraints.get("stop_on_infrastructure_failure") is not True
        or constraints.get("no_physics_step_after_first_detected_failure")
        is not True
        or constraints.get("preserve_v130_immutable") is not True
        or constraints.get(
            "observer_may_only_read_cached_state_and_write_receipt"
        )
        is not True
    ):
        raise RuntimeError("boundary-trace authorization constraint drift")
    return "seed1630_release_retreat_boundary_trace"


def _vector(value: Any) -> list[float]:
    if hasattr(value, "detach"):
        value = value.detach()
    if hasattr(value, "cpu"):
        value = value.cpu()
    if hasattr(value, "numpy"):
        value = value.numpy()
    import numpy as np

    return np.asarray(value, dtype=float).reshape(-1).tolist()


def _dof_indices(robot: Any, names: list[str]) -> list[int]:
    indices: list[int] = []
    for name in names:
        values = _vector(robot.get_joint(name).dofs_idx_local)
        if len(values) != 1:
            raise RuntimeError(f"expected one DOF for {name}, got {values}")
        indices.append(int(values[0]))
    return indices


def _read_dofs(robot: Any, indices: list[int]) -> list[float]:
    try:
        return _vector(robot.get_dofs_position(dofs_idx_local=indices))
    except TypeError:
        return _vector(robot.get_dofs_position(indices))


def build_interpolation_start(
    *,
    readback: Sequence[float],
    previous_action: Sequence[float],
    arm_indices: Sequence[int],
    gripper_indices: Sequence[int],
    expected_length: int,
) -> list[float]:
    """Build the per-DOF interpolation start vector for a combined arm+gripper move.

    Arm DOFs keep their actual readback so the arm interpolation still starts from the
    true joint state.  Gripper DOFs take the previously *commanded* action rather than
    the post-contact readback: once a clamp closes around a bowl the two finger
    readbacks drift asymmetrically, and seeding the next gripper move from that readback
    would inject an asymmetric command.  Using the last command keeps the gripper
    interpolation symmetric and continuous across contact.

    Pure (no Genesis, no NumPy) so it can be unit-tested in isolation.
    """
    if (
        not isinstance(expected_length, int)
        or isinstance(expected_length, bool)
        or expected_length <= 0
    ):
        raise ValueError("expected_length must be a positive integer")
    if len(readback) != expected_length:
        raise ValueError(
            f"readback length must be {expected_length}, got {len(readback)}"
        )
    if len(previous_action) != expected_length:
        raise ValueError(
            f"previous_action length must be {expected_length}, got {len(previous_action)}"
        )
    arm_set: set[int] = set()
    gripper_set: set[int] = set()
    for label, raw_collection, seen in (
        ("arm", arm_indices, arm_set),
        ("gripper", gripper_indices, gripper_set),
    ):
        for raw in raw_collection:
            if isinstance(raw, bool) or not isinstance(raw, int):
                raise ValueError(f"{label} index must be an integer, got {raw!r}")
            if raw < 0 or raw >= expected_length:
                raise ValueError(
                    f"{label} index {raw} is out of range [0, {expected_length})"
                )
            if raw in seen:
                raise ValueError(f"duplicate {label} index {raw}")
            seen.add(raw)
    overlap = sorted(arm_set & gripper_set)
    if overlap:
        raise ValueError(f"arm and gripper indices overlap: {overlap}")
    start = [float(value) for value in readback]
    if not all(math.isfinite(value) for value in start):
        raise ValueError("readback contains a non-finite value")
    previous = [float(value) for value in previous_action]
    if not all(math.isfinite(value) for value in previous):
        raise ValueError("previous_action contains a non-finite value")
    for index in gripper_indices:
        start[index] = previous[index]
    return start


def validate_consecutive_left_transition_contract(
    raw: dict[str, Any],
) -> dict[str, Any]:
    """Validate and normalize the consecutive-left high-clearance route contract.

    This is pure Python so contract drift can fail before Genesis is imported.
    """
    if not isinstance(raw, dict):
        raise ValueError(
            "consecutive_left_inter_bowl_transition must be an object"
        )
    protocol_version = raw.get("protocol_version")
    if (
        not isinstance(protocol_version, str)
        or not protocol_version.strip()
    ):
        raise ValueError(
            "consecutive-left transition protocol_version must be non-blank"
        )
    if raw.get("enabled") is not True:
        raise ValueError(
            "consecutive-left transition must be explicitly enabled"
        )
    clearance_raw = raw.get("clearance_tcp_z_m")
    if isinstance(clearance_raw, bool) or not isinstance(
        clearance_raw, (int, float)
    ):
        raise ValueError(
            "consecutive-left clearance_tcp_z_m must be finite numeric"
        )
    clearance = float(clearance_raw)
    if not math.isfinite(clearance) or not 0.90 < clearance <= 1.20:
        raise ValueError(
            "consecutive-left clearance_tcp_z_m must satisfy "
            "0.90 < value <= 1.20"
        )
    waypoint_count = raw.get("cartesian_waypoints_per_segment")
    if (
        isinstance(waypoint_count, bool)
        or not isinstance(waypoint_count, int)
        or not 1 <= waypoint_count <= 32
    ):
        raise ValueError(
            "consecutive-left cartesian_waypoints_per_segment must be "
            "an integer in [1, 32]"
        )
    duration_raw = raw.get("segment_minimum_duration_s")
    if isinstance(duration_raw, bool) or not isinstance(
        duration_raw, (int, float)
    ):
        raise ValueError(
            "consecutive-left segment_minimum_duration_s must be finite numeric"
        )
    duration = float(duration_raw)
    if not math.isfinite(duration) or not 0.0 < duration <= 5.0:
        raise ValueError(
            "consecutive-left segment_minimum_duration_s must satisfy "
            "0 < value <= 5"
        )
    return {
        "protocol_version": protocol_version.strip(),
        "enabled": True,
        "clearance_tcp_z_m": clearance,
        "cartesian_waypoints_per_segment": waypoint_count,
        "segment_minimum_duration_s": duration,
    }


def build_consecutive_left_transition_positions(
    *,
    previous_retreat_position_xyz_m: Sequence[float],
    next_front_clearance_position_xyz_m: Sequence[float],
    clearance_tcp_z_m: float,
    cartesian_waypoints_per_segment: int,
) -> dict[str, list[tuple[float, float, float]]]:
    """Build the deterministic Cartesian route around an existing bowl stack.

    The returned route has three translational segments plus a one-pose
    high-clearance reorientation stage.  The first and last poses remain bound
    to the caller's prior retreat and unchanged next front-clearance geometry.
    """
    if (
        isinstance(cartesian_waypoints_per_segment, bool)
        or not isinstance(cartesian_waypoints_per_segment, int)
        or not 1 <= cartesian_waypoints_per_segment <= 32
    ):
        raise ValueError(
            "cartesian_waypoints_per_segment must be an integer in [1, 32]"
        )
    raw_positions = (
        ("previous_retreat_position_xyz_m", previous_retreat_position_xyz_m),
        (
            "next_front_clearance_position_xyz_m",
            next_front_clearance_position_xyz_m,
        ),
    )
    normalized: dict[str, tuple[float, float, float]] = {}
    for label, raw_position in raw_positions:
        if len(raw_position) != 3:
            raise ValueError(f"{label} must contain exactly three values")
        values = tuple(float(value) for value in raw_position)
        if not all(math.isfinite(value) for value in values):
            raise ValueError(f"{label} contains a non-finite value")
        normalized[label] = values
    if isinstance(clearance_tcp_z_m, bool) or not isinstance(
        clearance_tcp_z_m, (int, float)
    ):
        raise ValueError("clearance_tcp_z_m must be finite numeric")
    clearance = float(clearance_tcp_z_m)
    previous = normalized["previous_retreat_position_xyz_m"]
    next_front = normalized["next_front_clearance_position_xyz_m"]
    if not math.isfinite(clearance):
        raise ValueError("clearance_tcp_z_m must be finite numeric")
    if clearance <= max(previous[2], next_front[2]):
        raise ValueError(
            "clearance_tcp_z_m must be above both transition endpoints"
        )

    vertical_end = (previous[0], previous[1], clearance)
    lateral_end = (next_front[0], next_front[1], clearance)

    def interpolate(
        start: tuple[float, float, float],
        end: tuple[float, float, float],
    ) -> list[tuple[float, float, float]]:
        path: list[tuple[float, float, float]] = []
        for waypoint in range(1, cartesian_waypoints_per_segment + 1):
            alpha = waypoint / cartesian_waypoints_per_segment
            path.append(
                tuple(
                    start[axis] + alpha * (end[axis] - start[axis])
                    for axis in range(3)
                )
            )
        return path

    return {
        "vertical_clearance": interpolate(previous, vertical_end),
        "reorient_at_clearance": [vertical_end],
        "lateral_clearance": interpolate(vertical_end, lateral_end),
        "descend_to_front_clearance": interpolate(lateral_end, next_front),
    }


def quaternion_slerp_wxyz(
    start_wxyz: Sequence[float],
    end_wxyz: Sequence[float],
    alpha: float,
) -> tuple[float, float, float, float]:
    """Return a normalized sign-invariant WXYZ quaternion interpolation."""
    if len(start_wxyz) != 4 or len(end_wxyz) != 4:
        raise ValueError("SLERP endpoints must each contain exactly four values")
    if isinstance(alpha, bool) or not isinstance(alpha, (int, float)):
        raise ValueError("SLERP alpha must be finite numeric")
    interpolation = float(alpha)
    if not math.isfinite(interpolation) or not 0.0 <= interpolation <= 1.0:
        raise ValueError("SLERP alpha must satisfy 0 <= alpha <= 1")

    endpoints: list[list[float]] = []
    for label, raw in (("start", start_wxyz), ("end", end_wxyz)):
        values = [float(value) for value in raw]
        if not all(math.isfinite(value) for value in values):
            raise ValueError(f"SLERP {label} quaternion contains non-finite data")
        norm = math.sqrt(sum(value * value for value in values))
        if norm <= 1e-12:
            raise ValueError(f"SLERP {label} quaternion has zero norm")
        endpoints.append([value / norm for value in values])
    start, end = endpoints
    dot = sum(left * right for left, right in zip(start, end))
    if dot < 0.0:
        end = [-value for value in end]
        dot = -dot
    dot = min(1.0, max(-1.0, dot))
    if dot > 0.9995:
        result = [
            left + interpolation * (right - left)
            for left, right in zip(start, end)
        ]
    else:
        theta = math.acos(dot)
        sin_theta = math.sin(theta)
        start_weight = math.sin((1.0 - interpolation) * theta) / sin_theta
        end_weight = math.sin(interpolation * theta) / sin_theta
        result = [
            start_weight * left + end_weight * right
            for left, right in zip(start, end)
        ]
    result_norm = math.sqrt(sum(value * value for value in result))
    return tuple(value / result_norm for value in result)


def normalize_quaternion_wxyz(
    quaternion_wxyz: Sequence[float],
) -> tuple[float, float, float, float]:
    """Normalize WXYZ and choose a deterministic sign representative."""

    if len(quaternion_wxyz) != 4:
        raise ValueError("quaternion must contain exactly four values")
    values = tuple(float(value) for value in quaternion_wxyz)
    if not all(math.isfinite(value) for value in values):
        raise ValueError("quaternion contains a non-finite value")
    norm = math.sqrt(sum(value * value for value in values))
    if norm <= 1e-12:
        raise ValueError("quaternion has zero norm")
    normalized = tuple(value / norm for value in values)
    for value in normalized:
        if abs(value) > 1e-15:
            if value < 0.0:
                normalized = tuple(-item for item in normalized)
            break
    return normalized


def quaternion_multiply_wxyz(
    left_wxyz: Sequence[float],
    right_wxyz: Sequence[float],
) -> tuple[float, float, float, float]:
    """Hamilton product for normalized or unnormalized WXYZ quaternions."""

    if len(left_wxyz) != 4 or len(right_wxyz) != 4:
        raise ValueError("quaternion product requires two four-value inputs")
    aw, ax, ay, az = (float(value) for value in left_wxyz)
    bw, bx, by, bz = (float(value) for value in right_wxyz)
    values = (aw, ax, ay, az, bw, bx, by, bz)
    if not all(math.isfinite(value) for value in values):
        raise ValueError("quaternion product contains a non-finite value")
    return (
        aw * bw - ax * bx - ay * by - az * bz,
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
    )


def rotate_vector_wxyz(
    quaternion_wxyz: Sequence[float],
    vector_xyz: Sequence[float],
) -> tuple[float, float, float]:
    """Rotate one XYZ vector by a WXYZ quaternion."""

    if len(vector_xyz) != 3:
        raise ValueError("rotation vector must contain exactly three values")
    vector = tuple(float(value) for value in vector_xyz)
    if not all(math.isfinite(value) for value in vector):
        raise ValueError("rotation vector contains a non-finite value")
    q = normalize_quaternion_wxyz(quaternion_wxyz)
    conjugate = (q[0], -q[1], -q[2], -q[3])
    rotated = quaternion_multiply_wxyz(
        quaternion_multiply_wxyz(q, (0.0, *vector)),
        conjugate,
    )
    return (rotated[1], rotated[2], rotated[3])


def relative_pose_wxyz(
    *,
    reference_position_xyz_m: Sequence[float],
    reference_quaternion_wxyz: Sequence[float],
    target_position_xyz_m: Sequence[float],
    target_quaternion_wxyz: Sequence[float],
) -> dict[str, list[float]]:
    """Express a target pose in one reference pose's coordinate frame."""

    if len(reference_position_xyz_m) != 3 or len(target_position_xyz_m) != 3:
        raise ValueError("relative-pose positions must contain three values")
    reference_position = tuple(
        float(value) for value in reference_position_xyz_m
    )
    target_position = tuple(float(value) for value in target_position_xyz_m)
    if not all(
        math.isfinite(value)
        for value in (*reference_position, *target_position)
    ):
        raise ValueError("relative-pose position contains a non-finite value")
    reference_quaternion = normalize_quaternion_wxyz(
        reference_quaternion_wxyz
    )
    target_quaternion = normalize_quaternion_wxyz(target_quaternion_wxyz)
    inverse_reference = (
        reference_quaternion[0],
        -reference_quaternion[1],
        -reference_quaternion[2],
        -reference_quaternion[3],
    )
    world_delta = tuple(
        target - reference
        for target, reference in zip(target_position, reference_position)
    )
    relative_translation = rotate_vector_wxyz(
        inverse_reference,
        world_delta,
    )
    relative_quaternion = normalize_quaternion_wxyz(
        quaternion_multiply_wxyz(
            inverse_reference,
            target_quaternion,
        )
    )
    return {
        "translation_xyz_m": list(relative_translation),
        "quaternion_wxyz": list(relative_quaternion),
    }


def pose_delta_wxyz(
    start_position_xyz_m: Sequence[float],
    start_quaternion_wxyz: Sequence[float],
    end_position_xyz_m: Sequence[float],
    end_quaternion_wxyz: Sequence[float],
) -> dict[str, Any]:
    """Return sign-invariant world translation and rotation deltas."""

    if len(start_position_xyz_m) != 3 or len(end_position_xyz_m) != 3:
        raise ValueError("pose-delta positions must contain three values")
    start_position = tuple(float(value) for value in start_position_xyz_m)
    end_position = tuple(float(value) for value in end_position_xyz_m)
    translation = tuple(
        end - start for start, end in zip(start_position, end_position)
    )
    if not all(math.isfinite(value) for value in translation):
        raise ValueError("pose-delta translation contains a non-finite value")
    start_quaternion = normalize_quaternion_wxyz(start_quaternion_wxyz)
    end_quaternion = normalize_quaternion_wxyz(end_quaternion_wxyz)
    dot = abs(
        sum(
            left * right
            for left, right in zip(start_quaternion, end_quaternion)
        )
    )
    rotation_angle = 2.0 * math.acos(min(1.0, max(-1.0, dot)))
    return {
        "translation_xyz_m": list(translation),
        "translation_norm_m": math.sqrt(
            sum(value * value for value in translation)
        ),
        "z_delta_m": translation[2],
        "rotation_angle_rad": rotation_angle,
    }


def build_consecutive_left_transition_ik_candidates(
    *,
    route_positions: dict[str, list[tuple[float, float, float]]],
    grasp_orientation_wxyz: Sequence[float],
    transit_orientation_wxyz: Sequence[float],
) -> dict[str, list[dict[str, Any]]]:
    """Build the frozen orientation-schedule matrix on one unchanged route."""
    expected_stages = (
        "vertical_clearance",
        "reorient_at_clearance",
        "lateral_clearance",
        "descend_to_front_clearance",
    )
    if tuple(route_positions) != expected_stages:
        raise ValueError(
            "route_positions must contain the exact consecutive-left stages"
        )
    normalized_positions: dict[str, list[tuple[float, float, float]]] = {}
    for stage in expected_stages:
        raw_stage = route_positions[stage]
        if not isinstance(raw_stage, list) or not raw_stage:
            raise ValueError(f"route stage {stage} must be a non-empty list")
        positions: list[tuple[float, float, float]] = []
        for raw_position in raw_stage:
            if len(raw_position) != 3:
                raise ValueError(f"route stage {stage} contains malformed position")
            position = tuple(float(value) for value in raw_position)
            if not all(math.isfinite(value) for value in position):
                raise ValueError(f"route stage {stage} contains non-finite position")
            positions.append(position)
        normalized_positions[stage] = positions
    if len(normalized_positions["reorient_at_clearance"]) != 1:
        raise ValueError("negative-control reorientation must contain one pose")
    lateral_count = len(normalized_positions["lateral_clearance"])
    descent_count = len(normalized_positions["descend_to_front_clearance"])
    if lateral_count != descent_count:
        raise ValueError("lateral and descent waypoint counts must match")

    grasp = quaternion_slerp_wxyz(
        grasp_orientation_wxyz,
        grasp_orientation_wxyz,
        0.0,
    )
    transit = quaternion_slerp_wxyz(
        transit_orientation_wxyz,
        transit_orientation_wxyz,
        0.0,
    )

    def pose_rows(
        stage: str,
        positions: Sequence[tuple[float, float, float]],
        orientations: Sequence[tuple[float, float, float, float]],
    ) -> list[dict[str, Any]]:
        if len(positions) != len(orientations):
            raise ValueError(f"{stage} position/orientation lengths differ")
        return [
            {
                "stage": stage,
                "waypoint_index": index,
                "waypoint_count": len(positions),
                "position_xyz_m": position,
                "orientation_wxyz": orientation,
            }
            for index, (position, orientation) in enumerate(
                zip(positions, orientations),
                start=1,
            )
        ]

    vertical = normalized_positions["vertical_clearance"]
    reorient = normalized_positions["reorient_at_clearance"]
    lateral = normalized_positions["lateral_clearance"]
    descent = normalized_positions["descend_to_front_clearance"]
    vertical_grasp = pose_rows(
        "vertical_clearance",
        vertical,
        [grasp] * len(vertical),
    )
    negative_control = [
        *vertical_grasp,
        *pose_rows("reorient_at_clearance", reorient, [transit]),
        *pose_rows("lateral_clearance", lateral, [transit] * lateral_count),
        *pose_rows(
            "descend_to_front_clearance",
            descent,
            [transit] * descent_count,
        ),
    ]
    lateral_slerp = [
        quaternion_slerp_wxyz(
            grasp,
            transit,
            waypoint / lateral_count,
        )
        for waypoint in range(1, lateral_count + 1)
    ]
    descent_slerp = [
        quaternion_slerp_wxyz(
            grasp,
            transit,
            waypoint / descent_count,
        )
        for waypoint in range(1, descent_count + 1)
    ]
    split_lateral = [
        quaternion_slerp_wxyz(
            grasp,
            transit,
            0.5 * waypoint / lateral_count,
        )
        for waypoint in range(1, lateral_count + 1)
    ]
    split_descent = [
        quaternion_slerp_wxyz(
            grasp,
            transit,
            0.5 + 0.5 * waypoint / descent_count,
        )
        for waypoint in range(1, descent_count + 1)
    ]
    return {
        G3_LEFT_IK_MATRIX_CANDIDATES[0]: negative_control,
        G3_LEFT_IK_MATRIX_CANDIDATES[1]: [
            *vertical_grasp,
            *pose_rows("lateral_clearance", lateral, lateral_slerp),
            *pose_rows(
                "descend_to_front_clearance",
                descent,
                [transit] * descent_count,
            ),
        ],
        G3_LEFT_IK_MATRIX_CANDIDATES[2]: [
            *vertical_grasp,
            *pose_rows("lateral_clearance", lateral, [grasp] * lateral_count),
            *pose_rows(
                "descend_to_front_clearance",
                descent,
                descent_slerp,
            ),
        ],
        G3_LEFT_IK_MATRIX_CANDIDATES[3]: [
            *vertical_grasp,
            *pose_rows("lateral_clearance", lateral, split_lateral),
            *pose_rows(
                "descend_to_front_clearance",
                descent,
                split_descent,
            ),
        ],
    }


def canonicalize_path_gripper_commands(
    *,
    path: Sequence[Sequence[float]],
    command_target: Sequence[float],
    gripper_indices: Sequence[int],
    expected_width: int,
) -> list[list[float]]:
    """Canonicalize a 2D motion path so every row's gripper DOFs share one target.

    Each row's arm DOFs are copied verbatim, preserving the upstream arm path
    exactly.  The gripper DOFs (the four clamp indices across both arms) on
    *every* row are overwritten with ``command_target``'s values, so a single
    symmetric command governs the gripper throughout the whole path.

    This closes the asymmetry that an RRTConnect transport path introduced: the
    planner was seeded from the post-contact readback, whose two clamp fingers
    had drifted to different widths, so the rows it returned carried an
    asymmetric gripper spread (max left/right split).  Re-stamping the gripper
    columns from a symmetric target keeps the executed action symmetric and
    continuous with the surrounding interpolation.

    Pure (no Genesis, no NumPy) so it can be unit-tested in isolation.  The
    input path and target are never mutated; a fresh list of fresh rows is
    returned.
    """
    if (
        not isinstance(expected_width, int)
        or isinstance(expected_width, bool)
        or expected_width <= 0
    ):
        raise ValueError("expected_width must be a positive integer")
    if len(path) == 0:
        raise ValueError("path must be a non-empty 2D sequence of rows")
    gripper_set: set[int] = set()
    for raw in gripper_indices:
        if isinstance(raw, bool) or not isinstance(raw, int):
            raise ValueError(f"gripper index must be an integer, got {raw!r}")
        if raw < 0 or raw >= expected_width:
            raise ValueError(
                f"gripper index {raw} is out of range [0, {expected_width})"
            )
        if raw in gripper_set:
            raise ValueError(f"duplicate gripper index {raw}")
        gripper_set.add(raw)
    target_values = [float(value) for value in command_target]
    if len(target_values) != expected_width:
        raise ValueError(
            f"command_target length must be {expected_width}, "
            f"got {len(target_values)}"
        )
    if not all(math.isfinite(value) for value in target_values):
        raise ValueError("command_target contains a non-finite value")
    gripper_targets = {index: target_values[index] for index in gripper_indices}
    canonicalized: list[list[float]] = []
    for row_index, row in enumerate(path):
        row_values = [float(value) for value in row]
        if len(row_values) != expected_width:
            raise ValueError(
                f"row {row_index} length must be {expected_width}, "
                f"got {len(row_values)}"
            )
        if not all(math.isfinite(value) for value in row_values):
            raise ValueError(f"row {row_index} contains a non-finite value")
        for index, value in gripper_targets.items():
            row_values[index] = value
        canonicalized.append(row_values)
    return canonicalized


def _contact_count(contact_info: Any) -> int:
    if not isinstance(contact_info, dict) or "geom_a" not in contact_info:
        raise RuntimeError("Genesis get_contacts returned an unexpected structure")
    shape = getattr(contact_info["geom_a"], "shape", None)
    if shape is None or len(shape) < 1:
        raise RuntimeError("Genesis contact geom_a has no row dimension")
    return int(shape[-1] if len(shape) > 1 else shape[0])


def _robot_geom_label(geom: Any) -> str:
    metadata = getattr(geom, "metadata", {})
    metadata = metadata if isinstance(metadata, dict) else {}
    suffix = metadata.get("name")
    if not suffix:
        suffix = (
            "source_mesh_collision"
            if metadata.get("mesh_path")
            else f"anonymous_{getattr(getattr(geom, 'type', None), 'name', 'geom')}"
        )
    return f"mantis:{geom.link.name}:{suffix}"


def _contact_pairs(
    contact_info: Any,
    labels: dict[int, str],
) -> list[str]:
    pairs: list[str] = []
    for geom_a, geom_b in zip(
        _vector(contact_info["geom_a"]),
        _vector(contact_info["geom_b"]),
    ):
        pair = sorted(
            (
                labels.get(int(geom_a), f"geom:{int(geom_a)}"),
                labels.get(int(geom_b), f"geom:{int(geom_b)}"),
            )
        )
        pairs.append(" <> ".join(pair))
    return pairs


def _self_contact_pairs(
    contact_info: Any,
    labels: dict[int, str],
) -> list[str]:
    result: list[str] = []
    for pair in _contact_pairs(contact_info, labels):
        pair_labels = pair.split(" <> ")
        if not all(label.startswith("mantis:") for label in pair_labels):
            continue
        if any(
            all(label.startswith(f"mantis:{side}_clamp") for label in pair_labels)
            for side in SIDES
        ):
            continue
        result.append(pair)
    return result


def _contact_diagnostics(contact_info: Any) -> dict[str, Any]:
    diagnostics: dict[str, Any] = {}
    for key in ("penetration", "force_a", "force_b", "normal", "position"):
        if key not in contact_info:
            continue
        value = contact_info[key]
        shape = tuple(int(size) for size in getattr(value, "shape", ()))
        diagnostics[key] = {
            "shape": shape,
            "values": _vector(value),
        }
    return diagnostics


def _angular_velocity(
    previous_quaternion: Any,
    quaternion: Any,
    elapsed_s: float,
) -> list[float]:
    import numpy as np

    q0 = np.asarray(previous_quaternion, dtype=float)
    q1 = np.asarray(quaternion, dtype=float)
    q0 /= np.linalg.norm(q0)
    q1 /= np.linalg.norm(q1)
    relative = np.asarray(
        [
            q1[0] * q0[0] + np.dot(q1[1:], q0[1:]),
            -q1[0] * q0[1] + q0[0] * q1[1] - q1[2] * q0[3] + q1[3] * q0[2],
            -q1[0] * q0[2] + q0[0] * q1[2] - q1[3] * q0[1] + q1[1] * q0[3],
            -q1[0] * q0[3] + q0[0] * q1[3] - q1[1] * q0[2] + q1[2] * q0[1],
        ],
        dtype=float,
    )
    if relative[0] < 0.0:
        relative *= -1.0
    vector_norm = float(np.linalg.norm(relative[1:]))
    if vector_norm < 1e-12:
        return [0.0, 0.0, 0.0]
    angle = 2.0 * math.atan2(vector_norm, min(1.0, max(-1.0, relative[0])))
    axis = relative[1:] / vector_norm
    return (axis * (angle / elapsed_s)).tolist()


def _build_claim_boundary(generation_mode: str, seed: int, is_canonical_g1: bool, run_id: str) -> str:
    """Build claim boundary text based on generation mode."""
    if generation_mode == "probe":
        return (
            f"Probe calibration run {run_id} (seed {seed}) completed successfully and generated "
            f"a replay plan for two-stage generation. This is a diagnostic-only probe result, "
            f"not a G1 success, learned policy, multi-seed evidence, or ROCm claim. "
            f"The replay plan captures exact placement offsets and candidate choices for replay."
        )
    elif generation_mode == "replay":
        return (
            f"Replay run {run_id} (seed {seed}) successfully executed a frozen probe plan "
            f"using deterministic replay mode. This is a two-stage replay result, not a G1 success, "
            f"learned policy, multi-seed evidence, or ROCm claim. The replay used exact candidate "
            f"indices and frozen XY offsets from the probe plan."
        )
    else:  # online
        if is_canonical_g1:
            return (
                f"Complete strict scripted G1 for seed {seed} using contact-triggered "
                f"idealized suction transport in one Genesis scene (run {run_id}); "
                f"no learned-policy or ROCm execution claim."
            )
        else:
            return (
                f"Strict scripted stack-bowls episode for seed {seed} (run {run_id}), a "
                f"training-data portability run; it is not the canonical G1 "
                f"seed 1 episode and makes no canonical G1, learned-policy, or "
                f"ROCm execution claim."
            )


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if (args.corrected_expert_contract is None) != (
        args.corrected_expert_authorization is None
    ):
        parser.error(
            "--corrected-expert-contract and "
            "--corrected-expert-authorization must be provided together"
        )
    corrected_expert_requested = args.corrected_expert_contract is not None
    if (args.level1_release_diagnostic_contract is None) != (
        args.level1_release_diagnostic_authorization is None
    ):
        parser.error(
            "--level1-release-diagnostic-contract and "
            "--level1-release-diagnostic-authorization must be provided together"
        )
    level1_release_requested = (
        args.level1_release_diagnostic_contract is not None
    )
    if (args.failure_telemetry_contract is None) != (
        args.failure_telemetry_authorization is None
    ):
        parser.error(
            "--failure-telemetry-contract and "
            "--failure-telemetry-authorization must be provided together"
        )
    failure_telemetry_requested = (
        args.failure_telemetry_contract is not None
    )
    if (args.release_retreat_boundary_contract is None) != (
        args.release_retreat_boundary_authorization is None
    ):
        parser.error(
            "--release-retreat-boundary-contract and "
            "--release-retreat-boundary-authorization must be provided together"
        )
    release_retreat_boundary_requested = (
        args.release_retreat_boundary_contract is not None
    )
    if corrected_expert_requested and level1_release_requested:
        parser.error(
            "corrected-expert and level1-release contracts are mutually exclusive"
        )
    if failure_telemetry_requested and (
        corrected_expert_requested or not level1_release_requested
    ):
        parser.error(
            "failure telemetry requires the predecessor level1-release "
            "contracts and is incompatible with corrected-expert execution"
        )
    if release_retreat_boundary_requested and not failure_telemetry_requested:
        parser.error(
            "release-retreat boundary tracing requires the complete "
            "WP-G3-CORR-014 failure-telemetry invocation"
        )
    if level1_release_requested:
        assert args.level1_release_diagnostic_contract is not None
        assert args.level1_release_diagnostic_authorization is not None
        for path, label in (
            (
                args.level1_release_diagnostic_contract,
                "level1-release diagnostic contract",
            ),
            (
                args.level1_release_diagnostic_authorization,
                "level1-release diagnostic authorization",
            ),
        ):
            if not path.is_file():
                parser.error(f"{label} does not exist: {path}")
    if failure_telemetry_requested:
        assert args.failure_telemetry_contract is not None
        assert args.failure_telemetry_authorization is not None
        for path, label in (
            (
                args.failure_telemetry_contract,
                "failure telemetry contract",
            ),
            (
                args.failure_telemetry_authorization,
                "failure telemetry authorization",
            ),
        ):
            if not path.is_file():
                parser.error(f"{label} does not exist: {path}")
    if release_retreat_boundary_requested:
        assert args.release_retreat_boundary_contract is not None
        assert args.release_retreat_boundary_authorization is not None
        for path, label in (
            (
                args.release_retreat_boundary_contract,
                "release-retreat boundary contract",
            ),
            (
                args.release_retreat_boundary_authorization,
                "release-retreat boundary authorization",
            ),
        ):
            if not path.is_file():
                parser.error(f"{label} does not exist: {path}")
    if not 1 <= args.cartesian_waypoints <= 16:
        parser.error("--cartesian-waypoints must be in [1, 16]")
    if not 1.0 <= args.transport_duration_s <= 8.0:
        parser.error("--transport-duration-s must be in [1, 8]")
    if not isinstance(args.seed, int) or args.seed < 1:
        parser.error("--seed must be a positive integer")

    # Generation mode validation
    if args.generation_mode == "probe":
        if args.capture:
            parser.error("--capture is forbidden in probe mode")
        if args.seed == G1_CANONICAL_SEED:
            parser.error(f"seed {G1_CANONICAL_SEED} is forbidden in probe mode to protect canonical semantics")
        if not isinstance(args.probe_max_policy_steps, int) or args.probe_max_policy_steps <= 0:
            parser.error("--probe-max-policy-steps must be positive integer")
        if args.replay_plan is not None:
            parser.error("--replay-plan is not allowed in probe mode")
    elif args.generation_mode == "replay":
        if args.replay_plan is None:
            parser.error("--replay-plan is required in replay mode")
        if not args.replay_plan.is_file():
            parser.error(f"--replay-plan file does not exist: {args.replay_plan}")
    elif args.generation_mode == "online":
        if args.replay_plan is not None:
            parser.error("--replay-plan is not allowed in online mode")
    if args.transition_ik_matrix_only:
        if args.generation_mode != "probe":
            parser.error(
                "--transition-ik-matrix-only requires generation-mode=probe"
            )
        if args.seed != G3_LEFT_IK_MATRIX_SEED:
            parser.error(
                "--transition-ik-matrix-only requires frozen seed "
                f"{G3_LEFT_IK_MATRIX_SEED}"
            )
        if not args.transition_ik_matrix_contract.is_file():
            parser.error(
                "matrix contract does not exist: "
                f"{args.transition_ik_matrix_contract}"
            )
    if (
        args.transition_ik_matrix_only
        and args.consecutive_left_orientation_schedule
        != G3_LEFT_DYNAMIC_ORIENTATION_SCHEDULES[0]
    ):
        parser.error(
            "matrix-only and non-default dynamic orientation schedule "
            "are mutually exclusive"
        )
    if (
        args.consecutive_left_orientation_schedule
        != G3_LEFT_DYNAMIC_ORIENTATION_SCHEDULES[0]
    ):
        allowed_modes = (
            {"probe", "replay"}
            if corrected_expert_requested
            else {"probe"}
        )
        if args.generation_mode not in allowed_modes:
            parser.error(
                "non-default consecutive-left orientation schedule "
                f"requires generation-mode in {sorted(allowed_modes)}"
            )
        if args.backend != "cpu":
            parser.error(
                "consecutive-left dynamic execution requires backend=cpu"
            )
        if args.capture and not corrected_expert_requested:
            parser.error(
                "R3 consecutive-left dynamic validation forbids capture"
            )
        if not args.consecutive_left_dynamic_contract.is_file():
            parser.error(
                "dynamic contract does not exist: "
                f"{args.consecutive_left_dynamic_contract}"
            )
        if corrected_expert_requested:
            assert args.corrected_expert_contract is not None
            assert args.corrected_expert_authorization is not None
            for path, label in (
                (args.corrected_expert_contract, "corrected-expert contract"),
                (
                    args.corrected_expert_authorization,
                    "corrected-expert authorization",
                ),
            ):
                if not path.is_file():
                    parser.error(f"{label} does not exist: {path}")
    bowl_urdf = args.bowl_asset_root / "urdf/robotwin_002_bowl_model3.urdf"
    bowl_manifest_path = args.bowl_asset_root / "manifest.json"
    for path in (args.mantis_urdf, bowl_urdf, bowl_manifest_path):
        if not path.is_file():
            parser.error(f"required asset file does not exist: {path}")

    port = load_json(args.port)
    source_task = load_json(args.source_task)
    task = load_json(args.task)
    scene_contract = load_json(args.scene_contract)
    camera_contract = load_json(args.camera_contract)
    bowl_manifest = load_json(bowl_manifest_path)
    consecutive_left_transition_contract = (
        validate_consecutive_left_transition_contract(
            scene_contract["contact_probe"][
                "consecutive_left_inter_bowl_transition"
            ]
        )
    )
    transition_ik_matrix_contract: dict[str, Any] | None = None
    if args.transition_ik_matrix_only:
        transition_ik_matrix_contract = load_json(
            args.transition_ik_matrix_contract
        )
        matrix = transition_ik_matrix_contract.get("matrix", {})
        candidate_ids = [
            candidate.get("candidate_id")
            for candidate in matrix.get("candidates_in_order", [])
        ]
        if transition_ik_matrix_contract.get("work_package_id") != (
            "WP-G3-CORR-009-R2"
        ):
            raise RuntimeError("transition IK matrix work-package drift")
        if matrix.get("seed") != G3_LEFT_IK_MATRIX_SEED:
            raise RuntimeError("transition IK matrix seed drift")
        if matrix.get("backend") != "cpu" or matrix.get(
            "cuda_visible_devices"
        ) != "":
            raise RuntimeError("transition IK matrix isolation drift")
        if matrix.get("capture") is not False or matrix.get(
            "retry_count"
        ) != 0:
            raise RuntimeError("transition IK matrix capture/retry drift")
        if tuple(candidate_ids) != G3_LEFT_IK_MATRIX_CANDIDATES:
            raise RuntimeError("transition IK matrix candidate-order drift")
    consecutive_left_dynamic_contract: dict[str, Any] | None = None
    corrected_expert_contract: dict[str, Any] | None = None
    corrected_expert_authorization: dict[str, Any] | None = None
    corrected_expert_phase: str | None = None
    level1_release_contract: dict[str, Any] | None = None
    level1_release_authorization: dict[str, Any] | None = None
    level1_release_phase: str | None = None
    failure_telemetry_contract: dict[str, Any] | None = None
    failure_telemetry_authorization: dict[str, Any] | None = None
    failure_telemetry_phase: str | None = None
    release_retreat_boundary_contract: dict[str, Any] | None = None
    release_retreat_boundary_authorization: dict[str, Any] | None = None
    release_retreat_boundary_phase: str | None = None
    if (
        args.consecutive_left_orientation_schedule
        != G3_LEFT_DYNAMIC_ORIENTATION_SCHEDULES[0]
    ):
        consecutive_left_dynamic_contract = load_json(
            args.consecutive_left_dynamic_contract
        )
        panel = consecutive_left_dynamic_contract.get(
            "diagnostic_panel",
            {},
        )
        intervention = consecutive_left_dynamic_contract.get(
            "single_intervention",
            {},
        )
        if consecutive_left_dynamic_contract.get("work_package_id") != (
            "WP-G3-CORR-009-R3"
        ):
            raise RuntimeError("dynamic orientation work-package drift")
        if intervention.get("candidate") != (
            args.consecutive_left_orientation_schedule
        ):
            raise RuntimeError("dynamic orientation schedule drift")
        if panel.get("seeds_in_order") != [1039, 1074, 1086, 1208]:
            raise RuntimeError("dynamic orientation seed-panel drift")
        if panel.get("backend") != "cpu" or panel.get(
            "cuda_visible_devices"
        ) != "":
            raise RuntimeError("dynamic orientation isolation drift")
        if panel.get("capture") is not False or panel.get(
            "retry_count"
        ) != 0:
            raise RuntimeError("dynamic orientation capture/retry drift")
        if corrected_expert_requested:
            assert args.corrected_expert_contract is not None
            assert args.corrected_expert_authorization is not None
            corrected_expert_contract = load_json(
                args.corrected_expert_contract
            )
            corrected_expert_authorization = load_json(
                args.corrected_expert_authorization
            )
            corrected_expert_phase = (
                validate_corrected_expert_execution_contract(
                    corrected_expert_contract,
                    corrected_expert_authorization,
                    planning_contract_sha256=sha256_file(
                        args.corrected_expert_contract
                    ),
                    seed=args.seed,
                    generation_mode=args.generation_mode,
                    capture=bool(args.capture),
                    backend=args.backend,
                    cuda_visible_devices=os.environ.get(
                        "CUDA_VISIBLE_DEVICES"
                    ),
                )
            )
            frozen = corrected_expert_contract.get("frozen_invariants", {})
            if frozen.get("source_reset_sampler_sha256") != sha256_file(
                ROOT / "src/mantis_rocm_bridge/stack_bowls_env.py"
            ):
                raise RuntimeError(
                    "corrected-expert source reset sampler hash drift"
                )
            if frozen.get("task_contract_sha256") != sha256_file(args.task):
                raise RuntimeError("corrected-expert task contract hash drift")
            if args.cartesian_waypoints != frozen.get(
                "cartesian_waypoints_per_segment"
            ):
                raise RuntimeError(
                    "corrected-expert Cartesian waypoint count drift"
                )
            if consecutive_left_transition_contract[
                "clearance_tcp_z_m"
            ] != frozen.get("clearance_tcp_z_m"):
                raise RuntimeError(
                    "corrected-expert clearance position-route drift"
                )
        elif level1_release_requested:
            assert args.level1_release_diagnostic_contract is not None
            assert args.level1_release_diagnostic_authorization is not None
            level1_release_contract = load_json(
                args.level1_release_diagnostic_contract
            )
            level1_release_authorization = load_json(
                args.level1_release_diagnostic_authorization
            )
            level1_release_phase = (
                validate_level1_release_execution_contract(
                    level1_release_contract,
                    level1_release_authorization,
                    planning_contract_sha256=sha256_file(
                        args.level1_release_diagnostic_contract
                    ),
                    seed=args.seed,
                    generation_mode=args.generation_mode,
                    capture=bool(args.capture),
                    backend=args.backend,
                    cuda_visible_devices=os.environ.get(
                        "CUDA_VISIBLE_DEVICES"
                    ),
                )
            )
            frozen = level1_release_contract.get("frozen_invariants", {})
            if frozen.get("source_reset_sampler_sha256") != sha256_file(
                ROOT / "src/mantis_rocm_bridge/stack_bowls_env.py"
            ):
                raise RuntimeError(
                    "level1-release source reset sampler hash drift"
                )
            if frozen.get("task_contract_sha256") != sha256_file(args.task):
                raise RuntimeError("level1-release task contract hash drift")
            if frozen.get("scene_contract_sha256") != sha256_file(
                args.scene_contract
            ):
                raise RuntimeError("level1-release scene contract hash drift")
            if frozen.get(
                "orientation_schedule_contract_sha256"
            ) != sha256_file(args.consecutive_left_dynamic_contract):
                raise RuntimeError(
                    "level1-release orientation contract hash drift"
                )
        elif args.seed not in panel["seeds_in_order"]:
            raise RuntimeError("seed is outside frozen dynamic panel")
    if failure_telemetry_requested:
        assert args.failure_telemetry_contract is not None
        assert args.failure_telemetry_authorization is not None
        assert args.level1_release_diagnostic_contract is not None
        assert args.level1_release_diagnostic_authorization is not None
        if level1_release_contract is None:
            raise RuntimeError(
                "failure telemetry predecessor contract was not activated"
            )
        failure_telemetry_contract = load_json(
            args.failure_telemetry_contract
        )
        failure_telemetry_authorization = load_json(
            args.failure_telemetry_authorization
        )
        failure_telemetry_phase = (
            validate_retreat_failure_telemetry_execution_contract(
                failure_telemetry_contract,
                failure_telemetry_authorization,
                planning_contract_sha256=sha256_file(
                    args.failure_telemetry_contract
                ),
                level1_contract_sha256=sha256_file(
                    args.level1_release_diagnostic_contract
                ),
                level1_authorization_sha256=sha256_file(
                    args.level1_release_diagnostic_authorization
                ),
                seed=args.seed,
                generation_mode=args.generation_mode,
                capture=bool(args.capture),
                backend=args.backend,
                cuda_visible_devices=os.environ.get(
                    "CUDA_VISIBLE_DEVICES"
                ),
            )
        )
        frozen_source = failure_telemetry_contract.get(
            "frozen_source_identity",
            {},
        )
        frozen_path_hashes = (
            (
                ROOT / "src/mantis_rocm_bridge/stack_bowls_env.py",
                "source_reset_sampler_sha256",
            ),
            (args.task, "task_contract_sha256"),
            (args.scene_contract, "scene_contract_sha256"),
            (
                args.consecutive_left_dynamic_contract,
                "orientation_schedule_contract_sha256",
            ),
            (args.source_task, "source_task_contract_sha256"),
            (args.mantis_urdf, "mantis_asset_sha256"),
            (bowl_urdf, "bowl_urdf_sha256"),
            (bowl_manifest_path, "bowl_manifest_sha256"),
        )
        for path, hash_field in frozen_path_hashes:
            if frozen_source.get(hash_field) != sha256_file(path):
                raise RuntimeError(
                    f"failure-telemetry frozen source drift: {hash_field}"
                )
    if release_retreat_boundary_requested:
        assert args.release_retreat_boundary_contract is not None
        assert args.release_retreat_boundary_authorization is not None
        assert args.failure_telemetry_contract is not None
        assert args.failure_telemetry_authorization is not None
        if failure_telemetry_contract is None:
            raise RuntimeError(
                "boundary trace predecessor telemetry was not activated"
            )
        release_retreat_boundary_contract = load_json(
            args.release_retreat_boundary_contract
        )
        release_retreat_boundary_authorization = load_json(
            args.release_retreat_boundary_authorization
        )
        release_retreat_boundary_phase = (
            validate_release_retreat_boundary_execution_contract(
                release_retreat_boundary_contract,
                release_retreat_boundary_authorization,
                planning_contract_sha256=sha256_file(
                    args.release_retreat_boundary_contract
                ),
                failure_contract_sha256=sha256_file(
                    args.failure_telemetry_contract
                ),
                failure_authorization_sha256=sha256_file(
                    args.failure_telemetry_authorization
                ),
                seed=args.seed,
                generation_mode=args.generation_mode,
                capture=bool(args.capture),
                backend=args.backend,
                cuda_visible_devices=os.environ.get(
                    "CUDA_VISIBLE_DEVICES"
                ),
            )
        )
    validate_contract_pair(port, task, source_task)
    validate_genesis_scene_contract(scene_contract, source_task, port)
    if bowl_manifest.get("distribution_allowed") is not True:
        raise RuntimeError("bowl materialization is not licensed for distribution")
    validate_g1_smoke_contract(task)

    seed = args.seed
    is_canonical_g1 = is_canonical_g1_seed(seed)
    generation_mode = args.generation_mode

    # Determine effective max policy steps
    task_max_policy_steps = int(task["max_policy_steps"])  # Should be 1200

    # Probe mode: validate horizon minimum against task max dynamically
    if generation_mode == "probe":
        if args.probe_max_policy_steps < task_max_policy_steps:
            parser.error(
                f"--probe-max-policy-steps ({args.probe_max_policy_steps}) must be >= "
                f"task max_policy_steps ({task_max_policy_steps})"
            )
        effective_max_policy_steps = int(args.probe_max_policy_steps)  # Should be 2400 by default
    else:
        effective_max_policy_steps = task_max_policy_steps

    reset = sample_source_reset_poses(seed=seed)
    ordered_reset = sorted(reset, key=lambda pose: pose.position_xyz_m[1])
    contract = dict(scene_contract["bimanual_rim_hook_probe"])
    contract["transport_duration_s"] = float(args.transport_duration_s)
    run_dir = args.ops_root / args.run_id
    begun = False
    receipt_written = False
    failure_telemetry_path = (
        run_dir / "failure_telemetry.json"
        if failure_telemetry_contract is not None
        else None
    )
    failure_telemetry_sha256: str | None = None
    release_retreat_boundary_path = (
        run_dir / "release_retreat_boundary_trace.json"
        if release_retreat_boundary_contract is not None
        else None
    )
    release_retreat_boundary_sha256: str | None = None
    release_retreat_boundary_snapshots: list[dict[str, Any]] = []

    # Load and validate replay plan if in replay mode
    replay_plan: ReplayPlan | None = None
    if generation_mode == "replay":
        replay_plan = ReplayPlan.read(args.replay_plan)

        # Reject pre-fix plans that need re-probe (candidate > 0 pollution)
        if plan_needs_reprobe(replay_plan):
            raise ValueError(
                f"Replay plan needs re-probe for candidate isolation. "
                f"Pre-fix plans with candidate > 0 are polluted and cannot be replayed safely. "
                f"Run a new probe calibration to generate a fresh plan."
            )

        # Validate plan matches current seed and task
        if replay_plan.seed != seed:
            raise ValueError(
                f"Replay plan seed {replay_plan.seed} does not match current seed {seed}"
            )
        if replay_plan.task_id != task["task_id"]:
            raise ValueError(
                f"Replay plan task_id {replay_plan.task_id} does not match current task_id {task['task_id']}"
            )

        # Validate hashes match current assets
        expected_hashes = {
            "task": sha256_file(args.task),
            "scene": sha256_file(args.scene_contract),
            "camera": sha256_file(args.camera_contract),
            "port": sha256_file(args.port),
            "mantis_urdf": sha256_file(args.mantis_urdf),
            "bowl_urdf": sha256_file(bowl_urdf),
        }
        for key, expected_hash in expected_hashes.items():
            if replay_plan.hashes[key] != expected_hash:
                raise ValueError(
                    f"Replay plan hash[{key}] {replay_plan.hashes[key]} does not match "
                    f"current hash {expected_hash}"
                )

        # Validate ordered reset poses match exactly
        validate_ordered_poses(replay_plan.reset_bowl_poses, [
            {
                "name": pose.name,
                "position_xyz_m": list(pose.position_xyz_m),
                "quaternion_wxyz": list(pose.quaternion_wxyz),
            }
            for pose in ordered_reset
        ])

        # Pre-simulation semantic validation for all replay steps
        for level_idx, step in enumerate(replay_plan.steps):
            # Validate exact bowl/order/side/source match with reset poses
            reset_pose = ordered_reset[level_idx]
            if step.bowl != reset_pose.name:
                raise ValueError(
                    f"Replay plan step {level_idx} bowl '{step.bowl}' does not match "
                    f"reset pose bowl '{reset_pose.name}'"
                )
            if step.level != level_idx:
                raise ValueError(
                    f"Replay plan step {level_idx} has level {step.level}, expected {level_idx}"
                )

            # Validate side dual clamp consistency
            expected_side = arm_for_bowl_x(reset_pose.position_xyz_m[0])
            if step.assigned_side != expected_side:
                raise ValueError(
                    f"Replay plan step {level_idx} side '{step.assigned_side}' does not match "
                    f"expected side '{expected_side}' for bowl {step.bowl} at x={reset_pose.position_xyz_m[0]:.6f}"
                )
            if step.assigned_side == "right" and not step.dual_clamp_required:
                raise ValueError(
                    f"Replay plan step {level_idx} (right side) must have dual_clamp_required=True, "
                    f"got {step.dual_clamp_required}"
                )

            # Validate left zero offset
            if step.assigned_side == "left":
                if step.place_xy_offset_m != (0.0, 0.0):
                    raise ValueError(
                        f"Replay plan step {level_idx} (left side) must have zero offset, "
                        f"got {step.place_xy_offset_m}"
                    )

            # Validate gate true for all steps
            if not step.probe_placement_gate_pass:
                raise ValueError(
                    f"Replay plan step {level_idx} must have probe_placement_gate_pass=True, "
                    f"got {step.probe_placement_gate_pass}"
                )

            # Validate source position matches reset pose exactly
            for i, (step_val, reset_val) in enumerate(zip(step.source_position_xyz_m, reset_pose.position_xyz_m)):
                if not math.isfinite(step_val) or not math.isfinite(reset_val):
                    raise ValueError(f"Non-finite source position at step {level_idx} axis {i}")
                if step_val != reset_val:  # Exact equality: frozen plan contract is exact
                    raise ValueError(
                        f"Replay plan step {level_idx} source_position_xyz_m[{i}]={step_val:.9f} "
                        f"does not exactly match reset pose {reset_val:.9f}"
                    )

    try:
        # Build begin_run details with mode-specific fields
        begin_details: dict[str, Any] = {
            "phase": "genesis_mantis_stack_bowls_scripted_g1",
            "protocol_version": "contact_triggered_suction_scripted_g1_v1",
            "seed": seed,
            "canonical_g1": is_canonical_g1,
            "generation_mode": generation_mode,
            "task_policy_step_limit": task_max_policy_steps,
            "effective_policy_step_limit": effective_max_policy_steps,
            "backend": args.backend,
            "capture_requested": args.capture,
            "transport_duration_s": args.transport_duration_s,
            "cartesian_waypoints": args.cartesian_waypoints,
            "consecutive_left_inter_bowl_transition_protocol": (
                consecutive_left_transition_contract["protocol_version"]
            ),
            "consecutive_left_inter_bowl_clearance_tcp_z_m": (
                consecutive_left_transition_contract["clearance_tcp_z_m"]
            ),
            "consecutive_left_inter_bowl_waypoints_per_segment": (
                consecutive_left_transition_contract[
                    "cartesian_waypoints_per_segment"
                ]
            ),
            "transition_ik_matrix_only": bool(
                args.transition_ik_matrix_only
            ),
            "consecutive_left_orientation_schedule": (
                args.consecutive_left_orientation_schedule
            ),
            "scene_contract_sha256": sha256_file(args.scene_contract),
            "camera_contract_sha256": sha256_file(args.camera_contract),
            "port_config_sha256": sha256_file(args.port),
            "mantis_urdf_sha256": sha256_file(args.mantis_urdf),
            "bowl_urdf_sha256": sha256_file(bowl_urdf),
        }
        if args.transition_ik_matrix_only:
            begin_details["transition_ik_matrix_contract_sha256"] = (
                sha256_file(args.transition_ik_matrix_contract)
            )
        if consecutive_left_dynamic_contract is not None:
            begin_details["consecutive_left_dynamic_contract_sha256"] = (
                sha256_file(args.consecutive_left_dynamic_contract)
            )
        if corrected_expert_contract is not None:
            assert args.corrected_expert_contract is not None
            assert args.corrected_expert_authorization is not None
            begin_details["corrected_expert_work_package_id"] = (
                G3_CORRECTED_EXPERT_WORK_PACKAGE
            )
            begin_details["corrected_expert_phase"] = corrected_expert_phase
            begin_details["corrected_expert_contract_sha256"] = sha256_file(
                args.corrected_expert_contract
            )
            begin_details["corrected_expert_authorization_sha256"] = (
                sha256_file(args.corrected_expert_authorization)
            )
        if level1_release_contract is not None:
            assert args.level1_release_diagnostic_contract is not None
            assert args.level1_release_diagnostic_authorization is not None
            begin_details["level1_release_work_package_id"] = (
                level1_release_contract["work_package_id"]
            )
            begin_details["level1_release_phase"] = level1_release_phase
            begin_details["level1_release_contract_sha256"] = sha256_file(
                args.level1_release_diagnostic_contract
            )
            begin_details["level1_release_authorization_sha256"] = (
                sha256_file(args.level1_release_diagnostic_authorization)
            )
            begin_details["level1_release_observability_schema"] = (
                level1_release_contract["single_primary_variable"]["candidate"]
            )
        if failure_telemetry_contract is not None:
            assert args.failure_telemetry_contract is not None
            assert args.failure_telemetry_authorization is not None
            begin_details["failure_telemetry_work_package_id"] = (
                RETREAT_FAILURE_TELEMETRY_WORK_PACKAGE
            )
            begin_details["failure_telemetry_phase"] = (
                failure_telemetry_phase
            )
            begin_details["failure_telemetry_contract_sha256"] = (
                sha256_file(args.failure_telemetry_contract)
            )
            begin_details["failure_telemetry_authorization_sha256"] = (
                sha256_file(args.failure_telemetry_authorization)
            )
            begin_details["stop_on_safety_failure"] = True
        if release_retreat_boundary_contract is not None:
            assert args.release_retreat_boundary_contract is not None
            assert args.release_retreat_boundary_authorization is not None
            begin_details["release_retreat_boundary_work_package_id"] = (
                RELEASE_RETREAT_BOUNDARY_WORK_PACKAGE
            )
            begin_details["release_retreat_boundary_phase"] = (
                release_retreat_boundary_phase
            )
            begin_details["release_retreat_boundary_contract_sha256"] = (
                sha256_file(args.release_retreat_boundary_contract)
            )
            begin_details[
                "release_retreat_boundary_authorization_sha256"
            ] = sha256_file(args.release_retreat_boundary_authorization)
            begin_details["release_retreat_boundary_snapshot_count"] = 5

        # Add mode-specific fields to begin_run
        if generation_mode == "replay" and args.replay_plan:
            begin_details["replay_plan_basename"] = args.replay_plan.name
            begin_details["replay_plan_sha256"] = sha256_file(args.replay_plan)
            begin_details["frozen_plan_validation_pass"] = True
        elif generation_mode == "probe":
            # Probe mode has mode/limits but no output hash yet
            pass
        elif generation_mode == "online":
            # Online mode: no replay/probe fields
            pass

        begin_run(
            args.ops_root,
            args.run_id,
            begin_details,
        )
        begun = True

        import genesis as gs
        import numpy as np

        dt = float(scene_contract["control"]["physics_dt_s"])
        policy_hz = float(task["policy_hz"])
        clock = PolicyCaptureClock(physics_dt_s=dt, policy_hz=policy_hz)
        gs.init(
            backend=resolve_backend(gs, args.backend),
            seed=seed,
            logging_level="warning",
        )
        scene = gs.Scene(
            sim_options=gs.options.SimOptions(dt=dt),
            show_viewer=False,
        )
        table = scene.add_entity(
            gs.morphs.Plane(
                pos=(
                    0.0,
                    0.0,
                    float(scene_contract["world"]["table_plane_z_m"]),
                ),
                fixed=True,
            )
        )
        base = scene_contract["world"]["mantis_base"]
        robot = scene.add_entity(
            gs.morphs.URDF(
                file=str(args.mantis_urdf.resolve()),
                pos=tuple(base["position_xyz_m"]),
                quat=tuple(base["quaternion_wxyz"]),
                fixed=True,
            )
        )
        bowls_by_name = {
            pose.name: scene.add_entity(
                gs.morphs.URDF(
                    file=str(bowl_urdf.resolve()),
                    pos=pose.position_xyz_m,
                    quat=pose.quaternion_wxyz,
                    fixed=False,
                    merge_fixed_links=False,
                    recompute_inertia=False,
                    file_meshes_are_zup=True,
                ),
                name=pose.name,
            )
            for pose in reset
        }

        cameras: dict[str, Any] = {}
        if args.capture:
            env_mount = camera_contract["mounts"]["env_cam"]
            env_pos = np.asarray(env_mount["position_xyz_m"], dtype=float)
            env_forward = np.asarray(env_mount["forward_xyz"], dtype=float)
            cameras["env_cam"] = scene.add_camera(
                res=(320, 240),
                pos=tuple(env_pos),
                lookat=tuple(env_pos + env_forward),
                fov=37.0,
                near=0.1,
                far=100.0,
                GUI=False,
            )
            mounts = genesis_wrist_mounts(camera_contract)
            for name in ("left_wrist_cam", "right_wrist_cam"):
                camera = scene.add_camera(
                    res=(424, 240),
                    pos=(0.0, 0.0, 1.0),
                    lookat=(0.0, 0.0, 0.0),
                    fov=37.0,
                    near=0.1,
                    far=100.0,
                    GUI=False,
                )
                camera.attach(
                    robot.get_link(mounts[name]["parent"]),
                    np.asarray(mounts[name]["offset_T"], dtype=float),
                )
                cameras[name] = camera
        scene.build()

        labels = {int(geom.idx): _robot_geom_label(geom) for geom in robot.geoms}
        labels.update(
            {int(geom.idx): f"table:{geom.link.name}" for geom in table.geoms}
        )
        for pose in reset:
            labels.update(
                {
                    int(geom.idx): f"{pose.name}:{geom.link.name}"
                    for geom in bowls_by_name[pose.name].geoms
                }
            )
        proximal_filter_links = (
            "pelvis_link",
            "right_shoulder_yaw_link",
        )
        proximal_filter_geom_ids = {
            link_name: [
                int(geom.idx)
                for geom in robot.get_link(link_name).geoms
            ]
            for link_name in proximal_filter_links
        }
        collider = scene.rigid_solver.collider
        collision_pair_idx = (
            collider._collider_info.collision_pair_idx.to_numpy()
        )
        filtered_pair_entries: list[dict[str, int]] = []
        for geom_a in proximal_filter_geom_ids[proximal_filter_links[0]]:
            for geom_b in proximal_filter_geom_ids[proximal_filter_links[1]]:
                lower, upper = sorted((geom_a, geom_b))
                original_index = int(collision_pair_idx[lower, upper])
                if original_index >= 0:
                    collision_pair_idx[lower, upper] = -1
                    filtered_pair_entries.append(
                        {
                            "geom_a": lower,
                            "geom_b": upper,
                            "original_pair_index": original_index,
                        }
                    )
        if not filtered_pair_entries:
            raise RuntimeError(
                "expected pelvis/right-shoulder-yaw collision pair was not active"
            )
        collider._collider_info.collision_pair_idx.from_numpy(
            collision_pair_idx
        )
        filtered_readback = (
            collider._collider_info.collision_pair_idx.to_numpy()
        )
        if any(
            int(filtered_readback[row["geom_a"], row["geom_b"]]) != -1
            for row in filtered_pair_entries
        ):
            raise RuntimeError("proximal allowed-collision filter readback failed")
        for bowl in bowls_by_name.values():
            bowl.set_friction(float(contract["bowl_friction_coefficient"]))
        for geom in robot.geoms:
            if any(
                geom.link.name.startswith(f"{side}_clamp")
                for side in SIDES
            ):
                geom.set_friction(float(contract["finger_friction_coefficient"]))

        physical_names = list(port["target"]["physical_joint_order"])
        all_indices = _dof_indices(robot, physical_names)
        arm_indices_by_side = {
            side: _dof_indices(robot, arm_dof_names(side)) for side in SIDES
        }
        all_arm_indices = [
            index for side in SIDES for index in arm_indices_by_side[side]
        ]
        gripper_names_by_side = {
            side: list(
                port["assets"]["virtual_gripper_mapping"]["coefficients"][
                    f"{side}_gripper_joint"
                ]
            )
            for side in SIDES
        }
        gripper_indices_by_side = {
            side: _dof_indices(robot, gripper_names_by_side[side])
            for side in SIDES
        }
        all_gripper_indices = [
            index for side in SIDES for index in gripper_indices_by_side[side]
        ]
        arm_index_set = set(all_arm_indices)
        robot.set_dofs_kp(
            [
                float(
                    contract["arm_kp"]
                    if index in arm_index_set
                    else contract["gripper_kp"]
                )
                for index in all_indices
            ],
            dofs_idx_local=all_indices,
        )
        robot.set_dofs_kv(
            [
                float(
                    contract["arm_kv"]
                    if index in arm_index_set
                    else contract["gripper_kv"]
                )
                for index in all_indices
            ],
            dofs_idx_local=all_indices,
        )
        lower_force = [
            -float(
                contract["arm_force_limit"]
                if index in arm_index_set
                else contract["gripper_force_limit"]
            )
            for index in all_indices
        ]
        robot.set_dofs_force_range(
            lower_force,
            [-value for value in lower_force],
            dofs_idx_local=all_indices,
        )

        open_qpos = np.asarray(physical_pose(port, 1.0), dtype=float)
        closed_qpos = np.asarray(physical_pose(port, 0.0), dtype=float)
        hold_qpos = np.asarray(
            physical_pose(port, float(contract["gripper_hold_open_fraction"])),
            dtype=float,
        )
        lift_qpos = np.asarray(
            physical_pose(port, float(contract["lift_gripper_open_fraction"])),
            dtype=float,
        )
        robot.set_qpos(open_qpos)
        robot.control_dofs_position(open_qpos, dofs_idx_local=all_indices)
        for _ in range(25):
            scene.step()

        tcp = scene_contract["tcp"]
        ik = scene_contract["ik_gate"]
        links = {
            side: robot.get_link(tcp[side]["link"])
            for side in SIDES
        }
        local_points = {
            side: np.asarray(tcp[side]["local_point_xyz_m"], dtype=float)
            for side in SIDES
        }
        orientations = {
            side: np.asarray(contract["orientations_wxyz"][side], dtype=float)
            for side in SIDES
        }
        separation_orientations = {
            side: np.asarray(
                contract["separation_orientations_wxyz"][side],
                dtype=float,
            )
            for side in SIDES
        }

        active_bowl_name: str | None = None
        active_side_name: str | None = None
        safety_failures: list[dict[str, Any]] = []
        contact_histogram: dict[str, int] = {}
        sim_step = 0
        next_frame_index = 0
        current_action = open_qpos.copy()
        active_command_context: dict[str, Any] | None = None
        captured: dict[str, list[Any]] = {
            "timestamps_s": [],
            "physical_state": [],
            "physical_action": [],
            "env_cam": [],
            "left_wrist_cam": [],
            "right_wrist_cam": [],
        }
        maximum_sampling_skew_s = 0.0

        def capture_tick(stage: str = "initial") -> None:
            nonlocal next_frame_index, maximum_sampling_skew_s
            tick = clock.tick(next_frame_index)
            if tick.physics_step > sim_step:
                return
            if next_frame_index > effective_max_policy_steps:
                raise RuntimeError(
                    f"scripted trajectory exceeded max_policy_steps during stage '{stage}': "
                    f"next_frame_index={next_frame_index}, max_policy_steps={effective_max_policy_steps} "
                    f"(generation_mode={generation_mode}, task_max={task_max_policy_steps})"
                )
            captured["timestamps_s"].append(tick.policy_timestamp_s)
            captured["physical_state"].append(_read_dofs(robot, all_indices))
            captured["physical_action"].append(current_action.copy())
            if args.capture:
                for name, camera in cameras.items():
                    captured[name].append(
                        genesis_rgb_array(
                            camera.render(rgb=True, force_render=True)
                        )
                    )
            maximum_sampling_skew_s = max(
                maximum_sampling_skew_s,
                tick.sampling_skew_s,
            )
            next_frame_index += 1

        def cached_pose(entity: Any) -> dict[str, list[float]]:
            """Read one entity or link pose without advancing simulation."""

            return {
                "position_xyz_m": _vector(entity.get_pos()),
                "quaternion_wxyz": list(
                    normalize_quaternion_wxyz(_vector(entity.get_quat()))
                ),
            }

        def cached_active_tcp_pose() -> dict[str, Any]:
            if active_side_name not in SIDES:
                raise RuntimeError(
                    "failure telemetry requires an active robot side"
                )
            link_pose = cached_pose(links[active_side_name])
            rotated_local_point = rotate_vector_wxyz(
                link_pose["quaternion_wxyz"],
                local_points[active_side_name],
            )
            link_position = link_pose["position_xyz_m"]
            return {
                "side": active_side_name,
                "position_xyz_m": [
                    float(link_position[index])
                    + float(rotated_local_point[index])
                    for index in range(3)
                ],
                "quaternion_wxyz": link_pose["quaternion_wxyz"],
            }

        def record_release_retreat_boundary_snapshot(
            label: str,
            *,
            weld_active: bool,
        ) -> None:
            """Read one frozen WP-015 cache point without advancing physics."""

            nonlocal release_retreat_boundary_sha256
            if release_retreat_boundary_contract is None:
                return
            if release_retreat_boundary_path is None:
                raise RuntimeError("boundary trace path is unavailable")
            if release_retreat_boundary_sha256 is not None:
                raise RuntimeError(
                    "refusing a boundary snapshot after trace finalization"
                )
            expected_labels = release_retreat_boundary_contract[
                "boundary_trace_contract"
            ]["ordered_snapshot_labels"]
            next_index = len(release_retreat_boundary_snapshots)
            if next_index >= len(expected_labels) or (
                label != expected_labels[next_index]
            ):
                raise RuntimeError(
                    "release-retreat boundary snapshot order drift: "
                    f"expected={expected_labels[next_index:next_index + 1]} "
                    f"actual={label}"
                )
            if active_bowl_name != "bowl3" or active_side_name != "left":
                raise RuntimeError(
                    "boundary trace requires active bowl3 on the left side"
                )
            if active_command_context is None:
                raise RuntimeError(
                    "boundary trace command context is unavailable"
                )
            policy_before = max(0, next_frame_index - 1)
            sim_before = sim_step
            robot_bowl2_info = robot.get_contacts(
                with_entity=bowls_by_name["bowl2"]
            )
            bowl3_bowl2_info = bowls_by_name["bowl3"].get_contacts(
                with_entity=bowls_by_name["bowl2"]
            )
            robot_bowl2_pairs = sorted(
                _contact_pairs(robot_bowl2_info, labels)
            )
            bowl3_bowl2_pairs = sorted(
                _contact_pairs(bowl3_bowl2_info, labels)
            )
            snapshot = {
                "label": label,
                "physics_step": sim_before,
                "policy_step": policy_before,
                "weld_registered": weld_active,
                "command_segment": dict(active_command_context),
                "commanded_qpos": _vector(current_action),
                "robot_qpos": _read_dofs(robot, all_indices),
                "active_tcp_pose": cached_active_tcp_pose(),
                "left_clamp_poses": {
                    link_name: cached_pose(robot.get_link(link_name))
                    for link_name in (
                        "left_clamp_left_link",
                        "left_clamp_right_link",
                    )
                },
                "bowl2_pose": cached_pose(bowls_by_name["bowl2"]),
                "bowl3_pose": cached_pose(bowls_by_name["bowl3"]),
                "robot_bowl2_contact_pairs": robot_bowl2_pairs,
                "robot_bowl2_contact_pair_count": len(
                    robot_bowl2_pairs
                ),
                "target_pair_present": (
                    RELEASE_RETREAT_BOUNDARY_TARGET_PAIR
                    in robot_bowl2_pairs
                ),
                "robot_bowl2_contact_diagnostics": (
                    _contact_diagnostics(robot_bowl2_info)
                ),
                "bowl3_bowl2_contact_pairs": bowl3_bowl2_pairs,
                "bowl3_bowl2_contact_pair_count": len(
                    bowl3_bowl2_pairs
                ),
                "bowl3_bowl2_contact_diagnostics": (
                    _contact_diagnostics(bowl3_bowl2_info)
                ),
                "contact_cache_source_physics_step": sim_before,
                "contact_cache_semantics": "most_recent_scene_step",
                "observer_policy_step_delta": (
                    max(0, next_frame_index - 1) - policy_before
                ),
                "observer_physics_step_delta": sim_step - sim_before,
            }
            release_retreat_boundary_snapshots.append(snapshot)
            if len(release_retreat_boundary_snapshots) == len(
                expected_labels
            ):
                release_retreat_boundary_sha256 = (
                    write_boundary_trace_exclusive(
                        release_retreat_boundary_path,
                        {
                            "schema_version": 1,
                            "work_package_id": (
                                RELEASE_RETREAT_BOUNDARY_WORK_PACKAGE
                            ),
                            "seed": seed,
                            "selected_bowl": "bowl3",
                            "supporting_nonselected_bowl": "bowl2",
                            "active_side": "left",
                            "target_pair": (
                                RELEASE_RETREAT_BOUNDARY_TARGET_PAIR
                            ),
                            "snapshots": (
                                release_retreat_boundary_snapshots
                            ),
                        },
                    )
                )

        def record_retreat_boundary_after_step(stage: str) -> None:
            """Record retreat steps 1/2 before the original safety sampler."""

            if release_retreat_boundary_contract is None:
                return
            if stage != "bowl3:retreat" or active_command_context is None:
                return
            if active_command_context.get("phase") != "interpolation":
                return
            step_index = active_command_context.get("step_index")
            if step_index not in (1, 2):
                return
            record_release_retreat_boundary_snapshot(
                f"retreat_step_{step_index}",
                weld_active=False,
            )

        def record_failure_telemetry(
            failure: dict[str, Any],
            *,
            contact_info: Any,
            nonselected_bowl_name: str | None,
        ) -> None:
            nonlocal failure_telemetry_sha256
            if failure_telemetry_contract is None:
                return
            if failure_telemetry_path is None:
                raise RuntimeError("failure telemetry path is unavailable")
            if failure_telemetry_sha256 is not None:
                raise RuntimeError(
                    "refusing a second first-failure telemetry record"
                )
            if active_command_context is None:
                raise RuntimeError(
                    "failure telemetry command context is unavailable"
                )
            if active_bowl_name is None:
                raise RuntimeError(
                    "failure telemetry selected bowl is unavailable"
                )
            sim_before = sim_step
            policy_index = max(0, next_frame_index - 1)
            payload = {
                "schema_version": 1,
                "work_package_id": (
                    RETREAT_FAILURE_TELEMETRY_WORK_PACKAGE
                ),
                "seed": seed,
                "stage": failure["stage"],
                "kind": failure["kind"],
                "selected_bowl": active_bowl_name,
                "nonselected_bowl": nonselected_bowl_name,
                "pairs": list(failure["pairs"]),
                "sim_step": sim_step,
                "policy_step": policy_index,
                "policy_time_s": policy_index / policy_hz,
                "command_segment": dict(active_command_context),
                "commanded_qpos": _vector(current_action),
                "robot_qpos": _read_dofs(robot, all_indices),
                "active_tcp_pose": cached_active_tcp_pose(),
                "left_clamp_poses": {
                    link_name: cached_pose(robot.get_link(link_name))
                    for link_name in (
                        "left_clamp_left_link",
                        "left_clamp_right_link",
                    )
                },
                "bowl2_pose": cached_pose(bowls_by_name["bowl2"]),
                "bowl3_pose": cached_pose(bowls_by_name["bowl3"]),
                "contact_diagnostics": _contact_diagnostics(contact_info),
                "observer_step_delta": sim_step - sim_before,
                "contact_cache_source_physics_step": sim_step,
                "contact_cache_semantics": "most_recent_scene_step",
            }
            failure_telemetry_sha256 = (
                write_failure_telemetry_exclusive(
                    failure_telemetry_path,
                    payload,
                )
            )

        def sample_safety(stage: str) -> None:
            if safety_failures:
                return
            table_info = robot.get_contacts(with_entity=table)
            if _contact_count(table_info):
                failure = {
                    "stage": stage,
                    "kind": "robot_table_contact",
                    "pairs": _contact_pairs(table_info, labels),
                }
                safety_failures.append(failure)
                record_failure_telemetry(
                    failure,
                    contact_info=table_info,
                    nonselected_bowl_name=None,
                )
                return
            self_info = robot.get_contacts()
            self_pairs = _self_contact_pairs(self_info, labels)
            if self_pairs:
                failure = {
                    "stage": stage,
                    "kind": "robot_self_contact",
                    "pairs": self_pairs,
                    "diagnostics": _contact_diagnostics(self_info),
                }
                safety_failures.append(failure)
                record_failure_telemetry(
                    failure,
                    contact_info=self_info,
                    nonselected_bowl_name=None,
                )
                return
            for bowl_name, bowl in bowls_by_name.items():
                if bowl_name == active_bowl_name:
                    continue
                info = robot.get_contacts(with_entity=bowl)
                if _contact_count(info):
                    pairs = _contact_pairs(info, labels)
                    expected_stack_contact = (
                        active_side_name is not None
                        and stage.split(":")[-1] in {"place", "release"}
                        and all(
                            f"mantis:{active_side_name}_clamp" in pair
                            for pair in pairs
                        )
                    )
                    if expected_stack_contact:
                        continue
                    failure = {
                        "stage": stage,
                        "kind": "robot_nonselected_bowl_contact",
                        "bowl": bowl_name,
                        "pairs": pairs,
                    }
                    safety_failures.append(failure)
                    record_failure_telemetry(
                        failure,
                        contact_info=info,
                        nonselected_bowl_name=bowl_name,
                    )
                    return

        def advance(
            target: np.ndarray,
            stage: str,
            *,
            command_context: dict[str, Any] | None = None,
        ) -> None:
            nonlocal sim_step, current_action, active_command_context
            target_array = np.asarray(target, dtype=float).copy()
            if command_context is None:
                active_command_context = {
                    "stage": stage,
                    "phase": "settle",
                    "step_index": 1,
                    "total_steps": 1,
                    "interpolation_fraction": 1.0,
                    "start_qpos": _vector(current_action),
                    "target_qpos": _vector(target_array),
                }
            else:
                active_command_context = dict(command_context)
            current_action = target_array
            robot.control_dofs_position(current_action, dofs_idx_local=all_indices)
            scene.step()
            sim_step += 1
            if release_retreat_boundary_contract is not None:
                record_retreat_boundary_after_step(stage)
            if sim_step % int(contract["contact_sample_interval_steps"]) == 0:
                sample_safety(stage)
            capture_tick(stage)
            if safety_failures:
                raise RuntimeError(
                    f"safety failure during {stage}: {safety_failures[-1]}"
                )

        capture_tick()
        tracker = EpisodeStageTracker(
            task,
            seed=seed,
            effective_policy_step_limit=effective_max_policy_steps,
        )
        tracker.complete_stage(
            task["stages"][0],
            policy_step=0,
            details={"reset_distribution": "exact_source", "seed": seed},
        )
        tracker.complete_stage(
            task["stages"][1],
            policy_step=0,
            details={
                "three_bowls_observed": True,
                "three_camera_capture": bool(args.capture),
            },
        )

        def policy_step() -> int:
            return max(0, next_frame_index - 1)

        def measured_gripper_fraction(side: str) -> float:
            qpos = dict(zip(physical_names, _read_dofs(robot, all_indices)))
            mapping = port["assets"]["virtual_gripper_mapping"]
            virtual_name = f"{side}_gripper_joint"
            values: list[float] = []
            for joint_name, coefficient in mapping["coefficients"][
                virtual_name
            ].items():
                offset = float(mapping["offsets"][virtual_name][joint_name])
                values.append(
                    (float(qpos[joint_name]) - offset) / float(coefficient)
                )
            return float(sum(values) / len(values))

        def solve_stage(
            stage: str,
            target_positions: dict[str, np.ndarray],
            initial: np.ndarray,
            *,
            separation: bool = False,
            orientation_override: dict[str, np.ndarray] | None = None,
            raise_on_tolerance_failure: bool = True,
        ) -> tuple[np.ndarray, dict[str, dict[str, float]]]:
            combined = initial.copy()
            errors: dict[str, dict[str, float]] = {}
            for side in target_positions:
                best: tuple[float, float, np.ndarray] | None = None
                # Genesis samples alternative IK seeds internally.  Repeat the
                # two valid whole-body initializations so boundary workspace
                # targets are not rejected by one unlucky sample set.
                for candidate_initial in (
                    combined,
                    open_qpos,
                    combined,
                    open_qpos,
                    combined,
                    open_qpos,
                ):
                    qpos, error = robot.inverse_kinematics(
                        links[side],
                        pos=target_positions[side],
                        quat=(
                            separation_orientations[side]
                            if separation
                            else (
                                orientation_override[side]
                                if orientation_override is not None
                                else orientations[side]
                            )
                        ),
                        local_point=local_points[side],
                        init_qpos=candidate_initial,
                        respect_joint_limit=True,
                        max_samples=int(ik["max_samples"]),
                        max_solver_iters=int(ik["max_solver_iters"]),
                        dofs_idx_local=arm_indices_by_side[side],
                        return_error=True,
                    )
                    error_values = _vector(error)
                    position_error = math.sqrt(
                        sum(value * value for value in error_values[:3])
                    )
                    rotation_error = math.sqrt(
                        sum(value * value for value in error_values[3:])
                    )
                    candidate = np.asarray(_vector(qpos), dtype=float)
                    for index in all_indices:
                        if index not in arm_indices_by_side[side]:
                            candidate[index] = combined[index]
                    if best is None or (position_error, rotation_error) < (
                        best[0],
                        best[1],
                    ):
                        best = (position_error, rotation_error, candidate)
                    if (
                        position_error <= float(ik["position_tolerance_m"])
                        and rotation_error
                        <= float(ik["rotation_tolerance_rad"])
                    ):
                        break
                assert best is not None
                errors[side] = {
                    "position_error_m": best[0],
                    "rotation_error_rad": best[1],
                }
                if (
                    best[0] > float(ik["position_tolerance_m"])
                    or best[1] > float(ik["rotation_tolerance_rad"])
                ) and raise_on_tolerance_failure:
                    raise RuntimeError(
                        f"{stage} {side} IK exceeds tolerance: {errors[side]}"
                    )
                combined = best[2]
            for index in all_gripper_indices:
                combined[index] = open_qpos[index]
            return combined, errors

        def command_segment(
            stage: str,
            target: np.ndarray,
            minimum_duration_s: float,
        ) -> float:
            # Arm start comes from the readback; gripper start comes from the last
            # commanded action so post-contact finger readbacks cannot seed an
            # asymmetric gripper interpolation between moves.
            start = np.asarray(
                build_interpolation_start(
                    readback=_read_dofs(robot, all_indices),
                    previous_action=current_action,
                    arm_indices=all_arm_indices,
                    gripper_indices=all_gripper_indices,
                    expected_length=len(all_indices),
                ),
                dtype=float,
            )
            duration = max(
                float(minimum_duration_s),
                max(
                    abs(target[index] - start[index])
                    for index in all_arm_indices
                ),
            )
            steps = max(1, int(math.ceil(duration / dt)))
            for step in range(1, steps + 1):
                alpha = step / steps
                advance(
                    start + alpha * (target - start),
                    stage,
                    command_context={
                        "stage": stage,
                        "phase": "interpolation",
                        "step_index": step,
                        "total_steps": steps,
                        "interpolation_fraction": alpha,
                        "start_qpos": _vector(start),
                        "target_qpos": _vector(target),
                    },
                )
            required = int(contract["waypoint_settle_consecutive_steps"])
            settle_steps = max(
                1,
                int(
                    math.ceil(
                        float(contract["waypoint_settle_timeout_s"]) / dt
                    )
                ),
            )
            consecutive = 0
            for settle_step in range(1, settle_steps + 1):
                advance(
                    target,
                    stage,
                    command_context={
                        "stage": stage,
                        "phase": "settle",
                        "step_index": settle_step,
                        "total_steps": settle_steps,
                        "interpolation_fraction": 1.0,
                        "start_qpos": _vector(start),
                        "target_qpos": _vector(target),
                    },
                )
                actual = _read_dofs(robot, all_indices)
                if max(
                    abs(actual[index] - float(target[index]))
                    for index in all_arm_indices
                ) <= float(contract["maximum_arm_tracking_error_rad"]):
                    consecutive += 1
                    if consecutive >= required:
                        break
                else:
                    consecutive = 0
            final_error = max(
                abs(
                    _read_dofs(robot, all_indices)[index]
                    - float(target[index])
                )
                for index in all_arm_indices
            )
            if final_error > float(contract["maximum_arm_tracking_error_rad"]):
                raise RuntimeError(
                    f"{stage} arm tracking error {final_error:.6f} exceeds limit"
                )
            return final_error

        def command_smooth_path(
            stage: str,
            path: list[np.ndarray],
            duration_s: float,
        ) -> None:
            # Arm start comes from the readback; gripper start comes from the last
            # commanded action so post-contact finger readbacks cannot seed an
            # asymmetric gripper interpolation between moves.
            start = np.asarray(
                build_interpolation_start(
                    readback=_read_dofs(robot, all_indices),
                    previous_action=current_action,
                    arm_indices=all_arm_indices,
                    gripper_indices=all_gripper_indices,
                    expected_length=len(all_indices),
                ),
                dtype=float,
            )
            nodes = [start, *path]
            steps = max(1, int(math.ceil(duration_s / dt)))
            for step in range(1, steps + 1):
                progress = step / steps
                smooth = (
                    10.0 * progress**3
                    - 15.0 * progress**4
                    + 6.0 * progress**5
                )
                coordinate = min(float(len(path)), smooth * len(path))
                segment = min(len(path) - 1, int(coordinate))
                alpha = coordinate - segment
                if step == steps:
                    alpha = 1.0
                target = nodes[segment] + alpha * (
                    nodes[segment + 1] - nodes[segment]
                )
                advance(
                    target,
                    stage,
                    command_context={
                        "stage": stage,
                        "phase": "interpolation",
                        "step_index": step,
                        "total_steps": steps,
                        "interpolation_fraction": progress,
                        "start_qpos": _vector(start),
                        "target_qpos": _vector(path[-1]),
                    },
                )
            required = int(contract["waypoint_settle_consecutive_steps"])
            settle_steps = max(
                1,
                int(
                    math.ceil(
                        float(contract["waypoint_settle_timeout_s"]) / dt
                    )
                ),
            )
            consecutive = 0
            final_target = path[-1]
            for settle_step in range(1, settle_steps + 1):
                advance(
                    final_target,
                    stage,
                    command_context={
                        "stage": stage,
                        "phase": "settle",
                        "step_index": settle_step,
                        "total_steps": settle_steps,
                        "interpolation_fraction": 1.0,
                        "start_qpos": _vector(start),
                        "target_qpos": _vector(final_target),
                    },
                )
                actual = _read_dofs(robot, all_indices)
                if max(
                    abs(actual[index] - float(final_target[index]))
                    for index in all_arm_indices
                ) <= float(contract["maximum_arm_tracking_error_rad"]):
                    consecutive += 1
                    if consecutive >= required:
                        break
                else:
                    consecutive = 0
            final_error = max(
                abs(
                    _read_dofs(robot, all_indices)[index]
                    - float(final_target[index])
                )
                for index in all_arm_indices
            )
            if final_error > float(contract["maximum_arm_tracking_error_rad"]):
                raise RuntimeError(
                    f"{stage} arm tracking error {final_error:.6f} exceeds limit"
                )

        def wait_policy_frames(
            count: int,
            target: np.ndarray,
            stage: str,
        ) -> None:
            goal_frame = policy_step() + count
            while policy_step() < goal_frame:
                advance(target, stage)

        def weld_registered(robot_link_index: int, bowl_link_index: int) -> bool:
            constraints = scene.rigid_solver.get_weld_constraints()
            link_a = [int(value) for value in _vector(constraints["link_a"])]
            link_b = [int(value) for value in _vector(constraints["link_b"])]
            return any(
                {a, b} == {robot_link_index, bowl_link_index}
                for a, b in zip(link_a, link_b)
            )

        def release_pose_snapshot(
            *,
            label: str,
            selected_bowl: Any,
            robot_link: Any,
            bowl_link: Any,
            assigned_side: str,
            weld_active: bool,
            supporting_bowl: Any | None,
            supporting_bowl_name: str | None,
        ) -> dict[str, Any]:
            """Read one release-frame pose/contact snapshot without stepping."""

            policy_before = policy_step()
            sim_before = sim_step
            suction_position = _vector(robot_link.get_pos())
            suction_quaternion = list(
                normalize_quaternion_wxyz(_vector(robot_link.get_quat()))
            )
            bowl_position = _vector(bowl_link.get_pos())
            bowl_quaternion = list(
                normalize_quaternion_wxyz(_vector(bowl_link.get_quat()))
            )
            pairs = sorted(
                _contact_pairs(
                    robot.get_contacts(with_entity=selected_bowl),
                    labels,
                )
            )
            active_clamp_links = sorted(
                {
                    item.split(":")[1]
                    for pair in pairs
                    for item in pair.split(" <> ")
                    if item.startswith(f"mantis:{assigned_side}_clamp")
                }
            )
            relative_pose = relative_pose_wxyz(
                reference_position_xyz_m=suction_position,
                reference_quaternion_wxyz=suction_quaternion,
                target_position_xyz_m=bowl_position,
                target_quaternion_wxyz=bowl_quaternion,
            )
            support_schema_active = (
                level1_release_contract is not None
                and level1_release_contract["single_primary_variable"][
                    "candidate"
                ]
                == "relative_pose_robot_and_support_contact_trace_v2"
            )
            support_pairs: list[str] = []
            support_diagnostics: dict[str, Any] = {}
            if support_schema_active and supporting_bowl is not None:
                support_info = selected_bowl.get_contacts(
                    with_entity=supporting_bowl
                )
                support_pairs = sorted(_contact_pairs(support_info, labels))
                support_diagnostics = _contact_diagnostics(support_info)
            policy_after = policy_step()
            sim_after = sim_step
            if policy_after != policy_before or sim_after != sim_before:
                raise RuntimeError(
                    "level1-release observability advanced the control clock"
                )
            snapshot = {
                "label": label,
                "policy_step": policy_before,
                "physics_step": sim_before,
                "weld_registered": weld_active,
                "suction_link_position_xyz_m": suction_position,
                "suction_link_quaternion_wxyz": suction_quaternion,
                "bowl_position_xyz_m": bowl_position,
                "bowl_quaternion_wxyz": bowl_quaternion,
                "bowl_in_suction_frame": relative_pose,
                "selected_bowl_contact_pairs": pairs,
                "selected_bowl_contact_pair_count": len(pairs),
                "active_side_clamp_links_in_contact": active_clamp_links,
                "observer_policy_step_delta": policy_after - policy_before,
                "observer_physics_step_delta": sim_after - sim_before,
            }
            if support_schema_active:
                snapshot.update(
                    {
                        "support_contact_query_applicable": (
                            supporting_bowl is not None
                        ),
                        "supporting_bowl_name": supporting_bowl_name,
                        "support_contact_pairs": support_pairs,
                        "support_contact_pair_count": len(support_pairs),
                        "support_contact_diagnostics": support_diagnostics,
                        "contact_cache_source_physics_step": sim_before,
                        "contact_cache_semantics": (
                            "most_recent_scene_step"
                        ),
                    }
                )
            return snapshot

        def begin_release_observability(
            *,
            level: int,
            bowl_name: str,
            selected_bowl: Any,
            robot_link: Any,
            bowl_link: Any,
            assigned_side: str,
            suction_link_name: str,
            supporting_bowl: Any | None,
            supporting_bowl_name: str | None,
        ) -> dict[str, Any] | None:
            """Create a fresh per-bowl trace before registering its weld."""

            if level1_release_contract is None:
                return None
            return {
                "schema_version": 1,
                "work_package_id": level1_release_contract["work_package_id"],
                "observability_schema": level1_release_contract[
                    "single_primary_variable"
                ]["candidate"],
                "level": level,
                "bowl": bowl_name,
                "assigned_side": assigned_side,
                "suction_link": suction_link_name,
                "snapshots": [
                    release_pose_snapshot(
                        label="contact_before_weld",
                        selected_bowl=selected_bowl,
                        robot_link=robot_link,
                        bowl_link=bowl_link,
                        assigned_side=assigned_side,
                        weld_active=False,
                        supporting_bowl=supporting_bowl,
                        supporting_bowl_name=supporting_bowl_name,
                    )
                ],
            }

        bowl_runs: list[dict[str, Any]] = []
        target_x, target_y = (
            float(value) for value in contract["transport_target_xy_m"]
        )
        source_grasp = scene_contract["contact_probe"]
        grasp_orientation = np.asarray(
            source_grasp["orientation_wxyz"],
            dtype=float,
        )
        transit_orientation = np.asarray(
            source_grasp["transit_orientation_wxyz"],
            dtype=float,
        )
        pregrasp_orientation = np.asarray(
            source_grasp["pregrasp_orientation_wxyz"],
            dtype=float,
        )
        height_offsets = [0.0, 0.03, 0.07]
        current = np.asarray(_read_dofs(robot, all_indices), dtype=float)

        for level, pose in enumerate(ordered_reset):
            active_bowl_name = pose.name
            selected_bowl = bowls_by_name[pose.name]
            supporting_bowl_name = (
                ordered_reset[level - 1].name if level > 0 else None
            )
            supporting_bowl = (
                bowls_by_name[supporting_bowl_name]
                if supporting_bowl_name is not None
                else None
            )
            source_assigned_side = arm_for_bowl_x(pose.position_xyz_m[0])
            assigned_side = source_assigned_side
            active_side_name = assigned_side
            source_x, source_y, _ = pose.position_xyz_m
            inactive_side = "right" if assigned_side == "left" else "left"
            side_gripper_indices = gripper_indices_by_side[assigned_side]
            level1_release_observability: dict[str, Any] | None = None
            if level > 0 and bowl_runs[-1]["assigned_side"] != assigned_side:
                park_target = current.copy()
                for index in (
                    arm_indices_by_side[inactive_side]
                    + gripper_indices_by_side[inactive_side]
                ):
                    park_target[index] = open_qpos[index]
                command_segment(
                    f"{pose.name}:park_inactive_{inactive_side}",
                    park_target,
                    1.0,
                )
                current = park_target
            if assigned_side == "left":
                grasp_y = (
                    source_y + float(source_grasp["grasp_center_y_offset_m"])
                )
                grasp_z = float(source_grasp["grasp_tcp_z_m"])
                place_position = np.asarray(
                    [
                        target_x,
                        target_y
                        + float(source_grasp["grasp_center_y_offset_m"]),
                        grasp_z + height_offsets[level],
                    ],
                    dtype=float,
                )
                grasp_position = np.asarray(
                    [source_x, grasp_y, grasp_z],
                    dtype=float,
                )
                pregrasp_position = grasp_position.copy()
                pregrasp_position[2] += float(
                    source_grasp["pregrasp_retreat_z_m"]
                )
                rim_clearance_position = np.asarray(
                    [
                        source_x,
                        grasp_y,
                        float(source_grasp["transit_clearance_z_m"]),
                    ],
                    dtype=float,
                )
                front_clearance_position = np.asarray(
                    [
                        source_x,
                        float(source_grasp["transit_front_y_m"]),
                        float(source_grasp["transit_clearance_z_m"]),
                    ],
                    dtype=float,
                )
                lift_position = grasp_position.copy()
                lift_position[2] += float(
                    source_grasp["vertical_lift_distance_m"]
                )
                active_orientations = {
                    "front_clearance": transit_orientation,
                    "rim_clearance": transit_orientation,
                    "pregrasp": pregrasp_orientation,
                    "approach": grasp_orientation,
                    "lift": grasp_orientation,
                    "transport": grasp_orientation,
                    "place": grasp_orientation,
                    "retreat": grasp_orientation,
                }
                grasp_close_pose = closed_qpos
                transport_gripper_pose = closed_qpos
                minimum_duration = float(
                    source_grasp["minimum_segment_duration_s"]
                )
                approach_duration = minimum_duration
                close_duration = float(
                    source_grasp["gripper_close_duration_s"]
                )
                hold_duration = float(source_grasp["post_close_hold_s"])
                lift_duration = float(
                    source_grasp["vertical_lift_duration_s"]
                )
                grasp_mode = "assigned_left_top_down_near_rim_suction"
            else:
                base_grasp_z = float(source_grasp["grasp_tcp_z_m"])
                calibrated_forward_offset = float(
                    source_grasp["grasp_center_y_offset_m"]
                )
                finger_forward_extent_m = float(source_grasp["finger_forward_extent_m"])
                grasp_candidates = right_grasp_pose_candidates(
                    base_grasp_z,
                    calibrated_forward_offset,
                    finger_forward_extent_m,
                )

                # Replay mode: validate and use only the planned candidate
                if generation_mode == "replay" and replay_plan is not None:
                    planned_step = replay_plan.steps[level]
                    if planned_step.assigned_side != "right":
                        raise ValueError(f"Replay plan level {level} expected side {planned_step.assigned_side}, got right")
                    # Validate the planned candidate tuple exists in current candidates
                    validate_candidate_tuple(
                        planned_step.right_grasp_candidate_tuple,
                        grasp_candidates,
                        planned_step.right_grasp_candidate_index,
                        "right",
                    )
                    # Set loop to only try the planned candidate
                    candidate_indices_to_try = [planned_step.right_grasp_candidate_index]
                elif generation_mode == "probe":
                    # Reorder only the probe visit sequence. The recorded
                    # candidate_index remains the original stable index.
                    candidate_indices_to_try = right_probe_candidate_search_order(
                        len(grasp_candidates)
                    )
                else:
                    # Online mode keeps the canonical 0..8 order.
                    candidate_indices_to_try = list(range(len(grasp_candidates)))

                grasp_attempts: list[dict[str, Any]] = []
                successful_candidate_index: int | None = None
                grasp_position = np.zeros(3, dtype=float)
                grasp_z = 0.0
                forward_offset = 0.0
                x_offset = 0.0
                place_position = np.asarray(
                    [
                        target_x,
                        target_y
                        + float(source_grasp["grasp_center_y_offset_m"]),
                        base_grasp_z - 0.04 + height_offsets[level],
                    ],
                    dtype=float,
                )
                right_orientation = np.asarray(
                    scene_contract["tcp"]["orientation_wxyz"],
                    dtype=float,
                )
                active_orientations = {
                    stage: right_orientation
                    for stage in (
                        "front_clearance",
                        "rim_clearance",
                        "pregrasp",
                        "approach",
                        "lift",
                        "transport",
                        "place",
                        "retreat",
                    )
                }
                grasp_close_pose = closed_qpos
                transport_gripper_pose = closed_qpos
                minimum_duration = float(
                    source_grasp["minimum_segment_duration_s"]
                )
                approach_duration = 1.0
                close_duration = float(
                    source_grasp["gripper_close_duration_s"]
                )
                hold_duration = float(source_grasp["post_close_hold_s"])
                lift_duration = 1.0
                grasp_mode = "assigned_right_forward_rim_pinch_suction"

            # Replay mode: apply frozen plan offset BEFORE transport/place planning and execution
            if generation_mode == "replay" and replay_plan is not None:
                planned_step = replay_plan.steps[level]
                if planned_step.assigned_side != assigned_side:
                    raise ValueError(f"Replay plan level {level} expected side {planned_step.assigned_side}, got {assigned_side}")

                # Validate offset is finite and bounded
                validate_finite_offset(planned_step.place_xy_offset_m)

                # Apply frozen offset to nominal place position BEFORE transport_position construction
                frozen_offset = planned_step.place_xy_offset_m
                place_position = place_position.copy()
                place_position[0] += frozen_offset[0]
                place_position[1] += frozen_offset[1]

            transport_position = place_position.copy()
            transport_position[2] = max(
                float(contract["transport_tcp_z_m"]),
                float(place_position[2]) + 0.06,
            )
            if assigned_side == "right":
                transport_position[2] = max(
                    float(transport_position[2]),
                    1.02,
                )
            retreat_position = transport_position.copy()

            stage_orientation = active_orientations
            qpos: dict[str, np.ndarray] = {}
            ik_errors: dict[str, dict[str, dict[str, float]]] = {}
            consecutive_left_transition_active = False
            consecutive_left_transition_positions: dict[
                str, list[tuple[float, float, float]]
            ] = {}
            consecutive_left_transition_paths: dict[str, list[np.ndarray]] = {}
            consecutive_left_transition_orientation_waypoints: dict[
                str, list[list[float]]
            ] = {}

            if assigned_side == "left":
                positions = {
                    "front_clearance": {assigned_side: front_clearance_position},
                    "rim_clearance": {assigned_side: rim_clearance_position},
                    "pregrasp": {assigned_side: pregrasp_position},
                    "approach": {assigned_side: grasp_position},
                    "lift": {assigned_side: lift_position},
                    "transport": {assigned_side: transport_position},
                    "place": {assigned_side: place_position},
                    "retreat": {assigned_side: retreat_position},
                }
                consecutive_left_transition_active = (
                    level >= 2
                    and bool(bowl_runs)
                    and bowl_runs[-1]["assigned_side"] == "left"
                )
                if consecutive_left_transition_active:
                    consecutive_left_transition_positions = (
                        build_consecutive_left_transition_positions(
                            previous_retreat_position_xyz_m=bowl_runs[-1][
                                "transport_tcp_position_xyz_m"
                            ],
                            next_front_clearance_position_xyz_m=(
                                front_clearance_position.tolist()
                            ),
                            clearance_tcp_z_m=(
                                consecutive_left_transition_contract[
                                    "clearance_tcp_z_m"
                                ]
                            ),
                            cartesian_waypoints_per_segment=(
                                consecutive_left_transition_contract[
                                    "cartesian_waypoints_per_segment"
                                ]
                            ),
                        )
                    )
                    if args.transition_ik_matrix_only:
                        assert transition_ik_matrix_contract is not None
                        if level != 2 or len(bowl_runs) != 2:
                            raise RuntimeError(
                                "transition IK matrix must activate after "
                                "exactly two completed bowl levels"
                            )
                        candidate_poses = (
                            build_consecutive_left_transition_ik_candidates(
                                route_positions=(
                                    consecutive_left_transition_positions
                                ),
                                grasp_orientation_wxyz=grasp_orientation,
                                transit_orientation_wxyz=transit_orientation,
                            )
                        )
                        matrix_policy_step_before = policy_step()
                        robot_qpos_before = np.asarray(
                            _read_dofs(robot, all_indices),
                            dtype=float,
                        )
                        bowl_positions_before = {
                            name: np.asarray(
                                _vector(entity.get_pos()),
                                dtype=float,
                            )
                            for name, entity in bowls_by_name.items()
                        }
                        bowl_quaternions_before = {
                            name: np.asarray(
                                _vector(entity.get_quat()),
                                dtype=float,
                            )
                            for name, entity in bowls_by_name.items()
                        }
                        safety_failure_count_before = len(safety_failures)
                        position_tolerance = float(
                            ik["position_tolerance_m"]
                        )
                        rotation_tolerance = float(
                            ik["rotation_tolerance_rad"]
                        )
                        candidate_results: list[dict[str, Any]] = []
                        for candidate_index, (
                            candidate_id,
                            candidate_pose_rows,
                        ) in enumerate(candidate_poses.items()):
                            candidate_current = current.copy()
                            waypoint_results: list[dict[str, Any]] = []
                            fully_reachable = True
                            for candidate_pose in candidate_pose_rows:
                                stage_name = str(candidate_pose["stage"])
                                waypoint_index = int(
                                    candidate_pose["waypoint_index"]
                                )
                                waypoint_count = int(
                                    candidate_pose["waypoint_count"]
                                )
                                matrix_key = (
                                    f"{candidate_id}:{stage_name}:"
                                    f"{waypoint_index:02d}_of_"
                                    f"{waypoint_count:02d}"
                                )
                                solved_qpos, solved_errors = solve_stage(
                                    f"{pose.name}:transition_ik_matrix:"
                                    f"{matrix_key}",
                                    {
                                        assigned_side: np.asarray(
                                            candidate_pose[
                                                "position_xyz_m"
                                            ],
                                            dtype=float,
                                        )
                                    },
                                    candidate_current,
                                    orientation_override={
                                        assigned_side: np.asarray(
                                            candidate_pose[
                                                "orientation_wxyz"
                                            ],
                                            dtype=float,
                                        )
                                    },
                                    raise_on_tolerance_failure=False,
                                )
                                error = solved_errors[assigned_side]
                                position_error = float(
                                    error["position_error_m"]
                                )
                                rotation_error = float(
                                    error["rotation_error_rad"]
                                )
                                waypoint_pass = (
                                    position_error <= position_tolerance
                                    and rotation_error
                                    <= rotation_tolerance
                                )
                                normalized_slack = min(
                                    1.0
                                    - position_error / position_tolerance,
                                    1.0
                                    - rotation_error / rotation_tolerance,
                                )
                                waypoint_results.append(
                                    {
                                        "stage": stage_name,
                                        "waypoint_index": waypoint_index,
                                        "waypoint_count": waypoint_count,
                                        "position_xyz_m": list(
                                            candidate_pose[
                                                "position_xyz_m"
                                            ]
                                        ),
                                        "orientation_wxyz": list(
                                            candidate_pose[
                                                "orientation_wxyz"
                                            ]
                                        ),
                                        "position_error_m": position_error,
                                        "rotation_error_rad": rotation_error,
                                        "position_tolerance_m": (
                                            position_tolerance
                                        ),
                                        "rotation_tolerance_rad": (
                                            rotation_tolerance
                                        ),
                                        "normalized_slack": (
                                            normalized_slack
                                        ),
                                        "within_tolerance": waypoint_pass,
                                    }
                                )
                                if not waypoint_pass:
                                    fully_reachable = False
                                    break
                                candidate_current = solved_qpos
                            candidate_results.append(
                                {
                                    "candidate_id": candidate_id,
                                    "candidate_order_index": (
                                        candidate_index
                                    ),
                                    "declared_waypoint_count": len(
                                        candidate_pose_rows
                                    ),
                                    "evaluated_waypoint_count": len(
                                        waypoint_results
                                    ),
                                    "fully_reachable": fully_reachable,
                                    "first_failure": (
                                        None
                                        if fully_reachable
                                        else waypoint_results[-1]
                                    ),
                                    "minimum_normalized_slack": min(
                                        row["normalized_slack"]
                                        for row in waypoint_results
                                    ),
                                    "waypoints": waypoint_results,
                                }
                            )

                        matrix_policy_step_after = policy_step()
                        robot_qpos_after = np.asarray(
                            _read_dofs(robot, all_indices),
                            dtype=float,
                        )
                        bowl_positions_after = {
                            name: np.asarray(
                                _vector(entity.get_pos()),
                                dtype=float,
                            )
                            for name, entity in bowls_by_name.items()
                        }
                        bowl_quaternions_after = {
                            name: np.asarray(
                                _vector(entity.get_quat()),
                                dtype=float,
                            )
                            for name, entity in bowls_by_name.items()
                        }
                        robot_qpos_max_delta = float(
                            np.max(
                                np.abs(
                                    robot_qpos_after
                                    - robot_qpos_before
                                )
                            )
                        )
                        bowl_position_max_delta = max(
                            float(
                                np.max(
                                    np.abs(
                                        bowl_positions_after[name]
                                        - bowl_positions_before[name]
                                    )
                                )
                            )
                            for name in bowls_by_name
                        )
                        bowl_quaternion_max_delta = max(
                            float(
                                min(
                                    np.linalg.norm(
                                        bowl_quaternions_after[name]
                                        - bowl_quaternions_before[name]
                                    ),
                                    np.linalg.norm(
                                        bowl_quaternions_after[name]
                                        + bowl_quaternions_before[name]
                                    ),
                                )
                            )
                            for name in bowls_by_name
                        )
                        acceptance = transition_ik_matrix_contract[
                            "acceptance"
                        ]
                        negative_gate = acceptance["negative_control"]
                        negative_result = candidate_results[0]
                        negative_failure = negative_result["first_failure"]
                        negative_control_pass = (
                            negative_result["candidate_id"]
                            == G3_LEFT_IK_MATRIX_CANDIDATES[0]
                            and negative_result["fully_reachable"] is False
                            and negative_failure is not None
                            and negative_failure["stage"]
                            == negative_gate["failure_stage"]
                            and float(
                                negative_gate[
                                    "position_error_m_interval"
                                ][0]
                            )
                            <= negative_failure["position_error_m"]
                            <= float(
                                negative_gate[
                                    "position_error_m_interval"
                                ][1]
                            )
                            and float(
                                negative_gate[
                                    "rotation_error_rad_interval"
                                ][0]
                            )
                            <= negative_failure["rotation_error_rad"]
                            <= float(
                                negative_gate[
                                    "rotation_error_rad_interval"
                                ][1]
                            )
                        )
                        candidate_gate = acceptance["candidate_gate"]
                        state_invariance_pass = (
                            matrix_policy_step_after
                            - matrix_policy_step_before
                            == int(
                                candidate_gate[
                                    "policy_step_delta_during_candidate_matrix"
                                ]
                            )
                            and robot_qpos_max_delta
                            <= float(
                                candidate_gate[
                                    "robot_qpos_max_delta_during_candidate_matrix"
                                ]
                            )
                            and bowl_position_max_delta
                            <= float(
                                candidate_gate[
                                    "bowl_position_max_delta_during_candidate_matrix_m"
                                ]
                            )
                            and len(safety_failures)
                            == safety_failure_count_before
                        )
                        reachable_candidates = [
                            result
                            for result in candidate_results[1:]
                            if result["fully_reachable"]
                        ]
                        selected_candidate = (
                            max(
                                reachable_candidates,
                                key=lambda result: (
                                    result[
                                        "minimum_normalized_slack"
                                    ],
                                    -result["candidate_order_index"],
                                ),
                            )
                            if reachable_candidates
                            else None
                        )
                        terminal_status = (
                            "COMPLETE_IK_MATRIX_ACCEPTED"
                            if (
                                negative_control_pass
                                and state_invariance_pass
                                and len(reachable_candidates)
                                >= int(
                                    candidate_gate[
                                        "minimum_fully_reachable_candidates"
                                    ]
                                )
                            )
                            else "COMPLETE_IK_MATRIX_REJECTED"
                        )
                        matrix_receipt = {
                            "schema_version": 1,
                            "work_package_id": "WP-G3-CORR-009-R2",
                            "terminal_status": terminal_status,
                            "run_id": args.run_id,
                            "seed": seed,
                            "backend": "cpu",
                            "cuda_visible_devices": "",
                            "capture_requested": False,
                            "retry_count": 0,
                            "matrix_only_after_level_1": True,
                            "candidate_solve_advances_physics": False,
                            "policy_step_before_matrix": (
                                matrix_policy_step_before
                            ),
                            "policy_step_after_matrix": (
                                matrix_policy_step_after
                            ),
                            "policy_step_delta_during_matrix": (
                                matrix_policy_step_after
                                - matrix_policy_step_before
                            ),
                            "robot_qpos_max_delta_during_matrix": (
                                robot_qpos_max_delta
                            ),
                            "bowl_position_max_delta_during_matrix_m": (
                                bowl_position_max_delta
                            ),
                            "bowl_quaternion_max_sign_invariant_l2_delta": (
                                bowl_quaternion_max_delta
                            ),
                            "safety_failure_count_before_matrix": (
                                safety_failure_count_before
                            ),
                            "safety_failure_count_after_matrix": len(
                                safety_failures
                            ),
                            "position_tolerance_m": position_tolerance,
                            "rotation_tolerance_rad": (
                                rotation_tolerance
                            ),
                            "negative_control_pass": (
                                negative_control_pass
                            ),
                            "state_invariance_pass": (
                                state_invariance_pass
                            ),
                            "reachable_candidate_count": len(
                                reachable_candidates
                            ),
                            "selected_candidate_id": (
                                None
                                if selected_candidate is None
                                else selected_candidate["candidate_id"]
                            ),
                            "selection_rule": (
                                transition_ik_matrix_contract["matrix"][
                                    "selection_rule"
                                ]
                            ),
                            "candidate_results": candidate_results,
                            "tool_sha256": sha256_file(Path(__file__)),
                            "scene_contract_sha256": sha256_file(
                                args.scene_contract
                            ),
                            "matrix_contract_sha256": sha256_file(
                                args.transition_ik_matrix_contract
                            ),
                            "episode_success": False,
                            "training_data_claim": False,
                            "learned_policy_claim": False,
                            "rocm_claim": False,
                            "claim_boundary": (
                                transition_ik_matrix_contract[
                                    "claim_boundary"
                                ]
                            ),
                        }
                        matrix_receipt_path = (
                            run_dir
                            / "transition_ik_matrix_level_2.json"
                        )
                        with matrix_receipt_path.open(
                            "x",
                            encoding="utf-8",
                        ) as handle:
                            json.dump(
                                matrix_receipt,
                                handle,
                                indent=2,
                                sort_keys=True,
                            )
                            handle.write("\n")
                        finish_run(
                            args.ops_root,
                            args.run_id,
                            "completed",
                            {
                                "terminal_status": terminal_status,
                                "matrix_receipt_sha256": sha256_file(
                                    matrix_receipt_path
                                ),
                                "selected_candidate_id": (
                                    matrix_receipt[
                                        "selected_candidate_id"
                                    ]
                                ),
                                "episode_success": False,
                                "training_data_claim": False,
                            },
                        )
                        receipt_written = True
                        print(
                            json.dumps(
                                matrix_receipt,
                                indent=2,
                                sort_keys=True,
                            )
                        )
                        return (
                            0
                            if terminal_status
                            == "COMPLETE_IK_MATRIX_ACCEPTED"
                            else 2
                        )
                    transition_current = current
                    if (
                        args.consecutive_left_orientation_schedule
                        == "coupled_descent_slerp"
                    ):
                        candidate_rows = (
                            build_consecutive_left_transition_ik_candidates(
                                route_positions=(
                                    consecutive_left_transition_positions
                                ),
                                grasp_orientation_wxyz=grasp_orientation,
                                transit_orientation_wxyz=transit_orientation,
                            )["coupled_descent_slerp"]
                        )
                        transition_pose_rows = {
                            stage: [
                                row
                                for row in candidate_rows
                                if row["stage"] == stage
                            ]
                            for stage in (
                                "vertical_clearance",
                                "lateral_clearance",
                                "descend_to_front_clearance",
                            )
                        }
                    else:
                        transition_orientations = {
                            "vertical_clearance": grasp_orientation,
                            "reorient_at_clearance": transit_orientation,
                            "lateral_clearance": transit_orientation,
                            "descend_to_front_clearance": transit_orientation,
                        }
                        transition_pose_rows = {
                            stage: [
                                {
                                    "stage": stage,
                                    "waypoint_index": index,
                                    "waypoint_count": len(
                                        consecutive_left_transition_positions[
                                            stage
                                        ]
                                    ),
                                    "position_xyz_m": position,
                                    "orientation_wxyz": (
                                        transition_orientations[stage]
                                    ),
                                }
                                for index, position in enumerate(
                                    consecutive_left_transition_positions[
                                        stage
                                    ],
                                    start=1,
                                )
                            ]
                            for stage in (
                                "vertical_clearance",
                                "reorient_at_clearance",
                                "lateral_clearance",
                                "descend_to_front_clearance",
                            )
                        }
                    for transition_stage, stage_pose_rows in (
                        transition_pose_rows.items()
                    ):
                        stage_path: list[np.ndarray] = []
                        stage_orientations: list[list[float]] = []
                        for pose_row in stage_pose_rows:
                            waypoint_index = int(
                                pose_row["waypoint_index"]
                            )
                            waypoint_count = int(
                                pose_row["waypoint_count"]
                            )
                            waypoint_position = pose_row["position_xyz_m"]
                            waypoint_orientation = pose_row[
                                "orientation_wxyz"
                            ]
                            waypoint_key = (
                                f"inter_bowl_{transition_stage}_"
                                f"{waypoint_index:02d}_of_"
                                f"{waypoint_count:02d}"
                            )
                            transition_current, ik_errors[waypoint_key] = (
                                solve_stage(
                                    f"{pose.name}:{waypoint_key}",
                                    {
                                        assigned_side: np.asarray(
                                            waypoint_position,
                                            dtype=float,
                                        )
                                    },
                                    transition_current,
                                    orientation_override={
                                        assigned_side: np.asarray(
                                            waypoint_orientation,
                                            dtype=float,
                                        )
                                    },
                                )
                            )
                            stage_path.append(transition_current)
                            stage_orientations.append(
                                [
                                    float(value)
                                    for value in waypoint_orientation
                                ]
                            )
                        consecutive_left_transition_paths[
                            transition_stage
                        ] = stage_path
                        consecutive_left_transition_orientation_waypoints[
                            transition_stage
                        ] = stage_orientations
                    qpos["front_clearance"] = consecutive_left_transition_paths[
                        "descend_to_front_clearance"
                    ][-1]
                    current = qpos["front_clearance"]
                solve_stages = (
                    *(
                        ()
                        if consecutive_left_transition_active
                        else ("front_clearance",)
                    ),
                    "rim_clearance",
                    *(
                        ()
                        if pose.name == "bowl3"
                        else ("pregrasp",)
                    ),
                    "approach",
                    "lift",
                )
                for stage in solve_stages:
                    qpos[stage], ik_errors[stage] = solve_stage(
                        f"{pose.name}:{stage}",
                        positions[stage],
                        current,
                        orientation_override={
                            assigned_side: stage_orientation[stage]
                        },
                    )
                    current = qpos[stage]
            else:
                front_clearance_position = np.asarray(
                    [
                        source_x,
                        float(source_grasp["transit_front_y_m"]),
                        float(source_grasp["transit_clearance_z_m"]),
                    ],
                    dtype=float,
                )
                qpos["front_clearance"], ik_errors["front_clearance"] = solve_stage(
                    f"{pose.name}:front_clearance",
                    {assigned_side: front_clearance_position},
                    current,
                    orientation_override={
                        assigned_side: stage_orientation["front_clearance"]
                    },
                )
                current = qpos["front_clearance"]

                command_segment(
                    f"{pose.name}:front_clearance",
                    qpos["front_clearance"],
                    minimum_duration,
                )

                # Freeze baseline: after first command_segment to front_clearance, capture baseline state
                candidate_baseline_qpos = qpos["front_clearance"].copy()
                # Capture initial bowl state for drift detection
                initial_bowl_position = np.asarray(_vector(selected_bowl.get_pos()), dtype=float)
                initial_bowl_quaternion = np.asarray(_vector(selected_bowl.get_quat()), dtype=float)
                # Initialize probe reset counter for this bowl
                probe_candidate_reset_count = 0

                for loop_idx, candidate_index in enumerate(candidate_indices_to_try):
                    # For loop_idx>0, return to baseline before starting new candidate
                    if loop_idx > 0:
                        # Return to frozen baseline (has internal maximum_arm_tracking_error_rad readback gate)
                        command_segment(
                            f"{pose.name}:return_to_baseline_candidate_{loop_idx}",
                            candidate_baseline_qpos,
                            minimum_duration,
                        )
                        # Set current to baseline for this candidate's solve_stage init
                        current = candidate_baseline_qpos

                        # Bowl drift check: verify selected_bowl hasn't moved since loop start
                        current_bowl_position = np.asarray(_vector(selected_bowl.get_pos()), dtype=float)
                        current_bowl_quaternion = np.asarray(_vector(selected_bowl.get_quat()), dtype=float)

                        # Position tolerance from scene_contract ik_gate
                        position_tolerance = float(scene_contract["ik_gate"]["position_tolerance_m"])
                        position_error = np.linalg.norm(current_bowl_position - initial_bowl_position)
                        if position_error > position_tolerance:
                            raise RuntimeError(
                                f"{pose.name} bowl position drift exceeded tolerance before candidate {candidate_index}: "
                                f"error={position_error:.6f} m, tolerance={position_tolerance:.6f} m"
                            )

                        # Quaternion tolerance: sign-invariant L2 using rotation_tolerance_rad
                        rotation_tolerance = float(scene_contract["ik_gate"]["rotation_tolerance_rad"])
                        # Sign-invariant quaternion comparison: use min distance considering both signs
                        quat_diff = current_bowl_quaternion - initial_bowl_quaternion
                        quat_sum = current_bowl_quaternion + initial_bowl_quaternion
                        quat_l2_diff = np.linalg.norm(quat_diff)
                        quat_l2_sum = np.linalg.norm(quat_sum)
                        rotation_error = min(quat_l2_diff, quat_l2_sum)
                        if rotation_error > rotation_tolerance:
                            raise RuntimeError(
                                f"{pose.name} bowl orientation drift exceeded tolerance before candidate {candidate_index}: "
                                f"error={rotation_error:.6f} rad, tolerance={rotation_tolerance:.6f} rad"
                            )

                    candidate_x, candidate_forward, candidate_z = grasp_candidates[candidate_index]
                    grasp_attempt = {
                        "candidate_index": candidate_index,
                        "x_offset_m": candidate_x,
                        "forward_offset_m": candidate_forward,
                        "grasp_z_m": candidate_z,
                    }
                    grasp_z = candidate_z
                    forward_offset = candidate_forward
                    x_offset = candidate_x

                    candidate_grasp_position = np.asarray(
                        [source_x + candidate_x, source_y + forward_offset, grasp_z],
                        dtype=float,
                    )
                    candidate_pregrasp_position = candidate_grasp_position.copy()
                    candidate_pregrasp_position[1] -= 0.04

                    # Use frozen candidate_baseline_qpos for solve_stage init (not current from failed attempt)
                    candidate_pregrasp_qpos, candidate_pregrasp_ik_errors = solve_stage(
                        f"{pose.name}:candidate_{candidate_index}_pregrasp",
                        {assigned_side: candidate_pregrasp_position},
                        candidate_baseline_qpos,  # Always init from frozen baseline
                        orientation_override={
                            assigned_side: stage_orientation["pregrasp"]
                        },
                    )
                    command_segment(
                        f"{pose.name}:candidate_{candidate_index}_pregrasp",
                        candidate_pregrasp_qpos,
                        minimum_duration,
                    )

                    candidate_approach_qpos, candidate_approach_ik_errors = solve_stage(
                        f"{pose.name}:candidate_{candidate_index}_approach",
                        {assigned_side: candidate_grasp_position},
                        candidate_pregrasp_qpos,
                        orientation_override={
                            assigned_side: stage_orientation["approach"]
                        },
                    )
                    grasp_attempt["approach_ik_errors"] = candidate_approach_ik_errors
                    command_segment(
                        f"{pose.name}:candidate_{candidate_index}_approach",
                        candidate_approach_qpos,
                        approach_duration,
                    )

                    closed_candidate_approach = candidate_approach_qpos.copy()
                    for index in side_gripper_indices:
                        closed_candidate_approach[index] = grasp_close_pose[index]
                    command_segment(
                        f"{pose.name}:candidate_{candidate_index}_close",
                        closed_candidate_approach,
                        close_duration,
                    )

                    hold_steps = max(
                        1, int(math.ceil(hold_duration / dt))
                    )
                    for _ in range(hold_steps):
                        advance(
                            closed_candidate_approach,
                            f"{pose.name}:candidate_{candidate_index}_hold",
                        )

                    selected_info = robot.get_contacts(with_entity=selected_bowl)
                    selected_pairs = _contact_pairs(selected_info, labels)
                    for pair in selected_pairs:
                        contact_histogram[pair] = (
                            contact_histogram.get(pair, 0) + 1
                        )
                    contacted_links = sorted(
                        {
                            label.split(":")[1]
                            for pair in selected_pairs
                            for label in pair.split(" <> ")
                            if label.startswith(f"mantis:{assigned_side}_clamp")
                            and f"{pose.name}:" in pair
                        }
                    )

                    # For right-side, require both exact clamp links
                    if assigned_side == "right":
                        required_right_links = {
                            "right_clamp_left_link",
                            "right_clamp_right_link",
                        }
                        contact_verified = required_right_links.issubset(set(contacted_links))
                        missing_required_links = sorted(
                            required_right_links - set(contacted_links)
                        )
                        grasp_attempt["contact_requirement"] = "both_right_clamps_required"
                        grasp_attempt["missing_required_contact_links"] = (
                            missing_required_links if missing_required_links else None
                        )
                    else:
                        # Left-side: any single clamp link is sufficient
                        contact_verified = bool(contacted_links)
                        grasp_attempt["contact_requirement"] = "any_left_clamp_sufficient"
                        grasp_attempt["missing_required_contact_links"] = None

                    grasp_attempt["contact_verified"] = contact_verified
                    grasp_attempt["contacted_links"] = contacted_links

                    if contact_verified:
                        successful_candidate_index = candidate_index
                        grasp_position = candidate_grasp_position
                        pregrasp_position = candidate_pregrasp_position
                        grasp_attempts.append(grasp_attempt)
                        current = closed_candidate_approach
                        break
                    else:
                        # Failure recovery: open, retreat to pregrasp, then loop continues to frozen baseline
                        open_retreat = candidate_approach_qpos.copy()
                        for index in side_gripper_indices:
                            open_retreat[index] = open_qpos[index]
                        command_segment(
                            f"{pose.name}:candidate_{candidate_index}_open",
                            open_retreat,
                            close_duration,
                        )

                        # Online/probe mode: safe retreat to pregrasp before next candidate loop
                        # Restore the safe retreat_to_pregrasp that was incorrectly deleted
                        open_pregrasp_retreat = candidate_pregrasp_qpos.copy()
                        for index in side_gripper_indices:
                            open_pregrasp_retreat[index] = open_qpos[index]
                        command_segment(
                            f"{pose.name}:candidate_{candidate_index}_retreat_to_pregrasp",
                            open_pregrasp_retreat,
                            minimum_duration,
                        )

                        # In replay mode, do not try other candidates - fail immediately
                        if generation_mode == "replay":
                            # Record probe_candidate_reset as not applied for replay
                            grasp_attempt["probe_candidate_reset"] = {
                                "applied": False,
                                "reason": "mode_forbids_mid_episode_reset",
                            }
                            grasp_attempts.append(grasp_attempt)
                            raise RuntimeError(
                                f"Replay mode failed at {pose.name}: planned candidate {candidate_index} did not "
                                f"achieve contact verification. No fallback candidates allowed in replay."
                            )

                        # Probe mode: execute diagnostic reset and verify
                        if generation_mode == "probe":
                            # Perform diagnostic reset
                            robot.set_qpos(candidate_baseline_qpos, zero_velocity=True)
                            robot.control_dofs_position(candidate_baseline_qpos, dofs_idx_local=all_indices)
                            selected_bowl.set_pos(initial_bowl_position, zero_velocity=True)
                            selected_bowl.set_quat(initial_bowl_quaternion, zero_velocity=True)
                            selected_bowl.zero_all_dofs_velocity()
                            scene.step()

                            # Sync the commanded-action bookkeeping to the reset so the
                            # next gripper interpolation starts from the symmetric frozen
                            # baseline rather than the post-contact finger readback.
                            current_action = candidate_baseline_qpos.copy()

                            # Read back and validate
                            readback_qpos = _read_dofs(robot, all_indices)
                            readback_bowl_position = np.asarray(_vector(selected_bowl.get_pos()), dtype=float)
                            readback_bowl_quaternion = np.asarray(_vector(selected_bowl.get_quat()), dtype=float)

                            # Compute errors
                            side_arm_indices = arm_indices_by_side[assigned_side]
                            arm_tracking_errors = [
                                abs(readback_qpos[i] - candidate_baseline_qpos[i])
                                for i in side_arm_indices
                            ]
                            arm_tracking_error_rad = max(arm_tracking_errors) if arm_tracking_errors else 0.0

                            bowl_position_error_m = np.linalg.norm(readback_bowl_position - initial_bowl_position)
                            # Sign-invariant quaternion L2
                            quat_diff = readback_bowl_quaternion - initial_bowl_quaternion
                            quat_sum = readback_bowl_quaternion + initial_bowl_quaternion
                            quat_l2_diff = np.linalg.norm(quat_diff)
                            quat_l2_sum = np.linalg.norm(quat_sum)
                            bowl_rotation_error_rad = min(quat_l2_diff, quat_l2_sum)

                            # Validate against existing thresholds
                            max_tracking_tolerance = float(contract["maximum_arm_tracking_error_rad"])
                            if arm_tracking_error_rad > max_tracking_tolerance:
                                raise RuntimeError(
                                    f"{pose.name} probe candidate reset failed arm tracking: "
                                    f"error={arm_tracking_error_rad:.6f} rad, tolerance={max_tracking_tolerance:.6f} rad"
                                )

                            position_tolerance = float(scene_contract["ik_gate"]["position_tolerance_m"])
                            if bowl_position_error_m > position_tolerance:
                                raise RuntimeError(
                                    f"{pose.name} probe candidate reset failed bowl position: "
                                    f"error={bowl_position_error_m:.6f} m, tolerance={position_tolerance:.6f} m"
                                )

                            rotation_tolerance = float(scene_contract["ik_gate"]["rotation_tolerance_rad"])
                            if bowl_rotation_error_rad > rotation_tolerance:
                                raise RuntimeError(
                                    f"{pose.name} probe candidate reset failed bowl rotation: "
                                    f"error={bowl_rotation_error_rad:.6f} rad, tolerance={rotation_tolerance:.6f} rad"
                                )

                            # Reset successful, update attempt record and counter
                            probe_candidate_reset_count += 1
                            grasp_attempt["probe_candidate_reset"] = {
                                "applied": True,
                                "reset_index": probe_candidate_reset_count,
                                "arm_tracking_error_rad": arm_tracking_error_rad,
                                "bowl_position_error_m": bowl_position_error_m,
                                "bowl_rotation_error_rad": bowl_rotation_error_rad,
                            }
                        else:
                            # Online mode: record as not applied
                            grasp_attempt["probe_candidate_reset"] = {
                                "applied": False,
                                "reason": "mode_forbids_mid_episode_reset",
                            }

                        grasp_attempts.append(grasp_attempt)

                        # Next loop iteration (loop_idx>0) will return to candidate_baseline_qpos
                        # with read-back/bowl drift gate

                if successful_candidate_index is None:
                    all_attempts_summary = "; ".join(
                        f"candidate {attempt['candidate_index']}: "
                        f"x_offset={attempt['x_offset_m']:.4f}m, "
                        f"forward={attempt['forward_offset_m']:.4f}m, "
                        f"z={attempt['grasp_z_m']:.4f}m, "
                        f"contact={attempt['contact_verified']}"
                        for attempt in grasp_attempts
                    )
                    raise RuntimeError(
                        f"refusing suction for {pose.name}: no verified "
                        f"{assigned_side}-clamp-to-bowl contact after trying all "
                        f"{len(grasp_attempts)} candidates. Attempts: "
                        f"{all_attempts_summary}"
                    )

                lift_position = grasp_position.copy()
                lift_position[2] += float(contract["lift_distance_m"])

                qpos["lift"], ik_errors["lift"] = solve_stage(
                    f"{pose.name}:lift",
                    {assigned_side: lift_position},
                    current,
                    orientation_override={assigned_side: stage_orientation["lift"]},
                )
                current = qpos["lift"]

                bowl_z_before_lift = float(_vector(selected_bowl.get_pos())[2])

                suction_link_name = contacted_links[0]
                robot_link = robot.get_link(suction_link_name)
                bowl_link = selected_bowl.get_link("bowl_link")
                weld_indices = {
                    "robot": int(robot_link.idx),
                    "bowl": int(bowl_link.idx),
                }
                level1_release_observability = begin_release_observability(
                    level=level,
                    bowl_name=pose.name,
                    selected_bowl=selected_bowl,
                    robot_link=robot_link,
                    bowl_link=bowl_link,
                    assigned_side=assigned_side,
                    suction_link_name=suction_link_name,
                    supporting_bowl=supporting_bowl,
                    supporting_bowl_name=supporting_bowl_name,
                )
                scene.rigid_solver.add_weld_constraint(
                    weld_indices["robot"],
                    weld_indices["bowl"],
                )
                if not weld_registered(weld_indices["robot"], weld_indices["bowl"]):
                    raise RuntimeError(f"Genesis did not register {pose.name} suction weld")
                if level1_release_observability is not None:
                    level1_release_observability["snapshots"].append(
                        release_pose_snapshot(
                            label="after_weld_registration",
                            selected_bowl=selected_bowl,
                            robot_link=robot_link,
                            bowl_link=bowl_link,
                            assigned_side=assigned_side,
                            weld_active=True,
                            supporting_bowl=supporting_bowl,
                            supporting_bowl_name=supporting_bowl_name,
                        )
                    )
                if level == 0:
                    tracker.complete_stage(
                        task["stages"][2],
                        policy_step=policy_step(),
                        details={
                            "bowl": pose.name,
                            "selection_rule": "lowest_source_y_then_source_arm_rule",
                            "assigned_side": assigned_side,
                            "contact_verified": True,
                            "suction_weld_registered": True,
                            "grasp_attempts": grasp_attempts,
                            "successful_candidate_index": successful_candidate_index,
                        },
                    )

                command_segment(
                    f"{pose.name}:lift",
                    qpos["lift"],
                    lift_duration,
                )
                lift_delta = (
                    float(_vector(selected_bowl.get_pos())[2]) - bowl_z_before_lift
                )
                if lift_delta < float(contract["minimum_lift_delta_m"]):
                    raise RuntimeError(
                        f"{pose.name} lift delta {lift_delta:.6f} is below threshold"
                    )

            def solve_assigned_path(
                stage: str,
                start_position: np.ndarray,
                end_position: np.ndarray,
                initial: np.ndarray,
                *,
                solver_initial: np.ndarray | None = None,
            ) -> tuple[list[np.ndarray], np.ndarray]:
                path: list[np.ndarray] = []
                active = initial if solver_initial is None else solver_initial.copy()
                for waypoint in range(1, args.cartesian_waypoints + 1):
                    alpha = waypoint / args.cartesian_waypoints
                    waypoint_position = (
                        start_position
                        + alpha * (end_position - start_position)
                    )
                    waypoint_name = (
                        f"{pose.name}:{stage}_{waypoint:02d}_of_"
                        f"{args.cartesian_waypoints:02d}"
                    )
                    active, ik_errors[waypoint_name] = solve_stage(
                        waypoint_name,
                        {assigned_side: waypoint_position},
                        active,
                        orientation_override={
                            assigned_side: stage_orientation[
                                stage
                                if stage in stage_orientation
                                else "transport"
                            ]
                        },
                    )
                    path.append(active)
                return path, active

            if assigned_side == "right":
                rrt_goal_position = transport_position.copy()
                rrt_goal_position[0] = source_x
                rrt_goal_position[1] = 0.0
                rrt_goal_position[2] = 0.95
                transport_goal, ik_errors["transport_goal"] = solve_stage(
                    f"{pose.name}:transport_goal",
                    {assigned_side: rrt_goal_position},
                    qpos["lift"],
                    orientation_override={
                        assigned_side: stage_orientation["transport"]
                    },
                )
                transport_path = [transport_goal]
                current = transport_goal
                transport_execution_paths = [("rrt_goal", transport_path)]
                post_rrt_transport_path, current = solve_assigned_path(
                    "transport_high_inward",
                    rrt_goal_position,
                    transport_position,
                    current,
                )
                retreat_transport_qpos = post_rrt_transport_path[-1]
            else:
                transport_path, current = solve_assigned_path(
                    "transport",
                    lift_position,
                    transport_position,
                    current,
                )
                transport_execution_paths = [("direct", transport_path)]
                post_rrt_transport_path = []
                retreat_transport_qpos = transport_path[-1]
            place_path, current = solve_assigned_path(
                "place",
                transport_position,
                place_position,
                current,
            )
            if assigned_side == "left":
                qpos["retreat"], ik_errors["retreat"] = solve_stage(
                    f"{pose.name}:retreat",
                    positions["retreat"],
                    current,
                    orientation_override={assigned_side: grasp_orientation},
                )
            else:
                qpos["retreat"] = retreat_transport_qpos.copy()

            for index in side_gripper_indices:
                qpos["lift"][index] = transport_gripper_pose[index]
                for waypoint_qpos in transport_path + place_path:
                    waypoint_qpos[index] = transport_gripper_pose[index]
                qpos["retreat"][index] = open_qpos[index]

            if assigned_side == "left":
                if consecutive_left_transition_active:
                    transition_duration = float(
                        consecutive_left_transition_contract[
                            "segment_minimum_duration_s"
                        ]
                    )
                    command_smooth_path(
                        f"{pose.name}:inter_bowl_vertical_clearance",
                        consecutive_left_transition_paths[
                            "vertical_clearance"
                        ],
                        transition_duration,
                    )
                    if "reorient_at_clearance" in (
                        consecutive_left_transition_paths
                    ):
                        command_segment(
                            f"{pose.name}:inter_bowl_reorient_at_clearance",
                            consecutive_left_transition_paths[
                                "reorient_at_clearance"
                            ][-1],
                            transition_duration,
                        )
                    command_smooth_path(
                        f"{pose.name}:inter_bowl_lateral_clearance",
                        consecutive_left_transition_paths[
                            "lateral_clearance"
                        ],
                        transition_duration,
                    )
                    command_smooth_path(
                        f"{pose.name}:inter_bowl_descend_to_front_clearance",
                        consecutive_left_transition_paths[
                            "descend_to_front_clearance"
                        ],
                        transition_duration,
                    )
                    transition_receipt_path = (
                        run_dir / f"inter_bowl_transition_level_{level}.json"
                    )
                    transition_receipt = {
                        "schema_version": 1,
                        "protocol_version": (
                            consecutive_left_transition_contract[
                                "protocol_version"
                            ]
                        ),
                        "run_id": args.run_id,
                        "seed": seed,
                        "generation_mode": generation_mode,
                        "previous_bowl": bowl_runs[-1]["bowl"],
                        "current_bowl": pose.name,
                        "previous_assigned_side": bowl_runs[-1][
                            "assigned_side"
                        ],
                        "current_assigned_side": assigned_side,
                        "stack_level": level,
                        "clearance_tcp_z_m": (
                            consecutive_left_transition_contract[
                                "clearance_tcp_z_m"
                            ]
                        ),
                        "cartesian_waypoints_per_segment": (
                            consecutive_left_transition_contract[
                                "cartesian_waypoints_per_segment"
                            ]
                        ),
                        "segment_minimum_duration_s": transition_duration,
                        "orientation_schedule_id": (
                            args.consecutive_left_orientation_schedule
                        ),
                        "orientation_schedule_contract_sha256": (
                            sha256_file(
                                args.consecutive_left_dynamic_contract
                            )
                            if consecutive_left_dynamic_contract is not None
                            else None
                        ),
                        "corrected_expert_work_package_id": (
                            G3_CORRECTED_EXPERT_WORK_PACKAGE
                            if corrected_expert_contract is not None
                            else None
                        ),
                        "corrected_expert_phase": corrected_expert_phase,
                        "corrected_expert_contract_sha256": (
                            sha256_file(args.corrected_expert_contract)
                            if corrected_expert_contract is not None
                            and args.corrected_expert_contract is not None
                            else None
                        ),
                        "corrected_expert_authorization_sha256": (
                            sha256_file(args.corrected_expert_authorization)
                            if corrected_expert_authorization is not None
                            and args.corrected_expert_authorization is not None
                            else None
                        ),
                        "level1_release_work_package_id": (
                            level1_release_contract["work_package_id"]
                            if level1_release_contract is not None
                            else None
                        ),
                        "level1_release_phase": level1_release_phase,
                        "level1_release_contract_sha256": (
                            sha256_file(
                                args.level1_release_diagnostic_contract
                            )
                            if level1_release_contract is not None
                            and args.level1_release_diagnostic_contract
                            is not None
                            else None
                        ),
                        "level1_release_authorization_sha256": (
                            sha256_file(
                                args.level1_release_diagnostic_authorization
                            )
                            if level1_release_authorization is not None
                            and args.level1_release_diagnostic_authorization
                            is not None
                            else None
                        ),
                        "executed_transition_stages": list(
                            consecutive_left_transition_paths
                        ),
                        "orientation_waypoints_wxyz": (
                            consecutive_left_transition_orientation_waypoints
                        ),
                        "route_positions_xyz_m": {
                            stage: [
                                list(position) for position in stage_positions
                            ]
                            for stage, stage_positions in (
                                consecutive_left_transition_positions.items()
                            )
                        },
                        "completed_through": (
                            f"{pose.name}:inter_bowl_"
                            "descend_to_front_clearance"
                        ),
                        "policy_step_after_transition": policy_step(),
                        "safety_failure_count_after_transition": len(
                            safety_failures
                        ),
                        "tool_sha256": sha256_file(Path(__file__)),
                        "scene_contract_sha256": sha256_file(
                            args.scene_contract
                        ),
                        "partial_only": True,
                        "episode_success": False,
                        "training_data_claim": False,
                        "learned_policy_claim": False,
                        "rocm_claim": False,
                        "claim_boundary": (
                            "Successful traversal of one scripted "
                            "consecutive-left high-clearance transition only; "
                            "not episode success, training data, learned-policy, "
                            "AMD/ROCm, hardware, or real-robot evidence."
                        ),
                    }
                    try:
                        with transition_receipt_path.open(
                            "x",
                            encoding="utf-8",
                        ) as handle:
                            json.dump(
                                transition_receipt,
                                handle,
                                indent=2,
                                sort_keys=True,
                            )
                            handle.write("\n")
                    except FileExistsError:
                        raise RuntimeError(
                            "refusing to overwrite prior inter-bowl "
                            f"transition diagnostic: {transition_receipt_path}"
                        )
                else:
                    command_segment(
                        f"{pose.name}:front_clearance",
                        qpos["front_clearance"],
                        minimum_duration,
                    )
                command_segment(
                    f"{pose.name}:rim_clearance",
                    qpos["rim_clearance"],
                    minimum_duration,
                )
                if "pregrasp" in qpos:
                    command_segment(
                        f"{pose.name}:pregrasp",
                        qpos["pregrasp"],
                        minimum_duration,
                    )
                command_segment(
                    f"{pose.name}:approach",
                    qpos["approach"],
                    approach_duration,
                )
                bowl_z_before_lift = float(_vector(selected_bowl.get_pos())[2])
                closed_approach = qpos["approach"].copy()
                for index in side_gripper_indices:
                    closed_approach[index] = grasp_close_pose[index]
                command_segment(
                    f"{pose.name}:close",
                    closed_approach,
                    close_duration,
                )
                hold_steps = max(
                    1,
                    int(math.ceil(hold_duration / dt)),
                )
                for _ in range(hold_steps):
                    advance(closed_approach, f"{pose.name}:hold")

                selected_info = robot.get_contacts(with_entity=selected_bowl)
                selected_pairs = _contact_pairs(selected_info, labels)
                for pair in selected_pairs:
                    contact_histogram[pair] = contact_histogram.get(pair, 0) + 1
                contacted_links = sorted(
                    {
                        label.split(":")[1]
                        for pair in selected_pairs
                        for label in pair.split(" <> ")
                        if label.startswith(f"mantis:{assigned_side}_clamp")
                        and f"{pose.name}:" in pair
                    }
                )
                contact_verified = bool(contacted_links)
                if not contact_verified:
                    raise RuntimeError(
                        f"refusing suction for {pose.name}: no verified "
                        f"{assigned_side}-clamp-to-bowl contact"
                    )

                suction_link_name = contacted_links[0]
                robot_link = robot.get_link(suction_link_name)
                bowl_link = selected_bowl.get_link("bowl_link")
                weld_indices = {
                    "robot": int(robot_link.idx),
                    "bowl": int(bowl_link.idx),
                }
                level1_release_observability = begin_release_observability(
                    level=level,
                    bowl_name=pose.name,
                    selected_bowl=selected_bowl,
                    robot_link=robot_link,
                    bowl_link=bowl_link,
                    assigned_side=assigned_side,
                    suction_link_name=suction_link_name,
                    supporting_bowl=supporting_bowl,
                    supporting_bowl_name=supporting_bowl_name,
                )
                scene.rigid_solver.add_weld_constraint(
                    weld_indices["robot"],
                    weld_indices["bowl"],
                )
                if not weld_registered(weld_indices["robot"], weld_indices["bowl"]):
                    raise RuntimeError(f"Genesis did not register {pose.name} suction weld")
                if level1_release_observability is not None:
                    level1_release_observability["snapshots"].append(
                        release_pose_snapshot(
                            label="after_weld_registration",
                            selected_bowl=selected_bowl,
                            robot_link=robot_link,
                            bowl_link=bowl_link,
                            assigned_side=assigned_side,
                            weld_active=True,
                            supporting_bowl=supporting_bowl,
                            supporting_bowl_name=supporting_bowl_name,
                        )
                    )
                if level == 0:
                    tracker.complete_stage(
                        task["stages"][2],
                        policy_step=policy_step(),
                        details={
                            "bowl": pose.name,
                            "selection_rule": "lowest_source_y_then_source_arm_rule",
                            "assigned_side": assigned_side,
                            "contact_verified": True,
                            "suction_weld_registered": True,
                        },
                    )

                command_segment(
                    f"{pose.name}:lift",
                    qpos["lift"],
                    lift_duration,
                )
                lift_delta = (
                    float(_vector(selected_bowl.get_pos())[2]) - bowl_z_before_lift
                )
                if lift_delta < float(contract["minimum_lift_delta_m"]):
                    raise RuntimeError(
                        f"{pose.name} lift delta {lift_delta:.6f} is below threshold"
                    )
            if assigned_side == "right":
                planned = robot.plan_path(
                    transport_path[-1],
                    qpos_start=np.asarray(
                        _read_dofs(robot, all_indices),
                        dtype=float,
                    ),
                    max_nodes=5000,
                    resolution=0.03,
                    timeout=60.0,
                    max_retry=3,
                    smooth_path=True,
                    num_waypoints=120,
                    ignore_collision=False,
                    planner="RRTConnect",
                    ee_link_name=suction_link_name,
                    with_entity=selected_bowl,
                )
                if hasattr(planned, "detach"):
                    planned = planned.detach()
                if hasattr(planned, "cpu"):
                    planned = planned.cpu()
                if hasattr(planned, "numpy"):
                    planned = planned.numpy()
                planned_array = np.asarray(planned, dtype=float)
                if planned_array.ndim == 3 and planned_array.shape[0] == 1:
                    planned_array = planned_array[0]
                if (
                    planned_array.ndim != 2
                    or planned_array.shape[1] != len(all_indices)
                    or planned_array.shape[0] < 2
                ):
                    raise RuntimeError(
                        "Genesis RRTConnect returned an invalid right-arm "
                        f"transport path shape: {planned_array.shape}"
                    )
                # Canonicalize gripper commands across every RRT waypoint: the
                # planner was seeded from the post-contact readback, whose two
                # clamp fingers had drifted asymmetrically, so the returned
                # rows carry an asymmetric gripper spread.  Re-stamp all four
                # gripper DOFs on every row from the symmetric target taken
                # from transport_path[-1] (active side transport pose, inactive
                # side open) -- never the readback -- so the executed action
                # stays symmetric.  Arm DOFs are copied verbatim; the RRT arm
                # path itself is untouched.
                canonicalized_rows = canonicalize_path_gripper_commands(
                    path=planned_array,
                    command_target=transport_path[-1],
                    gripper_indices=all_gripper_indices,
                    expected_width=len(all_indices),
                )
                transport_execution_paths = [
                    (
                        "rrtconnect_attached_bowl",
                        [
                            np.asarray(row, dtype=float)
                            for row in canonicalized_rows
                        ],
                    )
                ]
            for transport_stage, execution_path in transport_execution_paths:
                execution_duration = (
                    4.0
                    if transport_stage == "rrtconnect_attached_bowl"
                    else float(contract["transport_duration_s"])
                    / len(transport_execution_paths)
                )
                command_smooth_path(
                    f"{pose.name}:transport_{transport_stage}",
                    execution_path,
                    execution_duration,
                )
            if post_rrt_transport_path:
                command_smooth_path(
                    f"{pose.name}:transport_high_inward",
                    post_rrt_transport_path,
                    2.0,
                )
            command_smooth_path(
                f"{pose.name}:place",
                place_path,
                float(contract["place_duration_s"]),
            )

            # Right-side XY correction loop: max 2 deterministic feedback corrections
            # In replay mode, disable online correction and measure once against tolerance
            feedback_diagnostics: dict[str, Any] | None = None
            if assigned_side == "right":
                strict_evaluator_tolerance = float(task["success_predicate"]["xy_axis_alignment_tolerance_m"])
                # Conservative control tolerance: min(strict_evaluator_tolerance, 0.01 m)
                # This tightens control and does not relax success criteria
                control_xy_tolerance = min(strict_evaluator_tolerance, 0.01)

                # Replay mode: single measurement after offset-aware transport/place - no correction motion
                if generation_mode == "replay" and replay_plan is not None:
                    # frozen_offset was already applied before transport_position construction (line ~1420)
                    frozen_offset = replay_plan.steps[level].place_xy_offset_m
                    correction_attempts: list[dict[str, Any]] = []
                    corrections_applied = 0

                    measured_position = _vector(selected_bowl.get_pos())
                    measured_xy = (float(measured_position[0]), float(measured_position[1]))
                    target_xy = (target_x, target_y)
                    weld_verified = weld_registered(weld_indices["robot"], weld_indices["bowl"])

                    # Use control tolerance for measurement
                    correction = right_xy_correction(measured_xy, target_xy, control_xy_tolerance)

                    attempt_data = {
                        "iteration": 0,
                        "measured_position_xyz_m": measured_position,
                        "measured_xy_m": measured_xy,
                        "target_xy_m": target_xy,
                        "control_xy_tolerance_m": control_xy_tolerance,
                        "strict_evaluator_xy_tolerance_m": strict_evaluator_tolerance,
                        "correction_dx_dy_m": correction if correction else (0.0, 0.0),
                        "within_tolerance": correction is None,
                        "weld_verified": weld_verified,
                        "correction_applied": False,  # Truthful: replay never applies corrections
                        "frozen_plan_replay": True,
                        "frozen_offset_m": list(frozen_offset),
                    }
                    correction_attempts.append(attempt_data)

                    final_measured_position = measured_position
                    final_measured_xy = measured_xy
                    final_target_xy = target_xy
                    final_correction = correction
                    final_within_tolerance = final_correction is None
                    last_correction_iteration = None

                    if not final_within_tolerance:
                        error_x = final_measured_xy[0] - target_x
                        error_y = final_measured_xy[1] - target_y
                        raise RuntimeError(
                            f"{pose.name} replay placement XY exceeds tolerance: "
                            f"measured_xy={final_measured_xy}, target_xy=({target_x:.6f}, {target_y:.6f}), "
                            f"error=({error_x:.6f}, {error_y:.6f}) m, tolerance={control_xy_tolerance:.6f} m, "
                            f"frozen_offset={frozen_offset}, replay_plan_path={args.replay_plan.name}"
                        )

                    feedback_diagnostics = {
                        "scripted_oracle_demonstration_feedback": True,
                        "frozen_plan_replay": True,
                        "total_corrections_applied": 0,
                        "correction_attempts": correction_attempts,
                        "final_measured_position_xyz_m": final_measured_position,
                        "final_measured_xy_m": final_measured_xy,
                        "target_xy_m": final_target_xy,
                        "final_within_tolerance": final_within_tolerance,
                        "last_correction_iteration": last_correction_iteration,
                    }
                else:
                    # Online/probe mode: normal correction loop with explicit correction accounting
                    correction_attempts: list[dict[str, Any]] = []
                    corrections_applied = 0  # Explicit counter

                    for correction_iteration in range(2):  # Max 2 deterministic corrections
                        measured_position = _vector(selected_bowl.get_pos())
                        measured_xy = (float(measured_position[0]), float(measured_position[1]))
                        target_xy = (target_x, target_y)
                        weld_verified = weld_registered(weld_indices["robot"], weld_indices["bowl"])

                        # Use control tolerance for right_xy_correction
                        correction = right_xy_correction(measured_xy, target_xy, control_xy_tolerance)

                        # Each attempt starts with correction_applied=False
                        attempt_data = {
                            "iteration": correction_iteration,
                            "measured_position_xyz_m": measured_position,
                            "measured_xy_m": measured_xy,
                            "target_xy_m": target_xy,
                            "control_xy_tolerance_m": control_xy_tolerance,
                            "strict_evaluator_xy_tolerance_m": strict_evaluator_tolerance,
                            "correction_dx_dy_m": correction if correction else (0.0, 0.0),
                            "within_tolerance": correction is None,
                            "weld_verified": weld_verified,
                            "correction_applied": False,  # Initially False, becomes True after motion completes
                        }
                        correction_attempts.append(attempt_data)

                        if correction is None:
                            # Within tolerance - no correction needed, exit loop
                            break

                        # Weld precondition hard-fail: record attempt first, but do not move if weld not verified
                        if not weld_verified:
                            raise RuntimeError(
                                f"{pose.name} weld not verified before correction iteration {correction_iteration}: "
                                f"refusing to apply correction motion without active weld"
                            )

                        # Apply correction: lift, translate, descend
                        dx, dy = correction
                        lift_height = 0.06

                        # Current TCP position (at bowl)
                        current_tcp_position = place_position.copy()
                        lift_tcp_position = current_tcp_position.copy()
                        lift_tcp_position[2] += lift_height  # Same XY, +0.06m lift

                        # Build corrected_high_position from lift_tcp_position plus dx/dy
                        corrected_high_position = lift_tcp_position.copy()
                        corrected_high_position[0] += dx
                        corrected_high_position[1] += dy

                        # Build corrected_place_position from original low current_tcp_position plus dx/dy
                        corrected_place_position = current_tcp_position.copy()
                        corrected_place_position[0] += dx
                        corrected_place_position[1] += dy

                        # Solve lift path
                        correction_lift_path, correction_current = solve_assigned_path(
                            f"correction_{correction_iteration}_lift",
                            current_tcp_position,
                            lift_tcp_position,
                            current,
                        )

                        # Solve high translation
                        correction_translate_path, correction_current = solve_assigned_path(
                            f"correction_{correction_iteration}_translate",
                            lift_tcp_position,
                            corrected_high_position,
                            correction_current,
                        )

                        # Solve descent to corrected place
                        correction_descent_path, correction_current = solve_assigned_path(
                            f"correction_{correction_iteration}_descent",
                            corrected_high_position,
                            corrected_place_position,
                            correction_current,
                        )

                        # Set grippers to transport_gripper_pose for all correction waypoints
                        for waypoint_qpos in (correction_lift_path + correction_translate_path + correction_descent_path):
                            for index in side_gripper_indices:
                                waypoint_qpos[index] = transport_gripper_pose[index]

                        # Execute correction paths
                        command_smooth_path(
                            f"{pose.name}:correction_{correction_iteration}_lift",
                            correction_lift_path,
                            1.0,
                        )
                        command_smooth_path(
                            f"{pose.name}:correction_{correction_iteration}_translate",
                            correction_translate_path,
                            1.0,
                        )
                        command_smooth_path(
                            f"{pose.name}:correction_{correction_iteration}_descent",
                            correction_descent_path,
                            1.0,
                        )

                        # Update state for next iteration
                        current = correction_current
                        place_position = corrected_place_position
                        place_path = correction_descent_path
                        corrections_applied += 1
                        # Mark correction as applied in attempt data
                        correction_attempts[correction_iteration]["correction_applied"] = True

                        # Verify weld still active after correction
                        if not weld_registered(weld_indices["robot"], weld_indices["bowl"]):
                            raise RuntimeError(
                                f"{pose.name} weld lost during correction iteration {correction_iteration}"
                            )

                    # After corrections, perform final measurement and build feedback diagnostics centrally
                    final_measured_position = _vector(selected_bowl.get_pos())
                    final_measured_xy = (float(final_measured_position[0]), float(final_measured_position[1]))
                    final_target_xy = (target_x, target_y)
                    final_correction = right_xy_correction(final_measured_xy, final_target_xy, control_xy_tolerance)
                    final_within_tolerance = final_correction is None
                    last_correction_iteration = corrections_applied - 1 if corrections_applied > 0 else None

                    if not final_within_tolerance:
                        # Still outside tolerance after 2 corrections
                        weld_verified = weld_registered(weld_indices["robot"], weld_indices["bowl"])
                        error_x = final_measured_xy[0] - target_x
                        error_y = final_measured_xy[1] - target_y
                        raise RuntimeError(
                            f"{pose.name} placement XY exceeds tolerance after {corrections_applied} corrections: "
                            f"measured_xy={final_measured_xy}, target_xy=({target_x:.6f}, {target_y:.6f}), "
                            f"error=({error_x:.6f}, {error_y:.6f}) m, tolerance={control_xy_tolerance:.6f} m, "
                            f"weld_verified={weld_verified}, corrections_applied={corrections_applied}"
                        )

                    # Build feedback diagnostics centrally after final measurement
                    feedback_diagnostics = {
                        "scripted_oracle_demonstration_feedback": True,
                        "correction_attempts": correction_attempts,
                        "final_measured_position_xyz_m": final_measured_position,
                        "final_measured_xy_m": final_measured_xy,
                        "target_xy_m": final_target_xy,
                        "final_within_tolerance": final_within_tolerance,
                        "total_corrections_applied": corrections_applied,
                        "last_correction_iteration": last_correction_iteration,
                    }

            # Record final pre-release position and verify weld is still registered
            final_pre_release_position = _vector(selected_bowl.get_pos())
            if not weld_registered(weld_indices["robot"], weld_indices["bowl"]):
                raise RuntimeError(f"{pose.name} suction weld not registered before release")
            if level1_release_observability is not None:
                level1_release_observability["snapshots"].append(
                    release_pose_snapshot(
                        label="final_pre_release",
                        selected_bowl=selected_bowl,
                        robot_link=robot_link,
                        bowl_link=bowl_link,
                        assigned_side=assigned_side,
                        weld_active=True,
                        supporting_bowl=supporting_bowl,
                        supporting_bowl_name=supporting_bowl_name,
                    )
                )
            if (
                release_retreat_boundary_contract is not None
                and pose.name == "bowl3"
            ):
                record_release_retreat_boundary_snapshot(
                    "final_pre_release",
                    weld_active=True,
                )

            scene.rigid_solver.delete_weld_constraint(
                weld_indices["robot"],
                weld_indices["bowl"],
            )
            if weld_registered(weld_indices["robot"], weld_indices["bowl"]):
                raise RuntimeError(f"{pose.name} suction weld remained after deletion")

            release_target = place_path[-1].copy()
            for index in side_gripper_indices:
                release_target[index] = open_qpos[index]
            command_segment(
                f"{pose.name}:release",
                release_target,
                float(contract["release_duration_s"]),
            )

            # Record immediate post-release position
            immediate_post_release_position = _vector(selected_bowl.get_pos())

            # Verify weld remains absent after release
            if weld_registered(weld_indices["robot"], weld_indices["bowl"]):
                raise RuntimeError(
                    f"{pose.name} suction weld reappeared after release"
                )
            if level1_release_observability is not None:
                level1_release_observability["snapshots"].append(
                    release_pose_snapshot(
                        label="immediate_post_release",
                        selected_bowl=selected_bowl,
                        robot_link=robot_link,
                        bowl_link=bowl_link,
                        assigned_side=assigned_side,
                        weld_active=False,
                        supporting_bowl=supporting_bowl,
                        supporting_bowl_name=supporting_bowl_name,
                    )
                )
            if (
                release_retreat_boundary_contract is not None
                and pose.name == "bowl3"
            ):
                record_release_retreat_boundary_snapshot(
                    "immediate_post_release",
                    weld_active=False,
                )
                record_release_retreat_boundary_snapshot(
                    "pre_retreat",
                    weld_active=False,
                )

            if assigned_side == "right":
                # Split retreat: execute reversed final descent with grippers open first
                reverse_place_path = [
                    np.asarray(row, dtype=float).copy()
                    for row in reversed(place_path)
                ]

                # Set grippers to open for all retreat waypoints
                for waypoint_qpos in reverse_place_path:
                    for index in side_gripper_indices:
                        waypoint_qpos[index] = open_qpos[index]

                # Execute reversed final descent (vertical withdrawal)
                command_smooth_path(
                    f"{pose.name}:retreat_vertical_withdrawal",
                    reverse_place_path,
                    float(contract["retreat_duration_s"]) / 2,  # Split time between vertical and high clearance
                )

                # Record post_vertical_withdrawal bowl position
                post_vertical_withdrawal_position = _vector(selected_bowl.get_pos())

                # Move at high clearance to retreat_transport_qpos using joint-space path
                high_clearance_joint_path = [
                    reverse_place_path[-1].copy(),
                    retreat_transport_qpos.copy(),
                ]

                # Set grippers to open for high clearance waypoints
                for waypoint_qpos in high_clearance_joint_path:
                    for index in side_gripper_indices:
                        waypoint_qpos[index] = open_qpos[index]

                # Execute high clearance retreat in joint space
                command_smooth_path(
                    f"{pose.name}:retreat_high_clearance",
                    high_clearance_joint_path,
                    float(contract["retreat_duration_s"]) / 2,
                )

                # Record post_high_clearance_retreat position
                post_high_clearance_retreat_position = _vector(selected_bowl.get_pos())

                qpos["retreat"] = retreat_transport_qpos.copy()
            else:
                # Left-side retreat: unchanged behavior
                command_segment(
                    f"{pose.name}:retreat",
                    qpos["retreat"],
                    float(contract["retreat_duration_s"]),
                )
                # Set placeholder positions for left-side compatibility
                post_vertical_withdrawal_position = None
                post_high_clearance_retreat_position = None
            active_bowl_name = None
            active_side_name = None
            wait_policy_frames(
                int(contract["stability_policy_frames"]),
                qpos["retreat"],
                f"{pose.name}:settle",
            )
            placed_position = _vector(selected_bowl.get_pos())
            if level1_release_observability is not None:
                level1_release_observability["snapshots"].append(
                    release_pose_snapshot(
                        label="placed_after_stability",
                        selected_bowl=selected_bowl,
                        robot_link=robot_link,
                        bowl_link=bowl_link,
                        assigned_side=assigned_side,
                        weld_active=False,
                        supporting_bowl=supporting_bowl,
                        supporting_bowl_name=supporting_bowl_name,
                    )
                )
                snapshot_by_label = {
                    snapshot["label"]: snapshot
                    for snapshot in level1_release_observability["snapshots"]
                }
                after_weld = snapshot_by_label["after_weld_registration"]
                pre_release = snapshot_by_label["final_pre_release"]
                post_release = snapshot_by_label["immediate_post_release"]
                placed_snapshot = snapshot_by_label["placed_after_stability"]
                level1_release_observability["derived_metrics"] = {
                    "attachment_transform_drift_add_to_pre_release": (
                        pose_delta_wxyz(
                            (
                                after_weld["bowl_in_suction_frame"][
                                    "translation_xyz_m"
                                ]
                            ),
                            (
                                after_weld["bowl_in_suction_frame"][
                                    "quaternion_wxyz"
                                ]
                            ),
                            (
                                pre_release["bowl_in_suction_frame"][
                                    "translation_xyz_m"
                                ]
                            ),
                            (
                                pre_release["bowl_in_suction_frame"][
                                    "quaternion_wxyz"
                                ]
                            ),
                        )
                    ),
                    "bowl_motion_pre_release_to_immediate_post_release": (
                        pose_delta_wxyz(
                            pre_release["bowl_position_xyz_m"],
                            pre_release["bowl_quaternion_wxyz"],
                            post_release["bowl_position_xyz_m"],
                            post_release["bowl_quaternion_wxyz"],
                        )
                    ),
                    "bowl_motion_immediate_post_release_to_placed": (
                        pose_delta_wxyz(
                            post_release["bowl_position_xyz_m"],
                            post_release["bowl_quaternion_wxyz"],
                            placed_snapshot["bowl_position_xyz_m"],
                            placed_snapshot["bowl_quaternion_wxyz"],
                        )
                    ),
                    "release_drop_mm": (
                        pre_release["bowl_position_xyz_m"][2]
                        - post_release["bowl_position_xyz_m"][2]
                    )
                    * 1000.0,
                    "post_release_to_placed_drop_mm": (
                        post_release["bowl_position_xyz_m"][2]
                        - placed_snapshot["bowl_position_xyz_m"][2]
                    )
                    * 1000.0,
                }
                level1_release_observability[
                    "observer_advanced_clock"
                ] = any(
                    snapshot["observer_policy_step_delta"] != 0
                    or snapshot["observer_physics_step_delta"] != 0
                    for snapshot in level1_release_observability["snapshots"]
                )
            expected_height = float(
                task["success_predicate"]["target_heights_m"][level]
            )

            # Compute placement gate results and per-axis errors BEFORE raising
            strict_evaluator_tolerance = float(task["success_predicate"]["xy_axis_alignment_tolerance_m"])
            height_tolerance = float(task["success_predicate"]["height_absolute_tolerance_m"])

            x_error = abs(placed_position[0] - target_x)
            y_error = abs(placed_position[1] - target_y)
            z_error = abs(placed_position[2] - expected_height)

            placement_gate_passed = (
                x_error < strict_evaluator_tolerance
                and y_error < strict_evaluator_tolerance
                and z_error < height_tolerance
            )

            bowl_run_data = {
                "bowl": pose.name,
                "assigned_side": assigned_side,
                "source_assigned_side": source_assigned_side,
                "grasp_mode": grasp_mode,
                "source_position_xyz_m": list(pose.position_xyz_m),
                "stack_level": level,
                "grasp_tcp_position_xyz_m": grasp_position.tolist(),
                "place_tcp_position_xyz_m": place_position.tolist(),
                "transport_tcp_position_xyz_m": transport_position.tolist(),
                "lift_delta_m": lift_delta,
                "placed_position_xyz_m": placed_position,
                "contact_verified": contact_verified,
                "contacted_clamp_links": contacted_links,
                "suction_link": suction_link_name,
                "weld_registered_after_add": True,
                "weld_removed_before_release": True,
                "ik_errors": ik_errors,
                "final_pre_release_position_xyz_m": final_pre_release_position,
                "immediate_post_release_position_xyz_m": immediate_post_release_position,
                # Placement gate diagnostics
                "placement_gate_passed": placement_gate_passed,
                "expected_position_xyz_m": [target_x, target_y, expected_height],
                "xy_axis_alignment_tolerance_m": strict_evaluator_tolerance,
                "height_absolute_tolerance_m": height_tolerance,
                "placement_errors_xyz_m": [x_error, y_error, z_error],
            }
            if level1_release_observability is not None:
                assert args.level1_release_diagnostic_contract is not None
                assert args.level1_release_diagnostic_authorization is not None
                bowl_run_data["level1_release_observability"] = (
                    level1_release_observability
                )
                bowl_run_data["level1_release_contract_sha256"] = sha256_file(
                    args.level1_release_diagnostic_contract
                )
                bowl_run_data[
                    "level1_release_authorization_sha256"
                ] = sha256_file(
                    args.level1_release_diagnostic_authorization
                )
            if assigned_side == "right":
                bowl_run_data["grasp_attempts"] = grasp_attempts
                bowl_run_data["successful_candidate_index"] = (
                    successful_candidate_index
                )
                bowl_run_data["post_vertical_withdrawal_position_xyz_m"] = (
                    post_vertical_withdrawal_position
                )
                bowl_run_data["post_high_clearance_retreat_position_xyz_m"] = (
                    post_high_clearance_retreat_position
                )
                bowl_run_data["probe_candidate_reset_count"] = probe_candidate_reset_count
                if feedback_diagnostics is not None:
                    bowl_run_data["feedback_diagnostics"] = feedback_diagnostics


            # Write bowl progress file atomically BEFORE raising on gate failure
            bowl_progress_file = run_dir / f"bowl_progress_level_{level}.json"
            # Use "attempt" wording for claim boundary since gate hasn't passed yet
            claim_boundary_text = (
                f"Partial scripted placement attempt only: {pose.name} placement attempt at level {level} "
                f"using contact-triggered idealized suction transport in one Genesis scene. "
                f"This is a single-bowl milestone file recording a placement attempt. "
                f"This is not an episode completion receipt and makes no G1, learned-policy, multi-seed, or ROCm claim."
            )
            bowl_progress_data = {
                "schema_version": 1,
                "seed": seed,
                "generation_mode": generation_mode,
                "effective_policy_step_limit": effective_max_policy_steps,
                "bowl_data": bowl_run_data,
                "partial_only": True,
                "episode_success": False,
                "placement_attempt": True,
                "g1_claim": False,
                "learned_policy_claim": False,
                "rocm_claim": False,
                "multi_seed_evidence": False,
                "claim_boundary": claim_boundary_text,
            }
            if level1_release_observability is not None:
                assert args.level1_release_diagnostic_contract is not None
                assert args.level1_release_diagnostic_authorization is not None
                bowl_progress_data["level1_release_work_package_id"] = (
                    level1_release_contract["work_package_id"]
                )
                bowl_progress_data["level1_release_phase"] = (
                    level1_release_phase
                )
                bowl_progress_data["level1_release_contract_sha256"] = (
                    sha256_file(args.level1_release_diagnostic_contract)
                )
                bowl_progress_data[
                    "level1_release_authorization_sha256"
                ] = sha256_file(
                    args.level1_release_diagnostic_authorization
                )
            # Atomic exclusive create: fail if file already exists
            try:
                with bowl_progress_file.open("x", encoding="utf-8") as handle:
                    json.dump(bowl_progress_data, handle, indent=2, sort_keys=True)
                    handle.write("\n")
            except FileExistsError:
                raise RuntimeError(
                    f"Bowl progress file {bowl_progress_file} already exists - "
                    f"refusing to overwrite prior bowl diagnostics"
                )

            # Raise on placement gate failure AFTER progress file is written
            if not placement_gate_passed:
                raise RuntimeError(
                    f"{pose.name} placement misses level {level}: "
                    f"position={placed_position}, expected_position=({target_x:.6f}, {target_y:.6f}, {expected_height:.6f}), "
                    f"errors=({x_error:.6f}, {y_error:.6f}, {z_error:.6f}), "
                    f"xy_tolerance={strict_evaluator_tolerance:.6f}, height_tolerance={height_tolerance:.6f}"
                )

            # Only proceed with stage completion and bowl_runs if gate passed
            stage_index = (3, 4, 5)[level]
            tracker.complete_stage(
                task["stages"][stage_index],
                policy_step=policy_step(),
                details={
                    "bowl": pose.name,
                    "level": level,
                    "assigned_side": assigned_side,
                    "source_assigned_side": source_assigned_side,
                    "grasp_mode": grasp_mode,
                    "position_xyz_m": placed_position,
                    "lift_delta_m": lift_delta,
                    "contact_verified": contact_verified,
                    "weld_removed_before_release": True,
                },
            )

            bowl_runs.append(bowl_run_data)
            current = qpos["retreat"]

        left_open = measured_gripper_fraction("left")
        right_open = measured_gripper_fraction("right")
        tracker.complete_stage(
            task["stages"][6],
            policy_step=policy_step(),
            details={
                "left_gripper_open_fraction": left_open,
                "right_gripper_open_fraction": right_open,
            },
        )

        strict_tracker = StackStabilityTracker(
            required_frames=int(task["success_stable_frames"])
        )
        strict_rows: list[dict[str, Any]] = []
        previous_positions = [
            np.asarray(_vector(bowl.get_pos()), dtype=float)
            for bowl in bowls_by_name.values()
        ]
        previous_quaternions = [
            np.asarray(_vector(bowl.get_quat()), dtype=float)
            for bowl in bowls_by_name.values()
        ]
        previous_step = sim_step
        terminal_success = False
        final_target = current
        for frame in range(int(task["success_stable_frames"])):
            target_policy_frame = policy_step() + 1
            while policy_step() < target_policy_frame:
                advance(final_target, "verify_stack_stability")
            elapsed_s = (sim_step - previous_step) * dt
            positions = [
                np.asarray(_vector(bowl.get_pos()), dtype=float)
                for bowl in bowls_by_name.values()
            ]
            quaternions = [
                np.asarray(_vector(bowl.get_quat()), dtype=float)
                for bowl in bowls_by_name.values()
            ]
            linear_velocities = [
                ((position - previous) / elapsed_s).tolist()
                for position, previous in zip(positions, previous_positions)
            ]
            angular_velocities = [
                _angular_velocity(previous, quaternion, elapsed_s)
                for previous, quaternion in zip(
                    previous_quaternions,
                    quaternions,
                )
            ]
            left_open = measured_gripper_fraction("left")
            right_open = measured_gripper_fraction("right")
            strict = evaluate_strict_target_frame(
                [position.tolist() for position in positions],
                linear_velocities,
                angular_velocities,
                left_gripper_open_fraction=left_open,
                right_gripper_open_fraction=right_open,
                xy_axis_tolerance_m=float(
                    task["success_predicate"][
                        "xy_axis_alignment_tolerance_m"
                    ]
                ),
                height_absolute_tolerance_m=float(
                    task["success_predicate"][
                        "height_absolute_tolerance_m"
                    ]
                ),
                maximum_linear_speed_m_s=float(
                    task["success_predicate"][
                        "maximum_linear_speed_m_s"
                    ]
                ),
                maximum_angular_speed_rad_s=float(
                    task["success_predicate"][
                        "maximum_angular_speed_rad_s"
                    ]
                ),
                minimum_gripper_open_fraction=float(
                    task["success_predicate"][
                        "minimum_gripper_open_fraction"
                    ]
                ),
                no_safety_failure=not safety_failures,
                no_physics_divergence=True,
            )
            terminal_success = strict_tracker.update(
                bool(strict["frame_success"])
            )
            strict_rows.append(
                {
                    "frame": frame + 1,
                    "policy_step": policy_step(),
                    "positions_xyz_m": [
                        position.tolist() for position in positions
                    ],
                    "linear_velocities_m_s": linear_velocities,
                    "angular_velocities_rad_s": angular_velocities,
                    "left_gripper_open_fraction": left_open,
                    "right_gripper_open_fraction": right_open,
                    "strict": strict,
                    "consecutive_success_frames": (
                        strict_tracker.consecutive_frames
                    ),
                }
            )
            previous_positions = positions
            previous_quaternions = quaternions
            previous_step = sim_step

        if not terminal_success:
            raise RuntimeError(
                "strict terminal stability did not reach the required "
                f"{task['success_stable_frames']} consecutive frames"
            )
        tracker.complete_stage(
            task["stages"][7],
            policy_step=policy_step(),
            details={
                "strict_frame_success": True,
                "stable_frames": strict_tracker.consecutive_frames,
                "no_safety_failure": True,
                "no_physics_divergence": True,
            },
        )
        stage_trace = tracker.receipt(
            g1_claim=(generation_mode == "online" and is_canonical_g1),
            generation_mode=generation_mode,
            effective_policy_step_limit=effective_max_policy_steps,
        )

        capture_npz: str | None = None
        stage_trace_name = "stage_trace.json"
        if args.capture:
            capture_npz = capture_npz_name(seed)
            np.savez_compressed(
                run_dir / capture_npz,
                timestamps_s=np.asarray(captured["timestamps_s"], dtype=np.float64),
                physical_state=np.asarray(
                    captured["physical_state"],
                    dtype=np.float32,
                ),
                physical_action=np.asarray(
                    captured["physical_action"],
                    dtype=np.float32,
                ),
                env_cam=np.asarray(captured["env_cam"], dtype=np.uint8),
                left_wrist_cam=np.asarray(
                    captured["left_wrist_cam"],
                    dtype=np.uint8,
                ),
                right_wrist_cam=np.asarray(
                    captured["right_wrist_cam"],
                    dtype=np.uint8,
                ),
            )
            capture_manifest = {
                "schema_version": 1,
                "repo_id": "local/mantis_stack_bowls_scripted_g1_v1",
                "episodes": [
                    {
                        "seed": seed,
                        "npz": capture_npz,
                        "stage_trace": stage_trace_name,
                    }
                ],
            }
            (run_dir / "capture_manifest.json").write_text(
                json.dumps(capture_manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        (run_dir / stage_trace_name).write_text(
            json.dumps(stage_trace, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        # Probe mode: construct and write replay plan atomically after stability pass
        probe_plan_path: Path | None = None
        if generation_mode == "probe":
            # Construct plan steps from bowl_runs
            plan_steps = []
            for level, bowl_run in enumerate(bowl_runs):
                # Extract candidate data for right side
                if bowl_run["assigned_side"] == "right":
                    candidate_index = bowl_run["successful_candidate_index"]
                    # Find exactly one attempt whose candidate_index equals successful_candidate_index
                    grasp_attempts = bowl_run.get("grasp_attempts", [])
                    matching_attempts = [
                        attempt for attempt in grasp_attempts
                        if attempt.get("candidate_index") == candidate_index
                    ]
                    if len(matching_attempts) != 1:
                        raise ValueError(
                            f"Expected exactly one attempt with candidate_index={candidate_index} "
                            f"for level {level}, found {len(matching_attempts)}"
                        )
                    attempt = matching_attempts[0]
                    candidate_tuple = (
                        attempt["x_offset_m"],
                        attempt["forward_offset_m"],
                        attempt["grasp_z_m"],
                    )

                    # Extract XY offset from feedback_diagnostics - sum only applied corrections
                    feedback = bowl_run.get("feedback_diagnostics", {})
                    if feedback:
                        total_applied = feedback.get("total_corrections_applied", 0)
                        correction_attempts = feedback.get("correction_attempts", [])
                        # Only sum attempts where correction_applied is True
                        applied_attempts = [attempt for attempt in correction_attempts if attempt.get("correction_applied", False)]
                        # Assert count matches total_corrections_applied
                        if len(applied_attempts) != total_applied:
                            raise ValueError(
                                f"Probe plan construction: {len(applied_attempts)} attempts with correction_applied=True "
                                f"but total_corrections_applied={total_applied}"
                            )
                        offset_x = sum(attempt.get("correction_dx_dy_m", (0, 0))[0] for attempt in applied_attempts)
                        offset_y = sum(attempt.get("correction_dx_dy_m", (0, 0))[1] for attempt in applied_attempts)
                        place_offset = (offset_x, offset_y)
                    else:
                        # No corrections means zero offset
                        place_offset = (0.0, 0.0)

                    dual_clamp = True
                else:
                    # Left side
                    candidate_tuple = None
                    candidate_index = None
                    place_offset = (0.0, 0.0)  # Left offset must be exactly zero
                    dual_clamp = False

                # Get probe placement position from bowl_run - actual measured position where bowl ended up
                probe_placement = tuple(bowl_run["placed_position_xyz_m"])

                step = ReplayPlanStep(
                    level=level,
                    bowl=bowl_run["bowl"],
                    assigned_side=bowl_run["assigned_side"],
                    source_position_xyz_m=tuple(bowl_run["source_position_xyz_m"]),
                    right_grasp_candidate_index=candidate_index,
                    right_grasp_candidate_tuple=candidate_tuple,
                    place_xy_offset_m=place_offset,
                    dual_clamp_required=dual_clamp,
                    probe_placement_position_xyz_m=probe_placement,
                    probe_placement_gate_pass=bowl_run.get("placement_gate_passed", True),
                )
                plan_steps.append(step)

            # Construct full plan
            probe_plan = ReplayPlan(
                schema_version=1,
                seed=seed,
                task_id=task["task_id"],
                probe_source_run_id=args.run_id,
                candidate_isolation_version=CANDIDATE_ISOLATION_VERSION,
                hashes={
                    "task": sha256_file(args.task),
                    "scene": sha256_file(args.scene_contract),
                    "camera": sha256_file(args.camera_contract),
                    "port": sha256_file(args.port),
                    "mantis_urdf": sha256_file(args.mantis_urdf),
                    "bowl_urdf": sha256_file(bowl_urdf),
                },
                reset_bowl_poses=[
                    {
                        "name": pose.name,
                        "position_xyz_m": list(pose.position_xyz_m),
                        "quaternion_wxyz": list(pose.quaternion_wxyz),
                    }
                    for pose in ordered_reset
                ],
                steps=tuple(plan_steps),
                diagnostic_only_claim_boundary=(
                    f"Probe plan generated from diagnostic calibration run {args.run_id}. "
                    f"This is a replay plan for two-stage generation, not an episode success. "
                    f"No G1, learned-policy, multi-seed, ROCm, or episode success claim."
                ),
            )

            # Write plan atomically
            probe_plan_path = run_dir / "replay_plan.json"
            probe_plan.write_atomic(probe_plan_path)

        receipt = {
            "schema_version": 1,
            "generation_mode": generation_mode,
            "task_policy_step_limit": task_max_policy_steps,
            "effective_policy_step_limit": effective_max_policy_steps,
            "task_id": task["task_id"],
            "protocol_version": task["protocol_version"],
            "transport_protocol": "contact_triggered_suction_scripted_g1_v1",
            "seed": seed,
            "backend_requested": args.backend,
            "backend_active": str(gs.backend),
            "device": str(gs.device),
            "genesis_version": importlib.metadata.version("genesis-world"),
            "source_order_lowest_y_first": [
                pose.name for pose in ordered_reset
            ],
            "bowl_runs": bowl_runs,
            "strict_stability_rows": strict_rows,
            "safety_failures": safety_failures,
            "contact_histogram": dict(sorted(contact_histogram.items())),
            "allowed_proximal_collision_filter": {
                "links": list(proximal_filter_links),
                "geom_ids": proximal_filter_geom_ids,
                "filtered_pair_entries": filtered_pair_entries,
                "rationale": (
                    "Explicit allowed-collision-matrix entry for a proximal "
                    "Mantis mesh pair measured at 0.146 mm penetration in v81; "
                    "all other self, inter-arm, object, and table pairs remain active."
                ),
            },
            "policy_frames": len(captured["timestamps_s"]),
            "maximum_sampling_skew_s": maximum_sampling_skew_s,
            "capture_written": bool(args.capture),
            "capture_npz": capture_npz,
            "stage_trace": stage_trace_name,
            # Mode-aware claims - explicit booleans for all modes
            "scripted_g1_pass": generation_mode == "online" and is_canonical_g1,
            "probe_plan_pass": generation_mode == "probe" and probe_plan_path is not None,
            "g1_claim": generation_mode == "online" and is_canonical_g1,
            "learned_policy_claim": False,
            "rocm_claim": False,
            "multi_seed_evidence": False,
            "episode_success_claim": generation_mode == "online",
            "claim_boundary": _build_claim_boundary(generation_mode, seed, is_canonical_g1, args.run_id),
        }
        if corrected_expert_contract is not None:
            assert args.corrected_expert_contract is not None
            assert args.corrected_expert_authorization is not None
            receipt["corrected_expert_work_package_id"] = (
                G3_CORRECTED_EXPERT_WORK_PACKAGE
            )
            receipt["corrected_expert_phase"] = corrected_expert_phase
            receipt["corrected_expert_contract_sha256"] = sha256_file(
                args.corrected_expert_contract
            )
            receipt["corrected_expert_authorization_sha256"] = sha256_file(
                args.corrected_expert_authorization
            )
        if level1_release_contract is not None:
            assert args.level1_release_diagnostic_contract is not None
            assert args.level1_release_diagnostic_authorization is not None
            receipt["level1_release_work_package_id"] = (
                level1_release_contract["work_package_id"]
            )
            receipt["level1_release_phase"] = level1_release_phase
            receipt["level1_release_contract_sha256"] = sha256_file(
                args.level1_release_diagnostic_contract
            )
            receipt["level1_release_authorization_sha256"] = sha256_file(
                args.level1_release_diagnostic_authorization
            )
            receipt["level1_release_observability_schema"] = (
                level1_release_contract["single_primary_variable"]["candidate"]
            )
            receipt["claim_boundary"] = (
                "Instrumentation-only CPU release observability for one "
                f"predeclared {level1_release_contract['work_package_id']} "
                "seed. Any replay plan is an "
                "incidental probe artifact and is not authorized for capture, "
                "source collection, dataset admission, learned-policy, "
                "AMD/ROCm, hardware, or real-robot claims."
            )
        if failure_telemetry_contract is not None:
            assert args.failure_telemetry_contract is not None
            assert args.failure_telemetry_authorization is not None
            receipt["failure_telemetry_work_package_id"] = (
                RETREAT_FAILURE_TELEMETRY_WORK_PACKAGE
            )
            receipt["failure_telemetry_phase"] = (
                failure_telemetry_phase
            )
            receipt["failure_telemetry_contract_sha256"] = sha256_file(
                args.failure_telemetry_contract
            )
            receipt["failure_telemetry_authorization_sha256"] = (
                sha256_file(args.failure_telemetry_authorization)
            )
            receipt["failure_telemetry_written"] = False
            receipt["stop_on_safety_failure"] = True
            receipt["claim_boundary"] = (
                "One frozen seed-1630 CPU failure-telemetry observation. "
                "A completed run means the predecessor safety event did not "
                "reproduce in the single authorized attempt; no retry, repair, "
                "collection, export, training, AMD/ROCm, hardware, or "
                "publication action is authorized."
            )
        if release_retreat_boundary_contract is not None:
            assert args.release_retreat_boundary_contract is not None
            assert args.release_retreat_boundary_authorization is not None
            receipt["release_retreat_boundary_work_package_id"] = (
                RELEASE_RETREAT_BOUNDARY_WORK_PACKAGE
            )
            receipt["release_retreat_boundary_phase"] = (
                release_retreat_boundary_phase
            )
            receipt["release_retreat_boundary_contract_sha256"] = (
                sha256_file(args.release_retreat_boundary_contract)
            )
            receipt[
                "release_retreat_boundary_authorization_sha256"
            ] = sha256_file(args.release_retreat_boundary_authorization)
            receipt["release_retreat_boundary_trace_written"] = (
                release_retreat_boundary_sha256 is not None
            )
            if release_retreat_boundary_sha256 is not None:
                receipt["release_retreat_boundary_trace_path"] = (
                    "release_retreat_boundary_trace.json"
                )
                receipt["release_retreat_boundary_trace_sha256"] = (
                    release_retreat_boundary_sha256
                )
            receipt["claim_boundary"] = (
                "One frozen seed-1630 CPU cached boundary observation. "
                "No retry, repair, controller or safety-rule change, "
                "collection, export, training, AMD/ROCm, hardware, or "
                "publication action is authorized."
            )

        # Add mode-specific evidence fields
        if generation_mode == "replay" and args.replay_plan:
            receipt["replay_plan_basename"] = args.replay_plan.name
            receipt["replay_plan_sha256"] = sha256_file(args.replay_plan)
            receipt["frozen_plan_validation_pass"] = True
        elif generation_mode == "probe" and probe_plan_path:
            receipt["probe_plan_basename"] = probe_plan_path.name
            receipt["probe_plan_sha256"] = sha256_file(probe_plan_path)
        elif generation_mode == "online":
            # Online mode: no replay/probe plan fields
            pass
        receipt_path = run_dir / "receipt.json"
        receipt_path.write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        receipt_written = True
        # Build finish_run details with actual outcomes
        finish_details: dict[str, Any] = {
            "receipt_sha256": sha256_file(receipt_path),
            "episode_success_claim": generation_mode == "online",
            "scripted_g1_pass": generation_mode == "online" and is_canonical_g1,
            "capture_written": bool(args.capture),
        }

        # Add mode-specific fields to finish_run
        if generation_mode == "replay" and args.replay_plan:
            finish_details["frozen_plan_validation_pass"] = True
        elif generation_mode == "probe":
            finish_details["probe_plan_pass"] = probe_plan_path is not None
        if corrected_expert_contract is not None:
            finish_details["corrected_expert_work_package_id"] = (
                G3_CORRECTED_EXPERT_WORK_PACKAGE
            )
            finish_details["corrected_expert_phase"] = corrected_expert_phase
        if level1_release_contract is not None:
            assert args.level1_release_diagnostic_contract is not None
            assert args.level1_release_diagnostic_authorization is not None
            finish_details["level1_release_work_package_id"] = (
                level1_release_contract["work_package_id"]
            )
            finish_details["level1_release_phase"] = level1_release_phase
            finish_details["level1_release_contract_sha256"] = sha256_file(
                args.level1_release_diagnostic_contract
            )
            finish_details["level1_release_authorization_sha256"] = (
                sha256_file(args.level1_release_diagnostic_authorization)
            )
        if failure_telemetry_contract is not None:
            assert args.failure_telemetry_contract is not None
            assert args.failure_telemetry_authorization is not None
            finish_details["failure_telemetry_work_package_id"] = (
                RETREAT_FAILURE_TELEMETRY_WORK_PACKAGE
            )
            finish_details["failure_telemetry_phase"] = (
                failure_telemetry_phase
            )
            finish_details["failure_telemetry_contract_sha256"] = (
                sha256_file(args.failure_telemetry_contract)
            )
            finish_details["failure_telemetry_authorization_sha256"] = (
                sha256_file(args.failure_telemetry_authorization)
            )
            finish_details["failure_telemetry_written"] = False
            finish_details["stop_on_safety_failure"] = True
        if release_retreat_boundary_contract is not None:
            assert args.release_retreat_boundary_contract is not None
            assert args.release_retreat_boundary_authorization is not None
            finish_details["release_retreat_boundary_work_package_id"] = (
                RELEASE_RETREAT_BOUNDARY_WORK_PACKAGE
            )
            finish_details["release_retreat_boundary_phase"] = (
                release_retreat_boundary_phase
            )
            finish_details["release_retreat_boundary_contract_sha256"] = (
                sha256_file(args.release_retreat_boundary_contract)
            )
            finish_details[
                "release_retreat_boundary_authorization_sha256"
            ] = sha256_file(args.release_retreat_boundary_authorization)
            finish_details["release_retreat_boundary_trace_written"] = (
                release_retreat_boundary_sha256 is not None
            )
            if release_retreat_boundary_sha256 is not None:
                finish_details["release_retreat_boundary_trace_path"] = (
                    "release_retreat_boundary_trace.json"
                )
                finish_details["release_retreat_boundary_trace_sha256"] = (
                    release_retreat_boundary_sha256
                )

        finish_run(
            args.ops_root,
            args.run_id,
            "completed",
            finish_details,
        )
        print(json.dumps(receipt, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        if begun and not receipt_written:
            failure_details: dict[str, Any] = {
                "error_type": type(exc).__name__,
                "message": str(exc),
            }
            if level1_release_contract is not None:
                assert args.level1_release_diagnostic_contract is not None
                assert args.level1_release_diagnostic_authorization is not None
                failure_details["level1_release_work_package_id"] = (
                    level1_release_contract["work_package_id"]
                )
                failure_details["level1_release_phase"] = level1_release_phase
                failure_details["level1_release_contract_sha256"] = (
                    sha256_file(args.level1_release_diagnostic_contract)
                )
                failure_details[
                    "level1_release_authorization_sha256"
                ] = sha256_file(
                    args.level1_release_diagnostic_authorization
                )
            if failure_telemetry_contract is not None:
                assert args.failure_telemetry_contract is not None
                assert args.failure_telemetry_authorization is not None
                failure_details["failure_telemetry_work_package_id"] = (
                    RETREAT_FAILURE_TELEMETRY_WORK_PACKAGE
                )
                failure_details["failure_telemetry_phase"] = (
                    failure_telemetry_phase
                )
                failure_details["failure_telemetry_contract_sha256"] = (
                    sha256_file(args.failure_telemetry_contract)
                )
                failure_details[
                    "failure_telemetry_authorization_sha256"
                ] = sha256_file(args.failure_telemetry_authorization)
                failure_details["stop_on_safety_failure"] = True
                failure_details["failure_telemetry_written"] = (
                    failure_telemetry_sha256 is not None
                )
                if failure_telemetry_sha256 is not None:
                    failure_details["failure_telemetry_path"] = (
                        "failure_telemetry.json"
                    )
                    failure_details["failure_telemetry_sha256"] = (
                        failure_telemetry_sha256
                    )
            if release_retreat_boundary_contract is not None:
                assert args.release_retreat_boundary_contract is not None
                assert args.release_retreat_boundary_authorization is not None
                failure_details[
                    "release_retreat_boundary_work_package_id"
                ] = RELEASE_RETREAT_BOUNDARY_WORK_PACKAGE
                failure_details["release_retreat_boundary_phase"] = (
                    release_retreat_boundary_phase
                )
                failure_details[
                    "release_retreat_boundary_contract_sha256"
                ] = sha256_file(args.release_retreat_boundary_contract)
                failure_details[
                    "release_retreat_boundary_authorization_sha256"
                ] = sha256_file(
                    args.release_retreat_boundary_authorization
                )
                failure_details[
                    "release_retreat_boundary_trace_written"
                ] = release_retreat_boundary_sha256 is not None
                if release_retreat_boundary_sha256 is not None:
                    failure_details[
                        "release_retreat_boundary_trace_path"
                    ] = "release_retreat_boundary_trace.json"
                    failure_details[
                        "release_retreat_boundary_trace_sha256"
                    ] = release_retreat_boundary_sha256
            finish_run(
                args.ops_root,
                args.run_id,
                "failed",
                failure_details,
            )
        raise


if __name__ == "__main__":
    raise SystemExit(main())
