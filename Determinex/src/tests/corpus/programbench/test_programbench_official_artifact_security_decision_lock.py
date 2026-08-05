from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_ROOT / "scripts"))

from corpus.programbench.official_artifact_security_decision import (  # noqa: E402
    OfficialArtifactSecurityDecisionConfig,
    OfficialArtifactSecurityDecisionStatus,
    ProgramBenchOfficialArtifactSecurityDecision,
)
from corpus.programbench.official_artifact_security_decision_record import (  # noqa: E402
    verify_official_artifact_security_decision_record,
)

RECHECK = Path(
    "assurance/evidence/programbench_upstream_artifact_authority_recheck/programbench_doxygen_1776_doxygen.966d98e_task_cleanroom.UPSTREAM_ARTIFACT_AUTHORITY_RECHECK_COMPLETED.json"
)
IMAGE = "programbench/doxygen_1776_doxygen.966d98e:task_cleanroom"
DIGEST = "sha256:cc50d0f7e9a1f3f90512e3d4c34781f4686a8fa3774fbff489947ef41bde2e72"


def _runner(tmp_path: Path):
    return ProgramBenchOfficialArtifactSecurityDecision(
        OfficialArtifactSecurityDecisionConfig(
            root=_ROOT, output_dir=tmp_path / "security_decisions"
        )
    )


def test_security_decision_blocks_execution_when_scan_failed(tmp_path):
    record = _runner(tmp_path).decide(RECHECK)["record"]
    assert (
        record["decision"]
        == OfficialArtifactSecurityDecisionStatus.OFFICIAL_ARTIFACT_EXECUTION_BLOCKED_SCAN_FAILED.value
    )
    assert record["security_findings"]["execution_security_policy"] == "BLOCKED_SCAN_FAILED"
    assert record["security_findings"]["scan_status"] == "CLEANROOM_IMAGE_SCAN_FAILED"


def test_security_decision_keeps_metadata_only_admission(tmp_path):
    record = _runner(tmp_path).decide(RECHECK)["record"]
    assert record["security_findings"]["official_artifact_metadata_only"] is True
    assert record["authorization"]["metadata_only_admitted"] is True
    assert (
        OfficialArtifactSecurityDecisionStatus.OFFICIAL_ARTIFACT_METADATA_ONLY_ADMITTED.value
        in record["security_findings"]["decision_statuses"]
    )


def test_security_decision_records_expected_doxygen_image_and_digest(tmp_path):
    record = _runner(tmp_path).decide(RECHECK)["record"]
    assert record["instance_id"] == "doxygen__doxygen.966d98e"
    assert record["image_reference"] == IMAGE
    assert record["image_digest"] == DIGEST


def test_security_decision_does_not_grant_exception_or_sandbox_approval(tmp_path):
    auth = _runner(tmp_path).decide(RECHECK)["record"]["authorization"]
    assert auth["security_policy_exception_granted"] is False
    assert auth["stronger_sandbox_approved"] is False
    assert auth["docker_execution_authorized"] is False
    assert auth["programbench_rerun_authorized"] is False


def test_security_decision_keeps_cache_execution_and_training_false(tmp_path):
    record = _runner(tmp_path).decide(RECHECK)["record"]
    assert record["cache_ready"] is False
    assert record["executable"] is False
    assert record["training_eligible"] is False
    assert record["authorization"]["cache_ready"] is False
    assert record["authorization"]["training_eligible"] is False


def test_security_decision_consumes_upstream_authority_recheck(tmp_path):
    record = _runner(tmp_path).decide(RECHECK)["record"]
    assert record["upstream_authority_recheck"] == RECHECK.as_posix()
    assert record["security_findings"]["upstream_benchmark_artifact_authority"] == "PRESENT"
    assert record["security_findings"]["rebuild_provenance_authority"] == "ABSENT"
    assert record["security_findings"]["remediation_authority"] == "ABSENT"


def test_missing_recheck_blocks_security_decision(tmp_path):
    record = _runner(tmp_path).decide(tmp_path / "missing.json")["record"]
    assert (
        record["decision"]
        == OfficialArtifactSecurityDecisionStatus.OFFICIAL_ARTIFACT_SECURITY_DECISION_BLOCKED_NO_AUTHORITY_RECHECK.value
    )
    assert record["authorization"]["docker_execution_authorized"] is False


def test_signed_security_decision_record_is_written(tmp_path):
    result = _runner(tmp_path).decide(RECHECK)
    assert Path(result["record_path"]).is_file()
    assert verify_official_artifact_security_decision_record(result["record"])
