#!/usr/bin/env python3
"""Build the Track 2 project specification PDF with ReportLab."""

from __future__ import annotations

import os
from pathlib import Path

from PIL import Image
from reportlab.lib.colors import Color, HexColor, black, white
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph


ROOT = Path(__file__).resolve().parents[3]
ASSETS = ROOT / "submission" / "en" / "assets"
OUTPUT = ROOT / "submission" / "en" / "deliverables" / "RDK_Agent_Project_Specification.pdf"
BILIBILI_URL = "https://www.bilibili.com/video/BV1t3up6iEhy/"
BAIDU_URL = "https://dagent-platform.bj.bcebos.com/amd-hackathon/amd-hackathon-2026-07.mp4?authorization=bce-auth-v1/ALTAKYR0nFJFHMGlFjuontyVVP/2026-08-06T12%3A43%3A01Z/-1/host/1a12970cc4c9439caa28199256b028f90e82ba41ac92c68fb921b271be0b0acd"
PAGE_W, PAGE_H = A4

INK = HexColor("#111318")
MUTED = HexColor("#5E6673")
LIGHT = HexColor("#F1F3F5")
RULE = HexColor("#C6CBD2")
BLUE = HexColor("#2F7DF6")
PALE_BLUE = HexColor("#E8F1FF")
CYAN = HexColor("#55D5E5")
CORAL = HexColor("#FF6B5E")
GREEN = HexColor("#16A36A")


def pstyle(size=10.5, leading=15, color=INK, bold=False, align=TA_LEFT):
    return ParagraphStyle(
        "body",
        fontName="Helvetica-Bold" if bold else "Helvetica",
        fontSize=size,
        leading=leading,
        textColor=color,
        alignment=align,
        spaceAfter=0,
        spaceBefore=0,
    )


def paragraph(c, text, x, y_top, width, *, size=10.5, leading=15, color=INK, bold=False):
    item = Paragraph(text, pstyle(size=size, leading=leading, color=color, bold=bold))
    _, height = item.wrap(width, PAGE_H)
    item.drawOn(c, x, y_top - height)
    return y_top - height


def card(c, x, y, w, h, *, fill=LIGHT, stroke=None, radius=8):
    c.setFillColor(fill)
    c.setStrokeColor(stroke or fill)
    c.roundRect(x, y, w, h, radius, fill=1, stroke=1 if stroke else 0)


def image_fit(c, path, x, y, w, h, *, mode="contain"):
    with Image.open(path) as im:
        iw, ih = im.size
    if mode == "cover":
        scale = max(w / iw, h / ih)
    else:
        scale = min(w / iw, h / ih)
    dw, dh = iw * scale, ih * scale
    dx, dy = x + (w - dw) / 2, y + (h - dh) / 2
    c.saveState()
    p = c.beginPath()
    p.rect(x, y, w, h)
    c.clipPath(p, stroke=0, fill=0)
    c.drawImage(ImageReader(str(path)), dx, dy, width=dw, height=dh, mask="auto")
    c.restoreState()


def page_header(c, kicker, title, subtitle=None):
    c.setFillColor(BLUE)
    c.rect(42, PAGE_H - 57, 42, 4, fill=1, stroke=0)
    c.setFont("Helvetica-Bold", 8.5)
    c.setFillColor(MUTED)
    c.drawString(92, PAGE_H - 60, kicker.upper())
    c.setFillColor(INK)
    title_width = PAGE_W - 84
    title_size = min(26, max(18, 26 * title_width / stringWidth(title, "Helvetica-Bold", 26)))
    c.setFont("Helvetica-Bold", title_size)
    c.drawString(42, PAGE_H - 100, title)
    if subtitle:
        paragraph(c, subtitle, 42, PAGE_H - 115, PAGE_W - 84, size=10.5, leading=14, color=MUTED)


def footer(c, number):
    c.setStrokeColor(RULE)
    c.setLineWidth(0.45)
    c.line(42, 34, PAGE_W - 42, 34)
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 7.5)
    c.drawString(42, 20, "RDK Agent | AMD Radeon AI Agent Hackathon | Track 2")
    c.drawRightString(PAGE_W - 42, 20, f"{number:02d} / 12")


def next_page(c, number):
    footer(c, number)
    c.showPage()


def bullet_list(c, items, x, y_top, width, *, size=10.5, leading=15, gap=7, bullet_color=BLUE):
    y = y_top
    for item in items:
        c.setFillColor(bullet_color)
        c.circle(x + 3, y - 6, 2.4, fill=1, stroke=0)
        y = paragraph(c, item, x + 14, y, width - 14, size=size, leading=leading) - gap
    return y


def label(c, text, x, y, *, fill=BLUE, width=None):
    c.setFont("Helvetica-Bold", 7.5)
    text_w = stringWidth(text, "Helvetica-Bold", 7.5)
    w = width or text_w + 16
    c.setFillColor(fill)
    c.roundRect(x, y, w, 18, 9, fill=1, stroke=0)
    c.setFillColor(white)
    c.drawCentredString(x + w / 2, y + 5.4, text)
    return w


def build():
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(OUTPUT), pagesize=A4, pageCompression=1)
    c.setTitle("RDK Agent - Track 2 Project Specification")
    c.setAuthor("d-robotics agent")
    c.setSubject("AMD Radeon AI Agent Hackathon 2026 - Track 2")

    # 01 - Cover
    image_fit(c, ASSETS / "rdk-agent-hero.png", 0, 315, PAGE_W, PAGE_H - 315, mode="cover")
    c.setFillColor(INK)
    c.rect(0, 0, PAGE_W, 345, fill=1, stroke=0)
    label(c, "TRACK 2 | AI AGENT APPLICATION", 42, 290, fill=BLUE)
    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 38)
    c.drawString(42, 235, "RDK Agent")
    paragraph(
        c,
        "A safety-governed multi-agent system that turns natural-language intent into verified actions on RDK development boards.",
        42,
        205,
        PAGE_W - 84,
        size=17,
        leading=23,
        color=white,
    )
    c.setFillColor(CYAN)
    c.rect(42, 122, 72, 3, fill=1, stroke=0)
    paragraph(
        c,
        "PRIVATE AMD RADEON INFERENCE  /  TOOL CALLING  /  MULTI-STEP PLANNING  /  PERMISSION BOUNDARIES",
        42,
        108,
        PAGE_W - 84,
        size=9.5,
        leading=13,
        color=HexColor("#D8DEE8"),
        bold=True,
    )
    c.setFont("Helvetica", 8.5)
    c.setFillColor(HexColor("#AAB3C0"))
    c.drawString(42, 48, "Team / participant: d-robotics agent")
    c.drawRightString(PAGE_W - 42, 48, "Submission build: 2026-08-05")
    c.showPage()

    # 02 - Sophon naming story
    page_header(
        c,
        "Naming story",
        "Why 'Sophon'? A literary metaphor made operational",
        "The name connects a memorable science-fiction idea to a transparent, owner-controlled device agent.",
    )
    image_fit(c, ASSETS / "sophon-three-body-concept.png", 42, 385, PAGE_W - 84, 300, mode="cover")
    c.setFillColor(white)
    c.setFillAlpha(0.9)
    c.roundRect(54, 405, 232, 67, 7, fill=1, stroke=0)
    c.setFillAlpha(1)
    paragraph(c, "Three stars send a geometric messenger across a data lattice toward an RDK board.", 68, 455, 205, size=9.2, leading=12.5, bold=True)
    cols = [42, 218, 394]
    titles = ["FICTIONAL METAPHOR", "RDK-SOPHON", "RDK-AGENT"]
    bodies = [
        "A Sophon is sent toward Earth to observe and communicate.",
        "A board-side probe observes telemetry, health and available actions.",
        "The host-side agent reasons, calls tools and requests governed board operations.",
    ]
    for i, x in enumerate(cols):
        c.setFillColor(BLUE if i == 1 else LIGHT)
        c.rect(x, 333, 145, 3, fill=1, stroke=0)
        c.setFont("Helvetica-Bold", 8.2)
        c.setFillColor(BLUE if i == 1 else MUTED)
        c.drawString(x, 315, titles[i])
        paragraph(c, bodies[i], x, 297, 145, size=9.4, leading=13)
    card(c, 42, 104, PAGE_W - 84, 112, fill=PALE_BLUE)
    paragraph(c, "The crucial difference", 60, 196, 220, size=13, leading=17, bold=True, color=BLUE)
    paragraph(
        c,
        "The fictional Sophon is covert. RDK Sophon is deliberately transparent: deployed by the board owner, constrained by explicit action packages, logged, auditable and reversible. The metaphor describes proximity and communication - not surveillance without consent.",
        60,
        171,
        PAGE_W - 120,
        size=10.4,
        leading=15,
    )
    paragraph(
        c,
        "Project-created AI-generated concept illustration; no official artwork or adaptation assets are used. This independent project is not endorsed by or affiliated with the work's author, publishers, rights holders, or screen adaptations.",
        42,
        82,
        PAGE_W - 84,
        size=7.8,
        leading=10.5,
        color=MUTED,
    )
    next_page(c, 2)

    # 03 - Problem and scenarios
    page_header(c, "Product value", "One intent, one governed path to a real board", "RDK Agent removes the fragile handoffs between coding, verification, packaging, deployment and device acceptance.")
    card(c, 42, 589, PAGE_W - 84, 95, fill=INK)
    paragraph(c, "Developer intent", 60, 660, 150, size=9, leading=12, color=CYAN, bold=True)
    paragraph(c, '"Add or repair a board capability, prove it, then deploy it safely."', 60, 635, PAGE_W - 120, size=15, leading=20, color=white, bold=True)
    y = 545
    scenarios = [
        ("01", "Build with evidence", "A coding agent works inside explicit write paths; tests and verification artifacts are required before the action package can advance."),
        ("02", "Deploy atomically", "The release step validates a deterministic package, deploys it to the board and keeps rollback information."),
        ("03", "Operate in natural language", "The installed Skill exposes board actions to the agent while the board daemon enforces the device-side boundary."),
    ]
    for num, title, body in scenarios:
        c.setFont("Helvetica-Bold", 22)
        c.setFillColor(BLUE)
        c.drawString(42, y, num)
        c.setFont("Helvetica-Bold", 13)
        c.setFillColor(INK)
        c.drawString(88, y + 3, title)
        paragraph(c, body, 88, y - 14, PAGE_W - 130, size=10, leading=14)
        c.setStrokeColor(RULE)
        c.line(42, y - 75, PAGE_W - 42, y - 75)
        y -= 118
    card(c, 42, 98, PAGE_W - 84, 92, fill=LIGHT)
    paragraph(c, "Definition of done", 60, 167, 170, size=12.5, leading=16, bold=True)
    bullet_list(c, [
        "The requested action exists, passes executable checks and respects direction policy.",
        "The board responds after deployment, and acceptance can be repeated from CLI or agent chat.",
    ], 238, 168, PAGE_W - 298, size=9.4, leading=13, gap=5, bullet_color=GREEN)
    next_page(c, 3)

    # 04 - Architecture
    page_header(c, "Architecture", "Reasoning stays private; device authority stays local", "The host orchestrates; AMD Radeon inference supplies the model; rdk-sophon owns the final board-side action boundary.")
    image_fit(c, ASSETS / "architecture.png", 42, 268, PAGE_W - 84, 430, mode="contain")
    cols = [(42, "HOST", "Pi SDK/TUI coordinates scoped agents, Skills, tools and evidence."), (218, "AMD RADEON", "An OpenAI-compatible vLLM endpoint provides private model inference."), (394, "RDK X5", "probe-daemon exposes telemetry and allowlisted plugins over local RPC.")]
    for x, title, body in cols:
        c.setFont("Helvetica-Bold", 8.2)
        c.setFillColor(BLUE)
        c.drawString(x, 225, title)
        paragraph(c, body, x, 207, 145, size=9.1, leading=12.5)
    card(c, 42, 82, PAGE_W - 84, 74, fill=PALE_BLUE)
    paragraph(c, "Trust boundary", 58, 138, 110, size=10, leading=13, bold=True, color=BLUE)
    paragraph(c, "No prompt can directly bypass action-package validation, executable evidence gates or the daemon's plugin boundary.", 174, 138, PAGE_W - 232, size=9.5, leading=13)
    next_page(c, 4)

    # 05 - Workflow
    page_header(c, "Agent workflow", "Five nodes turn a request into a verified board action", "The implementation uses one Action Package TDD loop (maximum three iterations), then release, Skill installation and two acceptance checks.")
    image_fit(c, ASSETS / "workflow.png", 42, 235, PAGE_W - 84, 460, mode="contain")
    steps = ["1  Test", "2  Coding", "3  Verification", "4  Board release", "5  Skill + acceptance"]
    x = 42
    widths = [79, 91, 102, 104, 130]
    for i, step in enumerate(steps):
        w = widths[i]
        c.setFillColor(BLUE if i in (0, 3, 4) else INK)
        c.roundRect(x, 152, w, 27, 4, fill=1, stroke=0)
        c.setFillColor(white)
        c.setFont("Helvetica-Bold", 7.8)
        c.drawCentredString(x + w / 2, 161, step)
        x += w + 7
    paragraph(c, "Guardrails remain active at every transition: scoped tools, scoped writes, read-only sandboxing, direction policy and executable evidence.", 42, 125, PAGE_W - 84, size=10.2, leading=14, color=MUTED)
    next_page(c, 5)

    # 06 - Capabilities
    page_header(c, "Core capabilities", "Three Track 2 capabilities, backed by evidence", "The capability claims below are backed by repository implementation, tests and board-side evidence.")
    capabilities = [
        ("01", "Tool calling", "Agents use allowlisted tools and Skills to inspect code, run checks, package actions, deploy and query the board."),
        ("02", "Multi-step planning", "A five-node graph coordinates TDD, release, installation and acceptance with bounded retry behavior."),
        ("03", "Agent/tool permissions", "Role scopes, write-path scopes, offline read-only sandboxes and the device daemon constrain authority. Transport authentication and routine per-action approval remain roadmap items."),
    ]
    y = 590
    for num, title, body in capabilities:
        c.setFillColor(PALE_BLUE)
        c.circle(72, y + 8, 25, fill=1, stroke=0)
        c.setFillColor(BLUE)
        c.setFont("Helvetica-Bold", 13)
        c.drawCentredString(72, y + 3, num)
        c.setFillColor(INK)
        c.setFont("Helvetica-Bold", 14)
        c.drawString(112, y + 15, title)
        paragraph(c, body, 112, y - 8, PAGE_W - 160, size=10.2, leading=14.5)
        y -= 132
    card(c, 42, 128, PAGE_W - 84, 100, fill=INK)
    paragraph(c, "Honest boundary", 60, 205, 130, size=11, leading=14, bold=True, color=CYAN)
    paragraph(c, "The current system has in-process conversation context, but not a persistent local memory store. We do not claim RAG or persistent multi-turn memory in this submission.", 190, 205, PAGE_W - 250, size=9.8, leading=14, color=white)
    next_page(c, 6)

    # 07 - Safety
    page_header(c, "Safety model", "The control plane is stronger than the prompt", "RDK Agent assumes models can be wrong; permissions, policy and evidence are enforced by software below the model layer.")
    layers = [
        ("SCOPE", "Agent-specific tool, Skill and write-path allowlists", BLUE),
        ("SANDBOX", "Offline, read-only Podman execution for untrusted verification", INK),
        ("DIRECTION", "ACTION-DIRECTION-001 blocks commands that violate action direction", CORAL),
        ("EVIDENCE", "Executable checks must pass before a package can progress", GREEN),
        ("DEVICE", "probe-daemon exposes only registered board plugins and actions", CYAN),
    ]
    y = 604
    for tag, body, color in layers:
        c.setFillColor(color)
        c.rect(42, y, 94, 52, fill=1, stroke=0)
        c.setFillColor(white if color != CYAN else INK)
        c.setFont("Helvetica-Bold", 8.5)
        c.drawCentredString(89, y + 21, tag)
        c.setFillColor(LIGHT)
        c.rect(136, y, PAGE_W - 178, 52, fill=1, stroke=0)
        paragraph(c, body, 154, y + 36, PAGE_W - 214, size=10.2, leading=14, bold=True)
        y -= 72
    card(c, 42, 112, PAGE_W - 84, 92, fill=PALE_BLUE)
    paragraph(c, "Result", 60, 180, 80, size=11, leading=14, bold=True, color=BLUE)
    paragraph(c, "The model can propose. It cannot silently expand its own authority, bypass evidence, or directly mutate the board outside the daemon contract.", 140, 180, PAGE_W - 200, size=10, leading=14)
    next_page(c, 7)

    # 08 - AMD inference
    page_header(c, "AMD Radeon + ROCm", "Two Qwen3 model paths ran on Radeon", "The 80B model completed a single-GPU serving run; the trained 32B SFT model also completed the live five-node RDK Agent workflow.")
    card(c, 42, 520, PAGE_W - 84, 165, fill=INK)
    label(c, "BOTH MODELS RUN", 60, 642, fill=GREEN)
    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 17)
    c.drawString(60, 605, "Qwen3-Next-80B-A3B-Instruct")
    paragraph(c, "80B: single-Radeon llama.cpp serving + API canaries  |  32B SFT: five-node live Agent run, 5/5 in 4 min 04 s", 60, 580, PAGE_W - 120, size=9.4, leading=13, color=HexColor("#D5DBE5"))
    flow_y = 433
    boxes = [(42, 126, "RDK Agent"), (197, 166, "OpenAI-compatible API"), (392, 161, "vLLM + ROCm GPU")]
    for x, w, text_value in boxes:
        c.setFillColor(PALE_BLUE if x != 392 else HexColor("#DFF7F0"))
        c.roundRect(x, flow_y, w, 62, 7, fill=1, stroke=0)
        c.setFillColor(INK)
        c.setFont("Helvetica-Bold", 10)
        c.drawCentredString(x + w / 2, flow_y + 26, text_value)
    c.setStrokeColor(BLUE)
    c.setLineWidth(2)
    c.line(169, flow_y + 31, 190, flow_y + 31)
    c.line(364, flow_y + 31, 385, flow_y + 31)
    c.setFillColor(BLUE)
    c.circle(190, flow_y + 31, 2.2, fill=1, stroke=0)
    c.circle(385, flow_y + 31, 2.2, fill=1, stroke=0)
    paragraph(c, "Implemented inference reductions", 42, 365, 250, size=13, leading=17, bold=True)
    bullet_list(c, [
        "Role-specific prompts and scoped context reduce irrelevant tokens.",
        "Action packages and structured handoffs reduce free-form retry loops.",
        "Bounded TDD iterations cap runaway agent work.",
    ], 42, 337, 245, size=9.6, leading=13.5, gap=7)
    paragraph(c, "Archived model evidence", 309, 365, 244, size=13, leading=17, bold=True)
    bullet_list(c, [
        "Both paths identify the gfx1100 Radeon GPU and model weights.",
        "Baseline-versus-optimized metrics are archived for both paths.",
        "Only the separate private vLLM server provenance remains unarchived.",
    ], 309, 337, 244, size=9.6, leading=13.5, gap=7, bullet_color=GREEN)
    next_page(c, 8)

    # 09 - Optimization plan
    page_header(c, "Measured performance", "Two Radeon paths, two clearly scoped evidence sets", "The repository archives measured baseline-versus-optimized results for the 32B SFT and 80B serving paths without conflating their runtimes.")
    metrics = [
        ("TTFT", "Time to first token", "Measures interactive responsiveness"),
        ("TOTAL", "End-to-end latency", "Measures user-perceived task delay"),
        ("TOK/S", "Output throughput", "Measures serving efficiency"),
    ]
    x = 42
    for tag, title, desc in metrics:
        card(c, x, 500, 159, 150, fill=LIGHT)
        c.setFont("Helvetica-Bold", 24)
        c.setFillColor(BLUE)
        c.drawString(x + 18, 602, tag)
        paragraph(c, title, x + 18, 566, 123, size=10.5, leading=14, bold=True)
        paragraph(c, desc, x + 18, 526, 123, size=8.7, leading=12, color=MUTED)
        x += 176
    c.setFont("Helvetica-Bold", 13)
    c.setFillColor(INK)
    c.drawString(42, 440, "Benchmark sequence")
    rows = [
        ("01", "32B SFT", "88 trials per arm; TTFT p50 improved from 17.41 s to 8.26 s."),
        ("02", "80B", "Single Radeon; decode improved from 37.19 to 49.82 tok/s."),
        ("03", "Agent", "The 32B SFT model completed all five live workflow nodes in 4 min 04 s."),
        ("04", "Audit", "Raw or aggregate records, hashes and verification scripts remain in the repository."),
    ]
    y = 396
    for num, title, body in rows:
        c.setFillColor(BLUE)
        c.setFont("Helvetica-Bold", 9)
        c.drawString(42, y, num)
        c.setFillColor(INK)
        c.setFont("Helvetica-Bold", 10.5)
        c.drawString(76, y, title)
        paragraph(c, body, 146, y + 3, PAGE_W - 188, size=9.3, leading=12.5)
        y -= 58
    card(c, 42, 105, PAGE_W - 84, 65, fill=HexColor("#FFF1EF"))
    paragraph(c, "Evidence boundary: the private vLLM endpoint is verified only at the client-routing level; the 80B numbers above come from the separately archived llama.cpp run.", 58, 148, PAGE_W - 116, size=9.6, leading=13.5, bold=True, color=CORAL)
    next_page(c, 9)

    # 10 - Evidence
    page_header(c, "Verified evidence", "196 tests pass, and a live RDK X5 answers", "Evidence below was captured on 2026-08-05. Sensitive identifiers were intentionally removed.")
    image_fit(c, ASSETS / "test-evidence.png", 42, 415, PAGE_W - 84, 260, mode="contain")
    image_fit(c, ASSETS / "board-evidence.png", 42, 120, PAGE_W - 84, 260, mode="contain")
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 7.5)
    c.drawString(42, 94, "TypeScript: 134/134 | Rust: 62/62 | clippy -D warnings: pass | release build: pass")
    c.drawRightString(PAGE_W - 42, 94, "Read-only board checks: ping, state, plugins list")
    next_page(c, 10)

    # 11 - Reproducibility
    page_header(c, "Reproducibility", "The demo can be repeated from source to board", "The source repository includes environment setup, startup commands, dependency notes and a sanitized AMD model configuration example.")
    columns = [
        (42, "HOST", ["Node.js 22+", "npm install", "npm run check", "npm test", "npm run build"]),
        (218, "BOARD", ["Rust toolchain", "cargo test --workspace", "cargo clippy --workspace -- -D warnings", "cargo build --release --workspace"]),
        (394, "DEMO", ["Start probe-daemon", "Run rdk-agent", "Issue natural-language task", "Show action evidence", "Verify board result"]),
    ]
    for x, title, items in columns:
        c.setFillColor(INK)
        c.rect(x, 594, 145, 42, fill=1, stroke=0)
        c.setFillColor(white)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(x + 14, 609, title)
        card(c, x, 326, 145, 252, fill=LIGHT)
        y = 549
        for idx, item in enumerate(items, start=1):
            c.setFillColor(BLUE)
            c.setFont("Helvetica-Bold", 8)
            c.drawString(x + 14, y, f"{idx:02d}")
            paragraph(c, item, x + 39, y + 3, 94, size=8.6, leading=12)
            y -= 47
    card(c, 42, 146, PAGE_W - 84, 130, fill=PALE_BLUE)
    paragraph(c, "Demo evidence to show on screen", 60, 250, 210, size=12.5, leading=16, bold=True, color=BLUE)
    bullet_list(c, [
        "Natural-language request in the TUI, then visible graph progress.",
        "Tests and action-package validation before deployment.",
        "Board ping/state/plugin acceptance after deployment.",
        "AMD Radeon / ROCm server evidence with secrets redacted.",
    ], 60, 218, PAGE_W - 120, size=9.4, leading=13, gap=5)
    next_page(c, 11)

    # 12 - Close/checklist
    page_header(c, "Submission readiness", "The package is assembled and evidence-backed", "Team identity, public demo links, both Qwen3 model runs and measured Radeon results are now recorded.")
    checklist = [
        ("DONE", "Project specification, architecture and workflow", GREEN),
        ("DONE", "Source README, dependencies and reproducibility guide", GREEN),
        ("DONE", "PPT pitch deck and original visual assets", GREEN),
        ("DONE", "196-test and live-board evidence", GREEN),
        ("DONE", "Team: d-robotics agent", GREEN),
        ("DONE", "Public demo links: Bilibili primary + Baidu Cloud backup", GREEN),
        ("DONE", "32B SFT and 80B Radeon run evidence", GREEN),
    ]
    y = 636
    for status, item, color in checklist:
        label(c, status, 42, y - 5, fill=color, width=48)
        paragraph(c, item, 108, y + 8, PAGE_W - 150, size=10.4, leading=14, bold=True)
        c.setStrokeColor(RULE)
        c.line(42, y - 22, PAGE_W - 42, y - 22)
        y -= 54
    card(c, 42, 170, PAGE_W - 84, 86, fill=INK)
    paragraph(c, "Demo video", 60, 231, 120, size=10, leading=13, bold=True, color=CYAN)
    paragraph(
        c,
        f'<a href="{BILIBILI_URL}" color="#FFFFFF"><b>Bilibili: BV1t3up6iEhy</b></a><br/><a href="{BAIDU_URL}" color="#55D5E5">Backup: Baidu Cloud direct MP4</a>',
        60,
        207,
        PAGE_W - 120,
        size=12.5,
        leading=18,
        color=white,
    )
    paragraph(c, "Primary references", 42, 126, 160, size=10.5, leading=14, bold=True)
    paragraph(
        c,
        "Official repository: github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07<br/>Event page: luma.com/amd-4dhi<br/>Project evidence: submission/en/evidence/verification-2026-08-05.md",
        42,
        107,
        PAGE_W - 84,
        size=8.2,
        leading=11.5,
        color=MUTED,
    )
    footer(c, 12)
    c.save()
    print(OUTPUT)


if __name__ == "__main__":
    build()
