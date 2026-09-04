import csv
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
import pytest
from nuclear_agent.observations import Observation, load_json_observations, load_csv_observations
from nuclear_agent.likelihood import gaussian_loglikelihood, left_censored_gaussian_loglikelihood
from nuclear_agent.recovery import bounded_grid_recovery


def row(**overrides):
    x = {"radionuclide":"Cs-137", "receptor_id":"well-1", "timestamp":"2026-01-01T00:00:00Z", "value":2, "unit":"Bq/m3", "uncertainty":0.5, "detection_limit_flag":False, "detection_limit_value":None, "provenance":"lab:abc"}
    x.update(overrides); return x


def test_observation_is_immutable_and_normalizes_supported_units():
    o = Observation.from_dict(row(unit="kBq/m3", value=2))
    assert o.value == 2000.0 and o.unit == "Bq/m3"
    with pytest.raises(ValueError, match="unknown or ambiguous unit"):
        Observation.from_dict(row(unit="Bq"))
    with pytest.raises(ValueError, match="unknown field"):
        Observation.from_dict(row(extra=1))
    with pytest.raises(AttributeError): o.value = 3


def test_json_and_csv_ingestion_are_strict(tmp_path):
    p = tmp_path / "o.json"; p.write_text(json.dumps([row()]))
    assert len(load_json_observations(p)) == 1
    c = tmp_path / "o.csv"
    with c.open("w", newline="") as f:
        w=csv.DictWriter(f, fieldnames=row().keys()); w.writeheader(); w.writerow(row())
    assert load_csv_observations(c)[0].value == 2
    with pytest.raises(ValueError): load_json_observations(tmp_path / "missing.json")


def test_likelihoods_validate_and_censor():
    assert gaussian_loglikelihood(2, 2, 1) == pytest.approx(-0.9189385332)
    assert left_censored_gaussian_loglikelihood(1, 2, 1) == pytest.approx(-1.841021645)
    with pytest.raises(ValueError): gaussian_loglikelihood(1, 1, 0)
    with pytest.raises(ValueError): left_censored_gaussian_loglikelihood(1, 2, -1)


def test_deterministic_bounded_grid_recovery_and_identifiability():
    data=[(0, 3.0), (1, 5.0)]
    result=bounded_grid_recovery(data, lambda p,t: p["slope"]*t+p["intercept"], {"slope":[1,2,3], "intercept":[0,1,2,3]}, uncertainty=1)
    assert result.best_parameters == {"slope":2, "intercept":3} or result.best_parameters == {"slope":2, "intercept":2}
    assert result.identifiable
    flat=bounded_grid_recovery([(0,1)], lambda p,t: 1, {"x":[0,1]}, uncertainty=1)
    assert not flat.identifiable and any("flat" in item for item in flat.diagnostics)
