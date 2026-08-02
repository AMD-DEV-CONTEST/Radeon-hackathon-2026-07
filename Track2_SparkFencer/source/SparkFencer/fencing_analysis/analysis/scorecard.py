"""Single-bout scorecard built from SparkFencer's measured event data.

Metrics deliberately preserve their units and confidence limits.  In
particular, blade motion is measured in image pixels per second because a tip
does not lie on the piste plane and cannot honestly be converted to m/s from
the current camera calibration alone.
"""

from __future__ import annotations

import numpy as np

SIDES = ("left", "right")
SIDE_LABEL = {
    "zh": {"left": "左方剑手", "right": "右方剑手"},
    "en": {"left": "Left fencer", "right": "Right fencer"},
}
MEASUREMENT_NOTE = {
    "zh": "剑尖速度单位为 px/s；峰值采用高置信相邻帧速度的 P95，以降低单帧跳点影响。攻防转化基于规则候选，需结合证据视频复核。",
    "en": "Blade-tip speed is in px/s; the peak uses the P95 of high-confidence adjacent-frame speeds to limit "
          "single-frame jitter. Attack/defense conversion is based on rule-based candidates and should be "
          "cross-checked against the evidence video.",
}
INSUFFICIENT_SAMPLE = {"zh": "样本不足", "en": "insufficient samples"}


def blade_metrics(timeline, side):
    """High-confidence trajectory continuity and robust peak tip speed."""
    points = timeline.tip_img[side]
    confidence = timeline.tip_conf[side]
    valid = (confidence > 0.2) & ~np.isnan(points).any(axis=1)
    coverage = float(valid.mean()) if len(valid) else 0.0
    adjacent = valid[1:] & valid[:-1]
    continuity = float(adjacent.mean()) if len(adjacent) else 0.0
    speeds = []
    for index in np.where(adjacent)[0] + 1:
        speed = float(np.linalg.norm(points[index] - points[index - 1]) / timeline.dt)
        # Ignore impossible single-frame jumps, which are almost always an
        # association error rather than sword velocity.
        if speed <= 5000:
            speeds.append(speed)
    # P95 is a robust "peak" resistant to one imperfect tracked frame.
    peak = float(np.percentile(speeds, 95)) if speeds else None
    # Stability describes tracking continuity, not an aesthetic claim that a
    # real attacking blade should move slowly or in a straight line.
    stability = 100.0 * (0.55 * coverage + 0.45 * continuity)
    return {
        "tip_detection_rate": round(coverage, 3),
        "trajectory_continuity": round(continuity, 3),
        "trajectory_stability": round(stability, 1),
        "peak_tip_speed_px_s": round(peak, 1) if peak is not None else None,
        "speed_sample_count": len(speeds),
    }


def _defense_conversion(actions, side):
    opponent = "right" if side == "left" else "left"
    opponent_attacks = [a for a in actions if a.get("fencer") == opponent and a.get("type") == "attack"]
    responses = [a for a in actions if a.get("fencer") == side and a.get("type") in ("parry", "counter")]
    # The action detector creates a defense in the window of a known opposing
    # attack.  Match by that explicit origin first, then time as a fallback.
    covered = set()
    for response in responses:
        target = response.get("features", {}).get("against_attack_of")
        if target != opponent:
            continue
        for index, attack in enumerate(opponent_attacks):
            if index not in covered and abs(attack["start_sec"] - response["start_sec"]) <= 0.8:
                covered.add(index)
                break
    attempted = len(opponent_attacks)
    return {
        "opponent_attack_candidates": attempted,
        "defensive_response_candidates": len(covered),
        "rate": round(len(covered) / attempted, 3) if attempted else None,
    }


def _improvements(events, side, blade, conversion, lang):
    stats = events["stats"][side]
    footwork = stats["footwork"]
    reaction = stats["reaction"]
    style = (events.get("style") or {}).get("profiles", {}).get(side, {}).get("detail", {})
    candidates = []
    if blade["trajectory_stability"] < 70:
        if lang == "en":
            candidates.append((86, "Improve blade-tip trajectory continuity",
                               "Continuity of high-confidence trajectory is low, with frequent breaks or jumps "
                               "during fast actions.",
                               "Run 3 sets of stationary lunge drills, 10 reps each, keeping the guard-to-tip path "
                               "continuous with a stable end point."))
        else:
            candidates.append((86, "提高剑尖轨迹连续度", "高置信轨迹的连续度偏低，快速动作中存在较多断点或跳点。",
                               "进行 3 组直刺定点训练；每组 10 次，要求护手至剑尖路径连续且终点稳定。"))
    if reaction.get("median_sec") is not None and reaction["median_sec"] > 0.45:
        if lang == "en":
            candidates.append((92, "Shorten reaction onset time",
                               f"Median reaction time is {reaction['median_sec']}s, showing noticeable delay in "
                               f"this sample.",
                               "Do 5 sets of cue-and-recover reaction drills (verbal/light), 6 reps each; record "
                               "fastest and median reaction."))
        else:
            candidates.append((92, "缩短反应启动时间", f"反应时间中位数为 {reaction['median_sec']}s，当前样本中仍有明显延迟。",
                               "用口令/灯光刺激做 5 组反应-还原练习，每组 6 次，记录最快与中位反应。"))
    if conversion["rate"] is not None and conversion["rate"] < 0.5 and conversion["opponent_attack_candidates"] >= 2:
        if lang == "en":
            candidates.append((88, "Improve defensive conversion after opponent attacks",
                               f"Of the opponent's {conversion['opponent_attack_candidates']} attack candidates, "
                               f"only {conversion['defensive_response_candidates']} produced a defensive "
                               f"candidate.",
                               "Drill paired 'opponent thrust — parry/riposte' exercises: stabilize guard position "
                               "first, then add the riposte."))
        else:
            candidates.append((88, "提高对手进攻后的防守转化", f"对手 {conversion['opponent_attack_candidates']} 次进攻候选中，仅 {conversion['defensive_response_candidates']} 次出现防守候选。",
                               "安排“对手直刺—格挡/还击”双人练习，先稳定护手位置，再加还击。"))
    recovery = style.get("lunge_recovery_p75_sec")
    if recovery is not None and recovery > 0.8:
        if lang == "en":
            candidates.append((82, "Speed up lunge recovery",
                               f"P75 lunge recovery time is {recovery}s; a slow recovery may compromise the next "
                               f"defensive action.",
                               "Practice the lunge-recover-retreat 3-count drill, focusing on immediately "
                               "recovering weight after landing."))
        else:
            candidates.append((82, "加快弓步后的还原", f"弓步还原 P75 为 {recovery}s，后段回收可能影响下一次防守。",
                               "做弓步—还原—后退的三拍练习，重点在落地后立即回收重心。"))
    if footwork.get("lunge_count", 0) == 0:
        if lang == "en":
            candidates.append((65, "Gather verifiable attack samples",
                               "No lunge candidates were detected this session, so lunge quality and recovery "
                               "cannot be assessed.",
                               "Include 10 clearly visible lunge-recover combinations in the next recording, "
                               "keeping the full body and blade tip in frame."))
        else:
            candidates.append((65, "补充可验证的进攻样本", "本场未检出弓步候选，无法评估弓步质量与还原。",
                               "下一次录制加入 10 次清晰的弓步-还原组合，保持全身与剑尖在画面内。"))
    while len(candidates) < 3:
        if lang == "en":
            candidates.append((55, "Establish a baseline for the next session",
                               "Current metrics can serve as a personal starting point; trends only become "
                               "meaningful with consistent tracking.",
                               "Keep the same camera position and piste annotation next time, and focus on "
                               "comparing median reaction time, trajectory stability, and defensive conversion."))
        else:
            candidates.append((55, "建立下一场对照基线", "当前指标可作为个人起点，连续记录后才能判断趋势。",
                               "下一场保持同一机位和剑道标注，重点比较反应中位数、轨迹稳定度与防守转化。"))
    candidates.sort(key=lambda item: -item[0])
    return [{"priority": i + 1, "title": item[1], "reason": item[2], "action": item[3]}
            for i, item in enumerate(candidates[:3])]


def build_scorecard(events, timeline, lang="zh"):
    """Return a serializable per-side scorecard and attach no external state."""
    side_label = SIDE_LABEL.get(lang, SIDE_LABEL["zh"])
    sides = {}
    for side in SIDES:
        stats = events["stats"][side]
        blade = blade_metrics(timeline, side)
        conversion = _defense_conversion(events.get("actions", []), side)
        reaction = stats["reaction"]
        sides[side] = {
            "label": side_label[side],
            "metrics": {
                **blade,
                "reaction_median_sec": reaction.get("median_sec"),
                "reaction_sample_count": reaction.get("count", 0),
                "lunge_count": stats["footwork"].get("lunge_count", 0),
                "attack_count": stats.get("attack_count", 0),
                "defense_count": stats.get("defense_count", 0),
                "defense_conversion": conversion,
            },
            "improvements": _improvements(events, side, blade, conversion, lang),
        }
    return {
        "schema_version": "1.0",
        "lang": lang,
        "measurement_note": MEASUREMENT_NOTE.get(lang, MEASUREMENT_NOTE["zh"]),
        "sides": sides,
    }


def render_scorecard_markdown(scorecard):
    """Compact Markdown presentation used by the WebUI and session browser.

    Renders in whichever language the scorecard was built with (stored in
    ``scorecard["lang"]``), independent of the caller's current UI language —
    already-computed results are never retranslated in place.
    """
    lang = (scorecard or {}).get("lang", "zh")
    insufficient = INSUFFICIENT_SAMPLE.get(lang, INSUFFICIENT_SAMPLE["zh"])
    if not scorecard:
        return "Scorecard not available yet." if lang == "en" else "成绩卡尚不可用。"
    if lang == "en":
        title, header, top3 = "# Bout Scorecard", (
            "| Tip detection rate | Trajectory stability | Peak tip speed | Median reaction time | "
            "Lunges | Attack/Defense candidates | Defense conversion |"
        ), "**Top 3 improvements**"
        training_label = "Training"
    else:
        title, header, top3 = "# 单场成绩卡", (
            "| 剑尖检出率 | 轨迹稳定度 | 峰值剑尖速度 | 反应时间中位数 | 弓步 | 攻/防候选 | 防守转化 |"
        ), "**最重要的 3 个改进点**"
        training_label = "训练"
    lines = [title, "", scorecard.get("measurement_note", ""), ""]
    for side in SIDES:
        item = scorecard["sides"].get(side)
        if not item:
            continue
        m = item["metrics"]
        conv = m["defense_conversion"]
        reaction = f"{m['reaction_median_sec']:.3f}s" if m["reaction_median_sec"] is not None else insufficient
        speed = f"{m['peak_tip_speed_px_s']:.0f} px/s" if m["peak_tip_speed_px_s"] is not None else insufficient
        conversion = (
            f"{conv['rate'] * 100:.0f}% ({conv['defensive_response_candidates']}/{conv['opponent_attack_candidates']})"
            if conv["rate"] is not None else insufficient
        )
        lines += [
            f"## {item['label']}", "",
            header,
            "| --- | --- | --- | --- | --- | --- | --- |",
            f"| {m['tip_detection_rate'] * 100:.0f}% | {m['trajectory_stability']:.0f}/100 | {speed} | {reaction} | {m['lunge_count']} | {m['attack_count']}/{m['defense_count']} | {conversion} |",
            "", top3,
        ]
        for improvement in item["improvements"]:
            lines.append(f"{improvement['priority']}. **{improvement['title']}**: {improvement['reason']}  ")
            lines.append(f"   {training_label}: {improvement['action']}")
        lines.append("")
    return "\n".join(lines)
