"""Fencer style (打法) profiling — deep tactical version.

Layers (all aggregate statistics, robust to per-event noise):
  1. Five normalized dimensions + archetype label (radar chart)
  2. Interaction matrix   — how B responds while A advances (retreat/hold/press)
  3. Distance authority   — who drives closing / opening of the distance
  4. Attack context       — distance & opponent state at each attack onset
  5. Temporal evolution   — aggression/tempo drift across match thirds
  6. Burst rhythm         — explosive-bout frequency, duration, direction changes
  7. Phrase tactics       — per-phrase initiative and ground gained/lost
"""

import numpy as np

from .timeline import SIDES

STYLE_LABELS = [
    ("进攻压迫型", lambda p: p["aggression"] >= 0.6 and p["territory"] >= 0.55),
    ("防守反击型", lambda p: p["aggression"] <= 0.4 and p["counter_ratio"] >= 0.4),
    ("机动控距型", lambda p: p["distance"] <= 0.4 and p["tempo"] >= 0.5),
    ("稳健均衡型", lambda p: True),
]

ADV_THR = 0.35  # m/s — same threshold family as footwork segmentation


def _clip01(x):
    return float(np.clip(x, 0.0, 1.0))


def _pct(x):
    return round(float(x) * 100, 1)


def _phrase_slices(timeline, events):
    for ph in events.get("phrases", []):
        i0 = max(0, int(ph["start_sec"] * timeline.fps) - 1)
        i1 = min(timeline.n_frames, int(ph["end_sec"] * timeline.fps))
        if i1 > i0:
            yield ph, i0, i1


def _forward(timeline, side):
    return timeline.forward_v[side]


# ------------------------------------------------------------------ layer 2
def interaction_matrix(timeline):
    """While A advances, what is B doing? Percentages over A's advancing frames."""
    out = {}
    for a in SIDES:
        b = "right" if a == "left" else "left"
        fa, fb = _forward(timeline, a), _forward(timeline, b)
        mask = (~np.isnan(fa)) & (fa > ADV_THR) & (~np.isnan(fb))
        n = int(mask.sum())
        if n < timeline.fps:  # under 1s of joint data — not meaningful
            out[a] = None
            continue
        fb_m = fb[mask]
        out[a] = {
            "frames_sec": round(n / timeline.fps, 1),
            "opponent_retreats": _pct((fb_m < -ADV_THR).mean()),
            "opponent_holds": _pct((np.abs(fb_m) <= ADV_THR).mean()),
            "opponent_presses_back": _pct((fb_m > ADV_THR).mean()),
        }
    return out


# ------------------------------------------------------------------ layer 3
def distance_authority(timeline):
    """Decompose distance change into each fencer's contribution.

    distance = x_right − x_left, so d(dist) = v_right − v_left.
    While the gap is CLOSING, the closer's share = own forward speed over the
    combined closing speed. Symmetric for opening (retreat-driven)."""
    vl, vr = timeline.v["left"], timeline.v["right"]
    valid = (~np.isnan(vl)) & (~np.isnan(vr))
    ddist = vr - vl
    closing = valid & (ddist < -0.15)
    opening = valid & (ddist > 0.15)

    def share(mask, own_contrib):
        if mask.sum() < timeline.fps * 0.5:
            return None
        contrib = own_contrib[mask]
        total = np.abs(ddist[mask])
        return _pct(np.clip(contrib, 0, None).sum() / (total.sum() + 1e-9))

    return {
        "closing_time_sec": round(float(closing.sum()) / timeline.fps, 1),
        "opening_time_sec": round(float(opening.sum()) / timeline.fps, 1),
        # who eats the distance when it shrinks
        "closing_drive": {"left": share(closing, vl), "right": share(closing, -vr)},
        # who creates the distance when it grows
        "opening_drive": {"left": share(opening, -vl), "right": share(opening, vr)},
    }


# ------------------------------------------------------------------ layer 4
def attack_context(timeline, events, side):
    """Situation at each attack onset for one fencer."""
    opp = "right" if side == "left" else "left"
    fo = _forward(timeline, opp)
    contexts, distances = [], []
    for act in events.get("actions", []):
        if act["fencer"] != side or act["type"] != "attack":
            continue
        i = min(timeline.n_frames - 1, int(act["start_sec"] * timeline.fps))
        d = timeline.distance_smooth[i]
        if not np.isnan(d):
            distances.append(float(d))
        o = fo[i]
        if np.isnan(o):
            contexts.append("unknown")
        elif o > ADV_THR:
            contexts.append("into_advance")   # 对手前进中 -> 抢攻/对攻
        elif o < -ADV_THR:
            contexts.append("on_retreat")     # 对手后退中 -> 追击
        else:
            contexts.append("on_static")      # 对手静止 -> 主动发起
    n = len(contexts)
    if n == 0:
        return {"count": 0}
    return {
        "count": n,
        "mean_attack_distance_m": round(float(np.mean(distances)), 2) if distances else None,
        "into_opponent_advance": _pct(contexts.count("into_advance") / n),
        "on_opponent_retreat": _pct(contexts.count("on_retreat") / n),
        "on_opponent_static": _pct(contexts.count("on_static") / n),
    }


# ------------------------------------------------------------------ layer 5
def temporal_evolution(timeline, events, side):
    """Aggression / tempo / attack-rate across match thirds."""
    n = timeline.n_frames
    fv = _forward(timeline, side)
    segments = []
    for k in range(3):
        i0, i1 = n * k // 3, n * (k + 1) // 3
        t0, t1 = timeline.t[i0], timeline.t[min(i1, n - 1)]
        seg = fv[i0:i1]
        seg = seg[~np.isnan(seg)]
        atk = sum(1 for a in events.get("actions", [])
                  if a["fencer"] == side and a["type"] == "attack"
                  and t0 <= a["start_sec"] < t1)
        minutes = max((t1 - t0) / 60.0, 1e-6)
        segments.append({
            "third": k + 1,
            "advance_ratio": _pct((seg > ADV_THR).mean()) if len(seg) else None,
            "activity_ratio": _pct((np.abs(seg) > 0.25).mean()) if len(seg) else None,
            "mean_abs_speed": round(float(np.abs(seg).mean()), 2) if len(seg) else None,
            "attacks_per_min": round(atk / minutes, 1),
        })
    drift = None
    first, last = segments[0], segments[-1]
    if first["mean_abs_speed"] and last["mean_abs_speed"]:
        drift = round((last["mean_abs_speed"] - first["mean_abs_speed"])
                      / first["mean_abs_speed"] * 100, 1)
    return {"thirds": segments, "speed_drift_pct": drift}


# ------------------------------------------------------------------ layer 6
def burst_rhythm(timeline, side):
    """Explosive bouts and direction changes — the movement fingerprint."""
    fv = _forward(timeline, side)
    fps = timeline.fps
    active = (~np.isnan(fv)) & (np.abs(fv) > ADV_THR)

    bursts = []
    start = None
    for i, flag in enumerate(active):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            if i - start >= fps * 0.2:
                seg = np.abs(fv[start:i])
                bursts.append((i - start, float(np.nanmax(seg))))
            start = None
    total_min = max(timeline.t[-1] / 60.0, 1e-6) if timeline.n_frames else 1e-6

    # direction changes with hysteresis (advance <-> retreat flips)
    state, flips = 0, 0
    for value in fv:
        if np.isnan(value):
            continue
        new = 1 if value > ADV_THR else (-1 if value < -ADV_THR else 0)
        if new != 0 and state != 0 and new != state:
            flips += 1
        if new != 0:
            state = new
    explosive = [b for b in bursts if b[1] > 1.2]
    return {
        "bursts_per_min": round(len(bursts) / total_min, 1),
        "mean_burst_sec": round(float(np.mean([b[0] for b in bursts])) / fps, 2) if bursts else None,
        "peak_burst_speed": round(max((b[1] for b in bursts), default=0.0), 2),
        "explosive_burst_share": _pct(len(explosive) / len(bursts)) if bursts else None,
        "direction_changes_per_min": round(flips / total_min, 1),
    }


# ------------------------------------------------------------------ layer 7
def phrase_tactics(timeline, events):
    """Per-phrase initiative and ground gained, then per-fencer aggregates."""
    onset_thr = ADV_THR
    per_fencer = {s: {"initiated": 0, "ground_sum": 0.0, "press": 0, "yield": 0, "even": 0}
                  for s in SIDES}
    n_phrases = 0
    for _ph, i0, i1 in _phrase_slices(timeline, events):
        n_phrases += 1
        first = {}
        for side in SIDES:
            fv = _forward(timeline, side)[i0:i1]
            idx = np.where((~np.isnan(fv)) & (fv >= onset_thr))[0]
            if len(idx):
                first[side] = idx[0]
        initiator = min(first, key=first.get) if len(first) == 2 and first["left"] != first["right"] \
            else (next(iter(first)) if len(first) == 1 else None)
        if initiator:
            per_fencer[initiator]["initiated"] += 1
        for side in SIDES:
            x = timeline.x[side][i0:i1]
            x = x[~np.isnan(x)]
            if len(x) < 2:
                continue
            gained = float(x[-1] - x[0]) * (1 if side == "left" else -1)
            per_fencer[side]["ground_sum"] += gained
            if gained > 0.5:
                per_fencer[side]["press"] += 1
            elif gained < -0.5:
                per_fencer[side]["yield"] += 1
            else:
                per_fencer[side]["even"] += 1
    out = {"n_phrases": n_phrases}
    for side in SIDES:
        d = per_fencer[side]
        out[side] = {
            "phrases_initiated": d["initiated"],
            "initiative_rate": _pct(d["initiated"] / n_phrases) if n_phrases else None,
            "net_ground_m": round(d["ground_sum"], 2),
            "pressing_phrases": d["press"],
            "yielding_phrases": d["yield"],
            "even_phrases": d["even"],
        }
    return out


# ------------------------------------------------------------------ layer 1 (base dims)
def _base_profile(timeline, events, side, phrase_time, first_moves, total_first, config):
    stats = events["stats"]
    footwork = events["footwork"]
    opp = "right" if side == "left" else "left"
    fw = stats[side]["footwork"]
    atk = stats[side]["attack_count"]
    dfn = stats[side]["defense_count"]
    lunges = [l for l in footwork["lunges"] if l["fencer"] == side]
    center = timeline.piste_length / 2.0
    half = timeline.piste_length / 2.0

    adv, ret = fw["advance_time_sec"], fw["retreat_time_sec"]
    adv_ratio = adv / (adv + ret) if (adv + ret) > 0 else 0.5
    first_ratio = first_moves[side] / total_first
    atk_total = atk + stats[opp]["attack_count"]
    atk_share = atk / atk_total if atk_total else 0.5
    aggression = _clip01(0.4 * adv_ratio + 0.35 * first_ratio + 0.25 * atk_share)

    x = timeline.x[side]
    x = x[~np.isnan(x)]
    if len(x):
        scale = timeline.piste_length / 14.0
        en_garde = center - 2.0 * scale if side == "left" else center + 2.0 * scale
        span = half + 2.0 * scale
        push = (np.mean(x) - en_garde) / span if side == "left" else (en_garde - np.mean(x)) / span
        territory = _clip01(0.5 + push)
        beyond_center = float(np.mean(x > center)) if side == "left" else float(np.mean(x < center))
    else:
        territory, beyond_center = 0.5, 0.0

    fv = _forward(timeline, side)
    active = np.nansum(np.abs(fv) > config["phrase"]["activity_speed"]) / timeline.fps
    tempo = _clip01(active / phrase_time)

    dist = timeline.distance_smooth
    dvalid = dist[~np.isnan(dist)]
    mean_dist = float(np.mean(dvalid)) if len(dvalid) else np.nan
    distance_pref = _clip01(1.0 - (mean_dist - 1.5) / 3.5) if not np.isnan(mean_dist) else 0.5

    lunge_rate = len(lunges) / (phrase_time / 60.0) if phrase_time else 0.0
    recoveries = [l["recovery_sec"] - l["time_sec"] for l in lunges
                  if l.get("recovery_sec") is not None]
    spreads = [l["spread_m"] for l in lunges if l.get("spread_m")]
    mean_recovery = float(np.mean(recoveries)) if recoveries else None
    recovery_score = _clip01(1.0 - (mean_recovery - 0.4) / 1.2) if mean_recovery else 0.5
    technique = _clip01(0.5 * _clip01(lunge_rate / 8.0) + 0.5 * recovery_score)

    counter_ratio = dfn / (atk + dfn) if (atk + dfn) else 0.0

    profile = {
        "aggression": round(aggression, 3),
        "territory": round(territory, 3),
        "tempo": round(tempo, 3),
        "distance": round(distance_pref, 3),
        "technique": round(technique, 3),
        "counter_ratio": round(counter_ratio, 3),
        "detail": {
            "advance_time_ratio": round(adv_ratio, 3),
            "first_move_ratio": round(first_ratio, 3),
            "attack_share": round(atk_share, 3),
            "mean_position_m": round(float(np.mean(x)), 2) if len(x) else None,
            "time_beyond_center": round(beyond_center, 3),
            "mean_distance_m": round(mean_dist, 2) if not np.isnan(mean_dist) else None,
            "lunges_per_min": round(lunge_rate, 2),
            "mean_lunge_recovery_sec": round(mean_recovery, 2) if mean_recovery else None,
            "lunge_recovery_p75_sec": round(float(np.percentile(recoveries, 75)), 2) if recoveries else None,
            "lunge_spread_p50_m": round(float(np.median(spreads)), 2) if spreads else None,
            "lunge_quality_rate": _pct(np.mean([r < 0.8 for r in recoveries])) if recoveries else None,
            "phrases_first_move": first_moves[side],
        },
    }
    for label, cond in STYLE_LABELS:
        if cond(profile):
            profile["style_label"] = label
            break
    return profile


def _first_mover_counts(timeline, events, onset_speed):
    counts = {s: 0 for s in SIDES}
    for _ph, i0, i1 in _phrase_slices(timeline, events):
        first = {}
        for side in SIDES:
            fv = _forward(timeline, side)[i0:i1]
            idx = np.where((~np.isnan(fv)) & (fv >= onset_speed))[0]
            if len(idx):
                first[side] = idx[0]
        if len(first) == 2 and first["left"] != first["right"]:
            counts[min(first, key=first.get)] += 1
        elif len(first) == 1:
            counts[next(iter(first))] += 1
    return counts


def _tactical_reading(profiles, interaction, authority, phrase_t, attack_ctx):
    """Compact Chinese head-to-head interpretation, grounded in the numbers."""
    l, r = profiles["left"], profiles["right"]
    lines = [
        f"左方[{l['style_label']}] vs 右方[{r['style_label']}]。"
    ]
    lp, rp = phrase_t.get("left", {}), phrase_t.get("right", {})
    if lp.get("initiative_rate") is not None:
        lead = "左方" if (lp["initiative_rate"] or 0) >= (rp["initiative_rate"] or 0) else "右方"
        lines.append(f"回合发起权:左 {lp['initiative_rate']}% / 右 {rp['initiative_rate']}%,{lead}更主动;"
                     f"净得地 左 {lp['net_ground_m']}m / 右 {rp['net_ground_m']}m。")
    for side, zh in (("left", "左方"), ("right", "右方")):
        im = interaction.get(side)
        if im:
            lines.append(f"{zh}前进时,对手 {im['opponent_retreats']}% 后退、"
                         f"{im['opponent_holds']}% 站住、{im['opponent_presses_back']}% 对进。")
    cd = authority.get("closing_drive", {})
    if cd.get("left") is not None and cd.get("right") is not None:
        driver = "左方" if cd["left"] >= cd["right"] else "右方"
        lines.append(f"距离合拢主要由{driver}驱动(左 {cd['left']}% / 右 {cd['right']}%)。")
    for side, zh in (("left", "左方"), ("right", "右方")):
        ac = attack_ctx.get(side, {})
        if ac.get("count"):
            lines.append(f"{zh}进攻情境:抢攻 {ac['into_opponent_advance']}% / "
                         f"追击 {ac['on_opponent_retreat']}% / 主动发起 {ac['on_opponent_static']}%,"
                         f"平均出手距离 {ac['mean_attack_distance_m']}m。")
    return " ".join(lines)


def analyze_style(timeline, events, config):
    phrases = events.get("phrases", [])
    total_time = max(events["video"]["duration_sec"], 1e-6)
    phrase_time = sum(p["duration_sec"] for p in phrases) or total_time

    first_moves = _first_mover_counts(timeline, events, config["reaction"]["onset_speed"])
    total_first = sum(first_moves.values()) or 1

    profiles = {side: _base_profile(timeline, events, side, phrase_time,
                                    first_moves, total_first, config)
                for side in SIDES}

    interaction = interaction_matrix(timeline)
    authority = distance_authority(timeline)
    attack_ctx = {side: attack_context(timeline, events, side) for side in SIDES}
    evolution = {side: temporal_evolution(timeline, events, side) for side in SIDES}
    rhythm = {side: burst_rhythm(timeline, side) for side in SIDES}
    phrase_t = phrase_tactics(timeline, events)

    l, r = profiles["left"], profiles["right"]
    comparison = {
        "initiative": "left" if l["aggression"] > r["aggression"] else "right",
        "territory_control": "left" if l["territory"] > r["territory"] else "right",
        "aggression_gap": round(abs(l["aggression"] - r["aggression"]), 3),
        "summary": _tactical_reading(profiles, interaction, authority, phrase_t, attack_ctx),
    }
    return {
        "profiles": profiles,
        "interaction": interaction,
        "distance_authority": authority,
        "attack_context": attack_ctx,
        "evolution": evolution,
        "rhythm": rhythm,
        "phrase_tactics": phrase_t,
        "comparison": comparison,
    }
