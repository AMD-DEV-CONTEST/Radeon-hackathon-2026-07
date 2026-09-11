"""PI0.5 residual policy contract for contact-rich mobile parcel handling."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable

from .mobile_dataset import (
    MOBILE_ACTION_NAMES,
    MOBILE_STAGE_NAMES,
    MOBILE_STATE_NAMES,
)


PI05_FORCE_HISTORY_LENGTH = 6
PI05_GRASP_MODES = ("top_suction", "side_suction", "cooperative_cradle")
PI05_MAX_COOPERATIVE_DIFFERENTIAL_M = 0.005
PI05_BASE_AUTHORITY_M = {
    "pregrasp": 0.020,
    "grasp_approach": 0.010,
    "transport": 0.020,
}
PI05_ARM_AUTHORITY_M = {
    "pregrasp": 0.020,
    "grasp_approach": 0.010,
    "lift": 0.005,
    "transport": 0.010,
}
MOBILE_PI05_STATE_NAMES = (
    *MOBILE_STATE_NAMES,
    "left_cup_0_sealed",
    "left_cup_1_sealed",
    "left_cup_2_sealed",
    "parcel_shape_box",
    "parcel_shape_cylinder",
    "parcel_size_x_m",
    "parcel_size_y_m",
    "parcel_size_z_m",
    "parcel_mass_kg",
    "mode_top_suction",
    "mode_side_suction",
    "mode_cooperative_cradle",
    "retry_index",
    *(f"stage_{stage}" for stage in MOBILE_STAGE_NAMES),
    *(f"left_force_history_{index}_n" for index in range(PI05_FORCE_HISTORY_LENGTH)),
    *(f"right_force_history_{index}_n" for index in range(PI05_FORCE_HISTORY_LENGTH)),
    *(f"left_contact_anchor_{axis}_m" for axis in "xyz"),
    *(f"right_contact_anchor_{axis}_m" for axis in "xyz"),
)
MOBILE_PI05_RESIDUAL_ACTION_NAMES = (
    "base_residual_vx_m_s",
    "base_residual_vy_m_s",
    "base_residual_vyaw_rad_s",
    "left_contact_residual_dx_m",
    "left_contact_residual_dy_m",
    "left_contact_residual_dz_m",
    "right_contact_residual_dx_m",
    "right_contact_residual_dy_m",
    "right_contact_residual_dz_m",
    "mode_top_suction_logit",
    "mode_side_suction_logit",
    "mode_cooperative_cradle_logit",
    "suction_command_logit",
    "primitive_progress",
)
MOBILE_PI05_ABSOLUTE_STATE_NAMES = (
    *MOBILE_PI05_STATE_NAMES[:-6],
    *(f"current_left_tool_{axis}_m" for axis in "xyz"),
    *(f"current_right_tool_{axis}_m" for axis in "xyz"),
)
MOBILE_PI05_ABSOLUTE_ACTION_NAMES = (
    *MOBILE_ACTION_NAMES,
    "mode_top_suction_logit",
    "mode_side_suction_logit",
    "mode_cooperative_cradle_logit",
    "primitive_progress",
)
MOBILE_PI05_INCREMENTAL_ACTION_NAMES = (
    "base_vx",
    "base_vy",
    "base_vyaw",
    *(f"left_delta_{axis}_m" for axis in "xyz"),
    *(f"left_delta_rotation_vector_{axis}_rad" for axis in "xyz"),
    "left_tool_command",
    *(f"right_delta_{axis}_m" for axis in "xyz"),
    *(f"right_delta_rotation_vector_{axis}_rad" for axis in "xyz"),
    "right_tool_command",
    "mode_top_suction_logit",
    "mode_side_suction_logit",
    "mode_cooperative_cradle_logit",
    "primitive_progress",
)
PI05_ABSOLUTE_MODE_SLICE = slice(
    len(MOBILE_ACTION_NAMES), len(MOBILE_ACTION_NAMES) + 3
)
PI05_INCREMENTAL_MODE_SLICE = slice(17, 20)


@dataclass(frozen=True)
class PI05ResidualContext:
    sealed_cup_mask: tuple[bool, bool, bool]
    parcel_shape: str
    parcel_size_m: tuple[float, float, float]
    parcel_mass_kg: float
    grasp_mode: str
    retry_index: int
    stage: str
    left_force_history_n: tuple[float, ...]
    right_force_history_n: tuple[float, ...]
    left_contact_anchor_m: tuple[float, float, float]
    right_contact_anchor_m: tuple[float, float, float]
    grasp_mode_conditioned: bool = True


@dataclass(frozen=True)
class PI05ResidualProjection:
    absolute_action: tuple[float, ...]
    predicted_mode: str
    mode_logits: tuple[float, float, float]
    requested_suction: bool
    progress: float
    base_residual: tuple[float, float, float]
    left_contact_residual_m: tuple[float, float, float]
    right_contact_residual_m: tuple[float, float, float]
    arm_authority_m: float


@dataclass(frozen=True)
class PI05AbsoluteProjection:
    absolute_action: tuple[float, ...]
    predicted_mode: str
    mode_logits: tuple[float, float, float]
    requested_suction: bool
    progress: float


@dataclass(frozen=True)
class PI05RecoveryResidual:
    """Verified corrective label relative to a deliberately biased contact anchor."""

    left_contact_residual_m: tuple[float, float, float]
    right_contact_residual_m: tuple[float, float, float]
    arm_authority_m: float


@dataclass(frozen=True)
class PI05ModeConsensus:
    selected_mode: str
    vote_counts: tuple[int, int, int]
    mean_logits: tuple[float, float, float]
    consensus_fraction: float


def build_primitive_progress_targets(stages: Iterable[str]) -> tuple[float, ...]:
    """Return monotonic 0-to-1 targets for each contiguous primitive segment."""

    values = tuple(str(stage) for stage in stages)
    if any(stage not in MOBILE_STAGE_NAMES for stage in values):
        raise ValueError("progress stages contain an unsupported task stage")
    targets = [0.0] * len(values)
    start = 0
    while start < len(values):
        end = start + 1
        while end < len(values) and values[end] == values[start]:
            end += 1
        denominator = max(1, end - start - 1)
        for index in range(start, end):
            targets[index] = (index - start) / denominator if end - start > 1 else 1.0
        start = end
    return tuple(targets)


def build_pi05_observable_context_task(
    task: str,
    context: PI05ResidualContext,
) -> str:
    """Expose state ignored by LeRobot PI0.5 as mode-blind language context."""

    base = task.strip()
    if not base:
        raise ValueError("base task text must be non-empty")
    size = _finite_vector(context.parcel_size_m, 3, "parcel size")
    if context.parcel_shape not in {"box", "cylinder"}:
        raise ValueError("parcel_shape must be box or cylinder")
    if context.stage not in MOBILE_STAGE_NAMES:
        raise ValueError(f"unsupported task stage: {context.stage}")
    if context.retry_index < 0:
        raise ValueError("retry_index cannot be negative")
    if not math.isfinite(context.parcel_mass_kg) or context.parcel_mass_kg <= 0.0:
        raise ValueError("parcel mass must be finite and positive")
    marker = " Observable parcel context:"
    base = base.split(marker, 1)[0].rstrip()
    dimensions = " x ".join(f"{value:.4f}" for value in size)
    return (
        f"{base}{marker} shape {context.parcel_shape}; dimensions {dimensions} meters; "
        f"estimated mass {context.parcel_mass_kg:.3f} kilograms; current phase "
        f"{context.stage}; retry {context.retry_index}."
    )


def smooth_lift_residual_fraction(
    primitive_progress: float,
    vertical_speed_scale: float = 1.0,
) -> float:
    """Match lift-residual supervision to the physical smoothstep schedule."""

    if not math.isfinite(primitive_progress):
        raise ValueError("primitive progress must be finite")
    if not math.isfinite(vertical_speed_scale) or not 0.60 <= vertical_speed_scale <= 1.0:
        raise ValueError("vertical speed scale must be in [0.60, 1.0]")
    normalized = min(1.0, max(0.0, primitive_progress) * 1.5 * vertical_speed_scale)
    return normalized * normalized * (3.0 - 2.0 * normalized)


def select_pi05_mode_consensus(
    mode_logit_samples: Iterable[Iterable[float]],
) -> PI05ModeConsensus:
    """Aggregate stochastic PI0.5 mode samples without using an expert label."""

    samples = tuple(
        _finite_vector(values, len(PI05_GRASP_MODES), "mode logits")
        for values in mode_logit_samples
    )
    if not samples:
        raise ValueError("mode consensus requires at least one PI0.5 sample")
    votes = [0] * len(PI05_GRASP_MODES)
    for values in samples:
        votes[max(range(len(values)), key=values.__getitem__)] += 1
    mean_logits = tuple(
        sum(values[index] for values in samples) / len(samples)
        for index in range(len(PI05_GRASP_MODES))
    )
    selected_index = max(
        range(len(PI05_GRASP_MODES)),
        key=lambda index: (votes[index], mean_logits[index]),
    )
    return PI05ModeConsensus(
        selected_mode=PI05_GRASP_MODES[selected_index],
        vote_counts=tuple(votes),  # type: ignore[arg-type]
        mean_logits=mean_logits,  # type: ignore[arg-type]
        consensus_fraction=votes[selected_index] / len(samples),
    )


def build_pi05_recovery_residual(
    *,
    contact_offset_m: Iterable[float],
    contact_penetration_delta_m: float,
    approach_axis_world: Iterable[float],
    left_contact_offset_m: Iterable[float] | None = None,
    right_contact_offset_m: Iterable[float] | None = None,
    stage: str,
    grasp_mode: str,
) -> PI05RecoveryResidual:
    """Create a bounded residual label from a physically successful recovery.

    The lateral offset and penetration correction are both expressed in the
    world frame. Cooperative-cradle recovery is common-mode so the learned
    policy cannot shear a rigid parcel between the two end effectors.
    """

    if stage not in MOBILE_STAGE_NAMES:
        raise ValueError(f"unsupported task stage: {stage}")
    if grasp_mode not in PI05_GRASP_MODES:
        raise ValueError(f"unsupported grasp mode: {grasp_mode}")
    lateral = _finite_vector(contact_offset_m, 2, "contact offset")
    axis = _finite_vector(approach_axis_world, 3, "approach axis")
    axis_norm = math.sqrt(sum(value * value for value in axis))
    if axis_norm <= 1e-9:
        raise ValueError("approach axis must be non-zero")
    if not math.isfinite(contact_penetration_delta_m):
        raise ValueError("contact penetration delta must be finite")
    unit_axis = tuple(value / axis_norm for value in axis)
    raw = (
        lateral[0] + unit_axis[0] * contact_penetration_delta_m,
        lateral[1] + unit_axis[1] * contact_penetration_delta_m,
        unit_axis[2] * contact_penetration_delta_m,
    )
    authority = PI05_ARM_AUTHORITY_M.get(stage, 0.0)
    left_extra = (
        _finite_vector(left_contact_offset_m, 3, "left contact offset")
        if left_contact_offset_m is not None
        else (0.0, 0.0, 0.0)
    )
    left = _clip_norm(
        tuple(raw[index] + left_extra[index] for index in range(3)), authority
    )
    if grasp_mode == "cooperative_cradle":
        right_extra = (
            _finite_vector(right_contact_offset_m, 3, "right contact offset")
            if right_contact_offset_m is not None
            else (0.0, 0.0, 0.0)
        )
        right = _clip_norm(
            tuple(raw[index] + right_extra[index] for index in range(3)),
            authority,
        )
        if stage == "lift":
            left, right = _limit_cooperative_differential(left, right, authority)
    else:
        right = (0.0, 0.0, 0.0)
    return PI05RecoveryResidual(
        left_contact_residual_m=left,
        right_contact_residual_m=right,
        arm_authority_m=authority,
    )


def encode_pi05_state(
    legacy_state: Iterable[float],
    context: PI05ResidualContext,
) -> tuple[float, ...]:
    """Encode observable contact/task context without privileged parcel pose."""

    legacy = _finite_vector(legacy_state, len(MOBILE_STATE_NAMES), "legacy state")
    if context.parcel_shape not in {"box", "cylinder"}:
        raise ValueError("parcel_shape must be box or cylinder")
    if context.grasp_mode not in PI05_GRASP_MODES:
        raise ValueError(f"unsupported grasp mode: {context.grasp_mode}")
    if context.stage not in MOBILE_STAGE_NAMES:
        raise ValueError(f"unsupported task stage: {context.stage}")
    if context.retry_index < 0:
        raise ValueError("retry_index cannot be negative")
    size = _finite_vector(context.parcel_size_m, 3, "parcel size")
    if min(size) <= 0.0 or not math.isfinite(context.parcel_mass_kg) or context.parcel_mass_kg <= 0.0:
        raise ValueError("parcel size and mass must be finite and positive")
    left_anchor = _finite_vector(context.left_contact_anchor_m, 3, "left anchor")
    right_anchor = _finite_vector(context.right_contact_anchor_m, 3, "right anchor")
    left_history = _padded_force_history(context.left_force_history_n)
    right_history = _padded_force_history(context.right_force_history_n)
    shape_one_hot = tuple(float(context.parcel_shape == name) for name in ("box", "cylinder"))
    mode_one_hot = tuple(
        float(context.grasp_mode_conditioned and context.grasp_mode == name)
        for name in PI05_GRASP_MODES
    )
    stage_one_hot = tuple(float(context.stage == name) for name in MOBILE_STAGE_NAMES)
    encoded = (
        *legacy,
        *(float(value) for value in context.sealed_cup_mask),
        *shape_one_hot,
        *size,
        float(context.parcel_mass_kg),
        *mode_one_hot,
        float(context.retry_index),
        *stage_one_hot,
        *left_history,
        *right_history,
        *left_anchor,
        *right_anchor,
    )
    if len(encoded) != len(MOBILE_PI05_STATE_NAMES):
        raise RuntimeError("PI0.5 state contract length mismatch")
    return encoded


def encode_pi05_absolute_state(
    legacy_state: Iterable[float],
    context: PI05ResidualContext,
) -> tuple[float, ...]:
    """Encode observable state without action-derived contact targets."""

    legacy = _finite_vector(legacy_state, len(MOBILE_STATE_NAMES), "legacy state")
    encoded = list(encode_pi05_state(legacy, context))
    encoded[-6:-3] = legacy[24:27]
    encoded[-3:] = legacy[31:34]
    result = tuple(encoded)
    if len(result) != len(MOBILE_PI05_ABSOLUTE_STATE_NAMES):
        raise RuntimeError("PI0.5 absolute state contract length mismatch")
    return result


def decode_pi05_context(encoded_state: Iterable[float]) -> PI05ResidualContext:
    """Recover the explicit context fields from an encoded PI0.5 state."""

    values = _finite_vector(encoded_state, len(MOBILE_PI05_STATE_NAMES), "PI0.5 state")
    shape = ("box", "cylinder")[max(range(2), key=values[46:48].__getitem__)]
    mode = PI05_GRASP_MODES[max(range(3), key=values[52:55].__getitem__)]
    stage = MOBILE_STAGE_NAMES[max(range(len(MOBILE_STAGE_NAMES)), key=values[56:62].__getitem__)]
    return PI05ResidualContext(
        sealed_cup_mask=tuple(value >= 0.5 for value in values[43:46]),  # type: ignore[arg-type]
        parcel_shape=shape,
        parcel_size_m=values[48:51],  # type: ignore[arg-type]
        parcel_mass_kg=values[51],
        grasp_mode=mode,
        retry_index=max(0, int(round(values[55]))),
        stage=stage,
        left_force_history_n=values[62:68],
        right_force_history_n=values[68:74],
        left_contact_anchor_m=values[74:77],  # type: ignore[arg-type]
        right_contact_anchor_m=values[77:80],  # type: ignore[arg-type]
        grasp_mode_conditioned=any(value >= 0.5 for value in values[52:55]),
    )


def project_pi05_residual_action(
    residual_action: Iterable[float],
    expert_action: Iterable[float],
    *,
    stage: str,
    grasp_mode: str,
) -> PI05ResidualProjection:
    """Project a learned residual into the legacy 19-D executable action space."""

    residual = _finite_vector(
        residual_action,
        len(MOBILE_PI05_RESIDUAL_ACTION_NAMES),
        "PI0.5 residual action",
    )
    expert = _finite_vector(expert_action, 19, "expert action")
    if stage not in MOBILE_STAGE_NAMES:
        raise ValueError(f"unsupported task stage: {stage}")
    if grasp_mode not in PI05_GRASP_MODES:
        raise ValueError(f"unsupported grasp mode: {grasp_mode}")

    base_limit = PI05_BASE_AUTHORITY_M.get(stage, 0.0)
    arm_limit = PI05_ARM_AUTHORITY_M.get(stage, 0.0)
    base = _clip_norm(residual[:3], base_limit)
    left = _clip_norm(residual[3:6], arm_limit)
    right = _clip_norm(residual[6:9], arm_limit)
    if grasp_mode != "cooperative_cradle":
        right = (0.0, 0.0, 0.0)
    elif stage == "lift":
        left, right = _limit_cooperative_differential(left, right, arm_limit)
    if stage in {"place", "release"}:
        base = left = right = (0.0, 0.0, 0.0)

    mode_logits = residual[9:12]
    predicted_mode = PI05_GRASP_MODES[max(range(3), key=mode_logits.__getitem__)]
    absolute = (
        *(expert[index] + base[index] for index in range(3)),
        *(expert[3 + index] + left[index] for index in range(3)),
        *expert[6:11],
        *(expert[11 + index] + right[index] for index in range(3)),
        *expert[14:19],
    )
    return PI05ResidualProjection(
        absolute_action=tuple(float(value) for value in absolute),
        predicted_mode=predicted_mode,
        mode_logits=mode_logits,  # type: ignore[arg-type]
        requested_suction=residual[12] >= 0.0,
        progress=min(1.0, max(0.0, residual[13])),
        base_residual=base,
        left_contact_residual_m=left,
        right_contact_residual_m=right,
        arm_authority_m=arm_limit,
    )


def decode_pi05_absolute_action(
    policy_action: Iterable[float],
) -> PI05AbsoluteProjection:
    """Decode an expert-independent PI0.5 action and categorical mode output."""

    values = _finite_vector(
        policy_action,
        len(MOBILE_PI05_ABSOLUTE_ACTION_NAMES),
        "PI0.5 absolute action",
    )
    absolute = values[: len(MOBILE_ACTION_NAMES)]
    mode_logits = values[PI05_ABSOLUTE_MODE_SLICE]
    predicted_mode = PI05_GRASP_MODES[
        max(range(3), key=mode_logits.__getitem__)
    ]
    return PI05AbsoluteProjection(
        absolute_action=absolute,
        predicted_mode=predicted_mode,
        mode_logits=mode_logits,  # type: ignore[arg-type]
        requested_suction=absolute[10] >= 0.0,
        progress=min(1.0, max(0.0, values[-1])),
    )


def encode_pi05_incremental_action(
    absolute_action: Iterable[float],
    observable_state: Iterable[float],
) -> tuple[float, ...]:
    """Convert one 23-D absolute label to a DROID-style incremental SE(3) label."""

    action = _finite_vector(
        absolute_action,
        len(MOBILE_PI05_ABSOLUTE_ACTION_NAMES),
        "PI0.5 absolute action",
    )
    state = _finite_vector(
        observable_state,
        len(MOBILE_PI05_ABSOLUTE_STATE_NAMES),
        "PI0.5 observable state",
    )
    left_delta = tuple(action[3 + index] - state[74 + index] for index in range(3))
    right_delta = tuple(action[11 + index] - state[77 + index] for index in range(3))
    left_rotation = quaternion_delta_to_rotation_vector(state[27:31], action[6:10])
    right_rotation = quaternion_delta_to_rotation_vector(state[34:38], action[14:18])
    result = (
        *action[:3],
        *left_delta,
        *left_rotation,
        action[10],
        *right_delta,
        *right_rotation,
        action[18],
        *action[PI05_ABSOLUTE_MODE_SLICE],
        action[22],
    )
    if len(result) != len(MOBILE_PI05_INCREMENTAL_ACTION_NAMES):
        raise RuntimeError("PI0.5 incremental action contract length mismatch")
    return result


def decode_pi05_incremental_action(
    policy_action: Iterable[float],
    observable_state: Iterable[float],
) -> PI05AbsoluteProjection:
    """Decode a 21-D incremental SE(3) prediction into an executable absolute action."""

    values = _finite_vector(
        policy_action,
        len(MOBILE_PI05_INCREMENTAL_ACTION_NAMES),
        "PI0.5 incremental action",
    )
    state = _finite_vector(
        observable_state,
        len(MOBILE_PI05_ABSOLUTE_STATE_NAMES),
        "PI0.5 observable state",
    )
    left_position = tuple(state[74 + index] + values[3 + index] for index in range(3))
    right_position = tuple(state[77 + index] + values[10 + index] for index in range(3))
    left_quaternion = apply_rotation_vector_delta(state[27:31], values[6:9])
    right_quaternion = apply_rotation_vector_delta(state[34:38], values[13:16])
    absolute = (
        *values[:3],
        *left_position,
        *left_quaternion,
        values[9],
        *right_position,
        *right_quaternion,
        values[16],
    )
    mode_logits = values[PI05_INCREMENTAL_MODE_SLICE]
    predicted_mode = PI05_GRASP_MODES[
        max(range(3), key=mode_logits.__getitem__)
    ]
    return PI05AbsoluteProjection(
        absolute_action=absolute,
        predicted_mode=predicted_mode,
        mode_logits=mode_logits,  # type: ignore[arg-type]
        requested_suction=absolute[10] >= 0.0,
        progress=min(1.0, max(0.0, values[20])),
    )


def quaternion_delta_to_rotation_vector(
    current_quaternion: Iterable[float],
    target_quaternion: Iterable[float],
) -> tuple[float, float, float]:
    """Return the shortest world-frame rotation vector from current to target."""

    current = _normalized_quaternion(current_quaternion, "current quaternion")
    target = _normalized_quaternion(target_quaternion, "target quaternion")
    delta = _quaternion_multiply(target, _quaternion_conjugate(current))
    if delta[0] < 0.0:
        delta = tuple(-value for value in delta)  # type: ignore[assignment]
    vector_norm = math.sqrt(sum(value * value for value in delta[1:]))
    if vector_norm <= 1e-12:
        return (0.0, 0.0, 0.0)
    angle = 2.0 * math.atan2(vector_norm, max(0.0, delta[0]))
    return tuple(angle * value / vector_norm for value in delta[1:])  # type: ignore[return-value]


def apply_rotation_vector_delta(
    current_quaternion: Iterable[float],
    rotation_vector: Iterable[float],
) -> tuple[float, float, float, float]:
    """Apply a world-frame rotation-vector delta to a wxyz quaternion."""

    current = _normalized_quaternion(current_quaternion, "current quaternion")
    vector = _finite_vector(rotation_vector, 3, "rotation vector")
    angle = math.sqrt(sum(value * value for value in vector))
    if angle <= 1e-12:
        return current
    half = 0.5 * angle
    scale = math.sin(half) / angle
    delta = (math.cos(half), *(value * scale for value in vector))
    return _quaternion_multiply(delta, current)


def _normalized_quaternion(
    values: Iterable[float], name: str
) -> tuple[float, float, float, float]:
    quaternion = _finite_vector(values, 4, name)
    norm = math.sqrt(sum(value * value for value in quaternion))
    if norm <= 1e-12:
        raise ValueError(f"{name} must have non-zero norm")
    return tuple(value / norm for value in quaternion)  # type: ignore[return-value]


def _quaternion_conjugate(
    quaternion: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    return (quaternion[0], -quaternion[1], -quaternion[2], -quaternion[3])


def _quaternion_multiply(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    lw, lx, ly, lz = left
    rw, rx, ry, rz = right
    product = (
        lw * rw - lx * rx - ly * ry - lz * rz,
        lw * rx + lx * rw + ly * rz - lz * ry,
        lw * ry - lx * rz + ly * rw + lz * rx,
        lw * rz + lx * ry - ly * rx + lz * rw,
    )
    return _normalized_quaternion(product, "quaternion product")


def _padded_force_history(values: Iterable[float]) -> tuple[float, ...]:
    history = tuple(float(value) for value in values)[-PI05_FORCE_HISTORY_LENGTH:]
    if any(not math.isfinite(value) or value < 0.0 for value in history):
        raise ValueError("force history must contain finite non-negative values")
    return (0.0,) * (PI05_FORCE_HISTORY_LENGTH - len(history)) + history


def _finite_vector(values: Iterable[float], length: int, name: str) -> tuple[float, ...]:
    result = tuple(float(value) for value in values)
    if len(result) != length:
        raise ValueError(f"{name} must contain {length} values")
    if any(not math.isfinite(value) for value in result):
        raise ValueError(f"{name} contains non-finite values")
    return result


def _clip_norm(values: Iterable[float], limit: float) -> tuple[float, float, float]:
    vector = tuple(float(value) for value in values)
    norm = math.sqrt(sum(value * value for value in vector))
    if limit <= 0.0:
        return (0.0, 0.0, 0.0)
    if norm <= limit or norm <= 1e-12:
        return vector  # type: ignore[return-value]
    scale = limit / norm
    return tuple(value * scale for value in vector)  # type: ignore[return-value]


def _limit_cooperative_differential(
    left: tuple[float, float, float],
    right: tuple[float, float, float],
    authority: float,
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    common = tuple((left[index] + right[index]) / 2.0 for index in range(3))
    differential = _clip_norm(
        tuple(right[index] - left[index] for index in range(3)),
        PI05_MAX_COOPERATIVE_DIFFERENTIAL_M,
    )
    bounded_left = _clip_norm(
        tuple(common[index] - differential[index] / 2.0 for index in range(3)),
        authority,
    )
    bounded_right = _clip_norm(
        tuple(common[index] + differential[index] / 2.0 for index in range(3)),
        authority,
    )
    return bounded_left, bounded_right
