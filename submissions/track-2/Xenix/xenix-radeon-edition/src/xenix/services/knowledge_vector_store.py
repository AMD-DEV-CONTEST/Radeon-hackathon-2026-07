from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
import gc
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
from threading import Lock, RLock
import time
from uuid import uuid4

from ..config import AppPaths
from ..exceptions import ValidationError
from .storage.layout import (
    knowledge_indexes_root,
    knowledge_root,
    knowledge_staging_root,
)

_TABLE_NAME = "units"
_MANIFEST_FILE_NAME = "manifest.json"
_MANIFEST_SCHEMA_VERSION = 1
_MAX_MANIFEST_BYTES = 4_096
_MANIFEST_KEYS = frozenset(
    {
        "schema_version",
        "generation_id",
        "corpus_fingerprint",
        "profile_fingerprint",
        "dimensions",
        "unit_count",
        "unit_ids_sha256",
    }
)
_GENERATION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_MAX_FINGERPRINT_CHARACTERS = 256
_VECTOR_STAGE_PREFIX = "vector-"
_TRASH_DIRECTORY_NAME = ".vector-trash"
_TRASH_TOKEN_PATTERN = re.compile(
    r"^vector-(?:generation|stage)-[A-Za-z0-9_-]{1,80}-[0-9a-f]{32}$"
)
_WINDOWS_SHARING_VIOLATIONS = frozenset({5, 32, 33})
_WINDOWS_REPARSE_POINT = 0x0400
_SHARING_RETRY_DELAYS = (0.02, 0.08)


class _VectorLifecycle:
    def __init__(self) -> None:
        self._lock = RLock()

    @contextmanager
    def hold(self) -> Iterator[None]:
        with self._lock:
            yield


_LIFECYCLES_GUARD = Lock()
_LIFECYCLES: dict[str, _VectorLifecycle] = {}


def _lifecycle_for(root: Path) -> _VectorLifecycle:
    key = os.path.normcase(str(root.resolve()))
    with _LIFECYCLES_GUARD:
        lifecycle = _LIFECYCLES.get(key)
        if lifecycle is None:
            lifecycle = _VectorLifecycle()
            _LIFECYCLES[key] = lifecycle
        return lifecycle


class KnowledgeVectorStoreError(ValidationError):
    def __init__(self, message: str = "Knowledge vector storage is unavailable.") -> None:
        super().__init__(
            message,
            error_code="knowledge_vector_store_unavailable",
            retryable=True,
        )


@dataclass(frozen=True)
class KnowledgeVectorRecord:
    unit_id: str
    vector: tuple[float, ...]


class KnowledgeVectorGenerationState(StrEnum):
    USABLE = "usable"
    MISSING = "missing"
    CORRUPT = "corrupt"
    UNSAFE = "unsafe"


class LanceKnowledgeVectorStore:
    """Operation-scoped LanceDB adapter for immutable Knowledge generations."""

    def __init__(self, paths: AppPaths) -> None:
        self._knowledge_root = knowledge_root(paths)
        self._indexes_root = knowledge_indexes_root(paths)
        self._staging_root = knowledge_staging_root(paths)
        self._trash_root = self._indexes_root / _TRASH_DIRECTORY_NAME
        self._lifecycle = _lifecycle_for(self._knowledge_root)

    @contextmanager
    def lifecycle(self) -> Iterator[None]:
        """Serialize in-process vector publication, use, and reclamation per home."""

        with self._lifecycle.hold():
            self._validate_storage_topology()
            yield

    def write_generation(
        self,
        *,
        generation_id: str,
        records: Sequence[KnowledgeVectorRecord],
        dimensions: int,
        corpus_fingerprint: str,
        profile_fingerprint: str,
    ) -> str:
        with self.lifecycle():
            return self._write_generation(
                generation_id=generation_id,
                records=records,
                dimensions=dimensions,
                corpus_fingerprint=corpus_fingerprint,
                profile_fingerprint=profile_fingerprint,
            )

    def _write_generation(
        self,
        *,
        generation_id: str,
        records: Sequence[KnowledgeVectorRecord],
        dimensions: int,
        corpus_fingerprint: str,
        profile_fingerprint: str,
    ) -> str:
        self._validate_generation_id(generation_id)
        corpus_fingerprint = self._validated_fingerprint(corpus_fingerprint)
        profile_fingerprint = self._validated_fingerprint(profile_fingerprint)
        dimensions = self._validated_positive_int(dimensions)
        normalized = self._validated_records(records, dimensions=dimensions)
        unit_ids = [record.unit_id for record in normalized]
        stage = self._staging_root / f"vector-{generation_id}"
        final = self._indexes_root / generation_id
        stage_created = False
        try:
            self._assert_within(stage, self._staging_root)
            self._assert_within(final, self._indexes_root)
            if (
                stage.exists()
                or self._is_link_like(stage)
                or final.exists()
                or self._is_link_like(final)
            ):
                raise KnowledgeVectorStoreError()
            self._staging_root.mkdir(parents=True, exist_ok=True)
            self._indexes_root.mkdir(parents=True, exist_ok=True)
            self._validate_storage_topology()
            stage.mkdir(parents=False)
            stage_created = True
            self._write_lance_table(stage, normalized, dimensions=dimensions)
            self._write_manifest(
                stage,
                generation_id=generation_id,
                corpus_fingerprint=corpus_fingerprint,
                profile_fingerprint=profile_fingerprint,
                dimensions=dimensions,
                unit_ids=unit_ids,
            )
            if not self._generation_matches(
                stage,
                expected_manifest=self._manifest_payload(
                    generation_id=generation_id,
                    corpus_fingerprint=corpus_fingerprint,
                    profile_fingerprint=profile_fingerprint,
                    dimensions=dimensions,
                    unit_ids=unit_ids,
                ),
                expected_unit_ids=unit_ids,
            ):
                raise KnowledgeVectorStoreError()
            if not self._replace_with_retries(stage, final):
                raise KnowledgeVectorStoreError()
        except Exception as exc:
            if stage_created:
                try:
                    self._remove_staging_tree(stage)
                except Exception:
                    raise KnowledgeVectorStoreError() from None
            if isinstance(exc, KnowledgeVectorStoreError):
                raise
            raise KnowledgeVectorStoreError() from None
        return final.relative_to(self._knowledge_root).as_posix()

    def generation_is_usable(
        self,
        relative_path: str,
        *,
        expected_generation_id: str,
        expected_corpus_fingerprint: str,
        expected_profile_fingerprint: str,
        expected_unit_ids: Sequence[str],
        expected_count: int,
        expected_dimensions: int,
    ) -> bool:
        with self.lifecycle():
            return self._generation_is_usable(
                relative_path,
                expected_generation_id=expected_generation_id,
                expected_corpus_fingerprint=expected_corpus_fingerprint,
                expected_profile_fingerprint=expected_profile_fingerprint,
                expected_unit_ids=expected_unit_ids,
                expected_count=expected_count,
                expected_dimensions=expected_dimensions,
            )

    def _generation_is_usable(
        self,
        relative_path: str,
        *,
        expected_generation_id: str,
        expected_corpus_fingerprint: str,
        expected_profile_fingerprint: str,
        expected_unit_ids: Sequence[str],
        expected_count: int,
        expected_dimensions: int,
    ) -> bool:
        try:
            self._validate_generation_id(expected_generation_id)
            expected_corpus_fingerprint = self._validated_fingerprint(
                expected_corpus_fingerprint
            )
            expected_profile_fingerprint = self._validated_fingerprint(
                expected_profile_fingerprint
            )
            expected_count = self._validated_positive_int(expected_count)
            expected_dimensions = self._validated_positive_int(expected_dimensions)
            unit_ids = self._validated_unit_ids(expected_unit_ids)
            if len(unit_ids) != expected_count:
                return False
            expected_relative_path = f"indexes/{expected_generation_id}"
            if relative_path != expected_relative_path:
                return False
            path = self._resolve_generation_path(relative_path)
            return self._generation_matches(
                path,
                expected_manifest=self._manifest_payload(
                    generation_id=expected_generation_id,
                    corpus_fingerprint=expected_corpus_fingerprint,
                    profile_fingerprint=expected_profile_fingerprint,
                    dimensions=expected_dimensions,
                    unit_ids=unit_ids,
                ),
                expected_unit_ids=unit_ids,
            )
        except Exception:
            return False

    def search(
        self,
        relative_path: str,
        *,
        query_vector: Sequence[float],
        limit: int,
    ) -> list[str]:
        with self.lifecycle():
            return self._search(
                relative_path,
                query_vector=query_vector,
                limit=limit,
            )

    def _search(
        self,
        relative_path: str,
        *,
        query_vector: Sequence[float],
        limit: int,
    ) -> list[str]:
        if limit < 1:
            raise KnowledgeVectorStoreError()
        vector = self._validated_vector(query_vector)
        database = None
        table = None
        query = None
        result = None
        unit_id_column = None
        failed = False
        unit_ids: list[str] = []
        try:
            import lancedb

            path = self._resolve_generation_path(relative_path)
            database = lancedb.connect(str(path))
            table = database.open_table(_TABLE_NAME)
            query = table.search(list(vector))
            query = query.distance_type("cosine")
            query = query.select(["unit_id", "_distance"])
            query = query.limit(limit)
            result = query.to_arrow()
            unit_id_column = result.column("unit_id")
            unit_ids = [str(value) for value in unit_id_column.to_pylist()]
        except Exception as exc:
            failed = True
            self._discard_exception_traceback(exc)
        finally:
            unit_id_column = None
            result = None
            query = None
            table = None
            database = None
            gc.collect()
        if failed:
            raise KnowledgeVectorStoreError() from None
        return unit_ids

    def inspect_generation(
        self,
        relative_path: str,
        *,
        expected_generation_id: str,
        expected_corpus_fingerprint: str,
        expected_profile_fingerprint: str,
        expected_count: int,
        expected_dimensions: int,
    ) -> KnowledgeVectorGenerationState:
        """Inspect one metadata-bound projection without trusting its stored path."""

        with self.lifecycle():
            try:
                path = self._strict_generation_path(
                    relative_path,
                    expected_generation_id=expected_generation_id,
                )
            except KnowledgeVectorStoreError:
                return KnowledgeVectorGenerationState.UNSAFE
            if self._is_link_like(path):
                return KnowledgeVectorGenerationState.UNSAFE
            if not path.exists():
                return KnowledgeVectorGenerationState.MISSING
            if not path.is_dir():
                return KnowledgeVectorGenerationState.CORRUPT
            try:
                matches = self._generation_matches_metadata(
                    path,
                    expected_generation_id=expected_generation_id,
                    expected_corpus_fingerprint=expected_corpus_fingerprint,
                    expected_profile_fingerprint=expected_profile_fingerprint,
                    expected_count=expected_count,
                    expected_dimensions=expected_dimensions,
                )
            except Exception:
                return KnowledgeVectorGenerationState.CORRUPT
            return (
                KnowledgeVectorGenerationState.USABLE
                if matches
                else KnowledgeVectorGenerationState.CORRUPT
            )

    def list_definite_generation_paths(self) -> tuple[str, ...]:
        """List final directories whose bounded manifest proves vector provenance."""

        with self.lifecycle():
            if not self._indexes_root.is_dir():
                return ()
            entries: list[str] = []
            try:
                children = tuple(self._indexes_root.iterdir())
            except OSError as exc:
                raise KnowledgeVectorStoreError() from exc
            for child in children:
                if child.name == _TRASH_DIRECTORY_NAME or self._is_link_like(child):
                    continue
                try:
                    self._validate_generation_id(child.name)
                except KnowledgeVectorStoreError:
                    continue
                if not child.is_dir():
                    continue
                try:
                    manifest = self._read_manifest(child)
                except (KnowledgeVectorStoreError, OSError):
                    continue
                if manifest["generation_id"] == child.name:
                    entries.append(f"indexes/{child.name}")
            return tuple(sorted(entries))

    def quarantine_generation(
        self,
        relative_path: str,
        *,
        expected_generation_id: str,
    ) -> str | None:
        """Atomically detach one exact vector path into same-volume private trash."""

        with self.lifecycle():
            path = self._strict_generation_path(
                relative_path,
                expected_generation_id=expected_generation_id,
            )
            if self._is_link_like(path):
                raise KnowledgeVectorStoreError()
            if not path.exists():
                return None
            return self._quarantine_path(
                path,
                owned_root=self._indexes_root,
                kind="generation",
                identity=expected_generation_id,
            )

    def discard_unpublished_generation(
        self,
        relative_path: str,
        *,
        expected_generation_id: str,
    ) -> bool:
        """Best-effort reclamation for a final directory with no metadata row."""

        with self.lifecycle():
            try:
                token = self.quarantine_generation(
                    relative_path,
                    expected_generation_id=expected_generation_id,
                )
            except KnowledgeVectorStoreError:
                return False
            return token is None or self.delete_quarantined(token)

    def quarantine_stale_vector_staging(
        self,
        *,
        stale_before: float,
    ) -> tuple[str, ...]:
        """Detach only old, direct ``vector-<id>`` staging directories."""

        if not math.isfinite(stale_before):
            raise KnowledgeVectorStoreError()
        with self.lifecycle():
            if not self._staging_root.is_dir():
                return ()
            try:
                children = tuple(self._staging_root.iterdir())
            except OSError as exc:
                raise KnowledgeVectorStoreError() from exc
            tokens: list[str] = []
            for child in children:
                if (
                    not child.name.startswith(_VECTOR_STAGE_PREFIX)
                    or self._is_link_like(child)
                ):
                    continue
                generation_id = child.name.removeprefix(_VECTOR_STAGE_PREFIX)
                try:
                    self._validate_generation_id(generation_id)
                    if not child.is_dir() or child.stat().st_mtime > stale_before:
                        continue
                    token = self._quarantine_path(
                        child,
                        owned_root=self._staging_root,
                        kind="stage",
                        identity=generation_id,
                    )
                except (KnowledgeVectorStoreError, OSError):
                    continue
                tokens.append(token)
            return tuple(tokens)

    def list_quarantined(self) -> tuple[str, ...]:
        with self.lifecycle():
            if self._is_link_like(self._trash_root) or not self._trash_root.is_dir():
                return ()
            try:
                self._assert_within(self._trash_root, self._indexes_root)
                children = tuple(self._trash_root.iterdir())
            except (KnowledgeVectorStoreError, OSError):
                return ()
            return tuple(
                sorted(
                    child.name
                    for child in children
                    if _TRASH_TOKEN_PATTERN.fullmatch(child.name)
                    and not self._is_link_like(child)
                )
            )

    def delete_quarantined(self, token: str) -> bool:
        """Best-effort deletion; a sharing violation leaves private trash retryable."""

        if not _TRASH_TOKEN_PATTERN.fullmatch(str(token)):
            raise KnowledgeVectorStoreError()
        with self.lifecycle():
            if self._is_link_like(self._trash_root):
                return False
            path = self._trash_root / token
            try:
                self._assert_within(self._trash_root, self._indexes_root)
                self._assert_within(path, self._trash_root)
            except KnowledgeVectorStoreError:
                return False
            return self._remove_path_with_retries(path, best_effort=True)

    def _write_lance_table(
        self,
        path: Path,
        records: Sequence[KnowledgeVectorRecord],
        *,
        dimensions: int,
    ) -> None:
        schema = None
        payload = None
        database = None
        table = None
        failed = False
        try:
            import lancedb
            import pyarrow as pa

            schema = pa.schema(
                [
                    pa.field("unit_id", pa.string(), nullable=False),
                    pa.field(
                        "vector",
                        pa.list_(pa.float32(), dimensions),
                        nullable=False,
                    ),
                ]
            )
            payload = pa.Table.from_pylist(
                [
                    {"unit_id": record.unit_id, "vector": list(record.vector)}
                    for record in records
                ],
                schema=schema,
            )
            database = lancedb.connect(str(path))
            table = database.create_table(_TABLE_NAME, data=payload, mode="create")
            if table.count_rows() != len(records):
                raise KnowledgeVectorStoreError()
        except Exception as exc:
            failed = True
            self._discard_exception_traceback(exc)
        finally:
            table = None
            database = None
            payload = None
            schema = None
            gc.collect()
        if failed:
            raise KnowledgeVectorStoreError() from None

    def _generation_matches(
        self,
        path: Path,
        *,
        expected_manifest: dict[str, object],
        expected_unit_ids: Sequence[str],
    ) -> bool:
        if not path.is_dir():
            return False
        if self._read_manifest(path) != expected_manifest:
            return False

        return self._read_generation_unit_ids(
            path,
            expected_count=int(expected_manifest["unit_count"]),
            expected_dimensions=int(expected_manifest["dimensions"]),
        ) == list(expected_unit_ids)

    def _generation_matches_metadata(
        self,
        path: Path,
        *,
        expected_generation_id: str,
        expected_corpus_fingerprint: str,
        expected_profile_fingerprint: str,
        expected_count: int,
        expected_dimensions: int,
    ) -> bool:
        self._validate_generation_id(expected_generation_id)
        expected_corpus_fingerprint = self._validated_fingerprint(
            expected_corpus_fingerprint
        )
        expected_profile_fingerprint = self._validated_fingerprint(
            expected_profile_fingerprint
        )
        expected_count = self._validated_positive_int(expected_count)
        expected_dimensions = self._validated_positive_int(expected_dimensions)
        manifest = self._read_manifest(path)
        if (
            manifest["generation_id"] != expected_generation_id
            or manifest["corpus_fingerprint"] != expected_corpus_fingerprint
            or manifest["profile_fingerprint"] != expected_profile_fingerprint
            or manifest["unit_count"] != expected_count
            or manifest["dimensions"] != expected_dimensions
        ):
            return False
        unit_ids = self._read_generation_unit_ids(
            path,
            expected_count=expected_count,
            expected_dimensions=expected_dimensions,
        )
        return manifest["unit_ids_sha256"] == self._unit_ids_digest(unit_ids)

    def _read_generation_unit_ids(
        self,
        path: Path,
        *,
        expected_count: int,
        expected_dimensions: int,
    ) -> list[str]:

        database = None
        table = None
        schema = None
        vector_type = None
        query = None
        payload = None
        unit_id_column = None
        failed = False
        actual_unit_ids: list[str] = []
        try:
            import lancedb

            database = lancedb.connect(str(path))
            table = database.open_table(_TABLE_NAME)
            schema = table.schema
            vector_type = schema.field("vector").type
            if (
                table.count_rows() != expected_count
                or getattr(vector_type, "list_size", None)
                != expected_dimensions
            ):
                raise KnowledgeVectorStoreError()
            else:
                query = table.search()
                query = query.select(["unit_id"])
                query = query.limit(expected_count + 1)
                payload = query.to_arrow()
                unit_id_column = payload.column("unit_id")
                actual_unit_ids = [str(value) for value in unit_id_column.to_pylist()]
                if len(actual_unit_ids) != expected_count:
                    raise KnowledgeVectorStoreError()
                actual_unit_ids = self._validated_unit_ids(actual_unit_ids)
        except Exception as exc:
            failed = True
            self._discard_exception_traceback(exc)
        finally:
            unit_id_column = None
            payload = None
            query = None
            vector_type = None
            schema = None
            table = None
            database = None
            gc.collect()
        if failed:
            raise KnowledgeVectorStoreError() from None
        return actual_unit_ids

    def _write_manifest(
        self,
        path: Path,
        *,
        generation_id: str,
        corpus_fingerprint: str,
        profile_fingerprint: str,
        dimensions: int,
        unit_ids: Sequence[str],
    ) -> None:
        payload = self._manifest_payload(
            generation_id=generation_id,
            corpus_fingerprint=corpus_fingerprint,
            profile_fingerprint=profile_fingerprint,
            dimensions=dimensions,
            unit_ids=unit_ids,
        )
        encoded = json.dumps(
            payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        if not encoded or len(encoded) > _MAX_MANIFEST_BYTES:
            raise KnowledgeVectorStoreError()
        manifest_path = path / _MANIFEST_FILE_NAME
        self._assert_within(manifest_path, path)
        with manifest_path.open("xb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())

    def _read_manifest(self, path: Path) -> dict[str, object]:
        manifest_path = path / _MANIFEST_FILE_NAME
        self._assert_within(manifest_path, path)
        if self._is_link_like(manifest_path) or not manifest_path.is_file():
            raise KnowledgeVectorStoreError()
        with manifest_path.open("rb") as handle:
            encoded = handle.read(_MAX_MANIFEST_BYTES + 1)
        if not encoded or len(encoded) > _MAX_MANIFEST_BYTES:
            raise KnowledgeVectorStoreError()
        try:
            payload = json.loads(encoded.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise KnowledgeVectorStoreError() from exc
        if not isinstance(payload, dict) or set(payload) != _MANIFEST_KEYS:
            raise KnowledgeVectorStoreError()
        if (
            type(payload["schema_version"]) is not int
            or payload["schema_version"] != _MANIFEST_SCHEMA_VERSION
            or type(payload["generation_id"]) is not str
            or type(payload["corpus_fingerprint"]) is not str
            or type(payload["profile_fingerprint"]) is not str
            or type(payload["dimensions"]) is not int
            or type(payload["unit_count"]) is not int
            or type(payload["unit_ids_sha256"]) is not str
        ):
            raise KnowledgeVectorStoreError()
        self._validate_generation_id(payload["generation_id"])
        self._validated_fingerprint(payload["corpus_fingerprint"])
        self._validated_fingerprint(payload["profile_fingerprint"])
        self._validated_positive_int(payload["dimensions"])
        self._validated_positive_int(payload["unit_count"])
        if not _SHA256_PATTERN.fullmatch(payload["unit_ids_sha256"]):
            raise KnowledgeVectorStoreError()
        return payload

    @classmethod
    def _manifest_payload(
        cls,
        *,
        generation_id: str,
        corpus_fingerprint: str,
        profile_fingerprint: str,
        dimensions: int,
        unit_ids: Sequence[str],
    ) -> dict[str, object]:
        return {
            "schema_version": _MANIFEST_SCHEMA_VERSION,
            "generation_id": generation_id,
            "corpus_fingerprint": corpus_fingerprint,
            "profile_fingerprint": profile_fingerprint,
            "dimensions": dimensions,
            "unit_count": len(unit_ids),
            "unit_ids_sha256": cls._unit_ids_digest(unit_ids),
        }

    @staticmethod
    def _unit_ids_digest(unit_ids: Sequence[str]) -> str:
        digest = sha256(b"xenix.knowledge.unit-ids.v1\0")
        for unit_id in unit_ids:
            encoded = unit_id.encode("utf-8")
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)
        return digest.hexdigest()

    def _resolve_generation_path(self, value: str) -> Path:
        if type(value) is not str:
            raise KnowledgeVectorStoreError()
        relative = PurePosixPath(value)
        if (
            not value
            or value != relative.as_posix()
            or relative.is_absolute()
            or ".." in relative.parts
            or len(relative.parts) != 2
            or relative.parts[0] != "indexes"
        ):
            raise KnowledgeVectorStoreError()
        self._validate_generation_id(relative.parts[1])
        path = self._knowledge_root.joinpath(*relative.parts)
        if self._is_link_like(path):
            raise KnowledgeVectorStoreError()
        self._assert_within(path, self._indexes_root)
        return path

    def _strict_generation_path(
        self,
        value: str,
        *,
        expected_generation_id: str,
    ) -> Path:
        self._validate_generation_id(expected_generation_id)
        if value != f"indexes/{expected_generation_id}":
            raise KnowledgeVectorStoreError()
        return self._resolve_generation_path(value)

    @staticmethod
    def _validate_generation_id(value: str) -> None:
        if not _GENERATION_ID_PATTERN.fullmatch(str(value)):
            raise KnowledgeVectorStoreError()

    @staticmethod
    def _validated_fingerprint(value: str) -> str:
        if (
            type(value) is not str
            or not 1 <= len(value) <= _MAX_FINGERPRINT_CHARACTERS
            or any(
                ord(character) < 0x21 or ord(character) > 0x7E
                for character in value
            )
        ):
            raise KnowledgeVectorStoreError()
        return value

    @staticmethod
    def _validated_positive_int(value: int) -> int:
        if type(value) is not int or value < 1:
            raise KnowledgeVectorStoreError()
        return value

    @staticmethod
    def _discard_exception_traceback(exc: Exception) -> None:
        """Drop frames that may otherwise retain native Lance/Arrow handles."""
        exc.__traceback__ = None
        exc.__cause__ = None
        exc.__context__ = None

    @staticmethod
    def _validated_unit_ids(values: Sequence[str]) -> list[str]:
        if isinstance(values, (str, bytes)):
            raise KnowledgeVectorStoreError()
        normalized: list[str] = []
        seen: set[str] = set()
        for value in values:
            unit_id = str(value).strip()
            if not unit_id or unit_id in seen:
                raise KnowledgeVectorStoreError()
            seen.add(unit_id)
            normalized.append(unit_id)
        if not normalized:
            raise KnowledgeVectorStoreError()
        return normalized

    @classmethod
    def _validated_records(
        cls,
        records: Sequence[KnowledgeVectorRecord],
        *,
        dimensions: int,
    ) -> list[KnowledgeVectorRecord]:
        if dimensions < 1 or not records:
            raise KnowledgeVectorStoreError()
        normalized: list[KnowledgeVectorRecord] = []
        seen: set[str] = set()
        for record in records:
            unit_id = str(record.unit_id).strip()
            if not unit_id or unit_id in seen:
                raise KnowledgeVectorStoreError()
            vector = cls._validated_vector(record.vector)
            if len(vector) != dimensions:
                raise KnowledgeVectorStoreError()
            seen.add(unit_id)
            normalized.append(KnowledgeVectorRecord(unit_id=unit_id, vector=vector))
        return normalized

    @staticmethod
    def _validated_vector(values: Sequence[float]) -> tuple[float, ...]:
        try:
            vector = tuple(float(value) for value in values)
        except (TypeError, ValueError) as exc:
            raise KnowledgeVectorStoreError() from exc
        if not vector or not all(math.isfinite(value) for value in vector):
            raise KnowledgeVectorStoreError()
        return vector

    @staticmethod
    def _assert_within(path: Path, root: Path) -> None:
        resolved_root = root.resolve()
        resolved_path = path.resolve()
        if resolved_path == resolved_root or not resolved_path.is_relative_to(resolved_root):
            raise KnowledgeVectorStoreError()

    def _validate_storage_topology(self) -> None:
        try:
            knowledge_root = self._knowledge_root.resolve()
            expected_roots = (
                (self._indexes_root, knowledge_root / "indexes"),
                (self._staging_root, knowledge_root / "staging"),
                (
                    self._trash_root,
                    knowledge_root / "indexes" / _TRASH_DIRECTORY_NAME,
                ),
            )
            for path, expected in expected_roots:
                if (
                    self._is_link_like(path)
                    or path.resolve() != expected
                    or (path.exists() and not path.is_dir())
                ):
                    raise KnowledgeVectorStoreError()
        except KnowledgeVectorStoreError:
            raise
        except (OSError, RuntimeError) as exc:
            raise KnowledgeVectorStoreError() from exc

    @staticmethod
    def _is_link_like(path: Path) -> bool:
        is_junction = getattr(path, "is_junction", None)
        if path.is_symlink() or bool(is_junction and is_junction()):
            return True
        if os.name != "nt":
            return False
        try:
            attributes = int(getattr(path.lstat(), "st_file_attributes", 0))
        except FileNotFoundError:
            return False
        return bool(attributes & _WINDOWS_REPARSE_POINT)

    def _quarantine_path(
        self,
        path: Path,
        *,
        owned_root: Path,
        kind: str,
        identity: str,
    ) -> str:
        if kind not in {"generation", "stage"}:
            raise KnowledgeVectorStoreError()
        self._validate_generation_id(identity)
        if self._is_link_like(path):
            raise KnowledgeVectorStoreError()
        self._assert_within(path, owned_root)
        try:
            self._indexes_root.mkdir(parents=True, exist_ok=True)
            self._trash_root.mkdir(parents=False, exist_ok=True)
        except OSError as exc:
            raise KnowledgeVectorStoreError() from exc
        self._validate_storage_topology()
        if self._is_link_like(self._trash_root) or not self._trash_root.is_dir():
            raise KnowledgeVectorStoreError()
        self._assert_within(self._trash_root, self._indexes_root)
        token = f"vector-{kind}-{identity}-{uuid4().hex}"
        target = self._trash_root / token
        self._assert_within(target, self._trash_root)
        if not self._replace_with_retries(path, target):
            raise KnowledgeVectorStoreError()
        return token

    @classmethod
    def _replace_with_retries(cls, source: Path, target: Path) -> bool:
        for attempt in range(len(_SHARING_RETRY_DELAYS) + 1):
            try:
                os.replace(source, target)
                return True
            except FileNotFoundError:
                if not source.exists() and not cls._is_link_like(source):
                    return False
                raise KnowledgeVectorStoreError() from None
            except OSError as exc:
                if not cls._is_windows_sharing_violation(exc):
                    raise KnowledgeVectorStoreError() from None
                cls._discard_exception_traceback(exc)
                if attempt >= len(_SHARING_RETRY_DELAYS):
                    raise KnowledgeVectorStoreError() from None
                gc.collect()
                time.sleep(_SHARING_RETRY_DELAYS[attempt])
        return False

    @classmethod
    def _remove_path_with_retries(cls, path: Path, *, best_effort: bool) -> bool:
        for attempt in range(len(_SHARING_RETRY_DELAYS) + 1):
            try:
                if cls._is_link_like(path):
                    return False
                if path.is_dir():
                    shutil.rmtree(path)
                elif path.is_file():
                    path.unlink()
                else:
                    return True
                return True
            except FileNotFoundError:
                return True
            except OSError as exc:
                retryable = cls._is_windows_sharing_violation(exc)
                cls._discard_exception_traceback(exc)
                if not retryable or attempt >= len(_SHARING_RETRY_DELAYS):
                    if best_effort:
                        return False
                    raise KnowledgeVectorStoreError() from None
                gc.collect()
                time.sleep(_SHARING_RETRY_DELAYS[attempt])
        return False

    @staticmethod
    def _is_windows_sharing_violation(exc: OSError) -> bool:
        return (
            getattr(exc, "winerror", None) in _WINDOWS_SHARING_VIOLATIONS
            or isinstance(exc, PermissionError)
        )

    def _remove_staging_tree(self, path: Path) -> None:
        self._assert_within(path, self._staging_root)
        self._remove_path_with_retries(path, best_effort=False)
