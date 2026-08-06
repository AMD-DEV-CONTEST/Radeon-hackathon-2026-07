"""
slides_converter.py - Converts slide markdown to styled HTML and PDF
Generates presentation-quality slides with slide numbers using xhtml2pdf.
"""

import re
import os
import tempfile
import markdown

# ── LaTeX-to-Unicode symbol mapping ───────────────────────────────
_SYMBOL_MAP = {
    # Arrows
    r'\downarrow': '↓', r'\uparrow': '↑', r'\rightarrow': '→', r'\leftarrow': '←',
    r'\leftrightarrow': '↔', r'\Rightarrow': '⇒', r'\Leftarrow': '⇐', r'\Leftrightarrow': '⇔',
    r'\to': '→', r'\gets': '←', r'\updownarrow': '↕',
    # Comparison
    r'\approx': '≈', r'\neq': '≠', r'\leq': '≤', r'\geq': '≥',
    r'\le': '≤', r'\ge': '≥', r'\equiv': '≡', r'\sim': '∼', r'\propto': '∝',
    # Set theory
    r'\in': '∈', r'\notin': '∉', r'\subset': '⊂', r'\supset': '⊃',
    r'\subseteq': '⊆', r'\supseteq': '⊇', r'\cup': '∪', r'\cap': '∩',
    r'\emptyset': '∅', r'\forall': '∀', r'\exists': '∃',
    # Logic
    r'\land': '∧', r'\lor': '∨', r'\lnot': '¬', r'\neg': '¬',
    r'\therefore': '∴', r'\because': '∵',
    # Math
    r'\pm': '±', r'\mp': '∓', r'\times': '×', r'\div': '÷', r'\cdot': '·',
    r'\oplus': '⊕', r'\otimes': '⊗', r'\sum': '∑', r'\prod': '∏',
    r'\sqrt': '√', r'\infty': '∞', r'\partial': '∂', r'\nabla': '∇',
    # Greek lowercase
    r'\alpha': 'α', r'\beta': 'β', r'\gamma': 'γ', r'\delta': 'δ',
    r'\epsilon': 'ε', r'\zeta': 'ζ', r'\eta': 'η', r'\theta': 'θ',
    r'\lambda': 'λ', r'\mu': 'μ', r'\nu': 'ν', r'\xi': 'ξ',
    r'\pi': 'π', r'\rho': 'ρ', r'\sigma': 'σ', r'\tau': 'τ',
    r'\phi': 'φ', r'\chi': 'χ', r'\psi': 'ψ', r'\omega': 'ω',
    # Greek uppercase
    r'\Gamma': 'Γ', r'\Delta': 'Δ', r'\Theta': 'Θ', r'\Lambda': 'Λ',
    r'\Sigma': 'Σ', r'\Phi': 'Φ', r'\Psi': 'Ψ', r'\Omega': 'Ω',
    # Misc
    r'\degree': '°', r'\section': '§', r'\paragraph': '¶',
    r'\dagger': '†', r'\ddagger': '‡',
    r'\copyright': '©', r'\registered': '®', r'\trademark': '™',
    r'\checkmark': '✓', r'\cross': '✗',
    r'\ldots': '…', r'\cdots': '⋯', r'\dots': '…',
    r'\clubsuit': '♣', r'\diamondsuit': '♦', r'\heartsuit': '♥', r'\spadesuit': '♠',
}

_INLINE_MATH_RE = re.compile(r'\$([^$]+)\$')
_SYMBOL_RE = re.compile(r'\\([a-zA-Z]+)')


def _replace_symbol(match):
    cmd = '\\' + match.group(1)
    return _SYMBOL_MAP.get(cmd, match.group(0))


def replace_latex_symbols(text: str) -> str:
    """Convert LaTeX math notation to Unicode symbols in text."""
    if not text:
        return text

    def _replace_math_block(m):
        inner = m.group(1).strip()
        return _SYMBOL_RE.sub(_replace_symbol, inner)

    # Replace content inside $...$ first, then standalone \commands
    text = _INLINE_MATH_RE.sub(_replace_math_block, text)
    text = _SYMBOL_RE.sub(_replace_symbol, text)
    return text


def _build_slide_css() -> str:
    return """
  @page {
    size: A4 landscape;
    margin: 15mm 20mm 15mm 20mm;
  }

  body {
    font-family: Helvetica, Arial, sans-serif;
    color: #1e293b;
    line-height: 1.45;
    font-size: 10.5pt;
  }

  .slide {
    page-break-after: always;
    page-break-inside: avoid;
    position: relative;
    min-height: 170mm;
  }
  .slide:last-child { page-break-after: auto; }

  .slide-number {
    display: none;
  }

  /* Title slide */
  .slide-title { text-align: center; padding-top: 30mm; }
  .slide-title h1 { font-size: 26pt; font-weight: bold; margin-bottom: 4mm; }
  .slide-title .subtitle { font-size: 13pt; color: #4f46e5; }
  .slide-title .meta { margin-top: 10mm; font-size: 10pt; color: #64748b; }

  /* Content slide */
  .slide-content .slide-header {
    border-bottom: 1pt solid #e2e8f0;
    padding-bottom: 2mm;
    margin-bottom: 4mm;
  }
  .slide-content .slide-label {
    font-size: 7.5pt; color: #64748b;
    text-transform: uppercase; letter-spacing: 0.5pt;
  }
  .slide-content .slide-header h2 {
    font-size: 16pt; font-weight: bold; color: #1e293b; margin-top: 1mm;
  }
  .slide-content .slide-body h3 {
    font-size: 12pt; font-weight: bold; color: #4f46e5;
    margin-top: 3mm; margin-bottom: 1.5mm;
  }
  .slide-content .slide-body p { margin: 1.5mm 0; color: #334155; }
  .slide-content .slide-body ul,
  .slide-content .slide-body ol { margin: 1.5mm 0 1.5mm 6mm; color: #334155; }
  .slide-content .slide-body li { margin: 0.8mm 0; }
  .slide-content .slide-body strong { color: #1e293b; }
  .slide-content .slide-body table {
    width: 100%; border-collapse: collapse; margin: 2mm 0; font-size: 9.5pt;
    table-layout: auto;
  }
  .slide-content .slide-body th {
    background-color: #f1f5f9; font-weight: bold; text-align: left;
    padding: 1mm 2mm; border: 0.5pt solid #e2e8f0;
    vertical-align: middle;
  }
  .slide-content .slide-body td {
    padding: 1mm 2mm; border: 0.5pt solid #e2e8f0;
    vertical-align: top;
  }
  .slide-content .slide-body td p,
  .slide-content .slide-body th p {
    margin: 0;
    padding: 0;
  }
  .slide-content .slide-body td ul,
  .slide-content .slide-body td ol {
    margin: 0 0 0 4mm;
    padding: 0;
  }
  .slide-content .slide-body code {
    font-family: Courier, monospace; background-color: #f1f5f9; font-size: 9pt;
  }
  .slide-content .slide-body pre {
    background-color: #1e293b; color: #e2e8f0;
    padding: 2mm 3mm; font-size: 8.5pt; font-family: Courier, monospace;
  }
  .slide-content .slide-body blockquote {
    border-left: 2pt solid #818cf8; padding: 1.5mm 3mm;
    margin: 2mm 0; background-color: #eef2ff; color: #4338ca;
    font-style: italic;
  }
  .slide-footer {
    font-size: 7.5pt; color: #94a3b8; text-align: right;
    border-top: 0.5pt solid #e2e8f0; padding-top: 1.5mm;
  }

  /* Summary slide */
  .slide-summary .slide-header { border-bottom-color: #a7f3d0; }
  .slide-summary .slide-header h2 { color: #10b981; }
"""


SLIDE_TEMPLATES = {
    "title": """
<div class="slide slide-title">
  <h1>{title}</h1>
  <div class="subtitle">{subtitle}</div>
  <div class="meta">{meta}</div>
  <div class="slide-number">{slide_num} / {total}</div>
</div>""",

    "content": """
<div class="slide slide-content">
  <div class="slide-header">
    <div class="slide-label">{label}</div>
    <h2>{title}</h2>
  </div>
  <div class="slide-body">
    {body}
  </div>
</div>""",
}


def _md_fragment_to_html(md_text: str) -> str:
    """Convert a markdown fragment to HTML."""
    return markdown.markdown(md_text.strip(), extensions=["tables", "fenced_code"])


def _split_body_for_slides(body_md: str, max_table_rows: int = 5) -> list[str]:
    """
    If the markdown body contains a table with more than max_table_rows rows,
    split it into multiple chunks so each slide gets a readable table.
    
    Returns a list of markdown fragments (one per slide).
    Non-table content stays with the first chunk.
    """
    lines = body_md.strip().split("\n")

    # Find table boundaries (lines starting with |)
    table_start = None
    table_end = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("|") and table_start is None:
            table_start = i
        if table_start is not None and not stripped.startswith("|") and stripped != "":
            table_end = i
            break
    if table_start is not None and table_end is None:
        table_end = len(lines)

    # No table or table is small enough — return as-is
    if table_start is None:
        return [body_md]

    table_lines = lines[table_start:table_end]
    # Row lines = everything after the header (row 0) and separator (row 1)
    if len(table_lines) <= max_table_rows + 2:
        return [body_md]

    header_lines = table_lines[:2]  # header row + separator
    data_lines = table_lines[2:]   # data rows
    pre_table = lines[:table_start]
    post_table = lines[table_end:]

    # Split data rows into chunks
    chunks = []
    for i in range(0, len(data_lines), max_table_rows):
        chunk_data = data_lines[i:i + max_table_rows]
        chunk_lines = list(pre_table) + list(header_lines) + chunk_data + list(post_table)
        chunks.append("\n".join(chunk_lines))
        pre_table = []  # only keep pre-table content on the first chunk
        post_table = []  # only keep post-table content on the last chunk

    return chunks if chunks else [body_md]


def markdown_to_slide_html(md_content: str, course_code: str = "", course_title: str = "",
                           lecture_num: int = 0, topic: str = "") -> str:
    """
    Parse markdown and convert to HTML slides.
    - First # heading -> title slide
    - Each ## heading -> one content slide
    - ### and below -> body content within a slide
    """
    # Convert LaTeX symbols to Unicode before processing
    md_content = replace_latex_symbols(md_content)

    lines = md_content.strip().split("\n")

    slides = []  # list of (type, dict)
    title_done = False
    current_title = ""
    current_body: list[str] = []

    footer_text = f"{course_code} - Lecture {lecture_num}" if course_code else ""
    header_label = f"{course_code} - {course_title}" if course_code else ""

    def _flush():
        # Only create a slide if there's a title or non-empty body content
        has_body = any(line.strip() for line in current_body)
        if current_title or has_body:
            body_md = "\n".join(current_body)
            title_lower = current_title.lower()
            is_summary = any(w in title_lower for w in ["summary", "conclusion", "key takeaway", "recap"])
            label = "SUMMARY" if is_summary else header_label

            # Split large tables across multiple slides
            chunks = _split_body_for_slides(body_md, max_table_rows=5)
            for idx, chunk in enumerate(chunks):
                chunk_html = _md_fragment_to_html(chunk) if chunk.strip() else "<p>&nbsp;</p>"
                slide_title = current_title if idx == 0 else f"{current_title} (cont.)"
                slides.append(("content", {
                    "label": label, "title": slide_title,
                    "body": chunk_html, "footer": footer_text,
                }))

    for line in lines:
        s = line.strip()

        if s.startswith("# ") and not title_done:
            _flush()
            current_title, current_body = "", []
            title_text = s[2:].strip()
            subtitle = topic or course_title
            meta = []
            if course_code: meta.append(course_code)
            if lecture_num: meta.append(f"Lecture {lecture_num}")
            slides.append(("title", {
                "title": title_text, "subtitle": subtitle,
                "meta": " &bull; ".join(meta),
            }))
            title_done = True
            continue

        if s.startswith("## "):
            _flush()
            current_title = s[3:].strip()
            current_body = []
            continue

        current_body.append(line)

    _flush()

    if not slides:
        slides.append(("content", {
            "label": header_label or topic or "Content", "title": topic or "Content",
            "body": _md_fragment_to_html(md_content), "footer": footer_text,
        }))

    total = len(slides)
    css = _build_slide_css()
    parts = []
    for i, (stype, params) in enumerate(slides, 1):
        params["slide_num"] = i
        params["total"] = total
        tpl = SLIDE_TEMPLATES[stype]
        parts.append(tpl.format(**params))

    body_html = "\n".join(parts)
    return (
        '<!DOCTYPE html><html><head><meta charset="UTF-8">'
        f'<style>{css}</style></head><body>'
        f'{body_html}'
        '</body></html>'
    )


def html_to_pdf(html_content: str, output_path: str,
                footer_text: str = "", total_pages: int = 0) -> str:
    """Convert HTML to PDF using xhtml2pdf, then overlay footer/page-number with reportlab."""
    import io as _io
    from xhtml2pdf import pisa

    # Step 1: Generate base PDF into a buffer
    buf = _io.BytesIO()
    status = pisa.CreatePDF(src=html_content, dest=buf)
    if status.err:
        raise RuntimeError(f"PDF generation failed with {status.err} error(s)")
    buf.seek(0)

    # Step 2: Overlay footer and page numbers using reportlab
    from pypdf import PdfReader, PdfWriter
    from reportlab.pdfgen import canvas as rl_canvas
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.units import mm

    page_size = landscape(A4)
    width, height = page_size

    reader = PdfReader(buf)
    writer = PdfWriter()
    num_pages = len(reader.pages)
    footer_str = footer_text or ""

    for i, page in enumerate(reader.pages):
        # Create an overlay PDF with footer
        overlay_buf = _io.BytesIO()
        c = rl_canvas.Canvas(overlay_buf, pagesize=page_size)

        # Footer text — bottom left (skip for title slide, i==0)
        if i > 0:
            c.setFont("Helvetica", 7.5)
            c.setFillColorRGB(0.58, 0.58, 0.58)  # #94a3b8
            if footer_str:
                c.drawString(20 * mm, 10 * mm, footer_str)

            # Page number — bottom right
            page_label = f"{i + 1} / {num_pages}"
            c.drawRightString(width - 20 * mm, 10 * mm, page_label)
        else:
            # Title slide: only page number
            c.setFont("Helvetica", 7.5)
            c.setFillColorRGB(1, 1, 1)  # white on title slide
            page_label = f"{i + 1} / {num_pages}"
            c.drawRightString(width - 20 * mm, 10 * mm, page_label)

        c.save()
        overlay_buf.seek(0)

        # Merge overlay onto the page
        overlay_reader = PdfReader(overlay_buf)
        page.merge_page(overlay_reader.pages[0])
        writer.add_page(page)

    # Step 3: Write final PDF
    with open(output_path, "wb") as f:
        writer.write(f)

    return output_path


def generate_slides_pdf(md_content: str, course_code: str = "", course_title: str = "",
                        lecture_num: int = 0, topic: str = "",
                        output_dir: str = None) -> str:
    """Full pipeline: markdown -> HTML slides -> PDF. Returns PDF path."""
    if output_dir is None:
        output_dir = tempfile.gettempdir()

    html = markdown_to_slide_html(md_content, course_code, course_title, lecture_num, topic)

    safe_name = re.sub(r'[^\w\-]', '_', f"{course_code}_L{lecture_num}_{topic}")[:60]
    pdf_path = os.path.join(output_dir, f"{safe_name}.slides.pdf")

    footer_text = f"{course_code} - Lecture {lecture_num}" if course_code else ""
    html_to_pdf(html, pdf_path, footer_text=footer_text)
    return pdf_path
