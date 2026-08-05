import shutil

import pytest

import scripts.pb_eval_unified as U


def test_disk_guard_blocks_eval_when_free_space_is_too_low(monkeypatch):
    usage = shutil._ntuple_diskusage(
        total=100 * 1024**3,
        used=95 * 1024**3,
        free=5 * 1024**3,
    )
    monkeypatch.setattr(U.shutil, "disk_usage", lambda _path: usage)

    with pytest.raises(RuntimeError, match="PB eval disk guard"):
        U.ensure_eval_disk_headroom(path="/", min_free_gb=20)


def test_disk_guard_allows_eval_when_free_space_is_sufficient(monkeypatch):
    usage = shutil._ntuple_diskusage(
        total=100 * 1024**3,
        used=70 * 1024**3,
        free=30 * 1024**3,
    )
    monkeypatch.setattr(U.shutil, "disk_usage", lambda _path: usage)

    result = U.ensure_eval_disk_headroom(path="/", min_free_gb=20)

    assert result["free_gb"] == pytest.approx(30)
    assert result["min_free_gb"] == 20
