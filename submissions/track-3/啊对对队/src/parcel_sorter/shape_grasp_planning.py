"""Shape-dispatched geometry-aware grasp planning.

The box planner and the cylinder planner deliberately remain separate
algorithms.  This module only supplies the runtime boundary that selects the
appropriate candidate family and preserves an explicit capability decision.
It is pure apart from candidate generation, so it can be tested before a
Genesis scene is created and can be reused by later closed-loop adapters.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Sequence

from .cylinder_grasp_planning import plan_cylinder_grasp_candidates
from .grasp_planning import (
    box_requires_geometry_aware_grasp_planning,
    generate_box_grasp_pose_candidates,
    grasp_evaluation_is_feasible,
    grasp_evaluation_rank_key,
)
from .randomization import ParcelSample


@dataclass(frozen=True)
class ShapeGraspPlannerConfig:
    """Frozen planner parameters shared by a future closed-loop adapter."""

    cylinder_enabled: bool = True
    cylinder_jaw_aperture_m: float = 0.080
    cylinder_min_aperture_margin_m: float = 0.001
    cylinder_min_horizontal_rolling_friction: float = 0.001
    cylinder_max_parallel_jaw_length_m: float | None = 0.320
    cylinder_max_axis_tilt_deg: float = 20.0
    cylinder_upright_radial_yaw_count: int = 1
    cylinder_max_upright_vertical_offset_m: float = 0.040
    cylinder_min_upright_side_overlap_m: float = 0.020
    cylinder_max_horizontal_axial_offset_m: float = 0.050
    cylinder_min_horizontal_end_margin_m: float = 0.060
    cylinder_horizontal_radial_angles_deg: tuple[float, ...] = (0.0,)

    def validate(self) -> None:
        positive = (
            ("cylinder_jaw_aperture_m", self.cylinder_jaw_aperture_m),
            ("cylinder_min_upright_side_overlap_m", self.cylinder_min_upright_side_overlap_m),
            ("cylinder_min_horizontal_end_margin_m", self.cylinder_min_horizontal_end_margin_m),
        )
        if any(not math.isfinite(float(value)) or float(value) <= 0 for _, value in positive):
            raise ValueError("cylinder aperture and overlap distances must be positive and finite")
        nonnegative = (
            ("cylinder_min_aperture_margin_m", self.cylinder_min_aperture_margin_m),
            (
                "cylinder_min_horizontal_rolling_friction",
                self.cylinder_min_horizontal_rolling_friction,
            ),
            (
                "cylinder_max_upright_vertical_offset_m",
                self.cylinder_max_upright_vertical_offset_m,
            ),
            ("cylinder_max_horizontal_axial_offset_m", self.cylinder_max_horizontal_axial_offset_m),
        )
        if any(
            not math.isfinite(float(value)) or float(value) < 0
            for _, value in nonnegative
        ):
            raise ValueError("cylinder margins, thresholds, and offset limits must be non-negative and finite")
        if self.cylinder_max_parallel_jaw_length_m is not None and (
            not math.isfinite(float(self.cylinder_max_parallel_jaw_length_m))
            or self.cylinder_max_parallel_jaw_length_m <= 0
        ):
            raise ValueError("cylinder_max_parallel_jaw_length_m must be positive and finite when set")
        if not 0 < self.cylinder_max_axis_tilt_deg < 90:
            raise ValueError("cylinder_max_axis_tilt_deg must be in (0, 90)")
        if self.cylinder_upright_radial_yaw_count < 1:
            raise ValueError("cylinder_upright_radial_yaw_count must be positive")
        if not self.cylinder_horizontal_radial_angles_deg:
            raise ValueError("cylinder_horizontal_radial_angles_deg cannot be empty")
        if any(
            not math.isfinite(float(angle)) or abs(float(angle)) >= 90
            for angle in self.cylinder_horizontal_radial_angles_deg
        ):
            raise ValueError("cylinder radial angles must be finite and in (-90, 90)")


@dataclass(frozen=True)
class ShapeGraspPlan:
    """Candidate set plus a machine-readable capability/activation decision."""

    shape: str
    supported: bool
    activation_eligible: bool
    reason: str
    candidates: tuple[Any, ...]


def build_shape_grasp_plan(
    sample: ParcelSample,
    parcel_pose: Sequence[float],
    *,
    hand_clearance_m: float,
    include_symmetric_wrist: bool = True,
    config: ShapeGraspPlannerConfig = ShapeGraspPlannerConfig(),
) -> ShapeGraspPlan:
    """Select the correct candidate family without hiding capability limits.

    ``supported`` means the end-effector and geometry can be represented by the
    selected planner.  ``activation_eligible`` additionally applies the
    current box scope gate; the latter prevents a future integration from
    silently broadening the already registered box experiment.
    """

    if hand_clearance_m <= 0 or not math.isfinite(hand_clearance_m):
        raise ValueError("hand_clearance_m must be positive and finite")
    config.validate()

    if sample.shape == "box":
        candidates = generate_box_grasp_pose_candidates(
            sample,
            tuple(float(value) for value in parcel_pose),
            hand_clearance_m=hand_clearance_m,
            include_symmetric_wrist=include_symmetric_wrist,
        )
        eligible = box_requires_geometry_aware_grasp_planning(
            sample,
            hand_clearance_m=hand_clearance_m,
        )
        return ShapeGraspPlan(
            shape="box",
            supported=True,
            activation_eligible=eligible,
            reason=("supported" if eligible else "box_below_geometry_scope"),
            candidates=candidates,
        )

    if sample.shape == "cylinder":
        if not config.cylinder_enabled:
            return ShapeGraspPlan(
                shape="cylinder",
                supported=False,
                activation_eligible=False,
                reason="cylinder_planner_disabled",
                candidates=(),
            )
        plan = plan_cylinder_grasp_candidates(
            sample,
            tuple(float(value) for value in parcel_pose),
            hand_clearance_m=hand_clearance_m,
            jaw_aperture_m=config.cylinder_jaw_aperture_m,
            min_aperture_margin_m=config.cylinder_min_aperture_margin_m,
            min_horizontal_rolling_friction=config.cylinder_min_horizontal_rolling_friction,
            max_parallel_jaw_length_m=config.cylinder_max_parallel_jaw_length_m,
            max_axis_tilt_deg=config.cylinder_max_axis_tilt_deg,
            include_symmetric_wrist=include_symmetric_wrist,
            upright_radial_yaw_count=config.cylinder_upright_radial_yaw_count,
            max_upright_vertical_offset_m=config.cylinder_max_upright_vertical_offset_m,
            min_upright_side_overlap_m=config.cylinder_min_upright_side_overlap_m,
            max_horizontal_axial_offset_m=config.cylinder_max_horizontal_axial_offset_m,
            min_horizontal_end_margin_m=config.cylinder_min_horizontal_end_margin_m,
            horizontal_radial_angles_deg=config.cylinder_horizontal_radial_angles_deg,
        )
        return ShapeGraspPlan(
            shape="cylinder",
            supported=plan.capability.supported,
            activation_eligible=plan.capability.supported,
            reason=plan.capability.reason,
            candidates=plan.candidates,
        )

    raise ValueError(f"unsupported parcel shape: {sample.shape}")


def generate_shape_grasp_pose_candidates(
    sample: ParcelSample,
    parcel_pose: Sequence[float],
    *,
    hand_clearance_m: float,
    include_symmetric_wrist: bool = True,
    config: ShapeGraspPlannerConfig = ShapeGraspPlannerConfig(),
) -> tuple[Any, ...]:
    """Convenience wrapper returning only candidates for IK evaluation."""

    return build_shape_grasp_plan(
        sample,
        parcel_pose,
        hand_clearance_m=hand_clearance_m,
        include_symmetric_wrist=include_symmetric_wrist,
        config=config,
    ).candidates


def shape_grasp_evaluation_rank_key(
    evaluation: dict[str, Any],
    *,
    shape: str,
    collision_filter_enabled: bool = True,
    manipulability_ranking_enabled: bool = True,
) -> tuple[Any, ...]:
    """Keep hard feasibility first, then apply a shape-specific physical prior."""

    base = grasp_evaluation_rank_key(
        evaluation,
        collision_filter_enabled=collision_filter_enabled,
        manipulability_ranking_enabled=manipulability_ranking_enabled,
    )
    if shape == "box":
        return base
    if shape != "cylinder":
        raise ValueError(f"unsupported parcel shape: {shape}")

    rolling_risk = _finite_nonnegative(
        evaluation.get("rolling_risk_score", 0.0),
        "rolling_risk_score",
    )
    moment_arm = _finite_nonnegative(
        evaluation.get("centre_of_mass_moment_arm_m", 0.0),
        "centre_of_mass_moment_arm_m",
    )
    # Preserve the five hard feasibility/collision/error fields from the
    # registered ranker.  Physical cylinder stability then precedes wrist,
    # offset, joint-travel, manipulability, and clearance tie-breaks.
    return (*base[:5], rolling_risk, moment_arm, *base[5:])


def rank_shape_grasp_pose_evaluations(
    evaluations: Sequence[dict[str, Any]],
    *,
    shape: str,
    collision_filter_enabled: bool = True,
    manipulability_ranking_enabled: bool = True,
) -> list[dict[str, Any]]:
    """Rank evaluated candidates while preserving the box ordering contract."""

    return sorted(
        evaluations,
        key=lambda evaluation: shape_grasp_evaluation_rank_key(
            evaluation,
            shape=shape,
            collision_filter_enabled=collision_filter_enabled,
            manipulability_ranking_enabled=manipulability_ranking_enabled,
        ),
    )


def select_shape_grasp_pose_evaluation(
    evaluations: Sequence[dict[str, Any]],
    *,
    shape: str,
    rejected_candidate_ids: frozenset[str] = frozenset(),
    collision_filter_enabled: bool = True,
    manipulability_ranking_enabled: bool = True,
) -> dict[str, Any] | None:
    """Return the first non-rejected feasible candidate in shape-aware order."""

    ranked = rank_shape_grasp_pose_evaluations(
        evaluations,
        shape=shape,
        collision_filter_enabled=collision_filter_enabled,
        manipulability_ranking_enabled=manipulability_ranking_enabled,
    )
    return next(
        (
            evaluation
            for evaluation in ranked
            if str(evaluation["candidate_id"]) not in rejected_candidate_ids
            and grasp_evaluation_is_feasible(
                evaluation,
                collision_filter_enabled=collision_filter_enabled,
            )
        ),
        None,
    )


def _finite_nonnegative(value: Any, name: str) -> float:
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"{name} must be finite and non-negative")
    return result
