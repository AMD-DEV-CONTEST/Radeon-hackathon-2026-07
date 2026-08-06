#!/usr/bin/env python3
"""Render shared-physics telemetry without implying a camera replay.

The renderer keeps all six canonical robot identities visible in every frame
and annotates real kick/score events from the evaluator JSON.  It never
creates events that are absent from the source telemetry.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

TEAM_COLORS = {"A": "#35a7ff", "B": "#ff5d73"}
ROBOT_IDS = ("A_attacker", "A_defender", "A_keeper", "B_attacker", "B_defender", "B_keeper")


def field(ax):
    from matplotlib.patches import Circle, Rectangle
    ax.set_facecolor("#167846")
    ax.add_patch(Rectangle((-7, -4.5), 14, 9, fill=False, edgecolor="white", lw=2))
    ax.plot([0, 0], [-4.5, 4.5], color="white", lw=1.2)
    ax.add_patch(Circle((0, 0), 1, fill=False, edgecolor="white", lw=1.2))
    for x in (-7, 7):
        ax.add_patch(Rectangle((x - (1.65 if x > 0 else 0), -2), 1.65, 4,
                               fill=False, edgecolor="white", lw=1.2))
    ax.set(xlim=(-7.6, 7.6), ylim=(-5.15, 5.15), aspect="equal", xticks=[], yticks=[])
    for spine in ax.spines.values():
        spine.set_visible(False)


def render(source: Path, output: Path, fps: int = 10) -> None:
    import imageio.v2 as imageio
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    data = json.loads(source.read_text(encoding="utf-8"))
    steps = data.get("steps") or []
    if len(steps) < 2:
        raise ValueError("shared physics JSON must contain at least two steps")
    duration = float(data.get("duration_s", steps[-1].get("sim_time_s", 0.0)))
    with imageio.get_writer(output, fps=fps, codec="libx264", quality=8) as writer:
        for sample in steps:
            fig, ax = plt.subplots(figsize=(12.8, 7.2), dpi=100)
            fig.patch.set_facecolor("#0c1821")
            fig.subplots_adjust(left=.035, right=.965, bottom=.11, top=.86)
            field(ax)
            for robot_id in ROBOT_IDS:
                state = sample["robots"][robot_id]
                x, y = state["position"][:2]
                color = TEAM_COLORS[state["team"]]
                ax.scatter(x, y, s=420, color=color, edgecolor="white", lw=1.8, zorder=4)
                ax.text(x, y, robot_id.split("_")[1][0].upper(), ha="center", va="center",
                        color="white", fontsize=10, weight="bold", zorder=5)
                label = f"{robot_id} · {state['controller']}"
                ax.annotate(label, (x, y), xytext=(0, 18), textcoords="offset points",
                            ha="center", color="white", fontsize=7,
                            bbox={"boxstyle": "round,pad=.18", "fc": "#102734", "ec": color})
                if state.get("fallen"):
                    ax.annotate("FALLEN", (x, y), xytext=(0, -22), textcoords="offset points",
                                ha="center", color="#ffdf57", fontsize=7, weight="bold")
            ball = sample["ball"]["position"]
            ax.scatter(ball[0], ball[1], s=150, color="#ffcf33", edgecolor="#442b00", lw=1.5, zorder=7)
            ax.text(ball[0], ball[1] - .32, "BALL", ha="center", color="#fff5c2", fontsize=7, weight="bold")
            event = sample.get("events", {})
            score = sample.get("score", {"A": 0, "B": 0})
            t = float(sample.get("sim_time_s", 0.0))
            fig.text(.04, .94, "TRACK 3 · SHARED PHYSICS multi-robot", color="white", fontsize=16, weight="bold")
            fig.text(.96, .94, f"{t:04.1f}s / {duration:.1f}s    A {score.get('A', 0)} : {score.get('B', 0)} B",
                     color="white", fontsize=14, weight="bold", ha="right")
            kicks = event.get("kicks", [])
            if kicks or event.get("scored"):
                text = "KICK: " + ", ".join(kicks) if kicks else "GOAL!"
                if event.get("scored"):
                    text += f"  GOAL by {event.get('scored_by') or 'unknown'}"
                fig.text(.5, .895, text, color="#ffdf57", fontsize=13, weight="bold", ha="center")
            status = data.get("validation_status", data.get("status", "unknown"))
            fig.text(.5, .035, f"Telemetry visualization · validation={status} · no camera replay",
                     color="#b7c8d4", fontsize=9, ha="center")
            fig.canvas.draw()
            writer.append_data(np.asarray(fig.canvas.buffer_rgba(), dtype=np.uint8)[..., :3])
            plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--fps", type=int, default=10)
    args = parser.parse_args()
    render(args.input, args.output, args.fps)


if __name__ == "__main__":
    main()
