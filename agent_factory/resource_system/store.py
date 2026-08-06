from __future__ import annotations

import base64
from contextlib import contextmanager
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from typing import Any, Iterator

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from jsonschema import Draft202012Validator

from agent_factory.paths import factory_artifact_path
from agent_factory.runtime_contracts.schema import ResourceDescriptor
from agent_factory.sqlite_runtime import connect_sqlite, initialize_sqlite_store


RESOURCE_MASTER_KEY_ENV = "AGENTFACTORY_RESOURCE_MASTER_KEY"
RESOURCE_STORE_PATH_ENV = "AGENTFACTORY_RESOURCE_STORE_PATH"
RESOURCE_STORE_READ_ONLY_ENV = "AGENTFACTORY_RESOURCE_STORE_READ_ONLY"
SQLITE_BUSY_TIMEOUT_MS = 10000


class ResourceStoreError(RuntimeError):
    pass


class ResourceStore:
    def __init__(self, path: str | Path | None = None, *, master_key: str | None = None) -> None:
        self.path = Path(path or resource_store_path()).expanduser().resolve()
        self._master_key = master_key if master_key is not None else os.getenv(RESOURCE_MASTER_KEY_ENV, "")
        self.read_only = os.getenv(RESOURCE_STORE_READ_ONLY_ENV, "0") == "1"
        if not self.read_only:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            initialize_sqlite_store(
                self.path,
                self._ensure_schema,
                timeout_ms=SQLITE_BUSY_TIMEOUT_MS,
                wal=True,
            )

    @property
    def key_available(self) -> bool:
        return bool(self._master_key.strip())

    def status(
        self,
        package_id: str,
        descriptors: list[ResourceDescriptor],
        *,
        include_values: bool = False,
    ) -> list[dict[str, Any]]:
        existing = self._existing_resource_ids(package_id)
        items: list[dict[str, Any]] = []
        for descriptor in descriptors:
            configured = descriptor.resource_id in existing
            item = {
                "resource_id": descriptor.resource_id,
                "description": descriptor.description,
                "required": descriptor.required,
                "configured": configured,
                "secret_fields": list(descriptor.secret_fields),
                "used_by": list(descriptor.used_by),
                "sandbox_access_expectation": descriptor.sandbox_access_expectation,
                "value_schema": descriptor.value_schema,
                "key_available": self.key_available,
            }
            if include_values:
                item["value"] = self.resolve(package_id, descriptor) if configured and self.key_available else None
            items.append(item)
        return items

    def put(self, package_id: str, descriptor: ResourceDescriptor, value: Any) -> dict[str, Any]:
        self._assert_writable()
        cipher = self._cipher()
        errors = sorted(Draft202012Validator(descriptor.value_schema or {}).iter_errors(value), key=lambda item: list(item.path))
        if errors:
            raise ResourceStoreError("resource value validation failed: " + "; ".join(error.message for error in errors))
        nonce = os.urandom(12)
        plaintext = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        encrypted = cipher.encrypt(nonce, plaintext, _aad(package_id, descriptor.resource_id))
        now = _now()
        with self._connect() as conn:
            conn.execute(
                """
                insert into runtime_resources(package_id, resource_id, nonce_b64, ciphertext_b64, updated_at)
                values (?, ?, ?, ?, ?)
                on conflict(package_id, resource_id) do update set
                  nonce_b64=excluded.nonce_b64,
                  ciphertext_b64=excluded.ciphertext_b64,
                  updated_at=excluded.updated_at
                """,
                (package_id, descriptor.resource_id, _b64(nonce), _b64(encrypted), now),
            )
        return {"resource_id": descriptor.resource_id, "configured": True, "updated_at": now}

    def delete(self, package_id: str, resource_id: str) -> bool:
        self._assert_writable()
        with self._connect() as conn:
            cursor = conn.execute(
                "delete from runtime_resources where package_id = ? and resource_id = ?",
                (package_id, resource_id),
            )
        return cursor.rowcount > 0

    def delete_package(self, package_id: str) -> int:
        self._assert_writable()
        with self._connect() as conn:
            cursor = conn.execute("delete from runtime_resources where package_id = ?", (package_id,))
        return cursor.rowcount

    def transfer(self, source_package_id: str, target_package_id: str, descriptors: list[ResourceDescriptor]) -> None:
        self._assert_writable()
        descriptor_map = {item.resource_id: item for item in descriptors}
        with self._connect() as conn:
            rows = conn.execute(
                "select resource_id, nonce_b64, ciphertext_b64 from runtime_resources where package_id = ?",
                (source_package_id,),
            ).fetchall()
        for row in rows:
            resource_id = str(row["resource_id"])
            descriptor = descriptor_map.get(resource_id)
            if descriptor is None:
                continue
            value = self._decrypt_row(source_package_id, resource_id, row)
            self.put(target_package_id, descriptor, value)
        with self._connect() as conn:
            conn.execute("delete from runtime_resources where package_id = ?", (source_package_id,))

    def resolve(self, package_id: str, descriptor: ResourceDescriptor) -> Any:
        cipher = self._cipher()
        with self._connect() as conn:
            row = conn.execute(
                "select nonce_b64, ciphertext_b64 from runtime_resources where package_id = ? and resource_id = ?",
                (package_id, descriptor.resource_id),
            ).fetchone()
        if row is None:
            raise ResourceStoreError(f"resource_required: {descriptor.resource_id}")
        return self._decrypt_row(package_id, descriptor.resource_id, row)

    def _decrypt_row(self, package_id: str, resource_id: str, row: sqlite3.Row) -> Any:
        try:
            plaintext = self._cipher().decrypt(
                _unb64(str(row["nonce_b64"])),
                _unb64(str(row["ciphertext_b64"])),
                _aad(package_id, resource_id),
            )
            return json.loads(plaintext.decode("utf-8"))
        except Exception as exc:
            raise ResourceStoreError(f"resource decryption failed: {resource_id}") from exc

    def _existing_resource_ids(self, package_id: str) -> set[str]:
        with self._connect() as conn:
            rows = conn.execute("select resource_id from runtime_resources where package_id = ?", (package_id,)).fetchall()
        return {str(row["resource_id"]) for row in rows}

    def _cipher(self) -> AESGCM:
        if not self.key_available:
            raise ResourceStoreError(f"{RESOURCE_MASTER_KEY_ENV} is required for runtime resource values")
        return AESGCM(hashlib.sha256(self._master_key.encode("utf-8")).digest())

    def _assert_writable(self) -> None:
        if self.read_only:
            raise ResourceStoreError("runtime resource store is read-only")

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        if self.read_only:
            conn = connect_sqlite(
                f"{self.path.as_uri()}?mode=ro",
                timeout_ms=SQLITE_BUSY_TIMEOUT_MS,
                uri=True,
                query_only=True,
            )
        else:
            conn = connect_sqlite(self.path, timeout_ms=SQLITE_BUSY_TIMEOUT_MS)
        try:
            yield conn
            if not self.read_only:
                conn.commit()
        finally:
            conn.close()

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                create table if not exists runtime_resources (
                  package_id text not null,
                  resource_id text not null,
                  nonce_b64 text not null,
                  ciphertext_b64 text not null,
                  updated_at text not null,
                  primary key(package_id, resource_id)
                )
                """
            )


def resource_store_path() -> Path:
    configured = os.getenv(RESOURCE_STORE_PATH_ENV, "").strip()
    return Path(configured).expanduser() if configured else factory_artifact_path("resources", "runtime.sqlite")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _aad(package_id: str, resource_id: str) -> bytes:
    return f"{package_id}:{resource_id}".encode("utf-8")


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value.encode("ascii"))
