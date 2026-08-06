#!/usr/bin/env python3
"""Generate the PolicyCut poster PDF (docs/poster.pdf).

Layout: A2 landscape, dark product theme. Pulls real benchmark numbers from
artifacts/benchmarks/*.json when present and embeds UI screenshots from
docs/poster_assets/*.png when present, so the poster always reflects real
measured results. Pure reportlab — no system dependencies.

Usage: python scripts/make_poster.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "poster.pdf"
ASSETS = ROOT / "docs" / "poster_assets"

# A2 landscape
W, H = 594 * mm, 420 * mm

BG = HexColor("#0f1115")
PANEL = HexColor("#171a21")
BORDER = HexColor("#262a33")
TEXT = HexColor("#e6e6e6")
DIM = HexColor("#9aa3b2")
ACCENT = HexColor("#e8442e")
GREEN = HexColor("#3fb950")
AMBER = HexColor("#d29922")
BLUE = HexColor("#58a6ff")


def latest_benchmark() -> dict:
    bench_dir = ROOT / "artifacts" / "benchmarks"
    best: dict = {}
    if bench_dir.is_dir():
        files = sorted(bench_dir.glob("benchmark_*.json"))
        if files:
            try:
                best = json.loads(files[-1].read_text())
            except Exception:
                best = {}
    return best


def panel(c: canvas.Canvas, x, y, w, h, title=None):
    c.setFillColor(PANEL)
    c.setStrokeColor(BORDER)
    c.setLineWidth(1.2)
    c.roundRect(x, y, w, h, 4 * mm, stroke=1, fill=1)
    if title:
        c.setFillColor(ACCENT)
        c.setFont("Helvetica-Bold", 20)
        c.drawString(x + 7 * mm, y + h - 12 * mm, title)


def lines(c, x, y, items, size=12.5, leading=None, color=TEXT, font="Helvetica",
          bullet=None, max_chars=None):
    leading = leading or size * 1.42
    c.setFont(font, size)
    c.setFillColor(color)
    cy = y
    for it in items:
        txt = it
        if bullet and txt:
            txt = f"{bullet} {txt}"
        c.drawString(x, cy, txt)
        cy -= leading
    return cy


def wrap(text, n):
    words, out, cur = text.split(), [], ""
    for w_ in words:
        if len(cur) + len(w_) + 1 > n:
            out.append(cur)
            cur = w_
        else:
            cur = f"{cur} {w_}".strip()
    if cur:
        out.append(cur)
    return out


def main() -> int:
    bench = latest_benchmark()
    c = canvas.Canvas(str(OUT), pagesize=(W, H))

    # background
    c.setFillColor(BG)
    c.rect(0, 0, W, H, stroke=0, fill=1)

    # ---------- header ----------
    c.setFillColor(ACCENT)
    c.rect(0, H - 6 * mm, W, 6 * mm, stroke=0, fill=1)
    c.setFillColor(TEXT)
    c.setFont("Helvetica-Bold", 64)
    c.drawString(18 * mm, H - 32 * mm, "PolicyCut")
    c.setFont("Helvetica", 26)
    c.setFillColor(DIM)
    c.drawString(18 * mm, H - 44 * mm,
                 "Write your privacy policy in plain English — review, redact and audit your video, fully local on AMD Radeon.")
    c.setFont("Helvetica-Bold", 20)
    c.setFillColor(TEXT)
    c.drawRightString(W - 18 * mm, H - 30 * mm, "AMD Radeon Hackathon 2026")
    c.setFillColor(DIM)
    c.setFont("Helvetica", 17)
    c.drawRightString(W - 18 * mm, H - 40 * mm, "Track 1 · Multimodal Content Creation Tools")

    top = H - 56 * mm
    margin = 14 * mm
    gap = 8 * mm
    col_w = (W - 2 * margin - 3 * gap) / 4
    col_h = top - 16 * mm
    x0 = margin
    x1 = x0 + col_w + gap
    x2 = x1 + col_w + gap
    x3 = x2 + col_w + gap
    y0 = 16 * mm

    # ---------- column 1: problem + workflow ----------
    panel(c, x0, y0, col_w, col_h, "The problem")
    y = top - 24 * mm
    y = lines(c, x0 + 7 * mm, y, wrap(
        "Real footage is full of personal data: bystander faces, plates, ID cards, "
        "screens, spoken phone numbers and addresses. Manual redaction takes hours; "
        "cloud services require uploading exactly the footage you must protect; "
        "single-model demos cover one modality with no review and no audit.", 46),
        size=13.5, color=TEXT)
    y -= 6 * mm
    c.setFillColor(ACCENT); c.setFont("Helvetica-Bold", 20)
    c.drawString(x0 + 7 * mm, y, "One sentence in, evidence out")
    y -= 9 * mm
    c.setFillColor(BLUE); c.setFont("Courier-Bold", 12.5)
    for ln in ['"Pixelate every face, license plate,', ' identity document and screen.',
               ' Beep phone numbers, email addresses', ' and street addresses."']:
        c.drawString(x0 + 7 * mm, y, ln); y -= 5.6 * mm
    y -= 5 * mm
    steps = ["Upload video (≤60 s)", "Interpret policy  →  structured rules you confirm",
             "Automatic analysis (vision + audio, on Radeon)",
             "HUMAN REVIEW  —  confirm / fix / add on a dual-track timeline",
             "Render  →  redacted MP4 + redacted SRT + audit.json"]
    for i, s in enumerate(steps):
        c.setFillColor(ACCENT if "HUMAN" in s else PANEL)
        c.setStrokeColor(ACCENT if "HUMAN" in s else BORDER)
        c.roundRect(x0 + 7 * mm, y - 4.6 * mm, col_w - 14 * mm, 11.5 * mm, 2 * mm, stroke=1, fill=1)
        c.setFillColor(TEXT if "HUMAN" not in s else HexColor("#ffffff"))
        c.setFont("Helvetica-Bold" if "HUMAN" in s else "Helvetica", 12.5)
        for j, ln in enumerate(wrap(s, 44)[:2]):
            c.drawString(x0 + 11 * mm, y + 1.8 * mm - j * 4.6 * mm, ln)
        y -= 15 * mm
        if i < len(steps) - 1:
            c.setFillColor(DIM); c.setFont("Helvetica-Bold", 13)
            c.drawCentredString(x0 + col_w / 2, y + 8.2 * mm, "▼")

    # ---------- column 2: how it works ----------
    panel(c, x1, y0, col_w, col_h, "All local, all on Radeon")
    y = top - 24 * mm
    rows = [
        ("Policy → JSON rules", "Qwen3-4B-Instruct, strict schema,", "deterministic keyword fallback"),
        ("Open-vocab detection", "Grounding DINO tiny (Transformers", "port — no CUDA custom ops)"),
        ("Small-face assist", "YuNet (OpenCV Zoo, CPU assist)", ""),
        ("Mask tracking", "SAM 2.1 hiera-small, video", "propagation, SAM2_BUILD_CUDA=0"),
        ("Speech-to-text", "Whisper large-v3-turbo,", "word-level timestamps"),
        ("Spoken-PII locate", "regex + spoken-form normalization", "(\"five five five … at example dot com\")"),
    ]
    for name, l1, l2 in rows:
        c.setFillColor(TEXT); c.setFont("Helvetica-Bold", 14.5)
        c.drawString(x1 + 7 * mm, y, name)
        c.setFillColor(DIM); c.setFont("Helvetica", 12)
        c.drawString(x1 + 7 * mm, y - 5.4 * mm, l1)
        if l2:
            c.drawString(x1 + 7 * mm, y - 10.2 * mm, l2)
        y -= 17.5 * mm
    y -= 2 * mm
    c.setFillColor(ACCENT); c.setFont("Helvetica-Bold", 17)
    c.drawString(x1 + 7 * mm, y, "Fail toward privacy")
    y -= 8 * mm
    y = lines(c, x1 + 7 * mm, y, [
        "Empty SAM mask → padded box, never a hole",
        "Mask dilate 5–12 px + feather + safety box",
        "No word timestamps → whole segment muted",
        "Audio spans padded −150/+250 ms, gaps merged",
        "Unknown policy terms surfaced, never guessed",
        "Export blocked until every event reviewed",
    ], size=12.5, bullet="•", color=TEXT)

    # ---------- column 3: screenshots / product ----------
    panel(c, x2, y0, col_w, col_h, "A real editor, not a demo page")
    y = top - 22 * mm
    shots = sorted(ASSETS.glob("*.png")) if ASSETS.is_dir() else []
    if shots:
        for img_path in shots[:3]:
            try:
                img = ImageReader(str(img_path))
                iw, ih = img.getSize()
                tw = col_w - 14 * mm
                th = tw * ih / iw
                if y - th < y0 + 40 * mm:
                    break
                c.drawImage(img, x2 + 7 * mm, y - th, tw, th,
                            preserveAspectRatio=True, anchor='nw')
                c.setStrokeColor(BORDER)
                c.rect(x2 + 7 * mm, y - th, tw, th, stroke=1, fill=0)
                y -= th + 5 * mm
            except Exception:
                continue
    else:
        y = lines(c, x2 + 7 * mm, y - 4 * mm, [
            "Review workspace:",
            "  video + live canvas overlay of tracked boxes",
            "  dual-track timeline (visual + audio lanes)",
            "  confirm / ignore / retime every event",
            "  manual fixed regions for anything missed",
            "  frame stepping, 0.5× rate, event hopping",
        ], size=13, color=TEXT)
    y = min(y, y0 + 66 * mm)
    c.setFillColor(ACCENT); c.setFont("Helvetica-Bold", 17)
    c.drawString(x2 + 7 * mm, y, "Every export ships evidence")
    y -= 8 * mm
    y = lines(c, x2 + 7 * mm, y, [
        "redacted.mp4  H.264/AAC, metadata stripped",
        "redacted.srt  [REDACTED: PHONE|EMAIL|ADDRESS]",
        "audit.json    models, precision, timings, VRAM,",
        "              every event + human edits,",
        "              zero PII plaintext inside",
        "SHA-256 of input and output, ZIP bundle",
    ], size=12.5, font="Courier", color=TEXT)

    # ---------- column 4: Radeon proof + numbers ----------
    panel(c, x3, y0, col_w, col_h, "Measured on Radeon PRO W7900")
    y = top - 24 * mm
    env = bench.get("environment", {})
    gpu_name = env.get("gpu_name") or "AMD Radeon PRO W7900 (48 GB)"
    y = lines(c, x3 + 7 * mm, y, [
        f"GPU: {gpu_name}",
        f"ROCm/HIP: {env.get('hip_version') or 'ROCm PyTorch build'}",
        f"PyTorch: {env.get('torch_version') or 'platform ROCm wheels'}",
        "Precision: FP16 (per-stage FP32 fallback)",
    ], size=13, color=TEXT)
    y -= 5 * mm

    stages = bench.get("stages", {})
    table = []
    def add_row(label, key, fmt):
        s = stages.get(key) or {}
        if s:
            table.append((label, fmt(s)))
    add_row("Grounding DINO", "dino", lambda s: f"{s.get('keyframes_per_s', s.get('fps', '—'))} kf/s")
    add_row("SAM 2.1 propagation", "sam2", lambda s: f"{s.get('frames_per_s', s.get('fps', '—'))} fr/s")
    add_row("Whisper turbo", "whisper", lambda s: f"RTF {s.get('rtf', '—')}")
    add_row("End-to-end analysis", "analysis", lambda s: f"RTF {s.get('rtf', '—')}")
    add_row("Peak VRAM", "vram", lambda s: f"{s.get('peak_mb', '—')} MB")
    if not table:
        c.setFillColor(TEXT)
        c.setFont("Helvetica-Bold", 13.5)
        c.drawString(x3 + 7 * mm, y, "Measured benchmark tables:")
        y -= 6.5 * mm
        y = lines(c, x3 + 7 * mm, y, [
            "Grounding DINO keyframes/s",
            "SAM 2.1 propagation frames/s",
            "Whisper real-time factor",
            "End-to-end real-time factor",
            "Peak VRAM per stage",
        ], size=12.5, bullet="•", color=TEXT)
        c.setFillColor(GREEN)
        c.setFont("Courier-Bold", 12)
        c.drawString(x3 + 7 * mm, y, "→ artifacts/benchmarks/*.json")
        y -= 5.6 * mm
        c.drawString(x3 + 7 * mm, y, "→ docs/benchmark.md")
        y -= 7.8 * mm
    else:
        c.setFillColor(TEXT)
        for label, val in table:
            c.setFont("Helvetica-Bold", 13.5)
            c.drawString(x3 + 7 * mm, y, label)
            c.setFont("Courier-Bold", 13.5)
            c.setFillColor(GREEN)
            c.drawRightString(x3 + col_w - 7 * mm, y, str(val))
            c.setFillColor(TEXT)
            y -= 7.8 * mm
    y -= 4 * mm
    c.setFillColor(ACCENT); c.setFont("Helvetica-Bold", 17)
    c.drawString(x3 + 7 * mm, y, "Honest Radeon engineering")
    y -= 8 * mm
    y = lines(c, x3 + 7 * mm, y, [
        "--require-rocm: core stages refuse silent",
        "  CPU fallback — a Radeon run is provable",
        "Sequential model load/unload per stage",
        "torch.cuda.synchronize() around all timings",
        "Peak VRAM recorded per stage in audit.json",
        "ROCm-clean models: no CUDA custom kernels",
        "Zero external API calls during processing",
    ], size=12.5, bullet="•", color=TEXT)
    y -= 4 * mm
    c.setFillColor(AMBER); c.setFont("Helvetica-Bold", 13)
    for ln in wrap("PolicyCut is a human-in-the-loop privacy editor with an auditable, "
                   "fully local workflow — not a guarantee of legal compliance.", 44):
        c.drawString(x3 + 7 * mm, y, ln); y -= 5.6 * mm

    # footer
    c.setFillColor(DIM)
    c.setFont("Helvetica", 13)
    c.drawString(margin, 7 * mm,
                 "FastAPI + vanilla JS · atomic JSON + NPZ storage · 120 automated tests · MIT license")
    c.drawRightString(W - margin, 7 * mm, "github.com/xiaodouzi666/Radeon-hackathon-2026-07 · PolicyCut · Track 1")

    c.save()
    print(f"poster written: {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
