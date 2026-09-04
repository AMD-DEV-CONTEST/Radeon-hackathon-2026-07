import json, math, sys
from dataclasses import FrozenInstanceError
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).parents[1] / 'src'))
from nuclear_agent.gcs_surrogate import (
    Domain, generate_dataset, metadata_for, validate_metadata, validation_metrics,
    predict_guarded, oracle_parameter_hash, SurrogateMetadata,
)
DATA=Path(__file__).parents[1]/'src/nuclear_agent/data/parameters/illite_du_puy_cs_k_v1.json'

def test_domain_is_immutable_and_validates():
    d=Domain()
    with pytest.raises((FrozenInstanceError, AttributeError)):
        d.k_log10_min=0
    assert d.contains((-6,-12,.01)) and not d.contains((-7,-12,.1))

def test_dataset_is_deterministic_and_oracle_labels():
    a=generate_dataset(8, seed=7, parameter_path=DATA); b=generate_dataset(8, seed=7, parameter_path=DATA)
    assert a==b and len(a.features)==8 and all(math.isfinite(x) for x in a.labels)

def test_metadata_hash_validation_fails_closed(tmp_path):
    m=metadata_for(DATA, train_seed=3)
    assert validate_metadata(m, DATA)
    bad=SurrogateMetadata.from_dict({**m.to_dict(), 'oracle_parameter_hash':'bad'})
    assert not validate_metadata(bad, DATA)

def test_guard_falls_back_and_never_silently_uses_surrogate(monkeypatch):
    called=[]
    monkeypatch.setattr('nuclear_agent.gcs_surrogate._surrogate_predict', lambda *a: called.append(1) or 99.0)
    result=predict_guarded((-7,-12,.5), model=None, parameter_path=DATA)
    assert not result.accepted and result.reason=='outside_domain' and not called
    result=predict_guarded((-3,-8,.5), model=None, parameter_path=DATA)
    assert not result.accepted and result.reason=='model_unavailable' and result.used_oracle

def test_metrics_are_independent_max_and_median():
    m=validation_metrics([1,2,3],[1,1,2])
    assert m['max_relative_kd_error']==pytest.approx(9.0)
    assert m['median_relative_kd_error']==pytest.approx(9.0)

def test_metrics_compare_linear_kd_not_log_values():
    assert validation_metrics([1, 2], [0, 2])['max_relative_kd_error'] == pytest.approx(9.0)

def test_custom_domain_metadata_and_complete_contract():
    d=Domain(-5,-2,-10,-4,.1,.9); m=metadata_for(DATA, 3, d)
    assert validate_metadata(m, DATA)
    assert m.to_dict()['schema'] == 'gcs-surrogate'
    with pytest.raises(TypeError): m.domain['k_log10_min'] = 0

def test_invalid_inputs_are_rejected_without_oracle(monkeypatch):
    monkeypatch.setattr('nuclear_agent.gcs_surrogate._oracle', lambda *a: (_ for _ in ()).throw(AssertionError()))
    for x in [(float('nan'),-8,.5), (1,2), ('bad',-8,.5)]:
        r=predict_guarded(x, None, parameter_path=DATA)
        assert r.value is None and not r.accepted and not r.used_oracle

def test_inference_failure_and_nonfinite_output_fall_back(monkeypatch):
    if torch is None: pytest.skip('torch unavailable')
    m=metadata_for(DATA)
    monkeypatch.setattr('nuclear_agent.gcs_surrogate._surrogate_predict', lambda *a: (_ for _ in ()).throw(RuntimeError('x')))
    r=predict_guarded((-3,-8,.5), object(), m, DATA)
    assert r.value is not None and not r.accepted and r.used_oracle

def test_save_load_uses_separate_json_and_tensor_state(tmp_path):
    if torch is None: pytest.skip('torch unavailable')
    from nuclear_agent.gcs_surrogate import GCSMLP, save_surrogate, load_surrogate
    meta=metadata_for(DATA); p=tmp_path/'model.json'; save_surrogate(p, GCSMLP(), meta)
    assert p.exists() and p.with_suffix('.pt').exists()
    model, loaded=load_surrogate(p, DATA); assert not model.training and loaded.to_dict()==meta.to_dict()

try:
    import torch
except ImportError:
    torch=None
pytestmark=torch and pytest.mark.filterwarnings('ignore') or pytest.mark.skipif(False, reason='')
