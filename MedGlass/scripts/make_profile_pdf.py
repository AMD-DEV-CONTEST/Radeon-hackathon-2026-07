#!/usr/bin/env python3
"""Render docs/PROJECT_PROFILE.md to docs/PROJECT_PROFILE.pdf (fpdf2).

Simple markdown subset: headings, paragraphs, bullet lists, tables, code
blocks. Run from the repo root:  python3 scripts/make_profile_pdf.py
"""
from __future__ import annotations

import re
from pathlib import Path

from fpdf import FPDF

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "docs" / "PROJECT_PROFILE.md"
OUT = ROOT / "docs" / "PROJECT_PROFILE.pdf"

BOLD_RE = re.compile(r"\*\*(.+?)\*\*")

# Core PDF fonts are latin-1; map unicode niceties to safe equivalents.
_CHAR_MAP = {
    "\u2014": "--", "\u2013": "-", "\u2018": "'", "\u2019": "'",
    "\u201c": '"', "\u201d": '"', "\u2022": "-", "\u00b7": "-",
    "\u2192": "->", "\u2248": "~", "\u00d7": "x", "\u2265": ">=",
    "\u2264": "<=", "\u2026": "...", "\u00bd": "1/2", "\u2190": "<-",
}


def clean(text: str) -> str:
    for k, v in _CHAR_MAP.items():
        text = text.replace(k, v)
    return text.encode("latin-1", "replace").decode("latin-1")


class PDF(FPDF):
    def header(self) -> None:
        if self.page_no() > 1:
            self.set_font("Helvetica", "I", 8)
            self.set_text_color(120)
            self.cell(0, 6, "MedGlass - Project Profile - AMD AI DevMaster Hackathon 2026",
                      align="R")
            self.ln(8)

    def footer(self) -> None:
        self.set_y(-14)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(120)
        self.cell(0, 8, f"Page {self.page_no()}/{{nb}}", align="C")


def write_rich(pdf: PDF, text: str, size: int = 10) -> None:
    """Write a paragraph handling **bold** runs."""
    text = clean(text.replace("`", ""))
    pos = 0
    for m in BOLD_RE.finditer(text):
        if m.start() > pos:
            pdf.set_font("Helvetica", "", size)
            pdf.write(5, text[pos:m.start()])
        pdf.set_font("Helvetica", "B", size)
        pdf.write(5, m.group(1))
        pos = m.end()
    if pos < len(text):
        pdf.set_font("Helvetica", "", size)
        pdf.write(5, text[pos:])
    pdf.ln(5)


def render_table(pdf: PDF, rows: list[list[str]]) -> None:
    pdf.set_font("Helvetica", "", 8.5)
    n_cols = max(len(r) for r in rows)
    usable = pdf.w - pdf.l_margin - pdf.r_margin
    widths = [usable / n_cols] * n_cols
    # header row bold
    for ri, row in enumerate(rows):
        row = row + [""] * (n_cols - len(row))
        # estimate row height
        max_lines = 1
        for ci, cell in enumerate(row):
            lines = pdf.multi_cell(widths[ci], 4.5, clean(cell.replace("`", "")),
                                   split_only=True)
            max_lines = max(max_lines, len(lines))
        h = max_lines * 4.5 + 2
        if pdf.get_y() + h > pdf.h - 18:
            pdf.add_page()
        y0 = pdf.get_y()
        for ci, cell in enumerate(row):
            x0 = pdf.l_margin + sum(widths[:ci])
            pdf.set_xy(x0, y0)
            pdf.set_font("Helvetica", "B" if ri == 0 else "", 8.5)
            if ri == 0:
                pdf.set_fill_color(228, 235, 244)
                pdf.cell(widths[ci], h, "", fill=True)
                pdf.set_xy(x0, y0 + 1)
            pdf.multi_cell(widths[ci], 4.5, clean(cell.replace("`", "")))
        pdf.set_y(y0 + h)
        pdf.set_draw_color(180)
        pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(3)


def main() -> None:
    lines = SRC.read_text(encoding="utf-8").splitlines()
    pdf = PDF(format="A4")
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(True, margin=18)
    pdf.add_page()
    pdf.set_margins(14, 12, 14)

    i = 0
    in_code = False
    code_buf: list[str] = []
    table_buf: list[list[str]] = []

    def flush_table() -> None:
        nonlocal table_buf
        if table_buf:
            render_table(pdf, table_buf)
            table_buf = []

    while i < len(lines):
        line = lines[i]

        if line.strip().startswith("```"):
            if in_code:
                flush_table()
                pdf.set_font("Courier", "", 7.5)
                pdf.set_fill_color(244, 246, 249)
                for cl in code_buf:
                    if pdf.get_y() > pdf.h - 20:
                        pdf.add_page()
                    pdf.cell(0, 4.2, clean(" " + cl), new_x="LMARGIN",
                             new_y="NEXT", fill=True)
                pdf.ln(3)
                code_buf = []
                in_code = False
            else:
                flush_table()
                in_code = True
            i += 1
            continue
        if in_code:
            code_buf.append(line)
            i += 1
            continue

        if line.strip().startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if not all(re.fullmatch(r":?-{3,}:?", c) for c in cells):
                table_buf.append(cells)
            i += 1
            continue
        flush_table()

        if not line.strip():
            pdf.ln(2)
        elif line.startswith("# "):
            pdf.set_font("Helvetica", "B", 20)
            pdf.set_text_color(20, 60, 110)
            pdf.cell(0, 10, clean(line[2:].strip()), new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(0)
        elif line.startswith("## "):
            pdf.ln(2)
            if pdf.get_y() > pdf.h - 40:
                pdf.add_page()
            pdf.set_font("Helvetica", "B", 14)
            pdf.set_text_color(20, 60, 110)
            pdf.cell(0, 8, clean(line[3:].strip()), new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(0)
            pdf.set_draw_color(20, 60, 110)
            pdf.line(pdf.l_margin, pdf.get_y(), pdf.l_margin + 60, pdf.get_y())
            pdf.ln(2)
        elif line.startswith("### "):
            pdf.set_font("Helvetica", "B", 12)
            pdf.cell(0, 7, clean(line[4:].strip()), new_x="LMARGIN", new_y="NEXT")
        elif line.startswith("---"):
            pdf.ln(1)
            pdf.set_draw_color(160)
            y = pdf.get_y()
            pdf.line(pdf.l_margin, y, pdf.w - pdf.r_margin, y)
            pdf.ln(3)
        elif re.match(r"^\s*[-*] ", line):
            indent = (len(line) - len(line.lstrip())) * 0.6
            pdf.set_x(pdf.l_margin + 4 + indent)
            pdf.set_font("Helvetica", "", 10)
            pdf.cell(4, 5, "-")
            write_rich(pdf, line.strip()[2:].strip(), size=10)
        elif re.match(r"^\d+\.\s", line.strip()):
            pdf.set_x(pdf.l_margin + 4)
            num = line.strip().split(".", 1)[0] + "."
            pdf.set_font("Helvetica", "B", 10)
            pdf.cell(7, 5, num)
            write_rich(pdf, line.strip().split(".", 1)[1].strip(), size=10)
        else:
            write_rich(pdf, line.strip(), size=10)
        i += 1

    flush_table()
    pdf.output(str(OUT))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
