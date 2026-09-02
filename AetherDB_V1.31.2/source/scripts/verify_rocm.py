"""Fail-closed ROCm platform and model evidence verification.

The platform probe verifies devices, ROCm tooling, the PyTorch HIP runtime and
a real GPU matrix operation. Model verification remains a separate Worker
probe recorded by the server-owned resource scheduler.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PINNED_ROCM_BASE_IMAGE = (
    "rocm/pytorch:rocm7.2.4_ubuntu22.04_py3.10_pytorch_release_2.9.1"
    "@sha256:9c9592175fece788d6c0b86059012f49b568dc95c98c13879dfdf89c30342559"
)
IMMUTABLE_IMAGE_RE = re.compile(
    r"^[a-z0-9][a-z0-9._/-]*(?::[a-z0-9][a-z0-9._-]*)?@sha256:[0-9a-f]{64}$"
)
PACKAGE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,95}$")
ROCM_BACKENDS = {"rocm_migraphx", "rocm_pytorch"}
MAX_TOOL_OUTPUT_BYTES = 2 * 1024 * 1024


class RocmProbeError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.safe_message = message


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _required_literal(environment: dict[str, str], name: str, expected: str) -> str:
    value = environment.get(name, "").strip().lower()
    if value != expected:
        raise RocmProbeError(
            "COMPETITION_POLICY_INVALID",
            f"{name} must be {expected} in competition mode",
        )
    return value


def validate_competition_environment(environment: dict[str, str]) -> dict[str, Any]:
    _required_literal(environment, "AETHERDB_EXECUTION_MODE", "competition")
    _required_literal(environment, "REQUIRE_ROCM", "true")
    _required_literal(environment, "ALLOW_SILENT_FALLBACK", "false")
    _required_literal(environment, "ALLOW_UNVERIFIED_MODEL", "false")

    image_ref = environment.get("AETHERDB_COMPETITION_IMAGE", "").strip()
    if not IMMUTABLE_IMAGE_RE.fullmatch(image_ref):
        raise RocmProbeError(
            "COMPETITION_IMAGE_NOT_IMMUTABLE",
            "AETHERDB_COMPETITION_IMAGE must use name@sha256 with a full digest",
        )
    base_ref = environment.get("AETHERDB_ROCM_BASE_IMAGE_REF", "").strip()
    if base_ref != PINNED_ROCM_BASE_IMAGE:
        raise RocmProbeError(
            "ROCM_BASE_IMAGE_MISMATCH",
            "The runtime does not declare the pinned AetherDB ROCm base image",
        )
    return {
        "execution_mode": "competition",
        "require_rocm": True,
        "allow_silent_fallback": False,
        "allow_unverified_model": False,
        "competition_image": image_ref,
        "competition_image_digest": image_ref.rsplit("@", 1)[1],
        "rocm_base_image": base_ref,
    }


def _run_fixed_command(command: list[str], timeout: int = 20) -> dict[str, Any]:
    result = subprocess.run(
        command,
        capture_output=True,
        check=False,
        text=False,
        timeout=timeout,
        shell=False,
        env={**os.environ, "LC_ALL": "C", "LANG": "C"},
    )
    output = (result.stdout or b"") + b"\n" + (result.stderr or b"")
    if len(output) > MAX_TOOL_OUTPUT_BYTES:
        raise RocmProbeError(
            "ROCM_TOOL_OUTPUT_TOO_LARGE",
            f"{Path(command[0]).name} returned excessive diagnostic output",
        )
    if result.returncode != 0:
        raise RocmProbeError(
            "ROCM_TOOL_FAILED",
            f"{Path(command[0]).name} failed with exit code {result.returncode}",
        )
    if not output.strip():
        raise RocmProbeError(
            "ROCM_TOOL_EMPTY",
            f"{Path(command[0]).name} returned no device information",
        )
    return {
        "command": Path(command[0]).name,
        "exit_code": result.returncode,
        "output_sha256": _sha256_bytes(output),
        "output_size_bytes": len(output),
    }


def probe_device_layer() -> tuple[dict[str, Any], tuple[str, ...]]:
    if platform.system() != "Linux":
        raise RocmProbeError("ROCM_LINUX_REQUIRED", "ROCm competition mode requires Linux")
    if not Path("/dev/kfd").exists():
        raise RocmProbeError("ROCM_KFD_MISSING", "/dev/kfd is not available")
    render_nodes = tuple(sorted(Path("/dev/dri").glob("renderD*")))
    if not render_nodes:
        raise RocmProbeError("ROCM_RENDER_NODE_MISSING", "No /dev/dri/renderD* node is available")

    rocminfo = shutil.which("rocminfo")
    amd_smi = shutil.which("amd-smi")
    if not rocminfo:
        raise RocmProbeError("ROCMINFO_MISSING", "rocminfo is not installed")
    if not amd_smi:
        raise RocmProbeError("AMD_SMI_MISSING", "amd-smi is not installed")

    tool_results = [
        _run_fixed_command([rocminfo]),
        _run_fixed_command([amd_smi, "version"]),
        _run_fixed_command([amd_smi, "list", "--json"]),
    ]

    from services.model_runtime.hardware import collect_resource_snapshot

    snapshot = collect_resource_snapshot()
    amd_devices = tuple(
        item for item in snapshot.devices if item.vendor == "AMD"
    )
    if not amd_devices:
        raise RocmProbeError(
            "ROCM_RESOURCE_SNAPSHOT_EMPTY",
            "AetherDB resource discovery found no AMD compute device",
        )
    return (
        {
            "verified": True,
            "kfd_present": True,
            "render_node_count": len(render_nodes),
            "tool_results": tool_results,
            "device_count": len(amd_devices),
            "devices": [
                {
                    "visible_index": item.visible_index,
                    "name": item.name,
                    "total_vram_mb": item.total_vram_mb,
                    "driver_version": item.driver_version,
                    "device_fingerprint": item.fingerprint,
                    "source": item.source,
                }
                for item in amd_devices
            ],
        },
        tuple(item.fingerprint for item in amd_devices),
    )


def probe_framework_layer() -> tuple[dict[str, Any], Any]:
    try:
        import torch
    except ImportError as exc:
        raise RocmProbeError("PYTORCH_MISSING", "PyTorch is not installed") from exc

    hip_version = getattr(torch.version, "hip", None)
    if not hip_version:
        raise RocmProbeError(
            "PYTORCH_NOT_ROCM",
            "PyTorch does not report a HIP runtime",
        )
    if not torch.cuda.is_available():
        raise RocmProbeError(
            "PYTORCH_ROCM_UNAVAILABLE",
            "PyTorch cannot access a ROCm GPU",
        )
    device_count = int(torch.cuda.device_count())
    if device_count < 1:
        raise RocmProbeError("PYTORCH_DEVICE_EMPTY", "PyTorch reported zero ROCm devices")
    index_raw = os.environ.get("AETHERDB_ROCM_PROBE_DEVICE_INDEX", "0").strip()
    try:
        device_index = int(index_raw)
    except ValueError as exc:
        raise RocmProbeError(
            "ROCM_PROBE_DEVICE_INVALID",
            "AETHERDB_ROCM_PROBE_DEVICE_INDEX must be an integer",
        ) from exc
    if not 0 <= device_index < device_count:
        raise RocmProbeError(
            "ROCM_PROBE_DEVICE_INVALID",
            "The requested ROCm probe device index is unavailable",
        )
    properties = torch.cuda.get_device_properties(device_index)
    return (
        {
            "verified": True,
            "torch_version": str(torch.__version__),
            "hip_version": str(hip_version),
            "cuda_api_available": True,
            "device_count": device_count,
            "probe_device_index": device_index,
            "device_name": str(torch.cuda.get_device_name(device_index)),
            "total_memory_bytes": int(properties.total_memory),
        },
        torch,
    )


def probe_compute_layer(torch_module: Any, device_index: int) -> dict[str, Any]:
    device = torch_module.device(f"cuda:{device_index}")
    size = 256
    torch_module.manual_seed(731)
    left_cpu = torch_module.randn((size, size), dtype=torch_module.float32)
    right_cpu = torch_module.randn((size, size), dtype=torch_module.float32)
    expected = left_cpu @ right_cpu
    left = left_cpu.to(device)
    right = right_cpu.to(device)

    torch_module.cuda.synchronize(device)
    torch_module.cuda.reset_peak_memory_stats(device)
    started = time.perf_counter()
    actual_gpu = left @ right
    torch_module.cuda.synchronize(device)
    elapsed_ms = (time.perf_counter() - started) * 1000
    actual = actual_gpu.cpu()
    max_abs_error = float((actual - expected).abs().max().item())
    if not math.isfinite(max_abs_error) or max_abs_error > 0.02:
        raise RocmProbeError(
            "ROCM_COMPUTE_MISMATCH",
            "The ROCm matrix result failed numerical verification",
        )
    output = actual.contiguous().numpy().tobytes()
    return {
        "verified": True,
        "operation": "float32_matmul",
        "matrix_size": size,
        "elapsed_ms": round(elapsed_ms, 3),
        "max_abs_error": max_abs_error,
        "output_digest": _sha256_bytes(output),
        "max_memory_allocated_bytes": int(
            torch_module.cuda.max_memory_allocated(device)
        ),
        "max_memory_reserved_bytes": int(
            torch_module.cuda.max_memory_reserved(device)
        ),
    }


def _verified_model_rows(
    package_ids: Iterable[str],
    runtime_root: Path,
    device_fingerprints: tuple[str, ...],
) -> list[dict[str, Any]]:
    requested = tuple(dict.fromkeys(package_ids))
    if not requested:
        return []
    if any(not PACKAGE_ID_RE.fullmatch(item) for item in requested):
        raise RocmProbeError("MODEL_PACKAGE_ID_INVALID", "Invalid model package identifier")
    registry = runtime_root / "app_data" / "registry.db"
    if not registry.is_file():
        raise RocmProbeError(
            "MODEL_EVIDENCE_REGISTRY_MISSING",
            "The runtime registry is unavailable for model evidence verification",
        )
    if not device_fingerprints:
        raise RocmProbeError(
            "MODEL_EVIDENCE_DEVICE_MISSING",
            "No current AMD device fingerprint is available",
        )

    from services.model_packages.registry import get_manifest

    rows: list[dict[str, Any]] = []
    conn = sqlite3.connect(f"file:{registry.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        for package_id in requested:
            manifest = get_manifest(package_id, sync=False)
            placeholders = ",".join("?" for _ in device_fingerprints)
            row = conn.execute(
                "SELECT id,package_id,backend,device_fingerprint,probe_ref,verified_at "
                "FROM model_runtime_evidence "
                "WHERE package_id=? AND package_version=? AND manifest_digest=? "
                f"AND device_fingerprint IN ({placeholders}) "
                "AND backend IN ('rocm_migraphx','rocm_pytorch') "
                "AND verification_status='VERIFIED_ROCM' "
                "AND probe_ref LIKE 'worker:%' "
                "AND (expires_at IS NULL OR expires_at>?) "
                "ORDER BY verified_at DESC LIMIT 1",
                (
                    package_id,
                    manifest.package_version,
                    manifest.digest(),
                    *device_fingerprints,
                    _utc_now(),
                ),
            ).fetchone()
            if row is None:
                raise RocmProbeError(
                    "MODEL_RUNTIME_UNVERIFIED",
                    f"{package_id} has no current Worker-verified ROCm evidence",
                )
            rows.append(
                {
                    "evidence_id": row["id"],
                    "package_id": row["package_id"],
                    "backend": row["backend"],
                    "device_fingerprint": row["device_fingerprint"],
                    "probe_ref": row["probe_ref"],
                    "verified_at": row["verified_at"],
                }
            )
    except sqlite3.DatabaseError as exc:
        raise RocmProbeError(
            "MODEL_EVIDENCE_REGISTRY_INVALID",
            "The runtime registry cannot provide model evidence",
        ) from exc
    finally:
        conn.close()
    return rows


def build_probe_report(
    *,
    policy: dict[str, Any],
    device: dict[str, Any],
    framework: dict[str, Any],
    compute: dict[str, Any],
    model_rows: list[dict[str, Any]],
    required_packages: tuple[str, ...],
) -> dict[str, Any]:
    platform_verified = all(
        bool(layer.get("verified")) for layer in (device, framework, compute)
    )
    models_verified = bool(required_packages) and len(model_rows) == len(required_packages)
    return {
        "protocol_version": "1.0",
        "probe_kind": "aetherdb.rocm.competition",
        "captured_at": _utc_now(),
        "platform_verified": platform_verified,
        "competition_ready": platform_verified and models_verified,
        "policy": policy,
        "device": device,
        "framework": framework,
        "compute": compute,
        "model_evidence": {
            "required_packages": list(required_packages),
            "verified": models_verified,
            "items": model_rows,
            "note": (
                "No model was requested; the Resource Scheduler still requires a "
                "per-model Worker probe before competition execution."
                if not required_packages
                else None
            ),
        },
    }


def persist_report(report: dict[str, Any], runtime_root: Path) -> Path:
    root = runtime_root.expanduser()
    if not root.is_absolute():
        raise RocmProbeError(
            "RUNTIME_ROOT_INVALID",
            "AETHERDB_RUNTIME_ROOT must be an absolute path",
        )
    evidence_dir = root / "evidence" / "rocm"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    target = evidence_dir / "competition-probe.json"
    temporary = evidence_dir / ".competition-probe.tmp"
    temporary.write_text(
        json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    try:
        os.chmod(temporary, 0o600)
    except OSError:
        pass
    os.replace(temporary, target)
    return target


def run_competition_probe(
    environment: dict[str, str] | None = None,
    required_packages: tuple[str, ...] = (),
) -> dict[str, Any]:
    environment = dict(environment or os.environ)
    policy = validate_competition_environment(environment)
    device, fingerprints = probe_device_layer()
    framework, torch_module = probe_framework_layer()
    compute = probe_compute_layer(torch_module, framework["probe_device_index"])
    runtime_root = Path(
        environment.get("AETHERDB_RUNTIME_ROOT", "/var/lib/aetherdb")
    )
    model_rows = _verified_model_rows(
        required_packages,
        runtime_root,
        fingerprints,
    )
    report = build_probe_report(
        policy=policy,
        device=device,
        framework=framework,
        compute=compute,
        model_rows=model_rows,
        required_packages=required_packages,
    )
    persist_report(report, runtime_root)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify the AetherDB ROCm competition evidence chain"
    )
    parser.add_argument(
        "--require-package",
        action="append",
        default=[],
        help="Require current Worker-generated VERIFIED_ROCM evidence for a trusted package",
    )
    args = parser.parse_args()
    try:
        report = run_competition_probe(
            required_packages=tuple(args.require_package)
        )
    except RocmProbeError as exc:
        print(
            json.dumps(
                {
                    "protocol_version": "1.0",
                    "platform_verified": False,
                    "error": {"code": exc.code, "message": exc.safe_message},
                },
                ensure_ascii=True,
                sort_keys=True,
            )
        )
        return 2
    print(
        json.dumps(
            {
                "platform_verified": report["platform_verified"],
                "competition_ready": report["competition_ready"],
                "model_evidence_verified": report["model_evidence"]["verified"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
