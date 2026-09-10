from __future__ import annotations

import json
import os
import hashlib

import pytest

from specstyle.workflow import _job_store_transaction as tx
from specstyle.workflow._job_store_fs import CorruptStore


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _open(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    return descriptor, os.fstat(descriptor).st_dev


def _genesis(path, snapshot=b"snapshot"):
    descriptor, device = _open(path)
    try:
        return tx.genesis(descriptor, device, snapshot)
    finally:
        os.close(descriptor)


def test_pending_marker_is_never_accepted(tmp_path) -> None:
    (tmp_path / "snapshot.json").write_bytes(b"snapshot")
    (tmp_path / tx.MARKER).write_bytes(
        _canonical(
            {
                "version": 1,
                "phase": "PENDING",
                "generation": 1,
                "snapshot_sha256": "0" * 64,
                "events_sha256": None,
            }
        )
    )
    root_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(CorruptStore):
            tx.read(root_fd, os.fstat(root_fd).st_dev)
    finally:
        os.close(root_fd)


def test_generation_exhaustion_precedes_any_slot_mutation(tmp_path) -> None:
    snapshot = b"snapshot"
    (tmp_path / "snapshot.json").write_bytes(snapshot)
    marker = tx.marker_bytes("CLEAN", (1 << 63) - 1, snapshot, None)
    (tmp_path / tx.MARKER).write_bytes(marker)
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    root_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        state = tx.read(root_fd, os.fstat(root_fd).st_dev)
        with pytest.raises(tx.GenerationExhausted):
            tx.commit(root_fd, os.fstat(root_fd).st_dev, state, snapshot + b"x", None)
    finally:
        os.close(root_fd)
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == before


def test_removing_existing_events_is_rejected_before_any_mutation(tmp_path) -> None:
    first = _genesis(tmp_path)
    descriptor, device = _open(tmp_path)
    try:
        current = tx.commit(descriptor, device, first, b"snapshot", b"event\n")
        before = {
            path.name: (path.stat().st_ino, path.stat().st_mtime_ns, path.read_bytes())
            for path in tmp_path.iterdir()
        }
        with pytest.raises(CorruptStore):
            tx.commit(descriptor, device, current, b"snapshot", None)
    finally:
        os.close(descriptor)
    after = {
        path.name: (path.stat().st_ino, path.stat().st_mtime_ns, path.read_bytes())
        for path in tmp_path.iterdir()
    }
    assert after == before


@pytest.mark.parametrize(
    "marker",
    [
        b'{"events_sha256":null,"generation":0,"phase":"CLEAN","snapshot_sha256":"0","version":1}',
        b'{"events_sha256":null,"generation":true,"phase":"CLEAN","snapshot_sha256":"0"}',
        b'{"events_sha256":null,"generation":0,"phase":"CLEAN","snapshot_sha256":"0","version":1,"version":1}',
    ],
)
def test_bad_marker_schema_is_corruption(tmp_path, marker: bytes) -> None:
    (tmp_path / "snapshot.json").write_bytes(b"snapshot")
    (tmp_path / tx.MARKER).write_bytes(marker)
    descriptor, device = _open(tmp_path)
    try:
        with pytest.raises(CorruptStore):
            tx.read(descriptor, device)
    finally:
        os.close(descriptor)


def test_slot_only_directory_is_absent_but_unknown_entry_is_corrupt(tmp_path) -> None:
    (tmp_path / tx.SNAPSHOT_SWAP).write_bytes(b"partial")
    descriptor, device = _open(tmp_path)
    try:
        assert tx.read(descriptor, device).absent
        (tmp_path / "unknown").write_bytes(b"x")
        with pytest.raises(CorruptStore):
            tx.read(descriptor, device)
    finally:
        os.close(descriptor)


def test_genesis_and_commit_publish_clean_generations_with_fixed_names(
    tmp_path,
) -> None:
    first = _genesis(tmp_path)
    descriptor, device = _open(tmp_path)
    try:
        second = tx.commit(descriptor, device, first, b"snapshot", b"event\n")
    finally:
        os.close(descriptor)
    assert (first.generation, second.generation) == (0, 1)
    assert second.events == b"event\n"
    assert set(path.name for path in tmp_path.iterdir()) <= set(tx._LIMITS)


def test_pending_directory_fsync_failure_stays_pending(tmp_path, monkeypatch) -> None:
    current = _genesis(tmp_path)
    descriptor, device = _open(tmp_path)
    monkeypatch.setattr(
        tx.fs, "fsync_directory", lambda _fd: (_ for _ in ()).throw(tx.fs.StoreIO())
    )
    try:
        with pytest.raises(tx.fs.StoreIO):
            tx.commit(descriptor, device, current, b"snapshot", b"event\n")
        with pytest.raises(CorruptStore):
            tx.read(descriptor, device)
    finally:
        os.close(descriptor)


def test_state_identity_swap_rolls_back_and_leaves_pending(
    tmp_path, monkeypatch
) -> None:
    current = _genesis(tmp_path)
    original = tx.fs.rename_exchange
    calls = 0

    def attack(directory_fd: int, old: str, new: str) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            attacker = tmp_path / "attacker"
            attacker.write_bytes(b"attacker")
            os.replace(attacker, tmp_path / new)
        original(directory_fd, old, new)

    monkeypatch.setattr(tx.fs, "rename_exchange", attack)
    descriptor, device = _open(tmp_path)
    try:
        with pytest.raises(CorruptStore):
            tx.commit(descriptor, device, current, b"changed", None)
        assert (tmp_path / tx.SNAPSHOT).read_bytes() == b"attacker"
        with pytest.raises(CorruptStore):
            tx.read(descriptor, device)
    finally:
        os.close(descriptor)


def test_clean_exchange_uncertain_after_success_is_accepted_once(
    tmp_path, monkeypatch
) -> None:
    current = _genesis(tmp_path)
    original = tx.fs.rename_exchange
    calls = 0

    def uncertain(directory_fd: int, old: str, new: str) -> None:
        nonlocal calls
        calls += 1
        original(directory_fd, old, new)
        if calls == 3:
            raise tx.fs.RenameUncertain

    monkeypatch.setattr(tx.fs, "rename_exchange", uncertain)
    descriptor, device = _open(tmp_path)
    try:
        result = tx.commit(descriptor, device, current, b"changed", None)
    finally:
        os.close(descriptor)
    assert result.generation == 1
    assert calls == 3


def test_clean_exchange_uncertain_before_success_is_not_retried(
    tmp_path, monkeypatch
) -> None:
    current = _genesis(tmp_path)
    original = tx.fs.rename_exchange
    calls = 0

    def uncertain(directory_fd: int, old: str, new: str) -> None:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise tx.fs.RenameUncertain
        original(directory_fd, old, new)

    monkeypatch.setattr(tx.fs, "rename_exchange", uncertain)
    descriptor, device = _open(tmp_path)
    try:
        with pytest.raises(tx.fs.RenameUncertain):
            tx.commit(descriptor, device, current, b"changed", None)
        assert calls == 3
        with pytest.raises(CorruptStore):
            tx.read(descriptor, device)
    finally:
        os.close(descriptor)


def test_marker_hash_requires_events_hash_iff_file_exists(tmp_path) -> None:
    snapshot = b"snapshot"
    (tmp_path / tx.SNAPSHOT).write_bytes(snapshot)
    (tmp_path / tx.EVENTS).write_bytes(b"")
    (tmp_path / tx.MARKER).write_bytes(tx.marker_bytes("CLEAN", 0, snapshot, None))
    descriptor, device = _open(tmp_path)
    try:
        with pytest.raises(CorruptStore):
            tx.read(descriptor, device)
    finally:
        os.close(descriptor)


def test_marker_hash_is_exact_for_snapshot(tmp_path) -> None:
    snapshot = b"snapshot"
    (tmp_path / tx.SNAPSHOT).write_bytes(snapshot + b"x")
    marker = {
        "version": 1,
        "phase": "CLEAN",
        "generation": 0,
        "snapshot_sha256": hashlib.sha256(snapshot).hexdigest(),
        "events_sha256": None,
    }
    (tmp_path / tx.MARKER).write_bytes(_canonical(marker))
    descriptor, device = _open(tmp_path)
    try:
        with pytest.raises(CorruptStore):
            tx.read(descriptor, device)
    finally:
        os.close(descriptor)


@pytest.mark.parametrize("name", [tx.MARKER, tx.SNAPSHOT, tx.EVENTS])
def test_read_rechecks_final_file_identity_after_namespace_check(
    tmp_path, monkeypatch, name: str
) -> None:
    current = _genesis(tmp_path)
    descriptor, device = _open(tmp_path)
    try:
        tx.commit(descriptor, device, current, b"snapshot", b"event\n")
    finally:
        os.close(descriptor)
    attacker = tmp_path.with_name(f"{tmp_path.name}-{name}.attacker")
    attacker.write_bytes((tmp_path / name).read_bytes())
    original_names = tx.fs.directory_names
    calls = 0

    def replace_on_final_check(directory_fd: int):
        nonlocal calls
        result = original_names(directory_fd)
        calls += 1
        if calls == 2:
            os.replace(attacker, tmp_path / name)
        return result

    monkeypatch.setattr(tx.fs, "directory_names", replace_on_final_check)
    descriptor, device = _open(tmp_path)
    try:
        with pytest.raises(CorruptStore):
            tx.read(descriptor, device)
    finally:
        os.close(descriptor)
    assert calls == 2


def test_read_rechecks_full_identity_not_only_inode(tmp_path, monkeypatch) -> None:
    _genesis(tmp_path)
    original_names = tx.fs.directory_names
    calls = 0

    def chmod_on_final_check(directory_fd: int):
        nonlocal calls
        result = original_names(directory_fd)
        calls += 1
        if calls == 2:
            (tmp_path / tx.SNAPSHOT).chmod(0o400)
        return result

    monkeypatch.setattr(tx.fs, "directory_names", chmod_on_final_check)
    descriptor, device = _open(tmp_path)
    try:
        with pytest.raises(CorruptStore):
            tx.read(descriptor, device)
    finally:
        os.close(descriptor)
    assert calls == 2


@pytest.mark.parametrize(
    ("fault", "expected"),
    [
        ("slot_write", "absent"),
        ("file_fsync", "absent"),
        ("noreplace", "absent"),
        ("snapshot_dir_fsync", "legacy"),
        ("bootstrap_write", "legacy"),
        ("bootstrap_rename", "legacy"),
        ("bootstrap_dir_fsync", "clean"),
    ],
)
def test_genesis_failure_matrix_has_only_absent_legacy_or_clean(
    tmp_path, monkeypatch, fault: str, expected: str
) -> None:
    _inject_genesis_fault(monkeypatch, fault)
    descriptor, device = _open(tmp_path)
    try:
        with pytest.raises(tx.fs.StoreIO):
            tx.genesis(descriptor, device, b"snapshot")
        state = tx.read(descriptor, device)
    finally:
        os.close(descriptor)
    actual = "absent" if state.absent else "legacy" if state.legacy else "clean"
    assert actual == expected


def _inject_genesis_fault(monkeypatch, fault: str) -> None:
    if fault == "file_fsync":
        monkeypatch.setattr(
            tx.fs.os, "fsync", lambda _fd: (_ for _ in ()).throw(OSError())
        )
        return
    if fault in {"slot_write", "bootstrap_write"}:
        _inject_write_fault(monkeypatch, fault)
        return
    if fault in {"noreplace", "bootstrap_rename"}:
        _inject_rename_fault(monkeypatch, fault)
        return
    _inject_directory_fsync_fault(monkeypatch, fault)


def _inject_write_fault(monkeypatch, fault: str) -> None:
    original = tx.fs.write_slot

    def failing(*args, **kwargs):
        if fault == "slot_write" or args[1] == tx.MARKER_SWAP:
            raise tx.fs.StoreIO
        return original(*args, **kwargs)

    monkeypatch.setattr(tx.fs, "write_slot", failing)


def _inject_rename_fault(monkeypatch, fault: str) -> None:
    original = tx.fs.rename_noreplace
    calls = 0

    def failing(*args, **kwargs):
        nonlocal calls
        calls += 1
        if fault == "noreplace" or calls == 2:
            raise tx.fs.RenameUncertain
        return original(*args, **kwargs)

    monkeypatch.setattr(tx.fs, "rename_noreplace", failing)


def _inject_directory_fsync_fault(monkeypatch, fault: str) -> None:
    original = tx.fs.fsync_directory
    calls = 0

    def failing(descriptor: int):
        nonlocal calls
        calls += 1
        threshold = 1 if fault == "snapshot_dir_fsync" else 2
        if calls == threshold:
            raise tx.fs.StoreIO
        return original(descriptor)

    monkeypatch.setattr(tx.fs, "fsync_directory", failing)


def test_fixed_slots_are_never_unlinked(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        tx.fs.os,
        "unlink",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unlink")),
    )
    current = _genesis(tmp_path)
    descriptor, device = _open(tmp_path)
    try:
        result = tx.commit(descriptor, device, current, b"changed", b"event\n")
    finally:
        os.close(descriptor)
    assert result.generation == 1


def test_genesis_accepts_semantically_equivalent_legacy_final(tmp_path) -> None:
    (tmp_path / tx.SNAPSHOT).write_bytes(b'{"value": 1}')
    descriptor, device = _open(tmp_path)
    try:
        result = tx.genesis(
            descriptor,
            device,
            b'{"value":1}',
            lambda left, right: json.loads(left) == json.loads(right),
        )
    finally:
        os.close(descriptor)
    assert result.generation == 0
    assert (tmp_path / tx.MARKER).is_file()


@pytest.mark.parametrize(
    ("fault", "phase"),
    [
        ("pending_slot", "CLEAN"),
        ("pending_file_fsync", "CLEAN"),
        ("pending_exchange_before", "CLEAN"),
        ("pending_exchange_after", "PENDING"),
        ("pending_dir_fsync", "PENDING"),
        ("state_slot", "PENDING"),
        ("state_file_fsync", "PENDING"),
        ("state_exchange_before", "PENDING"),
        ("state_exchange_after", "PENDING"),
        ("state_dir_fsync", "PENDING"),
        ("clean_slot", "PENDING"),
        ("clean_file_fsync", "PENDING"),
    ],
)
def test_commit_failure_matrix_preserves_authoritative_phase(
    tmp_path, monkeypatch, fault: str, phase: str
) -> None:
    current = _genesis(tmp_path)
    _inject_commit_fault(monkeypatch, fault)
    descriptor, device = _open(tmp_path)
    try:
        with pytest.raises(tx.fs.StoreIO):
            tx.commit(descriptor, device, current, b"changed", None)
    finally:
        os.close(descriptor)
    assert json.loads((tmp_path / tx.MARKER).read_bytes())["phase"] == phase


def _inject_commit_fault(monkeypatch, fault: str) -> None:
    if fault.endswith("slot"):
        _inject_commit_write_fault(monkeypatch, fault)
    elif "file_fsync" in fault:
        _inject_commit_file_fsync_fault(monkeypatch, fault)
    elif "exchange" in fault:
        _inject_commit_exchange_fault(monkeypatch, fault)
    else:
        _inject_commit_dir_fsync_fault(monkeypatch, fault)


def _inject_commit_write_fault(monkeypatch, fault: str) -> None:
    original = tx.fs.write_slot
    marker_calls = 0

    def failing(*args, **kwargs):
        nonlocal marker_calls
        name = args[1]
        if name == tx.MARKER_SWAP:
            marker_calls += 1
        if fault == "pending_slot" and marker_calls == 1:
            raise tx.fs.StoreIO
        if fault == "state_slot" and name == tx.SNAPSHOT_SWAP:
            raise tx.fs.StoreIO
        if fault == "clean_slot" and marker_calls == 2:
            raise tx.fs.StoreIO
        return original(*args, **kwargs)

    monkeypatch.setattr(tx.fs, "write_slot", failing)


def _inject_commit_file_fsync_fault(monkeypatch, fault: str) -> None:
    target = {"pending_file_fsync": 1, "state_file_fsync": 3, "clean_file_fsync": 5}[
        fault
    ]
    original = tx.fs.os.fsync
    calls = 0

    def failing(descriptor: int):
        nonlocal calls
        calls += 1
        if calls == target:
            raise OSError
        return original(descriptor)

    monkeypatch.setattr(tx.fs.os, "fsync", failing)


def _inject_commit_exchange_fault(monkeypatch, fault: str) -> None:
    target = 1 if fault.startswith("pending") else 2
    after = fault.endswith("after")
    original = tx.fs.rename_exchange
    calls = 0

    def failing(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == target and not after:
            raise tx.fs.RenameUncertain
        result = original(*args, **kwargs)
        if calls == target:
            raise tx.fs.RenameUncertain
        return result

    monkeypatch.setattr(tx.fs, "rename_exchange", failing)


def _inject_commit_dir_fsync_fault(monkeypatch, fault: str) -> None:
    target = 1 if fault == "pending_dir_fsync" else 2
    original = tx.fs.fsync_directory
    calls = 0

    def failing(descriptor: int):
        nonlocal calls
        calls += 1
        if calls == target:
            raise tx.fs.StoreIO
        return original(descriptor)

    monkeypatch.setattr(tx.fs, "fsync_directory", failing)


def test_clean_directory_fsync_failure_accepts_valid_clean_state(
    tmp_path, monkeypatch
) -> None:
    current = _genesis(tmp_path)
    original = tx.fs.fsync_directory
    calls = 0

    def failing(descriptor: int):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise tx.fs.StoreIO
        return original(descriptor)

    monkeypatch.setattr(tx.fs, "fsync_directory", failing)
    descriptor, device = _open(tmp_path)
    try:
        result = tx.commit(descriptor, device, current, b"changed", None)
    finally:
        os.close(descriptor)
    assert result.generation == 1
    assert calls == 4


def test_clean_directory_fsync_persistent_failure_propagates_store_io(
    tmp_path, monkeypatch
) -> None:
    current = _genesis(tmp_path)
    original = tx.fs.fsync_directory
    calls = 0

    def failing(descriptor: int):
        nonlocal calls
        calls += 1
        if calls >= 3:
            raise tx.fs.StoreIO
        return original(descriptor)

    monkeypatch.setattr(tx.fs, "fsync_directory", failing)
    descriptor, device = _open(tmp_path)
    try:
        with pytest.raises(tx.fs.StoreIO):
            tx.commit(descriptor, device, current, b"changed", None)
    finally:
        os.close(descriptor)
    assert calls == 4
