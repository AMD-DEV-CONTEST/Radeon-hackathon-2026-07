from __future__ import annotations

from dataclasses import FrozenInstanceError
import os
import socket
import subprocess
from pathlib import Path
import stat
from types import SimpleNamespace

import pytest

from specstyle.errors import DomainError
from specstyle.observability.environment import (
    DefaultEnvironmentProbe,
    DeviceInventory,
    DeviceSnapshot,
    EnvironmentSnapshot,
    IntegerObservation,
    TextObservation,
    capture_environment,
    dump_environment_json,
    environment_to_primitive,
    hash_environment,
)
import specstyle.observability.environment as environment_module


class FakeProbe:
    def __init__(
        self, *, torch: str | None = "2.0", hip: str | None = "6.0", count: int = 1
    ) -> None:
        self.torch, self.hip, self.count = torch, hip, count

    def os_name(self) -> str | None:
        return "Linux"

    def os_release(self) -> str | None:
        return "6.1"

    def kernel_version(self) -> str | None:
        return "kernel"

    def machine(self) -> str | None:
        return "x86_64"

    def python_implementation(self) -> str | None:
        return "CPython"

    def python_version(self) -> str | None:
        return "3.11"

    def rocm_version(self) -> str | None:
        return None

    def pytorch_version(self) -> str | None:
        return self.torch

    def diffusers_version(self) -> str | None:
        return None

    def hip_version(self) -> str | None:
        return self.hip

    def device_count(self) -> int:
        return self.count

    def device_name(self, index: int, /) -> str | None:
        return f"GPU-{index}"

    def device_total_memory_bytes(self, index: int, /) -> int | None:
        return 8

    def device_gfx_arch(self, index: int, /) -> str | None:
        return "gfx1100"


def test_capture_environment_golden_multi_device_and_canonical_hash() -> None:
    snapshot = capture_environment(FakeProbe(count=2))
    assert snapshot.pytorch_version.status == "AVAILABLE"
    assert snapshot.rocm_version.reason == "NOT_REPORTED"
    assert [device.index for device in snapshot.hip_devices.devices] == [0, 1]
    primitive = environment_to_primitive(snapshot)
    assert primitive["hip_devices"]["devices"][0]["name"]["value"] == "GPU-0"
    assert (
        hash_environment(snapshot).value
        == "5464fe3eb10fd74ef75ea9c6728df464951aa4b87dd9931a9fac619ab4f64489"
    )
    assert dump_environment_json(snapshot) == (
        '{"diffusers_version":{"reason":"NOT_INSTALLED","status":"UNAVAILABLE","value":null},'
        '"hip_devices":{"devices":[{"gfx_arch":{"reason":null,"status":"AVAILABLE","value":"gfx1100"},'
        '"index":0,"name":{"reason":null,"status":"AVAILABLE","value":"GPU-0"},'
        '"total_memory_bytes":{"reason":null,"status":"AVAILABLE","value":8}},{"gfx_arch":'
        '{"reason":null,"status":"AVAILABLE","value":"gfx1100"},"index":1,"name":'
        '{"reason":null,"status":"AVAILABLE","value":"GPU-1"},"total_memory_bytes":'
        '{"reason":null,"status":"AVAILABLE","value":8}}],"reason":null,"status":"AVAILABLE"},'
        '"hip_version":{"reason":null,"status":"AVAILABLE","value":"6.0"},"kernel_version":'
        '{"reason":null,"status":"AVAILABLE","value":"kernel"},"machine":{"reason":null,'
        '"status":"AVAILABLE","value":"x86_64"},"os_name":{"reason":null,"status":"AVAILABLE",'
        '"value":"Linux"},"os_release":{"reason":null,"status":"AVAILABLE","value":"6.1"},'
        '"python_implementation":{"reason":null,"status":"AVAILABLE","value":"CPython"},'
        '"python_version":{"reason":null,"status":"AVAILABLE","value":"3.11"},'
        '"pytorch_version":{"reason":null,"status":"AVAILABLE","value":"2.0"},'
        '"rocm_version":{"reason":"NOT_REPORTED","status":"UNAVAILABLE","value":null},'
        '"schema_version":"1.0"}'
    )


def test_capture_environment_distinguishes_torch_missing_hip_missing_and_no_device() -> (
    None
):
    missing = capture_environment(FakeProbe(torch=None))
    no_hip = capture_environment(FakeProbe(hip=None))
    no_device = capture_environment(FakeProbe(count=0))
    assert missing.hip_version.reason == "NOT_INSTALLED"
    assert no_hip.hip_version.reason == "NO_HIP_RUNTIME"
    assert no_device.hip_devices.reason == "NO_DEVICE"


def test_capture_environment_isolates_metadata_success_from_runtime_failure() -> None:
    class BrokenRuntime(FakeProbe):
        def hip_version(self) -> str | None:
            raise RuntimeError("boom")

    snapshot = capture_environment(BrokenRuntime())
    assert snapshot.pytorch_version == TextObservation("AVAILABLE", "2.0", None)
    assert snapshot.hip_version.reason == "PROBE_FAILED"
    assert snapshot.hip_devices.reason == "PROBE_FAILED"


@pytest.mark.parametrize(
    "value",
    [" /private", "/private/path", "C:\\private", "https://x/?token=a", "Bearer abc"],
)
def test_text_observation_rejects_sensitive_values_without_retaining_them(
    value: str,
) -> None:
    observation = TextObservation("UNAVAILABLE", None, "INVALID_VALUE")
    assert observation.reason == "INVALID_VALUE"
    with pytest.raises(DomainError):
        TextObservation("AVAILABLE", value, None)


def test_models_are_frozen_slotted_and_cross_field_validated() -> None:
    observation = TextObservation("AVAILABLE", "Linux", None)
    with pytest.raises(FrozenInstanceError):
        observation.value = "other"  # type: ignore[misc]
    with pytest.raises(DomainError):
        IntegerObservation("AVAILABLE", True, None)
    with pytest.raises(DomainError):
        DeviceInventory("AVAILABLE", None, ())
    device = DeviceSnapshot(
        0, observation, IntegerObservation("AVAILABLE", 1, None), observation
    )
    with pytest.raises(DomainError):
        DeviceInventory("AVAILABLE", None, (device, device))


def test_all_environment_values_are_frozen_slotted_and_cross_field_validated() -> None:
    text = TextObservation("AVAILABLE", "Linux", None)
    integer = IntegerObservation("AVAILABLE", 1, None)
    device = DeviceSnapshot(0, text, integer, text)
    inventory = DeviceInventory("AVAILABLE", None, (device,))
    snapshot = EnvironmentSnapshot(
        "1.0", text, text, text, text, text, text, text, text, text, text, inventory
    )
    for value, field in (
        (text, "value"),
        (integer, "value"),
        (device, "index"),
        (inventory, "status"),
        (snapshot, "schema_version"),
    ):
        assert not hasattr(value, "__dict__")
        with pytest.raises(FrozenInstanceError):
            setattr(value, field, None)
    with pytest.raises(DomainError):
        DeviceInventory("UNAVAILABLE", "NO_DEVICE", (device,))


def test_environment_json_requires_exact_snapshot_type() -> None:
    with pytest.raises(DomainError):
        environment_to_primitive(object())  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "unsafe",
    [
        "note /private/path",
        "note ~/private",
        "note C:\\private",
        "note //server/share",
        r"note \\server\share",
        "bearer value",
        "password=value",
        "passwd=value",
        "secret=value",
        "token=value",
        "authorization=value",
        "credential=value",
        "cookie=value",
        "session=value",
        "api_key=value",
        "access-key=value",
        "privatekey=value",
        "client secret=value",
        "ftp://user:pass@example.test/a",
        "http://user:pass@example.test/a",
        "https://host/a?q=x",
        "https://host/a#fragment",
        "http://[",
        "file://safe",
    ],
)
def test_environment_text_materializes_every_unsafe_lexical_form(unsafe: str) -> None:
    class UnsafeProbe(FakeProbe):
        def os_name(self) -> str | None:
            return unsafe

    observed = capture_environment(UnsafeProbe()).os_name
    assert observed.status == "UNAVAILABLE"
    assert observed.reason == "INVALID_VALUE"
    assert observed.value is None


def test_environment_json_golden_keys_and_change_matrix() -> None:
    one = capture_environment(FakeProbe(count=1))
    two = capture_environment(FakeProbe(count=2))
    assert set(environment_to_primitive(one)) == {
        "schema_version",
        "os_name",
        "os_release",
        "kernel_version",
        "machine",
        "python_implementation",
        "python_version",
        "rocm_version",
        "hip_version",
        "pytorch_version",
        "diffusers_version",
        "hip_devices",
    }
    assert dump_environment_json(one).startswith('{"diffusers_version":')
    assert hash_environment(one) != hash_environment(two)


@pytest.mark.parametrize(
    "method",
    [
        "os_name",
        "os_release",
        "kernel_version",
        "machine",
        "python_implementation",
        "python_version",
        "rocm_version",
        "pytorch_version",
        "diffusers_version",
    ],
)
def test_each_scalar_probe_exception_is_isolated(method: str) -> None:
    class BrokenProbe(FakeProbe):
        pass

    def broken() -> None:
        raise RuntimeError("private probe error")

    setattr(BrokenProbe, method, staticmethod(broken))
    snapshot = capture_environment(BrokenProbe())
    field = getattr(snapshot, method)
    assert field.status == "UNAVAILABLE"
    assert field.reason == "PROBE_FAILED"


@pytest.mark.parametrize(
    "method", ["device_name", "device_total_memory_bytes", "device_gfx_arch"]
)
def test_each_device_probe_exception_is_isolated(method: str) -> None:
    class BrokenProbe(FakeProbe):
        pass

    def broken(index: int) -> None:
        raise RuntimeError("private device error")

    setattr(BrokenProbe, method, staticmethod(broken))
    device = capture_environment(BrokenProbe()).hip_devices.devices[0]
    field = getattr(
        device,
        {
            "device_name": "name",
            "device_total_memory_bytes": "total_memory_bytes",
            "device_gfx_arch": "gfx_arch",
        }[method],
    )
    assert field.status == "UNAVAILABLE"
    assert field.reason == "PROBE_FAILED"


def test_invalid_device_count_memory_and_gfx_are_field_specific() -> None:
    class InvalidCount(FakeProbe):
        def device_count(self) -> int:
            return True  # type: ignore[return-value]

    class InvalidDetails(FakeProbe):
        def device_total_memory_bytes(self, index: int, /) -> int | None:
            return 0

        def device_gfx_arch(self, index: int, /) -> str | None:
            return "/private/gfx"

    assert capture_environment(InvalidCount()).hip_devices.reason == "PROBE_FAILED"
    device = capture_environment(InvalidDetails()).hip_devices.devices[0]
    assert device.total_memory_bytes.reason == "INVALID_VALUE"
    assert device.gfx_arch.reason == "INVALID_VALUE"


def test_device_count_exception_and_none_fields_have_fixed_reasons() -> None:
    class CountBroken(FakeProbe):
        def device_count(self) -> int:
            raise RuntimeError("private count")

    class NoneFields(FakeProbe):
        def device_name(self, index: int, /) -> str | None:
            return None

        def device_total_memory_bytes(self, index: int, /) -> int | None:
            return None

        def device_gfx_arch(self, index: int, /) -> str | None:
            return None

    assert capture_environment(CountBroken()).hip_devices.reason == "PROBE_FAILED"
    device = capture_environment(NoneFields()).hip_devices.devices[0]
    assert (
        device.name.reason,
        device.total_memory_bytes.reason,
        device.gfx_arch.reason,
    ) == ("NOT_REPORTED", "NOT_REPORTED", "NOT_REPORTED")


def test_environment_hash_changes_for_scalar_status_and_device_attribute() -> None:
    class ScalarChanged(FakeProbe):
        def os_name(self) -> str | None:
            return "Darwin"

    class DeviceChanged(FakeProbe):
        def device_gfx_arch(self, index: int, /) -> str | None:
            return "gfx1200"

    baseline = capture_environment(FakeProbe())
    assert hash_environment(baseline) != hash_environment(
        capture_environment(ScalarChanged())
    )
    assert hash_environment(baseline) != hash_environment(
        capture_environment(FakeProbe(torch=None))
    )
    assert hash_environment(baseline) != hash_environment(
        capture_environment(DeviceChanged())
    )


def test_capture_default_probe_does_not_need_shell_network_or_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"getenv": 0, "run": 0, "connection": 0}

    def getenv(*args: object, **kwargs: object) -> str:
        calls["getenv"] += 1
        return "benign"

    def run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls["run"] += 1
        return subprocess.CompletedProcess(args=(), returncode=0, stdout="", stderr="")

    def connection(*args: object, **kwargs: object) -> object:
        calls["connection"] += 1
        return object()

    monkeypatch.setattr(os, "getenv", getenv)
    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(socket, "create_connection", connection)
    snapshot = capture_environment()
    assert calls == {"getenv": 0, "run": 0, "connection": 0}
    assert snapshot.schema_version == "1.0"
    assert snapshot.os_name.status in {"AVAILABLE", "UNAVAILABLE"}
    assert snapshot.hip_devices.status in {"AVAILABLE", "UNAVAILABLE"}


def test_default_probe_reads_rocm_only_from_fixed_regular_release_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence = tmp_path / "version"
    evidence.write_bytes(b"7.2.1\n")
    real_open = os.open

    def open_evidence(path: str, flags: int) -> int:
        assert path == "/opt/rocm/.info/version"
        assert flags & os.O_NOFOLLOW
        return real_open(evidence, flags)

    monkeypatch.setattr(environment_module.os, "open", open_evidence)

    assert DefaultEnvironmentProbe().rocm_version() == "7.2.1"


@pytest.mark.parametrize(
    "evidence",
    [b"7.2\n", b"release 7.2.1\n", b"7.2.1\n7.2.2\n", b"7.2.1-123\n"],
)
def test_default_probe_rejects_ambiguous_rocm_release_evidence(
    evidence: bytes, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence_path = tmp_path / "version"
    evidence_path.write_bytes(evidence)
    real_open = os.open
    monkeypatch.setattr(
        environment_module.os,
        "open",
        lambda _path, flags: real_open(evidence_path, flags),
    )
    assert DefaultEnvironmentProbe().rocm_version() is None


def test_default_probe_requires_bounded_regular_rocm_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_open = os.open
    target = tmp_path
    monkeypatch.setattr(
        environment_module.os, "open", lambda _path, flags: real_open(target, flags)
    )
    assert stat.S_ISDIR(target.stat().st_mode)
    assert DefaultEnvironmentProbe().rocm_version() is None

    target = tmp_path / "version"
    target.write_bytes(b"7.2.1" + b" " * 128)
    assert DefaultEnvironmentProbe().rocm_version() is None


def test_default_probe_reports_none_when_rocm_evidence_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing(*_args: object, **_kwargs: object) -> int:
        raise FileNotFoundError

    monkeypatch.setattr(environment_module.os, "open", missing)
    assert DefaultEnvironmentProbe().rocm_version() is None


def test_default_probe_uses_versions_from_imported_packages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    modules = {
        "torch": SimpleNamespace(
            __version__="2.9.0+rocm7.2.1", version=SimpleNamespace(hip="7.2.1")
        ),
        "diffusers": SimpleNamespace(__version__="0.35.1"),
    }
    monkeypatch.setattr(
        environment_module.importlib, "import_module", lambda name: modules[name]
    )
    probe = DefaultEnvironmentProbe()
    assert probe.pytorch_version() == "2.9.0+rocm7.2.1"
    assert probe.diffusers_version() == "0.35.1"
    assert probe.hip_version() == "7.2.1"


class _TorchVersionLike(str):
    """Mimic torch.torch_version.TorchVersion: str subclass with distinct type."""


def test_default_probe_coerces_torchversion_like_objects_to_plain_str(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    modules = {
        "torch": SimpleNamespace(
            __version__=_TorchVersionLike("2.9.1+gitff65f5b"),
            version=SimpleNamespace(hip=_TorchVersionLike("7.2.53211-e1a6bc5663")),
        ),
        "diffusers": SimpleNamespace(__version__="0.39.0"),
    }
    monkeypatch.setattr(
        environment_module.importlib, "import_module", lambda name: modules[name]
    )
    probe = DefaultEnvironmentProbe()
    pytorch = probe.pytorch_version()
    hip = probe.hip_version()
    assert type(pytorch) is str
    assert type(hip) is str
    assert pytorch == "2.9.1+gitff65f5b"
    assert hip == "7.2.53211-e1a6bc5663"
    snapshot = capture_environment(probe)
    assert snapshot.pytorch_version == TextObservation(
        "AVAILABLE", "2.9.1+gitff65f5b", None
    )
    assert snapshot.hip_version == TextObservation(
        "AVAILABLE", "7.2.53211-e1a6bc5663", None
    )


def test_capture_environment_isolates_imported_package_version_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken_import(_name: str) -> object:
        raise ImportError("package unavailable")

    monkeypatch.setattr(environment_module.importlib, "import_module", broken_import)
    snapshot = capture_environment(DefaultEnvironmentProbe())
    assert snapshot.pytorch_version.reason == "PROBE_FAILED"
    assert snapshot.diffusers_version.reason == "PROBE_FAILED"
    assert snapshot.hip_version.reason == "NOT_INSTALLED"
