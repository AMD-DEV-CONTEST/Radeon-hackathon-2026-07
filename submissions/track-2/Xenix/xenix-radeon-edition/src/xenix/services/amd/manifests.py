"""Immutable technical manifests for the optional managed AMD slice.

This module owns descriptor shape and canonical hashing only.  It performs no
resource discovery, download, target inspection, registration, or lifecycle
mutation.  Concrete product recipes are supplied by later composition tasks.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import PurePosixPath
from types import MappingProxyType
from urllib.parse import urlsplit


MANIFEST_SCHEMA_VERSION = 1

_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,255}$")
_ENVIRONMENT_NAME_PATTERN = re.compile(r"^[A-Z_][A-Z0-9_]{0,127}$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_SENSITIVE_PATTERN = re.compile(
    r"(?:^|[-_ =:])"
    r"(?:api[-_]?key|authorization|bearer|credential|password|private[-_]?key|secret|token)"
    r"(?:$|[-_ =:])",
    re.IGNORECASE,
)


class ManifestError(ValueError):
    """A manifest or catalog violates an immutable product invariant."""


class ManifestNotFoundError(ManifestError):
    """An exact manifest digest is absent from the catalog."""


class ManifestConflictError(ManifestError):
    """Two manifests claim the same immutable semantic identity."""


class ManifestCapability(StrEnum):
    CHAT = "chat"
    EMBEDDING = "embedding"
    OCR = "ocr"


class ExecutionProfilePlacement(StrEnum):
    """The one execution-location family a product profile may admit."""

    LEGACY = "legacy"
    PRIVATE_SSH = "private_ssh"
    LOCAL_WSL = "local_wsl"


class CompatibilityTargetKind(StrEnum):
    """The Linux environment that produced compatibility observations."""

    NATIVE_LINUX = "native_linux"
    WSL2 = "wsl2"


class ManifestAdmission(StrEnum):
    DRAFT = "draft"
    ADMITTED = "admitted"


class ManifestAdmissionBlocker(StrEnum):
    ACQUISITION_SOURCE_UNVERIFIED = "acquisition_source_unverified"
    ARTIFACT_DIGEST_UNVERIFIED = "artifact_digest_unverified"
    AUTHENTICATION_UNVERIFIED = "authentication_unverified"
    CAPACITY_UNMEASURED = "capacity_unmeasured"
    COMPATIBILITY_CELL_UNVERIFIED = "compatibility_cell_unverified"
    LICENSE_UNVERIFIED = "license_unverified"
    PROFILE_INCOMPLETE = "profile_incomplete"
    RUNTIME_RECIPE_INCOMPLETE = "runtime_recipe_incomplete"
    SELF_TEST_UNVERIFIED = "self_test_unverified"


class SourceKind(StrEnum):
    HTTPS = "https"
    HUGGING_FACE = "hugging_face"
    MODELSCOPE = "modelscope"
    PYPI = "pypi"


class ArtifactKind(StrEnum):
    RUNTIME = "runtime"
    MODEL = "model"
    TOKENIZER = "tokenizer"
    PLUGIN = "plugin"
    SCHEMA = "schema"
    SUPPORT = "support"


class ProtocolFieldDisposition(StrEnum):
    REQUIRED = "required"
    OPTIONAL = "optional"
    OMIT = "omit"


@dataclass(frozen=True, slots=True)
class ArtifactSource:
    """One exact, credential-free acquisition source reference."""

    source_id: str
    kind: SourceKind
    locator: str
    revision: str
    acquisition_verified: bool
    verification_reference: str | None

    def __post_init__(self) -> None:
        _require_identifier(self.source_id, "Source ID")
        _require_enum(self.kind, SourceKind, "Source kind")
        _require_safe_text(self.locator, "Source locator", maximum=2_048)
        _require_exact_reference(self.revision, "Source revision")
        _reject_secret_material(self.locator, "Source locator")

        parsed = urlsplit(self.locator)
        if parsed.scheme:
            if self.kind is not SourceKind.HTTPS or parsed.scheme != "https":
                raise ManifestError("URL sources must use the HTTPS source kind and scheme.")
            if not parsed.hostname or parsed.username or parsed.password:
                raise ManifestError("HTTPS source locator must be absolute and credential-free.")
            if parsed.query or parsed.fragment:
                raise ManifestError("HTTPS source locator must not contain query or fragment data.")
        if self.acquisition_verified:
            if self.verification_reference is None:
                raise ManifestError("A verified acquisition source requires an opaque verification reference.")
            _require_identifier(self.verification_reference, "Source verification reference")
        elif self.verification_reference is not None:
            raise ManifestError("An unverified acquisition source cannot claim a verification reference.")

    def canonical_payload(self) -> dict[str, object]:
        return {
            "source_id": self.source_id,
            "kind": self.kind.value,
            "locator": self.locator,
            "revision": self.revision,
            "acquisition_verified": self.acquisition_verified,
            "verification_reference": self.verification_reference,
        }


@dataclass(frozen=True, slots=True)
class ArtifactDescriptor:
    """One immutable acquired file with source, size, digest, and license."""

    artifact_id: str
    kind: ArtifactKind
    relative_path: str
    source_id: str
    sha256: str
    size_bytes: int
    license_spdx: str

    def __post_init__(self) -> None:
        _require_identifier(self.artifact_id, "Artifact ID")
        _require_enum(self.kind, ArtifactKind, "Artifact kind")
        _require_relative_path(self.relative_path, "Artifact path")
        _require_identifier(self.source_id, "Artifact source ID")
        _require_sha256(self.sha256, "Artifact SHA-256")
        if not isinstance(self.size_bytes, int) or isinstance(self.size_bytes, bool) or self.size_bytes <= 0:
            raise ManifestError("Artifact size must be a positive integer.")
        _require_identifier(self.license_spdx, "Artifact license")

    def canonical_payload(self) -> dict[str, object]:
        return {
            "artifact_id": self.artifact_id,
            "kind": self.kind.value,
            "relative_path": self.relative_path,
            "source_id": self.source_id,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "license_spdx": self.license_spdx,
        }


@dataclass(frozen=True, slots=True)
class ModelDescriptor:
    """Exact model/tokenizer identity projected later into a capability catalog."""

    model_id: str
    revision: str
    license_spdx: str
    artifact_ids: tuple[str, ...]
    tokenizer_id: str | None = None
    tokenizer_revision: str | None = None
    output_dimensions: int | None = None

    def __post_init__(self) -> None:
        _require_identifier(self.model_id, "Model ID")
        _require_exact_reference(self.revision, "Model revision")
        _require_identifier(self.license_spdx, "Model license")
        object.__setattr__(self, "artifact_ids", _unique_identifiers(self.artifact_ids, "Model artifact ID"))
        if not self.artifact_ids:
            raise ManifestError("A model must reference at least one immutable artifact.")
        if (self.tokenizer_id is None) != (self.tokenizer_revision is None):
            raise ManifestError("Tokenizer ID and revision must be supplied together.")
        if self.tokenizer_id is not None:
            _require_identifier(self.tokenizer_id, "Tokenizer ID")
            _require_exact_reference(self.tokenizer_revision, "Tokenizer revision")
        if self.output_dimensions is not None and (
            not isinstance(self.output_dimensions, int)
            or isinstance(self.output_dimensions, bool)
            or self.output_dimensions <= 0
        ):
            raise ManifestError("Model output dimensions must be a positive integer or omitted.")

    def canonical_payload(self) -> dict[str, object]:
        return {
            "model_id": self.model_id,
            "revision": self.revision,
            "license_spdx": self.license_spdx,
            "artifact_ids": list(self.artifact_ids),
            "tokenizer_id": self.tokenizer_id,
            "tokenizer_revision": self.tokenizer_revision,
            "output_dimensions": self.output_dimensions,
        }


@dataclass(frozen=True, slots=True)
class RuntimePackage:
    name: str
    version: str
    artifact_id: str

    def __post_init__(self) -> None:
        _require_identifier(self.name, "Runtime package name")
        _require_exact_reference(self.version, "Runtime package version")
        _require_identifier(self.artifact_id, "Runtime package artifact ID")

    def canonical_payload(self) -> dict[str, object]:
        return {
            "name": self.name,
            "version": self.version,
            "artifact_id": self.artifact_id,
        }


@dataclass(frozen=True, slots=True)
class RuntimeDescriptor:
    runtime_id: str
    runtime_version: str
    framework_id: str
    framework_version: str
    python_version: str
    packages: tuple[RuntimePackage, ...]
    allowed_plugins: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_identifier(self.runtime_id, "Runtime ID")
        _require_exact_reference(self.runtime_version, "Runtime version")
        _require_identifier(self.framework_id, "Framework ID")
        _require_exact_reference(self.framework_version, "Framework version")
        _require_exact_reference(self.python_version, "Python version")
        object.__setattr__(self, "packages", tuple(sorted(self.packages, key=lambda package: package.name)))
        _require_unique_values((package.name for package in self.packages), "Runtime package name")
        object.__setattr__(
            self,
            "allowed_plugins",
            tuple(sorted(_unique_identifiers(self.allowed_plugins, "Allowed plugin ID"))),
        )

    def canonical_payload(self) -> dict[str, object]:
        return {
            "runtime_id": self.runtime_id,
            "runtime_version": self.runtime_version,
            "framework_id": self.framework_id,
            "framework_version": self.framework_version,
            "python_version": self.python_version,
            "packages": [package.canonical_payload() for package in self.packages],
            "allowed_plugins": list(self.allowed_plugins),
        }


@dataclass(frozen=True, slots=True)
class ProtocolFieldRule:
    field_name: str
    disposition: ProtocolFieldDisposition
    expected_value: str | int | bool | None = None

    def __post_init__(self) -> None:
        _require_identifier(self.field_name, "Protocol field name")
        _require_enum(self.disposition, ProtocolFieldDisposition, "Protocol field disposition")
        if not isinstance(self.expected_value, str | int | bool | None):
            raise ManifestError("Protocol field expected value is not canonical JSON scalar data.")
        if self.disposition is ProtocolFieldDisposition.OMIT and self.expected_value is not None:
            raise ManifestError("An omitted protocol field cannot have an expected value.")
        if isinstance(self.expected_value, str):
            _require_safe_text(self.expected_value, "Protocol field value")
            _reject_secret_material(self.expected_value, "Protocol field value")

    def canonical_payload(self) -> dict[str, object]:
        return {
            "field_name": self.field_name,
            "disposition": self.disposition.value,
            "expected_value": self.expected_value,
        }


@dataclass(frozen=True, slots=True)
class ProtocolDescriptor:
    protocol_id: str
    protocol_version: str
    profile_id: str
    authentication_required: bool
    unauthenticated_request_rejected: bool
    field_rules: tuple[ProtocolFieldRule, ...] = ()

    def __post_init__(self) -> None:
        _require_identifier(self.protocol_id, "Protocol ID")
        _require_exact_reference(self.protocol_version, "Protocol version")
        _require_identifier(self.profile_id, "Protocol profile ID")
        object.__setattr__(self, "field_rules", tuple(sorted(self.field_rules, key=lambda rule: rule.field_name)))
        _require_unique_values((rule.field_name for rule in self.field_rules), "Protocol field rule")

    def canonical_payload(self) -> dict[str, object]:
        return {
            "protocol_id": self.protocol_id,
            "protocol_version": self.protocol_version,
            "profile_id": self.profile_id,
            "authentication_required": self.authentication_required,
            "unauthenticated_request_rejected": self.unauthenticated_request_rejected,
            "field_rules": [rule.canonical_payload() for rule in self.field_rules],
        }


@dataclass(frozen=True, slots=True)
class EnvironmentSetting:
    """One static non-secret launch setting."""

    name: str
    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not _ENVIRONMENT_NAME_PATTERN.fullmatch(self.name):
            raise ManifestError("Environment setting name is invalid.")
        _require_safe_text(self.value, "Environment setting value", allow_empty=True)
        _reject_secret_material(self.name, "Environment setting name")
        _reject_secret_material(self.value, "Environment setting value")

    def canonical_payload(self) -> dict[str, object]:
        return {"name": self.name, "value": self.value}


@dataclass(frozen=True, slots=True)
class LaunchDescriptor:
    """Exact non-secret launch recipe; runtime authentication is handed off separately."""

    executable: str
    served_model_name: str
    arguments: tuple[str, ...]
    environment: tuple[EnvironmentSetting, ...]
    loopback_only: bool
    protected_auth_handoff_required: bool
    isolated_cache_required: bool
    isolated_config_required: bool

    def __post_init__(self) -> None:
        _require_safe_text(self.executable, "Launch executable")
        _reject_secret_material(self.executable, "Launch executable")
        _require_identifier(self.served_model_name, "Served model name")
        object.__setattr__(self, "arguments", tuple(self.arguments))
        for argument in self.arguments:
            _require_safe_text(argument, "Launch argument", allow_empty=True)
            _reject_secret_material(argument, "Launch argument")
        object.__setattr__(self, "environment", tuple(sorted(self.environment, key=lambda setting: setting.name)))
        _require_unique_values((setting.name for setting in self.environment), "Environment setting")

    def canonical_payload(self) -> dict[str, object]:
        return {
            "executable": self.executable,
            "served_model_name": self.served_model_name,
            "arguments": list(self.arguments),
            "environment": [setting.canonical_payload() for setting in self.environment],
            "loopback_only": self.loopback_only,
            "protected_auth_handoff_required": self.protected_auth_handoff_required,
            "isolated_cache_required": self.isolated_cache_required,
            "isolated_config_required": self.isolated_config_required,
        }


@dataclass(frozen=True, slots=True)
class SelfTestDescriptor:
    test_id: str
    deadline_seconds: float
    required_evidence: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_identifier(self.test_id, "Self-test ID")
        if (
            not isinstance(self.deadline_seconds, int | float)
            or isinstance(self.deadline_seconds, bool)
            or self.deadline_seconds <= 0
        ):
            raise ManifestError("Self-test deadline must be positive.")
        object.__setattr__(
            self,
            "required_evidence",
            tuple(sorted(_unique_identifiers(self.required_evidence, "Self-test evidence ID"))),
        )
        if not self.required_evidence:
            raise ManifestError("A self-test must declare the evidence it produces.")

    def canonical_payload(self) -> dict[str, object]:
        return {
            "test_id": self.test_id,
            "deadline_seconds": self.deadline_seconds,
            "required_evidence": list(self.required_evidence),
        }


@dataclass(frozen=True, slots=True)
class CapacityRequirements:
    """Measured cold-install and operation headroom.

    ``None`` means the requirement is still unmeasured.  Such a manifest or
    profile may remain in a draft catalog, but cannot be admitted.
    """

    min_gpu_count: int
    min_free_vram_bytes: int | None
    min_free_system_memory_bytes: int | None
    required_persistent_bytes: int | None

    def __post_init__(self) -> None:
        if not isinstance(self.min_gpu_count, int) or isinstance(self.min_gpu_count, bool) or self.min_gpu_count <= 0:
            raise ManifestError("Minimum GPU count must be a positive integer.")
        for label, value in (
            ("Minimum free VRAM", self.min_free_vram_bytes),
            ("Minimum free system memory", self.min_free_system_memory_bytes),
            ("Required persistent storage", self.required_persistent_bytes),
        ):
            if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value <= 0):
                raise ManifestError(f"{label} must be a positive integer or unmeasured.")

    @property
    def measured(self) -> bool:
        return (
            self.min_free_vram_bytes is not None
            and self.min_free_system_memory_bytes is not None
            and self.required_persistent_bytes is not None
        )

    def canonical_payload(self) -> dict[str, object]:
        return {
            "min_gpu_count": self.min_gpu_count,
            "min_free_vram_bytes": self.min_free_vram_bytes,
            "min_free_system_memory_bytes": self.min_free_system_memory_bytes,
            "required_persistent_bytes": self.required_persistent_bytes,
        }


@dataclass(frozen=True, slots=True)
class CompatibilityCell:
    """One exact target prerequisite cell, never a broad ROCm range."""

    cell_id: str
    os_name: str
    os_version: str
    kernel_version: str
    architecture: str
    gpu_architecture: str
    driver_version: str
    rocm_version: str
    hip_version: str
    python_version: str
    admission: ManifestAdmission
    admission_blockers: tuple[ManifestAdmissionBlocker, ...] = ()
    target_kind: CompatibilityTargetKind = CompatibilityTargetKind.NATIVE_LINUX

    def __post_init__(self) -> None:
        _require_identifier(self.cell_id, "Compatibility cell ID")
        _require_enum(self.admission, ManifestAdmission, "Compatibility cell admission")
        _require_enum(self.target_kind, CompatibilityTargetKind, "Compatibility target kind")
        _require_identifier(self.os_name, "Operating system name")
        for label, value in (
            ("Operating system version", self.os_version),
            ("Kernel version", self.kernel_version),
            ("Architecture", self.architecture),
            ("GPU architecture", self.gpu_architecture),
            ("Driver version", self.driver_version),
            ("ROCm version", self.rocm_version),
            ("HIP version", self.hip_version),
            ("Python version", self.python_version),
        ):
            _require_exact_reference(value, label)
        blockers = _unique_admission_blockers(self.admission_blockers)
        object.__setattr__(self, "admission_blockers", blockers)
        _validate_admission(self.admission, blockers, "Compatibility cell")

    def canonical_payload(self) -> dict[str, object]:
        return {
            "cell_id": self.cell_id,
            "os_name": self.os_name,
            "os_version": self.os_version,
            "kernel_version": self.kernel_version,
            "architecture": self.architecture,
            "gpu_architecture": self.gpu_architecture,
            "driver_version": self.driver_version,
            "rocm_version": self.rocm_version,
            "hip_version": self.hip_version,
            "python_version": self.python_version,
            "admission": self.admission.value,
            "admission_blockers": [blocker.value for blocker in self.admission_blockers],
            "target_kind": self.target_kind.value,
        }


@dataclass(frozen=True, slots=True)
class ComponentManifest:
    manifest_id: str
    manifest_version: str
    capability: ManifestCapability
    sources: tuple[ArtifactSource, ...]
    artifacts: tuple[ArtifactDescriptor, ...]
    models: tuple[ModelDescriptor, ...]
    runtime: RuntimeDescriptor
    protocol: ProtocolDescriptor
    launch: LaunchDescriptor
    self_tests: tuple[SelfTestDescriptor, ...]
    compatibility_cells: tuple[CompatibilityCell, ...]
    capacity: CapacityRequirements
    admission: ManifestAdmission
    admission_blockers: tuple[ManifestAdmissionBlocker, ...] = ()
    schema_version: int = MANIFEST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_schema_version(self.schema_version)
        _require_identifier(self.manifest_id, "Manifest ID")
        _require_exact_reference(self.manifest_version, "Manifest version")
        _require_enum(self.capability, ManifestCapability, "Manifest capability")
        _require_enum(self.admission, ManifestAdmission, "Manifest admission")

        object.__setattr__(self, "sources", tuple(sorted(self.sources, key=lambda source: source.source_id)))
        object.__setattr__(self, "artifacts", tuple(sorted(self.artifacts, key=lambda artifact: artifact.artifact_id)))
        object.__setattr__(self, "models", tuple(sorted(self.models, key=lambda model: model.model_id)))
        object.__setattr__(self, "self_tests", tuple(sorted(self.self_tests, key=lambda test: test.test_id)))
        object.__setattr__(
            self,
            "compatibility_cells",
            tuple(sorted(self.compatibility_cells, key=lambda cell: cell.cell_id)),
        )
        blockers = _unique_admission_blockers(self.admission_blockers)
        object.__setattr__(self, "admission_blockers", blockers)

        if not self.sources or not self.artifacts or not self.models:
            raise ManifestError("A component manifest requires source, artifact, and model descriptors.")
        if not self.self_tests or not self.compatibility_cells:
            raise ManifestError("A component manifest requires self-tests and compatibility cells.")

        source_ids = _require_unique_values((source.source_id for source in self.sources), "Source ID")
        artifact_ids = _require_unique_values((artifact.artifact_id for artifact in self.artifacts), "Artifact ID")
        _require_unique_values((model.model_id for model in self.models), "Model ID")
        _require_unique_values((test.test_id for test in self.self_tests), "Self-test ID")
        _require_unique_values((cell.cell_id for cell in self.compatibility_cells), "Compatibility cell ID")

        for artifact in self.artifacts:
            _require_reference(artifact.source_id, source_ids, "Artifact source")
        for model in self.models:
            for artifact_id in model.artifact_ids:
                _require_reference(artifact_id, artifact_ids, "Model artifact")
        for package in self.runtime.packages:
            _require_reference(package.artifact_id, artifact_ids, "Runtime package artifact")

        _validate_admission(self.admission, blockers, "Component manifest")
        if (
            any(not source.acquisition_verified for source in self.sources)
            and ManifestAdmissionBlocker.ACQUISITION_SOURCE_UNVERIFIED not in blockers
        ):
            raise ManifestError("Unverified acquisition sources require an explicit admission blocker.")
        if not self.capacity.measured and ManifestAdmissionBlocker.CAPACITY_UNMEASURED not in blockers:
            raise ManifestError("Unmeasured component capacity requires an explicit admission blocker.")
        if self.admission is ManifestAdmission.ADMITTED:
            if not all(source.acquisition_verified for source in self.sources):
                raise ManifestError("An admitted component manifest requires verified acquisition sources.")
            if not self.capacity.measured:
                raise ManifestError("An admitted component manifest requires measured capacity.")
            if not any(cell.admission is ManifestAdmission.ADMITTED for cell in self.compatibility_cells):
                raise ManifestError("An admitted component manifest requires an admitted compatibility cell.")
            if not (
                self.launch.loopback_only
                and self.launch.protected_auth_handoff_required
                and self.protocol.authentication_required
                and self.protocol.unauthenticated_request_rejected
            ):
                raise ManifestError("An admitted component must require authenticated loopback service access.")

    @property
    def manifest_digest(self) -> str:
        return _canonical_sha256(self.canonical_payload())

    def canonical_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "manifest_id": self.manifest_id,
            "manifest_version": self.manifest_version,
            "capability": self.capability.value,
            "sources": [source.canonical_payload() for source in self.sources],
            "artifacts": [artifact.canonical_payload() for artifact in self.artifacts],
            "models": [model.canonical_payload() for model in self.models],
            "runtime": self.runtime.canonical_payload(),
            "protocol": self.protocol.canonical_payload(),
            "launch": self.launch.canonical_payload(),
            "self_tests": [test.canonical_payload() for test in self.self_tests],
            "compatibility_cells": [cell.canonical_payload() for cell in self.compatibility_cells],
            "capacity": self.capacity.canonical_payload(),
            "admission": self.admission.value,
            "admission_blockers": [blocker.value for blocker in self.admission_blockers],
        }


@dataclass(frozen=True, slots=True)
class ComponentManifestRef:
    capability: ManifestCapability
    manifest_id: str
    manifest_digest: str

    def __post_init__(self) -> None:
        _require_enum(self.capability, ManifestCapability, "Manifest reference capability")
        _require_identifier(self.manifest_id, "Manifest reference ID")
        _require_sha256(self.manifest_digest, "Manifest reference SHA-256")

    def canonical_payload(self) -> dict[str, object]:
        return {
            "capability": self.capability.value,
            "manifest_id": self.manifest_id,
            "manifest_digest": self.manifest_digest,
        }


@dataclass(frozen=True, slots=True)
class ExecutionProfileManifest:
    profile_id: str
    profile_version: str
    compatibility_cell_id: str
    components: tuple[ComponentManifestRef, ...]
    capacity: CapacityRequirements
    admission: ManifestAdmission
    admission_blockers: tuple[ManifestAdmissionBlocker, ...] = ()
    schema_version: int = MANIFEST_SCHEMA_VERSION
    placement: ExecutionProfilePlacement = ExecutionProfilePlacement.LEGACY

    def __post_init__(self) -> None:
        _require_schema_version(self.schema_version)
        _require_identifier(self.profile_id, "Profile ID")
        _require_exact_reference(self.profile_version, "Profile version")
        _require_identifier(self.compatibility_cell_id, "Profile compatibility cell ID")
        _require_enum(self.admission, ManifestAdmission, "Execution profile admission")
        _require_enum(self.placement, ExecutionProfilePlacement, "Execution profile placement")
        object.__setattr__(
            self,
            "components",
            tuple(sorted(self.components, key=lambda reference: reference.capability.value)),
        )
        if not self.components:
            raise ManifestError("An execution profile must reference at least one component.")
        _require_unique_values((reference.capability.value for reference in self.components), "Profile capability")
        blockers = _unique_admission_blockers(self.admission_blockers)
        object.__setattr__(self, "admission_blockers", blockers)
        _validate_admission(self.admission, blockers, "Execution profile")
        if not self.capacity.measured and ManifestAdmissionBlocker.CAPACITY_UNMEASURED not in blockers:
            raise ManifestError("Unmeasured profile capacity requires an explicit admission blocker.")
        if self.admission is ManifestAdmission.ADMITTED and not self.capacity.measured:
            raise ManifestError("An admitted execution profile requires measured coexistence capacity.")

    @property
    def manifest_digest(self) -> str:
        return _canonical_sha256(self.canonical_payload())

    def canonical_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "compatibility_cell_id": self.compatibility_cell_id,
            "components": [reference.canonical_payload() for reference in self.components],
            "capacity": self.capacity.canonical_payload(),
            "admission": self.admission.value,
            "admission_blockers": [blocker.value for blocker in self.admission_blockers],
            "placement": self.placement.value,
        }


@dataclass(frozen=True, slots=True)
class ManifestCatalog:
    """Read-only exact-digest catalog; construction validates every profile edge."""

    components: tuple[ComponentManifest, ...] = ()
    profiles: tuple[ExecutionProfileManifest, ...] = ()
    _components_by_digest: Mapping[str, ComponentManifest] = field(init=False, repr=False, compare=False)
    _profiles_by_digest: Mapping[str, ExecutionProfileManifest] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        components = tuple(self.components)
        profiles = tuple(self.profiles)
        object.__setattr__(self, "components", components)
        object.__setattr__(self, "profiles", profiles)

        component_by_digest: dict[str, ComponentManifest] = {}
        component_by_identity: dict[tuple[str, str], str] = {}
        for component in components:
            digest = component.manifest_digest
            if digest in component_by_digest:
                raise ManifestConflictError(f"Duplicate component manifest digest: {digest}")
            identity = (component.manifest_id, component.manifest_version)
            previous_digest = component_by_identity.get(identity)
            if previous_digest is not None and previous_digest != digest:
                raise ManifestConflictError("One component manifest identity resolves to different technical content.")
            component_by_digest[digest] = component
            component_by_identity[identity] = digest

        profile_by_digest: dict[str, ExecutionProfileManifest] = {}
        profile_by_identity: dict[tuple[str, str], str] = {}
        for profile in profiles:
            digest = profile.manifest_digest
            if digest in profile_by_digest:
                raise ManifestConflictError(f"Duplicate execution profile digest: {digest}")
            identity = (profile.profile_id, profile.profile_version)
            previous_digest = profile_by_identity.get(identity)
            if previous_digest is not None and previous_digest != digest:
                raise ManifestConflictError("One execution profile identity resolves to different technical content.")
            _validate_profile_references(profile, component_by_digest)
            profile_by_digest[digest] = profile
            profile_by_identity[identity] = digest

        object.__setattr__(self, "_components_by_digest", MappingProxyType(component_by_digest))
        object.__setattr__(self, "_profiles_by_digest", MappingProxyType(profile_by_digest))

    @classmethod
    def from_iterables(
        cls,
        components: Iterable[ComponentManifest],
        profiles: Iterable[ExecutionProfileManifest] = (),
    ) -> ManifestCatalog:
        return cls(components=tuple(components), profiles=tuple(profiles))

    @property
    def catalog_digest(self) -> str:
        return _canonical_sha256(
            {
                "schema_version": MANIFEST_SCHEMA_VERSION,
                "component_digests": sorted(self._components_by_digest),
                "profile_digests": sorted(self._profiles_by_digest),
            }
        )

    def component(self, manifest_digest: str) -> ComponentManifest:
        _require_sha256(manifest_digest, "Component manifest SHA-256")
        try:
            return self._components_by_digest[manifest_digest]
        except KeyError as error:
            raise ManifestNotFoundError("Component manifest is not present in the catalog.") from error

    def profile(self, manifest_digest: str) -> ExecutionProfileManifest:
        _require_sha256(manifest_digest, "Profile manifest SHA-256")
        try:
            return self._profiles_by_digest[manifest_digest]
        except KeyError as error:
            raise ManifestNotFoundError("Execution profile is not present in the catalog.") from error

    def profile_components(self, profile: ExecutionProfileManifest) -> tuple[ComponentManifest, ...]:
        return tuple(self.component(reference.manifest_digest) for reference in profile.components)


def _validate_profile_references(
    profile: ExecutionProfileManifest,
    components_by_digest: Mapping[str, ComponentManifest],
) -> None:
    expected_cell_payload: dict[str, object] | None = None
    expected_target_kind: CompatibilityTargetKind | None = None
    components: list[ComponentManifest] = []
    for reference in profile.components:
        component = components_by_digest.get(reference.manifest_digest)
        if component is None:
            raise ManifestNotFoundError("Execution profile references an absent component manifest.")
        if component.manifest_id != reference.manifest_id or component.capability is not reference.capability:
            raise ManifestConflictError("Execution profile component reference does not match its manifest.")
        matching_cell = next(
            (cell for cell in component.compatibility_cells if cell.cell_id == profile.compatibility_cell_id),
            None,
        )
        if matching_cell is None:
            raise ManifestConflictError("Execution profile cell is absent from a referenced component manifest.")
        cell_payload = matching_cell.canonical_payload()
        if expected_cell_payload is None:
            expected_cell_payload = cell_payload
            expected_target_kind = matching_cell.target_kind
        elif cell_payload != expected_cell_payload:
            raise ManifestConflictError("Execution profile components disagree on the exact compatibility cell.")
        if profile.admission is ManifestAdmission.ADMITTED and (
            component.admission is not ManifestAdmission.ADMITTED
            or matching_cell.admission is not ManifestAdmission.ADMITTED
        ):
            raise ManifestConflictError("An admitted execution profile references unadmitted component content.")
        components.append(component)

    required_target_kind = {
        ExecutionProfilePlacement.PRIVATE_SSH: CompatibilityTargetKind.NATIVE_LINUX,
        ExecutionProfilePlacement.LOCAL_WSL: CompatibilityTargetKind.WSL2,
    }.get(profile.placement)
    if required_target_kind is not None and expected_target_kind is not required_target_kind:
        raise ManifestConflictError(
            "Execution profile placement does not match its compatibility target kind."
        )

    if profile.admission is ManifestAdmission.ADMITTED:
        _validate_profile_capacity(profile.capacity, tuple(component.capacity for component in components))


def _canonical_sha256(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_admission(
    admission: ManifestAdmission,
    blockers: tuple[ManifestAdmissionBlocker, ...],
    label: str,
) -> None:
    if admission is ManifestAdmission.ADMITTED and blockers:
        raise ManifestError(f"{label} cannot be admitted with unresolved blockers.")
    if admission is ManifestAdmission.DRAFT and not blockers:
        raise ManifestError(f"{label} draft must state at least one typed admission blocker.")


def _require_schema_version(value: int) -> None:
    if value != MANIFEST_SCHEMA_VERSION:
        raise ManifestError(f"Unsupported manifest schema version: {value!r}")


def _require_identifier(value: str, label: str) -> None:
    if not isinstance(value, str) or not _IDENTIFIER_PATTERN.fullmatch(value):
        raise ManifestError(f"{label} is invalid.")


def _require_safe_text(
    value: str,
    label: str,
    *,
    maximum: int = 512,
    allow_empty: bool = False,
) -> None:
    if (
        not isinstance(value, str)
        or (not allow_empty and not value)
        or len(value) > maximum
        or value != value.strip()
        or any(ord(character) < 0x20 or ord(character) == 0x7F for character in value)
    ):
        raise ManifestError(f"{label} is invalid.")


def _require_exact_reference(value: str | None, label: str) -> None:
    if value is None:
        raise ManifestError(f"{label} is required.")
    _require_safe_text(value, label)
    if any(marker in value for marker in ("*", "?", ",", ">=", "<=", "~=", "^")):
        raise ManifestError(f"{label} must be an exact immutable reference.")
    if value.casefold() in {"head", "latest", "main", "master"}:
        raise ManifestError(f"{label} must not use a mutable alias.")


def _require_sha256(value: str, label: str) -> None:
    if not isinstance(value, str) or not _SHA256_PATTERN.fullmatch(value):
        raise ManifestError(f"{label} must be lowercase SHA-256.")


def _require_relative_path(value: str, label: str) -> None:
    _require_safe_text(value, label, maximum=1_024)
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or value.endswith("/"):
        raise ManifestError(f"{label} must be a bounded relative POSIX path.")


def _reject_secret_material(value: str, label: str) -> None:
    if _SENSITIVE_PATTERN.search(value):
        raise ManifestError(f"{label} must not contain credential or secret material.")


def _require_enum(value: object, enum_type: type[StrEnum], label: str) -> None:
    if not isinstance(value, enum_type):
        raise ManifestError(f"{label} is invalid.")


def _unique_identifiers(values: Iterable[str], label: str) -> tuple[str, ...]:
    materialized = tuple(values)
    for value in materialized:
        _require_identifier(value, label)
    _require_unique_values(materialized, label)
    return materialized


def _unique_admission_blockers(
    values: Iterable[ManifestAdmissionBlocker],
) -> tuple[ManifestAdmissionBlocker, ...]:
    materialized = tuple(values)
    for value in materialized:
        _require_enum(value, ManifestAdmissionBlocker, "Admission blocker")
    _require_unique_values((value.value for value in materialized), "Admission blocker")
    return tuple(sorted(materialized, key=lambda value: value.value))


def _require_unique_values(values: Iterable[str], label: str) -> set[str]:
    materialized = tuple(values)
    unique = set(materialized)
    if len(unique) != len(materialized):
        raise ManifestError(f"{label} values must be unique.")
    return unique


def _require_reference(value: str, available: set[str], label: str) -> None:
    if value not in available:
        raise ManifestError(f"{label} references absent immutable content.")


def _validate_profile_capacity(
    profile_capacity: CapacityRequirements,
    component_capacities: tuple[CapacityRequirements, ...],
) -> None:
    for label, profile_value, component_values in (
        (
            "GPU count",
            profile_capacity.min_gpu_count,
            tuple(capacity.min_gpu_count for capacity in component_capacities),
        ),
        (
            "Free VRAM",
            profile_capacity.min_free_vram_bytes,
            tuple(capacity.min_free_vram_bytes for capacity in component_capacities),
        ),
        (
            "Free system memory",
            profile_capacity.min_free_system_memory_bytes,
            tuple(capacity.min_free_system_memory_bytes for capacity in component_capacities),
        ),
        (
            "Persistent storage",
            profile_capacity.required_persistent_bytes,
            tuple(capacity.required_persistent_bytes for capacity in component_capacities),
        ),
    ):
        measured_components = tuple(value for value in component_values if value is not None)
        if profile_value is None or not measured_components or profile_value < max(measured_components):
            raise ManifestConflictError(
                f"Admitted profile {label} requirement cannot be below a component requirement."
            )


__all__ = [
    "ArtifactDescriptor",
    "ArtifactKind",
    "ArtifactSource",
    "CapacityRequirements",
    "CompatibilityCell",
    "CompatibilityTargetKind",
    "ComponentManifest",
    "ComponentManifestRef",
    "EnvironmentSetting",
    "ExecutionProfilePlacement",
    "ExecutionProfileManifest",
    "LaunchDescriptor",
    "MANIFEST_SCHEMA_VERSION",
    "ManifestAdmission",
    "ManifestAdmissionBlocker",
    "ManifestCapability",
    "ManifestCatalog",
    "ManifestConflictError",
    "ManifestError",
    "ManifestNotFoundError",
    "ModelDescriptor",
    "ProtocolDescriptor",
    "ProtocolFieldDisposition",
    "ProtocolFieldRule",
    "RuntimeDescriptor",
    "RuntimePackage",
    "SelfTestDescriptor",
    "SourceKind",
]
