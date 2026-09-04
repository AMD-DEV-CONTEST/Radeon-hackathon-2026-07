import hashlib
import json
from pathlib import Path

import pytest

from nuclear_agent.phreeqc_scenario import (
    ScenarioCompileError,
    activity_bq_m3_to_mol_kgw,
    compile_phreeqc_scenario,
    cs137_specific_activity_bq_mol,
    diagnose_phreeqc_output,
    parse_phreeqc_selected_output,
    run_phreeqc_scenario,
    write_scenario_replay,
)


def scenario():
    return {
        "site": {"radionuclide": "Cs-137", "data_provenance": "demonstration"},
        "transport": {
            "initial_concentration_bq_m3": 1_000_000.0,
            "distance_m": 100.0,
            "evaluation_times_s": [0.0, 1_000_000.0, 2_000_000.0],
            "bulk_density_kg_m3": 1700.0,
            "porosity": 0.35,
            "groundwater_velocity_m_s": 1.0e-5,
            "dispersion_m2_s": 1.0e-5,
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
                "water": "synthetic demonstration water; not site data",
                "cec": "synthetic demonstration CEC; requires calibration",
                "selectivity": "synthetic demonstration log K; requires multi-cation Cs experiments",
            },
        },
    }


def selected_output(*rows):
    header = "sim state soln dist_x time step pH mu K Cs K+ Cs+ KX CsX"
    return "\n".join([header, *rows]) + "\n"


def test_activity_conversion_is_reversible_and_finite():
    specific = cs137_specific_activity_bq_mol()
    mol = activity_bq_m3_to_mol_kgw(1_000_000.0, half_life_years=30.018)
    assert specific > 0
    assert mol > 0
    assert mol * specific * 1000.0 == pytest.approx(1_000_000.0)


def test_compiler_emits_deterministic_transport_exchange_input():
    first = compile_phreeqc_scenario(scenario())
    second = compile_phreeqc_scenario(json.loads(json.dumps(scenario())))
    assert first.input_text == second.input_text
    assert first.canonical_payload() == second.canonical_payload()
    assert "SOLUTION_MASTER_SPECIES" in first.input_text
    assert "Cs+ + X- = CsX" in first.input_text
    assert "K+ + X- = KX" in first.input_text
    assert "TRANSPORT" in first.input_text
    assert "-totals             Cs K Na Ca" in first.input_text
    assert first.metadata["scientific_result_qualified"] is False
    assert first.metadata["transport_mapping"]["shifts"] == 4
    assert "evaluation_time_policy" in first.metadata
    assert first.metadata["transport_mapping"]["cells"] == 20
    assert first.metadata["exchange"]["exchange_sites_mol_kgw"] == pytest.approx(
        100e-3 * 1700.0 / (0.35 * 1000.0)
    )


@pytest.mark.parametrize(
    "mutator, message",
    [
        (lambda s: s["phreeqc"].pop("exchange"), "phreeqc.exchange"),
        (lambda s: s["phreeqc"]["exchange"]["log_k"].pop("Cs"), "include Cs"),
        (lambda s: s["phreeqc"]["exchange"].update({"log_k": {"Cs": 1.2}}), "at least one competitor"),
        (lambda s: s["phreeqc"]["water"]["ions_mmol_kgw"].update({"Hg": 1.0}), "unsupported"),
        (lambda s: s["transport"].update({"groundwater_velocity_m_s": 0.0}), "must be positive"),
        (lambda s: s["phreeqc"]["exchange"].update({"cec_mmolc_kg": 0.0}), "must be positive"),
    ],
)
def test_compiler_fails_closed_on_invalid_scenarios(mutator, message):
    value = json.loads(json.dumps(scenario()))
    mutator(value)
    with pytest.raises(ScenarioCompileError, match=message):
        compile_phreeqc_scenario(value)


def test_compiler_disables_phreeqc_default_selected_output_columns():
    compiled = compile_phreeqc_scenario(scenario())
    for option in ("pe", "reaction", "temperature", "alkalinity", "water",
                   "charge_balance", "percent_error"):
        line = next(line for line in compiled.input_text.splitlines()
                    if line.strip().startswith(f"-{option}"))
        assert line.split()[-1] == "false"


def test_compiler_rejects_non_string_names_and_nonphysical_values():
    value = json.loads(json.dumps(scenario()))
    value["phreeqc"]["water"]["ions_mmol_kgw"] = {1: 1.0}
    with pytest.raises(ScenarioCompileError, match="component names must be strings"):
        compile_phreeqc_scenario(value)

    value = json.loads(json.dumps(scenario()))
    value["phreeqc"]["exchange"]["log_k"] = {"Cs": 1.2, 1: 0.0}
    with pytest.raises(ScenarioCompileError, match="log_k names must be strings"):
        compile_phreeqc_scenario(value)

    for field in (
        "distribution_coefficient_m3_kg",
        "potassium_mg_l",
        "competition_coefficient_l_mg",
    ):
        value = json.loads(json.dumps(scenario()))
        value["transport"].update({
            "distribution_coefficient_m3_kg": 0.2,
            "potassium_mg_l": 20.0,
            "competition_coefficient_l_mg": 0.01,
        })
        value["transport"][field] = -1.0
        with pytest.raises(ScenarioCompileError, match=field):
            compile_phreeqc_scenario(value)

    value = json.loads(json.dumps(scenario()))
    value["transport"]["bulk_density_kg_m3"] = 0.0
    with pytest.raises(ScenarioCompileError, match="bulk_density"):
        compile_phreeqc_scenario(value)

    value = json.loads(json.dumps(scenario()))
    value["transport"].update({
        "groundwater_velocity_m_s": 1e-308,
        "dispersion_m2_s": 1e308,
    })
    with pytest.raises(ScenarioCompileError, match="derived PHREEQC"):
        compile_phreeqc_scenario(value)

    value = json.loads(json.dumps(scenario()))
    value["transport"]["bulk_density_kg_m3"] = 1e308
    value["phreeqc"]["exchange"]["cec_mmolc_kg"] = 1e308
    with pytest.raises(ScenarioCompileError, match="derived PHREEQC exchange sites"):
        compile_phreeqc_scenario(value)


def test_compiler_rejects_off_grid_and_unbounded_time_requests():
    value = json.loads(json.dumps(scenario()))
    value["transport"]["evaluation_times_s"] = [0.0, 1_000_001.0]
    with pytest.raises(ScenarioCompileError, match="time_step grid"):
        compile_phreeqc_scenario(value)

    value = json.loads(json.dumps(scenario()))
    value["transport"]["evaluation_times_s"] = [0.0, 60_000_000_000.0]
    with pytest.raises(ScenarioCompileError, match="more than 100000"):
        compile_phreeqc_scenario(value)




def test_selected_output_parser_preserves_exchange_and_aqueous_columns():
    parsed = parse_phreeqc_selected_output(selected_output(
        "1 i_soln 1 -99 -99 -99 7.0 0.003 0.001 0.0 0.0009 0.0 0.1 0.0",
        "1 transp 1 100.0 10000000.0 20 7.1 0.004 0.0008 0.0002 0.0007 0.0001 0.05 0.05",
    ))
    assert len(parsed.rows) == 2
    assert parsed.rows[1].state == "transp"
    assert parsed.rows[1].cs_exchange_mol_kgw == pytest.approx(0.05)
    assert parsed.rows[1].distance_m == pytest.approx(100.0)



def test_selected_output_parser_normalizes_phreeqc_molality_prefix():
    parsed = parse_phreeqc_selected_output(
        "sim state soln dist_x time step pH mu K Cs m_K+ m_Cs+ m_KX m_CsX\n"
        "1 transp 1 100.0 1000000.0 20 7.1 0.004 "
        "0.001 0.0004 0.0009 0.0004 0.0001 0.0006\n"
    )
    assert parsed.columns[-4:] == ("K+", "Cs+", "KX", "CsX")


def test_selected_output_parser_rejects_negative_ionic_strength():
    with pytest.raises(ScenarioCompileError, match="ionic_strength"):
        parse_phreeqc_selected_output(selected_output(
            "1 transp 1 100.0 1.0 1 7.0 -0.004 0.0008 0.0009 0.0007 0.0009 0.0001 0.0002"
        ))


def test_selected_output_parser_rejects_negative_chemistry_values():
    with pytest.raises(ScenarioCompileError, match="non-negative"):
        parse_phreeqc_selected_output(selected_output(
            "1 transp 1 100.0 1.0 1 7.0 0.004 -0.0008 0.001 "
            "0.0007 0.0009 0.0001 0.0002"
        ))


def test_selected_output_parser_rejects_nonfinite_values_and_schema_changes():
    with pytest.raises(ScenarioCompileError, match="non-finite"):
        parse_phreeqc_selected_output(selected_output(
            "1 transp 1 100.0 1.0 1 7.0 0.004 0.0 nan 0.0 0.0 0.0 0.0"
        ))
    with pytest.raises(ScenarioCompileError, match="header mismatch"):
        parse_phreeqc_selected_output("sim state\n1 transp\n")


def test_compiled_input_hash_is_path_independent():
    compiled = compile_phreeqc_scenario(scenario())
    digest = hashlib.sha256(compiled.input_text.encode()).hexdigest()
    assert compiled.canonical_payload()["input_sha256"] == digest


def central_oklahoma_brine_case():
    value = scenario()
    value["site"]["site_id"] = "central-oklahoma-example14-brine"
    value["transport"].update({
        "bulk_density_kg_m3": 2700.0,
        "porosity": 0.22,
    })
    value["phreeqc"]["water"].update({"pH": 5.713, "pe": 4.0})
    value["phreeqc"]["water"]["ions_mmol_kgw"] = {
        "Ca": 465.5,
        "Mg": 160.9,
        "Na": 5402.0,
        "Cl": 6642.0,
        "C": 3.96,
        "S": 4.725,
    }
    value["phreeqc"]["exchange"]["log_k"] = {
        "Cs": 1.2,
        "Na": 0.0,
        "Ca": 0.8,
        "Mg": 0.6,
    }
    value["phreeqc"]["provenance"].update({
        "water_source": "USGS PHREEQC Example 14, Central Oklahoma aquifer",
        "selectivity_source": "PHREEQC phreeqc.dat for Na/Ca/Mg; Cs requires calibration",
    })
    return value


def test_compiler_supports_k_free_multicomponent_case_and_diagnostics():
    compiled = compile_phreeqc_scenario(central_oklahoma_brine_case())
    assert compiled.metadata["exchange"]["exchange_ions"] == ["Cs", "Na", "Ca", "Mg"]
    assert compiled.metadata["exchange"]["competitor_ions"] == ["Ca", "Mg", "Na"]
    assert "-totals             Cs Na Ca Mg" in compiled.input_text
    assert "-molalities         Cs+ Na+ Ca+2 Mg+2 CsX NaX CaX2 MgX2" in compiled.input_text
    assert "K+" not in compiled.input_text

    parsed = parse_phreeqc_selected_output(
        "sim state soln dist_x time step pH mu Cs Na Ca Mg Cs+ Na+ Ca+2 Mg+2 CsX NaX CaX2 MgX2\n"
        "1 transp 1 100.0 10000000.0 20 7.1 0.004 "
        "0.0008 0.0010 0.0006 0.0005 0.0007 0.0009 0.0001 0.0002 "
        "0.05 0.04 0.03 0.02\n",
        exchange_ions=("Cs", "Na", "Ca", "Mg"),
    )
    diagnostics = diagnose_phreeqc_output(compiled, parsed)
    assert diagnostics["summary"]["competitor_ions"] == ["Na", "Ca", "Mg"]
    assert diagnostics["rows"][0]["components"]["Ca"]["exchange_site_fraction"] > 0
    assert "K" not in diagnostics["summary"]["exchange_ions"]


def test_bounded_runner_parses_output_and_writes_replay(tmp_path):
    executable = tmp_path / "fake-phreeqc"
    executable.write_text(
        "#!/bin/sh\n"
        "cat > nuclidepath.sel <<'EOF'\n"
        "sim state soln dist_x time step pH mu Cs K Na Ca Cs+ K+ Na+ Ca+2 CsX KX NaX CaX2\n"
        "1 i_soln 1 -99 -99 -99 7.0 0.003 0.0 0.001 0.0006 0.0005 0.0 0.0009 0.0005 0.0004 0.1 0.0 0.0 0.0\n"
        "1 transp 1 100.0 10000000.0 20 7.1 0.004 0.0002 0.0008 0.0006 0.0005 0.0001 0.0007 0.0005 0.0004 0.05 0.05 0.04 0.03\n"
        "EOF\n"
        ": > \"$2\"\n"
        ": > \"$4\"\n"
        "echo 'PHREEQC scenario fixture'\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    database = tmp_path / "database.dat"
    database.write_text("database fixture\n", encoding="utf-8")
    run_root = tmp_path / "run-root"
    run_root.mkdir()
    compiled = compile_phreeqc_scenario(scenario())
    run = run_phreeqc_scenario(
        compiled,
        executable=executable,
        database=database,
        executable_sha256=hashlib.sha256(executable.read_bytes()).hexdigest(),
        database_sha256=hashlib.sha256(database.read_bytes()).hexdigest(),
        working_directory=run_root,
    )
    assert run.process.exit_status == 0
    assert run.selected_output.rows[-1].state == "transp"
    assert set(run.output_hashes) == {"nuclidepath.sel", "phreeqc.out", "phreeqc.log"}
    bundle = write_scenario_replay(tmp_path / "bundle", run)
    assert (bundle.path / "manifest.json").is_file()
