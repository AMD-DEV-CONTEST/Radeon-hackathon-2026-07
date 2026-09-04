#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import socket
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import urlopen

EXPECTED = {
    "python": "3.12.3",
    "rocm": "7.2.1",
    "gpu_architecture": "gfx1100",
    "torch": "2.9.1+gitff65f5b",
    "vllm": "0.16.1.dev0+g89a77b108.d20260317",
    "transformers": "4.57.6",
}
SERVICE_PORTS = (5173, 8000, 8787)


class RuntimeValidationError(RuntimeError):
    pass


def _run(command: list[str]) -> str:
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError) as error:
        raise RuntimeValidationError(f"runtime command failed: {command[0]}") from error
    return result.stdout.strip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest(path: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    for raw_line in path.read_text(encoding="ascii").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        digest, filename = line.split(maxsplit=1)
        entries[filename.strip()] = digest
    if not entries:
        raise RuntimeValidationError("model hash manifest is empty")
    return entries


def _runtime_probe(runtime_python: Path) -> dict[str, Any]:
    probe = """
import json
import platform
import torch
import transformers
import vllm

properties = torch.cuda.get_device_properties(0) if torch.cuda.is_available() else None
print(json.dumps({
    "python": platform.python_version(),
    "torch": torch.__version__,
    "hip": torch.version.hip,
    "transformers": transformers.__version__,
    "vllm": vllm.__version__,
    "cuda_available": torch.cuda.is_available(),
    "gpu_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
    "gpu_vram_bytes": properties.total_memory if properties is not None else 0,
    "gpu_architecture": getattr(properties, "gcnArchName", "") if properties else "",
}, sort_keys=True))
"""
    return json.loads(_run([str(runtime_python), "-c", probe]))


def _rocm_version() -> str:
    candidates = (Path("/opt/rocm/.info/version"), Path("/opt/rocm/.info/version-dev"))
    for path in candidates:
        if path.exists():
            return path.read_text(encoding="ascii").strip().split("-")[0]
    output = _run(["rocminfo"])
    for line in output.splitlines():
        if "ROCm Runtime Version" in line:
            return line.rsplit(":", 1)[-1].strip()
    raise RuntimeValidationError("ROCm version could not be determined")


def _verify_model(model_dir: Path, manifest_path: Path) -> tuple[dict[str, str], str]:
    verified: dict[str, str] = {}
    for filename, expected in _manifest(manifest_path).items():
        path = model_dir / filename
        if not path.is_file():
            raise RuntimeValidationError(f"model file is missing: {filename}")
        actual = _sha256(path)
        if actual != expected:
            raise RuntimeValidationError(f"model hash mismatch: {filename}")
        verified[filename] = actual
    aggregate = hashlib.sha256(
        json.dumps(verified, sort_keys=True, separators=(",", ":")).encode("ascii")
    ).hexdigest()
    return verified, aggregate


def _validate_loopback_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise RuntimeValidationError("service URLs must use uncredentialed localhost HTTP")
    if parsed.username is not None or parsed.password is not None:
        raise RuntimeValidationError("service URLs must not contain credentials")


def _http_ok(url: str) -> bool:
    _validate_loopback_url(url)
    try:
        with urlopen(url, timeout=5) as response:  # noqa: S310 - loopback is validated above
            return 200 <= response.status < 300
    except OSError:
        return False


def _loopback_listener(port: int) -> bool:
    output = _run(["ss", "-ltnH"])
    matches = [line for line in output.splitlines() if line.split()[3].endswith(f":{port}")]
    if len(matches) != 1:
        return False
    address = matches[0].split()[3].rsplit(":", 1)[0].strip("[]")
    try:
        return socket.getaddrinfo(address, port)[0][4][0] in {"127.0.0.1", "::1"}
    except socket.gaierror:
        return address in {"127.0.0.1", "::1", "localhost"}


def _assert_expected(probe: dict[str, Any], rocm_version: str) -> None:
    actual = {
        "python": str(probe["python"]),
        "rocm": rocm_version,
        "gpu_architecture": str(probe["gpu_architecture"]).split(":", 1)[0],
        "torch": str(probe["torch"]),
        "vllm": str(probe["vllm"]),
        "transformers": str(probe["transformers"]),
    }
    failures = [
        f"{key}: expected {value}, got {actual[key]}"
        for key, value in EXPECTED.items()
        if actual[key] != value
    ]
    if not probe["cuda_available"]:
        failures.append("PyTorch reports no Radeon device")
    if failures:
        raise RuntimeValidationError("; ".join(failures))


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the frozen PolicySeal Radeon runtime")
    parser.add_argument("--model-dir", type=Path, default=Path("/workspace/models/Qwen3-8B"))
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path(__file__).with_name("qwen3-8b.sha256"),
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--quick", action="store_true", help="Skip expensive model-file hashing")
    parser.add_argument("--require-model-server", action="store_true")
    parser.add_argument("--require-services", action="store_true")
    args = parser.parse_args()

    if platform.system() != "Linux":
        raise RuntimeValidationError("the frozen Radeon runtime requires Linux")
    runtime_python = Path("/opt/venv/bin/python")
    if not runtime_python.is_file():
        raise RuntimeValidationError("/opt/venv/bin/python is missing")

    probe = _runtime_probe(runtime_python)
    rocm_version = _rocm_version()
    _assert_expected(probe, rocm_version)
    model_files: dict[str, str] = {}
    model_sha256 = "not_checked"
    if not args.quick:
        model_files, model_sha256 = _verify_model(args.model_dir, args.manifest)

    service_urls = {
        "model": "http://127.0.0.1:8000/v1/models",
        "api": "http://127.0.0.1:8787/api/health",
        "web": "http://127.0.0.1:5173/",
    }
    required = ("model", "api", "web") if args.require_services else ()
    if args.require_model_server and "model" not in required:
        required = ("model",)
    services = {name: _http_ok(url) for name, url in service_urls.items()}
    for name in required:
        if not services[name]:
            raise RuntimeValidationError(f"required localhost service is unavailable: {name}")
    listeners = {str(port): _loopback_listener(port) for port in SERVICE_PORTS}
    for name in required:
        port = {"model": 8000, "api": 8787, "web": 5173}[name]
        if not listeners[str(port)]:
            raise RuntimeValidationError(f"service is not uniquely bound to loopback: {name}")

    report = {
        "schema_version": 1,
        "validated_at": datetime.now(UTC).isoformat(),
        "platform": platform.platform(),
        "python": probe["python"],
        "rocm": rocm_version,
        "hip": probe["hip"],
        "gpu_architecture": str(probe["gpu_architecture"]).split(":", 1)[0],
        "gpu_name": probe["gpu_name"],
        "gpu_vram_bytes": probe["gpu_vram_bytes"],
        "torch": probe["torch"],
        "vllm": probe["vllm"],
        "transformers": probe["transformers"],
        "model": "Qwen/Qwen3-8B",
        "model_dir": str(args.model_dir),
        "model_sha256": model_sha256,
        "model_files": model_files,
        "endpoint_scope": "localhost",
        "services": services,
        "loopback_listeners": listeners,
    }
    encoded = json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True)
    print(encoded)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(f"{encoded}\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeValidationError as error:
        print(f"Radeon runtime validation failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
