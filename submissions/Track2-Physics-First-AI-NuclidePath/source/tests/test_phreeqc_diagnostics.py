from dataclasses import replace

import pytest

from nuclear_agent.phreeqc_oracle import (
    NumericalOracleError,
    evaluate_phreeqc_numerical_oracle,
)
from nuclear_agent.phreeqc_scenario import (
    ScenarioCompileError,
    compile_phreeqc_scenario,
    diagnose_phreeqc_output,
    parse_phreeqc_selected_output,
)


def scenario():
    return {
        "site": {"radionuclide": "Cs-137"},
        "transport": {
            "initial_concentration_bq_m3": 1_000_000.0,
            "distance_m": 100.0,
            "evaluation_times_s": [0.0, 1_000_000.0],
            "distribution_coefficient_m3_kg": 0.2,
            "bulk_density_kg_m3": 1700.0,
            "porosity": 0.35,
            "groundwater_velocity_m_s": 1.0e-5,
            "dispersion_m2_s": 1.0e-5,
            "potassium_mg_l": 20.0,
            "competition_coefficient_l_mg": 0.01,
            "half_life_years": 30.018,
        },
        "phreeqc": {
            "water_density_kg_m3": 1000.0,
            "water": {
                "units": "mmol/kgw",
                "pH": 7.0,
                "pe": 12.0,
                "temperature_c": 25.0,
                "ions_mmol_kgw": {"K": 0.511, "Na": 1.0, "Ca": 0.6, "Cl": 2.711},
            },
            "exchange": {
                "cec_mmolc_kg": 100.0,
                "log_k": {"Cs": 1.2, "K": 0.4, "Na": 0.0, "Ca": 0.2},
            },
            "discretization": {"cells": 20},
            "provenance": {
                "water": "synthetic",
                "cec": "synthetic",
                "selectivity": "synthetic",
            },
        },
    }


def selected_output(*rows):
    header = "sim state soln dist_x time step pH mu K Cs K+ Cs+ KX CsX"
    return "\n".join([header, *rows]) + "\n"


def test_diagnostics_report_closure_fractions_and_empirical_comparison():
    compiled = compile_phreeqc_scenario(scenario())
    parsed = parse_phreeqc_selected_output(
        selected_output(
            "1 i_soln 1 -99 -99 -99 7.0 0.003 0.001 0.0 0.0009 0.0 0.1 0.0",
            "1 transp 1 100.0 1000000.0 20 7.1 0.004 0.001 0.0004 0.0009 0.0004 0.0001 0.0006",
        )
    )

    diagnostics = diagnose_phreeqc_output(compiled, parsed)
    row = diagnostics["rows"][1]

    assert diagnostics["diagnostic_version"] == "phreeqc-chemistry-diagnostic-2"
    assert diagnostics["status"] == "comparative-evidence-only"
    assert diagnostics["scientific_result_qualified"] is False
    assert row["dissolved_fraction"] == pytest.approx(0.4)
    assert row["exchange_fraction"] == pytest.approx(0.6)
    assert row["solution_total_relative_error"] == pytest.approx(0.0)
    assert row["apparent_kd_m3_kg"] == pytest.approx(0.0003088235294117647)
    assert row["apparent_retardation_factor"] == pytest.approx(2.5)
    assert row["comparison"]["empirical_effective_kd_m3_kg"] == pytest.approx(
        0.2 / 1.2
    )
    assert diagnostics["summary"]["rows_with_cs"] == 1
    assert diagnostics["summary"]["max_abs_solution_total_relative_error"] == pytest.approx(0.1)
    assert diagnostics["rows"][0]["components"]["K"]["solution_total_relative_error"] == pytest.approx(0.1)


def test_independent_numerical_oracle_is_machine_readable():
    compiled = compile_phreeqc_scenario(scenario())
    parsed = parse_phreeqc_selected_output(
        selected_output(
            "1 i_soln 1 -99 -99 -99 7.0 0.003 0.001 0.0 0.0009 0.0 0.1 0.0",
            "1 transp 1 100.0 1000000.0 20 7.1 0.004 "
            "0.001 0.0004 0.0009 0.0004 0.0001 0.0006",
        )
    )

    oracle = evaluate_phreeqc_numerical_oracle(compiled, parsed)

    assert oracle["oracle_version"] == "phreeqc-numerical-oracle-1"
    assert oracle["evidence_level"] == "NUMERICALLY_VERIFIED"
    assert oracle["status"] == "passed"
    assert oracle["scientific_result_qualified"] is False
    assert oracle["summary"]["rows_checked"] == 2
    assert oracle["summary"]["max_total_exchange_site_fraction"] < 1.0
    assert diagnose_phreeqc_output(compiled, parsed)["numerical_oracle"] == oracle


def test_independent_numerical_oracle_rejects_overfull_exchange_sites():
    compiled = compile_phreeqc_scenario(scenario())
    parsed = parse_phreeqc_selected_output(
        selected_output(
            "1 transp 1 100.0 1000000.0 20 7.1 0.004 "
            "0.001 0.0004 0.0009 0.0004 0.1 1.0"
        )
    )

    with pytest.raises(NumericalOracleError, match="occupancy"):
        evaluate_phreeqc_numerical_oracle(compiled, parsed)


def test_diagnostics_fails_closed_on_negative_chemistry_amount():
    compiled = compile_phreeqc_scenario(scenario())
    parsed = parse_phreeqc_selected_output(
        selected_output(
            "1 transp 1 100.0 1000000.0 20 7.1 0.004 "
            "0.001 0.001 0.0004 0.0001 0.05 0.05"
        )
    )
    invalid_row = replace(
        parsed.rows[0],
        aqueous_mol_kgw={**parsed.rows[0].aqueous_mol_kgw, "Cs": -0.0001},
    )
    parsed = replace(parsed, rows=(invalid_row,))
    with pytest.raises(ScenarioCompileError, match="non-negative"):
        diagnose_phreeqc_output(compiled, parsed)


def test_oracle_rejects_row_off_the_transport_grid():
    """Review finding: the parser verified shape but not semantic binding.

    A row whose distance or time is not on the declared transport grid must be
    rejected by the independent arithmetic oracle, even if it is structurally
    well-formed.
    """
    compiled = compile_phreeqc_scenario(scenario())
    # scenario(): 20 cells, 5 m cell length -> valid distances are 0..100 m
    parsed_ok = parse_phreeqc_selected_output(
        selected_output(
            "1 transp 1 100.0 1000000.0 20 7.1 0.004 "
            "0.001 0.0004 0.0009 0.0004 0.1 0.0"
        )
    )
    assert evaluate_phreeqc_numerical_oracle(compiled, parsed_ok)["status"] == "passed"

    # distance 101 m is off the grid (0..100 m in 5 m steps)
    bad_distance = replace(
        parsed_ok.rows[0], distance_m=101.0,
    )
    with pytest.raises(NumericalOracleError, match="off the transport grid"):
        evaluate_phreeqc_numerical_oracle(compiled, replace(parsed_ok, rows=(bad_distance,)))

    # time 1000500 s is off the time grid (time_step ~= 500000 s)
    bad_time = replace(
        parsed_ok.rows[0], time_s=1000500.0,
    )
    with pytest.raises(NumericalOracleError, match="off the transport time grid"):
        evaluate_phreeqc_numerical_oracle(compiled, replace(parsed_ok, rows=(bad_time,)))

    # decreasing step must be rejected
    bad_step = replace(
        parsed_ok.rows[0], step=19,
    )
    later = replace(parsed_ok.rows[0], step=18, time_s=1000000.0)
    with pytest.raises(NumericalOracleError, match="step decreases"):
        evaluate_phreeqc_numerical_oracle(compiled, replace(parsed_ok, rows=(bad_step, later)))
