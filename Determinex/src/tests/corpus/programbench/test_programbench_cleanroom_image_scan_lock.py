from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_ROOT / "scripts"))

import corpus.programbench.cleanroom_image_scan as scan_module  # noqa: E402
from corpus.programbench.cleanroom_image_import_record import (  # noqa: E402
    make_cleanroom_image_import_record,
    write_cleanroom_image_import_record,
)
from corpus.programbench.cleanroom_image_scan import (  # noqa: E402
    CleanroomImageScanConfig,
    CleanroomImageScanStatus,
    ProgramBenchCleanroomImageScan,
    ScannerResult,
    ScannerSpec,
    normalize_scan_output,
    summarize_findings,
)
from corpus.programbench.cleanroom_image_scan_record import (
    verify_cleanroom_image_scan_record,  # noqa: E402
)

IMAGE = "programbench/doxygen_1776_doxygen.966d98e:task_cleanroom"
DIGEST = "sha256:cc50d0f7e9a1f3f90512e3d4c34781f4686a8fa3774fbff489947ef41bde2e72"


def _artifact(tmp_path: Path) -> Path:
    path = tmp_path / "image.tar"
    path.write_text("image bytes\n", encoding="utf-8")
    return path


def _import_record_path(
    tmp_path: Path,
    *,
    artifact: Path | None = None,
    expected_digest: str = DIGEST,
    observed_digest: str = DIGEST,
) -> Path:
    artifact = artifact or _artifact(tmp_path)
    record = make_cleanroom_image_import_record(
        status="CLEANROOM_IMAGE_IMPORT_SCAN_UNAVAILABLE",
        provenance_record="provenance.json",
        admission_record="admission.json",
        image_reference=IMAGE,
        source_url_or_registry=f"docker.io/programbench/doxygen_1776_doxygen.966d98e@{expected_digest}",
        expected_digest=expected_digest,
        observed_digest=observed_digest,
        target={
            "tool": "doxygen__doxygen.966d98e",
            "candidate_id": "close_lock_v7_doxygen_richgo_20260527",
        },
        import_statuses=[
            "CLEANROOM_IMAGE_IMPORT_SCAN_UNAVAILABLE",
            "CLEANROOM_IMAGE_IMPORT_NOT_EXECUTABLE",
        ],
        artifact_import_path=str(artifact),
        quarantine_path=str(artifact),
        executable=False,
    )
    return write_cleanroom_image_import_record(record, tmp_path / "imports")


def _scanner(
    tmp_path: Path,
    *,
    scanner: ScannerSpec | None = None,
    runner=None,
) -> ProgramBenchCleanroomImageScan:
    return ProgramBenchCleanroomImageScan(
        CleanroomImageScanConfig(
            root=tmp_path,
            output_dir=tmp_path / "scans",
            scanner_override=scanner,
            scanner_runner=runner,
            timeout_seconds=1,
        )
    )


def _trivy_spec() -> ScannerSpec:
    return ScannerSpec(
        "trivy", "Version: 0.test", ["trivy", "image", "--input", "image.tar", "--format", "json"]
    )


def _grype_spec() -> ScannerSpec:
    return ScannerSpec("grype", "0.test", ["grype", "docker-archive:image.tar", "-o", "json"])


def test_missing_import_record_blocks_scan(tmp_path):
    result = _scanner(tmp_path).scan(tmp_path / "missing.json")

    assert (
        result["record"]["status"]
        == CleanroomImageScanStatus.CLEANROOM_IMAGE_SCAN_BLOCKED_NO_IMPORT_RECORD.value
    )


def test_missing_artifact_path_blocks_scan(tmp_path):
    record = _import_record_path(tmp_path, artifact=tmp_path / "missing.tar")
    result = _scanner(tmp_path).scan(record)

    assert (
        result["record"]["status"]
        == CleanroomImageScanStatus.CLEANROOM_IMAGE_SCAN_BLOCKED_MISSING_ARTIFACT.value
    )


def test_digest_mismatch_blocks_scan(tmp_path):
    record = _import_record_path(tmp_path, observed_digest="sha256:" + "0" * 64)
    result = _scanner(tmp_path).scan(record)

    assert (
        result["record"]["status"]
        == CleanroomImageScanStatus.CLEANROOM_IMAGE_SCAN_BLOCKED_DIGEST_MISMATCH.value
    )


def test_no_scanner_available_produces_scan_unavailable(tmp_path):
    # Mock _detect_scanner to return None so the "unavailable" code path is tested
    # deterministically regardless of which scanner tools are installed on the host.
    # (On hosts with docker scout, the real detector returns a spec and the scan times
    # out; this test is specifically about the absent-scanner code path, not the timeout path.)
    from unittest.mock import patch

    record = _import_record_path(tmp_path)
    with patch.object(scan_module, "_detect_scanner", return_value=None):
        result = _scanner(tmp_path).scan(record)

    assert (
        result["record"]["status"]
        == CleanroomImageScanStatus.CLEANROOM_IMAGE_SCAN_UNAVAILABLE.value
    )


def test_scanner_unavailable_keeps_cache_ready_false(tmp_path):
    from unittest.mock import patch

    record = _import_record_path(tmp_path)
    with patch.object(scan_module, "_detect_scanner", return_value=None):
        result = _scanner(tmp_path).scan(record)

    assert result["record"]["cache_ready"] is False


def test_mock_trivy_scan_pass_produces_signed_evidence(tmp_path):
    record = _import_record_path(tmp_path)

    def runner(_scanner, _artifact, _timeout):
        return ScannerResult(0, json.dumps({"Results": []}), "")

    result = _scanner(tmp_path, scanner=_trivy_spec(), runner=runner).scan(record)

    assert result["record"]["status"] == CleanroomImageScanStatus.CLEANROOM_IMAGE_SCAN_PASSED.value
    assert verify_cleanroom_image_scan_record(result["record"])


def test_mock_grype_scan_pass_produces_signed_evidence(tmp_path):
    record = _import_record_path(tmp_path)

    def runner(_scanner, _artifact, _timeout):
        return ScannerResult(0, json.dumps({"matches": []}), "")

    result = _scanner(tmp_path, scanner=_grype_spec(), runner=runner).scan(record)

    assert result["record"]["status"] == CleanroomImageScanStatus.CLEANROOM_IMAGE_SCAN_PASSED.value
    assert verify_cleanroom_image_scan_record(result["record"])


def test_scanner_failure_produces_error(tmp_path):
    record = _import_record_path(tmp_path)

    def runner(_scanner, _artifact, _timeout):
        return ScannerResult(2, "", "scanner failed")

    result = _scanner(tmp_path, scanner=_trivy_spec(), runner=runner).scan(record)

    assert result["record"]["status"] == CleanroomImageScanStatus.CLEANROOM_IMAGE_SCAN_ERROR.value


def test_explicit_scanner_launch_error_produces_error_record(tmp_path):
    record = _import_record_path(tmp_path)
    result = _scanner(
        tmp_path, scanner=ScannerSpec("trivy", "Version: broken", [str(tmp_path / "missing.exe")])
    ).scan(record)

    assert result["record"]["status"] == CleanroomImageScanStatus.CLEANROOM_IMAGE_SCAN_ERROR.value
    assert "scanner_execution_error" in result["record"]["reasons"][0]


def test_auto_detection_skips_unlaunchable_scanner(monkeypatch, tmp_path):
    monkeypatch.setattr(
        scan_module.shutil,
        "which",
        lambda name: str(tmp_path / f"{name}.exe") if name == "trivy" else None,
    )

    def blocked_run(*_args, **_kwargs):
        raise PermissionError("blocked")

    monkeypatch.setattr(scan_module.subprocess, "run", blocked_run)

    assert scan_module._detect_scanner(tmp_path / "image.tar") is None


def test_scanner_timeout_fails_closed(tmp_path):
    record = _import_record_path(tmp_path)

    def runner(_scanner, _artifact, _timeout):
        return ScannerResult(124, "", "timeout", timed_out=True)

    result = _scanner(tmp_path, scanner=_trivy_spec(), runner=runner).scan(record)

    assert result["record"]["status"] == CleanroomImageScanStatus.CLEANROOM_IMAGE_SCAN_TIMEOUT.value


def test_scan_findings_normalize_deterministically():
    raw = json.dumps(
        {
            "Results": [
                {
                    "Target": "layer",
                    "Vulnerabilities": [
                        {"VulnerabilityID": "CVE-B", "PkgName": "z", "Severity": "HIGH"},
                        {"VulnerabilityID": "CVE-A", "PkgName": "a", "Severity": "LOW"},
                    ],
                }
            ]
        }
    )

    normalized = normalize_scan_output("trivy", raw)

    assert [item["id"] for item in normalized] == ["CVE-B", "CVE-A"]
    assert summarize_findings(normalized) == {
        "critical": 0,
        "high": 1,
        "medium": 0,
        "low": 1,
        "unknown": 0,
        "total": 2,
    }


def test_scan_record_includes_artifact_digest_and_scanner_version(tmp_path):
    record = _import_record_path(tmp_path)

    def runner(_scanner, _artifact, _timeout):
        return ScannerResult(0, json.dumps({"Results": []}), "")

    result = _scanner(tmp_path, scanner=_trivy_spec(), runner=runner).scan(record)

    assert result["record"]["expected_digest"] == DIGEST
    assert result["record"]["observed_digest"] == DIGEST
    assert result["record"]["scanner_version"] == "Version: 0.test"


def test_scan_record_marks_not_executable(tmp_path):
    record = _import_record_path(tmp_path)

    def runner(_scanner, _artifact, _timeout):
        return ScannerResult(0, json.dumps({"Results": []}), "")

    result = _scanner(tmp_path, scanner=_trivy_spec(), runner=runner).scan(record)

    assert result["record"]["executable"] is False
    assert (
        CleanroomImageScanStatus.CLEANROOM_IMAGE_NOT_EXECUTABLE.value
        in result["record"]["scan_statuses"]
    )


def test_scan_record_marks_not_training_eligible(tmp_path):
    record = _import_record_path(tmp_path)

    def runner(_scanner, _artifact, _timeout):
        return ScannerResult(0, json.dumps({"Results": []}), "")

    result = _scanner(tmp_path, scanner=_trivy_spec(), runner=runner).scan(record)

    assert result["record"]["training_eligible"] is False
    assert (
        CleanroomImageScanStatus.CLEANROOM_IMAGE_TRAINING_INELIGIBLE.value
        in result["record"]["scan_statuses"]
    )


def test_high_findings_fail_scan(tmp_path):
    record = _import_record_path(tmp_path)

    def runner(_scanner, _artifact, _timeout):
        return ScannerResult(
            0,
            json.dumps(
                {
                    "Results": [
                        {"Vulnerabilities": [{"VulnerabilityID": "CVE-H", "Severity": "HIGH"}]}
                    ]
                }
            ),
            "",
        )

    result = _scanner(tmp_path, scanner=_trivy_spec(), runner=runner).scan(record)

    assert result["record"]["status"] == CleanroomImageScanStatus.CLEANROOM_IMAGE_SCAN_FAILED.value
