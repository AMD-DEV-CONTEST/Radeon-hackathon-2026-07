from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_ROOT / "scripts"))

from corpus.programbench.cleanroom_image_hydration_record import (  # noqa: E402
    make_cleanroom_image_hydration_record,
    write_cleanroom_image_hydration_record,
)
from corpus.programbench.cleanroom_image_scan_record import (  # noqa: E402
    make_cleanroom_image_scan_record,
    write_cleanroom_image_scan_record,
)
from corpus.programbench.cleanroom_image_scan_triage import (  # noqa: E402
    EXPECTED_DIGEST,
    EXPECTED_IMAGE,
    CleanroomImageScanTriageConfig,
    CleanroomImageScanTriageStatus,
    ProgramBenchCleanroomImageScanTriage,
)
from corpus.programbench.cleanroom_image_scan_triage_record import (
    verify_cleanroom_image_scan_triage_record,  # noqa: E402
)


def _findings() -> list[dict[str, str]]:
    return [
        {
            "id": "CVE-CRIT-FIX",
            "package": "stdlib",
            "installed_version": "v1.21.0",
            "fixed_version": "1.21.11",
            "severity": "critical",
            "target": "usr/local/go/bin/go",
        },
        {
            "id": "CVE-CRIT-NOFIX",
            "package": "linux-libc-dev",
            "installed_version": "5.15.0",
            "fixed_version": "",
            "severity": "critical",
            "target": "image.tar (ubuntu 22.04)",
        },
        {
            "id": "CVE-HIGH-FIX",
            "package": "openssl",
            "installed_version": "3.0",
            "fixed_version": "3.0.2",
            "severity": "high",
            "target": "image.tar (ubuntu 22.04)",
        },
        {
            "id": "CVE-MED",
            "package": "appdep",
            "installed_version": "1.0",
            "fixed_version": "",
            "severity": "medium",
            "target": "opt/app/node_modules/appdep",
        },
    ]


def _write_scan(
    tmp_path: Path,
    *,
    findings=None,
    expected_digest: str = EXPECTED_DIGEST,
    status: str = "CLEANROOM_IMAGE_SCAN_FAILED",
) -> Path:
    findings = _findings() if findings is None else findings
    summary = {
        "critical": 0,
        "high": 0,
        "medium": 0,
        "low": 0,
        "unknown": 0,
        "total": len(findings),
    }
    for item in findings:
        summary[item.get("severity", "unknown").lower()] += 1
    record = make_cleanroom_image_scan_record(
        status=status,
        import_record="import.json",
        image_reference=EXPECTED_IMAGE,
        artifact_path="T:/determinex_artifacts/quarantine/programbench/test.tar",
        expected_digest=expected_digest,
        observed_digest=expected_digest,
        file_sha256="sha256:file",
        file_size=123,
        scanner="trivy",
        scanner_version="Version: 0.test",
        findings_summary=summary,
        normalized_findings=findings,
        reasons=["critical_or_high_findings_present"] if status.endswith("FAILED") else [],
        cache_ready=False,
        executable=False,
    )
    return write_cleanroom_image_scan_record(record, tmp_path / "scan")


def _write_hydration(tmp_path: Path, *, expected_digest: str = EXPECTED_DIGEST) -> Path:
    record = make_cleanroom_image_hydration_record(
        status="CLEANROOM_IMAGE_SCAN_FAILED",
        admission_record="admission.json",
        image_reference=EXPECTED_IMAGE,
        source_url_or_registry=f"docker.io/programbench/doxygen@{expected_digest}",
        expected_digest=expected_digest,
        observed_digest=expected_digest,
        target={"tool": "doxygen__doxygen.966d98e"},
        hydration_statuses=["CLEANROOM_IMAGE_SCAN_FAILED", "CLEANROOM_IMAGE_POLICY_BLOCKED"],
        scan_result={"scanner": "trivy", "critical": 1, "high": 1, "policy": "block"},
        policy_result="CLEANROOM_IMAGE_POLICY_BLOCKED",
        reasons=["security_scan_policy_failed"],
        cache_ready=False,
        executable=False,
    )
    return write_cleanroom_image_hydration_record(record, tmp_path / "hydration")


def _triage(tmp_path: Path):
    return ProgramBenchCleanroomImageScanTriage(
        CleanroomImageScanTriageConfig(root=tmp_path, output_dir=tmp_path / "triage")
    )


def test_missing_scan_evidence_blocks_triage(tmp_path):
    hydration = _write_hydration(tmp_path)
    result = _triage(tmp_path).triage(tmp_path / "missing.json", hydration)

    assert (
        result["record"]["status"]
        == CleanroomImageScanTriageStatus.CLEANROOM_IMAGE_SCAN_TRIAGE_BLOCKED_NO_SCAN.value
    )


def test_missing_hydration_policy_block_evidence_blocks_triage(tmp_path):
    scan = _write_scan(tmp_path)
    result = _triage(tmp_path).triage(scan, tmp_path / "missing.json")

    assert (
        result["record"]["status"]
        == CleanroomImageScanTriageStatus.CLEANROOM_IMAGE_SCAN_TRIAGE_BLOCKED_NO_HYDRATION.value
    )


def test_wrong_artifact_digest_blocks_triage(tmp_path):
    scan = _write_scan(tmp_path, expected_digest="sha256:bad")
    hydration = _write_hydration(tmp_path)
    result = _triage(tmp_path).triage(scan, hydration)

    assert (
        result["record"]["status"]
        == CleanroomImageScanTriageStatus.CLEANROOM_IMAGE_SCAN_TRIAGE_BLOCKED_DIGEST_MISMATCH.value
    )


def test_empty_findings_with_failed_scan_produces_data_insufficient(tmp_path):
    scan = _write_scan(tmp_path, findings=[])
    hydration = _write_hydration(tmp_path)
    result = _triage(tmp_path).triage(scan, hydration)

    assert (
        result["record"]["status"]
        == CleanroomImageScanTriageStatus.CLEANROOM_IMAGE_SCAN_DATA_INSUFFICIENT.value
    )
    assert result["record"]["recommendation"] == "SCAN_DATA_INSUFFICIENT"


def test_critical_and_high_findings_are_grouped_deterministically(tmp_path):
    scan = _write_scan(tmp_path)
    hydration = _write_hydration(tmp_path)
    result = _triage(tmp_path).triage(scan, hydration)
    groups = result["record"]["grouped_findings"]

    assert [group["severity"] for group in groups[:3]] == ["critical", "critical", "high"]
    assert groups == sorted(
        groups,
        key=lambda item: (
            {"critical": 0, "high": 1, "medium": 2, "low": 3, "unknown": 4}[item["severity"]],
            -item["count"],
            item["package"],
            item["id"],
        ),
    )


def test_fixed_version_availability_is_summarized(tmp_path):
    result = _triage(tmp_path).triage(_write_scan(tmp_path), _write_hydration(tmp_path))
    summary = result["record"]["fixed_version_summary"]

    assert summary["critical_with_fix"] == 1
    assert summary["critical_without_fix"] == 1
    assert summary["high_with_fix"] == 1


def test_no_fixed_version_findings_are_summarized(tmp_path):
    result = _triage(tmp_path).triage(_write_scan(tmp_path), _write_hydration(tmp_path))

    assert result["record"]["fixed_version_summary"]["no_fixed_version_total"] == 2


def test_os_base_packages_classified_separately_from_application_packages(tmp_path):
    result = _triage(tmp_path).triage(_write_scan(tmp_path), _write_hydration(tmp_path))
    summary = result["record"]["category_summary"]

    assert summary["all_findings"]["os_base"] == 2
    assert summary["all_findings"]["language_runtime"] == 1
    assert summary["all_findings"]["application_dependency"] == 1


def test_triage_recommends_remediation_when_critical_high_exceed_policy(tmp_path):
    result = _triage(tmp_path).triage(_write_scan(tmp_path), _write_hydration(tmp_path))

    assert result["record"]["recommendation"] == "REMEDIATE_IMAGE_REQUIRED"
    assert (
        CleanroomImageScanTriageStatus.CLEANROOM_IMAGE_REMEDIATE_REQUIRED.value
        in result["record"]["triage_statuses"]
    )


def test_triage_does_not_suppress_vulnerabilities(tmp_path):
    result = _triage(tmp_path).triage(_write_scan(tmp_path), _write_hydration(tmp_path))

    assert result["record"]["severity_counts"]["total"] == len(_findings())
    assert sum(group["count"] for group in result["record"]["grouped_findings"]) == len(_findings())


def test_triage_does_not_mark_scan_passed(tmp_path):
    result = _triage(tmp_path).triage(_write_scan(tmp_path), _write_hydration(tmp_path))

    assert "CLEANROOM_IMAGE_SCAN_PASSED" not in result["record"]["triage_statuses"]


def test_triage_does_not_mark_cache_ready(tmp_path):
    result = _triage(tmp_path).triage(_write_scan(tmp_path), _write_hydration(tmp_path))

    assert result["record"]["cache_ready"] is False


def test_triage_does_not_mark_executable_true(tmp_path):
    result = _triage(tmp_path).triage(_write_scan(tmp_path), _write_hydration(tmp_path))

    assert result["record"]["executable"] is False


def test_triage_does_not_mark_training_eligible_true(tmp_path):
    result = _triage(tmp_path).triage(_write_scan(tmp_path), _write_hydration(tmp_path))

    assert result["record"]["training_eligible"] is False


def test_signed_triage_record_is_produced(tmp_path):
    result = _triage(tmp_path).triage(_write_scan(tmp_path), _write_hydration(tmp_path))

    assert Path(result["record_path"]).is_file()
    assert verify_cleanroom_image_scan_triage_record(result["record"])
