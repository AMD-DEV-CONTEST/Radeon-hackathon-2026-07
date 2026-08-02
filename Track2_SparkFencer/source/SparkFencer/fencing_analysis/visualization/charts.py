"""Offline charts from events.json + timeline (matplotlib, Agg backend).

Chart labels are in English to avoid CJK font issues on the headless server;
the coaching report itself is written in Chinese.
"""

import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from ..analysis.timeline import SIDES

SIDE_COLORS = {"left": "#d62728", "right": "#1f77b4"}
FOOTWORK_COLORS = {"advance": "#2ca02c", "retreat": "#d62728", "hold": "#c7c7c7"}


def generate_charts(output_dir, events, timeline):
    charts_dir = os.path.join(output_dir, "charts")
    os.makedirs(charts_dir, exist_ok=True)
    paths = []
    paths.append(_distance_chart(charts_dir, events, timeline))
    paths.append(_footwork_chart(charts_dir, events, timeline))
    paths.append(_reaction_chart(charts_dir, events))
    paths.append(_position_heatmap(charts_dir, timeline))
    paths.append(_style_radar(charts_dir, events))
    paths.append(_style_evolution(charts_dir, events))
    paths.append(_interaction_chart(charts_dir, events))
    paths = [p for p in paths if p]
    print(f"Charts written: {len(paths)} -> {charts_dir}")
    return paths


def _shade_phrases(ax, events):
    for phrase in events.get("phrases", []):
        ax.axvspan(phrase["start_sec"], phrase["end_sec"], color="#ffe08a", alpha=0.25, lw=0)


def _distance_chart(charts_dir, events, timeline):
    dist = events.get("distance", {})
    if not dist.get("available"):
        return None
    series = dist["series"]
    t = [p["t"] for p in series]
    d = [p["d"] for p in series]

    fig, ax = plt.subplots(figsize=(12, 4))
    _shade_phrases(ax, events)
    ax.plot(t, d, color="#333333", lw=1.2, label="distance")
    ax.axhline(dist["mean_m"], color="#888888", ls="--", lw=0.8, label=f"mean {dist['mean_m']:.2f} m")
    for lunge in events["footwork"]["lunges"]:
        ax.axvline(lunge["time_sec"], color=SIDE_COLORS[lunge["fencer"]], ls=":", lw=1, alpha=0.7)
    ax.set_xlabel("time (s)")
    ax.set_ylabel("fencing distance (m)")
    ax.set_title("Fencing distance over time (dotted lines = lunges, shaded = phrases)")
    ax.legend(loc="upper right", fontsize=8)
    path = os.path.join(charts_dir, "distance.png")
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)
    return path


def _footwork_chart(charts_dir, events, timeline):
    fig, ax = plt.subplots(figsize=(12, 3.6))
    _shade_phrases(ax, events)
    lanes = {"left": 1, "right": 0}
    for side in SIDES:
        for seg in events["footwork"]["segments"].get(side, []):
            ax.broken_barh(
                [(seg["start_sec"], seg["duration_sec"])],
                (lanes[side] + 0.1, 0.8),
                facecolors=FOOTWORK_COLORS.get(seg["type"], "#cccccc"),
            )
        for lunge in events["footwork"]["lunges"]:
            if lunge["fencer"] == side:
                ax.plot(lunge["time_sec"], lanes[side] + 0.5, marker="v", color="black", ms=7)
    ax.set_yticks([0.5, 1.5])
    ax.set_yticklabels(["right fencer", "left fencer"])
    ax.set_xlabel("time (s)")
    handles = [plt.Rectangle((0, 0), 1, 1, fc=c) for c in FOOTWORK_COLORS.values()]
    handles.append(plt.Line2D([], [], marker="v", color="black", ls="none"))
    ax.legend(handles, list(FOOTWORK_COLORS.keys()) + ["lunge"], loc="upper right", fontsize=8, ncol=4)
    ax.set_title("Footwork timeline (markers = lunges)")
    path = os.path.join(charts_dir, "footwork_timeline.png")
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)
    return path


def _reaction_chart(charts_dir, events):
    reactions = events.get("reactions", [])
    if not reactions:
        return None
    fig, ax = plt.subplots(figsize=(7, 4))
    for side in SIDES:
        times = [r["reaction_time_sec"] for r in reactions if r["responder"] == side]
        if times:
            ax.hist(times, bins=np.arange(0, 1.25, 0.1), alpha=0.6,
                    color=SIDE_COLORS[side], label=f"{side} fencer (n={len(times)})")
    ax.set_xlabel("reaction time (s)")
    ax.set_ylabel("count")
    ax.set_title("Reaction time distribution")
    ax.legend(fontsize=9)
    path = os.path.join(charts_dir, "reaction_times.png")
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)
    return path


STYLE_LABEL_EN = {
    "进攻压迫型": "Pressing attacker",
    "防守反击型": "Counter-attacker",
    "机动控距型": "Distance manager",
    "稳健均衡型": "Balanced",
}

RADAR_AXES = [
    ("aggression", "Aggression"),
    ("territory", "Territory"),
    ("tempo", "Tempo"),
    ("distance", "Close-quarters"),
    ("technique", "Technique"),
]


def _style_radar(charts_dir, events):
    style = events.get("style")
    if not style:
        return None
    axes_keys = [k for k, _ in RADAR_AXES]
    labels = [name for _, name in RADAR_AXES]
    angles = np.linspace(0, 2 * np.pi, len(axes_keys), endpoint=False).tolist()
    angles += angles[:1]

    fig, ax = plt.subplots(figsize=(6.5, 6), subplot_kw={"projection": "polar"})
    for side in SIDES:
        prof = style["profiles"][side]
        values = [prof[k] for k in axes_keys]
        values += values[:1]
        label_en = STYLE_LABEL_EN.get(prof.get("style_label", ""), "")
        ax.plot(angles, values, color=SIDE_COLORS[side], lw=2,
                label=f"{side} — {label_en}")
        ax.fill(angles, values, color=SIDE_COLORS[side], alpha=0.15)
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(labels, fontsize=10)
    ax.set_ylim(0, 1)
    ax.set_yticks([0.25, 0.5, 0.75])
    ax.set_yticklabels(["0.25", "0.5", "0.75"], fontsize=7)
    ax.set_title("Fencer style profile", pad=18)
    ax.legend(loc="lower right", bbox_to_anchor=(1.15, -0.1), fontsize=9)
    path = os.path.join(charts_dir, "style_radar.png")
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)
    return path


def _style_evolution(charts_dir, events):
    style = events.get("style") or {}
    evolution = style.get("evolution")
    if not evolution:
        return None
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.6))
    thirds = [1, 2, 3]
    for side in SIDES:
        segs = evolution[side]["thirds"]
        axes[0].plot(thirds, [s["advance_ratio"] for s in segs], "o-",
                     color=SIDE_COLORS[side], label=side)
        axes[1].plot(thirds, [s["attacks_per_min"] for s in segs], "o-",
                     color=SIDE_COLORS[side], label=side)
    axes[0].set_title("Advance time ratio by match third (%)")
    axes[1].set_title("Attacks per minute by match third")
    for ax in axes:
        ax.set_xticks(thirds)
        ax.set_xticklabels(["1st", "2nd", "3rd"])
        ax.legend(fontsize=8)
        ax.grid(alpha=0.25)
    path = os.path.join(charts_dir, "style_evolution.png")
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)
    return path


INTERACTION_COLORS = {"retreats": "#d62728", "holds": "#c7c7c7", "presses back": "#2ca02c"}


def _interaction_chart(charts_dir, events):
    style = events.get("style") or {}
    interaction = style.get("interaction")
    if not interaction or all(v is None for v in interaction.values()):
        return None
    rows = []
    for side, zh in (("left", "While LEFT advances"), ("right", "While RIGHT advances")):
        im = interaction.get(side)
        if im:
            rows.append((zh, [im["opponent_retreats"], im["opponent_holds"],
                              im["opponent_presses_back"]]))
    if not rows:
        return None
    fig, ax = plt.subplots(figsize=(9, 1.2 + len(rows)))
    labels = list(INTERACTION_COLORS.keys())
    for y, (name, vals) in enumerate(rows):
        left_edge = 0
        for value, key in zip(vals, labels):
            ax.barh(y, value, left=left_edge, color=INTERACTION_COLORS[key],
                    edgecolor="white", height=0.55)
            if value > 7:
                ax.text(left_edge + value / 2, y, f"{value:.0f}%", ha="center",
                        va="center", fontsize=9, color="black")
            left_edge += value
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([r[0] for r in rows])
    ax.set_xlim(0, 100)
    ax.set_xlabel("opponent response (%)")
    handles = [plt.Rectangle((0, 0), 1, 1, fc=c) for c in INTERACTION_COLORS.values()]
    ax.legend(handles, [f"opponent {k}" for k in labels], loc="upper center",
              bbox_to_anchor=(0.5, -0.35), ncol=3, fontsize=8)
    ax.set_title("Interaction matrix — response while the other advances")
    path = os.path.join(charts_dir, "interaction_matrix.png")
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)
    return path


def _position_heatmap(charts_dir, timeline):
    fig, axes = plt.subplots(2, 1, figsize=(12, 3.2), sharex=True)
    bins = np.linspace(0, timeline.piste_length, 57)
    for ax, side in zip(axes, SIDES):
        x = timeline.x[side]
        x = x[~np.isnan(x)]
        if len(x):
            hist, _ = np.histogram(x, bins=bins)
            ax.imshow(hist[np.newaxis, :], aspect="auto", cmap="hot",
                      extent=[0, timeline.piste_length, 0, 1])
        ax.set_yticks([])
        ax.set_ylabel(f"{side}", rotation=0, ha="right", va="center")
    axes[1].set_xlabel("piste position (m)")
    axes[0].set_title("Piste occupancy heatmap")
    path = os.path.join(charts_dir, "position_heatmap.png")
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)
    return path
