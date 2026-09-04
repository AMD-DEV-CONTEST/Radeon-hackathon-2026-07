from __future__ import annotations

import hashlib
import os
import re
import uuid
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from policyseal.domain.errors import ImmutableRevisionError


class UnsafeStoragePath(ValueError):
    """A storage identifier or suffix could escape the controlled file root."""


class FileNamespace(StrEnum):
    SOURCES = "sources"
    OUTPUTS = "outputs"
    PREVIEWS = "previews"
    EVIDENCE = "evidence"


_STORAGE_ID = re.compile(r"^[0-9a-f]{32}\.[a-z0-9]{1,8}$")
_SUFFIX = re.compile(r"^\.[a-z0-9]{1,8}$")


@dataclass(frozen=True, slots=True)
class StoredFile:
    storage_id: str
    sha256: str
    size_bytes: int
    path: Path


class ControlledFileStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, mode=0o700, exist_ok=True)

    def _namespace_root(self, namespace: FileNamespace) -> Path:
        path = (self.root / namespace.value).resolve()
        if not path.is_relative_to(self.root):
            raise UnsafeStoragePath("storage namespace escapes the controlled root")
        path.mkdir(parents=True, mode=0o700, exist_ok=True)
        return path

    def path_for(self, namespace: FileNamespace, storage_id: str) -> Path:
        if _STORAGE_ID.fullmatch(storage_id) is None:
            raise UnsafeStoragePath("invalid storage identifier")
        namespace_root = self._namespace_root(namespace)
        path = (namespace_root / storage_id).resolve()
        if not path.is_relative_to(namespace_root):
            raise UnsafeStoragePath("storage path escapes its namespace")
        return path

    def write(self, namespace: FileNamespace, data: bytes, *, suffix: str) -> StoredFile:
        normalized_suffix = suffix.lower()
        if _SUFFIX.fullmatch(normalized_suffix) is None:
            raise UnsafeStoragePath("invalid storage suffix")
        storage_id = f"{uuid.uuid4().hex}{normalized_suffix}"
        path = self.path_for(namespace, storage_id)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        descriptor = os.open(path, flags, 0o600)
        try:
            written = 0
            while written < len(data):
                written += os.write(descriptor, data[written:])
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return StoredFile(
            storage_id=storage_id,
            sha256=hashlib.sha256(data).hexdigest(),
            size_bytes=len(data),
            path=path,
        )

    def read(self, namespace: FileNamespace, storage_id: str) -> bytes:
        return self.path_for(namespace, storage_id).read_bytes()

    def replace(self, namespace: FileNamespace, storage_id: str, data: bytes) -> None:
        del namespace, storage_id, data
        raise ImmutableRevisionError("stored source and output revisions cannot be replaced")

    def delete(self, namespace: FileNamespace, storage_id: str) -> None:
        self.path_for(namespace, storage_id).unlink(missing_ok=True)
