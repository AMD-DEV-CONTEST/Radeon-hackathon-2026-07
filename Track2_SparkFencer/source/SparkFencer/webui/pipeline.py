"""Headless pipeline wrapper for the WebUI."""

import base64
import os
import re
import shutil
import time
import json
from html import escape

import cv2

from fencing_analysis.pipeline import run_pipeline
from fencing_analysis.analysis.scorecard import render_scorecard_markdown

_MAX_WEBUI_OUTPUTS = 10

_MD_IMAGE_RE = re.compile(r"(!\[[^\]]*\]\()([^)]+)(\))")
_MIME_BY_EXT = {".png": "png", ".jpg": "jpeg", ".jpeg": "jpeg", ".gif": "gif", ".webp": "webp"}


def _localize_report_images(report_text, output_dir):
    """Inline chart images embedded in report markdown as base64 data URIs.

    gr.Markdown renders raw local filesystem paths as literal browser URLs
    (there is no path-rewriting for markdown-embedded images, unlike
    gr.Image/gr.Gallery component values which Gradio serves itself), so a
    relative or absolute on-disk path never resolves in the browser. Data
    URIs sidestep that entirely. The on-disk report.md keeps portable
    relative paths; only the text handed to gr.Markdown() for display goes
    through this."""
    def _rewrite(match):
        prefix, path, suffix = match.groups()
        if path.startswith(("http://", "https://", "data:")):
            return match.group(0)
        mime = _MIME_BY_EXT.get(os.path.splitext(path)[1].lower())
        if not mime:
            return match.group(0)
        full_path = path if os.path.isabs(path) else os.path.join(output_dir, path)
        try:
            with open(full_path, "rb") as f:
                encoded = base64.b64encode(f.read()).decode("ascii")
        except OSError:
            return match.group(0)
        return f"{prefix}data:image/{mime};base64,{encoded}{suffix}"

    return _MD_IMAGE_RE.sub(_rewrite, report_text)


def _format_clock(seconds):
    seconds = max(0, float(seconds or 0))
    return f"{int(seconds // 60):02d}:{seconds % 60:05.2f}"


def render_match_timeline(events):
    """Compact, safe HTML timeline for the workbench's summary panel."""
    video = events.get("video") or {}
    duration = max(float(video.get("duration_sec") or 0), 0.1)
    markers = []

    style_map = {
        "attack": ("进攻", "attack"),
        "counter": ("反击", "counter"),
        "parry": ("防守", "defense"),
    }
    for action in events.get("actions") or []:
        label, kind = style_map.get(action.get("type"), ("动作", "other"))
        side = "左方" if action.get("fencer") == "left" else "右方"
        markers.append({
            "time": float(action.get("start_sec") or 0),
            "label": label,
            "side": side,
            "kind": kind,
            "confidence": action.get("confidence"),
        })
    for lunge in (events.get("footwork") or {}).get("lunges") or []:
        markers.append({
            "time": float(lunge.get("time_sec") or 0),
            "label": "弓步",
            "side": "左方" if lunge.get("fencer") == "left" else "右方",
            "kind": "lunge",
            "confidence": lunge.get("confidence"),
        })

    markers.sort(key=lambda item: item["time"])
    marker_html = []
    for item in markers:
        position = min(99.5, max(0.5, item["time"] / duration * 100))
        confidence = item["confidence"]
        suffix = f" · 置信 {float(confidence):.0%}" if confidence is not None else ""
        title = escape(f"{_format_clock(item['time'])} · {item['side']} · {item['label']}{suffix}")
        marker_html.append(
            f'<span class="sf-timeline-marker {item["kind"]}" style="left:{position:.2f}%" '
            f'title="{title}" aria-label="{title}"></span>'
        )

    tick_count = 6
    ticks = []
    for index in range(tick_count):
        second = duration * index / (tick_count - 1)
        ticks.append(f'<span style="left:{index / (tick_count - 1) * 100:.0f}%">{_format_clock(second)}</span>')
    marker_count = len(markers)
    empty = "<div class=\"sf-timeline-empty\">尚未识别到足够明确的动作事件；仍可查看成绩卡和图表。</div>" if not markers else ""
    return f'''<section class="sf-match-timeline">
      <div class="sf-timeline-head"><div><b>比赛事件时间线</b><small>{_format_clock(duration)} · {marker_count} 个事件</small></div>
      <div class="sf-timeline-legend"><span class="attack">进攻</span><span class="lunge">弓步</span><span class="counter">反击</span><span class="defense">防守</span></div></div>
      <div class="sf-timeline-track">{''.join(marker_html)}</div>
      <div class="sf-timeline-ticks">{''.join(ticks)}</div>{empty}
    </section>'''


def evidence_playback_choices(manifest):
    """Dropdown choices that identify a time window in the one replay video."""
    choices = []
    for event in manifest or []:
        start = float(event.get("playback_start_sec", event.get("start_sec", 0)))
        end = float(event.get("playback_end_sec", event.get("end_sec", start)))
        side = "左方" if event.get("fencer") == "left" else "右方"
        label = f"{_format_clock(start)}–{_format_clock(end)} · {side} · {event.get('kind', '事件')}"
        value = json.dumps({"id": event.get("id", ""), "start": start, "end": end,
                            "label": label}, ensure_ascii=False, separators=(",", ":"))
        choices.append((label, value))
    return choices


def render_evidence_windows(manifest):
    if not manifest:
        return "暂无事件时间证据。"
    rows = ["| 事件 | 剑手 | 回放时间段 |", "| --- | --- | --- |"]
    for event in manifest:
        start = float(event.get("playback_start_sec", event.get("start_sec", 0)))
        end = float(event.get("playback_end_sec", event.get("end_sec", start)))
        side = "左方" if event.get("fencer") == "left" else "右方"
        rows.append(f"| {event.get('kind', '事件')} | {side} | {_format_clock(start)}–{_format_clock(end)} |")
    return "\n".join(rows)


def cleanup_old_outputs(base_dir="outputs", prefix="webui_", keep=_MAX_WEBUI_OUTPUTS):
    if not os.path.isdir(base_dir):
        return
    dirs = []
    for name in os.listdir(base_dir):
        if name.startswith(prefix):
            full = os.path.join(base_dir, name)
            if os.path.isdir(full):
                dirs.append((os.path.getmtime(full), full))
    dirs.sort(reverse=True)
    for _, path in dirs[keep:]:
        try:
            shutil.rmtree(path)
        except Exception:
            pass


def list_sessions_info(root="outputs"):
    """All analyzed sessions (have events.json), newest first."""
    import json
    sessions = []
    if os.path.isdir(root):
        for name in os.listdir(root):
            epath = os.path.join(root, name, "events.json")
            if not os.path.exists(epath):
                continue
            with open(epath, encoding="utf-8") as f:
                e = json.load(f)
            sessions.append({
                "name": name,
                "mtime": os.path.getmtime(epath),
                "duration": e["video"]["duration_sec"],
                "phrases": len(e.get("phrases", [])),
            })
    sessions.sort(key=lambda s: -s["mtime"])
    return sessions


_STYLE_LABEL_EN = {
    "进攻压迫型": "Pressing attacker",
    "防守反击型": "Counter-attacker",
    "机动控距型": "Distance manager",
    "稳健均衡型": "Balanced",
}


def _session_overview_markdown(events, name, lang="zh"):
    """Render archive statistics in the currently selected interface language.

    Session JSON keeps the original analysis language, so this function only
    derives a compact, deterministic overview from structured metrics. It does
    not attempt to machine-translate the historical LLM report.
    """
    english = lang == "en"
    side_labels = {"left": "Left fencer", "right": "Right fencer"} if english else {
        "left": "左方", "right": "右方"
    }
    stats_lines = []
    for side in ("left", "right"):
        stats = events["stats"][side]
        footwork = stats["footwork"]
        style = (events.get("style") or {}).get("profiles", {}).get(side, {})
        style_label = style.get("style_label", "")
        if english:
            style_label = _STYLE_LABEL_EN.get(style_label, style_label)
            prefix = f"**{side_labels[side]}**"
            if style_label:
                prefix += f" [{style_label}]"
            stats_lines.append(
                f"{prefix} Detection {stats['coverage'] * 100:.0f}% · "
                f"Advance/Retreat {footwork['advance_count']}/{footwork['retreat_count']} · "
                f"Lunges {footwork['lunge_count']} · Peak speed {footwork['peak_speed_ms']:.1f} m/s · "
                f"Attack/Defense {stats['attack_count']}/{stats['defense_count']}"
            )
        else:
            prefix = f"**{side_labels[side]}**"
            if style_label:
                prefix += f"【{style_label}】"
            stats_lines.append(
                f"{prefix} 检出 {stats['coverage'] * 100:.0f}% · "
                f"前进/后退 {footwork['advance_count']}/{footwork['retreat_count']} · "
                f"弓步 {footwork['lunge_count']} · 峰速 {footwork['peak_speed_ms']:.1f} m/s · "
                f"攻/防 {stats['attack_count']}/{stats['defense_count']}"
            )

    distance = events.get("distance", {})
    if distance.get("available"):
        if english:
            stats_lines.append(
                f"**Distance** Mean {distance['mean_m']} m · Closest {distance['min_m']} m · "
                f"Farthest {distance['max_m']} m"
            )
        else:
            stats_lines.append(
                f"**距离** 均值 {distance['mean_m']} m · 最近 {distance['min_m']} m · 最远 {distance['max_m']} m"
            )

    comparison = (events.get("style") or {}).get("comparison", {})
    if english and comparison:
        initiative = side_labels.get(comparison.get("initiative"), comparison.get("initiative", ""))
        territory = side_labels.get(comparison.get("territory_control"), comparison.get("territory_control", ""))
        clauses = []
        if initiative:
            clauses.append(f"initiative: {initiative}")
        if territory:
            clauses.append(f"territory control: {territory}")
        if comparison.get("aggression_gap") is not None:
            clauses.append(f"aggression gap: {comparison['aggression_gap']:.2f}")
        if clauses:
            stats_lines.append("**Tactical comparison** " + " · ".join(clauses))
    elif comparison.get("summary"):
        stats_lines.append(f"**对位** {comparison['summary']}")

    duration = events["video"]["duration_sec"]
    phrase_count = len(events.get("phrases", []))
    if english:
        heading = f"Duration {duration:.0f}s · Phrases {phrase_count}"
    else:
        heading = f"时长 {duration:.0f}s · 回合 {phrase_count}"
    return f"### {name}\n\n{heading}\n\n" + "\n\n".join(stats_lines)


def load_session_assets(name, root="outputs", lang="zh"):
    """Everything the browser tab needs for one session."""
    import json
    base = os.path.join(root, name)
    with open(os.path.join(base, "events.json"), encoding="utf-8") as f:
        e = json.load(f)

    overview_md = _session_overview_markdown(e, name, lang)

    charts_dir = os.path.join(base, "charts")
    charts = [os.path.join(charts_dir, f) for f in sorted(os.listdir(charts_dir))
              if f.endswith(".png")] if os.path.isdir(charts_dir) else []

    report = ""
    rpath = os.path.join(base, "report.md")
    if os.path.exists(rpath):
        with open(rpath, encoding="utf-8") as f:
            report = _localize_report_images(f.read(), base)

    manifest = []
    manifest_path = os.path.join(base, "evidence_manifest.json")
    if os.path.exists(manifest_path):
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f).get("events", [])

    video = None
    for f in os.listdir(base):
        if f.startswith("annotated_") and f.endswith(".mp4"):
            video = os.path.join(base, f)
            break
    scorecard = render_scorecard_markdown(e.get("scorecard"))
    return overview_md, scorecard, video, charts, report, render_evidence_windows(manifest)


def read_first_frame(video_path):
    cap = cv2.VideoCapture(video_path)
    ret, frame = cap.read()
    cap.release()
    if not ret:
        return None
    return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)


def run_webui_analysis(video_path, corners, piste_length, weapon, skip_agents,
                       blade_detector="cv", blade_filter="kalman", blade_model_path=None,
                       vlm_base_url=None, vlm_model=None, vlm_api_key=None, max_events_to_review=None,
                       lang="zh", progress_cb=None):
    cleanup_old_outputs()
    video_name = os.path.splitext(os.path.basename(video_path))[0]
    output_dir = os.path.join("outputs", f"webui_{video_name}_{time.strftime('%Y%m%d_%H%M%S')}")

    overrides = {
        "language": lang,
        "piste": {"length": float(piste_length)},
        "weapon": weapon,
        "blade": {"detector": blade_detector, "filter": blade_filter},
    }
    if vlm_base_url or vlm_model or vlm_api_key or max_events_to_review:
        overrides["agents"] = {"local": {}}
        if vlm_base_url:
            overrides["agents"]["local"]["base_url"] = vlm_base_url
        if vlm_model:
            overrides["agents"]["local"]["model"] = vlm_model
        if vlm_api_key:
            overrides["agents"]["local"]["api_key"] = vlm_api_key
        if max_events_to_review:
            overrides["agents"]["max_events_to_review"] = int(max_events_to_review)
    if blade_model_path:
        overrides["blade"]["model_path"] = blade_model_path
    elif blade_detector == "yolo":
        overrides["blade"]["model_path"] = "weights/blade_best.pt"
    results = run_pipeline(
        video_path,
        corners=corners,
        output_dir=output_dir,
        config_path="config.yaml" if os.path.exists("config.yaml") else None,
        config_overrides=overrides,
        skip_agents=skip_agents,
        progress_callback=progress_cb,
    )

    charts_dir = os.path.join(output_dir, "charts")
    charts = []
    if os.path.isdir(charts_dir):
        charts = [os.path.join(charts_dir, f) for f in sorted(os.listdir(charts_dir))
                  if f.endswith(".png")]

    manifest = []
    manifest_path = results.get("evidence") or os.path.join(output_dir, "evidence_manifest.json")
    if manifest_path and os.path.exists(manifest_path):
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f).get("events", [])

    report_text = ""
    report_path = results.get("report")
    if report_path and os.path.exists(report_path):
        with open(report_path, "r", encoding="utf-8") as f:
            report_text = _localize_report_images(f.read(), output_dir)

    scorecard_text = "成绩卡尚不可用。"
    timeline_html = '<div class="sf-timeline-empty">分析完成后将在这里显示比赛事件时间线。</div>'
    events_path = results.get("events")
    if events_path and os.path.exists(events_path):
        with open(events_path, "r", encoding="utf-8") as f:
            events = json.load(f)
            scorecard_text = render_scorecard_markdown(events.get("scorecard"))
            timeline_html = render_match_timeline(events)
        # Keep a local multi-bout catalog in sync.  Indexing failure must never
        # discard a completed analysis (e.g. Ollama embedding service is down).
        try:
            from fencing_analysis.rag.session_store import SessionStore
            SessionStore().upsert(os.path.basename(output_dir), events)
        except Exception as exc:
            print(f"Session index update skipped: {exc}")

    return {
        "output_dir": output_dir,
        "video": results.get("perception", {}).get("video"),
        "report": report_text,
        "scorecard": scorecard_text,
        "timeline": timeline_html,
        "charts": charts,
        "evidence_choices": evidence_playback_choices(manifest),
    }
