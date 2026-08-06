"""Tier invariants and adjudication.

These tests exist because of the sharpest critique the design received: a tool
that says "this is Sarah Chen" on stylometric evidence will get someone hurt.
The answer is structural — the type system refuses to build such a finding —
and this file is what proves the structure holds.
"""
from __future__ import annotations

import pytest

from veil.agents.adjudicator import adjudicate
from veil.types import Finding, Role, Span, Tier


def _c(**kw):
    base = dict(
        persona="Data-Broker", tier=Tier.CORRELATIONAL, claim="c", reasoning="r",
        candidate_set_size=3,
    )
    base.update(kw)
    return Finding(**base)


class TestTierInvariants:
    def test_correlational_requires_candidate_set(self):
        with pytest.raises(ValueError, match="candidate_set_size"):
            Finding(persona="p", tier=Tier.CORRELATIONAL, claim="c", reasoning="r")

    def test_stylistic_requires_caveat(self):
        with pytest.raises(ValueError, match="caveat"):
            Finding(persona="p", tier=Tier.STYLISTIC, claim="c", reasoning="r")

    def test_mechanical_needs_neither(self):
        f = Finding(persona="p", tier=Tier.MECHANICAL, claim="c", reasoning="r")
        assert f.tier is Tier.MECHANICAL

    def test_candidate_set_of_zero_is_allowed_but_explicit(self):
        # 0 is falsy; the check must be `is None`, not truthiness.
        assert _c(candidate_set_size=0).candidate_set_size == 0


class TestRoleProjection:
    def test_auditor_sees_everything(self):
        f = _c(reasoning="she is the only person who...", spans=[Span(0, 4, "test")])
        d = f.redacted_for(Role.AUDITOR)
        assert d["reasoning"] and d["spans"]

    def test_redactor_never_sees_reasoning(self):
        f = _c(reasoning="the re-identification recipe", spans=[Span(0, 4, "test")])
        d = f.redacted_for(Role.REDACTOR)
        assert "reasoning" not in d and "spans" not in d
        assert d["claim"] == "c"

    def test_viewer_sees_neither_claim_nor_reasoning(self):
        d = _c().redacted_for(Role.VIEWER)
        assert "claim" not in d and "reasoning" not in d
        assert d["severity"] is not None


class TestAdjudication:
    def test_unsupported_mechanical_claim_is_demoted(self):
        f = Finding(
            persona="Layout-Forensicist", tier=Tier.MECHANICAL,
            claim="The author is definitely J. Okafor", reasoning="r",
            spans=[Span(0, 10, "body text", source="body")], severity=0.9,
        )
        result = adjudicate([f])
        assert result.accepted[0].tier is Tier.CORRELATIONAL
        assert result.demoted

    def test_mechanical_claim_with_underlay_span_survives(self):
        f = Finding(
            persona="Layout-Forensicist", tier=Tier.MECHANICAL,
            claim="Text under the redaction box reads 'J. Okafor'", reasoning="r",
            spans=[Span(0, 9, "J. Okafor", source="redaction_underlay")],
        )
        result = adjudicate([f])
        assert result.accepted[0].tier is Tier.MECHANICAL
        assert result.accepted[0].severity >= 0.9

    def test_certainty_language_is_softened_in_tier_s(self):
        f = Finding(
            persona="Stylometrist", tier=Tier.STYLISTIC,
            claim="The author is definitely the head of engineering",
            reasoning="r", caveat="Stylometry on 400 words is unreliable.",
            severity=0.9,
        )
        accepted = adjudicate([f]).accepted[0]
        assert "is definitely" not in accepted.claim
        assert accepted.severity <= 0.4

    def test_duplicate_findings_merge_and_credit_both_personas(self):
        span = [Span(10, 30, "senior engineer, Bristol")]
        a = _c(persona="Data-Broker", claim="Role plus city narrows to 4 people",
               spans=span, candidate_set_size=4)
        b = _c(persona="Insider", claim="Role plus city narrows this to four people",
               spans=span, candidate_set_size=6)
        result = adjudicate([a, b])
        assert len(result.accepted) == 1
        assert result.merged == 1
        assert "Data-Broker" in result.accepted[0].persona
        assert "Insider" in result.accepted[0].persona
        # The tightest defensible bound wins.
        assert result.accepted[0].candidate_set_size == 4

    def test_large_candidate_set_caps_severity(self):
        f = _c(candidate_set_size=5000, severity=0.95)
        assert adjudicate([f]).accepted[0].severity <= 0.2

    def test_ordering_puts_mechanical_first(self):
        s = Finding(persona="Stylometrist", tier=Tier.STYLISTIC, claim="s",
                    reasoning="r", caveat="unreliable")
        m = Finding(persona="Layout-Forensicist", tier=Tier.MECHANICAL, claim="m",
                    reasoning="r", spans=[Span(0, 4, "name", source="metadata")])
        order = [f.tier for f in adjudicate([s, _c(), m]).accepted]
        assert order == [Tier.MECHANICAL, Tier.CORRELATIONAL, Tier.STYLISTIC]

    def test_empty_claim_is_rejected(self):
        assert not adjudicate([_c(claim="   ")]).accepted
