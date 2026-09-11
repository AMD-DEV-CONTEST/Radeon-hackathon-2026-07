"""Fail-closed safety harness for residual and absolute mobile VLA actions."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Any, Iterable

from .mobile_task import decode_mobile_bimanual_action, limit_mobile_arm_step


@dataclass(frozen=True)
class MobileHarnessConfig:
    candidate_scales: tuple[float, ...] = (0.0, 0.25, 0.5, 0.75, 1.0)
    max_base_residual_m_s: float = 0.02
    max_yaw_residual_rad_s: float = 0.20
    max_position_residual_m: float = 0.01
    max_quaternion_residual_rad: float = math.radians(5.0)
    max_base_linear_speed_m_s: float = 0.05
    max_contact_base_linear_speed_m_s: float = 0.12
    max_base_yaw_rate_rad_s: float = 1.0
    max_cartesian_step_m: float = 0.04
    min_progress_ratio: float = 0.50
    force_limit_n: float = 35.0
    force_memory_window: int = 6
    force_memory_soft_limit_n: float = 20.0
    force_memory_rise_deadband_n: float = 2.0
    force_memory_rise_limit_n: float = 8.0

    def __post_init__(self) -> None:
        positive = (
            self.max_base_residual_m_s,
            self.max_yaw_residual_rad_s,
            self.max_position_residual_m,
            self.max_quaternion_residual_rad,
            self.max_base_linear_speed_m_s,
            self.max_contact_base_linear_speed_m_s,
            self.max_base_yaw_rate_rad_s,
            self.max_cartesian_step_m,
            self.force_limit_n,
            self.force_memory_soft_limit_n,
            self.force_memory_rise_deadband_n,
            self.force_memory_rise_limit_n,
        )
        if any(not math.isfinite(value) or value <= 0.0 for value in positive):
            raise ValueError("mobile harness limits must be finite and positive")
        if not 0.0 < self.min_progress_ratio <= 1.0:
            raise ValueError("min_progress_ratio must be in (0, 1]")
        if not self.candidate_scales or any(
            not math.isfinite(value) or not 0.0 <= value <= 1.0
            for value in self.candidate_scales
        ):
            raise ValueError("candidate scales must be finite values in [0, 1]")
        if 0.0 not in self.candidate_scales:
            raise ValueError("candidate scales must include the expert fallback 0.0")
        if self.force_memory_window < 2:
            raise ValueError("force_memory_window must be at least two samples")
        if self.force_memory_soft_limit_n >= self.force_limit_n:
            raise ValueError("force memory soft limit must be below the force limit")
        if self.force_memory_rise_deadband_n >= self.force_memory_rise_limit_n:
            raise ValueError("force memory rise deadband must be below the rise limit")


@dataclass(frozen=True)
class MobileHarnessCandidate:
    scale: float
    action: tuple[float, ...]
    safe: bool
    score: float
    min_progress_ratio: float
    max_cartesian_step_m: float
    tool_command_corrections: int
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class MobileHarnessDecision:
    selected: MobileHarnessCandidate
    candidates: tuple[MobileHarnessCandidate, ...]
    fallback_to_expert: bool
    emergency_stop: bool
    rejected_vla: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ForceMemoryDecision:
    scale_cap: float
    peak_force_n: float
    force_rise_n: float
    sample_count: int
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def force_memory_scale_cap(
    force_history_n: Iterable[float],
    *,
    config: MobileHarnessConfig = MobileHarnessConfig(),
) -> ForceMemoryDecision:
    """Turn recent contact-force history into a conservative VLA scale cap."""

    history = tuple(float(value) for value in force_history_n)
    if any(not math.isfinite(value) or value < 0.0 for value in history):
        raise ValueError("force history must contain finite non-negative values")
    history = history[-config.force_memory_window :]
    if not history:
        return ForceMemoryDecision(1.0, 0.0, 0.0, 0, ("no_force_history",))
    peak_force_n = max(history)
    force_rise_n = max(0.0, history[-1] - min(history))
    load_risk = max(
        0.0,
        (peak_force_n - config.force_memory_soft_limit_n)
        / (config.force_limit_n - config.force_memory_soft_limit_n),
    )
    rise_risk = max(
        0.0,
        (force_rise_n - config.force_memory_rise_deadband_n)
        / (config.force_memory_rise_limit_n - config.force_memory_rise_deadband_n),
    )
    risk = min(1.0, max(load_risk, rise_risk))
    reasons = []
    if load_risk > 0.0:
        reasons.append("sustained_force_risk")
    if rise_risk > 0.0:
        reasons.append("rising_force_risk")
    return ForceMemoryDecision(
        scale_cap=1.0 - risk,
        peak_force_n=peak_force_n,
        force_rise_n=force_rise_n,
        sample_count=len(history),
        reasons=tuple(reasons or ("stable_force_history",)),
    )


def select_mobile_harness_action(
    *,
    state: Iterable[float],
    expert_action: Iterable[float],
    vla_action: Iterable[float],
    stage: str,
    config: MobileHarnessConfig = MobileHarnessConfig(),
    maximum_vla_scale: float = 1.0,
    maximum_vla_scale_reason: str = "force_memory_scale_gate",
    arm_reference_is_expert_target: bool = False,
    absolute_vla_action: bool = False,
) -> MobileHarnessDecision:
    """Select the largest safe VLA contribution under the declared authority.

    Residual policies remain anchored to the deterministic expert. Absolute VLA
    policies are projected only against the observed robot state and safety
    limits; the expert action is not blended into their executable candidate.
    """

    if not math.isfinite(maximum_vla_scale) or not 0.0 <= maximum_vla_scale <= 1.0:
        raise ValueError("maximum_vla_scale must be finite and in [0, 1]")
    if not maximum_vla_scale_reason:
        raise ValueError("maximum_vla_scale_reason cannot be empty")
    state_values = _finite_vector(state, 43, "state")
    expert = _finite_vector(expert_action, 19, "expert action")
    raw_vla = tuple(float(value) for value in vla_action)
    rejected_vla = len(raw_vla) != 19 or any(
        not math.isfinite(value) for value in raw_vla
    )
    if not rejected_vla:
        rejected_vla = any(
            math.sqrt(sum(value * value for value in raw_vla[start : start + 4]))
            <= 1e-8
            for start in (6, 14)
        )
    if rejected_vla and absolute_vla_action:
        vla = (
            0.0,
            0.0,
            0.0,
            *state_values[24:31],
            1.0,
            *state_values[31:38],
            1.0,
        )
    else:
        vla = expert if rejected_vla else raw_vla
    force_n = max(abs(state_values[38]), abs(state_values[39]))
    if force_n >= config.force_limit_n:
        stop = _emergency_stop_candidate(
            state_values, expert, f"force_gate_stop:{force_n:.6g}N"
        )
        return MobileHarnessDecision(
            selected=stop,
            candidates=(stop,),
            fallback_to_expert=False,
            emergency_stop=True,
            rejected_vla=rejected_vla,
        )

    candidate_builder = _absolute_candidate if absolute_vla_action else _candidate
    candidates = tuple(
        candidate_builder(
            scale=float(scale),
            state=state_values,
            expert=expert,
            vla=vla,
            stage=stage,
            config=config,
            rejected_vla=rejected_vla,
            maximum_vla_scale=maximum_vla_scale,
            maximum_vla_scale_reason=maximum_vla_scale_reason,
            arm_reference_is_expert_target=arm_reference_is_expert_target,
        )
        for scale in config.candidate_scales
    )
    safe = tuple(candidate for candidate in candidates if candidate.safe)
    if not safe:
        stop = _emergency_stop_candidate(
            state_values, expert, "no_safe_candidate_stop"
        )
        return MobileHarnessDecision(
            selected=stop,
            candidates=(*candidates, stop),
            fallback_to_expert=False,
            emergency_stop=True,
            rejected_vla=rejected_vla,
        )
    selected = max(safe, key=lambda item: (item.score, item.scale))
    return MobileHarnessDecision(
        selected=selected,
        candidates=candidates,
        fallback_to_expert=(not absolute_vla_action and selected.scale == 0.0),
        emergency_stop=False,
        rejected_vla=rejected_vla,
    )


def transport_deadline_requires_expert(
    *,
    distance_m: float,
    remaining_time_s: float,
    expert_forward_speed_m_s: float,
    completion_tolerance_m: float = 0.005,
    minimum_capacity_ratio: float = 0.75,
) -> bool:
    """Fail over when conservative expert capacity cannot meet the deadline."""

    values = (
        distance_m,
        remaining_time_s,
        expert_forward_speed_m_s,
        completion_tolerance_m,
        minimum_capacity_ratio,
    )
    if any(not math.isfinite(value) for value in values):
        raise ValueError("transport deadline inputs must be finite")
    if distance_m < 0.0 or expert_forward_speed_m_s < 0.0:
        raise ValueError("transport distance and speed cannot be negative")
    if remaining_time_s <= 0.0 or completion_tolerance_m <= 0.0:
        raise ValueError("transport time and tolerance must be positive")
    if not 0.0 < minimum_capacity_ratio <= 1.0:
        raise ValueError("minimum capacity ratio must be in (0, 1]")
    remaining_distance_m = max(0.0, distance_m - completion_tolerance_m)
    conservative_capacity_m = (
        remaining_time_s * expert_forward_speed_m_s * minimum_capacity_ratio
    )
    return remaining_distance_m > conservative_capacity_m + 1e-9


def build_mobile_failure_replay_manifest(
    collection_summary: dict[str, Any],
    *,
    source_summary: str = "unknown",
    holdout_episode_ids: Iterable[str] = (),
) -> dict[str, Any]:
    """Convert mobile collection failures into an auditable curriculum queue."""

    results = collection_summary.get("results")
    if not isinstance(results, list):
        raise ValueError("mobile collection summary must contain a results list")
    holdout = {str(value) for value in holdout_episode_ids}
    items = []
    for result in results:
        if not isinstance(result, dict) or bool(result.get("success")):
            continue
        episode_id = str(result.get("episode_id", "unknown"))
        if episode_id in holdout:
            continue
        parameters = result.get("parameters") or {}
        failure_stage = str(result.get("failure_stage") or "unclassified")
        force_n = float(result.get("max_contact_force_n") or 0.0)
        mass_kg = float(parameters.get("mass_kg") or 0.0)
        stage_priority = {
            "force_safety_abort": 6.0,
            "lift_success": 4.5,
            "placement_success": 3.5,
            "release_success": 3.0,
        }.get(failure_stage, 2.0)
        boundary_bonus = min(1.0, max(0.0, mass_kg - 0.40) / 0.25)
        items.append(
            {
                "episode_id": episode_id,
                "profile": str(result.get("profile", parameters.get("profile", "unknown"))),
                "failure_stage": failure_stage,
                "priority": stage_priority + boundary_bonus,
                "max_contact_force_n": force_n,
                "parameters": parameters,
                "curriculum_bridge": {
                    **parameters,
                    "episode_id": f"{episode_id}-bridge",
                    "mass_kg": round(max(0.05, mass_kg * 0.90), 4),
                },
                "source_summary": source_summary,
            }
        )
    items.sort(key=lambda item: (-float(item["priority"]), str(item["episode_id"])))
    return {
        "schema_version": 1,
        "protocol": "mobile-failure-replay-curriculum-v1",
        "holdout_episode_ids": sorted(holdout),
        "items": items,
        "counts_by_failure_stage": {
            stage: sum(item["failure_stage"] == stage for item in items)
            for stage in sorted({str(item["failure_stage"]) for item in items})
        },
        "claim_boundary": (
            "queue generation only; collection, retraining, and checkpoint promotion "
            "remain separately gated"
        ),
    }


def _candidate(
    *,
    scale: float,
    state: tuple[float, ...],
    expert: tuple[float, ...],
    vla: tuple[float, ...],
    stage: str,
    config: MobileHarnessConfig,
    rejected_vla: bool,
    maximum_vla_scale: float,
    maximum_vla_scale_reason: str,
    arm_reference_is_expert_target: bool,
) -> MobileHarnessCandidate:
    expert_base_speed = math.hypot(expert[0], expert[1])
    precision_handoff = stage == "grasp_approach" and expert_base_speed < 0.025
    dynamic_base_residual_limit = (
        0.0
        if precision_handoff
        else min(
            config.max_base_residual_m_s,
            expert_base_speed * (1.0 - config.min_progress_ratio),
        )
    )
    base_residual = _clip_norm(
        tuple(vla[index] - expert[index] for index in (0, 1)),
        dynamic_base_residual_limit,
    )
    yaw_residual = _clip(
        vla[2] - expert[2], config.max_yaw_residual_rad_s
    )
    action = [
        expert[0] + scale * base_residual[0],
        expert[1] + scale * base_residual[1],
        expert[2] + scale * yaw_residual,
    ]
    tool_corrections = 0
    for action_start, state_start in ((3, 24), (11, 31)):
        expert_position = expert[action_start : action_start + 3]
        residual = _clip_norm(
            tuple(
                vla[action_start + index] - expert[action_start + index]
                for index in range(3)
            ),
            config.max_position_residual_m,
        )
        candidate_position = tuple(
            nominal + scale * offset
            for nominal, offset in zip(expert_position, residual, strict=True)
        )
        action.extend(candidate_position)
        action.extend(
            _bounded_slerp(
                expert[action_start + 3 : action_start + 7],
                vla[action_start + 3 : action_start + 7],
                scale=scale,
                max_angle_rad=config.max_quaternion_residual_rad,
            )
        )
        expert_tool = 1.0 if expert[action_start + 7] >= 0.0 else -1.0
        vla_tool = 1.0 if vla[action_start + 7] >= 0.0 else -1.0
        tool_corrections += int(expert_tool != vla_tool)
        action.append(expert_tool)

    reasons = []
    left_reference = (
        expert[3:6] if arm_reference_is_expert_target else state[24:27]
    )
    right_reference = (
        expert[11:14] if arm_reference_is_expert_target else state[31:34]
    )
    stage_base_speed_limit = (
        config.max_contact_base_linear_speed_m_s
        if stage == "grasp_approach"
        else config.max_base_linear_speed_m_s
    )
    try:
        expert_decoded = decode_mobile_bimanual_action(
            expert,
            max_base_linear_speed_m_s=stage_base_speed_limit,
            max_base_yaw_rate_rad_s=config.max_base_yaw_rate_rad_s,
        )
        expert_left = limit_mobile_arm_step(
            expert_decoded.left, left_reference, max_step_m=config.max_cartesian_step_m
        )
        expert_right = limit_mobile_arm_step(
            expert_decoded.right, right_reference, max_step_m=config.max_cartesian_step_m
        )
        decoded = decode_mobile_bimanual_action(
            action,
            max_base_linear_speed_m_s=stage_base_speed_limit,
            max_base_yaw_rate_rad_s=config.max_base_yaw_rate_rad_s,
        )
        left = limit_mobile_arm_step(
            decoded.left, left_reference, max_step_m=config.max_cartesian_step_m
        )
        right = limit_mobile_arm_step(
            decoded.right, right_reference, max_step_m=config.max_cartesian_step_m
        )
        left_step = math.dist(left.position_m, left_reference)
        right_step = math.dist(right.position_m, right_reference)
        if left.position_m != decoded.left.position_m or right.position_m != decoded.right.position_m:
            reasons.append("cartesian_step_clipped")
        if math.hypot(*action[:2]) > stage_base_speed_limit + 1e-9:
            reasons.append("base_speed_clipped")
        progress_values = [
            _progress_ratio(left_reference, expert_left.position_m, left.position_m),
            _progress_ratio(right_reference, expert_right.position_m, right.position_m),
        ]
        selected_base = decoded.base_velocity_xy_yaw[:2]
        if expert_base_speed > 1e-9:
            base_progress = sum(
                selected * nominal
                for selected, nominal in zip(selected_base, expert[:2], strict=True)
            ) / (expert_base_speed * expert_base_speed)
            parallel = tuple(
                base_progress * nominal for nominal in expert[:2]
            )
            lateral = math.dist(selected_base, parallel)
            progress_values.append(base_progress)
            if lateral > 0.35 * expert_base_speed + 1e-9:
                reasons.append("base_lateral_gate")
        elif math.hypot(*selected_base) > 1e-9:
            progress_values.append(0.0)
            reasons.append("base_hold_gate")
        else:
            progress_values.append(1.0)
        if min(progress_values) + 1e-9 < config.min_progress_ratio:
            reasons.append("expert_progress_gate")
        executable_action = (
            *decoded.base_velocity_xy_yaw,
            *left.position_m,
            *left.quaternion_wxyz,
            left.gripper,
            *right.position_m,
            *right.quaternion_wxyz,
            right.gripper,
        )
    except ValueError as exc:
        left_step = right_step = math.inf
        progress_values = [-math.inf]
        executable_action = tuple(float(value) for value in action)
        reasons.append(f"decode_error:{exc}")
    if rejected_vla and scale > 0.0:
        reasons.append("invalid_vla_action")
    if scale > maximum_vla_scale + 1e-9:
        reasons.append(maximum_vla_scale_reason)
    if stage == "release" and tool_corrections:
        reasons.append("stage_tool_interlock")
    if precision_handoff:
        reasons.append("contact_precision_handoff")
    safe = not any(
        reason in {
            "expert_progress_gate",
            "base_lateral_gate",
            "base_hold_gate",
            "invalid_vla_action",
            maximum_vla_scale_reason,
        }
        or reason.startswith("decode_error:")
        for reason in reasons
    )
    learned_score = -scale if precision_handoff else scale
    score = learned_score - 0.02 * tool_corrections - (10.0 if not safe else 0.0)
    return MobileHarnessCandidate(
        scale=scale,
        action=tuple(float(value) for value in executable_action),
        safe=safe,
        score=score,
        min_progress_ratio=min(progress_values),
        max_cartesian_step_m=max(left_step, right_step),
        tool_command_corrections=tool_corrections,
        reasons=tuple(reasons or ("verified",)),
    )


def _absolute_candidate(
    *,
    scale: float,
    state: tuple[float, ...],
    expert: tuple[float, ...],
    vla: tuple[float, ...],
    stage: str,
    config: MobileHarnessConfig,
    rejected_vla: bool,
    maximum_vla_scale: float,
    maximum_vla_scale_reason: str,
    arm_reference_is_expert_target: bool,
) -> MobileHarnessCandidate:
    """Project an absolute VLA action without using expert motion as a reference."""

    del expert, arm_reference_is_expert_target
    stage_base_speed_limit = (
        config.max_contact_base_linear_speed_m_s
        if stage == "grasp_approach"
        else config.max_base_linear_speed_m_s
    )
    reasons: list[str] = []
    tool_corrections = 0
    try:
        raw_decoded = decode_mobile_bimanual_action(
            vla,
            max_base_linear_speed_m_s=stage_base_speed_limit,
            max_base_yaw_rate_rad_s=config.max_base_yaw_rate_rad_s,
        )
        base = tuple(scale * value for value in raw_decoded.base_velocity_xy_yaw)
        action: list[float] = [*base]
        max_step = 0.0
        for decoded_arm, state_start, release_tool in (
            (raw_decoded.left, 24, -1.0),
            (raw_decoded.right, 31, 1.0),
        ):
            current_position = state[state_start : state_start + 3]
            current_quaternion = state[state_start + 3 : state_start + 7]
            scaled_position = tuple(
                current + scale * (target - current)
                for current, target in zip(
                    current_position, decoded_arm.position_m, strict=True
                )
            )
            bounded_position = limit_mobile_arm_step(
                decoded_arm,
                current_position,
                max_step_m=config.max_cartesian_step_m,
            ).position_m
            if scale < 1.0:
                scaled_decoded = type(decoded_arm)(
                    position_m=scaled_position,
                    quaternion_wxyz=_bounded_slerp(
                        current_quaternion,
                        decoded_arm.quaternion_wxyz,
                        scale=scale,
                        max_angle_rad=config.max_quaternion_residual_rad,
                    ),
                    gripper=decoded_arm.gripper,
                )
                bounded_position = limit_mobile_arm_step(
                    scaled_decoded,
                    current_position,
                    max_step_m=config.max_cartesian_step_m,
                ).position_m
                bounded_quaternion = scaled_decoded.quaternion_wxyz
            else:
                bounded_quaternion = _bounded_slerp(
                    current_quaternion,
                    decoded_arm.quaternion_wxyz,
                    scale=1.0,
                    max_angle_rad=config.max_quaternion_residual_rad,
                )
            if bounded_position != scaled_position:
                reasons.append("cartesian_step_clipped")
            max_step = max(max_step, math.dist(current_position, bounded_position))
            tool = decoded_arm.gripper
            if stage == "release":
                tool_corrections += int((tool >= 0.0) != (release_tool >= 0.0))
                tool = release_tool
                if tool_corrections:
                    reasons.append("deterministic_release_interlock")
            action.extend((*bounded_position, *bounded_quaternion, tool))
        if raw_decoded.base_velocity_xy_yaw != tuple(vla[:3]):
            reasons.append("base_speed_clipped")
        if rejected_vla and scale > 0.0:
            reasons.append("invalid_vla_action")
        if scale > maximum_vla_scale + 1e-9:
            reasons.append(maximum_vla_scale_reason)
        safe = not any(
            reason in {"invalid_vla_action", maximum_vla_scale_reason}
            for reason in reasons
        )
        executable_action = tuple(float(value) for value in action)
    except (TypeError, ValueError) as exc:
        max_step = math.inf
        executable_action = tuple(float(value) for value in vla)
        reasons.append(f"decode_error:{exc}")
        safe = False
    return MobileHarnessCandidate(
        scale=scale,
        action=executable_action,
        safe=safe,
        score=scale - (10.0 if not safe else 0.0),
        min_progress_ratio=1.0,
        max_cartesian_step_m=max_step,
        tool_command_corrections=tool_corrections,
        reasons=tuple(reasons or ("absolute_vla_verified",)),
    )


def _emergency_stop_candidate(
    state: tuple[float, ...], expert: tuple[float, ...], reason: str
) -> MobileHarnessCandidate:
    action = (
        0.0,
        0.0,
        0.0,
        *state[24:31],
        -1.0,
        *state[31:38],
        1.0,
    )
    return MobileHarnessCandidate(
        scale=-1.0,
        action=tuple(float(value) for value in action),
        safe=True,
        score=-1.0,
        min_progress_ratio=0.0,
        max_cartesian_step_m=0.0,
        tool_command_corrections=sum(
            (action[index] >= 0.0) != (expert[index] >= 0.0)
            for index in (10, 18)
        ),
        reasons=(reason,),
    )


def _finite_vector(values: Iterable[float], length: int, name: str) -> tuple[float, ...]:
    result = tuple(float(value) for value in values)
    if len(result) != length:
        raise ValueError(f"{name} must contain {length} values")
    if any(not math.isfinite(value) for value in result):
        raise ValueError(f"{name} contains non-finite values")
    return result


def _clip(value: float, limit: float) -> float:
    return max(-limit, min(limit, value))


def _clip_norm(values: tuple[float, ...], limit: float) -> tuple[float, ...]:
    norm = math.sqrt(sum(value * value for value in values))
    if norm <= limit or norm <= 1e-12:
        return values
    return tuple(value * limit / norm for value in values)


def _normalize_quaternion(values: tuple[float, ...]) -> tuple[float, ...]:
    norm = math.sqrt(sum(value * value for value in values))
    if norm <= 1e-8:
        raise ValueError("quaternion norm is zero")
    return tuple(value / norm for value in values)


def _bounded_slerp(
    start: tuple[float, ...],
    end: tuple[float, ...],
    *,
    scale: float,
    max_angle_rad: float,
) -> tuple[float, ...]:
    left = _normalize_quaternion(start)
    right = _normalize_quaternion(end)
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    if dot < 0.0:
        right = tuple(-value for value in right)
        dot = -dot
    dot = max(-1.0, min(1.0, dot))
    angle = 2.0 * math.acos(dot)
    bounded_scale = scale * min(1.0, max_angle_rad / max(angle, 1e-12))
    mixed = tuple(
        (1.0 - bounded_scale) * a + bounded_scale * b
        for a, b in zip(left, right, strict=True)
    )
    return _normalize_quaternion(mixed)


def _progress_ratio(
    current: tuple[float, ...],
    expert: tuple[float, ...],
    candidate: tuple[float, ...],
) -> float:
    motion = tuple(target - value for target, value in zip(expert, current, strict=True))
    denominator = sum(value * value for value in motion)
    if denominator <= 1e-12:
        return 1.0
    candidate_motion = tuple(
        target - value for target, value in zip(candidate, current, strict=True)
    )
    return sum(
        value * direction
        for value, direction in zip(candidate_motion, motion, strict=True)
    ) / denominator
