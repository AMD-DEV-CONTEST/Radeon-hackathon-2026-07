"""
Tests for scripts/pb_tier_classify.py's reconcile_from_archive() — the
archive-authoritative provenance law.

Regression coverage for the bug found 2026-07-02 during a corpus-center
audit: PROMOTE treated "in verified_locks.json" (score-verified: cache-
cleared eval, passed==total, tarball sha pinned — per that file's own
note) as sufficient grounds to force a row to strict_lock, without
checking whether the row's CURRENT status was a deliberate provenance
hold (needs_reverify). Three real corpus rows (chmln__handlr,
isona__dirble, ngrrram) are score-perfect and score-verified but were
explicitly parked at needs_reverify by the 2026-06-30 provenance audit
because their reimplementation-vs-upstream-copy status couldn't be
confirmed. Auto-promoting them would have silently re-introduced the
exact overclaiming that audit corrected.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from pb_tier_classify import reconcile_from_archive


def _perfect_archive(
    passed: int = 100, report_path: str = "corpus/programbench/locked/foo/eval_report.json"
):
    return (passed, passed, 0, 0, 0), report_path


def test_needs_reverify_is_never_auto_promoted_even_with_perfect_archive():
    entries = [
        {
            "slug": "chmln__handlr",
            "status": "needs_reverify",
            "reconcile_note": "not positively confirmed as upstream, but also not "
            "verified as a genuine native reimplementation -- "
            "needs manual reverify before being counted again.",
        }
    ]
    verified_short = {"handlr"}
    archive_best = {"handlr": _perfect_archive(1812)}

    changes = reconcile_from_archive(entries, verified_short, archive_best)

    assert changes == []
    assert entries[0]["status"] == "needs_reverify"
    assert entries[0]["reconcile_note"].startswith("not positively confirmed")


def test_stale_board_cache_status_still_promotes_perfect_archive():
    """The original brotli-fix case this rule was built for: a stale board
    cache score sitting on a row whose real archive is already perfect.
    This must keep working — the fix only excludes needs_reverify."""
    entries = [
        {
            "slug": "google__brotli",
            "status": "board_cache_only",
            "official_passed": 42,
            "official_total": 955,
        }
    ]
    verified_short = {"brotli"}
    archive_best = {
        "brotli": _perfect_archive(
            1212, "corpus/programbench/locked/google__brotli/eval_report.json"
        )
    }

    changes = reconcile_from_archive(entries, verified_short, archive_best)

    # PROMOTE fires; BACKFILL also fires in this test because the fake path
    # doesn't exist on disk (in production the real archive path does exist,
    # so BACKFILL wouldn't redundantly re-check it) — assert PROMOTE happened
    # rather than the exact change count.
    assert any("PROMOTE board_cache_only -> strict_lock" in c[1] for c in changes)
    assert entries[0]["status"] == "strict_lock"
    assert entries[0]["official_passed"] == 1212
    assert entries[0]["official_total"] == 1212


def test_unverified_perfect_archive_does_not_promote():
    """Not in verified_locks.json at all — archive completeness alone must
    never promote, or the demoted fakes (yj/svd2rust/...) would return."""
    entries = [{"slug": "some__fake_tool", "status": "gated_reject"}]
    verified_short = set()  # not verified
    archive_best = {"fake_tool": _perfect_archive(500)}

    changes = reconcile_from_archive(entries, verified_short, archive_best)

    assert changes == []
    assert entries[0]["status"] == "gated_reject"


def test_strict_lock_without_verification_is_demoted():
    entries = [{"slug": "yj", "status": "strict_lock"}]
    verified_short = set()  # yj was removed from verified_locks.json (CANON AUDIT)
    archive_best = {}

    changes = reconcile_from_archive(entries, verified_short, archive_best)

    assert len(changes) == 1
    assert "DEMOTE strict_lock -> unverified_lock" in changes[0][1]
    assert entries[0]["status"] == "unverified_lock"
    assert entries[0]["unverified_lock"] is True


def test_verified_strict_lock_is_not_demoted():
    entries = [{"slug": "jq", "status": "strict_lock"}]
    verified_short = {"jq"}
    archive_best = {}

    changes = reconcile_from_archive(entries, verified_short, archive_best)

    assert changes == []
    assert entries[0]["status"] == "strict_lock"


def test_alias_rows_are_skipped_entirely():
    entries = [
        {
            "slug": "some_alias",
            "status": "needs_reverify",
            "alias_of": "canonical_tool",
        }
    ]
    verified_short = {"alias"}
    archive_best = {"alias": _perfect_archive(10)}

    changes = reconcile_from_archive(entries, verified_short, archive_best)

    assert changes == []
    assert entries[0]["status"] == "needs_reverify"


def test_backfill_missing_eval_report_path_on_verified_strict_lock():
    entries = [{"slug": "google__brotli", "status": "strict_lock", "eval_report_path": ""}]
    verified_short = {"brotli"}
    archive_best = {
        "brotli": _perfect_archive(
            1212, "corpus/programbench/locked/google__brotli/eval_report.json"
        )
    }

    changes = reconcile_from_archive(entries, verified_short, archive_best)

    assert any("BACKFILL eval_report_path" in c[1] for c in changes)
    assert (
        entries[0]["eval_report_path"]
        == "corpus/programbench/locked/google__brotli/eval_report.json"
    )
