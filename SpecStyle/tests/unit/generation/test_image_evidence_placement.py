"""Image-evidence placement, transfer, and canonical closure contracts."""

from __future__ import annotations

import math
from pathlib import Path
from types import SimpleNamespace

import pytest

from specstyle.errors import DomainError, InfrastructureError
from specstyle.generation.diffusers_loader import load_production_pipeline
from specstyle.observability.hashing import hash_bytes
from tests.unit.generation.test_diffusers_loader import (
    _Diffusers,
    _FLOAT32,
    _ModelTensor,
    _Pipeline,
    _Torch,
    _assert_failed_pipeline_released,
    _environment,
    _supply,
)
from tests.unit.generation.test_image_evidence_encoder import (
    _Tensor,
    _encoder_runtime,
    _png,
)


_MEAN = (0.48145466, 0.4578275, 0.40821073)
_STD = (0.26862954, 0.26130258, 0.27577711)


class _ListSubclass(list):
    pass


class _TupleSubclass(tuple):
    pass


class _FloatSubclass(float):
    pass


class _TensorSubclass(_Tensor):
    pass


def _install_postload_mutation(
    monkeypatch: pytest.MonkeyPatch, mutation: object
) -> None:
    original = _Pipeline.load_ip_adapter

    def load_mutated(self: _Pipeline, *args: object, **kwargs: object) -> None:
        original(self, *args, **kwargs)
        mutation(self.image_encoder, self.feature_extractor)

    monkeypatch.setattr(_Pipeline, "load_ip_adapter", load_mutated)


def _load(tmp_path: Path, torch: _Torch, diffusers: _Diffusers):
    supply, graph = _supply(tmp_path)
    try:
        loaded = load_production_pipeline(
            supply,
            graph,
            _environment(),
            torch_module=torch,
            diffusers_module=diffusers,
        )
    except Exception:
        supply.close()
        raise
    return supply, loaded


def test_loader_accepts_exact_tuple_clip_statistics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_postload_mutation(
        monkeypatch,
        lambda _encoder, processor: (
            setattr(processor, "image_mean", _MEAN),
            setattr(processor, "image_std", _STD),
        ),
    )
    torch, diffusers = _Torch(), _Diffusers()
    supply, loaded = _load(tmp_path, torch, diffusers)
    try:
        assert loaded._borrow_image_evidence_encoder().layer == "hidden_states[-2]"
    finally:
        loaded.close()
        supply.close()


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("image_mean", _ListSubclass(_MEAN)),
        ("image_mean", _TupleSubclass(_MEAN)),
        ("image_mean", list(_MEAN[:2])),
        ("image_mean", [_FloatSubclass(_MEAN[0]), *_MEAN[1:]]),
        ("image_mean", [True, *_MEAN[1:]]),
        ("image_mean", [math.nan, *_MEAN[1:]]),
        ("image_mean", [math.inf, *_MEAN[1:]]),
        ("image_mean", [0.0, *_MEAN[1:]]),
        ("image_std", _ListSubclass(_STD)),
        ("image_std", _TupleSubclass(_STD)),
        ("image_std", list(_STD) + [0.0]),
        ("image_std", [_FloatSubclass(_STD[0]), *_STD[1:]]),
        ("image_std", [1, *_STD[1:]]),
        ("image_std", [-math.inf, *_STD[1:]]),
        ("image_std", [0.0, *_STD[1:]]),
    ],
)
def test_loader_rejects_nonexact_clip_statistics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    invalid: object,
) -> None:
    _install_postload_mutation(
        monkeypatch, lambda _encoder, processor: setattr(processor, field, invalid)
    )
    supply, _graph = _supply(tmp_path)
    torch, diffusers = _Torch(), _Diffusers()
    diffusers.track_issued_pipelines = True
    try:
        with pytest.raises(InfrastructureError, match="pipeline loading failed"):
            load_production_pipeline(
                supply,
                _graph,
                _environment(),
                torch_module=torch,
                diffusers_module=diffusers,
            )
        _assert_failed_pipeline_released(diffusers, torch)
    finally:
        supply.close()


def _mutate_placement(encoder: object, case: str) -> None:
    if case == "no_parameters":
        encoder._parameters = []
    elif case == "parameter_cpu":
        encoder._parameters[0].device = _Torch.device("cpu")
    elif case == "parameter_meta":
        encoder._parameters[0].device = _Torch.device("meta")
    elif case == "parameter_cuda1":
        encoder._parameters[0].device = _Torch.device("cuda:1")
    elif case == "parameter_fp32":
        encoder._parameters[0].dtype = _FLOAT32
    elif case == "mixed_parameter_device":
        encoder._parameters.append(_ModelTensor("cuda:1"))
    elif case == "mixed_parameter_dtype":
        encoder._parameters.append(_ModelTensor(dtype=_FLOAT32))
    elif case == "buffer_device":
        encoder._buffers[0].device = _Torch.device("cpu")
    elif case == "floating_buffer_dtype":
        encoder._buffers[0].dtype = _FLOAT32
    else:
        raise AssertionError(case)


_PLACEMENT_FAILURES = (
    "no_parameters",
    "parameter_cpu",
    "parameter_meta",
    "parameter_cuda1",
    "parameter_fp32",
    "mixed_parameter_device",
    "mixed_parameter_dtype",
    "buffer_device",
    "floating_buffer_dtype",
)


def test_loader_freezes_exact_encoder_placement(tmp_path: Path) -> None:
    torch, diffusers = _Torch(), _Diffusers()
    supply, loaded = _load(tmp_path, torch, diffusers)
    try:
        assert type(loaded._image_encoder_device) is torch.device
        assert loaded._image_encoder_device == torch.device("cuda:0")
        assert loaded._image_encoder_dtype is torch.float16
    finally:
        loaded.close()
        supply.close()


@pytest.mark.parametrize("case", _PLACEMENT_FAILURES)
def test_loader_rejects_invalid_encoder_placement_and_releases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    _install_postload_mutation(
        monkeypatch, lambda encoder, _processor: _mutate_placement(encoder, case)
    )
    supply, graph = _supply(tmp_path)
    torch, diffusers = _Torch(), _Diffusers()
    diffusers.track_issued_pipelines = True
    try:
        with pytest.raises(InfrastructureError, match="pipeline loading failed"):
            load_production_pipeline(
                supply,
                graph,
                _environment(),
                torch_module=torch,
                diffusers_module=diffusers,
            )
        _assert_failed_pipeline_released(diffusers, torch)
    finally:
        supply.close()


@pytest.mark.parametrize("case", _PLACEMENT_FAILURES)
def test_each_borrow_and_encode_revalidates_frozen_encoder_placement(
    tmp_path: Path, case: str
) -> None:
    payload = _png()
    with _encoder_runtime(tmp_path) as runtime:
        _mutate_placement(runtime.pipeline.image_encoder, case)
        for operation in (
            runtime.loaded._borrow_image_evidence_encoder,
            lambda: runtime.capability.encode(payload, hash_bytes(payload)),
        ):
            with pytest.raises(
                InfrastructureError, match="image evidence contract violation"
            ) as raised:
                operation()
            assert raised.value.__cause__ is None
        assert not runtime.processor_calls
        assert not runtime.encoder_calls


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("_image_encoder_device", _Torch.device("cpu")),
        ("_image_encoder_dtype", _FLOAT32),
    ),
)
def test_borrow_rejects_drifted_frozen_placement_fields(
    tmp_path: Path, field: str, replacement: object
) -> None:
    with _encoder_runtime(tmp_path) as runtime:
        object.__setattr__(runtime.loaded, field, replacement)
        with pytest.raises(
            InfrastructureError, match="image evidence contract violation"
        ) as raised:
            _ = runtime.capability.pin
        assert raised.value.__cause__ is None
        assert not runtime.processor_calls
        assert not runtime.encoder_calls


def test_closed_owner_requires_all_six_runtime_references_cleared(
    tmp_path: Path,
) -> None:
    payload = _png()
    with _encoder_runtime(tmp_path) as runtime:
        runtime.loaded.close()
        for field in (
            "_pipeline",
            "_pipeline_identity",
            "_image_encoder",
            "_image_processor",
            "_image_encoder_device",
            "_image_encoder_dtype",
        ):
            assert getattr(runtime.loaded, field) is None
        for operation in (
            lambda: runtime.capability.pin,
            runtime.loaded._borrow_image_evidence_encoder,
            lambda: runtime.capability.encode(payload, hash_bytes(payload)),
        ):
            with pytest.raises(DomainError, match="loaded pipeline is closed"):
                operation()


@pytest.mark.parametrize(
    "field",
    (
        "_pipeline",
        "_pipeline_identity",
        "_image_encoder",
        "_image_processor",
        "_image_encoder_device",
        "_image_encoder_dtype",
    ),
)
def test_closed_owner_with_any_residual_reference_is_contract_violation(
    tmp_path: Path, field: str
) -> None:
    with _encoder_runtime(tmp_path) as runtime:
        residual = getattr(runtime.loaded, field)
        runtime.loaded.close()
        object.__setattr__(runtime.loaded, field, residual)
        with pytest.raises(
            InfrastructureError, match="image evidence contract violation"
        ) as raised:
            _ = runtime.capability.pin
        assert raised.value.__cause__ is None


def _replace_processor_result(runtime: object, pixel_values: object) -> None:
    def process(*args: object, **kwargs: object) -> object:
        runtime.events.append("processor")
        runtime.processor_calls.append((args, kwargs))
        return SimpleNamespace(pixel_values=pixel_values)

    runtime.pipeline.feature_extractor.call_impl = process


def _invalid_raw_pixels(runtime: object, case: str) -> object:
    pixels = runtime.pixel_values
    if case == "subclass":
        return _TensorSubclass(
            pixels.data,
            pixels.events,
            pixels.name,
            shape=pixels.shape,
            device=pixels.device,
            dtype=pixels.dtype,
            contiguous=True,
        )
    if case == "device":
        pixels.device = runtime.torch.device("cuda:0")
    elif case == "dtype":
        pixels.dtype = runtime.torch.float16
    elif case == "shape":
        pixels.shape = (1, 3, 223, 224)
    elif case == "nonfinite":
        pixels.data[0][0][0][0] = math.nan
    elif case == "contiguous":
        pixels._contiguous = False
    elif case == "requires_grad":
        pixels.requires_grad = True
    else:
        raise AssertionError(case)
    return pixels


@pytest.mark.parametrize(
    "case",
    (
        "subclass",
        "device",
        "dtype",
        "shape",
        "nonfinite",
        "contiguous",
        "requires_grad",
    ),
)
def test_processor_raw_pixels_must_be_exact_cpu_float32_owned_tensor(
    tmp_path: Path, case: str
) -> None:
    payload = _png()
    with _encoder_runtime(tmp_path) as runtime:
        _replace_processor_result(runtime, _invalid_raw_pixels(runtime, case))
        with pytest.raises(
            InfrastructureError, match="image evidence contract violation"
        ) as raised:
            runtime.capability.encode(payload, hash_bytes(payload))
        assert raised.value.__cause__ is None
        assert len(runtime.processor_calls) == 1
        assert not runtime.encoder_calls


def test_encode_revalidates_placement_after_processor_before_encoder(
    tmp_path: Path,
) -> None:
    payload = _png()
    with _encoder_runtime(tmp_path) as runtime:
        encoder = runtime.pipeline.image_encoder

        def process(*args: object, **kwargs: object) -> object:
            runtime.events.append("processor")
            runtime.processor_calls.append((args, kwargs))
            encoder._parameters[0].device = runtime.torch.device("cpu")
            return SimpleNamespace(pixel_values=runtime.pixel_values)

        runtime.pipeline.feature_extractor.call_impl = process
        with pytest.raises(
            InfrastructureError, match="image evidence contract violation"
        ):
            runtime.capability.encode(payload, hash_bytes(payload))
        assert len(runtime.processor_calls) == 1
        assert not runtime.encoder_calls


@pytest.mark.parametrize(
    "fault",
    (
        "not_tensor",
        "subclass",
        "device",
        "dtype",
        "shape",
        "nonfinite",
        "contiguous",
        "requires_grad",
    ),
)
def test_transferred_pixels_are_revalidated_before_encoder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    payload = _png()
    with _encoder_runtime(tmp_path) as runtime:
        original_to = _Tensor.to

        def invalid_to(self: _Tensor, *, device: object, dtype: object) -> object:
            result = original_to(self, device=device, dtype=dtype)
            if self.name != "pixels":
                return result
            if fault == "not_tensor":
                return object()
            if fault == "subclass":
                return _TensorSubclass(
                    result.data,
                    result.events,
                    result.name,
                    shape=result.shape,
                    device=result.device,
                    dtype=result.dtype,
                    contiguous=True,
                )
            if fault == "device":
                result.device = runtime.torch.device("cpu")
            elif fault == "dtype":
                result.dtype = runtime.torch.float32
            elif fault == "shape":
                result.shape = (1, 3, 223, 224)
            elif fault == "nonfinite":
                result.data[0][0][0][0] = math.nan
            elif fault == "contiguous":
                result._contiguous = False
            elif fault == "requires_grad":
                result.requires_grad = True
            return result

        monkeypatch.setattr(_Tensor, "to", invalid_to)
        with pytest.raises(
            InfrastructureError, match="image evidence contract violation"
        ) as raised:
            runtime.capability.encode(payload, hash_bytes(payload))
        assert raised.value.__cause__ is None
        assert len(runtime.processor_calls) == 1
        assert not runtime.encoder_calls


@pytest.mark.parametrize(
    ("tensor", "field"),
    (
        ("hidden", "device"),
        ("hidden", "dtype"),
        ("projected", "device"),
        ("projected", "dtype"),
    ),
)
def test_encoder_raw_outputs_must_match_frozen_placement(
    tmp_path: Path, tensor: str, field: str
) -> None:
    payload = _png()
    with _encoder_runtime(tmp_path) as runtime:
        value = getattr(runtime, tensor)
        setattr(
            value,
            field,
            runtime.torch.device("cpu") if field == "device" else runtime.torch.float32,
        )
        with pytest.raises(
            InfrastructureError, match="image evidence contract violation"
        ):
            runtime.capability.encode(payload, hash_bytes(payload))
        assert len(runtime.encoder_calls) == 1


@pytest.mark.parametrize(
    "fault",
    (
        "clone_alias",
        "clone_storage_alias",
        "wrong_shape",
        "device",
        "dtype",
        "contiguous",
        "requires_grad",
        "nonfinite",
    ),
)
def test_encode_rejects_invalid_final_owned_tensor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    payload = _png()
    with _encoder_runtime(tmp_path) as runtime:
        original_clone = _Tensor.clone
        original_to = _Tensor.to
        if fault == "clone_alias":
            monkeypatch.setattr(_Tensor, "clone", lambda self: self)
        elif fault == "clone_storage_alias":

            def alias_storage(self: _Tensor) -> _Tensor:
                result = original_clone(self)
                result.storage = self.storage
                return result

            monkeypatch.setattr(_Tensor, "clone", alias_storage)
        elif fault == "wrong_shape":
            monkeypatch.setattr(
                _Tensor,
                "clone",
                lambda self: _Tensor([1.0], self.events, self.name),
            )
        elif fault == "contiguous":
            monkeypatch.setattr(_Tensor, "contiguous", lambda self: self)
        elif fault in ("requires_grad", "nonfinite"):

            def invalid_clone(self: _Tensor) -> _Tensor:
                result = original_clone(self)
                if fault == "requires_grad":
                    result.requires_grad = True
                else:
                    result.data[0] = math.nan
                return result

            monkeypatch.setattr(_Tensor, "clone", invalid_clone)
        else:

            def invalid_to(self: _Tensor, *, device: object, dtype: object) -> _Tensor:
                result = original_to(self, device=device, dtype=dtype)
                if self.name != "pixels":
                    setattr(
                        result,
                        fault,
                        runtime.torch.device("cuda:0")
                        if fault == "device"
                        else runtime.torch.float16,
                    )
                return result

            monkeypatch.setattr(_Tensor, "to", invalid_to)
        with pytest.raises(
            InfrastructureError, match="image evidence contract violation"
        ):
            runtime.capability.encode(payload, hash_bytes(payload))
