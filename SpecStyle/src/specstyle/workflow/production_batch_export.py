"""Secure one-bundle publication adapter for a frozen Production cohort."""

from __future__ import annotations

from collections.abc import Callable

from specstyle.errors import DomainError
from specstyle.exporting import qa_report as _qa
from specstyle.exporting.bundle import (
    _StagedBundle,
    _commit_staged_bundle,
    _stage_bundle,
)
from specstyle.exporting.manifest import ExportRequest
from specstyle.verification.rule_models import ArtifactDecision, VerificationReport
from specstyle.workflow.production_batch import (
    BatchPublicationReceipt,
    FrozenProductionCohort,
    ProductionBatchCandidate,
)

__all__ = ("SecureProductionBatchPublisher",)

_RequestBuilder = Callable[
    [
        FrozenProductionCohort,
        VerificationReport,
        tuple[ArtifactDecision, ...],
        tuple[ProductionBatchCandidate, ...],
    ],
    ExportRequest,
]


def _invalid() -> None:
    raise DomainError("invalid production batch export") from None


def _same(left: object, right: object) -> bool:
    return _qa.canonical_material(left) == _qa.canonical_material(right)


def _rebuild_request(value: object) -> ExportRequest:
    if type(value) is not ExportRequest:
        _invalid()
    try:
        rebuilt = ExportRequest(value.cohorts, value.environment, value.asset_credits)
    except Exception:
        _invalid()
    if not _same(value, rebuilt):
        _invalid()
    return rebuilt


def _validate_bindings(
    request: ExportRequest,
    manifest: object,
    report: object,
    decisions: object,
    candidates: object,
) -> None:
    valid_types = (
        type(manifest) is FrozenProductionCohort
        and type(report) is VerificationReport
        and type(decisions) is tuple
        and all(type(item) is ArtifactDecision for item in decisions)
        and type(candidates) is tuple
        and all(type(item) is ProductionBatchCandidate for item in candidates)
        and len(candidates) == manifest.expected_count
        and len(decisions) == len(candidates)
        and len(request.cohorts) == 1
    )
    if not valid_types:
        _invalid()
    cohort = request.cohorts[0]
    artifacts = tuple(item.artifact.ref for item in candidates)
    current = tuple(item.history.current_artifact.ref for item in cohort.items)
    terminals = tuple(item.terminal.artifact_decision for item in cohort.items)
    bindings_match = (
        cohort.output_profile == "xhs_grid"
        and _same(cohort.final_report, report)
        and _same(current, artifacts)
        and _same(terminals, decisions)
        and manifest.member_ids == tuple(item.member_id for item in candidates)
        and manifest.artifact_ids
        == tuple(item.artifact.ref.artifact_id for item in candidates)
        and manifest.artifact_sha256s
        == tuple(item.artifact.ref.sha256 for item in candidates)
        and manifest.seeds == tuple(item.seed for item in candidates)
        and manifest.compiled_spec_sha256 == candidates[0].compiled_spec_sha256
        and all(
            item.compiled_spec_sha256 == manifest.compiled_spec_sha256
            for item in candidates
        )
        and all(
            item.history.current_request.compiled_spec.compiled_spec_hash
            == manifest.compiled_spec_sha256
            for item in cohort.items
        )
    )
    if not bindings_match:
        _invalid()


class _SecureStagedBatchPublication:
    __slots__ = ("_staged",)

    def __init__(self, staged: _StagedBundle) -> None:
        self._staged = staged

    def commit(self) -> BatchPublicationReceipt:
        bundle = _commit_staged_bundle(self._staged, accept_exact_existing=True)
        return BatchPublicationReceipt(bundle.bundle_name, bundle.bundle_sha256)

    def close(self) -> None:
        self._staged.close()


class SecureProductionBatchPublisher:
    """Build, validate, stage and atomically publish one exact cohort export."""

    __slots__ = ("_root_fd", "_bundle_name", "_build_request")

    def __init__(
        self,
        target_root_fd: int,
        bundle_name: str,
        build_request: _RequestBuilder,
    ) -> None:
        if (
            type(target_root_fd) is not int
            or isinstance(target_root_fd, bool)
            or type(bundle_name) is not str
            or not callable(build_request)
        ):
            _invalid()
        self._root_fd = target_root_fd
        self._bundle_name = bundle_name
        self._build_request = build_request

    def stage(
        self,
        manifest: FrozenProductionCohort,
        report: VerificationReport,
        decisions: tuple[ArtifactDecision, ...],
        candidates: tuple[ProductionBatchCandidate, ...],
    ) -> _SecureStagedBatchPublication:
        try:
            request = _rebuild_request(
                self._build_request(manifest, report, decisions, candidates)
            )
            _validate_bindings(request, manifest, report, decisions, candidates)
        except DomainError:
            raise
        except Exception:
            _invalid()
        return _SecureStagedBatchPublication(
            _stage_bundle(request, self._root_fd, self._bundle_name)
        )
