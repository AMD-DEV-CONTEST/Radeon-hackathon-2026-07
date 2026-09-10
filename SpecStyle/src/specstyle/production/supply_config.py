"""Strict loader for the approved production model-supply configuration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from specstyle.domain.identifiers import Sha256
from specstyle.errors import DomainError
from specstyle.generation.model_approval import LicenseApproval
from specstyle.generation.model_registry import ModelDescriptor, ModelRegistry
from specstyle.generation.pipeline_factory import PipelineFactory, PipelineGraph
from specstyle.generation.weight_manifest import (
    ModelLoadEntrypoint,
    WeightFile,
    WeightManifest,
    manifest_root_sha256,
    manifest_sha256,
)
from specstyle.production.config_io import load_fixed_json_documents

_ROLES = ("base", "ip_adapter", "controlnet")
_MODEL_KEYS = {
    "model_id",
    "role",
    "revision",
    "expected_sha256",
    "license_spdx",
    "license_status",
    "family",
}
_MANIFEST_KEYS = {
    "schema_version",
    "model_id",
    "role",
    "revision",
    "relative_root",
    "entrypoint",
    "files",
    "root_sha256",
}
_ENTRYPOINT_KEYS = {
    "kind",
    "subfolder",
    "weight_name",
    "image_encoder_folder",
    "variant",
}
_FILE_KEYS = {"relative_path", "size_bytes", "sha256"}
_APPROVAL_KEYS = {
    "model_id",
    "revision",
    "manifest_sha256",
    "license_spdx",
    "evidence_url",
}
_PLACEHOLDER_MODEL_IDS = {
    "sdxl-base-1.0",
    "ip-adapter-plus-sdxl",
    "controlnet-canny-sdxl",
}


@dataclass(frozen=True, slots=True, init=False)
class ProductionSupplyConfig:
    graph: PipelineGraph
    manifests: tuple[WeightManifest, ...]
    approvals: tuple[LicenseApproval, ...]

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("production supply configs are issued only by the loader")


def _exact_object(value: object, keys: set[str], label: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        raise DomainError(f"invalid {label} schema")
    return value


def _exact_array(value: object, length: int, label: str) -> list[Any]:
    if type(value) is not list or len(value) != length:
        raise DomainError(f"invalid {label}")
    return value


def _outer(document: object, schema: str, collection: str) -> list[Any]:
    value = _exact_object(document, {"schema_version", collection}, collection)
    if type(value["schema_version"]) is not str or value["schema_version"] != schema:
        raise DomainError(f"invalid {collection} schema version")
    return _exact_array(value[collection], 3, collection)


def _load_descriptors(document: dict[str, Any]) -> tuple[ModelDescriptor, ...]:
    values = _outer(document, "specstyle.production.models.v1", "models")
    descriptors: list[ModelDescriptor] = []
    for item in values:
        raw = _exact_object(item, _MODEL_KEYS, "model descriptor")
        descriptor = ModelDescriptor(
            model_id=raw["model_id"],
            role=raw["role"],
            revision=raw["revision"],
            expected_sha256=Sha256(raw["expected_sha256"]),
            license_spdx=raw["license_spdx"],
            license_status=raw["license_status"],
            family=raw["family"],
        )
        descriptors.append(descriptor)
    if tuple(item.role for item in descriptors) != _ROLES:
        raise DomainError("production models must use fixed role order")
    if len({item.model_id for item in descriptors}) != 3:
        raise DomainError("production model ids must be unique")
    if any(item.model_id.casefold() in _PLACEHOLDER_MODEL_IDS for item in descriptors):
        raise DomainError("placeholder production model forbidden")
    return tuple(descriptors)


def _load_manifest_item(value: object) -> WeightManifest:
    raw = _exact_object(value, _MANIFEST_KEYS, "weight manifest")
    entrypoint = _exact_object(raw["entrypoint"], _ENTRYPOINT_KEYS, "entrypoint")
    file_values = raw["files"]
    if type(file_values) is not list:
        raise DomainError("invalid weight manifest files")
    files: list[WeightFile] = []
    for item in file_values:
        file_raw = _exact_object(item, _FILE_KEYS, "weight file")
        files.append(
            WeightFile(
                relative_path=file_raw["relative_path"],
                size_bytes=file_raw["size_bytes"],
                sha256=Sha256(file_raw["sha256"]),
            )
        )
    paths = [item.relative_path for item in files]
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        raise DomainError("weight manifest files must be uniquely sorted")
    return WeightManifest(
        schema_version=raw["schema_version"],
        model_id=raw["model_id"],
        role=raw["role"],
        revision=raw["revision"],
        relative_root=raw["relative_root"],
        entrypoint=ModelLoadEntrypoint(
            kind=entrypoint["kind"],
            subfolder=entrypoint["subfolder"],
            weight_name=entrypoint["weight_name"],
            image_encoder_folder=entrypoint["image_encoder_folder"],
            variant=entrypoint["variant"],
        ),
        files=tuple(files),
        root_sha256=Sha256(raw["root_sha256"]),
    )


def _load_manifests(document: dict[str, Any]) -> tuple[WeightManifest, ...]:
    values = _outer(
        document,
        "specstyle.production.weight_manifests.v1",
        "manifests",
    )
    manifests = tuple(_load_manifest_item(item) for item in values)
    if tuple(item.role for item in manifests) != _ROLES:
        raise DomainError("production manifests must use fixed role order")
    if any(manifest_root_sha256(item) != item.root_sha256 for item in manifests):
        raise DomainError("production manifest root digest mismatch")
    return manifests


def _load_approvals(document: dict[str, Any]) -> tuple[LicenseApproval, ...]:
    values = _outer(
        document,
        "specstyle.production.license_approvals.v1",
        "approvals",
    )
    approvals = tuple(
        LicenseApproval(
            model_id=raw["model_id"],
            revision=raw["revision"],
            manifest_sha256=Sha256(raw["manifest_sha256"]),
            license_spdx=raw["license_spdx"],
            evidence_url=raw["evidence_url"],
        )
        for raw in (
            _exact_object(item, _APPROVAL_KEYS, "license approval") for item in values
        )
    )
    if len({item.model_id for item in approvals}) != 3:
        raise DomainError("production approval models must be unique")
    return approvals


def _join_supply(
    graph: PipelineGraph,
    manifests: tuple[WeightManifest, ...],
    approvals: tuple[LicenseApproval, ...],
) -> tuple[LicenseApproval, ...]:
    descriptors = (graph.base, graph.ip_adapter, graph.controlnet)
    approvals_by_model = {item.model_id: item for item in approvals}
    ordered: list[LicenseApproval] = []
    for descriptor, manifest in zip(descriptors, manifests, strict=True):
        approval = approvals_by_model.get(descriptor.model_id)
        if (
            manifest.model_id != descriptor.model_id
            or manifest.role != descriptor.role
            or manifest.revision != descriptor.revision
            or manifest.root_sha256 != descriptor.expected_sha256
            or approval is None
            or approval.revision != descriptor.revision
            or approval.manifest_sha256 != manifest_sha256(manifest)
            or approval.license_spdx != descriptor.license_spdx
        ):
            raise DomainError("production supply closed-loop mismatch")
        ordered.append(approval)
    return tuple(ordered)


def _issue_config(
    graph: PipelineGraph,
    manifests: tuple[WeightManifest, ...],
    approvals: tuple[LicenseApproval, ...],
) -> ProductionSupplyConfig:
    issued = object.__new__(ProductionSupplyConfig)
    object.__setattr__(issued, "graph", graph)
    object.__setattr__(issued, "manifests", manifests)
    object.__setattr__(issued, "approvals", approvals)
    return issued


def load_production_supply_config(config_root_fd: int, /) -> ProductionSupplyConfig:
    """Load and cross-check production pins without verifying or loading weights."""
    documents = load_fixed_json_documents(config_root_fd)
    descriptors = _load_descriptors(documents["models.json"])
    manifests = _load_manifests(documents["weight_manifests.json"])
    approvals = _load_approvals(documents["license_approvals.json"])
    registry = ModelRegistry(descriptors)
    graph = PipelineFactory(registry, Path("models")).build_production(
        descriptors[0].model_id,
        descriptors[1].model_id,
        descriptors[2].model_id,
    )
    ordered_approvals = _join_supply(graph, manifests, approvals)
    return _issue_config(graph, manifests, ordered_approvals)
