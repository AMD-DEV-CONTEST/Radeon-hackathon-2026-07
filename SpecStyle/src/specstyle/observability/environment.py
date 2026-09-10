"""Auditable environment snapshots that do not read environment variables."""

from __future__ import annotations

import importlib
import json
import os
import platform
import re
import stat
from dataclasses import dataclass
from typing import Literal, Protocol, TypeAlias, runtime_checkable

from specstyle.domain.identifiers import Sha256
from specstyle.errors import DomainError
from specstyle.observability.hashing import hash_bytes

Availability: TypeAlias = Literal["AVAILABLE", "UNAVAILABLE"]
UnavailableReason: TypeAlias = Literal[
    "NOT_INSTALLED",
    "NOT_REPORTED",
    "NO_HIP_RUNTIME",
    "NO_DEVICE",
    "PROBE_FAILED",
    "INVALID_VALUE",
]
JsonScalar: TypeAlias = None | bool | int | float | str
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
_REASONS = {
    "NOT_INSTALLED",
    "NOT_REPORTED",
    "NO_HIP_RUNTIME",
    "NO_DEVICE",
    "PROBE_FAILED",
    "INVALID_VALUE",
}
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_SENSITIVE_TEXT = re.compile(
    r"(?<![A-Za-z0-9])(?:bearer|password|passwd|secret|token|authorization|"
    r"credential|cookie|session|api[_ -]?key|access[_ -]?key|private[_ -]?key|"
    r"client[_ -]?secret)(?![A-Za-z0-9])",
    re.ASCII | re.IGNORECASE,
)
_URL_TOKEN = re.compile(r"([A-Za-z][A-Za-z0-9+.-]*)://[^\x00-\x20<>\"']*", re.ASCII)
_PATH_TEXT = re.compile(
    r"(?:^|[\x20=:'\"(\[{},;])(?:/(?!/)|~/|[A-Za-z]:[\\/]|\\\\[^\\\x00-\x20]+\\)",
    re.ASCII,
)
_FORWARD_UNC = re.compile(r"(?:^|[\x20='\"(\[{},;])//[^/\x00-\x20]+/", re.ASCII)
_ROCM_RELEASE = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\n?")
_ROCM_VERSION_PATH = "/opt/rocm/.info/version"
_ROCM_VERSION_MAX_BYTES = 128


def _status(status: object, value: object, reason: object, validator: object) -> None:
    if type(status) is not str or status not in {"AVAILABLE", "UNAVAILABLE"}:
        raise DomainError("invalid observation status")
    if status == "AVAILABLE":
        if reason is not None:
            raise DomainError("invalid available observation")
        validator(value)  # type: ignore[operator]
        return
    if value is not None or type(reason) is not str or reason not in _REASONS:
        raise DomainError("invalid unavailable observation")


def _is_safe_observation_text(value: object) -> bool:
    """Reject public text that may contain secrets or paths without raising."""
    try:
        if (
            type(value) is not str
            or not 1 <= len(value) <= 512
            or value != value.strip()
        ):
            return False
        if (
            _CONTROL.search(value)
            or _SENSITIVE_TEXT.search(value)
            or _PATH_TEXT.search(value)
            or _FORWARD_UNC.search(value)
        ):
            return False
        for match in _URL_TOKEN.finditer(value):
            scheme, token = match.group(1).lower(), match.group(0)
            if scheme == "file" or any(character in token for character in "?#@[]"):
                return False
        return True
    except Exception:
        return False


def _safe_text(value: object) -> str:
    if not _is_safe_observation_text(value):
        raise DomainError("invalid environment text")
    return value


def _plain_text(value: object) -> str | None:
    """Normalize package version objects (e.g. torch.TorchVersion) to plain str."""
    if value is None:
        return None
    if type(value) is str:
        return value
    try:
        text = str(value)
    except Exception:
        return None
    return text if type(text) is str else None


def _safe_integer(value: object) -> int:
    if type(value) is not int or value < 0:
        raise DomainError("invalid environment integer")
    return value


@dataclass(frozen=True, slots=True)
class TextObservation:
    status: Availability
    value: str | None
    reason: UnavailableReason | None

    def __post_init__(self) -> None:
        _status(self.status, self.value, self.reason, _safe_text)


@dataclass(frozen=True, slots=True)
class IntegerObservation:
    status: Availability
    value: int | None
    reason: UnavailableReason | None

    def __post_init__(self) -> None:
        _status(self.status, self.value, self.reason, _safe_integer)


@dataclass(frozen=True, slots=True)
class DeviceSnapshot:
    index: int
    name: TextObservation
    total_memory_bytes: IntegerObservation
    gfx_arch: TextObservation

    def __post_init__(self) -> None:
        if type(self.index) is not int or self.index < 0:
            raise DomainError("invalid device index")
        if (
            type(self.name) is not TextObservation
            or type(self.gfx_arch) is not TextObservation
        ):
            raise DomainError("invalid device observation")
        if type(self.total_memory_bytes) is not IntegerObservation:
            raise DomainError("invalid device observation")
        if (
            self.total_memory_bytes.status == "AVAILABLE"
            and self.total_memory_bytes.value == 0
        ):
            raise DomainError("invalid device memory")


@dataclass(frozen=True, slots=True)
class DeviceInventory:
    status: Availability
    reason: UnavailableReason | None
    devices: tuple[DeviceSnapshot, ...]

    def __post_init__(self) -> None:
        if type(self.status) is not str or self.status not in {
            "AVAILABLE",
            "UNAVAILABLE",
        }:
            raise DomainError("invalid inventory status")
        if type(self.devices) is not tuple or any(
            type(item) is not DeviceSnapshot for item in self.devices
        ):
            raise DomainError("invalid inventory devices")
        if self.status == "AVAILABLE":
            if (
                self.reason is not None
                or not self.devices
                or [item.index for item in self.devices]
                != list(range(len(self.devices)))
            ):
                raise DomainError("invalid available inventory")
        elif (
            self.devices or type(self.reason) is not str or self.reason not in _REASONS
        ):
            raise DomainError("invalid unavailable inventory")


@dataclass(frozen=True, slots=True)
class EnvironmentSnapshot:
    schema_version: Literal["1.0"]
    os_name: TextObservation
    os_release: TextObservation
    kernel_version: TextObservation
    machine: TextObservation
    python_implementation: TextObservation
    python_version: TextObservation
    rocm_version: TextObservation
    hip_version: TextObservation
    pytorch_version: TextObservation
    diffusers_version: TextObservation
    hip_devices: DeviceInventory

    def __post_init__(self) -> None:
        if type(self.schema_version) is not str or self.schema_version != "1.0":
            raise DomainError("invalid environment schema")
        fields = (
            self.os_name,
            self.os_release,
            self.kernel_version,
            self.machine,
            self.python_implementation,
            self.python_version,
            self.rocm_version,
            self.hip_version,
            self.pytorch_version,
            self.diffusers_version,
        )
        if (
            any(type(item) is not TextObservation for item in fields)
            or type(self.hip_devices) is not DeviceInventory
        ):
            raise DomainError("invalid environment snapshot")


@runtime_checkable
class EnvironmentProbe(Protocol):
    def os_name(self) -> str | None: ...
    def os_release(self) -> str | None: ...
    def kernel_version(self) -> str | None: ...
    def machine(self) -> str | None: ...
    def python_implementation(self) -> str | None: ...
    def python_version(self) -> str | None: ...
    def rocm_version(self) -> str | None: ...
    def pytorch_version(self) -> str | None: ...
    def diffusers_version(self) -> str | None: ...
    def hip_version(self) -> str | None: ...
    def device_count(self) -> int: ...
    def device_name(self, index: int, /) -> str | None: ...
    def device_total_memory_bytes(self, index: int, /) -> int | None: ...
    def device_gfx_arch(self, index: int, /) -> str | None: ...


class DefaultEnvironmentProbe:
    """Observe only through frozen stdlib and torch APIs without compute or scans."""

    def os_name(self) -> str | None:
        return platform.system()

    def os_release(self) -> str | None:
        return platform.release()

    def kernel_version(self) -> str | None:
        return platform.version()

    def machine(self) -> str | None:
        return platform.machine()

    def python_implementation(self) -> str | None:
        return platform.python_implementation()

    def python_version(self) -> str | None:
        return platform.python_version()

    def rocm_version(self) -> str | None:
        return _read_rocm_release()

    def pytorch_version(self) -> str | None:
        # torch may return TorchVersion (str subclass); snapshot requires plain str.
        return _plain_text(importlib.import_module("torch").__version__)

    def diffusers_version(self) -> str | None:
        return _plain_text(importlib.import_module("diffusers").__version__)

    def hip_version(self) -> str | None:
        return _plain_text(importlib.import_module("torch").version.hip)

    def device_count(self) -> int:
        cuda = importlib.import_module("torch").cuda
        return cuda.device_count() if cuda.is_available() else 0

    def device_name(self, index: int, /) -> str | None:
        return importlib.import_module("torch").cuda.get_device_name(index)

    def device_total_memory_bytes(self, index: int, /) -> int | None:
        return (
            importlib.import_module("torch")
            .cuda.get_device_properties(index)
            .total_memory
        )

    def device_gfx_arch(self, index: int, /) -> str | None:
        return getattr(
            importlib.import_module("torch").cuda.get_device_properties(index),
            "gcnArchName",
            None,
        )


def _read_rocm_release() -> str | None:
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    try:
        file_fd = os.open(_ROCM_VERSION_PATH, flags)
    except (OSError, ValueError):
        return None
    try:
        before = os.fstat(file_fd)
        if (
            not stat.S_ISREG(before.st_mode)
            or not 1 <= before.st_size <= _ROCM_VERSION_MAX_BYTES
        ):
            return None
        payload = os.read(file_fd, before.st_size + 1)
        after = os.fstat(file_fd)
        if (
            len(payload) != before.st_size
            or before.st_dev != after.st_dev
            or before.st_ino != after.st_ino
            or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
            or before.st_ctime_ns != after.st_ctime_ns
        ):
            return None
        decoded = payload.decode("ascii", errors="strict")
        match = _ROCM_RELEASE.fullmatch(decoded)
        return None if match is None else decoded.rstrip("\n")
    except (OSError, UnicodeDecodeError, AttributeError, ValueError):
        return None
    finally:
        try:
            os.close(file_fd)
        except OSError:
            pass


def _text_probe(
    probe: EnvironmentProbe,
    method: str,
    absent: UnavailableReason,
    index: int | None = None,
) -> TextObservation:
    try:
        value = (
            getattr(probe, method)() if index is None else getattr(probe, method)(index)
        )
    except Exception:
        return TextObservation("UNAVAILABLE", None, "PROBE_FAILED")
    if value is None:
        return TextObservation("UNAVAILABLE", None, absent)
    try:
        return TextObservation("AVAILABLE", value, None)
    except DomainError:
        return TextObservation("UNAVAILABLE", None, "INVALID_VALUE")


def _integer_probe(
    probe: EnvironmentProbe, method: str, index: int
) -> IntegerObservation:
    try:
        value = getattr(probe, method)(index)
    except Exception:
        return IntegerObservation("UNAVAILABLE", None, "PROBE_FAILED")
    if value is None:
        return IntegerObservation("UNAVAILABLE", None, "NOT_REPORTED")
    try:
        return IntegerObservation("AVAILABLE", value, None)
    except DomainError:
        return IntegerObservation("UNAVAILABLE", None, "INVALID_VALUE")


def _devices(probe: EnvironmentProbe, hip: TextObservation) -> DeviceInventory:
    if hip.status != "AVAILABLE":
        return DeviceInventory("UNAVAILABLE", hip.reason, ())  # type: ignore[arg-type]
    try:
        count = probe.device_count()
    except Exception:
        return DeviceInventory("UNAVAILABLE", "PROBE_FAILED", ())
    if type(count) is not int or not 0 <= count <= 64:
        return DeviceInventory("UNAVAILABLE", "PROBE_FAILED", ())
    if count == 0:
        return DeviceInventory("UNAVAILABLE", "NO_DEVICE", ())
    devices: list[DeviceSnapshot] = []
    for index in range(count):
        memory = _integer_probe(probe, "device_total_memory_bytes", index)
        if memory.status == "AVAILABLE" and memory.value == 0:
            memory = IntegerObservation("UNAVAILABLE", None, "INVALID_VALUE")
        devices.append(
            DeviceSnapshot(
                index,
                _text_probe(probe, "device_name", "NOT_REPORTED", index),
                memory,
                _text_probe(probe, "device_gfx_arch", "NOT_REPORTED", index),
            )
        )
    return DeviceInventory("AVAILABLE", None, tuple(devices))


def capture_environment(
    probe: EnvironmentProbe | None = None, /
) -> EnvironmentSnapshot:
    """Isolate each field failure in one probe as a fixed unavailable reason."""
    active = DefaultEnvironmentProbe() if probe is None else probe
    platform_fields = tuple(
        _text_probe(active, name, "NOT_REPORTED")
        for name in (
            "os_name",
            "os_release",
            "kernel_version",
            "machine",
            "python_implementation",
            "python_version",
            "rocm_version",
        )
    )
    torch = _text_probe(active, "pytorch_version", "NOT_INSTALLED")
    diffusers = _text_probe(active, "diffusers_version", "NOT_INSTALLED")
    if torch.status != "AVAILABLE":
        hip = TextObservation("UNAVAILABLE", None, "NOT_INSTALLED")
        inventory = DeviceInventory("UNAVAILABLE", "NOT_INSTALLED", ())
    else:
        hip = _text_probe(active, "hip_version", "NO_HIP_RUNTIME")
        inventory = _devices(active, hip)
    return EnvironmentSnapshot(
        "1.0", *platform_fields, hip, torch, diffusers, inventory
    )


def _observation_primitive(
    value: TextObservation | IntegerObservation,
) -> dict[str, JsonValue]:
    return {"status": value.status, "value": value.value, "reason": value.reason}


def environment_to_primitive(snapshot: EnvironmentSnapshot, /) -> dict[str, JsonValue]:
    if type(snapshot) is not EnvironmentSnapshot:
        raise DomainError("invalid environment snapshot")
    devices: list[JsonValue] = []
    for device in snapshot.hip_devices.devices:
        devices.append(
            {
                "index": device.index,
                "name": _observation_primitive(device.name),
                "total_memory_bytes": _observation_primitive(device.total_memory_bytes),
                "gfx_arch": _observation_primitive(device.gfx_arch),
            }
        )
    result: dict[str, JsonValue] = {"schema_version": snapshot.schema_version}
    for name in (
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
    ):
        result[name] = _observation_primitive(getattr(snapshot, name))
    result["hip_devices"] = {
        "status": snapshot.hip_devices.status,
        "reason": snapshot.hip_devices.reason,
        "devices": devices,
    }
    return result


def dump_environment_json(snapshot: EnvironmentSnapshot, /) -> str:
    return json.dumps(
        environment_to_primitive(snapshot),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def hash_environment(snapshot: EnvironmentSnapshot, /) -> Sha256:
    return hash_bytes(dump_environment_json(snapshot).encode("utf-8"))
