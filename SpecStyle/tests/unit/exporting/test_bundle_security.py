"""EXP-001B bundle security tests (§13.11, §13.12)."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Event, Lock

import pytest

from specstyle.errors import DomainError, InfrastructureError
from specstyle.exporting.bundle import ExportBundle, export_bundle
from specstyle.exporting.manifest import _prepare_export
from tests.unit.exporting.test_bundle import _root_fd
from tests.unit.exporting.test_manifest import _export_request


def _fd_count() -> int:
    root = next(
        (path for path in (Path("/proc/self/fd"), Path("/dev/fd")) if path.is_dir()),
        None,
    )
    if root is None:
        pytest.skip("descriptor namespace unavailable")
    return len(os.listdir(root))


def _publish(tmp_path: Path, bundle_name: str) -> ExportBundle:
    root_fd = _root_fd(tmp_path)
    try:
        return export_bundle(_export_request(), root_fd, bundle_name)
    finally:
        os.close(root_fd)


def _tree_metadata(root: Path) -> dict[str, tuple[int, int, int, int]]:
    paths = (root, *sorted(root.rglob("*")))
    return {
        "." if path == root else path.relative_to(root).as_posix(): (
            path.lstat().st_ino,
            path.lstat().st_mode,
            path.lstat().st_size,
            path.lstat().st_mtime_ns,
        )
        for path in paths
    }


def test_stage_bundle_owns_hidden_staging_until_idempotent_close(
    tmp_path: Path,
) -> None:
    import specstyle.exporting.bundle as bundle_mod

    before = _fd_count()
    root_fd = _root_fd(tmp_path)
    staged = bundle_mod._stage_bundle(_export_request(), root_fd, "future-final")
    os.close(root_fd)

    entries = tuple(tmp_path.iterdir())
    assert len(entries) == 1
    assert entries[0].name.startswith(".")
    assert entries[0].is_dir()
    assert not (tmp_path / "future-final").exists()

    staged.close()
    staged.close()
    assert entries[0].is_dir()
    assert (entries[0] / "manifest.json").is_file()
    assert _fd_count() == before


def test_stage_close_preserves_unknown_staging_but_closes_owned_fds(
    tmp_path: Path,
) -> None:
    import specstyle.exporting.bundle as bundle_mod

    before = _fd_count()
    root_fd = _root_fd(tmp_path)
    try:
        staged = bundle_mod._stage_bundle(_export_request(), root_fd, "future-final")
    finally:
        os.close(root_fd)
    staging = next(tmp_path.iterdir())
    (staging / "unknown-entry").write_bytes(b"preserve")

    staged.close()

    assert staging.is_dir()
    assert (staging / "unknown-entry").read_bytes() == b"preserve"
    assert not (tmp_path / "future-final").exists()
    assert _fd_count() == before


def test_stage_close_preserves_same_name_replacement(tmp_path: Path) -> None:
    import specstyle.exporting.bundle as bundle_mod

    before = _fd_count()
    root_fd = _root_fd(tmp_path)
    try:
        staged = bundle_mod._stage_bundle(_export_request(), root_fd, "future-final")
    finally:
        os.close(root_fd)
    original = next(tmp_path.iterdir())
    preserved = tmp_path / ".preserved-original"
    original.rename(preserved)
    original.mkdir()

    staged.close()

    assert preserved.is_dir()
    assert (preserved / "manifest.json").is_file()
    assert original.is_dir()
    assert tuple(original.iterdir()) == ()
    assert _fd_count() == before


@pytest.mark.parametrize("drifted_fd", ["staging", "root"])
def test_stage_close_preserves_staging_on_held_fd_identity_drift(
    tmp_path: Path, drifted_fd: str
) -> None:
    import specstyle.exporting.bundle as bundle_mod

    before = _fd_count()
    root_fd = _root_fd(tmp_path)
    try:
        staged = bundle_mod._stage_bundle(_export_request(), root_fd, "future-final")
    finally:
        os.close(root_fd)
    staging = next(tmp_path.iterdir())
    replacement = tmp_path / f".{drifted_fd}-fd-replacement"
    replacement.mkdir()
    replacement_fd = _root_fd(replacement)
    try:
        owned_fd = getattr(staged, f"_{drifted_fd}_fd")
        os.dup2(replacement_fd, owned_fd, inheritable=False)
    finally:
        os.close(replacement_fd)

    staged.close()

    assert staging.is_dir()
    assert (staging / "manifest.json").is_file()
    assert replacement.is_dir()
    assert _fd_count() == before


def test_stage_close_attempts_both_fds_and_reports_only_first_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import specstyle.exporting.bundle as bundle_mod

    before = _fd_count()
    root_fd = _root_fd(tmp_path)
    try:
        staged = bundle_mod._stage_bundle(_export_request(), root_fd, "future-final")
    finally:
        os.close(root_fd)
    owned = (staged._staging_fd, staged._root_fd)
    real_close = os.close
    attempted: list[int] = []

    def close_then_fail(fd: int) -> None:
        real_close(fd)
        if fd in owned:
            attempted.append(fd)
            label = "staging" if fd == owned[0] else "root"
            raise OSError(f"{label} close failed")

    monkeypatch.setattr(os, "close", close_then_fail)
    with pytest.raises(InfrastructureError, match="^export close failed$") as caught:
        staged.close()
    staged.close()

    assert attempted == list(owned)
    assert str(caught.value.__cause__) == "staging close failed"
    staging = next(tmp_path.iterdir())
    assert staging.is_dir()
    assert (staging / "manifest.json").is_file()
    assert _fd_count() == before


def test_staged_bundle_constructor_rejects_forged_seal() -> None:
    import specstyle.exporting.bundle as bundle_mod
    from specstyle.exporting.manifest import _prepare_export

    identity = bundle_mod._NodeIdentity(1, 2)
    with pytest.raises(DomainError, match="^invalid staged export$"):
        bundle_mod._StagedBundle(
            object(),
            root_fd=-1,
            staging_fd=-1,
            root_identity=identity,
            staging_identity=identity,
            inventory_snapshot={},
            staging_name=".forged",
            bundle_name="forged",
            prepared=_prepare_export(_export_request()),
        )


@pytest.mark.parametrize("replacement_kind", ["root", "file", "directory"])
def test_stage_close_never_deletes_same_name_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    replacement_kind: str,
) -> None:
    import specstyle.exporting.bundle as bundle_mod

    root_fd = _root_fd(tmp_path)
    try:
        staged = bundle_mod._stage_bundle(_export_request(), root_fd, "future-final")
    finally:
        os.close(root_fd)
    staging = next(tmp_path.iterdir())
    triggered = False

    if replacement_kind == "file":
        real_unlink = os.unlink

        def swap_then_unlink(path, *args, **kwargs):
            nonlocal triggered
            parent_fd = kwargs.get("dir_fd")
            if path == "manifest.json" and parent_fd is not None:
                triggered = True
                os.rename(
                    path,
                    ".preserved-manifest",
                    src_dir_fd=parent_fd,
                    dst_dir_fd=parent_fd,
                )
                attacker_fd = os.open(
                    path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o600,
                    dir_fd=parent_fd,
                )
                os.write(attacker_fd, b"attacker-owned")
                os.close(attacker_fd)
            return real_unlink(path, *args, **kwargs)

        monkeypatch.setattr(os, "unlink", swap_then_unlink)
    else:
        real_rmdir = os.rmdir
        target = staging.name if replacement_kind == "root" else "talking_head_cover"

        def swap_then_rmdir(path, *args, **kwargs):
            nonlocal triggered
            parent_fd = kwargs.get("dir_fd")
            if path == target and parent_fd is not None and not triggered:
                triggered = True
                os.rename(
                    path,
                    f".preserved-{replacement_kind}",
                    src_dir_fd=parent_fd,
                    dst_dir_fd=parent_fd,
                )
                os.mkdir(path, 0o700, dir_fd=parent_fd)
            return real_rmdir(path, *args, **kwargs)

        monkeypatch.setattr(os, "rmdir", swap_then_rmdir)

    staged.close()

    assert not triggered
    assert staging.is_dir()
    assert (staging / "manifest.json").is_file()
    assert (staging / "approved" / "talking_head_cover").is_dir()


def test_stage_write_failure_has_no_final_or_descriptor_leak(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import specstyle.exporting.bundle as bundle_mod

    monkeypatch.setattr(os, "write", lambda _fd, _data: 0)
    before = _fd_count()
    root_fd = _root_fd(tmp_path)
    try:
        with pytest.raises(InfrastructureError, match="^export write failed$"):
            bundle_mod._stage_bundle(_export_request(), root_fd, "never-final")
    finally:
        os.close(root_fd)
    assert not (tmp_path / "never-final").exists()
    assert all(entry.name.startswith(".") for entry in tmp_path.iterdir())
    assert _fd_count() == before


def test_stage_fsync_failure_has_no_final_or_descriptor_leak(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import specstyle.exporting.bundle as bundle_mod

    monkeypatch.setattr(
        os, "fsync", lambda _fd: (_ for _ in ()).throw(OSError("sync denied"))
    )
    before = _fd_count()
    root_fd = _root_fd(tmp_path)
    try:
        with pytest.raises(InfrastructureError, match="^export sync failed$"):
            bundle_mod._stage_bundle(_export_request(), root_fd, "never-final")
    finally:
        os.close(root_fd)
    assert not (tmp_path / "never-final").exists()
    assert all(entry.name.startswith(".") for entry in tmp_path.iterdir())
    assert _fd_count() == before


def test_stage_readback_failure_has_no_final_or_descriptor_leak(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import specstyle.exporting.bundle as bundle_mod

    monkeypatch.setattr(
        os, "read", lambda _fd, _size: (_ for _ in ()).throw(OSError("read denied"))
    )
    before = _fd_count()
    root_fd = _root_fd(tmp_path)
    try:
        with pytest.raises(InfrastructureError, match="^export readback failed$"):
            bundle_mod._stage_bundle(_export_request(), root_fd, "never-final")
    finally:
        os.close(root_fd)
    assert not (tmp_path / "never-final").exists()
    assert all(entry.name.startswith(".") for entry in tmp_path.iterdir())
    assert _fd_count() == before


@pytest.mark.parametrize("mode", [0o720, 0o702])
def test_stage_rejects_group_or_world_writable_root(tmp_path: Path, mode: int) -> None:
    import specstyle.exporting.bundle as bundle_mod

    tmp_path.chmod(mode)
    root_fd = _root_fd(tmp_path)
    try:
        with pytest.raises(DomainError, match="^invalid export target$"):
            bundle_mod._stage_bundle(_export_request(), root_fd, "untrusted")
    finally:
        os.close(root_fd)


def test_stage_rejects_root_not_owned_by_effective_user(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import specstyle.exporting.bundle as bundle_mod

    actual_euid = os.geteuid()
    monkeypatch.setattr(os, "geteuid", lambda: actual_euid + 1)
    root_fd = _root_fd(tmp_path)
    try:
        with pytest.raises(DomainError, match="^invalid export target$"):
            bundle_mod._stage_bundle(_export_request(), root_fd, "untrusted")
    finally:
        os.close(root_fd)


def test_stage_rejects_root_identity_drift_before_return(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import specstyle.exporting.bundle as bundle_mod

    real_readback = bundle_mod._readback

    def readback_then_chmod(staging_fd, prepared, expected):
        real_readback(staging_fd, prepared, expected)
        tmp_path.chmod(0o750)

    monkeypatch.setattr(bundle_mod, "_readback", readback_then_chmod)
    root_fd = _root_fd(tmp_path)
    try:
        with pytest.raises(DomainError, match="^invalid export target$"):
            bundle_mod._stage_bundle(_export_request(), root_fd, "drift")
    finally:
        os.close(root_fd)
    assert not (tmp_path / "drift").exists()


def test_inspect_final_bundle_returns_none_only_when_initially_missing(
    tmp_path: Path,
) -> None:
    import specstyle.exporting.bundle as bundle_mod

    before = _fd_count()
    root_fd = _root_fd(tmp_path)
    try:
        inspected = bundle_mod._inspect_final_bundle(
            _prepare_export(_export_request()), root_fd, "missing"
        )
        os.fstat(root_fd)
    finally:
        os.close(root_fd)

    assert inspected is None
    assert _fd_count() == before


def test_inspect_rejects_group_writable_root(tmp_path: Path) -> None:
    import specstyle.exporting.bundle as bundle_mod

    prepared = _prepare_export(_export_request())
    _publish(tmp_path, "exact")
    tmp_path.chmod(0o770)
    root_fd = _root_fd(tmp_path)
    try:
        with pytest.raises(DomainError, match="^invalid export target$"):
            bundle_mod._inspect_final_bundle(prepared, root_fd, "exact")
    finally:
        os.close(root_fd)


def test_inspect_rejects_root_identity_drift_before_return(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import specstyle.exporting.bundle as bundle_mod

    prepared = _prepare_export(_export_request())
    _publish(tmp_path, "exact")
    real_readback = bundle_mod._readback

    def readback_then_chmod(final_fd, expected_prepared, expected):
        real_readback(final_fd, expected_prepared, expected)
        tmp_path.chmod(0o750)

    monkeypatch.setattr(bundle_mod, "_readback", readback_then_chmod)
    root_fd = _root_fd(tmp_path)
    try:
        with pytest.raises(DomainError, match="^invalid export target$"):
            bundle_mod._inspect_final_bundle(prepared, root_fd, "exact")
    finally:
        os.close(root_fd)


def test_inspect_exact_bundle_returns_hashes_without_metadata_mutation(
    tmp_path: Path,
) -> None:
    import specstyle.exporting.bundle as bundle_mod

    published = _publish(tmp_path, "exact")
    final = tmp_path / "exact"
    metadata_before = _tree_metadata(final)
    before = _fd_count()
    root_fd = _root_fd(tmp_path)
    try:
        inspected = bundle_mod._inspect_final_bundle(
            _prepare_export(_export_request()), root_fd, "exact"
        )
        os.fstat(root_fd)
    finally:
        os.close(root_fd)

    assert inspected == published
    assert inspected is not None
    assert inspected.files == published.files
    assert inspected.manifest_sha256 == published.manifest_sha256
    assert inspected.payload_sha256 == published.payload_sha256
    assert inspected.bundle_sha256 == published.bundle_sha256
    assert _tree_metadata(final) == metadata_before
    assert _fd_count() == before


@pytest.mark.parametrize("conflict", ["payload", "manifest", "extra", "dir", "symlink"])
def test_inspect_existing_content_inventory_and_node_conflicts_fail_closed(
    tmp_path: Path, conflict: str
) -> None:
    import specstyle.exporting.bundle as bundle_mod

    prepared = _prepare_export(_export_request())
    _publish(tmp_path, "conflict")
    final = tmp_path / "conflict"
    payload = prepared.payload_files[0]
    payload_path = final / payload.relative_path
    if conflict == "payload":
        payload_path.write_bytes(b"tampered")
    elif conflict == "manifest":
        (final / prepared.manifest_file.relative_path).write_bytes(b'{"forged":true}')
    elif conflict == "extra":
        (final / "unexpected-entry").write_bytes(b"unexpected")
    elif conflict == "dir":
        payload_path.unlink()
        payload_path.mkdir()
    else:
        payload_path.unlink()
        payload_path.symlink_to(final / prepared.manifest_file.relative_path)

    before = _fd_count()
    root_fd = _root_fd(tmp_path)
    try:
        with pytest.raises(DomainError, match="^export hash mismatch$"):
            bundle_mod._inspect_final_bundle(prepared, root_fd, "conflict")
    finally:
        os.close(root_fd)
    assert _fd_count() == before


@pytest.mark.parametrize("final_kind", ["regular", "symlink"])
def test_inspect_existing_final_symlink_or_non_directory_fails_closed(
    tmp_path: Path, final_kind: str
) -> None:
    import specstyle.exporting.bundle as bundle_mod

    _publish(tmp_path, "wrong-kind")
    final = tmp_path / "wrong-kind"
    preserved = tmp_path / ".preserved-exact"
    final.rename(preserved)
    if final_kind == "regular":
        final.write_bytes(b"not a directory")
    else:
        final.symlink_to(preserved, target_is_directory=True)

    root_fd = _root_fd(tmp_path)
    try:
        with pytest.raises(DomainError, match="^export hash mismatch$"):
            bundle_mod._inspect_final_bundle(
                _prepare_export(_export_request()), root_fd, "wrong-kind"
            )
    finally:
        os.close(root_fd)


def test_inspect_initial_lstat_non_enoent_error_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import specstyle.exporting.bundle as bundle_mod

    real_stat = os.stat

    def denied_stat(path, *args, **kwargs):
        if path == "denied" and kwargs.get("dir_fd") is not None:
            raise PermissionError("inspection denied")
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(os, "stat", denied_stat)
    root_fd = _root_fd(tmp_path)
    try:
        with pytest.raises(InfrastructureError, match="^export readback failed$"):
            bundle_mod._inspect_final_bundle(
                _prepare_export(_export_request()), root_fd, "denied"
            )
    finally:
        os.close(root_fd)


def test_inspect_preconfirmed_final_disappearing_before_open_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import specstyle.exporting.bundle as bundle_mod

    _publish(tmp_path, "vanishing")
    real_open_dir = bundle_mod._open_dir
    triggered = False

    def vanish_then_open(parent_fd: int, name: str) -> int:
        nonlocal triggered
        if name == "vanishing" and not triggered:
            triggered = True
            os.rename(
                "vanishing",
                ".vanished-after-lstat",
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
            )
        return real_open_dir(parent_fd, name)

    monkeypatch.setattr(bundle_mod, "_open_dir", vanish_then_open)
    root_fd = _root_fd(tmp_path)
    try:
        with pytest.raises(DomainError, match="^export hash mismatch$"):
            bundle_mod._inspect_final_bundle(
                _prepare_export(_export_request()), root_fd, "vanishing"
            )
    finally:
        os.close(root_fd)
    assert triggered
    assert (tmp_path / ".vanished-after-lstat").is_dir()


def test_inspect_same_name_exact_tree_swap_before_open_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import specstyle.exporting.bundle as bundle_mod

    _publish(tmp_path, "preopen")
    _publish(tmp_path, "replacement")
    real_open_dir = bundle_mod._open_dir
    triggered = False

    def swap_then_open(parent_fd: int, name: str) -> int:
        nonlocal triggered
        if name == "preopen" and not triggered:
            triggered = True
            os.rename(
                "preopen",
                ".preopen-original",
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
            )
            os.rename(
                "replacement",
                "preopen",
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
            )
        return real_open_dir(parent_fd, name)

    monkeypatch.setattr(bundle_mod, "_open_dir", swap_then_open)
    root_fd = _root_fd(tmp_path)
    try:
        with pytest.raises(DomainError, match="^export hash mismatch$"):
            bundle_mod._inspect_final_bundle(
                _prepare_export(_export_request()), root_fd, "preopen"
            )
    finally:
        os.close(root_fd)
    assert triggered
    assert (tmp_path / "preopen").is_dir()
    assert (tmp_path / ".preopen-original").is_dir()


@pytest.mark.parametrize("mutation", ["restore", "delete", "add"])
def test_inspect_mutation_after_readback_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    import specstyle.exporting.bundle as bundle_mod

    prepared = _prepare_export(_export_request())
    _publish(tmp_path, "postread")
    final = tmp_path / "postread"
    payload = prepared.payload_files[0]
    payload_path = final / payload.relative_path
    real_readback = bundle_mod._readback
    triggered = False

    def readback_then_mutate(staging_fd, expected_prepared, expected):
        nonlocal triggered
        real_readback(staging_fd, expected_prepared, expected)
        triggered = True
        if mutation == "restore":
            before = payload_path.stat()
            payload_path.write_bytes(b"temporary corruption")
            payload_path.write_bytes(payload.content)
            os.utime(
                payload_path,
                ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000),
            )
        elif mutation == "delete":
            payload_path.unlink()
        else:
            (final / "late-entry").write_bytes(b"late")

    monkeypatch.setattr(bundle_mod, "_readback", readback_then_mutate)
    root_fd = _root_fd(tmp_path)
    try:
        with pytest.raises(DomainError, match="^export hash mismatch$"):
            bundle_mod._inspect_final_bundle(prepared, root_fd, "postread")
    finally:
        os.close(root_fd)
    assert triggered


def test_same_bundle_inspections_serialize_through_s1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import specstyle.exporting.bundle as bundle_mod

    _publish(tmp_path, "same")
    prepared = _prepare_export(_export_request())
    real_inspect = bundle_mod._inspect_open_final
    first_entered = Event()
    second_entered = Event()
    release_first = Event()
    counter_lock = Lock()
    calls = 0

    def blocking_inspect(*args, **kwargs):
        nonlocal calls
        with counter_lock:
            calls += 1
            call_number = calls
        if call_number == 1:
            first_entered.set()
            assert release_first.wait(timeout=10)
        else:
            second_entered.set()
        return real_inspect(*args, **kwargs)

    def inspect_same() -> ExportBundle | None:
        root_fd = _root_fd(tmp_path)
        try:
            return bundle_mod._inspect_final_bundle(prepared, root_fd, "same")
        finally:
            os.close(root_fd)

    monkeypatch.setattr(bundle_mod, "_inspect_open_final", blocking_inspect)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(inspect_same)
        assert first_entered.wait(timeout=10)
        second = pool.submit(inspect_same)
        serialized = not second_entered.wait(timeout=0.2)
        release_first.set()
        results = (first.result(timeout=20), second.result(timeout=20))

    assert serialized
    assert results[0] == results[1]
    assert bundle_mod._BUNDLE_LOCKS == {}


def test_different_bundle_inspections_can_overlap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import specstyle.exporting.bundle as bundle_mod

    _publish(tmp_path, "first")
    _publish(tmp_path, "second")
    prepared = _prepare_export(_export_request())
    real_inspect = bundle_mod._inspect_open_final
    rendezvous = Barrier(2)

    def overlapping_inspect(*args, **kwargs):
        rendezvous.wait(timeout=10)
        return real_inspect(*args, **kwargs)

    def inspect_named(bundle_name: str) -> ExportBundle | None:
        root_fd = _root_fd(tmp_path)
        try:
            return bundle_mod._inspect_final_bundle(prepared, root_fd, bundle_name)
        finally:
            os.close(root_fd)

    monkeypatch.setattr(bundle_mod, "_inspect_open_final", overlapping_inspect)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = tuple(
            pool.submit(inspect_named, name) for name in ("first", "second")
        )
        results = tuple(future.result(timeout=20) for future in futures)

    assert all(result is not None for result in results)
    assert bundle_mod._BUNDLE_LOCKS == {}


def test_commit_rejects_staging_name_swap_before_native_rename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import specstyle.exporting.bundle as bundle_mod

    before = _fd_count()
    root_fd = _root_fd(tmp_path)
    try:
        staged = bundle_mod._stage_bundle(_export_request(), root_fd, "forged-final")
    finally:
        os.close(root_fd)
    staging_name = next(tmp_path.iterdir()).name
    real_rename = bundle_mod._native_rename
    preserved_name = ".verified-staging-preserved"

    def swap_then_rename(
        from_fd: int, from_name: str, to_fd: int, to_name: str
    ) -> None:
        os.rename(
            from_name,
            preserved_name,
            src_dir_fd=from_fd,
            dst_dir_fd=from_fd,
        )
        os.mkdir(from_name, 0o700, dir_fd=from_fd)
        attacker_dir_fd = os.open(
            from_name,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            dir_fd=from_fd,
        )
        try:
            forged_fd = os.open(
                "FORGED",
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
                dir_fd=attacker_dir_fd,
            )
            try:
                os.write(forged_fd, b"forged")
            finally:
                os.close(forged_fd)
        finally:
            os.close(attacker_dir_fd)
        real_rename(from_fd, from_name, to_fd, to_name)

    monkeypatch.setattr(bundle_mod, "_native_rename", swap_then_rename)
    with pytest.raises(
        InfrastructureError, match="^export publication verification failed$"
    ):
        bundle_mod._commit_staged_bundle(staged, accept_exact_existing=False)

    assert not (tmp_path / staging_name).exists()
    assert (tmp_path / preserved_name / "manifest.json").is_file()
    assert (tmp_path / "forged-final" / "FORGED").read_bytes() == b"forged"
    assert _fd_count() == before


@pytest.mark.parametrize(
    ("failure", "error_type", "message"),
    [
        (
            "readback",
            InfrastructureError,
            "export publication verification failed",
        ),
        ("root_return", DomainError, "invalid staged export"),
    ],
)
def test_commit_postpublish_failure_keeps_final_and_consumes_capability(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
    error_type: type[Exception],
    message: str,
) -> None:
    import specstyle.exporting.bundle as bundle_mod

    prepared = _prepare_export(_export_request())
    before = _fd_count()
    root_fd = _root_fd(tmp_path)
    try:
        staged = bundle_mod._stage_bundle(_export_request(), root_fd, "published")
    finally:
        os.close(root_fd)
    staging = next(tmp_path.iterdir())
    real_verify = bundle_mod._verify_published_final

    def fail_after_publish(candidate, final_fd, opened):
        if failure == "readback":
            payload = tmp_path / "published" / prepared.payload_files[0].relative_path
            payload.write_bytes(b"post-publish tamper")
        real_verify(candidate, final_fd, opened)
        if failure == "root_return":
            tmp_path.chmod(0o750)

    monkeypatch.setattr(bundle_mod, "_verify_published_final", fail_after_publish)
    with pytest.raises(error_type, match=f"^{message}$"):
        bundle_mod._commit_staged_bundle(staged, accept_exact_existing=False)

    assert not staging.exists()
    assert (tmp_path / "published").is_dir()
    with pytest.raises(DomainError, match="^invalid staged export$"):
        bundle_mod._commit_staged_bundle(staged, accept_exact_existing=False)
    assert _fd_count() == before


@pytest.mark.parametrize(
    ("mode", "message"),
    [(0o750, "invalid staged export"), (0o770, "invalid export target")],
)
def test_commit_rejects_root_permission_or_identity_drift(
    tmp_path: Path, mode: int, message: str
) -> None:
    import specstyle.exporting.bundle as bundle_mod

    root_fd = _root_fd(tmp_path)
    try:
        staged = bundle_mod._stage_bundle(_export_request(), root_fd, "never-final")
    finally:
        os.close(root_fd)
    staging = next(tmp_path.iterdir())
    tmp_path.chmod(mode)

    with pytest.raises(DomainError, match=f"^{message}$"):
        bundle_mod._commit_staged_bundle(staged, accept_exact_existing=False)

    assert staging.is_dir()
    assert not (tmp_path / "never-final").exists()


def test_commit_fresh_bundle_uses_no_replace_then_fsyncs_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import specstyle.exporting.bundle as bundle_mod

    before = _fd_count()
    root_fd = _root_fd(tmp_path)
    try:
        staged = bundle_mod._stage_bundle(_export_request(), root_fd, "fresh")
    finally:
        os.close(root_fd)
    staging_path = next(tmp_path.iterdir())
    owned_root_fd = staged._root_fd
    real_rename = bundle_mod._native_rename
    real_fsync = os.fsync
    renames: list[tuple[int, str, int, str]] = []
    root_syncs: list[int] = []

    def rename_spy(from_fd: int, from_name: str, to_fd: int, to_name: str) -> None:
        renames.append((from_fd, from_name, to_fd, to_name))
        real_rename(from_fd, from_name, to_fd, to_name)

    def fsync_spy(fd: int) -> None:
        if fd == owned_root_fd:
            root_syncs.append(fd)
        real_fsync(fd)

    monkeypatch.setattr(bundle_mod, "_native_rename", rename_spy)
    monkeypatch.setattr(os, "fsync", fsync_spy)
    committed = bundle_mod._commit_staged_bundle(staged, accept_exact_existing=False)

    assert committed.bundle_name == "fresh"
    assert renames == [(owned_root_fd, staging_path.name, owned_root_fd, "fresh")]
    assert root_syncs == [owned_root_fd]
    assert not staging_path.exists()
    assert (tmp_path / "fresh" / "manifest.json").is_file()
    assert _fd_count() == before


def test_commit_eexist_false_preserves_old_error_and_existing_identity(
    tmp_path: Path,
) -> None:
    import specstyle.exporting.bundle as bundle_mod

    _publish(tmp_path, "existing")
    existing = tmp_path / "existing"
    metadata_before = _tree_metadata(existing)
    before = _fd_count()
    root_fd = _root_fd(tmp_path)
    try:
        staged = bundle_mod._stage_bundle(_export_request(), root_fd, "existing")
    finally:
        os.close(root_fd)
    staging_path = next(
        path for path in tmp_path.iterdir() if path.name.startswith(".")
    )

    with pytest.raises(DomainError, match="^export target exists$"):
        bundle_mod._commit_staged_bundle(staged, accept_exact_existing=False)

    assert _tree_metadata(existing) == metadata_before
    assert staging_path.is_dir()
    assert _fd_count() == before


def test_commit_eexist_true_converges_exact_without_touching_existing(
    tmp_path: Path,
) -> None:
    import specstyle.exporting.bundle as bundle_mod

    published = _publish(tmp_path, "existing")
    existing = tmp_path / "existing"
    metadata_before = _tree_metadata(existing)
    before = _fd_count()
    root_fd = _root_fd(tmp_path)
    try:
        staged = bundle_mod._stage_bundle(_export_request(), root_fd, "existing")
    finally:
        os.close(root_fd)
    staging_path = next(
        path for path in tmp_path.iterdir() if path.name.startswith(".")
    )

    converged = bundle_mod._commit_staged_bundle(staged, accept_exact_existing=True)

    assert converged == published
    assert _tree_metadata(existing) == metadata_before
    assert staging_path.is_dir()
    assert _fd_count() == before


def test_commit_eexist_true_conflict_preserves_staging_and_fails_closed(
    tmp_path: Path,
) -> None:
    import specstyle.exporting.bundle as bundle_mod

    prepared = _prepare_export(_export_request())
    _publish(tmp_path, "conflict")
    (tmp_path / "conflict" / "manifest.json").write_bytes(b'{"forged":true}')
    before = _fd_count()
    root_fd = _root_fd(tmp_path)
    try:
        staged = bundle_mod._stage_bundle(_export_request(), root_fd, "conflict")
    finally:
        os.close(root_fd)
    staging_path = next(
        path for path in tmp_path.iterdir() if path.name.startswith(".")
    )

    with pytest.raises(DomainError, match="^export hash mismatch$"):
        bundle_mod._commit_staged_bundle(staged, accept_exact_existing=True)

    assert staging_path.is_dir()
    assert (staging_path / prepared.manifest_file.relative_path).is_file()
    with pytest.raises(DomainError, match="^invalid staged export$"):
        bundle_mod._commit_staged_bundle(staged, accept_exact_existing=True)
    assert _fd_count() == before


def test_commit_root_fsync_failure_keeps_final_and_consumes_capability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import specstyle.exporting.bundle as bundle_mod

    before = _fd_count()
    root_fd = _root_fd(tmp_path)
    try:
        staged = bundle_mod._stage_bundle(_export_request(), root_fd, "durability")
    finally:
        os.close(root_fd)
    staging_path = next(tmp_path.iterdir())
    owned_root_fd = staged._root_fd
    real_fsync = os.fsync

    def root_fsync_fails(fd: int) -> None:
        if fd == owned_root_fd:
            raise OSError("root durability failed")
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", root_fsync_fails)
    with pytest.raises(
        InfrastructureError,
        match="^export published but directory fsync failed$",
    ):
        bundle_mod._commit_staged_bundle(staged, accept_exact_existing=False)
    staged.close()

    assert not staging_path.exists()
    assert (tmp_path / "durability" / "manifest.json").is_file()
    with pytest.raises(DomainError, match="^invalid staged export$"):
        bundle_mod._commit_staged_bundle(staged, accept_exact_existing=False)
    assert _fd_count() == before


def test_commit_rejects_closed_double_and_forged_capabilities(tmp_path: Path) -> None:
    import specstyle.exporting.bundle as bundle_mod

    root_fd = _root_fd(tmp_path)
    try:
        closed = bundle_mod._stage_bundle(_export_request(), root_fd, "closed")
        committed = bundle_mod._stage_bundle(_export_request(), root_fd, "committed")
    finally:
        os.close(root_fd)
    closed.close()
    bundle_mod._commit_staged_bundle(committed, accept_exact_existing=False)
    forged = object.__new__(bundle_mod._StagedBundle)

    for invalid in (closed, committed, object(), forged):
        with pytest.raises(DomainError, match="^invalid staged export$"):
            bundle_mod._commit_staged_bundle(invalid, accept_exact_existing=False)


def test_commit_two_threads_same_final_have_one_publish_and_one_exact_convergence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import specstyle.exporting.bundle as bundle_mod

    root_fd = _root_fd(tmp_path)
    try:
        staged = tuple(
            bundle_mod._stage_bundle(_export_request(), root_fd, "shared")
            for _ in range(2)
        )
    finally:
        os.close(root_fd)
    real_rename = bundle_mod._native_rename
    counter_lock = Lock()
    successful_renames = 0

    def racing_rename(from_fd: int, from_name: str, to_fd: int, to_name: str) -> None:
        nonlocal successful_renames
        real_rename(from_fd, from_name, to_fd, to_name)
        with counter_lock:
            successful_renames += 1

    monkeypatch.setattr(bundle_mod, "_native_rename", racing_rename)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = tuple(
            pool.submit(
                bundle_mod._commit_staged_bundle,
                candidate,
                accept_exact_existing=True,
            )
            for candidate in staged
        )
        results = tuple(future.result(timeout=20) for future in futures)

    assert results[0] == results[1]
    assert successful_renames == 1
    assert (tmp_path / "shared" / "manifest.json").is_file()
    stale = tuple(path for path in tmp_path.iterdir() if path.name.startswith("."))
    assert len(stale) == 1
    assert (stale[0] / "manifest.json").is_file()


@pytest.mark.parametrize("tamper", ["content", "inventory"])
def test_commit_rejects_tampered_staging_before_native_rename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tamper: str
) -> None:
    import specstyle.exporting.bundle as bundle_mod

    prepared = _prepare_export(_export_request())
    before = _fd_count()
    root_fd = _root_fd(tmp_path)
    try:
        staged = bundle_mod._stage_bundle(_export_request(), root_fd, "never-final")
    finally:
        os.close(root_fd)
    staging_path = next(tmp_path.iterdir())
    if tamper == "content":
        (staging_path / prepared.payload_files[0].relative_path).write_bytes(b"tamper")
    else:
        (staging_path / "late-entry").write_bytes(b"tamper")

    def unexpected_rename(*_args: object) -> None:
        raise AssertionError("tampered staging reached native rename")

    monkeypatch.setattr(bundle_mod, "_native_rename", unexpected_rename)
    with pytest.raises(DomainError, match="^export hash mismatch$"):
        bundle_mod._commit_staged_bundle(staged, accept_exact_existing=False)

    assert not (tmp_path / "never-final").exists()
    assert staging_path.is_dir()
    with pytest.raises(DomainError, match="^invalid staged export$"):
        bundle_mod._commit_staged_bundle(staged, accept_exact_existing=False)
    assert _fd_count() == before


@pytest.mark.parametrize(
    ("platform", "function_name", "expected_flag"),
    [
        ("linux", "renameat2", 1),
        ("darwin", "renameatx_np", 0x00000004),
    ],
)
def test_native_rename_uses_platform_no_replace_flag(
    monkeypatch: pytest.MonkeyPatch,
    platform: str,
    function_name: str,
    expected_flag: int,
) -> None:
    import specstyle.exporting.bundle as bundle_mod

    class NativeCall:
        argtypes = None
        restype = None

        def __init__(self) -> None:
            self.calls: list[tuple[object, ...]] = []

        def __call__(self, *args: object) -> int:
            self.calls.append(args)
            return 0

    native_call = NativeCall()
    fake_libc = type("FakeLibc", (), {function_name: native_call})()
    monkeypatch.setattr(bundle_mod, "_libc", lambda: fake_libc)
    monkeypatch.setattr(bundle_mod.sys, "platform", platform)

    bundle_mod._native_rename(10, "from", 11, "to")

    assert len(native_call.calls) == 1
    assert native_call.calls[0][-1] == expected_flag


def test_two_writers_same_name_exactly_one_wins(tmp_path: Path) -> None:
    root_fd = _root_fd(tmp_path)
    try:
        bundle = export_bundle(_export_request(), root_fd, "shared")
    finally:
        os.close(root_fd)
    assert bundle.bundle_name == "shared"
    root_fd = _root_fd(tmp_path)
    try:
        with pytest.raises(DomainError, match="export target exists"):
            export_bundle(_export_request(), root_fd, "shared")
    finally:
        os.close(root_fd)
    assert (tmp_path / "shared").is_dir()


def test_native_no_replace_leaves_no_partial_final(tmp_path: Path) -> None:
    (tmp_path / "collide").mkdir()
    root_fd = _root_fd(tmp_path)
    try:
        with pytest.raises(DomainError, match="export target exists"):
            export_bundle(_export_request(), root_fd, "collide")
    finally:
        os.close(root_fd)
    # The original directory remains empty and has no manifest.
    assert not (tmp_path / "collide" / "manifest.json").exists()


def test_short_write_raises_and_leaves_no_final(tmp_path: Path, monkeypatch) -> None:
    real_write = os.write
    state = {"n": 0}

    def short_write(fd: int, data: bytes) -> int:
        state["n"] += 1
        if state["n"] == 1 and data:
            return 0
        return real_write(fd, data)

    monkeypatch.setattr(os, "write", short_write)
    root_fd = _root_fd(tmp_path)
    try:
        with pytest.raises(InfrastructureError, match="export write failed"):
            export_bundle(_export_request(), root_fd, "short")
    finally:
        os.close(root_fd)
    assert not (tmp_path / "short").exists()


def test_fsync_failure_raises_sync_failed(tmp_path: Path, monkeypatch) -> None:
    def boom(fd: int) -> None:
        raise OSError("sync denied")

    monkeypatch.setattr(os, "fsync", boom)
    root_fd = _root_fd(tmp_path)
    try:
        with pytest.raises(InfrastructureError, match="export sync failed"):
            export_bundle(_export_request(), root_fd, "syncfail")
    finally:
        os.close(root_fd)
    assert not (tmp_path / "syncfail").exists()


def test_readback_failure_raises_readback_failed(tmp_path: Path, monkeypatch) -> None:
    def boom(fd: int, n: int) -> bytes:
        raise OSError("read denied")

    # Trigger only during post-write readback; writing does not call os.read.
    monkeypatch.setattr(os, "read", boom)
    root_fd = _root_fd(tmp_path)
    try:
        with pytest.raises(InfrastructureError, match="export readback failed"):
            export_bundle(_export_request(), root_fd, "rback")
    finally:
        os.close(root_fd)
    assert not (tmp_path / "rback").exists()


def test_root_fd_not_directory_rejected(tmp_path: Path) -> None:
    file_path = tmp_path / "file"
    file_path.write_text("x")
    fd = os.open(os.fspath(file_path), os.O_RDONLY)
    try:
        with pytest.raises(DomainError, match="invalid export target"):
            export_bundle(_export_request(), fd, "x")
    finally:
        os.close(fd)


def test_bundle_name_rejects_path_escape(tmp_path: Path) -> None:
    root_fd = _root_fd(tmp_path)
    try:
        with pytest.raises(DomainError, match="invalid export target"):
            export_bundle(_export_request(), root_fd, "../escape")
    finally:
        os.close(root_fd)
    assert not (tmp_path.parent / "escape").exists()


def test_post_rename_fsync_failure_keeps_final(tmp_path: Path, monkeypatch) -> None:
    import specstyle.exporting.bundle as bundle_mod

    real_rename = bundle_mod._native_rename
    real_fsync = os.fsync
    state = {"renamed": False}

    def rename_wrapper(from_fd, from_name, to_fd, to_name):
        result = real_rename(from_fd, from_name, to_fd, to_name)
        state["renamed"] = True
        return result

    def fsync_boom(fd: int) -> None:
        if state["renamed"]:
            raise OSError("post-rename fsync denied")
        return real_fsync(fd)

    monkeypatch.setattr(bundle_mod, "_native_rename", rename_wrapper)
    monkeypatch.setattr(os, "fsync", fsync_boom)
    root_fd = _root_fd(tmp_path)
    try:
        with pytest.raises(
            InfrastructureError, match="export published but directory fsync failed"
        ):
            export_bundle(_export_request(), root_fd, "postren")
    finally:
        os.close(root_fd)
    # final must NOT be deleted (§13.11)
    final = tmp_path / "postren"
    assert final.is_dir()
    assert (final / "manifest.json").exists()


def test_native_unavailable_fails_closed(tmp_path: Path, monkeypatch) -> None:
    import specstyle.exporting.bundle as bundle_mod

    def boom(*a: object, **k: object) -> None:
        raise InfrastructureError("secure atomic publication unavailable")

    monkeypatch.setattr(bundle_mod, "_native_rename", boom)
    root_fd = _root_fd(tmp_path)
    try:
        with pytest.raises(
            InfrastructureError, match="secure atomic publication unavailable"
        ):
            export_bundle(_export_request(), root_fd, "native")
    finally:
        os.close(root_fd)
    assert not (tmp_path / "native").exists()
    stale = tuple(tmp_path.iterdir())
    assert len(stale) == 1
    assert stale[0].name.startswith(".")


def test_readback_mismatch_does_not_publish(tmp_path: Path, monkeypatch) -> None:
    import specstyle.exporting.bundle as bundle_mod

    def boom(*a: object, **k: object) -> None:
        raise DomainError("export hash mismatch")

    monkeypatch.setattr(bundle_mod, "_readback_file", boom)
    root_fd = _root_fd(tmp_path)
    try:
        with pytest.raises(DomainError, match="export hash mismatch"):
            export_bundle(_export_request(), root_fd, "mismatch")
    finally:
        os.close(root_fd)
    assert not (tmp_path / "mismatch").exists()
    stale = tuple(tmp_path.iterdir())
    assert len(stale) == 1
    assert stale[0].name.startswith(".")


def test_existing_leaf_symlink_target_not_overwritten(tmp_path: Path) -> None:
    """Final leaf name is a symlink → no-replace fails closed; symlink kept."""
    target = tmp_path / "real_target"
    target.mkdir()
    (target / "marker").write_text("keep")
    link = tmp_path / "leaf_link"
    link.symlink_to(target)
    root_fd = _root_fd(tmp_path)
    try:
        with pytest.raises(DomainError, match="export target exists"):
            export_bundle(_export_request(), root_fd, "leaf_link")
    finally:
        os.close(root_fd)
    assert link.is_symlink()
    assert (target / "marker").read_text() == "keep"
    assert not (target / "manifest.json").exists()


def test_parent_symlink_component_fails_closed(tmp_path: Path, monkeypatch) -> None:
    """Intermediate dir component replaced by symlink → O_NOFOLLOW fails closed."""
    import specstyle.exporting.bundle as bundle_mod

    real_mkdir = bundle_mod._mkdir_rel
    state = {"done": False}

    def mkdir_then_symlink(staging_fd, parts, dir_ids):
        real_mkdir(staging_fd, parts, dir_ids)
        if parts == ("approved",) and not state["done"]:
            state["done"] = True
            # Replace approved with a same-name symlink to simulate TOCTOU.
            os.rmdir("approved", dir_fd=staging_fd)
            os.symlink(".", "approved", dir_fd=staging_fd)
            dir_ids.pop("approved", None)
            for key in list(dir_ids):
                if key.startswith("approved/"):
                    dir_ids.pop(key)

    monkeypatch.setattr(bundle_mod, "_mkdir_rel", mkdir_then_symlink)
    root_fd = _root_fd(tmp_path)
    try:
        with pytest.raises(
            (InfrastructureError, DomainError),
            match="export (write|readback) failed|export hash mismatch",
        ):
            export_bundle(_export_request(), root_fd, "parent_sym")
    finally:
        os.close(root_fd)
    assert not (tmp_path / "parent_sym").exists()


def test_primary_failure_preserves_staging_without_online_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import specstyle.exporting.bundle as bundle_mod

    def boom_readback(*a: object, **k: object) -> None:
        raise DomainError("export hash mismatch")

    def unexpected_unlink(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("online staging cleanup is disabled")

    monkeypatch.setattr(bundle_mod, "_readback_file", boom_readback)
    monkeypatch.setattr(os, "unlink", unexpected_unlink)
    root_fd = _root_fd(tmp_path)
    try:
        with pytest.raises(DomainError, match="export hash mismatch"):
            export_bundle(_export_request(), root_fd, "mask")
    finally:
        os.close(root_fd)
    assert not (tmp_path / "mask").exists()
    stale = tuple(tmp_path.iterdir())
    assert len(stale) == 1
    assert stale[0].name.startswith(".")


def test_staging_root_fsync_is_invoked(tmp_path: Path, monkeypatch) -> None:
    """_fsync_dir(staging_fd, ()) fsyncs the staging root dirfd."""
    real_fsync = os.fsync
    seen: list[int] = []

    def spy_fsync(fd: int) -> None:
        seen.append(fd)
        return real_fsync(fd)

    monkeypatch.setattr(os, "fsync", spy_fsync)
    root_fd = _root_fd(tmp_path)
    try:
        export_bundle(_export_request(), root_fd, "fsync_root")
    finally:
        os.close(root_fd)
    # Cover file fsync, staging root, final root, and the empty-parts path.
    assert len(seen) >= 3
