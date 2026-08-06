from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from colorgraph.cli import build_parser
from colorgraph.evaluation import amd_demo_benchmark
from colorgraph.evaluation.amd_demo_benchmark import (
    AmdDriverEvidence,
    amd_device_is_supported,
    audit_amd_demo_benchmark_file,
)
from colorgraph.evaluation.production_benchmark import (
    BenchmarkRenderAcceleratorEvidence,
    BenchmarkSource,
    ProductionBenchmarkCase,
    summarize_benchmark_report,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_manifest(
    path: Path,
    *,
    source_sha256: str,
    redistribution_allowed: bool = True,
) -> None:
    payload = {
        "schema_version": "colorgraph.amd-demo-source-manifest/v1",
        "task_id": "CG-BENCH-001",
        "status": "ready_for_supported_amd_benchmark",
        "rights": {
            "license": "CC BY-SA 4.0",
            "license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
            "commercial_use_allowed": True,
            "redistribution_allowed": redistribution_allowed,
            "adaptation_allowed": True,
            "share_alike_required": True,
            "attribution": "Test source — CC BY-SA 4.0",
            "adaptation_notice": "12.5 second benchmark excerpt.",
        },
        "clip": {
            "path": "source.mp4",
            "sha256": source_sha256,
            "bytes": 1024,
            "duration_seconds": 12.5,
            "width": 1920,
            "height": 1080,
            "fps": 30.0,
            "frame_count": 375,
            "codec": "h264",
            "pixel_format": "yuv420p",
        },
        "scene_structure": {
            "hard_cut_times_seconds": [4.166667, 8.366667],
            "shot_count": 3,
            "visual_review": {
                "passed": True,
                "contact_sheet_path": "contact-sheet.png",
                "contact_sheet_sha256": "a" * 64,
                "observation": "Two unambiguous hard cuts.",
            },
        },
        "validation": {
            "full_decode_passed": True,
            "decoded_frames": 375,
            "duration_gate_passed": True,
            "resolution_gate_passed": True,
            "redistribution_gate_passed": redistribution_allowed,
            "hard_cut_shot_count_gate_passed": True,
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _completed_case(
    tmp_path: Path,
    variant: str,
    *,
    runtime: str,
    vendor: str,
    device_name: str,
    hip_version: str | None,
) -> ProductionBenchmarkCase:
    output = tmp_path / f"{variant}.mp4"
    output.write_bytes(f"{variant}-output".encode())
    now = datetime.now(UTC)
    quality_path = tmp_path / "current_combined.quality.json"
    quality_checked = variant == "current_combined"
    if quality_checked:
        quality_path.write_text('{"hard_checks_passed":true}', encoding="utf-8")
    return ProductionBenchmarkCase(
        case_key=f"{variant}:proxy_1080p:warm",
        input_digest="a" * 64,
        status="completed",
        variant=variant,
        profile="proxy_1080p",
        thermal_state="warm",
        graph_digest=("b" if variant == "no_mask" else "c") * 64,
        verify_mask_storage=False,
        output_path=str(output),
        output_sha256=_sha256(output),
        output_bytes=output.stat().st_size,
        output_width=1920,
        output_height=1080,
        output_fps=30.0,
        output_duration_seconds=12.5,
        output_codec="h264",
        output_pixel_format="yuv420p",
        frame_count=375,
        elapsed_seconds=10.0,
        processing_fps=37.5,
        p95_frame_latency_ms=30.0,
        batch_latency_sample_count=94,
        peak_vram_allocated_mb=512.0,
        peak_vram_reserved_mb=640.0,
        encoder="h264_amf",
        encoder_hardware_accelerated=True,
        encoder_available_verified=True,
        render_accelerator_evidence=BenchmarkRenderAcceleratorEvidence(
            schema_version="colorgraph.render-accelerator-evidence/v1",
            runtime=runtime,
            vendor=vendor,
            device_name=device_name,
            torch_device="cuda:0",
            hip_version=hip_version,
            batch_count=94,
            all_batches_accelerator_verified=runtime == "rocm",
            peak_allocated_memory_mb=512.0,
            peak_reserved_memory_mb=640.0,
            batch_evidence_sha256="f" * 64,
        ),
        bit_depth=8,
        compute_precision="fp32",
        precision_budget="colorgraph.precision/preview-v1",
        meets_master_precision=False,
        maximum_timestamp_error_seconds=0.0,
        quality_checked=quality_checked,
        quality_score=96 if quality_checked else None,
        hard_quality_checks_passed=True if quality_checked else None,
        quality_report_path=str(quality_path) if quality_checked else None,
        quality_report_sha256=_sha256(quality_path) if quality_checked else None,
        started_at=now,
        completed_at=now,
    )


def _write_raw_report(
    tmp_path: Path,
    *,
    runtime: str = "rocm",
    vendor: str = "AMD",
    device_name: str = "AMD Radeon RX 7900 XTX",
    hip_version: str | None = "7.2.1",
    operating_system: str = "Windows-11",
) -> tuple[Path, str]:
    source_sha256 = "d" * 64
    source = BenchmarkSource(
        project_id="amd-demo",
        path=str(tmp_path / "source.mp4"),
        size_bytes=1024,
        modified_time_ns=1,
        sha256=source_sha256,
        width=1920,
        height=1080,
        fps=30.0,
        duration_seconds=12.5,
        frame_count=375,
        codec="h264",
        pixel_format="yuv420p",
        real_long_media_qualified=False,
        qualification_reasons=["duration is below 120 seconds"],
    )
    cases = [
        _completed_case(
            tmp_path,
            "no_mask",
            runtime=runtime,
            vendor=vendor,
            device_name=device_name,
            hip_version=hip_version,
        ),
        _completed_case(
            tmp_path,
            "current_combined",
            runtime=runtime,
            vendor=vendor,
            device_name=device_name,
            hip_version=hip_version,
        ),
    ]
    report = summarize_benchmark_report(
        created_at=datetime.now(UTC),
        run_id="amd-demo-run",
        source=source,
        source_graph_digest="e" * 64,
        render_start_seconds=0,
        render_end_seconds=12.5,
        hardware={
            "available": True,
            "runtime": runtime,
            "vendor": vendor,
            "name": device_name,
        },
        software={
            "operating_system": operating_system,
            "python_version": "3.12.10 (test fixture)",
            "torch_version": "2.9.1+rocm7.2.1" if hip_version else "2.12.1+cu130",
            "hip_version": hip_version,
        },
        requested_variants=("no_mask", "current_combined"),
        requested_profiles=("proxy_1080p",),
        requested_thermal_states=("warm",),
        cases=cases,
        quality_checks_required=True,
    )
    raw_path = tmp_path / "raw-benchmark.json"
    raw_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return raw_path, source_sha256


def _audit(
    tmp_path: Path,
    raw_path: Path,
    source_sha256: str,
    *,
    redistribution_allowed: bool = True,
    driver_version: str | None = "32.0.24002.1001",
    output_name: str = "audit.json",
):
    manifest_path = tmp_path / f"{output_name}.manifest.json"
    _write_manifest(
        manifest_path,
        source_sha256=source_sha256,
        redistribution_allowed=redistribution_allowed,
    )
    output = tmp_path / output_name
    report, digest = audit_amd_demo_benchmark_file(
        source_manifest=manifest_path,
        benchmark_report=raw_path,
        output=output,
        driver_evidence=AmdDriverEvidence(
            version=driver_version,
            source="test_fixture",
        ),
    )
    return report, digest, output


def test_amd_demo_audit_passes_exact_supported_rocm_gate(tmp_path: Path) -> None:
    raw_path, source_sha256 = _write_raw_report(tmp_path)

    report, digest, output = _audit(tmp_path, raw_path, source_sha256)

    assert report.status == "passed"
    assert report.gate_passed is True
    assert report.blockers == []
    assert len(report.cases) == 2
    assert all(case.output_hash_verified for case in report.cases)
    assert digest == _sha256(output)
    sidecar = Path(report.audit_sha256_sidecar_path)
    assert sidecar.read_text(encoding="utf-8") == f"{digest}  {output.name}\n"


def test_cuda_report_is_engineering_preflight_only(tmp_path: Path) -> None:
    raw_path, source_sha256 = _write_raw_report(
        tmp_path,
        runtime="cuda",
        vendor="NVIDIA",
        device_name="NVIDIA GeForce RTX 5060 Ti",
        hip_version=None,
    )

    report, _, _ = _audit(
        tmp_path,
        raw_path,
        source_sha256,
        driver_version=None,
    )

    assert report.status == "engineering_preflight_only"
    assert report.gate_passed is False
    assert {
        "runtime_rocm",
        "vendor_amd",
        "supported_radeon",
        "hip_runtime",
        "amd_driver",
    } <= set(report.blockers)


def test_cuda_checkpoint_can_only_be_engineering_preflight(tmp_path: Path) -> None:
    raw_path, source_sha256 = _write_raw_report(
        tmp_path,
        runtime="cuda",
        vendor="NVIDIA",
        device_name="NVIDIA GeForce RTX 5060 Ti",
        hip_version=None,
    )
    payload = json.loads(raw_path.read_text(encoding="utf-8"))
    payload["cases"][0]["resumed_from_checkpoint"] = True
    payload["cases"][0]["checkpoint_reuse_reason"] = "exact_input_digest"
    raw_path.write_text(json.dumps(payload), encoding="utf-8")

    report, _, _ = _audit(
        tmp_path,
        raw_path,
        source_sha256,
        driver_version=None,
    )

    assert report.status == "engineering_preflight_only"
    assert "fresh_measurements" in report.blockers


def test_supported_amd_identity_rejects_unfrozen_torch_and_hip(
    tmp_path: Path,
) -> None:
    raw_path, source_sha256 = _write_raw_report(tmp_path)
    payload = json.loads(raw_path.read_text(encoding="utf-8"))
    payload["software"]["python_version"] = "3.13.0"
    payload["software"]["torch_version"] = "2.10.0+rocm7.3"
    payload["software"]["hip_version"] = "7.3"
    raw_path.write_text(json.dumps(payload), encoding="utf-8")

    report, _, _ = _audit(tmp_path, raw_path, source_sha256)

    assert report.status == "failed"
    assert {"python_runtime", "torch_runtime", "hip_runtime"} <= set(report.blockers)


def test_source_rights_failure_cannot_be_relabelled_as_preflight(tmp_path: Path) -> None:
    raw_path, source_sha256 = _write_raw_report(tmp_path)

    report, _, _ = _audit(
        tmp_path,
        raw_path,
        source_sha256,
        redistribution_allowed=False,
    )

    assert report.status == "failed"
    assert report.gate_passed is False
    assert "source_manifest" in report.blockers


def test_output_tamper_fails_hash_gate(tmp_path: Path) -> None:
    raw_path, source_sha256 = _write_raw_report(tmp_path)
    (tmp_path / "current_combined.mp4").write_bytes(b"tampered")

    report, _, _ = _audit(tmp_path, raw_path, source_sha256)

    assert report.status == "failed"
    assert "output_integrity" in report.blockers
    current = next(case for case in report.cases if case.variant == "current_combined")
    assert current.output_hash_verified is False


def test_missing_per_batch_gpu_evidence_fails_amd_gate(tmp_path: Path) -> None:
    raw_path, source_sha256 = _write_raw_report(tmp_path)
    payload = json.loads(raw_path.read_text(encoding="utf-8"))
    payload["cases"][0]["render_accelerator_evidence"] = None
    raw_path.write_text(json.dumps(payload), encoding="utf-8")

    report, _, _ = _audit(tmp_path, raw_path, source_sha256)

    assert report.status == "failed"
    assert "amd_gpu_execution" in report.blockers


def test_duplicate_case_cannot_satisfy_exact_coverage(tmp_path: Path) -> None:
    raw_path, source_sha256 = _write_raw_report(tmp_path)
    payload = json.loads(raw_path.read_text(encoding="utf-8"))
    payload["cases"].append(payload["cases"][0])
    raw_path.write_text(json.dumps(payload), encoding="utf-8")

    report, _, _ = _audit(tmp_path, raw_path, source_sha256)

    assert report.status == "failed"
    assert "case_coverage" in report.blockers


def test_checkpoint_measurements_cannot_satisfy_amd_gate(tmp_path: Path) -> None:
    raw_path, source_sha256 = _write_raw_report(tmp_path)
    payload = json.loads(raw_path.read_text(encoding="utf-8"))
    payload["cases"][0]["measurement_origin"] = "compatible_checkpoint"
    payload["cases"][0]["resumed_from_checkpoint"] = True
    payload["cases"][0]["resumed_from_input_digest"] = "a" * 64
    payload["cases"][0]["checkpoint_reuse_reason"] = "exact_input_digest"
    raw_path.write_text(json.dumps(payload), encoding="utf-8")

    report, _, _ = _audit(tmp_path, raw_path, source_sha256)

    assert report.status == "failed"
    assert "fresh_measurements" in report.blockers


def test_current_runtime_gate_rejects_cuda_before_render(monkeypatch) -> None:
    fake_info = SimpleNamespace(
        runtime="cuda",
        vendor="NVIDIA",
        name="NVIDIA GeForce RTX 5060 Ti",
    )
    monkeypatch.setattr(
        amd_demo_benchmark,
        "TorchComputeBackend",
        lambda _preference: SimpleNamespace(info=fake_info),
    )
    monkeypatch.setattr(amd_demo_benchmark.torch.version, "hip", None)

    with pytest.raises(RuntimeError, match="runtime=cuda"):
        amd_demo_benchmark._require_supported_current_amd_runtime(
            AmdDriverEvidence(version=None, source="unavailable")
        )


def test_final_runner_forces_fresh_exact_two_row_measurement(
    monkeypatch,
    tmp_path: Path,
) -> None:
    manifest = SimpleNamespace()
    driver = AmdDriverEvidence(
        version="32.0.24002.1001",
        source="test_fixture",
    )
    raw_calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        amd_demo_benchmark,
        "_load_source_manifest",
        lambda _path: manifest,
    )
    monkeypatch.setattr(
        amd_demo_benchmark,
        "_validate_project_source",
        lambda _project_id, _manifest: None,
    )
    monkeypatch.setattr(
        amd_demo_benchmark,
        "capture_amd_driver_evidence",
        lambda: driver,
    )
    monkeypatch.setattr(
        amd_demo_benchmark,
        "_require_supported_current_amd_runtime",
        lambda _driver: None,
    )
    monkeypatch.setattr(
        amd_demo_benchmark,
        "run_production_benchmark",
        lambda **kwargs: raw_calls.append(kwargs),
    )
    sentinel = (SimpleNamespace(gate_passed=True), "f" * 64)
    monkeypatch.setattr(
        amd_demo_benchmark,
        "audit_amd_demo_benchmark_file",
        lambda **_kwargs: sentinel,
    )

    result = amd_demo_benchmark.run_amd_demo_benchmark(
        project_id="project-id",
        source_manifest=tmp_path / "manifest.json",
        benchmark_output=tmp_path / "raw.json",
        output=tmp_path / "audit.json",
    )

    assert result == sentinel
    assert len(raw_calls) == 1
    assert raw_calls[0]["variants"] == ("no_mask", "current_combined")
    assert raw_calls[0]["profiles"] == ("proxy_1080p",)
    assert raw_calls[0]["thermal_states"] == ("warm",)
    assert raw_calls[0]["hash_source"] is True
    assert raw_calls[0]["quality_checks"] is True
    assert raw_calls[0]["resume"] is False
    assert raw_calls[0]["require_hardware_encoder"] is True


def test_supported_radeon_policy_is_exact_and_trademark_tolerant() -> None:
    assert amd_device_is_supported("AMD Radeon(TM) RX 7900 XTX")
    assert amd_device_is_supported("AMD Radeon RX 9070 XT (gfx1201)")
    assert not amd_device_is_supported("AMD Radeon(TM) Graphics")
    assert amd_device_is_supported(
        "AMD Radeon Graphics",
        operating_system="Linux",
        architecture="gfx1100:sramecc-:xnack-",
        total_memory_mb=49_136,
        compute_units=96,
    )
    assert not amd_device_is_supported(
        "AMD Radeon Graphics",
        operating_system="Linux",
        architecture="gfx1100",
        total_memory_mb=24_560,
        compute_units=96,
    )
    assert not amd_device_is_supported("NVIDIA GeForce RTX 5060 Ti")


def test_cli_exposes_run_and_audit_commands() -> None:
    parser = build_parser()
    run = parser.parse_args(
        [
            "amd-demo-benchmark",
            "project-id",
            "--source-manifest",
            "source.json",
            "--benchmark-output",
            "raw.json",
            "--output",
            "audit.json",
        ]
    )
    audit = parser.parse_args(
        [
            "amd-demo-benchmark-audit",
            "--source-manifest",
            "source.json",
            "--benchmark-report",
            "raw.json",
            "--output",
            "audit.json",
        ]
    )

    assert run.handler.__name__ == "_amd_demo_benchmark"
    assert audit.handler.__name__ == "_amd_demo_benchmark_audit"
