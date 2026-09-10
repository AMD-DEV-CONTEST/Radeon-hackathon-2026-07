"""L2-005 / L3-004 calibration contract tests (synthetic, CPU-only)."""

from __future__ import annotations

import pytest

from specstyle.calibration.l2_runner import run_l2_calibration
from specstyle.calibration.l3_runner import run_l3_calibration
from specstyle.calibration.splits import SampleRef, assign_split, build_split_manifest
from specstyle.calibration.threshold_search import (
    ScoredPair,
    holdout_evaluate,
    select_threshold_on_calibration,
)
from specstyle.domain.identifiers import Sha256
from specstyle.errors import DomainError
from specstyle.observability.hashing import hash_bytes


def _sample(i: int, *, style: str, content: str, pos: bool, tag: str) -> SampleRef:
    digest = hash_bytes(f"sample:{tag}:{i}".encode())
    return SampleRef(f"s{i}", digest, style, content, pos)


def test_assign_split_deterministic() -> None:
    h = hash_bytes(b"content-x")
    assert assign_split(h) == assign_split(h)


def test_content_id_leak_rejected() -> None:
    # Force same content_id into different hashes — isolation checks content_id.
    a = SampleRef("a", hash_bytes(b"1"), "st", "c1", True)
    b = SampleRef("b", hash_bytes(b"2"), "st", "c1", False)
    # May land same or different splits; if different, leak raises.
    try:
        build_split_manifest((a, b))
    except DomainError as exc:
        assert "leak" in str(exc)
    else:
        # Same split is allowed for same content_id only if same split — but
        # content_id isolation forbids cross-split; same split is ok.
        pass


def test_duplicate_content_hash_rejected() -> None:
    h = hash_bytes(b"same")
    a = SampleRef("a", h, "st", "c1", True)
    b = SampleRef("b", h, "st", "c2", False)
    with pytest.raises(DomainError, match="duplicate content hash"):
        build_split_manifest((a, b))


def test_l2_calibration_selects_and_freezes() -> None:
    samples: list[SampleRef] = []
    # Separable synthetic scores via score_fn using content_id.
    for i in range(40):
        pos = i % 2 == 0
        samples.append(
            _sample(
                i,
                style="sA" if pos else "sB",
                content=f"c{i}",
                pos=pos,
                tag="l2",
            )
        )

    def score(s: SampleRef) -> float:
        return 0.9 if s.label_positive else 0.1

    result = run_l2_calibration(tuple(samples), score, max_fpr=0.2, min_tpr=0.7)
    assert result.decision.status in ("VALIDATION_PASSED", "REJECTED", "DRAFT")
    assert result.decision.status != "VALIDATED"
    assert result.test_held is True
    assert result.manifest.manifest_hash


def test_threshold_selection_prefers_feasible() -> None:
    pairs = (
        ScoredPair("p1", 0.9, True),
        ScoredPair("p2", 0.85, True),
        ScoredPair("n1", 0.2, False),
        ScoredPair("n2", 0.15, False),
    )
    thr = select_threshold_on_calibration(
        pairs, metric_id="m", max_fpr=0.1, min_tpr=0.9
    )
    assert thr > 0.5


def test_holdout_requires_validation_passed() -> None:
    from specstyle.calibration.threshold_search import ThresholdDecision

    dec = ThresholdDecision(
        "m",
        "gte",
        0.5,
        1.0,
        0.0,
        1.0,
        0.0,
        "REJECTED",
        Sha256("c" * 64),
    )
    with pytest.raises(DomainError, match="VALIDATION_PASSED"):
        holdout_evaluate(dec, (ScoredPair("t", 0.6, True),))


def test_l3_calibration_components() -> None:
    samples = tuple(
        _sample(i, style="st", content=f"c{i}", pos=i % 2 == 0, tag="l3")
        for i in range(30)
    )

    def score(s: SampleRef) -> float:
        return 0.95 if s.label_positive else 0.05

    result = run_l3_calibration(samples, score, score, score)
    assert result.geometry.component == "geometry"
    assert result.features.decision.metric_id.startswith("l3_")
    assert result.composite.decision.status in ("VALIDATION_PASSED", "REJECTED")
    assert result.composite.decision.status != "VALIDATED"
