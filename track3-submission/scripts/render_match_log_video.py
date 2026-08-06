#!/usr/bin/env python3
"""Render a top-down video from a coordinator match JSON log.

This is deliberately an offline trajectory visualizer.  It does not replay the
physics simulation and must not be presented as a camera/Genesis render.
"""

from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import math
import platform
import shlex
from pathlib import Path

TEAM_COLORS = {"A": "#35a7ff", "B": "#ff5d73"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_match(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    identities = data.get("identities")
    if not isinstance(identities, dict) or not identities:
        raise ValueError("match log must contain a non-empty identities mapping")
    normalized = {}
    for client, identity in identities.items():
        if not isinstance(client, str) or not isinstance(identity, dict):
            raise ValueError("each identity must map a client id to an object")
        controller = identity.get("controller", identity.get("policy"))
        if not all(isinstance(identity.get(key), str) and identity[key] for key in ("team", "role")):
            raise ValueError(f"identity {client} must contain non-empty team and role")
        if not isinstance(controller, str) or not controller:
            raise ValueError(f"identity {client} must contain a non-empty controller")
        normalized[client] = dict(identity)
        normalized[client]["controller"] = controller
        normalized[client].pop("policy", None)
    data["identities"] = normalized
    log = data.get("log")
    if not isinstance(log, list) or len(log) < 2:
        raise ValueError("match log must contain at least two samples")
    expected = set(normalized)
    for index, sample in enumerate(log):
        if set(sample.get("robots", {})) != expected:
            raise ValueError(f"sample {index} robot ids do not match identities")
        events = sample.get("events", {})
        if not isinstance(events, dict) or set(events) != expected:
            raise ValueError(f"sample {index} event ids do not match identities")
        if any(not isinstance(event, dict) or
               not isinstance(event.get("fallen"), bool) or
               not isinstance(event.get("scored"), bool) for event in events.values()):
            raise ValueError(f"sample {index} events must contain boolean fallen/scored telemetry")
        numeric_objects = [sample.get("ball", {}), *sample["robots"].values()]
        for state in numeric_objects:
            for key in ("x", "y"):
                value = state.get(key)
                if not isinstance(value, (int, float)) or not math.isfinite(value):
                    raise ValueError(f"sample {index} has invalid {key} coordinate")
    times = []
    for index, sample in enumerate(log):
        value = sample.get("t")
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"sample {index} has invalid timestamp")
        times.append(float(value))
    if any(right <= left for left, right in zip(times, times[1:])):
        raise ValueError("sample timestamps must be strictly increasing")
    return data


def interpolate_sample(log: list[dict], timestamp: float, clients=None) -> dict:
    clients = tuple(clients or log[0]["robots"])
    times = [float(sample["t"]) for sample in log]
    right = bisect.bisect_right(times, timestamp)
    if right == 0:
        return log[0]
    if right >= len(log):
        return log[-1]
    left = right - 1
    alpha = (timestamp - times[left]) / (times[right] - times[left])

    def blend(first: dict, second: dict) -> dict:
        return {
            key: float(first[key]) + alpha * (float(second[key]) - float(first[key]))
            for key in first.keys() & second.keys()
            if isinstance(first[key], (int, float)) and isinstance(second[key], (int, float))
        }

    return {
        "t": timestamp,
        "ball": blend(log[left]["ball"], log[right]["ball"]),
        "robots": {
            client: blend(log[left]["robots"][client], log[right]["robots"][client])
            for client in clients
        },
        "events": log[left if alpha < 0.5 else right]["events"],
        "collisions": log[left].get("collisions", 0),
    }


def draw_field(ax) -> None:
    from matplotlib.patches import Arc, Circle, Rectangle

    ax.set_facecolor("#167846")
    ax.add_patch(Rectangle((-7, -4.5), 14, 9, fill=False, edgecolor="white", lw=2))
    ax.plot([0, 0], [-4.5, 4.5], color="white", lw=1.5)
    ax.add_patch(Circle((0, 0), 1.0, fill=False, edgecolor="white", lw=1.5))
    ax.add_patch(Circle((0, 0), 0.06, color="white"))
    for side in (-1, 1):
        x = 7 * side
        ax.add_patch(Rectangle((x - (1.65 if side > 0 else 0), -2.0), 1.65, 4.0,
                               fill=False, edgecolor="white", lw=1.5))
        ax.add_patch(Rectangle((x - (0.65 if side > 0 else 0), -1.0), 0.65, 2.0,
                               fill=False, edgecolor="white", lw=1.2))
        ax.add_patch(Rectangle((x if side > 0 else x - 0.35, -1.3), 0.35, 2.6,
                               fill=False, edgecolor="#d7e1e8", lw=2))
        ax.add_patch(Arc((x - 1.65 * side, 0), 2.0, 2.0,
                         theta1=90 if side > 0 else -90,
                         theta2=270 if side > 0 else 90, color="white", lw=1.2))
    ax.set_xlim(-7.6, 7.6)
    ax.set_ylim(-5.15, 5.15)
    ax.set_aspect("equal")
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)


def render_frame(sample: dict, identities: dict, duration: float, size: tuple[int, int]):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    width, height = size
    fig, ax = plt.subplots(figsize=(width / 100, height / 100), dpi=100)
    fig.patch.set_facecolor("#0c1821")
    fig.subplots_adjust(left=0.035, right=0.965, bottom=0.11, top=0.88)
    draw_field(ax)

    for client, identity in identities.items():
        team, role = identity["team"], identity["role"]
        state = sample["robots"][client]
        color = TEAM_COLORS.get(team, "#ad7cff")
        ax.scatter(state["x"], state["y"], s=380, color=color, edgecolor="white", lw=1.8, zorder=4)
        short_id = client.removeprefix("client_")
        ax.text(state["x"], state["y"], short_id, ha="center", va="center",
                color="white", fontsize=9, weight="bold", zorder=5)
        ax.annotate(f"{team} {role}", (state["x"], state["y"]), xytext=(0, 16),
                    textcoords="offset points", ha="center", color="white", fontsize=7,
                    weight="bold", bbox={"boxstyle": "round,pad=.18", "fc": "#102734", "ec": color, "alpha": .9})
        event = sample.get("events", {}).get(client, {})
        status = "FALLEN" if event.get("fallen") else "SCORED" if event.get("scored") else ""
        if status:
            ax.annotate(status, (state["x"], state["y"]), xytext=(0, -22),
                        textcoords="offset points", ha="center", color="#ffdf57",
                        fontsize=7, weight="bold")

    ball = sample["ball"]
    ax.scatter(ball["x"], ball["y"], s=135, color="#ffcf33", edgecolor="#442b00", lw=1.5, zorder=7)
    ax.text(ball["x"], ball["y"] - 0.32, "BALL", ha="center", color="#fff5c2", fontsize=7, weight="bold")

    timestamp = float(sample["t"])
    fig.text(.04, .945, "TRACK 3 · REMOTE multi-robot MATCH LOG", color="white", fontsize=15, weight="bold")
    fig.text(.96, .945, f"{timestamp:04.1f}s / {duration:.1f}s", color="white", fontsize=14,
             weight="bold", ha="right")
    teams = {}
    for client, identity in identities.items():
        teams.setdefault(identity["team"], {"controllers": set(), "clients": []})
        teams[identity["team"]]["controllers"].add(identity["controller"])
        teams[identity["team"]]["clients"].append(client.removeprefix("client_"))
    summaries = [
        f"TEAM {team}  {'/'.join(sorted(info['controllers']))} · clients {','.join(info['clients'])}"
        for team, info in sorted(teams.items())
    ]
    if summaries:
        fig.text(.04, .895, summaries[0], color=TEAM_COLORS.get(sorted(teams)[0], "white"), fontsize=10, weight="bold")
    if len(summaries) > 1:
        fig.text(.96, .895, summaries[1], color=TEAM_COLORS.get(sorted(teams)[1], "white"), fontsize=10,
                 weight="bold", ha="right")
    fig.text(.5, .035,
             "Offline visualization of coordinator trajectories · not a camera or physics-engine render",
             color="#b7c8d4", fontsize=9, ha="center")
    fig.canvas.draw()
    frame = np.asarray(fig.canvas.buffer_rgba(), dtype=np.uint8)[..., :3].copy()
    plt.close(fig)
    return frame


def render_video(input_path: Path, output_path: Path, metadata_path: Path, model_path: Path,
                 stdout_path: Path,
                 fps: int = 10, width: int = 1280, height: int = 720) -> dict:
    import imageio
    import imageio.v2 as imageio_v2
    import imageio_ffmpeg
    import matplotlib
    import numpy as np

    data = load_match(input_path)
    duration = float(data["log"][-1]["t"])
    frame_count = max(2, math.ceil(duration * fps) + 1)
    timestamps = np.linspace(float(data["log"][0]["t"]), duration, frame_count)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = " ".join(shlex.quote(part) for part in [
        "python3", "scripts/render_match_log_video.py", "--input", str(input_path),
        "--output", str(output_path), "--metadata", str(metadata_path), "--model", str(model_path),
        "--stdout-log", str(stdout_path),
        "--fps", str(fps), "--width", str(width), "--height", str(height),
    ])
    with imageio_v2.get_writer(output_path, fps=fps, codec="libx264", quality=8,
                               macro_block_size=None, pixelformat="yuv420p") as writer:
        for timestamp in timestamps:
            writer.append_data(render_frame(
                interpolate_sample(data["log"], float(timestamp), data["identities"]),
                data["identities"], duration, (width, height)
            ))

    metadata = {
        "artifact_type": "offline_match_log_visualization",
        "source_log": str(input_path),
        "source_log_sha256": sha256_file(input_path),
        "source_stdout_log": str(stdout_path),
        "source_stdout_sha256": sha256_file(stdout_path),
        "model": str(model_path),
        "model_sha256": sha256_file(model_path),
        "video_sha256": sha256_file(output_path),
        "renderer_sha256": sha256_file(Path(__file__)),
        "command": command,
        "frame_count": frame_count,
        "fps": fps,
        "duration_seconds": duration,
        "first_sample_t": float(data["log"][0]["t"]),
        "last_sample_t": duration,
        "resolution": [width, height],
        "source_samples": len(data["log"]),
        "source_sync_hz": data.get("sync_hz"),
        "role_mapping_basis": "identities embedded in the same source match log",
        "role_mapping": data["identities"],
        "identity_source": data.get("identity_source"),
        "event_summary": {
            event_name: sorted({
                client for sample in data["log"] for client, event in sample["events"].items()
                if event[event_name]
            })
            for event_name in ("fallen", "scored")
        },
        "identity_model_sha256": sorted({
            identity["model_sha"] for identity in data["identities"].values()
            if isinstance(identity.get("model_sha"), str)
        }),
        "tool_versions": {
            "python": platform.python_version(),
            "imageio": imageio.__version__,
            "matplotlib": matplotlib.__version__,
            "ffmpeg": imageio_ffmpeg.get_ffmpeg_version(),
        },
        "limitations": [
            "This is a linear interpolation of real remote coordinator trajectory samples.",
            "This is not a camera render or a replay of the Genesis physics simulation.",
            "Startup zero positions are retained because they occur in the source log before all workers report state.",
        ],
    }
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return metadata


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--stdout-log", type=Path, required=True)
    parser.add_argument("--fps", type=int, default=10)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.fps <= 0 or args.width <= 0 or args.height <= 0:
        raise SystemExit("fps, width, and height must be positive")
    metadata = render_video(args.input, args.output, args.metadata, args.model, args.stdout_log,
                            args.fps, args.width, args.height)
    print(f"Rendered {metadata['frame_count']} frames to {args.output}")
    print(f"Metadata: {args.metadata}")


if __name__ == "__main__":
    main()
