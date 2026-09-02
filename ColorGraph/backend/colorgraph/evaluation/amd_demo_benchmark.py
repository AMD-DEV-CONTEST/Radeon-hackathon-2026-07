from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import re
import subprocess
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import torch
from pydantic import BaseModel, ConfigDict, Field, JsonValue

import colorgraph.evaluation.production_benchmark as production_benchmark_module
from colorgraph.config import settings
from colorgraph.devices import TorchComputeBackend
from colorgraph.evaluation.models import StrictEvaluationModel
from colorgraph.evaluation.production_benchmark import (
    BenchmarkRenderAcceleratorEvidence,
    ProductionBenchmarkCase,
    ProductionBenchmarkReport,
    run_production_benchmark,
)
from colorgraph.media.probe import probe_media
from colorgraph.storage import ProjectStore

AMD_DEMO_BENCHMARK_VERSION = "colorgraph.amd-demo-benchmark/v1"
AMD_DEMO_SOURCE_MANIFEST_VERSION = "colorgraph.amd-demo-source-manifest/v1"
AMD_DEMO_SUPPORT_POLICY_VERSION = "amd-rocm-windows-linux-production-7.2.1-2026-08-02"
AMD_DEMO_EXPECTED_HIP_VERSION = "7.2.1"
AMD_DEMO_EXPECTED_TORCH_VERSION = "2.9.1+rocm7.2.1"
AMD_DEMO_EXPECTED_LINUX_HIP_PREFIX = "7.2.53211"
AMD_DEMO_EXPECTED_LINUX_TORCH_VERSION = "2.9.1+rocm7.2.1.gitff65f5bc"
AMD_DEMO_EXPECTED_RADEON_CLOUD_TORCH_VERSION = "2.9.1+gitff65f5b"
AMD_DEMO_REQUIRED_VARIANTS = ("no_mask", "current_combined")
AMD_DEMO_REQUIRED_CASE_KEYS = (
    "no_mask:proxy_1080p:warm",
    "current_combined:proxy_1080p:warm",
)
AMD_DEMO_SUPPORTED_RADEON_MODELS_WINDOWS = (
    "AMD Radeon RX 9070",
    "AMD Radeon RX 9070 XT",
    "AMD Radeon AI PRO R9700",
    "AMD Radeon RX 9060 XT",
    "AMD Radeon RX 7900 XTX",
    "AMD Radeon PRO W7900",
    "AMD Radeon PRO W7900 Dual Slot",
    "AMD Radeon RX 7700",
)
AMD_DEMO_SUPPORTED_RADEON_MODELS_LINUX = (
    "AMD Radeon RX 9070",
    "AMD Radeon RX 9070 XT",
    "AMD Radeon RX 9070 GRE",
    "AMD Radeon AI PRO R9700",
    "AMD Radeon RX 9060",
    "AMD Radeon RX 9060 XT",
    "AMD Radeon RX 7900 XTX",
    "AMD Radeon RX 7900 XT",
    "AMD Radeon RX 7900 GRE",
    "AMD Radeon PRO W7900",
    "AMD Radeon PRO W7900 Dual Slot",
    "AMD Radeon PRO W7800",
    "AMD Radeon PRO W7800 48GB",
    "AMD Radeon RX 7800 XT",
    "AMD Radeon PRO W7700",
    "AMD Radeon RX 7700",
    "AMD Radeon RX 7700 XT",
    "AMD Radeon AI PRO R9600D",
)
AMD_DEMO_SUPPORTED_RADEON_MODELS = tuple(
    dict.fromkeys(
        AMD_DEMO_SUPPORTED_RADEON_MODELS_WINDOWS
        + AMD_DEMO_SUPPORTED_RADEON_MODELS_LINUX
    )
)
AMD_DEMO_SUPPORT_SOURCES = (
    "https://rocm.docs.amd.com/projects/radeon-ryzen/en/latest/docs/"
    "compatibility/compatibilityrad/windows/windows_compatibility.html",
    "https://rocm.docs.amd.com/projects/radeon-ryzen/en/latest/docs/"
    "compatibility/compatibilityryz/windows/windows_compatibility.html",
    "https://rocm.docs.amd.com/projects/radeon-ryzen/en/docs-7.2/docs/"
    "compatibility/compatibilityrad/native_linux/native_linux_compatibility.html",
    "https://rocm.docs.amd.com/projects/radeon-ryzen/en/latest/docs/install/"
    "installrad/native_linux/install-pytorch.html",
)


class _EvidenceInputModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class AmdDemoRights(_EvidenceInputModel):
    license: str = Field(min_length=1)
    license_url: str = Field(min_length=1)
    commercial_use_allowed: bool
    redistribution_allowed: bool
    adaptation_allowed: bool
    share_alike_required: bool
    attribution: str = Field(min_length=1)
    adaptation_notice: str = Field(min_length=1)


class AmdDemoClip(_EvidenceInputModel):
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bytes: int = Field(gt=0)
    duration_seconds: float = Field(gt=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    fps: float = Field(gt=0)
    frame_count: int = Field(gt=0)
    codec: str = Field(min_length=1)
    pixel_format: str = Field(min_length=1)


class AmdDemoVisualReview(_EvidenceInputModel):
    passed: bool
    contact_sheet_path: str = Field(min_length=1)
    contact_sheet_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    observation: str = Field(min_length=1)


class AmdDemoSceneStructure(_EvidenceInputModel):
    hard_cut_times_seconds: list[float]
    shot_count: int = Field(ge=1)
    visual_review: AmdDemoVisualReview


class AmdDemoSourceValidation(_EvidenceInputModel):
    full_decode_passed: bool
    decoded_frames: int = Field(gt=0)
    duration_gate_passed: bool
    resolution_gate_passed: bool
    redistribution_gate_passed: bool
    hard_cut_shot_count_gate_passed: bool


class AmdDemoSourceManifest(_EvidenceInputModel):
    schema_version: Literal["colorgraph.amd-demo-source-manifest/v1"]
    task_id: Literal["CG-BENCH-001"]
    status: str = Field(min_length=1)
    rights: AmdDemoRights
    clip: AmdDemoClip
    scene_structure: AmdDemoSceneStructure
    validation: AmdDemoSourceValidation


class AmdDriverEvidence(StrictEvaluationModel):
    version: str | None = None
    source: str
    command: list[str] = Field(default_factory=list)


class AmdDemoSupportPolicy(StrictEvaluationModel):
    policy_version: str = AMD_DEMO_SUPPORT_POLICY_VERSION
    rocm_release: str = AMD_DEMO_EXPECTED_HIP_VERSION
    supported_radeon_models: list[str] = Field(
        default_factory=lambda: list(AMD_DEMO_SUPPORTED_RADEON_MODELS)
    )
    torch_builds: dict[str, list[str]] = Field(
        default_factory=lambda: {
            "windows": [AMD_DEMO_EXPECTED_TORCH_VERSION],
            "linux": [
                AMD_DEMO_EXPECTED_LINUX_TORCH_VERSION,
                AMD_DEMO_EXPECTED_RADEON_CLOUD_TORCH_VERSION,
            ],
        }
    )
    hardware_encoders: dict[str, list[str]] = Field(
        default_factory=lambda: {
            "windows": ["h264_amf", "hevc_amf"],
            "linux": ["h264_vaapi", "hevc_vaapi"],
        }
    )
    source_urls: list[str] = Field(default_factory=lambda: list(AMD_DEMO_SUPPORT_SOURCES))


class AmdDemoGateCheck(StrictEvaluationModel):
    check_id: str
    passed: bool
    required: JsonValue
    observed: JsonValue
    detail: str


class AmdDemoCaseEvidence(StrictEvaluationModel):
    case_key: str
    variant: str
    status: str
    processing_fps: float | None = None
    p95_frame_latency_ms: float | None = None
    peak_vram_allocated_mb: float | None = None
    peak_vram_reserved_mb: float | None = None
    output_codec: str | None = None
    encoder: str | None = None
    encoder_hardware_accelerated: bool | None = None
    encoder_available_verified: bool | None = None
    render_accelerator_evidence: BenchmarkRenderAcceleratorEvidence | None = None
    output_sha256: str | None = None
    output_hash_verified: bool
    quality_checked: bool
    hard_quality_checks_passed: bool | None = None
    quality_report_sha256: str | None = None
    quality_hash_verified: bool | None = None
    measurement_origin: str
    resumed_from_checkpoint: bool


class AmdDemoImplementationEvidence(StrictEvaluationModel):
    runner_version: str = AMD_DEMO_BENCHMARK_VERSION
    package_version: str
    runner_source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    production_benchmark_source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class AmdDemoBenchmarkReport(StrictEvaluationModel):
    schema_version: str = AMD_DEMO_BENCHMARK_VERSION
    created_at: datetime
    task_id: Literal["CG-BENCH-001"] = "CG-BENCH-001"
    status: Literal["passed", "engineering_preflight_only", "blocked", "failed"]
    gate_passed: bool
    source_manifest_path: str
    source_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    benchmark_report_path: str
    benchmark_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    benchmark_run_id: str
    audit_sha256_sidecar_path: str
    implementation: AmdDemoImplementationEvidence
    support_policy: AmdDemoSupportPolicy
    hardware: dict[str, object]
    software: dict[str, str | None]
    amd_driver: AmdDriverEvidence
    required_case_keys: list[str]
    cases: list[AmdDemoCaseEvidence]
    checks: list[AmdDemoGateCheck]
    blockers: list[str]
    raw_report_status: str
    raw_production_claim_allowed: bool
    notes: list[str]


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def _command_output(command: list[str], *, timeout_seconds: float = 10) -> str | None:
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    value = completed.stdout.strip()
    return value or None


def capture_amd_driver_evidence() -> AmdDriverEvidence:
    if os.name == "nt":
        command = [
            "powershell.exe",
            "-NoProfile",
            "-Command",
            (
                "(Get-CimInstance Win32_VideoController | "
                "Where-Object { $_.Name -match 'AMD|Radeon' } | "
                "Select-Object -ExpandProperty DriverVersion) -join ','"
            ),
        ]
        value = _command_output(command)
        if value:
            versions = sorted({item.strip() for item in value.split(",") if item.strip()})
            if versions:
                return AmdDriverEvidence(
                    version=",".join(versions),
                    source="windows_cim_video_controller",
                    command=command,
                )

    rocm_smi_command = ["rocm-smi", "--showdriverversion"]
    rocm_smi = _command_output(rocm_smi_command)
    if rocm_smi:
        match = re.search(r"driver\s+version\s*[:=]\s*([^\s,}]+)", rocm_smi, re.I)
        value = match.group(1) if match else rocm_smi.splitlines()[0].strip()
        return AmdDriverEvidence(
            version=value,
            source="rocm_smi",
            command=rocm_smi_command,
        )

    modinfo_command = ["modinfo", "amdgpu", "-F", "version"]
    modinfo = _command_output(modinfo_command)
    if modinfo:
        return AmdDriverEvidence(
            version=modinfo.splitlines()[0].strip(),
            source="linux_modinfo_amdgpu",
            command=modinfo_command,
        )
    return AmdDriverEvidence(version=None, source="unavailable")


def _normalized_device_name(value: str) -> str:
    normalized = re.sub(r"\((?:tm|r)\)", "", value, flags=re.I)
    return " ".join(normalized.casefold().split())


def _is_linux(operating_system: str | None = None) -> bool:
    value = operating_system or platform.system()
    return value.casefold().startswith("linux")


def amd_supported_radeon_models(operating_system: str | None = None) -> tuple[str, ...]:
    return (
        AMD_DEMO_SUPPORTED_RADEON_MODELS_LINUX
        if _is_linux(operating_system)
        else AMD_DEMO_SUPPORTED_RADEON_MODELS_WINDOWS
    )


def amd_hardware_encoders(operating_system: str | None = None) -> frozenset[str]:
    return (
        frozenset({"h264_vaapi", "hevc_vaapi"})
        if _is_linux(operating_system)
        else frozenset({"h264_amf", "hevc_amf"})
    )


def amd_torch_runtime_is_supported(
    torch_version: str | None,
    operating_system: str | None = None,
) -> bool:
    expected = (
        {
            AMD_DEMO_EXPECTED_LINUX_TORCH_VERSION,
            AMD_DEMO_EXPECTED_RADEON_CLOUD_TORCH_VERSION,
        }
        if _is_linux(operating_system)
        else {AMD_DEMO_EXPECTED_TORCH_VERSION}
    )
    return torch_version in expected


def amd_hip_runtime_is_supported(
    hip_version: str | None,
    operating_system: str | None = None,
) -> bool:
    if not hip_version:
        return False
    if _is_linux(operating_system):
        return hip_version.startswith(AMD_DEMO_EXPECTED_LINUX_HIP_PREFIX)
    return hip_version == AMD_DEMO_EXPECTED_HIP_VERSION


def amd_device_is_supported(
    device_name: str,
    *,
    operating_system: str | None = None,
    architecture: str | None = None,
    total_memory_mb: int | None = None,
    compute_units: int | None = None,
) -> bool:
    observed = _normalized_device_name(device_name)
    if any(
        observed == expected or observed.startswith(f"{expected} ")
        for expected in map(
            _normalized_device_name,
            amd_supported_radeon_models(operating_system),
        )
    ):
        return True

    # Some bare-metal cloud images intentionally expose a generic marketing
    # name. Accept only the complete, machine-probed W7900-family signature:
    # gfx1100, 96 CUs, and approximately 48 GiB. The Linux 7.2 matrix lists
    # both W7900 variants; RX 7900 XTX has the same CU count but only 24 GiB.
    normalized_architecture = (architecture or "").split(":", 1)[0].casefold()
    return (
        _is_linux(operating_system)
        and observed == _normalized_device_name("AMD Radeon Graphics")
        and normalized_architecture == "gfx1100"
        and compute_units == 96
        and total_memory_mb is not None
        and 48_000 <= total_memory_mb <= 50_000
    )


def _load_source_manifest(path: Path) -> AmdDemoSourceManifest:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return AmdDemoSourceManifest.model_validate(payload)


def _case_output_hash_verified(case: ProductionBenchmarkCase) -> bool:
    if not case.output_path or not case.output_sha256:
        return False
    path = Path(case.output_path)
    return path.is_file() and _file_sha256(path) == case.output_sha256


def _case_quality_hash_verified(case: ProductionBenchmarkCase) -> bool | None:
    if not case.quality_checked:
        return None
    if not case.quality_report_path or not case.quality_report_sha256:
        return False
    path = Path(case.quality_report_path)
    return path.is_file() and _file_sha256(path) == case.quality_report_sha256


def _case_evidence(case: ProductionBenchmarkCase) -> AmdDemoCaseEvidence:
    return AmdDemoCaseEvidence(
        case_key=case.case_key,
        variant=case.variant,
        status=case.status,
        processing_fps=case.processing_fps,
        p95_frame_latency_ms=case.p95_frame_latency_ms,
        peak_vram_allocated_mb=case.peak_vram_allocated_mb,
        peak_vram_reserved_mb=case.peak_vram_reserved_mb,
        output_codec=case.output_codec,
        encoder=case.encoder,
        encoder_hardware_accelerated=case.encoder_hardware_accelerated,
        encoder_available_verified=case.encoder_available_verified,
        render_accelerator_evidence=case.render_accelerator_evidence,
        output_sha256=case.output_sha256,
        output_hash_verified=_case_output_hash_verified(case),
        quality_checked=case.quality_checked,
        hard_quality_checks_passed=case.hard_quality_checks_passed,
        quality_report_sha256=case.quality_report_sha256,
        quality_hash_verified=_case_quality_hash_verified(case),
        measurement_origin=case.measurement_origin,
        resumed_from_checkpoint=case.resumed_from_checkpoint,
    )


def _static_manifest_failures(manifest: AmdDemoSourceManifest) -> list[str]:
    checks = {
        "manifest_status": manifest.status == "ready_for_supported_amd_benchmark",
        "redistribution_rights": (
            manifest.rights.commercial_use_allowed
            and manifest.rights.redistribution_allowed
            and manifest.rights.adaptation_allowed
            and bool(manifest.rights.attribution)
            and bool(manifest.rights.adaptation_notice)
        ),
        "duration": 12.0 <= manifest.clip.duration_seconds <= 25.0,
        "resolution": (manifest.clip.width, manifest.clip.height) == (1920, 1080),
        "shot_count": (
            2 <= manifest.scene_structure.shot_count <= 4
            and len(manifest.scene_structure.hard_cut_times_seconds)
            == manifest.scene_structure.shot_count - 1
            and manifest.scene_structure.visual_review.passed
        ),
        "source_validation": (
            manifest.validation.full_decode_passed
            and manifest.validation.decoded_frames == manifest.clip.frame_count
            and manifest.validation.duration_gate_passed
            and manifest.validation.resolution_gate_passed
            and manifest.validation.redistribution_gate_passed
            and manifest.validation.hard_cut_shot_count_gate_passed
        ),
    }
    return sorted(check_id for check_id, passed in checks.items() if not passed)


def _check(
    checks: list[AmdDemoGateCheck],
    check_id: str,
    passed: bool,
    *,
    required: JsonValue,
    observed: JsonValue,
    detail: str,
) -> None:
    checks.append(
        AmdDemoGateCheck(
            check_id=check_id,
            passed=passed,
            required=required,
            observed=observed,
            detail=detail,
        )
    )


def audit_amd_demo_benchmark(
    *,
    source_manifest: AmdDemoSourceManifest,
    source_manifest_path: Path,
    benchmark_report: ProductionBenchmarkReport,
    benchmark_report_path: Path,
    output_path: Path,
    driver_evidence: AmdDriverEvidence,
) -> AmdDemoBenchmarkReport:
    checks: list[AmdDemoGateCheck] = []
    case_by_key = {case.case_key: case for case in benchmark_report.cases}
    required_cases = [case_by_key[key] for key in AMD_DEMO_REQUIRED_CASE_KEYS if key in case_by_key]
    operating_system = str(benchmark_report.software.get("operating_system", ""))
    supported_encoders = amd_hardware_encoders(operating_system)

    manifest_failures = _static_manifest_failures(source_manifest)
    _check(
        checks,
        "source_manifest",
        not manifest_failures,
        required="licensed, redistributable, fully decoded 12-25 second 1080p source",
        observed={
            "status": source_manifest.status,
            "failed_static_checks": manifest_failures,
        },
        detail="The source manifest must pass every frozen AMD Demo source gate.",
    )
    _check(
        checks,
        "source_sha256",
        benchmark_report.source.sha256 == source_manifest.clip.sha256,
        required=source_manifest.clip.sha256,
        observed=benchmark_report.source.sha256,
        detail="The benchmark project source must match the licensed clip byte-for-byte.",
    )
    source_shape_matches = (
        benchmark_report.source.width == source_manifest.clip.width == 1920
        and benchmark_report.source.height == source_manifest.clip.height == 1080
        and benchmark_report.source.frame_count == source_manifest.clip.frame_count
        and abs(benchmark_report.source.duration_seconds - source_manifest.clip.duration_seconds)
        <= 0.05
        and abs(benchmark_report.source.fps - source_manifest.clip.fps) <= 1e-3
    )
    _check(
        checks,
        "source_media_shape",
        source_shape_matches,
        required={
            "width": 1920,
            "height": 1080,
            "duration_seconds": source_manifest.clip.duration_seconds,
            "fps": source_manifest.clip.fps,
            "frame_count": source_manifest.clip.frame_count,
        },
        observed={
            "width": benchmark_report.source.width,
            "height": benchmark_report.source.height,
            "duration_seconds": benchmark_report.source.duration_seconds,
            "fps": benchmark_report.source.fps,
            "frame_count": benchmark_report.source.frame_count,
        },
        detail="The raw report must describe the complete frozen 1080p clip.",
    )
    requested_scope = (
        set(benchmark_report.requested_variants) == set(AMD_DEMO_REQUIRED_VARIANTS)
        and benchmark_report.requested_profiles == ["proxy_1080p"]
        and benchmark_report.requested_thermal_states == ["warm"]
        and abs(benchmark_report.render_start_seconds) <= 1e-9
        and abs(benchmark_report.render_end_seconds - source_manifest.clip.duration_seconds) <= 0.05
    )
    _check(
        checks,
        "requested_scope",
        requested_scope,
        required={
            "variants": list(AMD_DEMO_REQUIRED_VARIANTS),
            "profiles": ["proxy_1080p"],
            "thermal_states": ["warm"],
            "full_clip": True,
        },
        observed={
            "variants": list(benchmark_report.requested_variants),
            "profiles": list(benchmark_report.requested_profiles),
            "thermal_states": list(benchmark_report.requested_thermal_states),
            "render_start_seconds": benchmark_report.render_start_seconds,
            "render_end_seconds": benchmark_report.render_end_seconds,
        },
        detail="The Demo gate accepts only the two frozen warm 1080p variants.",
    )
    exact_case_keys = sorted(case.case_key for case in benchmark_report.cases) == sorted(
        AMD_DEMO_REQUIRED_CASE_KEYS
    )
    cases_complete = (
        exact_case_keys
        and len(required_cases) == len(AMD_DEMO_REQUIRED_CASE_KEYS)
        and all(case.status == "completed" for case in required_cases)
    )
    _check(
        checks,
        "case_coverage",
        cases_complete,
        required=list(AMD_DEMO_REQUIRED_CASE_KEYS),
        observed={case.case_key: case.status for case in benchmark_report.cases},
        detail="Both requested rows must complete; blocked, failed, missing, or extra rows fail.",
    )
    fresh_measurements = bool(required_cases) and all(
        case.measurement_origin == "fresh_render"
        and not case.resumed_from_checkpoint
        and case.resumed_from_input_digest is None
        and case.checkpoint_reuse_reason is None
        for case in required_cases
    )
    _check(
        checks,
        "fresh_measurements",
        fresh_measurements and len(required_cases) == len(AMD_DEMO_REQUIRED_CASE_KEYS),
        required={
            "measurement_origin": "fresh_render",
            "resumed_from_checkpoint": False,
        },
        observed={
            case.case_key: {
                "measurement_origin": case.measurement_origin,
                "resumed_from_checkpoint": case.resumed_from_checkpoint,
                "checkpoint_reuse_reason": case.checkpoint_reuse_reason,
            }
            for case in required_cases
        },
        detail="Final AMD measurements cannot be reused from a prior device or driver.",
    )

    metric_rows_complete = bool(required_cases) and all(
        case.processing_fps is not None
        and case.processing_fps > 0
        and case.p95_frame_latency_ms is not None
        and case.p95_frame_latency_ms >= 0
        and case.peak_vram_allocated_mb is not None
        and case.peak_vram_allocated_mb > 0
        and case.peak_vram_reserved_mb is not None
        and case.peak_vram_reserved_mb > 0
        and bool(case.output_codec)
        and bool(case.encoder)
        for case in required_cases
    )
    _check(
        checks,
        "performance_evidence",
        metric_rows_complete and len(required_cases) == len(AMD_DEMO_REQUIRED_CASE_KEYS),
        required=[
            "processing_fps",
            "p95_frame_latency_ms",
            "peak_vram_allocated_mb",
            "peak_vram_reserved_mb",
            "output_codec",
            "encoder",
        ],
        observed={
            case.case_key: {
                "processing_fps": case.processing_fps,
                "p95_frame_latency_ms": case.p95_frame_latency_ms,
                "peak_vram_allocated_mb": case.peak_vram_allocated_mb,
                "peak_vram_reserved_mb": case.peak_vram_reserved_mb,
                "output_codec": case.output_codec,
                "encoder": case.encoder,
            }
            for case in required_cases
        },
        detail="Every completed row must carry measured performance, memory, and codec evidence.",
    )
    amd_gpu_rows_valid = bool(required_cases) and all(
        case.encoder in supported_encoders
        and case.encoder_hardware_accelerated is True
        and case.encoder_available_verified is True
        and case.render_accelerator_evidence is not None
        and case.render_accelerator_evidence.runtime == "rocm"
        and case.render_accelerator_evidence.vendor.casefold() == "amd"
        and bool(case.render_accelerator_evidence.hip_version)
        and case.render_accelerator_evidence.batch_count > 0
        and case.render_accelerator_evidence.all_batches_accelerator_verified
        and bool(case.render_accelerator_evidence.peak_allocated_memory_mb)
        for case in required_cases
    )
    _check(
        checks,
        "amd_gpu_execution",
        amd_gpu_rows_valid and len(required_cases) == len(AMD_DEMO_REQUIRED_CASE_KEYS),
        required={
            "renderer": "ROCm/AMD/HIP with every batch on accelerator",
            "encoder": sorted(supported_encoders),
            "encoder_available_verified": True,
        },
        observed={
            case.case_key: {
                "encoder": case.encoder,
                "encoder_hardware_accelerated": (case.encoder_hardware_accelerated),
                "encoder_available_verified": case.encoder_available_verified,
                "render_accelerator_evidence": (
                    case.render_accelerator_evidence.model_dump(mode="json")
                    if case.render_accelerator_evidence is not None
                    else None
                ),
            }
            for case in required_cases
        },
        detail=(
            "Every Demo row must prove ROCm tensor execution for every grading "
            "batch and an available AMD hardware encoder for the active OS."
        ),
    )
    output_rows_valid = bool(required_cases) and all(
        case.output_width == 1920
        and case.output_height == 1080
        and case.frame_count == source_manifest.clip.frame_count
        and case.output_duration_seconds is not None
        and abs(case.output_duration_seconds - source_manifest.clip.duration_seconds) <= 0.05
        and _case_output_hash_verified(case)
        for case in required_cases
    )
    _check(
        checks,
        "output_integrity",
        output_rows_valid and len(required_cases) == len(AMD_DEMO_REQUIRED_CASE_KEYS),
        required="two complete 1920x1080 outputs with independently verified SHA-256",
        observed={
            case.case_key: {
                "width": case.output_width,
                "height": case.output_height,
                "frame_count": case.frame_count,
                "duration_seconds": case.output_duration_seconds,
                "output_sha256": case.output_sha256,
                "hash_verified": _case_output_hash_verified(case),
            }
            for case in required_cases
        },
        detail="Output dimensions, duration, frame count, and file hashes must match.",
    )
    current = case_by_key.get("current_combined:proxy_1080p:warm")
    hard_quality_passed = bool(
        current
        and current.status == "completed"
        and current.quality_checked
        and current.hard_quality_checks_passed is True
        and _case_quality_hash_verified(current) is True
    )
    _check(
        checks,
        "hard_quality",
        hard_quality_passed,
        required={
            "case": "current_combined:proxy_1080p:warm",
            "hard_quality_checks_passed": True,
            "quality_report_hash_verified": True,
        },
        observed=(
            {
                "quality_checked": current.quality_checked,
                "hard_quality_checks_passed": current.hard_quality_checks_passed,
                "quality_score": current.quality_score,
                "quality_report_sha256": current.quality_report_sha256,
                "quality_report_hash_verified": _case_quality_hash_verified(current),
            }
            if current
            else None
        ),
        detail="The combined warm row must pass hard QA with a verified quality report.",
    )
    _check(
        checks,
        "model_provenance",
        benchmark_report.model_provenance_complete
        and not benchmark_report.model_provenance_blockers,
        required=True,
        observed={
            "complete": benchmark_report.model_provenance_complete,
            "blockers": benchmark_report.model_provenance_blockers,
        },
        detail="Every active mask asset must retain complete model and checkpoint provenance.",
    )

    runtime = str(benchmark_report.hardware.get("runtime", ""))
    vendor = str(benchmark_report.hardware.get("vendor", ""))
    device_name = str(benchmark_report.hardware.get("name", ""))
    _check(
        checks,
        "runtime_rocm",
        runtime == "rocm",
        required="rocm",
        observed=runtime,
        detail="CUDA and CPU reports are engineering preflight only.",
    )
    _check(
        checks,
        "vendor_amd",
        vendor.casefold() == "amd",
        required="AMD",
        observed=vendor,
        detail="The benchmark hardware vendor must be reported by the active backend as AMD.",
    )
    _check(
        checks,
        "supported_radeon",
        amd_device_is_supported(
            device_name,
            operating_system=operating_system,
            architecture=str(benchmark_report.hardware.get("architecture", "")),
            total_memory_mb=benchmark_report.hardware.get("total_memory_mb"),
            compute_units=benchmark_report.hardware.get("compute_units"),
        ),
        required={
            "models": list(amd_supported_radeon_models(operating_system)),
            "generic_cloud_signature": {
                "architecture": "gfx1100",
                "compute_units": 96,
                "total_memory_mb": "48000..50000",
            },
        },
        observed={
            "name": device_name,
            "architecture": benchmark_report.hardware.get("architecture"),
            "compute_units": benchmark_report.hardware.get("compute_units"),
            "total_memory_mb": benchmark_report.hardware.get("total_memory_mb"),
        },
        detail=(
            "The device must match the frozen ROCm 7.2.1 Radeon list by marketing "
            "name or the fail-closed W7900 cloud hardware signature."
        ),
    )
    hip_version = benchmark_report.software.get("hip_version")
    torch_version = benchmark_report.software.get("torch_version")
    python_version = benchmark_report.software.get("python_version")
    _check(
        checks,
        "python_runtime",
        bool(python_version and str(python_version).startswith("3.12.")),
        required="Python 3.12",
        observed=python_version,
        detail="The ROCm 7.2.1 gate requires a Python 3.12 runtime.",
    )
    _check(
        checks,
        "torch_runtime",
        amd_torch_runtime_is_supported(torch_version, operating_system),
        required=(
            [
                AMD_DEMO_EXPECTED_LINUX_TORCH_VERSION,
                AMD_DEMO_EXPECTED_RADEON_CLOUD_TORCH_VERSION,
            ]
            if _is_linux(operating_system)
            else AMD_DEMO_EXPECTED_TORCH_VERSION
        ),
        observed=torch_version,
        detail="The report must use the frozen official ROCm PyTorch wheel for its OS.",
    )
    _check(
        checks,
        "hip_runtime",
        amd_hip_runtime_is_supported(hip_version, operating_system),
        required=(
            f"{AMD_DEMO_EXPECTED_LINUX_HIP_PREFIX}*"
            if _is_linux(operating_system)
            else AMD_DEMO_EXPECTED_HIP_VERSION
        ),
        observed=hip_version,
        detail="The report must bind the frozen HIP runtime exposed by PyTorch.",
    )
    _check(
        checks,
        "amd_driver",
        bool(driver_evidence.version),
        required="machine-probed AMD display or amdgpu driver version",
        observed={
            "version": driver_evidence.version,
            "source": driver_evidence.source,
        },
        detail="Manual or inferred driver versions do not satisfy the gate.",
    )
    _check(
        checks,
        "raw_report_nonproduction",
        benchmark_report.status == "partial" and benchmark_report.production_claim_allowed is False,
        required={
            "status": "partial",
            "production_claim_allowed": False,
        },
        observed={
            "status": benchmark_report.status,
            "production_claim_allowed": benchmark_report.production_claim_allowed,
        },
        detail="The short two-row gate must never be re-labelled as the full production matrix.",
    )

    blockers = [check.check_id for check in checks if not check.passed]
    runtime_identity_checks = {
        "runtime_rocm",
        "vendor_amd",
        "supported_radeon",
    }
    non_runtime_blockers = [
        blocker for blocker in blockers if blocker not in runtime_identity_checks
    ]
    if not blockers:
        status: Literal["passed", "engineering_preflight_only", "blocked", "failed"] = "passed"
    elif any(blocker in runtime_identity_checks for blocker in blockers) and set(
        non_runtime_blockers
    ) <= {
        "hip_runtime",
        "python_runtime",
        "torch_runtime",
        "amd_driver",
        "fresh_measurements",
        "amd_gpu_execution",
    }:
        status = "engineering_preflight_only"
    elif set(blockers) <= {"hip_runtime", "amd_driver"}:
        status = "blocked"
    else:
        status = "failed"

    return AmdDemoBenchmarkReport(
        created_at=datetime.now(UTC),
        status=status,
        gate_passed=status == "passed",
        source_manifest_path=str(source_manifest_path),
        source_manifest_sha256=_file_sha256(source_manifest_path),
        benchmark_report_path=str(benchmark_report_path),
        benchmark_report_sha256=_file_sha256(benchmark_report_path),
        benchmark_run_id=benchmark_report.run_id,
        audit_sha256_sidecar_path=str(output_path.with_name(f"{output_path.name}.sha256")),
        implementation=AmdDemoImplementationEvidence(
            package_version=importlib.metadata.version("colorgraph-backend"),
            runner_source_sha256=_file_sha256(Path(__file__).resolve()),
            production_benchmark_source_sha256=_file_sha256(
                Path(production_benchmark_module.__file__).resolve()
            ),
        ),
        support_policy=AmdDemoSupportPolicy(),
        hardware=benchmark_report.hardware,
        software=benchmark_report.software,
        amd_driver=driver_evidence,
        required_case_keys=list(AMD_DEMO_REQUIRED_CASE_KEYS),
        cases=[_case_evidence(case) for case in required_cases],
        checks=checks,
        blockers=blockers,
        raw_report_status=benchmark_report.status,
        raw_production_claim_allowed=benchmark_report.production_claim_allowed,
        notes=[
            "This report authorizes only the narrowed CG-BENCH-001 AMD Demo gate.",
            "The full 20-row, >=120-second production matrix remains independently deferred.",
            "A CUDA/CPU result may validate execution wiring but cannot satisfy the AMD gate.",
        ],
    )


def audit_amd_demo_benchmark_file(
    *,
    source_manifest: str | Path,
    benchmark_report: str | Path,
    output: str | Path,
    driver_evidence: AmdDriverEvidence | None = None,
) -> tuple[AmdDemoBenchmarkReport, str]:
    manifest_path = Path(source_manifest).resolve()
    benchmark_path = Path(benchmark_report).resolve()
    output_path = Path(output).resolve()
    manifest = _load_source_manifest(manifest_path)
    raw_report = ProductionBenchmarkReport.model_validate_json(
        benchmark_path.read_text(encoding="utf-8")
    )
    report = audit_amd_demo_benchmark(
        source_manifest=manifest,
        source_manifest_path=manifest_path,
        benchmark_report=raw_report,
        benchmark_report_path=benchmark_path,
        output_path=output_path,
        driver_evidence=driver_evidence or capture_amd_driver_evidence(),
    )
    _atomic_write(output_path, report.model_dump_json(indent=2))
    digest = _file_sha256(output_path)
    sidecar = Path(report.audit_sha256_sidecar_path)
    _atomic_write(sidecar, f"{digest}  {output_path.name}\n")
    return report, digest


def _validate_project_source(project_id: str, manifest: AmdDemoSourceManifest) -> None:
    failures = _static_manifest_failures(manifest)
    if failures:
        raise ValueError(f"AMD Demo source manifest failed: {failures}")
    store = ProjectStore()
    project = store.get(project_id)
    source_path = store.resolve_source(project)
    if _file_sha256(source_path) != manifest.clip.sha256:
        raise ValueError("project source SHA-256 does not match the AMD Demo source manifest")
    media = probe_media(source_path)
    if (
        (media.width, media.height) != (manifest.clip.width, manifest.clip.height)
        or media.frame_count != manifest.clip.frame_count
        or abs(media.duration_seconds - manifest.clip.duration_seconds) > 0.05
    ):
        raise ValueError("project source media shape does not match the AMD Demo manifest")


def _require_supported_current_amd_runtime(driver: AmdDriverEvidence) -> None:
    info = TorchComputeBackend(settings.device_preference).info
    failures: list[str] = []
    if info.runtime != "rocm":
        failures.append(f"runtime={info.runtime}")
    if info.vendor.casefold() != "amd":
        failures.append(f"vendor={info.vendor}")
    if not amd_device_is_supported(
        info.name,
        operating_system=platform.system(),
        architecture=getattr(info, "architecture", None),
        total_memory_mb=getattr(info, "total_memory_mb", None),
        compute_units=getattr(info, "compute_units", None),
    ):
        failures.append(f"unsupported_device={info.name}")
    if not torch.version.hip:
        failures.append("torch.version.hip is empty")
    if not driver.version:
        failures.append("AMD driver version is unavailable")
    if failures:
        raise RuntimeError(
            "AMD Demo benchmark requires a supported AMD Radeon/ROCm environment: "
            + "; ".join(failures)
        )


def run_amd_demo_benchmark(
    *,
    project_id: str,
    source_manifest: str | Path,
    benchmark_output: str | Path,
    output: str | Path,
    batch_size: int = 4,
    progress: Callable[[str, int, int], None] | None = None,
) -> tuple[AmdDemoBenchmarkReport, str]:
    manifest_path = Path(source_manifest).resolve()
    benchmark_path = Path(benchmark_output).resolve()
    output_path = Path(output).resolve()
    if benchmark_path == output_path:
        raise ValueError("raw benchmark and AMD Demo audit outputs must be different files")
    manifest = _load_source_manifest(manifest_path)
    _validate_project_source(project_id, manifest)
    driver = capture_amd_driver_evidence()
    _require_supported_current_amd_runtime(driver)
    run_production_benchmark(
        project_id=project_id,
        output=benchmark_path,
        variants=AMD_DEMO_REQUIRED_VARIANTS,
        profiles=("proxy_1080p",),
        thermal_states=("warm",),
        batch_size=batch_size,
        hash_source=True,
        quality_checks=True,
        resume=False,
        require_hardware_encoder=True,
        progress=progress,
    )
    return audit_amd_demo_benchmark_file(
        source_manifest=manifest_path,
        benchmark_report=benchmark_path,
        output=output_path,
        driver_evidence=driver,
    )
