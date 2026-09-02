from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_ROOT / "scripts"))

from corpus.programbench.cleanroom_image_scanner_admission import (  # noqa: E402
    CleanroomImageScannerAdmissionConfig,
    CleanroomImageScannerAdmissionStatus,
    CommandResult,
    ProgramBenchCleanroomImageScannerAdmission,
)
from corpus.programbench.cleanroom_image_scanner_admission_record import (
    verify_cleanroom_image_scanner_admission_record,  # noqa: E402
)


def _exe(tmp_path: Path, name: str) -> Path:
    path = tmp_path / name
    path.write_text("binary marker\n", encoding="utf-8")
    return path


def _admitter(tmp_path: Path, runner=None, *, allow_wrappers: bool = False):
    return ProgramBenchCleanroomImageScannerAdmission(
        CleanroomImageScannerAdmissionConfig(
            root=tmp_path,
            output_dir=tmp_path / "admissions",
            command_runner=runner,
            allow_wrappers=allow_wrappers,
        )
    )


def _runner_ok(command: list[str], _timeout: int) -> CommandResult:
    if "--version" in command:
        return CommandResult(0, "Version: 0.test\n", "")
    if "version" in command:
        return CommandResult(0, '{"version":"0.test"}\n', "")
    return CommandResult(0, "docker-archive supported\n", "")


def test_missing_scanner_path_produces_not_found(tmp_path):
    result = _admitter(tmp_path).admit("trivy", tmp_path / "missing.exe")

    assert (
        result["record"]["status"]
        == CleanroomImageScannerAdmissionStatus.CLEANROOM_SCANNER_NOT_FOUND.value
    )


def test_unknown_scanner_name_is_rejected(tmp_path):
    result = _admitter(tmp_path).admit("unknown", _exe(tmp_path, "unknown.exe"))

    assert (
        result["record"]["status"]
        == CleanroomImageScannerAdmissionStatus.CLEANROOM_SCANNER_BLOCKED_UNKNOWN.value
    )


def test_trivy_path_with_valid_version_and_capability_is_admitted(tmp_path):
    result = _admitter(tmp_path, runner=_runner_ok).admit("trivy", _exe(tmp_path, "trivy.exe"))

    assert (
        result["record"]["status"]
        == CleanroomImageScannerAdmissionStatus.CLEANROOM_SCANNER_ADMITTED.value
    )
    assert result["record"]["scanner_name"] == "trivy"
    assert "trivy image --input" in result["record"]["capability"]


def test_grype_path_with_valid_version_and_capability_is_admitted(tmp_path):
    result = _admitter(tmp_path, runner=_runner_ok).admit("grype", _exe(tmp_path, "grype.exe"))

    assert (
        result["record"]["status"]
        == CleanroomImageScannerAdmissionStatus.CLEANROOM_SCANNER_ADMITTED.value
    )
    assert result["record"]["scanner_name"] == "grype"
    assert "docker-archive" in result["record"]["capability"]


def test_docker_scout_admitted_only_when_archive_capability_verified(tmp_path):
    result = _admitter(tmp_path, runner=_runner_ok).admit(
        "docker_scout", _exe(tmp_path, "docker.exe")
    )

    assert (
        result["record"]["status"]
        == CleanroomImageScannerAdmissionStatus.CLEANROOM_SCANNER_ADMITTED.value
    )
    assert result["record"]["scanner_name"] == "docker_scout"


def test_wrapper_path_rejected_unless_allowlisted(tmp_path):
    result = _admitter(tmp_path, runner=_runner_ok).admit("trivy", _exe(tmp_path, "trivy.ps1"))

    assert (
        result["record"]["status"]
        == CleanroomImageScannerAdmissionStatus.CLEANROOM_SCANNER_BLOCKED_WRAPPER.value
    )


def test_allowlisted_wrapper_can_be_admitted(tmp_path):
    result = _admitter(tmp_path, runner=_runner_ok, allow_wrappers=True).admit(
        "trivy", _exe(tmp_path, "trivy.ps1")
    )

    assert (
        result["record"]["status"]
        == CleanroomImageScannerAdmissionStatus.CLEANROOM_SCANNER_ADMITTED.value
    )


def test_scanner_requiring_container_execution_is_rejected(tmp_path):
    def runner(command: list[str], _timeout: int) -> CommandResult:
        if "version" in command:
            return CommandResult(0, "Docker Scout 1.test\n", "")
        return CommandResult(0, "usage without archive support\n", "")

    result = _admitter(tmp_path, runner=runner).admit("docker_scout", _exe(tmp_path, "docker.exe"))

    assert (
        result["record"]["status"]
        == CleanroomImageScannerAdmissionStatus.CLEANROOM_SCANNER_BLOCKED_REQUIRES_EXECUTION.value
    )


def test_version_read_failure_rejects_scanner(tmp_path):
    def runner(_command: list[str], _timeout: int) -> CommandResult:
        return CommandResult(1, "", "bad version")

    result = _admitter(tmp_path, runner=runner).admit("trivy", _exe(tmp_path, "trivy.exe"))

    assert (
        result["record"]["status"]
        == CleanroomImageScannerAdmissionStatus.CLEANROOM_SCANNER_VERSION_FAILED.value
    )


def test_capability_check_failure_rejects_docker_scout(tmp_path):
    def runner(command: list[str], _timeout: int) -> CommandResult:
        if "version" in command:
            return CommandResult(0, "Docker Scout 1.test\n", "")
        return CommandResult(1, "", "no archive")

    result = _admitter(tmp_path, runner=runner).admit("docker_scout", _exe(tmp_path, "docker.exe"))

    assert (
        result["record"]["status"]
        == CleanroomImageScannerAdmissionStatus.CLEANROOM_SCANNER_BLOCKED_REQUIRES_EXECUTION.value
    )


def test_signed_admission_record_is_produced(tmp_path):
    result = _admitter(tmp_path, runner=_runner_ok).admit("trivy", _exe(tmp_path, "trivy.exe"))

    assert Path(result["record_path"]).is_file()
    assert verify_cleanroom_image_scanner_admission_record(result["record"])


def test_scanner_admission_does_not_scan_doxygen_artifact(tmp_path):
    result = _admitter(tmp_path, runner=_runner_ok).admit("trivy", _exe(tmp_path, "trivy.exe"))

    assert "<archive.tar>" in result["record"]["scanner_command"]


def test_scanner_admission_does_not_mark_cache_ready(tmp_path):
    result = _admitter(tmp_path, runner=_runner_ok).admit("trivy", _exe(tmp_path, "trivy.exe"))

    assert result["record"]["cache_ready"] is False


def test_scanner_admission_does_not_mark_executable_true(tmp_path):
    result = _admitter(tmp_path, runner=_runner_ok).admit("trivy", _exe(tmp_path, "trivy.exe"))

    assert result["record"]["executable"] is False


def test_scanner_admission_does_not_mark_training_eligible_true(tmp_path):
    result = _admitter(tmp_path, runner=_runner_ok).admit("trivy", _exe(tmp_path, "trivy.exe"))

    assert result["record"]["training_eligible"] is False
