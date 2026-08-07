"""Generate the Radeon-Assistant architecture diagram (PNG).

Usage:
    cd submissions/Neoh
    python scripts/generate_architecture.py

Output:
    docs/architecture.png
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
from pathlib import Path

# All generated artifacts live in ../docs relative to this script (scripts/).
DOCS = Path(__file__).resolve().parent.parent / "docs"


# ---------------------------------------------------------------------------
# Layout configuration
# ---------------------------------------------------------------------------
FIG_W, FIG_H = 16, 12
LAYER_Y = [10.8, 9.0, 7.2, 5.4, 3.6, 1.8, 0.0]  # top -> bottom
LAYER_NAMES = [
    "1. User Layer",
    "2. Agent Layer",
    "3. Safety Layer",
    "4. Tool Layer",
    "5. Memory Layer",
    "6. Inference Layer",
    "7. Hardware Layer",
]
LAYER_COLORS = [
    "#4A90D9",  # blue
    "#E67E22",  # orange
    "#C0392B",  # red
    "#27AE60",  # green
    "#8E44AD",  # purple
    "#16A085",  # teal
    "#2C3E50",  # dark
]


def draw_box(ax, x, y, w, h, text, color, text_color="white", fontsize=9, bold=False):
    """Draw a rounded rectangle with centered text."""
    box = FancyBboxPatch(
        (x - w / 2, y - h / 2),
        w, h,
        boxstyle="round,pad=0.02,rounding_size=0.15",
        facecolor=color,
        edgecolor="white",
        linewidth=1.5,
        alpha=0.95,
    )
    ax.add_patch(box)
    weight = "bold" if bold else "normal"
    ax.text(
        x, y, text,
        ha="center", va="center",
        color=text_color,
        fontsize=fontsize,
        weight=weight,
        wrap=True,
    )
    return box


def draw_arrow(ax, x1, y1, x2, y2, color="#7F8C8D"):
    """Draw a vertical downward arrow."""
    ax.annotate(
        "",
        xy=(x2, y2), xytext=(x1, y1),
        arrowprops=dict(arrowstyle="->", color=color, lw=1.5),
    )


def main():
    fig, ax = plt.subplots(figsize=(FIG_W, FIG_H))
    ax.set_xlim(0, FIG_W)
    ax.set_ylim(-0.8, FIG_H)
    ax.axis("off")

    # Title
    ax.text(
        FIG_W / 2, 11.7,
        "Radeon-Assistant: Agent Architecture",
        ha="center", va="center",
        fontsize=20, weight="bold", color="#2C3E50"
    )
    ax.text(
        FIG_W / 2, 11.3,
        "Track 2 — Private AI Agent Development & Local Deployment  |  Team Neoh",
        ha="center", va="center",
        fontsize=11, color="#555555"
    )

    # Legend
    legend_items = [
        ("User Interface", "#4A90D9"),
        ("Agent Core", "#E67E22"),
        ("Safety / Privacy", "#C0392B"),
        ("Tools", "#27AE60"),
        ("Memory / RAG", "#8E44AD"),
        ("Inference", "#16A085"),
        ("Hardware", "#2C3E50"),
    ]
    lx, ly = 13.8, 10.6
    ax.text(lx, ly + 0.35, "Legend", fontsize=9, weight="bold", color="#333333")
    for i, (label, color) in enumerate(legend_items):
        yy = ly - i * 0.35
        rect = mpatches.Rectangle((lx - 0.15, yy - 0.1), 0.25, 0.2, facecolor=color, edgecolor="none")
        ax.add_patch(rect)
        ax.text(lx + 0.2, yy, label, fontsize=8, va="center", color="#333333")

    # Layer labels on the left
    for name, y, color in zip(LAYER_NAMES, LAYER_Y, LAYER_COLORS):
        ax.text(
            0.3, y, name,
            ha="left", va="center",
            fontsize=10, weight="bold", color=color,
        )

    # 1. User Layer
    draw_box(ax, 5.0, LAYER_Y[0], 3.2, 0.9, "Streamlit Web UI\n(port 7860)", LAYER_COLORS[0])
    draw_box(ax, 9.6, LAYER_Y[0], 3.2, 0.9, "CLI Mode\n(python app.py --mode cli)", LAYER_COLORS[0])

    # 2. Agent Layer
    draw_box(ax, 4.2, LAYER_Y[1], 2.6, 0.9, "Planner\nTask Decomposition", LAYER_COLORS[1])
    draw_box(ax, 7.8, LAYER_Y[1], 2.6, 0.9, "Executor\nStep Execution", LAYER_COLORS[1])
    draw_box(ax, 11.4, LAYER_Y[1], 2.6, 0.9, "Reflector\nResult Evaluation", LAYER_COLORS[1])

    # 3. Safety Layer
    draw_box(ax, 5.0, LAYER_Y[2], 3.4, 0.9, "Human-in-the-Loop Approval\n(high-risk tools)", LAYER_COLORS[2])
    draw_box(ax, 9.6, LAYER_Y[2], 3.4, 0.9, "Audit Logger\nJSON Lines", LAYER_COLORS[2])

    # 4. Tool Layer
    tool_boxes = [
        (3.1, "File Tools\nread / write / delete\nlist / mkdir"),
        (5.6, "Shell Tools\nexecute_command\nexecute_python"),
        (8.1, "Code Tools\ncode_interpreter\nformat_code"),
        (10.6, "System Tools\nCPU / Mem / Disk\nGPU / Processes"),
        (13.1, "Tool Registry\n14 tools\nauto-registered"),
    ]
    for x, text in tool_boxes:
        draw_box(ax, x, LAYER_Y[3], 2.2, 1.1, text, LAYER_COLORS[3], fontsize=8)

    # 5. Memory Layer
    draw_box(ax, 5.0, LAYER_Y[4], 3.4, 0.9, "Short-term Memory\nlast 20 messages", LAYER_COLORS[4])
    draw_box(ax, 9.6, LAYER_Y[4], 3.4, 0.9, "Long-term RAG\nFAISS + all-MiniLM-L6-v2", LAYER_COLORS[4])

    # 6. Inference Layer
    draw_box(ax, 4.0, LAYER_Y[5], 2.8, 0.9, "vLLM Engine\nROCm backend", LAYER_COLORS[5])
    draw_box(ax, 7.8, LAYER_Y[5], 2.8, 0.9, "Qwen2.5-14B-Instruct\nFP16 safetensors", LAYER_COLORS[5])
    draw_box(ax, 11.6, LAYER_Y[5], 2.8, 0.9, "ROCm 7.14\ngfx1100 override", LAYER_COLORS[5])

    # 7. Hardware Layer
    draw_box(ax, 7.3, LAYER_Y[6], 6.0, 0.9,
             "AMD Radeon GPU\nRadeon Pro W7900 / RX 7900 XT  |  100% local inference", LAYER_COLORS[6], fontsize=10, bold=True)

    # Arrows: top-down flow
    # User -> Agent
    for x in [5.0, 9.6]:
        draw_arrow(ax, x, LAYER_Y[0] - 0.5, 7.8, LAYER_Y[1] + 0.5)

    # Agent -> Safety
    draw_arrow(ax, 7.8, LAYER_Y[1] - 0.5, 7.3, LAYER_Y[2] + 0.5)

    # Safety -> Tools
    draw_arrow(ax, 7.3, LAYER_Y[2] - 0.5, 7.3, LAYER_Y[3] + 0.6)

    # Tools -> Memory
    draw_arrow(ax, 7.3, LAYER_Y[3] - 0.6, 7.3, LAYER_Y[4] + 0.5)

    # Memory -> Inference
    draw_arrow(ax, 7.3, LAYER_Y[4] - 0.5, 7.3, LAYER_Y[5] + 0.5)

    # Inference -> Hardware
    draw_arrow(ax, 7.3, LAYER_Y[5] - 0.5, 7.3, LAYER_Y[6] + 0.5)

    # Reflector feedback loop (Agent -> back to Planner)
    ax.annotate(
        "",
        xy=(4.2, LAYER_Y[1] + 0.5), xytext=(11.4, LAYER_Y[1] + 0.5),
        arrowprops=dict(arrowstyle="->", color="#E67E22", lw=1.2,
                        connectionstyle="arc3,rad=0.25"),
    )
    ax.text(7.8, LAYER_Y[1] + 0.85, "retry if not completed (max 10 iterations)",
            ha="center", va="bottom", fontsize=8, color="#E67E22")

    # Footer note
    ax.text(
        FIG_W / 2, -0.45,
        "Data flow: User input → Planner decomposes → Executor calls tools (with HITL approval) → Reflector evaluates → retry or return result. "
        "All inference runs locally on AMD Radeon GPU via ROCm.",
        ha="center", va="center",
        fontsize=8, color="#666666", style="italic"
    )

    plt.tight_layout()
    out_path = str(DOCS / "architecture.png")
    plt.savefig(out_path, dpi=200, bbox_inches="tight", facecolor="white", edgecolor="none")
    print(f"Saved architecture diagram to {out_path}")


if __name__ == "__main__":
    main()
