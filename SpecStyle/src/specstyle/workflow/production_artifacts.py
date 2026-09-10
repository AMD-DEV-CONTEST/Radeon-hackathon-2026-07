"""Private durable storage for the production generation artifact."""

from __future__ import annotations

import json
import os
import re
import secrets
import stat
import threading
import weakref
from typing import NoReturn

from specstyle.domain.artifacts import ArtifactRef
from specstyle.domain.identifiers import ArtifactId, JobId, Sha256
from specstyle.errors import DomainError, InfrastructureError
from specstyle.generation.protocols import GeneratedArtifact
from specstyle.observability.hashing import hash_bytes

__all__ = ()

_SCHEMA = "specstyle.production_artifact.v1"
_METADATA_KEYS = frozenset(
    "schema job_id artifact_id content_sha256 size_bytes media_type request_hash "
    "generation_fingerprint".split()
)
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_READ_FLAGS = os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC
_WRITE_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
_MAX_PNG = 32 * 1024 * 1024
_MAX_METADATA, _CHUNK = 4096, 64 * 1024
_MAX_JOB_ENTRIES = 8
_TEMP_PATTERN = re.compile(r"\.specstyle-(artifact|metadata)\.[0-9a-f]{32}\.tmp\Z")
_FINAL_BY_KIND = {"artifact": "artifact.png", "metadata": "metadata.json"}
_LIMIT_BY_KIND = {"artifact": _MAX_PNG, "metadata": _MAX_METADATA}
_Identity = tuple[int, int]


def _unavailable() -> InfrastructureError:
    return InfrastructureError("production artifact store unavailable")


def _corrupted() -> InfrastructureError:
    return InfrastructureError("production artifact store corrupted")


def _pairs_to_dict(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError("duplicate metadata key")
    return result


def _reject_constant(_value: str) -> NoReturn:
    raise ValueError("invalid numeric constant")


def _close_fd(fd: int) -> None:
    try:
        os.close(fd)
    except OSError:
        raise _unavailable() from None


def _close_quietly(*fds: int) -> None:
    for fd in fds:
        try:
            os.close(fd)
        except OSError:
            pass


def _close_fds(fds: tuple[int, ...]) -> None:
    failed = False
    for fd in fds:
        try:
            _close_fd(fd)
        except InfrastructureError:
            failed = True
    if failed:
        raise _unavailable()


def _directory_is_secure(fd: int, identity: _Identity) -> None:
    try:
        before = os.fstat(fd)
        if (
            not stat.S_ISDIR(before.st_mode)
            or (before.st_dev, before.st_uid) != identity
        ):
            raise _corrupted()
        os.fchmod(fd, 0o700)
        after = os.fstat(fd)
    except InfrastructureError:
        raise
    except OSError:
        raise _unavailable() from None
    if (
        not stat.S_ISDIR(after.st_mode)
        or (after.st_dev, after.st_uid) != identity
        or stat.S_IMODE(after.st_mode) != 0o700
    ):
        raise _corrupted()


def _fstat(fd: int) -> os.stat_result:
    try:
        return os.fstat(fd)
    except OSError:
        raise _unavailable() from None


def _named_stat(directory_fd: int, name: str) -> os.stat_result:
    try:
        return os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except OSError:
        raise _corrupted() from None


def _require_regular(
    result: os.stat_result,
    identity: _Identity,
    *,
    links: int | None,
    minimum: int,
    maximum: int,
) -> None:
    if (
        not stat.S_ISREG(result.st_mode)
        or (result.st_dev, result.st_uid) != identity
        or stat.S_IMODE(result.st_mode) != 0o600
        or (links is not None and result.st_nlink != links)
        or not minimum <= result.st_size <= maximum
    ):
        raise _corrupted()


def _same_file(first: os.stat_result, second: os.stat_result) -> bool:
    return (first.st_dev, first.st_ino) == (second.st_dev, second.st_ino)


def _same_snapshot(first: os.stat_result, second: os.stat_result) -> bool:
    fields = ("st_dev", "st_ino", "st_uid", "st_mode", "st_nlink", "st_size")
    times = ("st_mtime_ns", "st_ctime_ns")
    return all(getattr(first, key) == getattr(second, key) for key in fields + times)


def _fsync(fd: int) -> None:
    try:
        os.fsync(fd)
    except OSError:
        raise _unavailable() from None


def _open_directory(
    parent_fd: int, name: str, identity: _Identity, *, create: bool
) -> tuple[int | None, bool]:
    created = False
    try:
        fd = os.open(name, _DIR_FLAGS, dir_fd=parent_fd)
    except FileNotFoundError:
        if not create:
            return None, False
        try:
            os.mkdir(name, 0o700, dir_fd=parent_fd)
            created = True
        except FileExistsError:
            pass
        except OSError:
            raise _unavailable() from None
        try:
            fd = os.open(name, _DIR_FLAGS, dir_fd=parent_fd)
        except OSError:
            raise _corrupted() from None
    except OSError:
        raise _corrupted() from None
    try:
        _directory_is_secure(fd, identity)
        if created:
            _fsync(parent_fd)
        return fd, created
    except Exception:
        _close_quietly(fd)
        raise


def _open_scope(root_fd, identity, job_id, artifact_id, create) -> tuple[int, ...]:
    opened: list[int] = []
    try:
        for name in ("jobs", job_id.value, "artifacts", artifact_id.value):
            parent_fd = root_fd if not opened else opened[-1]
            fd, _ = _open_directory(parent_fd, name, identity, create=create)
            if fd is None:
                _close_fds(tuple(reversed(opened)))
                return ()
            if create:
                _fsync(parent_fd)
            opened.append(fd)
        return tuple(opened)
    except Exception:
        _close_quietly(*reversed(opened))
        raise


def _read_exact_bounded(fd: int, expected: int, maximum: int) -> bytes:
    if (
        type(expected) is not int
        or type(maximum) is not int
        or not 1 <= expected <= maximum
    ):
        raise _corrupted()
    chunks: list[bytes] = []
    total = 0
    while total < expected:
        amount = min(_CHUNK, expected - total)
        try:
            chunk = os.read(fd, amount)
        except OSError:
            raise _unavailable() from None
        if type(chunk) is not bytes or not chunk or len(chunk) > amount:
            raise _corrupted()
        chunks.append(chunk)
        total += len(chunk)
    try:
        extra = os.read(fd, 1)
    except OSError:
        raise _unavailable() from None
    if type(extra) is not bytes or extra:
        raise _corrupted()
    return b"".join(chunks)


def _inspect_open_file(
    fd: int,
    directory_fd: int,
    name: str,
    identity: _Identity,
    expected: int,
    links: int,
) -> os.stat_result:
    opened = _fstat(fd)
    named = _named_stat(directory_fd, name)
    _require_regular(opened, identity, links=links, minimum=expected, maximum=expected)
    _require_regular(named, identity, links=links, minimum=expected, maximum=expected)
    if not _same_file(opened, named):
        raise _corrupted()
    return opened


def _read_file(
    directory_fd: int,
    name: str,
    identity: _Identity,
    *,
    missing_ok: bool,
    expected: int | None,
    maximum: int,
    sync: bool = False,
) -> bytes | None:
    try:
        fd = os.open(name, _READ_FLAGS, dir_fd=directory_fd)
    except FileNotFoundError:
        if missing_ok:
            return None
        raise _corrupted() from None
    except OSError:
        raise _corrupted() from None
    try:
        initial = _fstat(fd)
        size = initial.st_size if expected is None else expected
        before = _inspect_open_file(fd, directory_fd, name, identity, size, 1)
        if not 1 <= size <= maximum:
            raise _corrupted()
        content = _read_exact_bounded(fd, size, maximum)
        after = _inspect_open_file(fd, directory_fd, name, identity, size, 1)
        if not _same_snapshot(before, after):
            raise _corrupted()
        if sync:
            _fsync(fd)
            durable = _inspect_open_file(fd, directory_fd, name, identity, size, 1)
            if not _same_snapshot(after, durable):
                raise _corrupted()
    except Exception:
        _close_quietly(fd)
        raise
    _close_fd(fd)
    return content


def _write_all(fd: int, content: bytes) -> None:
    written = 0
    while written < len(content):
        try:
            amount = os.write(fd, content[written : written + _CHUNK])
        except OSError:
            raise _unavailable() from None
        if amount <= 0:
            raise _unavailable()
        written += amount


def _open_temp(directory_fd: int, kind: str, identity: _Identity) -> tuple[str, int]:
    try:
        token = secrets.token_hex(16)
    except Exception:
        raise _unavailable() from None
    if type(token) is not str or re.fullmatch(r"[0-9a-f]{32}", token) is None:
        raise _unavailable()
    name = f".specstyle-{kind}.{token}.tmp"
    try:
        fd = os.open(name, _WRITE_FLAGS, 0o600, dir_fd=directory_fd)
    except FileExistsError:
        raise _corrupted() from None
    except OSError:
        raise _unavailable() from None
    try:
        _inspect_open_file(fd, directory_fd, name, identity, 0, 1)
    except Exception:
        _close_quietly(fd)
        raise
    return name, fd


def _cleanup_owned_quietly(directory_fd: int, name: str, fd: int) -> None:
    try:
        opened = os.fstat(fd)
        named = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if _same_file(opened, named):
            os.unlink(name, dir_fd=directory_fd)
            os.fsync(directory_fd)
    except Exception:
        pass


def _unlink_owned(directory_fd: int, name: str, fd: int, links: int) -> None:
    try:
        opened = os.fstat(fd)
        named = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        if links == 2:
            return
        raise _corrupted() from None
    except OSError:
        raise _corrupted() from None
    if not _same_file(opened, named) or opened.st_nlink != links:
        raise _corrupted()
    try:
        os.unlink(name, dir_fd=directory_fd)
    except OSError:
        raise _unavailable() from None


def _claim_temp(directory_fd: int, temp: str, final: str) -> bool:
    try:
        os.link(
            temp,
            final,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
            follow_symlinks=False,
        )
    except FileExistsError:
        return False
    except OSError:
        raise _unavailable() from None
    return True


def _atomic_publish(
    directory_fd: int,
    kind: str,
    content: bytes,
    identity: _Identity,
) -> None:
    final, maximum = _FINAL_BY_KIND[kind], _LIMIT_BY_KIND[kind]
    temp, fd = _open_temp(directory_fd, kind, identity)
    linked = False
    try:
        _write_all(fd, content)
        _inspect_open_file(fd, directory_fd, temp, identity, len(content), 1)
        _fsync(fd)
        _inspect_open_file(fd, directory_fd, temp, identity, len(content), 1)
        linked = _claim_temp(directory_fd, temp, final)
        if not linked:
            current = _read_file(
                directory_fd,
                final,
                identity,
                missing_ok=False,
                expected=len(content),
                maximum=maximum,
            )
            if current != content:
                raise _corrupted()
        else:
            _inspect_open_file(fd, directory_fd, final, identity, len(content), 2)
        _unlink_owned(directory_fd, temp, fd, 2 if linked else 1)
        _fsync(directory_fd)
        if linked:
            _inspect_open_file(fd, directory_fd, final, identity, len(content), 1)
    except Exception:
        if not linked:
            _cleanup_owned_quietly(directory_fd, temp, fd)
        _close_quietly(fd)
        raise
    _close_fd(fd)


def _encode_metadata(job_id: JobId, artifact: GeneratedArtifact) -> bytes:
    metadata = {
        "schema": _SCHEMA,
        "job_id": job_id.value,
        "artifact_id": artifact.ref.artifact_id.value,
        "content_sha256": artifact.ref.sha256.value,
        "size_bytes": len(artifact.content),
        "media_type": "image/png",
        "request_hash": artifact.request_hash.value,
        "generation_fingerprint": artifact.generation_fingerprint.value,
    }
    return json.dumps(
        metadata,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")


def _parse_metadata(content, job_id, artifact_id) -> dict[str, object]:
    try:
        value = json.loads(
            content.decode("ascii"),
            object_pairs_hook=_pairs_to_dict,
            parse_constant=_reject_constant,
        )
        if type(value) is not dict or set(value) != _METADATA_KEYS:
            raise ValueError
        if (
            json.dumps(
                value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
            ).encode("ascii")
            != content
        ):
            raise ValueError
        if (
            value["schema"] != _SCHEMA
            or value["job_id"] != job_id.value
            or value["artifact_id"] != artifact_id.value
            or value["media_type"] != "image/png"
            or type(value["size_bytes"]) is not int
            or not 1 <= value["size_bytes"] <= _MAX_PNG
        ):
            raise ValueError
        Sha256(value["content_sha256"])
        Sha256(value["request_hash"])
        Sha256(value["generation_fingerprint"])
        return value
    except (DomainError, TypeError, UnicodeError, ValueError):
        raise _corrupted() from None


def _artifact_from(metadata: dict[str, object], content: bytes) -> GeneratedArtifact:
    try:
        if (
            len(content) != metadata["size_bytes"]
            or hash_bytes(content).value != metadata["content_sha256"]
        ):
            raise ValueError
        return GeneratedArtifact(
            ArtifactRef(
                ArtifactId(metadata["artifact_id"]),
                Sha256(metadata["content_sha256"]),
            ),
            content,
            Sha256(metadata["request_hash"]),
            Sha256(metadata["generation_fingerprint"]),
        )
    except (DomainError, TypeError, ValueError):
        raise _corrupted() from None


def _validate_artifact(artifact: GeneratedArtifact) -> GeneratedArtifact:
    try:
        if type(artifact) is not GeneratedArtifact:
            raise DomainError("invalid production artifact")
        rebuilt = GeneratedArtifact(
            ArtifactRef(
                ArtifactId(artifact.ref.artifact_id.value),
                Sha256(artifact.ref.sha256.value),
            ),
            artifact.content,
            Sha256(artifact.request_hash.value),
            Sha256(artifact.generation_fingerprint.value),
        )
        if rebuilt != artifact or not 1 <= len(rebuilt.content) <= _MAX_PNG:
            raise DomainError("invalid production artifact")
        return rebuilt
    except DomainError:
        raise DomainError("invalid production artifact") from None
    except Exception:
        raise DomainError("invalid production artifact") from None


def _validate_artifact_ref(artifact_ref: ArtifactRef) -> ArtifactRef:
    try:
        if type(artifact_ref) is not ArtifactRef:
            raise ValueError
        rebuilt = ArtifactRef(
            ArtifactId(artifact_ref.artifact_id.value),
            Sha256(artifact_ref.sha256.value),
        )
        if rebuilt != artifact_ref:
            raise ValueError
        return rebuilt
    except Exception:
        raise DomainError("invalid production artifact reference") from None


def _validate_artifact_id(artifact_id: ArtifactId) -> ArtifactId:
    try:
        if type(artifact_id) is not ArtifactId:
            raise ValueError
        rebuilt = ArtifactId(artifact_id.value)
        if rebuilt != artifact_id:
            raise ValueError
        return rebuilt
    except Exception:
        raise DomainError("invalid production artifact id") from None


def _read_committed(
    artifact_fd: int,
    identity: _Identity,
    job_id: JobId,
    artifact_id: ArtifactId,
    *,
    sync: bool = False,
) -> GeneratedArtifact | None:
    raw_metadata = _read_file(
        artifact_fd,
        "metadata.json",
        identity,
        missing_ok=True,
        expected=None,
        maximum=_MAX_METADATA,
    )
    if raw_metadata is None:
        return None
    metadata = _parse_metadata(raw_metadata, job_id, artifact_id)
    content = _read_file(
        artifact_fd,
        "artifact.png",
        identity,
        missing_ok=False,
        expected=int(metadata["size_bytes"]),
        maximum=_MAX_PNG,
        sync=sync,
    )
    if content is None:
        raise _corrupted()
    artifact = _artifact_from(metadata, content)
    if sync:
        durable_metadata = _read_file(
            artifact_fd,
            "metadata.json",
            identity,
            missing_ok=False,
            expected=len(raw_metadata),
            maximum=_MAX_METADATA,
            sync=True,
        )
        if durable_metadata != raw_metadata:
            raise _corrupted()
        _fsync(artifact_fd)
    return artifact


def _namespace_stats(job_fd: int, identity: _Identity) -> dict[str, os.stat_result]:
    names: list[str] = []
    try:
        with os.scandir(job_fd) as entries:
            for entry in entries:
                if type(entry.name) is not str:
                    raise _corrupted()
                names.append(entry.name)
                if len(names) > _MAX_JOB_ENTRIES:
                    raise _corrupted()
    except InfrastructureError:
        raise
    except OSError:
        raise _unavailable() from None
    results: dict[str, os.stat_result] = {}
    for name in names:
        match = _TEMP_PATTERN.fullmatch(name)
        kind = match.group(1) if match is not None else None
        if name == "artifact.png":
            minimum, maximum = 1, _MAX_PNG
        elif name == "metadata.json":
            minimum, maximum = 1, _MAX_METADATA
        elif kind is not None:
            minimum, maximum = 0, _LIMIT_BY_KIND[kind]
        else:
            raise _corrupted()
        result = _named_stat(job_fd, name)
        _require_regular(result, identity, links=None, minimum=minimum, maximum=maximum)
        results[name] = result
    return results


def _alias_plans(
    names: tuple[str, ...], results: dict[str, os.stat_result]
) -> tuple[tuple[str, str], ...]:
    aliases: dict[str, list[str]] = {final: [] for final in _FINAL_BY_KIND.values()}
    for name in names:
        match = _TEMP_PATTERN.fullmatch(name)
        if match is not None:
            aliases[_FINAL_BY_KIND[match.group(1)]].append(name)
    plans: list[tuple[str, str]] = []
    for final, temps in aliases.items():
        final_stat = results.get(final)
        if final_stat is None:
            if temps:
                raise _corrupted()
            continue
        if not temps:
            if final_stat.st_nlink != 1:
                raise _corrupted()
            continue
        if len(temps) != 1:
            raise _corrupted()
        temp = temps[0]
        if final_stat.st_nlink != 2 or not _same_file(final_stat, results[temp]):
            raise _corrupted()
        plans.append((temp, final))
    return tuple(plans)


def _recover_alias(job_fd: int, temp: str, final: str, identity: _Identity) -> None:
    before, target = _named_stat(job_fd, temp), _named_stat(job_fd, final)
    maximum = _LIMIT_BY_KIND[_TEMP_PATTERN.fullmatch(temp).group(1)]  # type: ignore[union-attr]
    _require_regular(before, identity, links=2, minimum=1, maximum=maximum)
    if not _same_file(before, target):
        raise _corrupted()
    try:
        os.unlink(temp, dir_fd=job_fd)
    except OSError:
        raise _unavailable() from None
    _fsync(job_fd)
    after = _named_stat(job_fd, final)
    _require_regular(after, identity, links=1, minimum=1, maximum=maximum)
    if not _same_file(before, after):
        raise _corrupted()


def _recover_namespace(job_fd: int, identity: _Identity) -> None:
    results = _namespace_stats(job_fd, identity)
    for temp, final in _alias_plans(tuple(results), results):
        _recover_alias(job_fd, temp, final, identity)


class _JobLockHolder:
    __slots__ = ("lock", "__weakref__")

    def __init__(self) -> None:
        self.lock = threading.RLock()


class _ProductionArtifactRepository:
    __slots__ = ("_store", "_job_id", "_holder")

    def __init__(self, store, job_id, holder) -> None:
        self._store = store
        self._job_id = job_id
        self._holder: _JobLockHolder | None = holder

    def put(self, artifact: GeneratedArtifact, /) -> None:
        holder = self._holder
        if holder is None:
            raise InfrastructureError("production artifact repository closed")
        artifact = _validate_artifact(artifact)
        with holder.lock:
            self._put_locked(artifact)

    def _put_locked(self, artifact: GeneratedArtifact) -> None:
        root_fd, identity = self._store._open_root()
        fds = _open_scope(
            root_fd, identity, self._job_id, artifact.ref.artifact_id, True
        )
        if not fds:
            raise _unavailable()
        try:
            self._put_open(fds[-1], identity, artifact)
        except Exception:
            _close_quietly(*reversed(fds))
            raise
        _close_fds(tuple(reversed(fds)))

    def _put_open(
        self, artifact_fd: int, identity: _Identity, artifact: GeneratedArtifact
    ) -> None:
        _recover_namespace(artifact_fd, identity)
        committed = _read_committed(
            artifact_fd,
            identity,
            self._job_id,
            artifact.ref.artifact_id,
            sync=True,
        )
        if committed is not None:
            if committed != artifact:
                raise _corrupted()
            return
        current = _read_file(
            artifact_fd,
            "artifact.png",
            identity,
            missing_ok=True,
            expected=len(artifact.content),
            maximum=_MAX_PNG,
            sync=True,
        )
        if current is None:
            _atomic_publish(artifact_fd, "artifact", artifact.content, identity)
        elif current != artifact.content:
            raise _corrupted()
        else:
            _fsync(artifact_fd)
        metadata = _encode_metadata(self._job_id, artifact)
        if not 1 <= len(metadata) <= _MAX_METADATA:
            raise DomainError("invalid production artifact")
        _atomic_publish(artifact_fd, "metadata", metadata, identity)

    def __call__(self, artifact_ref: ArtifactRef, /) -> GeneratedArtifact | None:
        holder = self._holder
        if holder is None:
            raise InfrastructureError("production artifact repository closed")
        artifact_ref = _validate_artifact_ref(artifact_ref)
        with holder.lock:
            artifact = self._read_by_id_locked(artifact_ref.artifact_id)
            return (
                artifact if artifact is None or artifact.ref == artifact_ref else None
            )

    def get_by_id(self, artifact_id: ArtifactId, /) -> GeneratedArtifact | None:
        holder = self._holder
        if holder is None:
            raise InfrastructureError("production artifact repository closed")
        artifact_id = _validate_artifact_id(artifact_id)
        with holder.lock:
            return self._read_by_id_locked(artifact_id)

    def _read_by_id_locked(self, artifact_id: ArtifactId) -> GeneratedArtifact | None:
        root_fd, identity = self._store._open_root()
        fds = _open_scope(root_fd, identity, self._job_id, artifact_id, False)
        if not fds:
            return None
        try:
            _recover_namespace(fds[-1], identity)
            artifact = _read_committed(fds[-1], identity, self._job_id, artifact_id)
        except Exception:
            _close_quietly(*reversed(fds))
            raise
        _close_fds(tuple(reversed(fds)))
        return artifact

    def close(self) -> None:
        self._holder = None


class _ProductionArtifactStore:
    __slots__ = "_root_fd _root_identity _root_inode _lock_guard _locks _closed".split()

    def __init__(self, root_fd: int, root_stat: os.stat_result) -> None:
        self._root_fd = root_fd
        self._root_identity = (root_stat.st_dev, root_stat.st_uid)
        self._root_inode = root_stat.st_ino
        self._lock_guard = threading.Lock()
        self._locks = weakref.WeakValueDictionary()
        self._closed = False

    def _open_root(self) -> tuple[int, _Identity]:
        if self._closed:
            raise InfrastructureError("production artifact store closed")
        return self._root_fd, self._root_identity

    def for_job(self, job_id: JobId, /) -> _ProductionArtifactRepository:
        self._open_root()
        if type(job_id) is not JobId:
            raise DomainError("invalid production artifact job")
        rebuilt = JobId(job_id.value)
        key = (self._root_identity[0], self._root_inode, rebuilt.value)
        with self._lock_guard:
            holder = self._locks.setdefault(key, _JobLockHolder())
        return _ProductionArtifactRepository(self, rebuilt, holder)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        fd, self._root_fd = self._root_fd, -1
        _close_fd(fd)


def _open_production_artifact_store(root_fd: int, /) -> _ProductionArtifactStore:
    if type(root_fd) is not int or root_fd < 0:
        raise DomainError("invalid production artifact root")
    duplicated = -1
    try:
        duplicated = os.dup(root_fd)
        os.set_inheritable(duplicated, False)
        root_stat = os.fstat(duplicated)
        if not stat.S_ISDIR(root_stat.st_mode):
            raise ValueError
    except (OSError, ValueError):
        if duplicated >= 0:
            _close_quietly(duplicated)
        raise InfrastructureError("invalid production artifact root") from None
    return _ProductionArtifactStore(duplicated, root_stat)
