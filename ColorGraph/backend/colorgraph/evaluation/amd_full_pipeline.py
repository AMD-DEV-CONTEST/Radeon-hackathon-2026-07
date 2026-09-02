from __future__ import annotations

import asyncio
import hashlib
import importlib.metadata
import json
import os
import platform
import sys
import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path, PureWindowsPath
from typing import Literal

import numpy as np
import torch
from PIL import Image
from pydantic import Field, JsonValue

import colorgraph.agent.creative_provider as creative_provider_module
import colorgraph.devices.evidence as device_evidence_module
import colorgraph.devices.ollama_evidence as ollama_evidence_module
import colorgraph.evaluation.amd_demo_benchmark as amd_demo_benchmark_module
import colorgraph.grading.aces2_gpu as aces2_gpu_module
import colorgraph.grading.masks as masks_module
import colorgraph.grading.video as video_module
import colorgraph.quality.analyzer as quality_analyzer_module
from colorgraph.agent.creative_provider import (
    CreativeModelRequest,
    CreativeProviderRuntime,
    CreativeRole,
    ProviderCapabilities,
    ProviderHardwareEvidence,
    ProviderImage,
    ProviderResponseCache,
    RuntimeBudget,
    RuntimePolicy,
    configured_ollama_provider,
)
from colorgraph.agent.scene_understanding import LocalSceneAnalyzer
from colorgraph.config import settings
from colorgraph.devices import (
    OllamaBackendEvidence,
    StageReleaseEvidence,
    TorchComputeBackend,
    TorchStageEvidence,
    begin_ollama_backend_evidence,
    capture_ollama_backend_evidence,
    release_pytorch_stage,
    require_amd_rocm_stage_evidence,
)
from colorgraph.devices.base import DeviceInfo
from colorgraph.domain.grade_graph import GradeGraph
from colorgraph.evaluation.amd_demo_benchmark import (
    AMD_DEMO_EXPECTED_HIP_VERSION,
    AMD_DEMO_EXPECTED_LINUX_HIP_PREFIX,
    AMD_DEMO_EXPECTED_LINUX_TORCH_VERSION,
    AMD_DEMO_EXPECTED_RADEON_CLOUD_TORCH_VERSION,
    AMD_DEMO_EXPECTED_TORCH_VERSION,
    AmdDemoBenchmarkReport,
    AmdDemoSourceManifest,
    AmdDriverEvidence,
    amd_device_is_supported,
    amd_hip_runtime_is_supported,
    amd_torch_runtime_is_supported,
    capture_amd_driver_evidence,
    run_amd_demo_benchmark,
)
from colorgraph.evaluation.models import StrictEvaluationModel
from colorgraph.evaluation.precision_gate import PrecisionGateReport
from colorgraph.evaluation.production_benchmark import (
    BenchmarkRenderAcceleratorEvidence,
)
from colorgraph.grading.looks import graph_digest
from colorgraph.grading.video import VideoRenderer, require_amd_gpu_render
from colorgraph.media.probe import probe_media
from colorgraph.quality import analyze_video_quality
from colorgraph.storage import ProjectPaths, ProjectStore
from colorgraph.vision import DepthMaskProvider, SemanticMaskProvider
from colorgraph.vision.base import MaskPrediction
from colorgraph.vision.model_lifecycle import clear_inference_caches

AMD_FULL_PIPELINE_VERSION = "colorgraph.amd-full-pipeline/v1"
AMD_FULL_PIPELINE_TASK_IDS = ("CG-COLOR-003", "CG-BENCH-001")
AMD_FULL_OLLAMA_MODEL = "colorgraph-qwen3.5:9b"
AMD_FULL_OLLAMA_MODEL_DIGEST = "a2845456d7ad1e2100f620eaad82c3e63860a24330948111f6ad5d8202fd3634"
AMD_FULL_OLLAMA_QUANTIZATION = "Q4_K_M"
AMD_FULL_OLLAMA_MINIMUM_CONTEXT = 8_192
AMD_FULL_OLLAMA_MINIMUM_OFFLOAD_RATIO = 0.99
AMD_FULL_CLIP_MODEL_ID = "openai/clip-vit-base-patch32"
AMD_FULL_CLIP_MODEL_REVISION = "3d74acf9a28c67741b2f4f2ea7635f0aaf6f0268"
AMD_FULL_CLIP_CHECKPOINT_SHA256 = "c6ece25cb6d105a3e93bd8c06bc89990a83725dd82bfeddee62bba803d045ca4"
AMD_FULL_SEMANTIC_MODEL_ID = "nvidia/segformer-b0-finetuned-ade-512-512"
AMD_FULL_SEMANTIC_MODEL_REVISION = "489d5cd81a0b59fab9b7ea758d3548ebe99677da"
AMD_FULL_SEMANTIC_CHECKPOINT_SHA256 = (
    "ccce07e3f07157bbb9d9e60a01e7b2df1c2de197594b7455bd5caa374c4279f9"
)
AMD_FULL_DEPTH_MODEL_ID = "depth-anything/Depth-Anything-V2-Small-hf"
AMD_FULL_DEPTH_MODEL_REVISION = "5426e4f0f36572d16453bbda7a8389317b1bef99"
AMD_FULL_DEPTH_CHECKPOINT_SHA256 = (
    "31bf8a51525cf691e1ee69e76729183b0b8392b569099fc849cb75a7956b114a"
)
AMD_FULL_CHECKPOINT_HASH_KIND = "colorgraph.torch-state-dict/v1"
AMD_FULL_EXPECTED_RUNTIME_PACKAGES = {
    "aiofiles": "25.1.0",
    "easydict": "1.13",
    "einops": "0.4.1",
    "fastapi": "0.140.0",
    "hydra-core": "1.3.4",
    "httpx": "0.28.1",
    "numpy": "2.5.1",
    "opencolorio": "2.5.2",
    "opencv-python-headless": "4.13.0.92",
    "pillow": "12.3.0",
    "pydantic": "2.13.4",
    "python-multipart": "0.0.32",
    "scenedetect-headless": "0.7.1",
    "scipy": "1.18.0",
    "transformers": "5.14.1",
    "torchvision": (
        "0.24.1+rocm7.2.1"
        if os.name == "nt"
        else (
            "0.24.1+d801a34"
            if torch.__version__ == AMD_DEMO_EXPECTED_RADEON_CLOUD_TORCH_VERSION
            else "0.24.0+rocm7.2.1.gitb919bd0c"
        )
    ),
    "uvicorn": "0.51.0",
}
AMD_FULL_REQUIREMENTS_FILENAME = (
    "requirements-amd-rocm-windows-7.2.1.txt"
    if os.name == "nt"
    else (
        "requirements-amd-rocm-linux-radeon-cloud-7.2.1.txt"
        if torch.__version__ == AMD_DEMO_EXPECTED_RADEON_CLOUD_TORCH_VERSION
        else "requirements-amd-rocm-linux-7.2.1.txt"
    )
)
AMD_FULL_SEMANTIC_TARGETS = (
    "sky",
    "vegetation",
    "water",
    "mountain",
    "rock",
    "cliff",
    "land",
    "sand",
    "snow",
    "road",
    "building",
)
AMD_FULL_DEPTH_TARGETS = ("depth_near", "depth_mid", "depth_far")


class AmdVlmProbeOutput(StrictEvaluationModel):
    scene_summary: str = Field(min_length=1, max_length=600)
    lighting: str = Field(min_length=1, max_length=200)
    light_direction: Literal["front", "back", "side", "diffuse", "mixed"]
    risks: list[str] = Field(min_length=1, max_length=5)
    grading_cautions: list[str] = Field(min_length=1, max_length=5)


class AmdPrecisionGateBinding(StrictEvaluationModel):
    report_path: str
    report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["passed"]
    expected_runtime: Literal["rocm"]
    device_name: str
    torch_version: str
    hip_version: str
    repeats: int = Field(ge=3)
    peak_accelerator_memory_mb: int = Field(gt=0)
    master_passed: bool
    preview_passed: bool
    determinism_passed: bool


class AmdAiStageEvidence(StrictEvaluationModel):
    stage: Literal["clip_scene", "semantic_masks", "depth_masks"]
    model_id: str
    model_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    checkpoint_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    checkpoint_hash_kind: Literal["colorgraph.torch-state-dict/v1"]
    representative_frame_count: int = Field(gt=0)
    representative_frame_set_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    observation_count: int = Field(gt=0)
    observation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    torch_stages: list[TorchStageEvidence] = Field(min_length=1)


class AmdOllamaProbeEvidence(StrictEvaluationModel):
    provider_id: str
    model_id: Literal["colorgraph-qwen3.5:9b"]
    model_revision: str
    request_id: str
    request_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    representative_frame_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    output: AmdVlmProbeOutput
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider_audit_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    hardware: ProviderHardwareEvidence
    backend: OllamaBackendEvidence


class AmdDemoBenchmarkBinding(StrictEvaluationModel):
    audit_report_path: str
    audit_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    raw_report_path: str
    raw_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["passed"]
    required_case_keys: list[str]
    gate_passed: bool


class AmdFinalRenderEvidence(StrictEvaluationModel):
    output_path: str
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_bytes: int = Field(gt=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    fps: float = Field(gt=0)
    duration_seconds: float = Field(gt=0)
    frame_count: int = Field(gt=0)
    codec: str
    pixel_format: str
    bit_depth: Literal[10]
    encoder: Literal["hevc_amf", "hevc_vaapi"]
    processing_fps: float = Field(gt=0)
    elapsed_seconds: float = Field(gt=0)
    compute_precision: Literal["fp32"]
    meets_master_precision: bool
    encoder_hardware_accelerated: bool
    encoder_available_verified: bool
    accelerator: BenchmarkRenderAcceleratorEvidence
    quality_report_path: str
    quality_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    quality_score: int = Field(ge=0, le=100)
    hard_quality_checks_passed: bool
    mask_frames_decoded: int = Field(ge=0)
    mask_transition_samples: int = Field(ge=0)
    mask_temporal_observations: int = Field(ge=0)
    sky_mask_samples: int = Field(ge=0)
    sky_boundary_samples: int = Field(ge=0)
    sky_banding_samples: int = Field(ge=0)


class AmdFullImplementationEvidence(StrictEvaluationModel):
    package_version: str
    runtime_packages: dict[str, str]
    amd_requirements_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    runner_source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    torch_evidence_source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    ollama_evidence_source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider_source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    amd_benchmark_source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    renderer_source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    aces2_gpu_source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    mask_resolver_source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    quality_analyzer_source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class AmdPipelineCheck(StrictEvaluationModel):
    check_id: str
    passed: Literal[True]
    detail: str


class AmdRepresentativeFrameEvidence(StrictEvaluationModel):
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class AmdFullPipelineReport(StrictEvaluationModel):
    schema_version: Literal["colorgraph.amd-full-pipeline/v1"] = AMD_FULL_PIPELINE_VERSION
    created_at: datetime
    status: Literal["passed"]
    gate_passed: Literal[True]
    task_ids: list[Literal["CG-COLOR-003", "CG-BENCH-001"]]
    project_id: str
    source_path: str
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    graph_path: str
    graph_file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    graph_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    representative_frames: list[AmdRepresentativeFrameEvidence] = Field(min_length=1)
    report_sha256_sidecar_path: str
    hardware: DeviceInfo
    amd_driver: AmdDriverEvidence
    precision: AmdPrecisionGateBinding
    ai_stages: list[AmdAiStageEvidence] = Field(min_length=3, max_length=3)
    stage_releases: list[StageReleaseEvidence] = Field(min_length=3)
    ollama: AmdOllamaProbeEvidence
    demo_benchmark: AmdDemoBenchmarkBinding
    final_render: AmdFinalRenderEvidence
    implementation: AmdFullImplementationEvidence
    checks: list[AmdPipelineCheck]
    gpu_compute_boundaries: list[str]
    cpu_media_boundaries: list[str]
    notes: list[str]


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def _require_supported_amd_runtime(
    backend: TorchComputeBackend,
    driver: AmdDriverEvidence,
) -> DeviceInfo:
    info = backend.info
    operating_system = platform.system()
    failures: list[str] = []
    if sys.version_info[:2] != (3, 12):
        failures.append(f"python={sys.version_info.major}.{sys.version_info.minor}, expected=3.12")
    if info.runtime != "rocm":
        failures.append(f"runtime={info.runtime}")
    if info.vendor.casefold() != "amd":
        failures.append(f"vendor={info.vendor}")
    if not amd_device_is_supported(
        info.name,
        operating_system=operating_system,
        architecture=info.architecture,
        total_memory_mb=info.total_memory_mb,
        compute_units=info.compute_units,
    ):
        failures.append(f"unsupported_device={info.name}")
    expected_torch = (
        [
            AMD_DEMO_EXPECTED_LINUX_TORCH_VERSION,
            AMD_DEMO_EXPECTED_RADEON_CLOUD_TORCH_VERSION,
        ]
        if operating_system == "Linux"
        else AMD_DEMO_EXPECTED_TORCH_VERSION
    )
    if not amd_torch_runtime_is_supported(info.torch_version, operating_system):
        failures.append(f"torch={info.torch_version}, expected={expected_torch}")
    observed_hip = str(torch.version.hip) if torch.version.hip else ""
    expected_hip = (
        f"{AMD_DEMO_EXPECTED_LINUX_HIP_PREFIX}*"
        if operating_system == "Linux"
        else AMD_DEMO_EXPECTED_HIP_VERSION
    )
    if not amd_hip_runtime_is_supported(observed_hip, operating_system):
        failures.append(f"hip={observed_hip or 'empty'}, expected={expected_hip}")
    if not driver.version:
        failures.append("AMD driver version is unavailable")
    if failures:
        raise RuntimeError(
            "full AMD pipeline requires a supported AMD Radeon/ROCm host: " + "; ".join(failures)
        )
    return info


def _require_runtime_package_versions() -> dict[str, str]:
    observed: dict[str, str] = {}
    failures: list[str] = []
    for distribution, expected in AMD_FULL_EXPECTED_RUNTIME_PACKAGES.items():
        try:
            version = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            failures.append(f"{distribution}=missing, expected={expected}")
            continue
        observed[distribution] = version
        if version != expected:
            failures.append(f"{distribution}={version}, expected={expected}")
    if failures:
        raise RuntimeError(
            "AMD full-pipeline runtime dependency freeze failed: " + "; ".join(failures)
        )
    return observed


def _bind_precision_report(
    path: str | Path,
    *,
    hardware: DeviceInfo,
) -> AmdPrecisionGateBinding:
    report_path = Path(path).resolve()
    report = PrecisionGateReport.model_validate_json(report_path.read_text(encoding="utf-8"))
    hip_version = str(torch.version.hip) if torch.version.hip else ""
    failures: list[str] = []
    if report.status != "passed":
        failures.append(f"status={report.status}")
    if report.expected_runtime != "rocm":
        failures.append(f"expected_runtime={report.expected_runtime}")
    if report.hardware.runtime != "rocm":
        failures.append(f"hardware.runtime={report.hardware.runtime}")
    if report.hardware.vendor.casefold() != "amd":
        failures.append(f"hardware.vendor={report.hardware.vendor}")
    if report.hardware.name != hardware.name:
        failures.append(f"hardware.name={report.hardware.name!r} != active {hardware.name!r}")
    if report.hip_version != hip_version or not report.hip_version:
        failures.append(f"hip_version={report.hip_version!r} != active {hip_version!r}")
    if report.torch_version != hardware.torch_version:
        failures.append(
            f"torch_version={report.torch_version!r} != active {hardware.torch_version!r}"
        )
    if report.determinism.repeats < 3:
        failures.append(f"determinism.repeats={report.determinism.repeats}")
    if report.peak_accelerator_memory_mb <= 0:
        failures.append("peak accelerator memory is empty")
    if not (report.master.passed and report.preview.passed and report.determinism.passed):
        failures.append("one or more precision sub-gates failed")
    if failures:
        raise RuntimeError("ROCm precision report binding failed: " + "; ".join(failures))
    return AmdPrecisionGateBinding(
        report_path=str(report_path),
        report_sha256=_file_sha256(report_path),
        status="passed",
        expected_runtime="rocm",
        device_name=report.hardware.name,
        torch_version=report.torch_version,
        hip_version=report.hip_version,
        repeats=report.determinism.repeats,
        peak_accelerator_memory_mb=report.peak_accelerator_memory_mb,
        master_passed=report.master.passed,
        preview_passed=report.preview.passed,
        determinism_passed=report.determinism.passed,
    )


def _resolve_representative_frames(
    project: ProjectPaths,
    graph: GradeGraph,
) -> list[Path]:
    resolved: list[Path] = []
    for shot in sorted(graph.shots, key=lambda item: item.index):
        if not shot.representative_frame:
            raise RuntimeError(f"shot {shot.id} lacks a representative frame")
        recorded = Path(shot.representative_frame)
        candidates = (
            [recorded]
            if recorded.is_absolute()
            else [
                project.root / recorded,
                project.frames_dir / recorded,
                project.frames_dir / recorded.name,
            ]
        )
        portable_name = PureWindowsPath(shot.representative_frame).name
        if portable_name:
            portable_candidate = project.frames_dir / portable_name
            if portable_candidate not in candidates:
                candidates.append(portable_candidate)
        match = next((candidate.resolve() for candidate in candidates if candidate.is_file()), None)
        if match is None:
            raise RuntimeError(
                f"representative frame for shot {shot.id} is unavailable: {recorded}"
            )
        if match not in resolved:
            resolved.append(match)
    if not resolved:
        raise RuntimeError("project graph does not contain representative frames")
    return resolved


def _representative_frame_evidence(
    frames: list[Path],
) -> list[AmdRepresentativeFrameEvidence]:
    return [
        AmdRepresentativeFrameEvidence(
            path=str(frame),
            sha256=_file_sha256(frame),
        )
        for frame in frames
    ]


def _require_inputs_unchanged(
    *,
    source_path: Path,
    source_sha256: str,
    graph_path: Path,
    graph_file_sha256: str,
    representative_frames: list[AmdRepresentativeFrameEvidence],
) -> None:
    failures: list[str] = []
    if _file_sha256(source_path) != source_sha256:
        failures.append("source video changed during the full pipeline")
    if _file_sha256(graph_path) != graph_file_sha256:
        failures.append("grade graph changed during the full pipeline")
    for frame in representative_frames:
        path = Path(frame.path)
        if not path.is_file() or _file_sha256(path) != frame.sha256:
            failures.append(f"representative frame changed: {frame.path}")
    if failures:
        raise RuntimeError("AMD full-pipeline frozen input binding failed: " + "; ".join(failures))


def _prediction_summary(prediction: MaskPrediction) -> dict[str, JsonValue]:
    mask = np.asarray(prediction.mask, dtype="<f4")
    return {
        "target": prediction.target,
        "confidence": float(prediction.confidence),
        "score_semantics": prediction.score_semantics,
        "shape": [int(value) for value in mask.shape],
        "minimum": float(mask.min()),
        "maximum": float(mask.max()),
        "mean": float(mask.mean()),
        "mask_sha256": hashlib.sha256(mask.tobytes()).hexdigest(),
        "metadata_sha256": _canonical_sha256(prediction.metadata),
    }


def _require_stage_collection(
    evidence: list[TorchStageEvidence],
    *,
    required_stage_names: set[str],
    expected_model_id: str,
) -> None:
    observed = {item.stage for item in evidence}
    missing = required_stage_names - observed
    if missing:
        raise RuntimeError(f"AI stage evidence is missing: {sorted(missing)}")
    for item in evidence:
        if item.model_id != expected_model_id:
            raise RuntimeError(
                f"AI stage {item.stage!r} used model {item.model_id!r}; "
                f"expected {expected_model_id!r}"
            )
        require_amd_rocm_stage_evidence(item)


def _require_pinned_model_identity(
    records: list[dict[str, object]],
    *,
    stage: str,
    model_id: str,
    model_revision: str,
    checkpoint_sha256: str,
) -> None:
    if not records:
        raise RuntimeError(f"{stage} did not emit model identity records")
    required = {
        "model_id": model_id,
        "model_revision": model_revision,
        "checkpoint_sha256": checkpoint_sha256,
        "checkpoint_hash_kind": AMD_FULL_CHECKPOINT_HASH_KIND,
    }
    failures: list[str] = []
    for key, expected in required.items():
        observed = {str(record.get(key)) for record in records if record.get(key) is not None}
        if observed != {expected}:
            failures.append(f"{key}={sorted(observed)!r}, expected={expected!r}")
    if failures:
        raise RuntimeError(
            f"{stage} model identity differs from the frozen checkpoint: " + "; ".join(failures)
        )


def _run_local_ai_stages(
    backend: TorchComputeBackend,
    representative_frames: list[Path],
    *,
    representative_frame_set_sha256: str,
) -> tuple[list[AmdAiStageEvidence], list[StageReleaseEvidence]]:
    clear_inference_caches()
    backend.empty_cache()
    backend.synchronize()
    stage_results: list[AmdAiStageEvidence] = []
    releases: list[StageReleaseEvidence] = []

    scene = LocalSceneAnalyzer(
        backend,
        model_id=AMD_FULL_CLIP_MODEL_ID,
        model_revision=AMD_FULL_CLIP_MODEL_REVISION,
        local_files_only=True,
    )
    scene.reset_inference_evidence()
    scene_observations = []
    for frame in representative_frames:
        observation = scene.analyze(frame).model_dump(mode="json")
        scene_observations.append(observation)
    _require_pinned_model_identity(
        scene_observations,
        stage="clip_scene",
        model_id=AMD_FULL_CLIP_MODEL_ID,
        model_revision=AMD_FULL_CLIP_MODEL_REVISION,
        checkpoint_sha256=AMD_FULL_CLIP_CHECKPOINT_SHA256,
    )
    clip_evidence = list(scene.inference_evidence)
    _require_stage_collection(
        clip_evidence,
        required_stage_names={"clip_image_embedding", "clip_text_embedding"},
        expected_model_id=AMD_FULL_CLIP_MODEL_ID,
    )
    stage_results.append(
        AmdAiStageEvidence(
            stage="clip_scene",
            model_id=AMD_FULL_CLIP_MODEL_ID,
            model_revision=AMD_FULL_CLIP_MODEL_REVISION,
            checkpoint_sha256=AMD_FULL_CLIP_CHECKPOINT_SHA256,
            checkpoint_hash_kind=AMD_FULL_CHECKPOINT_HASH_KIND,
            representative_frame_count=len(representative_frames),
            representative_frame_set_sha256=representative_frame_set_sha256,
            observation_count=len(scene_observations),
            observation_sha256=_canonical_sha256(scene_observations),
            torch_stages=clip_evidence,
        )
    )
    releases.append(release_pytorch_stage(backend, transition="clip-to-semantic"))

    semantic = SemanticMaskProvider(
        backend,
        model_id=AMD_FULL_SEMANTIC_MODEL_ID,
        model_revision=AMD_FULL_SEMANTIC_MODEL_REVISION,
        local_files_only=True,
    )
    semantic_targets = [
        target for target in AMD_FULL_SEMANTIC_TARGETS if target in semantic.supported_targets
    ]
    if not semantic_targets:
        raise RuntimeError("semantic provider does not expose any required target")
    semantic_observations: list[dict[str, JsonValue]] = []
    semantic_identities: list[dict[str, object]] = []
    semantic_evidence: list[TorchStageEvidence] = []
    for frame in representative_frames:
        with Image.open(frame) as image:
            predictions = semantic.predict_many(image, semantic_targets)
        semantic_observations.extend(
            _prediction_summary(predictions[target]) for target in semantic_targets
        )
        semantic_identities.extend(
            {
                "model_id": semantic.model_id,
                **predictions[target].metadata,
            }
            for target in semantic_targets
        )
        if semantic.last_inference_evidence is None:
            raise RuntimeError("semantic provider did not emit torch stage evidence")
        semantic_evidence.append(semantic.last_inference_evidence)
    _require_stage_collection(
        semantic_evidence,
        required_stage_names={"semantic_segmentation"},
        expected_model_id=AMD_FULL_SEMANTIC_MODEL_ID,
    )
    _require_pinned_model_identity(
        semantic_identities,
        stage="semantic_masks",
        model_id=AMD_FULL_SEMANTIC_MODEL_ID,
        model_revision=AMD_FULL_SEMANTIC_MODEL_REVISION,
        checkpoint_sha256=AMD_FULL_SEMANTIC_CHECKPOINT_SHA256,
    )
    stage_results.append(
        AmdAiStageEvidence(
            stage="semantic_masks",
            model_id=AMD_FULL_SEMANTIC_MODEL_ID,
            model_revision=AMD_FULL_SEMANTIC_MODEL_REVISION,
            checkpoint_sha256=AMD_FULL_SEMANTIC_CHECKPOINT_SHA256,
            checkpoint_hash_kind=AMD_FULL_CHECKPOINT_HASH_KIND,
            representative_frame_count=len(representative_frames),
            representative_frame_set_sha256=representative_frame_set_sha256,
            observation_count=len(semantic_observations),
            observation_sha256=_canonical_sha256(semantic_observations),
            torch_stages=semantic_evidence,
        )
    )
    releases.append(release_pytorch_stage(backend, transition="semantic-to-depth"))

    depth = DepthMaskProvider(
        backend,
        model_id=AMD_FULL_DEPTH_MODEL_ID,
        model_revision=AMD_FULL_DEPTH_MODEL_REVISION,
        local_files_only=True,
    )
    depth_observations: list[dict[str, JsonValue]] = []
    depth_identities: list[dict[str, object]] = []
    depth_evidence: list[TorchStageEvidence] = []
    for frame_index, frame in enumerate(representative_frames):
        depth.reset_shot(f"amd-probe-{frame_index:03d}")
        with Image.open(frame) as image:
            predictions = depth.predict_many(image, list(AMD_FULL_DEPTH_TARGETS))
        depth_observations.extend(
            _prediction_summary(predictions[target]) for target in AMD_FULL_DEPTH_TARGETS
        )
        depth_identities.extend(
            {
                "model_id": depth.model_id,
                **predictions[target].metadata,
            }
            for target in AMD_FULL_DEPTH_TARGETS
        )
        if depth.last_inference_evidence is None:
            raise RuntimeError("depth provider did not emit torch stage evidence")
        depth_evidence.append(depth.last_inference_evidence)
    _require_stage_collection(
        depth_evidence,
        required_stage_names={"depth_estimation"},
        expected_model_id=AMD_FULL_DEPTH_MODEL_ID,
    )
    _require_pinned_model_identity(
        depth_identities,
        stage="depth_masks",
        model_id=AMD_FULL_DEPTH_MODEL_ID,
        model_revision=AMD_FULL_DEPTH_MODEL_REVISION,
        checkpoint_sha256=AMD_FULL_DEPTH_CHECKPOINT_SHA256,
    )
    stage_results.append(
        AmdAiStageEvidence(
            stage="depth_masks",
            model_id=AMD_FULL_DEPTH_MODEL_ID,
            model_revision=AMD_FULL_DEPTH_MODEL_REVISION,
            checkpoint_sha256=AMD_FULL_DEPTH_CHECKPOINT_SHA256,
            checkpoint_hash_kind=AMD_FULL_CHECKPOINT_HASH_KIND,
            representative_frame_count=len(representative_frames),
            representative_frame_set_sha256=representative_frame_set_sha256,
            observation_count=len(depth_observations),
            observation_sha256=_canonical_sha256(depth_observations),
            torch_stages=depth_evidence,
        )
    )
    releases.append(release_pytorch_stage(backend, transition="analysis-to-ollama"))
    return stage_results, releases


def _require_ollama_configuration() -> ProviderCapabilities:
    failures: list[str] = []
    if not settings.enable_ollama_creative_provider:
        failures.append("COLORGRAPH_ENABLE_OLLAMA_CREATIVE_PROVIDER is false")
    if settings.ollama_creative_model != AMD_FULL_OLLAMA_MODEL:
        failures.append(f"model={settings.ollama_creative_model!r}")
    if settings.ollama_creative_model_digest != AMD_FULL_OLLAMA_MODEL_DIGEST:
        failures.append("model digest differs from the frozen Qwen3.5-9B digest")
    if settings.ollama_creative_quantization != AMD_FULL_OLLAMA_QUANTIZATION:
        failures.append(f"quantization={settings.ollama_creative_quantization!r}")
    if not settings.ollama_creative_require_gpu:
        failures.append("GPU residency is not required")
    if settings.ollama_creative_min_gpu_offload_ratio < AMD_FULL_OLLAMA_MINIMUM_OFFLOAD_RATIO:
        failures.append(
            f"minimum GPU offload ratio is below {AMD_FULL_OLLAMA_MINIMUM_OFFLOAD_RATIO}"
        )
    if not settings.ollama_creative_unload_after_request:
        failures.append("post-request VRAM release verification is disabled")
    if not settings.ollama_creative_image_input:
        failures.append("image input is disabled")
    if not settings.ollama_creative_strict_structured_output:
        failures.append("strict structured output is disabled")
    if settings.ollama_creative_max_context_tokens < AMD_FULL_OLLAMA_MINIMUM_CONTEXT:
        failures.append(f"configured context is below {AMD_FULL_OLLAMA_MINIMUM_CONTEXT} tokens")
    if settings.ollama_creative_max_images < 1:
        failures.append("configured image limit is below one")
    if failures:
        raise RuntimeError("AMD Ollama VLM configuration is incomplete: " + "; ".join(failures))
    return ProviderCapabilities(
        image_input=True,
        strict_structured_output=True,
        maximum_context_tokens=settings.ollama_creative_max_context_tokens,
        maximum_images=settings.ollama_creative_max_images,
        batch_requests=False,
        audio_input=False,
    )


async def _run_ollama_probe_async(
    representative_frame: Path,
    *,
    source_sha256: str,
    graph_sha256: str,
    ollama_server_log: str | Path | None,
) -> AmdOllamaProbeEvidence:
    capabilities = _require_ollama_configuration()
    provider = configured_ollama_provider(
        settings,
        capabilities=capabilities,
    )
    image_bytes = representative_frame.read_bytes()
    image_sha256 = hashlib.sha256(image_bytes).hexdigest()
    request_id = f"amd-vlm-{source_sha256[:16]}-{image_sha256[:16]}"
    request = CreativeModelRequest(
        role=CreativeRole.DIRECTOR,
        prompt=(
            "Analyze the supplied landscape frame as a visual-understanding hardware "
            "probe. Return only the requested JSON. Describe the scene and lighting, "
            "choose one light_direction enum, and list concrete clipping, saturation, "
            "haze, temporal, or masking risks plus grading cautions. Do not propose "
            "an Agent plan and do not invent objects that are not visible."
        ),
        prompt_version="colorgraph.amd-vlm-probe/v1",
        schema_version="colorgraph.amd-vlm-probe-output/v1",
        output_model=AmdVlmProbeOutput,
        input_asset_digests=(source_sha256, graph_sha256, image_sha256),
        images=(
            ProviderImage(
                asset_id=representative_frame.name,
                sha256=image_sha256,
                media_type="image/jpeg",
                content=image_bytes,
                detail="high",
            ),
        ),
        max_output_tokens=512,
        estimated_input_tokens=1_500,
        request_id=request_id,
    )
    runtime = CreativeProviderRuntime(
        {role: provider for role in CreativeRole},
        policy=RuntimePolicy(
            timeout_seconds=900,
            maximum_retries=0,
            maximum_concurrency=1,
            requests_per_minute=60,
        ),
        budget=RuntimeBudget(
            maximum_provider_attempts=1,
            maximum_input_tokens=capabilities.maximum_context_tokens,
            maximum_output_tokens=512,
            maximum_cost_usd=0,
        ),
        cache=ProviderResponseCache(),
    )
    await provider.release()
    cursor = begin_ollama_backend_evidence(ollama_server_log)
    try:
        result = await runtime.run(request)
        backend_evidence = capture_ollama_backend_evidence(
            cursor,
            expected_library="ROCm",
        )
    finally:
        await runtime.release()

    hardware = result.audit.hardware_evidence
    if hardware is None:
        raise RuntimeError("Ollama response did not carry hardware evidence")
    hardware_failures: list[str] = []
    if hardware.model_name != AMD_FULL_OLLAMA_MODEL:
        hardware_failures.append(f"model={hardware.model_name}")
    if hardware.model_digest != AMD_FULL_OLLAMA_MODEL_DIGEST:
        hardware_failures.append("digest mismatch")
    if hardware.quantization_level != AMD_FULL_OLLAMA_QUANTIZATION:
        hardware_failures.append(f"quantization={hardware.quantization_level}")
    if not hardware.gpu_verified:
        hardware_failures.append("GPU residency is unverified")
    if hardware.gpu_offload_ratio < AMD_FULL_OLLAMA_MINIMUM_OFFLOAD_RATIO:
        hardware_failures.append(f"gpu_offload_ratio={hardware.gpu_offload_ratio}")
    if not hardware.vram_release_verified:
        hardware_failures.append("VRAM release is unverified")
    if backend_evidence.matching_scheduler_lines != 1:
        hardware_failures.append(
            "fresh log range contains an ambiguous number of GPU scheduler lines: "
            f"{backend_evidence.matching_scheduler_lines}"
        )
    if hardware_failures:
        raise RuntimeError("Ollama AMD hardware evidence failed: " + "; ".join(hardware_failures))

    output_payload = result.output.model_dump(mode="json")
    audit_payload = result.audit.model_dump(mode="json")
    return AmdOllamaProbeEvidence(
        provider_id=result.audit.provider_id,
        model_id=AMD_FULL_OLLAMA_MODEL,
        model_revision=result.audit.model_revision,
        request_id=request_id,
        request_digest=result.audit.request_digest,
        representative_frame_sha256=image_sha256,
        output=result.output,
        output_sha256=_canonical_sha256(output_payload),
        provider_audit_sha256=_canonical_sha256(audit_payload),
        hardware=hardware,
        backend=backend_evidence,
    )


def _run_ollama_probe(
    representative_frame: Path,
    *,
    source_sha256: str,
    graph_sha256: str,
    ollama_server_log: str | Path | None,
) -> AmdOllamaProbeEvidence:
    return asyncio.run(
        _run_ollama_probe_async(
            representative_frame,
            source_sha256=source_sha256,
            graph_sha256=graph_sha256,
            ollama_server_log=ollama_server_log,
        )
    )


def _bind_demo_benchmark(
    report: AmdDemoBenchmarkReport,
    *,
    report_path: Path,
    report_sha256: str,
) -> AmdDemoBenchmarkBinding:
    if not report.gate_passed or report.status != "passed":
        raise RuntimeError("AMD Demo benchmark did not pass: " + ", ".join(report.blockers))
    if _file_sha256(report_path) != report_sha256:
        raise RuntimeError("AMD Demo benchmark audit hash changed after generation")
    raw_path = Path(report.benchmark_report_path).resolve()
    if _file_sha256(raw_path) != report.benchmark_report_sha256:
        raise RuntimeError("raw AMD benchmark hash changed after audit")
    return AmdDemoBenchmarkBinding(
        audit_report_path=str(report_path),
        audit_report_sha256=report_sha256,
        raw_report_path=str(raw_path),
        raw_report_sha256=report.benchmark_report_sha256,
        status="passed",
        required_case_keys=list(report.required_case_keys),
        gate_passed=True,
    )


def _quality_evidence_count(
    values: dict[str, object],
    key: str,
) -> int:
    raw_value = values.get(key, 0)
    if isinstance(raw_value, bool):
        raise RuntimeError(f"mask QA evidence {key} must be an integer count")
    try:
        numeric = float(raw_value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"mask QA evidence {key} must be an integer count") from exc
    if not np.isfinite(numeric) or numeric < 0 or numeric != round(numeric):
        raise RuntimeError(f"mask QA evidence {key} is invalid: {raw_value!r}")
    return int(numeric)


def _require_mask_quality_evidence(
    quality: object,
    graph: GradeGraph,
) -> dict[str, int]:
    masks = list(getattr(graph, "masks", []))
    empty = {
        "mask_frames_decoded": 0,
        "mask_transition_samples": 0,
        "mask_temporal_observations": 0,
        "sky_mask_samples": 0,
        "sky_boundary_samples": 0,
        "sky_banding_samples": 0,
    }
    if not masks:
        return empty

    raw_metrics = getattr(quality, "metrics", None)
    if not isinstance(raw_metrics, dict):
        raise RuntimeError("final Main10 mask QA report has no metric evidence")
    counts = {
        key: _quality_evidence_count(raw_metrics, key)
        for key in (
            "mask_frames_decoded",
            "mask_transition_samples",
            "sky_mask_samples",
            "sky_boundary_samples",
            "sky_banding_samples",
        )
    }
    temporal = getattr(quality, "temporal_evidence", None)
    counts["mask_temporal_observations"] = _quality_evidence_count(
        {
            "mask_temporal_observations": (
                getattr(temporal, "mask_observations", 0) if temporal is not None else 0
            )
        },
        "mask_temporal_observations",
    )

    required = [
        "mask_frames_decoded",
        "mask_transition_samples",
        "mask_temporal_observations",
    ]
    if any(getattr(asset, "target", None) == "sky" for asset in masks):
        required.extend(
            [
                "sky_mask_samples",
                "sky_boundary_samples",
                "sky_banding_samples",
            ]
        )
    missing = [key for key in required if counts[key] <= 0]
    if missing:
        detail = ", ".join(f"{key}={counts[key]}" for key in missing)
        raise RuntimeError("final Main10 render lacks decoded mask QA evidence: " + detail)
    return counts


def _render_final_master(
    backend: TorchComputeBackend,
    *,
    source_path: Path,
    graph: GradeGraph,
    destination: Path,
    batch_size: int,
) -> AmdFinalRenderEvidence:
    expected_encoder = "hevc_amf" if os.name == "nt" else "hevc_vaapi"
    renderer = VideoRenderer(backend)
    result = renderer.render(
        source_path,
        destination,
        graph,
        batch_size=batch_size,
        bit_depth=10,
        include_audio=True,
        verify_mask_storage=True,
        require_hardware_encoder=True,
    )
    require_amd_gpu_render(result)
    rendered = probe_media(destination)
    failures: list[str] = []
    if result.encoder != expected_encoder:
        failures.append(f"encoder={result.encoder}")
    if rendered.codec.casefold() not in {"hevc", "h265"}:
        failures.append(f"codec={rendered.codec}")
    if rendered.bit_depth != 10:
        failures.append(f"bit_depth={rendered.bit_depth}")
    if result.frame_count != graph.media.frame_count:
        failures.append(f"frame_count={result.frame_count} != source={graph.media.frame_count}")
    if not result.meets_master_precision:
        failures.append("master precision budget was not met")
    if failures:
        raise RuntimeError("final Main10 render gate failed: " + "; ".join(failures))

    quality = analyze_video_quality(
        source_path,
        destination,
        graph=graph,
        expected_frame_count=result.frame_count,
    )
    quality_path = destination.with_suffix(".quality.json")
    _atomic_write(quality_path, quality.model_dump_json(indent=2))
    if not quality.hard_checks_passed:
        raise RuntimeError(
            "final Main10 render failed hard quality checks: "
            + ", ".join(quality.technical_hard_failures)
        )
    mask_quality = _require_mask_quality_evidence(quality, graph)
    return AmdFinalRenderEvidence(
        output_path=str(destination),
        output_sha256=_file_sha256(destination),
        output_bytes=destination.stat().st_size,
        width=rendered.width,
        height=rendered.height,
        fps=rendered.fps,
        duration_seconds=rendered.duration_seconds,
        frame_count=result.frame_count,
        codec=rendered.codec,
        pixel_format=rendered.pixel_format or "unreported",
        bit_depth=10,
        encoder=result.encoder,
        processing_fps=result.processing_fps,
        elapsed_seconds=result.elapsed_seconds,
        compute_precision="fp32",
        meets_master_precision=result.meets_master_precision,
        encoder_hardware_accelerated=result.encoder_hardware_accelerated,
        encoder_available_verified=result.encoder_available_verified,
        accelerator=BenchmarkRenderAcceleratorEvidence.model_validate(
            asdict(result.accelerator_evidence)
        ),
        quality_report_path=str(quality_path),
        quality_report_sha256=_file_sha256(quality_path),
        quality_score=quality.score,
        hard_quality_checks_passed=quality.hard_checks_passed,
        **mask_quality,
    )


def _validate_source_manifest(
    source_manifest_path: Path,
    source_path: Path,
) -> AmdDemoSourceManifest:
    manifest = AmdDemoSourceManifest.model_validate_json(
        source_manifest_path.read_text(encoding="utf-8")
    )
    actual_sha256 = _file_sha256(source_path)
    media = probe_media(source_path)
    failures: list[str] = []
    if actual_sha256 != manifest.clip.sha256:
        failures.append("source SHA-256 differs from manifest")
    if (media.width, media.height) != (1920, 1080):
        failures.append(f"source resolution is {media.width}x{media.height}")
    if not 12 <= media.duration_seconds <= 25:
        failures.append(f"source duration is {media.duration_seconds:.6f}s")
    if media.frame_count != manifest.clip.frame_count:
        failures.append(f"source frame count {media.frame_count} != {manifest.clip.frame_count}")
    if not (
        manifest.rights.redistribution_allowed
        and manifest.rights.adaptation_allowed
        and manifest.validation.full_decode_passed
    ):
        failures.append("manifest rights or full-decode validation is incomplete")
    if failures:
        raise RuntimeError("AMD full-pipeline source gate failed: " + "; ".join(failures))
    return manifest


def run_amd_full_pipeline(
    *,
    project_id: str,
    source_manifest: str | Path,
    precision_report: str | Path,
    output_dir: str | Path,
    output: str | Path,
    batch_size: int = 4,
    ollama_server_log: str | Path | None = None,
) -> tuple[AmdFullPipelineReport, str]:
    """Run the fail-closed AMD AI, grading, AMF, QA, and benchmark acceptance path."""

    if batch_size < 1:
        raise ValueError("batch size must be positive")
    output_root = Path(output_dir).resolve()
    output_path = Path(output).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    raw_benchmark_path = output_root / "amd-demo-raw-benchmark.json"
    benchmark_audit_path = output_root / "amd-demo-benchmark-audit.json"
    final_master_path = output_root / "final-master-main10.mp4"
    reserved_paths = {
        output_path,
        raw_benchmark_path,
        benchmark_audit_path,
        final_master_path,
    }
    if len(reserved_paths) != 4:
        raise ValueError("full-pipeline output paths must be distinct")

    backend = TorchComputeBackend("rocm")
    driver = capture_amd_driver_evidence()
    hardware = _require_supported_amd_runtime(backend, driver)
    runtime_packages = _require_runtime_package_versions()
    precision = _bind_precision_report(precision_report, hardware=hardware)

    store = ProjectStore()
    project = store.get(project_id)
    source_path = store.resolve_source(project)
    graph = store.load_graph(project_id)
    source_manifest_path = Path(source_manifest).resolve()
    _validate_source_manifest(source_manifest_path, source_path)
    source_sha256 = _file_sha256(source_path)
    graph_file_sha256 = _file_sha256(project.graph_path)
    graph_sha256 = graph_digest(graph)
    representative_frames = _resolve_representative_frames(project, graph)
    representative_evidence = _representative_frame_evidence(representative_frames)
    representative_frame_set_sha256 = _canonical_sha256(
        [item.model_dump(mode="json") for item in representative_evidence]
    )

    ai_stages, stage_releases = _run_local_ai_stages(
        backend,
        representative_frames,
        representative_frame_set_sha256=representative_frame_set_sha256,
    )
    ollama = _run_ollama_probe(
        representative_frames[0],
        source_sha256=source_sha256,
        graph_sha256=graph_sha256,
        ollama_server_log=ollama_server_log,
    )
    stage_releases.append(release_pytorch_stage(backend, transition="ollama-to-render"))

    benchmark_report, benchmark_sha256 = run_amd_demo_benchmark(
        project_id=project_id,
        source_manifest=source_manifest_path,
        benchmark_output=raw_benchmark_path,
        output=benchmark_audit_path,
        batch_size=batch_size,
    )
    demo_binding = _bind_demo_benchmark(
        benchmark_report,
        report_path=benchmark_audit_path,
        report_sha256=benchmark_sha256,
    )
    if benchmark_report.hardware.get("name") != hardware.name:
        raise RuntimeError("AMD Demo benchmark device differs from the AI/precision device")
    if benchmark_report.amd_driver.version != driver.version:
        raise RuntimeError("AMD Demo benchmark driver differs from the full-pipeline preflight")

    final_render = _render_final_master(
        backend,
        source_path=source_path,
        graph=graph,
        destination=final_master_path,
        batch_size=batch_size,
    )
    _require_inputs_unchanged(
        source_path=source_path,
        source_sha256=source_sha256,
        graph_path=project.graph_path,
        graph_file_sha256=graph_file_sha256,
        representative_frames=representative_evidence,
    )
    sidecar_path = output_path.with_name(f"{output_path.name}.sha256")
    amd_requirements_path = Path(__file__).resolve().parents[2] / AMD_FULL_REQUIREMENTS_FILENAME
    implementation = AmdFullImplementationEvidence(
        package_version=importlib.metadata.version("colorgraph-backend"),
        runtime_packages=runtime_packages,
        amd_requirements_sha256=_file_sha256(amd_requirements_path),
        runner_source_sha256=_file_sha256(Path(__file__).resolve()),
        torch_evidence_source_sha256=_file_sha256(Path(device_evidence_module.__file__).resolve()),
        ollama_evidence_source_sha256=_file_sha256(Path(ollama_evidence_module.__file__).resolve()),
        provider_source_sha256=_file_sha256(Path(creative_provider_module.__file__).resolve()),
        amd_benchmark_source_sha256=_file_sha256(
            Path(amd_demo_benchmark_module.__file__).resolve()
        ),
        renderer_source_sha256=_file_sha256(Path(video_module.__file__).resolve()),
        aces2_gpu_source_sha256=_file_sha256(Path(aces2_gpu_module.__file__).resolve()),
        mask_resolver_source_sha256=_file_sha256(Path(masks_module.__file__).resolve()),
        quality_analyzer_source_sha256=_file_sha256(
            Path(quality_analyzer_module.__file__).resolve()
        ),
    )
    report = AmdFullPipelineReport(
        created_at=datetime.now(UTC),
        status="passed",
        gate_passed=True,
        task_ids=list(AMD_FULL_PIPELINE_TASK_IDS),
        project_id=project_id,
        source_path=str(source_path),
        source_sha256=source_sha256,
        graph_path=str(project.graph_path),
        graph_file_sha256=graph_file_sha256,
        graph_digest=graph_sha256,
        representative_frames=representative_evidence,
        report_sha256_sidecar_path=str(sidecar_path),
        hardware=hardware,
        amd_driver=driver,
        precision=precision,
        ai_stages=ai_stages,
        stage_releases=stage_releases,
        ollama=ollama,
        demo_benchmark=demo_binding,
        final_render=final_render,
        implementation=implementation,
        checks=[
            AmdPipelineCheck(
                check_id="supported_rocm_host",
                passed=True,
                detail="Supported AMD Radeon, HIP runtime, and machine-probed driver.",
            ),
            AmdPipelineCheck(
                check_id="frozen_inputs",
                passed=True,
                detail=(
                    "Source video, grade graph, and representative-frame hashes "
                    "remained unchanged throughout the run."
                ),
            ),
            AmdPipelineCheck(
                check_id="precision_gate",
                passed=True,
                detail="Three-run ROCm FP32 precision and determinism report is bound.",
            ),
            AmdPipelineCheck(
                check_id="local_ai_gpu",
                passed=True,
                detail="CLIP, semantic segmentation, and depth emitted AMD tensor evidence.",
            ),
            AmdPipelineCheck(
                check_id="ollama_rocm",
                passed=True,
                detail=(
                    "Pinned Qwen3.5-9B Q4_K_M was GPU-resident, Ollama logged "
                    "library=ROCm, and its VRAM was released before rendering."
                ),
            ),
            AmdPipelineCheck(
                check_id="amd_demo_benchmark",
                passed=True,
                detail="Both fresh 1080p Demo rows passed with per-batch GPU and AMF evidence.",
            ),
            AmdPipelineCheck(
                check_id="final_main10_render",
                passed=True,
                detail="Full source rendered in FP32 through native GPU ACES2 and HEVC AMF.",
            ),
            AmdPipelineCheck(
                check_id="hard_quality",
                passed=True,
                detail=(
                    "The final Main10 output passed hard technical quality checks "
                    "with decoded FFV1 mask, temporal, sky-boundary, and sky-banding "
                    "observations."
                ),
            ),
        ],
        gpu_compute_boundaries=[
            "CLIP image/text inference on PyTorch ROCm",
            "SegFormer semantic inference on PyTorch ROCm",
            "Depth Anything V2 inference on PyTorch ROCm",
            "Qwen3.5-9B Q4_K_M vision inference through Ollama ROCm",
            "grade graph math, LUTs, masks, and native ACES 2 output transform on PyTorch ROCm",
            "H.264/HEVC encoding through AMD AMF",
        ],
        cpu_media_boundaries=[
            "FFmpeg demux and RGB48 decode feed the GPU renderer through a host pipe",
            "one final GPU-to-host transfer feeds each rendered batch to FFmpeg/AMF",
            "audio muxing, container metadata, file hashing, and report serialization",
            "OpenCV/FFmpeg technical quality measurement after render",
        ],
        notes=[
            "This gate covers the narrowed 12-25 second 1080p AMD submission path.",
            "It does not revive deferred model comparisons, Agent tasks, or human Gold work.",
            (
                "The CLIP, semantic, depth, and VLM calls are representative-frame "
                "device proofs; the final grade consumes the separately frozen, "
                "provenance-bound FFV1 mask assets rather than regenerating them."
            ),
            "CPU media I/O is disclosed and is not presented as GPU AI or GPU grading compute.",
        ],
    )
    _atomic_write(output_path, report.model_dump_json(indent=2))
    digest = _file_sha256(output_path)
    _atomic_write(sidecar_path, f"{digest}  {output_path.name}\n")
    return report, digest
