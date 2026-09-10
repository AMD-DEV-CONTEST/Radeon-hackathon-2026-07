"""Immutable binding between a compiled Preview request and its GPU runtime."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Any

from specstyle.domain.identifiers import ArtifactId, Sha256
from specstyle.errors import DomainError
from specstyle.exporting.qa_report import graph_primitive
from specstyle.generation.model_approval import LicenseApproval, VerifiedComponent
from specstyle.generation.model_registry import ModelDescriptor
from specstyle.generation.preview_adapter_supply import (
    PreviewAdapterManifest,
    VerifiedPreviewAdapter,
    preview_adapter_manifest_sha256,
)
from specstyle.generation.requests import GenerationRequest
from specstyle.generation.weight_manifest import WeightManifest, manifest_sha256
from specstyle.observability.hashing import hash_bytes

_BINDING_SEAL = object()


def _canonical_json(value: object) -> str:
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        parsed = json.loads(encoded)
    except (TypeError, ValueError, RecursionError, json.JSONDecodeError) as exc:
        raise DomainError("invalid preview execution material") from exc
    if (
        json.dumps(
            parsed,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        != encoded
    ):
        raise DomainError("non-canonical preview execution material")
    return encoded


def _fingerprint(material: str) -> Sha256:
    if type(material) is not str:
        raise DomainError("invalid preview execution material")
    return Sha256(hashlib.sha256(material.encode("utf-8")).hexdigest())


def _descriptor_primitive(value: ModelDescriptor) -> dict[str, object]:
    if type(value) is not ModelDescriptor:
        raise DomainError("invalid preview model descriptor")
    return {
        "model_id": value.model_id,
        "role": value.role,
        "revision": value.revision,
        "expected_sha256": value.expected_sha256.value,
        "license_spdx": value.license_spdx,
        "license_status": value.license_status,
        "family": value.family,
    }


def _approval_primitive(value: LicenseApproval) -> dict[str, str]:
    if type(value) is not LicenseApproval:
        raise DomainError("invalid preview license approval")
    return {
        "model_id": value.model_id,
        "revision": value.revision,
        "manifest_sha256": value.manifest_sha256.value,
        "license_spdx": value.license_spdx,
        "evidence_url": value.evidence_url,
    }


def _production_model_primitive(
    descriptor: ModelDescriptor, component: VerifiedComponent
) -> dict[str, object]:
    if (
        type(component) is not VerifiedComponent
        or type(component.manifest) is not WeightManifest
        or component.model_id != descriptor.model_id
        or component.role != descriptor.role
    ):
        raise DomainError("invalid preview production model binding")
    return {
        "descriptor": _descriptor_primitive(descriptor),
        "manifest_sha256": manifest_sha256(component.manifest).value,
        "manifest_root_sha256": component.manifest.root_sha256.value,
        "approval": _approval_primitive(component.approval),
    }


def _preview_model_primitive(adapter: VerifiedPreviewAdapter) -> dict[str, object]:
    if (
        type(adapter) is not VerifiedPreviewAdapter
        or type(adapter.manifest) is not PreviewAdapterManifest
    ):
        raise DomainError("invalid preview adapter binding")
    return {
        "descriptor": _descriptor_primitive(adapter.descriptor),
        "manifest_sha256": preview_adapter_manifest_sha256(adapter.manifest).value,
        "manifest_root_sha256": adapter.manifest.root_sha256.value,
        "approval": _approval_primitive(adapter.approval),
    }


def _snapshot_model_bindings(
    graph: object, components: object, adapter: VerifiedPreviewAdapter
) -> str:
    from specstyle.generation.pipeline_factory import PipelineGraph

    if type(graph) is not PipelineGraph or type(components) is not dict:
        raise DomainError("invalid preview model bindings")
    roles = ("base", "ip_adapter", "controlnet")
    if tuple(components) != roles:
        raise DomainError("invalid preview model bindings")
    descriptors = (graph.base, graph.ip_adapter, graph.controlnet)
    models = [
        _production_model_primitive(descriptor, components[role])
        for descriptor, role in zip(descriptors, roles, strict=True)
    ]
    models.append(_preview_model_primitive(adapter))
    return _canonical_json(models)


def _canonical_scheduler_config(value: object) -> str:
    try:
        material = value if type(value) is dict else dict(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise DomainError("invalid preview scheduler config") from exc
    return _canonical_json(material)


@dataclass(frozen=True, slots=True, init=False)
class PreviewExecutionBinding:
    compiled_request_fingerprint: Sha256
    execution_fingerprint: Sha256
    material_json: str
    _seal: object = field(repr=False, compare=False)

    def __init__(self, *_: object, **__: object) -> None:
        raise TypeError("preview execution bindings are issued only before execution")

    def __copy__(self) -> PreviewExecutionBinding:
        raise TypeError("preview execution bindings cannot be copied")

    def __deepcopy__(self, _memo: dict[int, object]) -> PreviewExecutionBinding:
        raise TypeError("preview execution bindings cannot be copied")

    def __reduce_ex__(self, _protocol: int) -> object:
        raise TypeError("preview execution bindings cannot be serialized")


def _validate_execution_binding(binding: object) -> None:
    if (
        type(binding) is not PreviewExecutionBinding
        or getattr(binding, "_seal", None) is not _BINDING_SEAL
        or type(getattr(binding, "compiled_request_fingerprint", None)) is not Sha256
        or type(getattr(binding, "execution_fingerprint", None)) is not Sha256
        or type(getattr(binding, "material_json", None)) is not str
    ):
        raise DomainError("invalid preview execution binding")
    try:
        material = json.loads(binding.material_json)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise DomainError("invalid preview execution binding") from exc
    if not _valid_binding_material(binding, material):
        raise DomainError("invalid preview execution binding")


def _valid_binding_material(binding: PreviewExecutionBinding, material: object) -> bool:
    if type(material) is not dict or set(material) != {
        "schema_version",
        "compiled_request_fingerprint",
        "compiled_request",
        "models",
        "environment_sha256",
        "runtime",
        "scheduler",
        "lora_fuse_scale",
    }:
        return False
    compiled = material["compiled_request"]
    return (
        _canonical_json(material) == binding.material_json
        and material["schema_version"] == "specstyle.preview.execution.v3"
        and _valid_compiled_material(compiled)
        and _valid_runtime_material(material["runtime"])
        and material["compiled_request_fingerprint"]
        == binding.compiled_request_fingerprint.value
        and _fingerprint(_canonical_json(compiled))
        == binding.compiled_request_fingerprint
        and _fingerprint(binding.material_json) == binding.execution_fingerprint
        and binding.execution_fingerprint != binding.compiled_request_fingerprint
    )


def _valid_runtime_material(value: object) -> bool:
    keys = {
        "rocm_version",
        "torch_version",
        "diffusers_version",
        "peft_version",
        "dtype",
        "vae_at_rest_dtype",
        "vae_compute_dtype",
        "vae_precision_policy",
    }
    return (
        type(value) is dict
        and set(value) == keys
        and value["peft_version"] == "0.18.1"
        and value["dtype"] == "float16"
        and value["vae_at_rest_dtype"] == "float16"
        and value["vae_compute_dtype"] == "float32"
        and value["vae_precision_policy"] == "diffusers_force_upcast_roundtrip_v1"
        and all(
            type(value[key]) is str and value[key]
            for key in ("rocm_version", "torch_version", "diffusers_version")
        )
    )


def _valid_compiled_material(value: object) -> bool:
    if type(value) is not dict or set(value) != {
        "schema_version",
        "request_sha256",
        "generation_fingerprint",
        "compiled_spec_sha256",
        "run_id",
        "variation_index",
        "seed",
        "resolution",
        "graph",
    }:
        return False
    seed = value["seed"]
    resolution = value["resolution"]
    graph = value["graph"]
    return (
        value["schema_version"] == "specstyle.preview.compiled-request.v2"
        and type(value["run_id"]) is str
        and value["run_id"].startswith("preview-")
        and type(value["variation_index"]) is int
        and 0 <= value["variation_index"] < 2**31
        and type(seed) is dict
        and seed.get("algorithm") == "specstyle.seed.v1"
        and type(seed.get("value")) is int
        and 0 <= seed["value"] < 2**63
        and type(resolution) is list
        and len(resolution) == 2
        and all(type(item) is int and item > 0 for item in resolution)
        and type(graph) is dict
        and graph.get("resolution") == resolution
    )


def _issue_execution_binding(
    compiled_fingerprint: Sha256, material_json: str
) -> PreviewExecutionBinding:
    issued = object.__new__(PreviewExecutionBinding)
    object.__setattr__(issued, "compiled_request_fingerprint", compiled_fingerprint)
    object.__setattr__(issued, "execution_fingerprint", _fingerprint(material_json))
    object.__setattr__(issued, "material_json", material_json)
    object.__setattr__(issued, "_seal", _BINDING_SEAL)
    _validate_execution_binding(issued)
    return issued


@dataclass(frozen=True, slots=True)
class PreviewGeneratedArtifact:
    artifact_id: ArtifactId
    content: bytes
    content_sha256: Sha256
    binding: PreviewExecutionBinding
    execution_fingerprint: Sha256

    def __post_init__(self) -> None:
        if (
            type(self.artifact_id) is not ArtifactId
            or type(self.content) is not bytes
            or type(self.content_sha256) is not Sha256
            or type(self.binding) is not PreviewExecutionBinding
            or type(self.execution_fingerprint) is not Sha256
            or hash_bytes(self.content) != self.content_sha256
            or self.execution_fingerprint != self.binding.execution_fingerprint
            or self.artifact_id
            != _preview_artifact_id(self.execution_fingerprint, self.content_sha256)
        ):
            raise DomainError("invalid preview generated artifact")
        _validate_execution_binding(self.binding)


def _preview_artifact_id(execution: Sha256, content: Sha256) -> ArtifactId:
    if type(execution) is not Sha256 or type(content) is not Sha256:
        raise DomainError("invalid preview artifact binding")
    material = _canonical_json(
        {
            "schema_version": "specstyle.preview.artifact.v1",
            "execution_fingerprint": execution.value,
            "content_sha256": content.value,
        }
    )
    return ArtifactId(f"preview-{_fingerprint(material).value}")


def _positive_zero(value: object) -> bool:
    return type(value) is float and value == 0.0 and math.copysign(1.0, value) == 1.0


def _validate_preview_request(loaded: object, request: object) -> GenerationRequest:
    from specstyle.generation.preview_diffusers_loader import (
        _validate_loaded_preview_pipeline,
    )

    _validate_loaded_preview_pipeline(loaded, require_open=True)
    if type(request) is not GenerationRequest:
        raise DomainError("invalid preview generation request")
    graph = request.graph
    runtime = graph.runtime
    if (
        request.generation_profile != "preview"
        or request.environment_hash != loaded._environment_hash
        or graph.generation_profile != "preview"
        or graph.pipeline != "lcm"
        or graph.scheduler is not None
        or type(graph.steps) is not int
        or isinstance(graph.steps, bool)
        or not 4 <= graph.steps <= 8
        or not _positive_zero(graph.guidance_scale)
        or graph.controlnet.controlnet_type != "canny"
        or runtime.backend != "rocm"
        or runtime.dtype != "float16"
        or (
            runtime.rocm_version,
            runtime.torch_version,
            runtime.diffusers_version,
            runtime.dtype,
        )
        != loaded._runtime
    ):
        raise DomainError("preview generation binding mismatch")
    _validate_request_model_pins(loaded, graph)
    return request


def _validate_request_model_pins(loaded: Any, graph: Any) -> None:
    for resolved, descriptor in (
        (graph.base_model, loaded._graph.base),
        (graph.ip_adapter, loaded._graph.ip_adapter),
        (graph.controlnet, loaded._graph.controlnet),
    ):
        if (
            resolved.pin.id != descriptor.model_id
            or resolved.pin.revision != descriptor.revision
            or resolved.pin.sha256 != descriptor.expected_sha256
        ):
            raise DomainError("preview model binding mismatch")


def bind_preview_execution(loaded: object, request: object) -> PreviewExecutionBinding:
    """Freeze every request, supply, scheduler, fuse and runtime input before GPU use."""
    request = _validate_preview_request(loaded, request)
    compiled_material = {
        "schema_version": "specstyle.preview.compiled-request.v2",
        "request_sha256": request.request_hash.value,
        "generation_fingerprint": request.generation_fingerprint.value,
        "compiled_spec_sha256": request.compiled_spec.compiled_spec_hash.value,
        "run_id": request.job_id.value,
        "variation_index": request.variation_index,
        "seed": {
            "algorithm": request.seed.algorithm,
            "value": request.seed.seed,
        },
        "resolution": list(request.graph.resolution),
        "graph": graph_primitive(request.graph),
    }
    compiled_fingerprint = _fingerprint(_canonical_json(compiled_material))
    material = {
        "schema_version": "specstyle.preview.execution.v3",
        "compiled_request_fingerprint": compiled_fingerprint.value,
        "compiled_request": compiled_material,
        "models": json.loads(loaded._model_bindings_json),
        "environment_sha256": loaded._environment_hash.value,
        "runtime": {
            "rocm_version": loaded._runtime[0],
            "torch_version": loaded._runtime[1],
            "diffusers_version": loaded._runtime[2],
            "peft_version": loaded._peft_version,
            "dtype": loaded._runtime[3],
            "vae_at_rest_dtype": loaded._vae_at_rest_dtype,
            "vae_compute_dtype": loaded._vae_compute_dtype,
            "vae_precision_policy": loaded._vae_precision_policy,
        },
        "scheduler": {
            "identity": loaded._scheduler_identity,
            "config": json.loads(loaded._scheduler_config_json),
            "config_sha256": _fingerprint(loaded._scheduler_config_json).value,
        },
        "lora_fuse_scale": loaded._lora_fuse_scale,
    }
    material_json = _canonical_json(material)
    return _issue_execution_binding(compiled_fingerprint, material_json)


def build_preview_artifact(
    content: bytes, binding: PreviewExecutionBinding
) -> PreviewGeneratedArtifact:
    if type(content) is not bytes:
        raise DomainError("invalid preview artifact input")
    _validate_execution_binding(binding)
    content_sha256 = hash_bytes(content)
    return PreviewGeneratedArtifact(
        _preview_artifact_id(binding.execution_fingerprint, content_sha256),
        content,
        content_sha256,
        binding,
        binding.execution_fingerprint,
    )
