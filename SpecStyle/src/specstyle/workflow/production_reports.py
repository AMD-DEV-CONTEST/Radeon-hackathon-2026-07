"""Private durable storage for per-attempt production verification reports."""

from __future__ import annotations

import json
import os
import re
import stat
import threading
import weakref
from typing import NoReturn

from specstyle.domain.artifacts import ArtifactRef
from specstyle.domain.enums import (
    RuleLevel,
    RuleScope,
    RuleStatus,
    StaticApplicability,
)
from specstyle.domain.identifiers import (
    ArtifactId,
    AttemptId,
    JobId,
    RuleId,
    Sha256,
)
from specstyle.errors import DomainError, InfrastructureError
from specstyle.generation.protocols import _rebuild_request
from specstyle.generation.requests import GenerationRequest
from specstyle.observability.hashing import hash_bytes
from specstyle.verification.rule_models import (
    GatePolicy,
    RuleDefinition,
    RuleResult,
    VerificationReport,
)
from specstyle.workflow import production_artifacts as _storage

__all__ = ()

_SCHEMA = "specstyle.production_report.v1"
_MEDIA_TYPE = "application/json"
_MAX_REPORT = 1024 * 1024
_MAX_METADATA = 4096
_MAX_ENTRIES = 8
_TEMP_PATTERN = re.compile(r"\.specstyle-(report|metadata)\.[0-9a-f]{32}\.tmp\Z")
_FINAL_BY_KIND = {"report": "report.json", "metadata": "metadata.json"}
_LIMIT_BY_KIND = {"report": _MAX_REPORT, "metadata": _MAX_METADATA}
_METADATA_KEYS = frozenset(
    "schema job_id attempt_id artifact_id artifact_sha256 request_hash "
    "generation_fingerprint compiled_spec_hash output_profile report_sha256 "
    "size_bytes media_type".split()
)
_REPORT_KEYS = frozenset({"schema", "artifacts", "rules", "results"})
_ARTIFACT_KEYS = frozenset({"artifact_id", "sha256"})
_RULE_KEYS = frozenset(
    {"rule_id", "level", "scope", "required", "applicability", "gate_policy"}
)
_POLICY_KEYS = frozenset({"on_fail", "on_unverifiable", "on_warning"})
_RESULT_KEYS = frozenset({"rule_id", "status", "affected_artifact_ids", "score"})
_Identity = tuple[int, int]


def _unavailable() -> InfrastructureError:
    return InfrastructureError("production report store unavailable")


def _corrupted() -> InfrastructureError:
    return InfrastructureError("production report store corrupted")


def _translate(error: InfrastructureError) -> InfrastructureError:
    if error.args == ("production artifact store corrupted",):
        return _corrupted()
    if error.args == ("production artifact store unavailable",):
        return _unavailable()
    return error


def _pairs_to_dict(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value = dict(pairs)
    if len(value) != len(pairs):
        raise ValueError
    return value


def _reject_constant(_value: str) -> NoReturn:
    raise ValueError


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def _exact_dict(value: object, keys: frozenset[str]) -> dict[str, object]:
    if type(value) is not dict or set(value) != keys:
        raise ValueError
    return value


def _string(value: object) -> str:
    if type(value) is not str:
        raise ValueError
    return value


def _string_list(value: object) -> tuple[str, ...]:
    if type(value) is not list or any(type(item) is not str for item in value):
        raise ValueError
    return tuple(value)


def _validate_request(
    request: object, job_id: JobId, attempt_id: AttemptId
) -> GenerationRequest:
    try:
        rebuilt = _rebuild_request(request)
        if rebuilt.job_id != job_id or rebuilt.attempt_id != attempt_id:
            raise ValueError
        return rebuilt
    except Exception:
        raise DomainError("invalid production report") from None


def _rebuild_rule(rule: object) -> RuleDefinition:
    if type(rule) is not RuleDefinition:
        raise ValueError
    policy = rule.gate_policy
    if type(policy) is not GatePolicy:
        raise ValueError
    return RuleDefinition(
        RuleId(rule.rule_id.value),
        RuleLevel(rule.level.value),
        RuleScope(rule.scope.value),
        rule.required,
        StaticApplicability(rule.applicability.value),
        GatePolicy(policy.on_fail, policy.on_unverifiable, policy.on_warning),
    )


def _rebuild_result(result: object) -> RuleResult:
    if type(result) is not RuleResult:
        raise ValueError
    return RuleResult(
        RuleId(result.rule_id.value),
        RuleStatus(result.status.value),
        tuple(ArtifactId(item.value) for item in result.affected_artifact_ids),
        result.score,
    )


def _validate_report(report: object) -> VerificationReport:
    try:
        if type(report) is not VerificationReport or len(report.artifacts) != 1:
            raise ValueError
        artifact = report.artifacts[0]
        if type(artifact) is not ArtifactRef:
            raise ValueError
        rebuilt = VerificationReport(
            (
                ArtifactRef(
                    ArtifactId(artifact.artifact_id.value),
                    Sha256(artifact.sha256.value),
                ),
            ),
            tuple(_rebuild_rule(rule) for rule in report.rules),
            tuple(_rebuild_result(result) for result in report.results),
        )
        if rebuilt != report:
            raise ValueError
        return rebuilt
    except Exception:
        raise DomainError("invalid production report") from None


def _report_primitive(report: VerificationReport) -> dict[str, object]:
    return {
        "schema": _SCHEMA,
        "artifacts": [
            {
                "artifact_id": artifact.artifact_id.value,
                "sha256": artifact.sha256.value,
            }
            for artifact in report.artifacts
        ],
        "rules": [_rule_primitive(rule) for rule in report.rules],
        "results": [_result_primitive(result) for result in report.results],
    }


def _rule_primitive(rule: RuleDefinition) -> dict[str, object]:
    return {
        "rule_id": rule.rule_id.value,
        "level": rule.level.value,
        "scope": rule.scope.value,
        "required": rule.required,
        "applicability": rule.applicability.value,
        "gate_policy": {
            "on_fail": rule.gate_policy.on_fail,
            "on_unverifiable": rule.gate_policy.on_unverifiable,
            "on_warning": rule.gate_policy.on_warning,
        },
    }


def _result_primitive(result: RuleResult) -> dict[str, object]:
    return {
        "rule_id": result.rule_id.value,
        "status": result.status.value,
        "affected_artifact_ids": [item.value for item in result.affected_artifact_ids],
        "score": None if result.score is None else result.score.hex(),
    }


def _artifact_from(value: object) -> ArtifactRef:
    value = _exact_dict(value, _ARTIFACT_KEYS)
    return ArtifactRef(
        ArtifactId(_string(value["artifact_id"])),
        Sha256(_string(value["sha256"])),
    )


def _rule_from(value: object) -> RuleDefinition:
    value = _exact_dict(value, _RULE_KEYS)
    policy = _exact_dict(value["gate_policy"], _POLICY_KEYS)
    required = value["required"]
    if type(required) is not bool:
        raise ValueError
    return RuleDefinition(
        RuleId(_string(value["rule_id"])),
        RuleLevel(_string(value["level"])),
        RuleScope(_string(value["scope"])),
        required,
        StaticApplicability(_string(value["applicability"])),
        GatePolicy(
            _string(policy["on_fail"]),
            _string(policy["on_unverifiable"]),
            _string(policy["on_warning"]),
        ),
    )


def _score_from(value: object) -> float | None:
    if value is None:
        return None
    encoded = _string(value)
    score = float.fromhex(encoded)
    if score.hex() != encoded:
        raise ValueError
    return score


def _result_from(value: object) -> RuleResult:
    value = _exact_dict(value, _RESULT_KEYS)
    return RuleResult(
        RuleId(_string(value["rule_id"])),
        RuleStatus(_string(value["status"])),
        tuple(
            ArtifactId(item) for item in _string_list(value["affected_artifact_ids"])
        ),
        _score_from(value["score"]),
    )


def _decode_report(content: bytes) -> VerificationReport:
    try:
        value = json.loads(
            content.decode("ascii"),
            object_pairs_hook=_pairs_to_dict,
            parse_constant=_reject_constant,
        )
        if _canonical(value) != content:
            raise ValueError
        value = _exact_dict(value, _REPORT_KEYS)
        artifacts, rules, results = (
            value["artifacts"],
            value["rules"],
            value["results"],
        )
        if any(type(items) is not list for items in (artifacts, rules, results)):
            raise ValueError
        report = VerificationReport(
            tuple(_artifact_from(item) for item in artifacts),
            tuple(_rule_from(item) for item in rules),
            tuple(_result_from(item) for item in results),
        )
        if value["schema"] != _SCHEMA or len(report.artifacts) != 1:
            raise ValueError
        return report
    except Exception:
        raise _corrupted() from None


def _encode_metadata(
    request: GenerationRequest, report: VerificationReport, encoded: bytes
) -> bytes:
    artifact = report.artifacts[0]
    return _canonical(
        {
            "schema": _SCHEMA,
            "job_id": request.job_id.value,
            "attempt_id": request.attempt_id.value,
            "artifact_id": artifact.artifact_id.value,
            "artifact_sha256": artifact.sha256.value,
            "request_hash": request.request_hash.value,
            "generation_fingerprint": request.generation_fingerprint.value,
            "compiled_spec_hash": request.compiled_spec.compiled_spec_hash.value,
            "output_profile": request.output_profile,
            "report_sha256": hash_bytes(encoded).value,
            "size_bytes": len(encoded),
            "media_type": _MEDIA_TYPE,
        }
    )


def _decode_metadata(
    content: bytes, job_id: JobId, attempt_id: AttemptId
) -> dict[str, object]:
    try:
        value = json.loads(
            content.decode("ascii"),
            object_pairs_hook=_pairs_to_dict,
            parse_constant=_reject_constant,
        )
        if _canonical(value) != content:
            raise ValueError
        value = _exact_dict(value, _METADATA_KEYS)
        if (
            value["schema"] != _SCHEMA
            or value["job_id"] != job_id.value
            or value["attempt_id"] != attempt_id.value
            or value["media_type"] != _MEDIA_TYPE
            or type(value["size_bytes"]) is not int
            or not 1 <= value["size_bytes"] <= _MAX_REPORT
            or value["output_profile"]
            not in {"xhs_grid", "talking_head_cover", "background_sequence"}
        ):
            raise ValueError
        ArtifactId(_string(value["artifact_id"]))
        for key in (
            "artifact_sha256",
            "request_hash",
            "generation_fingerprint",
            "compiled_spec_hash",
            "report_sha256",
        ):
            Sha256(_string(value[key]))
        return value
    except Exception:
        raise _corrupted() from None


def _open_report_directory(
    root_fd: int,
    identity: _Identity,
    job_id: JobId,
    attempt_id: AttemptId,
    *,
    create: bool,
) -> tuple[int, ...]:
    opened: list[int] = []
    try:
        for name in ("jobs", job_id.value, "reports", attempt_id.value):
            parent_fd = root_fd if not opened else opened[-1]
            fd, _ = _storage._open_directory(parent_fd, name, identity, create=create)
            if fd is None:
                _storage._close_fds(tuple(reversed(opened)))
                return ()
            if create:
                _storage._fsync(parent_fd)
            opened.append(fd)
        return tuple(opened)
    except Exception:
        _storage._close_quietly(*reversed(opened))
        raise


def _namespace_stats(directory_fd: int, identity: _Identity):
    names: list[str] = []
    try:
        with os.scandir(directory_fd) as entries:
            for entry in entries:
                if type(entry.name) is not str:
                    raise _corrupted()
                names.append(entry.name)
                if len(names) > _MAX_ENTRIES:
                    raise _corrupted()
    except InfrastructureError:
        raise
    except OSError:
        raise _unavailable() from None
    results = {}
    for name in names:
        match = _TEMP_PATTERN.fullmatch(name)
        kind = match.group(1) if match is not None else None
        if name == "report.json":
            minimum, maximum = 1, _MAX_REPORT
        elif name == "metadata.json":
            minimum, maximum = 1, _MAX_METADATA
        elif kind is not None:
            minimum, maximum = 0, _LIMIT_BY_KIND[kind]
        else:
            raise _corrupted()
        result = _storage._named_stat(directory_fd, name)
        _storage._require_regular(
            result, identity, links=None, minimum=minimum, maximum=maximum
        )
        results[name] = result
    return results


def _alias_plans(results) -> tuple[tuple[str, str], ...]:
    aliases = {final: [] for final in _FINAL_BY_KIND.values()}
    for name in results:
        match = _TEMP_PATTERN.fullmatch(name)
        if match is not None:
            aliases[_FINAL_BY_KIND[match.group(1)]].append(name)
    plans = []
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
        if final_stat.st_nlink != 2 or not _storage._same_file(
            final_stat, results[temp]
        ):
            raise _corrupted()
        plans.append((temp, final))
    return tuple(plans)


def _recover_alias(
    directory_fd: int, temp: str, final: str, identity: _Identity
) -> None:
    before = _storage._named_stat(directory_fd, temp)
    target = _storage._named_stat(directory_fd, final)
    match = _TEMP_PATTERN.fullmatch(temp)
    if match is None:
        raise _corrupted()
    maximum = _LIMIT_BY_KIND[match.group(1)]
    _storage._require_regular(before, identity, links=2, minimum=1, maximum=maximum)
    if not _storage._same_file(before, target):
        raise _corrupted()
    try:
        os.unlink(temp, dir_fd=directory_fd)
    except OSError:
        raise _unavailable() from None
    _storage._fsync(directory_fd)
    after = _storage._named_stat(directory_fd, final)
    _storage._require_regular(after, identity, links=1, minimum=1, maximum=maximum)
    if not _storage._same_file(before, after):
        raise _corrupted()


def _recover_namespace(directory_fd: int, identity: _Identity) -> None:
    results = _namespace_stats(directory_fd, identity)
    for temp, final in _alias_plans(results):
        _recover_alias(directory_fd, temp, final, identity)


def _atomic_publish(
    directory_fd: int, kind: str, content: bytes, identity: _Identity
) -> None:
    final, maximum = _FINAL_BY_KIND[kind], _LIMIT_BY_KIND[kind]
    temp, fd = _storage._open_temp(directory_fd, kind, identity)
    linked = False
    try:
        _storage._write_all(fd, content)
        _storage._inspect_open_file(fd, directory_fd, temp, identity, len(content), 1)
        _storage._fsync(fd)
        _storage._inspect_open_file(fd, directory_fd, temp, identity, len(content), 1)
        linked = _storage._claim_temp(directory_fd, temp, final)
        if not linked:
            current = _storage._read_file(
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
            _storage._inspect_open_file(
                fd, directory_fd, final, identity, len(content), 2
            )
        _storage._unlink_owned(directory_fd, temp, fd, 2 if linked else 1)
        _storage._fsync(directory_fd)
        if linked:
            _storage._inspect_open_file(
                fd, directory_fd, final, identity, len(content), 1
            )
    except Exception:
        if not linked:
            _storage._cleanup_owned_quietly(directory_fd, temp, fd)
        _storage._close_quietly(fd)
        raise
    _storage._close_fd(fd)


def _sync_metadata(
    directory_fd: int,
    identity: _Identity,
    raw_metadata: bytes,
) -> None:
    durable = _storage._read_file(
        directory_fd,
        "metadata.json",
        identity,
        missing_ok=False,
        expected=len(raw_metadata),
        maximum=_MAX_METADATA,
        sync=True,
    )
    if durable != raw_metadata:
        raise _corrupted()
    _storage._fsync(directory_fd)


def _read_committed(
    directory_fd: int,
    identity: _Identity,
    job_id: JobId,
    attempt_id: AttemptId,
    *,
    sync: bool = False,
) -> tuple[VerificationReport, bytes] | None:
    raw_metadata = _storage._read_file(
        directory_fd,
        "metadata.json",
        identity,
        missing_ok=True,
        expected=None,
        maximum=_MAX_METADATA,
    )
    if raw_metadata is None:
        return None
    metadata = _decode_metadata(raw_metadata, job_id, attempt_id)
    encoded = _storage._read_file(
        directory_fd,
        "report.json",
        identity,
        missing_ok=False,
        expected=int(metadata["size_bytes"]),
        maximum=_MAX_REPORT,
        sync=sync,
    )
    if encoded is None or hash_bytes(encoded).value != metadata["report_sha256"]:
        raise _corrupted()
    report = _decode_report(encoded)
    artifact = report.artifacts[0]
    if (
        artifact.artifact_id.value != metadata["artifact_id"]
        or artifact.sha256.value != metadata["artifact_sha256"]
    ):
        raise _corrupted()
    if sync:
        _sync_metadata(directory_fd, identity, raw_metadata)
    return report, raw_metadata


class _AttemptLockHolder:
    __slots__ = ("lock", "__weakref__")

    def __init__(self) -> None:
        self.lock = threading.RLock()


class _ProductionReportRepository:
    __slots__ = ("_store", "_job_id", "_attempt_id", "_holder")

    def __init__(self, store, job_id, attempt_id, holder) -> None:
        self._store = store
        self._job_id = job_id
        self._attempt_id = attempt_id
        self._holder: _AttemptLockHolder | None = holder

    def put(self, request: GenerationRequest, report: VerificationReport, /) -> None:
        holder = self._holder
        if holder is None:
            raise InfrastructureError("production report repository closed")
        request = _validate_request(request, self._job_id, self._attempt_id)
        report = _validate_report(report)
        with holder.lock:
            try:
                self._put_locked(request, report)
            except InfrastructureError as error:
                raise _translate(error) from None

    def _put_locked(
        self, request: GenerationRequest, report: VerificationReport
    ) -> None:
        encoded = _canonical(_report_primitive(report))
        if not 1 <= len(encoded) <= _MAX_REPORT:
            raise DomainError("invalid production report")
        metadata = _encode_metadata(request, report, encoded)
        if not 1 <= len(metadata) <= _MAX_METADATA:
            raise DomainError("invalid production report")
        root_fd, identity = self._store._open_root()
        fds = _open_report_directory(
            root_fd, identity, self._job_id, self._attempt_id, create=True
        )
        if not fds:
            raise _unavailable()
        try:
            self._put_open(fds[-1], identity, report, encoded, metadata)
        except Exception:
            _storage._close_quietly(*reversed(fds))
            raise
        _storage._close_fds(tuple(reversed(fds)))

    def _put_open(
        self,
        directory_fd: int,
        identity: _Identity,
        report: VerificationReport,
        encoded: bytes,
        metadata: bytes,
    ) -> None:
        _recover_namespace(directory_fd, identity)
        current = _read_committed(
            directory_fd,
            identity,
            self._job_id,
            self._attempt_id,
            sync=True,
        )
        if current is not None:
            if current != (report, metadata):
                raise _corrupted()
            return
        partial = _storage._read_file(
            directory_fd,
            "report.json",
            identity,
            missing_ok=True,
            expected=len(encoded),
            maximum=_MAX_REPORT,
            sync=True,
        )
        if partial is None:
            _atomic_publish(directory_fd, "report", encoded, identity)
        elif partial != encoded:
            raise _corrupted()
        else:
            _storage._fsync(directory_fd)
        _atomic_publish(directory_fd, "metadata", metadata, identity)
        if _read_committed(
            directory_fd,
            identity,
            self._job_id,
            self._attempt_id,
            sync=True,
        ) != (report, metadata):
            raise _corrupted()

    def __call__(self, /) -> VerificationReport | None:
        holder = self._holder
        if holder is None:
            raise InfrastructureError("production report repository closed")
        with holder.lock:
            try:
                return self._read_locked()
            except InfrastructureError as error:
                raise _translate(error) from None

    def _read_locked(self) -> VerificationReport | None:
        root_fd, identity = self._store._open_root()
        fds = _open_report_directory(
            root_fd, identity, self._job_id, self._attempt_id, create=False
        )
        if not fds:
            return None
        try:
            _recover_namespace(fds[-1], identity)
            committed = _read_committed(
                fds[-1], identity, self._job_id, self._attempt_id
            )
        except Exception:
            _storage._close_quietly(*reversed(fds))
            raise
        _storage._close_fds(tuple(reversed(fds)))
        return None if committed is None else committed[0]

    def close(self) -> None:
        self._holder = None


class _ProductionReportStore:
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
            raise InfrastructureError("production report store closed")
        return self._root_fd, self._root_identity

    def for_attempt(
        self, job_id: JobId, attempt_id: AttemptId, /
    ) -> _ProductionReportRepository:
        self._open_root()
        if type(job_id) is not JobId or type(attempt_id) is not AttemptId:
            raise DomainError("invalid production report attempt")
        job, attempt = JobId(job_id.value), AttemptId(attempt_id.value)
        key = (
            self._root_identity[0],
            self._root_inode,
            job.value,
            attempt.value,
        )
        with self._lock_guard:
            holder = self._locks.setdefault(key, _AttemptLockHolder())
        return _ProductionReportRepository(self, job, attempt, holder)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        fd, self._root_fd = self._root_fd, -1
        try:
            _storage._close_fd(fd)
        except InfrastructureError as error:
            raise _translate(error) from None


def _open_production_report_store(root_fd: int, /) -> _ProductionReportStore:
    if type(root_fd) is not int or root_fd < 0:
        raise DomainError("invalid production report root")
    duplicated = -1
    try:
        duplicated = os.dup(root_fd)
        os.set_inheritable(duplicated, False)
        root_stat = os.fstat(duplicated)
        if not stat.S_ISDIR(root_stat.st_mode):
            raise ValueError
    except (OSError, ValueError):
        if duplicated >= 0:
            _storage._close_quietly(duplicated)
        raise InfrastructureError("invalid production report root") from None
    return _ProductionReportStore(duplicated, root_stat)
