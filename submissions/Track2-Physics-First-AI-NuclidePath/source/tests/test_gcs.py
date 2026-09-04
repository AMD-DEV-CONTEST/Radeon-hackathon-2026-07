import json
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from nuclear_agent.gcs import CsKState, load_illite_parameters, calculate_kd

DATA = Path(__file__).parents[1] / "src/nuclear_agent/data/parameters/illite_du_puy_cs_k_v1.json"


def test_loader_transparently_normalizes_rounded_site_percentages():
    params = load_illite_parameters(DATA)
    assert params.source_rounding_policy == "derive_residual_planar"
    assert math.isclose(sum(site.capacity_fraction for site in params.sites), 1.0)
    assert params.provenance["basis"] == "secondary_transcription"
    assert params.provenance["primary_paper_verified"] is False


def test_units_and_finite_positive_validation():
    params = load_illite_parameters(DATA)
    assert params.cec_unit == "mol_charge/kg"
    assert params.sites[0].capacity_unit == "mol_charge/kg"
    with pytest.raises(ValueError):
        CsKState(potassium_mol_l=0, cesium_mol_l=1e-9, illite_mass_fraction=0.5)
    with pytest.raises(ValueError):
        CsKState(potassium_mol_l=1e-3, cesium_mol_l=math.nan, illite_mass_fraction=0.5)


def test_occupancy_bounds_mass_balance_and_limits():
    params = load_illite_parameters(DATA)
    result = calculate_kd(params, CsKState(1e-3, 1e-9, 0.5))
    assert all(0 <= x <= site.capacity_mol_charge_per_kg for x, site in zip(result.occupancies, params.sites))
    assert math.isclose(sum(result.occupancies), result.total_sorbed_cs_mol_per_kg)
    high_k = calculate_kd(params, CsKState(1.0, 1e-9, 1.0))
    low_k = calculate_kd(params, CsKState(1e-6, 1e-9, 1.0))
    assert high_k.illite_kd_l_kg < low_k.illite_kd_l_kg
    assert calculate_kd(params, CsKState(1e-3, 1e-9, 0)).bulk_kd_l_kg == 0
    same_state = calculate_kd(params, CsKState(1.0, 1e-9, 1))
    assert same_state.bulk_kd_l_kg == same_state.illite_kd_l_kg


def test_trace_limit_matches_capacity_weighted_kc_over_k():
    params = load_illite_parameters(DATA)
    state = CsKState(1e-3, 1e-18, 1.0)
    result = calculate_kd(params, state)
    expected = sum(s.capacity_mol_charge_per_kg * s.kc / state.potassium_mol_l for s in params.sites)
    assert math.isclose(result.illite_kd_l_kg, expected, rel_tol=1e-8)


def test_unsupported_chemistry_fails_closed_and_result_provenance_is_immutable():
    params = load_illite_parameters(DATA)
    with pytest.raises(ValueError):
        calculate_kd(params, CsKState(1e-3, 1e-9, 1.0, competitor="Na"))
    result = calculate_kd(params, CsKState(1e-3, 1e-9, 1.0))
    with pytest.raises(TypeError):
        result.provenance["basis"] = "changed"
    with pytest.raises(TypeError):
        result.provenance["nested"] = {}


def test_incomplete_or_malformed_provenance_fails_closed(tmp_path):
    data = json.loads(DATA.read_text())
    del data["provenance"]["basis"]
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        load_illite_parameters(path)


def _variant(tmp_path, **changes):
    data = json.loads(DATA.read_text())
    data.update(changes)
    path = tmp_path / "variant.json"
    path.write_text(json.dumps(data))
    return path


def test_source_percentages_are_preserved_and_planar_is_residual():
    params = load_illite_parameters(DATA)
    assert [s.capacity_fraction * 100 for s in params.sites] == [0.25, 20.0, 79.75]


@pytest.mark.parametrize("field,value", [("schema_version", "9.0.0"), ("material", "smectite"),
                                           ("cec_unit", "mol/kg"), ("source_rounding_policy", "normalize")])
def test_wrong_top_level_contract_is_value_error(tmp_path, field, value):
    with pytest.raises(ValueError):
        load_illite_parameters(_variant(tmp_path, **{field: value}))


def test_duplicate_or_wrong_site_names_are_value_error(tmp_path):
    data = json.loads(DATA.read_text())
    data["sites"][1]["name"] = "FES"
    path = tmp_path / "dup.json"; path.write_text(json.dumps(data))
    with pytest.raises(ValueError): load_illite_parameters(path)
    data["sites"][1]["name"] = "wrong"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError): load_illite_parameters(path)


@pytest.mark.parametrize("field,value", [("cec", True), ("cec", math.inf), ("cec", -math.inf),
                                           ("cec", math.nan)])
def test_boolean_or_nonfinite_cec_is_value_error(tmp_path, field, value):
    with pytest.raises(ValueError): load_illite_parameters(_variant(tmp_path, **{field: value}))


def test_boolean_or_overflowing_site_numbers_are_value_error(tmp_path):
    data = json.loads(DATA.read_text()); data["sites"][0]["log10_kc_cs_k"] = True
    path = tmp_path / "bad.json"; path.write_text(json.dumps(data))
    with pytest.raises(ValueError): load_illite_parameters(path)
    data["sites"][0]["log10_kc_cs_k"] = 400
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError): load_illite_parameters(path)


def test_direct_mutable_provenance_is_defensively_frozen():
    provenance = {
        "basis": "secondary_transcription", "source": "source",
        "tables": ["Table 1"], "primary_paper_verified": False,
        "notes": {"nested": []},
    }
    from nuclear_agent.gcs import IlliteParameters, Site, KdResult
    params = IlliteParameters("Illite du Puy", .2, "mol_charge/kg", "derive_residual_planar",
                              (Site("FES", 1, .0025, .0005),
                               Site("type-II", 1, .2, .04),
                               Site("planar", 1, .7975, .1595)), provenance)
    provenance["notes"]["nested"].append("changed")
    assert params.provenance["notes"]["nested"] == ()
    result = KdResult((1.0,), 1.0, 1.0, 1.0, provenance)
    provenance["notes"]["nested"].append("again")
    assert result.provenance["notes"]["nested"] == ("changed",)


@pytest.mark.parametrize("k,cs", [(1e-3, 1e308), (1e308, 1e-308)])
def test_extreme_finite_inputs_never_return_nonfinite(k, cs):
    params = load_illite_parameters(DATA)
    try:
        result = calculate_kd(params, CsKState(k, cs, 1.0))
    except ValueError:
        return
    assert all(math.isfinite(x) for x in (*result.occupancies, result.total_sorbed_cs_mol_per_kg,
                                           result.illite_kd_l_kg, result.bulk_kd_l_kg))


def test_direct_public_dataclasses_reject_invalid_scientific_state():
    from nuclear_agent.gcs import IlliteParameters, Site, KdResult

    provenance = {
        "basis": "secondary_transcription",
        "source": "source",
        "tables": ("Table 1",),
        "primary_paper_verified": False,
    }
    valid_sites = (
        Site("FES", 10.0, 0.0025, 0.0005),
        Site("type-II", 2.0, 0.2, 0.04),
        Site("planar", 1.0, 0.7975, 0.1595),
    )
    invalid_params = [
        ("wrong", 0.2, "mol_charge/kg", "derive_residual_planar", valid_sites),
        ("Illite du Puy", math.nan, "mol_charge/kg", "derive_residual_planar", valid_sites),
        ("Illite du Puy", 0.2, "mol/kg", "derive_residual_planar", valid_sites),
        ("Illite du Puy", 0.2, "mol_charge/kg", "normalize", valid_sites),
        ("Illite du Puy", 0.2, "mol_charge/kg", "derive_residual_planar", ()),
    ]
    for values in invalid_params:
        with pytest.raises(ValueError):
            IlliteParameters(*(values + (provenance,)))

    with pytest.raises(ValueError):
        IlliteParameters(
            "Illite du Puy", 0.2, "mol_charge/kg", "derive_residual_planar",
            (Site("FES", 10.0, 1.0, 0.1), Site("type-II", 2.0, 1.0, 0.1),
             Site("planar", 1.0, 1.0, 0.1)), provenance,
        )
    with pytest.raises(ValueError):
        KdResult((math.nan,), 1.0, 1.0, 1.0, provenance)
    with pytest.raises(ValueError):
        KdResult((0.1,), math.inf, 1.0, 1.0, provenance)


def test_calculate_rejects_direct_parameters_with_inconsistent_capacity():
    from nuclear_agent.gcs import IlliteParameters, Site

    provenance = {
        "basis": "secondary_transcription", "source": "source",
        "tables": ("Table 1",), "primary_paper_verified": False,
    }
    with pytest.raises(ValueError):
        IlliteParameters(
            "Illite du Puy", 0.2, "mol_charge/kg", "derive_residual_planar",
            (Site("FES", 10.0, 0.0025, 0.05),
             Site("type-II", 2.0, 0.2, 0.04),
             Site("planar", 1.0, 0.7975, 0.1595)), provenance,
        )


@pytest.mark.parametrize("params,state", [(None, None), ("bad", CsKState(1e-3, 1e-9, 1.0))])
def test_calculate_boundary_validation(params, state):
    with pytest.raises(ValueError): calculate_kd(params, state)
