"""Footwork segmentation from the piste-position time series.

Segments each fencer's motion into advance / retreat / hold periods and
detects lunges (sudden ankle-spread jump with forward drive and arm
extension) with their recoveries.
"""

import numpy as np

from .timeline import SIDES, moving_average


def _segments_from_labels(t, labels, min_len_frames):
    """Turn a per-frame label array into [(label, i_start, i_end)] runs,
    dropping runs shorter than min_len_frames."""
    segments = []
    start = 0
    for i in range(1, len(labels) + 1):
        if i == len(labels) or labels[i] != labels[start]:
            if labels[start] is not None and (i - start) >= min_len_frames:
                segments.append((labels[start], start, i - 1))
            start = i
    return segments


def detect_footwork(timeline, config):
    cfg = config["footwork"]
    fps = timeline.fps
    min_len = max(2, int(cfg["min_segment_sec"] * fps))
    thr = cfg["advance_speed"]

    result = {"segments": {}, "lunges": []}

    for side in SIDES:
        fv = timeline.forward_v[side]
        labels = []
        for value in fv:
            if np.isnan(value):
                labels.append(None)
            elif value > thr:
                labels.append("advance")
            elif value < -thr:
                labels.append("retreat")
            else:
                labels.append("hold")
        runs = _segments_from_labels(timeline.t, labels, min_len)

        merged = []
        for label, i0, i1 in runs:
            if merged and merged[-1][0] == label and (i0 - merged[-1][2]) <= min_len:
                merged[-1] = (label, merged[-1][1], i1)
            else:
                merged.append((label, i0, i1))

        segments = []
        for label, i0, i1 in merged:
            seg_v = fv[i0:i1 + 1]
            seg_v = seg_v[~np.isnan(seg_v)]
            segments.append({
                "type": label,
                "start_sec": round(float(timeline.t[i0]), 3),
                "end_sec": round(float(timeline.t[i1]), 3),
                "duration_sec": round(float(timeline.t[i1] - timeline.t[i0]), 3),
                "mean_speed_ms": round(float(np.abs(seg_v).mean()), 3) if len(seg_v) else None,
                "peak_speed_ms": round(float(np.abs(seg_v).max()), 3) if len(seg_v) else None,
            })
        result["segments"][side] = segments
        result["lunges"].extend(_detect_lunges(timeline, side, cfg))

    result["lunges"].sort(key=lambda e: e["time_sec"])
    return result


def _detect_lunges(timeline, side, cfg):
    fps = timeline.fps
    spread = moving_average(timeline.ankle_spread[side], max(3, int(fps * 0.12) | 1))
    fv = timeline.forward_v[side]
    elbow = timeline.elbow_angle[side]
    window = max(2, int(cfg["lunge_window_sec"] * fps))
    jump_thr = cfg["lunge_spread_jump"]
    refractory = int(fps * 1.0)

    lunges = []
    last_end = -refractory
    n = timeline.n_frames
    for i in range(window, n):
        if i - last_end < refractory:
            continue
        base = spread[i - window]
        now = spread[i]
        if np.isnan(base) or np.isnan(now):
            continue
        if now - base < jump_thr:
            continue
        # Forward drive during the jump window.
        drive = fv[i - window:i + 1]
        drive = drive[~np.isnan(drive)]
        if len(drive) == 0 or drive.max() < cfg["advance_speed"]:
            continue
        # Arm extension near the spread peak (lunges come with an extended arm).
        arm = elbow[max(0, i - window):min(n, i + window)]
        arm = arm[~np.isnan(arm)]
        extended = len(arm) > 0 and arm.max() >= cfg["lunge_min_elbow_deg"]
        # A wide step alone is common during ordinary advance/recovery.  Require
        # a pose-confirmed weapon arm for a lunge candidate.
        if not extended:
            continue

        # Find the local spread peak to time-stamp the lunge.
        peak_i = i
        while peak_i + 1 < n and not np.isnan(spread[peak_i + 1]) and spread[peak_i + 1] >= spread[peak_i]:
            peak_i += 1

        # Recovery: spread returns below base + 40% of the jump.
        recovery_sec = None
        recover_level = base + 0.4 * (spread[peak_i] - base)
        for j in range(peak_i, min(n, peak_i + int(fps * 2.0))):
            if not np.isnan(spread[j]) and spread[j] <= recover_level:
                recovery_sec = round(float(timeline.t[j]), 3)
                break

        drive_duration = float(np.mean(drive >= cfg["advance_speed"])) if len(drive) else 0.0
        confidence = 0.58 + min((now - base - jump_thr) * 0.45, 0.20) + min(drive_duration * 0.18, 0.18)
        lunges.append({
            "fencer": side,
            "time_sec": round(float(timeline.t[peak_i]), 3),
            "start_sec": round(float(timeline.t[max(0, i - window)]), 3),
            "spread_m": round(float(spread[peak_i]), 3),
            "spread_jump_m": round(float(now - base), 3),
            "arm_extended": bool(extended),
            "forward_drive_ratio": round(drive_duration, 2),
            "recovery_sec": recovery_sec,
            "confidence": round(min(confidence, 1.0), 2),
        })
        last_end = peak_i
    return lunges


def footwork_stats(footwork, side):
    segments = footwork["segments"].get(side, [])
    lunges = [l for l in footwork["lunges"] if l["fencer"] == side]
    advances = [s for s in segments if s["type"] == "advance"]
    retreats = [s for s in segments if s["type"] == "retreat"]
    return {
        "advance_count": len(advances),
        "retreat_count": len(retreats),
        "advance_time_sec": round(sum(s["duration_sec"] for s in advances), 2),
        "retreat_time_sec": round(sum(s["duration_sec"] for s in retreats), 2),
        "lunge_count": len(lunges),
        "peak_speed_ms": max((s["peak_speed_ms"] or 0 for s in segments), default=0),
    }
