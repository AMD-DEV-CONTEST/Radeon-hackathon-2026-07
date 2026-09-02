from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from colorgraph.cli import build_parser
from colorgraph.devices.base import DeviceInfo
from colorgraph.evaluation import amd_full_pipeline
from colorgraph.evaluation.precision_gate import (
    DeterminismComparison,
    PrecisionComparison,
    PrecisionGateReport,
)
from colorgraph.grading.video import RenderAcceleratorEvidence
from colorgraph.vision.base import MaskPrediction


def _device() -> DeviceInfo:
    return DeviceInfo(
        available=True,
        runtime="rocm",
        vendor="AMD",
        name="AMD Radeon RX 7900 XTX",
        index=0,
        total_memory_mb=24_576,
        allocated_memory_mb=0,
        reserved_memory_mb=0,
        torch_version="2.9.1+rocm7.2.1",
        runtime_version="7.2.1",
    )


def _precision_comparison() -> PrecisionComparison:
    return PrecisionComparison(
        reference="cpu",
        candidate="rocm",
        reference_dtype="float32",
        candidate_dtype="float32",
        reference_output_sha256="a" * 64,
        candidate_output_sha256="b" * 64,
        maximum_normalized_channel_error=1e-7,
        p95_normalized_channel_error=1e-8,
        mean_normalized_channel_error=1e-9,
        maximum_delta_e_2000=1e-5,
        p95_delta_e_2000=1e-6,
        mean_delta_e_2000=1e-7,
        channel_error_budget=1e-5,
        delta_e_2000_budget=0.01,
        passed=True,
    )


def _write_precision_report(path: Path, *, runtime: str = "rocm") -> None:
    hardware = _device().model_copy(
        update={
            "runtime": runtime,
            "vendor": "AMD" if runtime == "rocm" else "NVIDIA",
        }
    )
    report = PrecisionGateReport(
        created_at=datetime.now(UTC),
        status="passed",
        expected_runtime=runtime,
        hardware=hardware,
        operating_system="Windows",
        python_version="3.12.10",
        torch_version="2.9.1+rocm7.2.1",
        hip_version="7.2.1" if runtime == "rocm" else None,
        cuda_version=None if runtime == "rocm" else "13.0",
        input_sha256="c" * 64,
        graph_sha256="d" * 64,
        lut_sha256="e" * 64,
        sample_shape=[4, 3, 32, 64],
        timestamps=[0.0, 0.25, 0.5, 0.75],
        cpu_elapsed_ms=10,
        accelerator_elapsed_ms=[2, 2, 2],
        peak_accelerator_memory_mb=128,
        master=_precision_comparison(),
        preview=_precision_comparison(),
        determinism=DeterminismComparison(
            repeats=3,
            output_sha256=["f" * 64] * 3,
            maximum_normalized_channel_drift=0,
            drift_budget=1e-7,
            passed=True,
        ),
    )
    path.write_text(report.model_dump_json(indent=2), encoding="utf-8")


def test_precision_binding_requires_same_active_rocm_device(
    monkeypatch,
    tmp_path: Path,
) -> None:
    report_path = tmp_path / "precision.json"
    _write_precision_report(report_path)
    monkeypatch.setattr(
        amd_full_pipeline,
        "torch",
        SimpleNamespace(version=SimpleNamespace(hip="7.2.1")),
    )

    binding = amd_full_pipeline._bind_precision_report(
        report_path,
        hardware=_device(),
    )

    assert binding.status == "passed"
    assert binding.expected_runtime == "rocm"
    assert binding.repeats == 3
    assert binding.report_sha256 == amd_full_pipeline._file_sha256(report_path)


def test_full_runtime_gate_requires_frozen_rocm_build(monkeypatch) -> None:
    monkeypatch.setattr(amd_full_pipeline.platform, "system", lambda: "Windows")
    monkeypatch.setattr(
        amd_full_pipeline.torch,
        "version",
        SimpleNamespace(hip="7.2.1"),
    )
    driver = amd_full_pipeline.AmdDriverEvidence(
        version="32.0.24002.1024",
        source="test_fixture",
    )

    observed = amd_full_pipeline._require_supported_amd_runtime(
        SimpleNamespace(info=_device()),
        driver,
    )

    assert observed.torch_version == "2.9.1+rocm7.2.1"

    changed = _device().model_copy(update={"torch_version": "2.10.0+rocm7.3"})
    with pytest.raises(RuntimeError, match=r"expected=2.9.1\+rocm7.2.1"):
        amd_full_pipeline._require_supported_amd_runtime(
            SimpleNamespace(info=changed),
            driver,
        )


def test_ollama_gate_freezes_qwen_quantization_and_gpu_policy(monkeypatch) -> None:
    configured = SimpleNamespace(
        enable_ollama_creative_provider=True,
        ollama_creative_model=amd_full_pipeline.AMD_FULL_OLLAMA_MODEL,
        ollama_creative_model_digest=(amd_full_pipeline.AMD_FULL_OLLAMA_MODEL_DIGEST),
        ollama_creative_quantization="Q4_K_M",
        ollama_creative_require_gpu=True,
        ollama_creative_min_gpu_offload_ratio=0.99,
        ollama_creative_unload_after_request=True,
        ollama_creative_image_input=True,
        ollama_creative_strict_structured_output=True,
        ollama_creative_max_context_tokens=8192,
        ollama_creative_max_images=1,
    )
    monkeypatch.setattr(amd_full_pipeline, "settings", configured)

    capabilities = amd_full_pipeline._require_ollama_configuration()

    assert capabilities.image_input is True
    assert capabilities.strict_structured_output is True
    assert capabilities.maximum_context_tokens == 8192

    configured.ollama_creative_quantization = "Q8_0"
    with pytest.raises(RuntimeError, match="quantization"):
        amd_full_pipeline._require_ollama_configuration()


def test_mask_observation_hash_binds_float_pixels_and_metadata() -> None:
    first = MaskPrediction(
        target="sky",
        mask=np.asarray([[0.0, 0.5], [0.75, 1.0]], dtype=np.float32),
        confidence=0.8,
        metadata={"model": "segformer", "revision": "abc"},
    )
    changed = MaskPrediction(
        target="sky",
        mask=np.asarray([[0.0, 0.5], [0.70, 1.0]], dtype=np.float32),
        confidence=0.8,
        metadata={"model": "segformer", "revision": "abc"},
    )

    first_summary = amd_full_pipeline._prediction_summary(first)
    changed_summary = amd_full_pipeline._prediction_summary(changed)

    assert first_summary["mask_sha256"] != changed_summary["mask_sha256"]
    assert first_summary["metadata_sha256"] == changed_summary["metadata_sha256"]


def test_ai_model_identity_gate_rejects_checkpoint_drift() -> None:
    record = {
        "model_id": amd_full_pipeline.AMD_FULL_SEMANTIC_MODEL_ID,
        "model_revision": amd_full_pipeline.AMD_FULL_SEMANTIC_MODEL_REVISION,
        "checkpoint_sha256": (amd_full_pipeline.AMD_FULL_SEMANTIC_CHECKPOINT_SHA256),
        "checkpoint_hash_kind": amd_full_pipeline.AMD_FULL_CHECKPOINT_HASH_KIND,
    }

    amd_full_pipeline._require_pinned_model_identity(
        [record],
        stage="semantic_masks",
        model_id=amd_full_pipeline.AMD_FULL_SEMANTIC_MODEL_ID,
        model_revision=amd_full_pipeline.AMD_FULL_SEMANTIC_MODEL_REVISION,
        checkpoint_sha256=(amd_full_pipeline.AMD_FULL_SEMANTIC_CHECKPOINT_SHA256),
    )

    changed = {
        **record,
        "checkpoint_sha256": "0" * 64,
    }
    with pytest.raises(RuntimeError, match="frozen checkpoint"):
        amd_full_pipeline._require_pinned_model_identity(
            [changed],
            stage="semantic_masks",
            model_id=amd_full_pipeline.AMD_FULL_SEMANTIC_MODEL_ID,
            model_revision=amd_full_pipeline.AMD_FULL_SEMANTIC_MODEL_REVISION,
            checkpoint_sha256=(amd_full_pipeline.AMD_FULL_SEMANTIC_CHECKPOINT_SHA256),
        )


def test_runtime_package_gate_rejects_version_drift(monkeypatch) -> None:
    versions = dict(amd_full_pipeline.AMD_FULL_EXPECTED_RUNTIME_PACKAGES)
    monkeypatch.setattr(
        amd_full_pipeline.importlib.metadata,
        "version",
        lambda distribution: versions[distribution],
    )

    assert amd_full_pipeline._require_runtime_package_versions() == versions

    versions["transformers"] = "99.0.0"
    with pytest.raises(RuntimeError, match="transformers=99.0.0"):
        amd_full_pipeline._require_runtime_package_versions()


def test_runtime_package_gate_matches_amd_requirements_file() -> None:
    requirements = (
        Path(amd_full_pipeline.__file__).resolve().parents[2]
        / amd_full_pipeline.AMD_FULL_REQUIREMENTS_FILENAME
    ).read_text(encoding="utf-8")
    for distribution, version in amd_full_pipeline.AMD_FULL_EXPECTED_RUNTIME_PACKAGES.items():
        if distribution == "torchvision":
            assert (
                f"torchvision-{version.replace('+', '%2B')}-" in requirements
                or f"torchvision=={version}" in requirements
            )
        elif distribution == "uvicorn":
            assert f"uvicorn[standard]=={version}" in requirements
        else:
            assert f"{distribution}=={version}" in requirements


def test_full_pipeline_input_binding_detects_mid_run_changes(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.mp4"
    graph = tmp_path / "grade_graph.json"
    frame = tmp_path / "frame.jpg"
    source.write_bytes(b"source")
    graph.write_bytes(b"graph")
    frame.write_bytes(b"frame")
    frame_evidence = amd_full_pipeline._representative_frame_evidence([frame])

    amd_full_pipeline._require_inputs_unchanged(
        source_path=source,
        source_sha256=amd_full_pipeline._file_sha256(source),
        graph_path=graph,
        graph_file_sha256=amd_full_pipeline._file_sha256(graph),
        representative_frames=frame_evidence,
    )

    frame.write_bytes(b"changed")
    with pytest.raises(RuntimeError, match="representative frame changed"):
        amd_full_pipeline._require_inputs_unchanged(
            source_path=source,
            source_sha256=amd_full_pipeline._file_sha256(source),
            graph_path=graph,
            graph_file_sha256=amd_full_pipeline._file_sha256(graph),
            representative_frames=frame_evidence,
        )


def test_representative_frames_rebase_windows_paths_for_linux_package(
    tmp_path: Path,
) -> None:
    frames_dir = tmp_path / "frames"
    frames_dir.mkdir()
    frame = frames_dir / "shot_001.jpg"
    frame.write_bytes(b"frame")
    project = SimpleNamespace(root=tmp_path, frames_dir=frames_dir)
    graph = SimpleNamespace(
        shots=[
            SimpleNamespace(
                id="shot_001",
                index=0,
                representative_frame=(
                    r"C:\frozen\colorgraph\project\frames\shot_001.jpg"
                ),
            )
        ]
    )

    assert amd_full_pipeline._resolve_representative_frames(project, graph) == [
        frame.resolve()
    ]


def test_final_master_gate_requires_main10_amf_and_writes_hashed_quality(
    monkeypatch,
    tmp_path: Path,
) -> None:
    destination = tmp_path / "master.mp4"
    expected_encoder = "hevc_amf" if amd_full_pipeline.os.name == "nt" else "hevc_vaapi"
    accelerator = RenderAcceleratorEvidence(
        schema_version="colorgraph.render-accelerator-evidence/v1",
        runtime="rocm",
        vendor="AMD",
        device_name="AMD Radeon RX 7900 XTX",
        torch_device="cuda:0",
        hip_version="7.2.1",
        batch_count=4,
        all_batches_accelerator_verified=True,
        peak_allocated_memory_mb=512,
        peak_reserved_memory_mb=640,
        batch_evidence_sha256="a" * 64,
    )

    class FakeRenderer:
        def __init__(self, _backend) -> None:
            pass

        def render(self, _source, output, _graph, **kwargs):
            assert kwargs["bit_depth"] == 10
            assert kwargs["require_hardware_encoder"] is True
            Path(output).write_bytes(b"main10-amd-hardware")
            return SimpleNamespace(
                encoder=expected_encoder,
                frame_count=12,
                meets_master_precision=True,
                processing_fps=24.0,
                elapsed_seconds=0.5,
                encoder_hardware_accelerated=True,
                encoder_available_verified=True,
                accelerator_evidence=accelerator,
            )

    quality = SimpleNamespace(
        hard_checks_passed=True,
        technical_hard_failures=[],
        score=98,
        model_dump_json=lambda indent: '{"hard_checks_passed":true}',
    )
    monkeypatch.setattr(amd_full_pipeline, "VideoRenderer", FakeRenderer)
    monkeypatch.setattr(
        amd_full_pipeline,
        "probe_media",
        lambda _path: SimpleNamespace(
            width=1920,
            height=1080,
            fps=24.0,
            duration_seconds=0.5,
            codec="hevc",
            pixel_format="p010le",
            bit_depth=10,
        ),
    )
    monkeypatch.setattr(
        amd_full_pipeline,
        "analyze_video_quality",
        lambda *_args, **_kwargs: quality,
    )

    evidence = amd_full_pipeline._render_final_master(
        SimpleNamespace(),
        source_path=tmp_path / "source.mp4",
        graph=SimpleNamespace(media=SimpleNamespace(frame_count=12)),
        destination=destination,
        batch_size=4,
    )

    assert evidence.encoder == expected_encoder
    assert evidence.bit_depth == 10
    assert evidence.hard_quality_checks_passed is True
    assert evidence.mask_frames_decoded == 0
    assert evidence.mask_temporal_observations == 0
    assert Path(evidence.quality_report_path).is_file()
    assert evidence.output_sha256 == amd_full_pipeline._file_sha256(destination)


def test_final_mask_quality_gate_requires_real_ffv1_observations() -> None:
    quality = SimpleNamespace(
        metrics={
            "mask_frames_decoded": 20.0,
            "mask_transition_samples": 15.0,
            "sky_mask_samples": 4.0,
            "sky_boundary_samples": 4.0,
            "sky_banding_samples": 4.0,
        },
        temporal_evidence=SimpleNamespace(mask_observations=12),
    )
    graph = SimpleNamespace(masks=[SimpleNamespace(id="mask_sky", target="sky")])

    evidence = amd_full_pipeline._require_mask_quality_evidence(
        quality,
        graph,
    )

    assert evidence == {
        "mask_frames_decoded": 20,
        "mask_transition_samples": 15,
        "mask_temporal_observations": 12,
        "sky_mask_samples": 4,
        "sky_boundary_samples": 4,
        "sky_banding_samples": 4,
    }

    quality.metrics["sky_boundary_samples"] = 0.0
    with pytest.raises(RuntimeError, match="sky_boundary_samples=0"):
        amd_full_pipeline._require_mask_quality_evidence(quality, graph)


def test_cli_exposes_full_amd_pipeline_gate() -> None:
    arguments = build_parser().parse_args(
        [
            "amd-full-pipeline",
            "project-id",
            "--source-manifest",
            "manifest.json",
            "--precision-report",
            "precision.json",
            "--output-dir",
            "artifacts",
            "--output",
            "report.json",
        ]
    )

    assert arguments.handler.__name__ == "_amd_full_pipeline"
    assert arguments.batch_size == 4
