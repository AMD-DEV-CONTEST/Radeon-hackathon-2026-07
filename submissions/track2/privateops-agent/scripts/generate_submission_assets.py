from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A3, A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.pdfgen import canvas


ROOT = Path(__file__).resolve().parent.parent
SUBMISSION = ROOT / "submission"
ASSETS = SUBMISSION / "assets"
INK = colors.HexColor("#131722")
MUTED = colors.HexColor("#687184")
DARK = colors.HexColor("#11151f")
PANEL = colors.HexColor("#f1f3f6")
LINE = colors.HexColor("#d9dde5")
ACCENT = colors.HexColor("#ed5334")
GREEN = colors.HexColor("#4aaa7d")
BLUE = colors.HexColor("#4e8ed4")


def register_fonts() -> None:
    arial = Path("C:/Windows/Fonts/arial.ttf")
    arial_bold = Path("C:/Windows/Fonts/arialbd.ttf")
    if arial.exists() and arial_bold.exists():
        pdfmetrics.registerFont(TTFont("PrivateOpsSans", str(arial)))
        pdfmetrics.registerFont(TTFont("PrivateOpsSans-Bold", str(arial_bold)))


FONT = "PrivateOpsSans" if Path("C:/Windows/Fonts/arial.ttf").exists() else "Helvetica"
BOLD = "PrivateOpsSans-Bold" if Path("C:/Windows/Fonts/arialbd.ttf").exists() else "Helvetica-Bold"


def project_styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle("DocTitle", fontName=BOLD, fontSize=34, leading=34, textColor=DARK, spaceAfter=8 * mm))
    styles.add(ParagraphStyle("Section", fontName=BOLD, fontSize=22, leading=25, textColor=DARK, spaceAfter=5 * mm))
    styles.add(ParagraphStyle("Sub", fontName=BOLD, fontSize=12.5, leading=15, textColor=DARK, spaceBefore=4 * mm, spaceAfter=2 * mm))
    styles.add(ParagraphStyle("BodyPO", fontName=FONT, fontSize=9.6, leading=14, textColor=INK, spaceAfter=3 * mm))
    styles.add(ParagraphStyle("Lead", fontName=FONT, fontSize=12, leading=17, textColor=colors.HexColor("#394154"), spaceAfter=5 * mm))
    styles.add(ParagraphStyle("SmallPO", fontName=FONT, fontSize=8, leading=11, textColor=MUTED))
    styles.add(ParagraphStyle("CardTitle", fontName=BOLD, fontSize=10.5, leading=13, textColor=DARK, spaceAfter=1.5 * mm))
    styles.add(ParagraphStyle("CardBody", fontName=FONT, fontSize=8.7, leading=12, textColor=colors.HexColor("#3f4757")))
    return styles


def page_frame(canvas_obj, doc) -> None:
    canvas_obj.saveState()
    canvas_obj.setStrokeColor(LINE)
    canvas_obj.line(18 * mm, 14 * mm, 192 * mm, 14 * mm)
    canvas_obj.setFont(FONT, 7.5)
    canvas_obj.setFillColor(MUTED)
    canvas_obj.drawString(18 * mm, 9 * mm, "PRIVATEOPS AGENT · 2026 AMD AI DEVMASTER · TRACK 2")
    canvas_obj.drawRightString(192 * mm, 9 * mm, str(doc.page))
    canvas_obj.restoreState()


def heading(number: str, title: str, styles) -> list:
    return [
        Table([[number]], colWidths=[12 * mm], rowHeights=[7 * mm], style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), ACCENT), ("TEXTCOLOR", (0, 0), (-1, -1), colors.white),
            ("FONTNAME", (0, 0), (-1, -1), BOLD), ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ROUNDEDCORNERS", [2 * mm]),
        ])),
        Spacer(1, 4 * mm),
        Paragraph(title, styles["Section"]),
    ]


def card(title: str, body: str, styles):
    return Table(
        [[Paragraph(title, styles["CardTitle"]), Paragraph(body, styles["CardBody"])]],
        colWidths=[42 * mm, 44 * mm],
        style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), PANEL), ("BOX", (0, 0), (-1, -1), 0.7, LINE),
            ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 5 * mm),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5 * mm), ("TOPPADDING", (0, 0), (-1, -1), 4 * mm),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4 * mm),
        ]),
    )


def bullets(items: list[str], styles) -> list:
    return [Paragraph(f"<font color='#ed5334'>•</font> {item}", styles["BodyPO"]) for item in items]


def project_specification() -> None:
    path = SUBMISSION / "PrivateOps-Agent-Project-Specification.pdf"
    frame = Frame(18 * mm, 18 * mm, 174 * mm, 261 * mm, id="content")
    doc = BaseDocTemplate(str(path), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=18 * mm, bottomMargin=18 * mm, title="PrivateOps Agent Project Specification", author="PrivateOps Agent")
    doc.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=page_frame)])
    styles = project_styles()
    story = []

    story += [Spacer(1, 25 * mm), Paragraph("2026 AMD AI DEVMASTER · TRACK 2", ParagraphStyle("CoverKicker", parent=styles["SmallPO"], fontName=BOLD, fontSize=10, leading=12, textColor=ACCENT, spaceAfter=15 * mm)), Paragraph("PrivateOps<br/>Agent", styles["DocTitle"]), Paragraph("A permission-first private computer AI on AMD Radeon GPU + ROCm.", ParagraphStyle("CoverLead", parent=styles["Lead"], fontSize=17, leading=22, textColor=colors.HexColor("#444d60"))), Spacer(1, 26 * mm)]
    cover_cards = [[Paragraph("BROAD VISIBILITY", styles["CardTitle"]), Paragraph("DELIBERATE ACTION", styles["CardTitle"]), Paragraph("EVIDENCE FOR DECISIONS", styles["CardTitle"])], [Paragraph("Supported observation", styles["CardBody"]), Paragraph("Exact-action confirmation", styles["CardBody"]), Paragraph("Local audit + Radeon proof", styles["CardBody"])]]
    story += [Table(cover_cards, colWidths=[58 * mm] * 3, style=TableStyle([("BACKGROUND", (0, 0), (-1, -1), PANEL), ("BOX", (0, 0), (-1, -1), .8, LINE), ("INNERGRID", (0, 0), (-1, -1), .5, LINE), ("TOPPADDING", (0, 0), (-1, -1), 5 * mm), ("BOTTOMPADDING", (0, 0), (-1, -1), 5 * mm), ("LEFTPADDING", (0, 0), (-1, -1), 5 * mm)])), Spacer(1, 25 * mm), Paragraph("Version 1.0 · English submission package · MIT License", styles["SmallPO"]), PageBreak()]

    story += heading("01", "Application scenario", styles)
    story += [Paragraph("People increasingly say, 'I gave my whole computer to my AI.' Useful AI needs permission if it is going to take work away from people—but permission must not mean silent control.", styles["Lead"])]
    story += [Table([[Paragraph("PRODUCT PROMISE", styles["CardTitle"]), Paragraph("Broad visibility. Deliberate action. Evidence for every decision. PrivateOps observes supported computer and project state, defaults to read-only behavior, and requires a second exact-action confirmation before any supported side effect.", styles["CardBody"])]], colWidths=[35 * mm, 139 * mm], style=TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fff0eb")), ("BOX", (0, 0), (-1, -1), 1, ACCENT), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("PADDING", (0, 0), (-1, -1), 5 * mm)]))]
    story += [Paragraph("Two truthful surfaces", styles["Sub"]), Paragraph("Windows exposes seven fixed read-only system collectors. Radeon Cloud exposes private project and runtime observation beside the local model. Whole-computer permission means broad supported visibility, never unrestricted administrator access.", styles["BodyPO"]), Spacer(1, 3 * mm), card("Independent developers", "Computer observation, release audits, competition packaging, and reproducible checks.", styles), Spacer(1, 3 * mm), card("Small private teams", "Local knowledge operations where source, credentials, and internal plans cannot leave the controlled environment.", styles), Paragraph("Distinctive value", styles["Sub"])]
    story += bullets(["Safe, confirm, and blocked decisions remain reviewer-visible.", "One-use tokens bind permission to one exact action.", "All five Track 2 capability categories reinforce one permission-first workflow."], styles)
    story.append(PageBreak())

    story += heading("02", "Architecture and data flow", styles)
    story += [Paragraph("A dependency-light Python service orchestrates local evidence, planning, guarded tools, memory, model inference, audit, and benchmark proof. A no-build browser console exposes every layer.", styles["Lead"])]
    flow_data = [[Paragraph(f"<b>{i:02d}</b><br/>{label}", ParagraphStyle(f"flow{i}", parent=styles["SmallPO"], alignment=TA_CENTER, textColor=colors.white, leading=12)) for i, label in enumerate(["Classify", "Retrieve", "Plan + tools", "Generate", "Audit"], 1)]]
    story += [Table(flow_data, colWidths=[34.8 * mm] * 5, style=TableStyle([("BACKGROUND", (0, 0), (-1, -1), DARK), ("INNERGRID", (0, 0), (-1, -1), 2, colors.white), ("TOPPADDING", (0, 0), (-1, -1), 5 * mm), ("BOTTOMPADDING", (0, 0), (-1, -1), 5 * mm)])), Spacer(1, 6 * mm)]
    architecture = [
        ["Component", "Responsibility", "Trust property"],
        ["Retrieval", "Indexes approved text files and creates stable evidence IDs.", "Answers expose source and snippet."],
        ["Permission", "Classifies requests as safe, confirm, or blocked.", "Side effects never execute silently."],
        ["Tool registry", "Inventory, search, tests, and readiness checks.", "Paths stay confined; commands are allow-listed."],
        ["Planner", "Creates retrieve, inspect, and synthesize steps.", "Status and results remain visible."],
        ["Local state", "Memory, JSONL audit, profile, and benchmarks.", "Atomic writes and credential redaction."],
        ["ROCm provider", "Calls a loopback OpenAI-compatible server.", "No closed remote core dependency."],
    ]
    architecture_cells = [
        [Paragraph(value, ParagraphStyle(f"arch-{row_index}-{column_index}", parent=styles["SmallPO"], fontName=BOLD if row_index == 0 else FONT, textColor=colors.white if row_index == 0 else INK)) for column_index, value in enumerate(row)]
        for row_index, row in enumerate(architecture)
    ]
    story += [Table(architecture_cells, colWidths=[33 * mm, 76 * mm, 65 * mm], repeatRows=1, style=TableStyle([("BACKGROUND", (0, 0), (-1, 0), DARK), ("GRID", (0, 0), (-1, -1), .6, LINE), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("PADDING", (0, 0), (-1, -1), 3 * mm)])), Paragraph("Failure behavior", styles["Sub"]), Paragraph("Malformed and oversized requests receive stable errors. Non-loopback competition endpoints, path escape, shell metacharacters, expired or reused confirmation tokens, and unsupported verified benchmark claims are rejected. ROCm mode never silently falls back to development output.", styles["BodyPO"]), PageBreak()]

    story += heading("03", "Core capabilities", styles)
    capability_rows = [
        [card("Local RAG", "Fourteen bilingual sources, Chinese bigrams, stable IDs, bounded snippets.", styles), card("Tool calling", "Project tools plus seven fixed Windows collectors with structured results.", styles)],
        [card("Multi-step planning", "Inspectable retrieval, tool work, and synthesis stages.", styles), card("Local memory", "Project facts and preferences in atomic local JSON state.", styles)],
        [card("Privacy controls", "Three risk levels, one-use tokens, path confinement, and allow-listing.", styles), card("Audit ledger", "Chronological records of evidence, tools, provider, latency, and memory.", styles)],
    ]
    for row in capability_rows:
        story += [Table([row], colWidths=[87 * mm, 87 * mm], style=TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 1.5 * mm), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5 * mm)]))]
    story += [Paragraph("Agent framework", styles["Sub"]), Paragraph("PrivateOps uses LangChain Core StructuredTool adapters as its open Agent tool framework. Each adapter delegates to the permission-aware registry, preserving path confinement, confirmation tokens, allow-listing, structured results, and audit recording.", styles["BodyPO"]), Paragraph("Interaction design", styles["Sub"]), Paragraph("The Local Trust Console keeps proof adjacent to the user task and exposes an explicit Remote model / Local ROCm selector. Remote mode requires its own API key; Local ROCm restores the loopback Qwen defaults and accepts an empty key. The interface is responsive, keyboard-focusable, and honors reduced-motion preferences.", styles["BodyPO"]), PageBreak()]

    story += heading("04", "Model and local deployment", styles)
    story += [Paragraph("Competition mode runs an open-weight instruct model through vLLM on a loopback endpoint inside the same Radeon Cloud instance as PrivateOps.", styles["Lead"])]
    modes = [["Mode", "Purpose", "Runtime contract"], ["Remote model", "Optional integration testing on ordinary computers.", "HTTP(S) endpoint and key required."], ["Local ROCm", "ROCm vLLM on 127.0.0.1 in the same instance.", "Loopback required; key optional."]]
    story += [Table(modes, colWidths=[30 * mm, 85 * mm, 59 * mm], style=TableStyle([("BACKGROUND", (0, 0), (-1, 0), DARK), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("FONTNAME", (0, 0), (-1, 0), BOLD), ("FONTNAME", (0, 1), (-1, -1), FONT), ("FONTSIZE", (0, 0), (-1, -1), 8.5), ("GRID", (0, 0), (-1, -1), .6, LINE), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("PADDING", (0, 0), (-1, -1), 3 * mm)])), Paragraph("Default profile", styles["Sub"]), Paragraph("Qwen/Qwen2.5-7B-Instruct is the shared competition default. vLLM serves it on 127.0.0.1:8000 with an 8,192-token context and 0.85 GPU-memory utilization. The Apache-2.0 model remains configurable when the cloud image requires another compatible open artifact.", styles["BodyPO"]), Paragraph("Privacy boundary", styles["Sub"])]
    story += bullets(["The browser talks only to the PrivateOps service.", "The service retrieves files only from the configured workspace.", "The service calls the model on a validated loopback URL.", "API keys are omitted from status, audit, and browser responses.", "Core behavior does not call shared public model APIs."], styles)
    story += [Paragraph("Reproducibility", styles["Sub"]), Paragraph("Separate commands start the ROCm model server, application, benchmark collector, tests, smoke check, and final material validator. The cloud runbook includes rocminfo, HIP, PyTorch, endpoint, tunnel, and evidence commands.", styles["BodyPO"]), PageBreak()]

    story += heading("05", "Radeon optimization and measurement", styles)
    story += [Paragraph("A verified same-instance run captured AMD Radeon Graphics (gfx1100), ROCm 7.2.1, ROCm vLLM, and Qwen2.5-7B-Instruct. Final metrics are generated from the immutable machine record.", styles["Lead"]), Paragraph("Implemented optimization", styles["Sub"])]
    story += bullets(["8,192-token context and 0.85 GPU-memory utilization preserve headroom.", "Loopback transport keeps prompts local and avoids public-network latency.", "Top-k RAG, environment exclusion, bounded samples, and a 25-item list limit reduce context.", "Temperature zero improves repeatability during evidence collection."], styles)
    metrics = [["Metric", "Verified value", "Scope"], ["Direct latency", "1,511.072 ms", "Loopback completion."], ["Throughput", "32.427 tokens/s", "49 completion tokens."], ["Complete Agent", "18,384.639 ms", "RAG, tool, model, audit."]]
    story += [Table(metrics, colWidths=[38 * mm, 58 * mm, 78 * mm], style=TableStyle([("BACKGROUND", (0, 0), (-1, 0), DARK), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("FONTNAME", (0, 0), (-1, 0), BOLD), ("FONTNAME", (0, 1), (-1, -1), FONT), ("FONTSIZE", (0, 0), (-1, -1), 8.5), ("GRID", (0, 0), (-1, -1), .6, LINE), ("PADDING", (0, 0), (-1, -1), 3 * mm)])), Spacer(1, 6 * mm), Table([[Paragraph("INTEGRITY RULE", styles["CardTitle"]), Paragraph("No baseline speedup, P50/P95, VRAM peak, concurrency, or hardware soak value is claimed without a new Radeon measurement.", styles["CardBody"])]], colWidths=[35 * mm, 139 * mm], style=TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fff0eb")), ("BOX", (0, 0), (-1, -1), 1, ACCENT), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("PADDING", (0, 0), (-1, -1), 5 * mm)])), PageBreak()]

    story += heading("06", "Verification and deliverables", styles)
    story += [Paragraph("Automated coverage", styles["Sub"]), Paragraph("The 102-test local finalization baseline covers bilingual retrieval, explicit remote/local provider validation, ROCm profile, LangChain tools, bounded inventories, permission and confirmation, memory, audit integrity, benchmark provenance, Agent orchestration, HTTP errors, Markdown safety, UI state, the provider-required smoke path, and unresolved submission placeholders. A repeatable software stability check verifies visible provider failure and zero silent fallback.", styles["BodyPO"]), Paragraph("Reviewer deliverables", styles["Sub"])]
    story += bullets(["Complete source, tests, local and cloud startup scripts.", "Project specification PDF and editable HTML source.", "Editable English competition PPT with source notes.", "Architecture SVG/PNG and one-page poster PDF.", "Timed demo narration and exact shot list.", "Radeon Cloud runbook and benchmark evidence schema.", "English PR copy and final checklist."], styles)
    story += [Paragraph("Completed proof and final user gates", styles["Sub"]), Paragraph("The real Radeon Cloud run, measured evidence, and public demonstration video are complete. The video is available at https://www.bilibili.com/video/BV1nQuA6qEFS/. Only account-bound identity confirmation, the official repository Fork, and Pull Request remain user actions.", styles["BodyPO"]), Spacer(1, 14 * mm), Paragraph("Broad visibility. Deliberate action. Evidence for every decision.", ParagraphStyle("Close", parent=styles["Lead"], fontName=BOLD, fontSize=18, leading=22, textColor=ACCENT))]
    doc.build(story)


def poster() -> None:
    width, height = landscape(A3)
    path = SUBMISSION / "PrivateOps-Agent-Poster.pdf"
    c = canvas.Canvas(str(path), pagesize=(width, height), pageCompression=1)
    c.setTitle("PrivateOps Agent Poster")
    c.setFillColor(colors.HexColor("#0b0e14")); c.rect(0, 0, width, height, fill=1, stroke=0)
    c.setFillColor(colors.HexColor("#2b1713")); c.circle(width * .79, height * .92, 95 * mm, fill=1, stroke=0)
    c.setFillColor(ACCENT); c.setFont(BOLD, 13); c.drawString(22 * mm, height - 25 * mm, "2026 AMD AI DEVMASTER · TRACK 2")
    c.setFillColor(colors.white); c.setFont(BOLD, 56); c.drawString(22 * mm, height - 67 * mm, "Permission before action.")
    c.setFillColor(colors.HexColor("#b6bdc9")); c.setFont(FONT, 19); c.drawString(22 * mm, height - 82 * mm, "A private computer AI with broad visibility and deliberate action on Radeon + ROCm.")
    c.setStrokeColor(colors.HexColor("#704033")); c.roundRect(width - 93 * mm, height - 36 * mm, 69 * mm, 14 * mm, 7 * mm, fill=0, stroke=1)
    c.setFillColor(colors.HexColor("#ff866d")); c.setFont(BOLD, 12); c.drawCentredString(width - 58.5 * mm, height - 31 * mm, "AMD RADEON + ROCm")
    cards = [
        ("01", "BROAD VISIBILITY", "See enough to help", ["14 bilingual RAG sources", "Project + Windows tools", "Source-visible answers"], BLUE),
        ("02", "DELIBERATE ACTION", "Permission is explicit", ["Safe read-only checks", "Exact-action confirmation", "Blocked exfiltration"], GREEN),
        ("03", "EVIDENCE FOR DECISIONS", "Audit + GPU proof", ["Append-only local ledger", "1,511.072 ms", "32.427 tokens/s"], ACCENT),
    ]
    card_y = 47 * mm; card_h = 108 * mm; gap = 8 * mm; card_w = (width - 44 * mm - 2 * gap) / 3
    for index, (num, label, title, points, color) in enumerate(cards):
        x = 22 * mm + index * (card_w + gap)
        c.setFillColor(colors.HexColor("#121720")); c.setStrokeColor(colors.HexColor("#323a49")); c.roundRect(x, card_y, card_w, card_h, 5 * mm, fill=1, stroke=1)
        c.setFillColor(color); c.setFont(BOLD, 12); c.drawString(x + 8 * mm, card_y + card_h - 13 * mm, f"{num} · {label}")
        c.setFillColor(colors.white); c.setFont(BOLD, 22); c.drawString(x + 8 * mm, card_y + card_h - 31 * mm, title)
        c.setFont(FONT, 14); c.setFillColor(colors.HexColor("#b7bec9"))
        for point_index, point in enumerate(points):
            c.setFillColor(color); c.circle(x + 10 * mm, card_y + card_h - (50 + point_index * 14) * mm, 1.5 * mm, fill=1, stroke=0)
            c.setFillColor(colors.HexColor("#b7bec9")); c.drawString(x + 16 * mm, card_y + card_h - (52 + point_index * 14) * mm, point)
    c.setStrokeColor(colors.HexColor("#323a49")); c.line(22 * mm, 31 * mm, width - 22 * mm, 31 * mm)
    c.setFillColor(colors.white); c.setFont(BOLD, 18); c.drawString(22 * mm, 19 * mm, "PrivateOps Agent")
    c.setFillColor(colors.HexColor("#7f8998")); c.setFont(FONT, 11); c.drawRightString(width - 22 * mm, 19 * mm, "Broad visibility · deliberate action · evidence for every decision")
    c.save()


def architecture_png() -> None:
    image = Image.new("RGB", (1400, 820), "#0b0e14")
    draw = ImageDraw.Draw(image)
    font_path = "C:/Windows/Fonts/arial.ttf"
    bold_path = "C:/Windows/Fonts/arialbd.ttf"
    font = lambda size: ImageFont.truetype(font_path, size) if Path(font_path).exists() else ImageFont.load_default()
    bold = lambda size: ImageFont.truetype(bold_path, size) if Path(bold_path).exists() else ImageFont.load_default()
    draw.text((70, 45), "PRIVATEOPS AGENT · PERMISSION-FIRST ARCHITECTURE", fill="#ff5b35", font=bold(20))

    def panel(box, title, lines, color):
        draw.rounded_rectangle(box, radius=20, fill="#151a24", outline="#343c4d", width=2)
        draw.ellipse((box[0] + 28, box[1] + 34, box[0] + 48, box[1] + 54), fill=color)
        draw.text((box[0] + 62, box[1] + 28), title, fill="#f3f0e8", font=bold(24))
        for i, line in enumerate(lines):
            draw.text((box[0] + 34, box[1] + 100 + i * 50), line, fill="#9aa2b2", font=font(18))

    panel((70, 125, 340, 685), "Trust Console", ["Conversation", "Evidence", "Visible plan", "Permission gate", "Audit ledger", "Radeon proof"], "#ff5b35")
    panel((440, 125, 860, 685), "Permission Kernel", ["1 · Safe / confirm / blocked", "2 · Evidence retrieval", "3 · Plan + guarded tools", "4 · Local model synthesis", "5 · Append audit evidence"], "#6fe2ac")
    panel((965, 125, 1330, 300), "Local Knowledge", ["Files · chunks · evidence IDs"], "#76b7ff")
    panel((965, 325, 1330, 500), "Guarded Tools", ["Confined · allow-listed · confirmed"], "#6fe2ac")
    panel((965, 525, 1330, 700), "Radeon + ROCm", ["Loopback vLLM model server"], "#ff5b35")
    for start, end in [((340, 405), (440, 405)), ((860, 240), (965, 210)), ((860, 410), (965, 410)), ((860, 575), (965, 610))]:
        draw.line((start, end), fill="#596579", width=4)
        draw.polygon([(end[0], end[1]), (end[0] - 14, end[1] - 8), (end[0] - 14, end[1] + 8)], fill="#596579")
    draw.text((70, 760), "Only same-instance loopback ROCm is competition-eligible. Shared APIs remain development-only.", fill="#9aa2b2", font=font(17))
    image.save(ASSETS / "architecture.png", optimize=True)


def main() -> None:
    SUBMISSION.mkdir(parents=True, exist_ok=True)
    ASSETS.mkdir(parents=True, exist_ok=True)
    register_fonts()
    project_specification()
    poster()
    architecture_png()
    print("Generated project specification PDF, poster PDF, and architecture PNG.")


if __name__ == "__main__":
    main()
