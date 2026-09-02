"""Install one mutually exclusive ONNX Runtime distribution for BGE-M3."""
import argparse
import json
import os
import platform
import re
import subprocess
import sys
from pathlib import Path


ORT_VERSION = "1.23.2"
ROCM_RELEASE = "7.2.4"
ROCM_REPOSITORY = "https://repo.radeon.com/rocm/manylinux"
ROCM_INDEX = f"{ROCM_REPOSITORY}/rocm-rel-{ROCM_RELEASE}/"
ROCM_RELEASE_RE = re.compile(r"^\d+\.\d+\.\d+$")
ORT_DISTRIBUTIONS = (
    "onnxruntime",
    "onnxruntime-gpu",
    "onnxruntime-directml",
    "onnxruntime_migraphx",
)


def detect_rocm_release(
    environment: dict[str, str] | None = None,
    version_paths: tuple[Path, ...] | None = None,
) -> str:
    environment = os.environ if environment is None else environment
    configured = environment.get("AETHERDB_ROCM_RELEASE", "").strip()
    if configured:
        if not ROCM_RELEASE_RE.fullmatch(configured):
            raise ValueError("AETHERDB_ROCM_RELEASE must use major.minor.patch")
        return configured
    paths = version_paths or (
        Path("/opt/rocm/.info/version"),
        Path("/opt/rocm/.info/version-dev"),
    )
    for path in paths:
        try:
            value = path.read_text(encoding="utf-8").strip().split("-", 1)[0]
        except OSError:
            continue
        if ROCM_RELEASE_RE.fullmatch(value):
            return value
    return ROCM_RELEASE


def build_install_plan(
    backend: str,
    system: str | None = None,
    rocm_release: str | None = None,
) -> list[list[str]]:
    system = system or platform.system()
    uninstall = [sys.executable, "-m", "pip", "uninstall", "-y", *ORT_DISTRIBUTIONS]
    if backend == "cpu":
        install = [sys.executable, "-m", "pip", "install", f"onnxruntime=={ORT_VERSION}"]
    elif backend == "cuda":
        install = [sys.executable, "-m", "pip", "install", f"onnxruntime-gpu=={ORT_VERSION}"]
    elif backend == "rocm":
        if system != "Linux":
            raise ValueError("MIGraphX runtime installation is supported on Linux only")
        release = rocm_release or detect_rocm_release()
        if not ROCM_RELEASE_RE.fullmatch(release):
            raise ValueError("ROCm release must use major.minor.patch")
        index = f"{ROCM_REPOSITORY}/rocm-rel-{release}/"
        install = [
            sys.executable,
            "-m",
            "pip",
            "install",
            f"onnxruntime_migraphx=={ORT_VERSION}",
            "--no-index",
            "--find-links",
            index,
        ]
    else:
        raise ValueError(f"Unsupported backend: {backend}")
    return [uninstall, install]


def main() -> int:
    parser = argparse.ArgumentParser(description="Select the BGE-M3 ONNX Runtime backend")
    parser.add_argument("backend", choices=("cpu", "cuda", "rocm"))
    parser.add_argument("--rocm-release")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        plan = build_install_plan(args.backend, rocm_release=args.rocm_release)
    except ValueError as exc:
        parser.error(str(exc))

    print(json.dumps({"backend": args.backend, "commands": plan}, indent=2))
    if not args.execute:
        return 0
    for command in plan:
        subprocess.run(command, check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
