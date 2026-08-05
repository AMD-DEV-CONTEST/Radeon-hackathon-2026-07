from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_ROOT / "scripts"))

from corpus.programbench.approved_scanner_setup import (  # noqa: E402
    ApprovedScannerSetupConfig,
    ApprovedScannerSetupStatus,
    ProgramBenchApprovedScannerSetup,
)
from corpus.programbench.approved_scanner_setup_record import (
    verify_approved_scanner_setup_record,  # noqa: E402
)
from corpus.programbench.cleanroom_image_scanner_admission import CommandResult  # noqa: E402


def _exe(tmp_path: Path, name: str) -> Path:
    path = tmp_path / name
    path.write_text("binary marker\n", encoding="utf-8")
    return path


def _runner_ok(command: list[str], _timeout: int) -> CommandResult:
    if "--version" in command:
        return CommandResult(0, "Version: 0.test\n", "")
    if "version" in command:
        return CommandResult(0, '{"version":"0.test"}\n', "")
    return CommandResult(0, "docker-archive supported\n", "")


def _runner_fail(_command: list[str], _timeout: int) -> CommandResult:
    return CommandResult(1, "", "failed")


def _setup(
    tmp_path: Path, *, which=None, runner=None, allow_wrappers: bool = False
) -> ProgramBenchApprovedScannerSetup:
    return ProgramBenchApprovedScannerSetup(
        ApprovedScannerSetupConfig(
            root=tmp_path,
            output_dir=tmp_path / "setup",
            admission_output_dir=tmp_path / "admission",
            command_runner=runner,
            which=which or (lambda _name: None),
            allow_wrappers=allow_wrappers,
        )
    )


def test_existing_trivy_path_is_preferred_and_accepted(tmp_path):
    trivy = _exe(tmp_path, "trivy.exe")
    grype = _exe(tmp_path, "grype.exe")

    result = _setup(
        tmp_path,
        runner=_runner_ok,
        which=lambda name: (
            str(trivy) if name == "trivy" else str(grype) if name == "grype" else None
        ),
    ).setup()

    assert (
        result["record"]["status"]
        == ApprovedScannerSetupStatus.APPROVED_SCANNER_ADMISSION_PASSED.value
    )
    assert result["record"]["scanner_name"] == "trivy"


def test_existing_grype_path_is_accepted_when_trivy_absent(tmp_path):
    grype = _exe(tmp_path, "grype.exe")

    result = _setup(
        tmp_path, runner=_runner_ok, which=lambda name: str(grype) if name == "grype" else None
    ).setup()

    assert (
        result["record"]["status"]
        == ApprovedScannerSetupStatus.APPROVED_SCANNER_ADMISSION_PASSED.value
    )
    assert result["record"]["scanner_name"] == "grype"


def test_unknown_scanner_is_rejected(tmp_path):
    result = _setup(tmp_path, runner=_runner_ok).setup("unknown", _exe(tmp_path, "unknown.exe"))

    assert (
        result["record"]["status"]
        == ApprovedScannerSetupStatus.APPROVED_SCANNER_OPERATOR_PATH_REJECTED.value
    )
    assert "unknown_scanner_name" in result["record"]["reasons"]


def test_missing_scanner_produces_setup_required(tmp_path):
    result = _setup(tmp_path).setup()

    assert (
        result["record"]["status"]
        == ApprovedScannerSetupStatus.APPROVED_SCANNER_SETUP_REQUIRED.value
    )
    assert (
        ApprovedScannerSetupStatus.APPROVED_SCANNER_SETUP_REQUIRED.value
        in result["record"]["setup_statuses"]
    )


def test_operator_provided_valid_scanner_path_is_accepted(tmp_path):
    result = _setup(tmp_path, runner=_runner_ok).setup(scanner_path=_exe(tmp_path, "trivy.exe"))

    assert (
        result["record"]["status"]
        == ApprovedScannerSetupStatus.APPROVED_SCANNER_ADMISSION_PASSED.value
    )
    assert (
        ApprovedScannerSetupStatus.APPROVED_SCANNER_OPERATOR_PATH_ACCEPTED.value
        in result["record"]["setup_statuses"]
    )


def test_operator_provided_invalid_path_is_rejected(tmp_path):
    result = _setup(tmp_path, runner=_runner_ok).setup(scanner_path=tmp_path / "trivy.exe")

    assert (
        result["record"]["status"]
        == ApprovedScannerSetupStatus.APPROVED_SCANNER_ADMISSION_FAILED.value
    )
    assert (
        ApprovedScannerSetupStatus.APPROVED_SCANNER_OPERATOR_PATH_REJECTED.value
        in result["record"]["setup_statuses"]
    )


def test_version_read_failure_rejects_scanner(tmp_path):
    result = _setup(tmp_path, runner=_runner_fail).setup("trivy", _exe(tmp_path, "trivy.exe"))

    assert (
        result["record"]["status"]
        == ApprovedScannerSetupStatus.APPROVED_SCANNER_ADMISSION_FAILED.value
    )
    assert result["record"]["admission_status"] == "CLEANROOM_SCANNER_VERSION_FAILED"


def test_capability_failure_rejects_scanner(tmp_path):
    def runner(command: list[str], _timeout: int) -> CommandResult:
        if "version" in command:
            return CommandResult(0, "Docker Scout 1.test\n", "")
        return CommandResult(1, "", "no archive")

    result = _setup(tmp_path, runner=runner).setup("docker_scout", _exe(tmp_path, "docker.exe"))

    assert (
        result["record"]["status"]
        == ApprovedScannerSetupStatus.APPROVED_SCANNER_ADMISSION_FAILED.value
    )
    assert result["record"]["admission_status"] == "CLEANROOM_SCANNER_BLOCKED_REQUIRES_EXECUTION"


def test_setup_record_is_signed(tmp_path):
    result = _setup(tmp_path, runner=_runner_ok).setup("trivy", _exe(tmp_path, "trivy.exe"))

    assert Path(result["record_path"]).is_file()
    assert verify_approved_scanner_setup_record(result["record"])


def test_scanner_admission_can_be_rerun_after_valid_setup(tmp_path):
    result = _setup(tmp_path, runner=_runner_ok).setup("trivy", _exe(tmp_path, "trivy.exe"))

    assert result["record"]["admission_status"] == "CLEANROOM_SCANNER_ADMITTED"
    assert Path(result["record"]["admission_record_path"]).is_file()


def test_setup_does_not_scan_doxygen_artifact(tmp_path):
    result = _setup(tmp_path, runner=_runner_ok).setup("trivy", _exe(tmp_path, "trivy.exe"))

    assert "sha256_cc50d0f7e9a1f3f90512e3d4c34781f4686a8fa3774fbff489947ef41bde2e72.tar" not in str(
        result["record"]
    )


def test_setup_does_not_mark_cache_ready(tmp_path):
    result = _setup(tmp_path, runner=_runner_ok).setup("trivy", _exe(tmp_path, "trivy.exe"))

    assert result["record"]["cache_ready"] is False


def test_setup_does_not_mark_executable_true(tmp_path):
    result = _setup(tmp_path, runner=_runner_ok).setup("trivy", _exe(tmp_path, "trivy.exe"))

    assert result["record"]["executable"] is False


def test_setup_does_not_mark_training_eligible_true(tmp_path):
    result = _setup(tmp_path, runner=_runner_ok).setup("trivy", _exe(tmp_path, "trivy.exe"))

    assert result["record"]["training_eligible"] is False


def test_no_docker_container_execution_occurs(tmp_path):
    seen: list[list[str]] = []

    def runner(command: list[str], timeout: int) -> CommandResult:
        seen.append(command)
        return _runner_ok(command, timeout)

    _setup(tmp_path, runner=runner).setup("trivy", _exe(tmp_path, "trivy.exe"))

    assert all("run" not in command for command in seen)


def test_no_programbench_rerun_occurs(tmp_path):
    seen: list[list[str]] = []

    def runner(command: list[str], timeout: int) -> CommandResult:
        seen.append(command)
        return _runner_ok(command, timeout)

    _setup(tmp_path, runner=runner).setup("grype", _exe(tmp_path, "grype.exe"))

    assert all(
        not any(part.lower() in {"programbench", "eval"} for part in command) for command in seen
    )
