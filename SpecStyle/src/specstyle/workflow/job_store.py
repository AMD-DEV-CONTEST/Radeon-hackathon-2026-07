"""Descriptor-rooted JobStore facade.

Workflow candidates are validated before I/O.  Persistent bytes are decoded
as infrastructure state and therefore fail closed as ``job store corrupted``.
The fixed-slot marker protocol is intentionally irreversible: old readers do
not understand its internal names and will reject migrated jobs.
"""

from __future__ import annotations

import os
import sys
import threading
import weakref
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from specstyle.domain.identifiers import JobId
from specstyle.errors import DomainError, InfrastructureError
from specstyle.workflow import _job_store_codec as codec
from specstyle.workflow import _job_store_fs as fs
from specstyle.workflow import _job_store_transaction as transaction
from specstyle.workflow.job_models import (
    Event,
    EventType,
    Job,
    JobBudget,
    JobSnapshot,
    JobState,
    JobStatus,
)
from specstyle.workflow.state_machine import replay_events, validate_transition

_canonical_json = codec.canonical_json
_event_to_primitive = codec.event_to_primitive
_JOB_LOCKS_GUARD = threading.Lock()
_NAMESPACE_HOLDERS: weakref.WeakValueDictionary[tuple[int, int], _NamespaceHolder] = (
    weakref.WeakValueDictionary()
)


class _JobLockHolder:
    __slots__ = ("lock", "__weakref__")

    def __init__(self) -> None:
        self.lock = threading.RLock()


class _NamespaceHolder:
    __slots__ = (
        "jobs",
        "exports",
        "exports_lock",
        "condition",
        "epoch",
        "mutations",
        "jobs_identity",
        "__weakref__",
    )

    def __init__(self) -> None:
        self.jobs: weakref.WeakValueDictionary[str, _JobLockHolder] = (
            weakref.WeakValueDictionary()
        )
        self.exports: weakref.WeakValueDictionary[str, object] = (
            weakref.WeakValueDictionary()
        )
        self.exports_lock = threading.Lock()
        self.condition = threading.Condition(threading.Lock())
        self.epoch = 0
        self.mutations = 0
        self.jobs_identity: fs.Identity | None = None


@dataclass(frozen=True, slots=True)
class _DecodedState:
    persisted: transaction.State
    snapshot: JobSnapshot | None
    events: tuple[Event, ...]
    state: JobState | None


_OpenedJob = tuple[int, int, fs.Identity, fs.Identity]


def _canonical_genesis(job: Job) -> JobSnapshot:
    if type(job) is not Job:
        raise DomainError("invalid job snapshot") from None
    genesis = Job(
        job.job_id,
        job.compiled_spec_hash,
        job.cohort_profiles,
        JobBudget(job.budget.max_attempts_per_item),
        JobStatus.CREATED,
        job.created_at,
        job.created_at,
    )
    return JobSnapshot(codec.SNAPSHOT_VERSION, genesis, 0, (), ())


def _validated_snapshot(
    job_id: JobId, snapshot: JobSnapshot, events: tuple[Event, ...]
) -> JobState:
    if (
        type(job_id) is not JobId
        or type(snapshot) is not JobSnapshot
        or type(events) is not tuple
        or type(snapshot.last_sequence) is not int
        or snapshot.job.job_id != job_id
        or not 0 <= snapshot.last_sequence <= len(events)
    ):
        raise DomainError("invalid job snapshot") from None
    prefix = replay_events(
        _canonical_genesis(snapshot.job), events[: snapshot.last_sequence]
    )
    expected = JobSnapshot(
        codec.SNAPSHOT_VERSION,
        prefix.job,
        prefix.last_sequence,
        prefix.attempt_ids,
        prefix.bundle_names,
    )
    if snapshot != expected:
        raise DomainError("invalid job snapshot") from None
    return replay_events(expected, events[snapshot.last_sequence :])


def _safe_job_id(value: object, message: str) -> JobId:
    try:
        if type(value) is not JobId or type(value.value) is not str:
            raise DomainError(message)
        return JobId(str.__str__(value.value))
    except (AttributeError, TypeError, ValueError, DomainError):
        raise DomainError(message) from None


def _corrupted() -> InfrastructureError:
    return InfrastructureError("job store corrupted")


def _io_failed() -> InfrastructureError:
    return InfrastructureError("job store io failed")


@contextmanager
def _translate_storage():
    try:
        yield
    except transaction.GenerationExhausted:
        raise InfrastructureError("job store generation exhausted") from None
    except fs.CorruptStore:
        raise _corrupted() from None
    except fs.StoreIO:
        raise _io_failed() from None


def _root_dev(identity: fs.Identity | tuple[int, ...]) -> int:
    return identity.dev if isinstance(identity, fs.Identity) else identity[0]


def _read_state_file(
    directory_fd: int,
    directory_identity: fs.Identity | tuple[int, ...],
    name: str,
    expected_identity: fs.Identity,
) -> bytes:
    limits = {
        transaction.SNAPSHOT: (1, transaction.MAX_SNAPSHOT),
        transaction.EVENTS: (0, transaction.MAX_EVENTS),
    }
    record = fs.read_file(
        directory_fd, name, *limits[name], _root_dev(directory_identity)
    )
    assert record is not None
    if not record.identity.same_inode(expected_identity):
        raise _corrupted()
    return record.data


def _decode_persisted(job_id: JobId, persisted: transaction.State) -> _DecodedState:
    if persisted.absent:
        return _DecodedState(persisted, None, (), None)
    try:
        assert persisted.snapshot is not None
        snapshot = codec.decode_snapshot(persisted.snapshot)
        events = codec.decode_events(job_id, persisted.events or b"")
        state = _validated_snapshot(job_id, snapshot, events)
    except Exception:
        raise _corrupted() from None
    return _DecodedState(persisted, snapshot, events, state)


def _validated_state_from_fd(
    job_fd: int,
    directory_identity: fs.Identity | tuple[int, ...],
    job_id: JobId,
) -> JobState | None:
    with _translate_storage():
        first = transaction.read(job_fd, _root_dev(directory_identity))
        decoded = _decode_persisted(job_id, first)
        second = transaction.read(job_fd, _root_dev(directory_identity))
        if first != second:
            raise fs.CorruptStore
    if decoded.state is None and not first.slot_only:
        raise _corrupted()
    return decoded.state


def _namespace_holder(identity: tuple[int, int]) -> _NamespaceHolder:
    with _JOB_LOCKS_GUARD:
        holder = _NAMESPACE_HOLDERS.get(identity)
        if holder is None:
            holder = _NamespaceHolder()
            _NAMESPACE_HOLDERS[identity] = holder
        return holder


def _snapshot_bytes_equivalent(left: bytes, right: bytes) -> bool:
    try:
        return codec.decode_snapshot(left) == codec.decode_snapshot(right)
    except Exception:
        return False


class JobStore:
    """Single-process workflow repository pinned to one directory inode."""

    def __init__(self, root: Path, /) -> None:
        if not isinstance(root, Path):
            raise DomainError("invalid job store root")
        try:
            root_fd = os.open(os.fspath(root), fs.DIRECTORY_FLAGS)
        except OSError:
            raise DomainError("invalid job store root") from None
        try:
            self._initialize(root_fd)
        except BaseException:
            fs.close_quietly(root_fd)
            raise

    @classmethod
    def from_root_fd(cls, root_fd: int, /) -> JobStore:
        if type(root_fd) is not int:
            raise DomainError("invalid job store root")
        try:
            duplicate = fs.duplicate_fd(root_fd)
        except fs.StoreIO:
            raise DomainError("invalid job store root") from None
        instance = cls.__new__(cls)
        try:
            instance._initialize(duplicate)
        except BaseException:
            fs.close_quietly(duplicate)
            raise
        return instance

    def _initialize(self, root_fd: int) -> None:
        try:
            result = os.fstat(root_fd)
            identity = fs.validate_directory(result, result.st_dev)
        except (OSError, fs.CorruptStore):
            raise DomainError("invalid job store root") from None
        self._root_fd = root_fd
        self._root_identity = (identity.dev, identity.ino)
        self._root_dev = identity.dev
        self._namespace_holder: _NamespaceHolder | None = _namespace_holder(
            self._root_identity
        )
        self._lease_condition = threading.Condition(threading.Lock())
        self._lease_count = 0
        self._lease_threads: dict[int, int] = {}
        self._lifecycle = "OPEN"
        self._finalizer = weakref.finalize(self, fs.close_quietly, root_fd)

    @contextmanager
    def _operation(self):
        thread_id = threading.get_ident()
        with self._lease_condition:
            if self._lifecycle != "OPEN":
                raise InfrastructureError("job store closed")
            try:
                operation_fd = fs.duplicate_fd(self._root_fd)
            except fs.StoreIO:
                raise _io_failed() from None
            self._lease_count += 1
            self._lease_threads[thread_id] = self._lease_threads.get(thread_id, 0) + 1
        primary: BaseException | None = None
        try:
            yield operation_fd
        except BaseException as cause:
            primary = cause
            raise
        finally:
            self._finish_operation(operation_fd, thread_id, primary)

    def _finish_operation(
        self, operation_fd: int, thread_id: int, primary: BaseException | None
    ) -> None:
        close_error = False
        try:
            fs.close_owned(operation_fd)
        except fs.StoreIO:
            close_error = True
        with self._lease_condition:
            self._lease_count -= 1
            remaining = self._lease_threads[thread_id] - 1
            if remaining:
                self._lease_threads[thread_id] = remaining
            else:
                del self._lease_threads[thread_id]
            if self._lease_count == 0:
                self._lease_condition.notify_all()
        if close_error and primary is None:
            raise _io_failed()

    def close(self) -> None:
        thread_id = threading.get_ident()
        with self._lease_condition:
            if self._lease_threads.get(thread_id, 0):
                raise InfrastructureError("job store closed")
            if self._lifecycle == "CLOSED":
                return
            if self._lifecycle == "CLOSING":
                while self._lifecycle != "CLOSED":
                    self._lease_condition.wait()
                return
            self._lifecycle = "CLOSING"
            while self._lease_count:
                self._lease_condition.wait()
            root_fd, self._root_fd = self._root_fd, -1
        failure = False
        try:
            fs.close_owned(root_fd)
        except fs.StoreIO:
            failure = True
        finally:
            self._finalizer.detach()
            self._namespace_holder = None
            with self._lease_condition:
                self._lifecycle = "CLOSED"
                self._lease_condition.notify_all()
        if failure:
            raise _io_failed()

    def _job_lock_holder(self, job_id: JobId, /) -> _JobLockHolder:
        namespace = self._namespace_holder
        if namespace is None:
            raise InfrastructureError("job store closed")
        with _JOB_LOCKS_GUARD:
            holder = namespace.jobs.get(job_id.value)
            if holder is None:
                holder = _JobLockHolder()
                namespace.jobs[job_id.value] = holder
            return holder

    @contextmanager
    def _namespace_mutation(self):
        namespace = self._namespace_holder
        if namespace is None:
            raise InfrastructureError("job store closed")
        with namespace.condition:
            namespace.mutations += 1
        try:
            yield
        finally:
            with namespace.condition:
                namespace.mutations -= 1
                namespace.epoch += 1
                namespace.condition.notify_all()

    @staticmethod
    def _stable_epoch(namespace: _NamespaceHolder) -> int:
        with namespace.condition:
            while namespace.mutations:
                namespace.condition.wait()
            return namespace.epoch

    def _bind_jobs_identity(self, identity: fs.Identity | None) -> None:
        namespace = self._namespace_holder
        if namespace is None:
            raise InfrastructureError("job store closed")
        with namespace.condition:
            expected = namespace.jobs_identity
            if identity is None:
                if expected is not None:
                    raise fs.CorruptStore
            elif expected is None:
                namespace.jobs_identity = identity
            elif not expected.same_inode(identity):
                raise fs.CorruptStore

    @contextmanager
    def _job_lock(self, job_id: JobId, /):
        holder = self._job_lock_holder(job_id)
        with holder.lock:
            yield

    def _open_job(
        self, root_fd: int, job_id: JobId, *, create: bool = False
    ) -> _OpenedJob | None:
        jobs = (
            fs.open_or_create_directory(root_fd, "jobs", self._root_dev)
            if create
            else fs.open_directory(root_fd, "jobs", self._root_dev, missing_ok=True)
        )
        if jobs is None:
            self._bind_jobs_identity(None)
            return None
        self._bind_jobs_identity(jobs[1])
        jobs_fd = jobs[0]
        try:
            job = (
                fs.open_or_create_directory(jobs_fd, job_id.value, self._root_dev)
                if create
                else fs.open_directory(
                    jobs_fd, job_id.value, self._root_dev, missing_ok=True
                )
            )
            if job is None:
                fs.close_owned(jobs_fd)
                return None
            return jobs_fd, job[0], jobs[1], job[1]
        except BaseException:
            fs.close_quietly(jobs_fd)
            raise

    @staticmethod
    def _close_job(opened: _OpenedJob | None) -> None:
        if opened is None:
            return
        primary = sys.exception()
        close_failure: fs.StoreIO | None = None
        for descriptor in (opened[1], opened[0]):
            try:
                fs.close_owned(descriptor, primary)
            except fs.StoreIO as cause:
                close_failure = cause
        if close_failure is not None and primary is None:
            raise close_failure

    def _read_job(self, root_fd: int, job_id: JobId) -> transaction.State:
        opened = self._open_job(root_fd, job_id)
        if opened is None:
            return transaction.State(None, None, None, None, None, None)
        try:
            state = transaction.read(opened[1], self._root_dev)
            self._require_job_binding(root_fd, opened, job_id)
            return state
        finally:
            self._close_job(opened)

    def _require_job_binding(
        self, root_fd: int, opened: _OpenedJob, job_id: JobId
    ) -> None:
        try:
            jobs = fs.named_identity(root_fd, "jobs", self._root_dev)
            job = fs.named_identity(opened[0], job_id.value, self._root_dev)
        except FileNotFoundError:
            raise fs.CorruptStore from None
        if not jobs.same_inode(opened[2]) or not job.same_inode(opened[3]):
            raise fs.CorruptStore

    def _decode_job(self, root_fd: int, job_id: JobId) -> _DecodedState:
        with _translate_storage():
            return _decode_persisted(job_id, self._read_job(root_fd, job_id))

    def _commit(
        self,
        root_fd: int,
        job_id: JobId,
        expected: transaction.State,
        snapshot: bytes,
        events: bytes | None,
    ) -> None:
        with self._namespace_mutation(), _translate_storage():
            opened = self._open_job(root_fd, job_id, create=True)
            assert opened is not None
            try:
                transaction.commit(
                    opened[1],
                    self._root_dev,
                    expected,
                    snapshot,
                    events,
                    _snapshot_bytes_equivalent,
                )
                self._require_job_binding(root_fd, opened, job_id)
            finally:
                self._close_job(opened)

    def list_job_ids(self, /) -> tuple[JobId, ...]:
        with self._operation() as root_fd, _translate_storage():
            namespace = self._namespace_holder
            assert namespace is not None
            while True:
                epoch = self._stable_epoch(namespace)
                try:
                    result = self._list_once(root_fd)
                except fs.CorruptStore:
                    if self._stable_epoch(namespace) != epoch:
                        continue
                    raise
                if self._stable_epoch(namespace) != epoch:
                    continue
                if result is None:
                    raise fs.CorruptStore
                return result

    def _list_once(self, root_fd: int) -> tuple[JobId, ...] | None:
        opened = fs.open_directory(root_fd, "jobs", self._root_dev, missing_ok=True)
        if opened is None:
            self._bind_jobs_identity(None)
            try:
                fs.named_identity(root_fd, "jobs", self._root_dev)
            except FileNotFoundError:
                return ()
            raise fs.CorruptStore
        self._bind_jobs_identity(opened[1])
        jobs_fd = opened[0]
        try:
            before = fs.directory_names(jobs_fd)
            listed = self._validate_list_entries(jobs_fd, before)
            if listed is None or set(fs.directory_names(jobs_fd)) != set(before):
                return None
            current = fs.named_identity(root_fd, "jobs", self._root_dev)
            if not current.same_inode(opened[1]):
                raise fs.CorruptStore
            return tuple(sorted(listed, key=lambda item: item.value))
        except FileNotFoundError:
            raise fs.CorruptStore from None
        finally:
            fs.close_owned(jobs_fd)

    def _validate_list_entries(
        self, jobs_fd: int, names: tuple[str, ...]
    ) -> list[JobId] | None:
        result: list[JobId] = []
        for name in names:
            try:
                job_id = JobId(name)
            except DomainError:
                raise fs.CorruptStore from None
            try:
                checked, identity = self._validated_listed_job(jobs_fd, name)
                current = fs.named_identity(jobs_fd, name, self._root_dev)
                if checked is None:
                    continue
                if checked != job_id or not current.same_inode(identity):
                    raise fs.CorruptStore
                result.append(job_id)
            except FileNotFoundError:
                return None
            except InfrastructureError as cause:
                if cause.args == ("job store corrupted",):
                    raise fs.CorruptStore from None
                raise
        return result

    def _validated_listed_job(
        self, jobs_fd: int, name: str, /
    ) -> tuple[JobId | None, fs.Identity]:
        try:
            job_id = JobId(name)
        except DomainError:
            raise fs.CorruptStore from None
        opened = fs.open_directory(jobs_fd, name, self._root_dev)
        assert opened is not None
        try:
            with self._job_lock(job_id):
                state = _validated_state_from_fd(opened[0], opened[1], job_id)
            return job_id if state is not None else None, opened[1]
        finally:
            fs.close_owned(opened[0])

    def load(self, job_id: JobId, /) -> JobState:
        job_id = _safe_job_id(job_id, "invalid job event")
        with self._operation() as root_fd, self._job_lock(job_id):
            decoded = self._decode_job(root_fd, job_id)
            if decoded.state is None:
                raise DomainError("job not found") from None
            return decoded.state

    def get_snapshot(self, job_id: JobId, /) -> JobSnapshot | None:
        job_id = _safe_job_id(job_id, "invalid job event")
        with self._operation() as root_fd, self._job_lock(job_id):
            return self._decode_job(root_fd, job_id).snapshot

    def save_snapshot(self, job_id: JobId, snapshot: JobSnapshot, /) -> None:
        snapshot, job_id = self._validate_snapshot_candidate(job_id, snapshot)
        with self._operation() as root_fd, self._job_lock(job_id):
            decoded = self._decode_job(root_fd, job_id)
            self._validate_snapshot_update(job_id, snapshot, decoded)
            self._commit(
                root_fd,
                job_id,
                decoded.persisted,
                codec.encode_snapshot(snapshot),
                decoded.persisted.events,
            )

    @staticmethod
    def _validate_snapshot_candidate(
        job_id: JobId, snapshot: JobSnapshot
    ) -> tuple[JobSnapshot, JobId]:
        try:
            rebuilt = codec.rebuild_snapshot(snapshot)
            if type(job_id) is not JobId or rebuilt.job.job_id != job_id:
                raise DomainError("invalid job snapshot")
            return rebuilt, _safe_job_id(job_id, "invalid job snapshot")
        except (AttributeError, TypeError, DomainError):
            raise DomainError("invalid job snapshot") from None

    @staticmethod
    def _validate_snapshot_update(
        job_id: JobId, snapshot: JobSnapshot, decoded: _DecodedState
    ) -> None:
        try:
            _validated_snapshot(job_id, snapshot, decoded.events)
            if decoded.snapshot is None:
                if snapshot != _canonical_genesis(snapshot.job):
                    raise DomainError("invalid job snapshot")
                return
            old = decoded.snapshot
            if (
                _canonical_genesis(old.job) != _canonical_genesis(snapshot.job)
                or snapshot.last_sequence < old.last_sequence
                or snapshot.last_sequence == old.last_sequence
                and snapshot != old
            ):
                raise DomainError("invalid job snapshot")
        except (AttributeError, TypeError, DomainError):
            raise DomainError("invalid job snapshot") from None

    def append_event(self, job_id: JobId, event: Event, /) -> Event:
        if type(job_id) is not JobId or type(event) is not Event:
            raise DomainError("invalid job event") from None
        job_id = _safe_job_id(job_id, "invalid job event")
        event = codec.rebuild_event(event)
        with self._operation() as root_fd, self._job_lock(job_id):
            decoded = self._decode_job(root_fd, job_id)
            if decoded.state is None or decoded.snapshot is None:
                raise DomainError("job not found") from None
            finalized = self._validate_event(job_id, event, decoded.state)
            events = (decoded.persisted.events or b"") + codec.encode_event(finalized)
            if len(events) > transaction.MAX_EVENTS:
                raise _io_failed()
            self._commit(
                root_fd,
                job_id,
                decoded.persisted,
                decoded.persisted.snapshot,
                events,
            )
            return finalized

    @staticmethod
    def _validate_event(job_id: JobId, event: Event, state: JobState) -> Event:
        if state.job.terminal:
            raise DomainError("job is terminal") from None
        attempts = {item.value for item in state.attempt_ids}
        bundles = set(state.bundle_names)
        payload = event.payload
        if (
            event.event_type is EventType.ATTEMPT_STARTED
            and payload.attempt_id.value in attempts
        ):
            raise DomainError("duplicate job attempt") from None
        if (
            event.event_type is EventType.REPAIR_STEP
            and payload.child_attempt_id.value in attempts
        ):
            raise DomainError("duplicate job attempt") from None
        if (
            event.event_type is EventType.EXPORT_PUBLISHED
            and payload.bundle_name in bundles
        ):
            raise DomainError("duplicate job export") from None
        if event.job_id != job_id or event.from_state is not state.job.status:
            raise DomainError("invalid job transition") from None
        validate_transition(state.job.status, event.to_state, event.event_type)
        finalized = Event(
            state.last_sequence + 1,
            event.job_id,
            event.event_type,
            event.from_state,
            event.to_state,
            event.timestamp,
            event.payload,
        )
        try:
            replay_events(
                JobSnapshot(
                    codec.SNAPSHOT_VERSION,
                    state.job,
                    state.last_sequence,
                    state.attempt_ids,
                    state.bundle_names,
                ),
                (finalized,),
            )
        except (DomainError, TypeError, AttributeError):
            raise DomainError("invalid job event") from None
        return finalized

    def list_events(self, job_id: JobId, /) -> tuple[Event, ...]:
        job_id = _safe_job_id(job_id, "invalid job event")
        with self._operation() as root_fd, self._job_lock(job_id):
            return self._decode_job(root_fd, job_id).events
