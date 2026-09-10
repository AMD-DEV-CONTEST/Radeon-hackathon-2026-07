from __future__ import annotations

import os

import pytest

from specstyle.workflow import _job_store_fs as fs


def test_read_file_allows_legacy_private_modes_and_rejects_group_write(
    tmp_path,
) -> None:
    root_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for mode in (0o400, 0o600):
            path = tmp_path / f"safe-{mode:o}"
            path.write_bytes(b"x")
            path.chmod(mode)
            assert fs.read_file(root_fd, path.name, 1, 1, os.fstat(root_fd).st_dev).data
        unsafe = tmp_path / "unsafe"
        unsafe.write_bytes(b"x")
        unsafe.chmod(0o620)
        with pytest.raises(fs.CorruptStore):
            fs.read_file(root_fd, "unsafe", 1, 1, os.fstat(root_fd).st_dev)
    finally:
        os.close(root_fd)


def test_atomic_rename_reports_unsupported_without_path_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(fs, "_atomic_backend", lambda: None)
    with pytest.raises(fs.StoreIO):
        fs.rename_noreplace(3, "old", "new")
