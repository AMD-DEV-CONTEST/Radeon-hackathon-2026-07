"""Strict manifest contract for separately managed local model packages."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


PACKAGE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,95}$")
VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[a-z0-9.-]+)?$")
TOKEN_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SUPPORTED_MODALITIES = {"text", "image", "audio", "video"}
SUPPORTED_PLATFORMS = {"windows", "linux", "macos"}
SUPPORTED_ARCHITECTURES = {"x86_64", "arm64"}


def safe_relative_path(value: str, *, label: str = "path") -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ValueError(f"{label} must be a non-empty POSIX relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"{label} must stay inside the package root")
    return path.as_posix()


class PackageFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str
    download_path: str
    size: int = Field(gt=0)
    sha256: str
    role: str = Field(pattern=r"^[a-z][a-z0-9._-]{0,63}$")

    @field_validator("path", "download_path")
    @classmethod
    def validate_path(cls, value: str, info):
        return safe_relative_path(value, label=info.field_name)

    @field_validator("sha256")
    @classmethod
    def validate_sha256(cls, value: str):
        if SHA256_RE.fullmatch(value) is None:
            raise ValueError("sha256 must be 64 lowercase hexadecimal characters")
        return value


class PackageLicense(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    license_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9+._-]{0,63}$")
    display_name: str = Field(min_length=1, max_length=128)
    url: str
    redistribution_allowed: bool
    requires_acceptance: bool = True
    notice_path: str | None = None

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str):
        parsed = urlparse(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.fragment
        ):
            raise ValueError("license URL must be a credential-free HTTPS URL")
        return value

    @field_validator("notice_path")
    @classmethod
    def validate_notice_path(cls, value: str | None):
        return safe_relative_path(value, label="notice_path") if value else None


class PackageSource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["trusted_https", "offline_only"]
    base_url: str | None = None
    trusted_redirect_hosts: tuple[str, ...] = ()
    revision: str | None = Field(default=None, max_length=128)

    @field_validator("trusted_redirect_hosts")
    @classmethod
    def validate_hosts(cls, values: tuple[str, ...]):
        normalized = []
        for value in values:
            host = value.strip().lower()
            plain = host[1:] if host.startswith(".") else host
            if (
                not plain
                or "/" in plain
                or ":" in plain
                or plain == "localhost"
                or plain.endswith(".local")
            ):
                raise ValueError("trusted redirect host is invalid")
            if host not in normalized:
                normalized.append(host)
        return tuple(normalized)

    @model_validator(mode="after")
    def validate_source(self):
        if self.kind == "offline_only":
            if self.base_url is not None or self.trusted_redirect_hosts:
                raise ValueError("offline-only sources cannot define network locations")
            return self
        parsed = urlparse(self.base_url or "")
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or not (self.base_url or "").endswith("/")
        ):
            raise ValueError("trusted source base_url must be a credential-free HTTPS directory")
        host = parsed.hostname.lower()
        if not any(
            host == allowed or (allowed.startswith(".") and host.endswith(allowed))
            for allowed in self.trusted_redirect_hosts
        ):
            raise ValueError("source host must be included in trusted_redirect_hosts")
        return self


class ResourceProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    minimum_ram_mb: int | None = Field(default=None, ge=0)
    recommended_ram_mb: int | None = Field(default=None, ge=0)
    minimum_vram_mb: int | None = Field(default=None, ge=0)
    recommended_vram_mb: int | None = Field(default=None, ge=0)
    evidence_level: Literal["estimated", "vendor", "verified"] = "estimated"

    @model_validator(mode="after")
    def validate_ranges(self):
        for minimum, recommended in (
            (self.minimum_ram_mb, self.recommended_ram_mb),
            (self.minimum_vram_mb, self.recommended_vram_mb),
        ):
            if minimum is not None and recommended is not None and recommended < minimum:
                raise ValueError("recommended resources cannot be below minimum resources")
        return self


class EmbeddingContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    dimension: int = Field(gt=0)
    normalization: Literal["l2", "none"]
    vector_schema_version: int = Field(gt=0)
    vector_space_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,95}$")


class PackageRuntimePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    residency_mode: Literal["PINNED", "PREFERRED", "ON_DEMAND"]
    default_lease_mode: Literal["EXCLUSIVE", "SHARED"]
    shared_gpu_eligible: bool = False
    idle_unload_seconds: int = Field(default=300, ge=30, le=86_400)

    @model_validator(mode="after")
    def validate_shared_mode(self):
        if self.default_lease_mode == "SHARED" and not self.shared_gpu_eligible:
            raise ValueError("SHARED lease mode requires shared_gpu_eligible")
        return self


class ModelPackageManifest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        protected_namespaces=(),
    )

    schema_version: Literal[1]
    package_id: str
    package_version: str
    display_name: str = Field(min_length=1, max_length=160)
    package_kind: str = Field(pattern=r"^[a-z][a-z0-9._-]{1,63}$")
    core_required: bool = False
    model_profile_id: str | None = Field(default=None, max_length=128)
    model_family: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")
    modalities: tuple[str, ...]
    capabilities: tuple[str, ...]
    runtime_adapter: str = Field(pattern=r"^[a-z][a-z0-9._-]{1,95}$")
    supported_platforms: tuple[str, ...]
    supported_architectures: tuple[str, ...]
    supported_backends: tuple[str, ...]
    install_subdir: str
    install_size_bytes: int = Field(gt=0)
    model_size_bytes: int = Field(gt=0)
    resource_profile: ResourceProfile
    embedding: EmbeddingContract | None = None
    residency_policy_default: Literal["always", "idle_unload", "exclusive", "shared"]
    runtime_policy: PackageRuntimePolicy | None = None
    offload_capabilities: tuple[str, ...] = ()
    license: PackageLicense
    source: PackageSource
    files: tuple[PackageFile, ...]

    @field_validator("package_id")
    @classmethod
    def validate_package_id(cls, value: str):
        if PACKAGE_ID_RE.fullmatch(value) is None:
            raise ValueError("invalid package_id")
        return value

    @field_validator("package_version")
    @classmethod
    def validate_version(cls, value: str):
        if VERSION_RE.fullmatch(value) is None:
            raise ValueError("invalid package_version")
        return value

    @field_validator("install_subdir")
    @classmethod
    def validate_install_subdir(cls, value: str):
        return safe_relative_path(value, label="install_subdir")

    @field_validator(
        "modalities",
        "capabilities",
        "supported_platforms",
        "supported_architectures",
        "supported_backends",
        "offload_capabilities",
    )
    @classmethod
    def validate_tokens(cls, values: tuple[str, ...], info):
        if info.field_name != "offload_capabilities" and not values:
            raise ValueError(f"{info.field_name} cannot be empty")
        if len(values) != len(set(values)):
            raise ValueError(f"{info.field_name} cannot contain duplicates")
        if any(TOKEN_RE.fullmatch(value) is None for value in values):
            raise ValueError(f"{info.field_name} contains an invalid token")
        if info.field_name == "modalities" and not set(values) <= SUPPORTED_MODALITIES:
            raise ValueError("unsupported modality")
        if info.field_name == "supported_platforms" and not set(values) <= SUPPORTED_PLATFORMS:
            raise ValueError("unsupported platform")
        if (
            info.field_name == "supported_architectures"
            and not set(values) <= SUPPORTED_ARCHITECTURES
        ):
            raise ValueError("unsupported architecture")
        return values

    @model_validator(mode="after")
    def validate_manifest(self):
        if not self.files or len({item.path for item in self.files}) != len(self.files):
            raise ValueError("package files must be present and unique")
        if sum(item.size for item in self.files) != self.install_size_bytes:
            raise ValueError("install_size_bytes must equal the declared file sizes")
        if self.model_size_bytes > self.install_size_bytes:
            raise ValueError("model_size_bytes cannot exceed install_size_bytes")
        if self.license.notice_path and self.license.notice_path not in {
            item.path for item in self.files
        }:
            raise ValueError("license notice must be a declared package file")
        if self.embedding is not None and "embedding" not in self.capabilities:
            raise ValueError("embedding contract requires the embedding capability")
        if self.embedding is not None and "text" not in self.modalities:
            raise ValueError("current embedding contract requires text modality")
        if self.runtime_policy is not None:
            if (
                self.runtime_policy.default_lease_mode == "SHARED"
                and self.resource_profile.recommended_vram_mb in (None, 0)
            ):
                raise ValueError("SHARED GPU policy requires a VRAM resource declaration")
        return self

    def digest(self) -> str:
        payload = json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def public_dict(self) -> dict:
        payload = self.model_dump(mode="json")
        payload["manifest_digest"] = self.digest()
        return payload


def load_package_manifest(path: Path) -> ModelPackageManifest:
    return ModelPackageManifest.model_validate_json(path.read_text(encoding="utf-8"))
