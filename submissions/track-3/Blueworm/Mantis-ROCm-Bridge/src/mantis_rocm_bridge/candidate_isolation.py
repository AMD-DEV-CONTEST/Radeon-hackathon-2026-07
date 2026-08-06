"""Candidate-loop baseline isolation for the right-arm grasp sweep.

The right-arm grasp sweep tries a list of grasp candidates in order. Before the
fix in this module, a failed candidate's recovery re-solved a front-clearance
qpos from a drifted seed and threaded that re-solved value forward as the next
candidate's IK seed and command start. The result was that candidate N>0 ran
from a different nominal/physical state than candidate 0, so a probe run that
succeeded on candidate 3 could not be reproduced by a replay run that executed
candidate 3 directly from the original front-clearance baseline.

These helpers enforce a hard invariant:

    Every grasp candidate's IK seed AND command start must be the SAME frozen
    front-clearance qpos captured when the loop is entered. A failed
    candidate's recovery must return the real robot to that frozen baseline and
must never thread a re-solved (drifted) front clearance forward.

The module is intentionally free of numpy and Genesis dependencies so the
isolation invariant can be exercised as plain, deterministic logic in unit
tests. It also provides:

  * a strict arm read-back check that reuses the existing arm tracking-error
    limit without lowering it,
  * a selected-bowl pose-drift safe-fail (a failed attempt that dislodges the
    bowl must abort instead of retrying against a moved bowl; the bowl is never
    teleported back during a valid episode),
  * a replay-plan staleness check that marks pre-fix plans whose successful
    right-side candidate was not the first one tried as needing re-probe.
"""

from __future__ import annotations

import math
from typing import Iterable, Sequence


# Plans generated with candidate-loop baseline isolation are stamped with this
# version. Pre-fix plans (and any plan lacking the field) deserialize as 0.
CANDIDATE_ISOLATION_VERSION = 1


# Conservative selected-bowl drift safety bounds used when isolating candidates.
#
# These are NEW safety limits, tighter than the task placement tolerances
# (xy_axis_alignment_tolerance_m = 0.04 m, height_absolute_tolerance_m = 0.02 m)
# and the grasp half-span (0.115 m). They catch a failed attempt that visibly
# dislodges the bowl so the episode safe-fails rather than retrying against a
# moved bowl. They do NOT relax any tracking/collision/contact/safety/task gate.
BOWL_DRIFT_TRANSLATION_TOLERANCE_M = 0.01  # 1 cm
BOWL_DRIFT_ROTATION_TOLERANCE_RAD = 0.05  # ~2.86 deg, same order as arm tracking error


def _require_finite(value: float, label: str) -> float:
    """Validate that ``value`` is a finite real number and return it as float."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a finite number, got {type(value).__name__}")
    f = float(value)
    if f != f or f in (float("inf"), float("-inf")):
        raise ValueError(f"{label} must be finite, got {value}")
    return f


def _require_sequence(values: Sequence[float], length: int, label: str) -> list[float]:
    """Validate that ``values`` is a finite numeric sequence of the given length."""
    if not isinstance(values, (list, tuple)):
        raise ValueError(f"{label} must be a list or tuple, got {type(values).__name__}")
    if len(values) != length:
        raise ValueError(f"{label} must have {length} elements, got {len(values)}")
    return [_require_finite(v, f"{label}[{i}]") for i, v in enumerate(values)]


def freeze_front_clearance_baseline(qpos: Sequence[float]) -> tuple[float, ...]:
    """Freeze the front-clearance qpos that opens the right-arm candidate loop.

    The returned immutable tuple is the single source of truth for every
    candidate's IK seed and command start. It is captured exactly once, when the
    loop is entered, and must never be mutated or re-derived.
    """
    if not isinstance(qpos, (list, tuple)):
        raise ValueError("front-clearance baseline must be a list or tuple")
    if len(qpos) == 0:
        raise ValueError("front-clearance baseline must be non-empty")
    return tuple(_require_finite(v, f"front_clearance_qpos[{i}]") for i, v in enumerate(qpos))


def candidate_loop_init_qpos(baseline: Sequence[float]) -> tuple[float, ...]:
    """Return the IK-seed qpos for any candidate in the loop.

    This is deliberately always the frozen baseline, independent of how many
    prior candidates failed. Calling this (rather than threading a mutable
    ``current``) is what makes the start point immune to pollution by a prior
    failure's re-solved front clearance.
    """
    return freeze_front_clearance_baseline(baseline)


def arm_readback_error_rad(
    readback: Sequence[float],
    baseline: Sequence[float],
    arm_indices: Sequence[int],
) -> float:
    """Max absolute per-DOF error over the arm DOFs between read-back and baseline.

    Mirrors the existing ``command_segment`` tracking-error definition: the max
    abs difference restricted to the arm DOF indices, so the same physical
    meaning and the same threshold apply.
    """
    if len(readback) != len(baseline):
        raise ValueError(
            f"readback length {len(readback)} does not match baseline length {len(baseline)}"
        )
    if not arm_indices:
        raise ValueError("arm_indices must be non-empty")
    rb = [_require_finite(v, f"readback[{i}]") for i, v in enumerate(readback)]
    bl = [_require_finite(v, f"baseline[{i}]") for i, v in enumerate(baseline)]
    error = 0.0
    for raw_index in arm_indices:
        if isinstance(raw_index, bool) or not isinstance(raw_index, int):
            raise ValueError(f"arm_indices entries must be int, got {type(raw_index).__name__}")
        index = int(raw_index)
        if index < 0 or index >= len(bl):
            raise ValueError(f"arm index {index} out of range for {len(bl)} DOFs")
        error = max(error, abs(rb[index] - bl[index]))
    return error


def readback_within_arm_tolerance(
    readback: Sequence[float],
    baseline: Sequence[float],
    max_tracking_error_rad: float,
    arm_indices: Sequence[int],
) -> bool:
    """True iff the real robot read-back is at the frozen baseline within tolerance."""
    limit = _require_finite(max_tracking_error_rad, "max_tracking_error_rad")
    if limit < 0.0:
        raise ValueError("max_tracking_error_rad must be non-negative")
    return arm_readback_error_rad(readback, baseline, arm_indices) <= limit


def assert_arm_at_baseline(
    readback: Sequence[float],
    baseline: Sequence[float],
    max_tracking_error_rad: float,
    *,
    stage: str,
    arm_indices: Sequence[int],
) -> None:
    """Raise if the real robot read-back drifted off the frozen baseline.

    Uses the EXISTING arm tracking-error limit (passed in by the caller) and
    does not lower it. A failure here means the recovery did not return the arm
    to the baseline, so starting the next candidate would replay the pollution
    the isolation fix exists to prevent.
    """
    error = arm_readback_error_rad(readback, baseline, arm_indices)
    limit = _require_finite(max_tracking_error_rad, "max_tracking_error_rad")
    if error > limit:
        raise RuntimeError(
            f"{stage}: real robot read-back drifted {error:.6f} rad from the "
            f"frozen front-clearance baseline, exceeding the arm tracking-error "
            f"limit {limit:.6f} rad (threshold not lowered); refusing to start "
            f"the next candidate from a polluted state."
        )


def translation_distance_m(pos0_xyz: Sequence[float], pos1_xyz: Sequence[float]) -> float:
    """Euclidean translation between two 3-vectors in meters."""
    a = _require_sequence(pos0_xyz, 3, "pos0_xyz")
    b = _require_sequence(pos1_xyz, 3, "pos1_xyz")
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))


def _normalize_quat(q_wxyz: list[float]) -> list[float]:
    """Return a unit-length copy of a WXYZ quaternion."""
    w, x, y, z = q_wxyz
    norm = math.sqrt(w * w + x * x + y * y + z * z)
    if norm == 0.0:
        raise ValueError("zero-norm quaternion cannot be normalized")
    return [w / norm, x / norm, y / norm, z / norm]


def _quat_conj(q_wxyz: list[float]) -> list[float]:
    """Conjugate of a WXYZ quaternion (inverse for a unit quaternion)."""
    w, x, y, z = q_wxyz
    return [w, -x, -y, -z]


def _quat_mul(a_wxyz: list[float], b_wxyz: list[float]) -> list[float]:
    """Hamilton product of two WXYZ quaternions."""
    aw, ax, ay, az = a_wxyz
    bw, bx, by, bz = b_wxyz
    return [
        aw * bw - ax * bx - ay * by - az * bz,
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
    ]


def quaternion_relative_angle_rad(
    q0_wxyz: Sequence[float],
    q1_wxyz: Sequence[float],
) -> float:
    """Unsigned rotation angle (rad) between two WXYZ quaternions in [0, pi]."""
    a = _normalize_quat(_require_sequence(q0_wxyz, 4, "q0_wxyz"))
    b = _normalize_quat(_require_sequence(q1_wxyz, 4, "q1_wxyz"))
    rel = _quat_mul(_quat_conj(a), b)
    # Double-cover: a rotation and its negated quaternion represent the same
    # orientation, so take the absolute w component.
    cos_half = abs(rel[0])
    if cos_half > 1.0:
        cos_half = 1.0
    return 2.0 * math.acos(cos_half)


def bowl_drift_within_tolerance(
    pos0_xyz: Sequence[float],
    quat0_wxyz: Sequence[float],
    pos_now_xyz: Sequence[float],
    quat_now_wxyz: Sequence[float],
    *,
    max_translation_drift_m: float,
    max_rotation_drift_rad: float,
) -> bool:
    """True iff the selected bowl pose is still within drift bounds."""
    t_limit = _require_finite(max_translation_drift_m, "max_translation_drift_m")
    r_limit = _require_finite(max_rotation_drift_rad, "max_rotation_drift_rad")
    if t_limit < 0.0 or r_limit < 0.0:
        raise ValueError("drift tolerances must be non-negative")
    return (
        translation_distance_m(pos0_xyz, pos_now_xyz) <= t_limit
        and quaternion_relative_angle_rad(quat0_wxyz, quat_now_wxyz) <= r_limit
    )


def assert_bowl_pose_stable(
    pos0_xyz: Sequence[float],
    quat0_wxyz: Sequence[float],
    pos_now_xyz: Sequence[float],
    quat_now_wxyz: Sequence[float],
    *,
    max_translation_drift_m: float,
    max_rotation_drift_rad: float,
    stage: str,
) -> None:
    """Raise if the selected bowl drifted beyond safe bounds during a failed attempt.

    The bowl is never teleported back; a drift beyond these bounds means the
    candidate geometry assumptions no longer hold, so the episode safe-fails
    rather than retrying against a moved bowl.
    """
    t = translation_distance_m(pos0_xyz, pos_now_xyz)
    r = quaternion_relative_angle_rad(quat0_wxyz, quat_now_wxyz)
    t_limit = _require_finite(max_translation_drift_m, "max_translation_drift_m")
    r_limit = _require_finite(max_rotation_drift_rad, "max_rotation_drift_rad")
    if t > t_limit or r > r_limit:
        raise RuntimeError(
            f"{stage}: selected bowl drifted during the failed candidate "
            f"(translation={t:.6f} m, rotation={r:.6f} rad) beyond the safe "
            f"bounds (translation<={t_limit:.6f} m, rotation<={r_limit:.6f} rad); "
            f"safe-failing rather than retrying against a moved bowl. The bowl "
            f"is never teleported back during a valid episode."
        )


def simulate_candidate_loop_inits(
    frozen_baseline: Sequence[float],
    failure_recovery_resolved_fronts: Iterable[Sequence[float]],
) -> list[tuple[float, ...]]:
    """Pure model of the right-arm candidate loop's IK-seed threading.

    Given the frozen front-clearance baseline captured at loop entry and a list
    of the re-solved front clearances produced by each failed candidate's
    recovery (which under the OLD bug were threaded forward as the next
    candidate's init), return the init actually used for each candidate, in
    order.

    With candidate isolation every candidate's init is the frozen baseline; the
    drifted resolved fronts are deliberately discarded, so the returned sequence
    is all-baseline regardless of how badly the resolved fronts drifted.

    The number of returned inits is ``len(failure_recovery_resolved_fronts) +
    1``: one init per failed candidate plus the init of the next (final or sole)
    candidate.
    """
    baseline = freeze_front_clearance_baseline(frozen_baseline)
    inits: list[tuple[float, ...]] = []
    for _resolved in failure_recovery_resolved_fronts:
        # Each failed candidate ran from the frozen baseline; the resolved
        # front clearance it produced on recovery is intentionally NOT used.
        inits.append(candidate_loop_init_qpos(baseline))
    # The next (final or sole) candidate also starts from the frozen baseline.
    inits.append(candidate_loop_init_qpos(baseline))
    return inits


def legacy_polluted_candidate_inits(
    frozen_baseline: Sequence[float],
    failure_recovery_resolved_fronts: Iterable[Sequence[float]],
) -> list[tuple[float, ...]]:
    """The pre-fix (buggy) IK-seed threading, for contrast in tests.

    This mirrors exactly what the loop did before the isolation fix: each
    failed candidate's recovery re-solved a front clearance and that re-solved
    value was threaded forward as the next candidate's init. The first candidate
    starts from the clean baseline, but every subsequent candidate starts from
    the drifted resolved front produced by the prior failure.
    """
    baseline = freeze_front_clearance_baseline(frozen_baseline)
    inits: list[tuple[float, ...]] = []
    current = baseline
    for resolved in failure_recovery_resolved_fronts:
        inits.append(current)
        current = freeze_front_clearance_baseline(resolved)  # the bug
    inits.append(current)
    return inits


def plan_needs_reprobe_for_candidate_isolation(
    right_side_candidate_indices: Iterable[int | None],
    candidate_isolation_version: int,
) -> bool:
    """Decide whether a replay plan must be re-probed for candidate isolation.

    A pre-fix plan (``candidate_isolation_version`` < 1) needs re-probe iff some
    right-side step's successful grasp candidate was NOT the first one tried.
    Only ``candidate_index > 0`` could have inherited a polluted/drifted start
    under the pre-fix recovery; ``candidate_index == 0`` is tried first from a
    clean baseline and is therefore compatible. Plans stamped with
    ``candidate_isolation_version`` >= 1 were generated with baseline isolation
    and never need re-probe for this.

    Left-side steps (candidate index ``None``) are irrelevant to the right-arm
    sweep and are skipped.
    """
    if isinstance(candidate_isolation_version, bool) or not isinstance(
        candidate_isolation_version, int
    ):
        raise ValueError("candidate_isolation_version must be an int")
    if candidate_isolation_version >= 1:
        return False
    for raw_index in right_side_candidate_indices:
        if raw_index is None:
            continue
        if isinstance(raw_index, bool) or not isinstance(raw_index, int):
            raise ValueError(
                "right_side_candidate_indices entries must be int or None, "
                f"got {type(raw_index).__name__}"
            )
        if int(raw_index) > 0:
            return True
    return False
