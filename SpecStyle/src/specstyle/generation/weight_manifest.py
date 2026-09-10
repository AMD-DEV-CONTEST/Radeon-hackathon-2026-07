"""Immutable, content-addressed manifests for local model supplies."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass, replace
from typing import Literal

from specstyle.domain.identifiers import Sha256
from specstyle.errors import DomainError, InfrastructureError

ManifestRole = Literal["base", "ip_adapter", "controlnet"]
EntrypointKind = Literal["diffusers_pretrained", "diffusers_ip_adapter"]
_REVISION = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")


def _relative_path(value: object, *, field: str) -> str:
    if type(value) is not str or not value or value.startswith("/") or "\\" in value:
        raise DomainError(f"invalid {field}")
    parts = value.split("/")
    if (
        len(value.encode("utf-8")) > 4096
        or any(len(part.encode("utf-8")) > 255 for part in parts)
        or any(part in ("", ".", "..") for part in parts)
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise DomainError(f"invalid {field}")
    return value


@dataclass(frozen=True, slots=True)
class WeightFile:
    relative_path: str
    size_bytes: int
    sha256: Sha256

    def __post_init__(self) -> None:
        _relative_path(self.relative_path, field="weight path")
        if type(self.size_bytes) is not int or self.size_bytes < 0:
            raise DomainError("invalid weight size")
        if type(self.sha256) is not Sha256:
            raise DomainError("invalid weight sha")


@dataclass(frozen=True, slots=True)
class ModelLoadEntrypoint:
    kind: EntrypointKind
    subfolder: str
    weight_name: str | None = None
    image_encoder_folder: str | None = None
    variant: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in ("diffusers_pretrained", "diffusers_ip_adapter"):
            raise DomainError("invalid model entrypoint")
        _relative_path(self.subfolder, field="entrypoint subfolder")
        for value, field in (
            (self.weight_name, "entrypoint weight name"),
            (self.image_encoder_folder, "entrypoint image encoder folder"),
            (self.variant, "entrypoint variant"),
        ):
            if value is not None and (type(value) is not str or not value):
                raise DomainError(f"invalid {field}")
        if self.weight_name is not None:
            _relative_path(self.weight_name, field="entrypoint weight name")
        if self.image_encoder_folder is not None:
            _relative_path(
                self.image_encoder_folder, field="entrypoint image encoder folder"
            )
        if self.kind == "diffusers_ip_adapter" and self.weight_name is None:
            raise DomainError("ip adapter entrypoint requires weight name")


def effective_image_encoder_subfolder(entrypoint: ModelLoadEntrypoint, /) -> str:
    if type(entrypoint) is not ModelLoadEntrypoint:
        raise DomainError("invalid model entrypoint")
    folder = entrypoint.image_encoder_folder or "image_encoder"
    return folder if "/" in folder else f"{entrypoint.subfolder}/{folder}"


@dataclass(frozen=True, slots=True)
class WeightManifest:
    model_id: str
    role: ManifestRole
    revision: str
    relative_root: str
    entrypoint: ModelLoadEntrypoint
    files: tuple[WeightFile, ...]
    root_sha256: Sha256
    schema_version: str = "specstyle.weight-manifest.v1"

    def __post_init__(self) -> None:
        if self.schema_version != "specstyle.weight-manifest.v1":
            raise DomainError("invalid weight manifest schema")
        if type(self.model_id) is not str or not self.model_id:
            raise DomainError("invalid weight manifest model")
        if self.role not in ("base", "ip_adapter", "controlnet"):
            raise DomainError("invalid weight manifest role")
        if type(self.revision) is not str or _REVISION.fullmatch(self.revision) is None:
            raise DomainError("invalid weight manifest revision")
        _relative_path(self.relative_root, field="weight manifest root")
        if type(self.entrypoint) is not ModelLoadEntrypoint:
            raise DomainError("invalid weight manifest entrypoint")
        if type(self.files) is not tuple or not self.files:
            raise DomainError("invalid weight manifest files")
        paths: set[str] = set()
        for item in self.files:
            if type(item) is not WeightFile or item.relative_path in paths:
                raise DomainError("invalid weight manifest files")
            paths.add(item.relative_path)
        expected_kind = (
            "diffusers_ip_adapter"
            if self.role == "ip_adapter"
            else "diffusers_pretrained"
        )
        if self.entrypoint.kind != expected_kind:
            raise DomainError("invalid role entrypoint")
        safetensor_paths = {
            item.relative_path
            for item in self.files
            if item.relative_path.endswith(".safetensors")
        }
        if not safetensor_paths:
            raise DomainError("weight manifest requires safetensors")
        entrypoint_safetensors = {
            path
            for path in safetensor_paths
            if path.startswith(f"{self.entrypoint.subfolder}/")
        }
        if not entrypoint_safetensors:
            raise DomainError("weight manifest entrypoint requires safetensors")
        if self.role == "ip_adapter":
            weight_path = f"{self.entrypoint.subfolder}/{self.entrypoint.weight_name}"
            if weight_path not in entrypoint_safetensors:
                raise DomainError(
                    "weight manifest ip weight must reference safetensors"
                )
            encoder_root = effective_image_encoder_subfolder(self.entrypoint)
            required_encoder_files = {
                f"{encoder_root}/config.json",
                f"{encoder_root}/model.safetensors",
            }
            if not required_encoder_files.issubset(paths):
                raise DomainError(
                    "weight manifest image encoder config.json and model.safetensors required"
                )
        if type(self.root_sha256) is not Sha256:
            raise DomainError("invalid weight manifest root")

    def with_computed_root(self) -> WeightManifest:
        return replace(self, root_sha256=manifest_root_sha256(self))


def _manifest_payload(manifest: WeightManifest, *, include_root: bool) -> bytes:
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
            "image_encoder_folder": manifest.entrypoint.image_encoder_folder,
            "variant": manifest.entrypoint.variant,
        },
        "files": [
            {
                "relative_path": item.relative_path,
                "size_bytes": item.size_bytes,
                "sha256": item.sha256.value,
            }
            for item in sorted(manifest.files, key=lambda item: item.relative_path)
        ],
    }
    if include_root:
        payload["root_sha256"] = manifest.root_sha256.value
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def manifest_root_sha256(manifest: WeightManifest) -> Sha256:
    if type(manifest) is not WeightManifest:
        raise DomainError("invalid weight manifest")
    return Sha256(
        hashlib.sha256(_manifest_payload(manifest, include_root=False)).hexdigest()
    )


def manifest_sha256(manifest: WeightManifest) -> Sha256:
    if type(manifest) is not WeightManifest:
        raise DomainError("invalid weight manifest")
    return Sha256(
        hashlib.sha256(_manifest_payload(manifest, include_root=True)).hexdigest()
    )


@dataclass(frozen=True, slots=True)
class VerifiedWeightManifest:
    """A manifest whose regular files were verified via a caller-owned root fd."""

    manifest: WeightManifest


_ALLOWED_NON_PICKLE_SUFFIXES = (".json", ".txt", ".model")


def _close_fd(fd: int) -> None:
    try:
        os.close(fd)
    except OSError as exc:
        raise InfrastructureError("model supply fd close failed") from exc


def _close_fd_quietly(fd: int) -> None:
    try:
        os.close(fd)
    except OSError:
        pass


class _OwnedFd:
    __slots__ = ("_fd",)

    def __init__(self, fd: int) -> None:
        self._fd = fd

    def __enter__(self) -> _OwnedFd:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _traceback: object,
    ) -> None:
        if self._fd < 0:
            return
        fd = self._fd
        self._fd = -1
        if exc_type is None:
            _close_fd(fd)
        else:
            _close_fd_quietly(fd)

    @property
    def fd(self) -> int:
        if self._fd < 0:
            raise InfrastructureError("model supply fd unavailable")
        return self._fd

    def replace(self, replacement_fd: int) -> None:
        current_fd = self.fd
        self._fd = -1
        try:
            _close_fd(current_fd)
        except InfrastructureError:
            _close_fd_quietly(replacement_fd)
            raise
        self._fd = replacement_fd

    def release(self) -> int:
        fd = self.fd
        self._fd = -1
        return fd


def _require_trusted_node(node_stat: os.stat_result) -> None:
    if node_stat.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise InfrastructureError("model supply node not trusted")


def _validate_root_fd(root_fd: object) -> int:
    if type(root_fd) is not int or root_fd < 0:
        raise DomainError("invalid model supply root")
    try:
        root_stat = os.fstat(root_fd)
    except OSError as exc:
        raise InfrastructureError("model supply root unavailable") from exc
    if not stat.S_ISDIR(root_stat.st_mode):
        raise InfrastructureError("model supply root invalid")
    _require_trusted_node(root_stat)
    return root_fd


def _open_child_directory(parent_fd: int, component: str) -> int:
    try:
        child_fd = os.open(
            component,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            dir_fd=parent_fd,
        )
    except (OSError, ValueError) as exc:
        raise InfrastructureError("model supply path refused") from exc
    with _OwnedFd(child_fd) as owned:
        try:
            child_stat = os.fstat(owned.fd)
        except OSError as exc:
            raise InfrastructureError("model supply path refused") from exc
        _require_trusted_node(child_stat)
        return owned.release()


def _duplicate_fd(fd: int) -> int:
    try:
        return os.dup(fd)
    except OSError as exc:
        raise InfrastructureError("model supply path refused") from exc


def _open_regular_file(parent_fd: int, filename: str) -> int:
    try:
        return os.open(filename, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent_fd)
    except (OSError, ValueError) as exc:
        raise InfrastructureError("model supply path refused") from exc


def _open_directory(parent_fd: int, relative_path: str) -> int:
    with _OwnedFd(_duplicate_fd(parent_fd)) as current:
        for component in relative_path.split("/"):
            current.replace(_open_child_directory(current.fd, component))
        return current.release()


def _allowed_weight_file(relative_path: str) -> bool:
    return relative_path.endswith(".safetensors") or relative_path.endswith(
        _ALLOWED_NON_PICKLE_SUFFIXES
    )


def _read_and_hash(component_fd: int, item: WeightFile) -> None:
    if not _allowed_weight_file(item.relative_path):
        raise InfrastructureError("model supply weight format refused")
    components = item.relative_path.split("/")
    with _OwnedFd(_duplicate_fd(component_fd)) as directory:
        for component in components[:-1]:
            directory.replace(_open_child_directory(directory.fd, component))
        with _OwnedFd(_open_regular_file(directory.fd, components[-1])) as file:
            try:
                file_stat = os.fstat(file.fd)
                _require_trusted_node(file_stat)
                if not stat.S_ISREG(file_stat.st_mode):
                    raise InfrastructureError("model supply file not regular")
                if file_stat.st_size != item.size_bytes:
                    raise InfrastructureError("model supply file size mismatch")
                digest = hashlib.sha256()
                while chunk := os.read(file.fd, 1024 * 1024):
                    digest.update(chunk)
            except InfrastructureError:
                raise
            except OSError as exc:
                raise InfrastructureError("model supply path refused") from exc
            if Sha256(digest.hexdigest()) != item.sha256:
                raise InfrastructureError("model supply file hash mismatch")


def _listed_files(directory_fd: int, prefix: str = "") -> set[str]:
    found: set[str] = set()
    try:
        names = os.listdir(directory_fd)
    except (OSError, ValueError) as exc:
        raise InfrastructureError("model supply path unreadable") from exc
    for name in names:
        try:
            item_stat = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        except (OSError, ValueError) as exc:
            raise InfrastructureError("model supply path refused") from exc
        relative_path = f"{prefix}/{name}" if prefix else name
        _require_trusted_node(item_stat)
        if stat.S_ISLNK(item_stat.st_mode):
            raise InfrastructureError("model supply path refused")
        if stat.S_ISREG(item_stat.st_mode):
            found.add(relative_path)
        elif stat.S_ISDIR(item_stat.st_mode):
            with _OwnedFd(_open_child_directory(directory_fd, name)) as child:
                found.update(_listed_files(child.fd, relative_path))
        else:
            raise InfrastructureError("model supply file not regular")
    return found


def _verify_component(
    root_fd: int, manifest: WeightManifest, *, keep_open: bool
) -> int | None:
    _validate_root_fd(root_fd)
    if type(manifest) is not WeightManifest:
        raise DomainError("invalid weight manifest")
    if manifest_root_sha256(manifest) != manifest.root_sha256:
        raise DomainError("weight manifest root digest mismatch")
    with _OwnedFd(_open_directory(root_fd, manifest.relative_root)) as component:
        actual_files = _listed_files(component.fd)
        expected_files = {item.relative_path for item in manifest.files}
        if actual_files != expected_files:
            raise InfrastructureError("model supply files do not match manifest")
        for item in manifest.files:
            _read_and_hash(component.fd, item)
        if keep_open:
            return component.release()
        return None


def verify_weight_manifest(
    root_fd: int, manifest: WeightManifest
) -> VerifiedWeightManifest:
    """Verify a single component without closing the caller-owned root fd."""
    _verify_component(root_fd, manifest, keep_open=False)
    return VerifiedWeightManifest(manifest)
