"""Reaction time estimation.

For every clear movement onset of fencer A (after a quiet period), find
fencer B's first significant response — a footwork velocity change or a
wrist-speed spike — and report the latency.
"""

import numpy as np

from .timeline import SIDES


def _movement_onsets(forward_v, fps, onset_speed, quiet_sec=0.4):
    quiet_frames = int(quiet_sec * fps)
    onsets = []
    below_count = quiet_frames  # start eligible
    for i, value in enumerate(forward_v):
        if np.isnan(value):
            continue
        if abs(value) < onset_speed * 0.5:
            below_count += 1
        elif value >= onset_speed:
            if below_count >= quiet_frames:
                onsets.append(i)
            below_count = 0
        else:
            below_count = 0
    return onsets


def detect_reactions(timeline, config):
    cfg = config["reaction"]
    fps = timeline.fps
    window = int(cfg["response_window_sec"] * fps)
    min_frames = max(2, int(round(cfg["min_reaction_sec"] * fps)))

    reactions = []
    for stim_side in SIDES:
        resp_side = "right" if stim_side == "left" else "left"
        onsets = _movement_onsets(timeline.forward_v[stim_side], fps, cfg["onset_speed"])

        resp_fv = timeline.forward_v[resp_side]
        wrist_speed = timeline.wrist_speed_img[resp_side]
        wrist_med = np.nanmedian(wrist_speed)
        wrist_thr = wrist_med * 2.5 if not np.isnan(wrist_med) else np.inf

        for onset_i in onsets:
            response_i = None
            response_kind = None
            for j in range(onset_i + min_frames, min(timeline.n_frames, onset_i + window)):
                fv_j = resp_fv[j]
                if not np.isnan(fv_j) and abs(fv_j) >= cfg["onset_speed"]:
                    response_i, response_kind = j, "footwork"
                    break
                ws_j = wrist_speed[j]
                if not np.isnan(ws_j) and ws_j >= wrist_thr:
                    response_i, response_kind = j, "blade"
                    break
            if response_i is None:
                continue
            if timeline.t[response_i] - timeline.t[onset_i] < cfg["min_reaction_sec"]:
                continue
            reactions.append({
                "stimulus_fencer": stim_side,
                "responder": resp_side,
                "stimulus_sec": round(float(timeline.t[onset_i]), 3),
                "response_sec": round(float(timeline.t[response_i]), 3),
                "reaction_time_sec": round(float(timeline.t[response_i] - timeline.t[onset_i]), 3),
                "response_kind": response_kind,
            })

    reactions.sort(key=lambda r: r["stimulus_sec"])
    return reactions


def reaction_stats(reactions, responder):
    times = [r["reaction_time_sec"] for r in reactions if r["responder"] == responder]
    if not times:
        return {"count": 0}
    arr = np.array(times)
    return {
        "count": len(times),
        "mean_sec": round(float(arr.mean()), 3),
        "median_sec": round(float(np.median(arr)), 3),
        "best_sec": round(float(arr.min()), 3),
        "worst_sec": round(float(arr.max()), 3),
    }
