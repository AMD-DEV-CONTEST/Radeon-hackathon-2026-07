#!/usr/bin/env python3
"""Generate dark-themed diagrams (architecture / pipeline / performance) for the
English PDF, PPT and video deliverables."""
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

OUT = Path(__file__).resolve().parents[1] / "deliverables" / "assets"
OUT.mkdir(parents=True, exist_ok=True)

BG = "#0b0d0a"
PANEL = "#1a1d15"
PANEL2 = "#23271b"
BORDER = "#3a3d2e"
TEXT = "#e8e2cf"
MUTED = "#9a937b"
AMBER = "#ffaa55"
ORANGE = "#ff7733"
GREEN = "#7fbf7f"

plt.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "text.color": TEXT,
        "axes.edgecolor": BORDER,
        "axes.labelcolor": TEXT,
        "xtick.color": MUTED,
        "ytick.color": MUTED,
        "figure.facecolor": BG,
        "axes.facecolor": BG,
    }
)


def panel(ax, x, y, w, h, title, body="", fc=PANEL, ec=BORDER, title_color=AMBER, fs=13, bf=10.5):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.012,rounding_size=0.02",
                                fc=fc, ec=ec, lw=1.2, mutation_aspect=1))
    ax.text(x + w / 2, y + h - 0.065, title, ha="center", va="top", color=title_color,
            fontsize=fs, fontweight="bold")
    if body:
        ax.text(x + w / 2, y + 0.055, body, ha="center", va="bottom", color=TEXT, fontsize=bf)


def arrow(ax, x1, y1, x2, y2, color=AMBER):
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle="-|>", mutation_scale=16,
                                 lw=2.2, color=color, shrinkA=2, shrinkB=2))


# ---------------------------------------------------------------- architecture
fig, ax = plt.subplots(figsize=(11.5, 6.0), dpi=170)
ax.set_xlim(0, 1)
ax.set_ylim(0, 1)
ax.axis("off")

panel(ax, 0.03, 0.66, 0.94, 0.28,
      "BROWSER UI  (web/)",
      "Workflow forms · job list · live preview · asset download · Three.js 3D scene viewer",
      fs=14, bf=10.5)
arrow(ax, 0.5, 0.655, 0.5, 0.545)
ax.text(0.52, 0.60, "HTTP + polling  :8000", color=MUTED, fontsize=9)

panel(ax, 0.18, 0.25, 0.64, 0.28,
      "FASTAPI BACKEND  (server/)",
      "Job queue · SQLite archive (params/seed/outputs) · offline zh→en translator\n"
      "output proxy · /api/scene batch assembler",
      fs=14, bf=10)
panel(ax, 0.03, 0.25, 0.13, 0.28, "SQLite", "jobs.db\nbatch archive", fc=PANEL2, fs=10)
panel(ax, 0.84, 0.25, 0.13, 0.28, "Translator", "MarianMT\nopus-mt-zh-en", fc=PANEL2, fs=10)

arrow(ax, 0.5, 0.24, 0.5, 0.13)
ax.text(0.52, 0.185, "HTTP  /prompt · /history · /view  :8188", color=MUTED, fontsize=9)

panel(ax, 0.18, 0.02, 0.64, 0.10,
      "COMFYUI GPU ENGINE",
      "workflows W1–W7 (API JSON) · custom nodes · SDXL · MiDaS · ControlNet OpenPose · MusicGen · TripoSR",
      fs=13, bf=9.5, title_color=ORANGE)
panel(ax, 0.03, 0.02, 0.13, 0.10, "AMD GPU", "ROCm 7.1\n48 GiB VRAM", fc=PANEL2, fs=10, title_color=GREEN)

fig.tight_layout()
fig.savefig(OUT / "architecture.png", dpi=170)
plt.close(fig)


# ---------------------------------------------------------------- pipeline
fig, ax = plt.subplots(figsize=(12.0, 4.4), dpi=170)
ax.set_xlim(0, 1)
ax.set_ylim(0, 1)
ax.axis("off")
ax.text(0.5, 0.94, "ONE TEXT SETTING  →  A STYLE-CONSISTENT GAME ASSET CHAIN",
        ha="center", va="top", color=TEXT, fontsize=15, fontweight="bold")

steps = [
    ("W1", "Concept art", "SDXL"),
    ("W2", "Depth map", "MiDaS"),
    ("W3", "PBR set", "Gradient"),
    ("W4", "Music", "MusicGen"),
    ("W5", "SFX", "DSP"),
    ("W6", "Sprite atlas", "OpenPose"),
    ("W7", "3D model", "TripoSR"),
]
n = len(steps)
box_w, box_h = 0.112, 0.42
gap = (1.0 - 2 * 0.03 - n * box_w) / (n - 1)
x = 0.03
for i, (wid, name, model) in enumerate(steps):
    y = 0.30
    panel(ax, x, y, box_w, box_h, wid, f"{name}\n{model}", fc=PANEL if i % 2 == 0 else PANEL2,
          title_color=AMBER if i % 2 == 0 else ORANGE, fs=11, bf=8.2)
    if i < n - 1:
        arrow(ax, x + box_w + 0.002, y + box_h / 2, x + box_w + gap - 0.002, y + box_h / 2)
    x += box_w + gap

ax.text(0.5, 0.085, "Anchor: character sheet / concept image conditions every downstream stage (W2–W7)",
        ha="center", va="center", color=MUTED, fontsize=10)
fig.tight_layout()
fig.savefig(OUT / "pipeline.png", dpi=170)
plt.close(fig)


# ---------------------------------------------------------------- performance
bench = json.load(open(Path(__file__).resolve().parents[1] / "deliverables" / "perf" / "benchmark.json"))
jobs = bench["jobs"]
order = ["W1", "W2", "W3", "W4", "W5", "W6"]
labels = ["W1\nConcept art", "W2\nDepth", "W3\nPBR set", "W4\nMusic", "W5\nSFX", "W6\nSprite atlas"]
exec_s = [next(j["execution_seconds"] for j in jobs if j["workflow"] == w) for w in order]
wall_s = [next(j["wall_seconds"] for j in jobs if j["workflow"] == w) for w in order]

fig, ax = plt.subplots(figsize=(10.5, 4.8), dpi=170)
y = range(len(order))
b1 = ax.barh(y, wall_s, height=0.42, color=PANEL2, edgecolor=BORDER, label="End-to-end wall time (s)")
b2 = ax.barh([v + 0.42 for v in y], exec_s, height=0.42, color=AMBER, edgecolor=ORANGE, label="GPU execution time (s)")
ax.set_yticks([v + 0.21 for v in y])
ax.set_yticklabels(labels, fontsize=10)
ax.invert_yaxis()
for bars in (b1, b2):
    for r in bars:
        ax.text(r.get_width() + 0.3, r.get_y() + r.get_height() / 2, f"{r.get_width():.1f}",
                va="center", color=TEXT, fontsize=8.5)
ax.set_xlim(0, 26)
ax.set_xlabel("Seconds", fontsize=10)
ax.set_title("Live W1–W6 run on AMD Radeon (gfx1100, ROCm 7.1, torch 2.11+rocm7.1)",
             color=TEXT, fontsize=12)
ax.legend(loc="lower right", fontsize=9, facecolor=PANEL, edgecolor=BORDER)
ax.spines[["top", "right"]].set_visible(False)
fig.tight_layout()
fig.savefig(OUT / "performance.png", dpi=170)
plt.close(fig)

print("diagrams written to", OUT)
