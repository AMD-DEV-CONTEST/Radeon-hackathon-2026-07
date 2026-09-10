"""Audited, crash-recoverable transactions for production context migrations."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
from types import MappingProxyType
from typing import Callable, Iterator, Mapping, Sequence

from specstyle.errors import DomainError
from specstyle.production.context_config import load_production_context_config

__all__ = (
    "ContextMigrationError",
    "ContextMigrationPlan",
    "ContextMigrationPolicyError",
    "ContextSnapshot",
    "LoaderExpectation",
    "run_context_migration",
    "thaw_json",
)

_MAX_CONTEXT_BYTES = 1024 * 1024
_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
_FILE_READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW
_PLAN_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_AUDIT_SCHEMA = re.compile(r"specstyle\.[a-z0-9.-]+\.v[1-9][0-9]*\Z")
if hasattr(os, "O_CLOEXEC"):
    _DIRECTORY_FLAGS |= os.O_CLOEXEC
    _FILE_READ_FLAGS |= os.O_CLOEXEC


class ContextMigrationError(RuntimeError):
    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


class ContextMigrationPolicyError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class LoaderExpectation:
    status: str
    exact_error: str | None = None

    def __post_init__(self) -> None:
        valid = (self.status == "PASS" and self.exact_error is None) or (
            self.status == "EXPECTED_EXACT_REJECTION"
            and type(self.exact_error) is str
            and bool(self.exact_error)
        )
        if not valid:
            raise ValueError("invalid loader expectation")


@dataclass(frozen=True, slots=True)
class ContextSnapshot:
    raw: bytes
    sha256: str
    document: Mapping[str, object]
    loaded: object | None
    loader_error: str | None

    def __post_init__(self) -> None:
        if (
            type(self.raw) is not bytes
            or not _valid_digest(self.sha256)
            or not isinstance(self.document, MappingProxyType)
            or ((self.loaded is None) == (self.loader_error is None))
        ):
            raise ValueError("invalid context snapshot")


Policy = Callable[[ContextSnapshot], None]
Transform = Callable[[ContextSnapshot], object]


@dataclass(frozen=True, slots=True)
class ContextMigrationPlan:
    plan_id: str
    audit_schema: str
    source_loader: LoaderExpectation
    target_loader: LoaderExpectation
    recognize_source: Policy
    recognize_target: Policy
    transform: Transform
    applied_status: str
    already_status: str
    rollback_status: str

    def __post_init__(self) -> None:
        if (
            type(self.plan_id) is not str
            or _PLAN_ID.fullmatch(self.plan_id) is None
            or type(self.audit_schema) is not str
            or _AUDIT_SCHEMA.fullmatch(self.audit_schema) is None
            or type(self.source_loader) is not LoaderExpectation
            or type(self.target_loader) is not LoaderExpectation
            or any(
                not callable(value)
                for value in (
                    self.recognize_source,
                    self.recognize_target,
                    self.transform,
                )
            )
            or any(
                type(value) is not str or not value
                for value in (
                    self.applied_status,
                    self.already_status,
                    self.rollback_status,
                )
            )
        ):
            raise ValueError("invalid context migration plan")


def _valid_digest(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _freeze_json(value: object) -> object:
    if type(value) is dict:
        return MappingProxyType(
            {key: _freeze_json(item) for key, item in value.items()}
        )
    if type(value) is list:
        return tuple(_freeze_json(item) for item in value)
    if type(value) in {str, int, float, bool} or value is None:
        return value
    raise ContextMigrationError("CONTEXT_JSON_INVALID")


def thaw_json(value: object) -> object:
    if isinstance(value, MappingProxyType):
        return {key: thaw_json(item) for key, item in value.items()}
    if type(value) is tuple:
        return [thaw_json(item) for item in value]
    return value


def _result(status: str, reason: str, **fields: object) -> dict[str, object]:
    return {"schema_version": 1, "status": status, "reason_code": reason, **fields}


def _validate_directory(fd: int, label: str, *, private: bool = False) -> None:
    try:
        info = os.fstat(fd)
    except OSError as exc:
        raise ContextMigrationError(f"{label.upper()}_UNAVAILABLE") from exc
    mode = stat.S_IMODE(info.st_mode)
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid not in {0, os.geteuid()}
        or mode & 0o022
        or (private and (info.st_uid != os.geteuid() or mode != 0o700))
    ):
        raise ContextMigrationError(f"{label.upper()}_UNTRUSTED")


@contextmanager
def _open_root(path: Path, label: str, *, private: bool = False) -> Iterator[int]:
    try:
        fd = os.open(path, _DIRECTORY_FLAGS)
    except OSError as exc:
        raise ContextMigrationError(f"{label.upper()}_UNAVAILABLE") from exc
    try:
        _validate_directory(fd, label, private=private)
        yield fd
    finally:
        os.close(fd)


def _validate_context_file(info: os.stat_result) -> None:
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid not in {0, os.geteuid()}
        or stat.S_IMODE(info.st_mode) != 0o600
        or info.st_nlink != 1
        or not 0 < info.st_size <= _MAX_CONTEXT_BYTES
    ):
        raise ContextMigrationError("CONTEXT_FILE_UNTRUSTED")


@contextmanager
def _open_context_file(config_fd: int) -> Iterator[int]:
    try:
        fd = os.open("context.json", _FILE_READ_FLAGS, dir_fd=config_fd)
    except OSError as exc:
        raise ContextMigrationError("CONTEXT_FILE_UNAVAILABLE") from exc
    try:
        _validate_context_file(os.fstat(fd))
        yield fd
    finally:
        os.close(fd)


def _read_fd(fd: int) -> bytes:
    try:
        info = os.fstat(fd)
        _validate_context_file(info)
        os.lseek(fd, 0, os.SEEK_SET)
        value = os.read(fd, info.st_size + 1)
    except OSError as exc:
        raise ContextMigrationError("CONTEXT_READ_FAILED") from exc
    if len(value) != info.st_size or len(value) > _MAX_CONTEXT_BYTES:
        raise ContextMigrationError("CONTEXT_READ_FAILED")
    return value


def _identity(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_uid,
        info.st_gid,
        info.st_nlink,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _loader_outcome(
    config_fd: int, evidence_fd: int
) -> tuple[object | None, str | None]:
    try:
        return load_production_context_config(config_fd, evidence_fd), None
    except DomainError as exc:
        return None, str(exc)
    except Exception as exc:
        raise ContextMigrationError("CONTEXT_VALIDATION_FAILED") from exc


def _capture_snapshot(
    config_fd: int, evidence_fd: int
) -> tuple[ContextSnapshot, tuple[int, ...]]:
    with _open_context_file(config_fd) as held:
        raw = _read_fd(held)
        identity = _identity(os.fstat(held))
    loaded, loader_error = _loader_outcome(config_fd, evidence_fd)
    with _open_context_file(config_fd) as current:
        if _identity(os.fstat(current)) != identity or _read_fd(current) != raw:
            raise ContextMigrationError("CONTEXT_CHANGED_DURING_MIGRATION")
    try:
        document = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContextMigrationError("CONTEXT_JSON_INVALID") from exc
    frozen = _freeze_json(document)
    if not isinstance(frozen, MappingProxyType):
        raise ContextMigrationError("CONTEXT_JSON_INVALID")
    return ContextSnapshot(raw, _sha256(raw), frozen, loaded, loader_error), identity


def _expect(snapshot: ContextSnapshot, expectation: LoaderExpectation) -> None:
    if expectation.status == "PASS":
        valid = snapshot.loaded is not None and snapshot.loader_error is None
    else:
        valid = (
            snapshot.loaded is None and snapshot.loader_error == expectation.exact_error
        )
    if not valid:
        raise ContextMigrationPolicyError("loader expectation mismatch")


def _matches(
    snapshot: ContextSnapshot, plan: ContextMigrationPlan, source: bool
) -> bool:
    try:
        _expect(snapshot, plan.source_loader if source else plan.target_loader)
        (plan.recognize_source if source else plan.recognize_target)(snapshot)
        return True
    except (ContextMigrationPolicyError, KeyError, TypeError, ValueError, IndexError):
        return False


@contextmanager
def _migration_lock(audit_fd: int) -> Iterator[None]:
    flags = os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    fd = -1
    try:
        fd = os.open("production-context-migration.lock", flags, 0o600, dir_fd=audit_fd)
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_nlink != 1
        ):
            raise ContextMigrationError("MIGRATION_LOCK_UNTRUSTED")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    except BlockingIOError as exc:
        raise ContextMigrationError("MIGRATION_BUSY") from exc
    except OSError as exc:
        raise ContextMigrationError("MIGRATION_LOCK_UNAVAILABLE") from exc
    finally:
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass


def _write_all(fd: int, value: bytes) -> None:
    offset = 0
    try:
        while offset < len(value):
            written = os.write(fd, value[offset:])
            if written <= 0:
                raise OSError
            offset += written
        os.fsync(fd)
    except OSError as exc:
        raise ContextMigrationError("MIGRATION_WRITE_FAILED") from exc


def _remove_audit_files(root_fd: int, names: Sequence[str]) -> None:
    try:
        for name in names:
            try:
                os.unlink(name, dir_fd=root_fd)
            except FileNotFoundError:
                pass
        os.fsync(root_fd)
    except OSError as exc:
        raise ContextMigrationError("AUDIT_CLEANUP_FAILED") from exc


def _existing_audit_matches(root_fd: int, name: str, value: bytes) -> bool:
    try:
        fd = os.open(name, _FILE_READ_FLAGS, dir_fd=root_fd)
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise ContextMigrationError("AUDIT_CONFLICT") from exc
    try:
        if _read_fd(fd) != value:
            raise ContextMigrationError("AUDIT_CONFLICT")
        return True
    finally:
        os.close(fd)


def _cleanup_audit_temps(root_fd: int, name: str) -> None:
    prefix = f".{name}.tmp-"
    try:
        candidates = [
            entry for entry in os.listdir(root_fd) if entry.startswith(prefix)
        ]
        for candidate in candidates:
            fd = os.open(candidate, _FILE_READ_FLAGS, dir_fd=root_fd)
            info = os.fstat(fd)
            os.close(fd)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_nlink not in {1, 2}
            ):
                raise ContextMigrationError("AUDIT_RECOVERY_FAILED")
            os.unlink(candidate, dir_fd=root_fd)
        if candidates:
            os.fsync(root_fd)
    except ContextMigrationError:
        raise
    except OSError as exc:
        raise ContextMigrationError("AUDIT_RECOVERY_FAILED") from exc


def _write_once(root_fd: int, name: str, value: bytes) -> None:
    _cleanup_audit_temps(root_fd, name)
    if _existing_audit_matches(root_fd, name, value):
        return
    temp = f".{name}.tmp-{secrets.token_hex(12)}"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    try:
        fd = os.open(temp, flags, 0o600, dir_fd=root_fd)
    except OSError as exc:
        raise ContextMigrationError("AUDIT_WRITE_FAILED") from exc
    try:
        _write_all(fd, value)
    except Exception:
        os.close(fd)
        _remove_audit_files(root_fd, (temp,))
        raise
    except BaseException:
        os.close(fd)
        raise
    else:
        os.close(fd)
    try:
        os.link(
            temp, name, src_dir_fd=root_fd, dst_dir_fd=root_fd, follow_symlinks=False
        )
    except FileExistsError:
        _remove_audit_files(root_fd, (temp,))
        if _existing_audit_matches(root_fd, name, value):
            return
        raise ContextMigrationError("AUDIT_CONFLICT")
    except OSError as exc:
        _remove_audit_files(root_fd, (temp,))
        raise ContextMigrationError("AUDIT_WRITE_FAILED") from exc
    try:
        os.unlink(temp, dir_fd=root_fd)
        os.fsync(root_fd)
    except OSError as exc:
        _remove_audit_files(root_fd, (temp, name))
        raise ContextMigrationError("AUDIT_SYNC_FAILED") from exc


def _audit_payload(
    plan: ContextMigrationPlan, status: str, before: str, after: str
) -> bytes:
    return _canonical_json(
        {
            "schema_version": plan.audit_schema,
            "plan_id": plan.plan_id,
            "status": status,
            "before_sha256": before,
            "after_sha256": after,
        }
    )


def _audit_stem(plan: ContextMigrationPlan, before: str, after: str) -> str:
    return f"migration-{plan.plan_id}-{before}-{after}"


def _prepare_audit(
    audit_fd: int,
    plan: ContextMigrationPlan,
    source: ContextSnapshot,
    after: str,
) -> str:
    stem = _audit_stem(plan, source.sha256, after)
    _write_once(audit_fd, f"context-before-{source.sha256}.json", source.raw)
    _write_once(
        audit_fd,
        f"{stem}.prepared.json",
        _audit_payload(plan, "PREPARED", source.sha256, after),
    )
    return f"{stem}.committed.json"


def _create_stage(config_fd: int, raw: bytes) -> tuple[str, int]:
    name = f".production-context-{secrets.token_hex(12)}"
    created = False
    stage_fd: int | None = None
    try:
        os.mkdir(name, 0o700, dir_fd=config_fd)
        created = True
        stage_fd = os.open(name, _DIRECTORY_FLAGS, dir_fd=config_fd)
        _validate_directory(stage_fd, "staged_context", private=True)
        file_fd = os.open(
            "context.json",
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=stage_fd,
        )
        try:
            _write_all(file_fd, raw)
        finally:
            os.close(file_fd)
        os.fsync(stage_fd)
        return name, stage_fd
    except BaseException as exc:
        if stage_fd is not None:
            _cleanup_stage(config_fd, name, stage_fd)
        elif created:
            try:
                os.rmdir(name, dir_fd=config_fd)
                os.fsync(config_fd)
            except OSError as cleanup_exc:
                raise ContextMigrationError("STAGING_CLEANUP_FAILED") from cleanup_exc
        if isinstance(exc, ContextMigrationError):
            raise
        if isinstance(exc, OSError):
            raise ContextMigrationError("STAGING_FAILED") from exc
        raise


def _cleanup_stage(config_fd: int, name: str, stage_fd: int) -> None:
    try:
        try:
            os.unlink("context.json", dir_fd=stage_fd)
        except FileNotFoundError:
            pass
        os.close(stage_fd)
        os.rmdir(name, dir_fd=config_fd)
        os.fsync(config_fd)
    except OSError as exc:
        raise ContextMigrationError("STAGING_CLEANUP_FAILED") from exc


def _online_unchanged(
    config_fd: int, expected_identity: tuple[int, ...], expected_raw: bytes
) -> None:
    with _open_context_file(config_fd) as current:
        if (
            _identity(os.fstat(current)) != expected_identity
            or _read_fd(current) != expected_raw
        ):
            raise ContextMigrationError("CONTEXT_CHANGED_DURING_MIGRATION")


def _publish_stage(config_fd: int, stage_fd: int) -> None:
    try:
        os.replace(
            "context.json", "context.json", src_dir_fd=stage_fd, dst_dir_fd=config_fd
        )
    except OSError as exc:
        raise ContextMigrationError("CONTEXT_PUBLISH_FAILED") from exc


def _sync_config_directory(config_fd: int) -> None:
    try:
        os.fsync(config_fd)
    except OSError as exc:
        raise ContextMigrationError("CONTEXT_SYNC_FAILED") from exc


def _validate_snapshot(
    snapshot: ContextSnapshot, plan: ContextMigrationPlan, *, source: bool
) -> None:
    if not _matches(snapshot, plan, source):
        raise ContextMigrationError(
            "SOURCE_POLICY_REFUSED" if source else "TARGET_POLICY_REFUSED"
        )


def _rollback(
    config_fd: int,
    evidence_fd: int,
    plan: ContextMigrationPlan,
    source: ContextSnapshot,
) -> None:
    name, stage_fd = _create_stage(config_fd, source.raw)
    try:
        staged, _ = _capture_snapshot(stage_fd, evidence_fd)
        _validate_snapshot(staged, plan, source=True)
        _publish_stage(config_fd, stage_fd)
        _sync_config_directory(config_fd)
        online, _ = _capture_snapshot(config_fd, evidence_fd)
        if online.sha256 != source.sha256:
            raise ContextMigrationError("ROLLBACK_FAILED")
        _validate_snapshot(online, plan, source=True)
    except Exception as exc:
        raise ContextMigrationError("ROLLBACK_FAILED") from exc
    finally:
        _cleanup_stage(config_fd, name, stage_fd)


def _target_raw(plan: ContextMigrationPlan, source: ContextSnapshot) -> bytes:
    try:
        transformed = plan.transform(source)
        return _canonical_json(transformed)
    except (
        ContextMigrationPolicyError,
        KeyError,
        TypeError,
        ValueError,
        IndexError,
    ) as exc:
        raise ContextMigrationError("SOURCE_POLICY_REFUSED") from exc


def _apply(
    config_fd: int,
    evidence_fd: int,
    audit_fd: int,
    plan: ContextMigrationPlan,
    source: ContextSnapshot,
    source_identity: tuple[int, ...],
    target_raw: bytes,
) -> dict[str, object]:
    after = _sha256(target_raw)
    committed_name = _prepare_audit(audit_fd, plan, source, after)
    name, stage_fd = _create_stage(config_fd, target_raw)
    published = False
    try:
        staged, _ = _capture_snapshot(stage_fd, evidence_fd)
        if staged.sha256 != after:
            raise ContextMigrationError("TARGET_POLICY_REFUSED")
        _validate_snapshot(staged, plan, source=False)
        _online_unchanged(config_fd, source_identity, source.raw)
        _publish_stage(config_fd, stage_fd)
        published = True
        _sync_config_directory(config_fd)
        online, target_identity = _capture_snapshot(config_fd, evidence_fd)
        if online.sha256 != after:
            raise ContextMigrationError("TARGET_POLICY_REFUSED")
        _validate_snapshot(online, plan, source=False)
        _online_unchanged(config_fd, target_identity, online.raw)
        _write_once(
            audit_fd,
            committed_name,
            _audit_payload(plan, "COMMITTED", source.sha256, after),
        )
        return _result(
            plan.applied_status,
            "OK",
            before_sha256=source.sha256,
            after_sha256=after,
        )
    except Exception:
        if published:
            _rollback(config_fd, evidence_fd, plan, source)
            return _result(
                plan.rollback_status,
                "POST_PUBLISH_FAILURE",
                before_sha256=source.sha256,
            )
        raise
    finally:
        _cleanup_stage(config_fd, name, stage_fd)


def _read_audit_file(audit_fd: int, name: str) -> bytes:
    try:
        fd = os.open(name, _FILE_READ_FLAGS, dir_fd=audit_fd)
    except OSError as exc:
        raise ContextMigrationError("AUDIT_RECOVERY_FAILED") from exc
    try:
        return _read_fd(fd)
    except Exception as exc:
        raise ContextMigrationError("AUDIT_RECOVERY_FAILED") from exc
    finally:
        os.close(fd)


def _recover_commit(
    config_fd: int,
    evidence_fd: int,
    audit_fd: int,
    plan: ContextMigrationPlan,
    before: str,
    target: ContextSnapshot,
    target_identity: tuple[int, ...],
) -> None:
    stem = _audit_stem(plan, before, target.sha256)
    backup = _read_audit_file(audit_fd, f"context-before-{before}.json")
    prepared = _read_audit_file(audit_fd, f"{stem}.prepared.json")
    if _sha256(backup) != before or prepared != _audit_payload(
        plan, "PREPARED", before, target.sha256
    ):
        raise ContextMigrationError("AUDIT_RECOVERY_FAILED")
    name, stage_fd = _create_stage(config_fd, backup)
    try:
        source, _ = _capture_snapshot(stage_fd, evidence_fd)
        _validate_snapshot(source, plan, source=True)
        if _sha256(_target_raw(plan, source)) != target.sha256:
            raise ContextMigrationError("AUDIT_RECOVERY_FAILED")
    finally:
        _cleanup_stage(config_fd, name, stage_fd)
    _online_unchanged(config_fd, target_identity, target.raw)
    _write_once(
        audit_fd,
        f"{stem}.committed.json",
        _audit_payload(plan, "COMMITTED", before, target.sha256),
    )


def _run_locked(
    config_fd: int,
    evidence_fd: int,
    audit_fd: int,
    plan: ContextMigrationPlan,
    expected_before: str,
    apply: bool,
) -> dict[str, object]:
    snapshot, identity = _capture_snapshot(config_fd, evidence_fd)
    if _matches(snapshot, plan, source=True):
        if snapshot.sha256 != expected_before:
            raise ContextMigrationError("EXPECTED_DIGEST_MISMATCH")
        target_raw = _target_raw(plan, snapshot)
        after = _sha256(target_raw)
        if not apply:
            return _result(
                "REFUSED",
                "DRY_RUN",
                before_sha256=snapshot.sha256,
                after_sha256=after,
            )
        return _apply(
            config_fd,
            evidence_fd,
            audit_fd,
            plan,
            snapshot,
            identity,
            target_raw,
        )
    if _matches(snapshot, plan, source=False):
        if snapshot.sha256 == expected_before:
            return _result(
                plan.already_status,
                "OK",
                before_sha256=snapshot.sha256,
                after_sha256=snapshot.sha256,
            )
        if not apply:
            raise ContextMigrationError("EXPECTED_DIGEST_MISMATCH")
        _recover_commit(
            config_fd,
            evidence_fd,
            audit_fd,
            plan,
            expected_before,
            snapshot,
            identity,
        )
        return _result(
            plan.already_status,
            "RECOVERED_COMMIT",
            before_sha256=expected_before,
            after_sha256=snapshot.sha256,
        )
    raise ContextMigrationError("SOURCE_POLICY_REFUSED")


def run_context_migration(
    *,
    config_root: Path,
    context_evidence_root: Path,
    audit_root: Path,
    expected_before_sha256: str,
    apply: bool,
    plan: ContextMigrationPlan,
) -> dict[str, object]:
    if (
        not _valid_digest(expected_before_sha256)
        or type(apply) is not bool
        or type(plan) is not ContextMigrationPlan
    ):
        return _result("REFUSED", "INVALID_ARGUMENT")
    try:
        with _open_root(Path(config_root), "config") as config_fd:
            with _open_root(Path(context_evidence_root), "evidence") as evidence_fd:
                if not apply:
                    return _run_locked(
                        config_fd,
                        evidence_fd,
                        -1,
                        plan,
                        expected_before_sha256,
                        False,
                    )
                with _open_root(Path(audit_root), "audit", private=True) as audit_fd:
                    with _migration_lock(audit_fd):
                        return _run_locked(
                            config_fd,
                            evidence_fd,
                            audit_fd,
                            plan,
                            expected_before_sha256,
                            True,
                        )
    except ContextMigrationError as exc:
        return _result("REFUSED", exc.reason_code)
    except Exception:
        return _result("REFUSED", "INTERNAL_FAILURE")
