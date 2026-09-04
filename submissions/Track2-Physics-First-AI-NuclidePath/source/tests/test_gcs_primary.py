import json
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from nuclear_agent.gcs import (
    PrimaryGCSState,
    calculate_primary_kd,
    load_primary_gcs_parameters,
)

DATA = Path(__file__).parents[1] / "src/nuclear_agent/data/parameters/bradbury_baeyens_gcs_v2.json"


def test_primary_record_reproduces_tables_1_and_2():
    p = load_primary_gcs_parameters(DATA)
    assert p.cec_mol_charge_per_kg == 0.2
    assert [s.capacity_fraction for s in p.sites] == pytest.approx([0.0025, 0.20, 0.7975])
    assert [math.log10(s.kc_cs_k) for s in p.sites] == pytest.approx([4.6, 1.5, 0.5])
    assert [math.log10(s.kc_cs_na) for s in p.sites] == pytest.approx([7.0, 3.6, 1.6])
    assert [math.log10(s.kc_k_na) for s in p.sites] == pytest.approx([2.4, 2.1, 1.1])
    assert p.sites[0].kc_nh4_k == pytest.approx(10**1.1)
    assert p.sites[1].kc_nh4_k is None and p.sites[2].kc_nh4_k is None
    assert p.provenance["basis"] == "primary_paper"
    assert p.provenance["primary_paper_verified"] is True
    assert p.provenance["supplied_pdf_sha256"] == "8a9a90a8a8e414b8936c4ab9c3e923023424b7159c66ca1418d7bdf83dbb78ac"


def test_reported_binary_selectivities_are_thermodynamically_consistent():
    p = load_primary_gcs_parameters(DATA)
    for site in p.sites:
        # Eq. 8: Kc(K/Na) = Kc(Cs/Na) / Kc(Cs/K).
        assert site.kc_cs_na / site.kc_cs_k == pytest.approx(site.kc_k_na)
    # FES Table 2 also gives Cs/NH4 = 10^3.5.
    fes = p.sites[0]
    assert fes.kc_cs_k / fes.kc_nh4_k == pytest.approx(10**3.5)


def test_primary_mass_action_mass_balance_and_illite_scaling():
    p = load_primary_gcs_parameters(DATA)
    state = PrimaryGCSState(cesium_mol_l=1e-8, potassium_mol_l=1e-3,
                            sodium_mol_l=0.1, ammonium_mol_l=2e-4,
                            illite_mass_fraction=0.25, ph=7.5)
    r = calculate_primary_kd(p, state)
    assert sum(r.occupancies) == pytest.approx(r.total_sorbed_cs_mol_per_kg)
    assert all(0 <= x <= s.capacity_mol_charge_per_kg for x, s in zip(r.occupancies, p.sites))
    assert r.bulk_kd_l_kg == pytest.approx(0.25 * r.illite_kd_l_kg)
    assert r.competitor_treatment["NH4"] == "FES only; no unsupported type-II/planar coefficient inferred"
    assert r.competitor_treatment["Ca"] == "effectively noncompetitive in primary-paper Cs model"


def test_k_na_and_nh4_each_reduce_cs_sorption():
    p = load_primary_gcs_parameters(DATA)
    base = dict(cesium_mol_l=1e-9, potassium_mol_l=1e-6,
                sodium_mol_l=1e-6, ammonium_mol_l=0.0,
                illite_mass_fraction=1.0, ph=7.0)
    baseline = calculate_primary_kd(p, PrimaryGCSState(**base)).illite_kd_l_kg
    for ion, value in (("potassium_mol_l", 1e-2), ("sodium_mol_l", 1.0),
                       ("ammonium_mol_l", 1e-2)):
        changed = {**base, ion: value}
        assert calculate_primary_kd(p, PrimaryGCSState(**changed)).illite_kd_l_kg < baseline


def test_applicability_is_explicit_and_inputs_fail_closed():
    p = load_primary_gcs_parameters(DATA)
    r = calculate_primary_kd(p, PrimaryGCSState(2e-3, 1e-3, 0.1, 0, 1, ph=10))
    assert "cesium_above_primary_paper_domain" in r.applicability_warnings
    assert "ph_outside_primary_paper_range" in r.applicability_warnings
    with pytest.raises(ValueError):
        PrimaryGCSState(1e-9, 0, 0, 0, 1)
    with pytest.raises(ValueError):
        PrimaryGCSState(math.nan, 1e-3, 0, 0, 1)
    with pytest.raises(ValueError):
        PrimaryGCSState(1e-9, 1e-3, 0, 0, 1.1)


def test_primary_provenance_is_immutable():
    result = calculate_primary_kd(
        load_primary_gcs_parameters(DATA),
        PrimaryGCSState(1e-9, 1e-3, 0.1, 0, 1),
    )
    with pytest.raises(TypeError):
        result.provenance["basis"] = "changed"


def test_primary_parameter_schema_rejects_tampered_applicability_and_uncertainty(tmp_path):
    raw = json.loads(DATA.read_text())
    for mutate in (
        lambda x: x.update(selectivity_uncertainty_log10=-0.2),
        lambda x: x["applicability"].update(ph_min=10, ph_max=6),
        lambda x: x["applicability"].update(maximum_equilibrium_cs_mol_l="bad"),
        lambda x: x["provenance"].update(supplied_pdf_sha256="not-a-hash"),
    ):
        candidate = json.loads(json.dumps(raw)); mutate(candidate)
        path = tmp_path / "bad.json"; path.write_text(json.dumps(candidate))
        with pytest.raises(ValueError):
            load_primary_gcs_parameters(path)
