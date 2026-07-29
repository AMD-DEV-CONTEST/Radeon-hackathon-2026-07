from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    Flowable,
    Frame,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "output" / "pdf" / "RedactFlow-AMD-Project-Report.pdf"
OUTPUT.parent.mkdir(parents=True, exist_ok=True)

PAPER = colors.HexColor("#F4F0E8")
INK = colors.HexColor("#171717")
MUTED = colors.HexColor("#676B67")
LINE = colors.HexColor("#C8C1B6")
RED = colors.HexColor("#ED1C24")
WHITE = colors.HexColor("#FFFDF8")


class ArchitectureDiagram(Flowable):
    def __init__(self, width: float, height: float = 118 * mm):
        super().__init__()
        self.width = width
        self.height = height

    def draw(self) -> None:
        canvas = self.canv
        canvas.saveState()
        canvas.setFillColor(WHITE)
        canvas.setStrokeColor(LINE)
        canvas.roundRect(0, 0, self.width, self.height, 4, fill=1, stroke=1)

        nodes = [
            (8, 74, 43, 25, "PRIVATE\nVAULT"),
            (61, 74, 43, 25, "LOCAL\nRAG"),
            (114, 74, 43, 25, "VISIBLE\nPLAN"),
            (114, 28, 43, 25, "PERMISSION\nGATE"),
            (61, 28, 43, 25, "REDACTION\nTOOLS"),
            (8, 28, 43, 25, "SAFE\nRELEASE"),
        ]
        scale_x = self.width / (165 * mm)
        scale_y = self.height / (110 * mm)

        def px(value: float) -> float:
            return value * mm * scale_x

        def py(value: float) -> float:
            return value * mm * scale_y

        canvas.setLineWidth(1.2)
        canvas.setStrokeColor(INK)
        arrow_pairs = [((51, 86), (61, 86)), ((104, 86), (114, 86)), ((135, 74), (135, 53)), ((114, 40), (104, 40)), ((61, 40), (51, 40))]
        for (x1, y1), (x2, y2) in arrow_pairs:
            canvas.line(px(x1), py(y1), px(x2), py(y2))
            canvas.line(px(x2), py(y2), px(x2 - 2 if x2 > x1 else x2 + 2), py(y2 + 1.3))
            canvas.line(px(x2), py(y2), px(x2 - 2 if x2 > x1 else x2 + 2), py(y2 - 1.3))

        for index, (x, y, w, h, label) in enumerate(nodes):
            canvas.setFillColor(INK if index not in (3, 5) else RED)
            canvas.roundRect(px(x), py(y), px(w), py(h), 3, fill=1, stroke=0)
            canvas.setFillColor(WHITE)
            canvas.setFont("Helvetica-Bold", 9)
            line1, line2 = label.split("\n")
            center = px(x + w / 2)
            canvas.drawCentredString(center, py(y + h / 2 + 2.4), line1)
            canvas.drawCentredString(center, py(y + h / 2 - 2.4), line2)

        canvas.setFillColor(MUTED)
        canvas.setFont("Helvetica", 8.5)
        canvas.drawString(px(8), py(9), "Optional local Qwen inference: ROCm-enabled llama.cpp on AMD Radeon GPU")
        canvas.setStrokeColor(RED)
        canvas.setDash(4, 3)
        canvas.line(px(61), py(17), px(157), py(17))
        canvas.restoreState()


class ReportDoc(BaseDocTemplate):
    def __init__(self, filename: str):
        super().__init__(
            filename,
            pagesize=A4,
            leftMargin=18 * mm,
            rightMargin=18 * mm,
            topMargin=20 * mm,
            bottomMargin=18 * mm,
            title="RedactFlow AMD Project Report",
            author="RedactFlow contributors",
        )
        frame = Frame(self.leftMargin, self.bottomMargin, self.width, self.height, id="main")
        self.addPageTemplates(PageTemplate(id="report", frames=[frame], onPage=self.draw_page))

    def draw_page(self, canvas, doc) -> None:
        canvas.saveState()
        canvas.setFillColor(PAPER)
        canvas.rect(0, 0, A4[0], A4[1], fill=1, stroke=0)
        canvas.setStrokeColor(INK)
        canvas.setLineWidth(0.7)
        canvas.line(18 * mm, A4[1] - 13 * mm, A4[0] - 18 * mm, A4[1] - 13 * mm)
        canvas.setFont("Helvetica-Bold", 8)
        canvas.setFillColor(INK)
        canvas.drawString(18 * mm, A4[1] - 10 * mm, "REDACTFLOW AMD")
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(MUTED)
        canvas.drawRightString(A4[0] - 18 * mm, A4[1] - 10 * mm, "2026 AMD AI DEVMASTER - AGENTIC AI")
        canvas.setStrokeColor(LINE)
        canvas.line(18 * mm, 12 * mm, A4[0] - 18 * mm, 12 * mm)
        canvas.setFont("Helvetica", 7.5)
        canvas.drawString(18 * mm, 8 * mm, "LOCAL-FIRST DOCUMENT RELEASE AGENT")
        canvas.drawRightString(A4[0] - 18 * mm, 8 * mm, f"{doc.page:02d}")
        canvas.restoreState()


styles = getSampleStyleSheet()
styles.add(
    ParagraphStyle(
        name="Eyebrow",
        parent=styles["Normal"],
        fontName="Courier-Bold",
        fontSize=8,
        leading=10,
        textColor=RED,
        spaceAfter=6,
        uppercase=True,
    )
)
styles.add(
    ParagraphStyle(
        name="TitleXL",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=36,
        leading=37,
        tracking=-1.2,
        textColor=INK,
        alignment=TA_LEFT,
        spaceAfter=12,
    )
)
styles.add(
    ParagraphStyle(
        name="Deck",
        parent=styles["Normal"],
        fontName="Times-Roman",
        fontSize=16,
        leading=22,
        textColor=MUTED,
        spaceAfter=14,
    )
)
styles.add(
    ParagraphStyle(
        name="H1x",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=24,
        leading=28,
        textColor=INK,
        spaceBefore=6,
        spaceAfter=12,
    )
)
styles.add(
    ParagraphStyle(
        name="H2x",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=14,
        leading=17,
        textColor=INK,
        spaceBefore=10,
        spaceAfter=6,
    )
)
styles.add(
    ParagraphStyle(
        name="Bodyx",
        parent=styles["BodyText"],
        fontName="Times-Roman",
        fontSize=10.5,
        leading=15,
        textColor=INK,
        spaceAfter=8,
    )
)
styles.add(
    ParagraphStyle(
        name="Smallx",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=12,
        textColor=MUTED,
    )
)
styles.add(
    ParagraphStyle(
        name="Bulletx",
        parent=styles["Bodyx"],
        leftIndent=10,
        firstLineIndent=-8,
        bulletIndent=0,
        spaceAfter=4,
    )
)


def bullet(text: str) -> Paragraph:
    return Paragraph(f"- {text}", styles["Bulletx"])


story = [
    Spacer(1, 28 * mm),
    Paragraph("PROJECT REPORT / 01", styles["Eyebrow"]),
    Paragraph("RedactFlow<br/>AMD", styles["TitleXL"]),
    Paragraph(
        "A local-first document release agent that retrieves evidence, detects sensitive values, pauses at a human permission boundary, and creates auditable release-safe copies.",
        styles["Deck"],
    ),
    Spacer(1, 7 * mm),
    Table(
        [
            ["TRACK", "Agentic AI"],
            ["LOCAL MODEL", "Qwen2.5-7B-Instruct via ROCm llama.cpp"],
            ["CORE CLAIM", "No closed remote API required"],
            ["CAPABILITIES", "RAG / tools / planning / memory / permissions"],
        ],
        colWidths=[38 * mm, 118 * mm],
        style=TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), WHITE),
                ("TEXTCOLOR", (0, 0), (0, -1), RED),
                ("FONTNAME", (0, 0), (0, -1), "Courier-Bold"),
                ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("GRID", (0, 0), (-1, -1), 0.5, LINE),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 9),
                ("RIGHTPADDING", (0, 0), (-1, -1), 9),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        ),
    ),
    PageBreak(),
    Paragraph("CONTEXT / 02", styles["Eyebrow"]),
    Paragraph("A safer path from private source to public statement", styles["H1x"]),
    Paragraph(
        "Operational releases are often assembled from private incident notes, migration plans, vendor messages, and research documents. Those sources mix approved facts with personal contacts, credentials, internal addresses, and statements that are not ready for publication.",
        styles["Bodyx"],
    ),
    Paragraph(
        "A generic remote copilot creates two risks at once: the source may leave the organization, and the final answer may hide which actions were taken. RedactFlow keeps the source local and turns the prompt into a visible sequence of constrained tools.",
        styles["Bodyx"],
    ),
    Spacer(1, 4 * mm),
    Paragraph("Target users", styles["H2x"]),
    bullet("Security and incident-response teams preparing public updates."),
    bullet("Operations teams publishing migration or vendor notices."),
    bullet("Researchers creating shareable summaries from private notes."),
    bullet("Small organizations that need on-device AI assistance."),
    Spacer(1, 6 * mm),
    Table(
        [
            [Paragraph("BEFORE", styles["Eyebrow"]), Paragraph("WITH REDACTFLOW", styles["Eyebrow"])],
            ["Copy private text into a general chat", "Store and retrieve from a local vault"],
            ["Trust an opaque answer", "Inspect grounded evidence"],
            ["Agent acts with broad authority", "Approve transform and write tools separately"],
            ["Overwrite or manually copy results", "Create non-destructive release copies"],
        ],
        colWidths=[78 * mm, 78 * mm],
        style=TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), INK),
                ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
                ("BACKGROUND", (0, 1), (-1, -1), WHITE),
                ("GRID", (0, 0), (-1, -1), 0.5, LINE),
                ("FONTNAME", (0, 1), (-1, -1), "Times-Roman"),
                ("FONTSIZE", (0, 1), (-1, -1), 9.5),
                ("LEADING", (0, 1), (-1, -1), 13),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 9),
                ("RIGHTPADDING", (0, 0), (-1, -1), 9),
                ("TOPPADDING", (0, 0), (-1, -1), 9),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
            ]
        ),
    ),
    PageBreak(),
    Paragraph("SYSTEM / 03", styles["Eyebrow"]),
    Paragraph("Architecture built around effects, not chat messages", styles["H1x"]),
    ArchitectureDiagram(174 * mm),
    Spacer(1, 5 * mm),
    Paragraph(
        "The FastAPI service exposes document, planning, execution, and memory endpoints. The interface shows every plan before execution and classifies tools as read, transform, or write. Transform and write actions remain blocked until a user explicitly enables them.",
        styles["Bodyx"],
    ),
    PageBreak(),
    Paragraph("AGENT CAPABILITIES / 04", styles["Eyebrow"]),
    Paragraph("All five required capabilities in one review loop", styles["H1x"]),
]

capabilities = [
    ("01", "Local RAG", "Overlapped local chunks are scored against the task. Retrieved passages remain visible beside the output."),
    ("02", "Tool use", "Narrow tools perform evidence search, sensitive-data inspection, redaction, and minimal audit persistence."),
    ("03", "Multi-step planning", "Every task becomes an ordered plan with purpose, effect class, and approval requirement."),
    ("04", "Local memory", "SQLite stores plan and decision metadata while excluding raw detected secrets from audit memories."),
    ("05", "Permission control", "Read operations can inspect; transformation and persistence must be approved independently."),
]

for number, title, description in capabilities:
    story.append(
        KeepTogether(
            [
                Table(
                    [[number, Paragraph(f"<b>{title}</b><br/>{description}", styles["Bodyx"])]],
                    colWidths=[18 * mm, 138 * mm],
                    style=TableStyle(
                        [
                            ("BACKGROUND", (0, 0), (0, 0), RED),
                            ("TEXTCOLOR", (0, 0), (0, 0), WHITE),
                            ("FONTNAME", (0, 0), (0, 0), "Courier-Bold"),
                            ("FONTSIZE", (0, 0), (0, 0), 11),
                            ("ALIGN", (0, 0), (0, 0), "CENTER"),
                            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                            ("BACKGROUND", (1, 0), (1, 0), WHITE),
                            ("BOX", (0, 0), (-1, -1), 0.5, LINE),
                            ("LEFTPADDING", (0, 0), (-1, -1), 10),
                            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                            ("TOPPADDING", (0, 0), (-1, -1), 9),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                        ]
                    ),
                ),
                Spacer(1, 3 * mm),
            ]
        )
    )

story.extend(
    [
        PageBreak(),
        Paragraph("AMD PLATFORM / 05", styles["Eyebrow"]),
        Paragraph("Local Qwen inference accelerated by Radeon and ROCm", styles["H1x"]),
        Paragraph(
            "RedactFlow connects to a local OpenAI-compatible llama.cpp server. The supplied launch script targets a HIP-enabled build, offloads model layers to the assigned AMD Radeon GPU, and binds the endpoint to loopback. Ordinary public endpoints are rejected by the client.",
            styles["Bodyx"],
        ),
        Paragraph("Recommended competition configuration", styles["H2x"]),
        bullet("AMD Radeon GPU allocated through the hackathon developer program."),
        bullet("ROCm release supported by the target image and GPU architecture."),
        bullet("llama.cpp built with GGML_HIP=ON and the matching AMDGPU target."),
        bullet("Qwen2.5-7B-Instruct GGUF sized for available VRAM."),
        Spacer(1, 5 * mm),
        Table(
            [
                ["EVIDENCE", "COMMAND / ARTIFACT"],
                ["GPU and ROCm environment", "python scripts/rocm_probe.py > artifacts/rocm-environment.json"],
                ["Repeatable inference latency", "python scripts/benchmark.py --runs 10 > artifacts/rocm-benchmark.json"],
                ["Local application runtime", "LOCAL_LLM_ENABLED=1 ./scripts/run_local.sh"],
                ["Model server", "./scripts/run_rocm_llama.sh"],
            ],
            colWidths=[52 * mm, 104 * mm],
            style=TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), INK),
                    ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
                    ("FONTNAME", (0, 0), (-1, 0), "Courier-Bold"),
                    ("BACKGROUND", (0, 1), (-1, -1), WHITE),
                    ("GRID", (0, 0), (-1, -1), 0.5, LINE),
                    ("FONTNAME", (0, 1), (0, -1), "Helvetica"),
                    ("FONTNAME", (1, 1), (1, -1), "Courier"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("LEADING", (0, 0), (-1, -1), 11),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 8),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ]
            ),
        ),
        PageBreak(),
        Paragraph("DELIVERY / 06", styles["Eyebrow"]),
        Paragraph("Reproducible by design", styles["H1x"]),
        Paragraph(
            "The repository includes pinned dependencies, sample data, deterministic demo mode, API and unit tests, an AMD environment probe, a repeatable benchmark, and a narrated demo script. A reviewer can validate the workflow on CPU first, then enable local inference on a Radeon machine without changing the application architecture.",
            styles["Bodyx"],
        ),
        Spacer(1, 4 * mm),
        Paragraph("Validation coverage", styles["H2x"]),
        bullet("Local retrieval selects grounded evidence from the correct document."),
        bullet("Sensitive values are detected and replaced without modifying source content."),
        bullet("Execution remains blocked when transform or write permissions are absent."),
        bullet("Approved execution produces release copies and a minimal local audit memory."),
        bullet("The browser workflow completes without console warnings or errors."),
        Spacer(1, 8 * mm),
        Table(
            [["OPEN SOURCE", "MIT LICENSE"], ["Repository", "RedactFlow AMD"], ["Track", "2026 AMD AI DevMaster - Agentic AI"], ["Submission", "Source + PDF + 3-5 minute video + PPT/poster"]],
            colWidths=[78 * mm, 78 * mm],
            style=TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), RED),
                    ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
                    ("FONTNAME", (0, 0), (-1, 0), "Courier-Bold"),
                    ("FONTSIZE", (0, 0), (-1, 0), 8),
                    ("BACKGROUND", (0, 1), (-1, -1), WHITE),
                    ("GRID", (0, 0), (-1, -1), 0.5, LINE),
                    ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                    ("FONTSIZE", (0, 1), (-1, -1), 9),
                    ("LEFTPADDING", (0, 0), (-1, -1), 9),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 9),
                    ("TOPPADDING", (0, 0), (-1, -1), 9),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
                ]
            ),
        ),
    ]
)


ReportDoc(str(OUTPUT)).build(story)
print(OUTPUT)
