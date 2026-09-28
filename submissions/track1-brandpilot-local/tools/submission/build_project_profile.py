"""Build the judge-facing BrandPilot Local Project Profile PDF."""

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    Image,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "submission" / "BrandPilot-Local-Project-Profile.pdf"
SHOTS = ROOT / "evidence" / "final-submission" / "screenshots"

PAGE_W, PAGE_H = A4
MARGIN = 18 * mm
RED = colors.HexColor("#EF3340")
INK = colors.HexColor("#F6F3F2")
MUTED = colors.HexColor("#B5AEAC")
BG = colors.HexColor("#08080A")
CARD = colors.HexColor("#141417")
LINE = colors.HexColor("#303036")
GREEN = colors.HexColor("#67D6A5")


styles = getSampleStyleSheet()
styles.add(ParagraphStyle(name="CoverKicker", fontName="Helvetica-Bold", fontSize=10, leading=13, textColor=RED, spaceAfter=8, tracking=1.5))
styles.add(ParagraphStyle(name="CoverTitle", fontName="Helvetica-Bold", fontSize=31, leading=34, textColor=INK, spaceAfter=12))
styles.add(ParagraphStyle(name="CoverLead", fontName="Helvetica", fontSize=13, leading=19, textColor=MUTED, spaceAfter=16))
styles.add(ParagraphStyle(name="H1Dark", fontName="Helvetica-Bold", fontSize=24, leading=28, textColor=INK, spaceAfter=10))
styles.add(ParagraphStyle(name="H2Dark", fontName="Helvetica-Bold", fontSize=15, leading=18, textColor=INK, spaceBefore=8, spaceAfter=6))
styles.add(ParagraphStyle(name="BodyDark", fontName="Helvetica", fontSize=9.3, leading=14, textColor=MUTED, spaceAfter=7))
styles.add(ParagraphStyle(name="SmallDark", fontName="Helvetica", fontSize=7.8, leading=11, textColor=MUTED))
styles.add(ParagraphStyle(name="Callout", fontName="Helvetica-Bold", fontSize=12, leading=16, textColor=INK))


def page_background(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(BG)
    canvas.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    canvas.setFillColor(RED)
    canvas.rect(MARGIN, PAGE_H - 13 * mm, 14 * mm, 1.4 * mm, fill=1, stroke=0)
    canvas.setFillColor(colors.HexColor("#7B7574"))
    canvas.setFont("Helvetica", 7.5)
    canvas.drawString(MARGIN, 10 * mm, "BrandPilot Local - AMD AI DevMaster Track 1")
    canvas.drawRightString(PAGE_W - MARGIN, 10 * mm, str(doc.page))
    canvas.restoreState()


def img(name: str, width: float, height: float | None = None) -> Image:
    item = Image(str(SHOTS / name))
    ratio = item.imageHeight / item.imageWidth
    item.drawWidth = width
    item.drawHeight = height if height is not None else width * ratio
    return item


def section(title: str, eyebrow: str) -> list:
    return [Paragraph(eyebrow.upper(), styles["CoverKicker"]), Paragraph(title, styles["H1Dark"])]


def bullet(text: str) -> Paragraph:
    return Paragraph(f"<font color='#EF3340'>-</font>&nbsp;&nbsp;{text}", styles["BodyDark"])


def card_table(items: list[tuple[str, str]], widths=None) -> Table:
    data = [[Paragraph(k, styles["SmallDark"]), Paragraph(v, styles["Callout"])] for k, v in items]
    table = Table(data, colWidths=widths or [48 * mm, 120 * mm], hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), CARD),
        ("BOX", (0, 0), (-1, -1), 0.5, LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return table


def build_story() -> list:
    story: list = []
    story += [Spacer(1, 23 * mm), Paragraph("AMD AI DEVMASTER HACKATHON - TRACK 1", styles["CoverKicker"]), Paragraph("BrandPilot Local", styles["CoverTitle"])]
    story.append(Paragraph("A review-first campaign creation studio on a verified AMD Radeon and ROCm foundation.", styles["CoverLead"]))
    story.append(img("home-desktop.png", 168 * mm, 95 * mm))
    story += [Spacer(1, 9 * mm), Paragraph("PROJECT PROFILE", styles["CoverKicker"]), Paragraph("Talal Khawaja  |  Aqeela Urooj", styles["Callout"]), Spacer(1, 4 * mm), Paragraph("Mock-first local product. Recorded Radeon evidence. Honest browser-edge boundary.", styles["BodyDark"]), PageBreak()]

    story += section("The campaign workflow is fragmented", "Problem")
    story.append(Paragraph("Small brands and creative teams often move one campaign across prompt tools, design files, copy documents, and approval threads. That fragmentation slows iteration, weakens traceability, and can expose sensitive product assets to unnecessary services.", styles["BodyDark"]))
    story += [Spacer(1, 3 * mm), Paragraph("BrandPilot brings the system together", styles["H2Dark"])]
    for text in [
        "Validated rights-cleared product-image intake",
        "Audience, benefits, tone, colors, creative direction, formats, and guardrails",
        "Multiple disclosed campaign concepts and copy in one board",
        "Persisted human approval, rejection, or needs-changes state",
        "Mock by default; authenticated Radeon worker only by explicit opt-in",
    ]:
        story.append(bullet(text))
    story += [Spacer(1, 5 * mm), img("studio-desktop.png", 168 * mm, 91 * mm), PageBreak()]

    story += section("One asset becomes an accountable campaign", "Product experience")
    flow = [
        ("01", "Upload", "Validated product image"),
        ("02", "Direct", "Campaign context and guardrails"),
        ("03", "Create", "Four labelled mock directions"),
        ("04", "Review", "Stored human decision"),
    ]
    flow_table = Table([[Paragraph(n, styles["CoverKicker"]), Paragraph(f"<b>{t}</b><br/><font color='#B5AEAC'>{d}</font>", styles["BodyDark"])] for n, t, d in flow], colWidths=[18 * mm, 150 * mm])
    flow_table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), CARD), ("BOX", (0, 0), (-1, -1), 0.5, LINE), ("INNERGRID", (0, 0), (-1, -1), 0.35, LINE), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
    story += [flow_table, Spacer(1, 6 * mm), img("results-desktop.png", 168 * mm, 94 * mm), Spacer(1, 4 * mm), Paragraph("The screen above is a local mock demonstration. Mock concepts are explicitly labelled and do not imply GPU execution.", styles["SmallDark"]), PageBreak()]

    story += section("Architecture keeps every boundary visible", "System design")
    story.append(img("architecture-desktop.png", 168 * mm, 94 * mm))
    story += [Spacer(1, 5 * mm)]
    for text in [
        "Next.js frontend for responsive campaign configuration and review",
        "FastAPI for upload validation, JSON persistence, protected results, and review",
        "Experimental single-job worker with lazy load and pipeline reuse",
        "Pinned SDXL img2img in fp16 on AMD Radeon through PyTorch/HIP",
        "Bearer authentication, explicit CORS, loopback bind, and no CPU/mock fallback",
    ]:
        story.append(bullet(text))
    story.append(PageBreak())

    story += section("Real SDXL ran on AMD Radeon with ROCm", "Radeon implementation")
    env = Table([[img("verified-radeon-environment.png", 91 * mm, 44 * mm), img("verified-radeon-output.png", 68 * mm, 68 * mm)]], colWidths=[96 * mm, 72 * mm])
    env.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), CARD), ("BOX", (0, 0), (-1, -1), 0.5, LINE), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ALIGN", (1, 0), (1, 0), "CENTER"), ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
    story += [env, Spacer(1, 5 * mm)]
    story.append(card_table([
        ("GPU / architecture", "AMD Radeon Graphics / gfx1100"),
        ("PyTorch / HIP", "2.9.1+gitff65f5b / 7.2.53211-e1a6bc5663"),
        ("Model", "SDXL base 1.0, exact revision pinned"),
        ("Pipeline", "StableDiffusionXLImg2ImgPipeline, fp16"),
        ("Runtime choices", "No CPU offload; no attention slicing"),
    ]))
    story.append(Paragraph("The real image above was generated on AMD Radeon with ROCm during the verified cloud session.", styles["SmallDark"]))
    story.append(PageBreak())

    story += section("Measured performance, not projected performance", "Verified result")
    story.append(card_table([
        ("Resolution", "768 x 768"),
        ("Steps / strength / guidance", "15 / 0.35 / 6.5"),
        ("Seed", "20260725"),
        ("Cold model load", "132.295 seconds"),
        ("Generation", "222.111 seconds"),
        ("Total smoke test", "357.706 seconds"),
        ("Peak allocated / reserved", "13.41 GiB / 14.31 GiB"),
        ("Output SHA-256", "bce21d016a8179ac4ddabcbf5869a71eacf03565948d0d1f97d24e279b125452"),
    ]))
    story += [Spacer(1, 7 * mm), Paragraph("Application-integrated loopback proof", styles["H2Dark"]), Paragraph("A later authenticated FastAPI-to-Radeon loopback job completed in 252.243 seconds from start to completion and persisted an Approved human-review state. Session 1 memory/hash values are not presented as measurements from that later job.", styles["BodyDark"]), PageBreak()]

    story += section("The public edge is the one missing link", "Honest validation")
    story.append(img("final-dns-blocker.png", 168 * mm, 94 * mm))
    story += [Spacer(1, 5 * mm)]
    matrix = [
        ("Standalone SDXL on Radeon/ROCm", "VERIFIED"),
        ("Authenticated FastAPI loopback generation", "VERIFIED"),
        ("Official rc-tunnel 0.3.0 install and activation", "VERIFIED"),
        ("Chrome TLS/auth/CORS/project/upload in Session 2b", "VERIFIED"),
        ("Protected real result rendered through public edge", "BLOCKED - DNS"),
    ]
    story.append(card_table(matrix))
    story.append(Paragraph("No unofficial tunnel, TLS bypass, host override, or fabricated success was used. The final retry stopped before model load and the instance was destroyed.", styles["BodyDark"]))
    story.append(PageBreak())

    story += section("Human review is part of the result", "Responsible AI")
    story.append(img("review-approved.png", 168 * mm, 105 * mm))
    story += [Spacer(1, 5 * mm)]
    for text in [
        "Every mock or experimental result keeps its disclosure.",
        "Approval, rejection, and requested changes are stored with the project.",
        "Rights-cleared inputs, generated-media disclosure, and product-claim review remain required.",
        "Local processing can reduce exposure; it does not replace copyright, trademark, or commercial-use review.",
    ]:
        story.append(bullet(text))
    story.append(PageBreak())

    story += section("Practical today, disciplined about tomorrow", "Value and roadmap")
    story.append(Paragraph("BrandPilot's innovation is the accountable campaign system around generation: brand context, multiple directions, output framing, provenance, persistence, and human decision-making in one premium responsive product.", styles["BodyDark"]))
    story.append(Paragraph("Current limitations", styles["H2Dark"]))
    for text in [
        "No completed public browser-to-Radeon generation or permanent hosted backend",
        "No product identity, logo, or packaging-text preservation claim",
        "No IP-Adapter, ControlNet, LoRA, fine-tuning, video, or comparative benchmark",
        "No production readiness or commercial model/source clearance",
    ]:
        story.append(bullet(text))
    story.append(Paragraph("Next measured phase", styles["H2Dark"]))
    story.append(Paragraph("After submission, compare base SDXL against IP-Adapter plus masking/compositing using defined product-preservation quality criteria.", styles["BodyDark"]))
    story += [Spacer(1, 6 * mm), Paragraph("Team", styles["H2Dark"]), card_table([("Talal Khawaja", "Project lead, application development, Radeon integration, documentation, and demo preparation"), ("Aqeela Urooj", "Product testing, output review, usability feedback, and documentation review")]), Spacer(1, 6 * mm), Paragraph("Repository: github.com/kmt9967/brandpilot-local", styles["Callout"]), Paragraph("Evidence map: docs/judging-evidence-map.md", styles["BodyDark"]), Paragraph("Claim boundary: docs/final-claim-audit.md", styles["BodyDark"])]
    return story


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc = BaseDocTemplate(
        str(OUT),
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=18 * mm,
        bottomMargin=16 * mm,
        title="BrandPilot Local Project Profile",
        author="BrandPilot Local Team",
        subject="AMD AI DevMaster Hackathon Track 1 submission",
        creator="BrandPilot Local",
    )
    frame = Frame(MARGIN, 16 * mm, PAGE_W - 2 * MARGIN, PAGE_H - 34 * mm, id="body")
    doc.addPageTemplates([PageTemplate(id="dark", frames=[frame], onPage=page_background)])
    doc.build(build_story())


if __name__ == "__main__":
    main()
