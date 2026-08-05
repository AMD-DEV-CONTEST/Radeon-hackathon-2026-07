from __future__ import annotations

from corpus.programbench.artifact_import_operator_guide import (
    ACCEPTABLE_FORMS,
    REJECTED_FORMS,
    ArtifactImportOperatorGuideConfig,
    ProgramBenchArtifactImportOperatorGuide,
    render_markdown,
)
from corpus.programbench.artifact_import_operator_guide_record import (
    verify_artifact_import_operator_guide_record,
)


def _guide() -> dict[str, object]:
    return ProgramBenchArtifactImportOperatorGuide(
        ArtifactImportOperatorGuideConfig(write_record=False, write_doc=False)
    ).build()


def test_operator_guide_is_written_for_all_metadata_admitted_targets() -> None:
    record = _guide()

    assert record["status"] == "ARTIFACT_IMPORT_OPERATOR_GUIDE_WRITTEN"
    assert verify_artifact_import_operator_guide_record(record)
    assert len(record["targets"]) == 10
    assert record["current_state"]["exact_manifest_digests_admitted_metadata_only"] == 10
    assert all(
        row["required_packet_type"] == "artifact_import_provenance" for row in record["targets"]
    )
    assert all(row["digest"].startswith("sha256:") for row in record["targets"])


def test_operator_guide_rejects_unsafe_metadata_forms() -> None:
    record = _guide()

    rejected = set(record["rejected_forms"])
    for item in (
        "latest tags",
        "name-only images",
        "tag-only pulls",
        "screenshots",
        "fixture packets",
        "artifact with missing sha256",
        "artifact with mismatched digest",
    ):
        assert item in rejected
    assert "exact digest image tar exported by controlled process" in ACCEPTABLE_FORMS
    assert set(REJECTED_FORMS).issubset(rejected)


def test_operator_guide_does_not_authorize_execution_or_training() -> None:
    record = _guide()
    auth = record["authorization"]

    assert auth["docker_run_authorized"] is False
    assert auth["docker_pull_authorized"] is False
    assert auth["artifact_import_authorized"] is False
    assert auth["scan_authorized"] is False
    assert auth["programbench_rerun_authorized"] is False
    assert auth["executable"] is False
    assert auth["cache_ready"] is False
    assert auth["training_eligible"] is False
    assert auth["training_rows_written"] is False


def test_operator_guide_excludes_doxygen_from_batch001_import_targets() -> None:
    record = _guide()

    assert record["doxygen_included"] is False
    assert all(not row["instance_id"].startswith("doxygen__") for row in record["targets"])


def test_operator_guide_documents_inbox_outbox_flow_and_commands() -> None:
    record = _guide()

    assert (
        record["operator_flow"]["templates_live_at"]
        == "assurance/operator_outbox/programbench/batch001_import_scan"
    )
    assert (
        record["operator_flow"]["completed_packets_go_to"]
        == "assurance/operator_inbox/programbench"
    )
    assert record["operator_flow"]["only_if_real_packets_exist"] is True
    assert "inbox-scan --json" in record["cli_commands"]["scan_inbox"]
    assert "review-live-packets --json" in record["cli_commands"]["review_live_packets"]


def test_operator_guide_markdown_contains_all_targets_and_warnings() -> None:
    record = _guide()
    markdown = render_markdown(record)

    assert "ProgramBench Artifact Import Operator Guide" in markdown
    assert "Doxygen is intentionally not included" in markdown
    assert markdown.count("artifact_import_provenance") >= 10
    for warning in record["hard_warnings"]:
        assert warning in markdown
