"""Auditable 1-D Cs-137 transport screening with K+ competition.

The concentration model is the reactive Ogata--Banks solution for a constant
boundary concentration on a semi-infinite, homogeneous, saturated domain.
It is a research/demo screening model, not a safety-authorized or calibrated
radiological assessment code. Units are SI unless explicitly stated.
"""

from dataclasses import dataclass
import math


SECONDS_PER_YEAR = 365.25 * 24 * 3600
_LOG_SQRT_PI = 0.5 * math.log(math.pi)


@dataclass(frozen=True)
class TransportParameters:
    initial_concentration_bq_m3: float
    distribution_coefficient_m3_kg: float
    bulk_density_kg_m3: float = 1700.0
    porosity: float = 0.35
    groundwater_velocity_m_s: float = 1.0e-5
    dispersion_m2_s: float = 1.0e-5
    potassium_mg_l: float = 0.0
    competition_coefficient_l_mg: float = 0.01
    half_life_years: float = 30.018

    def __post_init__(self) -> None:
        values = {
            "initial_concentration_bq_m3": self.initial_concentration_bq_m3,
            "distribution_coefficient_m3_kg": self.distribution_coefficient_m3_kg,
            "bulk_density_kg_m3": self.bulk_density_kg_m3,
            "porosity": self.porosity,
            "groundwater_velocity_m_s": self.groundwater_velocity_m_s,
            "dispersion_m2_s": self.dispersion_m2_s,
            "potassium_mg_l": self.potassium_mg_l,
            "competition_coefficient_l_mg": self.competition_coefficient_l_mg,
            "half_life_years": self.half_life_years,
        }
        if any(not math.isfinite(value) for value in values.values()):
            raise ValueError("physical parameters must be finite")
        positive = {
            "initial_concentration_bq_m3": self.initial_concentration_bq_m3,
            "bulk_density_kg_m3": self.bulk_density_kg_m3,
            "porosity": self.porosity,
            "groundwater_velocity_m_s": self.groundwater_velocity_m_s,
            "dispersion_m2_s": self.dispersion_m2_s,
            "half_life_years": self.half_life_years,
        }
        if any(value <= 0 for value in positive.values()):
            raise ValueError("physical positive parameters must be > 0")
        if not 0 < self.porosity <= 1:
            raise ValueError("porosity must be in (0, 1]")
        if self.distribution_coefficient_m3_kg < 0:
            raise ValueError("distribution coefficient must be >= 0")
        if self.potassium_mg_l < 0 or self.competition_coefficient_l_mg < 0:
            raise ValueError("potassium and competition coefficient must be >= 0")

    @property
    def effective_distribution_coefficient_m3_kg(self) -> float:
        """Empirical competitive-adsorption reduction for sensitivity screening."""
        return self.distribution_coefficient_m3_kg / (
            1.0 + self.competition_coefficient_l_mg * self.potassium_mg_l
        )

    @property
    def retardation_factor(self) -> float:
        return 1.0 + (
            self.bulk_density_kg_m3
            / self.porosity
            * self.effective_distribution_coefficient_m3_kg
        )

    @property
    def decay_constant_s(self) -> float:
        return math.log(2.0) / (self.half_life_years * SECONDS_PER_YEAR)


def _scaled_erfc(log_scale: float, argument: float) -> float:
    """Return ``exp(log_scale) * erfc(argument)`` without overflow.

    The second Ogata--Banks term may combine a very large exponential with a
    very small complementary error function. For positive arguments above 8,
    a log-domain asymptotic expansion avoids the indeterminate ``inf * 0``.
    """
    if argument > 8.0:
        inverse_square = 1.0 / (argument * argument)
        correction = (
            1.0
            - 0.5 * inverse_square
            + 0.75 * inverse_square**2
            - 1.875 * inverse_square**3
        )
        log_value = (
            log_scale
            - argument * argument
            - math.log(argument)
            - _LOG_SQRT_PI
            + math.log(correction)
        )
    else:
        erfc_value = math.erfc(argument)
        if erfc_value == 0.0:
            return 0.0
        log_value = log_scale + math.log(erfc_value)

    if log_value < -745.0:
        return 0.0
    if log_value > 709.0:
        raise OverflowError("scaled erfc exceeded floating-point range")
    return math.exp(log_value)


def simulate_transport(
    params: TransportParameters,
    distance_m: float,
    time_s: float,
) -> dict[str, float]:
    """Evaluate the reactive Ogata--Banks constant-source solution.

    Governing equation on ``x >= 0``::

        R dC/dt = D d2C/dx2 - v dC/dx - lambda R C

    with ``C(x, 0) = 0`` for ``x > 0``, ``C(0, t) = C0`` for ``t >= 0`` and
    ``C(infinity, t) = 0``. ``v`` is pore-water velocity, ``D`` is the
    longitudinal hydrodynamic-dispersion coefficient and equilibrium linear
    sorption is represented by ``R``. Radioactive decay acts in dissolved and
    sorbed phases at the same physical decay constant.

    The solution is bounded by the imposed source concentration. It omits
    finite source duration/geometry, heterogeneity, nonlinear or kinetic
    sorption and preferential flow.
    """
    if not math.isfinite(distance_m) or not math.isfinite(time_s):
        raise ValueError("distance and time must be finite")
    if distance_m < 0 or time_s < 0:
        raise ValueError("distance and time must be >= 0")

    retardation = params.retardation_factor
    velocity = params.groundwater_velocity_m_s
    dispersion = params.dispersion_m2_s
    decay = params.decay_constant_s
    travel_time_s = distance_m * retardation / velocity
    decay_factor = math.exp(-decay * time_s)
    decay_velocity = math.sqrt(velocity**2 + 4.0 * decay * retardation * dispersion)
    steady_state_fraction = math.exp(
        (velocity - decay_velocity) * distance_m / (2.0 * dispersion)
    )

    if distance_m == 0.0:
        concentration = params.initial_concentration_bq_m3
    elif time_s == 0.0:
        concentration = 0.0
    else:
        denominator = 2.0 * math.sqrt(dispersion * retardation * time_s)
        first = _scaled_erfc(
            (velocity - decay_velocity) * distance_m / (2.0 * dispersion),
            (retardation * distance_m - decay_velocity * time_s) / denominator,
        )
        second = _scaled_erfc(
            (velocity + decay_velocity) * distance_m / (2.0 * dispersion),
            (retardation * distance_m + decay_velocity * time_s) / denominator,
        )
        concentration_fraction = min(1.0, max(0.0, 0.5 * (first + second)))
        concentration = params.initial_concentration_bq_m3 * concentration_fraction

    return {
        "concentration_bq_m3": concentration,
        "effective_kd_m3_kg": params.effective_distribution_coefficient_m3_kg,
        "retardation_factor": retardation,
        "travel_time_s": travel_time_s,
        "decay_factor": decay_factor,
        "steady_state_fraction": steady_state_fraction,
    }
