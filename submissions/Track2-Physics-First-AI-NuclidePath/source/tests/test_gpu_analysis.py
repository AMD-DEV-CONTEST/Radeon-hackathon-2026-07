import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import pytest

torch = pytest.importorskip("torch")

from nuclear_agent.gpu_analysis import batched_transport_torch
from nuclear_agent.transport import TransportParameters, simulate_transport


def _params():
    return TransportParameters(
        initial_concentration_bq_m3=1.0e6,
        distribution_coefficient_m3_kg=0.2,
        bulk_density_kg_m3=1700.0,
        porosity=0.35,
        groundwater_velocity_m_s=1.0e-5,
        dispersion_m2_s=1.0e-3,
        potassium_mg_l=20.0,
        competition_coefficient_l_mg=0.01,
        half_life_years=30.018,
    )


def test_batched_transport_fp64_matches_scalar_reference():
    params = _params()
    distances = [0.0, 10.0, 100.0, 100.0]
    times = [0.0, 1.0e8, 5.0e9, 1.0e10]

    result = batched_transport_torch(params, distances, times, device="cpu", dtype="float64")

    assert result["backend"] == "torch"
    assert result["dtype"] == "float64"
    for index, (distance, time_s) in enumerate(zip(distances, times, strict=True)):
        expected = simulate_transport(params, distance, time_s)
        assert result["concentration_bq_m3"][index] == pytest.approx(
            expected["concentration_bq_m3"], rel=2e-12, abs=1e-12
        )
        assert result["retardation_factor"][index] == pytest.approx(
            expected["retardation_factor"], rel=1e-14
        )


def test_batched_transport_rejects_mismatched_or_invalid_coordinates():
    params = _params()
    with pytest.raises(ValueError, match="same non-zero length"):
        batched_transport_torch(params, [1.0], [1.0, 2.0], device="cpu")
    with pytest.raises(ValueError, match="non-negative finite"):
        batched_transport_torch(params, [-1.0], [1.0], device="cpu")


def test_batched_transport_requires_explicit_available_device():
    params = _params()
    if not torch.cuda.is_available():
        with pytest.raises(RuntimeError, match="ROCm/CUDA device"):
            batched_transport_torch(params, [1.0], [1.0], device="cuda")
