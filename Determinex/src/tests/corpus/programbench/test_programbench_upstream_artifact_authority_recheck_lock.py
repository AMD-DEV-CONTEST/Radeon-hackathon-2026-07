from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_ROOT / "scripts"))

from corpus.programbench.upstream_artifact_authority_recheck import (  # noqa: E402
    EXPECTED_DIGEST,
    INSTANCE_ID,
    AuthorityValue,
    ExecutionSecurityPolicy,
    ProgramBenchUpstreamArtifactAuthorityRecheck,
    UpstreamArtifactAuthorityRecheckConfig,
    UpstreamArtifactAuthorityRecheckStatus,
    image_name,
)
from corpus.programbench.upstream_artifact_authority_recheck_record import (  # noqa: E402
    verify_upstream_artifact_authority_recheck_record,
)

IMAGE = "programbench/doxygen_1776_doxygen.966d98e:task_cleanroom"
MANIFEST = Path(
    "assurance/evidence/programbench_dockerhub_manifest_provenance/programbench_doxygen_1776_doxygen.966d98e_task_cleanroom.EXACT_REMOTE_MANIFEST_FOUND.json"
)
REQUEST = Path(
    "assurance/evidence/programbench_operator_provenance_requests/programbench_doxygen_1776_doxygen.966d98e_task_cleanroom.OPERATOR_PROVENANCE_REQUEST_PACKET_WRITTEN.json"
)
DECISION = Path(
    "assurance/evidence/programbench_rebuild_provenance_quarantine_decisions/programbench_doxygen_1776_doxygen.966d98e_task_cleanroom.REBUILD_QUARANTINE_DECISION_PARTIAL_ONLY.json"
)
SCAN = Path(
    "assurance/evidence/programbench_cleanroom_image_scans/programbench_doxygen_1776_doxygen.966d98e_task_cleanroom.CLEANROOM_IMAGE_SCAN_FAILED.json"
)
HYDRATION = Path(
    "assurance/evidence/programbench_cleanroom_image_hydration/programbench_doxygen_1776_doxygen.966d98e_task_cleanroom.CLEANROOM_IMAGE_SCAN_FAILED.json"
)
ALTERNATE = Path(
    "assurance/evidence/programbench_alternate_cleanroom_image_provenance/programbench_doxygen_1776_doxygen.966d98e_task_cleanroom.ALTERNATE_CLEANROOM_PROVENANCE_NOT_FOUND.json"
)
PROVIDER_REGISTRY = Path("locks/sentinel/PROGRAMBENCH_ONLINE_PROVIDER_REGISTRY_LOCK_001.json")
TRIAGE = Path(
    "assurance/evidence/programbench_cleanroom_image_scan_triage/programbench_doxygen_1776_doxygen.966d98e_task_cleanroom.CLEANROOM_IMAGE_SCAN_TRIAGED.json"
)


def _runner(
    tmp_path: Path,
    *,
    expected_digest: str = EXPECTED_DIGEST,
    authority_paths: list[Path] | None = None,
):
    return ProgramBenchUpstreamArtifactAuthorityRecheck(
        UpstreamArtifactAuthorityRecheckConfig(
            root=_ROOT,
            output_dir=tmp_path / "upstream_recheck",
            instance_id=INSTANCE_ID,
            expected_digest=expected_digest,
            local_authority_paths=authority_paths or [],
        )
    )


def _recheck(tmp_path: Path, **kwargs):
    defaults = {
        "manifest_record_path": MANIFEST,
        "operator_request_path": REQUEST,
        "rebuild_decision_path": DECISION,
        "scan_record_path": SCAN,
        "hydration_record_path": HYDRATION,
        "alternate_record_path": ALTERNATE,
        "provider_registry_lock_path": PROVIDER_REGISTRY,
        "triage_record_path": TRIAGE,
    }
    defaults.update(kwargs)
    return _runner(tmp_path).recheck(**defaults)


def test_doxygen_instance_maps_to_expected_task_cleanroom_image():
    assert image_name(INSTANCE_ID) == IMAGE


def test_live_recheck_admits_upstream_artifact_authority_present_metadata_only(tmp_path):
    record = _recheck(tmp_path)["record"]
    assert record["upstream_benchmark_artifact_authority"] == AuthorityValue.PRESENT.value
    assert (
        record["decision"]
        == "OFFICIAL_ARTIFACT_METADATA_ONLY_ADMITTED_EXECUTION_BLOCKED_SCAN_FAILED"
    )
    assert record["authority_findings"]["exact_provider_manifest"]["metadata_only_lookup"] is True
    assert record["authority_findings"]["exact_provider_manifest"]["pulled_layers"] is False
    assert record["authority_findings"]["exact_provider_manifest"]["executed"] is False


def test_recheck_consumes_prior_doxygen_records(tmp_path):
    record = _recheck(tmp_path)["record"]
    consumed = record["consumed_records"]
    assert consumed["manifest_record"] == MANIFEST.as_posix()
    assert consumed["operator_provenance_request"] == REQUEST.as_posix()
    assert consumed["rebuild_quarantine_decision"] == DECISION.as_posix()
    assert consumed["scan_record"] == SCAN.as_posix()
    assert consumed["hydration_record"] == HYDRATION.as_posix()
    assert consumed["alternate_provenance_record"] == ALTERNATE.as_posix()


def test_recheck_verifies_image_name_and_digest_consistency(tmp_path):
    record = _recheck(tmp_path)["record"]
    assert record["image_reference"] == IMAGE
    assert record["image_digest"] == EXPECTED_DIGEST
    assert record["verification"]["image_consistency"] is True
    assert record["verification"]["digest_consistency"] is True
    assert record["verification"]["manifest_digest_matches_expected"] is True


def test_artifact_authority_is_distinct_from_rebuild_and_remediation_authority(tmp_path):
    record = _recheck(tmp_path)["record"]
    assert record["upstream_benchmark_artifact_authority"] == AuthorityValue.PRESENT.value
    assert record["rebuild_provenance_authority"] == AuthorityValue.ABSENT.value
    assert record["remediation_authority"] == AuthorityValue.ABSENT.value
    boundaries = record["authority_findings"]["authority_boundaries"]
    assert boundaries["upstream_benchmark_artifact_authority_is_not_rebuild_authority"] is True
    assert boundaries["upstream_benchmark_artifact_authority_is_not_remediation_authority"] is True


def test_execution_security_policy_stays_blocked_by_failed_scan(tmp_path):
    record = _recheck(tmp_path)["record"]
    assert record["execution_security_policy"] == ExecutionSecurityPolicy.BLOCKED_SCAN_FAILED.value
    assert record["verification"]["scan_status"] == "CLEANROOM_IMAGE_SCAN_FAILED"
    assert record["verification"]["hydration_policy_result"] == "CLEANROOM_IMAGE_POLICY_BLOCKED"


def test_training_cache_and_execution_remain_false(tmp_path):
    record = _recheck(tmp_path)["record"]
    assert record["cache_ready"] is False
    assert record["executable"] is False
    assert record["training_eligible"] is False
    assert record["authorization"]["programbench_rerun_authorized"] is False
    assert record["authorization"]["docker_execution_authorized"] is False


def test_record_statuses_include_expected_authority_and_policy_boundaries(tmp_path):
    statuses = _recheck(tmp_path)["record"]["authority_findings"]["authority_statuses"]
    assert (
        UpstreamArtifactAuthorityRecheckStatus.UPSTREAM_ARTIFACT_AUTHORITY_PRESENT.value in statuses
    )
    assert (
        UpstreamArtifactAuthorityRecheckStatus.REBUILD_PROVENANCE_AUTHORITY_ABSENT.value in statuses
    )
    assert UpstreamArtifactAuthorityRecheckStatus.REMEDIATION_AUTHORITY_ABSENT.value in statuses
    assert (
        UpstreamArtifactAuthorityRecheckStatus.OFFICIAL_ARTIFACT_EXECUTION_BLOCKED_SCAN_FAILED.value
        in statuses
    )
    assert UpstreamArtifactAuthorityRecheckStatus.TRAINING_INELIGIBLE.value in statuses


def test_provider_registry_exact_path_is_recorded_without_authorizing_execution(tmp_path):
    record = _recheck(tmp_path)["record"]
    assert record["authority_findings"]["provider_registry_exact_path_allowed"] is True
    assert record["authorization"]["metadata_only_admitted"] is True
    assert record["authorization"]["docker_pull_authorized"] is False
    assert record["authorization"]["hydration_authorized"] is False


def test_missing_local_programbench_authority_evidence_makes_authority_inconclusive(tmp_path):
    missing_doc = tmp_path / "empty_authority.md"
    missing_doc.write_text("no image model here\n", encoding="utf-8")
    runner = _runner(tmp_path, authority_paths=[missing_doc])
    record = runner.recheck(
        manifest_record_path=MANIFEST,
        operator_request_path=REQUEST,
        rebuild_decision_path=DECISION,
        scan_record_path=SCAN,
        hydration_record_path=HYDRATION,
        alternate_record_path=ALTERNATE,
        provider_registry_lock_path=PROVIDER_REGISTRY,
        triage_record_path=TRIAGE,
    )["record"]
    assert record["upstream_benchmark_artifact_authority"] == AuthorityValue.INCONCLUSIVE.value
    assert record["execution_security_policy"] == ExecutionSecurityPolicy.BLOCKED_SCAN_FAILED.value


def test_digest_mismatch_blocks_present_authority(tmp_path):
    runner = _runner(tmp_path, expected_digest="sha256:" + "0" * 64)
    record = runner.recheck(
        manifest_record_path=MANIFEST,
        operator_request_path=REQUEST,
        rebuild_decision_path=DECISION,
        scan_record_path=SCAN,
        hydration_record_path=HYDRATION,
        alternate_record_path=ALTERNATE,
        provider_registry_lock_path=PROVIDER_REGISTRY,
        triage_record_path=TRIAGE,
    )["record"]
    assert record["upstream_benchmark_artifact_authority"] == AuthorityValue.INCONCLUSIVE.value
    assert record["verification"]["digest_consistency"] is False
    assert "digest_consistency_not_verified" in record["reasons"]


def test_signed_recheck_record_is_written(tmp_path):
    result = _recheck(tmp_path)
    assert Path(result["record_path"]).is_file()
    assert verify_upstream_artifact_authority_recheck_record(result["record"])


def test_no_policy_exception_or_rerun_authority_is_granted(tmp_path):
    auth = _recheck(tmp_path)["record"]["authorization"]
    assert auth["policy_exception_authorized"] is False
    assert auth["programbench_rerun_authorized"] is False
    assert auth["rebuild_authorized"] is False
    assert auth["remediation_authorized"] is False


def test_alternate_not_found_record_does_not_force_dead_end_when_official_artifact_is_present(
    tmp_path,
):
    record = _recheck(tmp_path)["record"]
    assert (
        record["verification"]["alternate_provenance_status"]
        == "ALTERNATE_CLEANROOM_PROVENANCE_NOT_FOUND"
    )
    assert record["upstream_benchmark_artifact_authority"] == AuthorityValue.PRESENT.value
