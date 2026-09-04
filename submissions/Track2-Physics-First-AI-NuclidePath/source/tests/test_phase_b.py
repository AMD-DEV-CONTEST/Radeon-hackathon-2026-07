import math
import random
from pathlib import Path
import pytest

from nuclear_agent.analysis import ParameterRange, run_morris
from nuclear_agent.gcs import PrimaryGCSState, calculate_primary_kd, load_primary_gcs_parameters
from nuclear_agent.gpu_analysis import evaluate_scenarios_torch
from nuclear_agent.transport import TransportParameters, simulate_transport

try:
    import torch
except ImportError:
    torch=None

PARAMS=Path(__file__).parents[1]/"src/nuclear_agent/data/parameters/bradbury_baeyens_gcs_v2.json"

@pytest.mark.skipif(torch is None, reason="optional PyTorch unavailable")
def test_phase_b_fp64_pipeline_matches_scalar_primary_gcs_and_transport():
    gp=load_primary_gcs_parameters(PARAMS)
    base=TransportParameters(1000,0,1700,.35,1e-5,1e-5,0,0,30.018)
    rng=random.Random(44)
    chemistry=[]
    for _ in range(8):
        chemistry.append([10**rng.uniform(-11,-5),10**rng.uniform(-5,-2),
                          10**rng.uniform(-4,-1),10**rng.uniform(-7,-3),rng.uniform(.05,.8)])
    distances=[0,5,20]; times=[0,1e6,1e8]
    result=evaluate_scenarios_torch(base,gp,chemistry,distances,times,dtype="float64")
    actual=result["concentration_bq_m3"].detach().cpu().tolist()
    kd_actual=result["bulk_kd_l_kg"].detach().cpu().tolist()
    for i,row in enumerate(chemistry):
        kd=calculate_primary_kd(gp,PrimaryGCSState(*row)).bulk_kd_l_kg
        assert kd_actual[i] == pytest.approx(kd,rel=2e-12)
        tp=TransportParameters(1000,kd/1000,1700,.35,1e-5,1e-5,0,0,30.018)
        for j,x in enumerate(distances):
            for k,t in enumerate(times):
                assert actual[i][j][k] == pytest.approx(simulate_transport(tp,x,t)["concentration_bq_m3"],rel=2e-10,abs=1e-12)

@pytest.mark.skipif(torch is None, reason="optional PyTorch unavailable")
def test_phase_b_pipeline_rejects_invalid_chemistry():
    gp=load_primary_gcs_parameters(PARAMS); base=TransportParameters(1,0)
    for bad in ([[1e-9,0,0,0,.2]], [[math.nan,1e-3,.1,0,.2]], [[1e-9,1e-3,.1,0,2]]):
        with pytest.raises(ValueError): evaluate_scenarios_torch(base,gp,bad,[1],[1])


def _payload():
    return {"scenario_id":"morris","initial_concentration_bq_m3":1000.,"distance_m":10.,
            "evaluation_times_s":[0.,1e8],"distribution_coefficient_m3_kg":.2}


def test_morris_is_seeded_reproducible_and_reports_elementary_effects():
    ranges={"distribution_coefficient_m3_kg":ParameterRange(.1,.3,"uniform","literature-range","source"),
            "groundwater_velocity_m_s":ParameterRange(5e-6,2e-5,"uniform","demonstration-range","source")}
    a=run_morris(_payload(),ranges,trajectories=6,levels=4,seed=9)
    b=run_morris(_payload(),ranges,trajectories=6,levels=4,seed=9)
    assert a==b and a["analysis_version"]=="morris-0.1"
    assert all(v["mu_star"]>=abs(v["mu"]) for v in a["parameters"].values())
    assert all(len(v["effects"])==6 for v in a["parameters"].values())

@pytest.mark.parametrize("trajectories,levels", [(0,4),(2,1),(True,4)])
def test_morris_invalid_design_fails_closed(trajectories,levels):
    ranges={"distribution_coefficient_m3_kg":ParameterRange(.1,.3,"uniform","literature-range","source")}
    with pytest.raises(ValueError): run_morris(_payload(),ranges,trajectories=trajectories,levels=levels)
