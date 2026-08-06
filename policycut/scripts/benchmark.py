#!/usr/bin/env python3
"""PolicyCut end-to-end benchmark.

Runs the real analysis + render pipeline on a given video/policy and reports
per-stage wall time, derived throughputs (DINO keyframes/s, Whisper realtime
factor, SAM2 frames/s) and peak VRAM. Degrades gracefully when models or
ffmpeg are missing: stages that cannot run are recorded as "skipped" with a
reason; the script never crashes because of a missing dependency.

Usage:
    python scripts/benchmark.py path/to/video.mp4 \
        --policy "blur all faces and license plates, mute phone numbers" \
        --precision fp16 --interval 0.5
"""

from __future__ import annotations

import argparse
import inspect
import json
import os
import shutil
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

OUT_DIR = PROJECT_ROOT / "artifacts" / "benchmarks"

ANALYSIS_STAGES = [
    "NORMALIZING", "PARSING_POLICY", "TRANSCRIBING", "DETECTING_PII",
    "DETECTING_VISUAL", "TRACKING", "BUILDING_PREVIEW", "REVIEW_READY",
]
RENDER_STAGES = ["RENDERING", "MUXING", "AUDITING", "COMPLETE"]


class StageClock:
    """Collects stage transitions + metrics from the pipeline progress callback."""

    def __init__(self) -> None:
        self.order: list[str] = []
        self.first_seen: dict[str, float] = {}
        self.last_seen: dict[str, float] = {}
        self.metrics: dict[str, dict] = {}

    def cb(self, stage: str, progress: float = 0.0, message: str = "", metrics: dict | None = None) -> None:
        now = time.perf_counter()
        if stage not in self.first_seen:
            self.first_seen[stage] = now
            self.order.append(stage)
        self.last_seen[stage] = now
        if metrics:
            for k, v in metrics.items():
                if isinstance(v, dict):
                    self.metrics.setdefault(k, {}).update(v)
                else:
                    self.metrics.setdefault(stage, {})[k] = v

    def wall(self, stage: str) -> float | None:
        """Wall time of a stage: from its first tick to the next stage's first tick."""
        if stage not in self.first_seen:
            return None
        idx = self.order.index(stage)
        if idx + 1 < len(self.order):
            return self.first_seen[self.order[idx + 1]] - self.first_seen[stage]
        return self.last_seen[stage] - self.first_seen[stage]


def _bind_and_call(fn, pool: dict):
    """Call fn filling parameters by name from pool (contract-tolerant)."""
    sig = inspect.signature(fn)
    kwargs = {}
    for name, param in sig.parameters.items():
        if name in pool:
            kwargs[name] = pool[name]
        elif param.default is inspect.Parameter.empty and param.kind in (
            param.POSITIONAL_OR_KEYWORD, param.KEYWORD_ONLY,
        ):
            # try loose aliases
            aliases = {
                "pid": "project_id", "project": "project_id",
                "cb": "progress_cb", "progress": "progress_cb", "callback": "progress_cb",
                "cancel": "cancel_event", "cancel_evt": "cancel_event", "stop_event": "cancel_event",
                "cfg": "settings", "config": "settings",
            }
            if name in aliases and aliases[name] in pool:
                kwargs[name] = pool[aliases[name]]
    return fn(**kwargs)


def probe_video(path: Path) -> dict:
    """Best-effort media info: ffprobe via policycut, else OpenCV, else minimal."""
    info = {"filename": path.name, "duration_s": None, "width": None, "height": None, "fps": None}
    try:
        from policycut.media.probe import probe_media  # type: ignore[attr-defined]
        mi = probe_media(str(path))
        return {"filename": path.name, "duration_s": mi.duration_s, "width": mi.width,
                "height": mi.height, "fps": mi.fps, "_media_info": mi}
    except Exception:
        pass
    try:
        import policycut.media.probe as probe_mod
        for name in dir(probe_mod):
            fn = getattr(probe_mod, name)
            if callable(fn) and name.startswith("probe") and not name.startswith("_"):
                mi = fn(str(path))
                if mi is not None:
                    return {"filename": path.name, "duration_s": getattr(mi, "duration_s", None),
                            "width": getattr(mi, "width", None), "height": getattr(mi, "height", None),
                            "fps": getattr(mi, "fps", None), "_media_info": mi}
    except Exception:
        pass
    try:
        import cv2
        cap = cv2.VideoCapture(str(path))
        if cap.isOpened():
            fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
            frames = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
            info.update({
                "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
                "fps": float(fps),
                "duration_s": float(frames / fps) if fps else None,
            })
        cap.release()
    except Exception:
        pass
    return info


def vram_reset():
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.synchronize()
            torch.cuda.reset_peak_memory_stats()
    except Exception:
        pass


def vram_peak_mb() -> float | None:
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.synchronize()
            return float(torch.cuda.max_memory_allocated()) / (1024 * 1024)
    except Exception:
        pass
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PolicyCut benchmark")
    parser.add_argument("video", help="path to input video (<= 60 s recommended)")
    parser.add_argument("--policy", default="blur all faces and license plates, mute phone numbers and emails",
                        help="natural-language policy text")
    parser.add_argument("--precision", choices=["fp16", "fp32"], default="fp16")
    parser.add_argument("--interval", type=float, default=None, help="override DINO keyframe interval (s)")
    parser.add_argument("--keep", action="store_true", help="keep the temporary benchmark project dir")
    args = parser.parse_args(argv)

    video_path = Path(args.video).expanduser().resolve()
    if not video_path.is_file():
        sys.exit(f"error: video not found: {video_path}")

    # Isolated data dir so the benchmark does not pollute real projects.
    tmp_data = Path(tempfile.mkdtemp(prefix="policycut_bench_"))
    os.environ["POLICYCUT_DATA_DIR"] = str(tmp_data)
    os.environ["POLICYCUT_PRECISION"] = args.precision  # hint consumed by model stages when supported

    report: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "video": {"name": video_path.name, "size_bytes": video_path.stat().st_size},
        "policy_text": args.policy,
        "precision": args.precision,
        "stages": {},
        "derived": {},
        "warnings": [],
    }

    try:
        from policycut.config import get_settings
        settings = get_settings()
        settings.data_dir = tmp_data
        if args.interval is not None:
            settings.dino_interval_s = args.interval
        report["interval_s"] = getattr(settings, "dino_interval_s", args.interval)
    except Exception as exc:
        report["warnings"].append(f"config unavailable: {exc}")
        settings = None

    try:
        from policycut.core.device import device_info
        report["environment"] = device_info()
    except Exception as exc:
        report["environment"] = {"error": str(exc)}

    media = probe_video(video_path)
    duration = media.get("duration_s")
    report["video"].update({k: v for k, v in media.items() if not k.startswith("_")})

    ok = True
    try:
        from policycut.core.storage import ProjectStore
        store = ProjectStore(tmp_data)
        project = store.create_project("benchmark")
        pid = project.id
        ext = video_path.suffix.lower() or ".mp4"
        dest = store.path(pid, "source", "original" + ext)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(video_path, dest)
        if media.get("_media_info") is not None:
            project.media = media["_media_info"]
        project.policy_text = args.policy
        store.save_project(project)
    except Exception as exc:
        report["warnings"].append(f"project setup failed: {exc}")
        ok = False
        store = None
        pid = None

    # --- policy parsing (timed separately; LLM optional) ---
    if ok:
        t0 = time.perf_counter()
        try:
            from policycut.policy.parser import parse_policy
            use_llm = os.environ.get("POLICYCUT_NO_LLM", "0") != "1"
            spec, source = parse_policy(args.policy, use_llm=use_llm)
            store.save_policy(pid, spec)
            report["stages"]["POLICY_PARSE"] = {"wall_s": round(time.perf_counter() - t0, 3), "source": source}
        except Exception as exc:
            report["stages"]["POLICY_PARSE"] = {"status": "skipped", "reason": str(exc)}
            report["warnings"].append(f"policy parse failed: {exc}")
            ok = False

    clock = StageClock()
    cancel_event = threading.Event()

    # --- analysis ---
    if ok:
        vram_reset()
        t_start = time.perf_counter()
        try:
            from policycut.pipeline import run_analysis
            _bind_and_call(run_analysis, {
                "project_id": pid, "store": store, "settings": settings,
                "progress_cb": clock.cb, "cancel_event": cancel_event,
            })
            report["derived"]["e2e_analysis_s"] = round(time.perf_counter() - t_start, 3)
        except Exception as exc:
            report["warnings"].append(f"analysis failed/degraded: {exc}")
            report["derived"]["e2e_analysis_s"] = round(time.perf_counter() - t_start, 3)
        peak = vram_peak_mb()
        if peak is not None:
            report["derived"]["analysis_peak_vram_mb"] = round(peak, 1)

    for stage in ANALYSIS_STAGES:
        wall = clock.wall(stage)
        if wall is None:
            report["stages"].setdefault(stage, {"status": "skipped", "reason": "stage did not run"})
        else:
            entry: dict = {"wall_s": round(wall, 3)}
            entry.update(clock.metrics.get(stage, {}))
            report["stages"][stage] = entry

    # --- derived throughputs ---
    def _stage_wall(name):
        e = report["stages"].get(name, {})
        return e.get("wall_s")

    if duration and _stage_wall("TRANSCRIBING"):
        report["derived"]["whisper_rtf"] = round(_stage_wall("TRANSCRIBING") / duration, 3)
    dino_wall = _stage_wall("DETECTING_VISUAL")
    if dino_wall and dino_wall > 0.05:  # skip when the stage failed instantly
        frames = report["stages"]["DETECTING_VISUAL"].get("frames")
        if not frames and duration and settings is not None:
            frames = int(duration / max(getattr(settings, "dino_interval_s", 0.5), 1e-6))
        if frames:
            report["derived"]["dino_keyframes_per_s"] = round(frames / dino_wall, 2)
    track_wall = _stage_wall("TRACKING")
    if track_wall:
        tframes = report["stages"]["TRACKING"].get("frames")
        if tframes:
            report["derived"]["sam2_frames_per_s"] = round(tframes / track_wall, 2)

    # --- render (confirm all events first) ---
    if ok:
        try:
            events = store.load_events(pid)
            for ev in events:
                if ev.status == "pending":
                    ev.status = "confirmed"
            store.save_events(pid, events)
            report["events_total"] = len(events)
        except Exception as exc:
            report["warnings"].append(f"could not confirm events: {exc}")

        vram_reset()
        rclock = StageClock()
        t0 = time.perf_counter()
        try:
            from policycut.pipeline import run_render
            _bind_and_call(run_render, {
                "project_id": pid, "store": store, "settings": settings,
                "progress_cb": rclock.cb, "cancel_event": threading.Event(),
            })
            report["derived"]["render_s"] = round(time.perf_counter() - t0, 3)
        except Exception as exc:
            report["warnings"].append(f"render failed/degraded: {exc}")
        for stage in RENDER_STAGES:
            wall = rclock.wall(stage)
            if wall is not None:
                entry = {"wall_s": round(wall, 3)}
                entry.update(rclock.metrics.get(stage, {}))
                report["stages"][stage] = entry
        peak = vram_peak_mb()
        if peak is not None:
            report["derived"]["render_peak_vram_mb"] = round(peak, 1)

    if duration and report["derived"].get("e2e_analysis_s"):
        total = report["derived"]["e2e_analysis_s"] + report["derived"].get("render_s", 0.0)
        report["derived"]["realtime_factor"] = round(total / duration, 3)

    # --- write JSON ---
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = OUT_DIR / f"benchmark_{ts}.json"
    tmp = out_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(report, indent=2, default=str))
    os.replace(tmp, out_path)

    # --- markdown table ---
    print(f"\n## PolicyCut benchmark — {video_path.name} "
          f"({duration:.1f}s)" if duration else f"\n## PolicyCut benchmark — {video_path.name}")
    print(f"precision: {args.precision}   interval: {report.get('interval_s')}   "
          f"gpu: {report.get('environment', {}).get('name', 'n/a')}\n")
    print("| Stage | Wall (s) | Throughput | Notes |")
    print("|---|---|---|---|")
    for stage in ["POLICY_PARSE"] + ANALYSIS_STAGES + RENDER_STAGES:
        entry = report["stages"].get(stage)
        if not entry:
            continue
        if entry.get("status") == "skipped":
            print(f"| {stage} | — | — | skipped: {entry.get('reason', '')[:60]} |")
            continue
        thr = ""
        if stage == "TRANSCRIBING" and report["derived"].get("whisper_rtf"):
            thr = f"RTF {report['derived']['whisper_rtf']}"
        elif stage == "DETECTING_VISUAL" and report["derived"].get("dino_keyframes_per_s"):
            thr = f"{report['derived']['dino_keyframes_per_s']} kf/s"
        elif stage == "TRACKING" and report["derived"].get("sam2_frames_per_s"):
            thr = f"{report['derived']['sam2_frames_per_s']} fr/s"
        notes = ", ".join(f"{k}={v}" for k, v in entry.items() if k not in ("wall_s",))
        print(f"| {stage} | {entry.get('wall_s', '—')} | {thr} | {notes[:70]} |")
    print("| **Derived** | | | |")
    for k, v in report["derived"].items():
        print(f"| {k} | {v} | | |")
    if report["warnings"]:
        print("\nWarnings:")
        for w in report["warnings"]:
            print(f"  - {w}")
    print(f"\nJSON written to {out_path}")

    if not args.keep:
        shutil.rmtree(tmp_data, ignore_errors=True)
    else:
        print(f"Benchmark project kept at {tmp_data}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
