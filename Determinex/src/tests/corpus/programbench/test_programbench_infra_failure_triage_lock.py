from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_ROOT / "scripts"))

from corpus.programbench.infra_failure_triage import (  # noqa: E402
    InfraFailureTriageConfig,
    InfraFailureTriageStatus,
    ProgramBenchInfraFailureTriage,
)
from corpus.programbench.infra_failure_triage_record import (
    verify_infra_failure_triage_record,  # noqa: E402
)
from corpus.programbench.real_bounded_rerun_record import (  # noqa: E402
    make_real_rerun_record,
    write_real_rerun_record,
)

MISSING_IMAGE = "programbench/doxygen_1776_doxygen.966d98e:task_cleanroom"


def _real_failure(tmp_path: Path) -> Path:
    record = make_real_rerun_record(
        status="REAL_BOUNDED_RERUN_INFRA_FAILURE",
        packet_id="doxygen_real_bounded_rerun_20260527",
        target={
            "tool": "doxygen__doxygen.966d98e",
            "candidate_id": "close_lock_v7_doxygen_richgo_20260527",
        },
        rerun_scope={
            "tool": "doxygen__doxygen.966d98e",
            "candidate_id": "close_lock_v7_doxygen_richgo_20260527",
            "max_attempts": 1,
        },
        outcome={
            "status": "executed",
            "stdout": (
                "preflight failed before official eval:\n"
                f"FAIL image missing: {MISSING_IMAGE}\n"
                f"Error response from daemon: No such image: {MISSING_IMAGE}"
            ),
            "stderr": "",
        },
    )
    return write_real_rerun_record(record, tmp_path / "real")


def _source_registry(tmp_path: Path) -> Path:
    path = tmp_path / "assurance" / "config" / "artifact_sources.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "name": "determinex_artifacts",
                        "type": "private_registry",
                        "trust_level": "trusted_internal",
                        "allowed_for": ["image", "image_pull_if_digest_pinned"],
                        "requires_digest": True,
                    },
                    {
                        "name": "docker_hub",
                        "type": "oci_registry",
                        "trust_level": "public_untrusted",
                        "allowed_for": ["image_metadata", "image_pull_if_digest_pinned"],
                        "requires_digest": True,
                        "requires_security_scan": True,
                    },
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def _triage(tmp_path: Path, *, image_lister=None, provenance_roots: list[Path] | None = None):
    return ProgramBenchInfraFailureTriage(
        InfraFailureTriageConfig(
            root=tmp_path,
            output_dir=tmp_path / "triage",
            provenance_roots=provenance_roots or [tmp_path / "provenance"],
            artifact_sources_path=_source_registry(tmp_path).relative_to(tmp_path),
            image_lister=image_lister,
        )
    )


def _write_provenance(tmp_path: Path, name: str, row: dict) -> Path:
    root = tmp_path / "provenance"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{name}.json"
    payload = {
        "schema_version": "determinex-artifact-provenance-v1",
        "artifact_id": MISSING_IMAGE,
        "artifact_type": "oci_image",
        "source": "determinex_artifacts",
        "resolved_digest": "sha256:" + "a" * 64,
        "tag": "task_cleanroom",
        "trust_level": "trusted_internal",
        "security_scan": {"critical": 0, "high": 0, "policy": "pass"},
        "allowed_use": ["programbench_replay"],
        **row,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def test_real_bounded_rerun_infra_failure_loads_successfully(tmp_path):
    result = _triage(tmp_path).triage(_real_failure(tmp_path))

    assert result["record"]["status"] == InfraFailureTriageStatus.INFRA_FAILURE_TRIAGED.value


def test_missing_cleanroom_docker_image_is_classified(tmp_path):
    result = _triage(tmp_path).triage(_real_failure(tmp_path))

    assert (
        result["record"]["failure_type"] == InfraFailureTriageStatus.MISSING_CLEANROOM_IMAGE.value
    )
    assert (
        InfraFailureTriageStatus.MISSING_CLEANROOM_IMAGE.value
        in result["record"]["failure_statuses"]
    )


def test_missing_image_reference_is_extracted_exactly(tmp_path):
    result = _triage(tmp_path).triage(_real_failure(tmp_path))

    assert result["record"]["missing_image"] == MISSING_IMAGE


def test_missing_image_linked_to_authorized_doxygen_scope(tmp_path):
    result = _triage(tmp_path).triage(_real_failure(tmp_path))

    target = result["record"]["target"]
    assert target["tool"] == "doxygen__doxygen.966d98e"
    assert target["candidate_id"] == "close_lock_v7_doxygen_richgo_20260527"
    assert result["record"]["evidence"]["rerun_scope"]["max_attempts"] == 1


def test_local_image_inspection_is_read_only_injected_lister(tmp_path):
    calls = {"count": 0}

    def list_images():
        calls["count"] += 1
        return [MISSING_IMAGE]

    result = _triage(tmp_path, image_lister=list_images).triage(_real_failure(tmp_path))

    assert calls["count"] == 1
    assert (
        result["record"]["local_image_status"] == InfraFailureTriageStatus.IMAGE_PRESENT_LOCAL.value
    )


def test_existing_exact_pinned_provenance_is_detected(tmp_path):
    _write_provenance(tmp_path, "exact", {})

    result = _triage(tmp_path).triage(_real_failure(tmp_path))

    assert (
        result["record"]["source_status"]
        == InfraFailureTriageStatus.IMAGE_SOURCE_EXACT_REFERENCE_FOUND.value
    )
    assert (
        result["record"]["provenance_status"]
        == InfraFailureTriageStatus.IMAGE_SOURCE_EXACT_REFERENCE_FOUND.value
    )


def test_no_provenance_requires_operator_or_blocks_no_provenance(tmp_path):
    result = _triage(tmp_path).triage(_real_failure(tmp_path))

    assert (
        result["record"]["source_status"]
        == InfraFailureTriageStatus.IMAGE_RECOVERY_REQUIRES_OPERATOR.value
    )
    assert (
        result["record"]["provenance_status"]
        == InfraFailureTriageStatus.IMAGE_HYDRATION_BLOCKED_NO_PROVENANCE.value
    )


def test_ambiguous_source_produces_ambiguous_status(tmp_path):
    _write_provenance(tmp_path, "one", {"resolved_digest": "sha256:" + "a" * 64})
    _write_provenance(tmp_path, "two", {"resolved_digest": "sha256:" + "b" * 64})

    result = _triage(tmp_path).triage(_real_failure(tmp_path))

    assert (
        result["record"]["source_status"] == InfraFailureTriageStatus.IMAGE_SOURCE_AMBIGUOUS.value
    )


def test_floating_latest_source_is_blocked(tmp_path):
    _write_provenance(
        tmp_path,
        "latest",
        {
            "artifact_id": "programbench/doxygen_1776_doxygen.966d98e:latest",
            "image": MISSING_IMAGE,
            "resolved_digest": "",
            "tag": "latest",
        },
    )

    result = _triage(tmp_path).triage(_real_failure(tmp_path))

    assert result["record"]["source_status"] == InfraFailureTriageStatus.IMAGE_SOURCE_BLOCKED.value
    assert (
        result["record"]["provenance_status"]
        == InfraFailureTriageStatus.IMAGE_HYDRATION_BLOCKED_NO_DIGEST.value
    )


def test_public_untrusted_source_cannot_hydrate_directly(tmp_path):
    _write_provenance(
        tmp_path,
        "public",
        {
            "source": "docker_hub",
            "trust_level": "public_untrusted",
            "resolved_digest": "sha256:" + "c" * 64,
        },
    )

    result = _triage(tmp_path).triage(_real_failure(tmp_path))

    assert result["record"]["source_status"] == InfraFailureTriageStatus.IMAGE_SOURCE_BLOCKED.value
    assert (
        result["record"]["provenance_status"]
        == InfraFailureTriageStatus.IMAGE_HYDRATION_BLOCKED_POLICY.value
    )


def test_quarantine_only_artifact_cannot_execute(tmp_path):
    _write_provenance(tmp_path, "quarantine", {"quarantine_only": True})

    result = _triage(tmp_path).triage(_real_failure(tmp_path))

    assert (
        result["record"]["provenance_status"]
        == InfraFailureTriageStatus.IMAGE_HYDRATION_READY_QUARANTINE_ONLY.value
    )
    assert "execution from quarantine" in result["record"]["blocked_actions"]


def test_signed_triage_record_is_produced(tmp_path):
    result = _triage(tmp_path).triage(_real_failure(tmp_path))
    path = Path(result["record_path"])

    assert path.is_file()
    assert verify_infra_failure_triage_record(result["record"])
    assert result["record"]["training_eligible"] is False
    assert result["record"]["record_status"] == "active_eval_evidence"


def test_allowed_and_blocked_recovery_actions_are_encoded(tmp_path):
    result = _triage(tmp_path).triage(_real_failure(tmp_path))

    assert "operator-supplied digest/provenance" in result["record"]["allowed_actions"]
    assert "docker pull latest" in result["record"]["blocked_actions"]
    assert "broad web search" in result["record"]["blocked_actions"]
