"""Tests for the standalone AMD deployment environment probe."""

from __future__ import annotations

import hashlib
import importlib.util
import inspect
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPT = Path(__file__).parents[3] / "deployment/amd/scripts/probe_environment.py"


def load_probe():
    spec = importlib.util.spec_from_file_location("probe_environment", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


probe = load_probe()


def fake_probe_deps(
    probe,
    *,
    hip: str = "7.2.1",
    count: object = 1,
    fp16: object = True,
    dependencies: bool = True,
    devices=None,
):
    cuda = SimpleNamespace(is_available=lambda: True, device_count=lambda: count)
    torch = SimpleNamespace(version=SimpleNamespace(hip=hip), cuda=cuda)
    fingerprints = {"torch": "2.9.1", "torch_hip": hip, "torch_binary_sha256": "d" * 64, "torch_file_sha256": "a" * 64, "torch_metadata_sha256": "b" * 64, "torch_record_sha256": "c" * 64}  # fmt: skip

    def matching_dependencies(versions: dict[str, str]) -> bool:
        if dependencies:
            versions.update(probe.DEPENDENCIES)
        return dependencies

    return probe.ProbeDeps(system=lambda: "Linux", implementation=lambda: "CPython", pyver=lambda: (3, 12), rocm=lambda: "7.2.1", torch=lambda: torch, fingerprints=lambda _: dict(fingerprints), devices=lambda _: devices if devices is not None else [{"index": 0, "name": "AMD Radeon", "total_memory": 16}], fp16=lambda _: fp16, dependencies=matching_dependencies)  # fmt: skip


def pre_result(probe, *, repo_sha=None, lock_sha=None):
    value, code = probe.run_probe(phase="pre", repo_sha=repo_sha, lock_sha=lock_sha, deps=fake_probe_deps(probe))  # fmt: skip
    assert code == 0
    return value


def write_baseline(probe, path: Path, value: dict) -> None:
    path.write_text(probe.canonical_json(value) + "\n")
    path.chmod(0o600)


def changing_fstat(probe, *, call=2, index=1, delta=1):
    original, calls = probe.os.fstat, 0

    def changed(fd: int):
        nonlocal calls
        calls += 1
        info = original(fd)
        if calls != call:
            return info
        values = list(info)
        values[index] += delta
        return os.stat_result(values)

    return changed


def fake_torch_install(tmp_path: Path):
    root = tmp_path / "site-packages"
    files = {
        root / "torch/__init__.py": b"torch",
        root / "torch/lib/libtorch.so": b"torch-binary",
        root / "torch/lib/libtorch_cpu.so": b"cpu-binary",
        root / "torch/lib/libtorch_hip.so": b"hip-binary",
        root / "torch/lib/libtorch_python.so": b"python-binary",
        root / "torch-2.9.1.dist-info/METADATA": b"meta",
        root / "torch-2.9.1.dist-info/RECORD": b"record",
    }
    for path, content in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    torch = SimpleNamespace(__version__="2.9.1", __file__=str(root / "torch/__init__.py"), version=SimpleNamespace(hip=None))  # fmt: skip
    distribution = SimpleNamespace(root=root, version="2.9.1", metadata={"Name": "torch"}, files=[Path(path.relative_to(root)) for path in files], locate_file=lambda relative: root / relative)  # fmt: skip
    return torch, distribution


class _TorchVersionLike:
    def __str__(self) -> str:
        return "2.9.1+gitff65f5b"


INVALID_ARGUMENTS = [["--phase", "post", "--json-out", "out.json"], ["--phase", "pre", "--json-out", "out.json", "--repo-sha", "bad"], ["--phase", "pre", "--json-out", "out.json", "--lock-sha", "bad"], ["--phase", "wrong", "--json-out", "out.json"], ["--phase", "pre", "--json-out", "/private/token", "--unknown", "secret"]]  # fmt: skip


@pytest.mark.parametrize("arguments", INVALID_ARGUMENTS)
def test_invalid_arguments_return_two_silently(arguments, capsys) -> None:
    assert probe.main(arguments) == 2
    assert capsys.readouterr() == ("", "")


def test_main_emits_one_whitelisted_canonical_failure(
    tmp_path, monkeypatch, capsys
) -> None:
    cases = [("pre", "HOST_UNSUPPORTED", 10), ("pre", "TORCH_UNAVAILABLE", 11), ("pre", "GPU_UNAVAILABLE", 12), ("post", "BASELINE_INVALID", 20), ("post", "DEPENDENCY_MISMATCH", 20)]  # fmt: skip
    for phase, reason, code in cases:
        output = tmp_path / f"{reason}.json"
        monkeypatch.setattr(
            probe,
            "run_probe",
            lambda _p=phase, _r=reason, _c=code, **_: probe.failure(
                _p, _r, _c, "a" * 40, "b" * 64
            ),
        )
        args = ["--phase", phase, "--json-out", str(output)]
        if phase == "post":
            args += ["--baseline-json", str(tmp_path / "baseline.json")]
        args += ["--repo-sha", "a" * 40, "--lock-sha", "b" * 64]
        assert probe.main(args) == code
        captured, record = capsys.readouterr(), json.loads(output.read_text())
        assert captured == (output.read_text(), "") and set(record) == probe.SCHEMA_KEYS
        assert (record["checks"], record["versions"], record["devices"]) == ({}, {}, [])


@pytest.mark.parametrize("count", [0, -1, True, "1", 99])
def test_write_all_rejects_non_exact_write_counts(monkeypatch, count) -> None:
    monkeypatch.setattr(probe.os, "write", lambda *_: count)
    with pytest.raises(probe.EvidenceWriteError):
        probe.write_all(1, b"ok")


def test_probe_failure_preserves_code_when_evidence_write_fails(
    tmp_path, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(
        probe,
        "run_probe",
        lambda **_: probe.failure("pre", "GPU_UNAVAILABLE", 12, None, None),
    )
    monkeypatch.setattr(
        probe,
        "write_evidence",
        lambda *_: (_ for _ in ()).throw(probe.EvidenceWriteError()),
    )
    assert probe.main(["--phase", "pre", "--json-out", str(tmp_path / "out")]) == 12
    assert capsys.readouterr() == ("", "EVIDENCE_WRITE_FAILED\n")
    monkeypatch.setattr(
        probe, "run_probe", lambda **_: (probe.empty_result("pre", None, None), 0)
    )
    assert probe.main(["--phase", "pre", "--json-out", str(tmp_path / "pass")]) == 70
    assert capsys.readouterr() == ("", "EVIDENCE_WRITE_FAILED\n")


def test_main_maps_serialization_failure_to_fixed_error(tmp_path, monkeypatch, capsys):
    result = probe.empty_result("pre", None, None)
    result["checks"] = {"unsafe": type("PrivateToken", (), {})()}
    monkeypatch.setattr(probe, "run_probe", lambda **_: (result, 0))
    output = tmp_path / "out.json"
    assert probe.main(["--phase", "pre", "--json-out", str(output)]) == 70
    assert capsys.readouterr() == ("", "EVIDENCE_WRITE_FAILED\n")
    assert not output.exists()


def test_untrusted_fingerprints_never_enter_result() -> None:
    valid = {
        "torch": "2.9.1",
        "torch_hip": "7.2.1",
        "torch_file_sha256": "a" * 64,
        "torch_metadata_sha256": "b" * 64,
        "torch_record_sha256": "c" * 64,
    }
    cases = [
        {key: val for key, val in valid.items() if key != "torch"},
        {**valid, "extra": "value"},
        {**valid, "torch": "/private/token"},
        {**valid, "torch_hip": "\x01"},
        {**valid, "torch_hip": "7" * 129},
        {**valid, "torch_hip": "7.3"},
        {**valid, "torch_file_sha256": "A" * 64},
    ]
    for fingerprints in cases:
        deps = fake_probe_deps(probe)
        deps.fingerprints = lambda _, value=fingerprints: value
        result, code = probe.run_probe(
            phase="pre", repo_sha=None, lock_sha=None, deps=deps
        )
        assert (result["reason_code"], code) == ("TORCH_UNAVAILABLE", 11)
        assert result["versions"] == {"rocm": "7.2.1"}
        assert "/private/token" not in probe.canonical_json(result)
    result, code = probe.run_probe(
        phase="pre",
        repo_sha=None,
        lock_sha=None,
        deps=fake_probe_deps(probe, hip="6.4"),
    )
    assert (result["reason_code"], code) == ("HIP_VERSION_MISMATCH", 11)


def test_dependencies_match_real_metadata_exact_missing_and_mismatch(
    monkeypatch,
) -> None:
    base = {"rocm": "7.2.1", "torch": "2.9.1"}
    monkeypatch.setattr(
        probe.importlib.metadata, "version", lambda name: probe.DEPENDENCIES[name]
    )
    versions = dict(base)
    assert probe.dependencies_match(versions)
    assert set(versions) == {*base, *probe.DEPENDENCIES}
    for bad_name in (
        next(iter(probe.DEPENDENCIES)),
        next(reversed(probe.DEPENDENCIES)),
    ):
        versions = dict(base)
        monkeypatch.setattr(
            probe.importlib.metadata,
            "version",
            lambda name, bad=bad_name: "0" if name == bad else probe.DEPENDENCIES[name],
        )
        assert not probe.dependencies_match(versions) and versions == base
    monkeypatch.setattr(
        probe.importlib.metadata,
        "version",
        lambda _: (_ for _ in ()).throw(
            probe.importlib.metadata.PackageNotFoundError()
        ),
    )
    assert not probe.dependencies_match(dict(base))


def test_torch_fingerprints_accept_verified_rocm_local_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    torch, distribution = fake_torch_install(tmp_path)
    torch.__version__ = _TorchVersionLike()
    torch.version.hip = "7.2.53211-e1a6bc5663"
    distribution.version = "2.9.1+gitff65f5b"
    monkeypatch.setattr(
        probe.importlib.metadata, "distribution", lambda _: distribution
    )

    fingerprints = probe.torch_fingerprints(torch)

    assert fingerprints["torch"] == "2.9.1+gitff65f5b"
    assert fingerprints["torch_hip"] == "7.2.53211-e1a6bc5663"
    assert probe.valid_fingerprints(fingerprints, "7.2.53211-e1a6bc5663")
    assert probe.hip_matches("7.2.53211-e1a6bc5663")


def test_fingerprints_reject_unapproved_torch_build() -> None:
    fingerprints = {
        "torch": "2.9.1+unknown",
        "torch_hip": "7.2.53211-e1a6bc5663",
        "torch_binary_sha256": "d" * 64,
        "torch_file_sha256": "a" * 64,
        "torch_metadata_sha256": "b" * 64,
        "torch_record_sha256": "c" * 64,
    }

    assert not probe.valid_fingerprints(fingerprints, fingerprints["torch_hip"])


def test_hip_match_rejects_unapproved_build() -> None:
    assert not probe.hip_matches("7.2.99999-unknown")


def test_baseline_requires_exactly_one_trailing_lf(tmp_path: Path) -> None:
    value = pre_result(probe)
    path = tmp_path / "baseline.json"
    canonical = probe.canonical_json(value)
    write_baseline(probe, path, value)
    assert probe.load_baseline(path) == value
    changed = json.loads(canonical)
    changed["versions"]["torch_file_sha256"] = "d" * 64
    assert probe.torch_changed(value, changed)
    for invalid in (canonical, canonical + "\n\n", canonical + " \n"):
        path.write_text(invalid)
        with pytest.raises(probe.BaselineError, match="^BASELINE_INVALID$"):
            probe.load_baseline(path)


def test_baseline_rejects_duplicate_nan_extra_missing_and_bad_nested(
    tmp_path: Path,
) -> None:
    path = tmp_path / "baseline.json"
    value = pre_result(probe)
    raw_cases = [
        '{"schema_version":1,"schema_version":1}\n',
        probe.canonical_json(value).replace(
            '"schema_version":1', '"schema_version":NaN'
        )
        + "\n",
        probe.canonical_json({**value, "extra": 1}) + "\n",
        probe.canonical_json(
            {key: val for key, val in value.items() if key != "devices"}
        )
        + "\n",
    ]
    nested = [json.loads(probe.canonical_json(value)) for _ in range(5)]
    nested[0]["checks"]["fp16"] = False
    del nested[1]["checks"]["fp16"]
    nested[2]["checks"]["extra"] = True
    nested[3]["devices"][0]["total_memory"] = True
    nested[4]["schema_version"] = True
    for raw in raw_cases + [probe.canonical_json(item) + "\n" for item in nested]:
        path.write_text(raw)
        path.chmod(0o600)
        with pytest.raises(probe.BaselineError, match="^BASELINE_INVALID$"):
            probe.load_baseline(path)


def test_baseline_rejects_symlink_hardlink_mode_owner_and_oversize(
    tmp_path: Path, monkeypatch
) -> None:
    path = tmp_path / "baseline.json"
    write_baseline(probe, path, pre_result(probe))
    path.chmod(0o644)
    with pytest.raises(probe.BaselineError):
        probe.load_baseline(path)
    path.chmod(0o600)
    link = tmp_path / "link.json"
    link.symlink_to(path)
    with pytest.raises(probe.BaselineError):
        probe.load_baseline(link)
    hardlink = tmp_path / "hardlink.json"
    os.link(path, hardlink)
    with pytest.raises(probe.BaselineError):
        probe.load_baseline(path)
    hardlink.unlink()
    uid = os.geteuid()
    monkeypatch.setattr(probe.os, "geteuid", lambda: uid + 1)
    with pytest.raises(probe.BaselineError):
        probe.load_baseline(path)
    monkeypatch.undo()
    path.write_bytes(b"x" * (probe.MAX_EVIDENCE_BYTES + 1))
    path.chmod(0o600)
    with pytest.raises(probe.BaselineError):
        probe.load_baseline(path)


@pytest.mark.parametrize("failure", ["short", "zero", "oserror", "changed", "close"])
def test_baseline_fd_read_and_identity_faults(
    tmp_path: Path, monkeypatch, failure
) -> None:
    path = tmp_path / "baseline.json"
    write_baseline(probe, path, pre_result(probe))
    original_read, original_close = probe.os.read, probe.os.close
    if failure == "short":
        monkeypatch.setattr(
            probe.os, "read", lambda fd, count: original_read(fd, min(3, count))
        )
        assert probe.load_baseline(path)["status"] == "PASS"
        return
    if failure == "zero":
        monkeypatch.setattr(probe.os, "read", lambda *_: b"")
    elif failure == "oserror":
        monkeypatch.setattr(
            probe.os, "read", lambda *_: (_ for _ in ()).throw(OSError())
        )
    elif failure == "close":
        monkeypatch.setattr(
            probe.os, "close", lambda *_: (_ for _ in ()).throw(OSError())
        )
    else:
        monkeypatch.setattr(probe.os, "fstat", changing_fstat(probe))
    with pytest.raises(probe.BaselineError, match="^BASELINE_INVALID$"):
        probe.load_baseline(path)
    monkeypatch.setattr(probe.os, "close", original_close)


def test_post_dependency_attack_restores_whitelisted_versions(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    write_baseline(probe, baseline, pre_result(probe))
    deps = fake_probe_deps(probe)

    def injected(versions):
        versions.update(probe.DEPENDENCIES)
        versions["injected"] = "/private/token"
        return True

    deps.dependencies = injected
    result, code = probe.run_probe(
        phase="post", repo_sha=None, lock_sha=None, baseline_json=baseline, deps=deps
    )
    assert (result["reason_code"], code) == ("DEPENDENCY_MISMATCH", 20)
    assert set(result["versions"]) == {"rocm", *probe.TORCH_KEYS}
    assert "/private/token" not in probe.canonical_json(result)


def test_real_main_pre_output_round_trips_into_real_main_post(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    deps = fake_probe_deps(probe)
    monkeypatch.setattr(probe, "ProbeDeps", lambda: deps)
    pre, post = tmp_path / "pre.json", tmp_path / "post.json"
    assert probe.main(["--phase", "pre", "--json-out", str(pre)]) == 0
    post_args = [
        "--phase",
        "post",
        "--json-out",
        str(post),
        "--baseline-json",
        str(pre),
    ]
    assert probe.main(post_args) == 0
    captured = capsys.readouterr()
    assert captured.err == "" and captured.out == pre.read_text() + post.read_text()
    assert pre.read_bytes().endswith(b"\n") and not pre.read_bytes().endswith(b"\n\n")
    post_record = json.loads(post.read_text())
    assert post_record["status"] == "PASS"
    assert post_record["checks"]["torch_unchanged"] is True
    assert post_record["checks"]["dependencies"] is True
    assert {key: post_record["versions"][key] for key in probe.DEPENDENCIES} == (
        probe.DEPENDENCIES
    )


def test_rocm_reader_short_reads_exact_eof_and_rejects_tail(tmp_path, monkeypatch):
    path = tmp_path / "version"
    path.write_bytes(b"7.2.1")
    original_read = probe.os.read
    monkeypatch.setattr(
        probe.os, "read", lambda fd, count: original_read(fd, min(count, 2))
    )
    assert probe.bounded_regular_text(path) == "7.2.1"
    path.write_bytes(b"7.2.1\n")
    assert probe.bounded_regular_text(path) == "7.2.1"
    for invalid in (b"7.2.1\r\n", b"7.2.1\n\n", b"7.2.1 ", b"7.2.1x"):
        path.write_bytes(invalid)
        with pytest.raises(ValueError):
            probe.bounded_regular_text(path)
    monkeypatch.setattr(probe.os, "read", original_read)
    path.write_bytes(b"7.2.1/private/token")
    deps = fake_probe_deps(probe)
    deps.rocm = lambda: probe.bounded_regular_text(path)
    result, code = probe.run_probe(phase="pre", repo_sha=None, lock_sha=None, deps=deps)
    assert (result["reason_code"], code, result["versions"]) == (
        "ROCM_VERSION_MISMATCH",
        10,
        {"rocm": ""},
    )
    assert "/private/token" not in probe.canonical_json(result)


@pytest.mark.parametrize("condition", ["empty", "owner", "changed", "symlink", "fifo"])
def test_rocm_reader_rejects_untrusted_file_state_without_blocking(
    tmp_path, monkeypatch, condition
) -> None:
    path = tmp_path / "version"
    path.write_bytes(b"" if condition == "empty" else b"7.2.1")
    if condition == "owner":
        monkeypatch.setattr(probe.os, "fstat", changing_fstat(probe, call=1, index=4))
    elif condition == "changed":
        monkeypatch.setattr(probe.os, "fstat", changing_fstat(probe))
    elif condition == "symlink":
        path.unlink()
        path.symlink_to(tmp_path / "missing")
    elif condition == "fifo":
        path.unlink()
        os.mkfifo(path)
    with pytest.raises((ValueError, OSError)):
        probe.bounded_regular_text(path)


@pytest.mark.parametrize("raw", ["7.2.1evil", "7.2.1/private/token", "secret"])
def test_rocm_mismatch_always_serializes_empty_version(raw: str) -> None:
    deps = fake_probe_deps(probe)
    deps.rocm = lambda: raw
    result, code = probe.run_probe(phase="pre", repo_sha=None, lock_sha=None, deps=deps)
    assert (result["reason_code"], code) == ("ROCM_VERSION_MISMATCH", 10)
    assert result["versions"] == {"rocm": ""} and raw not in probe.canonical_json(
        result
    )


@pytest.mark.parametrize(
    "mutation", ["name", "version", "outside", "duplicate", "split_dist_info"]
)
def test_torch_fingerprints_bind_one_canonical_distribution(
    tmp_path, monkeypatch, mutation
) -> None:
    torch, distribution = fake_torch_install(tmp_path)
    if mutation == "name":
        distribution.metadata = {"Name": "not-torch"}
    elif mutation == "version":
        distribution.version = "2.8.0"
    elif mutation == "outside":
        outside = tmp_path / "outside.py"
        outside.write_bytes(b"torch")
        torch.__file__ = str(outside)
    elif mutation == "duplicate":
        distribution.files.append(Path("other.dist-info/METADATA"))
    else:
        distribution.files[-1] = Path("other.dist-info/RECORD")
    monkeypatch.setattr(
        probe.importlib.metadata, "distribution", lambda _: distribution
    )
    with pytest.raises((ValueError, OSError)):
        probe.torch_fingerprints(torch)


def test_torch_fingerprints_hash_bound_python_metadata_and_binaries(tmp_path, monkeypatch) -> None:  # fmt: skip
    torch, distribution = fake_torch_install(tmp_path)
    monkeypatch.setattr(
        probe.importlib.metadata, "distribution", lambda _: distribution
    )
    fingerprints = probe.torch_fingerprints(torch)
    expected = {"torch": "2.9.1", "torch_hip": "", "torch_binary_sha256": "c712ade6dc7964551b3192498325f364710cb3bae2528a6080d6e5559851fd82", "torch_file_sha256": hashlib.sha256(b"torch").hexdigest(), "torch_metadata_sha256": hashlib.sha256(b"meta").hexdigest(), "torch_record_sha256": hashlib.sha256(b"record").hexdigest()}  # fmt: skip
    assert fingerprints == expected
    (distribution.root / "torch/lib/libtorch.so").write_bytes(b"changed")
    assert probe.torch_fingerprints(torch)["torch_binary_sha256"] != fingerprints["torch_binary_sha256"]  # fmt: skip


@pytest.mark.parametrize("kind", ["symlink", "special", "fifo", "outside", "changed"])
def test_rooted_hash_rejects_untrusted_targets_without_blocking(
    tmp_path, monkeypatch, kind
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    target = root / "file"
    target.write_bytes(b"content")
    if kind == "symlink":
        target.unlink()
        target.symlink_to(tmp_path / "missing")
    elif kind == "special":
        root, target = Path("/dev"), Path("/dev/null")
    elif kind == "fifo":
        target.unlink()
        os.mkfifo(target)
    elif kind == "outside":
        target = tmp_path / "outside"
        target.write_bytes(b"content")
    else:
        monkeypatch.setattr(probe.os, "fstat", changing_fstat(probe))
    with pytest.raises((ValueError, OSError)):
        probe.sha256_file(target, root=root)


@pytest.mark.parametrize("kind", ["symlink", "fifo", "special"])
def test_torch_fingerprint_rejects_unsafe_imported_file(tmp_path, monkeypatch, kind):
    torch, distribution = fake_torch_install(tmp_path)
    torch_path = Path(torch.__file__)
    if kind == "symlink":
        torch_path.unlink()
        torch_path.symlink_to(tmp_path / "missing")
    elif kind == "fifo":
        torch_path.unlink()
        os.mkfifo(torch_path)
    else:
        torch.__file__ = "/dev/null"
        distribution.root = Path("/dev")
        distribution.files[0] = Path("null")
    monkeypatch.setattr(
        probe.importlib.metadata, "distribution", lambda _: distribution
    )
    with pytest.raises((ValueError, OSError)):
        probe.torch_fingerprints(torch)


@pytest.mark.parametrize("boundary", ["open", "write", "fsync", "close"])
def test_evidence_rejects_ancestor_rebind_at_io_boundaries(
    tmp_path, monkeypatch, boundary
):
    parent, moved = tmp_path / "evidence", tmp_path / "moved"
    parent.mkdir(mode=0o700)
    output, rebound = parent / "out.json", False

    def rebind():
        nonlocal rebound
        if not rebound:
            parent.rename(moved)
            parent.mkdir(mode=0o700)
            output.write_bytes(b"keep")
            rebound = True

    original = getattr(probe.os, boundary)

    def attacked(*args, **kwargs):
        if boundary == "open" and str(args[0]) == output.name:
            rebind()
        result = original(*args, **kwargs)
        if boundary != "open":
            rebind()
        return result

    monkeypatch.setattr(probe.os, boundary, attacked)
    with pytest.raises(probe.EvidenceWriteError):
        probe.write_evidence(output, b"evidence")
    assert output.read_bytes() == b"keep"
    assert (moved / output.name).exists()


def test_evidence_binds_create_stat_and_fsync_to_one_parent_fd(tmp_path, monkeypatch):
    output = tmp_path / "out.json"
    original_open, original_stat = probe.os.open, probe.os.stat
    parent_fd = None
    target_dir_fds, stat_dir_fds = [], []

    def recording_open(target, flags, *args, **kwargs):
        nonlocal parent_fd
        fd = original_open(target, flags, *args, **kwargs)
        if str(target) == output.parent.name and flags & getattr(os, "O_DIRECTORY", 0):
            parent_fd = fd
        elif str(target) == output.name:
            target_dir_fds.append(kwargs.get("dir_fd"))
        return fd

    def recording_stat(target, *args, **kwargs):
        if str(target) == output.name:
            stat_dir_fds.append(kwargs.get("dir_fd"))
        return original_stat(target, *args, **kwargs)

    monkeypatch.setattr(probe.os, "open", recording_open)
    monkeypatch.setattr(probe.os, "stat", recording_stat)
    probe.write_evidence(output, b"{}")
    assert target_dir_fds == [parent_fd] and stat_dir_fds == [parent_fd] * 3
    info = output.stat()
    assert (info.st_mode & 0o777, info.st_uid, info.st_nlink, info.st_size) == (
        0o600,
        os.geteuid(),
        1,
        2,
    )


def test_evidence_partial_failure_is_preserved_and_never_unlinked(
    tmp_path, monkeypatch
):
    path = tmp_path / "partial.json"
    original_write = probe.os.write
    calls = 0

    def partial_then_error(fd, data):
        nonlocal calls
        calls += 1
        if calls == 1:
            return original_write(fd, data[:1])
        raise OSError("write failed")

    monkeypatch.setattr(probe.os, "write", partial_then_error)
    monkeypatch.setattr(
        probe.os,
        "unlink",
        lambda *_: (_ for _ in ()).throw(AssertionError("must not unlink")),
    )
    with pytest.raises(probe.EvidenceWriteError):
        probe.write_evidence(path, b"evidence")
    assert path.read_bytes() == b"e"


def test_evidence_rejects_oversize_and_detects_post_close_swap(tmp_path, monkeypatch):
    oversized = tmp_path / "oversized.json"
    with pytest.raises(probe.EvidenceWriteError):
        probe.write_evidence(oversized, b"x" * (probe.MAX_EVIDENCE_BYTES + 1))
    assert not oversized.exists()
    existing, link = tmp_path / "existing", tmp_path / "link"
    existing.write_text("old")
    link.symlink_to(tmp_path / "missing")
    for unsafe in (existing, link):
        with pytest.raises(probe.EvidenceWriteError):
            probe.write_evidence(unsafe, b"{}")
    path, replacement = tmp_path / "swap.json", tmp_path / "replacement.json"
    replacement.write_bytes(b"attacker")
    replacement.chmod(0o600)
    original_close = probe.os.close
    calls = 0

    def swap_after_close(fd):
        nonlocal calls
        calls += 1
        original_close(fd)
        if calls == 1:
            os.replace(replacement, path)

    monkeypatch.setattr(probe.os, "close", swap_after_close)
    with pytest.raises(probe.EvidenceWriteError):
        probe.write_evidence(path, b"{}")
    assert path.read_bytes() == b"attacker"


IntSubclass = type("IntSubclass", (int,), {})


@pytest.mark.parametrize(
    ("available", "count"), [(1, 1), (True, True), (True, IntSubclass(1)), (True, 17)]
)
def test_gpu_rejects_non_exact_cuda_types_and_oversized_count(available, count):
    deps = fake_probe_deps(probe)
    torch = deps.torch()
    torch.cuda = SimpleNamespace(
        is_available=lambda: available, device_count=lambda: count
    )
    result, code = probe.run_probe(phase="pre", repo_sha=None, lock_sha=None, deps=deps)
    assert (result["reason_code"], code, result["devices"]) == (
        "GPU_UNAVAILABLE",
        12,
        [],
    )


@pytest.mark.parametrize("field", ["name", "memory"])
def test_device_evidence_never_invokes_conversion_magic(field: str) -> None:
    called = []

    def fail(_):
        called.append(True)
        raise AssertionError("conversion called")

    trap = type("Trap", (), {"__str__": fail, "__int__": fail})()
    props = SimpleNamespace(
        name=trap if field == "name" else "AMD Radeon RX 7900 XTX",
        total_memory=trap if field == "memory" else 16,
    )
    torch = SimpleNamespace(
        cuda=SimpleNamespace(
            device_count=lambda: 1, get_device_properties=lambda _: props
        )
    )
    with pytest.raises((TypeError, ValueError)):
        probe.device_evidence(torch)
    assert called == []


def test_device_evidence_normalizes_amd_name_and_strict_gcn() -> None:
    props = SimpleNamespace(
        name="AMD Radeon RX 7900 XTX",
        total_memory=16,
        gcnArchName="gfx1100:sramecc+:xnack-",
    )
    torch = SimpleNamespace(
        cuda=SimpleNamespace(
            device_count=lambda: 1, get_device_properties=lambda _: props
        )
    )
    assert probe.device_evidence(torch) == [{"index": 0, "name": "AMD Radeon", "total_memory": 16, "gcn_arch": "gfx1100:sramecc+:xnack-"}]  # fmt: skip
    for memory, gcn in ((2**64, "gfx1100"), (IntSubclass(16), "gfx1100"), (16, "gfx" + "1" * 64)):  # fmt: skip
        props.total_memory, props.gcnArchName = memory, gcn
        with pytest.raises(ValueError):
            probe.device_evidence(torch)
    result, code = probe.run_probe(
        phase="pre", repo_sha=None, lock_sha=None, deps=fake_probe_deps(probe, fp16=1)
    )
    assert (result["reason_code"], code) == ("FP16_CHECK_FAILED", 12)


@pytest.mark.parametrize(("name", "memory", "gcn"), [("/private/token", 16, "gfx1100"), ("NVIDIA GPU", 16, "gfx1100"), ("AMD Radeon secret", 16, "/private/token"), ("AMD Radeon", 16, "gfx1100:bad"), ("AMD Radeon", 2**64, "gfx1100"), ("AMD Radeon", IntSubclass(16), "gfx1100"), ("AMD Radeon", 16, "gfx" + "1" * 64)])  # fmt: skip
def test_gpu_rejects_unsafe_device_values_without_serializing(name, memory, gcn):
    devices = [{"index": 0, "name": name, "total_memory": memory, "gcn_arch": gcn}]
    result, code = probe.run_probe(
        phase="pre",
        repo_sha=None,
        lock_sha=None,
        deps=fake_probe_deps(probe, devices=devices),
    )
    assert (result["reason_code"], code, result["devices"]) == (
        "FP16_CHECK_FAILED",
        12,
        [],
    )
    assert name not in probe.canonical_json(result) and gcn not in probe.canonical_json(
        result
    )


def test_standalone_runs_with_cleared_environment(tmp_path: Path) -> None:
    output = tmp_path / "standalone.json"
    arguments = [sys.executable, "-I", str(SCRIPT), "--phase", "pre", "--json-out", str(output)]  # fmt: skip
    completed = subprocess.run(
        arguments,
        env={"PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        check=False,
    )
    record = json.loads(completed.stdout)
    expected_by_reason = {"OK": 0, "HOST_UNSUPPORTED": 10, "PYTHON_UNSUPPORTED": 10, "ROCM_VERSION_MISMATCH": 10, "TORCH_UNAVAILABLE": 11, "HIP_VERSION_MISMATCH": 11, "GPU_UNAVAILABLE": 12, "FP16_CHECK_FAILED": 12}  # fmt: skip
    assert completed.returncode == expected_by_reason[record["reason_code"]]
    assert record["status"] == ("PASS" if completed.returncode == 0 else "FAIL")
    assert completed.stderr == ""
    assert completed.stdout == output.read_text()
    assert set(record) == probe.SCHEMA_KEYS


def test_public_orchestrators_and_files_stay_within_size_limits() -> None:
    assert len(inspect.getsource(probe.run_probe).splitlines()) < 50
    assert len(inspect.getsource(probe.write_evidence).splitlines()) < 50
    assert len(SCRIPT.read_text().splitlines()) <= 800
    assert len(Path(__file__).read_text().splitlines()) <= 800
