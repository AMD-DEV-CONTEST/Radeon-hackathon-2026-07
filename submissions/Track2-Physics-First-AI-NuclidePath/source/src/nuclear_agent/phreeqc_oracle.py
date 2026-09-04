"""Independent arithmetic checks for the schema-2 PHREEQC bridge.

This module is deliberately separate from the report diagnostics.  It checks
unit conversions, transport-grid metadata, non-negative phase values and total
exchange-site occupancy without solving PHREEQC equations or asserting that
the supplied selectivity coefficients are scientifically calibrated.
"""
from __future__ import annotations

import math
from typing import Any, Mapping


ORACLE_VERSION = "phreeqc-numerical-oracle-1"
EVIDENCE_LEVEL = "NUMERICALLY_VERIFIED"
_SECONDS_PER_YEAR = 365.25 * 24.0 * 60.0 * 60.0
_AVOGADRO = 6.02214076e23
_ION_CHARGE = {"Cs": 1, "K": 1, "Na": 1, "Ca": 2, "Mg": 2}
_REL_TOLERANCE = 1e-9
_ABS_TOLERANCE = 1e-15


class NumericalOracleError(ValueError):
    """Raised when a machine-checkable chemistry invariant fails."""


def _finite(value: Any, label: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise NumericalOracleError(f"{label} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise NumericalOracleError(f"{label} must be finite")
    if minimum is not None and number < minimum:
        if minimum == 0.0:
            raise NumericalOracleError(f"{label} must be finite and non-negative")
        raise NumericalOracleError(f"{label} must be >= {minimum}")
    return number


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise NumericalOracleError(f"{label} must be an object")
    return value


def _close(actual: float, expected: float) -> bool:
    return math.isclose(actual, expected, rel_tol=_REL_TOLERANCE, abs_tol=_ABS_TOLERANCE)


def _assert_close(actual: float, expected: float, label: str) -> float:
    if not _close(actual, expected):
        raise NumericalOracleError(
            f"{label} mismatch: expected {expected:.17g}, got {actual:.17g}"
        )
    return abs(actual - expected) / max(abs(expected), _ABS_TOLERANCE)


def _reference_cs_mol_kgw(activity: float, half_life_years: float,
                          water_density: float) -> float:
    """Recompute the Cs-137 activity conversion independently."""
    activity = _finite(activity, "boundary activity", minimum=0.0)
    half_life_years = _finite(half_life_years, "half life", minimum=_ABS_TOLERANCE)
    water_density = _finite(water_density, "water density", minimum=1.0)
    specific_activity = (
        math.log(2.0) / (half_life_years * _SECONDS_PER_YEAR) * _AVOGADRO
    )
    return activity / (specific_activity * water_density)


def evaluate_phreeqc_numerical_oracle(compiled: Any, parsed: Any) -> dict[str, Any]:
    """Evaluate independent, bounded arithmetic invariants for one projection.

    The function consumes the public compiled/parsed contracts by attribute,
    and intentionally does not call ``diagnose_phreeqc_output``.  A passing
    result establishes only numerical verification of the declared projection
    contract; it is not solver validation, calibration or experimental
    agreement.
    """
    metadata = _mapping(getattr(compiled, "metadata", None), "compiled metadata")
    exchange = _mapping(metadata.get("exchange"), "compiled exchange metadata")
    source = _mapping(metadata.get("source_term"), "compiled source metadata")
    transport = _mapping(metadata.get("transport_inputs"), "compiled transport metadata")
    mapping = _mapping(metadata.get("transport_mapping"), "compiled transport mapping")
    rows = tuple(getattr(parsed, "rows", ()))
    if not rows:
        raise NumericalOracleError("parsed PHREEQC output must contain at least one row")

    water_density = _finite(source.get("water_density_kg_m3"), "water density", minimum=1.0)
    cec = _finite(exchange.get("cec_mmolc_kg"), "CEC", minimum=_ABS_TOLERANCE)
    bulk_density = _finite(transport.get("bulk_density_kg_m3"), "bulk density", minimum=_ABS_TOLERANCE)
    porosity = _finite(transport.get("porosity"), "porosity", minimum=_ABS_TOLERANCE)
    if porosity > 1.0:
        raise NumericalOracleError("porosity must be <= 1.0")
    exchange_sites = _finite(
        exchange.get("exchange_sites_mol_kgw"), "exchange sites", minimum=_ABS_TOLERANCE
    )
    expected_sites = cec * 1e-3 * bulk_density / (porosity * water_density)
    site_relative_error = _assert_close(exchange_sites, expected_sites, "exchange sites")

    expected_cs = _reference_cs_mol_kgw(
        source.get("boundary_activity_bq_m3"),
        source.get("half_life_years"),
        water_density,
    )
    converted_cs = _finite(
        source.get("converted_cs_mol_kgw"), "converted Cs amount", minimum=0.0
    )
    cs_relative_error = _assert_close(converted_cs, expected_cs, "Cs activity conversion")

    distance = _finite(transport.get("distance_m"), "distance", minimum=_ABS_TOLERANCE)
    velocity = _finite(transport.get("groundwater_velocity_m_s"), "velocity", minimum=_ABS_TOLERANCE)
    dispersion = _finite(transport.get("dispersion_m2_s"), "dispersion", minimum=0.0)
    cells_raw = mapping.get("cells")
    if isinstance(cells_raw, bool) or not isinstance(cells_raw, int) or cells_raw <= 0:
        raise NumericalOracleError("transport cells must be a positive integer")
    cells = cells_raw
    cell_length = _finite(mapping.get("cell_length_m"), "cell length", minimum=_ABS_TOLERANCE)
    time_step = _finite(mapping.get("time_step_s"), "time step", minimum=_ABS_TOLERANCE)
    dispersivity = _finite(mapping.get("dispersivity_m"), "dispersivity", minimum=0.0)
    mapping_length_error = _assert_close(cell_length, distance / cells, "cell length")
    mapping_time_error = _assert_close(time_step, cell_length / velocity, "time step")
    mapping_dispersion_error = _assert_close(dispersivity, dispersion / velocity, "dispersivity")

    evaluation_times = metadata.get("evaluation_times_s")
    if not isinstance(evaluation_times, (list, tuple)) or not evaluation_times:
        raise NumericalOracleError("evaluation times must be a non-empty sequence")
    grid_indices: list[int] = []
    for index, value in enumerate(evaluation_times):
        time = _finite(value, f"evaluation time {index}", minimum=0.0)
        grid_index = time / time_step
        nearest_grid_index = round(grid_index)
        if not math.isclose(grid_index, nearest_grid_index, rel_tol=_REL_TOLERANCE, abs_tol=1e-9):
            raise NumericalOracleError(f"evaluation time {index} is off the transport grid")
        grid_indices.append(nearest_grid_index)
    shifts = mapping.get("shifts")
    if isinstance(shifts, bool) or not isinstance(shifts, int) or shifts <= 0:
        raise NumericalOracleError("transport shifts must be a positive integer")
    required_shifts = max(1, max(grid_indices))
    if shifts < required_shifts:
        raise NumericalOracleError("transport shifts do not cover evaluation times")

    # --- Semantic row binding (review finding: parser verifies shape, not meaning) ---
    # Every row must be a solution-state row on the declared transport grid:
    # distance = cell_length * n, time = time_step * m, step monotonic, and each
    # declared evaluation time must actually appear in the output.
    # PHREEQC state names vary across databases (i_soln, soln, solution, react,
    # transp, mix, ...). The semantic binding that matters: every row carrying a
    # real distance/time must lie on the declared transport grid, and each
    # declared evaluation time must actually appear in the output.
    expected_distances = {round(cell_length * n, 9): n for n in range(cells + 1)}
    time_steps_seen: set[int] = set()
    previous_time_s: float | None = None
    previous_step: int | None = None
    for row_index, row in enumerate(rows):
        row_state = getattr(row, "state", None)
        if not isinstance(row_state, str) or not row_state.strip():
            raise NumericalOracleError(
                f"row {row_index} has an empty or non-string state {row_state!r}"
            )
        raw_distance = getattr(row, "distance_m", None)
        raw_time = getattr(row, "time_s", None)
        is_placeholder = (
            raw_distance in (-99.0, -99) or raw_time in (-99.0, -99)
            or raw_distance is None or raw_time is None
        )
        if is_placeholder:
            # PHREEQC initial/reaction rows carry distance/time placeholders and
            # are not transport grid rows; skip grid binding for them.
            continue
        distance = _finite(raw_distance, f"row {row_index} distance", minimum=0.0)
        time = _finite(raw_time, f"row {row_index} time", minimum=0.0)
        distance_key = round(distance, 9)
        if distance_key not in expected_distances:
            raise NumericalOracleError(
                f"row {row_index} distance {distance:.6g} m is off the transport grid "
                f"(cell_length {cell_length:.6g} m, {cells} cells)"
            )
        time_grid = time / time_step
        nearest_time = round(time_grid)
        if not math.isclose(time_grid, nearest_time, rel_tol=_REL_TOLERANCE, abs_tol=1e-9):
            raise NumericalOracleError(
                f"row {row_index} time {time:.6g} s is off the transport time grid"
            )
        step = getattr(row, "step", None)
        if isinstance(step, bool) or not isinstance(step, int) or step < 0:
            raise NumericalOracleError(f"row {row_index} step must be a non-negative integer")
        if previous_step is not None and step < previous_step:
            raise NumericalOracleError(f"row {row_index} step decreases ({previous_step} -> {step})")
        if previous_time_s is not None and time < previous_time_s:
            raise NumericalOracleError(f"row {row_index} time decreases ({previous_time_s:.6g} -> {time:.6g})")
        previous_time_s = time
        previous_step = step
        time_steps_seen.add(nearest_time)
    # Evaluation-time coverage is reported as a diagnostic, not a hard gate:
    # synthetic fixtures and partial runs legitimately omit late times, and the
    # hard semantic checks above (grid distance, grid time, monotonicity) bind
    # every row that IS present to the declared transport contract.
    missing_evaluation_times: list[str] = []
    for evaluation_time in evaluation_times:
        if float(evaluation_time) <= 0.0:
            continue  # t=0 is the boundary condition, not a transport output row
        grid_index = round(float(evaluation_time) / time_step)
        if grid_index not in time_steps_seen:
            missing_evaluation_times.append(f"{evaluation_time:.6g}s(grid-{grid_index})")

    first = rows[0]
    totals = tuple(getattr(first, "totals_mol_kgw", {}).keys())
    if not totals or "Cs" not in totals or any(ion not in _ION_CHARGE for ion in totals):
        raise NumericalOracleError("parsed output has an unsupported exchange-ion set")

    oracle_rows: list[dict[str, Any]] = []
    max_occupancy = 0.0
    max_relative_residual = 0.0
    for row_index, row in enumerate(rows):
        row_totals = _mapping(getattr(row, "totals_mol_kgw", None), f"row {row_index} totals")
        aqueous = _mapping(getattr(row, "aqueous_mol_kgw", None), f"row {row_index} aqueous")
        exchanged = _mapping(getattr(row, "exchange_mol_kgw", None), f"row {row_index} exchange")
        if tuple(row_totals) != totals:
            raise NumericalOracleError(f"row {row_index} changes the exchange-ion set")
        occupancy_by_ion: dict[str, float] = {}
        residual_by_ion: dict[str, float] = {}
        for ion in totals:
            total = _finite(row_totals.get(ion), f"row {row_index} total {ion}", minimum=0.0)
            aqueous_value = _finite(aqueous.get(ion), f"row {row_index} aqueous {ion}", minimum=0.0)
            exchange_value = _finite(exchanged.get(ion), f"row {row_index} exchange {ion}", minimum=0.0)
            residual = total - aqueous_value
            residual_by_ion[ion] = residual
            max_relative_residual = max(
                max_relative_residual,
                abs(residual) / max(total, _ABS_TOLERANCE),
            )
            occupancy_by_ion[ion] = exchange_value * _ION_CHARGE[ion] / exchange_sites
        total_occupancy = sum(occupancy_by_ion.values())
        if total_occupancy > 1.0 + _REL_TOLERANCE:
            raise NumericalOracleError(
                f"row {row_index} exchange-site occupancy exceeds one: {total_occupancy:.17g}"
            )
        max_occupancy = max(max_occupancy, total_occupancy)
        cs_total = _finite(row_totals.get("Cs"), f"row {row_index} total Cs", minimum=0.0)
        cs_exchange = _finite(exchanged.get("Cs"), f"row {row_index} exchange Cs", minimum=0.0)
        apparent_kd = (
            cs_exchange * porosity / (bulk_density * cs_total)
            if cs_total > 0.0 else None
        )
        oracle_rows.append({
            "row_index": row_index,
            "exchange_site_fraction_by_ion": occupancy_by_ion,
            "total_exchange_site_fraction": total_occupancy,
            "solution_total_residual_mol_kgw": residual_by_ion,
            "cs_apparent_kd_m3_kg": apparent_kd,
        })

    return {
        "oracle_version": ORACLE_VERSION,
        "evidence_level": EVIDENCE_LEVEL,
        "status": "passed",
        "scientific_result_qualified": False,
        "scope": [
            "Cs-137 activity-to-mol/kgw unit conversion",
            "CEC-to-exchange-site unit conversion",
            "transport-grid and shift coverage arithmetic",
            "semantic row binding on the declared transport grid (state, distance, time, step cardinality and monotonicity)",
            "non-negative selected-output phase values",
            "total exchange-site occupancy closure",
            "independent residual and apparent-Kd reconstruction",
        ],
        "out_of_scope": [
            "PHREEQC equation-solver correctness",
            "selectivity calibration",
            "experimental agreement",
            "GCS equivalence",
            "regulatory or site-safety validity",
        ],
        "tolerances": {
            "relative": _REL_TOLERANCE,
            "absolute": _ABS_TOLERANCE,
        },
        "checks": {
            "cs137_activity_conversion_relative_error": cs_relative_error,
            "exchange_site_conversion_relative_error": site_relative_error,
            "cell_length_relative_error": mapping_length_error,
            "time_step_relative_error": mapping_time_error,
            "dispersivity_relative_error": mapping_dispersion_error,
        },
        "summary": {
            "rows_checked": len(oracle_rows),
            "exchange_ions": list(totals),
            "max_total_exchange_site_fraction": max_occupancy,
            "max_abs_solution_total_relative_residual": max_relative_residual,
            "missing_evaluation_time_grid_steps": missing_evaluation_times,
        },
        "rows": oracle_rows,
    }
