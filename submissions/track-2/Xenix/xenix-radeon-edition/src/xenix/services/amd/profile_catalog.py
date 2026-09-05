"""Explicit, side-effect-free loading of the bundled AMD product manifests.

The loader deliberately names every resource it accepts.  It does not discover
plugins or manifests, resolve a network location, make a target directory, or
cache mutable runtime state.  Resources are read only when a public loader is
called, which keeps importing the Radeon control plane inert.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from enum import StrEnum
from pathlib import Path
from typing import TypeVar

from xenix.resources import package_resource_path

from .manifests import (
    ArtifactDescriptor,
    ArtifactKind,
    ArtifactSource,
    CapacityRequirements,
    CompatibilityCell,
    CompatibilityTargetKind,
    ComponentManifest,
    ComponentManifestRef,
    EnvironmentSetting,
    ExecutionProfileManifest,
    ExecutionProfilePlacement,
    LaunchDescriptor,
    ManifestAdmission,
    ManifestAdmissionBlocker,
    ManifestCapability,
    ManifestCatalog,
    ManifestError,
    ModelDescriptor,
    ProtocolDescriptor,
    ProtocolFieldDisposition,
    ProtocolFieldRule,
    RuntimeDescriptor,
    RuntimePackage,
    SelfTestDescriptor,
    SourceKind,
)


_RESOURCE_ROOT = ("amd", "manifests")
_COMPONENT_RESOURCES = (
    ("components", "qwen3.5-9b.json"),
    ("components", "qwen3.5-4b.json"),
    ("components", "bge-m3.json"),
    ("components", "bge-m3-v2.json"),
    ("components", "rapidocr-3.9.2-pp-ocrv6.json"),
    ("components", "rapidocr-3.9.2-pp-ocrv6-v2.json"),
)
_PROFILE_RESOURCES = (
    ("profiles", "radeon-cloud-gfx1100-chat-qwen3.5-9b.json"),
    ("profiles", "radeon-cloud-gfx1100-chat-qwen3.5-4b.json"),
    ("profiles", "radeon-cloud-gfx1100-embedding.json"),
    ("profiles", "radeon-cloud-gfx1100-embedding-v2.json"),
    ("profiles", "radeon-cloud-gfx1100-ocr.json"),
    ("profiles", "radeon-cloud-gfx1100-ocr-v2.json"),
    ("profiles", "radeon-wsl2-gfx1100-embedding.json"),
    ("profiles", "radeon-wsl2-gfx1100-ocr.json"),
)
_ManifestEnum = TypeVar("_ManifestEnum", bound=StrEnum)


class ProductManifestResourceError(ManifestError):
    """A bundled AMD product manifest resource is structurally invalid."""


def load_product_manifest_catalog() -> ManifestCatalog:
    """Load the single bundled AMD product catalog on explicit caller demand.

    The returned catalog retains immutable component/profile digests and validates
    every profile reference.  Resource reads are the only I/O performed here.
    """

    components = tuple(_load_component_manifest(resource) for resource in _COMPONENT_RESOURCES)
    profiles = tuple(_load_execution_profile(resource) for resource in _PROFILE_RESOURCES)
    return ManifestCatalog.from_iterables(components, profiles)


def _load_component_manifest(resource: tuple[str, ...]) -> ComponentManifest:
    payload = _read_json_object(resource)
    _require_fields(
        payload,
        {
            "schema_version",
            "manifest_id",
            "manifest_version",
            "capability",
            "sources",
            "artifacts",
            "models",
            "runtime",
            "protocol",
            "launch",
            "self_tests",
            "compatibility_cells",
            "capacity",
            "admission",
            "admission_blockers",
        },
        resource,
    )
    return ComponentManifest(
        schema_version=_integer(payload["schema_version"], resource, "schema_version"),
        manifest_id=_string(payload["manifest_id"], resource, "manifest_id"),
        manifest_version=_string(payload["manifest_version"], resource, "manifest_version"),
        capability=_enum(ManifestCapability, payload["capability"], resource, "capability"),
        sources=tuple(
            _parse_artifact_source(item, resource, f"sources[{index}]")
            for index, item in enumerate(_array(payload["sources"], resource, "sources"))
        ),
        artifacts=tuple(
            _parse_artifact(item, resource, f"artifacts[{index}]")
            for index, item in enumerate(_array(payload["artifacts"], resource, "artifacts"))
        ),
        models=tuple(
            _parse_model(item, resource, f"models[{index}]")
            for index, item in enumerate(_array(payload["models"], resource, "models"))
        ),
        runtime=_parse_runtime(_object(payload["runtime"], resource, "runtime"), resource, "runtime"),
        protocol=_parse_protocol(_object(payload["protocol"], resource, "protocol"), resource, "protocol"),
        launch=_parse_launch(_object(payload["launch"], resource, "launch"), resource, "launch"),
        self_tests=tuple(
            _parse_self_test(item, resource, f"self_tests[{index}]")
            for index, item in enumerate(_array(payload["self_tests"], resource, "self_tests"))
        ),
        compatibility_cells=tuple(
            _parse_compatibility_cell(item, resource, f"compatibility_cells[{index}]")
            for index, item in enumerate(_array(payload["compatibility_cells"], resource, "compatibility_cells"))
        ),
        capacity=_parse_capacity(_object(payload["capacity"], resource, "capacity"), resource, "capacity"),
        admission=_enum(ManifestAdmission, payload["admission"], resource, "admission"),
        admission_blockers=_parse_admission_blockers(payload["admission_blockers"], resource, "admission_blockers"),
    )


def _load_execution_profile(resource: tuple[str, ...]) -> ExecutionProfileManifest:
    payload = _read_json_object(resource)
    _require_fields(
        payload,
        {
            "schema_version",
            "profile_id",
            "profile_version",
            "compatibility_cell_id",
            "components",
            "capacity",
            "admission",
            "admission_blockers",
            "placement",
        },
        resource,
    )
    return ExecutionProfileManifest(
        schema_version=_integer(payload["schema_version"], resource, "schema_version"),
        profile_id=_string(payload["profile_id"], resource, "profile_id"),
        profile_version=_string(payload["profile_version"], resource, "profile_version"),
        compatibility_cell_id=_string(payload["compatibility_cell_id"], resource, "compatibility_cell_id"),
        components=tuple(
            _parse_component_reference(item, resource, f"components[{index}]")
            for index, item in enumerate(_array(payload["components"], resource, "components"))
        ),
        capacity=_parse_capacity(_object(payload["capacity"], resource, "capacity"), resource, "capacity"),
        admission=_enum(ManifestAdmission, payload["admission"], resource, "admission"),
        admission_blockers=_parse_admission_blockers(payload["admission_blockers"], resource, "admission_blockers"),
        placement=_enum(ExecutionProfilePlacement, payload["placement"], resource, "placement"),
    )


def _parse_artifact_source(value: object, resource: tuple[str, ...], field: str) -> ArtifactSource:
    payload = _object(value, resource, field)
    _require_fields(
        payload,
        {"source_id", "kind", "locator", "revision", "acquisition_verified", "verification_reference"},
        resource,
        field,
    )
    return ArtifactSource(
        source_id=_string(payload["source_id"], resource, f"{field}.source_id"),
        kind=_enum(SourceKind, payload["kind"], resource, f"{field}.kind"),
        locator=_string(payload["locator"], resource, f"{field}.locator"),
        revision=_string(payload["revision"], resource, f"{field}.revision"),
        acquisition_verified=_boolean(payload["acquisition_verified"], resource, f"{field}.acquisition_verified"),
        verification_reference=_optional_string(
            payload["verification_reference"], resource, f"{field}.verification_reference"
        ),
    )


def _parse_artifact(value: object, resource: tuple[str, ...], field: str) -> ArtifactDescriptor:
    payload = _object(value, resource, field)
    _require_fields(
        payload,
        {"artifact_id", "kind", "relative_path", "source_id", "sha256", "size_bytes", "license_spdx"},
        resource,
        field,
    )
    return ArtifactDescriptor(
        artifact_id=_string(payload["artifact_id"], resource, f"{field}.artifact_id"),
        kind=_enum(ArtifactKind, payload["kind"], resource, f"{field}.kind"),
        relative_path=_string(payload["relative_path"], resource, f"{field}.relative_path"),
        source_id=_string(payload["source_id"], resource, f"{field}.source_id"),
        sha256=_string(payload["sha256"], resource, f"{field}.sha256"),
        size_bytes=_integer(payload["size_bytes"], resource, f"{field}.size_bytes"),
        license_spdx=_string(payload["license_spdx"], resource, f"{field}.license_spdx"),
    )


def _parse_model(value: object, resource: tuple[str, ...], field: str) -> ModelDescriptor:
    payload = _object(value, resource, field)
    _require_fields(
        payload,
        {
            "model_id",
            "revision",
            "license_spdx",
            "artifact_ids",
            "tokenizer_id",
            "tokenizer_revision",
            "output_dimensions",
        },
        resource,
        field,
    )
    return ModelDescriptor(
        model_id=_string(payload["model_id"], resource, f"{field}.model_id"),
        revision=_string(payload["revision"], resource, f"{field}.revision"),
        license_spdx=_string(payload["license_spdx"], resource, f"{field}.license_spdx"),
        artifact_ids=tuple(
            _string(item, resource, f"{field}.artifact_ids[{index}]")
            for index, item in enumerate(_array(payload["artifact_ids"], resource, f"{field}.artifact_ids"))
        ),
        tokenizer_id=_optional_string(payload["tokenizer_id"], resource, f"{field}.tokenizer_id"),
        tokenizer_revision=_optional_string(payload["tokenizer_revision"], resource, f"{field}.tokenizer_revision"),
        output_dimensions=_optional_integer(payload["output_dimensions"], resource, f"{field}.output_dimensions"),
    )


def _parse_runtime(value: Mapping[str, object], resource: tuple[str, ...], field: str) -> RuntimeDescriptor:
    _require_fields(
        value,
        {
            "runtime_id",
            "runtime_version",
            "framework_id",
            "framework_version",
            "python_version",
            "packages",
            "allowed_plugins",
        },
        resource,
        field,
    )
    return RuntimeDescriptor(
        runtime_id=_string(value["runtime_id"], resource, f"{field}.runtime_id"),
        runtime_version=_string(value["runtime_version"], resource, f"{field}.runtime_version"),
        framework_id=_string(value["framework_id"], resource, f"{field}.framework_id"),
        framework_version=_string(value["framework_version"], resource, f"{field}.framework_version"),
        python_version=_string(value["python_version"], resource, f"{field}.python_version"),
        packages=tuple(
            _parse_runtime_package(item, resource, f"{field}.packages[{index}]")
            for index, item in enumerate(_array(value["packages"], resource, f"{field}.packages"))
        ),
        allowed_plugins=tuple(
            _string(item, resource, f"{field}.allowed_plugins[{index}]")
            for index, item in enumerate(_array(value["allowed_plugins"], resource, f"{field}.allowed_plugins"))
        ),
    )


def _parse_runtime_package(value: object, resource: tuple[str, ...], field: str) -> RuntimePackage:
    payload = _object(value, resource, field)
    _require_fields(payload, {"name", "version", "artifact_id"}, resource, field)
    return RuntimePackage(
        name=_string(payload["name"], resource, f"{field}.name"),
        version=_string(payload["version"], resource, f"{field}.version"),
        artifact_id=_string(payload["artifact_id"], resource, f"{field}.artifact_id"),
    )


def _parse_protocol(value: Mapping[str, object], resource: tuple[str, ...], field: str) -> ProtocolDescriptor:
    _require_fields(
        value,
        {
            "protocol_id",
            "protocol_version",
            "profile_id",
            "authentication_required",
            "unauthenticated_request_rejected",
            "field_rules",
        },
        resource,
        field,
    )
    return ProtocolDescriptor(
        protocol_id=_string(value["protocol_id"], resource, f"{field}.protocol_id"),
        protocol_version=_string(value["protocol_version"], resource, f"{field}.protocol_version"),
        profile_id=_string(value["profile_id"], resource, f"{field}.profile_id"),
        authentication_required=_boolean(
            value["authentication_required"], resource, f"{field}.authentication_required"
        ),
        unauthenticated_request_rejected=_boolean(
            value["unauthenticated_request_rejected"], resource, f"{field}.unauthenticated_request_rejected"
        ),
        field_rules=tuple(
            _parse_protocol_field_rule(item, resource, f"{field}.field_rules[{index}]")
            for index, item in enumerate(_array(value["field_rules"], resource, f"{field}.field_rules"))
        ),
    )


def _parse_protocol_field_rule(value: object, resource: tuple[str, ...], field: str) -> ProtocolFieldRule:
    payload = _object(value, resource, field)
    _require_fields(payload, {"field_name", "disposition", "expected_value"}, resource, field)
    expected_value = payload["expected_value"]
    if not isinstance(expected_value, str | int | bool | None):
        raise _resource_error(resource, f"{field}.expected_value must be a JSON scalar or null.")
    return ProtocolFieldRule(
        field_name=_string(payload["field_name"], resource, f"{field}.field_name"),
        disposition=_enum(ProtocolFieldDisposition, payload["disposition"], resource, f"{field}.disposition"),
        expected_value=expected_value,
    )


def _parse_launch(value: Mapping[str, object], resource: tuple[str, ...], field: str) -> LaunchDescriptor:
    _require_fields(
        value,
        {
            "executable",
            "served_model_name",
            "arguments",
            "environment",
            "loopback_only",
            "protected_auth_handoff_required",
            "isolated_cache_required",
            "isolated_config_required",
        },
        resource,
        field,
    )
    return LaunchDescriptor(
        executable=_string(value["executable"], resource, f"{field}.executable"),
        served_model_name=_string(value["served_model_name"], resource, f"{field}.served_model_name"),
        arguments=tuple(
            _string(item, resource, f"{field}.arguments[{index}]")
            for index, item in enumerate(_array(value["arguments"], resource, f"{field}.arguments"))
        ),
        environment=tuple(
            _parse_environment_setting(item, resource, f"{field}.environment[{index}]")
            for index, item in enumerate(_array(value["environment"], resource, f"{field}.environment"))
        ),
        loopback_only=_boolean(value["loopback_only"], resource, f"{field}.loopback_only"),
        protected_auth_handoff_required=_boolean(
            value["protected_auth_handoff_required"], resource, f"{field}.protected_auth_handoff_required"
        ),
        isolated_cache_required=_boolean(
            value["isolated_cache_required"], resource, f"{field}.isolated_cache_required"
        ),
        isolated_config_required=_boolean(
            value["isolated_config_required"], resource, f"{field}.isolated_config_required"
        ),
    )


def _parse_environment_setting(value: object, resource: tuple[str, ...], field: str) -> EnvironmentSetting:
    payload = _object(value, resource, field)
    _require_fields(payload, {"name", "value"}, resource, field)
    return EnvironmentSetting(
        name=_string(payload["name"], resource, f"{field}.name"),
        value=_string(payload["value"], resource, f"{field}.value"),
    )


def _parse_self_test(value: object, resource: tuple[str, ...], field: str) -> SelfTestDescriptor:
    payload = _object(value, resource, field)
    _require_fields(payload, {"test_id", "deadline_seconds", "required_evidence"}, resource, field)
    return SelfTestDescriptor(
        test_id=_string(payload["test_id"], resource, f"{field}.test_id"),
        deadline_seconds=_number(payload["deadline_seconds"], resource, f"{field}.deadline_seconds"),
        required_evidence=tuple(
            _string(item, resource, f"{field}.required_evidence[{index}]")
            for index, item in enumerate(_array(payload["required_evidence"], resource, f"{field}.required_evidence"))
        ),
    )


def _parse_compatibility_cell(value: object, resource: tuple[str, ...], field: str) -> CompatibilityCell:
    payload = _object(value, resource, field)
    _require_fields(
        payload,
        {
            "cell_id",
            "os_name",
            "os_version",
            "kernel_version",
            "architecture",
            "gpu_architecture",
            "driver_version",
            "rocm_version",
            "hip_version",
            "python_version",
            "admission",
            "admission_blockers",
            "target_kind",
        },
        resource,
        field,
    )
    return CompatibilityCell(
        cell_id=_string(payload["cell_id"], resource, f"{field}.cell_id"),
        os_name=_string(payload["os_name"], resource, f"{field}.os_name"),
        os_version=_string(payload["os_version"], resource, f"{field}.os_version"),
        kernel_version=_string(payload["kernel_version"], resource, f"{field}.kernel_version"),
        architecture=_string(payload["architecture"], resource, f"{field}.architecture"),
        gpu_architecture=_string(payload["gpu_architecture"], resource, f"{field}.gpu_architecture"),
        driver_version=_string(payload["driver_version"], resource, f"{field}.driver_version"),
        rocm_version=_string(payload["rocm_version"], resource, f"{field}.rocm_version"),
        hip_version=_string(payload["hip_version"], resource, f"{field}.hip_version"),
        python_version=_string(payload["python_version"], resource, f"{field}.python_version"),
        admission=_enum(ManifestAdmission, payload["admission"], resource, f"{field}.admission"),
        admission_blockers=_parse_admission_blockers(
            payload["admission_blockers"], resource, f"{field}.admission_blockers"
        ),
        target_kind=_enum(CompatibilityTargetKind, payload["target_kind"], resource, f"{field}.target_kind"),
    )


def _parse_capacity(value: Mapping[str, object], resource: tuple[str, ...], field: str) -> CapacityRequirements:
    _require_fields(
        value,
        {
            "min_gpu_count",
            "min_free_vram_bytes",
            "min_free_system_memory_bytes",
            "required_persistent_bytes",
        },
        resource,
        field,
    )
    return CapacityRequirements(
        min_gpu_count=_integer(value["min_gpu_count"], resource, f"{field}.min_gpu_count"),
        min_free_vram_bytes=_optional_integer(value["min_free_vram_bytes"], resource, f"{field}.min_free_vram_bytes"),
        min_free_system_memory_bytes=_optional_integer(
            value["min_free_system_memory_bytes"], resource, f"{field}.min_free_system_memory_bytes"
        ),
        required_persistent_bytes=_optional_integer(
            value["required_persistent_bytes"], resource, f"{field}.required_persistent_bytes"
        ),
    )


def _parse_component_reference(value: object, resource: tuple[str, ...], field: str) -> ComponentManifestRef:
    payload = _object(value, resource, field)
    _require_fields(payload, {"capability", "manifest_id", "manifest_digest"}, resource, field)
    return ComponentManifestRef(
        capability=_enum(ManifestCapability, payload["capability"], resource, f"{field}.capability"),
        manifest_id=_string(payload["manifest_id"], resource, f"{field}.manifest_id"),
        manifest_digest=_string(payload["manifest_digest"], resource, f"{field}.manifest_digest"),
    )


def _parse_admission_blockers(
    value: object,
    resource: tuple[str, ...],
    field: str,
) -> tuple[ManifestAdmissionBlocker, ...]:
    return tuple(
        _enum(ManifestAdmissionBlocker, item, resource, f"{field}[{index}]")
        for index, item in enumerate(_array(value, resource, field))
    )


def _read_json_object(resource: tuple[str, ...]) -> Mapping[str, object]:
    path = _resource_path(resource)
    try:
        with path.open(encoding="utf-8") as stream:
            value = json.load(stream)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise _resource_error(resource, "could not be read as UTF-8 JSON.") from error
    return _object(value, resource, "root")


def _resource_path(resource: tuple[str, ...]) -> Path:
    try:
        return package_resource_path(*_RESOURCE_ROOT, *resource)
    except OSError as error:
        raise _resource_error(resource, "is unavailable from the packaged resources.") from error


def _object(value: object, resource: tuple[str, ...], field: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise _resource_error(resource, f"{field} must be a JSON object.")
    return value


def _array(value: object, resource: tuple[str, ...], field: str) -> Sequence[object]:
    if not isinstance(value, list):
        raise _resource_error(resource, f"{field} must be a JSON array.")
    return value


def _string(value: object, resource: tuple[str, ...], field: str) -> str:
    if not isinstance(value, str):
        raise _resource_error(resource, f"{field} must be a string.")
    return value


def _optional_string(value: object, resource: tuple[str, ...], field: str) -> str | None:
    if value is None:
        return None
    return _string(value, resource, field)


def _integer(value: object, resource: tuple[str, ...], field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise _resource_error(resource, f"{field} must be an integer.")
    return value


def _optional_integer(value: object, resource: tuple[str, ...], field: str) -> int | None:
    if value is None:
        return None
    return _integer(value, resource, field)


def _number(value: object, resource: tuple[str, ...], field: str) -> int | float:
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise _resource_error(resource, f"{field} must be a number.")
    return value


def _boolean(value: object, resource: tuple[str, ...], field: str) -> bool:
    if not isinstance(value, bool):
        raise _resource_error(resource, f"{field} must be a boolean.")
    return value


def _enum(
    enum_type: type[_ManifestEnum],
    value: object,
    resource: tuple[str, ...],
    field: str,
) -> _ManifestEnum:
    raw_value = _string(value, resource, field)
    try:
        return enum_type(raw_value)
    except ValueError as error:
        raise _resource_error(resource, f"{field} is not a supported value.") from error


def _require_fields(
    payload: Mapping[str, object],
    expected: set[str],
    resource: tuple[str, ...],
    field: str = "root",
) -> None:
    actual = set(payload)
    missing = sorted(expected - actual)
    unexpected = sorted(actual - expected)
    if missing or unexpected:
        details: list[str] = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if unexpected:
            details.append("unexpected " + ", ".join(unexpected))
        raise _resource_error(resource, f"{field} fields are invalid: {'; '.join(details)}.")


def _resource_error(resource: tuple[str, ...], detail: str) -> ProductManifestResourceError:
    return ProductManifestResourceError(f"AMD manifest resource {'/'.join(resource)}: {detail}")


__all__ = [
    "ProductManifestResourceError",
    "load_product_manifest_catalog",
]
