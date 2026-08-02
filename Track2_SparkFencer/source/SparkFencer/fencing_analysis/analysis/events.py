"""Run the offline analysis pass and assemble events.json."""

import json
import os

import numpy as np

from ..data.writer import write_json
from .actions import detect_actions
from .distance import analyze_distance
from .footwork import detect_footwork, footwork_stats
from .reaction import detect_reactions, reaction_stats
from .scorecard import build_scorecard
from .style import analyze_style
from .timeline import SIDES, Timeline


def detect_phrases(timeline, config):
    """Activity-based segmentation into phrases (exchanges)."""
    cfg = config["phrase"]
    fps = timeline.fps
    active = np.zeros(timeline.n_frames, dtype=bool)
    for side in SIDES:
        fv = timeline.forward_v[side]
        active |= (~np.isnan(fv)) & (np.abs(fv) > cfg["activity_speed"])

    max_gap = int(cfg["max_gap_sec"] * fps)
    min_len = int(cfg["min_phrase_sec"] * fps)

    phrases = []
    start = None
    gap = 0
    for i, flag in enumerate(active):
        if flag:
            if start is None:
                start = i
            gap = 0
        elif start is not None:
            gap += 1
            if gap > max_gap:
                end = i - gap
                if end - start >= min_len:
                    phrases.append((start, end))
                start, gap = None, 0
    if start is not None and (timeline.n_frames - 1 - start) >= min_len:
        phrases.append((start, timeline.n_frames - 1))

    return [
        {
            "id": f"phrase_{k:03d}",
            "start_sec": round(float(timeline.t[i0]), 3),
            "end_sec": round(float(timeline.t[i1]), 3),
            "duration_sec": round(float(timeline.t[i1] - timeline.t[i0]), 3),
        }
        for k, (i0, i1) in enumerate(phrases)
    ]


def run_analysis(output_dir, config):
    metadata_path = os.path.join(output_dir, "metadata.json")
    detections_path = os.path.join(output_dir, "detections.jsonl")
    with open(metadata_path, "r", encoding="utf-8") as f:
        metadata = json.load(f)

    print("Loading detections timeline...")
    timeline = Timeline(detections_path, metadata)
    for side in SIDES:
        print(f"  {side} fencer coverage: {timeline.coverage(side) * 100:.1f}% of frames")

    print("Analyzing distance / footwork / actions / reactions / phrases...")
    distance = analyze_distance(timeline)
    footwork = detect_footwork(timeline, config)
    actions = detect_actions(timeline, footwork, config)
    reactions = detect_reactions(timeline, config)
    phrases = detect_phrases(timeline, config)

    stats = {}
    for side in SIDES:
        fv = timeline.forward_v[side]
        fv_valid = fv[~np.isnan(fv)]
        stats[side] = {
            "coverage": round(timeline.coverage(side), 3),
            "footwork": footwork_stats(footwork, side),
            "reaction": reaction_stats(reactions, side),
            "avg_abs_speed_ms": round(float(np.abs(fv_valid).mean()), 3) if len(fv_valid) else None,
            "attack_count": sum(1 for a in actions if a["fencer"] == side and a["type"] == "attack"),
            "defense_count": sum(1 for a in actions if a["fencer"] == side and a["type"] in ("parry", "counter")),
            "blade_tip_detection_rate": round(float((timeline.tip_conf[side] > 0.2).mean()), 3),
        }

    events = {
        "schema_version": "1.0",
        "video": metadata["video"],
        "weapon": config["weapon"],
        "phrases": phrases,
        "footwork": footwork,
        "actions": actions,
        "reactions": reactions,
        "distance": distance,
        "stats": stats,
    }
    events["style"] = analyze_style(timeline, events, config)
    events["scorecard"] = build_scorecard(events, timeline, lang=config.get("language", "zh"))
    events_path = os.path.join(output_dir, "events.json")
    write_json(events_path, events)
    print(f"Events written to {events_path}: {len(phrases)} phrases, "
          f"{len(footwork['lunges'])} lunges, {len(actions)} action candidates, "
          f"{len(reactions)} reaction samples")
    return events_path, events, timeline
