"""Phase A1-A3: Benchmark records, predicted envelopes, and selectivity uncertainty.

Strict TDD: failing tests first. No invented chemistry.
Tests verify:
- A1: Paper benchmark records (Boom/Oxford/Palfris/Opalinus) from Tables 4-5
- A2: Predicted isotherm envelopes at lower/upper illite fractions
- A3: Selectivity uncertainty (±0.2 log10 Kc) with quantiles and Eq.8 consistency
"""
import json
import math
import sys
from pathlib import Path

import pytest
import tomllib

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from nuclear_agent.gcs_validation import (
    BradburyRock,
    BradburyMineralogy,
    BradburyWaterChemistry,
    load_bradbury_rocks_v1,
    predict_cs_isotherm_envelope,
    sample_selectivity_uncertainty,
    _perturb_systematic,
)
from nuclear_agent.gcs import load_primary_gcs_parameters


ROCKS_DATA = (
    Path(__file__).parents[1] / "src/nuclear_agent/data/validation/bradbury_2000_rocks_v1.json"
)


class TestA1BenchmarkRecords:
    def test_validation_dataset_is_included_in_installed_wheel_contract(self):
        project = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())
        package_data = project["tool"]["setuptools"]["package-data"]["nuclear_agent"]
        assert "data/validation/*.json" in package_data

    """Phase A1: Paper benchmark records from Bradbury & Baeyens Tables 4-5."""

    def test_load_rocks_returns_four_distinct_systems(self):
        rocks = load_bradbury_rocks_v1(ROCKS_DATA)
        assert len(rocks) == 4
        names = [r.name for r in rocks]
        assert names == ["Boom Clay", "Oxford Clay", "Palfris Marl", "Opalinus Clay"]

    def test_boom_clay_mineralogy_preserved_from_table4(self):
        rocks = load_bradbury_rocks_v1(ROCKS_DATA)
        boom = next(r for r in rocks if r.name == "Boom Clay")
        assert boom.mineralogy is not None
        assert boom.mineralogy.illite_weight_fraction_range == (0.20, 0.30)
        assert boom.mineralogy.quartz_weight_percent == 20
        assert boom.mineralogy.carbonates_weight_percent_range == (1, 5)
        assert boom.mineralogy.k_feldspar_weight_percent_range == (5, 10)
        # Smectite range from Table 4
        assert boom.mineralogy.smectite_weight_fraction_range == (0.10, 0.20)

    def test_oxford_clay_mineralogy_preserved_from_table4(self):
        rocks = load_bradbury_rocks_v1(ROCKS_DATA)
        oxford = next(r for r in rocks if r.name == "Oxford Clay")
        assert oxford.mineralogy is not None
        assert oxford.mineralogy.illite_weight_fraction_range == (0.16, 0.36)
        assert oxford.mineralogy.quartz_weight_percent_range == (9, 30)
        assert oxford.mineralogy.carbonates_weight_percent_range == (2, 40)

    def test_palfris_marl_mineralogy_preserved_from_table4(self):
        rocks = load_bradbury_rocks_v1(ROCKS_DATA)
        palfris = next(r for r in rocks if r.name == "Palfris Marl")
        assert palfris.mineralogy is not None
        assert palfris.mineralogy.illite_weight_fraction_range == (0.11, 0.17)
        assert palfris.mineralogy.quartz_weight_percent_range == (12, 18)
        assert palfris.mineralogy.pyrite_weight_percent == pytest.approx(0.3)

    def test_opalinus_clay_mineralogy_preserved_from_table4(self):
        rocks = load_bradbury_rocks_v1(ROCKS_DATA)
        opalinus = next(r for r in rocks if r.name == "Opalinus Clay")
        assert opalinus.mineralogy is not None
        assert opalinus.mineralogy.illite_weight_fraction_range == (0.18, 0.26)
        assert opalinus.mineralogy.quartz_weight_percent_range == (10, 14)
        assert opalinus.mineralogy.siderite_weight_percent_range == (3, 5)
        assert opalinus.mineralogy.k_feldspar_weight_percent_range == (1.5, 3)

    def test_boom_clay_water_chemistry_preserved_from_table5(self):
        rocks = load_bradbury_rocks_v1(ROCKS_DATA)
        boom = next(r for r in rocks if r.name == "Boom Clay")
        assert boom.water_chemistry is not None
        # Table 5: Na = 2.9e-2 M
        assert math.isclose(boom.water_chemistry.sodium_mol_l, 2.9e-2, rel_tol=1e-6)
        # Table 5: K = 1.0e-3 M
        assert math.isclose(boom.water_chemistry.potassium_mol_l, 1.0e-3, rel_tol=1e-6)
        # Table 5: NH4 missing (null)
        assert boom.water_chemistry.ammonium_mol_l is None
        # Table 5: pH = 8.8
        assert math.isclose(boom.water_chemistry.ph, 8.8, rel_tol=1e-6)

    def test_oxford_clay_water_chemistry_preserved_from_table5(self):
        rocks = load_bradbury_rocks_v1(ROCKS_DATA)
        oxford = next(r for r in rocks if r.name == "Oxford Clay")
        assert oxford.water_chemistry is not None
        # Table 5: Na = 1.6e-1 M
        assert math.isclose(oxford.water_chemistry.sodium_mol_l, 1.6e-1, rel_tol=1e-6)
        # Table 5: K = 1.1e-5 M
        assert math.isclose(oxford.water_chemistry.potassium_mol_l, 1.1e-5, rel_tol=1e-6)
        # Table 5: NH4 = 2.4e-4 M (Oxford only)
        assert math.isclose(oxford.water_chemistry.ammonium_mol_l, 2.4e-4, rel_tol=1e-6)
        # Table 5: Cs = null for Oxford
        assert oxford.water_chemistry.cesium_mol_l is None

    def test_palfris_marl_water_chemistry_preserved_from_table5(self):
        rocks = load_bradbury_rocks_v1(ROCKS_DATA)
        palfris = next(r for r in rocks if r.name == "Palfris Marl")
        assert palfris.water_chemistry is not None
        # Table 5: Na = 8.0e-2 M
        assert math.isclose(palfris.water_chemistry.sodium_mol_l, 8.0e-2, rel_tol=1e-6)
        # Table 5: Cs = 2.5e-8 M
        assert math.isclose(
            palfris.water_chemistry.cesium_mol_l, 2.5e-8, rel_tol=1e-6
        )

    def test_opalinus_clay_water_chemistry_preserved_from_table5(self):
        rocks = load_bradbury_rocks_v1(ROCKS_DATA)
        opalinus = next(r for r in rocks if r.name == "Opalinus Clay")
        assert opalinus.water_chemistry is not None
        # Table 5: Na = 2.5e-1 M
        assert math.isclose(opalinus.water_chemistry.sodium_mol_l, 2.5e-1, rel_tol=1e-6)
        # Table 5: K = 5.8e-3 M
        assert math.isclose(opalinus.water_chemistry.potassium_mol_l, 5.8e-3, rel_tol=1e-6)
        # Table 5: Cs = 4.8e-8 M
        assert math.isclose(
            opalinus.water_chemistry.cesium_mol_l, 4.8e-8, rel_tol=1e-6
        )

    def test_records_are_immutable_validated_loaders(self):
        rocks = load_bradbury_rocks_v1(ROCKS_DATA)
        boom = rocks[0]
        # Attempt to mutate should fail
        with pytest.raises((AttributeError, TypeError)):
            boom.name = "Modified"

    def test_unknown_fields_fail_closed(self, tmp_path):
        raw = json.loads(ROCKS_DATA.read_text())
        raw["rocks"][0]["mineralogy"]["invented"] = 1
        path = tmp_path / "bad.json"; path.write_text(json.dumps(raw))
        with pytest.raises(ValueError, match="unknown mineralogy field"):
            load_bradbury_rocks_v1(path)

    def test_provenance_discloses_paper_input_reconstruction_not_measured_validation(self):
        rocks = load_bradbury_rocks_v1(ROCKS_DATA)
        for rock in rocks:
            assert rock.provenance is not None
            assert rock.provenance["basis"] == "paper_tables_4_5"
            assert rock.provenance["primary_paper_verified"] is True
            assert rock.provenance["supplied_pdf_sha256"].startswith("8a9a90a8")
            assert (
                "paper-input reconstruction, not digitized measured validation"
                in rock.provenance["note"]
            )


class TestA2IsothermEnvelopes:
    """Phase A2: Predicted Cs isotherm envelopes at lower/upper illite fractions."""

    def test_predict_envelope_returns_grids_at_lower_and_upper_illite(self):
        rocks = load_bradbury_rocks_v1(ROCKS_DATA)
        boom = next(r for r in rocks if r.name == "Boom Clay")
        result = predict_cs_isotherm_envelope(boom)
        assert result is not None
        assert "lower_illite_envelope" in result
        assert "upper_illite_envelope" in result
        assert result["lower_illite_envelope"] is not None
        assert result["upper_illite_envelope"] is not None

    def test_envelope_contains_concentration_dependent_prediction(self):
        rocks = load_bradbury_rocks_v1(ROCKS_DATA)
        boom = next(r for r in rocks if r.name == "Boom Clay")
        result = predict_cs_isotherm_envelope(boom)
        lower = result["lower_illite_envelope"]
        # Should have Cs concentrations (mol/L) as keys
        assert len(lower["cs_concentrations_mol_l"]) > 0
        # Should have corresponding Kd predictions (L/kg)
        assert len(lower["predicted_kd_l_kg"]) == len(lower["cs_concentrations_mol_l"])

    def test_envelope_monotonic_concentration_behavior_holds(self):
        """At fixed illite fraction, higher Cs -> lower Kd (concentration-dependent behavior)."""
        rocks = load_bradbury_rocks_v1(ROCKS_DATA)
        palfris = next(r for r in rocks if r.name == "Palfris Marl")
        result = predict_cs_isotherm_envelope(palfris)
        lower = result["lower_illite_envelope"]
        cs = lower["cs_concentrations_mol_l"]
        kd = lower["predicted_kd_l_kg"]
        # Cs concentrations should be sorted ascending
        assert list(cs) == sorted(cs)
        # Kd should be non-increasing (decreasing or flat due to site saturation)
        for i in range(len(kd) - 1):
            assert kd[i] >= kd[i + 1] or math.isclose(kd[i], kd[i + 1], rel_tol=1e-3)

    def test_envelope_labeled_as_paper_input_reconstruction(self):
        rocks = load_bradbury_rocks_v1(ROCKS_DATA)
        oxford = next(r for r in rocks if r.name == "Oxford Clay")
        result = predict_cs_isotherm_envelope(oxford)
        assert result["label"] == "paper-input reconstruction, not digitized measured validation"

    def test_different_illite_fractions_produce_different_kd_values(self):
        """Bulk Kd should be proportional to illite fraction."""
        rocks = load_bradbury_rocks_v1(ROCKS_DATA)
        opalinus = next(r for r in rocks if r.name == "Opalinus Clay")
        result = predict_cs_isotherm_envelope(opalinus)
        lower = result["lower_illite_envelope"]
        upper = result["upper_illite_envelope"]
        # Compare at the same Cs concentration (should be same grid)
        assert lower["cs_concentrations_mol_l"] == upper["cs_concentrations_mol_l"]
        # Bulk Kd should scale with illite fraction: upper illite -> higher Kd
        for i in range(len(lower["predicted_kd_l_kg"])):
            assert (
                upper["predicted_kd_l_kg"][i]
                > lower["predicted_kd_l_kg"][i]
            ), f"Upper illite should produce higher Kd at index {i}"

    def test_missing_reported_k_or_na_fails_closed_without_fallback(self):
        boom = load_bradbury_rocks_v1(ROCKS_DATA)[0]
        missing = BradburyRock(boom.name, boom.location, boom.mineralogy,
                               BradburyWaterChemistry(potassium_mol_l=None, sodium_mol_l=.1),
                               boom.provenance)
        with pytest.raises(ValueError, match="reported K and Na"):
            predict_cs_isotherm_envelope(missing)


class TestA3SelectivityUncertainty:
    """Phase A3: Seeded ±0.2 log10 Kc uncertainty with quantiles and Eq.8 consistency."""

    def test_sample_uncertainty_returns_quantiles(self):
        rocks = load_bradbury_rocks_v1(ROCKS_DATA)
        boom = next(r for r in rocks if r.name == "Boom Clay")
        result = sample_selectivity_uncertainty(boom, seed=42, n_samples=500)
        assert "p05" in result
        assert "p50" in result
        assert "p95" in result
        assert all(hasattr(result[key], "keys") for key in ["p05", "p50", "p95"])

    def test_sample_uncertainty_quantiles_are_properly_ordered(self):
        """P05 <= P50 <= P95 across all Cs concentrations."""
        rocks = load_bradbury_rocks_v1(ROCKS_DATA)
        palfris = next(r for r in rocks if r.name == "Palfris Marl")
        result = sample_selectivity_uncertainty(palfris, seed=123, n_samples=1000)
        cs_concs = result["p50"]["cs_concentrations_mol_l"]
        for cs_idx in range(len(cs_concs)):
            p05_kd = result["p05"]["predicted_kd_l_kg"][cs_idx]
            p50_kd = result["p50"]["predicted_kd_l_kg"][cs_idx]
            p95_kd = result["p95"]["predicted_kd_l_kg"][cs_idx]
            assert p05_kd <= p50_kd <= p95_kd, f"Quantile order violated at index {cs_idx}"

    def test_seeded_sampling_produces_reproducible_results(self):
        rocks = load_bradbury_rocks_v1(ROCKS_DATA)
        oxford = next(r for r in rocks if r.name == "Oxford Clay")
        result1 = sample_selectivity_uncertainty(oxford, seed=777, n_samples=200)
        result2 = sample_selectivity_uncertainty(oxford, seed=777, n_samples=200)
        # Results should be identical with same seed
        assert (
            result1["p50"]["predicted_kd_l_kg"]
            == result2["p50"]["predicted_kd_l_kg"]
        )

    def test_uncertainty_preserves_eq8_coefficient_consistency(self):
        """Eq.8 relates selectivity coefficients: log(Cs_Na Kc) / log(Cs_K Kc).

        Perturbing selectivity must respect this relationship, not independently
        perturb both coefficients.
        """
        rocks = load_bradbury_rocks_v1(ROCKS_DATA)
        opalinus = next(r for r in rocks if r.name == "Opalinus Clay")
        result = sample_selectivity_uncertainty(opalinus, seed=42, n_samples=300)
        params = load_primary_gcs_parameters(Path(__file__).parents[1] / "src/nuclear_agent/data/parameters/bradbury_baeyens_gcs_v2.json")
        perturbed = _perturb_systematic(params, result["sampled_log10_shifts"][0])
        for before, after in zip(params.sites, perturbed.sites):
            assert after.kc_cs_na / after.kc_cs_k == pytest.approx(before.kc_k_na)
        assert result["uncertainty_interpretation"]["eq8_preserved"] is True

    def test_uncertainty_interpretation_is_honestly_demonstrative(self):
        rocks = load_bradbury_rocks_v1(ROCKS_DATA)
        boom = next(r for r in rocks if r.name == "Boom Clay")
        result = sample_selectivity_uncertainty(boom, seed=99, n_samples=500)
        interpretation = result["uncertainty_interpretation"]
        assert interpretation["classification"] == "demonstrative-systematic"
        assert "does not prescribe" in interpretation["limitation"]

    @pytest.mark.parametrize("samples", [0, -1, True])
    def test_invalid_sample_count_fails_closed(self, samples):
        boom = load_bradbury_rocks_v1(ROCKS_DATA)[0]
        with pytest.raises(ValueError):
            sample_selectivity_uncertainty(boom, n_samples=samples)

    def test_seed_controls_random_number_generation(self):
        rocks = load_bradbury_rocks_v1(ROCKS_DATA)
        oxford = next(r for r in rocks if r.name == "Oxford Clay")
        result_seed1 = sample_selectivity_uncertainty(
            oxford, seed=111, n_samples=100
        )
        result_seed2 = sample_selectivity_uncertainty(
            oxford, seed=222, n_samples=100
        )
        # Different seeds should produce different (but similar) quantile estimates
        p50_1 = result_seed1["p50"]["predicted_kd_l_kg"][0]
        p50_2 = result_seed2["p50"]["predicted_kd_l_kg"][0]
        # They may be close but not identical
        assert not math.isclose(p50_1, p50_2, rel_tol=1e-9)
