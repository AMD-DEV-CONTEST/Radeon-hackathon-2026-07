"""L1-002 layout and text soft rules — shipped functions."""

from __future__ import annotations

from specstyle.domain.enums import RuleStatus
from specstyle.domain.identifiers import ArtifactId
from specstyle.verification.l1.layout import BBox, SafeZone, check_layout
from specstyle.verification.l1.text_overlay import (
    TextOverlaySpec,
    check_text_overlay,
    soft_quality_warnings,
)


def test_layout_missing_bbox_policies() -> None:
    aid = ArtifactId("a1")
    zone = SafeZone(0.1, 0.1, 0.9, 0.9)
    assert check_layout(aid, None, zone).status is RuleStatus.UNVERIFIABLE
    assert (
        check_layout(aid, None, zone, missing_policy="warning").status
        is RuleStatus.WARNING
    )


def test_layout_outside_safe_zone_fails() -> None:
    aid = ArtifactId("a1")
    zone = SafeZone(0.1, 0.1, 0.9, 0.9)
    bad = (BBox(0.0, 0.2, 0.3, 0.4),)
    good = (BBox(0.2, 0.2, 0.5, 0.5),)
    assert check_layout(aid, bad, zone).status is RuleStatus.FAIL
    assert check_layout(aid, good, zone).status is RuleStatus.PASS


def test_text_overlay_match_truncate_and_missing() -> None:
    aid = ArtifactId("a1")
    assert (
        check_text_overlay(aid, TextOverlaySpec("hello", 10, "hello")).status
        is RuleStatus.PASS
    )
    assert (
        check_text_overlay(aid, TextOverlaySpec("hello", 3, "hello")).status
        is RuleStatus.FAIL
    )
    assert (
        check_text_overlay(aid, TextOverlaySpec("hello", 10, "world")).status
        is RuleStatus.FAIL
    )
    assert (
        check_text_overlay(aid, TextOverlaySpec("hello", 10, None)).status
        is RuleStatus.UNVERIFIABLE
    )


def test_soft_quality_warning_not_hard() -> None:
    aid = ArtifactId("a1")
    assert (
        soft_quality_warnings(
            aid, blur_score=0.5, exposure_score=0.5, contrast_score=0.5
        ).status
        is RuleStatus.PASS
    )
    assert (
        soft_quality_warnings(
            aid, blur_score=None, exposure_score=0.5, contrast_score=0.5
        ).status
        is RuleStatus.WARNING
    )
    assert (
        soft_quality_warnings(
            aid, blur_score=0.01, exposure_score=0.5, contrast_score=0.5
        ).status
        is RuleStatus.WARNING
    )
    # Soft never returns FAIL (not a hard gate).
    for status in (
        soft_quality_warnings(
            aid, blur_score=None, exposure_score=None, contrast_score=None
        ).status,
        soft_quality_warnings(
            aid, blur_score=0.01, exposure_score=0.99, contrast_score=0.01
        ).status,
    ):
        assert status is not RuleStatus.FAIL


def test_layout_empty_bbox_tuple_fails() -> None:
    aid = ArtifactId("a1")
    zone = SafeZone(0.1, 0.1, 0.9, 0.9)
    assert check_layout(aid, (), zone).status is RuleStatus.FAIL
