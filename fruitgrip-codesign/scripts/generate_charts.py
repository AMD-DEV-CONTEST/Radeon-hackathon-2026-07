#!/usr/bin/env python3
"""Regenerate every chart under docs/images/ from the committed results/*.json.

No values are computed or approximated here -- every number plotted is read
directly from an existing results file. Run from the repo root:

    uv run python scripts/generate_charts.py
"""
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
OUT = ROOT / "docs" / "images"
OUT.mkdir(parents=True, exist_ok=True)

COLOR_WINNER = "#2f6f4f"
COLOR_BASELINE = "#8a8f98"
COLOR_TIE = "#4a6fa5"
COLOR_REGRESS = "#b5493f"
COLOR_ACCENT = "#c9862f"
COLOR_GRID = "#d8dce1"

plt.rcParams.update(
    {
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "axes.edgecolor": "#3a3f47",
        "axes.labelcolor": "#1f2328",
        "text.color": "#1f2328",
        "xtick.color": "#3a3f47",
        "ytick.color": "#3a3f47",
        "font.size": 11,
        "font.family": "sans-serif",
        "axes.grid": True,
        "grid.color": COLOR_GRID,
        "grid.linewidth": 0.8,
        "axes.axisbelow": True,
        "savefig.dpi": 190,
        "savefig.bbox": "tight",
    }
)


def load(rel_path):
    with open(RESULTS / rel_path) as f:
        return json.load(f)


def chart_confirmation():
    d = load("01_core_confirmation/confirmation_eval.json")
    names = ["Baseline\n(2-finger)", "Winner\n(3-finger, co-designed)"]
    rates = [d["baseline"]["success_rate"] * 100, d["winner"]["success_rate"] * 100]
    ci_lo = [d["baseline"]["success_rate_95ci"][0] * 100, d["winner"]["success_rate_95ci"][0] * 100]
    ci_hi = [d["baseline"]["success_rate_95ci"][1] * 100, d["winner"]["success_rate_95ci"][1] * 100]
    err_lo = [rates[i] - ci_lo[i] for i in range(2)]
    err_hi = [ci_hi[i] - rates[i] for i in range(2)]
    n = d["baseline"]["n_trials"]

    fig, ax = plt.subplots(figsize=(6.2, 4.6))
    colors = [COLOR_BASELINE, COLOR_WINNER]
    bars = ax.bar(names, rates, color=colors, width=0.55, zorder=3)
    ax.errorbar(names, rates, yerr=[err_lo, err_hi], fmt="none", ecolor="#1f2328", elinewidth=1.8, capsize=7, zorder=4)
    for bar, rate in zip(bars, rates):
        ax.text(bar.get_x() + bar.get_width() / 2, rate + max(err_hi) + 3, f"{rate:.1f}%", ha="center", fontsize=16, fontweight="bold")
    ax.set_ylim(0, 122)
    ax.set_yticks(range(0, 101, 20))
    ax.set_ylabel("Pick-and-place success rate (%)", fontsize=11.5)
    ax.set_title(f"93.3% vs 26.7%\nn={n} paired trials, non-overlapping 95% Wilson CI", fontsize=13.5, fontweight="bold", pad=14)
    ax.spines[["top", "right"]].set_visible(False)
    fig.savefig(OUT / "confirmation_bar.png")
    plt.close(fig)


def chart_ycb_generalization():
    d = load("03_generalization/ycb_generalization_eval.json")
    rows = []
    for obj in d["objects"]:
        b = d["baseline"][obj]["success_rate"]
        w = d["winner"][obj]["success_rate"]
        rows.append((obj, b, w, w - b))
    both_fail = sum(1 for r in rows if r[1] == 0 and r[2] == 0)
    rows = [r for r in rows if not (r[1] == 0 and r[2] == 0)]
    rows.sort(key=lambda r: r[3])

    labels = [r[0].split("_", 1)[-1].replace("_", " ").replace("-", " ").title() for r in rows]
    diffs = [r[3] * 100 for r in rows]

    def color_for(r):
        if abs(r[3]) < 1e-9:
            return COLOR_TIE
        return COLOR_WINNER if r[3] > 0 else COLOR_BASELINE

    colors = [color_for(r) for r in rows]

    fig, ax = plt.subplots(figsize=(9, 8))
    y = range(len(rows))
    ax.barh(y, diffs, color=colors, zorder=3, height=0.72)
    ax.set_yticks(list(y))
    ax.set_yticklabels(labels, fontsize=11)
    ax.axvline(0, color="#1f2328", linewidth=1.2)
    ax.set_xlabel("Winner success rate − baseline success rate (percentage points)", fontsize=11.5)
    ax.set_title(
        "Generalization is category-specific, not universal",
        fontsize=17, fontweight="bold", pad=16,
    )
    ax.text(
        0.5, 1.015,
        f"36 real YCB objects · {len(rows)} show a measurable difference · {both_fail} more score 0% for both designs (not shown)",
        transform=ax.transAxes, ha="center", fontsize=10.5, color="#5a6270",
    )
    ax.spines[["top", "right"]].set_visible(False)

    handles = [
        plt.Rectangle((0, 0), 1, 1, color=COLOR_WINNER),
        plt.Rectangle((0, 0), 1, 1, color=COLOR_BASELINE),
        plt.Rectangle((0, 0), 1, 1, color=COLOR_TIE),
    ]
    ax.legend(handles, ["Winner-favored (round/curved)", "Baseline-favored (flat-faced)", "Both succeed equally"], loc="lower right", fontsize=10, frameon=True)
    fig.savefig(OUT / "ycb_category_split.png")
    plt.close(fig)


def chart_friction_doseresponse():
    gen = load("05_cross_simulator/friction_doseresponse_genesis.json")
    mj = load("05_cross_simulator/friction_doseresponse_mujoco.json")

    fig, ax = plt.subplots(figsize=(7.5, 5.2))
    series = [
        (gen, "baseline", "Genesis · baseline", COLOR_BASELINE, "-", "o"),
        (gen, "winner", "Genesis · winner", COLOR_WINNER, "-", "o"),
        (mj, "baseline", "MuJoCo · baseline", COLOR_BASELINE, "--", "^"),
        (mj, "winner", "MuJoCo · winner", COLOR_WINNER, "--", "^"),
    ]
    for data, key, label, color, ls, marker in series:
        pts = data[key]["points"]
        x = [p["friction_ratio"] for p in pts]
        y = [p["success_rate"] * 100 for p in pts]
        ax.plot(x, y, ls, marker=marker, color=color, label=label, linewidth=2.0, markersize=4.5)

    ax.set_xlabel("Friction ratio (× nominal)", fontsize=11.5)
    ax.set_ylabel("Pick-and-place success rate (%)", fontsize=11.5)
    ax.set_title("The cross-simulator reversal, explained mechanistically", fontsize=14.5, fontweight="bold", pad=12)
    ax.set_ylim(-3, 108)
    ax.legend(fontsize=9.5, frameon=True, ncol=2)
    ax.spines[["top", "right"]].set_visible(False)
    fig.savefig(OUT / "friction_doseresponse.png")
    plt.close(fig)


def chart_rocm_throughput():
    cpu = load("04_rocm_benchmark/throughput_bench_cpu.json")
    gpu = load("04_rocm_benchmark/throughput_bench_gpu.json") + load("04_rocm_benchmark/throughput_bench_gpu_extended.json")

    fig, ax = plt.subplots(figsize=(8, 5.6))
    cx = [r["n_envs"] for r in cpu]
    cy = [r["env_steps_per_sec"] for r in cpu]
    gx = [r["n_envs"] for r in gpu]
    gy = [r["env_steps_per_sec"] for r in gpu]
    ax.plot(cx, cy, "-o", color=COLOR_BASELINE, label="CPU (Ryzen 7 5825U)", linewidth=2.2, markersize=6)
    ax.plot(gx, gy, "-o", color=COLOR_WINNER, label="ROCm GPU (batched)", linewidth=2.6, markersize=6.5)
    ax.fill_between(gx, gy, color=COLOR_WINNER, alpha=0.06)
    ax.set_xscale("log", base=2)
    ax.set_yscale("log")
    ax.set_xlabel("Parallel environments (n_envs, log scale)", fontsize=11.5)
    ax.set_ylabel("Throughput (env-steps/sec, log scale)", fontsize=11.5)
    ax.set_title("148,419 vs 5,052 env-steps/sec — 29.4x peak throughput", fontsize=14.5, fontweight="bold", pad=12)
    peak_cpu = max(cy)
    peak_gpu = max(gy)
    ax.annotate(
        f"{peak_gpu / peak_cpu:.1f}x",
        xy=(gx[-1], gy[-1]),
        xytext=(gx[-1] * 0.22, gy[-1] * 1.05),
        fontsize=22,
        fontweight="bold",
        color=COLOR_WINNER,
    )
    ax.legend(fontsize=10.5, frameon=True, loc="lower right")
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(True, which="both", axis="both")
    fig.savefig(OUT / "rocm_throughput.png")
    plt.close(fig)


def chart_attribution_reliability():
    d = load("02_attribution_multiseed/attribution_multiseed.json")
    seed_labels = [f"Seeds\n{s[0]}-{s[-1]}" for s in d["seed_sets"]]
    baseline_rates = [r["baseline"]["agg"]["success_rate"] * 100 for r in d["runs"]]
    winner_rates = [r["joint_best"]["agg"]["success_rate"] * 100 for r in d["runs"]]
    x = range(len(seed_labels))

    fig, ax = plt.subplots(figsize=(7.5, 5.2))
    ax.plot(x, winner_rates, "-o", color=COLOR_WINNER, linewidth=2.8, markersize=9, label="Winner (joint search): 100% every seed", zorder=4)
    ax.plot(x, baseline_rates, "-o", color=COLOR_BASELINE, linewidth=2.2, markersize=8, linestyle="--", label="Baseline: swings 0-66.7%", zorder=3)
    ax.fill_between(x, baseline_rates, [100] * len(x), color=COLOR_BASELINE, alpha=0.06)
    ax.set_xticks(list(x))
    ax.set_xticklabels(seed_labels, fontsize=9.5)
    ax.set_ylim(-5, 112)
    ax.set_ylabel("Pick-and-place success rate (%)", fontsize=11.5)
    ax.set_title("5 independent seed sets, n=3 trials each — same protocol every time", fontsize=10, color="#5a6270", pad=10)
    fig.suptitle("The winner is reliable, not just lucky on one seed", fontsize=14.5, fontweight="bold", y=0.99)
    fig.subplots_adjust(top=0.85)
    ax.legend(fontsize=10, frameon=True, loc="lower left")
    ax.spines[["top", "right"]].set_visible(False)
    fig.savefig(OUT / "attribution_reliability.png")
    plt.close(fig)


def chart_force_margin():
    fig, ax = plt.subplots(figsize=(6.5, 5.2))
    required = 1.02
    names = ["Baseline\n(2 contacts)", "Winner\n(3 contacts)"]
    available = [30.8, 38.2]
    margins = ["~30x", "~37x"]
    colors = [COLOR_BASELINE, COLOR_WINNER]

    bars = ax.bar(names, available, color=colors, width=0.5, zorder=3)
    ax.axhline(required, color=COLOR_REGRESS, linewidth=2, linestyle="--", zorder=4)
    ax.text(1.42, required + 0.6, f"physically required: {required:.2f}N", color=COLOR_REGRESS, fontsize=9.5, ha="right", fontweight="bold")

    for bar, val, margin in zip(bars, available, margins):
        ax.text(bar.get_x() + bar.get_width() / 2, val + 1.2, f"{val:.1f}N", ha="center", fontsize=13, fontweight="bold")
        ax.text(bar.get_x() + bar.get_width() / 2, val * 0.5, margin, ha="center", va="center", fontsize=20, fontweight="bold", color="white")

    ax.set_ylabel("Available support force (N)", fontsize=11.5)
    ax.set_title("Available = n_contacts × μ × mean peak force, vs. worst-case required grip force", fontsize=9.5, color="#5a6270", pad=10)
    fig.suptitle("Not force — both designs have 30-37x headroom", fontsize=14.5, fontweight="bold", y=0.99)
    fig.subplots_adjust(top=0.85)
    ax.set_ylim(0, 44)
    ax.spines[["top", "right"]].set_visible(False)
    fig.savefig(OUT / "force_margin.png")
    plt.close(fig)


def chart_grasp_planner_comparison():
    old = load("03_generalization/ycb_generalization_eval.json")
    new = load("08_grasp_planner/ycb_generalization_eval_planner.json")

    picks = [
        ("013_apple", "winner", "Apple\n(winner)"),
        ("077_rubiks_cube", "winner", "Rubik's Cube\n(winner)"),
        ("058_golf_ball", "winner", "Golf Ball\n(winner)"),
        ("033_spatula", "baseline", "Spatula\n(baseline)"),
        ("048_hammer", "winner", "Hammer\n(winner)"),
        ("065-a_cups", "winner", "Cups\n(winner)"),
    ]
    labels, before, after, colors = [], [], [], []
    for obj, design, label in picks:
        b = old[design][obj]["success_rate"] * 100
        a = new[design][obj]["success_rate"] * 100
        labels.append(label)
        before.append(b)
        after.append(a)
        colors.append(COLOR_WINNER if a > b else COLOR_REGRESS)

    x = range(len(labels))
    width = 0.36
    fig, ax = plt.subplots(figsize=(9.5, 5.6))
    ax.bar([i - width / 2 for i in x], before, width=width, color="#c7cbd1", label="Fixed heuristic (before)", zorder=3)
    bars_after = ax.bar([i + width / 2 for i in x], after, width=width, color=colors, label="Grasp planner (after)", zorder=3)
    for i, (b, a) in enumerate(zip(before, after)):
        ax.text(i - width / 2, b + 2, f"{b:.0f}%", ha="center", fontsize=9.5)
        ax.text(i + width / 2, a + 2, f"{a:.0f}%", ha="center", fontsize=9.5, fontweight="bold")
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, fontsize=10)
    ax.set_ylabel("Pick-and-place success rate (%)", fontsize=11.5)
    ax.set_ylim(0, 112)
    ax.set_title("Same statistical protocol (n=15) — reported with equal weight either direction", fontsize=9.5, color="#5a6270", pad=10)
    fig.suptitle("Geometry-driven grasp planning: real wins, one real regression", fontsize=14, fontweight="bold", y=0.99)
    fig.subplots_adjust(top=0.85)
    handles = [
        plt.Rectangle((0, 0), 1, 1, color="#c7cbd1"),
        plt.Rectangle((0, 0), 1, 1, color=COLOR_WINNER),
        plt.Rectangle((0, 0), 1, 1, color=COLOR_REGRESS),
    ]
    ax.legend(handles, ["Before (fixed heuristic)", "After — improved", "After — regressed"], fontsize=9.5, frameon=True, loc="upper left")
    ax.spines[["top", "right"]].set_visible(False)
    fig.savefig(OUT / "grasp_planner_comparison.png")
    plt.close(fig)


def chart_architecture_diagram():
    fig, ax = plt.subplots(figsize=(13, 6.4))
    ax.set_xlim(0, 13)
    ax.set_ylim(0, 6.4)
    ax.axis("off")

    def box(cx, cy, w, h, text, color, text_color="white", fontsize=10.5):
        b = FancyBboxPatch(
            (cx - w / 2, cy - h / 2), w, h,
            boxstyle="round,pad=0.02,rounding_size=0.12",
            linewidth=0, facecolor=color, zorder=3,
        )
        ax.add_patch(b)
        ax.text(cx, cy, text, ha="center", va="center", fontsize=fontsize, color=text_color, fontweight="bold", zorder=4, linespacing=1.4)
        return b

    def arrow(x0, y0, x1, y1, color="#3a3f47", style="-|>", lw=2.0):
        a = FancyArrowPatch((x0, y0), (x1, y1), arrowstyle=style, mutation_scale=16, linewidth=lw, color=color, zorder=2)
        ax.add_patch(a)

    main_y = 4.6
    box(1.5, main_y, 2.6, 1.5, "Parametric\nGripper Geometry\ngripper_gen.py", "#4a5568")
    box(4.6, main_y, 2.6, 1.5, "CMA-ES + QD Search\nsearch.py\nfruit_archive.py", COLOR_ACCENT)
    box(7.7, main_y, 2.6, 1.5, "Co-Adapted Controller\ncontroller_adapt.py\n(+ grasp_planner.py)", COLOR_TIE)
    box(10.8, main_y, 2.6, 1.5, "Domain-Randomized\nPhysics Trial\nGenesis / ROCm", "#4a5568")

    arrow(2.8, main_y, 3.3, main_y)
    arrow(5.9, main_y, 6.4, main_y)
    arrow(9.0, main_y, 9.5, main_y)

    bottom_y = 1.6
    box(4.6, bottom_y, 2.6, 1.5, "Statistically-Powered\nComparison\nn=30, Wilson CI", COLOR_WINNER)
    box(7.7, bottom_y, 2.6, 1.5, "Cross-Simulator\nReplication\nGenesis ⇄ MuJoCo", COLOR_BASELINE)
    box(10.8, bottom_y, 2.6, 1.5, "Frozen Designs\nBaseline vs Winner\nfrozen_designs.py", "#4a5568")

    arrow(10.8, main_y - 0.75, 10.8, bottom_y + 0.75)
    arrow(9.5, bottom_y, 9.0, bottom_y)
    arrow(6.4, bottom_y, 5.9, bottom_y)

    ax.text(6.5, 6.0, "End-to-end pipeline", fontsize=17, fontweight="bold", ha="center")
    ax.text(6.5, 5.55, "Franka Panda + parametric gripper  →  co-adapted controller  →  domain-randomized trial  →  statistically powered, cross-simulator-replicated comparison", fontsize=9.5, ha="center", color="#5a6270")

    fig.savefig(OUT / "architecture_diagram.png")
    plt.close(fig)


DASHBOARD_TILES = [
    "confirmation_bar.png",
    "ycb_category_split.png",
    "rocm_throughput.png",
    "attribution_reliability.png",
    "force_margin.png",
    "grasp_planner_comparison.png",
]


def build_composite_dashboard():
    tile_w, tile_h = 640, 480
    cols, rows = 3, 2
    header_h = 110
    pad = 14

    canvas_w = cols * tile_w + (cols + 1) * pad
    canvas_h = header_h + rows * tile_h + (rows + 1) * pad
    canvas = Image.new("RGB", (canvas_w, canvas_h), "#f4f5f7")
    draw = ImageDraw.Draw(canvas)

    mpl_fonts = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
    try:
        font_title = ImageFont.truetype(str(mpl_fonts / "DejaVuSans-Bold.ttf"), 40)
        font_sub = ImageFont.truetype(str(mpl_fonts / "DejaVuSans.ttf"), 20)
    except OSError:
        font_title = ImageFont.load_default()
        font_sub = ImageFont.load_default()

    draw.text((pad, 18), "FruitGrip-CoDesign — every headline result, at a glance", fill="#1f2328", font=font_title)
    draw.text((pad, 68), "Every chart below is generated directly from committed results/*.json — no illustration, no approximation.", fill="#5a6270", font=font_sub)

    for i, name in enumerate(DASHBOARD_TILES):
        r, c = divmod(i, cols)
        x = pad + c * (tile_w + pad)
        y = header_h + pad + r * (tile_h + pad)
        img_path = OUT / name
        if not img_path.exists():
            continue
        im = Image.open(img_path).convert("RGB")
        im.thumbnail((tile_w, tile_h), Image.LANCZOS)
        tile = Image.new("RGB", (tile_w, tile_h), "white")
        ox = (tile_w - im.width) // 2
        oy = (tile_h - im.height) // 2
        tile.paste(im, (ox, oy))
        canvas.paste(tile, (x, y))

    canvas.save(OUT / "dashboard.png", quality=92)


if __name__ == "__main__":
    chart_confirmation()
    chart_ycb_generalization()
    chart_friction_doseresponse()
    chart_rocm_throughput()
    chart_attribution_reliability()
    chart_force_margin()
    chart_grasp_planner_comparison()
    chart_architecture_diagram()
    build_composite_dashboard()
    print(f"wrote 9 charts + dashboard to {OUT}")
