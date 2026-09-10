"""Pure CPU float64 production metric tests."""

from __future__ import annotations

import copy
import importlib
import math

import pytest

from specstyle.domain.enums import RuleStatus
from tests.unit.generation.test_diffusers_loader import _FLOAT16, _Torch
from tests.unit.verification._production_fixtures import (
    _FLOAT64,
    _MetricTensor,
    _Scalar,
    _configure_torch,
)


def _runtime() -> _Torch:
    torch = _Torch()
    _configure_torch(torch)
    return torch


def _tensor(
    torch: _Torch,
    data: list[object],
    *,
    name: str,
    shape: tuple[int, ...] | None = None,
    dtype: object | None = None,
    contiguous: bool = True,
    requires_grad: bool = False,
) -> _MetricTensor:
    return _MetricTensor(
        data,
        shape=shape,
        device=torch.device("cpu"),
        dtype=torch.float32 if dtype is None else dtype,
        contiguous=contiguous,
        requires_grad=requires_grad,
        name=name,
    )


def test_l2_uses_float64_patch_mean_and_population_std_without_mutation() -> None:
    metrics = importlib.import_module("specstyle.verification.production_metrics")
    torch = _runtime()
    output = _tensor(torch, [[1.0, 1.0], [3.0, 5.0]], name="output")
    reference = _tensor(torch, [[1.0, 1.0], [3.0, 5.0]], name="reference")
    snapshots = (copy.deepcopy(output.data), copy.deepcopy(reference.data))

    score = metrics._l2_similarity(torch, output, (reference,))

    assert score == pytest.approx(1.0)
    assert output.data == snapshots[0]
    assert reference.data == snapshots[1]
    for tensor in (output, reference):
        assert (tensor.name, "to", torch.device("cpu"), _FLOAT64) in tensor.events
        assert (tensor.name, "mean", 0) in tensor.events
        assert (tensor.name, "std", 0, 0) in tensor.events


@pytest.mark.parametrize(
    ("references", "expected"),
    (
        (((-1.0, 0.0), (0.0, 1.0), (1.0, 0.0)), 0.0),
        (((-1.0, 0.0), (0.0, 1.0), (1.0, 0.0), (1.0, 0.0)), 0.5),
        (((-1.0, 0.0), (1.0, 0.0), (1.0, 0.0)), 1.0),
    ),
)
def test_l2_uses_odd_even_median_and_duplicate_weighting(
    references: tuple[tuple[float, float], ...], expected: float
) -> None:
    metrics = importlib.import_module("specstyle.verification.production_metrics")
    torch = _runtime()
    output = _tensor(torch, [[1.0, 0.0], [1.0, 0.0]], name="output")
    patches = tuple(
        _tensor(torch, [list(vector), list(vector)], name=f"reference-{index}")
        for index, vector in enumerate(references)
    )

    assert metrics._l2_similarity(torch, output, patches) == pytest.approx(expected)


def test_l3_explicitly_normalizes_float64_projected_embeddings() -> None:
    metrics = importlib.import_module("specstyle.verification.production_metrics")
    torch = _runtime()
    output = _tensor(torch, [3.0, 4.0], name="output")
    source = _tensor(torch, [6.0, 8.0], name="source")
    snapshots = (copy.deepcopy(output.data), copy.deepcopy(source.data))

    score = metrics._l3_similarity(torch, output, source)

    assert score == pytest.approx(1.0)
    assert output.data == snapshots[0]
    assert source.data == snapshots[1]
    for tensor in (output, source):
        assert (tensor.name, "to", torch.device("cpu"), _FLOAT64) in tensor.events


@pytest.mark.parametrize(
    "mutation",
    (
        "nan",
        "inf",
        "zero",
        "wrong_rank",
        "wrong_dtype",
        "wrong_device",
        "wrong_dimension",
        "noncontiguous",
        "requires_grad",
    ),
)
def test_l2_rejects_each_invalid_tensor_contract(mutation: str) -> None:
    metrics = importlib.import_module("specstyle.verification.production_metrics")
    torch = _runtime()
    output = _tensor(torch, [[1.0, 0.0], [1.0, 0.0]], name="output")
    reference = _tensor(torch, [[1.0, 0.0], [1.0, 0.0]], name="reference")
    if mutation == "nan":
        output.data[0][0] = float("nan")
    elif mutation == "inf":
        output.data[0][0] = float("inf")
    elif mutation == "zero":
        output.data = [[0.0, 0.0], [0.0, 0.0]]
    elif mutation == "wrong_rank":
        output = _tensor(torch, [1.0, 0.0], name="output")
    elif mutation == "wrong_dtype":
        output.dtype = _FLOAT16
    elif mutation == "wrong_device":
        output.device = torch.device("cuda:0")
    elif mutation == "wrong_dimension":
        reference = _tensor(torch, [[1.0, 0.0, 0.0]], name="reference")
    elif mutation == "noncontiguous":
        output._contiguous = False
    else:
        output.requires_grad = True

    with pytest.raises(metrics._MetricContractViolation):
        metrics._l2_similarity(torch, output, (reference,))


@pytest.mark.parametrize(
    "mutation", ("nan", "zero", "wrong_rank", "wrong_device", "wrong_dimension")
)
def test_l3_rejects_each_invalid_tensor_contract(mutation: str) -> None:
    metrics = importlib.import_module("specstyle.verification.production_metrics")
    torch = _runtime()
    output = _tensor(torch, [1.0, 0.0], name="output")
    source = _tensor(torch, [1.0, 0.0], name="source")
    if mutation == "nan":
        source.data[0] = float("nan")
    elif mutation == "zero":
        source.data = [0.0, 0.0]
    elif mutation == "wrong_rank":
        source = _tensor(torch, [[1.0, 0.0]], name="source")
    elif mutation == "wrong_device":
        source.device = torch.device("cuda:0")
    else:
        source = _tensor(torch, [1.0, 0.0, 0.0], name="source")

    with pytest.raises(metrics._MetricContractViolation):
        metrics._l3_similarity(torch, output, source)


@pytest.mark.parametrize(
    ("status", "score", "expected"),
    (
        ("DRAFT", None, RuleStatus.UNVERIFIABLE),
        ("CALIBRATED", None, RuleStatus.UNVERIFIABLE),
        ("REVOKED", None, RuleStatus.FAIL),
        ("VALIDATED", 0.5, RuleStatus.PASS),
        ("VALIDATED", 0.499999999999, RuleStatus.FAIL),
    ),
)
def test_threshold_status_and_exact_equality_policy(
    status: str, score: float | None, expected: RuleStatus
) -> None:
    metrics = importlib.import_module("specstyle.verification.production_metrics")

    outcome = metrics._threshold_outcome(status, 0.5, score)

    assert outcome.status is expected
    assert outcome.score is score
    assert outcome.execute is False


def test_validated_threshold_requests_execution_when_score_is_absent() -> None:
    metrics = importlib.import_module("specstyle.verification.production_metrics")

    outcome = metrics._threshold_outcome("VALIDATED", 0.5, None)

    assert outcome.status is None
    assert outcome.score is None
    assert outcome.execute is True


def test_threshold_outcome_canonicalizes_negative_zero_score() -> None:
    metrics = importlib.import_module("specstyle.verification.production_metrics")

    outcome = metrics._threshold_outcome("VALIDATED", -0.1, -0.0)

    assert outcome.score == 0.0
    assert math.copysign(1.0, outcome.score) == 1.0


def test_similarity_canonicalizes_negative_zero_score() -> None:
    metrics = importlib.import_module("specstyle.verification.production_metrics")
    torch = _runtime()
    output = _tensor(torch, [1.0, 0.0], name="output")
    source = _tensor(torch, [1.0, 0.0], name="source")

    def negative_zero_dot(_left: object, _right: object) -> _Scalar:
        return _Scalar(-0.0)

    torch.dot = negative_zero_dot
    score = metrics._l3_similarity(torch, output, source)

    assert score == 0.0
    assert math.copysign(1.0, score) == 1.0


def test_even_median_canonicalizes_negative_zero_underflow() -> None:
    metrics = importlib.import_module("specstyle.verification.production_metrics")

    score = metrics._median((-5e-324, 0.0))

    assert score == 0.0
    assert math.copysign(1.0, score) == 1.0
