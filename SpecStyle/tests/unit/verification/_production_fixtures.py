"""Private, CPU-only fixtures for production verifier contract tests."""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from PIL import Image

from specstyle.domain.artifacts import ArtifactRef, AssetRef
from specstyle.domain.identifiers import (
    ArtifactId,
    AssetId,
    AttemptId,
    Identifier,
    JobId,
    RuleId,
)
from specstyle.generation.diffusers_loader import load_production_pipeline
from specstyle.generation.preprocess import PreprocessPlan, preprocess_image
from specstyle.generation.protocols import GeneratedArtifact
from specstyle.generation.requests import (
    GenerationRequest,
    PreparedControlInput,
    RenderedPrompt,
)
from specstyle.observability.environment import hash_environment
from specstyle.observability.hashing import hash_bytes
from specstyle.spec.compiled_models import CompilerContext
from specstyle.spec.compiler import compile_style_spec
from tests.unit.generation.test_diffusers_loader import (
    _Diffusers,
    _Device,
    _FLOAT16,
    _Torch,
    _environment,
    _supply,
)
from tests.unit.verification._production_builders import (
    _L1_MAPPINGS,
    _compiler_context,
    _pin,
    _raw_spec,
)


_FLOAT64 = object()


def _png(
    color: tuple[int, int, int] = (32, 64, 96),
    *,
    size: tuple[int, int] = (64, 64),
    mode: str = "RGB",
    metadata: Any = None,
) -> bytes:
    output = BytesIO()
    Image.new(mode, size, color if mode == "RGB" else 1).save(
        output, "PNG", pnginfo=metadata
    )
    return output.getvalue()


def _first_pixel(content: bytes) -> tuple[int, int, int]:
    with Image.open(BytesIO(content)) as image:
        pixel = image.getpixel((0, 0))
    assert type(pixel) is tuple and len(pixel) == 3
    return pixel


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


class _MetricTensor:
    _next_storage = 1

    def __init__(
        self,
        data: list[object],
        *,
        shape: tuple[int, ...] | None = None,
        device: _Device | None = None,
        dtype: object = _FLOAT16,
        contiguous: bool = False,
        requires_grad: bool = False,
        storage: int | None = None,
        events: list[object] | None = None,
        name: str = "tensor",
    ) -> None:
        self.data = copy.deepcopy(data)
        self.shape = _shape(self.data) if shape is None else shape
        self.ndim = len(self.shape)
        self.device = _Device("cuda:0") if device is None else device
        self.dtype = dtype
        self._contiguous = contiguous
        self.requires_grad = requires_grad
        self.storage = self._next_storage if storage is None else storage
        _MetricTensor._next_storage += storage is None
        self.events = [] if events is None else events
        self.name = name

    def _spawn(
        self, data: list[object], *, shape: tuple[int, ...] | None = None
    ) -> _MetricTensor:
        return _MetricTensor(
            data,
            shape=shape,
            device=self.device,
            dtype=self.dtype,
            contiguous=self._contiguous,
            requires_grad=self.requires_grad,
            events=self.events,
            name=self.name,
        )

    def __getitem__(self, key: object) -> _MetricTensor:
        if key == 0:
            return self._spawn(self.data[0])
        if key == (0, slice(1, None), slice(None)):
            return self._spawn(self.data[0][1:])
        raise AssertionError(f"unexpected tensor index: {key!r}")

    def detach(self) -> _MetricTensor:
        self.events.append((self.name, "detach"))
        result = self._spawn(self.data, shape=self.shape)
        result.requires_grad = False
        result.storage = self.storage
        return result

    def to(self, *, device: _Device, dtype: object) -> _MetricTensor:
        self.events.append((self.name, "to", device, dtype))
        result = self._spawn(self.data, shape=self.shape)
        result.device, result.dtype = device, dtype
        return result

    def contiguous(self) -> _MetricTensor:
        self.events.append((self.name, "contiguous"))
        self._contiguous = True
        return self

    def clone(self) -> _MetricTensor:
        self.events.append((self.name, "clone"))
        return self._spawn(self.data, shape=self.shape)

    def is_contiguous(self) -> bool:
        return self._contiguous

    def data_ptr(self) -> int:
        return self.storage

    def mean(self, *, dim: int) -> _MetricTensor:
        assert dim == 0 and self.ndim == 2 and self.data
        rows = self.data
        values = [sum(column) / len(rows) for column in zip(*rows, strict=True)]
        self.events.append((self.name, "mean", dim))
        return self._spawn(values)

    def std(self, *, dim: int, correction: int) -> _MetricTensor:
        assert dim == 0 and correction == 0 and self.ndim == 2 and self.data
        rows = self.data
        means = [sum(column) / len(rows) for column in zip(*rows, strict=True)]
        values = [
            math.sqrt(sum((value - mean) ** 2 for value in column) / len(rows))
            for column, mean in zip(zip(*rows, strict=True), means, strict=True)
        ]
        self.events.append((self.name, "std", dim, correction))
        return self._spawn(values)

    def __truediv__(self, value: float) -> _MetricTensor:
        assert type(value) is float and math.isfinite(value) and value > 0
        return self._spawn([item / value for item in _flatten(self.data)])


class _Scalar:
    def __init__(self, value: float | bool) -> None:
        self.value = value

    def all(self) -> _Scalar:
        return self

    def item(self) -> float | bool:
        return self.value


class _Linalg:
    @staticmethod
    def vector_norm(tensor: _MetricTensor) -> _Scalar:
        return _Scalar(math.sqrt(sum(value * value for value in _flatten(tensor.data))))


class _InferenceMode:
    def __enter__(self) -> None:
        return None

    def __exit__(self, *_: object) -> None:
        return None


class _OOM(RuntimeError):
    pass


def _configure_torch(torch: _Torch) -> None:
    torch.Tensor = _MetricTensor
    torch.float64 = _FLOAT64
    torch.isfinite = lambda tensor: _Scalar(
        all(math.isfinite(value) for value in _flatten(tensor.data))
    )
    torch.linalg = _Linalg()
    torch.inference_mode = _InferenceMode
    torch.OutOfMemoryError = _OOM
    torch.cuda.OutOfMemoryError = _OOM

    def concatenate(values: tuple[_MetricTensor, ...], *, dim: int) -> _MetricTensor:
        assert type(values) is tuple and values and dim == 0
        first = values[0]
        return _MetricTensor(
            [item for value in values for item in _flatten(value.data)],
            device=first.device,
            dtype=first.dtype,
            contiguous=True,
            events=first.events,
            name=first.name,
        )

    def dot(left: _MetricTensor, right: _MetricTensor) -> _Scalar:
        left_values, right_values = _flatten(left.data), _flatten(right.data)
        assert len(left_values) == len(right_values)
        return _Scalar(
            sum(a * b for a, b in zip(left_values, right_values, strict=True))
        )

    torch.cat = concatenate
    torch.dot = dot


class _ArtifactResolver:
    def __init__(self, artifact: GeneratedArtifact) -> None:
        self.value: object = artifact
        self.error: Exception | None = None
        self.calls: list[ArtifactRef] = []

    def __call__(self, reference: ArtifactRef, /) -> object:
        self.calls.append(reference)
        if self.error is not None:
            raise self.error
        return self.value


class _StyleResolver:
    def __init__(self, values: dict[AssetRef, bytes]) -> None:
        self.values: dict[AssetRef, object] = dict(values)
        self.error: Exception | None = None
        self.calls: list[AssetRef] = []

    def __call__(self, reference: AssetRef, /) -> object:
        self.calls.append(reference)
        if self.error is not None:
            raise self.error
        return self.values.get(reference)


@dataclass(slots=True)
class _ProductionCase:
    supply: Any
    loaded: Any
    torch: _Torch
    compiler_context: CompilerContext
    request: GenerationRequest
    plan: Any
    artifact: GeneratedArtifact
    artifact_resolver: _ArtifactResolver
    style_resolver: _StyleResolver
    l1_mappings: tuple[tuple[RuleId, str], ...]
    evidence_vectors: dict[tuple[int, int, int], tuple[list[list[float]], list[float]]]
    evidence_calls: dict[tuple[int, int, int], int]

    def allowlist(
        self,
        production: Any,
        *,
        compiler_context: CompilerContext | None = None,
        provenance: object | None = None,
        mappings: tuple[tuple[RuleId, str], ...] | None = None,
    ) -> object:
        capability = self.loaded._borrow_image_evidence_encoder()
        entries = self.l1_mappings if mappings is None else mappings
        return production._ProductionVerificationAllowlist(
            "specstyle.production_verifier.v1",
            self.compiler_context if compiler_context is None else compiler_context,
            capability.processor_provenance if provenance is None else provenance,
            tuple(production._L1RuleMapping(*entry) for entry in entries),
        )

    def close(self) -> None:
        try:
            self.loaded.close()
        finally:
            self.supply.close()


def _configure_evidence(case: _ProductionCase) -> None:
    pipeline = case.loaded.borrow_pipeline()
    state: dict[str, tuple[int, int, int]] = {}

    def process(*args: object, **kwargs: object) -> object:
        assert args == () and kwargs["return_tensors"] == "pt"
        image = kwargs["images"]
        color = image.getpixel((0, 0))
        state["color"] = color
        pixels = _MetricTensor(
            [[[[1.0]]] * 3],
            shape=(1, 3, 224, 224),
            device=case.torch.device("cpu"),
            dtype=case.torch.float32,
            contiguous=True,
            name="pixels",
        )
        return SimpleNamespace(pixel_values=pixels)

    def encode(*args: object, **kwargs: object) -> object:
        assert len(args) == 1 and kwargs == {
            "output_hidden_states": True,
            "return_dict": True,
        }
        color = state["color"]
        case.evidence_calls[color] = case.evidence_calls.get(color, 0) + 1
        patch, projected = case.evidence_vectors[color]
        cls = [9.0] * len(patch[0])
        hidden = _MetricTensor([[cls, *patch]], name="patch")
        embedding = _MetricTensor([projected], name="projected")
        return SimpleNamespace(
            hidden_states=(object(), hidden, object()), image_embeds=embedding
        )

    pipeline.feature_extractor.call_impl = process
    pipeline.image_encoder.call_impl = encode


def _load_case_pipeline(tmp_path: Path) -> tuple[object, object, _Torch, object]:
    supply, pipeline_graph = _supply(tmp_path)
    torch, diffusers = _Torch(), _Diffusers()
    _configure_torch(torch)
    loaded = load_production_pipeline(
        supply,
        pipeline_graph,
        _environment(),
        torch_module=torch,
        diffusers_module=diffusers,
    )
    return supply, pipeline_graph, torch, loaded


def _compile_case(
    pipeline_graph: object,
    loaded: object,
    styles: tuple[bytes, ...],
    *,
    l2_status: str,
    l3_status: str,
    l3_kind: str,
    l3_requirement: str,
    fidelity_required: bool,
    l1_bundle_actions: tuple[Identifier, ...],
    domain_profile: str,
) -> tuple[CompilerContext, object]:
    capability = loaded._borrow_image_evidence_encoder()
    context = _compiler_context(
        pipeline_graph,
        capability.preprocessing_version,
        l2_status=l2_status,
        l3_status=l3_status,
        l3_kind=l3_kind,
        l3_requirement=l3_requirement,
        l1_bundle_actions=l1_bundle_actions,
        domain_profile=domain_profile,
    )
    raw = _raw_spec(
        pipeline_graph,
        context,
        styles,
        fidelity_required=fidelity_required,
        domain_profile=domain_profile,
    )
    return context, compile_style_spec(raw, context)


def _source_image(content: bytes | None = None) -> object:
    content = _png((200, 10, 10)) if content is None else content
    return preprocess_image(
        content,
        AssetRef(AssetId("source"), hash_bytes(content)),
        PreprocessPlan(
            (64, 64), "contain_pad", (0, 0, 0), _pin("processor", "processor")
        ),
    )


def _generation_request(
    compiled: object, styles: tuple[bytes, ...], source_content: bytes | None = None
) -> tuple[GenerationRequest, tuple[AssetRef, ...]]:
    source = _source_image(source_content)
    graph = compiled.production_graphs[0]
    references = tuple(
        AssetRef(AssetId(f"style-{index}"), hash_bytes(content))
        for index, content in enumerate(styles)
    )
    request = GenerationRequest(
        JobId("job"),
        AttemptId("attempt"),
        None,
        compiled,
        "production",
        "xhs_grid",
        source,
        references,
        RenderedPrompt(
            _pin("template", "template"), graph.preset_id, "positive", "negative"
        ),
        PreparedControlInput("canny", source),
        0,
        hash_environment(_environment()),
    )
    return request, references


def _generated_artifact(
    request: GenerationRequest, content: bytes | None = None
) -> GeneratedArtifact:
    content = _png((10, 200, 10)) if content is None else content
    return GeneratedArtifact(
        ArtifactRef(ArtifactId("artifact"), hash_bytes(content)),
        content,
        request.request_hash,
        request.generation_fingerprint,
    )


def _evidence_vectors(
    styles: tuple[bytes, ...],
) -> dict[tuple[int, int, int], tuple[list[list[float]], list[float]]]:
    vector = ([[1.0, 0.0], [1.0, 0.0]], [1.0, 0.0])
    values = {
        (200, 10, 10): vector,
        (10, 200, 10): vector,
    }
    values.update({_first_pixel(content): vector for content in styles})
    return values


def _make_production_case(
    tmp_path: Path,
    *,
    style_contents: tuple[bytes, ...] | None = None,
    l2_status: str = "VALIDATED",
    l3_status: str = "VALIDATED",
    l3_kind: str = "L3_DIAGNOSTIC",
    l3_requirement: str = "always_advisory",
    fidelity_required: bool = False,
    l1_bundle_actions: tuple[Identifier, ...] = (),
    domain_profile: str = "product_instance",
    source_content: bytes | None = None,
    artifact_content: bytes | None = None,
) -> _ProductionCase:
    styles = (_png((10, 10, 200)),) if style_contents is None else style_contents
    supply, pipeline_graph, torch, loaded = _load_case_pipeline(tmp_path)
    context, compiled = _compile_case(
        pipeline_graph,
        loaded,
        styles,
        l2_status=l2_status,
        l3_status=l3_status,
        l3_kind=l3_kind,
        l3_requirement=l3_requirement,
        fidelity_required=fidelity_required,
        l1_bundle_actions=l1_bundle_actions,
        domain_profile=domain_profile,
    )
    request, references = _generation_request(compiled, styles, source_content)
    artifact = _generated_artifact(request, artifact_content)
    case = _ProductionCase(
        supply,
        loaded,
        torch,
        context,
        request,
        compiled.verification_plans[0],
        artifact,
        _ArtifactResolver(artifact),
        _StyleResolver(dict(zip(references, styles, strict=True))),
        _L1_MAPPINGS,
        _evidence_vectors(styles),
        {},
    )
    _configure_evidence(case)
    return case


@pytest.fixture
def production_case(tmp_path: Path) -> Any:
    case = _make_production_case(tmp_path)
    try:
        yield case
    finally:
        case.close()
