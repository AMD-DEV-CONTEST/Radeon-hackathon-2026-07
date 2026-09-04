"""Compile and run an opt-in NuclidePath chemistry scenario in PHREEQC.

The compiler is deliberately narrower than a general PHREEQC interface.  It
maps a declared NuclidePath groundwater scenario to a one-dimensional PHREEQC
transport input with aqueous Cs and an explicitly declared set of competing
 cations (K, Na, Ca, and Mg) and cation exchange.  The existing
NuclidePath deterministic transport model remains the canonical screening
model; this module produces a chemistry evidence slice that can later be
coupled to it after calibration.

No thermodynamic coefficient is supplied by this module.  Exchange constants,
CEC, and water composition must be supplied by the scenario and accompanied by
provenance.  The inline Cs+ definition is intentionally minimal and is not a
claim of complete cesium thermochemistry.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
from typing import Any, Mapping, Sequence


SCHEMA = "nuclidepath-phreeqc-chemistry-2"
CONTRACT = "process-qualified-only"
SECONDS_PER_YEAR = 365.25 * 24.0 * 60.0 * 60.0
AVOGADRO = 6.02214076e23
CS137_ATOMIC_MASS_G_MOL = 136.907089
_MAX_TRANSPORT_SHIFTS = 100_000

_WATER_COMPONENTS = {
    "Na", "K", "Ca", "Mg", "Cl", "C", "C(4)", "S", "S(6)", "N(5)", "Al", "Si",
}
_EXCHANGE_IONS = {"Cs", "K", "Na", "Ca", "Mg"}
_EXCHANGE_ORDER = ("Cs", "K", "Na", "Ca", "Mg")
_EXCHANGE_SPECIES = {
    "Cs": ("Cs+", "X-", "CsX", 1),
    "K": ("K+", "X-", "KX", 1),
    "Na": ("Na+", "X-", "NaX", 1),
    "Ca": ("Ca+2", "2X-", "CaX2", 2),
    "Mg": ("Mg+2", "2X-", "MgX2", 2),
}


class ScenarioCompileError(ValueError):
    """Raised when a chemistry projection is incomplete or unsafe."""


class ScenarioRunError(RuntimeError):
    """Raised when the bounded PHREEQC scenario contract fails."""


def _finite(value: Any, label: str, *, minimum: float | None = None,
            maximum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ScenarioCompileError(f"{label} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ScenarioCompileError(f"{label} must be finite")
    if minimum is not None and number < minimum:
        raise ScenarioCompileError(f"{label} must be >= {minimum}")
    if maximum is not None and number > maximum:
        raise ScenarioCompileError(f"{label} must be <= {maximum}")
    return number


def _positive_int(value: Any, label: str, *, maximum: int = 100_000) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0 or value > maximum:
        raise ScenarioCompileError(f"{label} must be an integer in [1, {maximum}]")
    return value


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ScenarioCompileError(f"{label} must be an object")
    return value


def _required(mapping: Mapping[str, Any], key: str, label: str | None = None) -> Any:
    if key not in mapping:
        raise ScenarioCompileError(f"missing {label or key}")
    return mapping[key]


def _fmt(value: float) -> str:
    """Format a finite PHREEQC scalar without locale dependence."""
    if value == 0.0:
        value = 0.0
    return format(value, ".12g")


def _ordered_exchange_ions(names: Sequence[str]) -> tuple[str, ...]:
    """Return a stable Cs-first ordering for a declared exchange set."""
    name_set = set(names)
    return tuple(ion for ion in _EXCHANGE_ORDER if ion in name_set)


def cs137_specific_activity_bq_mol(half_life_years: float = 30.018) -> float:
    """Return Cs-137 specific activity in Bq/mol for a declared half-life."""
    half_life = _finite(half_life_years, "half_life_years", minimum=0.0)
    if half_life == 0.0:
        raise ScenarioCompileError("half_life_years must be positive")
    decay_constant = math.log(2.0) / (half_life * SECONDS_PER_YEAR)
    return decay_constant * AVOGADRO


def activity_bq_m3_to_mol_kgw(activity_bq_m3: float, *, half_life_years: float,
                              water_density_kg_m3: float = 1000.0) -> float:
    """Convert Cs-137 activity in water to mol/kgw.

    The conversion treats the PHREEQC ``Cs`` component as total cesium and
    assumes the declared water density.  This is a unit conversion, not a
    claim that the supplied activity represents a complete isotope inventory.
    """
    activity = _finite(activity_bq_m3, "initial_concentration_bq_m3", minimum=0.0)
    density = _finite(water_density_kg_m3, "water_density_kg_m3", minimum=1.0)
    return activity / (cs137_specific_activity_bq_mol(half_life_years) * density)


def _validate_provenance(value: Any) -> dict[str, str]:
    provenance = _mapping(value, "phreeqc.provenance")
    if not provenance:
        raise ScenarioCompileError("phreeqc.provenance must not be empty")
    result: dict[str, str] = {}
    for key, item in provenance.items():
        if not isinstance(key, str) or not isinstance(item, str) or not item.strip():
            raise ScenarioCompileError("phreeqc.provenance values must be non-empty strings")
        result[key] = item.strip()
    return result


@dataclass(frozen=True)
class PhreeqcTransportMapping:
    cells: int
    cell_length_m: float
    time_step_s: float
    shifts: int
    dispersivity_m: float


@dataclass(frozen=True)
class CompiledPhreeqcScenario:
    """Deterministic PHREEQC input plus path-free compilation metadata."""

    input_text: str
    metadata: Mapping[str, Any]
    output_file: str = "nuclidepath.sel"

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "contract": CONTRACT,
            "input_sha256": hashlib.sha256(self.input_text.encode("utf-8")).hexdigest(),
            "metadata": dict(self.metadata),
            "output_file": self.output_file,
        }


def _water_lines(water: Mapping[str, Any], cs_mol_kgw: float | None) -> list[str]:
    units = _required(water, "units", "phreeqc.water.units")
    if units != "mmol/kgw":
        raise ScenarioCompileError("phreeqc.water.units must be exactly 'mmol/kgw'")
    pH = _finite(_required(water, "pH", "phreeqc.water.pH"), "phreeqc.water.pH", minimum=0.0, maximum=14.0)
    pe = _finite(_required(water, "pe", "phreeqc.water.pe"), "phreeqc.water.pe")
    temperature = _finite(_required(water, "temperature_c", "phreeqc.water.temperature_c"),
                           "phreeqc.water.temperature_c", minimum=-273.15, maximum=1000.0)
    ions = _mapping(_required(water, "ions_mmol_kgw", "phreeqc.water.ions_mmol_kgw"),
                    "phreeqc.water.ions_mmol_kgw")
    if any(not isinstance(name, str) for name in ions):
        raise ScenarioCompileError("water component names must be strings")
    unknown = set(ions) - _WATER_COMPONENTS
    if unknown:
        raise ScenarioCompileError("unsupported water components: " + ", ".join(sorted(unknown)))
    values: dict[str, float] = {}
    for name, value in ions.items():
        if not isinstance(name, str):
            raise ScenarioCompileError("water component names must be strings")
        values[name] = _finite(value, f"phreeqc.water.ions_mmol_kgw.{name}", minimum=0.0)
    lines = [
        "    units       mmol/kgw",
        f"    temp        {_fmt(temperature)}",
        f"    pH          {_fmt(pH)}",
        f"    pe          {_fmt(pe)}",
    ]
    for name in sorted(values):
        if values[name] != 0.0:
            lines.append(f"    {name:<10} {_fmt(values[name])}")
    if cs_mol_kgw is not None and cs_mol_kgw != 0.0:
        lines.append(f"    Cs          {_fmt(cs_mol_kgw * 1000.0)}")
    return lines


def _exchange_lines(log_k: Mapping[str, float]) -> list[str]:
    lines = [
        "EXCHANGE_MASTER_SPECIES",
        "    X           X-",
        "",
        "EXCHANGE_SPECIES",
        "    X- = X-",
        "        log_k   0.0",
    ]
    for ion in _EXCHANGE_ORDER:
        if ion not in log_k:
            continue
        aqueous, site, exchange, charge = _EXCHANGE_SPECIES[ion]
        lines.extend([
            f"    {aqueous} + {site} = {exchange}",
            f"        log_k   {_fmt(log_k[ion])}",
        ])
    return lines


def _selected_output_lines(exchange_ions: Sequence[str]) -> list[str]:
    totals = " ".join(exchange_ions)
    molalities = " ".join(
        [*(_EXCHANGE_SPECIES[ion][0] for ion in exchange_ions),
         *(_EXCHANGE_SPECIES[ion][2] for ion in exchange_ions)]
    )
    return [
        "SELECTED_OUTPUT 1 NuclidePath chemistry projection",
        "    -file               nuclidepath.sel",
        "    -reset              true",
        "    -high_precision     true",
        "    -simulation         true",
        "    -state              true",
        "    -solution           true",
        "    -distance           true",
        "    -time               true",
        "    -step               true",
        "    -pH                 true",
        # PHREEQC carries several legacy selected-output columns unless they
        # are explicitly disabled. Keep the emitted schema closed so the
        # parser cannot silently reinterpret a solver-version default.
        "    -pe                 false",
        "    -reaction           false",
        "    -temperature        false",
        "    -alkalinity         false",
        "    -water              false",
        "    -charge_balance     false",
        "    -percent_error      false",
        "    -ionic_strength     true",
        f"    -totals             {totals}",
        f"    -molalities         {molalities}",
    ]


def compile_phreeqc_scenario(scenario: Mapping[str, Any], *,
                             cells: int | None = None,
                             max_shifts: int | None = None) -> CompiledPhreeqcScenario:
    """Compile a declared NuclidePath scenario into PHREEQC input.

    The input requires an explicit ``phreeqc`` block.  A minimal valid block is:

    ``water`` with pH, pe, temperature, units, and major ions in mmol/kgw;
    ``exchange`` with CEC, Cs and one or more declared competitor
    log-selectivity values, and provenance; and
    ``discretization`` with a declared cell count.
    """
    root = _mapping(scenario, "scenario")
    site = _mapping(_required(root, "site"), "site")
    if site.get("radionuclide") != "Cs-137":
        raise ScenarioCompileError("phreeqc chemistry projection currently requires site.radionuclide='Cs-137'")
    transport = _mapping(_required(root, "transport"), "transport")
    phreeqc = _mapping(_required(root, "phreeqc"), "phreeqc")
    water = _mapping(_required(phreeqc, "water", "phreeqc.water"), "phreeqc.water")
    exchange = _mapping(_required(phreeqc, "exchange", "phreeqc.exchange"), "phreeqc.exchange")
    discretization = _mapping(_required(phreeqc, "discretization", "phreeqc.discretization"),
                               "phreeqc.discretization")
    provenance = _validate_provenance(_required(phreeqc, "provenance"))
    if not {"water", "cec", "selectivity"} <= set(provenance):
        raise ScenarioCompileError("phreeqc.provenance must include water, cec, and selectivity")

    distance = _finite(_required(transport, "distance_m"), "transport.distance_m", minimum=0.0)
    velocity = _finite(_required(transport, "groundwater_velocity_m_s"),
                       "transport.groundwater_velocity_m_s", minimum=0.0)
    dispersion = _finite(_required(transport, "dispersion_m2_s"),
                         "transport.dispersion_m2_s", minimum=0.0)
    if distance == 0.0 or velocity == 0.0:
        raise ScenarioCompileError("distance_m and groundwater_velocity_m_s must be positive")
    times = _required(transport, "evaluation_times_s")
    if not isinstance(times, Sequence) or isinstance(times, (str, bytes)) or not times:
        raise ScenarioCompileError("transport.evaluation_times_s must be a non-empty array")
    evaluation_times = [_finite(value, "transport.evaluation_times_s", minimum=0.0) for value in times]
    if evaluation_times != sorted(evaluation_times):
        raise ScenarioCompileError("transport.evaluation_times_s must be sorted")

    requested_cells = discretization.get("cells") if cells is None else cells
    cell_count = _positive_int(requested_cells, "phreeqc.discretization.cells", maximum=10_000)
    cell_length = distance / cell_count
    time_step = cell_length / velocity
    if not math.isfinite(cell_length) or not math.isfinite(time_step) or time_step <= 0.0:
        raise ScenarioCompileError(
            "derived PHREEQC cell length and time_step must be finite and positive"
        )
    off_grid_times = []
    grid_indices: list[int] = []
    for value in evaluation_times:
        grid_index = value / time_step
        nearest_grid_index = round(grid_index)
        if not math.isclose(grid_index, nearest_grid_index, rel_tol=1e-12, abs_tol=1e-9):
            off_grid_times.append(value)
        grid_indices.append(nearest_grid_index)
    if off_grid_times:
        raise ScenarioCompileError(
            "transport.evaluation_times_s must align with the PHREEQC time_step grid"
        )
    # Use the already validated integer grid indices. Reapplying ceil to the
    # floating-point quotient can turn an exact 40-step request into 41 when
    # the derived time step is represented as 499999.99999999994.
    required_shifts = max(1, max(grid_indices))
    if required_shifts > _MAX_TRANSPORT_SHIFTS:
        raise ScenarioCompileError(
            "evaluation_times_s require more than 100000 PHREEQC transport shifts"
        )
    if max_shifts is None:
        shifts = required_shifts
    else:
        shifts = _positive_int(max_shifts, "max_shifts", maximum=100_000)
        if shifts < required_shifts:
            raise ScenarioCompileError("max_shifts does not cover evaluation_times_s")
    dispersivity = dispersion / velocity
    if not math.isfinite(dispersivity):
        raise ScenarioCompileError("derived PHREEQC dispersivity must be finite")

    bulk_density = _finite(_required(transport, "bulk_density_kg_m3"),
                            "transport.bulk_density_kg_m3", minimum=1e-12)
    porosity = _finite(_required(transport, "porosity"), "transport.porosity", minimum=1e-12, maximum=1.0)
    water_density = _finite(phreeqc.get("water_density_kg_m3", 1000.0),
                             "phreeqc.water_density_kg_m3", minimum=1.0)
    cec = _finite(_required(exchange, "cec_mmolc_kg", "phreeqc.exchange.cec_mmolc_kg"),
                  "phreeqc.exchange.cec_mmolc_kg", minimum=0.0)
    if cec == 0.0:
        raise ScenarioCompileError("phreeqc.exchange.cec_mmolc_kg must be positive")
    log_k_raw = _mapping(_required(exchange, "log_k", "phreeqc.exchange.log_k"),
                         "phreeqc.exchange.log_k")
    if "Cs" not in log_k_raw:
        raise ScenarioCompileError("phreeqc.exchange.log_k must include Cs")
    if any(not isinstance(name, str) for name in log_k_raw):
        raise ScenarioCompileError("phreeqc.exchange.log_k names must be strings")
    unknown_log_k = set(log_k_raw) - _EXCHANGE_IONS
    if unknown_log_k:
        raise ScenarioCompileError("unsupported exchange ions: " + ", ".join(sorted(unknown_log_k)))
    competitor_ions = set(log_k_raw) - {"Cs"}
    if not competitor_ions:
        raise ScenarioCompileError(
            "phreeqc.exchange.log_k must include at least one competitor (K, Na, Ca, or Mg)"
        )
    log_k = {name: _finite(value, f"phreeqc.exchange.log_k.{name}", minimum=-50.0, maximum=50.0)
             for name, value in log_k_raw.items()}
    exchange_ions = _ordered_exchange_ions(log_k)

    half_life = _finite(_required(transport, "half_life_years"),
                        "transport.half_life_years", minimum=1e-12)
    activity = _finite(_required(transport, "initial_concentration_bq_m3"),
                       "transport.initial_concentration_bq_m3", minimum=0.0)
    cs_mol_kgw = activity_bq_m3_to_mol_kgw(activity, half_life_years=half_life,
                                           water_density_kg_m3=water_density)
    sites_mol_kgw = _finite(
        cec * 1e-3 * bulk_density / (porosity * water_density),
        "derived PHREEQC exchange sites",
        minimum=1e-300,
    )

    canonical_keys = (
        "distribution_coefficient_m3_kg",
        "potassium_mg_l",
        "competition_coefficient_l_mg",
    )
    canonical_available = all(key in transport for key in canonical_keys)
    canonical_empirical: dict[str, Any] = {
        "available": canonical_available,
        "bulk_density_kg_m3": bulk_density,
        "porosity": porosity,
    }
    for key in canonical_keys:
        canonical_empirical[key] = (
            _finite(transport[key], f"transport.{key}", minimum=0.0)
            if key in transport else None
        )

    # The input deliberately defines only the minimal inline cesium aqueous
    # species needed by the exchange projection.  It does not claim a complete
    # Cs thermodynamic database.
    lines = [
        f"TITLE NuclidePath Cs-137 chemistry projection ({SCHEMA})",
        "",
        "SOLUTION_MASTER_SPECIES",
        "    Cs          Cs+       0.0       Cs        132.90545196",
        "",
        "SOLUTION_SPECIES",
        "    Cs+ = Cs+",
        "        log_k   0.0",
        "",
        *_exchange_lines(log_k),
        "",
        "SOLUTION 0 Boundary maintained Cs-137 release",
        *_water_lines(water, cs_mol_kgw),
        "",
        f"SOLUTION 1-{cell_count} Initial aquifer water",
        *_water_lines(water, None),
        "",
        f"EXCHANGE 1-{cell_count} Initial cation exchanger",
        "    -equilibrate         1",
        f"    X                   {_fmt(sites_mol_kgw)}",
        "",
        "END",
        "",
        *_selected_output_lines(exchange_ions),
        "",
        "TRANSPORT",
        f"    -cells               {cell_count}",
        f"    -shifts              {shifts}",
        f"    -lengths             {_fmt(cell_length)}",
        f"    -time_step           {_fmt(time_step)}",
        "    -flow_direction      forward",
        "    -boundary_conditions flux flux",
        "    -diffusion_coefficient 0.0",
        f"    -dispersivities      {_fmt(dispersivity)}",
        "    -correct_disp        true",
        f"    -punch_cells         {cell_count}",
        "    -punch_frequency     1",
        "",
        "END",
        "",
    ]
    input_text = "\n".join(lines)
    mapping = PhreeqcTransportMapping(cell_count, cell_length, time_step, shifts, dispersivity)
    metadata = {
        "schema": SCHEMA,
        "contract": CONTRACT,
        "model": "aqueous-speciation-plus-gaines-thomas-cation-exchange-transport",
        "selected_output_semantics": (
            "Declared-ion totals are PHREEQC solution totals; each corresponding "
            "exchange species is selected in mol/kgw; displayed phase partitions "
            "and equivalent-site occupancies are reconstructed."
        ),
        "database_assumption": "phreeqc.dat with an inline minimal Cs+ master/species definition",
        "scientific_evidence_level": "NUMERICALLY_VERIFIED",
        "scientific_result_qualified": False,
        "scientific_result_reason": (
            "The independent arithmetic oracle verifies the declared projection "
            "contract; calibration and experimental agreement are still required."
        ),
        "radioactive_decay": "not applied by PHREEQC; retained by the canonical NuclidePath screening model",
        "water": {
            "units": "mmol/kgw",
            "pH": _finite(_required(water, "pH"), "phreeqc.water.pH"),
            "pe": _finite(_required(water, "pe"), "phreeqc.water.pe"),
            "temperature_c": _finite(_required(water, "temperature_c"), "phreeqc.water.temperature_c"),
            "ions_mmol_kgw": dict(sorted(_mapping(
                _required(water, "ions_mmol_kgw"), "phreeqc.water.ions_mmol_kgw"
            ).items())),
        },
        "exchange": {
            "cec_mmolc_kg": cec,
            "exchange_sites_mol_kgw": sites_mol_kgw,
            "log_k": dict(sorted(log_k.items())),
            "exchange_ions": list(exchange_ions),
            "competitor_ions": sorted(competitor_ions),
            "convention": "Gaines-Thomas-equivalent-fraction (PHREEQC database convention)",
        },
        "source_term": {
            "boundary_activity_bq_m3": activity,
            "half_life_years": half_life,
            "converted_cs_mol_kgw": cs_mol_kgw,
            "water_density_kg_m3": water_density,
        },
        "transport_mapping": asdict(mapping),
        "transport_inputs": {
            "distance_m": distance,
            "groundwater_velocity_m_s": velocity,
            "dispersion_m2_s": dispersion,
            "bulk_density_kg_m3": bulk_density,
            "porosity": porosity,
        },
        "canonical_empirical_model": canonical_empirical,
        "evaluation_times_s": evaluation_times,
        "evaluation_time_policy": (
            "Requested evaluation times must lie on the PHREEQC transport grid; "
            "selected output is emitted at those times without interpolation."
        ),
        "provenance": provenance,
    }
    return CompiledPhreeqcScenario(input_text, metadata)


@dataclass(frozen=True)
class PhreeqcOutputRow:
    simulation: int
    state: str
    solution: int
    distance_m: float
    time_s: float
    step: int
    pH: float
    ionic_strength: float
    totals_mol_kgw: Mapping[str, float]
    aqueous_mol_kgw: Mapping[str, float]
    exchange_mol_kgw: Mapping[str, float]

    def _value(self, values: Mapping[str, float], ion: str) -> float:
        return float(values.get(ion, 0.0))

    @property
    def k_total_mol_kgw(self) -> float:
        return self._value(self.totals_mol_kgw, "K")

    @property
    def cs_total_mol_kgw(self) -> float:
        return self._value(self.totals_mol_kgw, "Cs")

    @property
    def k_aqueous_mol_kgw(self) -> float:
        return self._value(self.aqueous_mol_kgw, "K")

    @property
    def cs_aqueous_mol_kgw(self) -> float:
        return self._value(self.aqueous_mol_kgw, "Cs")

    @property
    def k_exchange_mol_kgw(self) -> float:
        return self._value(self.exchange_mol_kgw, "K")

    @property
    def cs_exchange_mol_kgw(self) -> float:
        return self._value(self.exchange_mol_kgw, "Cs")


@dataclass(frozen=True)
class ParsedPhreeqcOutput:
    columns: tuple[str, ...]
    rows: tuple[PhreeqcOutputRow, ...]


_HEADER_ALIASES = {
    "sim": "simulation", "simulation": "simulation",
    "state": "state", "soln": "solution", "solution": "solution",
    "dist_x": "distance_m", "distance": "distance_m",
    "time": "time_s", "step": "step", "pH": "pH", "ph": "pH",
    "mu": "ionic_strength", "ionic_strength": "ionic_strength",
}


def _header_name(token: str) -> str:
    if token in _HEADER_ALIASES:
        return _HEADER_ALIASES[token]
    # PHREEQC labels selected molality columns with an m_ prefix. The
    # public schema uses the declared species names, so normalize only known
    # exchange species and keep every other token subject to exact validation.
    if token.startswith("m_"):
        species = token[2:]
        known_species = {
            species_name
            for aqueous, _, exchange, _ in _EXCHANGE_SPECIES.values()
            for species_name in (aqueous, exchange)
        }
        if species in known_species:
            return species
    return token


def parse_phreeqc_selected_output(
    text: str,
    *,
    exchange_ions: Sequence[str] | None = None,
) -> ParsedPhreeqcOutput:
    """Parse selected output for a declared, possibly K-free exchange set.

    The compiler passes the exact declared ion order.  For compatibility with
    the first bridge fixture, callers that omit ``exchange_ions`` may use a
    header-driven parser; the parser still rejects unknown or missing
    exchange/aqueous species and never guesses a column's meaning.
    """
    if not isinstance(text, str):
        raise ScenarioCompileError("selected output must be text")
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        raise ScenarioCompileError("selected output must contain a header and a data row")
    raw_columns = tuple(lines[0].split())
    columns = tuple(_header_name(token) for token in raw_columns)
    prefix = (
        "simulation", "state", "solution", "distance_m", "time_s", "step",
        "pH", "ionic_strength",
    )
    if len(columns) <= len(prefix) or columns[:len(prefix)] != prefix:
        raise ScenarioCompileError(f"selected-output header mismatch: expected prefix {prefix!r}, got {columns!r}")
    if exchange_ions is not None:
        declared = _ordered_exchange_ions(exchange_ions)
        if len(declared) != len(tuple(exchange_ions)) or "Cs" not in declared:
            raise ScenarioCompileError("exchange_ions must contain unique supported ions including Cs")
        totals = declared
    else:
        tail = columns[len(prefix):]
        total_values: list[str] = []
        while tail and tail[0] in _EXCHANGE_IONS:
            total_values.append(tail[0])
            tail = tail[1:]
        totals = tuple(total_values)
        if not totals or "Cs" not in totals:
            raise ScenarioCompileError("selected-output header must include Cs and at least one exchange total")
    expected_molalities = tuple(
        [*(_EXCHANGE_SPECIES[ion][0] for ion in totals),
         *(_EXCHANGE_SPECIES[ion][2] for ion in totals)]
    )
    expected = prefix + totals + expected_molalities
    if columns != expected:
        raise ScenarioCompileError(
            f"selected-output header mismatch: expected {expected!r}, got {columns!r}"
        )
    rows: list[PhreeqcOutputRow] = []
    for line_number, line in enumerate(lines[1:], start=2):
        fields = line.split()
        if len(fields) != len(expected):
            raise ScenarioCompileError(f"selected-output field count mismatch on line {line_number}")
        if not fields[1]:
            raise ScenarioCompileError(f"empty selected-output state on line {line_number}")
        try:
            integer_values = [float(fields[index]) for index in (0, 2, 5)]
            if any(not value.is_integer() for value in integer_values):
                raise ValueError("non-integral identifier")
            numeric = [float(value) for value in fields[3:5] + fields[6:]]
        except ValueError as exc:
            raise ScenarioCompileError(f"invalid selected-output number on line {line_number}") from exc
        if any(not math.isfinite(value) for value in integer_values + numeric):
            raise ScenarioCompileError(f"non-finite selected-output value on line {line_number}")
        if float(fields[7]) < 0.0:
            raise ScenarioCompileError(
                f"selected-output ionic_strength must be non-negative on line {line_number}"
            )
        total_start = len(prefix)
        total_end = total_start + len(totals)
        total_values = [float(value) for value in fields[total_start:total_end]]
        molality_values = [
            float(value) for value in fields[total_end:]
        ]
        aqueous = {
            ion: molality_values[index]
            for index, ion in enumerate(totals)
        }
        exchanged = {
            ion: molality_values[index + len(totals)]
            for index, ion in enumerate(totals)
        }
        chemistry_values = (
            ("total", dict(zip(totals, total_values))),
            ("aqueous", aqueous),
            ("exchange", exchanged),
        )
        for phase, values in chemistry_values:
            for ion, value in values.items():
                if value < 0.0:
                    raise ScenarioCompileError(
                        f"selected-output {phase} {ion} values must be finite "
                        f"and non-negative on line {line_number}"
                    )
        rows.append(PhreeqcOutputRow(
            int(integer_values[0]), fields[1], int(integer_values[1]),
            float(fields[3]), float(fields[4]), int(integer_values[2]),
            float(fields[6]), float(fields[7]),
            dict(zip(totals, total_values)), aqueous, exchanged,
        ))
    return ParsedPhreeqcOutput(columns, tuple(rows))



def _nonnegative_output(value: float, label: str) -> float:
    if not math.isfinite(value) or value < 0.0:
        raise ScenarioCompileError(f"{label} must be finite and non-negative")
    return value


def diagnose_phreeqc_output(
    compiled: CompiledPhreeqcScenario,
    parsed: ParsedPhreeqcOutput,
) -> dict[str, Any]:
    """Derive transparent chemistry diagnostics without qualifying the result.

    PHREEQC's `-totals` columns report solution totals, while exchange
    amounts are selected separately.  The function reconstructs the displayed
    aqueous-plus-exchange partition and reports the solution-total residual
    rather than treating it as a global mass balance.  When the original
    empirical Kd inputs are present, it also reports a side-by-side comparison;
    it never selects one model as the project result.
    """
    if not isinstance(parsed, ParsedPhreeqcOutput):
        raise ScenarioCompileError("parsed PHREEQC output has an invalid type")
    from .phreeqc_oracle import NumericalOracleError, evaluate_phreeqc_numerical_oracle

    try:
        numerical_oracle = evaluate_phreeqc_numerical_oracle(compiled, parsed)
    except NumericalOracleError as exc:
        raise ScenarioCompileError(
            f"PHREEQC numerical oracle rejected output: {exc}"
        ) from exc
    exchange_metadata = _mapping(compiled.metadata.get("exchange"), "compiled exchange metadata")
    source_metadata = _mapping(compiled.metadata.get("source_term"), "compiled source metadata")
    transport_metadata = _mapping(
        compiled.metadata.get("canonical_empirical_model"),
        "compiled canonical empirical metadata",
    )
    exchange_sites = _finite(
        exchange_metadata.get("exchange_sites_mol_kgw"),
        "compiled exchange sites",
        minimum=1e-300,
    )
    bulk_density = _finite(
        transport_metadata.get("bulk_density_kg_m3"),
        "compiled bulk density",
        minimum=1e-300,
    )
    porosity = _finite(
        transport_metadata.get("porosity"),
        "compiled porosity",
        minimum=1e-300,
        maximum=1.0,
    )
    rows: list[dict[str, Any]] = []
    apparent_kd_values: list[float] = []
    cs_site_fractions: list[float] = []
    max_site_fraction_by_ion: dict[str, float] = {}
    max_abs_closure = 0.0
    rows_with_cs = 0
    empirical_available = bool(transport_metadata.get("available"))
    empirical: dict[str, Any] = {
        "available": empirical_available,
        "effective_kd_m3_kg": None,
        "retardation_factor": None,
    }
    if empirical_available:
        kd = _finite(
            transport_metadata.get("distribution_coefficient_m3_kg"),
            "compiled empirical distribution coefficient",
            minimum=0.0,
        )
        potassium = _finite(
            transport_metadata.get("potassium_mg_l"),
            "compiled empirical potassium",
            minimum=0.0,
        )
        coefficient = _finite(
            transport_metadata.get("competition_coefficient_l_mg"),
            "compiled empirical competition coefficient",
            minimum=0.0,
        )
        effective_kd = kd / (1.0 + coefficient * potassium)
        empirical["effective_kd_m3_kg"] = effective_kd
        empirical["retardation_factor"] = 1.0 + bulk_density * effective_kd / porosity

    for row in parsed.rows:
        component_diagnostics: dict[str, dict[str, Any]] = {}
        for ion in row.totals_mol_kgw:
            total = _nonnegative_output(
                row.totals_mol_kgw[ion], f"selected-output total {ion}"
            )
            aqueous = _nonnegative_output(
                row.aqueous_mol_kgw.get(ion, 0.0), f"selected-output aqueous {ion}"
            )
            exchanged = _nonnegative_output(
                row.exchange_mol_kgw.get(ion, 0.0), f"selected-output exchanged {ion}"
            )
            residual = total - aqueous
            relative_residual = residual / max(total, 1e-300)
            max_abs_closure = max(max_abs_closure, abs(relative_residual))
            charge = _EXCHANGE_SPECIES[ion][3]
            site_fraction = exchanged * charge / exchange_sites
            max_site_fraction_by_ion[ion] = max(
                max_site_fraction_by_ion.get(ion, 0.0), site_fraction
            )
            component_diagnostics[ion] = {
                "total_mol_kgw": total,
                "aqueous_mol_kgw": aqueous,
                "exchange_mol_kgw": exchanged,
                "exchange_charge_equivalents_mol_kgw": exchanged * charge,
                "exchange_site_fraction": site_fraction,
                "solution_total_residual_mol_kgw": residual,
                "solution_total_relative_error": relative_residual,
            }

        cs = component_diagnostics["Cs"]
        cs_total = cs["total_mol_kgw"]
        cs_aqueous = cs["aqueous_mol_kgw"]
        cs_exchange = cs["exchange_mol_kgw"]
        solution_total_residual = cs["solution_total_residual_mol_kgw"]
        relative_solution_residual = cs["solution_total_relative_error"]
        phase_total = cs_total + cs_exchange
        if phase_total > 0.0:
            rows_with_cs += 1
            dissolved_fraction = cs_total / phase_total
            exchange_fraction = cs_exchange / phase_total
        else:
            dissolved_fraction = None
            exchange_fraction = None
        if cs_total > 0.0:
            apparent_kd = cs_exchange * porosity / (bulk_density * cs_total)
            apparent_retardation = 1.0 + cs_exchange / cs_total
            apparent_kd_values.append(apparent_kd)
        else:
            apparent_kd = None
            apparent_retardation = None
        site_fraction = cs["exchange_site_fraction"]
        cs_site_fractions.append(site_fraction)
        row_comparison = {
            "empirical_effective_kd_m3_kg": empirical["effective_kd_m3_kg"],
            "empirical_retardation_factor": empirical["retardation_factor"],
            "apparent_kd_ratio_to_empirical": (
                apparent_kd / empirical["effective_kd_m3_kg"]
                if apparent_kd is not None and empirical["effective_kd_m3_kg"] not in (None, 0.0)
                else None
            ),
        }
        rows.append({
            "simulation": row.simulation,
            "state": row.state,
            "solution": row.solution,
            "distance_m": row.distance_m,
            "time_s": row.time_s,
            "step": row.step,
            "cs_total_mol_kgw": cs_total,
            "cs_aqueous_mol_kgw": cs_aqueous,
            "cs_exchange_mol_kgw": cs_exchange,
            "components": component_diagnostics,
            "exchange_ions": list(row.totals_mol_kgw),
            "competitor_exchange_site_fractions": {
                ion: values["exchange_site_fraction"]
                for ion, values in component_diagnostics.items()
                if ion != "Cs"
            },
            "displayed_aqueous_plus_exchange_mol_kgw": phase_total,
            "dissolved_fraction": dissolved_fraction,
            "exchange_fraction": exchange_fraction,
            "exchange_site_fraction": site_fraction,
            "solution_total_residual_mol_kgw": solution_total_residual,
            "solution_total_relative_error": relative_solution_residual,
            "apparent_kd_m3_kg": apparent_kd,
            "apparent_retardation_factor": apparent_retardation,
            "comparison": row_comparison,
        })

    return {
        "diagnostic_version": "phreeqc-chemistry-diagnostic-2",
        "status": "comparative-evidence-only",
        "scientific_evidence_level": "NUMERICALLY_VERIFIED",
        "scientific_result_qualified": False,
        "scientific_result_reason": (
            "The independent oracle verifies declared arithmetic invariants; "
            "calibration and experimental agreement are still required."
        ),
        "numerical_oracle": numerical_oracle,
        "rows": rows,
        "summary": {
            "rows_total": len(rows),
            "rows_with_cs": rows_with_cs,
            "exchange_ions": list(parsed.rows[0].totals_mol_kgw) if parsed.rows else [],
            "competitor_ions": [
                ion for ion in (list(parsed.rows[0].totals_mol_kgw) if parsed.rows else [])
                if ion != "Cs"
            ],
            "max_abs_solution_total_relative_error": max_abs_closure,
            "apparent_kd_range_m3_kg": (
                [min(apparent_kd_values), max(apparent_kd_values)]
                if apparent_kd_values else None
            ),
            "max_exchange_site_fraction": max(cs_site_fractions) if cs_site_fractions else 0.0,
            "max_exchange_site_fraction_by_ion": dict(sorted(max_site_fraction_by_ion.items())),
        },
        "canonical_empirical_model": empirical,
        "source_term": {
            "boundary_activity_bq_m3": source_metadata.get("boundary_activity_bq_m3"),
            "half_life_years": source_metadata.get("half_life_years"),
            "radioactive_decay": "not applied by PHREEQC",
        },
    }


@dataclass(frozen=True)
class PhreeqcScenarioRun:
    compiled: CompiledPhreeqcScenario
    process: Any
    working_directory: Path
    output_hashes: Mapping[str, str]
    selected_output: ParsedPhreeqcOutput

    def deterministic_payload(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "contract": CONTRACT,
            "compiled": self.compiled.canonical_payload(),
            "process": {
                "exit_status": self.process.exit_status,
                "timed_out": self.process.timed_out,
                "stdout": self.process.stdout,
                "stderr": self.process.stderr,
                "stdout_sha256": self.process.stdout_sha256,
                "stderr_sha256": self.process.stderr_sha256,
                "output_limits_exceeded": list(self.process.output_limits_exceeded),
                "streams_complete": self.process.streams_complete,
                "stream_drain_timed_out": self.process.stream_drain_timed_out,
                "stream_errors": list(self.process.stream_errors),
            },
            "output_hashes": dict(sorted(self.output_hashes.items())),
            "selected_output": [asdict(row) for row in self.selected_output.rows],
            "chemistry_diagnostics": diagnose_phreeqc_output(
                self.compiled, self.selected_output
            ),
            "scientific_evidence_level": "NUMERICALLY_VERIFIED",
            "scientific_result_qualified": False,
        }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stable_output_read(path: Path, *, max_bytes: int) -> tuple[bytes, str]:
    """Read one bounded output through a descriptor without following symlinks."""
    try:
        preliminary = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise ScenarioRunError(f"output unavailable: {path.name}") from exc
    if not stat.S_ISREG(preliminary.st_mode) or preliminary.st_nlink != 1:
        raise ScenarioRunError(f"output must be a single-link regular file: {path.name}")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ScenarioRunError(f"output unavailable: {path.name}") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > max_bytes:
            raise ScenarioRunError(f"output exceeds the bounded file contract: {path.name}")
        digest = hashlib.sha256()
        data = bytearray()
        while chunk := os.read(descriptor, 1024 * 1024):
            data.extend(chunk)
            digest.update(chunk)
            if len(data) > max_bytes:
                raise ScenarioRunError(f"output exceeds the bounded file contract: {path.name}")
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    identity = lambda value: (value.st_dev, value.st_ino, value.st_size,
                              value.st_mtime_ns, value.st_ctime_ns, value.st_nlink)
    if identity(before) != identity(after) or len(data) != after.st_size:
        raise ScenarioRunError(f"output changed while being read: {path.name}")
    try:
        current = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise ScenarioRunError(f"output changed after being read: {path.name}") from exc
    if not stat.S_ISREG(current.st_mode) or identity(current) != identity(after):
        raise ScenarioRunError(f"output path changed after being read: {path.name}")
    return bytes(data), digest.hexdigest()


def _canonical_output_hashes(run: PhreeqcScenarioRun) -> dict[str, str]:
    """Hash replay-stable solver artifacts while retaining raw run evidence.

    PHREEQC embeds staged absolute input/database paths and wall-clock
    duration in phreeqc.out and phreeqc.log. Those fields describe the
    invocation, not the chemistry result, so they must be normalized before a
    replay payload can be compared across two isolated runs.
    """
    canonical: dict[str, str] = {}
    for name, raw_digest in sorted(run.output_hashes.items()):
        path = run.working_directory / name
        data, observed_digest = _stable_output_read(path, max_bytes=16 * 1024 * 1024)
        if observed_digest != raw_digest:
            raise ScenarioRunError(f"solver output changed before replay canonicalization: {name}")
        if name in {"phreeqc.out", "phreeqc.log"}:
            try:
                text = data.decode("utf-8", errors="strict")
            except UnicodeDecodeError as exc:
                raise ScenarioRunError(f"solver output is not UTF-8: {name}") from exc
            text = text.replace(str(run.working_directory / "input.pqi"), "input.pqi")
            text = text.replace(str(run.working_directory / "database.dat"), "database.dat")
            text = re.sub(r"End of Run after [0-9.]+ Seconds\.",
                          "End of Run after <duration> Seconds.", text)
            data = text.encode("utf-8")
        canonical[name] = hashlib.sha256(data).hexdigest()
    return canonical


def _safe_source(path: Path, label: str) -> Path:
    path = Path(path)
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise ScenarioRunError(f"{label} must be an absolute regular non-symlink file")
    return path


def _verify_digest(value: str, label: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ScenarioRunError(f"{label} must be a lowercase SHA-256 digest")
    return value


def run_phreeqc_scenario(compiled: CompiledPhreeqcScenario, *, executable: Path,
                         database: Path, executable_sha256: str,
                         database_sha256: str, working_directory: Path,
                         timeout_seconds: float = 30.0,
                         max_output_file_bytes: int = 16 * 1024 * 1024,
                         max_output_total_bytes: int = 32 * 1024 * 1024) -> PhreeqcScenarioRun:
    """Run a compiled scenario through the existing bounded adapter contract."""
    from .external_adapters import ExternalSolverManifest, run_replayable

    executable = _safe_source(executable, "executable")
    database = _safe_source(database, "database")
    executable_sha256 = _verify_digest(executable_sha256, "executable_sha256")
    database_sha256 = _verify_digest(database_sha256, "database_sha256")
    if (isinstance(max_output_file_bytes, bool) or not isinstance(max_output_file_bytes, int)
            or max_output_file_bytes <= 0):
        raise ScenarioRunError("max_output_file_bytes must be a positive integer")
    if (isinstance(max_output_total_bytes, bool) or not isinstance(max_output_total_bytes, int)
            or max_output_total_bytes <= 0):
        raise ScenarioRunError("max_output_total_bytes must be a positive integer")
    if _sha256_file(executable) != executable_sha256:
        raise ScenarioRunError("executable SHA-256 mismatch")
    if _sha256_file(database) != database_sha256:
        raise ScenarioRunError("database SHA-256 mismatch")
    root = Path(working_directory)
    if not root.is_absolute() or root.is_symlink() or not root.is_dir():
        raise ScenarioRunError("working_directory must be an absolute non-symlink directory")
    run_directory = root / "phreeqc-scenario-run"
    if run_directory.exists() or run_directory.is_symlink():
        raise ScenarioRunError("dedicated PHREEQC scenario run directory already exists")
    run_directory.mkdir(mode=0o700)
    staged_executable = run_directory / "phreeqc"
    staged_database = run_directory / "database.dat"
    input_path = run_directory / "input.pqi"
    shutil.copyfile(executable, staged_executable, follow_symlinks=False)
    shutil.copyfile(database, staged_database, follow_symlinks=False)
    staged_executable.chmod(stat.S_IMODE(executable.stat().st_mode))
    input_path.write_bytes(compiled.input_text.encode("utf-8"))
    if (_sha256_file(staged_executable) != executable_sha256
            or _sha256_file(staged_database) != database_sha256):
        raise ScenarioRunError("staged PHREEQC artifact digest mismatch")
    manifest = ExternalSolverManifest(
        executable=staged_executable,
        executable_sha256=executable_sha256,
        database=staged_database,
        database_sha256=database_sha256,
        input_files=((input_path, hashlib.sha256(input_path.read_bytes()).hexdigest()),),
        version=SCHEMA,
        command=(str(staged_executable), str(input_path), "phreeqc.out",
                 str(staged_database), "phreeqc.log"),
        working_directory=run_directory,
    )
    result = run_replayable(manifest, timeout=timeout_seconds)
    if (result.timed_out or result.stream_drain_timed_out or not result.streams_complete
            or result.stream_errors or result.output_limits_exceeded
            or result.launch_error is not None or result.exit_status != 0):
        raise ScenarioRunError("PHREEQC scenario execution failed closed")
    if compiled.output_file != "nuclidepath.sel":
        raise ScenarioRunError("compiled output_file must be nuclidepath.sel")
    expected_outputs = {"nuclidepath.sel", "phreeqc.out", "phreeqc.log"}
    entries = {path.name: path for path in run_directory.iterdir()
               if path.name not in {"phreeqc", "database.dat", "input.pqi"}}
    if set(entries) != expected_outputs or any(path.is_symlink() or not path.is_file() for path in entries.values()):
        raise ScenarioRunError("PHREEQC scenario output inventory mismatch")
    output_hashes: dict[str, str] = {}
    selected_data: bytes | None = None
    total_output_bytes = 0
    for name, path in sorted(entries.items()):
        data, digest = _stable_output_read(path, max_bytes=max_output_file_bytes)
        total_output_bytes += len(data)
        if total_output_bytes > max_output_total_bytes:
            raise ScenarioRunError("PHREEQC scenario outputs exceed the bounded total size")
        output_hashes[name] = digest
        if name == compiled.output_file:
            selected_data = data
    if selected_data is None:
        raise ScenarioRunError("selected output is missing")
    try:
        selected_text = selected_data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ScenarioRunError("selected output is unavailable or not UTF-8") from exc
    selected = parse_phreeqc_selected_output(
        selected_text,
        exchange_ions=tuple(compiled.metadata["exchange"]["exchange_ions"]),
    )
    try:
        diagnose_phreeqc_output(compiled, selected)
    except ScenarioCompileError as exc:
        raise ScenarioRunError("PHREEQC selected output failed chemistry diagnostics") from exc
    return PhreeqcScenarioRun(compiled, result, run_directory, output_hashes, selected)


def write_scenario_replay(path: Path, run: PhreeqcScenarioRun):
    """Write and internally verify a replay bundle for a scenario run."""
    from .replay import ReplayBundle, verify_bundle

    canonical = run.deterministic_payload()
    canonical_output_hashes = _canonical_output_hashes(run)
    canonical["output_hashes"] = canonical_output_hashes
    encoded = json.dumps(canonical, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()
    results = {
        "qualification_content": canonical,
        "qualification_content_sha256": hashlib.sha256(encoded).hexdigest(),
    }
    bundle = ReplayBundle.write(
        path,
        {"schema": SCHEMA, "compiled_input_sha256": canonical["compiled"]["input_sha256"]},
        {"contract": CONTRACT, "artifacts": canonical_output_hashes},
        results,
        tool_trace=[{"tool": "phreeqc", "command": ["phreeqc", "input.pqi", "phreeqc.out", "database.dat", "phreeqc.log"]}],
        metadata={
            "contract": CONTRACT,
            "scientific_evidence_level": "NUMERICALLY_VERIFIED",
            "scientific_result_qualified": False,
            "raw_output_hashes": dict(sorted(run.output_hashes.items())),
        },
    )
    verify_bundle(bundle.path)
    return bundle
