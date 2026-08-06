"""Layout forensics — the Tier M evidence path.

The demo's opening moment is a redaction box with live text underneath it, so
these tests build that exact PDF and assert we recover the text. If this file
goes red, the demo has no punch.
"""
from __future__ import annotations

import pytest

from veil.tools.layout_forensics import Rect, font_runs, extract_underlay, width_leak

pytest.importorskip("reportlab", reason="reportlab is needed to synthesise fixtures")


@pytest.fixture
def bad_redaction(tmp_path):
    """A PDF redacted the way people actually do it: a black box drawn on top
    of text that is still in the content stream."""
    from reportlab.lib.pagesizes import LETTER
    from reportlab.pdfgen import canvas

    path = tmp_path / "bad_redaction.pdf"
    c = canvas.Canvas(str(path), pagesize=LETTER)
    c.setFont("Helvetica", 12)
    c.drawString(72, 700, "Incident reported by J. Okafor on 14 March 2019.")
    # Cover the name with an opaque rectangle — and nothing else.
    c.setFillColorRGB(0, 0, 0)
    c.rect(175, 695, 62, 15, fill=1, stroke=0)
    c.save()
    return str(path)


@pytest.fixture
def proper_redaction(tmp_path):
    """The same page with the text genuinely removed — only the box remains."""
    from reportlab.lib.pagesizes import LETTER
    from reportlab.pdfgen import canvas

    path = tmp_path / "proper_redaction.pdf"
    c = canvas.Canvas(str(path), pagesize=LETTER)
    c.setFont("Helvetica", 12)
    c.drawString(72, 700, "Incident reported by ")
    c.drawString(240, 700, " on 14 March 2019.")
    c.setFillColorRGB(0, 0, 0)
    c.rect(175, 695, 62, 15, fill=1, stroke=0)
    c.save()
    return str(path)


class TestUnderlayRecovery:
    def test_recovers_text_under_a_drawn_box(self, bad_redaction):
        spans = extract_underlay(bad_redaction)
        assert spans, "Failed to recover text under the redaction rectangle."
        recovered = " ".join(s.text for s in spans)
        assert "Okafor" in recovered

    def test_recovered_spans_are_tagged_as_mechanical_evidence(self, bad_redaction):
        spans = extract_underlay(bad_redaction)
        assert all(s.source == "redaction_underlay" for s in spans)
        assert all(s.page == 1 for s in spans)

    def test_properly_redacted_pdf_yields_nothing(self, proper_redaction):
        assert extract_underlay(proper_redaction) == []


class TestWidthLeak:
    def test_empty_box_still_leaks_a_length_estimate(self, proper_redaction):
        leaks = width_leak(proper_redaction)
        assert leaks, "A genuinely empty redaction box still constrains word length."
        lo, hi = leaks[0]["estimated_chars"]
        assert lo < hi and lo >= 1

    def test_box_with_text_under_it_is_left_to_the_underlay_attack(self, bad_redaction):
        # No double-reporting: if we recovered the text, we do not also guess
        # its length.
        assert width_leak(bad_redaction) == []


class TestRectGeometry:
    def test_contains_is_inclusive_at_the_boundary(self):
        r = Rect(0, 0, 10, 10)
        assert r.contains(0, 0) and r.contains(10, 10) and r.contains(5, 5)
        assert not r.contains(10.1, 5)

    def test_width(self):
        assert Rect(5, 0, 17.5, 10).width == 12.5


class TestFontRuns:
    def test_uniform_document_has_no_anomalies(self, tmp_path):
        from reportlab.lib.pagesizes import LETTER
        from reportlab.pdfgen import canvas

        path = tmp_path / "uniform.pdf"
        c = canvas.Canvas(str(path), pagesize=LETTER)
        c.setFont("Helvetica", 12)
        for i, y in enumerate(range(700, 600, -20)):
            c.drawString(72, y, f"A perfectly ordinary line of body text, number {i}.")
        c.save()
        assert font_runs(str(path)) == []

    def test_late_edit_in_a_different_font_is_flagged(self, tmp_path):
        from reportlab.lib.pagesizes import LETTER
        from reportlab.pdfgen import canvas

        path = tmp_path / "mixed.pdf"
        c = canvas.Canvas(str(path), pagesize=LETTER)
        c.setFont("Helvetica", 12)
        c.drawString(72, 700, "The report was approved by the committee on ")
        c.setFont("Times-Bold", 12)   # pasted in later
        c.drawString(72, 680, "14 March 2019")
        c.setFont("Helvetica", 12)
        c.drawString(72, 660, " following a full review of the submitted evidence.")
        c.save()

        anomalies = font_runs(str(path))
        assert anomalies
        assert any("March" in a["text"] for a in anomalies)
