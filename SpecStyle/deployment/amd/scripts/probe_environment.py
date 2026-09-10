#!/usr/bin/env python3
"""Emit a deliberately small, non-secret AMD installation evidence record."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.metadata
import importlib.util
import io
import json
import os
import platform
import re
import stat
import sys
from pathlib import Path
from typing import Any, Callable


SCHEMA_KEYS = frozenset(("schema_version", "status", "stage", "reason_code", "repo_sha", "lock_sha", "checks", "versions", "devices"))  # fmt: skip
TORCH_KEYS = ("torch", "torch_hip", "torch_binary_sha256", "torch_file_sha256", "torch_metadata_sha256", "torch_record_sha256")  # fmt: skip
REQUIRED_TORCH_BINARY_PATHS = frozenset((Path("torch/lib/libtorch_cpu.so"), Path("torch/lib/libtorch_hip.so"), Path("torch/lib/libtorch_python.so")))  # fmt: skip
DEPENDENCIES = {
    "Brotli": "1.2.0",
    "Jinja2": "3.1.6",
    "MarkupSafe": "2.1.5",
    "Pygments": "2.15.0",
    "PyYAML": "6.0.3",
    "accelerate": "1.12.0",
    "aiofiles": "23.2.1",
    "annotated-doc": "0.0.4",
    "annotated-types": "0.7.0",
    "anyio": "4.12.1",
    "certifi": "2026.2.25",
    "charset-normalizer": "3.4.5",
    "click": "8.3.0",
    "contourpy": "1.3.3",
    "cycler": "0.12.1",
    "diffusers": "0.39.0",
    "fastapi": "0.135.1",
    "ffmpy": "1.0.0",
    "filelock": "3.20.0",
    "fonttools": "4.62.1",
    "fsspec": "2025.9.0",
    "gradio": "6.15.1",
    "gradio-client": "2.5.0",
    "groovy": "0.1.2",
    "h11": "0.16.0",
    "hf-xet": "1.4.2",
    "hf-gradio": "0.4.1",
    "httpcore": "1.0.9",
    "httpx": "0.28.1",
    "huggingface-hub": "0.36.2",
    "idna": "3.11",
    "importlib-metadata": "9.0.0",
    "importlib-resources": "6.5.2",
    "kiwisolver": "1.5.0",
    "markdown-it-py": "4.0.0",
    "matplotlib": "3.10.8",
    "mdurl": "0.1.2",
    "transformers": "4.57.3",
    "numpy": "1.26.4",
    "opencv-python-headless": "4.11.0.86",
    "orjson": "3.11.9",
    "packaging": "26.0",
    "pandas": "2.2.3",
    "peft": "0.18.1",
    "Pillow": "12.3.0",
    "psutil": "7.1.0",
    "pydantic": "2.11.10",
    "pydantic-core": "2.33.2",
    "pydub": "0.25.1",
    "pyparsing": "3.3.2",
    "python-dateutil": "2.9.0.post0",
    "python-multipart": "0.0.32",
    "pytz": "2026.1.post1",
    "regex": "2026.2.28",
    "requests": "2.32.5",
    "rich": "14.3.3",
    "ruff": "0.16.1",
    "safetensors": "0.8.0",
    "safehttpx": "0.1.7",
    "semantic-version": "2.10.0",
    "shellingham": "1.5.4",
    "six": "1.17.0",
    "starlette": "1.3.1",
    "tokenizers": "0.22.2",
    "tomlkit": "0.12.0",
    "tqdm": "4.67.3",
    "typer": "0.24.1",
    "typing-extensions": "4.15.0",
    "typing-inspection": "0.4.2",
    "tzdata": "2025.3",
    "urllib3": "2.6.3",
    "uvicorn": "0.42.0",
    "websockets": "12.0",
    "zipp": "4.1.0",
}
TORCH_DISTRIBUTION_BY_BUILD = {
    "2.9.1+gitff65f5b": "2.9.1+gitff65f5b",
    "2.9.1": "2.9.1",
    "2.8.0": "2.8.0",
    "2.7.1": "2.7.1",
}
TORCH_VERSIONS = frozenset(TORCH_DISTRIBUTION_BY_BUILD)
HIP_BUILDS = frozenset(("7.2.53211-e1a6bc5663", "7.2.1"))
PRE_CHECKS = frozenset(("linux", "cpython_3_12", "rocm_7_2_1", "torch_version", "hip_7_2", "cuda_available", "device_evidence", "fp16"))  # fmt: skip
MAX_EVIDENCE_BYTES, MAX_GCN_CHARS = 65536, 32
MAX_TORCH_BINARY_COUNT, MAX_TORCH_BINARY_BYTES = 128, 1024 * 1024 * 1024
MAX_TORCH_BINARY_TOTAL_BYTES = 2 * 1024 * 1024 * 1024
SAFE_FLAGS = getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
DIRECTORY_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | SAFE_FLAGS
READ_FLAGS = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | SAFE_FLAGS


def _load_trusted_paths():
    path = Path(__file__).with_name("_probe_trusted_paths.py")
    spec = importlib.util.spec_from_file_location("_amd_probe_trusted_paths", path)
    if spec is None or spec.loader is None:
        raise ImportError("trusted path module unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_TRUSTED_PATHS = _load_trusted_paths()
EvidenceWriteError = _TRUSTED_PATHS.TrustedPathError


class BaselineError(Exception): ...


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)  # fmt: skip


def empty_result(
    phase: str, repo_sha: str | None, lock_sha: str | None
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "status": "PASS",
        "stage": phase,
        "reason_code": "OK",
        "repo_sha": repo_sha,
        "lock_sha": lock_sha,
        "checks": {},
        "versions": {},
        "devices": [],
    }


def failure(
    phase: str, reason: str, exit_code: int, repo_sha: str | None, lock_sha: str | None
) -> tuple[dict[str, Any], int]:
    result = empty_result(phase, repo_sha, lock_sha)
    result.update(status="FAIL", reason_code=reason)
    return result, exit_code


def open_rooted_file(root: Path, target: Path) -> int:
    try:
        parts = target.relative_to(root).parts
    except ValueError:
        raise ValueError("unsafe file") from None
    if not parts or any(part in ("", ".", "..") for part in parts):
        raise ValueError("unsafe file")
    directory = os.open(root, DIRECTORY_FLAGS)
    try:
        for part in parts[:-1]:
            child = os.open(part, DIRECTORY_FLAGS, dir_fd=directory)
            os.close(directory)
            directory = child
        return os.open(parts[-1], READ_FLAGS, dir_fd=directory)
    finally:
        os.close(directory)


def sha256_file(
    path: Path, limit: int = 16 * 1024 * 1024, *, root: Path | None = None
) -> str:
    return hashlib.sha256(trusted_file_bytes(path, limit, root=root)).hexdigest()


def sha256_stream_file(path: Path, limit: int = MAX_TORCH_BINARY_BYTES, *, root: Path | None = None) -> tuple[int, str]:  # fmt: skip
    fd = open_rooted_file(root or path.parent, path)
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode) or opened.st_uid not in (0, os.geteuid()) or opened.st_nlink != 1 or not 0 < opened.st_size <= limit:  # fmt: skip
            raise ValueError("unsafe file")
        digest = hashlib.sha256()
        remaining = opened.st_size
        while remaining:
            chunk = os.read(fd, min(1024 * 1024, remaining))
            if not chunk:
                raise ValueError("unsafe file")
            digest.update(chunk)
            remaining -= len(chunk)
        if os.read(fd, 1) or not same_identity(opened, os.fstat(fd)):
            raise ValueError("changed file")
        return opened.st_size, digest.hexdigest()
    finally:
        os.close(fd)


def trusted_file_bytes(path: Path, limit: int, *, root: Path | None = None) -> bytes:
    fd = open_rooted_file(root or path.parent, path)
    try:
        opened = os.fstat(fd)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_uid not in (0, os.geteuid())
            or opened.st_nlink != 1
            or not 0 < opened.st_size <= limit
        ):
            raise ValueError("unsafe file")
        try:
            data = read_exact(fd, opened.st_size)
        except BaselineError:
            raise ValueError("unsafe file") from None
        if not same_identity(opened, os.fstat(fd)):
            raise ValueError("changed file")
        return data
    finally:
        os.close(fd)


def bounded_regular_text(path: Path, limit: int = 4096) -> str:
    data = trusted_file_bytes(path, limit)
    if data not in (b"7.2.1", b"7.2.1\n"):
        raise ValueError("unsafe file")
    return "7.2.1"


def distribution_file(distribution: Any, name: str) -> Path:
    matches = [
        Path(relative)
        for relative in distribution.files or ()
        if Path(relative).name == name
        and Path(relative).parent.name.endswith(".dist-info")
    ]
    if len(matches) != 1:
        raise ValueError("distribution file missing")
    return Path(distribution.locate_file(matches[0]))


def torch_binary_fingerprint(
    distribution: Any, root: Path, files: tuple[Path, ...]
) -> str:
    manifest: list[dict[str, object]] = []
    binaries = tuple(sorted(path for path in files if path.parent == Path("torch/lib")))
    if not REQUIRED_TORCH_BINARY_PATHS.issubset(binaries) or not 3 <= len(binaries) <= MAX_TORCH_BINARY_COUNT or any(files.count(path) != 1 for path in binaries):  # fmt: skip
        raise ValueError("distribution binary set invalid")
    total = 0
    for relative in binaries:
        target = Path(distribution.locate_file(relative))
        size, digest = sha256_stream_file(target, root=root)
        total += size
        if total > MAX_TORCH_BINARY_TOTAL_BYTES:
            raise ValueError("distribution binaries too large")
        manifest.append({"path": relative.as_posix(), "sha256": digest, "size": size})
    material = canonical_json(manifest).encode("ascii")
    return hashlib.sha256(material).hexdigest()


def torch_fingerprints(torch: Any) -> dict[str, str]:
    distribution = importlib.metadata.distribution("torch")
    try:
        version = str(torch.__version__)
    except Exception:
        raise ValueError("distribution mismatch") from None
    name = distribution.metadata.get("Name")
    if (
        version not in TORCH_DISTRIBUTION_BY_BUILD
        or type(distribution.version) is not str
        or distribution.version != TORCH_DISTRIBUTION_BY_BUILD[version]
        or type(name) is not str
        or name.lower().replace("_", "-") != "torch"
    ):
        raise ValueError("distribution mismatch")
    root = Path(distribution.locate_file(Path()))
    torch_file = Path(torch.__file__)
    try:
        torch_relative = torch_file.relative_to(root)
    except ValueError:
        raise ValueError("distribution mismatch") from None
    files = tuple(Path(relative) for relative in distribution.files or ())
    if files.count(torch_relative) != 1:
        raise ValueError("distribution mismatch")
    metadata = distribution_file(distribution, "METADATA")
    record = distribution_file(distribution, "RECORD")
    if metadata.parent != record.parent:
        raise ValueError("distribution mismatch")
    return {
        "torch": version,
        "torch_hip": str(torch.version.hip or ""),
        "torch_binary_sha256": torch_binary_fingerprint(distribution, root, files),
        "torch_file_sha256": sha256_file(torch_file, root=root),
        "torch_metadata_sha256": sha256_file(metadata, root=root),
        "torch_record_sha256": sha256_file(record, root=root),
    }


def hip_matches(version: object) -> bool:
    return str(version or "") in HIP_BUILDS


def device_evidence(torch: Any) -> list[dict[str, Any]]:
    count = torch.cuda.device_count()
    if type(count) is not int or not 1 <= count <= 16:
        raise ValueError("invalid device count")
    devices: list[dict[str, Any]] = []
    for index in range(count):
        props = torch.cuda.get_device_properties(index)
        name = getattr(props, "name", None)
        memory = getattr(props, "total_memory", None)
        architecture = getattr(props, "gcnArchName", None)
        if (
            type(name) is not str
            or type(memory) is not int
            or not 0 < memory < 2**64
            or re.fullmatch(r"AMD Radeon(?: [A-Za-z0-9][A-Za-z0-9 +.-]{0,63})?", name)
            is None
            or architecture is not None
            and not valid_gcn(architecture)
        ):
            raise ValueError("invalid device properties")
        device = {
            "index": index,
            "name": "AMD Radeon",
            "total_memory": memory,
        }
        if architecture is not None:
            device["gcn_arch"] = architecture
        devices.append(device)
    return devices


def fp16_check(torch: Any) -> bool:
    matrix = torch.ones((2, 2), device="cuda", dtype=torch.float16)
    result = matrix @ matrix
    valid = bool(torch.isfinite(result).all().item())
    torch.cuda.synchronize()
    return valid


def dependencies_match(versions: dict[str, Any]) -> bool:
    found: dict[str, str] = {}
    for name, expected in DEPENDENCIES.items():
        try:
            actual = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            return False
        if actual != expected or not valid_version(actual):
            return False
        found[name] = actual
    versions.update(found)
    return True


class ProbeDeps:
    def __init__(
        self,
        system: Callable[[], str] = platform.system,
        implementation: Callable[[], str] = platform.python_implementation,
        pyver: Callable[[], tuple[int, int]] = lambda: sys.version_info[:2],
        rocm: Callable[[], str] = lambda: bounded_regular_text(
            Path("/opt/rocm/.info/version")
        ),
        torch: Callable[[], Any] = lambda: __import__("torch"),
        fingerprints: Callable[[Any], dict[str, str]] = torch_fingerprints,
        devices: Callable[[Any], list[dict[str, Any]]] = device_evidence,
        fp16: Callable[[Any], bool] = fp16_check,
        dependencies: Callable[[dict[str, Any]], bool] = dependencies_match,
    ) -> None:
        self.system, self.implementation, self.pyver, self.rocm = (
            system,
            implementation,
            pyver,
            rocm,
        )
        self.torch, self.fingerprints, self.devices = torch, fingerprints, devices
        self.fp16, self.dependencies = fp16, dependencies


def _fail_result(
    result: dict[str, Any], reason: str, code: int
) -> tuple[dict[str, Any], int]:
    result.update(status="FAIL", reason_code=reason)
    return result, code


def valid_public_text(value: object, limit: int = 128) -> bool:
    forbidden = ("/", "\\", "file:", "-----begin", "token", "password", "secret")
    return (
        isinstance(value, str)
        and 0 < len(value) <= limit
        and value.isascii()
        and not any(part in value.lower() for part in forbidden)
        and not any(ord(char) < 32 for char in value)
    )


def valid_devices(devices: list[dict[str, Any]]) -> bool:
    if type(devices) is not list or not 1 <= len(devices) <= 16:
        return False
    for position, device in enumerate(devices):
        if (
            type(device) is not dict
            or set(device) - {"index", "name", "total_memory", "gcn_arch"}
            or type(device.get("index")) is not int
            or device["index"] != position
            or type(device.get("total_memory")) is not int
            or not 0 < device["total_memory"] < 2**64
            or type(device.get("name")) is not str
            or device["name"] != "AMD Radeon"
        ):
            return False
        if "gcn_arch" in device and not valid_gcn(device["gcn_arch"]):
            return False
    return True


def valid_gcn(value: object) -> bool:
    return (
        type(value) is str
        and len(value) <= MAX_GCN_CHARS
        and re.fullmatch(r"gfx[0-9a-f]+(?::(?:sramecc|xnack)[+-]){0,2}", value)
        is not None
    )


def valid_version(value: object) -> bool:
    if not valid_public_text(value):
        return False
    return (
        re.fullmatch(
            r"(?:0|[1-9][0-9]*)(?:\.(?:0|[1-9][0-9]*)){1,3}"
            r"(?:\.(?:post|rc|dev)[0-9]+)?",
            value,
        )
        is not None
    )


def valid_fingerprints(value: object, torch_hip: object) -> bool:
    if not isinstance(value, dict) or set(value) != set(TORCH_KEYS):
        return False
    if value.get("torch") not in TORCH_VERSIONS:
        return False
    if not valid_public_text(value.get("torch_hip")) or value["torch_hip"] != str(
        torch_hip or ""
    ):
        return False
    return all(
        isinstance(value[key], str)
        and len(value[key]) == 64
        and all(char in "0123456789abcdef" for char in value[key])
        for key in TORCH_KEYS[2:]
    )


def host_stage(result: dict[str, Any], deps: ProbeDeps) -> tuple[str, int] | None:
    checks = result["checks"]
    checks["linux"] = deps.system() == "Linux"
    if not checks["linux"]:
        return "HOST_UNSUPPORTED", 10
    checks["cpython_3_12"] = deps.implementation() == "CPython" and deps.pyver() == (
        3,
        12,
    )
    if not checks["cpython_3_12"]:
        return "PYTHON_UNSUPPORTED", 10
    result["versions"]["rocm"] = ""
    try:
        rocm = deps.rocm()
    except Exception:
        return "ROCM_VERSION_MISMATCH", 10
    checks["rocm_7_2_1"] = type(rocm) is str and rocm == "7.2.1"
    if not checks["rocm_7_2_1"]:
        return "ROCM_VERSION_MISMATCH", 10
    result["versions"]["rocm"] = rocm
    return None


def torch_stage(
    result: dict[str, Any], deps: ProbeDeps
) -> tuple[Any | None, tuple[str, int] | None]:
    try:
        torch = deps.torch()
        fingerprints = deps.fingerprints(torch)
        torch_hip = torch.version.hip
    except Exception:
        return None, ("TORCH_UNAVAILABLE", 11)
    if not valid_fingerprints(fingerprints, torch_hip):
        return None, ("TORCH_UNAVAILABLE", 11)
    result["versions"].update(fingerprints)
    result["checks"]["torch_version"] = True
    result["checks"]["hip_7_2"] = hip_matches(torch_hip)
    if not result["checks"]["hip_7_2"]:
        return None, ("HIP_VERSION_MISMATCH", 11)
    return torch, None


def gpu_stage(
    result: dict[str, Any], deps: ProbeDeps, torch: Any
) -> tuple[str, int] | None:
    checks = result["checks"]
    try:
        available = torch.cuda.is_available()
        count = torch.cuda.device_count()
    except Exception:
        available, count = False, 0
    checks["cuda_available"] = (
        type(available) is bool
        and available
        and type(count) is int
        and 1 <= count <= 16
    )
    if not checks["cuda_available"]:
        return "GPU_UNAVAILABLE", 12
    try:
        devices = deps.devices(torch)
        checks["device_evidence"] = valid_devices(devices)
        if not checks["device_evidence"]:
            return "FP16_CHECK_FAILED", 12
        result["devices"] = devices
        fp16 = deps.fp16(torch)
        checks["fp16"] = type(fp16) is bool and fp16
    except Exception:
        result["devices"] = []
        return "FP16_CHECK_FAILED", 12
    return None if checks["fp16"] else ("FP16_CHECK_FAILED", 12)


def post_stage(
    result: dict[str, Any], baseline_json: Path | None, deps: ProbeDeps
) -> tuple[str, int] | None:
    if baseline_json is None:
        return "BASELINE_INVALID", 20
    try:
        result["checks"]["torch_unchanged"] = not torch_changed(
            load_baseline(baseline_json), result
        )
    except BaselineError:
        return "BASELINE_INVALID", 20
    if not result["checks"]["torch_unchanged"]:
        return "TORCH_CHANGED", 20
    original_versions = dict(result["versions"])
    expected_keys = {"rocm", *TORCH_KEYS, *DEPENDENCIES}
    try:
        matches = deps.dependencies(result["versions"])
    except Exception:
        matches = False
    valid_dependencies = (
        bool(matches)
        and set(result["versions"]) == expected_keys
        and all(
            result["versions"].get(name) == version
            for name, version in DEPENDENCIES.items()
        )
    )
    if not valid_dependencies:
        result["versions"].clear()
        result["versions"].update(original_versions)
    result["checks"]["dependencies"] = valid_dependencies
    return None if result["checks"]["dependencies"] else ("DEPENDENCY_MISMATCH", 20)


def run_probe(
    *,
    phase: str,
    repo_sha: str | None,
    lock_sha: str | None,
    baseline_json: Path | None = None,
    deps: ProbeDeps | None = None,
) -> tuple[dict[str, Any], int]:
    deps = deps or ProbeDeps()
    result = empty_result(phase, repo_sha, lock_sha)
    outcome = host_stage(result, deps)
    if outcome:
        return _fail_result(result, *outcome)
    torch, outcome = torch_stage(result, deps)
    if outcome:
        return _fail_result(result, *outcome)
    outcome = gpu_stage(result, deps, torch)
    if outcome:
        return _fail_result(result, *outcome)
    if phase == "post":
        outcome = post_stage(result, baseline_json, deps)
        if outcome:
            return _fail_result(result, *outcome)
    return result, 0


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in pairs:
        if key in output:
            raise BaselineError("duplicate")
        output[key] = value
    return output


def same_file(left: os.stat_result, right: os.stat_result) -> bool:
    return left.st_dev == right.st_dev and left.st_ino == right.st_ino


def same_identity(left: os.stat_result, right: os.stat_result) -> bool:
    return same_file(left, right) and (
        left.st_mode,
        left.st_nlink,
        left.st_uid,
        left.st_gid,
        left.st_size,
        left.st_mtime_ns,
        left.st_ctime_ns,
    ) == (
        right.st_mode,
        right.st_nlink,
        right.st_uid,
        right.st_gid,
        right.st_size,
        right.st_mtime_ns,
        right.st_ctime_ns,
    )


def _baseline_invalid() -> None:
    raise BaselineError("BASELINE_INVALID")


def read_exact(fd: int, size: int) -> bytes:
    data = bytearray()
    while len(data) < size:
        try:
            chunk = os.read(fd, min(65536, size - len(data)))
        except OSError:
            _baseline_invalid()
        if not chunk:
            _baseline_invalid()
        data.extend(chunk)
    try:
        if os.read(fd, 1):
            _baseline_invalid()
    except OSError:
        _baseline_invalid()
    return bytes(data)


def trusted_baseline_text(path: Path) -> str:
    try:
        return _TRUSTED_PATHS.read_baseline(str(path), MAX_EVIDENCE_BYTES)
    except _TRUSTED_PATHS.TrustedPathError:
        _baseline_invalid()


def valid_baseline(value: object) -> bool:
    if not isinstance(value, dict) or set(value) != SCHEMA_KEYS:
        return False
    if (
        type(value["schema_version"]) is not int
        or value["schema_version"] != 1
        or value["status"] != "PASS"
        or value["stage"] != "pre"
        or value["reason_code"] != "OK"
    ):
        return False
    if not valid_sha(value["repo_sha"], 40) or not valid_sha(value["lock_sha"], 64):
        return False
    versions, checks, devices = value["versions"], value["checks"], value["devices"]
    if (
        not isinstance(versions, dict)
        or not isinstance(checks, dict)
        or not isinstance(devices, list)
    ):
        return False
    if set(checks) != PRE_CHECKS or any(
        type(flag) is not bool or not flag for flag in checks.values()
    ):
        return False
    if set(versions) != {"rocm", *TORCH_KEYS} or any(
        key not in versions or not isinstance(versions[key], str) for key in TORCH_KEYS
    ):
        return False
    hashes = TORCH_KEYS[2:]
    return (
        versions["rocm"] == "7.2.1"
        and versions["torch"] in TORCH_VERSIONS
        and valid_fingerprints(
            {key: versions[key] for key in TORCH_KEYS}, versions["torch_hip"]
        )
        and all(
            len(versions[key]) == 64
            and all(char in "0123456789abcdef" for char in versions[key])
            for key in hashes
        )
        and valid_devices(devices)
    )


def load_baseline(path: Path) -> dict[str, Any]:
    try:
        text = trusted_baseline_text(path)
        value = json.loads(
            text,
            object_pairs_hook=_no_duplicates,
            parse_constant=lambda _: (_ for _ in ()).throw(BaselineError("constant")),
        )
        if canonical_json(value) + "\n" != text or not valid_baseline(value):
            raise BaselineError("schema")
        return value
    except (
        OSError,
        ValueError,
        TypeError,
        json.JSONDecodeError,
        BaselineError,
    ):
        raise BaselineError("BASELINE_INVALID") from None


def torch_changed(baseline: dict[str, Any], current: dict[str, Any]) -> bool:
    old = baseline.get("versions", {})
    new = current.get("versions", {})
    return any(
        not isinstance(old.get(key), str) or old.get(key) != new.get(key)
        for key in TORCH_KEYS
    )


write_all = _TRUSTED_PATHS.write_all


def write_evidence(path: Path, data: bytes) -> None:
    _TRUSTED_PATHS.write_evidence(str(path), data, MAX_EVIDENCE_BYTES)


def valid_sha(value: str | None, length: int) -> bool:
    return (
        value is None
        or isinstance(value, str)
        and len(value) == length
        and all(character in "0123456789abcdef" for character in value)
    )


def parse_args(arguments: list[str]) -> argparse.Namespace | None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--phase", choices=("pre", "post"), required=True)
    parser.add_argument("--json-out", required=True)
    parser.add_argument("--baseline-json")
    parser.add_argument("--repo-sha")
    parser.add_argument("--lock-sha")
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            values = parser.parse_args(arguments)
    except (SystemExit, argparse.ArgumentError):
        return None
    if values.phase == "post" and not values.baseline_json:
        return None
    if not _TRUSTED_PATHS.is_canonical_absolute(values.json_out) or (
        values.baseline_json is not None
        and not _TRUSTED_PATHS.is_canonical_absolute(values.baseline_json)
    ):
        return None
    if not valid_sha(values.repo_sha, 40) or not valid_sha(values.lock_sha, 64):
        return None
    return values


def main(arguments: list[str] | None = None) -> int:
    values = parse_args(sys.argv[1:] if arguments is None else arguments)
    if values is None:
        return 2
    result, exit_code = run_probe(
        phase=values.phase,
        repo_sha=values.repo_sha,
        lock_sha=values.lock_sha,
        baseline_json=Path(values.baseline_json) if values.baseline_json else None,
    )
    try:
        payload = canonical_json(result).encode("ascii") + b"\n"
    except Exception:
        print("EVIDENCE_WRITE_FAILED", file=sys.stderr)
        return 70
    try:
        write_evidence(Path(values.json_out), payload)
    except EvidenceWriteError:
        print("EVIDENCE_WRITE_FAILED", file=sys.stderr)
        return exit_code or 70
    print(payload.decode("ascii"), end="")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
