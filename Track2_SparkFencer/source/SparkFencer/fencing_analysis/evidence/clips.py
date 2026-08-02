"""Build time-window evidence without duplicating video into event clips.

The WebUI reuses the single annotated replay video and seeks it to each event's
start/end window.  When VLM review is enabled, lightweight keyframes are still
written for the local vision model; no per-event MP4 is created.
"""

import os
import cv2

from ..data.writer import write_json


def _select_events(events, config):
    """Pick the events worth cutting: lunges, action candidates and the
    best/worst reaction samples, capped per type."""
    cap = config["evidence"]["max_events_per_type"]
    selected = []

    lunges = sorted(events["footwork"]["lunges"], key=lambda e: -e["confidence"])[:cap]
    for lunge in lunges:
        selected.append({
            "kind": "lunge",
            "fencer": lunge["fencer"],
            "start_sec": lunge["start_sec"],
            "end_sec": lunge.get("recovery_sec") or lunge["time_sec"] + 1.0,
            "peak_sec": lunge["time_sec"],
            "confidence": lunge["confidence"],
            "detail": lunge,
        })

    actions = sorted(events["actions"], key=lambda a: -a["confidence"])
    per_type = {}
    for action in actions:
        per_type.setdefault(action["type"], [])
        if len(per_type[action["type"]]) >= cap:
            continue
        per_type[action["type"]].append(action)
        selected.append({
            "kind": f"action_{action['type']}",
            "fencer": action["fencer"],
            "start_sec": action["start_sec"],
            "end_sec": action["end_sec"],
            "peak_sec": (action["start_sec"] + action["end_sec"]) / 2,
            "confidence": action["confidence"],
            "detail": action,
        })

    reactions = sorted(events["reactions"], key=lambda r: r["reaction_time_sec"])
    picks = reactions[: cap // 2] + reactions[-(cap // 2):] if len(reactions) > cap else reactions
    seen = set()
    for reaction in picks:
        key = (reaction["stimulus_sec"], reaction["responder"])
        if key in seen:
            continue
        seen.add(key)
        selected.append({
            "kind": "reaction",
            "fencer": reaction["responder"],
            "start_sec": reaction["stimulus_sec"],
            "end_sec": reaction["response_sec"] + 0.5,
            "peak_sec": reaction["response_sec"],
            "confidence": 0.5,
            "detail": reaction,
        })

    selected.sort(key=lambda e: e["start_sec"])
    for idx, event in enumerate(selected):
        event["id"] = f"ev_{idx:03d}_{event['kind']}"
    return selected


def _extract_keyframes(video_path, times, out_prefix):
    paths = []
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return paths
    for k, t in enumerate(times):
        cap.set(cv2.CAP_PROP_POS_MSEC, max(0, t * 1000.0))
        ret, frame = cap.read()
        if not ret:
            continue
        height = frame.shape[0]
        if height > 720:
            scale = 720.0 / height
            frame = cv2.resize(frame, None, fx=scale, fy=scale)
        path = f"{out_prefix}_kf{k}.jpg"
        cv2.imwrite(path, frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        paths.append(path)
    cap.release()
    return paths


def extract_evidence(output_dir, events, config, source_video=None, include_keyframes=True):
    evidence_dir = os.path.join(output_dir, "evidence")
    os.makedirs(evidence_dir, exist_ok=True)

    keyframe_source = None
    if include_keyframes:
        annotated = os.path.join(output_dir, f"annotated_{events['video']['name']}.mp4")
        keyframe_source = annotated if os.path.exists(annotated) else (source_video or events["video"].get("path"))

    max_keyframes = config["evidence"]["max_keyframes"]
    duration = events["video"]["duration_sec"]

    selected = _select_events(events, config)
    manifest = []
    for event in selected:
        start = max(0.0, event["start_sec"])
        end = min(duration, event["end_sec"])
        if end <= start:
            continue
        keyframes = []
        if include_keyframes and keyframe_source:
            span = max(end - start, 0.1)
            times = [start + span * f for f in (0.15, 0.4, 0.6, 0.85)][:max_keyframes]
            # Make sure the peak moment is included.
            if event.get("peak_sec"):
                times[len(times) // 2] = min(max(event["peak_sec"], start), end)
            keyframes = _extract_keyframes(keyframe_source, sorted(times),
                                           os.path.join(evidence_dir, event["id"]))

        manifest.append({
            **event,
            "clip": None,
            "playback_start_sec": round(start, 3),
            "playback_end_sec": round(end, 3),
            "keyframes": [os.path.relpath(p, output_dir) for p in keyframes],
        })

    manifest_path = os.path.join(output_dir, "evidence_manifest.json")
    write_json(manifest_path, {"schema_version": "1.0", "events": manifest})
    print(f"Evidence: {len(manifest)} event windows; per-event MP4 disabled")
    return manifest_path, manifest
