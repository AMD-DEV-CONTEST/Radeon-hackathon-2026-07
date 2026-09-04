import copy
import math
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from nuclear_agent.scenario_v2 import (
    ScenarioInputV2,
    ScenarioInputV2Error,
    load_molar_masses,
    run_transport_contract_v2,
)
from nuclear_agent.contracts import run_transport_contract
from nuclear_agent.gcs import (
    PrimaryGCSState, calculate_primary_kd, load_primary_gcs_parameters,
)


def chemistry():
    return {ion: {"value_mg_l": value, "source": "https://example.test/chem", "classification": "measured"}
            for ion, value in {"K": 10.0, "Na": 2.0, "Ca": 4.0, "Mg": 3.0, "NH4": 1.0}.items()}


def payload(*radionuclides):
    return {
        "schema_version": "nuclidepath-multispecies-2.0",
        "scenario_id": "nested",
        "radionuclides": list(radionuclides),
        "chemistry": chemistry(),
        "distance_m": 10.0,
        "evaluation_times_s": [0.0, 1.0e7],
        "bulk_density_kg_m3": 1700.0,
        "porosity": 0.35,
        "groundwater_velocity_m_s": 1e-5,
        "dispersion_m2_s": 1e-5,
    }


def nuclide(name="Cs-137", c0=100.0, half=30.0, sorption=None):
    return {"name": name, "initial_concentration_bq_m3": c0, "half_life_years": half,
            "half_life_source": "https://example.test/half-life", "half_life_classification": "evaluated",
            "sorption": sorption or {"model": "linear_kd", "kd_m3_kg": 1.0,
                                      "source": "https://example.test/kd", "classification": "measured"}}


def test_nested_payload_produces_species_results_and_shared_chemistry():
    result = run_transport_contract_v2(payload(nuclide("Cs-137"), nuclide("Sr-90", half=28.8)))
    assert result["schema_version"] == "nuclidepath-multispecies-2.0"
    assert [x["radionuclide"] for x in result["species_results"]] == ["Cs-137", "Sr-90"]
    assert set(result["chemistry"]) == {"mg_l", "mol_l", "ion_provenance", "molar_mass_provenance"}
    assert result["chemistry"]["mg_l"]["Ca"] == 4.0
    assert result["chemistry"]["mol_l"]["Ca"] == pytest.approx(4e-3 / 40.078)
    assert result["chemistry"]["ion_provenance"]["Na"]["use"] == "used by primary GCS"
    assert result["chemistry"]["ion_provenance"]["NH4"]["use"] == "used by primary GCS on FES only"
    assert result["chemistry"]["ion_provenance"]["Ca"]["use"] == "effectively noncompetitive in primary-paper Cs GCS"


def test_validation_rejects_duplicates_unknowns_missing_zero_and_bad_numbers():
    with pytest.raises(ScenarioInputV2Error): run_transport_contract_v2(payload(nuclide("Cs-137"), nuclide("Cs-137")))
    bad = payload(nuclide())
    bad["chemistry"]["Na"]["extra"] = 1
    with pytest.raises(ScenarioInputV2Error): run_transport_contract_v2(bad)
    bad = payload(nuclide()); del bad["chemistry"]["Mg"]
    with pytest.raises(ScenarioInputV2Error): run_transport_contract_v2(bad)
    bad = payload(nuclide()); bad["chemistry"]["K"]["value_mg_l"] = 0
    assert run_transport_contract_v2(bad)["chemistry"]["mol_l"]["K"] == 0
    for value in (-1, float("nan"), True):
        bad = payload(nuclide()); bad["chemistry"]["K"]["value_mg_l"] = value
        with pytest.raises(ScenarioInputV2Error): run_transport_contract_v2(bad)


def test_gcs_only_cs_and_no_double_legacy_k_correction():
    gcs = {"model": "gcs_cs_k", "stable_cs_mol_l": 1e-8, "illite_mass_fraction": .2,
           "source": "https://example.test/gcs", "classification": "secondary"}
    result = run_transport_contract_v2(payload(nuclide("Cs-137", sorption=gcs)))
    assert result["species_results"][0]["sorption"]["model"] == "gcs_cs_k"
    assert result["species_results"][0]["transport_parameters"]["potassium_mg_l"] == 0
    assert result["species_results"][0]["transport_parameters"]["competition_coefficient_l_mg"] == 0
    assert result["species_results"][0]["sorption"]["gcs_provenance"]["basis"] == "primary_paper"
    assert result["species_results"][0]["sorption"]["competitor_treatment"]["NH4"].startswith("FES only")
    with pytest.raises(ScenarioInputV2Error): run_transport_contract_v2(payload(nuclide("Sr-90", sorption=gcs)))


def test_outputs_are_immutable_and_decay_is_independent():
    result = run_transport_contract_v2(payload(nuclide("Cs-137", half=10), nuclide("Sr-90", half=100)))
    with pytest.raises(TypeError): result["chemistry"]["mg_l"]["K"] = 3
    assert result["species_results"][0]["half_life_years"] == 10.0
    assert result["species_results"][1]["half_life_years"] == 100.0


def test_molar_mass_loader_validates_and_freezes():
    masses, provenance = load_molar_masses()
    assert set(masses) == {"K", "Na", "Ca", "Mg", "NH4"}
    assert provenance["schema_version"] == "1.0.0"
    with pytest.raises(TypeError): masses["K"] = 1


def test_direct_constructor_has_same_validation_and_deep_freeze():
    p = payload(nuclide())
    x = ScenarioInputV2(
        scenario_id=p["scenario_id"], radionuclides=p["radionuclides"], chemistry=p["chemistry"],
        distance_m=p["distance_m"], evaluation_times_s=p["evaluation_times_s"])
    with pytest.raises(TypeError): x.chemistry["K"]["value_mg_l"] = 99
    with pytest.raises(ScenarioInputV2Error):
        ScenarioInputV2(scenario_id="x", radionuclides=p["radionuclides"], chemistry=p["chemistry"],
                       distance_m=1, evaluation_times_s=[0, 0])


def test_porosity_is_a_probability_and_times_are_strictly_ordered_unique():
    for porosity in (-0.1, 1.01):
        p = payload(nuclide()); p["porosity"] = porosity
        with pytest.raises(ScenarioInputV2Error): run_transport_contract_v2(p)
    for times in ([1, 0], [0, 0]):
        p = payload(nuclide()); p["evaluation_times_s"] = times
        with pytest.raises(ScenarioInputV2Error): run_transport_contract_v2(p)


def test_molar_loader_fails_closed_for_non_object_and_bad_nested_records(tmp_path):
    for raw in ("[]", '{"masses": null}', '{"masses": {"K": "bad"}}'):
        f = tmp_path / "m.json"; f.write_text(raw)
        with pytest.raises((ValueError, ScenarioInputV2Error)):
            load_molar_masses(f)


def test_molar_loader_fails_closed_for_non_utf8_input(tmp_path):
    path = tmp_path / "invalid-encoding.json"
    path.write_bytes(b"\xff\xfe\x00")
    with pytest.raises(ValueError, match="malformed molar mass record"):
        load_molar_masses(path)


def test_molar_mass_provenance_is_explicit_and_conventional_nh4():
    masses, provenance = load_molar_masses()
    assert masses["NH4"] == pytest.approx(18.039)
    assert provenance["source_url"] == "https://ciaaw.org/atomic-weights.htm"
    assert provenance["source_version"]
    assert provenance["unit"] == "g/mol"
    assert provenance["nh4_components"]["N"] == 14.007
    assert provenance["nh4_components"]["H"] == 1.008


@pytest.mark.parametrize("bad", [
    lambda p: [p, p],
    lambda p: [{**p, "name": "Xe-999"}],
    lambda p: [{**p, "unexpected": 1}],
])
def test_direct_constructor_does_not_bypass_radionuclide_validation(bad):
    p = payload(nuclide())
    with pytest.raises(ScenarioInputV2Error):
        ScenarioInputV2("x", bad(p["radionuclides"][0]), p["chemistry"], 1, [0, 1])


def test_direct_constructor_does_not_bypass_chemistry_validation_or_caller_mutation():
    p = payload(nuclide())
    bad = copy.deepcopy(p["chemistry"]); bad["K"]["extra"] = 1
    with pytest.raises(ScenarioInputV2Error): ScenarioInputV2("x", p["radionuclides"], bad, 1, [0, 1])
    x = ScenarioInputV2("x", p["radionuclides"], p["chemistry"], 1, [0, 1])
    p["chemistry"]["K"]["value_mg_l"] = 999
    p["radionuclides"][0]["sorption"]["kd_m3_kg"] = 999
    assert x.chemistry["K"]["value_mg_l"] == 10.0
    assert x.radionuclides[0]["sorption"]["kd_m3_kg"] == 1.0


def test_all_ion_molar_conversions_are_mass_over_molar_mass():
    result = run_transport_contract_v2(payload(nuclide()))
    masses, _ = load_molar_masses()
    for ion in ("K", "Na", "Ca", "Mg", "NH4"):
        assert result["chemistry"]["mol_l"][ion] == pytest.approx(result["chemistry"]["mg_l"][ion] / 1000 / masses[ion])


def test_independent_half_lives_change_actual_decay_outputs():
    mobile = {"model": "linear_kd", "kd_m3_kg": 0.0,
              "source": "https://example.test/kd", "classification": "measured"}
    result = run_transport_contract_v2(
        payload(nuclide("Cs-137", half=10, sorption=mobile),
                nuclide("Sr-90", half=100, sorption=mobile))
    )
    cs_point = result["species_results"][0]["points"][-1]
    sr_point = result["species_results"][1]["points"][-1]
    assert cs_point["decay_factor"] < sr_point["decay_factor"]
    assert cs_point["concentration_bq_m3"] != sr_point["concentration_bq_m3"]


def test_gcs_kd_matches_independent_calculation_and_is_not_reduced_twice():
    gcs = {"model": "gcs_cs_k", "stable_cs_mol_l": 1e-8, "illite_mass_fraction": .2,
           "source": "https://example.test/gcs", "classification": "secondary"}
    case = payload(nuclide("Cs-137", sorption=gcs))
    result = run_transport_contract_v2(case)
    masses, _ = load_molar_masses()
    mol = {ion: case["chemistry"][ion]["value_mg_l"] / 1000 / masses[ion]
           for ion in ("K", "Na", "NH4")}
    parameter_path = Path(__file__).parents[1] / "src/nuclear_agent/data/parameters/bradbury_baeyens_gcs_v2.json"
    expected = calculate_primary_kd(
        load_primary_gcs_parameters(parameter_path),
        PrimaryGCSState(1e-8, mol["K"], mol["Na"], mol["NH4"], .2),
    ).bulk_kd_l_kg / 1000
    species = result["species_results"][0]
    assert species["points"][0]["effective_kd_m3_kg"] == pytest.approx(expected)
    assert species["transport_parameters"] == {
        "potassium_mg_l": 0, "competition_coefficient_l_mg": 0
    }


def test_v2_primary_gcs_uses_na_and_nh4_but_not_ca_or_mg():
    gcs = {"model": "gcs_cs_k", "stable_cs_mol_l": 1e-9, "illite_mass_fraction": 1.0,
           "source": "Bradbury and Baeyens 2000", "classification": "official"}
    base = payload(nuclide("Cs-137", sorption=gcs))
    base["chemistry"]["Na"]["value_mg_l"] = 0
    base["chemistry"]["NH4"]["value_mg_l"] = 0
    baseline = run_transport_contract_v2(base)["species_results"][0]["points"][0]["effective_kd_m3_kg"]
    for ion in ("Na", "NH4"):
        changed = copy.deepcopy(base); changed["chemistry"][ion]["value_mg_l"] = 1000
        value = run_transport_contract_v2(changed)["species_results"][0]["points"][0]["effective_kd_m3_kg"]
        assert value < baseline
    for ion in ("Ca", "Mg"):
        changed = copy.deepcopy(base); changed["chemistry"][ion]["value_mg_l"] = 1000
        value = run_transport_contract_v2(changed)["species_results"][0]["points"][0]["effective_kd_m3_kg"]
        assert value == pytest.approx(baseline)


def test_v2_execution_does_not_change_legacy_contract_behavior():
    legacy = {
        "scenario_id": "legacy-stability", "initial_concentration_bq_m3": 1e6,
        "distance_m": 10.0, "evaluation_times_s": [0.0, 1e8],
        "distribution_coefficient_m3_kg": 0.2,
    }
    before = run_transport_contract(legacy).to_dict()
    run_transport_contract_v2(payload(nuclide()))
    after = run_transport_contract(legacy).to_dict()
    assert after == before
