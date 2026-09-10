"""Strict loader for the independent Preview adapter supply configuration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from specstyle.domain.identifiers import Sha256
from specstyle.errors import DomainError
from specstyle.generation.model_approval import LicenseApproval
from specstyle.generation.model_registry import ModelDescriptor, ModelRegistry
from specstyle.generation.preview_adapter_supply import (
    PreviewAdapterEntrypoint,
    PreviewAdapterManifest,
    preview_adapter_manifest_root_sha256,
    preview_adapter_manifest_sha256,
)
from specstyle.generation.weight_manifest import WeightFile
from specstyle.production.config_io import load_fixed_json_documents

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
_ENTRYPOINT_KEYS = {"kind", "subfolder", "weight_name"}
_FILE_KEYS = {"relative_path", "size_bytes", "sha256"}
_APPROVAL_KEYS = {
    "model_id",
    "revision",
    "manifest_sha256",
    "license_spdx",
    "evidence_url",
}


@dataclass(frozen=True, slots=True, init=False)
class PreviewSupplyConfig:
    descriptor: ModelDescriptor
    manifest: PreviewAdapterManifest
    approval: LicenseApproval

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("preview supply configs are issued only by the loader")


def _exact_object(value: object, keys: set[str], label: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        raise DomainError(f"invalid {label} schema")
    return value


def _singleton(document: object, schema: str, collection: str) -> object:
    outer = _exact_object(document, {"schema_version", collection}, collection)
    if outer["schema_version"] != schema:
        raise DomainError(f"invalid {collection} schema version")
    values = outer[collection]
    if type(values) is not list or len(values) != 1:
        raise DomainError(f"invalid {collection}")
    return values[0]


def _load_descriptor(document: dict[str, Any]) -> ModelDescriptor:
    raw = _exact_object(
        _singleton(document, "specstyle.preview.models.v1", "models"),
        _MODEL_KEYS,
        "preview model descriptor",
    )
    descriptor = ModelDescriptor(
        model_id=raw["model_id"],
        role=raw["role"],
        revision=raw["revision"],
        expected_sha256=Sha256(raw["expected_sha256"]),
        license_spdx=raw["license_spdx"],
        license_status=raw["license_status"],
        family=raw["family"],
    )
    if (
        descriptor.role != "preview_adapter"
        or descriptor.model_id.casefold() == "lcm-lora-sdxl"
        or descriptor.family != "sdxl-production"
    ):
        raise DomainError("invalid preview adapter descriptor")
    ModelRegistry((descriptor,)).require_production(descriptor.model_id)
    return descriptor


def _load_files(value: object) -> tuple[WeightFile, ...]:
    if type(value) is not list:
        raise DomainError("invalid preview adapter files")
    files = tuple(
        WeightFile(
            relative_path=raw["relative_path"],
            size_bytes=raw["size_bytes"],
            sha256=Sha256(raw["sha256"]),
        )
        for raw in (
            _exact_object(item, _FILE_KEYS, "preview adapter file") for item in value
        )
    )
    paths = [item.relative_path for item in files]
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        raise DomainError("preview adapter files must be uniquely sorted")
    return files


def _load_manifest(document: dict[str, Any]) -> PreviewAdapterManifest:
    raw = _exact_object(
        _singleton(
            document,
            "specstyle.preview.weight_manifests.v1",
            "manifests",
        ),
        _MANIFEST_KEYS,
        "preview adapter manifest",
    )
    entrypoint = _exact_object(
        raw["entrypoint"], _ENTRYPOINT_KEYS, "preview adapter entrypoint"
    )
    manifest = PreviewAdapterManifest(
        model_id=raw["model_id"],
        role=raw["role"],
        revision=raw["revision"],
        relative_root=raw["relative_root"],
        entrypoint=PreviewAdapterEntrypoint(
            kind=entrypoint["kind"],
            subfolder=entrypoint["subfolder"],
            weight_name=entrypoint["weight_name"],
        ),
        files=_load_files(raw["files"]),
        root_sha256=Sha256(raw["root_sha256"]),
        schema_version=raw["schema_version"],
    )
    if preview_adapter_manifest_root_sha256(manifest) != manifest.root_sha256:
        raise DomainError("preview adapter manifest root digest mismatch")
    return manifest


def _load_approval(document: dict[str, Any]) -> LicenseApproval:
    raw = _exact_object(
        _singleton(
            document,
            "specstyle.preview.license_approvals.v1",
            "approvals",
        ),
        _APPROVAL_KEYS,
        "preview adapter license approval",
    )
    return LicenseApproval(
        model_id=raw["model_id"],
        revision=raw["revision"],
        manifest_sha256=Sha256(raw["manifest_sha256"]),
        license_spdx=raw["license_spdx"],
        evidence_url=raw["evidence_url"],
    )


def _issue_config(
    descriptor: ModelDescriptor,
    manifest: PreviewAdapterManifest,
    approval: LicenseApproval,
) -> PreviewSupplyConfig:
    issued = object.__new__(PreviewSupplyConfig)
    object.__setattr__(issued, "descriptor", descriptor)
    object.__setattr__(issued, "manifest", manifest)
    object.__setattr__(issued, "approval", approval)
    return issued


def load_preview_supply_config(config_root_fd: int, /) -> PreviewSupplyConfig:
    """Load one Preview-only adapter pin without creating a pipeline graph."""
    documents = load_fixed_json_documents(config_root_fd)
    descriptor = _load_descriptor(documents["models.json"])
    manifest = _load_manifest(documents["weight_manifests.json"])
    approval = _load_approval(documents["license_approvals.json"])
    if (
        descriptor.model_id != manifest.model_id
        or descriptor.revision != manifest.revision
        or descriptor.expected_sha256 != manifest.root_sha256
        or approval.model_id != descriptor.model_id
        or approval.revision != descriptor.revision
        or approval.manifest_sha256 != preview_adapter_manifest_sha256(manifest)
        or approval.license_spdx != descriptor.license_spdx
    ):
        raise DomainError("preview adapter supply closed-loop mismatch")
    return _issue_config(descriptor, manifest, approval)
