#!/usr/bin/env python3
"""Render docs/project-profile.md into a polished A4 PDF (docs/project-profile.pdf).

Official Project Profile Document for the AMD Radeon Hackathon 2026, Track 1
submission. Uses reportlab Platypus only (no external converters).

Handles the markdown subset used by the profile document:
  # / ## / ### headings, paragraphs, **bold**, *italic*, `inline code`,
  fenced code blocks, pipe tables, bullet lists, numbered lists,
  > blockquotes and --- horizontal rules.

Run:
    python scripts/make_profile_pdf.py
"""

from __future__ import annotations

import os
import re
import sys

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "docs", "project-profile.md")
OUT = os.path.join(ROOT, "docs", "project-profile.pdf")

TITLE = "PolicyCut — Policy-Driven Local Privacy Video Editor"
SUBTITLE = "AMD Radeon Hackathon 2026 · Track 1 · Multimodal Content Creation Tools"
FOOTER_LEFT = "PolicyCut · AMD Radeon Hackathon 2026 · Track 1"

# ---------------------------------------------------------------------------
# Palette (light print theme)
# ---------------------------------------------------------------------------
ACCENT = colors.HexColor("#E8442E")          # AMD red
TEXT = colors.HexColor("#1B1B1B")            # near-black body text
MUTED = colors.HexColor("#6B6B6B")
CODE_TEXT = colors.HexColor("#26241F")
CODE_BG = colors.HexColor("#F5F4F1")         # light-gray code background
CODE_BORDER = colors.HexColor("#E2E0DB")
INLINE_CODE_BG = "#F0EEEA"
TABLE_GRID = colors.HexColor("#DCDAD5")
TABLE_HEADER_BG = colors.HexColor("#FBE8E4")  # soft accent tint
TABLE_ROW_ALT = colors.HexColor("#FAF9F7")
QUOTE_TEXT = colors.HexColor("#44403C")
FOOTER_GRAY = colors.HexColor("#8C8A86")
FOOTER_RULE = colors.HexColor("#E5E3DF")

# ---------------------------------------------------------------------------
# Fonts. Base-14 Helvetica for body text (crisp print look); a Unicode
# monospace TTF for code (the architecture diagram uses box-drawing chars,
# arrows and "≤" that do not exist in WinAnsi Courier); a Unicode fallback
# face for the few non-WinAnsi chars that appear in body text.
# ---------------------------------------------------------------------------
BODY = "Helvetica"
BODY_BOLD = "Helvetica-Bold"
BODY_ITALIC = "Helvetica-Oblique"

MONO = "Courier"          # replaced below when a Unicode TTF registers
MONO_UNICODE = False
FALLBACK_FACE = None      # Unicode face used for isolated body-text glyphs

# Plain-text transliterations used only when no Unicode font is available.
_ASCII_MAP = {
    "─": "-", "━": "-", "│": "|", "┃": "|",
    "├": "+", "┤": "+", "└": "+", "┘": "+", "┌": "+", "┐": "+",
    "┬": "+", "┴": "+", "┼": "+",
    "→": "->", "←": "<-", "↔": "<->", "⇒": "=>",
    "≤": "<=", "≥": ">=", "−": "-", "≈": "~", "×": "x",
    "•": "*", "∙": "*", "·": ".",
}


def _register_fonts() -> None:
    global MONO, MONO_UNICODE, FALLBACK_FACE
    mono_candidates = [
        ("PCMono", "/System/Library/Fonts/Menlo.ttc", 0),
        ("PCMono", "/System/Library/Fonts/Supplemental/Courier New.ttf", None),
        ("PCMono", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", None),
    ]
    for name, path, sub in mono_candidates:
        if not os.path.exists(path):
            continue
        try:
            if sub is None:
                pdfmetrics.registerFont(TTFont(name, path))
            else:
                pdfmetrics.registerFont(TTFont(name, path, subfontIndex=sub))
            MONO, MONO_UNICODE = name, True
            break
        except Exception:
            continue
    fallback_candidates = [
        ("PCUni", "/Library/Fonts/Arial Unicode.ttf", None),
        ("PCUni", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", None),
    ]
    for name, path, sub in fallback_candidates:
        if not os.path.exists(path):
            continue
        try:
            pdfmetrics.registerFont(TTFont(name, path))
            FALLBACK_FACE = name
            break
        except Exception:
            continue
    if FALLBACK_FACE is None and MONO_UNICODE:
        FALLBACK_FACE = MONO  # mono covers the needed glyphs; better than "?"


def _cp1252_ok(ch: str) -> bool:
    try:
        ch.encode("cp1252")
        return True
    except UnicodeEncodeError:
        return False


def _xml_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _body_char(ch: str) -> str:
    """Return paragraph-markup for one body-text character, substituting a
    Unicode span (or an ASCII transliteration) for non-WinAnsi glyphs."""
    if ord(ch) < 128 or _cp1252_ok(ch):
        return ch
    if FALLBACK_FACE:
        return '<font face="%s">%s</font>' % (FALLBACK_FACE, ch)
    return _xml_escape(_ASCII_MAP.get(ch, "?"))


def _code_plain(text: str) -> str:
    """Plain (non-XML) code text, transliterated only if the mono font
    cannot represent non-ASCII glyphs."""
    if MONO_UNICODE:
        return text
    out = []
    for ch in text:
        if ord(ch) < 128 or _cp1252_ok(ch):
            out.append(ch)
        else:
            out.append(_ASCII_MAP.get(ch, "?"))
    return "".join(out)


# ---------------------------------------------------------------------------
# Inline markdown -> reportlab paragraph markup
# ---------------------------------------------------------------------------
_CODE_RE = re.compile(r"`([^`]+)`")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*", re.S)
_ITALIC_RE = re.compile(r"\*([^\s*](?:[^*]*[^\s*])?)\*")
_PLACEHOLDER_RE = re.compile("\x02(\\d+)\x03")


def inline_markup(text: str, code_size: float) -> str:
    """Convert **bold**, *italic* and `code` spans to paragraph markup."""
    t = _xml_escape(text)

    stash: list[str] = []

    def _stash(m: re.Match) -> str:
        stash.append(m.group(1))
        return "\x02%d\x03" % (len(stash) - 1)

    t = _CODE_RE.sub(_stash, t)
    t = _BOLD_RE.sub(r"<b>\1</b>", t)
    t = _ITALIC_RE.sub(r"<i>\1</i>", t)
    t = "".join(_body_char(ch) for ch in t)

    def _restore(m: re.Match) -> str:
        code = stash[int(m.group(1))]
        if not MONO_UNICODE:
            code = "".join(
                ch if (ord(ch) < 128 or _cp1252_ok(ch))
                else _xml_escape(_ASCII_MAP.get(ch, "?"))
                for ch in code
            )
        return '<font face="%s" size="%.1f" backColor="%s">%s</font>' % (
            MONO, code_size, INLINE_CODE_BG, code
        )

    return _PLACEHOLDER_RE.sub(_restore, t)


def strip_inline(text: str) -> str:
    """Markdown inline syntax removed — used for width estimation only."""
    return re.sub(r"[`*]", "", text)


# ---------------------------------------------------------------------------
# Block-level markdown parser
# ---------------------------------------------------------------------------
_HR_RE = re.compile(r"^(-{3,}|\*{3,}|_{3,})$")
_HEADING_RE = re.compile(r"^(#{1,4})\s+(.*)$")
_BULLET_RE = re.compile(r"^[-*+]\s+(.*)$")
_ORDERED_RE = re.compile(r"^(\d+)[.)]\s+(.*)$")
_TABLE_SEP_CELL_RE = re.compile(r"^:?-{2,}:?$")


def parse_markdown(md: str) -> list[tuple]:
    lines = md.splitlines()
    blocks: list[tuple] = []
    para: list[str] = []
    i = 0

    def flush() -> None:
        if para:
            blocks.append(("p", " ".join(para)))
            para.clear()

    while i < len(lines):
        raw = lines[i]
        s = raw.strip()

        if s.startswith("```"):                       # fenced code block
            flush()
            i += 1
            buf: list[str] = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                buf.append(lines[i].rstrip())
                i += 1
            i += 1  # closing fence
            blocks.append(("code", buf))
            continue

        if not s:
            flush()
            i += 1
            continue

        m = _HEADING_RE.match(s)
        if m:
            flush()
            blocks.append(("h%d" % len(m.group(1)), m.group(2).strip()))
            i += 1
            continue

        if _HR_RE.match(s):
            flush()
            blocks.append(("hr", None))
            i += 1
            continue

        if s.startswith("|"):                          # pipe table
            flush()
            rows: list[list[str]] = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(_TABLE_SEP_CELL_RE.match(c) for c in cells):
                    rows.append(cells)
                i += 1
            if rows:
                blocks.append(("table", rows))
            continue

        if s.startswith(">"):                          # blockquote
            flush()
            q: list[str] = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                q.append(lines[i].strip().lstrip(">").strip())
                i += 1
            blocks.append(("quote", " ".join(x for x in q if x)))
            continue

        if _BULLET_RE.match(s):                        # bullet list
            flush()
            items: list[str] = []
            while i < len(lines):
                t = lines[i].strip()
                m = _BULLET_RE.match(t)
                if m:
                    items.append(m.group(1))
                elif t and lines[i].startswith(("  ", "\t")) and items:
                    items[-1] += " " + t               # lazy continuation
                else:
                    break
                i += 1
            blocks.append(("ul", items))
            continue

        m = _ORDERED_RE.match(s)
        if m:                                          # numbered list
            flush()
            oitems: list[tuple[str, str]] = []
            while i < len(lines):
                t = lines[i].strip()
                m = _ORDERED_RE.match(t)
                if m:
                    oitems.append((m.group(1), m.group(2)))
                elif t and lines[i].startswith(("  ", "\t")) and oitems:
                    oitems[-1] = (oitems[-1][0], oitems[-1][1] + " " + t)
                else:
                    break
                i += 1
            blocks.append(("ol", oitems))
            continue

        para.append(s)
        i += 1

    flush()
    return blocks


def drop_duplicate_title(blocks: list[tuple]) -> list[tuple]:
    """The PDF gets a styled title header, so skip the markdown H1, the bold
    hackathon subtitle paragraph and the horizontal rule that follow it."""
    out = list(blocks)
    if out and out[0][0] == "h1":
        out.pop(0)
    if out and out[0][0] == "p" and out[0][1].lstrip("*").startswith("AMD Radeon Hackathon"):
        out.pop(0)
    if out and out[0][0] == "hr":
        out.pop(0)
    return out


# ---------------------------------------------------------------------------
# Flowable builders
# ---------------------------------------------------------------------------
def make_styles() -> dict:
    st = {}
    st["body"] = ParagraphStyle(
        "body", fontName=BODY, fontSize=10, leading=14.4,
        textColor=TEXT, alignment=TA_LEFT, spaceAfter=7,
    )
    st["h2"] = ParagraphStyle(
        "h2", fontName=BODY_BOLD, fontSize=13.5, leading=17,
        textColor=ACCENT, spaceBefore=16, spaceAfter=3, keepWithNext=1,
    )
    st["h3"] = ParagraphStyle(
        "h3", fontName=BODY_BOLD, fontSize=11.5, leading=15,
        textColor=TEXT, spaceBefore=12, spaceAfter=4, keepWithNext=1,
    )
    st["h4"] = ParagraphStyle(
        "h4", fontName=BODY_BOLD, fontSize=10.5, leading=14,
        textColor=TEXT, spaceBefore=10, spaceAfter=3, keepWithNext=1,
    )
    st["bullet"] = ParagraphStyle(
        "bullet", parent=st["body"], leftIndent=16, bulletIndent=4,
        spaceAfter=4, bulletFontName=BODY, bulletFontSize=10,
    )
    st["numbered"] = ParagraphStyle(
        "numbered", parent=st["body"], leftIndent=20, bulletIndent=4,
        spaceAfter=4, bulletFontName=BODY_BOLD, bulletFontSize=9.5,
    )
    st["quote"] = ParagraphStyle(
        "quote", fontName=BODY_ITALIC, fontSize=9.8, leading=13.6,
        textColor=QUOTE_TEXT, spaceAfter=0,
    )
    st["cell"] = ParagraphStyle(
        "cell", fontName=BODY, fontSize=9, leading=12,
        textColor=TEXT,
    )
    st["cell_head"] = ParagraphStyle(
        "cell_head", fontName=BODY_BOLD, fontSize=9, leading=12,
        textColor=TEXT,
    )
    st["title"] = ParagraphStyle(
        "title", fontName=BODY_BOLD, fontSize=20.5, leading=25.5,
        textColor=TEXT,
    )
    st["subtitle"] = ParagraphStyle(
        "subtitle", fontName=BODY, fontSize=10.5, leading=14.5,
        textColor=MUTED, spaceBefore=6,
    )
    return st


def build_code_block(code_lines: list[str], frame_w: float, page_h: float) -> list:
    """Code block in a light-gray box; font size shrinks so the longest line
    fits the frame width. Small blocks stay together; long ones are chunked
    so they can flow across pages."""
    if not code_lines:
        return []
    pad_side, pad_v = 9, 7
    avail = frame_w - 2 * pad_side - 2  # small slack for rounding
    longest_w10 = max(
        (pdfmetrics.stringWidth(_code_plain(l), MONO, 10) for l in code_lines),
        default=1.0,
    )
    size = 8.5
    if longest_w10 > 0:
        size = min(8.5, 10.0 * avail / longest_w10)
    size = max(size, 4.5)
    leading = size * 1.32

    style = ParagraphStyle(
        "codeblock", fontName=MONO, fontSize=size, leading=leading,
        textColor=CODE_TEXT,
    )

    def box(chunk: list[str]) -> Table:
        pre = Preformatted("\n".join(_code_plain(l) for l in chunk), style)
        t = Table([[pre]], colWidths=[frame_w])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), CODE_BG),
            ("BOX", (0, 0), (-1, -1), 0.6, CODE_BORDER),
            ("LEFTPADDING", (0, 0), (-1, -1), pad_side),
            ("RIGHTPADDING", (0, 0), (-1, -1), pad_side),
            ("TOPPADDING", (0, 0), (-1, -1), pad_v),
            ("BOTTOMPADDING", (0, 0), (-1, -1), pad_v),
        ]))
        return t

    est_h = len(code_lines) * leading + 2 * pad_v
    max_keep = page_h * 0.72
    flow: list = []
    if est_h <= max_keep:
        b = box(code_lines)
        b.spaceBefore = 3          # no leading Spacer: it would break the
        flow.append(KeepTogether([b]))  # keepWithNext chain from a heading
    else:  # split long blocks into stacked boxes that may cross pages
        per_chunk = max(8, int((max_keep - 2 * pad_v) / leading))
        for start in range(0, len(code_lines), per_chunk):
            b = box(code_lines[start:start + per_chunk])
            if start == 0:
                b.spaceBefore = 3
            flow.append(b)
    flow.append(Spacer(1, 7))
    return flow


def build_table(rows: list[list[str]], styles: dict, frame_w: float,
                page_h: float) -> list:
    ncols = max(len(r) for r in rows)
    rows = [list(r) + [""] * (ncols - len(r)) for r in rows]

    data = []
    for ri, row in enumerate(rows):
        pstyle = styles["cell_head"] if ri == 0 else styles["cell"]
        data.append([Paragraph(inline_markup(c, 7.6), pstyle) for c in row])

    # Column widths: proportional to (damped) content length, but never
    # narrower than the column's longest unbreakable word.
    weights, minw = [], []
    for j in range(ncols):
        col_texts = [strip_inline(r[j]) for r in rows]
        maxlen = max((len(t) for t in col_texts), default=1)
        weights.append(max(6.0, float(maxlen)) ** 0.62)
        longest_word = ""
        for t in col_texts:
            for w in re.split(r"\s+", t):
                if len(w) > len(longest_word):
                    longest_word = w
        need = pdfmetrics.stringWidth(longest_word, BODY_BOLD, 9) + 14
        minw.append(min(frame_w * 0.42, need))

    widths = [frame_w * w / sum(weights) for w in weights]
    fixed = [False] * ncols
    for _ in range(ncols):
        changed = False
        for j in range(ncols):
            if not fixed[j] and widths[j] < minw[j]:
                widths[j] = minw[j]
                fixed[j] = True
                changed = True
        if not changed:
            break
        free = frame_w - sum(widths[j] for j in range(ncols) if fixed[j])
        flex = [j for j in range(ncols) if not fixed[j]]
        if not flex or free <= 0:
            break
        fsum = sum(weights[j] for j in flex)
        for j in flex:
            widths[j] = free * weights[j] / fsum
    total = sum(widths)
    if total > frame_w:
        widths = [w * frame_w / total for w in widths]

    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), TABLE_HEADER_BG),
        ("LINEBELOW", (0, 0), (-1, 0), 0.9, ACCENT),
        ("GRID", (0, 0), (-1, -1), 0.4, TABLE_GRID),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, TABLE_ROW_ALT]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))

    _, est_h = t.wrap(frame_w, page_h)
    t.spaceBefore = 3
    flow: list = []
    if est_h <= page_h * 0.55:
        flow.append(KeepTogether([t]))
    else:  # long table: let Platypus split it by row (header repeats)
        flow.append(t)
    flow.append(Spacer(1, 8))
    return flow


def build_quote(text: str, styles: dict, frame_w: float) -> list:
    para = Paragraph(inline_markup(text, 8.4), styles["quote"])
    bar_w, indent_w = 2.6, 10
    t = Table(
        [["", "", para]],
        colWidths=[indent_w, bar_w, frame_w - indent_w - bar_w],
    )
    t.setStyle(TableStyle([
        ("BACKGROUND", (1, 0), (1, 0), ACCENT),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("LEFTPADDING", (2, 0), (2, 0), 10),
        ("RIGHTPADDING", (2, 0), (2, 0), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    t.spaceBefore = 3
    return [KeepTogether([t]), Spacer(1, 8)]


def heading_rule() -> HRFlowable:
    hr = HRFlowable(
        width="100%", thickness=0.7, color=ACCENT,
        spaceBefore=0, spaceAfter=8, lineCap="butt",
    )
    hr.keepWithNext = 1
    return hr


def title_header(styles: dict) -> list:
    return [
        Paragraph(inline_markup(TITLE, 16), styles["title"]),
        Paragraph(inline_markup(SUBTITLE, 8.5), styles["subtitle"]),
        HRFlowable(width="100%", thickness=1.4, color=ACCENT,
                   spaceBefore=10, spaceAfter=14, lineCap="butt"),
    ]


# ---------------------------------------------------------------------------
# Page decoration
# ---------------------------------------------------------------------------
def draw_footer(canv, doc) -> None:
    canv.saveState()
    y = 13 * mm
    canv.setStrokeColor(FOOTER_RULE)
    canv.setLineWidth(0.5)
    canv.line(doc.leftMargin, y + 9, doc.leftMargin + doc.width, y + 9)
    canv.setFont(BODY, 7.6)
    canv.setFillColor(FOOTER_GRAY)
    canv.drawString(doc.leftMargin, y, FOOTER_LEFT)
    canv.drawRightString(doc.leftMargin + doc.width, y, "Page %d" % canv.getPageNumber())
    canv.restoreState()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    _register_fonts()

    with open(SRC, "r", encoding="utf-8") as fh:
        md = fh.read()

    blocks = drop_duplicate_title(parse_markdown(md))
    styles = make_styles()

    doc = SimpleDocTemplate(
        OUT,
        pagesize=A4,
        leftMargin=22 * mm,
        rightMargin=22 * mm,
        topMargin=20 * mm,
        bottomMargin=24 * mm,
        title=TITLE,
        author="PolicyCut Team",
        subject=SUBTITLE,
    )
    frame_w = doc.width
    page_h = doc.height

    story: list = list(title_header(styles))
    pending_heading: list = []  # heading (+ rule) waiting for its content

    def emit(flow: list) -> None:
        """Append a block's flowables, binding any pending heading to them.
        reportlab's keepWithNext cannot chain a heading into a following
        KeepTogether (containers are excluded by _ktAllow), so when the block
        starts with a KeepTogether the heading is merged inside it."""
        nonlocal pending_heading
        if pending_heading:
            if flow and isinstance(flow[0], KeepTogether):
                flow[0] = KeepTogether(pending_heading + list(flow[0]._content))
            else:
                flow = pending_heading + flow
            pending_heading = []
        story.extend(flow)

    for kind, payload in blocks:
        if kind in ("h1", "h2"):
            emit([])  # flush any stacked heading first
            pending_heading = [
                Paragraph(inline_markup(payload, 11.5), styles["h2"]),
                heading_rule(),
            ]
        elif kind in ("h3", "h4"):
            emit([])
            pending_heading = [Paragraph(inline_markup(payload, 9.8), styles[kind])]
        elif kind == "p":
            emit([Paragraph(inline_markup(payload, 8.6), styles["body"])])
        elif kind == "ul":
            emit([Paragraph(inline_markup(item, 8.6), styles["bullet"],
                            bulletText="•") for item in payload] + [Spacer(1, 3)])
        elif kind == "ol":
            emit([Paragraph(inline_markup(item, 8.6), styles["numbered"],
                            bulletText="%s." % num) for num, item in payload]
                 + [Spacer(1, 3)])
        elif kind == "quote":
            emit(build_quote(payload, styles, frame_w))
        elif kind == "code":
            emit(build_code_block(payload, frame_w, page_h))
        elif kind == "table":
            emit(build_table(payload, styles, frame_w, page_h))
        elif kind == "hr":
            emit([HRFlowable(width="100%", thickness=0.6, color=ACCENT,
                             spaceBefore=10, spaceAfter=12, lineCap="butt")])
    emit([])  # trailing heading, if the document ends with one

    doc.build(story, onFirstPage=draw_footer, onLaterPages=draw_footer)
    print("Wrote %s" % OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
