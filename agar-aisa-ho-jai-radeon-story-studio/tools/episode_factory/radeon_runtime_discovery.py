from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence


SCHEMA_VERSION = "aahj.radeon-runtime-observation/v1"
PREFLIGHT_SCHEMA_VERSION = "aahj.radeon-runtime-preflight/v1"

GFX_RE = re.compile(r"\bgfx[0-9a-z]+\b", re.IGNORECASE)
PCI_RE = re.compile(r"\b[0-9a-f]{2,4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-7]\b", re.IGNORECASE)
VERSION_RE = re.compile(r"\b\d+(?:\.\d+){1,3}(?:[-+._a-z0-9]*)?\b", re.IGNORECASE)
VRAM_BYTES_RE = re.compile(
    r"(?:VRAM Total Memory|Total VRAM Memory|vram_total_memory)\s*[:=]\s*(\d+)",
    re.IGNORECASE,
)
ROCM_SMI_VRAM_RE = re.compile(
    r"(?:VRAM Total Memory \(B\)|vram total memory)\s*[:=]\s*(\d+)",
    re.IGNORECASE,
)


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CommandResult:
    argv: tuple[str, ...]
    available: bool
    returncode: int | None
    stdout: str
    stderr: str

    @property
    def succeeded(self) -> bool:
        return self.available and self.returncode == 0


class CommandRunner(Protocol):
    def run(self, argv: Sequence[str]) -> CommandResult:
        ...


class SubprocessCommandRunner:
    def __init__(self, *, timeout_seconds: float = 15.0):
        self.timeout_seconds = timeout_seconds

    def run(self, argv: Sequence[str]) -> CommandResult:
        normalized = tuple(str(part) for part in argv)
        try:
            completed = subprocess.run(
                normalized,
                check=False,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                env={
                    **os.environ,
                    "LC_ALL": "C",
                    "LANG": "C",
                },
            )
        except FileNotFoundError:
            return CommandResult(
                argv=normalized,
                available=False,
                returncode=None,
                stdout="",
                stderr="command not found",
            )
        except subprocess.TimeoutExpired as exc:
            return CommandResult(
                argv=normalized,
                available=True,
                returncode=124,
                stdout=(exc.stdout or "") if isinstance(exc.stdout, str) else "",
                stderr="command timed out",
            )

        return CommandResult(
            argv=normalized,
            available=True,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )


@dataclass(frozen=True)
class RadeonGpuObservation:
    architecture: str
    marketing_name: str | None
    pci_address: str | None
    vram_bytes: int | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "architecture": self.architecture,
            "marketing_name": self.marketing_name,
            "pci_address": self.pci_address,
            "vram_bytes": self.vram_bytes,
        }


@dataclass(frozen=True)
class RadeonRuntimeObservation:
    kernel_release: str
    operating_system: dict[str, str]
    amdgpu_driver_loaded: bool
    amdgpu_driver_version: str | None
    rocm_version: str | None
    hip_version: str | None
    rocminfo_available: bool
    rocm_smi_available: bool
    hipcc_available: bool
    amd_pci_devices: tuple[str, ...]
    gpus: tuple[RadeonGpuObservation, ...]
    command_evidence: dict[str, dict[str, Any]]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "kernel_release": self.kernel_release,
            "operating_system": dict(sorted(self.operating_system.items())),
            "amdgpu_driver_loaded": self.amdgpu_driver_loaded,
            "amdgpu_driver_version": self.amdgpu_driver_version,
            "rocm_version": self.rocm_version,
            "hip_version": self.hip_version,
            "rocminfo_available": self.rocminfo_available,
            "rocm_smi_available": self.rocm_smi_available,
            "hipcc_available": self.hipcc_available,
            "amd_pci_devices": list(self.amd_pci_devices),
            "gpus": [gpu.as_dict() for gpu in self.gpus],
            "command_evidence": {
                key: value
                for key, value in sorted(self.command_evidence.items())
            },
        }

    @property
    def observation_id(self) -> str:
        return sha256_json(self.as_dict())


@dataclass(frozen=True)
class PreflightCheck:
    name: str
    passed: bool
    required: bool
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "required": self.required,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class RadeonRuntimePreflight:
    observation_id: str
    checks: tuple[PreflightCheck, ...]

    @property
    def ready(self) -> bool:
        return all(check.passed for check in self.checks if check.required)

    def as_dict(self) -> dict[str, Any]:
        payload = {
            "schema_version": PREFLIGHT_SCHEMA_VERSION,
            "observation_id": self.observation_id,
            "ready": self.ready,
            "checks": [check.as_dict() for check in self.checks],
        }
        payload["preflight_id"] = sha256_json(payload)
        return payload


class FileReader(Protocol):
    def __call__(self, path: Path) -> str | None:
        ...


def default_file_reader(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except (FileNotFoundError, PermissionError, OSError):
        return None


def parse_os_release(text: str | None) -> dict[str, str]:
    if not text:
        return {}
    result: dict[str, str] = {}
    for line in text.splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, raw = line.split("=", 1)
        value = raw.strip().strip('"').strip("'")
        if key in {"ID", "VERSION_ID", "PRETTY_NAME"}:
            result[key.lower()] = value
    return result


def first_version(text: str) -> str | None:
    match = VERSION_RE.search(text)
    return match.group(0) if match else None


def parse_rocminfo_gpus(text: str) -> list[RadeonGpuObservation]:
    if not text:
        return []

    blocks = re.split(r"\n\s*\n", text)
    observations: list[RadeonGpuObservation] = []

    for block in blocks:
        architectures = GFX_RE.findall(block)
        if not architectures:
            continue

        architecture = architectures[0].lower()
        marketing_name = None
        pci_address = None
        vram_bytes = None

        for line in block.splitlines():
            stripped = line.strip()
            lower = stripped.lower()
            if lower.startswith("marketing name:"):
                marketing_name = stripped.split(":", 1)[1].strip() or None
            elif lower.startswith("name:") and architecture not in lower:
                candidate = stripped.split(":", 1)[1].strip()
                if candidate and candidate.lower() not in {"amdgcn-amd-amdhsa", "agent"}:
                    marketing_name = marketing_name or candidate
            if pci_address is None:
                pci_match = PCI_RE.search(stripped)
                if pci_match:
                    pci_address = pci_match.group(0).lower()
            if vram_bytes is None:
                vram_match = VRAM_BYTES_RE.search(stripped)
                if vram_match:
                    vram_bytes = int(vram_match.group(1))

        observations.append(
            RadeonGpuObservation(
                architecture=architecture,
                marketing_name=marketing_name,
                pci_address=pci_address,
                vram_bytes=vram_bytes,
            )
        )

    deduplicated: dict[tuple[str, str | None], RadeonGpuObservation] = {}
    for gpu in observations:
        key = (gpu.architecture, gpu.pci_address)
        existing = deduplicated.get(key)
        if existing is None:
            deduplicated[key] = gpu
        else:
            deduplicated[key] = RadeonGpuObservation(
                architecture=gpu.architecture,
                marketing_name=existing.marketing_name or gpu.marketing_name,
                pci_address=gpu.pci_address,
                vram_bytes=existing.vram_bytes or gpu.vram_bytes,
            )
    return sorted(
        deduplicated.values(),
        key=lambda gpu: (gpu.pci_address or "", gpu.architecture),
    )


def parse_rocm_smi_vram(text: str) -> int | None:
    match = ROCM_SMI_VRAM_RE.search(text)
    return int(match.group(1)) if match else None


def evidence(result: CommandResult) -> dict[str, Any]:
    stdout = result.stdout.strip()
    stderr = result.stderr.strip()
    return {
        "argv": list(result.argv),
        "available": result.available,
        "returncode": result.returncode,
        "stdout_sha256": hashlib.sha256(
            stdout.encode("utf-8")
        ).hexdigest() if stdout else None,
        "stderr_sha256": hashlib.sha256(
            stderr.encode("utf-8")
        ).hexdigest() if stderr else None,
    }


def discover_radeon_runtime(
    *,
    runner: CommandRunner | None = None,
    read_file: FileReader = default_file_reader,
    kernel_release: str | None = None,
) -> RadeonRuntimeObservation:
    runner = runner or SubprocessCommandRunner()

    lspci = runner.run(("lspci", "-D", "-nn"))
    rocminfo = runner.run(("rocminfo",))
    rocm_smi = runner.run(("rocm-smi", "--showproductname", "--showmeminfo", "vram"))
    hipcc = runner.run(("hipcc", "--version"))
    modinfo = runner.run(("modinfo", "-F", "version", "amdgpu"))
    lsmod = runner.run(("lsmod",))

    amd_pci_devices = tuple(
        sorted(
            line.strip()
            for line in lspci.stdout.splitlines()
            if ("amd" in line.lower() or "advanced micro devices" in line.lower())
            and any(
                marker in line.lower()
                for marker in ("vga", "display", "3d controller")
            )
        )
    )

    gpus = parse_rocminfo_gpus(rocminfo.stdout if rocminfo.succeeded else "")
    smi_vram = parse_rocm_smi_vram(
        rocm_smi.stdout if rocm_smi.succeeded else ""
    )
    if smi_vram is not None and len(gpus) == 1 and gpus[0].vram_bytes is None:
        only = gpus[0]
        gpus = [
            RadeonGpuObservation(
                architecture=only.architecture,
                marketing_name=only.marketing_name,
                pci_address=only.pci_address,
                vram_bytes=smi_vram,
            )
        ]

    rocm_version_text = (
        read_file(Path("/opt/rocm/.info/version"))
        or read_file(Path("/opt/rocm/.info/version-dev"))
        or ""
    )
    rocm_version = first_version(rocm_version_text)
    if rocm_version is None and hipcc.succeeded:
        rocm_version = first_version(hipcc.stdout + "\n" + hipcc.stderr)

    hip_version = None
    if hipcc.succeeded:
        hip_match = re.search(
            r"(?:HIP version|HIP VERSION)\s*[:=]?\s*([0-9][^\s,;]*)",
            hipcc.stdout + "\n" + hipcc.stderr,
            re.IGNORECASE,
        )
        hip_version = (
            hip_match.group(1)
            if hip_match
            else first_version(hipcc.stdout + "\n" + hipcc.stderr)
        )

    driver_loaded = (
        lsmod.succeeded
        and any(
            line.split()[0] == "amdgpu"
            for line in lsmod.stdout.splitlines()
            if line.split()
        )
    ) or Path("/sys/module/amdgpu").is_dir()
    driver_version = (
        modinfo.stdout.strip().splitlines()[0].strip()
        if modinfo.succeeded and modinfo.stdout.strip()
        else None
    )

    return RadeonRuntimeObservation(
        kernel_release=kernel_release or platform.release(),
        operating_system=parse_os_release(read_file(Path("/etc/os-release"))),
        amdgpu_driver_loaded=driver_loaded,
        amdgpu_driver_version=driver_version,
        rocm_version=rocm_version,
        hip_version=hip_version,
        rocminfo_available=rocminfo.succeeded,
        rocm_smi_available=rocm_smi.succeeded,
        hipcc_available=hipcc.succeeded,
        amd_pci_devices=amd_pci_devices,
        gpus=tuple(gpus),
        command_evidence={
            "hipcc": evidence(hipcc),
            "lsmod": evidence(lsmod),
            "lspci": evidence(lspci),
            "modinfo_amdgpu": evidence(modinfo),
            "rocm_smi": evidence(rocm_smi),
            "rocminfo": evidence(rocminfo),
        },
    )


def preflight_radeon_runtime(
    observation: RadeonRuntimeObservation,
) -> RadeonRuntimePreflight:
    unique_arches = sorted({gpu.architecture for gpu in observation.gpus})
    vram_known = bool(observation.gpus) and all(
        gpu.vram_bytes is not None and gpu.vram_bytes > 0
        for gpu in observation.gpus
    )

    checks = (
        PreflightCheck(
            name="amd_gpu_present",
            passed=bool(observation.amd_pci_devices or observation.gpus),
            required=True,
            detail=(
                f"{len(observation.amd_pci_devices)} PCI display device(s), "
                f"{len(observation.gpus)} ROCm GPU agent(s)"
            ),
        ),
        PreflightCheck(
            name="amdgpu_driver_loaded",
            passed=observation.amdgpu_driver_loaded,
            required=True,
            detail=(
                observation.amdgpu_driver_version
                or "amdgpu module was not observed as loaded"
            ),
        ),
        PreflightCheck(
            name="rocminfo_available",
            passed=observation.rocminfo_available,
            required=True,
            detail="rocminfo executed successfully"
            if observation.rocminfo_available
            else "rocminfo unavailable or failed",
        ),
        PreflightCheck(
            name="rocm_version_detected",
            passed=observation.rocm_version is not None,
            required=True,
            detail=observation.rocm_version or "ROCm version not detected",
        ),
        PreflightCheck(
            name="hip_runtime_detected",
            passed=observation.hip_version is not None,
            required=True,
            detail=observation.hip_version or "HIP version not detected",
        ),
        PreflightCheck(
            name="gpu_architecture_unambiguous",
            passed=len(unique_arches) == 1,
            required=True,
            detail=", ".join(unique_arches)
            if unique_arches
            else "no gfx architecture detected",
        ),
        PreflightCheck(
            name="vram_detected",
            passed=vram_known,
            required=False,
            detail="VRAM detected for every GPU"
            if vram_known
            else "VRAM is unknown for one or more GPUs",
        ),
        PreflightCheck(
            name="rocm_smi_available",
            passed=observation.rocm_smi_available,
            required=False,
            detail="rocm-smi executed successfully"
            if observation.rocm_smi_available
            else "rocm-smi unavailable or failed",
        ),
    )
    return RadeonRuntimePreflight(
        observation_id=observation.observation_id,
        checks=checks,
    )


def execution_contract_fragment(
    observation: RadeonRuntimeObservation,
) -> dict[str, Any]:
    preflight = preflight_radeon_runtime(observation)
    if not preflight.ready:
        failed = [
            check.name
            for check in preflight.checks
            if check.required and not check.passed
        ]
        raise ValueError(
            "Radeon runtime is not ready: " + ", ".join(failed)
        )

    unique_arches = sorted({gpu.architecture for gpu in observation.gpus})
    return {
        "rocm_version": observation.rocm_version,
        "gpu_arch": unique_arches[0],
        "driver_version": observation.amdgpu_driver_version or "loaded-version-unknown",
        "environment": {
            "hip_version": observation.hip_version or "unknown",
            "kernel_release": observation.kernel_release,
            "runtime_observation_id": observation.observation_id,
            "runtime_preflight_id": preflight.as_dict()["preflight_id"],
        },
    }
