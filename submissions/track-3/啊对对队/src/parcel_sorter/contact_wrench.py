from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Any, Mapping, Sequence


Vector3 = tuple[float, float, float]


def _vector(values: Sequence[float], name: str) -> Vector3:
    if len(values) != 3:
        raise ValueError(f"{name} must contain three values")
    vector = tuple(float(value) for value in values)
    if any(not math.isfinite(value) for value in vector):
        raise ValueError(f"{name} must be finite")
    return vector  # type: ignore[return-value]


def _add(left: Vector3, right: Vector3) -> Vector3:
    return tuple(a + b for a, b in zip(left, right, strict=True))  # type: ignore[return-value]


def _subtract(left: Vector3, right: Vector3) -> Vector3:
    return tuple(a - b for a, b in zip(left, right, strict=True))  # type: ignore[return-value]


def _scale(vector: Vector3, scalar: float) -> Vector3:
    return tuple(value * scalar for value in vector)  # type: ignore[return-value]


def _dot(left: Vector3, right: Vector3) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True))


def _cross(left: Vector3, right: Vector3) -> Vector3:
    return (
        left[1] * right[2] - left[2] * right[1],
        left[2] * right[0] - left[0] * right[2],
        left[0] * right[1] - left[1] * right[0],
    )


def _norm(vector: Vector3) -> float:
    return math.sqrt(_dot(vector, vector))


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


@dataclass(frozen=True)
class ContactPoint:
    """One finger contact with force standardized as acting on the parcel."""

    finger_id: str
    position_world_m: Vector3
    force_on_parcel_world_n: Vector3
    normal_world: Vector3
    penetration_m: float = 0.0

    def validate(self) -> None:
        if not self.finger_id:
            raise ValueError("finger_id is required")
        _vector(self.position_world_m, "position_world_m")
        _vector(self.force_on_parcel_world_n, "force_on_parcel_world_n")
        normal = _vector(self.normal_world, "normal_world")
        if _norm(normal) <= 1e-12:
            raise ValueError("normal_world must be non-zero")
        if not math.isfinite(self.penetration_m):
            raise ValueError("penetration_m must be finite")


@dataclass(frozen=True)
class ContactWrenchConfig:
    parcel_mass_kg: float
    parcel_dimensions_m: Vector3
    friction_coefficient: float
    max_contact_force_n: float = 35.0
    transport_acceleration_m_s2: float = 1.5
    gravity_m_s2: float = 9.81
    minimum_active_force_n: float = 1e-4

    def validate(self) -> None:
        dimensions = _vector(self.parcel_dimensions_m, "parcel_dimensions_m")
        positive = (
            self.parcel_mass_kg,
            self.friction_coefficient,
            self.max_contact_force_n,
            self.transport_acceleration_m_s2,
            self.gravity_m_s2,
            self.minimum_active_force_n,
            *dimensions,
        )
        if any(not math.isfinite(value) or value <= 0.0 for value in positive):
            raise ValueError("contact-wrench configuration values must be finite and positive")


@dataclass(frozen=True)
class ContactWrenchQuality:
    finite: bool
    contact_count: int
    bilateral_contact: bool
    peak_contact_force_n: float
    total_normal_force_n: float
    total_tangential_force_n: float
    minimum_friction_margin_n: float
    friction_cone_score: float
    force_symmetry_score: float
    support_span_m: float
    support_span_score: float
    contact_center_offset_m: float
    contact_centering_score: float
    net_force_residual_n: float
    force_balance_score: float
    net_torque_residual_nm: float
    torque_balance_score: float
    disturbance_force_margin_n: float
    disturbance_force_score: float
    disturbance_torque_margin_nm: float
    disturbance_torque_score: float
    safety_score: float
    quality_score: float
    robust: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_contact_wrench(
    contacts: Sequence[ContactPoint],
    parcel_com_world_m: Sequence[float],
    config: ContactWrenchConfig,
) -> ContactWrenchQuality:
    """Evaluate measured contact support without changing the controller.

    The score is a diagnostic bottleneck score, not a learned success
    probability. Contact normals are oriented to agree with the measured force
    acting on the parcel, which makes the calculation independent of Genesis'
    geom-A/geom-B ordering.
    """
    config.validate()
    parcel_com = _vector(parcel_com_world_m, "parcel_com_world_m")
    parcel_diagonal = _norm(config.parcel_dimensions_m)
    characteristic_radius = 0.5 * parcel_diagonal
    for contact in contacts:
        contact.validate()

    active = [
        contact
        for contact in contacts
        if _norm(_vector(contact.force_on_parcel_world_n, "force"))
        >= config.minimum_active_force_n
    ]
    if not active:
        return ContactWrenchQuality(
            finite=True,
            contact_count=0,
            bilateral_contact=False,
            peak_contact_force_n=0.0,
            total_normal_force_n=0.0,
            total_tangential_force_n=0.0,
            minimum_friction_margin_n=-config.parcel_mass_kg
            * config.transport_acceleration_m_s2,
            friction_cone_score=0.0,
            force_symmetry_score=0.0,
            support_span_m=0.0,
            support_span_score=0.0,
            contact_center_offset_m=parcel_diagonal,
            contact_centering_score=0.0,
            net_force_residual_n=config.parcel_mass_kg * config.gravity_m_s2,
            force_balance_score=0.0,
            net_torque_residual_nm=0.0,
            torque_balance_score=0.0,
            disturbance_force_margin_n=-config.parcel_mass_kg
            * config.transport_acceleration_m_s2,
            disturbance_force_score=0.0,
            disturbance_torque_margin_nm=-config.parcel_mass_kg
            * config.transport_acceleration_m_s2
            * characteristic_radius,
            disturbance_torque_score=0.0,
            safety_score=1.0,
            quality_score=0.0,
            robust=False,
        )

    per_finger: dict[str, dict[str, Any]] = {}
    total_force: Vector3 = (0.0, 0.0, 0.0)
    total_torque: Vector3 = (0.0, 0.0, 0.0)
    peak_force = 0.0
    total_normal = 0.0
    total_tangential = 0.0
    positive_force_reserve = 0.0
    positive_torque_reserve = 0.0
    all_margins: list[float] = []

    for contact in active:
        force = _vector(contact.force_on_parcel_world_n, "force_on_parcel_world_n")
        normal = _vector(contact.normal_world, "normal_world")
        normal = _scale(normal, 1.0 / _norm(normal))
        if _dot(force, normal) < 0.0:
            normal = _scale(normal, -1.0)
        normal_force = max(0.0, _dot(force, normal))
        tangential_vector = _subtract(force, _scale(normal, normal_force))
        tangential_force = _norm(tangential_vector)
        friction_capacity = config.friction_coefficient * normal_force
        friction_margin = friction_capacity - tangential_force
        moment_arm = _subtract(
            _vector(contact.position_world_m, "position_world_m"),
            parcel_com,
        )
        torque = _cross(moment_arm, force)
        force_magnitude = _norm(force)

        aggregate = per_finger.setdefault(
            contact.finger_id,
            {
                "normal_force_n": 0.0,
                "tangential_force_n": 0.0,
                "friction_capacity_n": 0.0,
                "weighted_position": (0.0, 0.0, 0.0),
                "position_weight": 0.0,
            },
        )
        position_weight = max(normal_force, force_magnitude, config.minimum_active_force_n)
        aggregate["normal_force_n"] += normal_force
        aggregate["tangential_force_n"] += tangential_force
        aggregate["friction_capacity_n"] += friction_capacity
        aggregate["weighted_position"] = _add(
            aggregate["weighted_position"],
            _scale(contact.position_world_m, position_weight),
        )
        aggregate["position_weight"] += position_weight

        total_force = _add(total_force, force)
        total_torque = _add(total_torque, torque)
        peak_force = max(peak_force, force_magnitude)
        total_normal += normal_force
        total_tangential += tangential_force
        all_margins.append(friction_margin)
        positive_force_reserve += max(0.0, friction_margin)
        positive_torque_reserve += max(0.0, friction_margin) * _norm(moment_arm)

    required_fingers = ("left_finger", "right_finger")
    bilateral = all(finger in per_finger for finger in required_fingers)
    finger_margins = []
    finger_scores = []
    finger_centroids: list[Vector3] = []
    finger_normal_loads = []
    for finger in required_fingers:
        aggregate = per_finger.get(finger)
        if aggregate is None:
            finger_margins.append(-config.parcel_mass_kg * config.gravity_m_s2)
            finger_scores.append(0.0)
            continue
        margin = aggregate["friction_capacity_n"] - aggregate["tangential_force_n"]
        finger_margins.append(margin)
        finger_scores.append(
            _clamp01(margin / max(aggregate["friction_capacity_n"], 1e-12))
        )
        finger_centroids.append(
            _scale(
                aggregate["weighted_position"],
                1.0 / aggregate["position_weight"],
            )
        )
        finger_normal_loads.append(float(aggregate["normal_force_n"]))

    friction_score = min(finger_scores)
    symmetry_score = (
        _clamp01(
            1.0
            - abs(finger_normal_loads[0] - finger_normal_loads[1])
            / max(sum(finger_normal_loads), 1e-12)
        )
        if bilateral
        else 0.0
    )
    support_span = math.dist(*finger_centroids) if bilateral else 0.0
    support_score = _clamp01(support_span / min(config.parcel_dimensions_m))
    if bilateral:
        contact_center = _scale(_add(*finger_centroids), 0.5)
        center_offset = math.dist(contact_center, parcel_com)
        centering_score = _clamp01(1.0 - center_offset / characteristic_radius)
    else:
        center_offset = parcel_diagonal
        centering_score = 0.0

    gravity_force: Vector3 = (0.0, 0.0, -config.parcel_mass_kg * config.gravity_m_s2)
    net_force = _add(total_force, gravity_force)
    net_force_residual = _norm(net_force)
    force_scale = config.parcel_mass_kg * (
        config.gravity_m_s2 + config.transport_acceleration_m_s2
    )
    force_balance_score = _clamp01(1.0 - net_force_residual / force_scale)
    net_torque_residual = _norm(total_torque)
    torque_scale = force_scale * characteristic_radius
    torque_balance_score = _clamp01(1.0 - net_torque_residual / torque_scale)

    disturbance_force_demand = (
        config.parcel_mass_kg * config.transport_acceleration_m_s2
    )
    disturbance_force_margin = positive_force_reserve - disturbance_force_demand
    disturbance_force_score = _clamp01(
        positive_force_reserve / disturbance_force_demand
    )
    disturbance_torque_demand = disturbance_force_demand * characteristic_radius
    disturbance_torque_margin = positive_torque_reserve - disturbance_torque_demand
    disturbance_torque_score = _clamp01(
        positive_torque_reserve / disturbance_torque_demand
    )
    safety_score = 1.0 if peak_force <= config.max_contact_force_n else 0.0

    components = (
        friction_score,
        symmetry_score,
        support_score,
        centering_score,
        force_balance_score,
        torque_balance_score,
        disturbance_force_score,
        disturbance_torque_score,
    )
    quality_score = 0.0
    if bilateral and safety_score > 0.0 and all(value > 0.0 for value in components):
        quality_score = math.exp(
            sum(math.log(value) for value in components) / len(components)
        )
    quality_score = _clamp01(quality_score)
    minimum_margin = min(finger_margins)
    robust = (
        bilateral
        and safety_score > 0.0
        and minimum_margin >= 0.0
        and disturbance_force_margin >= 0.0
        and disturbance_torque_margin >= 0.0
    )
    finite_values = (
        peak_force,
        total_normal,
        total_tangential,
        minimum_margin,
        support_span,
        center_offset,
        net_force_residual,
        net_torque_residual,
        disturbance_force_margin,
        disturbance_torque_margin,
        quality_score,
    )
    finite = all(math.isfinite(value) for value in finite_values)
    if not finite:
        raise ValueError("contact-wrench calculation produced a non-finite value")

    return ContactWrenchQuality(
        finite=finite,
        contact_count=len(active),
        bilateral_contact=bilateral,
        peak_contact_force_n=peak_force,
        total_normal_force_n=total_normal,
        total_tangential_force_n=total_tangential,
        minimum_friction_margin_n=minimum_margin,
        friction_cone_score=friction_score,
        force_symmetry_score=symmetry_score,
        support_span_m=support_span,
        support_span_score=support_score,
        contact_center_offset_m=center_offset,
        contact_centering_score=centering_score,
        net_force_residual_n=net_force_residual,
        force_balance_score=force_balance_score,
        net_torque_residual_nm=net_torque_residual,
        torque_balance_score=torque_balance_score,
        disturbance_force_margin_n=disturbance_force_margin,
        disturbance_force_score=disturbance_force_score,
        disturbance_torque_margin_nm=disturbance_torque_margin,
        disturbance_torque_score=disturbance_torque_score,
        safety_score=safety_score,
        quality_score=quality_score,
        robust=robust,
    )


def evaluate_contact_wrench_torch(
    positions_world_m: Any,
    forces_on_parcel_world_n: Any,
    normals_world: Any,
    finger_indices: Any,
    parcel_com_world_m: Any,
    config: ContactWrenchConfig,
    torch: Any,
) -> ContactWrenchQuality:
    """Vectorized equivalent of :func:`evaluate_contact_wrench` for ROCm.

    Finger index 0 denotes ``left_finger`` and index 1 denotes
    ``right_finger``. All mechanics remain on the input device; the final
    scalar vector is transferred to the host once for JSON telemetry.
    """
    config.validate()
    count = int(positions_world_m.shape[0])
    expected_vectors = (count, 3)
    if tuple(positions_world_m.shape) != expected_vectors:
        raise ValueError("positions_world_m must have shape (N, 3)")
    if tuple(forces_on_parcel_world_n.shape) != expected_vectors:
        raise ValueError("forces_on_parcel_world_n must have shape (N, 3)")
    if tuple(normals_world.shape) != expected_vectors:
        raise ValueError("normals_world must have shape (N, 3)")
    if tuple(finger_indices.shape) != (count,):
        raise ValueError("finger_indices must have shape (N,)")
    if tuple(parcel_com_world_m.shape) != (3,):
        raise ValueError("parcel_com_world_m must have shape (3,)")
    if count == 0:
        return evaluate_contact_wrench((), (0.0, 0.0, 0.0), config)

    dtype = forces_on_parcel_world_n.dtype
    device = forces_on_parcel_world_n.device
    scalar = lambda value: torch.as_tensor(value, dtype=dtype, device=device)
    zero = scalar(0.0)
    one = scalar(1.0)
    epsilon = scalar(1e-12)

    normal_norm = torch.linalg.vector_norm(normals_world, dim=-1, keepdim=True)
    normals = normals_world / torch.clamp(normal_norm, min=epsilon)
    signed_normal_force = torch.sum(forces_on_parcel_world_n * normals, dim=-1)
    normals = torch.where(
        (signed_normal_force < 0.0).unsqueeze(-1),
        -normals,
        normals,
    )
    normal_force = torch.clamp(
        torch.sum(forces_on_parcel_world_n * normals, dim=-1), min=0.0
    )
    tangential_vectors = forces_on_parcel_world_n - normals * normal_force.unsqueeze(-1)
    tangential_force = torch.linalg.vector_norm(tangential_vectors, dim=-1)
    force_magnitude = torch.linalg.vector_norm(forces_on_parcel_world_n, dim=-1)
    friction_capacity = normal_force * config.friction_coefficient
    contact_margin = friction_capacity - tangential_force
    moment_arms = positions_world_m - parcel_com_world_m.unsqueeze(0)
    contact_torque = torch.linalg.cross(
        moment_arms,
        forces_on_parcel_world_n,
        dim=-1,
    )

    finger_presence = []
    finger_normal = []
    finger_tangential = []
    finger_capacity = []
    finger_centroids = []
    for finger_index in (0, 1):
        mask = finger_indices == finger_index
        mask_float = mask.to(dtype=dtype)
        presence = torch.any(mask)
        weights = torch.maximum(
            torch.maximum(normal_force, force_magnitude),
            scalar(config.minimum_active_force_n),
        ) * mask_float
        weight_sum = torch.sum(weights)
        finger_presence.append(presence)
        finger_normal.append(torch.sum(normal_force * mask_float))
        finger_tangential.append(torch.sum(tangential_force * mask_float))
        finger_capacity.append(torch.sum(friction_capacity * mask_float))
        finger_centroids.append(
            torch.sum(positions_world_m * weights.unsqueeze(-1), dim=0)
            / torch.clamp(weight_sum, min=epsilon)
        )

    presence = torch.stack(finger_presence)
    bilateral = torch.all(presence)
    finger_normal_tensor = torch.stack(finger_normal)
    finger_capacity_tensor = torch.stack(finger_capacity)
    finger_margin = finger_capacity_tensor - torch.stack(finger_tangential)
    missing_margin = scalar(-config.parcel_mass_kg * config.gravity_m_s2)
    finger_margin = torch.where(presence, finger_margin, missing_margin)
    finger_score = torch.where(
        presence,
        torch.clamp(
            finger_margin / torch.clamp(finger_capacity_tensor, min=epsilon),
            min=0.0,
            max=1.0,
        ),
        zero,
    )
    friction_score = torch.min(finger_score)
    symmetry_score = torch.where(
        bilateral,
        torch.clamp(
            one
            - torch.abs(finger_normal_tensor[0] - finger_normal_tensor[1])
            / torch.clamp(torch.sum(finger_normal_tensor), min=epsilon),
            min=0.0,
            max=1.0,
        ),
        zero,
    )

    dimensions = torch.as_tensor(
        config.parcel_dimensions_m,
        dtype=dtype,
        device=device,
    )
    parcel_diagonal = torch.linalg.vector_norm(dimensions)
    characteristic_radius = parcel_diagonal * 0.5
    centroids = torch.stack(finger_centroids)
    support_span = torch.where(
        bilateral,
        torch.linalg.vector_norm(centroids[0] - centroids[1]),
        zero,
    )
    support_score = torch.clamp(support_span / torch.min(dimensions), 0.0, 1.0)
    contact_center = torch.mean(centroids, dim=0)
    center_offset = torch.where(
        bilateral,
        torch.linalg.vector_norm(contact_center - parcel_com_world_m),
        parcel_diagonal,
    )
    centering_score = torch.where(
        bilateral,
        torch.clamp(one - center_offset / characteristic_radius, 0.0, 1.0),
        zero,
    )

    total_force = torch.sum(forces_on_parcel_world_n, dim=0)
    gravity_force = torch.stack(
        (
            zero,
            zero,
            scalar(-config.parcel_mass_kg * config.gravity_m_s2),
        )
    )
    net_force_residual = torch.linalg.vector_norm(total_force + gravity_force)
    force_scale = scalar(
        config.parcel_mass_kg
        * (config.gravity_m_s2 + config.transport_acceleration_m_s2)
    )
    force_balance_score = torch.clamp(one - net_force_residual / force_scale, 0.0, 1.0)
    net_torque_residual = torch.linalg.vector_norm(torch.sum(contact_torque, dim=0))
    torque_scale = force_scale * characteristic_radius
    torque_balance_score = torch.clamp(
        one - net_torque_residual / torque_scale, 0.0, 1.0
    )

    positive_force_reserve = torch.sum(torch.clamp(contact_margin, min=0.0))
    positive_torque_reserve = torch.sum(
        torch.clamp(contact_margin, min=0.0)
        * torch.linalg.vector_norm(moment_arms, dim=-1)
    )
    disturbance_force_demand = scalar(
        config.parcel_mass_kg * config.transport_acceleration_m_s2
    )
    disturbance_force_margin = positive_force_reserve - disturbance_force_demand
    disturbance_force_score = torch.clamp(
        positive_force_reserve / disturbance_force_demand, 0.0, 1.0
    )
    disturbance_torque_demand = disturbance_force_demand * characteristic_radius
    disturbance_torque_margin = positive_torque_reserve - disturbance_torque_demand
    disturbance_torque_score = torch.clamp(
        positive_torque_reserve / disturbance_torque_demand, 0.0, 1.0
    )
    safety_score = (torch.max(force_magnitude) <= config.max_contact_force_n).to(dtype)

    components = torch.stack(
        (
            friction_score,
            symmetry_score,
            support_score,
            centering_score,
            force_balance_score,
            torque_balance_score,
            disturbance_force_score,
            disturbance_torque_score,
        )
    )
    positive_components = torch.all(components > 0.0)
    geometric_mean = torch.pow(torch.clamp(torch.prod(components), min=0.0), 1.0 / 8.0)
    quality_score = torch.where(
        bilateral & (safety_score > 0.0) & positive_components,
        geometric_mean,
        zero,
    )
    minimum_margin = torch.min(finger_margin)
    robust = (
        bilateral
        & (safety_score > 0.0)
        & (minimum_margin >= 0.0)
        & (disturbance_force_margin >= 0.0)
        & (disturbance_torque_margin >= 0.0)
    )
    finite = torch.all(
        torch.isfinite(
            torch.stack(
                (
                    torch.max(force_magnitude),
                    torch.sum(normal_force),
                    torch.sum(tangential_force),
                    minimum_margin,
                    support_span,
                    center_offset,
                    net_force_residual,
                    net_torque_residual,
                    disturbance_force_margin,
                    disturbance_torque_margin,
                    quality_score,
                )
            )
        )
    )
    packed = torch.stack(
        (
            finite.to(dtype),
            bilateral.to(dtype),
            torch.max(force_magnitude),
            torch.sum(normal_force),
            torch.sum(tangential_force),
            minimum_margin,
            friction_score,
            symmetry_score,
            support_span,
            support_score,
            center_offset,
            centering_score,
            net_force_residual,
            force_balance_score,
            net_torque_residual,
            torque_balance_score,
            disturbance_force_margin,
            disturbance_force_score,
            disturbance_torque_margin,
            disturbance_torque_score,
            safety_score,
            torch.clamp(quality_score, 0.0, 1.0),
            robust.to(dtype),
        )
    ).detach().cpu().tolist()
    if not bool(round(packed[0])):
        raise ValueError("contact-wrench calculation produced a non-finite value")
    return ContactWrenchQuality(
        finite=True,
        contact_count=count,
        bilateral_contact=bool(round(packed[1])),
        peak_contact_force_n=float(packed[2]),
        total_normal_force_n=float(packed[3]),
        total_tangential_force_n=float(packed[4]),
        minimum_friction_margin_n=float(packed[5]),
        friction_cone_score=float(packed[6]),
        force_symmetry_score=float(packed[7]),
        support_span_m=float(packed[8]),
        support_span_score=float(packed[9]),
        contact_center_offset_m=float(packed[10]),
        contact_centering_score=float(packed[11]),
        net_force_residual_n=float(packed[12]),
        force_balance_score=float(packed[13]),
        net_torque_residual_nm=float(packed[14]),
        torque_balance_score=float(packed[15]),
        disturbance_force_margin_n=float(packed[16]),
        disturbance_force_score=float(packed[17]),
        disturbance_torque_margin_nm=float(packed[18]),
        disturbance_torque_score=float(packed[19]),
        safety_score=float(packed[20]),
        quality_score=float(packed[21]),
        robust=bool(round(packed[22])),
    )


def _window_summary(events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not events:
        return {"samples": 0, "available": False}
    quality = [float(event["quality_score"]) for event in events]
    return {
        "samples": len(events),
        "available": True,
        "bilateral_fraction": sum(
            bool(event["bilateral_contact"]) for event in events
        )
        / len(events),
        "robust_fraction": sum(bool(event["robust"]) for event in events)
        / len(events),
        "quality_score_min": min(quality),
        "quality_score_mean": sum(quality) / len(quality),
        "quality_score_final": quality[-1],
        "minimum_friction_margin_n": min(
            float(event["minimum_friction_margin_n"]) for event in events
        ),
        "minimum_disturbance_force_margin_n": min(
            float(event["disturbance_force_margin_n"]) for event in events
        ),
        "minimum_disturbance_torque_margin_nm": min(
            float(event["disturbance_torque_margin_nm"]) for event in events
        ),
        "maximum_contact_center_offset_m": max(
            float(event["contact_center_offset_m"])
            for event in events
            if math.isfinite(float(event["contact_center_offset_m"]))
        ),
    }


def summarize_contact_wrench_events(
    events: Sequence[Mapping[str, Any]],
    *,
    predictive_window_samples: int = 24,
    minimum_loaded_lift_m: float = 0.005,
) -> dict[str, Any]:
    """Summarize fixed pre-lift and early-loaded windows without outcome leakage."""
    if predictive_window_samples < 1:
        raise ValueError("predictive_window_samples must be positive")
    if not math.isfinite(minimum_loaded_lift_m) or minimum_loaded_lift_m < 0.0:
        raise ValueError("minimum_loaded_lift_m must be finite and non-negative")
    if not events:
        return {
            "status": "no_telemetry",
            "predictive_window_samples": predictive_window_samples,
            "minimum_loaded_lift_m": minimum_loaded_lift_m,
            "prelift_settle": _window_summary(()),
            "early_loaded": _window_summary(()),
        }

    loaded_index = next(
        (
            index
            for index, event in enumerate(events)
            if bool(event["bilateral_contact"])
            and float(event["parcel_lift_m"]) >= minimum_loaded_lift_m
            and str(event["command"]) in {"move_lift", "move_drop"}
        ),
        None,
    )
    if loaded_index is None:
        prelift = tuple(events[-predictive_window_samples:])
        loaded: tuple[Mapping[str, Any], ...] = ()
        status = "no_early_loaded_window"
    else:
        prelift = tuple(
            event
            for event in events[max(0, loaded_index - predictive_window_samples) : loaded_index]
            if bool(event["bilateral_contact"])
        )
        loaded = tuple(events[loaded_index : loaded_index + predictive_window_samples])
        status = (
            "complete"
            if len(loaded) == predictive_window_samples
            else "truncated_early_loaded_window"
        )
    return {
        "status": status,
        "predictive_window_samples": predictive_window_samples,
        "minimum_loaded_lift_m": minimum_loaded_lift_m,
        "first_early_loaded_event_index": loaded_index,
        "prelift_settle": _window_summary(prelift),
        "early_loaded": _window_summary(loaded),
    }
