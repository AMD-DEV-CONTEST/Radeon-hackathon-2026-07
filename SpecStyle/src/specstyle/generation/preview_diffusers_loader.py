"""Verified local-only Diffusers/ROCm loader for the exact LCM Preview topology."""

from __future__ import annotations

import gc
import hashlib
import importlib
import json
import math
import sys
from dataclasses import dataclass, field
from typing import Any

from specstyle.domain.identifiers import Sha256
from specstyle.errors import DomainError, InfrastructureError, _GpuOutOfMemoryError
from specstyle.generation.diffusers_loader import (
    _GPU_LEASE,
    _empty_cache,
    _ip_adapter_kwargs,
    _is_torch_oom,
    _joined_component_root,
    _pretrained_load_kwargs,
    _release_failed_pipeline,
    _release_resource,
    _validate_environment,
)
from specstyle.generation.model_approval import VerifiedPipelineSupply
from specstyle.generation.model_registry import ModelDescriptor
from specstyle.generation.pipeline_factory import PipelineGraph
from specstyle.generation.preview_adapter_supply import VerifiedPreviewAdapter
from specstyle.generation.preview_execution import (
    _canonical_scheduler_config,
    _snapshot_model_bindings,
)
from specstyle.observability.environment import EnvironmentSnapshot

_CAPABILITY_SEAL = object()
_SCHEDULER_IDENTITY = "diffusers.LCMScheduler"
_LORA_FUSE_SCALE = 1.0
_LORA_ADAPTER_NAME = "specstyle_lcm"
_PEFT_VERSION = "0.18.1"
_RUNTIME_DTYPE = "float16"
_VAE_AT_REST_DTYPE = "float16"
_VAE_COMPUTE_DTYPE = "float32"
_VAE_PRECISION_POLICY = "diffusers_force_upcast_roundtrip_v1"
_VAE_HASH_DOMAIN = b"specstyle.preview.vae-tensor-integrity.v1\x00"
_DTYPE_BYTES = {
    "bfloat16": 2,
    "bool": 1,
    "complex128": 16,
    "complex64": 8,
    "float16": 2,
    "float32": 4,
    "float64": 8,
    "int16": 2,
    "int32": 4,
    "int64": 8,
    "int8": 1,
    "uint8": 1,
}
_PIPELINE_COMPONENTS = (
    "unet",
    "controlnet",
    "vae",
    "text_encoder",
    "text_encoder_2",
    "image_encoder",
    "feature_extractor",
)


class _PreviewPipelineIntegrityError(DomainError):
    pass


@dataclass(slots=True)
class _PreviewLoadState:
    control: Any = None
    pipeline: Any = None


@dataclass(frozen=True, slots=True)
class _PipelineIntegrity:
    components: tuple[tuple[str, Any], ...]
    adapter_state: tuple[object, ...]
    tensors: tuple[_TensorIntegrity, ...]
    lora_layers: tuple[_LoraLayerIntegrity, ...]


@dataclass(frozen=True, slots=True)
class _TensorIntegrity:
    name: str
    tensor: Any
    version: int
    data_ptr: int | None
    shape: tuple[int, ...]
    dtype: str
    content_sha256: str | None


@dataclass(frozen=True, slots=True)
class _LoraLayerIntegrity:
    name: str
    layer: Any
    merged_adapters: tuple[str, ...]
    scaling: tuple[tuple[str, float], ...]


@dataclass(frozen=True, slots=True, init=False)
class LoadedPreviewPipeline:
    _pipeline: Any = field(repr=False, compare=False)
    _pipeline_identity: Any = field(repr=False, compare=False)
    _scheduler_identity_object: Any = field(repr=False, compare=False)
    _scheduler_type: type[Any] = field(repr=False, compare=False)
    _graph: PipelineGraph = field(repr=False, compare=False)
    _environment_hash: Sha256 = field(repr=False, compare=False)
    _runtime: tuple[str, str, str, str] = field(repr=False, compare=False)
    _peft_version: str = field(repr=False, compare=False)
    _model_bindings_json: str = field(repr=False, compare=False)
    _scheduler_identity: str = field(repr=False, compare=False)
    _scheduler_config_json: str = field(repr=False, compare=False)
    _lora_fuse_scale: float = field(repr=False, compare=False)
    _vae_at_rest_dtype: str = field(repr=False, compare=False)
    _vae_compute_dtype: str = field(repr=False, compare=False)
    _vae_precision_policy: str = field(repr=False, compare=False)
    _integrity: _PipelineIntegrity | None = field(repr=False, compare=False)
    _torch: Any = field(repr=False, compare=False)
    _closed: bool = field(repr=False, compare=False)
    _poisoned: bool = field(repr=False, compare=False)
    _seal: object = field(repr=False, compare=False)

    def __init__(self, *_: object, **__: object) -> None:
        raise TypeError(
            "loaded preview pipelines are issued only by the preview loader"
        )

    def _borrow_pipeline(self, /) -> Any:
        _validate_loaded_preview_pipeline(self, require_open=True)
        return self._pipeline

    def close(self) -> None:
        with _GPU_LEASE:
            _validate_loaded_preview_pipeline(self, require_open=False)
            if self._closed:
                return
            pipeline = self._pipeline
            object.__setattr__(self, "_closed", True)
            object.__setattr__(self, "_pipeline", None)
            object.__setattr__(self, "_pipeline_identity", None)
            object.__setattr__(self, "_scheduler_identity_object", None)
            object.__setattr__(self, "_integrity", None)
            try:
                _release_resource(pipeline)
            except Exception as exc:
                raise InfrastructureError("preview pipeline release failed") from exc
            finally:
                pipeline = None
                gc.collect()
                _empty_cache(self._torch)

    def __copy__(self) -> LoadedPreviewPipeline:
        raise TypeError("loaded preview pipelines cannot be copied")

    def __deepcopy__(self, _memo: dict[int, object]) -> LoadedPreviewPipeline:
        raise TypeError("loaded preview pipelines cannot be copied")

    def __reduce_ex__(self, _protocol: int) -> object:
        raise TypeError("loaded preview pipelines cannot be serialized")


def _validate_loaded_preview_pipeline(value: object, *, require_open: bool) -> None:
    try:
        if (
            type(value) is not LoadedPreviewPipeline
            or getattr(value, "_seal", None) is not _CAPABILITY_SEAL
            or type(getattr(value, "_graph", None)) is not PipelineGraph
            or type(getattr(value, "_environment_hash", None)) is not Sha256
            or type(getattr(value, "_runtime", None)) is not tuple
            or len(value._runtime) != 4
            or any(type(item) is not str for item in value._runtime)
            or value._runtime[3] != _RUNTIME_DTYPE
            or getattr(value, "_peft_version", None) != _PEFT_VERSION
            or type(getattr(value, "_model_bindings_json", None)) is not str
            or getattr(value, "_scheduler_identity", None) != _SCHEDULER_IDENTITY
            or type(getattr(value, "_scheduler_config_json", None)) is not str
            or getattr(value, "_lora_fuse_scale", None) != _LORA_FUSE_SCALE
            or getattr(value, "_vae_at_rest_dtype", None) != _VAE_AT_REST_DTYPE
            or getattr(value, "_vae_compute_dtype", None) != _VAE_COMPUTE_DTYPE
            or getattr(value, "_vae_precision_policy", None) != _VAE_PRECISION_POLICY
            or type(getattr(value, "_closed", None)) is not bool
            or type(getattr(value, "_poisoned", None)) is not bool
            or (
                not getattr(value, "_closed", True)
                and type(getattr(value, "_integrity", None)) is not _PipelineIntegrity
            )
        ):
            raise _PreviewPipelineIntegrityError(
                "invalid loaded preview pipeline capability"
            )
        if require_open and value._poisoned:
            raise _PreviewPipelineIntegrityError(
                "preview pipeline runtime integrity failed"
            )
        if require_open and (value._closed or value._pipeline is None):
            raise _PreviewPipelineIntegrityError("loaded preview pipeline is closed")
        if require_open and (
            value._pipeline is not value._pipeline_identity
            or value._pipeline.scheduler is not value._scheduler_identity_object
            or type(value._pipeline.scheduler) is not value._scheduler_type
            or getattr(value._pipeline.vae, "dtype", None) is not value._torch.float16
            or _canonical_scheduler_config(value._pipeline.scheduler.config)
            != value._scheduler_config_json
            or not _pipeline_integrity_matches(value._pipeline, value._integrity)
        ):
            raise _PreviewPipelineIntegrityError(
                "invalid loaded preview pipeline capability"
            )
    except _PreviewPipelineIntegrityError:
        raise
    except Exception as exc:
        raise _PreviewPipelineIntegrityError(
            "invalid loaded preview pipeline capability"
        ) from exc


def _adapter_state(pipeline: Any) -> tuple[object, ...]:
    try:
        active = tuple(pipeline.get_active_adapters())
        listed_raw = pipeline.get_list_adapters()
        listed = tuple((key, tuple(value)) for key, value in sorted(listed_raw.items()))
        fused = tuple(sorted(pipeline.fused_loras))
        state = (active, listed, fused, pipeline.num_fused_loras)
    except Exception as exc:
        raise DomainError("invalid loaded preview pipeline capability") from exc
    listed_names = {
        adapter_name for _component, adapters in listed for adapter_name in adapters
    }
    if (
        active != (_LORA_ADAPTER_NAME,)
        or listed_names != {_LORA_ADAPTER_NAME}
        or fused != (_LORA_ADAPTER_NAME,)
        or type(state[3]) is not int
        or state[3] != 1
    ):
        raise DomainError("invalid loaded preview pipeline capability")
    return state


def _tensor_data_ptr(tensor: Any) -> int | None:
    method = getattr(tensor, "data_ptr", None)
    if method is None:
        return None
    if not callable(method):
        raise DomainError("invalid loaded preview pipeline capability")
    value = method()
    if type(value) is not int or value < 0:
        raise DomainError("invalid loaded preview pipeline capability")
    return value


def _tensor_shape(tensor: Any) -> tuple[int, ...]:
    try:
        shape = tuple(tensor.shape)
    except Exception as exc:
        raise DomainError("invalid loaded preview pipeline capability") from exc
    if any(type(item) is not int or item < 0 for item in shape):
        raise DomainError("invalid loaded preview pipeline capability")
    return shape


def _tensor_dtype(tensor: Any) -> str:
    try:
        value = str(tensor.dtype)
    except Exception as exc:
        raise DomainError("invalid loaded preview pipeline capability") from exc
    normalized = value.removeprefix("torch.")
    if normalized not in _DTYPE_BYTES:
        raise DomainError("invalid loaded preview pipeline capability")
    return normalized


def _vae_content_sha256(
    name: str, tensor: Any, shape: tuple[int, ...], dtype: str
) -> str:
    snapshot = array = None
    try:
        metadata = json.dumps(
            {
                "byte_order": "little",
                "dtype": dtype,
                "layout": "C",
                "name": name,
                "shape": list(shape),
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
        snapshot = tensor.detach().to(device="cpu", copy=True).contiguous()
        array = snapshot.numpy()
        array_dtype = getattr(array, "dtype", None)
        byteorder = getattr(array_dtype, "byteorder", "=")
        if byteorder == ">" or (byteorder == "=" and sys.byteorder != "little"):
            raise ValueError("non-little-endian tensor")
        view = memoryview(array)
        if not view.c_contiguous:
            raise ValueError("non-contiguous tensor")
        byte_view = view.cast("B")
        expected_bytes = math.prod(shape) * _DTYPE_BYTES[dtype]
        if byte_view.nbytes != expected_bytes:
            raise ValueError("tensor byte length mismatch")
        digest = hashlib.sha256()
        digest.update(_VAE_HASH_DOMAIN)
        digest.update(len(metadata).to_bytes(8, "big"))
        digest.update(metadata)
        digest.update(byte_view.nbytes.to_bytes(8, "big"))
        digest.update(byte_view)
        return digest.hexdigest()
    except Exception as exc:
        raise DomainError("invalid loaded preview pipeline capability") from exc
    finally:
        array = snapshot = None


def _capture_tensor_integrity(
    components: tuple[tuple[str, Any], ...],
) -> tuple[_TensorIntegrity, ...]:
    captured: list[_TensorIntegrity] = []
    for component_name, component in components:
        for kind, method_name in (
            ("parameter", "named_parameters"),
            ("buffer", "named_buffers"),
        ):
            method = getattr(component, method_name, None)
            if method is None:
                continue
            if not callable(method):
                raise DomainError("invalid loaded preview pipeline capability")
            for name, tensor in method():
                version = getattr(tensor, "_version", None)
                if type(name) is not str or type(version) is not int or version < 0:
                    raise DomainError("invalid loaded preview pipeline capability")
                full_name = f"{component_name}.{kind}.{name}"
                shape = _tensor_shape(tensor)
                dtype = _tensor_dtype(tensor)
                captured.append(
                    _TensorIntegrity(
                        full_name,
                        tensor,
                        version,
                        _tensor_data_ptr(tensor),
                        shape,
                        dtype,
                        (
                            _vae_content_sha256(full_name, tensor, shape, dtype)
                            if component_name == "vae"
                            else None
                        ),
                    )
                )
    if not captured or len({item.name for item in captured}) != len(captured):
        raise DomainError("invalid loaded preview pipeline capability")
    return tuple(sorted(captured, key=lambda item: item.name))


def _lora_layer_state(
    components: tuple[tuple[str, Any], ...],
) -> tuple[_LoraLayerIntegrity, ...]:
    captured: list[_LoraLayerIntegrity] = []
    for component_name, component in components:
        method = getattr(component, "named_modules", None)
        if method is None:
            continue
        if not callable(method):
            raise DomainError("invalid loaded preview pipeline capability")
        for name, layer in method():
            if not hasattr(layer, "merged_adapters") or not hasattr(layer, "scaling"):
                continue
            try:
                merged = tuple(layer.merged_adapters)
                scaling = tuple(sorted(layer.scaling.items()))
            except Exception as exc:
                raise DomainError("invalid loaded preview pipeline capability") from exc
            if (
                merged != (_LORA_ADAPTER_NAME,)
                or len(scaling) != 1
                or scaling[0][0] != _LORA_ADAPTER_NAME
                or type(scaling[0][1]) is not float
                or not math.isfinite(scaling[0][1])
                or scaling[0][1] <= 0.0
            ):
                raise DomainError("invalid loaded preview pipeline capability")
            captured.append(
                _LoraLayerIntegrity(f"{component_name}.{name}", layer, merged, scaling)
            )
    if not captured or len({item.name for item in captured}) != len(captured):
        raise DomainError("invalid loaded preview pipeline capability")
    return tuple(captured)


def _capture_pipeline_integrity(pipeline: Any) -> _PipelineIntegrity:
    components: list[tuple[str, Any]] = []
    for name in _PIPELINE_COMPONENTS:
        component = getattr(pipeline, name, None)
        if component is None:
            raise DomainError("invalid loaded preview pipeline capability")
        components.append((name, component))
    captured = tuple(components)
    return _PipelineIntegrity(
        captured,
        _adapter_state(pipeline),
        _capture_tensor_integrity(captured),
        _lora_layer_state(captured),
    )


def _tensor_integrity_matches(
    components: tuple[tuple[str, Any], ...], expected: tuple[_TensorIntegrity, ...]
) -> bool:
    try:
        current = _capture_tensor_integrity(components)
    except DomainError:
        return False
    return len(current) == len(expected) and all(
        left.name == right.name
        and left.tensor is right.tensor
        and left.version == right.version
        and left.shape == right.shape
        and left.dtype == right.dtype
        and left.content_sha256 == right.content_sha256
        and (left.data_ptr == right.data_ptr or left.name.startswith("vae."))
        for left, right in zip(current, expected, strict=True)
    )


def _lora_integrity_matches(
    components: tuple[tuple[str, Any], ...],
    expected: tuple[_LoraLayerIntegrity, ...],
) -> bool:
    try:
        current = _lora_layer_state(components)
    except DomainError:
        return False
    return len(current) == len(expected) and all(
        left.name == right.name
        and left.layer is right.layer
        and left.merged_adapters == right.merged_adapters
        and left.scaling == right.scaling
        for left, right in zip(current, expected, strict=True)
    )


def _pipeline_integrity_matches(
    pipeline: Any, integrity: _PipelineIntegrity | None
) -> bool:
    if type(integrity) is not _PipelineIntegrity:
        return False
    if any(
        getattr(pipeline, name, None) is not item for name, item in integrity.components
    ):
        return False
    try:
        return (
            _adapter_state(pipeline) == integrity.adapter_state
            and _tensor_integrity_matches(integrity.components, integrity.tensors)
            and _lora_integrity_matches(integrity.components, integrity.lora_layers)
        )
    except DomainError:
        return False


def _validated_components(
    supply: object, adapter: object, graph: object
) -> dict[str, Any]:
    if (
        type(supply) is not VerifiedPipelineSupply
        or type(adapter) is not VerifiedPreviewAdapter
        or type(graph) is not PipelineGraph
    ):
        raise DomainError("invalid verified preview supply")
    adapter.borrow_loader_path()
    if (
        graph.profile != "preview"
        or type(graph.preview_adapter) is not ModelDescriptor
        or graph.preview_adapter != adapter.descriptor
    ):
        raise DomainError("invalid verified preview supply")
    models = supply.models
    roles = ("base", "ip_adapter", "controlnet")
    by_role = {component.role: component for component in models}
    if tuple(by_role) != roles:
        raise DomainError("invalid verified preview supply")
    for descriptor, role in zip(
        (graph.base, graph.ip_adapter, graph.controlnet), roles, strict=True
    ):
        component = by_role[role]
        if (
            component.model_id != descriptor.model_id
            or component.manifest.revision != descriptor.revision
            or component.manifest.root_sha256 != descriptor.expected_sha256
        ):
            raise DomainError("preview graph and production supply mismatch")
    return by_role


def _lora_kwargs(adapter: VerifiedPreviewAdapter) -> dict[str, object]:
    entrypoint = adapter.manifest.entrypoint
    return {
        "subfolder": entrypoint.subfolder,
        "weight_name": entrypoint.weight_name,
        "local_files_only": True,
        "use_safetensors": True,
        "adapter_name": _LORA_ADAPTER_NAME,
    }


def _load_runtime_modules(
    torch_module: Any | None,
    diffusers_module: Any | None,
    peft_module: Any | None,
) -> tuple[Any, Any, Any]:
    try:
        torch = (
            importlib.import_module("torch") if torch_module is None else torch_module
        )
        diffusers = (
            importlib.import_module("diffusers")
            if diffusers_module is None
            else diffusers_module
        )
        peft = importlib.import_module("peft") if peft_module is None else peft_module
    except Exception as exc:
        raise InfrastructureError("preview runtime unavailable") from exc
    if (
        getattr(peft, "__version__", None) != _PEFT_VERSION
        or getattr(getattr(diffusers, "utils", None), "USE_PEFT_BACKEND", None)
        is not True
    ):
        raise InfrastructureError("preview runtime unavailable")
    return torch, diffusers, peft


def _issue_loaded_preview(
    pipeline: Any,
    scheduler: Any,
    scheduler_type: type[Any],
    graph: PipelineGraph,
    environment: EnvironmentSnapshot,
    environment_hash: Sha256,
    model_bindings_json: str,
    scheduler_config_json: str,
    integrity: _PipelineIntegrity,
    torch: Any,
) -> LoadedPreviewPipeline:
    issued = object.__new__(LoadedPreviewPipeline)
    values = {
        "_pipeline": pipeline,
        "_pipeline_identity": pipeline,
        "_scheduler_identity_object": scheduler,
        "_scheduler_type": scheduler_type,
        "_graph": graph,
        "_environment_hash": environment_hash,
        "_runtime": (
            environment.rocm_version.value,
            environment.pytorch_version.value,
            environment.diffusers_version.value,
            _RUNTIME_DTYPE,
        ),
        "_peft_version": _PEFT_VERSION,
        "_model_bindings_json": model_bindings_json,
        "_scheduler_identity": _SCHEDULER_IDENTITY,
        "_scheduler_config_json": scheduler_config_json,
        "_lora_fuse_scale": _LORA_FUSE_SCALE,
        "_vae_at_rest_dtype": _VAE_AT_REST_DTYPE,
        "_vae_compute_dtype": _VAE_COMPUTE_DTYPE,
        "_vae_precision_policy": _VAE_PRECISION_POLICY,
        "_integrity": integrity,
        "_torch": torch,
        "_closed": False,
        "_poisoned": False,
        "_seal": _CAPABILITY_SEAL,
    }
    for name, value in values.items():
        object.__setattr__(issued, name, value)
    _validate_loaded_preview_pipeline(issued, require_open=True)
    return issued


def _build_preview_pipeline(
    state: _PreviewLoadState,
    components: dict[str, Any],
    preview_adapter: VerifiedPreviewAdapter,
    torch: Any,
    diffusers: Any,
) -> tuple[Any, str, _PipelineIntegrity]:
    control_entrypoint = components["controlnet"].manifest.entrypoint
    base_entrypoint = components["base"].manifest.entrypoint
    state.control = diffusers.ControlNetModel.from_pretrained(
        _joined_component_root(
            components["controlnet"].borrow_loader_path(), control_entrypoint
        ),
        **_pretrained_load_kwargs(control_entrypoint, torch),
    )
    state.pipeline = (
        diffusers.StableDiffusionXLControlNetImg2ImgPipeline.from_pretrained(
            _joined_component_root(
                components["base"].borrow_loader_path(), base_entrypoint
            ),
            controlnet=state.control,
            **_pretrained_load_kwargs(base_entrypoint, torch),
        )
    )
    scheduler = diffusers.LCMScheduler.from_config(state.pipeline.scheduler.config)
    if type(scheduler) is not diffusers.LCMScheduler:
        raise InfrastructureError("preview pipeline loading failed")
    state.pipeline.scheduler = scheduler
    state.pipeline.to("cuda:0", torch.float16)
    state.pipeline.load_ip_adapter(
        components["ip_adapter"].borrow_loader_path(),
        **_ip_adapter_kwargs(components["ip_adapter"].manifest.entrypoint),
    )
    state.pipeline.load_lora_weights(
        preview_adapter.borrow_loader_path(), **_lora_kwargs(preview_adapter)
    )
    state.pipeline.fuse_lora(
        lora_scale=_LORA_FUSE_SCALE, adapter_names=[_LORA_ADAPTER_NAME]
    )
    integrity = _capture_pipeline_integrity(state.pipeline)
    return scheduler, _canonical_scheduler_config(scheduler.config), integrity


def _poison_loaded_preview_pipeline(value: object) -> None:
    if (
        type(value) is not LoadedPreviewPipeline
        or getattr(value, "_seal", None) is not _CAPABILITY_SEAL
    ):
        raise DomainError("invalid loaded preview pipeline capability")
    object.__setattr__(value, "_poisoned", True)


def load_preview_pipeline(
    production_supply: VerifiedPipelineSupply,
    preview_adapter: VerifiedPreviewAdapter,
    graph: PipelineGraph,
    environment: EnvironmentSnapshot,
    /,
    *,
    torch_module: Any | None = None,
    diffusers_module: Any | None = None,
    peft_module: Any | None = None,
) -> LoadedPreviewPipeline:
    """Load the exact SDXL/Canny/IP-Adapter/LCM-LoRA Preview topology."""
    with _GPU_LEASE:
        torch, diffusers, _peft = _load_runtime_modules(
            torch_module, diffusers_module, peft_module
        )
        environment_hash = _validate_environment(environment, torch, diffusers)
        components = _validated_components(production_supply, preview_adapter, graph)
        bindings_json = _snapshot_model_bindings(graph, components, preview_adapter)
        state = _PreviewLoadState()
        try:
            scheduler, scheduler_config_json, integrity = _build_preview_pipeline(
                state, components, preview_adapter, torch, diffusers
            )
            return _issue_loaded_preview(
                state.pipeline,
                scheduler,
                diffusers.LCMScheduler,
                graph,
                environment,
                environment_hash,
                bindings_json,
                scheduler_config_json,
                integrity,
                torch,
            )
        except Exception as error:
            _release_failed_pipeline(state.control, state.pipeline, torch)
            state.control = state.pipeline = None
            gc.collect()
            _empty_cache(torch)
            if _is_torch_oom(error, torch):
                raise _GpuOutOfMemoryError("preview pipeline loading OOM") from error
            raise InfrastructureError("preview pipeline loading failed") from error
