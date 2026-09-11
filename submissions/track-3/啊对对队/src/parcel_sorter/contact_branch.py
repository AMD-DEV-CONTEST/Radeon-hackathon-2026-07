from __future__ import annotations

import math
from typing import Any, Mapping, Sequence


FINGER_NAMES = ("left_finger", "right_finger")


def summarize_contact_branch_events(
    events: Sequence[Mapping[str, Any]],
    force_abort_n: float,
) -> dict[str, Any]:
    """Summarize high-rate diagnostic events without changing control."""
    if not math.isfinite(force_abort_n) or force_abort_n <= 0.0:
        raise ValueError("force_abort_n must be finite and positive")
    if not events:
        return {
            "status": "no_samples",
            "sample_count": 0,
            "first_bilateral_support_loss": None,
            "first_force_abort": None,
            "peak_force_contact": None,
            "maximum_contact_penetration_m": 0.0,
            "finger_max_abs_velocity_m_s": [0.0, 0.0],
            "finger_max_abs_actual_force_n": [0.0, 0.0],
            "finger_max_abs_control_force_n": [0.0, 0.0],
            "contact_pairs": [],
        }

    _validate_event_order(events)

    first_bilateral_loss = None
    first_force_abort = None
    bilateral_support_seen = False
    peak_contact: dict[str, Any] | None = None
    maximum_contact_penetration_m = 0.0
    finger_velocity = [0.0, 0.0]
    finger_actual = [0.0, 0.0]
    finger_control = [0.0, 0.0]
    pair_aggregates: dict[str, dict[str, Any]] = {}

    for event in events:
        reference = _event_reference(event)
        bilateral = bool(event.get("bilateral_parcel_contact", False))
        if bilateral:
            bilateral_support_seen = True
        elif first_bilateral_loss is None and bilateral_support_seen:
            first_bilateral_loss = reference
        parcel_peak = _finite_float(
            event.get("peak_parcel_contact_force_n", 0.0),
            "peak_parcel_contact_force_n",
        )
        if first_force_abort is None and parcel_peak > force_abort_n:
            first_force_abort = {**reference, "force_n": parcel_peak}

        velocity = _finger_pair(event, "finger_dof_velocity_m_s")
        actual = _finger_pair(event, "finger_actual_force_n")
        control = _finger_pair(event, "finger_control_force_n")
        for index in range(2):
            finger_velocity[index] = max(
                finger_velocity[index],
                abs(velocity[index]),
            )
            finger_actual[index] = max(finger_actual[index], abs(actual[index]))
            finger_control[index] = max(finger_control[index], abs(control[index]))

        for contact in event.get("contacts", ()):
            penetration_m = _finite_float(
                contact.get("penetration_m", 0.0),
                "penetration_m",
            )
            maximum_contact_penetration_m = max(
                maximum_contact_penetration_m,
                penetration_m,
            )
            force = _finite_float(
                contact.get("force_magnitude_n", 0.0),
                "force_magnitude_n",
            )
            pair_key = contact_pair_key(contact)
            aggregate = pair_aggregates.setdefault(
                pair_key,
                {
                    "pair": pair_key,
                    "samples": 0,
                    "peak_force_n": 0.0,
                    "first": reference,
                    "last": reference,
                },
            )
            aggregate["samples"] += 1
            aggregate["peak_force_n"] = max(aggregate["peak_force_n"], force)
            aggregate["last"] = reference
            if peak_contact is None or force > peak_contact["force_magnitude_n"]:
                peak_contact = {
                    **reference,
                    "force_magnitude_n": force,
                    "pair": pair_key,
                    "geom_a": contact["geom_a"],
                    "geom_b": contact["geom_b"],
                }

    return {
        "status": "complete",
        "sample_count": len(events),
        "first_sample": _event_reference(events[0]),
        "last_sample": _event_reference(events[-1]),
        "first_bilateral_support_loss": first_bilateral_loss,
        "first_force_abort": first_force_abort,
        "peak_force_contact": peak_contact,
        "maximum_contact_penetration_m": maximum_contact_penetration_m,
        "finger_max_abs_velocity_m_s": finger_velocity,
        "finger_max_abs_actual_force_n": finger_actual,
        "finger_max_abs_control_force_n": finger_control,
        "contact_pairs": sorted(
            pair_aggregates.values(),
            key=lambda row: (-row["peak_force_n"], row["pair"]),
        ),
    }


def compare_contact_branch_events(
    reference_events: Sequence[Mapping[str, Any]],
    candidate_events: Sequence[Mapping[str, Any]],
    *,
    force_difference_n: float = 1.0,
    finger_position_difference_m: float = 0.0001,
    finger_velocity_difference_m_s: float = 0.01,
    finger_force_difference_n: float = 1.0,
) -> dict[str, Any]:
    """Find preregistered high-rate divergences between two aligned traces."""
    thresholds = (
        force_difference_n,
        finger_position_difference_m,
        finger_velocity_difference_m_s,
        finger_force_difference_n,
    )
    if any(not math.isfinite(value) or value <= 0.0 for value in thresholds):
        raise ValueError("comparison thresholds must be finite and positive")

    reference = _event_index(reference_events, "reference_events")
    candidate = _event_index(candidate_events, "candidate_events")
    common = sorted(set(reference) & set(candidate))
    missing_reference = sorted(set(candidate) - set(reference))
    missing_candidate = sorted(set(reference) - set(candidate))
    first_by_signal: dict[str, dict[str, Any] | None] = {
        "contact_signature": None,
        "contact_count": None,
        "bilateral_support": None,
        "parcel_peak_force": None,
        "finger_position": None,
        "finger_velocity": None,
        "finger_actual_force": None,
        "finger_control_force": None,
    }

    for key in common:
        left = reference[key]
        right = candidate[key]
        event_ref = {"control_step": key[0], "physics_substep": key[1]}
        _set_first_difference(
            first_by_signal,
            "contact_signature",
            _contact_signature(left) != _contact_signature(right),
            event_ref,
        )
        _set_first_difference(
            first_by_signal,
            "contact_count",
            int(left.get("parcel_contact_count", 0))
            != int(right.get("parcel_contact_count", 0)),
            event_ref,
        )
        _set_first_difference(
            first_by_signal,
            "bilateral_support",
            bool(left.get("bilateral_parcel_contact", False))
            != bool(right.get("bilateral_parcel_contact", False)),
            event_ref,
        )
        _set_numeric_difference(
            first_by_signal,
            "parcel_peak_force",
            event_ref,
            (
                _finite_float(left.get("peak_parcel_contact_force_n", 0.0), "force"),
            ),
            (
                _finite_float(right.get("peak_parcel_contact_force_n", 0.0), "force"),
            ),
            force_difference_n,
        )
        _set_numeric_difference(
            first_by_signal,
            "finger_position",
            event_ref,
            _finger_pair(left, "finger_dof_position_m"),
            _finger_pair(right, "finger_dof_position_m"),
            finger_position_difference_m,
        )
        _set_numeric_difference(
            first_by_signal,
            "finger_velocity",
            event_ref,
            _finger_pair(left, "finger_dof_velocity_m_s"),
            _finger_pair(right, "finger_dof_velocity_m_s"),
            finger_velocity_difference_m_s,
        )
        for signal, field in (
            ("finger_actual_force", "finger_actual_force_n"),
            ("finger_control_force", "finger_control_force_n"),
        ):
            _set_numeric_difference(
                first_by_signal,
                signal,
                event_ref,
                _finger_pair(left, field),
                _finger_pair(right, field),
                finger_force_difference_n,
            )

    observed = [
        {"signal": signal, **event}
        for signal, event in first_by_signal.items()
        if event is not None
    ]
    first_divergence = min(
        observed,
        key=lambda row: (row["control_step"], row["physics_substep"], row["signal"]),
        default=None,
    )
    return {
        "status": "complete" if common else "no_aligned_samples",
        "aligned_sample_count": len(common),
        "missing_reference_samples": [
            {"control_step": step, "physics_substep": substep}
            for step, substep in missing_reference
        ],
        "missing_candidate_samples": [
            {"control_step": step, "physics_substep": substep}
            for step, substep in missing_candidate
        ],
        "thresholds": {
            "force_difference_n": force_difference_n,
            "finger_position_difference_m": finger_position_difference_m,
            "finger_velocity_difference_m_s": finger_velocity_difference_m_s,
            "finger_force_difference_n": finger_force_difference_n,
        },
        "first_divergence": first_divergence,
        "first_divergence_by_signal": first_by_signal,
    }


def contact_pair_key(contact: Mapping[str, Any]) -> str:
    sides = []
    for field in ("geom_a", "geom_b"):
        geom = contact.get(field)
        if not isinstance(geom, Mapping):
            raise ValueError(f"{field} must be a mapping")
        sides.append(
            "/".join(
                str(geom.get(name, "unknown"))
                for name in ("entity_role", "link_name", "geom_role")
            )
        )
    return " <-> ".join(sorted(sides))


def _event_key(event: Mapping[str, Any]) -> tuple[int, int]:
    return int(event["control_step"]), int(event["physics_substep"])


def _event_index(
    events: Sequence[Mapping[str, Any]],
    name: str,
) -> dict[tuple[int, int], Mapping[str, Any]]:
    result: dict[tuple[int, int], Mapping[str, Any]] = {}
    for event in events:
        key = _event_key(event)
        if key in result:
            raise ValueError(f"{name} contains duplicate sample {key[0]}/{key[1]}")
        result[key] = event
    return result


def _validate_event_order(events: Sequence[Mapping[str, Any]]) -> None:
    previous: tuple[int, int] | None = None
    for event in events:
        key = _event_key(event)
        if previous is not None and key <= previous:
            raise ValueError("contact-branch events must be strictly ordered")
        previous = key


def _event_reference(event: Mapping[str, Any]) -> dict[str, int]:
    step, substep = _event_key(event)
    return {"control_step": step, "physics_substep": substep}


def _finite_float(value: Any, name: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"{name} must be finite")
    return parsed


def _finger_pair(event: Mapping[str, Any], field: str) -> tuple[float, float]:
    values = event.get(field)
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        raise ValueError(f"{field} must contain two values")
    parsed = tuple(_finite_float(value, field) for value in values)
    if len(parsed) != 2:
        raise ValueError(f"{field} must contain two values")
    return parsed  # type: ignore[return-value]


def _contact_signature(event: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(sorted(contact_pair_key(contact) for contact in event.get("contacts", ())))


def _set_first_difference(
    result: dict[str, dict[str, Any] | None],
    signal: str,
    different: bool,
    reference: Mapping[str, Any],
) -> None:
    if different and result[signal] is None:
        result[signal] = dict(reference)


def _set_numeric_difference(
    result: dict[str, dict[str, Any] | None],
    signal: str,
    reference: Mapping[str, Any],
    left: Sequence[float],
    right: Sequence[float],
    threshold: float,
) -> None:
    difference = max(abs(a - b) for a, b in zip(left, right, strict=True))
    if difference >= threshold and result[signal] is None:
        result[signal] = {**reference, "max_abs_difference": difference}
