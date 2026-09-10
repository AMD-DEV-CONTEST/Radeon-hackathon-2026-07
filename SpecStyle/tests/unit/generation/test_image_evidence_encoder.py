"""APP-COMPOSE-001B0 verified image-evidence encoder contract."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import pickle
from contextlib import contextmanager
from dataclasses import FrozenInstanceError
from enum import Enum
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Iterator

import pytest
from PIL import Image

import specstyle.generation.diffusers_loader as diffusers_loader_module
from specstyle.domain.identifiers import Sha256
from specstyle.errors import DomainError, InfrastructureError
from specstyle.generation.diffusers_loader import load_production_pipeline
from specstyle.observability.hashing import hash_bytes
from specstyle.spec.compiled_models import ResourcePin
from tests.unit.generation.test_diffusers_loader import (
    _CLIPImageProcessor,
    _CLIPVisionModelWithProjection,
    _Diffusers,
    _Device,
    _FLOAT16,
    _Torch,
    _Transformers,
    _assert_failed_pipeline_released,
    _environment,
    _supply,
)


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def test_capability_exposes_derived_processor_provenance(tmp_path: Path) -> None:
    supply, graph = _supply(tmp_path)
    torch, diffusers = _Torch(), _Diffusers()
    loaded = load_production_pipeline(
        supply, graph, _environment(), torch_module=torch, diffusers_module=diffusers
    )
    try:
        capability = loaded._borrow_image_evidence_encoder()
        provenance = capability.processor_provenance
        processor = loaded.borrow_pipeline().feature_extractor
        normalized_config = processor.to_dict()
        normalized_config["resample"] = processor.resample.value
        expected_config_sha = Sha256(
            hashlib.sha256(_canonical_json(normalized_config)).hexdigest()
        )
        fqname = "transformers.models.clip.image_processing_clip._CLIPImageProcessor"
        identity = {
            "schema": "specstyle.processor_provenance.v1",
            "transformers_version": _Transformers.__version__,
            "class_fqname": fqname,
            "config_sha256": expected_config_sha.value,
        }
        expected_version = (
            "specstyle.clip_image_processor.v1.sha256."
            + hashlib.sha256(_canonical_json(identity)).hexdigest()
        )

        assert type(provenance).__name__ == "_ProcessorProvenance"
        assert not hasattr(provenance, "__dict__")
        assert provenance.transformers_version == _Transformers.__version__
        assert provenance.class_fqname == fqname
        assert provenance.config_sha256 == expected_config_sha
        assert capability.preprocessing_version == expected_version
    finally:
        loaded.close()
        supply.close()


def test_loader_rejects_transformers_distribution_version_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    supply, graph = _supply(tmp_path)
    torch, diffusers = _Torch(), _Diffusers()
    diffusers.track_issued_pipelines = True
    monkeypatch.setattr(
        diffusers_loader_module,
        "_installed_transformers_version",
        lambda: "4.57.2",
        raising=False,
    )
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


def test_loader_rejects_processor_class_outside_transformers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    supply, graph = _supply(tmp_path)
    torch, diffusers = _Torch(), _Diffusers()
    diffusers.track_issued_pipelines = True
    monkeypatch.setattr(_CLIPImageProcessor, "__module__", "untrusted.processor")
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


class _DictSubclass(dict):
    pass


class _ListSubclass(list):
    pass


class _IntSubclass(int):
    pass


class _StrSubclass(str):
    pass


@pytest.mark.parametrize(
    "invalid_config",
    [
        [],
        _DictSubclass(ok=True),
        {1: "non-string-key"},
        {"value": float("nan")},
        {"value": float("inf")},
        {"value": _ListSubclass([1])},
        {"value": _DictSubclass(ok=True)},
        {"value": _IntSubclass(1)},
        {"value": _StrSubclass("x")},
        {"value": object()},
    ],
)
def test_loader_rejects_noncanonical_processor_config_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    invalid_config: object,
) -> None:
    supply, graph = _supply(tmp_path)
    torch, diffusers = _Torch(), _Diffusers()
    diffusers.track_issued_pipelines = True
    monkeypatch.setattr(_CLIPImageProcessor, "to_dict", lambda self: invalid_config)
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


def test_processor_provenance_canonicalizes_tuples_and_enums(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Choice(Enum):
        ITEM = "item"

    config = {"tuple": (Choice.ITEM, {"nested": (1, 2)})}
    monkeypatch.setattr(_CLIPImageProcessor, "to_dict", lambda self: config)
    supply, graph = _supply(tmp_path)
    torch, diffusers = _Torch(), _Diffusers()
    loaded = load_production_pipeline(
        supply, graph, _environment(), torch_module=torch, diffusers_module=diffusers
    )
    try:
        provenance = loaded._borrow_image_evidence_encoder().processor_provenance
        expected = _canonical_json({"tuple": ["item", {"nested": [1, 2]}]})
        assert provenance.config_sha256 == Sha256(hashlib.sha256(expected).hexdigest())
    finally:
        loaded.close()
        supply.close()


@pytest.mark.parametrize("drift", ["config", "property"])
def test_each_image_evidence_borrow_rejects_processor_drift(
    tmp_path: Path, drift: str
) -> None:
    supply, graph = _supply(tmp_path)
    torch, diffusers = _Torch(), _Diffusers()
    loaded = load_production_pipeline(
        supply, graph, _environment(), torch_module=torch, diffusers_module=diffusers
    )
    try:
        loaded._borrow_image_evidence_encoder()
        processor = loaded.borrow_pipeline().feature_extractor
        if drift == "config":
            processor.provenance_extra = "changed"
        else:
            processor.do_resize = False
        with pytest.raises(
            InfrastructureError, match="image evidence contract violation"
        ):
            loaded._borrow_image_evidence_encoder()
    finally:
        loaded.close()
        supply.close()


def _shape(data: object) -> tuple[int, ...]:
    if type(data) is not list:
        return ()
    if not data:
        return (0,)
    child = _shape(data[0])
    assert all(_shape(item) == child for item in data)
    return (len(data), *child)


def _flatten(data: object) -> list[float]:
    if type(data) is list:
        return [value for item in data for value in _flatten(item)]
    return [float(data)]


class _Tensor:
    _next_storage = 1

    def __init__(
        self,
        data: list[object],
        events: list[object],
        name: str,
        *,
        shape: tuple[int, ...] | None = None,
        device: _Device | None = None,
        dtype: object = _FLOAT16,
        contiguous: bool = False,
        requires_grad: bool = False,
        storage: int | None = None,
    ) -> None:
        self.data = copy.deepcopy(data)
        self.events = events
        self.name = name
        self.shape = _shape(self.data) if shape is None else shape
        self.ndim = len(self.shape)
        self.device = _Device("cuda:0") if device is None else device
        self.dtype = dtype
        self._contiguous = contiguous
        self.requires_grad = requires_grad
        self.storage = _Tensor._next_storage if storage is None else storage
        _Tensor._next_storage += storage is None

    def _spawn(
        self, data: list[object], shape: tuple[int, ...] | None = None
    ) -> _Tensor:
        return _Tensor(
            data,
            self.events,
            self.name,
            shape=shape,
            device=self.device,
            dtype=self.dtype,
            contiguous=self._contiguous,
            requires_grad=self.requires_grad,
        )

    def __getitem__(self, key: object) -> _Tensor:
        if key == 0:
            return self._spawn(self.data[0])
        if (
            type(key) is tuple
            and len(key) == 3
            and key[0] == 0
            and key[1] == slice(1, None)
            and key[2] == slice(None)
        ):
            return self._spawn(self.data[0][1:])
        raise AssertionError(f"unexpected tensor index: {key!r}")

    def detach(self) -> _Tensor:
        self.events.append((self.name, "detach"))
        result = self._spawn(self.data, self.shape)
        result.requires_grad = False
        result.storage = self.storage
        return result

    def clone(self) -> _Tensor:
        self.events.append((self.name, "clone"))
        return self._spawn(self.data, self.shape)

    def contiguous(self) -> _Tensor:
        self.events.append((self.name, "contiguous"))
        self._contiguous = True
        return self

    def is_contiguous(self) -> bool:
        return self._contiguous

    def to(self, *, device: _Device, dtype: object) -> _Tensor:
        self.events.append((self.name, "to", device, dtype))
        result = self._spawn(self.data, self.shape)
        result.device, result.dtype = device, dtype
        return result

    def data_ptr(self) -> int:
        return self.storage


class _Scalar:
    def __init__(self, value: float | bool) -> None:
        self.value = value

    def all(self) -> _Scalar:
        return self

    def item(self) -> float | bool:
        return self.value


class _Linalg:
    @staticmethod
    def vector_norm(tensor: _Tensor) -> _Scalar:
        return _Scalar(math.sqrt(sum(value * value for value in _flatten(tensor.data))))


class _InferenceMode:
    def __init__(self, events: list[object]) -> None:
        self.events = events

    def __enter__(self) -> None:
        self.events.append("inference_enter")

    def __exit__(self, *_: object) -> None:
        self.events.append("inference_exit")


class _OOM(RuntimeError):
    pass


def _png(*, mode: str = "RGB") -> bytes:
    output = BytesIO()
    Image.new(mode, (2, 2), 1).save(output, "PNG")
    return output.getvalue()


def _animated_gif() -> bytes:
    output = BytesIO()
    first = Image.new("RGB", (2, 2), "red")
    second = Image.new("RGB", (2, 2), "blue")
    first.save(output, "GIF", save_all=True, append_images=[second])
    return output.getvalue()


@contextmanager
def _encoder_runtime(tmp_path: Path) -> Iterator[SimpleNamespace]:
    supply, graph = _supply(tmp_path)
    torch, diffusers = _Torch(), _Diffusers()
    loaded = load_production_pipeline(
        supply, graph, _environment(), torch_module=torch, diffusers_module=diffusers
    )
    events: list[object] = []
    torch.Tensor = _Tensor
    torch.inference_mode = lambda: _InferenceMode(events)
    torch.isfinite = lambda tensor: _Scalar(
        all(math.isfinite(value) for value in _flatten(tensor.data))
    )
    torch.linalg = _Linalg()
    torch.OutOfMemoryError = _OOM
    torch.cuda.OutOfMemoryError = _OOM
    pipeline = loaded.borrow_pipeline()
    pixel_values = _Tensor(
        [[[[1.0, 1.0], [1.0, 1.0]]] * 3],
        events,
        "pixels",
        shape=(1, 3, 224, 224),
        device=torch.device("cpu"),
        dtype=torch.float32,
        contiguous=True,
    )
    hidden = _Tensor([[[9.0, 9.0], [1.0, 2.0], [3.0, 4.0]]], events, "patch")
    projected = _Tensor([[3.0, 4.0, 0.0]], events, "projected")
    processor_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
    encoder_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def process(*args: object, **kwargs: object) -> object:
        events.append("processor")
        processor_calls.append((args, kwargs))
        return SimpleNamespace(pixel_values=pixel_values)

    def encode(*args: object, **kwargs: object) -> object:
        events.append("encoder")
        encoder_calls.append((args, kwargs))
        return SimpleNamespace(
            hidden_states=(object(), hidden, object()),
            image_embeds=projected,
        )

    pipeline.feature_extractor.call_impl = process
    pipeline.image_encoder.call_impl = encode
    runtime = SimpleNamespace(
        supply=supply,
        graph=graph,
        torch=torch,
        loaded=loaded,
        pipeline=pipeline,
        capability=loaded._borrow_image_evidence_encoder(),
        events=events,
        pixel_values=pixel_values,
        hidden=hidden,
        projected=projected,
        processor_calls=processor_calls,
        encoder_calls=encoder_calls,
    )
    try:
        yield runtime
    finally:
        loaded.close()
        supply.close()


def test_image_evidence_capability_is_issued_only_and_owner_only(
    tmp_path: Path,
) -> None:
    with _encoder_runtime(tmp_path) as runtime:
        capability = runtime.capability
        capability_type = type(capability)
        assert capability_type.__name__ == "_VerifiedImageEvidenceEncoder"
        assert capability_type.__slots__ == ("_owner", "_seal")
        assert not hasattr(capability, "_image_encoder")
        assert not hasattr(capability, "_image_processor")
        assert capability.pin == ResourcePin(
            runtime.graph.ip_adapter.model_id,
            runtime.graph.ip_adapter.revision,
            runtime.graph.ip_adapter.expected_sha256,
        )
        assert capability.layer == "hidden_states[-2]"
        with pytest.raises(TypeError):
            capability_type()
        with pytest.raises(TypeError):
            copy.copy(capability)
        with pytest.raises(TypeError):
            copy.deepcopy(capability)
        with pytest.raises(TypeError):
            pickle.dumps(capability)


def test_close_clears_image_evidence_refs_and_invalidates_old_capability(
    tmp_path: Path,
) -> None:
    with _encoder_runtime(tmp_path) as runtime:
        runtime.loaded.close()
        assert runtime.loaded._pipeline is None
        assert runtime.loaded._image_encoder is None
        assert runtime.loaded._image_processor is None
        with pytest.raises(DomainError, match="loaded pipeline is closed"):
            _ = runtime.capability.pin


@pytest.mark.parametrize("identity", ["pipeline", "encoder", "processor"])
def test_borrow_rejects_each_image_evidence_identity_drift(
    tmp_path: Path, identity: str
) -> None:
    with _encoder_runtime(tmp_path) as runtime:
        original = runtime.loaded._pipeline
        if identity == "pipeline":
            replacement = SimpleNamespace(
                image_encoder=runtime.pipeline.image_encoder,
                feature_extractor=runtime.pipeline.feature_extractor,
            )
            object.__setattr__(runtime.loaded, "_pipeline", replacement)
        elif identity == "encoder":
            runtime.pipeline.image_encoder = _CLIPVisionModelWithProjection()
        else:
            runtime.pipeline.feature_extractor = _CLIPImageProcessor()
        try:
            with pytest.raises(
                InfrastructureError, match="image evidence contract violation"
            ):
                runtime.loaded._borrow_image_evidence_encoder()
        finally:
            object.__setattr__(runtime.loaded, "_pipeline", original)


def test_capability_rejects_tampered_seal(tmp_path: Path) -> None:
    with _encoder_runtime(tmp_path) as runtime:
        object.__setattr__(runtime.capability, "_seal", object())
        with pytest.raises(
            DomainError, match="invalid image evidence encoder capability"
        ):
            _ = runtime.capability.pin


def test_encode_returns_owned_cpu_float32_evidence_with_exact_calls(
    tmp_path: Path,
) -> None:
    image_bytes = _png()
    with _encoder_runtime(tmp_path) as runtime:
        evidence = runtime.capability.encode(image_bytes, hash_bytes(image_bytes))

        assert type(evidence).__name__ == "_VerifiedImageEvidence"
        assert not hasattr(evidence, "__dict__")
        assert evidence.asset_sha256 == hash_bytes(image_bytes)
        assert evidence.patch_hidden_state.data == [[1.0, 2.0], [3.0, 4.0]]
        assert evidence.projected_embedding.data == [3.0, 4.0, 0.0]
        for tensor in (
            evidence.patch_hidden_state,
            evidence.projected_embedding,
        ):
            assert tensor.device == runtime.torch.device("cpu")
            assert tensor.dtype is runtime.torch.float32
            assert tensor.is_contiguous() is True
            assert tensor.requires_grad is False
        assert len(runtime.processor_calls) == 1
        assert runtime.processor_calls[0][0] == ()
        assert runtime.processor_calls[0][1]["images"].mode == "RGB"
        assert runtime.processor_calls[0][1]["return_tensors"] == "pt"
        assert len(runtime.encoder_calls) == 1
        encoder_pixels = runtime.encoder_calls[0][0][0]
        assert encoder_pixels is not runtime.pixel_values
        assert encoder_pixels.device == runtime.torch.device("cuda:0")
        assert encoder_pixels.dtype is runtime.torch.float16
        assert runtime.encoder_calls[0][1] == {
            "output_hidden_states": True,
            "return_dict": True,
        }
        assert (
            runtime.events.index("inference_enter")
            < runtime.events.index("encoder")
            < runtime.events.index("inference_exit")
        )
        assert runtime.events.count("processor") == 1
        assert runtime.events.count("encoder") == 1
        for name in ("patch", "projected"):
            operations = [event[1] for event in runtime.events if event[:1] == (name,)]
            assert operations == ["detach", "to", "contiguous", "clone"]
        runtime.hidden.data[0][1][0] = 99.0
        runtime.projected.data[0][0] = 99.0
        assert evidence.patch_hidden_state.data[0][0] == 1.0
        assert evidence.projected_embedding.data[0] == 3.0
        with pytest.raises(FrozenInstanceError):
            evidence.asset_sha256 = Sha256("0" * 64)
        with pytest.raises(TypeError):
            runtime.capability.encode(
                image_bytes=image_bytes, asset_sha256=hash_bytes(image_bytes)
            )


class _BytesSubclass(bytes):
    pass


@pytest.mark.parametrize(
    "payload",
    [
        "not-bytes",
        _BytesSubclass(_png()),
        b"not-an-image",
        _png(mode="RGBA"),
        _animated_gif(),
    ],
)
def test_encode_rejects_invalid_image_input_without_running_models(
    tmp_path: Path, payload: object
) -> None:
    with _encoder_runtime(tmp_path) as runtime:
        digest = hash_bytes(payload) if type(payload) is bytes else Sha256("0" * 64)
        with pytest.raises(DomainError, match="invalid image evidence input"):
            runtime.capability.encode(payload, digest)
        assert not runtime.processor_calls
        assert not runtime.encoder_calls


def test_encode_rejects_hash_mismatch_and_nonexact_digest(tmp_path: Path) -> None:
    payload = _png()
    with _encoder_runtime(tmp_path) as runtime:
        for digest in (Sha256("0" * 64), hash_bytes(payload).value):
            with pytest.raises(DomainError, match="invalid image evidence input"):
                runtime.capability.encode(payload, digest)
        assert not runtime.processor_calls
        assert not runtime.encoder_calls


@pytest.mark.parametrize(
    "case",
    [
        "missing_hidden_states",
        "hidden_states_not_tuple",
        "hidden_states_too_short",
        "hidden_wrong_rank",
        "hidden_wrong_batch",
        "hidden_without_patch",
        "hidden_zero_width",
        "missing_projected",
        "projected_wrong_rank",
        "projected_wrong_batch",
        "projected_empty",
        "patch_nonfinite",
        "patch_zero_norm",
        "projected_nonfinite",
        "projected_zero_norm",
    ],
)
def test_encode_rejects_each_malformed_encoder_output(
    tmp_path: Path, case: str
) -> None:
    payload = _png()
    with _encoder_runtime(tmp_path) as runtime:
        hidden = runtime.hidden
        projected = runtime.projected
        hidden_states: object = (object(), hidden, object())
        if case == "hidden_states_not_tuple":
            hidden_states = [object(), hidden, object()]
        elif case == "hidden_states_too_short":
            hidden_states = (hidden,)
        elif case == "hidden_wrong_rank":
            hidden = _Tensor([[1.0, 2.0]], runtime.events, "patch")
            hidden_states = (object(), hidden, object())
        elif case == "hidden_wrong_batch":
            hidden = _Tensor([[[1.0], [2.0]], [[3.0], [4.0]]], runtime.events, "patch")
            hidden_states = (object(), hidden, object())
        elif case == "hidden_without_patch":
            hidden = _Tensor([[[1.0, 2.0]]], runtime.events, "patch")
            hidden_states = (object(), hidden, object())
        elif case == "hidden_zero_width":
            hidden = _Tensor([[[], []]], runtime.events, "patch")
            hidden_states = (object(), hidden, object())
        elif case == "projected_wrong_rank":
            projected = _Tensor([1.0, 2.0], runtime.events, "projected")
        elif case == "projected_wrong_batch":
            projected = _Tensor([[1.0], [2.0]], runtime.events, "projected")
        elif case == "projected_empty":
            projected = _Tensor([[]], runtime.events, "projected")
        elif case == "patch_nonfinite":
            hidden = _Tensor([[[9.0], [float("nan")]]], runtime.events, "patch")
            hidden_states = (object(), hidden, object())
        elif case == "patch_zero_norm":
            hidden = _Tensor([[[9.0], [0.0]]], runtime.events, "patch")
            hidden_states = (object(), hidden, object())
        elif case == "projected_nonfinite":
            projected = _Tensor([[float("inf")]], runtime.events, "projected")
        elif case == "projected_zero_norm":
            projected = _Tensor([[0.0, 0.0]], runtime.events, "projected")

        def malformed(*args: object, **kwargs: object) -> object:
            runtime.events.append("encoder")
            runtime.encoder_calls.append((args, kwargs))
            values: dict[str, object] = {}
            if case != "missing_hidden_states":
                values["hidden_states"] = hidden_states
            if case != "missing_projected":
                values["image_embeds"] = projected
            return SimpleNamespace(**values)

        runtime.pipeline.image_encoder.call_impl = malformed
        with pytest.raises(
            InfrastructureError, match="image evidence contract violation"
        ) as raised:
            runtime.capability.encode(payload, hash_bytes(payload))
        assert raised.value.__cause__ is None
        assert len(runtime.processor_calls) == 1
        assert len(runtime.encoder_calls) == 1


@pytest.mark.parametrize("case", ["missing", "wrong_shape", "nonfinite"])
def test_encode_rejects_malformed_processor_output(tmp_path: Path, case: str) -> None:
    payload = _png()
    with _encoder_runtime(tmp_path) as runtime:

        def malformed(*args: object, **kwargs: object) -> object:
            runtime.events.append("processor")
            runtime.processor_calls.append((args, kwargs))
            if case == "missing":
                return SimpleNamespace()
            if case == "wrong_shape":
                return SimpleNamespace(
                    pixel_values=_Tensor([[[[1.0]]]], runtime.events, "pixels")
                )
            return SimpleNamespace(
                pixel_values=_Tensor(
                    [[[[float("nan")]] * 2] * 3], runtime.events, "pixels"
                )
            )

        runtime.pipeline.feature_extractor.call_impl = malformed
        with pytest.raises(
            InfrastructureError, match="image evidence contract violation"
        ):
            runtime.capability.encode(payload, hash_bytes(payload))
        assert len(runtime.processor_calls) == 1
        assert not runtime.encoder_calls


@pytest.mark.parametrize("stage", ["processor", "encoder"])
def test_encode_maps_oom_and_clears_cache(tmp_path: Path, stage: str) -> None:
    payload = _png()
    with _encoder_runtime(tmp_path) as runtime:
        target = (
            runtime.pipeline.feature_extractor
            if stage == "processor"
            else runtime.pipeline.image_encoder
        )
        target.call_impl = lambda *args, **kwargs: (_ for _ in ()).throw(_OOM())
        before = runtime.torch.cuda.empty_cache_calls
        with pytest.raises(InfrastructureError, match="image evidence OOM") as raised:
            runtime.capability.encode(payload, hash_bytes(payload))
        assert raised.value.__cause__ is None
        assert raised.value.__context__ is None
        assert runtime.torch.cuda.empty_cache_calls == before + 1


@pytest.mark.parametrize("stage", ["processor", "encoder"])
def test_encode_maps_other_runtime_failures(tmp_path: Path, stage: str) -> None:
    payload = _png()
    with _encoder_runtime(tmp_path) as runtime:
        target = (
            runtime.pipeline.feature_extractor
            if stage == "processor"
            else runtime.pipeline.image_encoder
        )
        target.call_impl = lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("secret")
        )
        with pytest.raises(
            InfrastructureError, match="image evidence encoding failed"
        ) as raised:
            runtime.capability.encode(payload, hash_bytes(payload))
        assert raised.value.__cause__ is None
        assert raised.value.__context__ is None


def test_encode_rechecks_processor_provenance_before_runtime(tmp_path: Path) -> None:
    payload = _png()
    with _encoder_runtime(tmp_path) as runtime:
        runtime.pipeline.feature_extractor.provenance_extra = "changed"
        with pytest.raises(
            InfrastructureError, match="image evidence contract violation"
        ):
            runtime.capability.encode(payload, hash_bytes(payload))
        assert not runtime.processor_calls
        assert not runtime.encoder_calls
