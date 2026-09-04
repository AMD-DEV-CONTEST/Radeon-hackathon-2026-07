import math
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

try:
    import torch
except ImportError:
    torch = None

from nuclear_agent.gcs import PrimaryGCSState, calculate_primary_kd, load_primary_gcs_parameters
from nuclear_agent.gcs_primary_accelerated import calculate_primary_kd_batch
from nuclear_agent.gpu_analysis import batched_primary_gcs_torch

DATA = Path(__file__).parents[1] / "src/nuclear_agent/data/parameters/bradbury_baeyens_gcs_v2.json"
pytestmark = pytest.mark.skipif(torch is None, reason="optional PyTorch unavailable")


def states(n=64, seed=42):
    r = random.Random(seed)
    return tuple(PrimaryGCSState(
        10 ** r.uniform(-12, -3), 10 ** r.uniform(-6, -1),
        10 ** r.uniform(-5, 0), 10 ** r.uniform(-8, -1),
        r.uniform(0.01, 1.0), r.uniform(6, 9),
    ) for _ in range(n))


def test_exact_batch_matches_scalar_primary_oracle_fp64():
    p = load_primary_gcs_parameters(DATA)
    batch = states()
    accelerated = calculate_primary_kd_batch(p, batch, device="cpu", dtype="float64")
    expected = [calculate_primary_kd(p, state).bulk_kd_l_kg for state in batch]
    assert accelerated.backend == "torch-exact"
    assert accelerated.approximation is False
    assert accelerated.dtype == "float64"
    assert len(accelerated.bulk_kd_l_kg) == len(batch)
    for actual, oracle in zip(accelerated.bulk_kd_l_kg, expected):
        assert actual == pytest.approx(oracle, rel=2e-12, abs=1e-12)


@pytest.mark.parametrize("size", [1, 10, 1000])
def test_exact_batch_parity_across_batch_sizes(size):
    p = load_primary_gcs_parameters(DATA)
    batch = states(size, size)
    actual = calculate_primary_kd_batch(p, batch, dtype="float64").bulk_kd_l_kg
    expected = tuple(calculate_primary_kd(p, state).bulk_kd_l_kg for state in batch)
    assert actual == pytest.approx(expected, rel=2e-12, abs=1e-12)


def test_fp32_is_finite_and_close_to_scalar_oracle():
    p = load_primary_gcs_parameters(DATA)
    batch = states(128, 9)
    accelerated = calculate_primary_kd_batch(p, batch, dtype="float32")
    expected = [calculate_primary_kd(p, state).bulk_kd_l_kg for state in batch]
    errors = [abs(a / b - 1) for a, b in zip(accelerated.bulk_kd_l_kg, expected)]
    assert all(math.isfinite(x) and x >= 0 for x in accelerated.bulk_kd_l_kg)
    assert max(errors) < 2e-5


def test_batch_rejects_empty_wrong_types_and_unavailable_device():
    p = load_primary_gcs_parameters(DATA)
    with pytest.raises(ValueError): calculate_primary_kd_batch(p, ())
    with pytest.raises(ValueError): calculate_primary_kd_batch(p, ("bad",))
    with pytest.raises(ValueError): calculate_primary_kd_batch(p, states(1), dtype="float16")
    if not torch.cuda.is_available():
        with pytest.raises(RuntimeError): calculate_primary_kd_batch(p, states(1), device="cuda")


def test_batch_preserves_primary_competitor_effects():
    p = load_primary_gcs_parameters(DATA)
    base = PrimaryGCSState(1e-9, 1e-6, 1e-6, 0, 1)
    batch = (base,
             PrimaryGCSState(1e-9, 1e-2, 1e-6, 0, 1),
             PrimaryGCSState(1e-9, 1e-6, 1.0, 0, 1),
             PrimaryGCSState(1e-9, 1e-6, 1e-6, 1e-2, 1))
    values = calculate_primary_kd_batch(p, batch).bulk_kd_l_kg
    assert values[1] < values[0]
    assert values[2] < values[0]
    assert values[3] < values[0]


def test_project_gpu_analysis_entry_point_uses_exact_primary_backend():
    p = load_primary_gcs_parameters(DATA)
    batch = states(3, 11)
    result = batched_primary_gcs_torch(p, batch, device="cpu", dtype="float64")
    assert result.backend == "torch-exact"
    assert result.approximation is False
