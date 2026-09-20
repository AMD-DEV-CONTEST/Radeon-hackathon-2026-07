#!/usr/bin/env python3
"""Build the official English Track 2 project specification PDF."""

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate, Frame, KeepTogether, PageTemplate, Paragraph, Spacer,
    Table, TableStyle, PageBreak,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output/pdf/AMD_Quant_Assistant_Project_Specification.pdf"
RED = colors.HexColor("#ED1C24")
BLACK = colors.HexColor("#111111")
DARK = colors.HexColor("#242424")
GRAY = colors.HexColor("#666666")
LIGHT = colors.HexColor("#F3F4F6")
GREEN = colors.HexColor("#16865B")


class SpecDoc(BaseDocTemplate):
    def __init__(self, filename):
        super().__init__(filename, pagesize=A4, rightMargin=18*mm, leftMargin=18*mm,
                         topMargin=19*mm, bottomMargin=17*mm)
        frame = Frame(self.leftMargin, self.bottomMargin, self.width, self.height,
                      leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
        self.addPageTemplates(PageTemplate(id="main", frames=frame, onPage=self.decorate))

    def decorate(self, canvas, doc):
        canvas.saveState()
        if doc.page > 1:
            canvas.setStrokeColor(colors.HexColor("#DDDDDD"))
            canvas.line(18*mm, A4[1]-13*mm, A4[0]-18*mm, A4[1]-13*mm)
            canvas.setFont("Helvetica-Bold", 8)
            canvas.setFillColor(DARK)
            canvas.drawString(18*mm, A4[1]-10*mm, "AMD QUANT ASSISTANT")
            canvas.setFont("Helvetica", 8)
            canvas.setFillColor(GRAY)
            canvas.drawRightString(A4[0]-18*mm, 10*mm, f"Track 2 Project Specification  |  {doc.page}")
        canvas.restoreState()


styles = getSampleStyleSheet()
styles.add(ParagraphStyle(name="TitleX", parent=styles["Title"], fontName="Helvetica-Bold",
                          fontSize=29, leading=33, textColor=BLACK, alignment=TA_LEFT,
                          spaceAfter=5*mm))
styles.add(ParagraphStyle(name="Deck", parent=styles["Normal"], fontName="Helvetica",
                          fontSize=13, leading=18, textColor=GRAY, spaceAfter=7*mm))
styles.add(ParagraphStyle(name="H1X", parent=styles["Heading1"], fontName="Helvetica-Bold",
                          fontSize=20, leading=24, textColor=BLACK, spaceBefore=4*mm,
                          spaceAfter=3*mm))
styles.add(ParagraphStyle(name="H2X", parent=styles["Heading2"], fontName="Helvetica-Bold",
                          fontSize=12, leading=15, textColor=RED, spaceBefore=3*mm,
                          spaceAfter=2*mm))
styles.add(ParagraphStyle(name="BodyX", parent=styles["BodyText"], fontName="Helvetica",
                          fontSize=9.5, leading=14, textColor=DARK, spaceAfter=2.3*mm))
styles.add(ParagraphStyle(name="SmallX", parent=styles["BodyText"], fontName="Helvetica",
                          fontSize=8, leading=11, textColor=GRAY))
styles.add(ParagraphStyle(name="Metric", parent=styles["BodyText"], fontName="Helvetica-Bold",
                          fontSize=18, leading=20, textColor=BLACK, alignment=TA_CENTER))
styles.add(ParagraphStyle(name="MetricLabel", parent=styles["BodyText"], fontName="Helvetica",
                          fontSize=7.5, leading=10, textColor=GRAY, alignment=TA_CENTER))


def P(text, style="BodyX"):
    return Paragraph(text, styles[style])


def bullet(text):
    return Paragraph(f"<font color='#ED1C24'>●</font> &nbsp;{text}", styles["BodyX"])


def section(title, intro=None):
    out = [P(title, "H1X")]
    if intro:
        out.append(P(intro))
    return out


def standard_table(rows, widths=None):
    table = Table(rows, colWidths=widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), BLACK),
        ("TEXTCOLOR", (0,0), (-1,0), colors.white),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTNAME", (0,1), (-1,-1), "Helvetica"),
        ("FONTSIZE", (0,0), (-1,-1), 8),
        ("LEADING", (0,0), (-1,-1), 11),
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("GRID", (0,0), (-1,-1), .35, colors.HexColor("#D8D8D8")),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, LIGHT]),
        ("LEFTPADDING", (0,0), (-1,-1), 6),
        ("RIGHTPADDING", (0,0), (-1,-1), 6),
        ("TOPPADDING", (0,0), (-1,-1), 5),
        ("BOTTOMPADDING", (0,0), (-1,-1), 5),
    ]))
    return table


def build():
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    story = []

    story += [Spacer(1, 14*mm), P("AMD AI DEVMASTER HACKATHON 2026", "H2X"),
              P("AMD Quant Assistant", "TitleX"),
              P("A private, auditable quantitative investment Agent running locally on AMD Radeon GPU and ROCm.", "Deck")]
    metrics = [[P("24 / 24", "Metric"), P("98.1%", "Metric"), P("285", "Metric"), P("32K", "Metric")],
               [P("CN evaluation", "MetricLabel"), P("token accuracy", "MetricLabel"), P("tests passed", "MetricLabel"), P("served context", "MetricLabel")]]
    mt = Table(metrics, colWidths=[42*mm]*4, rowHeights=[14*mm, 8*mm])
    mt.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),LIGHT), ("BOX",(0,0),(-1,-1),.8,colors.HexColor("#D9D9D9")),
                            ("INNERGRID",(0,0),(-1,-1),.4,colors.HexColor("#D9D9D9")), ("VALIGN",(0,0),(-1,-1),"MIDDLE")]))
    story += [mt, Spacer(1, 9*mm), P("One-line pitch", "H2X"),
              P("The model proposes; deterministic code verifies; an independent Risk Agent has veto authority."),
              Spacer(1, 6*mm), P("Track 2 - Development and Local Deployment of Private AI Agents", "SmallX"),
              P("Submission repository: github.com/gxinxing/Radeon-hackathon-2026-07", "SmallX"), PageBreak()]

    story += section("1. Application scenario", "Domestic-market research is full of natural-language ideas that cannot be trusted until they are grounded, structured, measured, and risk checked. The project turns an ordinary user request into a traceable decision workflow while keeping data and inference local.")
    story += [bullet("General questions receive a natural assistant response instead of being forced into a strategy template."),
              bullet("Quantitative requests use RAG, structured DSL, deterministic validation, backtesting, and risk reporting."),
              bullet("The reproducible demo uses deterministic synthetic domestic-market data and never places real orders."),
              P("Target users", "H2X"),
              standard_table([["User", "Need", "Delivered experience"],
                              ["Individual researcher", "Turn an idea into a measurable strategy", "Natural language to validated DSL and backtest"],
                              ["Quant team", "Audit model behavior", "Repair logs, sources, constraints, and risk verdict"],
                              ["Private deployment owner", "Keep inference local", "ROCm vLLM endpoint and self-hosted interfaces"]], [37*mm, 55*mm, 78*mm]),
              Spacer(1, 5*mm)]
    story += section("2. Agent architecture")
    flow = [[P("USER", "MetricLabel"), "→", P("INTENT ROUTER", "MetricLabel"), "→", P("RETRIEVAL AGENT", "MetricLabel"), "→", P("REASONING AGENT", "MetricLabel"), "→", P("RISK AGENT", "MetricLabel")],
            ["", "", P("General answer", "SmallX"), "", P("RAG + confidence", "SmallX"), "", P("Qwen + LoRA", "SmallX"), "", P("Independent veto", "SmallX")]]
    ft = Table(flow, colWidths=[20*mm,7*mm,28*mm,7*mm,33*mm,7*mm,33*mm,7*mm,29*mm], rowHeights=[13*mm,11*mm])
    ft.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),BLACK), ("TEXTCOLOR",(0,0),(-1,0),colors.white),
                            ("ALIGN",(0,0),(-1,-1),"CENTER"), ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
                            ("BOX",(0,0),(-1,-1),.6,colors.HexColor("#CFCFCF")), ("INNERGRID",(0,0),(-1,-1),.3,colors.HexColor("#DCDCDC"))]))
    story += [ft, Spacer(1, 4*mm), P("Execution path: natural language → RAG → strategy DSL → canonicalization → schema and semantic validation → deterministic backtest → independent risk report.")]
    story += [PageBreak()]

    story += section("3. Core Agent capabilities")
    story += [standard_table([["Capability", "Implementation", "Evidence"],
        ["Reasoning", "ReAct Thought / Action / Observation loop", "src/agent/core.py"],
        ["Planning", "Intent routing and dynamic tool sequencing", "src/agent/orchestrator.py"],
        ["Tool use", "Knowledge, indicators, validation, backtest, report", "src/agent/tools.py"],
        ["Memory", "Working, episodic, and semantic tiers", "src/agent/memory.py"],
        ["Task execution", "DSL, backtest, walk-forward, risk verdict", "src/dsl and src/backtest"],
        ["Self-healing", "Allow-listed diagnose, repair, verify, rollback graph", "scripts/graph_engine.py"]], [29*mm, 83*mm, 58*mm])]
    story += section("4. Model and local deployment", "Qwen2.5-7B is adapted with FP16 LoRA for domestic-market strategy generation. The merged model is served by vLLM through an OpenAI-compatible endpoint, allowing Open WebUI, Dify, and the Python Agent runtime to use the same private model asset.")
    story += [standard_table([["Layer", "Configuration"],
        ["Base model", "Qwen2.5-7B-Instruct"], ["Adapter", "LoRA r=64, alpha=128, dropout=0.05"],
        ["Serving", "vLLM FP16, model name models/qwen-trader-merged"], ["Endpoint", "http://127.0.0.1:8000/v1"],
        ["Interfaces", "Open WebUI, Dify six-node workflow, optional Gradio"]], [45*mm, 125*mm]), PageBreak()]

    story += section("5. AMD Radeon and ROCm optimization")
    story += [standard_table([["Item", "Measured configuration"],
        ["GPU", "AMD Radeon Graphics, gfx1100, 48 GiB VRAM"], ["ROCm", "7.2.1"],
        ["Training", "400 samples, 39 steps, 615 seconds"], ["Peak training memory", "16.21 GB"],
        ["Inference", "vLLM FP16, 32,768-token served context"], ["Runtime", "ROCm-native local inference; no hosted model API"]], [56*mm, 114*mm]),
        P("Optimization choices", "H2X"),
        bullet("FP16 LoRA limits training cost while preserving the full local base model."),
        bullet("vLLM provides continuous batching and an OpenAI-compatible interface for multiple Agent consumers."),
        bullet("Context compaction at 20K tokens and 512/128 RAG chunking prevent long-chat overflow."),
        bullet("The Graph Engine verifies services and repairs only allow-listed configuration with rollback."),
        P("Measured evaluation", "H2X"),
        standard_table([["Metric", "Before", "Final"], ["Overall pass rate", "45.83%", "100% (24/24)"],
                        ["JSON validity", "75%", "100%"], ["Instrument match", "70.83%", "100%"],
                        ["Constraint compliance", "45.83%", "100%"], ["Average latency", "10.24 s", "8.30 s"]], [62*mm, 50*mm, 58*mm])]
    story += [PageBreak()]

    story += section("6. Safety, reproducibility, and limitations")
    story += [bullet("Risk constraints are implemented in deterministic code and cannot be overridden by model text."),
              bullet("RAG content is bounded, source-aware, and confidence gated."),
              bullet("No live order is submitted; paper mode is explicitly labeled simulation."),
              bullet("Synthetic data makes the system path reproducible, but does not prove real investment performance."),
              bullet("The 24/24 score includes transparent typed canonicalization and validation, not unconstrained raw-model accuracy."),
              P("Reproduction", "H2X"),
              P("1. Place the merged model at models/qwen-trader-merged.  2. Run bash scripts/setup.sh to start the API and vLLM.  3. Run bash scripts/verify_submission.sh.  4. Review artifacts/cn_market_eval_reproduced.json."),
              P("Deliverables", "H2X"),
              standard_table([["Deliverable", "Location"], ["Source and tests", "src/, tests/, scripts/"],
                              ["Training and serving", "training/"], ["Dify workflow and tools", "dify/"],
                              ["Evaluation evidence", "artifacts/"], ["Technical documentation", "README.md and docs/"]], [62*mm, 108*mm]),
              Spacer(1, 7*mm), P("Disclaimer", "H2X"),
              P("This project is a hackathon research demonstration. It is not investment advice, does not connect to a live brokerage account, and does not promise trading returns.")]

    SpecDoc(str(OUTPUT)).build(story)
    print(OUTPUT)


if __name__ == "__main__":
    build()
