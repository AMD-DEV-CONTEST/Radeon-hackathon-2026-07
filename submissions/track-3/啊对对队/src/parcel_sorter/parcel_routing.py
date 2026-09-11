"""Parcel classification and semantic destination routing."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ParcelRoute:
    category: str
    destination: str
    reason: str


def classify_and_route(
    *,
    profile_id: str,
    shape: str,
    handling_class: str,
    dimensions_m: tuple[float, float, float],
    mass_kg: float,
) -> ParcelRoute:
    """Classify from observable/catalog attributes, never rollout outcomes."""

    if len(dimensions_m) != 3 or any(value <= 0 for value in dimensions_m):
        raise ValueError("parcel dimensions must contain three positive values")
    if mass_kg <= 0:
        raise ValueError("parcel mass must be positive")
    normalized = profile_id.lower()
    if shape == "cylinder" or handling_class == "cradle_required":
        return ParcelRoute("cylindrical", "tube_rack", "cylinder geometry requires rack storage")
    if "electronics" in normalized:
        return ParcelRoute("fragile", "fragile_bin", "electronics profile receives low-impact handling")
    if max(dimensions_m) >= 0.45 or mass_kg >= 3.0:
        return ParcelRoute("oversize", "oversize_lane", "size or mass exceeds standard tote envelope")
    if min(dimensions_m) <= 0.04 or any(token in normalized for token in ("mail", "envelope")):
        return ParcelRoute("mailer", "mailer_bin", "thin mailer geometry")
    return ParcelRoute("carton", "carton_bin", "standard rigid carton")


def routing_task_text(profile_id: str, route: ParcelRoute) -> str:
    return (
        f"Classify {profile_id} as {route.category}, pick it safely, and deliver it "
        f"to {route.destination}."
    )
