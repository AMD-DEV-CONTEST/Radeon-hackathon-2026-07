"""Coaching report generation (Chinese or English, markdown).

With an agent backend the report is written by the model from the analysis
summary; without one a rule-based template still produces a complete report.
The output language follows ``config["language"]`` (zh by default).
"""

import json
import os
import re

from .base import create_agent
from ..analysis.scorecard import render_scorecard_markdown

SIDE_LABEL = {
    "zh": {"left": "左方剑手", "right": "右方剑手"},
    "en": {"left": "Left fencer", "right": "Right fencer"},
}

STYLE_LABEL_EN = {
    "进攻压迫型": "Pressing attacker",
    "防守反击型": "Counter-attacker",
    "机动控距型": "Distance manager",
    "稳健均衡型": "Balanced",
}


def _english_tactical_summary(style):
    """Build an English tactical summary from metrics, never the zh cache.

    ``style.comparison.summary`` is intentionally a Chinese coaching reading
    stored for Chinese reports.  English reports must derive their own text
    from the structured metrics so one report cannot contain a mixed language.
    """
    profiles = style.get("profiles", {})
    left, right = profiles.get("left", {}), profiles.get("right", {})
    left_style = STYLE_LABEL_EN.get(left.get("style_label", ""), left.get("style_label", ""))
    right_style = STYLE_LABEL_EN.get(right.get("style_label", ""), right.get("style_label", ""))
    lines = [f"Left [{left_style}] vs Right [{right_style}]."]
    phrase = style.get("phrase_tactics", {})
    lp, rp = phrase.get("left", {}), phrase.get("right", {})
    if lp.get("initiative_rate") is not None:
        leader = "Left" if (lp.get("initiative_rate") or 0) >= (rp.get("initiative_rate") or 0) else "Right"
        lines.append(
            f"Phrase initiative: Left {lp['initiative_rate']}% / Right {rp['initiative_rate']}%; "
            f"{leader} initiated more often. Net ground: Left {lp['net_ground_m']}m / Right {rp['net_ground_m']}m.")
    interaction = style.get("interaction", {})
    for side, label in (("left", "Left"), ("right", "Right")):
        data = interaction.get(side)
        if data:
            lines.append(
                f"When {label} advanced, the opponent retreated {data['opponent_retreats']}%, "
                f"held {data['opponent_holds']}%, and pressed back {data['opponent_presses_back']}%.")
    closing = style.get("distance_authority", {}).get("closing_drive", {})
    if closing.get("left") is not None and closing.get("right") is not None:
        driver = "Left" if closing["left"] >= closing["right"] else "Right"
        lines.append(f"Distance closing was driven mainly by {driver} (Left {closing['left']}% / Right {closing['right']}%).")
    for side, label in (("left", "Left"), ("right", "Right")):
        data = style.get("attack_context", {}).get(side, {})
        if data.get("count"):
            lines.append(
                f"{label} attack context: into an advance {data['into_opponent_advance']}% / "
                f"on a retreat {data['on_opponent_retreat']}% / from a static start {data['on_opponent_static']}%; "
                f"mean attack distance {data['mean_attack_distance_m']}m.")
    return " ".join(lines)


def _stats_summary(events, lang):
    side_label = SIDE_LABEL.get(lang, SIDE_LABEL["zh"])
    lines = []
    for side in ("left", "right"):
        s = events["stats"][side]
        fw = s["footwork"]
        rx = s["reaction"]
        if lang == "en":
            lines.append(
                f"{side_label[side]}: detection rate {s['coverage'] * 100:.0f}%, "
                f"{fw['advance_count']} advances ({fw['advance_time_sec']}s total), "
                f"{fw['retreat_count']} retreats ({fw['retreat_time_sec']}s total), "
                f"{fw['lunge_count']} lunges, peak speed {fw['peak_speed_ms']} m/s, "
                f"{s['attack_count']} attack candidates, {s['defense_count']} defense candidates, "
                + (f"median reaction time {rx['median_sec']}s (fastest {rx['best_sec']}s / "
                   f"slowest {rx['worst_sec']}s, n={rx['count']})"
                   if rx.get("count") else "insufficient reaction-time samples")
            )
        else:
            lines.append(
                f"{side_label[side]}: 检出率 {s['coverage'] * 100:.0f}%，"
                f"前进 {fw['advance_count']} 次(共 {fw['advance_time_sec']}s)，"
                f"后退 {fw['retreat_count']} 次(共 {fw['retreat_time_sec']}s)，"
                f"弓步 {fw['lunge_count']} 次，峰值速度 {fw['peak_speed_ms']} m/s，"
                f"进攻候选 {s['attack_count']} 次，防守候选 {s['defense_count']} 次，"
                + (f"反应时间中位数 {rx['median_sec']}s (最快 {rx['best_sec']}s / 最慢 {rx['worst_sec']}s，n={rx['count']})"
                   if rx.get("count") else "反应时间样本不足")
            )
    dist = events.get("distance", {})
    if dist.get("available"):
        if lang == "en":
            lines.append(
                f"Engagement distance: mean {dist['mean_m']}m, closest {dist['min_m']}m, farthest {dist['max_m']}m, "
                f"max closing speed {dist.get('max_closing_speed_ms')} m/s"
            )
        else:
            lines.append(
                f"交锋距离: 平均 {dist['mean_m']}m，最近 {dist['min_m']}m，最远 {dist['max_m']}m，"
                f"最大合拢速度 {dist.get('max_closing_speed_ms')} m/s"
            )
    if lang == "en":
        lines.append(f"Segmented into {len(events.get('phrases', []))} engagement phrases.")
    else:
        lines.append(f"共分为 {len(events.get('phrases', []))} 个交锋回合。")
    return "\n".join(lines)


def _style_section(events, lang):
    style = events.get("style")
    if not style:
        return ""
    side_label = SIDE_LABEL.get(lang, SIDE_LABEL["zh"])
    heading = "## Style analysis" if lang == "en" else "## 打法分析"
    comparison = style.get("comparison", {})
    summary = _english_tactical_summary(style) if lang == "en" else comparison.get("summary", "")
    lines = [heading, "", summary, ""]
    for side in ("left", "right"):
        p = style["profiles"][side]
        d = p["detail"]
        if lang == "en":
            lines.append(
                f"- **{side_label[side]} [{STYLE_LABEL_EN.get(p.get('style_label', ''), p.get('style_label', ''))}]** "
                f"aggression {p['aggression']:.2f} | territory {p['territory']:.2f} | "
                f"tempo {p['tempo']:.2f} | close-range preference {p['distance']:.2f} | technique {p['technique']:.2f}; "
                f"first-move ratio {d['first_move_ratio']:.0%}, mean position {d['mean_position_m']}m, "
                f"{d['lunges_per_min']} lunges/min"
                + (f", median recovery {d['mean_lunge_recovery_sec']}s (quality rate {d['lunge_quality_rate']}%)"
                   if d.get("mean_lunge_recovery_sec") else "")
            )
        else:
            lines.append(
                f"- **{side_label[side]}【{p.get('style_label', '')}】** "
                f"进攻性 {p['aggression']:.2f} | 空间控制 {p['territory']:.2f} | "
                f"节奏 {p['tempo']:.2f} | 近战偏好 {p['distance']:.2f} | 技术 {p['technique']:.2f}；"
                f"先动率 {d['first_move_ratio']:.0%}，平均站位 {d['mean_position_m']}m，"
                f"弓步 {d['lunges_per_min']}/分钟"
                + (f"，恢复中位 {d['mean_lunge_recovery_sec']}s(达标率 {d['lunge_quality_rate']}%)"
                   if d.get("mean_lunge_recovery_sec") else "")
            )

    rhythm = style.get("rhythm", {})
    evolution = style.get("evolution", {})
    for side in ("left", "right"):
        rh, ev = rhythm.get(side), evolution.get(side)
        extra = []
        if lang == "en":
            if rh:
                extra.append(f"{rh['bursts_per_min']} bursts/min (mean {rh['mean_burst_sec']}s, "
                             f"explosive share {rh['explosive_burst_share']}%), "
                             f"{rh['direction_changes_per_min']} direction changes/min")
            if ev and ev.get("speed_drift_pct") is not None:
                trend = "increased" if ev["speed_drift_pct"] > 0 else "decreased"
                extra.append(f"later-phase movement intensity {trend} {abs(ev['speed_drift_pct'])}% vs the opening")
            if extra:
                lines.append(f"  - {side_label[side]} tempo: {'; '.join(extra)}")
        else:
            if rh:
                extra.append(f"爆发 {rh['bursts_per_min']} 次/分(均长 {rh['mean_burst_sec']}s,"
                             f"高强占比 {rh['explosive_burst_share']}%),变向 {rh['direction_changes_per_min']} 次/分")
            if ev and ev.get("speed_drift_pct") is not None:
                trend = "提升" if ev["speed_drift_pct"] > 0 else "下降"
                extra.append(f"后段移动强度较开局{trend} {abs(ev['speed_drift_pct'])}%")
            if extra:
                lines.append(f"  - {side_label[side]}节奏:{';'.join(extra)}")

    lines += ["", "![style](charts/style_radar.png)", "",
              "![interaction](charts/interaction_matrix.png)", "",
              "![evolution](charts/style_evolution.png)", ""]
    return "\n".join(lines)


def _template_report(events, lang):
    charts = "\n".join(
        f"![{name}](charts/{name}.png)"
        for name in ("distance", "footwork_timeline", "reaction_times", "position_heatmap")
    )
    if lang == "en":
        return f"""# SparkFencer Training Analysis Report

Video: {events['video']['name']} ({events['video']['duration_sec']:.0f}s)

## Data overview

{_stats_summary(events, lang)}

{render_scorecard_markdown(events.get("scorecard"))}

{_style_section(events, lang)}

## Charts

{charts}

## Note

This report was generated automatically by rule-based analysis (no AI coach enabled). Configure ANTHROPIC_API_KEY
or a local VLM to get a full report with targeted training advice.
"""
    return f"""# SparkFencer 训练分析报告

视频: {events['video']['name']}（{events['video']['duration_sec']:.0f} 秒）

## 数据概览

{_stats_summary(events, lang)}

{render_scorecard_markdown(events.get("scorecard"))}

{_style_section(events, lang)}

## 图表

{charts}

## 说明

本报告由规则分析自动生成（未启用 AI 教练点评）。配置 ANTHROPIC_API_KEY 或本地 VLM 后可获得
带针对性训练建议的完整报告。
"""


def _agent_report(agent, events, validated, lang):
    validated_str = json.dumps(validated or [], ensure_ascii=False)[:6000]
    if lang == "en":
        prompt = f"""You are a professional fencing coach. Based on the automated analysis data below, write a
training analysis report (in English, markdown) for this training video.

## Data overview
{_stats_summary(events, lang)}

## Bout scorecard
{render_scorecard_markdown(events.get("scorecard"))}

## AI-cross-validated events (with verdicts and reasoning)
{validated_str}

Requirements:
1. Title the report "SparkFencer Training Analysis Report", followed by 3-5 sentences of overall assessment.
2. For the left and right fencers separately, give strengths, weaknesses, and 2-3 specific training suggestions
   (e.g. footwork tempo, lunge quality, reaction speed, distance control), tied to the data.
3. You may cite specific event types (e.g. a particular lunge or riposte) as evidence, but do not list or cite
   specific start/end timestamps, and do not suggest reviewing the video.
4. If some events were rejected by cross-validation, note that the detection may be a false positive and don't
   base conclusions on them.
5. End with a "Charts" section embedding charts/distance.png, charts/footwork_timeline.png,
   charts/reaction_times.png, charts/position_heatmap.png.
6. Output markdown directly, with no extra explanation."""
    else:
        prompt = f"""你是一名专业击剑教练。根据以下自动分析数据，为这段训练视频写一份中文训练分析报告（markdown）。

## 数据概览
{_stats_summary(events, lang)}

## 单场成绩卡
{render_scorecard_markdown(events.get("scorecard"))}

## 经 AI 交叉验证的事件（含裁定与理由）
{validated_str}

要求:
1. 标题为「SparkFencer 训练分析报告」，随后给出 3-5 句总体评价。
2. 分别针对左方、右方剑手给出优势、问题与 2-3 条具体训练建议（如步法节奏、弓步质量、反应速度、距离控制），建议要与数据对应。
3. 可结合具体事件类型（如某次弓步、某次反击）作为证据说明问题，但不要罗列或标注具体的开始/结束时间戳，也不要提示回看视频。
4. 若某些事件被验证否决(reject)，在报告中说明检测可能误报，不要基于它们下结论。
5. 末尾加一节「图表」，内嵌 charts/distance.png、charts/footwork_timeline.png、charts/reaction_times.png、charts/position_heatmap.png。
6. 直接输出 markdown 正文，不要额外解释。"""
    return agent.query(prompt)


def _strip_markdown_fence(text):
    """Some local VLMs wrap the whole answer in a ```markdown ... ``` fence
    despite being told to output markdown directly; unwrap it so the report
    renders as markdown instead of one giant code block."""
    match = re.match(r"^\s*```(?:markdown)?\s*\n(.*)\n```\s*$", text, re.DOTALL)
    return match.group(1) if match else text


def generate_report(output_dir, events, validated, config, use_agent=True):
    lang = config.get("language", "zh")
    report = None
    if use_agent:
        agent = create_agent(config)
        if agent is not None:
            try:
                print(f"Generating coach report with agent backend '{agent.name}'...")
                report = _strip_markdown_fence(_agent_report(agent, events, validated, lang))
            except Exception as exc:
                print(f"Agent report failed ({exc}); falling back to template report.")

    if not report:
        report = _template_report(events, lang)

    report_path = os.path.join(output_dir, "report.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"Report written to {report_path}")
    return report_path
