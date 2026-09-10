"""Secure atomic export adapter for formal Production batches."""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import pytest

from specstyle.domain.identifiers import Identifier
from specstyle.errors import DomainError
from specstyle.observability.hashing import hash_bytes
from specstyle.reliability.fixtures import sample_approved_export_request


def _inputs():
    from specstyle.workflow.production_batch import (
        FrozenProductionCohort,
        ProductionBatchCandidate,
    )

    request = sample_approved_export_request()
    cohort = request.cohorts[0]
    item = cohort.items[0]
    artifact = item.history.current_artifact
    compiled_sha = item.history.current_request.compiled_spec.compiled_spec_hash
    candidate = ProductionBatchCandidate(
        Identifier("member-0"),
        100,
        artifact,
        item.history.current_report,
        compiled_sha,
    )
    manifest = FrozenProductionCohort(
        Identifier("batch-1"),
        hash_bytes(b"target"),
        1,
        (candidate.member_id,),
        (artifact.ref.artifact_id,),
        (artifact.ref.sha256,),
        (candidate.seed,),
        compiled_sha,
        hash_bytes(b"l2"),
        hash_bytes(b"l3"),
        hash_bytes(b"runtime"),
        hash_bytes(b"manifest"),
    )
    return (
        request,
        manifest,
        cohort.final_report,
        (item.terminal.artifact_decision,),
        (candidate,),
    )


def _root(tmp_path: Path) -> tuple[int, Path]:
    root = tmp_path / "export"
    root.mkdir(mode=0o700)
    return os.open(root, os.O_RDONLY | os.O_DIRECTORY), root


def test_secure_batch_publisher_stages_then_atomically_commits_and_converges(
    tmp_path: Path,
) -> None:
    from specstyle.workflow.production_batch_export import (
        SecureProductionBatchPublisher,
    )

    request, manifest, report, decisions, candidates = _inputs()
    root_fd, root = _root(tmp_path)
    try:
        publisher = SecureProductionBatchPublisher(
            root_fd,
            "formal-batch-1",
            lambda *_args: request,
        )
        staged = publisher.stage(manifest, report, decisions, candidates)
        assert not (root / "formal-batch-1").exists()

        first = staged.commit()
        assert (root / first.bundle_name / "manifest.json").is_file()

        replay = publisher.stage(manifest, report, decisions, candidates).commit()
        assert replay == first
        assert [
            path.name for path in root.iterdir() if not path.name.startswith(".")
        ] == ["formal-batch-1"]
    finally:
        os.close(root_fd)


def test_secure_batch_publisher_rejects_builder_output_not_bound_to_cohort(
    tmp_path: Path,
) -> None:
    from specstyle.verification.rule_models import VerificationReport
    from specstyle.workflow.production_batch_export import (
        SecureProductionBatchPublisher,
    )

    request, manifest, report, decisions, candidates = _inputs()
    drifted_report = VerificationReport(
        report.artifacts,
        report.rules,
        (replace(report.results[0], score=0.5), *report.results[1:]),
    )
    root_fd, root = _root(tmp_path)
    try:
        publisher = SecureProductionBatchPublisher(
            root_fd, "formal-batch-1", lambda *_args: request
        )
        with pytest.raises(DomainError, match="^invalid production batch export$"):
            publisher.stage(manifest, drifted_report, decisions, candidates)
        assert not any(root.iterdir())
    finally:
        os.close(root_fd)


def test_secure_batch_publisher_close_never_promotes_staging(tmp_path: Path) -> None:
    from specstyle.workflow.production_batch_export import (
        SecureProductionBatchPublisher,
    )

    request, manifest, report, decisions, candidates = _inputs()
    root_fd, root = _root(tmp_path)
    try:
        staged = SecureProductionBatchPublisher(
            root_fd, "formal-batch-1", lambda *_args: request
        ).stage(manifest, report, decisions, candidates)
        staged.close()
        assert not (root / "formal-batch-1").exists()
    finally:
        os.close(root_fd)
