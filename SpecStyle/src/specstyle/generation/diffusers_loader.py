"""Verified, local-only Diffusers/ROCm production loader."""

from __future__ import annotations

import importlib
import gc
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Any

from specstyle.domain.identifiers import Sha256
from specstyle.errors import DomainError, InfrastructureError, _GpuOutOfMemoryError
from specstyle.generation.image_evidence import (
    _EVIDENCE_CONTRACT_ERROR,
    _ProcessorProvenance,
    _VerifiedImageEvidence,
    _build_processor_provenance,
    _classify_encoding_failure,
    _close_image_quietly,
    _decode_image_evidence_input,
    _derive_preprocessing_version,
    _encoder_placement,
    _is_torch_oom,
    _run_image_evidence_encoder,
    _validate_frozen_encoder_placement,
    _validate_image_processor,
)
from specstyle.generation.local_weights import ResolvedWeight
from specstyle.generation.model_approval import VerifiedPipelineSupply
from specstyle.generation.pipeline_factory import PipelineGraph
from specstyle.generation.rocm_probe import RocmProbeResult
from specstyle.observability.environment import EnvironmentSnapshot, hash_environment
from specstyle.spec.compiled_models import ResourcePin

PipelineBuilder = Callable[[PipelineGraph, tuple[ResolvedWeight, ...]], Any]
_CAPABILITY_SEAL = object()
_ROCM_VERSION = "7.2.1"
_DIFFUSERS_VERSION = "0.39.0"
_IMAGE_EVIDENCE_CAPABILITY_SEAL = object()
_EVIDENCE_LAYER = "hidden_states[-2]"
_GPU_LEASE = threading.RLock()


@dataclass(frozen=True, slots=True, init=False)
class LoadedPipeline:
    """A loader-issued capability; the verified model supply remains caller-owned."""

    _pipeline: Any = field(repr=False, compare=False)
    _pipeline_identity: Any = field(repr=False, compare=False)
    _graph: PipelineGraph = field(repr=False, compare=False)
    _environment_hash: Sha256 = field(repr=False, compare=False)
    _runtime: tuple[str, str, str, str] = field(repr=False, compare=False)
    _torch: Any = field(repr=False, compare=False)
    _image_encoder: Any = field(repr=False, compare=False)
    _image_processor: Any = field(repr=False, compare=False)
    _image_encoder_device: Any = field(repr=False, compare=False)
    _image_encoder_dtype: Any = field(repr=False, compare=False)
    _image_encoder_pin: ResourcePin = field(repr=False, compare=False)
    _transformers: Any = field(repr=False, compare=False)
    _processor_provenance: _ProcessorProvenance = field(repr=False, compare=False)
    _closed: bool = field(repr=False, compare=False)
    _seal: object = field(repr=False, compare=False)

    def __init__(self, *_: object, **__: object) -> None:
        raise TypeError("loaded pipelines are issued only by the production loader")

    def borrow_pipeline(self, /) -> Any:
        _validate_loaded_pipeline(self, require_open=True)
        return self._pipeline

    def _borrow_image_evidence_encoder(self, /) -> _VerifiedImageEvidenceEncoder:
        _validate_image_evidence_owner(self)
        capability = object.__new__(_VerifiedImageEvidenceEncoder)
        object.__setattr__(capability, "_owner", self)
        object.__setattr__(capability, "_seal", _IMAGE_EVIDENCE_CAPABILITY_SEAL)
        return capability

    def close(self) -> None:
        with _GPU_LEASE:
            self._close_under_lease()

    def _close_under_lease(self) -> None:
        _validate_loaded_pipeline(self, require_open=False)
        if self._closed:
            return
        pipeline = self._pipeline
        object.__setattr__(self, "_closed", True)
        object.__setattr__(self, "_pipeline", None)
        object.__setattr__(self, "_pipeline_identity", None)
        object.__setattr__(self, "_image_encoder", None)
        object.__setattr__(self, "_image_processor", None)
        object.__setattr__(self, "_image_encoder_device", None)
        object.__setattr__(self, "_image_encoder_dtype", None)
        failure: InfrastructureError | None = None
        try:
            _release_resource(pipeline)
        except Exception:
            failure = InfrastructureError("pipeline release failed")
        pipeline = None
        gc.collect()
        _empty_cache(self._torch)
        if failure is not None:
            raise failure

    def __copy__(self) -> LoadedPipeline:
        raise TypeError("loaded pipelines cannot be copied")

    def __deepcopy__(self, _memo: dict[int, object]) -> LoadedPipeline:
        raise TypeError("loaded pipelines cannot be copied")

    def __reduce_ex__(self, _protocol: int) -> object:
        raise TypeError("loaded pipelines cannot be serialized")


@dataclass(frozen=True, slots=True, init=False)
class _VerifiedImageEvidenceEncoder:
    _owner: LoadedPipeline = field(repr=False, compare=False)
    _seal: object = field(repr=False, compare=False)

    def __init__(self, *_: object, **__: object) -> None:
        raise TypeError("image evidence encoders are issued only by loaded pipelines")

    @property
    def pin(self) -> ResourcePin:
        _validate_image_evidence_encoder(self)
        return self._owner._image_encoder_pin

    @property
    def processor_provenance(self) -> _ProcessorProvenance:
        _validate_image_evidence_encoder(self)
        return self._owner._processor_provenance

    @property
    def preprocessing_version(self) -> str:
        _validate_image_evidence_encoder(self)
        return _derive_preprocessing_version(self._owner._processor_provenance)

    @property
    def layer(self) -> str:
        _validate_image_evidence_encoder(self)
        return _EVIDENCE_LAYER

    def encode(
        self, image_bytes: bytes, asset_sha256: Sha256, /
    ) -> _VerifiedImageEvidence:
        with _GPU_LEASE:
            _validate_image_evidence_encoder(self)
            return _encode_image_evidence(self._owner, image_bytes, asset_sha256)

    def __copy__(self) -> _VerifiedImageEvidenceEncoder:
        raise TypeError("image evidence encoders cannot be copied")

    def __deepcopy__(self, _memo: dict[int, object]) -> _VerifiedImageEvidenceEncoder:
        raise TypeError("image evidence encoders cannot be copied")

    def __reduce_ex__(self, _protocol: int) -> object:
        raise TypeError("image evidence encoders cannot be serialized")


@dataclass(frozen=True, slots=True)
class LoadPlan:
    graph: PipelineGraph
    base: ResolvedWeight
    ip_adapter: ResolvedWeight
    controlnet: ResolvedWeight
    preview: ResolvedWeight | None
    rocm: RocmProbeResult


def plan_local_load(
    graph: PipelineGraph,
    cache_root: Path,
    relpaths: dict[str, str],
    *,
    require_gpu: bool = True,
    torch_module: Any | None = None,
) -> LoadPlan:
    """Fail closed: this pre-manifest entry point is not production-authorized."""
    raise DomainError("legacy production loader disabled; verified supply required")


def load_pipeline(
    plan: LoadPlan,
    *,
    builder: PipelineBuilder | None = None,
    local_files_only: bool = True,
) -> Any:
    """Fail closed before builders or download flags can affect behavior."""
    raise DomainError("legacy production loader disabled; verified supply required")


def _plain_expected_text(value: object) -> object:
    """Normalize TorchVersion-like package versions to plain str for comparison."""
    if value is None or type(value) is str:
        return value
    try:
        text = str(value)
    except Exception:
        return value
    return text if type(text) is str else value


def _require_text(observation: object, expected: object) -> None:
    expected = _plain_expected_text(expected)
    if (
        getattr(observation, "status", None) != "AVAILABLE"
        or getattr(observation, "value", None) != expected
        or getattr(observation, "reason", None) is not None
    ):
        raise DomainError("production environment mismatch")


def _validate_environment(environment: object, torch: Any, diffusers: Any) -> Sha256:
    if type(environment) is not EnvironmentSnapshot:
        raise DomainError("invalid production environment")
    _require_text(environment.rocm_version, _ROCM_VERSION)
    _require_text(environment.hip_version, getattr(torch.version, "hip", None))
    _require_text(environment.pytorch_version, getattr(torch, "__version__", None))
    _require_text(environment.diffusers_version, _DIFFUSERS_VERSION)
    if (
        _plain_expected_text(getattr(diffusers, "__version__", None))
        != _DIFFUSERS_VERSION
    ):
        raise DomainError("production environment mismatch")
    devices = environment.hip_devices
    if getattr(devices, "status", None) != "AVAILABLE" or not devices.devices:
        raise DomainError("production environment mismatch")
    cuda = getattr(torch, "cuda", None)
    if (
        cuda is None
        or cuda.is_available() is not True
        or cuda.device_count() != len(devices.devices)
    ):
        raise DomainError("production device mismatch")
    for index, device in enumerate(devices.devices):
        if device.index != index:
            raise DomainError("production device mismatch")
        properties = cuda.get_device_properties(index)
        _require_text(device.name, cuda.get_device_name(index))
        _require_integer(device.total_memory_bytes, properties.total_memory)
        _require_text(device.gfx_arch, getattr(properties, "gcnArchName", None))
    return hash_environment(environment)


def _require_integer(observation: object, expected: object) -> None:
    if (
        getattr(observation, "status", None) != "AVAILABLE"
        or getattr(observation, "value", None) != expected
        or getattr(observation, "reason", None) is not None
    ):
        raise DomainError("production environment mismatch")


def _validated_components(supply: object, graph: object) -> dict[str, Any]:
    if type(supply) is not VerifiedPipelineSupply or type(graph) is not PipelineGraph:
        raise DomainError("invalid verified production supply")
    if graph.profile != "production" or graph.preview_adapter is not None:
        raise DomainError("invalid production pipeline graph")
    models = supply.models
    descriptors = (graph.base, graph.ip_adapter, graph.controlnet)
    roles = ("base", "ip_adapter", "controlnet")
    if tuple(item.role for item in descriptors) != roles:
        raise DomainError("invalid production pipeline graph")
    by_role = {component.role: component for component in models}
    if tuple(by_role) != roles:
        raise DomainError("invalid verified production supply")
    for descriptor, role in zip(descriptors, roles):
        component = by_role[role]
        if (
            component.model_id != descriptor.model_id
            or component.manifest.model_id != descriptor.model_id
            or component.manifest.revision != descriptor.revision
            or component.manifest.root_sha256 != descriptor.expected_sha256
            or component.approval.revision != descriptor.revision
        ):
            raise DomainError("graph and verified supply mismatch")
    return by_role


def _pretrained_kwargs(entrypoint: Any, torch: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "subfolder": entrypoint.subfolder,
        "local_files_only": True,
        "use_safetensors": True,
        "torch_dtype": torch.float16,
    }
    if entrypoint.variant is not None:
        kwargs["variant"] = entrypoint.variant
    return kwargs


def _joined_component_root(component_path: str, entrypoint: Any) -> str:
    """Join verified component fd path with entrypoint subfolder.

    Diffusers pipeline ``load_config`` fails for ``/proc/self/fd/N`` + ``subfolder=``
    (it looks for ``model_index.json`` on the fd root). Joining works for both
    ControlNet model loads and full SDXL pipelines.
    """
    if type(component_path) is not str or not component_path:
        raise InfrastructureError("pipeline loading failed")
    subfolder = getattr(entrypoint, "subfolder", None)
    if type(subfolder) is not str or not subfolder:
        raise InfrastructureError("pipeline loading failed")
    return f"{component_path.rstrip('/')}/{subfolder}"


def _pretrained_load_kwargs(entrypoint: Any, torch: Any) -> dict[str, Any]:
    """Kwargs for from_pretrained after the subfolder is joined into the root path."""
    kwargs = _pretrained_kwargs(entrypoint, torch)
    kwargs.pop("subfolder", None)
    return kwargs


def _ip_adapter_kwargs(entrypoint: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "subfolder": entrypoint.subfolder,
        "weight_name": entrypoint.weight_name,
        "local_files_only": True,
        "use_safetensors": True,
    }
    if entrypoint.image_encoder_folder is not None:
        kwargs["image_encoder_folder"] = entrypoint.image_encoder_folder
    if entrypoint.variant is not None:
        kwargs["variant"] = entrypoint.variant
    return kwargs


def _import_transformers() -> Any:
    return importlib.import_module("transformers")


def _installed_transformers_version() -> str:
    return importlib_metadata.version("transformers")


def _map_encoding_failure(error: BaseException, torch: Any) -> InfrastructureError:
    failure_kind = _classify_encoding_failure(error, torch)
    if failure_kind == "oom":
        gc.collect()
        _empty_cache(torch)
        return _GpuOutOfMemoryError("image evidence OOM")
    if failure_kind == "contract":
        return InfrastructureError("image evidence contract violation")
    return InfrastructureError("image evidence encoding failed")


def _encode_image_evidence(
    owner: LoadedPipeline, image_bytes: object, asset_sha256: object
) -> _VerifiedImageEvidence:
    image = _decode_image_evidence_input(image_bytes, asset_sha256)
    failure: InfrastructureError | None = None
    try:
        patch, projected = _run_image_evidence_encoder(
            owner._image_processor,
            owner._image_encoder,
            owner._torch,
            owner._image_encoder_device,
            owner._image_encoder_dtype,
            image,
        )
    except Exception as error:
        failure = _map_encoding_failure(error, owner._torch)
    finally:
        _close_image_quietly(image)
    if failure is not None:
        raise failure
    return _VerifiedImageEvidence(asset_sha256, patch, projected)


def _empty_cache(torch: Any) -> None:
    try:
        torch.cuda.empty_cache()
    except Exception:
        pass


def _release_resource(resource: Any) -> None:
    if resource is None:
        return
    failure = False
    if hasattr(resource, "maybe_free_model_hooks"):
        try:
            resource.maybe_free_model_hooks()
        except Exception:
            failure = True
    if hasattr(resource, "to"):
        try:
            resource.to("cpu")
        except Exception:
            failure = True
    if failure:
        raise InfrastructureError("pipeline resource release failed")


def _release_failed_pipeline(control: Any, pipeline: Any, torch: Any) -> None:
    try:
        _release_resource(pipeline)
    except Exception:
        pass
    try:
        _release_resource(control)
    except Exception:
        pass
    control = None
    pipeline = None


def _validate_loaded_pipeline(value: object, *, require_open: bool) -> None:
    if (
        type(value) is not LoadedPipeline
        or getattr(value, "_seal", None) is not _CAPABILITY_SEAL
        or type(getattr(value, "_graph", None)) is not PipelineGraph
        or type(getattr(value, "_environment_hash", None)) is not Sha256
        or type(getattr(value, "_runtime", None)) is not tuple
        or len(value._runtime) != 4
        or any(type(item) is not str for item in value._runtime)
        or value._runtime[3] != "float16"
        or type(getattr(value, "_image_encoder_pin", None)) is not ResourcePin
        or type(getattr(value, "_processor_provenance", None))
        is not _ProcessorProvenance
        or type(getattr(value, "_closed", None)) is not bool
    ):
        raise DomainError("invalid loaded pipeline capability")
    if require_open and (value._closed or value._pipeline is None):
        raise DomainError("loaded pipeline is closed")
    if require_open and (
        value._pipeline is not value._pipeline_identity
        or type(value._image_encoder)
        is not getattr(value._transformers, "CLIPVisionModelWithProjection", None)
        or type(value._image_processor)
        is not getattr(value._transformers, "CLIPImageProcessor", None)
        or getattr(value._pipeline, "image_encoder", None) is not value._image_encoder
        or getattr(value._pipeline, "feature_extractor", None)
        is not value._image_processor
    ):
        raise DomainError("invalid loaded pipeline capability")


def _validate_image_evidence_owner(owner: object) -> None:
    if (
        type(owner) is not LoadedPipeline
        or getattr(owner, "_seal", None) is not _CAPABILITY_SEAL
    ):
        raise DomainError("invalid image evidence encoder capability")
    if getattr(owner, "_closed", None) is True:
        refs = (
            getattr(owner, field, object())
            for field in (
                "_pipeline",
                "_pipeline_identity",
                "_image_encoder",
                "_image_processor",
                "_image_encoder_device",
                "_image_encoder_dtype",
            )
        )
        if all(item is None for item in refs):
            raise DomainError("loaded pipeline is closed")
        raise InfrastructureError(_EVIDENCE_CONTRACT_ERROR) from None
    try:
        _validate_loaded_pipeline(owner, require_open=True)
        _validate_image_processor(owner._image_processor, owner._image_encoder)
        _validate_frozen_encoder_placement(
            owner._image_encoder,
            owner._torch,
            owner._image_encoder_device,
            owner._image_encoder_dtype,
        )
        provenance = _build_processor_provenance(
            owner._transformers,
            owner._image_processor,
            _installed_transformers_version(),
        )
        if provenance != owner._processor_provenance:
            raise InfrastructureError("image evidence contract violation")
    except Exception:
        raise InfrastructureError("image evidence contract violation") from None


def _validate_image_evidence_encoder(value: object) -> None:
    if (
        type(value) is not _VerifiedImageEvidenceEncoder
        or getattr(value, "_seal", None) is not _IMAGE_EVIDENCE_CAPABILITY_SEAL
        or type(getattr(value, "_owner", None)) is not LoadedPipeline
    ):
        raise DomainError("invalid image evidence encoder capability")
    _validate_image_evidence_owner(value._owner)


def load_production_pipeline(
    supply: VerifiedPipelineSupply,
    graph: PipelineGraph,
    environment: EnvironmentSnapshot,
    /,
    *,
    torch_module: Any | None = None,
    diffusers_module: Any | None = None,
) -> LoadedPipeline:
    with _GPU_LEASE:
        return _load_production_pipeline_under_lease(
            supply,
            graph,
            environment,
            torch_module=torch_module,
            diffusers_module=diffusers_module,
        )


def _load_production_pipeline_under_lease(
    supply: VerifiedPipelineSupply,
    graph: PipelineGraph,
    environment: EnvironmentSnapshot,
    /,
    *,
    torch_module: Any | None = None,
    diffusers_module: Any | None = None,
) -> LoadedPipeline:
    """Load the one supported SDXL/Canny production topology from borrowed paths."""
    runtime_failure: InfrastructureError | None = None
    try:
        torch = (
            importlib.import_module("torch") if torch_module is None else torch_module
        )
        diffusers = (
            importlib.import_module("diffusers")
            if diffusers_module is None
            else diffusers_module
        )
        transformers = _import_transformers()
    except Exception:
        torch = diffusers = transformers = None
        runtime_failure = InfrastructureError("production runtime unavailable")
    if runtime_failure is not None:
        raise runtime_failure
    environment_hash = _validate_environment(environment, torch, diffusers)
    components = _validated_components(supply, graph)
    control = None
    pipeline = None
    failure: InfrastructureError | None = None
    try:
        control_entrypoint = components["controlnet"].manifest.entrypoint
        base_entrypoint = components["base"].manifest.entrypoint
        control = diffusers.ControlNetModel.from_pretrained(
            _joined_component_root(
                components["controlnet"].borrow_loader_path(), control_entrypoint
            ),
            **_pretrained_load_kwargs(control_entrypoint, torch),
        )
        pipeline = diffusers.StableDiffusionXLControlNetImg2ImgPipeline.from_pretrained(
            _joined_component_root(
                components["base"].borrow_loader_path(), base_entrypoint
            ),
            controlnet=control,
            **_pretrained_load_kwargs(base_entrypoint, torch),
        )
        pipeline.scheduler = diffusers.EulerDiscreteScheduler.from_config(
            pipeline.scheduler.config
        )
        pipeline.to("cuda:0", torch.float16)
        if (
            getattr(pipeline, "image_encoder", object()) is not None
            or getattr(pipeline, "feature_extractor", object()) is not None
        ):
            raise InfrastructureError("pipeline loading failed")
        pipeline.load_ip_adapter(
            components["ip_adapter"].borrow_loader_path(),
            **_ip_adapter_kwargs(components["ip_adapter"].manifest.entrypoint),
        )
        image_encoder_type = transformers.CLIPVisionModelWithProjection
        image_processor_type = transformers.CLIPImageProcessor
        image_encoder = getattr(pipeline, "image_encoder", None)
        image_processor = getattr(pipeline, "feature_extractor", None)
        if (
            type(image_encoder_type) is not type
            or type(image_processor_type) is not type
            or type(image_encoder) is not image_encoder_type
            or type(image_processor) is not image_processor_type
        ):
            raise InfrastructureError("pipeline loading failed")
        _validate_image_processor(image_processor, image_encoder)
        image_encoder_device, image_encoder_dtype = _encoder_placement(
            image_encoder, torch
        )
        processor_provenance = _build_processor_provenance(
            transformers, image_processor, _installed_transformers_version()
        )
    except Exception as error:
        failure = (
            _GpuOutOfMemoryError("pipeline loading OOM")
            if _is_torch_oom(error, torch)
            else InfrastructureError("pipeline loading failed")
        )

    if failure is not None:
        _release_failed_pipeline(control, pipeline, torch)
        control = pipeline = components = None
        gc.collect()
        _empty_cache(torch)
        raise failure

    instance = None
    try:
        instance = object.__new__(LoadedPipeline)
        object.__setattr__(instance, "_pipeline", pipeline)
        object.__setattr__(instance, "_pipeline_identity", pipeline)
        object.__setattr__(instance, "_graph", graph)
        object.__setattr__(instance, "_environment_hash", environment_hash)
        object.__setattr__(
            instance,
            "_runtime",
            (
                environment.rocm_version.value,
                environment.pytorch_version.value,
                environment.diffusers_version.value,
                "float16",
            ),
        )
        object.__setattr__(instance, "_torch", torch)
        object.__setattr__(instance, "_image_encoder", image_encoder)
        object.__setattr__(instance, "_image_processor", image_processor)
        object.__setattr__(instance, "_image_encoder_device", image_encoder_device)
        object.__setattr__(instance, "_image_encoder_dtype", image_encoder_dtype)
        object.__setattr__(instance, "_transformers", transformers)
        object.__setattr__(instance, "_processor_provenance", processor_provenance)
        ip_component = components["ip_adapter"]
        object.__setattr__(
            instance,
            "_image_encoder_pin",
            ResourcePin(
                ip_component.model_id,
                ip_component.manifest.revision,
                ip_component.manifest.root_sha256,
            ),
        )
        object.__setattr__(instance, "_closed", False)
        object.__setattr__(instance, "_seal", _CAPABILITY_SEAL)
        _validate_loaded_pipeline(instance, require_open=True)
    except Exception:
        failure = InfrastructureError("pipeline loading failed")
    if failure is not None:
        _release_failed_pipeline(control, pipeline, torch)
        control = pipeline = instance = None
        gc.collect()
        _empty_cache(torch)
        raise failure
    return instance
