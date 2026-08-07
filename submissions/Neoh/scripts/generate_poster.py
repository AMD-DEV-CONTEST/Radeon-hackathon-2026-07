"""Generate the Radeon-Assistant single-page poster (poster.png).

Usage:
    cd submissions/Neoh
    python scripts/generate_poster.py

Output:
    docs/poster.png
"""

from pathlib import Path

# All generated artifacts live in ../docs relative to this script (scripts/).
DOCS = Path(__file__).resolve().parent.parent / "docs"

from PIL import Image, ImageDraw, ImageFont

FONT_DIR = "/usr/share/fonts/truetype/dejavu"
REG = ImageFont.truetype(f"{FONT_DIR}/DejaVuSans.ttf", 22)
BOLD = ImageFont.truetype(f"{FONT_DIR}/DejaVuSans-Bold.ttf", 22)
TITLE = ImageFont.truetype(f"{FONT_DIR}/DejaVuSans-Bold.ttf", 64)
SUB = ImageFont.truetype(f"{FONT_DIR}/DejaVuSans-Bold.ttf", 30)
H2 = ImageFont.truetype(f"{FONT_DIR}/DejaVuSans-Bold.ttf", 30)
SMALL = ImageFont.truetype(f"{FONT_DIR}/DejaVuSans.ttf", 18)
SMALL_B = ImageFont.truetype(f"{FONT_DIR}/DejaVuSans-Bold.ttf", 18)

# Palette
INK = (35, 40, 47)        # near-black text
BODY = (60, 60, 60)
NAVY = (27, 38, 49)       # header / block bg
AMBER = (224, 58, 62)     # AMD-ish red accent
PANEL = (244, 246, 248)   # light panel
WHITE = (255, 255, 255)
LINE = (210, 214, 218)

W, H = 1400, 2260
MARGIN = 60


def text_w(draw, s, font):
    return draw.textlength(s, font=font)


def wrap(draw, text, font, max_w):
    words = text.split()
    lines, cur = [], ""
    for wd in words:
        trial = (cur + " " + wd).strip()
        if text_w(draw, trial, font) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = wd
    if cur:
        lines.append(cur)
    return lines


def draw_block_title(draw, y, title):
    draw.rectangle([MARGIN, y, MARGIN + 10, y + 36], fill=AMBER)
    draw.text((MARGIN + 22, y + 1), title, font=H2, fill=INK)
    return y + 50


def body_para(draw, y, text, font=REG, color=BODY, lh=30, max_w=W - 2 * MARGIN):
    for ln in wrap(draw, text, font, max_w):
        draw.text((MARGIN, y), ln, font=font, fill=color)
        y += lh
    return y + 6


def bullet(draw, y, text, font=REG, color=BODY, lh=27):
    x0 = MARGIN + 6
    draw.ellipse([x0, y + 7, x0 + 8, y + 15], fill=AMBER)
    bx = MARGIN + 24
    lines = wrap(draw, text, font, W - 2 * MARGIN - 30)
    for i, ln in enumerate(lines):
        draw.text((bx, y), ln, font=font, fill=color)
        y += lh
    return y + 4


def main():
    img = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(img)

    # ---------------- Header ----------------
    d.rectangle([0, 0, W, 188], fill=NAVY)
    d.text((MARGIN, 34), "Radeon-Assistant", font=TITLE, fill=WHITE)
    d.text((MARGIN, 108), "A Privacy-First Local AI Agent on AMD Radeon GPU",
            font=SUB, fill=(233, 236, 239))
    d.text((MARGIN, 148),
           "AMD Radeon Hackathon 2026-07  ·  Track 2 — Private AI Agent Dev & Local Deployment  ·  Team: Neoh",
           font=SMALL, fill=(180, 188, 196))
    y = 188 + 28

    # ---------------- 1. Application Scenario ----------------
    y = draw_block_title(d, y, "Application Scenario")
    y = body_para(d, y,
        "All LLM inference, embedding, and vector search run locally on an AMD Radeon GPU via vLLM + ROCm. "
        "No external API is called during inference, making the system ideal for data-privacy, offline, and "
        "on-premise AI-assistant use cases.")
    # scenario chips
    chips = ["Local RAG Q&A", "Office Automation", "Multi-Step Planning",
             "Hardware R&D", "Privacy-First"]
    cx = MARGIN
    cy = y + 4
    for c in chips:
        cw = int(text_w(d, c, SMALL_B)) + 28
        d.rounded_rectangle([cx, cy, cx + cw, cy + 34], radius=8, fill=PANEL, outline=LINE)
        d.text((cx + 14, cy + 7), c, font=SMALL_B, fill=INK)
        cx += cw + 14
    y = cy + 34 + 26

    # ---------------- 2. Core Capabilities ----------------
    y = draw_block_title(d, y, "Core Capabilities")
    caps = [
        ("Local RAG Knowledge Base", "FAISS + all-MiniLM-L6-v2; PDF / DOCX / MD / TXT with table extraction."),
        ("Tool Calling", "14 built-in tools across file / shell / code / system / hardware categories."),
        ("Multi-Step Planning", "Planner → Executor → Reflector loop with self-reflection and retry."),
        ("Local Multi-Turn Memory", "Short-term buffer (20 msgs) + long-term FAISS vector retrieval."),
        ("Permission & Privacy", "Human-in-the-loop approval gate + JSON-Lines audit logging."),
    ]
    col_w = (W - 2 * MARGIN - 30) // 2
    x_left, x_right = MARGIN, MARGIN + col_w + 30
    cols = [x_left, x_right]
    # Place 5 capabilities as two sequential columns: left = items 1-3, right = 4-5.
    def draw_caps_col(items, cx):
        cy = y
        for t, desc in items:
            d.text((cx, cy), t, font=BOLD, fill=INK)
            cy += 30
            for ln in wrap(d, desc, REG, col_w - 10):
                d.text((cx, cy), ln, font=REG, fill=BODY)
                cy += 27
            cy += 14
        return cy
    h_l = draw_caps_col(caps[:3], cols[0])
    h_r = draw_caps_col(caps[3:], cols[1])
    y = max(h_l, h_r) + 18

    # ---------------- 3. Architecture ----------------
    y = draw_block_title(d, y, "System Architecture")
    arch = DOCS / "architecture.png"
    if arch.exists():
        a = Image.open(arch).convert("RGB")
        max_w = W - 2 * MARGIN
        scale = max_w / a.width
        aw, ah = max_w, int(a.height * scale)
        a = a.resize((aw, ah))
        # panel behind
        d.rectangle([MARGIN - 8, y - 8, MARGIN + aw + 8, y + ah + 8], fill=PANEL, outline=LINE)
        img.paste(a, (MARGIN, y))
        y += ah + 8
    else:
        y = body_para(d, y, "[architecture.png not found at generation time]")
    y = body_para(d, y,
        "Layered design: UI → Agent → Safety → Tools → Memory → Inference → AMD Radeon GPU.",
        font=SMALL, color=BODY)

    # ---------------- 4. AMD ROCm Optimization ----------------
    y = draw_block_title(d, y, "AMD ROCm Inference Optimization")
    y = body_para(d, y,
        "Optimized for AMD Radeon (ROCm 7.14, gfx1100). vLLM PagedAttention + continuous batching, "
        "ROCm graph capture, and configurable single-GPU tensor parallelism.", font=SMALL)
    # perf table
    rows = [
        ("Radeon Pro W7900", "Qwen2.5-14B FP16", "27.5 tok/s", "~30 GB"),
        ("Radeon Pro W7900", "Qwen2.5-7B FP16", "46 tok/s", "~15 GB"),
    ]
    tbl_x = MARGIN
    tbl_w = W - 2 * MARGIN
    col_x = [tbl_x, tbl_x + int(tbl_w * 0.42), tbl_x + int(tbl_w * 0.66), tbl_x + int(tbl_w * 0.84)]
    row_h = 34
    # header row
    hdr = ["GPU", "Model", "Speed", "VRAM"]
    d.rectangle([tbl_x, y, tbl_x + tbl_w, y + row_h], fill=NAVY)
    for i, htxt in enumerate(hdr):
        d.text((col_x[i] + 8, y + 7), htxt, font=SMALL_B, fill=WHITE)
    y += row_h
    for r in rows:
        d.rectangle([tbl_x, y, tbl_x + tbl_w, y + row_h], outline=LINE, fill=WHITE)
        for i, cell in enumerate(r):
            d.text((col_x[i] + 8, y + 7), cell, font=SMALL, fill=INK)
        y += row_h
    y += 22

    # ---------------- Footer ----------------
    d.rectangle([0, y, W, H], fill=NAVY)
    fy = y + 24
    d.text((MARGIN, fy), "Repository:  github.com/RainmeoX/Radeon-hackathon-2026-07  (submissions/Neoh)",
           font=SMALL_B, fill=WHITE)
    fy += 26
    d.text((MARGIN, fy), "Demo: local Web UI + CLI (no cloud dependency) — demo video included in repository",
           font=SMALL, fill=(200, 206, 212))
    fy += 26
    d.text((MARGIN, fy), "All inference runs locally on AMD Radeon — no external API is called.",
           font=SMALL, fill=(200, 206, 212))

    out = DOCS / "poster.png"
    img.save(out)
    print(f"Saved poster to {out} ({W}x{H})")


if __name__ == "__main__":
    main()
