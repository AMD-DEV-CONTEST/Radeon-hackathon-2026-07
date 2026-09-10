"""Independent, content-addressed Preview adapter supply capability."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass, field, replace
from typing import Literal

from specstyle.domain.identifiers import Sha256
from specstyle.errors import DomainError, InfrastructureError
from specstyle.generation.model_approval import LicenseApproval
from specstyle.generation.model_registry import ModelDescriptor, ModelRegistry
from specstyle.generation.weight_manifest import (
    WeightFile,
    _close_fd_quietly,
    _listed_files,
    _open_directory,
    _OwnedFd,
    _read_and_hash,
    _relative_path,
    _validate_root_fd,
)

PreviewAdapterKind = Literal["diffusers_lora"]
_REVISION = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")
_CAPABILITY_SEAL = object()


@dataclass(frozen=True, slots=True)
class PreviewAdapterEntrypoint:
    kind: PreviewAdapterKind
    subfolder: str
    weight_name: str

    def __post_init__(self) -> None:
        if self.kind != "diffusers_lora":
            raise DomainError("invalid preview adapter entrypoint")
        _relative_path(self.subfolder, field="preview adapter subfolder")
        _relative_path(self.weight_name, field="preview adapter weight name")


@dataclass(frozen=True, slots=True)
class PreviewAdapterManifest:
    model_id: str
    role: str
    revision: str
    relative_root: str
    entrypoint: PreviewAdapterEntrypoint
    files: tuple[WeightFile, ...]
    root_sha256: Sha256
    schema_version: str = "specstyle.preview-adapter-manifest.v1"

    def __post_init__(self) -> None:
        if self.schema_version != "specstyle.preview-adapter-manifest.v1":
            raise DomainError("invalid preview adapter manifest schema")
        if type(self.model_id) is not str or not self.model_id:
            raise DomainError("invalid preview adapter model")
        if self.role != "preview_adapter":
            raise DomainError("invalid preview adapter role")
        if type(self.revision) is not str or _REVISION.fullmatch(self.revision) is None:
            raise DomainError("invalid preview adapter revision")
        _relative_path(self.relative_root, field="preview adapter root")
        if type(self.entrypoint) is not PreviewAdapterEntrypoint:
            raise DomainError("invalid preview adapter entrypoint")
        self._validate_files()
        if type(self.root_sha256) is not Sha256:
            raise DomainError("invalid preview adapter root digest")

    def _validate_files(self) -> None:
        if type(self.files) is not tuple or not self.files:
            raise DomainError("invalid preview adapter files")
        if any(type(item) is not WeightFile for item in self.files):
            raise DomainError("invalid preview adapter files")
        paths = [item.relative_path for item in self.files]
        if paths != sorted(paths) or len(paths) != len(set(paths)):
            raise DomainError("preview adapter files must be uniquely sorted")
        if any(not path.endswith((".json", ".safetensors")) for path in paths):
            raise DomainError("preview adapter file format refused")
        weight_path = f"{self.entrypoint.subfolder}/{self.entrypoint.weight_name}"
        if not weight_path.endswith(".safetensors") or weight_path not in paths:
            raise DomainError("preview adapter weight must reference safetensors")

    def with_computed_root(self) -> PreviewAdapterManifest:
        return replace(self, root_sha256=preview_adapter_manifest_root_sha256(self))


def _manifest_payload(manifest: PreviewAdapterManifest, *, include_root: bool) -> bytes:
    payload: dict[str, object] = {
        "schema_version": manifest.schema_version,
        "model_id": manifest.model_id,
        "role": manifest.role,
        "revision": manifest.revision,
        "relative_root": manifest.relative_root,
        "entrypoint": {
            "kind": manifest.entrypoint.kind,
            "subfolder": manifest.entrypoint.subfolder,
            "weight_name": manifest.entrypoint.weight_name,
        },
        "files": [
            {
                "relative_path": item.relative_path,
                "size_bytes": item.size_bytes,
                "sha256": item.sha256.value,
            }
            for item in manifest.files
        ],
    }
    if include_root:
        payload["root_sha256"] = manifest.root_sha256.value
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def preview_adapter_manifest_root_sha256(manifest: PreviewAdapterManifest) -> Sha256:
    if type(manifest) is not PreviewAdapterManifest:
        raise DomainError("invalid preview adapter manifest")
    return Sha256(
        hashlib.sha256(_manifest_payload(manifest, include_root=False)).hexdigest()
    )


def preview_adapter_manifest_sha256(manifest: PreviewAdapterManifest) -> Sha256:
    if type(manifest) is not PreviewAdapterManifest:
        raise DomainError("invalid preview adapter manifest")
    return Sha256(
        hashlib.sha256(_manifest_payload(manifest, include_root=True)).hexdigest()
    )


@dataclass(frozen=True, slots=True, init=False)
class VerifiedPreviewAdapter:
    descriptor: ModelDescriptor
    manifest: PreviewAdapterManifest
    approval: LicenseApproval
    _fd: int = field(repr=False, compare=False)
    _identity: tuple[int, int] = field(repr=False, compare=False)
    _seal: object = field(repr=False, compare=False)

    def __init__(self, *_: object, **__: object) -> None:
        raise TypeError("verified preview adapters are issued only by verification")

    def borrow_loader_path(self) -> str:
        _validate_verified_preview_adapter(self, require_open=True, check_fd=True)
        return f"/proc/self/fd/{self._fd}"

    def close(self) -> None:
        _validate_verified_preview_adapter(self, require_open=False, check_fd=False)
        fd = self._fd
        if fd < 0:
            return
        try:
            fd_stat = os.fstat(fd)
            if (fd_stat.st_dev, fd_stat.st_ino) != self._identity:
                raise InfrastructureError(
                    "verified preview adapter fd identity changed"
                )
            os.close(fd)
        except OSError as exc:
            raise InfrastructureError("verified preview adapter close failed") from exc
        finally:
            object.__setattr__(self, "_fd", -1)

    def __copy__(self) -> VerifiedPreviewAdapter:
        raise TypeError("verified preview adapters cannot be copied")

    def __deepcopy__(self, _memo: dict[int, object]) -> VerifiedPreviewAdapter:
        raise TypeError("verified preview adapters cannot be copied")

    def __reduce_ex__(self, _protocol: int) -> object:
        raise TypeError("verified preview adapters cannot be serialized")


def _validate_verified_preview_adapter(
    adapter: object, *, require_open: bool, check_fd: bool
) -> None:
    if (
        type(adapter) is not VerifiedPreviewAdapter
        or getattr(adapter, "_seal", None) is not _CAPABILITY_SEAL
        or type(getattr(adapter, "descriptor", None)) is not ModelDescriptor
        or type(getattr(adapter, "manifest", None)) is not PreviewAdapterManifest
        or type(getattr(adapter, "approval", None)) is not LicenseApproval
        or type(getattr(adapter, "_fd", None)) is not int
        or type(getattr(adapter, "_identity", None)) is not tuple
    ):
        raise DomainError("invalid verified preview adapter capability")
    descriptor = adapter.descriptor
    manifest = adapter.manifest
    approval = adapter.approval
    if not _closed_loop_matches(descriptor, manifest, approval):
        raise DomainError("invalid verified preview adapter capability")
    if adapter._fd == -1:
        if require_open:
            raise DomainError("verified preview adapter is closed")
        return
    if adapter._fd < 0 or len(adapter._identity) != 2:
        raise DomainError("invalid verified preview adapter capability")
    if check_fd:
        _validate_capability_fd(adapter._fd, adapter._identity)


def _validate_capability_fd(fd: int, identity: tuple[int, int]) -> None:
    try:
        fd_stat = os.fstat(fd)
    except OSError as exc:
        raise DomainError("verified preview adapter is closed") from exc
    if (
        not stat.S_ISDIR(fd_stat.st_mode)
        or (fd_stat.st_dev, fd_stat.st_ino) != identity
    ):
        raise DomainError("invalid verified preview adapter capability")


def _closed_loop_matches(
    descriptor: ModelDescriptor,
    manifest: PreviewAdapterManifest,
    approval: LicenseApproval,
) -> bool:
    return (
        descriptor.role == "preview_adapter"
        and descriptor.model_id == manifest.model_id == approval.model_id
        and descriptor.revision == manifest.revision == approval.revision
        and descriptor.expected_sha256 == manifest.root_sha256
        and descriptor.license_spdx == approval.license_spdx
        and approval.manifest_sha256 == preview_adapter_manifest_sha256(manifest)
    )


def _verify_component(root_fd: int, manifest: PreviewAdapterManifest) -> int:
    _validate_root_fd(root_fd)
    if preview_adapter_manifest_root_sha256(manifest) != manifest.root_sha256:
        raise DomainError("preview adapter manifest root digest mismatch")
    with _OwnedFd(_open_directory(root_fd, manifest.relative_root)) as component:
        expected = {item.relative_path for item in manifest.files}
        if _listed_files(component.fd) != expected:
            raise InfrastructureError("preview adapter files do not match manifest")
        for item in manifest.files:
            _read_and_hash(component.fd, item)
        return component.release()


def _issue_verified_preview_adapter(
    descriptor: ModelDescriptor,
    manifest: PreviewAdapterManifest,
    approval: LicenseApproval,
    component_fd: int,
) -> VerifiedPreviewAdapter:
    try:
        component_stat = os.fstat(component_fd)
    except OSError as exc:
        raise InfrastructureError("preview adapter component unavailable") from exc
    issued = object.__new__(VerifiedPreviewAdapter)
    object.__setattr__(issued, "descriptor", descriptor)
    object.__setattr__(issued, "manifest", manifest)
    object.__setattr__(issued, "approval", approval)
    object.__setattr__(issued, "_fd", component_fd)
    object.__setattr__(
        issued, "_identity", (component_stat.st_dev, component_stat.st_ino)
    )
    object.__setattr__(issued, "_seal", _CAPABILITY_SEAL)
    _validate_verified_preview_adapter(issued, require_open=True, check_fd=True)
    return issued


def verify_preview_adapter(
    root_fd: int,
    descriptor: ModelDescriptor,
    manifest: PreviewAdapterManifest,
    approval: LicenseApproval,
) -> VerifiedPreviewAdapter:
    """Verify and retain one Preview-only adapter directory."""
    if (
        type(descriptor) is not ModelDescriptor
        or type(manifest) is not PreviewAdapterManifest
        or type(approval) is not LicenseApproval
    ):
        raise DomainError("invalid preview adapter supply")
    ModelRegistry((descriptor,)).require_production(descriptor.model_id)
    if not _closed_loop_matches(descriptor, manifest, approval):
        raise DomainError("preview adapter supply closed-loop mismatch")
    component_fd = _verify_component(root_fd, manifest)
    try:
        return _issue_verified_preview_adapter(
            descriptor, manifest, approval, component_fd
        )
    except Exception:
        _close_fd_quietly(component_fd)
        raise
