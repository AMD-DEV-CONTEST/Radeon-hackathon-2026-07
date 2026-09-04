"""Stable JSON contracts between agents and deterministic physics tools."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping
from types import MappingProxyType
import hashlib
import json

from .transport import TransportParameters, simulate_transport


class ValidationError(ValueError):
    """Raised when an external scenario payload violates the contract."""


@dataclass(frozen=True)
class EvidenceRecord:
    """Immutable, provenance-bearing parameter evidence record."""
    parameter: str
    value: Any = None
    value_range: tuple[Any, ...] | None = None
    unit: str = ""
    source: str = ""
    location: str = ""
    hash: str = ""
    evidence_class: str = ""
    applicability: str = ""
    caveat: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.parameter, str) or not self.parameter.strip(): raise ValidationError("parameter is required")
        if (self.value is None) == (self.value_range is None): raise ValidationError("exactly one of value or value_range is required")
        if isinstance(self.value, float) and not math.isfinite(self.value): raise ValidationError("value must be finite")
        if self.value_range is not None:
            if not isinstance(self.value_range, tuple) or len(self.value_range) != 2: raise ValidationError("value_range must contain two values")
            if any(isinstance(x, bool) or not isinstance(x, (int,float)) or not math.isfinite(float(x)) for x in self.value_range) or self.value_range[0] > self.value_range[1]: raise ValidationError("value_range must be ordered finite numbers")
        for name in ("unit","source","location","hash","evidence_class","applicability"):
            if not isinstance(getattr(self,name), str) or not getattr(self,name).strip(): raise ValidationError(f"{name} is required")
        if not isinstance(self.caveat, str): raise ValidationError("caveat must be a string")
        if len(self.hash) != 64 or any(c not in "0123456789abcdef" for c in self.hash.lower()): raise ValidationError("hash must be a SHA-256 hex digest")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "EvidenceRecord":
        allowed = {"parameter", "value", "value_range", "unit", "source", "location", "hash", "class", "applicability", "caveat"}
        unknown = set(payload) - allowed
        if unknown: raise ValidationError(f"unknown evidence field: {sorted(unknown)[0]}")
        if not isinstance(payload.get("parameter"), str) or not payload["parameter"].strip(): raise ValidationError("parameter is required")
        has_value, has_range = "value" in payload, "value_range" in payload
        if has_value == has_range: raise ValidationError("exactly one of value or value_range is required")
        vr = tuple(payload["value_range"]) if has_range and isinstance(payload["value_range"], (list, tuple)) else None
        if has_range and (vr is None or len(vr) != 2): raise ValidationError("value_range must contain two values")
        for name in ("unit", "source", "location", "hash", "class", "applicability", "caveat"):
            if not isinstance(payload.get(name, ""), str): raise ValidationError(f"{name} must be a string")
        for name in ("unit", "source", "location", "hash", "class", "applicability"):
            if not payload.get(name, "").strip(): raise ValidationError(f"{name} is required")
        digest = payload.get("hash", "")
        if digest and (len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest.lower())): raise ValidationError("hash must be a SHA-256 hex digest")
        return cls(payload["parameter"], payload.get("value"), vr, payload.get("unit", ""), payload.get("source", ""), payload.get("location", ""), digest, payload.get("class", ""), payload.get("applicability", ""), payload.get("caveat", ""))

    def to_dict(self) -> dict[str, Any]:
        quantity = {"value_range": list(self.value_range)} if self.value_range is not None else {"value": self.value}
        return {"parameter": self.parameter, **quantity, "unit": self.unit, "source": self.source, "location": self.location, "hash": self.hash, "class": self.evidence_class, "applicability": self.applicability, "caveat": self.caveat}


@dataclass(frozen=True)
class ScenarioInput:
    scenario_id: str
    initial_concentration_bq_m3: float
    distance_m: float
    evaluation_times_s: tuple[float, ...]
    distribution_coefficient_m3_kg: float
    bulk_density_kg_m3: float = 1700.0
    porosity: float = 0.35
    groundwater_velocity_m_s: float = 1.0e-5
    dispersion_m2_s: float = 1.0e-5
    potassium_mg_l: float = 0.0
    competition_coefficient_l_mg: float = 0.01
    half_life_years: float = 30.018

    _REQUIRED = frozenset(
        {
            "scenario_id",
            "initial_concentration_bq_m3",
            "distance_m",
            "evaluation_times_s",
            "distribution_coefficient_m3_kg",
        }
    )
    _FIELDS = frozenset(
        {
            "scenario_id",
            "initial_concentration_bq_m3",
            "distance_m",
            "evaluation_times_s",
            "distribution_coefficient_m3_kg",
            "bulk_density_kg_m3",
            "porosity",
            "groundwater_velocity_m_s",
            "dispersion_m2_s",
            "potassium_mg_l",
            "competition_coefficient_l_mg",
            "half_life_years",
        }
    )

    def __post_init__(self) -> None:
        if not isinstance(self.scenario_id, str):
            raise ValidationError("scenario_id must be a string")
        if not self.scenario_id.strip():
            raise ValidationError("scenario_id must not be empty")
        if self.initial_concentration_bq_m3 <= 0:
            raise ValidationError("initial_concentration_bq_m3 must be > 0")
        if self.distance_m < 0:
            raise ValidationError("distance_m must be >= 0")
        if not self.evaluation_times_s:
            raise ValidationError("evaluation_times_s must not be empty")
        if any(time < 0 for time in self.evaluation_times_s):
            raise ValidationError("evaluation_times_s values must be >= 0")
        try:
            self.to_transport_parameters()
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ScenarioInput":
        unknown = [
            key for key in payload if not isinstance(key, str) or key not in cls._FIELDS
        ]
        if unknown:
            first = sorted(unknown, key=lambda value: str(value))[0]
            raise ValidationError(f"unknown field: {first!r}")
        missing = cls._REQUIRED - set(payload)
        if missing:
            raise ValidationError(f"missing field: {sorted(missing)[0]}")
        scenario_id = payload["scenario_id"]
        if not isinstance(scenario_id, str):
            raise ValidationError("scenario_id must be a string")
        times = payload["evaluation_times_s"]
        if not isinstance(times, list):
            raise ValidationError("evaluation_times_s must be a list of numbers")

        def number(name: str, value: Any) -> float:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValidationError(f"{name} must be a non-boolean number")
            converted = float(value)
            if not math.isfinite(converted):
                raise ValidationError(f"{name} must be finite")
            return converted

        times_tuple = tuple(number("evaluation_times_s value", value) for value in times)
        values = {
            "scenario_id": scenario_id,
            "initial_concentration_bq_m3": number(
                "initial_concentration_bq_m3", payload["initial_concentration_bq_m3"]
            ),
            "distance_m": number("distance_m", payload["distance_m"]),
            "evaluation_times_s": times_tuple,
            "distribution_coefficient_m3_kg": number(
                "distribution_coefficient_m3_kg",
                payload["distribution_coefficient_m3_kg"],
            ),
        }
        defaults = {
            "bulk_density_kg_m3": 1700.0,
            "porosity": 0.35,
            "groundwater_velocity_m_s": 1.0e-5,
            "dispersion_m2_s": 1.0e-5,
            "potassium_mg_l": 0.0,
            "competition_coefficient_l_mg": 0.01,
            "half_life_years": 30.018,
        }
        for name, default in defaults.items():
            values[name] = number(name, payload.get(name, default))
        return cls(**values)

    def to_transport_parameters(self) -> TransportParameters:
        return TransportParameters(
            initial_concentration_bq_m3=self.initial_concentration_bq_m3,
            distribution_coefficient_m3_kg=self.distribution_coefficient_m3_kg,
            bulk_density_kg_m3=self.bulk_density_kg_m3,
            porosity=self.porosity,
            groundwater_velocity_m_s=self.groundwater_velocity_m_s,
            dispersion_m2_s=self.dispersion_m2_s,
            potassium_mg_l=self.potassium_mg_l,
            competition_coefficient_l_mg=self.competition_coefficient_l_mg,
            half_life_years=self.half_life_years,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "initial_concentration_bq_m3": self.initial_concentration_bq_m3,
            "distance_m": self.distance_m,
            "evaluation_times_s": list(self.evaluation_times_s),
            "distribution_coefficient_m3_kg": self.distribution_coefficient_m3_kg,
            "bulk_density_kg_m3": self.bulk_density_kg_m3,
            "porosity": self.porosity,
            "groundwater_velocity_m_s": self.groundwater_velocity_m_s,
            "dispersion_m2_s": self.dispersion_m2_s,
            "potassium_mg_l": self.potassium_mg_l,
            "competition_coefficient_l_mg": self.competition_coefficient_l_mg,
            "half_life_years": self.half_life_years,
        }


@dataclass(frozen=True)
class TransportContractResult:
    scenario_id: str
    inputs: dict[str, Any]
    points: tuple[dict[str, float], ...]
    assumptions: tuple[str, ...]
    warnings: tuple[str, ...] = ()
    tool: str = "simulate_transport"
    model_version: str = "transport-prototype-0.3"

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "model_version": self.model_version,
            "scenario_id": self.scenario_id,
            "inputs": self.inputs,
            "points": [dict(point) for point in self.points],
            "assumptions": list(self.assumptions),
            "warnings": list(self.warnings),
        }


def run_transport_contract(payload: Mapping[str, Any]) -> TransportContractResult:
    """Validate a scenario and execute the deterministic transport tool."""
    scenario = ScenarioInput.from_dict(payload)
    params = scenario.to_transport_parameters()
    points = tuple(
        {
            "time_s": time_s,
            **simulate_transport(params, scenario.distance_m, time_s),
        }
        for time_s in scenario.evaluation_times_s
    )
    return TransportContractResult(
        scenario_id=scenario.scenario_id,
        inputs=scenario.to_dict(),
        points=points,
        assumptions=(
            "1-D homogeneous saturated semi-infinite medium",
            "constant concentration boundary at x=0; zero initial concentration for x>0",
            "reactive Ogata-Banks analytical solution",
            "groundwater_velocity_m_s is pore-water velocity",
            "empirical competitive adsorption",
        ),
        warnings=(
            "Prototype model; not validated for operational radiological assessment",
        ),
    )
