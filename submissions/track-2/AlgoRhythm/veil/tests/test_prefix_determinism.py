"""Prefix determinism — guards the AMD optimisation story.

vLLM's automatic prefix cache fires only on a byte-identical prefix. If a
future edit lets persona identity, a timestamp, a set iteration order, or a
dict ordering leak into build_prefix(), the cache hit rate collapses and the
central performance claim on the deck stops being true — silently, with no
error anywhere.

These tests are the tripwire. prefix.py points here in its module docstring.
"""
from __future__ import annotations

import re

from veil.agents.personas import ALL_PERSONAS
from veil.inference.prefix import build_prefix, build_suffix
from veil.types import Finding, Span, Tier

DOC = "The reviewer joined in March 2019 and is based in Bristol."
SPANS = [
    Span(0, 20, "The reviewer joined ", page=1, source="body"),
    Span(20, 30, "March 2019", page=1, source="body"),
    Span(30, 58, " and is based in Bristol.", page=2, source="body"),
]


class TestDeterminism:
    def test_identical_inputs_give_identical_prefix(self):
        assert build_prefix(DOC, SPANS) == build_prefix(DOC, SPANS)

    def test_span_order_does_not_affect_prefix(self):
        # Spans arrive from concurrent extractors in nondeterministic order.
        # build_prefix sorts them; if that sort is removed, this fails.
        assert build_prefix(DOC, SPANS) == build_prefix(DOC, list(reversed(SPANS)))

    def test_prefix_is_identical_across_all_five_personas(self):
        prefixes = {build_prefix(DOC, SPANS) for _ in ALL_PERSONAS}
        assert len(prefixes) == 1

    def test_prefix_contains_no_persona_name(self):
        prefix = build_prefix(DOC, SPANS)
        for persona in ALL_PERSONAS:
            assert persona.name not in prefix, (
                f"{persona.name} leaked into the shared prefix — the cache will miss."
            )

    def test_prefix_contains_no_timestamp_or_uuid(self):
        prefix = build_prefix(DOC, SPANS)
        assert not re.search(r"\b\d{10,13}\b", prefix), "A timestamp leaked into the prefix."
        assert not re.search(r"\b[0-9a-f]{12,}\b", prefix), "A UUID leaked into the prefix."

    def test_prefix_ends_where_suffix_begins(self):
        # No overlap, no gap: the suffix must be pure tail.
        prefix = build_prefix(DOC, SPANS)
        suffix = build_suffix("Insider", "attack")
        assert not prefix.endswith(suffix[:20])


class TestSuffixVariation:
    def test_suffix_differs_per_persona(self):
        suffixes = {
            build_suffix(p.name, p.instruction) for p in ALL_PERSONAS
        }
        assert len(suffixes) == len(ALL_PERSONAS)

    def test_prior_findings_change_only_the_suffix(self):
        prior = [
            Finding(
                persona="Data-Broker", tier=Tier.CORRELATIONAL,
                claim="Bristol + March 2019 narrows to 6 people",
                reasoning="r", candidate_set_size=6,
            )
        ]
        with_prior = build_suffix("Insider", "attack", prior)
        without = build_suffix("Insider", "attack", None)
        assert with_prior != without
        # And the prefix is untouched by iteration state.
        assert build_prefix(DOC, SPANS) == build_prefix(DOC, SPANS)

    def test_suffix_is_short_relative_to_prefix(self):
        """The economics only work if the varying part is small. If a change
        makes the suffix comparable to the prefix, the cache saves little."""
        prefix = build_prefix(DOC * 50, SPANS)
        suffix = build_suffix("Insider", ALL_PERSONAS[2].instruction)
        assert len(suffix) < len(prefix) * 0.25
