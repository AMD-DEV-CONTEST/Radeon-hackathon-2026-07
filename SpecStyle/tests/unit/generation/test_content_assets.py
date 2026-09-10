"""Security and lifecycle contract for local content-addressed style assets."""

from __future__ import annotations

from io import BytesIO
import os
from pathlib import Path
import stat
import threading

import pytest
from PIL import Image, PngImagePlugin

from specstyle.domain.artifacts import AssetRef
from specstyle.domain.identifiers import AssetId
from specstyle.errors import DomainError, InfrastructureError
from specstyle.generation.content_assets import open_content_addressed_style_resolver
from specstyle.observability.hashing import hash_bytes


def _png(
    *,
    size: tuple[int, int] = (64, 64),
    mode: str = "RGB",
    metadata: bool = False,
) -> bytes:
    output = BytesIO()
    info = None
    if metadata:
        info = PngImagePlugin.PngInfo()
        info.add_text("comment", "not allowed")
    Image.new(mode, size, 7).save(output, "PNG", pnginfo=info)
    return output.getvalue()


def _ref(content: bytes, asset_id: str = "style") -> AssetRef:
    return AssetRef(AssetId(asset_id), hash_bytes(content))


def _path(root: Path, reference: AssetRef) -> Path:
    digest = reference.sha256.value
    return root / "sha256" / digest[:2] / digest


def _write(root: Path, content: bytes, reference: AssetRef | None = None) -> AssetRef:
    reference = _ref(content) if reference is None else reference
    path = _path(root, reference)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    path.chmod(0o600)
    return reference


def _open_root(root: Path) -> int:
    root.chmod(0o700)
    return os.open(root, os.O_RDONLY | os.O_DIRECTORY)


def _resolver(root: Path, reference: AssetRef, size: tuple[int, int] = (64, 64)):
    root_fd = _open_root(root)
    try:
        resolver = open_content_addressed_style_resolver(root_fd, (reference,), size)
        os.fstat(root_fd)
        return resolver, root_fd
    except BaseException:
        os.close(root_fd)
        raise


def test_resolver_reads_only_digest_derived_clean_rgb_png(tmp_path: Path) -> None:
    content = _png()
    reference = _write(tmp_path, content)
    resolver, root_fd = _resolver(tmp_path, reference)
    try:
        assert resolver(AssetRef(AssetId("style"), reference.sha256)) == content
    finally:
        resolver.close()
        os.fstat(root_fd)
        os.close(root_fd)


@pytest.mark.parametrize(
    ("root_fd", "allowed", "size"),
    [
        (True, (), (64, 64)),
        (-1, (), (64, 64)),
        (0, [], (64, 64)),
        (0, (), (64, 64)),
        (0, (object(),), (64, 64)),
        (0, (), [64, 64]),
        (0, (), (64,)),
        (0, (), (True, 64)),
        (0, (), (56, 64)),
        (0, (), (4104, 64)),
    ],
)
def test_factory_rejects_nonexact_inputs(
    root_fd: object, allowed: object, size: object
) -> None:
    with pytest.raises(DomainError):
        open_content_addressed_style_resolver(  # type: ignore[arg-type]
            root_fd, allowed, size
        )


def test_factory_rejects_duplicate_and_subclass_references(tmp_path: Path) -> None:
    content = _png()
    reference = _write(tmp_path, content)

    class HostileRef(AssetRef):
        pass

    root_fd = _open_root(tmp_path)
    try:
        with pytest.raises(DomainError):
            open_content_addressed_style_resolver(
                root_fd, (reference, reference), (64, 64)
            )
        with pytest.raises(DomainError):
            open_content_addressed_style_resolver(
                root_fd,
                (HostileRef(reference.asset_id, reference.sha256),),
                (64, 64),
            )
    finally:
        os.close(root_fd)


def test_factory_rejects_non_directory_foreign_or_writable_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file_path = tmp_path / "file"
    file_path.write_bytes(b"x")
    file_fd = os.open(file_path, os.O_RDONLY)
    try:
        with pytest.raises(InfrastructureError):
            open_content_addressed_style_resolver(file_fd, (_ref(_png()),), (64, 64))
    finally:
        os.close(file_fd)

    content = _png()
    reference = _write(tmp_path, content)
    tmp_path.chmod(0o720)
    root_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(InfrastructureError):
            open_content_addressed_style_resolver(root_fd, (reference,), (64, 64))
    finally:
        os.close(root_fd)
        tmp_path.chmod(0o700)

    root_fd = _open_root(tmp_path)
    real_fstat = os.fstat
    first = True

    def foreign_owner(fd: int) -> os.stat_result:
        nonlocal first
        result = real_fstat(fd)
        if first:
            first = False
            values = list(result)
            values[stat.ST_UID] = result.st_uid + 1
            return os.stat_result(values)
        return result

    monkeypatch.setattr("specstyle.generation.content_assets.os.fstat", foreign_owner)
    try:
        with pytest.raises(InfrastructureError):
            open_content_addressed_style_resolver(root_fd, (reference,), (64, 64))
        real_fstat(root_fd)
    finally:
        os.close(root_fd)


def test_factory_maps_root_stat_failure_and_closes_its_duplicate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = _png()
    reference = _write(tmp_path, content)
    root_fd = _open_root(tmp_path)
    before = len(os.listdir("/dev/fd"))
    monkeypatch.setattr(
        "specstyle.generation.content_assets.os.fstat",
        lambda _fd: (_ for _ in ()).throw(OSError("stat failed")),
    )
    try:
        with pytest.raises(InfrastructureError):
            open_content_addressed_style_resolver(root_fd, (reference,), (64, 64))
        assert len(os.listdir("/dev/fd")) == before
    finally:
        os.close(root_fd)


def test_factory_preserves_root_stat_failure_and_notes_duplicate_close_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = _png()
    reference = _write(tmp_path, content)
    root_fd = _open_root(tmp_path)
    real_dup = os.dup
    real_fstat = os.fstat
    real_close = os.close
    duplicated: list[int] = []
    close_attempts: list[int] = []

    def tracked_dup(fd: int) -> int:
        duplicate = real_dup(fd)
        duplicated.append(duplicate)
        return duplicate

    def failing_fstat(fd: int) -> os.stat_result:
        if fd in duplicated:
            raise OSError("root-stat")
        return real_fstat(fd)

    def failing_close(fd: int) -> None:
        real_close(fd)
        if fd in duplicated:
            close_attempts.append(fd)
            raise OSError("duplicate-close")

    monkeypatch.setattr("specstyle.generation.content_assets.os.dup", tracked_dup)
    monkeypatch.setattr("specstyle.generation.content_assets.os.fstat", failing_fstat)
    monkeypatch.setattr("specstyle.generation.content_assets.os.close", failing_close)
    try:
        with pytest.raises(InfrastructureError) as caught:
            open_content_addressed_style_resolver(root_fd, (reference,), (64, 64))
        assert type(caught.value.__cause__) is OSError
        assert str(caught.value.__cause__) == "root-stat"
        assert caught.value.__notes__ == ["style asset cleanup failed"]
        assert close_attempts == duplicated
    finally:
        monkeypatch.undo()
        os.close(root_fd)


def test_factory_preserves_issue_failure_and_notes_duplicate_close_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = _png()
    reference = _write(tmp_path, content)
    root_fd = _open_root(tmp_path)
    real_dup = os.dup
    real_close = os.close
    duplicated: list[int] = []
    primary = MemoryError("issue-memory")

    def tracked_dup(fd: int) -> int:
        duplicate = real_dup(fd)
        duplicated.append(duplicate)
        return duplicate

    def failing_close(fd: int) -> None:
        real_close(fd)
        if fd in duplicated:
            raise OSError("duplicate-close")

    monkeypatch.setattr("specstyle.generation.content_assets.os.dup", tracked_dup)
    monkeypatch.setattr("specstyle.generation.content_assets.os.close", failing_close)
    monkeypatch.setattr(
        "specstyle.generation.content_assets.threading.Lock",
        lambda: (_ for _ in ()).throw(primary),
    )
    try:
        with pytest.raises(MemoryError) as caught:
            open_content_addressed_style_resolver(root_fd, (reference,), (64, 64))
        assert caught.value is primary
        assert caught.value.__notes__ == ["style asset cleanup failed"]
    finally:
        monkeypatch.undo()
        os.close(root_fd)


def test_directory_open_preserves_memory_error_and_notes_fd_close_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = _png()
    reference = _write(tmp_path, content)
    resolver, root_fd = _resolver(tmp_path, reference)
    real_open = os.open
    real_fstat = os.fstat
    real_close = os.close
    internal_fds: list[int] = []
    close_attempts: list[int] = []
    primary = MemoryError("directory-stat-memory")

    def tracked_open(path: str, flags: int, *args: object, **kwargs: object) -> int:
        fd = real_open(path, flags, *args, **kwargs)  # type: ignore[arg-type]
        if path == "sha256":
            internal_fds.append(fd)
        return fd

    def failing_fstat(fd: int) -> os.stat_result:
        if fd in internal_fds:
            raise primary
        return real_fstat(fd)

    def failing_close(fd: int) -> None:
        real_close(fd)
        if fd in internal_fds:
            close_attempts.append(fd)
            raise OSError("directory-close")

    monkeypatch.setattr("specstyle.generation.content_assets.os.open", tracked_open)
    monkeypatch.setattr("specstyle.generation.content_assets.os.fstat", failing_fstat)
    monkeypatch.setattr("specstyle.generation.content_assets.os.close", failing_close)
    try:
        with pytest.raises(MemoryError) as caught:
            resolver(reference)
        assert caught.value is primary
        assert close_attempts == internal_fds
        assert caught.value.__notes__ == ["style asset cleanup failed"]
    finally:
        monkeypatch.undo()
        for fd in internal_fds:
            try:
                real_fstat(fd)
            except OSError:
                pass
            else:
                real_close(fd)
        resolver.close()
        os.close(root_fd)


def test_resolver_rejects_unauthorized_and_nonexact_call_reference(
    tmp_path: Path,
) -> None:
    content = _png()
    reference = _write(tmp_path, content)
    resolver, root_fd = _resolver(tmp_path, reference)

    class HostileRef(AssetRef):
        pass

    try:
        with pytest.raises(DomainError):
            resolver(_ref(content, "other"))
        with pytest.raises(DomainError):
            resolver(HostileRef(reference.asset_id, reference.sha256))
        with pytest.raises(DomainError):
            resolver(object())  # type: ignore[arg-type]
    finally:
        resolver.close()
        os.close(root_fd)


@pytest.mark.parametrize("target", ["sha256", "prefix", "file"])
def test_resolver_refuses_symlinks_at_every_level(tmp_path: Path, target: str) -> None:
    content = _png()
    reference = _ref(content)
    real_root = tmp_path / "real"
    _write(real_root, content, reference)
    real_path = _path(real_root, reference)
    served = tmp_path / "served"
    served.mkdir()
    if target == "sha256":
        (served / "sha256").symlink_to(real_root / "sha256", target_is_directory=True)
    elif target == "prefix":
        (served / "sha256").mkdir()
        (served / "sha256" / reference.sha256.value[:2]).symlink_to(
            real_path.parent, target_is_directory=True
        )
    else:
        digest = reference.sha256.value
        parent = served / "sha256" / digest[:2]
        parent.mkdir(parents=True)
        (parent / digest).symlink_to(real_path)
    resolver, root_fd = _resolver(served, reference)
    try:
        with pytest.raises(InfrastructureError):
            resolver(reference)
    finally:
        resolver.close()
        os.close(root_fd)


@pytest.mark.parametrize("problem", ["fifo", "mode", "nlink", "empty", "oversize"])
def test_resolver_rejects_untrusted_or_bounded_file(
    tmp_path: Path, problem: str
) -> None:
    content = _png()
    reference = _write(tmp_path, content)
    path = _path(tmp_path, reference)
    if problem == "fifo":
        path.unlink()
        os.mkfifo(path)
    elif problem == "mode":
        path.chmod(0o620)
    elif problem == "nlink":
        os.link(path, tmp_path / "alias")
    elif problem == "empty":
        path.write_bytes(b"")
    else:
        with path.open("wb") as stream:
            stream.truncate(32 * 1024 * 1024 + 1)
    resolver, root_fd = _resolver(tmp_path, reference)
    try:
        with pytest.raises(InfrastructureError):
            resolver(reference)
    finally:
        resolver.close()
        os.close(root_fd)


@pytest.mark.parametrize("mode", [0o644, 0o440, 0o640, 0o4400, 0o2400, 0o1400])
def test_resolver_rejects_any_file_mode_outside_owner_read_only_or_read_write(
    tmp_path: Path, mode: int
) -> None:
    content = _png()
    reference = _write(tmp_path, content)
    _path(tmp_path, reference).chmod(mode)
    resolver, root_fd = _resolver(tmp_path, reference)
    try:
        with pytest.raises(InfrastructureError):
            resolver(reference)
    finally:
        resolver.close()
        os.close(root_fd)


@pytest.mark.parametrize("mode", [0o400, 0o600])
def test_resolver_accepts_exact_owner_only_file_modes(
    tmp_path: Path, mode: int
) -> None:
    content = _png()
    reference = _write(tmp_path, content)
    _path(tmp_path, reference).chmod(mode)
    resolver, root_fd = _resolver(tmp_path, reference)
    try:
        assert resolver(reference) == content
    finally:
        resolver.close()
        os.close(root_fd)


def test_resolver_rejects_foreign_owned_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = _png()
    reference = _write(tmp_path, content)
    resolver, root_fd = _resolver(tmp_path, reference)
    real_fstat = os.fstat

    def foreign_regular(fd: int) -> os.stat_result:
        result = real_fstat(fd)
        if stat.S_ISREG(result.st_mode):
            values = list(result)
            values[stat.ST_UID] = result.st_uid + 1
            return os.stat_result(values)
        return result

    monkeypatch.setattr("specstyle.generation.content_assets.os.fstat", foreign_regular)
    try:
        with pytest.raises(InfrastructureError):
            resolver(reference)
    finally:
        resolver.close()
        os.close(root_fd)


def test_resolver_rejects_short_read_and_postread_size_race(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = _png()
    reference = _write(tmp_path, content)
    resolver, root_fd = _resolver(tmp_path, reference)
    monkeypatch.setattr(
        "specstyle.generation.content_assets.os.read", lambda _fd, _n: b""
    )
    try:
        with pytest.raises(InfrastructureError):
            resolver(reference)
    finally:
        resolver.close()
        os.close(root_fd)

    monkeypatch.undo()
    resolver, root_fd = _resolver(tmp_path, reference)
    real_fstat = os.fstat
    regular_calls = 0

    def changed_size(fd: int) -> os.stat_result:
        nonlocal regular_calls
        result = real_fstat(fd)
        if stat.S_ISREG(result.st_mode):
            regular_calls += 1
            if regular_calls == 2:
                values = list(result)
                values[stat.ST_SIZE] = result.st_size + 1
                return os.stat_result(values)
        return result

    monkeypatch.setattr("specstyle.generation.content_assets.os.fstat", changed_size)
    try:
        with pytest.raises(InfrastructureError):
            resolver(reference)
    finally:
        resolver.close()
        os.close(root_fd)


def test_resolver_rejects_hash_mismatch_and_invalid_png_contract(
    tmp_path: Path,
) -> None:
    cases = (_png(metadata=True), _png(mode="L"), _png(size=(72, 64)))
    expected_ref = _ref(_png())
    for index, content in enumerate(cases):
        root = tmp_path / str(index)
        root.mkdir()
        _write(root, content, expected_ref)
        resolver, root_fd = _resolver(root, expected_ref)
        try:
            with pytest.raises(InfrastructureError):
                resolver(expected_ref)
        finally:
            resolver.close()
            os.close(root_fd)

    for index, content in enumerate(cases):
        root = tmp_path / f"valid-hash-{index}"
        root.mkdir()
        reference = _write(root, content)
        resolver, root_fd = _resolver(root, reference)
        try:
            with pytest.raises(InfrastructureError):
                resolver(reference)
        finally:
            resolver.close()
            os.close(root_fd)


def test_close_is_idempotent_fail_closed_and_never_owns_caller_fd(
    tmp_path: Path,
) -> None:
    content = _png()
    reference = _write(tmp_path, content)
    resolver, root_fd = _resolver(tmp_path, reference)
    resolver.close()
    resolver.close()
    os.fstat(root_fd)
    with pytest.raises(InfrastructureError):
        resolver(reference)
    os.close(root_fd)


def _fail_owned_root_close(monkeypatch: pytest.MonkeyPatch, resolver: object) -> None:
    real_close = os.close
    owned_fd = resolver._root_fd  # type: ignore[attr-defined]

    def failing_close(fd: int) -> None:
        real_close(fd)
        if fd == owned_fd:
            raise OSError("root-close")

    monkeypatch.setattr("specstyle.generation.content_assets.os.close", failing_close)


def test_context_manager_propagates_cleanup_error_without_body_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = _png()
    reference = _write(tmp_path, content)
    resolver, root_fd = _resolver(tmp_path, reference)
    _fail_owned_root_close(monkeypatch, resolver)
    try:
        with pytest.raises(InfrastructureError) as caught:
            with resolver:
                pass
        assert type(caught.value.__cause__) is OSError
        assert str(caught.value.__cause__) == "root-close"
        resolver.close()
    finally:
        monkeypatch.undo()
        resolver.close()
        os.close(root_fd)


def test_context_manager_preserves_body_error_and_notes_root_cleanup_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = _png()
    reference = _write(tmp_path, content)
    resolver, root_fd = _resolver(tmp_path, reference)
    primary = ValueError("body-error")
    _fail_owned_root_close(monkeypatch, resolver)
    try:
        with pytest.raises(ValueError) as caught:
            with resolver:
                raise primary
        assert caught.value is primary
        assert caught.value.__notes__ == ["style asset resolver cleanup failed"]
        resolver.close()
    finally:
        monkeypatch.undo()
        resolver.close()
        os.close(root_fd)


def test_call_and_close_share_one_lock_and_leave_no_internal_fds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = _png()
    reference = _write(tmp_path, content)
    resolver, root_fd = _resolver(tmp_path, reference)
    real_open = os.open
    entered = threading.Event()
    release = threading.Event()

    def pausing_open(path: str, flags: int, *args: object, **kwargs: object) -> int:
        fd = real_open(path, flags, *args, **kwargs)  # type: ignore[arg-type]
        if path == reference.sha256.value:
            entered.set()
            assert release.wait(5)
        return fd

    monkeypatch.setattr("specstyle.generation.content_assets.os.open", pausing_open)
    values: list[bytes] = []
    reader = threading.Thread(target=lambda: values.append(resolver(reference)))
    closer = threading.Thread(target=resolver.close)
    reader.start()
    assert entered.wait(5)
    closer.start()
    closer.join(0.1)
    assert closer.is_alive()
    release.set()
    reader.join(5)
    closer.join(5)
    assert values == [content]
    os.fstat(root_fd)
    os.close(root_fd)


def _inject_internal_close_failures(
    monkeypatch: pytest.MonkeyPatch,
    reference: AssetRef,
) -> list[str]:
    real_open = os.open
    real_close = os.close
    labels: dict[int, str] = {}
    attempts: list[str] = []
    names = {
        "sha256": "sha256",
        reference.sha256.value[:2]: "prefix",
        reference.sha256.value: "file",
    }

    def tracked_open(path: str, flags: int, *args: object, **kwargs: object) -> int:
        fd = real_open(path, flags, *args, **kwargs)  # type: ignore[arg-type]
        label = names.get(path)
        if label is not None:
            labels[fd] = label
        return fd

    def failing_close(fd: int) -> None:
        label = labels.get(fd)
        if label is not None:
            attempts.append(label)
        real_close(fd)
        if label is not None:
            raise OSError(f"close-{label}")

    monkeypatch.setattr("specstyle.generation.content_assets.os.open", tracked_open)
    monkeypatch.setattr("specstyle.generation.content_assets.os.close", failing_close)
    return attempts


def test_resolve_reports_first_cleanup_error_after_success_and_attempts_all_fds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = _png()
    reference = _write(tmp_path, content)
    resolver, root_fd = _resolver(tmp_path, reference)
    before = len(os.listdir("/dev/fd"))
    attempts = _inject_internal_close_failures(monkeypatch, reference)
    try:
        with pytest.raises(InfrastructureError) as caught:
            resolver(reference)
        assert type(caught.value.__cause__) is OSError
        assert str(caught.value.__cause__) == "close-file"
        assert attempts == ["file", "prefix", "sha256"]
        assert len(os.listdir("/dev/fd")) == before
    finally:
        monkeypatch.undo()
        resolver.close()
        os.close(root_fd)


def test_resolve_preserves_memory_error_notes_cleanup_and_attempts_all_fds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = _png()
    reference = _write(tmp_path, content)
    resolver, root_fd = _resolver(tmp_path, reference)
    before = len(os.listdir("/dev/fd"))
    primary = MemoryError("primary-memory")
    attempts = _inject_internal_close_failures(monkeypatch, reference)
    monkeypatch.setattr(
        "specstyle.generation.content_assets._read_unchanged_regular_file",
        lambda _fd: (_ for _ in ()).throw(primary),
    )
    try:
        with pytest.raises(MemoryError) as caught:
            resolver(reference)
        assert caught.value is primary
        assert caught.value.__notes__ == ["style asset cleanup failed"]
        assert attempts == ["file", "prefix", "sha256"]
        assert len(os.listdir("/dev/fd")) == before
    finally:
        monkeypatch.undo()
        resolver.close()
        os.close(root_fd)


def test_failure_does_not_leak_file_descriptors(tmp_path: Path) -> None:
    content = _png()
    reference = _write(tmp_path, content)
    _path(tmp_path, reference).chmod(0o622)
    before = len(os.listdir("/dev/fd"))
    resolver, root_fd = _resolver(tmp_path, reference)
    try:
        for _ in range(5):
            with pytest.raises(InfrastructureError):
                resolver(reference)
        assert len(os.listdir("/dev/fd")) == before + 2
    finally:
        resolver.close()
        os.close(root_fd)
    assert len(os.listdir("/dev/fd")) == before
