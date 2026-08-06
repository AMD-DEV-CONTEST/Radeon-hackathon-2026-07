"""Planner triage — which personas run, and for how many iterations.

The planner is allowed to skip a persona only when that persona cannot produce
evidence for the document in front of it. That is a narrow licence and it is
easy to widen by accident, so these tests pin it down: the two documented skips
must happen, and nothing else may.

The failure mode this guards against is the expensive one. A planner that
quietly filtered out the Data-Broker would produce a run that finds nothing,
reports MINIMAL risk, and hands back a document that is still identifying —
with a reassuring green number attached to it.
"""
from __future__ import annotations

from veil.agents.personas import ALL_PERSONAS
from veil.agents.planner import _STYLOMETRY_FLOOR_CHARS, Plan, plan, revise_budget
from veil.types import Span

LONG = "The reviewing director joined in March 2019. " * 40
SHORT = "One short line."


def _names(p: Plan) -> list[str]:
    return [x.name for x in p.personas]


def _spans(text: str, source: str = "body") -> list[Span]:
    return [Span(0, len(text), text, page=1, source=source)]


class TestPersonaSelection:
    def test_long_pdf_runs_every_persona(self):
        p = plan(LONG, _spans(LONG), source_path="report.pdf")
        assert len(p.personas) == 5
        assert not p.skipped

    def test_plain_text_skips_the_forensicist(self):
        p = plan(LONG, _spans(LONG), source_path="notes.txt")
        assert "Layout-Forensicist" not in _names(p)
        assert any(s["persona"] == "Layout-Forensicist" for s in p.skipped)

    def test_plain_text_still_runs_every_inference_persona(self):
        """Skipping the container attack must not touch the others."""
        p = plan(LONG, _spans(LONG), source_path="notes.txt")
        for expected in ("Data-Broker", "Insider", "Journalist", "Stylometrist"):
            assert expected in _names(p), f"{expected} was wrongly filtered out"

    def test_short_document_skips_stylometry(self):
        p = plan(SHORT, _spans(SHORT), source_path="a.pdf")
        assert "Stylometrist" not in _names(p)

    def test_document_just_over_the_floor_keeps_stylometry(self):
        text = "x" * (_STYLOMETRY_FLOOR_CHARS + 1)
        p = plan(text, _spans(text), source_path="a.pdf")
        assert "Stylometrist" in _names(p)

    def test_document_just_under_the_floor_drops_it(self):
        text = "x" * (_STYLOMETRY_FLOOR_CHARS - 1)
        p = plan(text, _spans(text), source_path="a.pdf")
        assert "Stylometrist" not in _names(p)

    def test_mechanical_evidence_overrides_a_misleading_extension(self):
        """A .txt that already yielded underlay spans is worth attacking.

        Extension is a hint, not a fact — the loader's findings outrank it.
        """
        spans = _spans(LONG) + [Span(0, 5, "Osei", source="redaction_underlay")]
        p = plan(LONG, spans, source_path="dump.txt")
        assert "Layout-Forensicist" in _names(p)

    def test_metadata_spans_also_count_as_structure(self):
        spans = _spans(LONG) + [Span(0, 5, "J. Okafor", source="metadata")]
        p = plan(LONG, spans, source_path="dump.txt")
        assert "Layout-Forensicist" in _names(p)

    def test_missing_source_path_is_not_treated_as_structured(self):
        p = plan(LONG, _spans(LONG), source_path=None)
        assert "Layout-Forensicist" not in _names(p)

    def test_every_skip_carries_a_stated_reason(self):
        p = plan(SHORT, _spans(SHORT), source_path="a.txt")
        assert p.skipped
        for entry in p.skipped:
            assert entry["persona"] and len(entry["reason"]) > 20

    def test_planner_never_produces_a_run_with_no_attackers(self):
        """An empty persona set would score every document MINIMAL."""
        p = plan("", [], source_path="empty.txt")
        assert len(p.personas) >= 1

    def test_selection_preserves_the_canonical_order(self):
        p = plan(LONG, _spans(LONG), source_path="a.pdf")
        canonical = [x.name for x in ALL_PERSONAS]
        assert _names(p) == [n for n in canonical if n in _names(p)]

    def test_summary_is_json_serialisable(self):
        import json

        json.dumps(plan(LONG, _spans(LONG), source_path="a.pdf").summary())


class TestIterationBudget:
    def test_requested_iterations_are_respected(self):
        p = plan(LONG, _spans(LONG), source_path="a.pdf", requested_iterations=2)
        assert p.max_iterations == 2

    def test_critical_risk_keeps_the_whole_budget(self):
        p = plan(LONG, _spans(LONG), source_path="a.pdf", requested_iterations=3)
        assert revise_budget(p, 0.8, 1) == 3

    def test_moderate_risk_earns_one_more_pass(self):
        p = plan(LONG, _spans(LONG), source_path="a.pdf", requested_iterations=3)
        assert revise_budget(p, 0.4, 1) == 2

    def test_low_risk_stops_now(self):
        """Repair costs utility; grinding at weak findings is not free."""
        p = plan(LONG, _spans(LONG), source_path="a.pdf", requested_iterations=3)
        assert revise_budget(p, 0.1, 1) == 1

    def test_revision_never_exceeds_the_original_budget(self):
        p = plan(LONG, _spans(LONG), source_path="a.pdf", requested_iterations=2)
        for risk in (0.0, 0.2, 0.5, 0.9, 1.0):
            assert revise_budget(p, risk, 1) <= 2
