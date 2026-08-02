"""Pose-constrained attack, parry and counter candidates.

The classifier deliberately requires a temporal relation between arm extension,
forward/retreat footwork, distance change and the opponent's action.  This is
more conservative than frame-level wrist-speed thresholds and therefore
reduces false attacks caused by pose jitter or a non-fencing hand movement.
"""

import numpy as np

from .timeline import SIDES


def _valid(values):
    return values[~np.isnan(values)]


def _coverage(values):
    return float(np.mean(~np.isnan(values))) if len(values) else 0.0


def _peak(values, default=np.nan):
    values = _valid(values)
    return float(values.max()) if len(values) else default


def _median(values, default=np.nan):
    values = _valid(values)
    return float(np.median(values)) if len(values) else default


def _rising_edges(series, threshold):
    edges, below = [], True
    for i, value in enumerate(series):
        if np.isnan(value):
            continue
        if value >= threshold and below:
            edges.append(i)
            below = False
        elif value < threshold:
            below = True
    return edges


def _nearest_lunge(lunges, sec, tolerance=0.55):
    choices = [l for l in lunges if abs(float(l["time_sec"]) - sec) <= tolerance]
    return min(choices, key=lambda l: abs(float(l["time_sec"]) - sec)) if choices else None


def _dedupe(actions, min_gap):
    kept = []
    for action in sorted(actions, key=lambda a: (-a["confidence"], a["start_sec"])):
        if any(action["fencer"] == old["fencer"] and action["type"] == old["type"]
               and abs(action["start_sec"] - old["start_sec"]) < min_gap for old in kept):
            continue
        kept.append(action)
    return sorted(kept, key=lambda a: a["start_sec"])


def detect_actions(timeline, footwork, config):
    cfg = config["actions"]
    fps, n = max(1, int(round(timeline.fps))), timeline.n_frames
    min_gap = int(cfg["min_gap_sec"] * fps)
    attack_window = max(2, int(cfg.get("attack_window_sec", 0.45) * fps))
    ext_threshold = cfg["extension_elbow_deg"]
    min_extension_gain = cfg.get("min_extension_gain_deg", 16.0)
    attacks = []
    lunges_by_side = {side: [l for l in footwork["lunges"] if l["fencer"] == side] for side in SIDES}

    # An attack needs deliberate arm extension plus at least one lower-body or
    # distance cue.  A held-out straight arm is not enough.
    for side in SIDES:
        elbow, forward_v = timeline.elbow_angle[side], timeline.forward_v[side]
        for i in _rising_edges(elbow, ext_threshold):
            lo, hi = max(0, i - attack_window), min(n, i + attack_window + 1)
            before = _median(elbow[lo:i], default=ext_threshold)
            after = _peak(elbow[i:hi])
            extension_gain = after - before if not np.isnan(after) else 0.0
            drive = _peak(forward_v[lo:hi], default=0.0)
            lunge = _nearest_lunge(lunges_by_side[side], float(timeline.t[i]))
            closing = _peak(timeline.closing_speed[lo:hi], default=0.0)
            distance = _median(timeline.distance_smooth[lo:hi])

            if extension_gain < min_extension_gain:
                continue
            forward = drive >= cfg["attack_min_speed"]
            closing_ok = closing >= cfg.get("attack_min_closing_speed", 0.12)
            if not (forward or lunge or closing_ok):
                continue

            # Blade-tip evidence corroborates the elbow-angle proxy: a genuine
            # thrust shows the tip itself moving away from the wrist. Used as
            # a soft score adjustment (not a gate) since detector coverage is
            # partial and quiet-period jitter overlaps the low end of this
            # signal too much to safely reject on it alone.
            tip_reach = timeline.tip_reach_img[side][lo:hi]
            tip_coverage = _coverage(tip_reach)
            tip_reach_gain = 0.0
            if tip_coverage >= cfg.get("tip_min_coverage", 0.35):
                valid_reach = _valid(tip_reach)
                tip_reach_gain = float(valid_reach.max() - valid_reach.min())

            score = 0.42
            score += min(0.20, extension_gain / 90.0)
            score += 0.18 if forward else 0.0
            score += 0.20 if lunge else 0.0
            score += 0.10 if closing_ok else 0.0
            if tip_coverage >= cfg.get("tip_min_coverage", 0.35):
                score += min(0.08, tip_reach_gain / cfg.get("attack_tip_reach_boost_px", 60.0) * 0.08)
            end_i = min(n - 1, i + attack_window)
            attacks.append({
                "fencer": side, "type": "attack",
                "start_sec": round(float(timeline.t[i]), 3),
                "end_sec": round(float(timeline.t[end_i]), 3),
                "confidence": round(min(score, 0.98), 2),
                "features": {
                    "pose_extension_gain_deg": round(float(extension_gain), 1),
                    "elbow_peak_deg": round(float(after), 1),
                    "with_lunge": bool(lunge), "forward_drive": bool(forward),
                    "closing_distance": bool(closing_ok),
                    "peak_forward_speed_ms": round(float(drive), 3),
                    "distance_m": round(float(distance), 2) if not np.isnan(distance) else None,
                    "tip_reach_gain_px": round(tip_reach_gain, 1) if tip_coverage >= cfg.get("tip_min_coverage", 0.35) else None,
                },
            })
    attacks = _dedupe(attacks, cfg["min_gap_sec"])

    defenses = []
    response_window = int(cfg.get("defense_window_sec", 0.75) * fps)
    min_delay = int(cfg.get("min_counter_delay_sec", 0.10) * fps)
    for attack in attacks:
        side = "right" if attack["fencer"] == "left" else "left"
        i0 = max(0, int(round(attack["start_sec"] * fps)) - 1)
        i1 = min(n, i0 + response_window)
        wrist_speed = timeline.wrist_speed_img[side]
        baseline = _median(wrist_speed[max(0, i0 - fps):i0], default=np.nan)
        if np.isnan(baseline):
            baseline = _median(wrist_speed, default=np.nan)
        if np.isnan(baseline) or baseline <= 0:
            continue
        wrist_thr = max(baseline * cfg.get("defense_wrist_multiplier", 2.1), 1e-3)

        response_i = None
        for j in range(i0 + min_delay, i1):
            if not np.isnan(wrist_speed[j]) and wrist_speed[j] >= wrist_thr:
                response_i = j
                break
        if response_i is None:
            continue

        pose_lo = max(0, response_i - int(0.2 * fps))
        pose_hi = min(n, response_i + int(0.3 * fps))
        elbow = timeline.elbow_angle[side]
        extension_gain = _peak(elbow[response_i:pose_hi], default=0.0) - _median(elbow[pose_lo:response_i], default=0.0)
        forward_drive = _peak(timeline.forward_v[side][response_i:pose_hi], default=0.0)
        retreat_drive = -_median(timeline.forward_v[side][pose_lo:pose_hi], default=0.0)
        lunge = _nearest_lunge(lunges_by_side[side], float(timeline.t[response_i]), tolerance=0.45)

        # Counter/riposte demands a distinct return initiative: arm re-extension
        # or forward/lunge drive after the opponent's attack. Otherwise it is a
        # parry/defensive blade response.
        counter = (extension_gain >= min_extension_gain * 0.65 and forward_drive >= cfg["attack_min_speed"] * 0.65) or bool(lunge)

        # Blade-tip forward speed is a more direct offense/defense cue than
        # elbow re-extension: a point-in-line riposte from an already-extended
        # arm shows little extension_gain but a clear forward tip drive, which
        # the pose-only heuristic above would miss. Calibrated against real
        # detections.jsonl (median tip-forward-speed peak: attack ~6.5 m/s,
        # counter ~5.3 m/s, parry ~3.9 m/s).
        tip_fwd_window = timeline.tip_forward_v[side][response_i:pose_hi]
        tip_coverage = _coverage(tip_fwd_window)
        tip_fwd_peak = _peak(tip_fwd_window, default=np.nan)
        tip_trusted = tip_coverage >= cfg.get("tip_min_coverage", 0.35)
        if tip_trusted and not counter and tip_fwd_peak >= cfg.get("defense_tip_strong_counter_speed", 6.0):
            counter = True

        action_type = "counter" if counter else "parry"
        score = 0.43 + min(0.24, wrist_speed[response_i] / (wrist_thr * 4))
        score += 0.18 if counter else 0.0
        score += 0.10 if retreat_drive >= cfg.get("defense_retreat_speed", 0.25) else 0.0
        if tip_trusted:
            agrees = (tip_fwd_peak >= cfg.get("defense_tip_counter_speed", 4.5)) == counter
            score += 0.05 if agrees else -0.05
        end_i = min(n - 1, response_i + int(0.35 * fps))
        defenses.append({
            "fencer": side, "type": action_type,
            "start_sec": round(float(timeline.t[response_i]), 3),
            "end_sec": round(float(timeline.t[end_i]), 3),
            "confidence": round(min(score, 0.96), 2),
            "features": {
                "against_attack_of": attack["fencer"],
                "against_attack_id": attack.get("id"),
                "response_delay_sec": round(float(timeline.t[response_i] - timeline.t[i0]), 3),
                "wrist_speed_spike": round(float(wrist_speed[response_i]), 1),
                "wrist_threshold": round(float(wrist_thr), 1),
                "pose_extension_gain_deg": round(float(extension_gain), 1),
                "forward_drive": round(float(forward_drive), 3),
                "retreating": bool(retreat_drive >= cfg.get("defense_retreat_speed", 0.25)),
                "tip_forward_speed_peak_ms": round(float(tip_fwd_peak), 3) if tip_trusted else None,
            },
        })

    actions = _dedupe(attacks + defenses, cfg["min_gap_sec"])
    for idx, action in enumerate(actions):
        action["id"] = f"act_{idx:03d}"
    # Back-fill the parent id now that action ids are stable.
    attack_by_time = {(a["fencer"], a["start_sec"]): a["id"] for a in actions if a["type"] == "attack"}
    for action in actions:
        parent = action.get("features", {}).get("against_attack_of")
        if parent:
            opponent_start = min((a["start_sec"] for a in actions if a["type"] == "attack" and a["fencer"] == parent
                                  and a["start_sec"] <= action["start_sec"]), default=None)
            if opponent_start is not None:
                action["features"]["against_attack_id"] = attack_by_time.get((parent, opponent_start))
    return actions
