"""Immutable, versioned source-term contracts for 1-D transport.

Values are deliberately dimensioned source quantities.  This module never
converts a released mass to concentration: callers must provide the flow,
geometry, and dilution model at the transport boundary.
"""
from __future__ import annotations

from dataclasses import dataclass
import bisect
import math
from typing import Protocol


SOURCE_CONTRACT_VERSION = "source-term-1.0"

def _contract(version: str, unit: str) -> None:
    if version != SOURCE_CONTRACT_VERSION: raise ValueError("unsupported source contract version")
    if not isinstance(unit,str) or not unit.strip(): raise ValueError("quantity_unit must not be empty")


def _finite(name: str, value: float, *, nonnegative: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError(f"{name} must be a finite number")
    value = float(value)
    if nonnegative and value < 0:
        raise ValueError(f"{name} must be >= 0")
    return value


class SourceTerm(Protocol):
    version: str
    quantity_unit: str
    def value_at(self, time_s: float) -> float: ...
    def integrated_input(self, start_s: float, end_s: float) -> float: ...


def convolve_source(source: SourceTerm, impulse_response, time_s: float, *, steps: int = 512) -> float:
    """Numerically convolve a regular source with a causal impulse response.

    ``impulse_response(age_s)`` must be supplied by the transport model and
    must have units compatible with ``source``.  Pulse sources are represented
    by their normalized amount and should be handled analytically by the
    caller; no mass/concentration conversion is attempted here.
    """
    _finite("time_s", time_s, nonnegative=True)
    if isinstance(steps, bool) or not isinstance(steps, int) or steps < 1:
        raise ValueError("steps must be a positive integer")
    if time_s == 0.0:
        return 0.0
    dt = time_s / steps
    total = 0.0
    for i in range(steps + 1):
        age = time_s - i * dt
        weight = 0.5 if i in (0, steps) else 1.0
        total += weight * source.value_at(i * dt) * impulse_response(age)
    return total * dt


@dataclass(frozen=True)
class MaintainedBoundary:
    value: float
    quantity_unit: str = "concentration"
    version: str = SOURCE_CONTRACT_VERSION

    def __post_init__(self):
        _finite("value", self.value, nonnegative=True)
        _contract(self.version,self.quantity_unit)
    def value_at(self, time_s: float) -> float:
        _finite("time_s", time_s, nonnegative=True); return self.value
    def integrated_input(self, start_s: float, end_s: float) -> float:
        _finite("start_s", start_s, nonnegative=True); _finite("end_s", end_s, nonnegative=True)
        if end_s < start_s: raise ValueError("end_s must be >= start_s")
        return self.value * (end_s - start_s)


@dataclass(frozen=True)
class FiniteDurationBoundary:
    value: float
    duration_s: float
    quantity_unit: str = "concentration"
    version: str = SOURCE_CONTRACT_VERSION
    def __post_init__(self):
        _contract(self.version,self.quantity_unit); _finite("value", self.value, nonnegative=True); _finite("duration_s", self.duration_s, nonnegative=True)
    def value_at(self, time_s: float) -> float:
        _finite("time_s", time_s, nonnegative=True); return self.value if time_s <= self.duration_s else 0.0
    def integrated_input(self, start_s: float, end_s: float) -> float:
        _finite("start_s", start_s, nonnegative=True); _finite("end_s", end_s, nonnegative=True)
        if end_s < start_s: raise ValueError("end_s must be >= start_s")
        return self.value * max(0.0, min(end_s, self.duration_s) - start_s)


@dataclass(frozen=True)
class InstantaneousPulse:
    amount: float
    time_s: float = 0.0
    quantity_unit: str = "mass_per_area"
    version: str = SOURCE_CONTRACT_VERSION
    def __post_init__(self):
        _contract(self.version,self.quantity_unit); _finite("amount", self.amount, nonnegative=True); _finite("time_s", self.time_s, nonnegative=True)
    def value_at(self, time_s: float) -> float:
        _finite("time_s", time_s, nonnegative=True); return 0.0
    def integrated_input(self, start_s: float, end_s: float) -> float:
        _finite("start_s", start_s, nonnegative=True); _finite("end_s", end_s, nonnegative=True)
        if end_s < start_s: raise ValueError("end_s must be >= start_s")
        return self.amount if start_s <= self.time_s <= end_s else 0.0


@dataclass(frozen=True)
class ConstantRateRelease:
    rate: float
    duration_s: float | None = None
    quantity_unit: str = "mass_per_area_per_s"
    version: str = SOURCE_CONTRACT_VERSION
    def __post_init__(self):
        _contract(self.version,self.quantity_unit); _finite("rate", self.rate, nonnegative=True)
        if self.duration_s is not None: _finite("duration_s", self.duration_s, nonnegative=True)
    def value_at(self, time_s: float) -> float:
        _finite("time_s", time_s, nonnegative=True)
        return self.rate if self.duration_s is None or time_s <= self.duration_s else 0.0
    def integrated_input(self, start_s: float, end_s: float) -> float:
        _finite("start_s", start_s, nonnegative=True); _finite("end_s", end_s, nonnegative=True)
        if end_s < start_s: raise ValueError("end_s must be >= start_s")
        stop = end_s if self.duration_s is None else min(end_s, self.duration_s)
        return self.rate * max(0.0, stop - start_s)


@dataclass(frozen=True)
class PiecewiseLinearSeries:
    times_s: tuple[float, ...]
    values: tuple[float, ...]
    quantity_unit: str = "concentration"
    version: str = SOURCE_CONTRACT_VERSION
    def __post_init__(self):
        object.__setattr__(self, "times_s", tuple(self.times_s))
        object.__setattr__(self, "values", tuple(self.values))
        _contract(self.version,self.quantity_unit)
        if len(self.times_s) < 2 or len(self.times_s) != len(self.values): raise ValueError("times_s and values must have equal length >= 2")
        for i, t in enumerate(self.times_s): _finite(f"times_s[{i}]", t, nonnegative=True)
        for i, v in enumerate(self.values): _finite(f"values[{i}]", v, nonnegative=True)
        if any(b <= a for a, b in zip(self.times_s, self.times_s[1:])): raise ValueError("times_s must be strictly increasing")
    def value_at(self, time_s: float) -> float:
        _finite("time_s", time_s, nonnegative=True)
        if time_s <= self.times_s[0]: return self.values[0]
        if time_s >= self.times_s[-1]: return self.values[-1]
        i = bisect.bisect_right(self.times_s, time_s) - 1
        f = (time_s-self.times_s[i])/(self.times_s[i+1]-self.times_s[i])
        return self.values[i] + f*(self.values[i+1]-self.values[i])
    def integrated_input(self, start_s: float, end_s: float) -> float:
        _finite("start_s", start_s, nonnegative=True); _finite("end_s", end_s, nonnegative=True)
        if end_s < start_s: raise ValueError("end_s must be >= start_s")
        points = [start_s] + [t for t in self.times_s if start_s < t < end_s] + [end_s]
        return sum((self.value_at(a)+self.value_at(b))*(b-a)/2 for a,b in zip(points, points[1:]))
