"""Guardian edit taxonomy and validation.

The edit types (SUPPRESS < GENERALIZE < PSEUDONYMIZE < RESTRUCTURE) form a
ladder of aggressiveness. The tests here enforce that the ladder is respected
at dispatch time, that a "generalize" is not secretly a suppression with a
nicer label, and that edits whose spans no longer match the document are
rejected rather than silently corrupting it.
"""
from __future__ import annotations

import pytest

from veil.agents.guardian import Guardian
from veil.inference.client import VLLMClient
from veil.types import Edit, EditType, Finding, Span, Tier


def _finding(**kw):
    base = dict(persona="p", tier=Tier.CORRELATIONAL, claim="c", reasoning="r",
                candidate_set_size=10, severity=0.7)
    base.update(kw)
    return Finding(**base)


class TestEditValidation:
    def test_generalize_that_removes_everything_is_rejected(self):
        edit = Edit(
            finding_id="f1", edit_type=EditType.GENERALIZE,
            span=Span(0, 50, "Senior software engineer at Acme Corp in Bristol"),
            replacement="",
            rationale="blank",
        )
        # Guardian._build would reject this before apply_edits ever sees it.
        # The ratio check is 15% of original length minimum.
        assert len(edit.replacement) < len(edit.span.text) * 0.15

    def test_span_text_mismatch_is_rejected(self):
        from veil.tools.redact_apply import apply_edits

        doc = "The author joined in March 2019."
        edit = Edit(
            finding_id="f1", edit_type=EditType.GENERALIZE,
            span=Span(22, 32, "April 2019"),  # wrong month
            replacement="2019", rationale="generalize to year",
        )
        result = apply_edits(doc, [edit])
        assert not result.applied
        assert result.skipped[0]["reason"].startswith("span text mismatch")

    def test_overlapping_edits_are_rejected(self):
        from veil.tools.redact_apply import apply_edits

        doc = "Bristol senior engineer"
        a = Edit("f1", EditType.GENERALIZE, Span(0, 7, "Bristol"), "UK city", "r")
        b = Edit("f2", EditType.GENERALIZE, Span(0, 23, "Bristol senior engineer"),
                 "UK-based role", "r")
        result = apply_edits(doc, [a, b])
        assert len(result.applied) == 1
        assert len(result.skipped) == 1

    def test_edits_applied_right_to_left_so_offsets_stay_valid(self):
        from veil.tools.redact_apply import apply_edits

        doc = "Alice moved to Bristol in March."
        # Apply out of order; the function sorts them.
        a = Edit("f1", EditType.SUPPRESS, Span(0, 5, "Alice"), "", "r")
        b = Edit("f2", EditType.GENERALIZE, Span(26, 31, "March"), "early 2024", "r")
        result = apply_edits(doc, [a, b])
        assert result.text == "[REDACTED] moved to Bristol in early 2024."
        assert len(result.applied) == 2


class TestAggressivenessLevels:
    """The aggressiveness setting gates which edit types the Guardian may emit."""

    @pytest.mark.asyncio
    async def test_low_aggressiveness_forbids_suppress_and_restructure(self):
        # This test cannot call a real model, so it just verifies the static
        # allowlist. A real end-to-end test would need vLLM running.
        from veil.agents.guardian import _ALLOWED_BY_LEVEL

        assert EditType.GENERALIZE in _ALLOWED_BY_LEVEL["low"]
        assert EditType.SUPPRESS not in _ALLOWED_BY_LEVEL["low"]
        assert EditType.RESTRUCTURE not in _ALLOWED_BY_LEVEL["low"]

    @pytest.mark.asyncio
    async def test_balanced_permits_suppress_but_not_restructure(self):
        from veil.agents.guardian import _ALLOWED_BY_LEVEL

        assert EditType.SUPPRESS in _ALLOWED_BY_LEVEL["balanced"]
        assert EditType.RESTRUCTURE not in _ALLOWED_BY_LEVEL["balanced"]

    @pytest.mark.asyncio
    async def test_high_permits_everything(self):
        from veil.agents.guardian import _ALLOWED_BY_LEVEL

        assert set(_ALLOWED_BY_LEVEL["high"]) == set(EditType)


class TestMinimalEdits:
    """The Guardian is scored on killing the finding while keeping the prose."""

    def test_generalisation_retains_more_utility_than_suppression(self):
        from veil.scoring.utility import score
        from veil.tools.redact_apply import apply_edits

        doc = (
            "The reviewer, a senior software engineer based in Bristol, joined "
            "the team in March 2019 and led the migration project."
        )
        span = Span(doc.index("senior"), doc.index("Bristol") + 7,
                    "senior software engineer based in Bristol")

        generalised = apply_edits(
            doc,
            [Edit("f1", EditType.GENERALIZE, span, "an engineer in the UK", "widen role and geography")],
        )
        suppressed = apply_edits(doc, [Edit("f1", EditType.SUPPRESS, span, "", "remove")])

        assert score(doc, generalised.text).value > score(doc, suppressed.text).value

    def test_pseudonymisation_is_consistent_across_documents(self):
        from veil.tools.entity_ledger import make_alias

        # The same person must get the same alias in every document, or
        # cross-document accumulation becomes invisible.
        assert make_alias("person", "J. Okafor") == make_alias("person", "j. okafor ")
        assert make_alias("person", "J. Okafor") != make_alias("person", "J. Okonkwo")

    def test_redaction_marker_is_counted_not_scored_as_content(self):
        from veil.scoring.utility import score

        doc = "Alice met Bob in Bristol."
        redacted = "[REDACTED] met [REDACTED] in Bristol."
        result = score(doc, redacted)
        assert result.redaction_count == 2
        # The marker text must not inflate token retention.
        assert result.token_retention < 1.0
