from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from pydantic import ValidationError

from colorgraph.evaluation.research_watch import (
    ResearchArtifactEvidence,
    ResearchGoldEvidence,
    ResearchRuntimeEvidence,
    ResearchSource,
    ResearchWatchCandidate,
    ResearchWatchManifest,
    ResearchWatchPolicy,
    audit_research_watch,
    audit_research_watch_file,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
WATCH_MANIFEST = REPOSITORY_ROOT / "docs" / "research-watchlist-v1.json"


def _source(kind: str) -> ResearchSource:
    return ResearchSource(
        kind=kind,
        url=f"https://example.com/{kind}",
        checked_on=date(2026, 7, 30),
        note=f"Official {kind} evidence",
    )


def _qualified_candidate() -> ResearchWatchCandidate:
    return ResearchWatchCandidate(
        candidate_id="qualified-candidate",
        name="Qualified candidate",
        category="video_segmentation",
        sources=[_source("paper"), _source("code"), _source("license"), _source("weights")],
        code=ResearchArtifactEvidence(
            availability="available",
            license_id="Apache-2.0",
            license_disposition="commercial_allowed",
            immutable_revision="a" * 40,
        ),
        weights=ResearchArtifactEvidence(
            availability="available",
            license_id="Apache-2.0",
            license_disposition="commercial_allowed",
            sha256="b" * 64,
        ),
        runtime=ResearchRuntimeEvidence(
            reproducibility_status="passed",
            reproducibility_report_sha256="c" * 64,
            peak_vram_mb=12_000,
            tested_platforms=["windows"],
            passed_platforms=["windows"],
        ),
        gold_set=ResearchGoldEvidence(
            status="passed",
            report_sha256="d" * 64,
        ),
    )


def _audit(candidate: ResearchWatchCandidate):
    manifest = ResearchWatchManifest(
        checked_on=date(2026, 7, 30),
        policy=ResearchWatchPolicy(),
        candidates=[candidate],
    )
    return audit_research_watch(
        manifest,
        manifest_path="manifest.json",
        manifest_sha256="e" * 64,
        created_at=datetime(2026, 7, 30, tzinfo=UTC),
    )


def test_checked_in_watchlist_is_current_and_fail_closed() -> None:
    report = audit_research_watch_file(WATCH_MANIFEST)

    assert report.registry_integrity_passed is True
    assert len(report.candidates) == 7
    assert report.eligible_candidates == []
    assert report.promoted_candidates == []
    assert report.invalid_candidates == []
    assert set(report.watch_candidates) == {
        "acetone-3b-preview",
        "autoshot",
        "lumivideo",
        "photoagent",
        "sam3.1-object-multiplex",
        "video-depth-anything-base",
        "video-depth-anything-large",
    }


def test_every_gate_is_required_before_formal_todo_eligibility() -> None:
    report = _audit(_qualified_candidate())

    assert report.eligible_candidates == ["qualified-candidate"]
    assert report.candidates[0].promotion_ready is True
    assert report.candidates[0].blockers == []


def test_noncommercial_memory_platform_and_gold_fail_closed() -> None:
    candidate = _qualified_candidate()
    candidate.weights.license_disposition = "noncommercial"
    candidate.runtime.peak_vram_mb = 17_000
    candidate.runtime.passed_platforms = []
    candidate.gold_set.status = "failed"

    report = _audit(candidate)

    assert report.watch_candidates == ["qualified-candidate"]
    assert set(report.candidates[0].blockers) >= {
        "weights_license_not_commercially_cleared",
        "target_vram_limit_exceeded",
        "target_platform_not_passed",
        "gold_set_not_passed",
    }


def test_premature_formal_todo_is_an_integrity_failure() -> None:
    candidate = _qualified_candidate()
    candidate.gold_set.status = "not_run"
    candidate.gold_set.report_sha256 = None
    candidate.formal_todo_id = "CG-VOS-999"

    report = _audit(candidate)

    assert report.registry_integrity_passed is False
    assert report.invalid_candidates == ["qualified-candidate"]
    assert report.candidates[0].status == "invalid_premature_promotion"


def test_registry_rejects_duplicate_candidates_and_insecure_sources() -> None:
    candidate = _qualified_candidate()
    try:
        ResearchSource(
            kind="paper",
            url="http://example.com/paper",
            checked_on=date(2026, 7, 30),
            note="Not secure",
        )
    except ValidationError:
        pass
    else:
        raise AssertionError("HTTP research sources must be rejected")

    try:
        ResearchWatchManifest(
            checked_on=date(2026, 7, 30),
            candidates=[candidate, candidate.model_copy(deep=True)],
        )
    except ValidationError:
        pass
    else:
        raise AssertionError("duplicate candidate IDs must be rejected")
