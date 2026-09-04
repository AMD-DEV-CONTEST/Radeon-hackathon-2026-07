import copy
import json
import math

import pytest

from nuclear_agent.scientific_validation import (
    AcceptancePolicy,
    DATASET_SCHEMA,
    MODEL_SCHEMA,
    ModelSpec,
    ObservationDataset,
    ScientificValidationError,
    ScientificValidationGateError,
    build_validation_report,
    deterministic_group_split,
    fit_calibration_model,
    require_experimental_validation,
    verify_validation_report,
)


def _model_payload():
    return {
        "schema": MODEL_SCHEMA,
        "ions": ["K", "Na", "Ca", "Mg"],
        "ion_scales_mmol_kgw": {"K": 1.0, "Na": 1.0, "Ca": 1.0, "Mg": 1.0},
        "cec_scale_mmolc_kg": 100.0,
        "ridge_lambda": 1.0e-10,
    }


def _dataset_payload():
    spec = ModelSpec.from_mapping(_model_payload())
    coefficients = (2.0, -0.25, 0.12, -0.08, 0.04, 0.18)
    observations = []
    for group_number in range(1, 6):
        for replicate in range(3):
            k = 0.25 * group_number + 0.17 * replicate
            na = 0.40 + 0.13 * group_number + 0.11 * replicate
            ca = 0.30 + 0.09 * group_number * group_number + 0.07 * replicate
            mg = 0.20 + 0.16 * group_number + 0.05 * replicate
            cec = 70.0 + 11.0 * group_number + 3.0 * replicate
            observation = {
                "observation_id": f"obs-{group_number}-{replicate}",
                "group_id": f"batch-{group_number}",
                "mineral": "illite-test-fixture",
                "cec_mmolc_kg": cec,
                "cs_mol_kgw": 1.0e-8 * (replicate + 1),
                "competitors_mmol_kgw": {"K": k, "Na": na, "Ca": ca, "Mg": mg},
            }
            parsed = {
                "observation_id": observation["observation_id"],
                "group_id": observation["group_id"],
                "mineral": observation["mineral"],
                "cec_mmolc_kg": cec,
                "cs_mol_kgw": observation["cs_mol_kgw"],
                "competitors_mmol_kgw": observation["competitors_mmol_kgw"],
                "kd_m3_kg": 1.0,
            }
            from nuclear_agent.scientific_validation import Observation

            parsed_observation = Observation.from_mapping(parsed, len(observations))
            log_kd = sum(c * x for c, x in zip(coefficients, spec.feature_vector(parsed_observation)))
            observation["kd_m3_kg"] = 10.0 ** log_kd
            observations.append(observation)
    return {
        "schema": DATASET_SCHEMA,
        "dataset_id": "synthetic-calibration-gate-fixture-v1",
        "data_status": "synthetic_test_only",
        "provenance": {
            "source": "unit-test-generated values",
            "license": "test-fixture-only",
            "method": "deterministic analytic construction",
            "units": "kd_m3_kg; cec_mmolc_kg; concentrations_mmol_kgw; cs_mol_kgw",
            "retrieved_at": "2026-08-04",
            "permission": "test-fixture-only",
        },
        "observations": observations,
        "split": {
            "calibration_group_ids": ["batch-1", "batch-2", "batch-3", "batch-4"],
            "holdout_group_ids": ["batch-5"],
        },
    }


def test_dataset_requires_explicit_provenance_and_competitor_zeros():
    payload = _dataset_payload()
    del payload["provenance"]["permission"]
    with pytest.raises(ScientificValidationError, match="provenance.permission"):
        ObservationDataset.from_mapping(payload)

    payload = _dataset_payload()
    del payload["observations"][0]["competitors_mmol_kgw"]["K"]
    with pytest.raises(ScientificValidationError, match="competitors_mmol_kgw"):
        ObservationDataset.from_mapping(payload)


def test_dataset_rejects_split_leakage_and_measured_data_without_permission():
    payload = _dataset_payload()
    payload["split"]["holdout_group_ids"] = ["batch-4", "batch-5"]
    with pytest.raises(ScientificValidationError, match="disjoint"):
        ObservationDataset.from_mapping(payload)

    payload = _dataset_payload()
    payload["data_status"] = "measured_traceable"
    with pytest.raises(ScientificValidationError, match="permission"):
        ObservationDataset.from_mapping(payload)


def test_measured_data_requires_verifiable_source_url_and_digest():
    """A self-declared measured_traceable status must not promote a model.

    The reviewer mutated a synthetic fixture to data_status=measured_traceable
    with permission=public and the gate granted EXPERIMENTALLY_VALIDATED.
    Fail closed: measured data require a public source URL, a 64-hex digest
    and an experimental method description.
    """
    payload = _dataset_payload()
    payload["data_status"] = "measured_traceable"
    payload["provenance"]["permission"] = "public"
    # missing source URL + digest -> rejected
    with pytest.raises(ScientificValidationError, match="http"):
        ObservationDataset.from_mapping(payload)

    payload["provenance"]["source"] = "https://doi.org/10.1016/j.gea.2023.01.001"
    payload["provenance"]["dataset_sha256"] = "abc"
    with pytest.raises(ScientificValidationError, match="dataset_sha256"):
        ObservationDataset.from_mapping(payload)

    payload["provenance"]["dataset_sha256"] = "a" * 64
    # method still says "deterministic analytic construction" -> rejected
    with pytest.raises(ScientificValidationError, match="method"):
        ObservationDataset.from_mapping(payload)

    payload["provenance"]["method"] = "laboratory batch sorption experiment"
    dataset = ObservationDataset.from_mapping(payload)
    assert dataset.data_status == "measured_traceable"


def test_group_split_is_deterministic_and_disjoint():
    dataset = ObservationDataset.from_mapping(_dataset_payload())
    first = deterministic_group_split(dataset.observations, dataset.dataset_id)
    second = deterministic_group_split(dataset.observations, dataset.dataset_id)
    assert first == second
    assert set(first[0]).isdisjoint(first[1])
    assert set(first[0]) | set(first[1]) == {item.group_id for item in dataset.observations}


def test_synthetic_fixture_fits_but_cannot_promote_scientific_evidence():
    dataset = ObservationDataset.from_mapping(_dataset_payload())
    spec = ModelSpec.from_mapping(_model_payload())
    model = fit_calibration_model(dataset, spec)
    assert model.calibration_observation_count == 12
    report = build_validation_report(
        dataset,
        spec,
        acceptance=AcceptancePolicy(
            min_holdout_observations=3,
            min_holdout_groups=1,
            max_rmse_log10=1.0e-4,
            max_max_relative_error=1.0e-3,
        ),
    )
    assert report["holdout_passed"] is True
    assert report["promotion"]["granted"] is False
    assert report["promotion"]["evidence_level"] == "NOT_PROMOTED"
    assert "synthetic" in " ".join(report["promotion"]["reasons"])
    verify_validation_report(report)
    altered = copy.deepcopy(report)
    altered["metrics"]["holdout"]["rmse_log10"] = 999.0
    with pytest.raises(ScientificValidationError, match="digest mismatch"):
        verify_validation_report(altered)
    with pytest.raises(ScientificValidationGateError, match="gate is closed"):
        require_experimental_validation(report)
    assert len(report["report_sha256"]) == 64


def test_report_is_json_safe_and_input_copy_is_unchanged():
    payload = _dataset_payload()
    original = json.dumps(payload, sort_keys=True)
    dataset = ObservationDataset.from_mapping(payload)
    report = build_validation_report(dataset, ModelSpec.from_mapping(_model_payload()))
    json.dumps(report, allow_nan=False)
    assert json.dumps(payload, sort_keys=True) == original


def test_model_rejects_nonpositive_scale():
    payload = _model_payload()
    payload["cec_scale_mmolc_kg"] = 0.0
    with pytest.raises(ScientificValidationError, match="cec_scale"):
        ModelSpec.from_mapping(payload)
