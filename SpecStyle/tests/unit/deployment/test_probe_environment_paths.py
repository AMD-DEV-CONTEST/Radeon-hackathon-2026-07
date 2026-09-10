"""Trusted-path attack tests for the standalone AMD environment probe."""

from __future__ import annotations

import importlib.util
import json
import os
import stat
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[3] / "deployment/amd/scripts/probe_environment.py"


def load_probe():
    spec = importlib.util.spec_from_file_location("probe_environment_paths", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


probe = load_probe()


def baseline_value(hash_char: str = "a") -> dict:
    return {
        "schema_version": 1,
        "status": "PASS",
        "stage": "pre",
        "reason_code": "OK",
        "repo_sha": None,
        "lock_sha": None,
        "checks": {
            "linux": True,
            "cpython_3_12": True,
            "rocm_7_2_1": True,
            "torch_version": True,
            "hip_7_2": True,
            "cuda_available": True,
            "device_evidence": True,
            "fp16": True,
        },
        "versions": {
            "rocm": "7.2.1",
            "torch": "2.9.1",
            "torch_hip": "7.2.1",
            "torch_binary_sha256": "d" * 64,
            "torch_file_sha256": hash_char * 64,
            "torch_metadata_sha256": "b" * 64,
            "torch_record_sha256": "c" * 64,
        },
        "devices": [{"index": 0, "name": "AMD Radeon", "total_memory": 16}],
    }


def write_baseline(path: Path, hash_char: str = "a") -> None:
    payload = json.dumps(
        baseline_value(hash_char),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    path.write_text(payload + "\n")
    path.chmod(0o600)


def success_probe(monkeypatch) -> None:
    monkeypatch.setattr(
        probe,
        "run_probe",
        lambda **_: (probe.empty_result("pre", None, None), 0),
    )


def directory(path: Path, mode: int) -> Path:
    path.mkdir(parents=True)
    path.chmod(mode)
    return path


def rebind_fixture(tmp_path: Path, leaf: bytes):
    outer = directory(tmp_path / "outer", 0o777)
    parent = directory(outer / "safe", 0o700)
    replacement = directory(tmp_path / "replacement", 0o777)
    replacement_parent = directory(replacement / "safe", 0o700)
    sentinel = replacement_parent / "record.json"
    sentinel.write_bytes(leaf)
    sentinel.chmod(0o600)
    moved = tmp_path / "moved"
    rebound = False

    def rebind() -> None:
        nonlocal rebound
        if not rebound:
            outer.rename(moved)
            replacement.rename(outer)
            rebound = True

    return parent / "record.json", sentinel.open("rb"), rebind


def install_close_attack(monkeypatch, path: Path, boundary: str, rebind) -> None:
    original_open, original_close = probe.os.open, probe.os.close
    fds = {"file": None, "parent": None}

    def recording_open(target, flags, *args, **kwargs):
        fd = original_open(target, flags, *args, **kwargs)
        if str(target) == path.name:
            fds["file"] = fd
        if (Path(target) == path.parent or str(target) == path.parent.name) and (
            flags & getattr(os, "O_DIRECTORY", 0)
        ):
            fds["parent"] = fd
        return fd

    def attacked_close(fd):
        original_close(fd)
        if fd == fds[boundary]:
            rebind()

    monkeypatch.setattr(probe.os, "open", recording_open)
    monkeypatch.setattr(probe.os, "close", attacked_close)


NONCANONICAL_PATHS = [
    "record.json",
    "/tmp/./record.json",
    "/tmp/../record.json",
    "/tmp//record.json",
    "/tmp/record.json/",
    "/tmp/record\0.json",
    "/" + "/".join(["part"] * 65) + "/record.json",
]


@pytest.mark.parametrize("raw", NONCANONICAL_PATHS)
def test_parse_args_rejects_noncanonical_output_paths(raw: str) -> None:
    assert probe.parse_args(["--phase", "pre", "--json-out", raw]) is None


def test_parse_args_accepts_canonical_root_leaf() -> None:
    assert probe.parse_args(["--phase", "pre", "--json-out", "/record.json"])


@pytest.mark.parametrize("raw", NONCANONICAL_PATHS)
def test_parse_args_rejects_noncanonical_baseline_paths(tmp_path, raw: str) -> None:
    arguments = [
        "--phase",
        "post",
        "--json-out",
        str(tmp_path / "out.json"),
        "--baseline-json",
        raw,
    ]
    assert probe.parse_args(arguments) is None


def test_main_rejects_relative_path_silently_before_probe(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        probe,
        "run_probe",
        lambda **_: (_ for _ in ()).throw(AssertionError("probe must not run")),
    )
    assert probe.main(["--phase", "pre", "--json-out", "record.json"]) == 2
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("boundary", ["file", "parent"])
def test_evidence_rejects_untrusted_outer_rebind_at_close_boundaries(
    tmp_path, monkeypatch, capsys, boundary
) -> None:
    output, sentinel, rebind = rebind_fixture(tmp_path, b"keep")
    install_close_attack(monkeypatch, output, boundary, rebind)
    success_probe(monkeypatch)
    assert probe.main(["--phase", "pre", "--json-out", str(output)]) == 70
    assert capsys.readouterr() == ("", "EVIDENCE_WRITE_FAILED\n")
    sentinel.seek(0)
    assert sentinel.read() == b"keep"
    sentinel.close()


@pytest.mark.parametrize("boundary", ["file", "parent"])
def test_baseline_rejects_untrusted_outer_rebind_at_close_boundaries(
    tmp_path, monkeypatch, boundary
) -> None:
    baseline, sentinel, rebind = rebind_fixture(tmp_path, b"replacement")
    write_baseline(baseline)
    install_close_attack(monkeypatch, baseline, boundary, rebind)
    with pytest.raises(probe.BaselineError, match="^BASELINE_INVALID$"):
        probe.load_baseline(baseline)
    sentinel.seek(0)
    assert sentinel.read() == b"replacement"
    sentinel.close()


def test_post_stage_maps_untrusted_baseline_to_code_twenty(tmp_path) -> None:
    outer = directory(tmp_path / "outer", 0o777)
    baseline = directory(outer / "safe", 0o700) / "baseline.json"
    write_baseline(baseline)
    result = probe.empty_result("post", None, None)
    assert probe.post_stage(result, baseline, object()) == ("BASELINE_INVALID", 20)


def test_evidence_rejects_world_writable_and_symlink_ancestors(
    tmp_path, monkeypatch, capsys
) -> None:
    success_probe(monkeypatch)
    unsafe = directory(tmp_path / "unsafe", 0o777)
    output = directory(unsafe / "safe", 0o700) / "out.json"
    assert probe.main(["--phase", "pre", "--json-out", str(output)]) == 70
    assert capsys.readouterr() == ("", "EVIDENCE_WRITE_FAILED\n")
    target = directory(tmp_path / "target" / "safe", 0o700)
    link = tmp_path / "link"
    link.symlink_to(target.parent, target_is_directory=True)
    linked_output = link / "safe" / "out.json"
    assert probe.main(["--phase", "pre", "--json-out", str(linked_output)]) == 70
    assert capsys.readouterr() == ("", "EVIDENCE_WRITE_FAILED\n")


@pytest.mark.parametrize(
    "condition", ["world_writable", "owner", "identity", "post_mode"]
)
def test_evidence_rejects_untrusted_parent_before_create(
    tmp_path, monkeypatch, condition
) -> None:
    parent = directory(tmp_path / "evidence", 0o700)
    output = parent / "out.json"
    originals = (probe.os.open, probe.os.fstat, probe.os.stat)
    original_open, original_fstat, original_stat = originals
    parent_fd, parent_fstats = None, 0

    def recording_open(target, flags, *args, **kwargs):
        nonlocal parent_fd
        fd = original_open(target, flags, *args, **kwargs)
        if str(target) == parent.name and flags & getattr(os, "O_DIRECTORY", 0):
            parent_fd = fd
        return fd

    def attacked_fstat(fd):
        nonlocal parent_fstats
        info = original_fstat(fd)
        if fd == parent_fd:
            parent_fstats += 1
            if condition == "post_mode" and parent_fstats == 2:
                values = list(info)
                values[0] |= 0o022
                return os.stat_result(values)
        return info

    def attacked_stat(target, *args, **kwargs):
        info = original_stat(target, *args, **kwargs)
        if condition == "identity" and str(target) == parent.name:
            values = list(info)
            values[1] += 1
            return os.stat_result(values)
        return info

    if condition == "world_writable":
        parent.chmod(0o777)
    elif condition == "owner":
        uid = os.geteuid()
        monkeypatch.setattr(probe.os, "geteuid", lambda: uid + 1)
    else:
        monkeypatch.setattr(probe.os, "open", recording_open)
        monkeypatch.setattr(probe.os, "fstat", attacked_fstat)
        monkeypatch.setattr(probe.os, "stat", attacked_stat)
    with pytest.raises(probe.EvidenceWriteError):
        probe.write_evidence(output, b"{}")
    assert output.exists() is (condition == "post_mode")


def test_evidence_close_failure_is_once_per_fd(tmp_path, monkeypatch) -> None:
    original_open, original_close = probe.os.open, probe.os.close
    opened, closed = [], []

    def recording_open(target, flags, *args, **kwargs):
        fd = original_open(target, flags, *args, **kwargs)
        opened.append(fd)
        return fd

    def first_close_reports_failure(fd):
        closed.append(fd)
        original_close(fd)
        if len(closed) == 1:
            raise OSError("close failed")

    monkeypatch.setattr(probe.os, "open", recording_open)
    monkeypatch.setattr(probe.os, "close", first_close_reports_failure)
    with pytest.raises(probe.EvidenceWriteError):
        probe.write_evidence(tmp_path / "close.json", b"{}")
    assert sorted(opened) == sorted(closed) and len(closed) == len(set(closed))


@pytest.mark.parametrize("failure_call", [1, 2])
def test_evidence_fsync_failure_closes_every_fd_once(
    tmp_path, monkeypatch, failure_call
) -> None:
    original_open, original_close, original_fsync = (
        probe.os.open,
        probe.os.close,
        probe.os.fsync,
    )
    opened, closed, fsync_calls = [], [], 0

    def recording_open(target, flags, *args, **kwargs):
        fd = original_open(target, flags, *args, **kwargs)
        opened.append(fd)
        return fd

    def recording_close(fd):
        closed.append(fd)
        original_close(fd)

    def failing_fsync(fd):
        nonlocal fsync_calls
        fsync_calls += 1
        if fsync_calls == failure_call:
            raise OSError("fsync failed")
        original_fsync(fd)

    monkeypatch.setattr(probe.os, "open", recording_open)
    monkeypatch.setattr(probe.os, "close", recording_close)
    monkeypatch.setattr(probe.os, "fsync", failing_fsync)
    with pytest.raises(probe.EvidenceWriteError):
        probe.write_evidence(tmp_path / "fsync.json", b"{}")
    assert sorted(opened) == sorted(closed) and len(closed) == len(set(closed))


def test_primary_error_keeps_fixed_cleanup_note(tmp_path, monkeypatch) -> None:
    original_close, reported = probe.os.close, False

    def failing_write(*_):
        raise OSError("/private/token")

    def reporting_close(fd):
        nonlocal reported
        original_close(fd)
        if not reported:
            reported = True
            raise OSError("secret close")

    monkeypatch.setattr(probe.os, "write", failing_write)
    monkeypatch.setattr(probe.os, "close", reporting_close)
    with pytest.raises(probe.EvidenceWriteError) as caught:
        probe.write_evidence(tmp_path / "notes.json", b"{}")
    assert str(caught.value) == "write failed"
    assert caught.value.__notes__ == ["cleanup close failed"]


def test_write_all_maps_oserror_to_fixed_error(monkeypatch) -> None:
    monkeypatch.setattr(
        probe.os,
        "write",
        lambda *_: (_ for _ in ()).throw(OSError("/private/token")),
    )
    with pytest.raises(probe.EvidenceWriteError, match="^write failed$"):
        probe.write_all(1, b"{}")


def forged_info(info, *, uid: int, permissions: int):
    values = list(info)
    values[0] = stat.S_IFDIR | permissions
    values[4] = uid
    return os.stat_result(values)


@pytest.mark.parametrize(
    ("owner", "permissions", "expected"),
    [
        (0, 0o1777, 0),
        (0, 0o3777, 70),
        (os.geteuid(), 0o1777, 0 if os.geteuid() == 0 else 70),
        (os.geteuid() + 1, 0o755, 70),
    ],
)
def test_sticky_and_owner_semantics(
    tmp_path, monkeypatch, capsys, owner, permissions, expected
) -> None:
    outer = directory(tmp_path / "outer", 0o700)
    output = directory(outer / "safe", 0o700) / "out.json"
    original_open, original_fstat, original_stat = (
        probe.os.open,
        probe.os.fstat,
        probe.os.stat,
    )
    outer_fd = None

    def recording_open(target, flags, *args, **kwargs):
        nonlocal outer_fd
        fd = original_open(target, flags, *args, **kwargs)
        if str(target) == outer.name:
            outer_fd = fd
        return fd

    def recording_fstat(fd):
        info = original_fstat(fd)
        return (
            forged_info(info, uid=owner, permissions=permissions)
            if fd == outer_fd
            else info
        )

    def recording_stat(target, *args, **kwargs):
        info = original_stat(target, *args, **kwargs)
        return (
            forged_info(info, uid=owner, permissions=permissions)
            if str(target) == outer.name
            else info
        )

    monkeypatch.setattr(probe.os, "open", recording_open)
    monkeypatch.setattr(probe.os, "fstat", recording_fstat)
    monkeypatch.setattr(probe.os, "stat", recording_stat)
    success_probe(monkeypatch)
    assert probe.main(["--phase", "pre", "--json-out", str(output)]) == expected
    captured = capsys.readouterr()
    assert captured.err == ("" if expected == 0 else "EVIDENCE_WRITE_FAILED\n")


def test_baseline_leaf_open_is_parent_relative_nonblocking(
    tmp_path, monkeypatch
) -> None:
    baseline = tmp_path / "baseline.json"
    write_baseline(baseline)
    original_open = probe.os.open
    calls = []

    def recording_open(target, flags, *args, **kwargs):
        calls.append((target, flags, kwargs.get("dir_fd")))
        return original_open(target, flags, *args, **kwargs)

    monkeypatch.setattr(probe.os, "open", recording_open)
    assert probe.load_baseline(baseline)["status"] == "PASS"
    leaf = [call for call in calls if str(call[0]) == baseline.name]
    assert len(leaf) == 1 and leaf[0][2] is not None
    assert leaf[0][1] & getattr(os, "O_NONBLOCK", 0)


def test_evidence_opens_root_and_each_directory_by_name(tmp_path, monkeypatch) -> None:
    output = directory(tmp_path / "one" / "two", 0o700) / "out.json"
    original_open = probe.os.open
    calls = []

    def recording_open(target, flags, *args, **kwargs):
        calls.append((target, flags, kwargs.get("dir_fd")))
        return original_open(target, flags, *args, **kwargs)

    monkeypatch.setattr(probe.os, "open", recording_open)
    probe.write_evidence(output, b"{}")
    assert calls[0][0] == "/" and calls[0][2] is None
    directory_calls = [call for call in calls[:-1] if call[0] != "/"]
    assert directory_calls and all(call[2] is not None for call in directory_calls)
    required = (
        getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    assert all(call[1] & required == required for call in calls[:-1])
