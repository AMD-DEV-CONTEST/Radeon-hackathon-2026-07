"""Layout forensics — the Tier M evidence source.

This is the tool that produces the demo's opening punch: text that is still
present in the PDF content stream underneath a drawn redaction rectangle. It is
mechanical, it is verifiable, and it needs no model to be true.

Three attacks are implemented:
  1. redaction underlay  — glyphs whose bounding box sits inside an opaque
     filled rectangle. The rectangle hides them from a human, not from pdfplumber.
  2. character-width leak — the pixel width of a covered region constrains the
     set of words that could fit it.
  3. font-run anomaly    — a span in a font/size used nowhere else nearby marks
     a late edit.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from veil.tools.registry import REGISTRY
from veil.types import Span

# Mean glyph advance as a fraction of font size, measured across the demo
# corpus. Used only to bound a word-length estimate, never to assert a word.
_MEAN_ADVANCE_RATIO = 0.5

# How far outside a rectangle a glyph may sit and still count as covered.
# Redaction boxes are often drawn a hair tight around the text they hide, so a
# little slack avoids missing a real leak; more than a point or two and we
# start swallowing the neighbouring word.
_EDGE_TOLERANCE_PT = 1.5

# Recovered glyphs must span at least this fraction of the box width before we
# call it an underlay. Below it, we are almost certainly looking at a stray
# character from adjacent text rather than hidden content, and a false Tier M
# finding is worse than a missed one — Tier M is the tier that claims certainty.
_MIN_COVERAGE_RATIO = 0.35


@dataclass
class Rect:
    x0: float
    y0: float
    x1: float
    y1: float

    def contains(self, cx: float, cy: float) -> bool:
        return self.x0 <= cx <= self.x1 and self.y0 <= cy <= self.y1

    @property
    def width(self) -> float:
        return self.x1 - self.x0


def _opaque_rects(page: Any) -> list[Rect]:
    """Filled rectangles dark enough to be a redaction box."""
    out: list[Rect] = []
    for r in list(page.rects) + list(getattr(page, "curves", [])):
        if not r.get("fill"):
            continue
        colour = r.get("non_stroking_color")
        if isinstance(colour, (int, float)):
            dark = colour < 0.35
        elif isinstance(colour, (list, tuple)) and colour:
            dark = sum(colour) / len(colour) < 0.35
        else:
            dark = False
        if dark and (r["x1"] - r["x0"]) > 8 and (r["bottom"] - r["top"]) > 4:
            out.append(Rect(r["x0"], r["top"], r["x1"], r["bottom"]))
    return out


def _covered_chars(rect: Rect, chars: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Glyphs a rectangle genuinely covers.

    Containment is tested on the glyph's full horizontal extent, not its
    centroid. This matters: in "reported by |REDACTED|", the final "y" of "by"
    sits close enough to the box edge that its midpoint falls inside, and a
    centroid test reports a recovered underlay of "y". That is a false positive
    at Tier M — the tier that asserts certainty — so the bar is full
    containment, with a small tolerance for boxes drawn a hair tight around the
    text they cover.
    """
    tol = _EDGE_TOLERANCE_PT
    out = []
    for ch in chars:
        cy = (ch["top"] + ch["bottom"]) / 2
        if (
            ch["x0"] >= rect.x0 - tol
            and ch["x1"] <= rect.x1 + tol
            and rect.y0 <= cy <= rect.y1
        ):
            out.append(ch)
    return out


def _covers_enough(rect: Rect, chars: list[dict[str, Any]]) -> bool:
    """Does the recovered run account for a real share of the box?

    A single glyph inside a wide box is far likelier to be a stray than a
    redaction failure. Real underlay text fills most of the box that was drawn
    to hide it.
    """
    if not chars:
        return False
    span = max(c["x1"] for c in chars) - min(c["x0"] for c in chars)
    return span >= rect.width * _MIN_COVERAGE_RATIO


def extract_underlay(pdf_path: str) -> list[Span]:
    """Return text that a drawn rectangle covers but does not remove."""
    import pdfplumber

    found: list[Span] = []
    with pdfplumber.open(pdf_path) as pdf:
        for pno, page in enumerate(pdf.pages, start=1):
            rects = _opaque_rects(page)
            if not rects:
                continue
            claimed: set[int] = set()
            for rect in rects:
                chars = [
                    ch
                    for ch in _covered_chars(rect, page.chars)
                    if id(ch) not in claimed
                ]
                if not _covers_enough(rect, chars):
                    continue
                claimed.update(id(ch) for ch in chars)
                chars.sort(key=lambda c: (round(c["top"], 1), c["x0"]))
                text = "".join(c["text"] for c in chars).strip()
                if text:
                    found.append(
                        Span(
                            start=0,
                            end=len(text),
                            text=text,
                            page=pno,
                            source="redaction_underlay",
                        )
                    )
    return found


def width_leak(pdf_path: str) -> list[dict[str, Any]]:
    """For redaction boxes that are genuinely empty, estimate what fits.

    A properly flattened redaction still leaks the length of what it replaced.
    We report a character-count range, never a guessed word — the persona is
    responsible for combining this with the corpus.
    """
    import pdfplumber

    out: list[dict[str, Any]] = []
    with pdfplumber.open(pdf_path) as pdf:
        for pno, page in enumerate(pdf.pages, start=1):
            sizes = [c["size"] for c in page.chars] or [10.0]
            body_size = max(set(sizes), key=sizes.count)
            for rect in _opaque_rects(page):
                # Same predicate the underlay attack uses, so the two can never
                # disagree about whether a box was empty.
                if _covers_enough(rect, _covered_chars(rect, page.chars)):
                    continue  # underlay attack already handled this one
                est = rect.width / (body_size * _MEAN_ADVANCE_RATIO)
                out.append(
                    {
                        "page": pno,
                        "box_width_pt": round(rect.width, 1),
                        "estimated_chars": [max(1, int(est * 0.8)), int(est * 1.2)],
                        "method": "box width / mean glyph advance at body font size",
                    }
                )
    return out


def font_runs(pdf_path: str, min_len: int = 3) -> list[dict[str, Any]]:
    """Spans whose font or size differs from the surrounding body text."""
    import pdfplumber

    anomalies: list[dict[str, Any]] = []
    with pdfplumber.open(pdf_path) as pdf:
        for pno, page in enumerate(pdf.pages, start=1):
            chars = page.chars
            if not chars:
                continue
            keys = [(c.get("fontname"), round(c.get("size", 0), 1)) for c in chars]
            body = max(set(keys), key=keys.count)
            run: list[dict[str, Any]] = []
            for ch, key in zip(chars, keys):
                if key != body:
                    run.append(ch)
                elif run:
                    text = "".join(c["text"] for c in run).strip()
                    if len(text) >= min_len:
                        anomalies.append(
                            {
                                "page": pno,
                                "text": text,
                                "font": run[0].get("fontname"),
                                "size": round(run[0].get("size", 0), 1),
                                "body_font": body[0],
                                "body_size": body[1],
                            }
                        )
                    run = []
    return anomalies


@REGISTRY.register(
    name="layout_forensics",
    description=(
        "Run mechanical forensics on the source PDF: recover text hidden under "
        "drawn redaction rectangles, estimate the character length of genuinely "
        "empty redaction boxes, and flag font runs that indicate a late edit. "
        "Returns only what was extracted — nothing inferred."
    ),
    parameters={
        "type": "object",
        "properties": {
            "pdf_path": {"type": "string", "description": "Path to the source PDF."},
            "attack": {
                "type": "string",
                "enum": ["underlay", "width", "fonts", "all"],
                "description": "Which forensic pass to run. Default 'all'.",
            },
        },
        "required": ["pdf_path"],
    },
)
def layout_forensics(pdf_path: str, attack: str = "all") -> dict[str, Any]:
    out: dict[str, Any] = {}
    if attack in ("underlay", "all"):
        out["underlay_text"] = [
            {"page": s.page, "text": s.text} for s in extract_underlay(pdf_path)
        ]
    if attack in ("width", "all"):
        out["width_leaks"] = width_leak(pdf_path)
    if attack in ("fonts", "all"):
        out["font_anomalies"] = font_runs(pdf_path)
    return out
