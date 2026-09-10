"""Fixed-slot marker transaction protocol for JobStore.

Migration is deliberately one-way: publishing ``MARKER`` makes legacy readers
reject the directory.  PENDING is evidence of an interrupted transaction and
is never recovered or auto-accepted by ordinary reads.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass

from specstyle.workflow import _job_store_fs as fs

MARKER = ".specstyle-state.marker"
MARKER_SWAP = ".specstyle-state.marker.swap"
SNAPSHOT_SWAP = ".specstyle-snapshot.swap"
EVENTS_SWAP = ".specstyle-events.swap"
SNAPSHOT = "snapshot.json"
EVENTS = "events.ndjson"
MAX_MARKER = 1024
MAX_SNAPSHOT = 1024 * 1024
MAX_EVENTS = 64 * 1024 * 1024
MAX_GENERATION = (1 << 63) - 1
_KEYS = {"version", "phase", "generation", "snapshot_sha256", "events_sha256"}
_LIMITS = {
    MARKER: (1, MAX_MARKER),
    MARKER_SWAP: (0, MAX_MARKER),
    SNAPSHOT: (1, MAX_SNAPSHOT),
    SNAPSHOT_SWAP: (0, MAX_SNAPSHOT),
    EVENTS: (0, MAX_EVENTS),
    EVENTS_SWAP: (0, MAX_EVENTS),
}


class GenerationExhausted(Exception):
    """The signed 63-bit generation space has been consumed."""


class _CleanOutcomeUncertain(Exception):
    pass


@dataclass(frozen=True, slots=True)
class Marker:
    phase: str
    generation: int
    snapshot_sha256: str
    events_sha256: str | None


@dataclass(frozen=True, slots=True)
class State:
    snapshot: bytes | None
    events: bytes | None
    snapshot_identity: fs.Identity | None
    events_identity: fs.Identity | None
    marker_identity: fs.Identity | None
    generation: int | None
    slot_only: bool = False

    @property
    def absent(self) -> bool:
        return self.snapshot is None

    @property
    def legacy(self) -> bool:
        return self.snapshot is not None and self.marker_identity is None


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def marker_bytes(
    phase: str, generation: int, snapshot: bytes, events: bytes | None
) -> bytes:
    return _canonical(
        {
            "version": 1,
            "phase": phase,
            "generation": generation,
            "snapshot_sha256": _hash(snapshot),
            "events_sha256": _hash(events) if events is not None else None,
        }
    )


def _pairs(items: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in items:
        if type(key) is not str or key in result:
            raise fs.CorruptStore
        result[key] = value
    return result


def _parse_marker(data: bytes) -> Marker:
    try:
        value = json.loads(
            data,
            object_pairs_hook=_pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(fs.CorruptStore()),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as cause:
        raise fs.CorruptStore from cause
    if type(value) is not dict or set(value) != _KEYS or _canonical(value) != data:
        raise fs.CorruptStore
    return _validate_marker_fields(value)


def _valid_hash(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _validate_marker_fields(value: dict[str, object]) -> Marker:
    generation = value["generation"]
    events_hash = value["events_sha256"]
    if (
        type(value["version"]) is not int
        or value["version"] != 1
        or type(value["phase"]) is not str
        or value["phase"] not in {"CLEAN", "PENDING"}
        or type(generation) is not int
        or not 0 <= generation <= MAX_GENERATION
        or not _valid_hash(value["snapshot_sha256"])
        or events_hash is not None
        and not _valid_hash(events_hash)
    ):
        raise fs.CorruptStore
    return Marker(value["phase"], generation, value["snapshot_sha256"], events_hash)


def _validate_namespace(directory_fd: int, root_dev: int) -> set[str]:
    names = set(fs.directory_names(directory_fd))
    if names - set(_LIMITS):
        raise fs.CorruptStore
    for name in names:
        minimum, maximum = _LIMITS[name]
        fs.inspect_file(directory_fd, name, minimum, maximum, root_dev)
    return names


def _read_finals(directory_fd: int, root_dev: int):
    snapshot = fs.read_file(
        directory_fd, SNAPSHOT, 1, MAX_SNAPSHOT, root_dev, missing_ok=True
    )
    events = fs.read_file(
        directory_fd, EVENTS, 0, MAX_EVENTS, root_dev, missing_ok=True
    )
    return snapshot, events


def _legacy_state(snapshot, events, *, slot_only: bool = False) -> State:
    if snapshot is None:
        if events is not None:
            raise fs.CorruptStore
        return State(None, None, None, None, None, None, slot_only)
    return State(
        snapshot.data,
        events.data if events is not None else None,
        snapshot.identity,
        events.identity if events is not None else None,
        None,
        None,
    )


def read(directory_fd: int, root_dev: int) -> State:
    names = _validate_namespace(directory_fd, root_dev)
    snapshot, events = _read_finals(directory_fd, root_dev)
    marker_record = fs.read_file(
        directory_fd, MARKER, 1, MAX_MARKER, root_dev, missing_ok=True
    )
    if marker_record is None:
        result = _legacy_state(snapshot, events, slot_only=bool(names))
        return _complete_read(directory_fd, root_dev, names, result)
    if snapshot is None:
        raise fs.CorruptStore
    marker = _parse_marker(marker_record.data)
    if marker.phase != "CLEAN":
        raise fs.CorruptStore
    _verify_hashes(marker, snapshot.data, events.data if events else None)
    result = State(
        snapshot.data,
        events.data if events else None,
        snapshot.identity,
        events.identity if events else None,
        marker_record.identity,
        marker.generation,
    )
    return _complete_read(directory_fd, root_dev, names, result)


def _complete_read(
    directory_fd: int, root_dev: int, names: set[str], state: State
) -> State:
    if set(fs.directory_names(directory_fd)) != names:
        raise fs.CorruptStore
    _require_identity(
        directory_fd, SNAPSHOT, state.snapshot_identity, 1, MAX_SNAPSHOT, root_dev
    )
    _require_identity(
        directory_fd, EVENTS, state.events_identity, 0, MAX_EVENTS, root_dev
    )
    _require_identity(
        directory_fd, MARKER, state.marker_identity, 1, MAX_MARKER, root_dev
    )
    return state


def _require_identity(
    directory_fd: int,
    name: str,
    expected: fs.Identity | None,
    minimum: int,
    maximum: int,
    root_dev: int,
) -> None:
    current = fs.inspect_file(
        directory_fd, name, minimum, maximum, root_dev, missing_ok=True
    )
    if current != expected:
        raise fs.CorruptStore


def _verify_hashes(marker: Marker, snapshot: bytes, events: bytes | None) -> None:
    if marker.snapshot_sha256 != _hash(snapshot):
        raise fs.CorruptStore
    if marker.events_sha256 != (_hash(events) if events is not None else None):
        raise fs.CorruptStore


def _same_state(left: State, right: State) -> bool:
    return (
        left.snapshot == right.snapshot
        and left.events == right.events
        and left.generation == right.generation
        and _same_identity(left.snapshot_identity, right.snapshot_identity)
        and _same_identity(left.events_identity, right.events_identity)
        and _same_identity(left.marker_identity, right.marker_identity)
    )


def _same_identity(left: fs.Identity | None, right: fs.Identity | None) -> bool:
    if left is None or right is None:
        return left is right
    return left.same_inode(right)


def genesis(
    directory_fd: int,
    root_dev: int,
    snapshot: bytes,
    equivalent: Callable[[bytes, bytes], bool] | None = None,
) -> State:
    if not 0 < len(snapshot) <= MAX_SNAPSHOT:
        raise fs.StoreIO
    current = read(directory_fd, root_dev)
    if not current.absent:
        if (
            _equivalent_snapshot(current.snapshot, snapshot, equivalent)
            and current.events is None
        ):
            return (
                current
                if not current.legacy
                else _bootstrap(directory_fd, root_dev, current)
            )
        raise fs.CorruptStore
    candidate = fs.write_slot(
        directory_fd, SNAPSHOT_SWAP, snapshot, MAX_SNAPSHOT, root_dev
    )
    try:
        fs.rename_noreplace(directory_fd, SNAPSHOT_SWAP, SNAPSHOT)
    except fs.DestinationExists:
        return _accept_existing_genesis(
            directory_fd, root_dev, snapshot, equivalent, uncertain=False
        )
    except fs.RenameUncertain:
        return _accept_existing_genesis(
            directory_fd, root_dev, snapshot, equivalent, uncertain=True
        )
    _require_published(directory_fd, SNAPSHOT, candidate, MAX_SNAPSHOT, root_dev)
    fs.fsync_directory(directory_fd)
    legacy = read(directory_fd, root_dev)
    return _bootstrap(directory_fd, root_dev, legacy)


def _accept_existing_genesis(
    directory_fd: int,
    root_dev: int,
    snapshot: bytes,
    equivalent: Callable[[bytes, bytes], bool] | None,
    *,
    uncertain: bool,
) -> State:
    concurrent = read(directory_fd, root_dev)
    valid = (
        _equivalent_snapshot(concurrent.snapshot, snapshot, equivalent)
        and concurrent.events is None
    )
    if not valid:
        if uncertain:
            raise fs.RenameUncertain
        raise fs.CorruptStore
    if uncertain:
        fs.fsync_directory(directory_fd)
    return (
        concurrent
        if not concurrent.legacy
        else _bootstrap(directory_fd, root_dev, concurrent)
    )


def _equivalent_snapshot(
    stored: bytes | None,
    candidate: bytes,
    equivalent: Callable[[bytes, bytes], bool] | None,
) -> bool:
    if stored is None:
        return False
    return (
        stored == candidate or equivalent is not None and equivalent(stored, candidate)
    )


def _require_published(
    directory_fd: int,
    name: str,
    expected: fs.Identity,
    maximum: int,
    root_dev: int,
) -> None:
    current = fs.inspect_file(directory_fd, name, 0, maximum, root_dev)
    if current is None or not current.same_inode(expected):
        raise fs.CorruptStore


def _bootstrap(directory_fd: int, root_dev: int, legacy: State) -> State:
    assert legacy.snapshot is not None and legacy.legacy
    data = marker_bytes("CLEAN", 0, legacy.snapshot, legacy.events)
    candidate = fs.write_slot(directory_fd, MARKER_SWAP, data, MAX_MARKER, root_dev)
    try:
        fs.rename_noreplace(directory_fd, MARKER_SWAP, MARKER)
    except fs.DestinationExists:
        concurrent = read(directory_fd, root_dev)
        if concurrent.generation != 0 or not _equivalent(concurrent, legacy):
            raise fs.CorruptStore from None
        return concurrent
    except fs.RenameUncertain:
        concurrent = read(directory_fd, root_dev)
        if concurrent.generation != 0 or not _equivalent(concurrent, legacy):
            raise
        fs.fsync_directory(directory_fd)
        return concurrent
    _require_published(directory_fd, MARKER, candidate, MAX_MARKER, root_dev)
    fs.fsync_directory(directory_fd)
    return read(directory_fd, root_dev)


def _equivalent(left: State, right: State) -> bool:
    return left.snapshot == right.snapshot and left.events == right.events


def commit(
    directory_fd: int,
    root_dev: int,
    expected: State,
    snapshot: bytes,
    events: bytes | None,
    equivalent: Callable[[bytes, bytes], bool] | None = None,
) -> State:
    _validate_targets(snapshot, events)
    current = read(directory_fd, root_dev)
    if not _same_state(current, expected):
        raise fs.CorruptStore
    if current.absent:
        if events is not None:
            raise fs.CorruptStore
        return genesis(directory_fd, root_dev, snapshot, equivalent)
    if current.generation == MAX_GENERATION:
        raise GenerationExhausted
    if current.events is not None and events is None:
        raise fs.CorruptStore
    if current.legacy:
        current = _bootstrap(directory_fd, root_dev, current)
    assert current.generation is not None
    return _commit_clean(
        directory_fd, root_dev, current, snapshot, events, current.generation + 1
    )


def _validate_targets(snapshot: bytes, events: bytes | None) -> None:
    if type(snapshot) is not bytes or not 0 < len(snapshot) <= MAX_SNAPSHOT:
        raise fs.StoreIO
    if events is not None and (type(events) is not bytes or len(events) > MAX_EVENTS):
        raise fs.StoreIO


def _commit_clean(
    directory_fd: int,
    root_dev: int,
    current: State,
    snapshot: bytes,
    events: bytes | None,
    generation: int,
) -> State:
    pending = marker_bytes("PENDING", generation, snapshot, events)
    pending_id = fs.write_slot(directory_fd, MARKER_SWAP, pending, MAX_MARKER, root_dev)
    _exchange_expected(
        directory_fd, MARKER_SWAP, MARKER, pending_id, current.marker_identity, root_dev
    )
    fs.fsync_directory(directory_fd)
    _publish_changed_state(directory_fd, root_dev, current, snapshot, events)
    fs.fsync_directory(directory_fd)
    return _publish_clean(
        directory_fd, root_dev, pending_id, generation, snapshot, events
    )


def _publish_changed_state(
    directory_fd: int,
    root_dev: int,
    current: State,
    snapshot: bytes,
    events: bytes | None,
) -> None:
    if snapshot != current.snapshot:
        _publish_file(
            directory_fd,
            root_dev,
            SNAPSHOT_SWAP,
            SNAPSHOT,
            snapshot,
            MAX_SNAPSHOT,
            current.snapshot_identity,
        )
    if events != current.events:
        _publish_file(
            directory_fd,
            root_dev,
            EVENTS_SWAP,
            EVENTS,
            events if events is not None else b"",
            MAX_EVENTS,
            current.events_identity,
        )


def _publish_file(
    directory_fd: int,
    root_dev: int,
    slot: str,
    final: str,
    data: bytes,
    maximum: int,
    expected: fs.Identity | None,
) -> None:
    candidate = fs.write_slot(directory_fd, slot, data, maximum, root_dev)
    if expected is None:
        try:
            fs.rename_noreplace(directory_fd, slot, final)
        except fs.DestinationExists:
            raise fs.CorruptStore from None
        _require_published(directory_fd, final, candidate, maximum, root_dev)
        return
    _exchange_expected(directory_fd, slot, final, candidate, expected, root_dev)


def _exchange_expected(
    directory_fd: int,
    slot: str,
    final: str,
    candidate: fs.Identity,
    expected: fs.Identity | None,
    root_dev: int,
) -> None:
    if expected is None:
        raise fs.CorruptStore
    current = fs.inspect_file(directory_fd, final, 0, _LIMITS[final][1], root_dev)
    if current is None or not current.same_inode(expected):
        raise fs.CorruptStore
    fs.rename_exchange(directory_fd, slot, final)
    published = fs.inspect_file(directory_fd, final, 0, _LIMITS[final][1], root_dev)
    retired = fs.inspect_file(directory_fd, slot, 0, _LIMITS[slot][1], root_dev)
    if published is None or retired is None:
        raise fs.CorruptStore
    if published.same_inode(candidate) and retired.same_inode(expected):
        return
    _rollback_if_stable(directory_fd, slot, final, published, retired, root_dev)
    raise fs.CorruptStore


def _rollback_if_stable(
    directory_fd: int,
    slot: str,
    final: str,
    published: fs.Identity,
    retired: fs.Identity,
    root_dev: int,
) -> None:
    latest_final = fs.inspect_file(directory_fd, final, 0, _LIMITS[final][1], root_dev)
    latest_slot = fs.inspect_file(directory_fd, slot, 0, _LIMITS[slot][1], root_dev)
    if (
        latest_final is not None
        and latest_slot is not None
        and latest_final.same_inode(published)
        and latest_slot.same_inode(retired)
    ):
        fs.rename_exchange(directory_fd, slot, final)


def _publish_clean(
    directory_fd: int,
    root_dev: int,
    pending: fs.Identity,
    generation: int,
    snapshot: bytes,
    events: bytes | None,
) -> State:
    clean = marker_bytes("CLEAN", generation, snapshot, events)
    candidate = fs.write_slot(directory_fd, MARKER_SWAP, clean, MAX_MARKER, root_dev)
    try:
        _exchange_clean(directory_fd, root_dev, pending, candidate)
        fs.fsync_directory(directory_fd)
    except _CleanOutcomeUncertain:
        accepted = _confirm_uncertain_clean(
            directory_fd, root_dev, generation, snapshot, events
        )
        if accepted is not None:
            return accepted
        raise fs.CorruptStore from None
    except fs.RenameUncertain:
        accepted = _confirm_uncertain_clean(
            directory_fd, root_dev, generation, snapshot, events
        )
        if accepted is not None:
            return accepted
        raise
    except fs.StoreIO as cause:
        return _compensate_clean_fsync(
            directory_fd, root_dev, generation, snapshot, events, cause
        )
    accepted = _accept_clean(directory_fd, root_dev, generation, snapshot, events)
    if accepted is None:
        raise fs.CorruptStore
    return accepted


def _compensate_clean_fsync(
    directory_fd: int,
    root_dev: int,
    generation: int,
    snapshot: bytes,
    events: bytes | None,
    cause: fs.StoreIO,
) -> State:
    accepted = _accept_clean(directory_fd, root_dev, generation, snapshot, events)
    if accepted is None:
        raise cause
    fs.fsync_directory(directory_fd)
    accepted = _accept_clean(directory_fd, root_dev, generation, snapshot, events)
    if accepted is None:
        raise fs.CorruptStore
    return accepted


def _confirm_uncertain_clean(
    directory_fd: int,
    root_dev: int,
    generation: int,
    snapshot: bytes,
    events: bytes | None,
) -> State | None:
    accepted = _accept_clean(directory_fd, root_dev, generation, snapshot, events)
    if accepted is None:
        return None
    fs.fsync_directory(directory_fd)
    return _accept_clean(directory_fd, root_dev, generation, snapshot, events)


def _exchange_clean(
    directory_fd: int,
    root_dev: int,
    pending: fs.Identity,
    candidate: fs.Identity,
) -> None:
    current = fs.inspect_file(directory_fd, MARKER, 1, MAX_MARKER, root_dev)
    if current is None or not current.same_inode(pending):
        raise fs.CorruptStore
    fs.rename_exchange(directory_fd, MARKER_SWAP, MARKER)
    try:
        final = fs.inspect_file(directory_fd, MARKER, 1, MAX_MARKER, root_dev)
        retired = fs.inspect_file(directory_fd, MARKER_SWAP, 0, MAX_MARKER, root_dev)
    except fs.CorruptStore:
        raise _CleanOutcomeUncertain from None
    if final is None or retired is None:
        raise _CleanOutcomeUncertain
    if not final.same_inode(candidate) or not retired.same_inode(pending):
        raise _CleanOutcomeUncertain


def _accept_clean(
    directory_fd: int,
    root_dev: int,
    generation: int,
    snapshot: bytes,
    events: bytes | None,
) -> State | None:
    try:
        state = read(directory_fd, root_dev)
    except fs.CorruptStore:
        return None
    if (
        state.generation == generation
        and state.snapshot == snapshot
        and state.events == events
    ):
        return state
    return None
