#!/usr/bin/env python3
"""
Assemble contest demo video (3–5 min) with burned-in English captions.

Storyboard (VIDEO.md-aligned, adapted to available clips):
  1. Title / problem / method cards
  2. Expert pick-and-place
  3. SmolVLA Sync successes (native)
  4. Sync freeze under +200 ms
  5. Async recovers under +200 ms
  6. RTC honest comparison + continuity clip
  7. π0.5 B1d place success
  8. Env-B held-out 3–5 cm shift (honest negative)
  9. Result figures + summary cards
 10. AMD / end card
"""
from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path("/workspace/latency_aware_vla")
OUT_DIR = ROOT / "artifacts" / "video_clips" / "demo_build"
FINAL = ROOT / "artifacts" / "demo-video.mp4"
SRT = ROOT / "artifacts" / "demo-video.en.srt"
W, H, FPS = 1280, 720, 30
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_B = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

CLIPS = {
    "expert": ROOT / "artifacts/video_clips/01_expert_pick_place_preview.mp4",
    "smol_ok_a": ROOT / "output/eval/smolvla_sync_E50_n20_s400/videos/ep005_ok_sbs.mp4",
    "smol_ok_b": ROOT / "output/eval/smolvla_sync_E50_n20_s400/videos/ep016_ok_sbs.mp4",
    "sync_d200": ROOT / "output/eval/smolvla_sync_E50_d200_n20_s400/videos/ep000_fail_sbs.mp4",
    "sync_d200_b": ROOT / "output/eval/smolvla_sync_E50_d200_n20_s400/videos/ep004_fail_sbs.mp4",
    "async_ok": ROOT / "output/eval/smolvla_async_E10_d200_n20/videos/ep016_ok_sbs.mp4",
    "rtc_fail": ROOT / "output/eval/smolvla_rtc_E10_d200_n20/videos/ep000_fail_sbs.mp4",
    "pi05_ok": ROOT / "output/eval/pi05_sync_E50_b1d_n20/videos/ep003_ok_sbs.mp4",
    # Paired Env-A place winner (ep3) fails under held-out 4.9 cm shift.
    "envb_fail": ROOT / "output/eval/pi05_sync_E50_b1d_envb_n20/videos/ep003_fail_sbs.mp4",
    "fig_latency": ROOT / "artifacts/figures/eval/env_a_latency_story.png",
    "fig_rtc": ROOT / "artifacts/figures/eval/env_a_rtc_story_success.png",
    "fig_pi05": ROOT / "artifacts/figures/eval/env_a_pi05_opt_success.png",
    "fig_envb": ROOT / "artifacts/figures/eval/env_a_vs_b.png",
}


def font(size: int, bold: bool = False):
    return ImageFont.truetype(FONT_B if bold else FONT, size)


def make_card(path: Path, lines: list[tuple[str, int, bool]], duration_s: float):
    img = Image.new("RGB", (W, H), (18, 24, 32))
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, W, 8], fill=(0, 140, 120))
    blocks = []
    for text, size, bold in lines:
        f = font(size, bold)
        wrapped = []
        for para in text.split("\n"):
            if not para:
                wrapped.append("")
                continue
            wrapped.extend(textwrap.wrap(para, width=52) or [""])
        blocks.append((wrapped, f))

    total_h = 0
    for wrapped, f in blocks:
        for line in wrapped:
            bbox = draw.textbbox((0, 0), line or " ", font=f)
            total_h += (bbox[3] - bbox[1]) + 10
        total_h += 14

    y = max(40, (H - total_h) // 2)
    for wrapped, f in blocks:
        for line in wrapped:
            bbox = draw.textbbox((0, 0), line or " ", font=f)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
            draw.text(((W - tw) // 2, y), line, font=f, fill=(240, 240, 240))
            y += th + 10
        y += 14

    path.parent.mkdir(parents=True, exist_ok=True)
    png = path.with_suffix(".png")
    img.save(png)
    subprocess.run(
        [
            "ffmpeg", "-y", "-loop", "1", "-i", str(png),
            "-c:v", "libx264", "-t", f"{duration_s:.3f}",
            "-pix_fmt", "yuv420p", "-r", str(FPS),
            "-vf", f"scale={W}:{H}",
            str(path),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return duration_s


def make_figure_slide(src_png: Path, path: Path, title: str, duration_s: float):
    """Place a results figure on the slate card with a title."""
    canvas = Image.new("RGB", (W, H), (18, 24, 32))
    draw = ImageDraw.Draw(canvas)
    draw.rectangle([0, 0, W, 8], fill=(0, 140, 120))
    f = font(28, True)
    bbox = draw.textbbox((0, 0), title, font=f)
    tw = bbox[2] - bbox[0]
    draw.text(((W - tw) // 2, 24), title, font=f, fill=(240, 240, 240))

    fig = Image.open(src_png).convert("RGB")
    max_w, max_h = W - 80, H - 100
    fig.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
    x = (W - fig.width) // 2
    y = 70 + (max_h - fig.height) // 2
    canvas.paste(fig, (x, y))

    path.parent.mkdir(parents=True, exist_ok=True)
    png = path.with_suffix(".png")
    canvas.save(png)
    subprocess.run(
        [
            "ffmpeg", "-y", "-loop", "1", "-i", str(png),
            "-c:v", "libx264", "-t", f"{duration_s:.3f}",
            "-pix_fmt", "yuv420p", "-r", str(FPS),
            str(path),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def esc(s: str) -> str:
    return (
        s.replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\\'")
        .replace("%", "\\%")
    )


def normalize_clip(src: Path, dst: Path, max_s: float | None, caption: str, label: str | None):
    dst.parent.mkdir(parents=True, exist_ok=True)
    filters = [
        f"scale={W}:{H}:force_original_aspect_ratio=decrease",
        f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=0x121820",
        "setsar=1",
        "fps=30",
    ]
    if label:
        filters.append(
            f"drawtext=fontfile={FONT_B}:text='{esc(label)}':"
            f"fontsize=28:fontcolor=white:borderw=2:bordercolor=black:"
            f"x=24:y=20"
        )
    if caption:
        filters.append(
            f"drawtext=fontfile={FONT}:text='{esc(caption)}':"
            f"fontsize=24:fontcolor=white:borderw=2:bordercolor=black:"
            f"x=(w-text_w)/2:y=h-78:box=1:boxcolor=black@0.55:boxborderw=10"
        )

    cmd = ["ffmpeg", "-y", "-i", str(src)]
    if max_s is not None:
        cmd += ["-t", f"{max_s:.3f}"]
    cmd += [
        "-vf", ",".join(filters),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(FPS),
        "-an",
        str(dst),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    out = subprocess.check_output(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(dst),
        ],
        text=True,
    ).strip()
    return float(out)


def sec_to_ts(t: float) -> str:
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")


def write_srt(entries: list[tuple[float, float, str]], path: Path):
    lines = []
    for i, (a, b, text) in enumerate(entries, 1):
        lines.append(str(i))
        lines.append(f"{sec_to_ts(a)} --> {sec_to_ts(b)}")
        lines.append(text)
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def probe(path: Path) -> float:
    return float(
        subprocess.check_output(
            [
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", str(path),
            ],
            text=True,
        ).strip()
    )


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for k, p in CLIPS.items():
        if not p.exists():
            raise SystemExit(f"Missing asset {k}: {p}")

    segments: list[tuple[Path, str]] = []

    p = OUT_DIR / "01_title.mp4"
    make_card(
        p,
        [
            ("Latency-Aware VLA on AMD", 42, True),
            ("Real-Time Chunking for Closed-Loop Physical AI", 24, False),
            ("AMD AI DevMaster Hackathon 2026  ·  Track 3", 20, False),
            ("Data · Train · Infer · Eval on one Radeon GPU", 18, False),
        ],
        12.0,
    )
    segments.append((p, "Large VLAs think in chunks. Inference delay stalls the robot."))

    p = OUT_DIR / "02_problem.mp4"
    make_card(
        p,
        [
            ("The problem", 36, True),
            ("Chunk inference takes ~300–350 ms on our AMD GPU.", 22, False),
            ("Sync waits for the next chunk → the arm freezes.", 22, False),
            ("We inject +200 ms delay and compare Sync / Async / RTC.", 22, False),
        ],
        14.0,
    )
    segments.append((p, "If the robot waits, motion stalls. We measure that on AMD ROCm."))

    p = OUT_DIR / "03_method.mp4"
    make_card(
        p,
        [
            ("Method on one Radeon GPU", 34, True),
            ("A: Fine-tune SmolVLA and π0.5 on synthetic demos", 22, False),
            ("B: Latency-aware executors — Sync / Async / RTC", 22, False),
            ("Task: pick fruit → place in basket (Genesis Franka)", 22, False),
            ("Paired seeds · GPU render only · frozen formal JSON", 18, False),
        ],
        14.0,
    )
    segments.append((p, "We fine-tune on AMD and execute with latency-aware chunking."))

    p = OUT_DIR / "04_expert.mp4"
    normalize_clip(
        CLIPS["expert"],
        p,
        max_s=None,
        caption="Expert demo: pick fruit and place in basket",
        label="Env-A expert",
    )
    segments.append((p, "Task: pick the fruit and place it in the basket."))

    p = OUT_DIR / "05_smol_ok_a.mp4"
    normalize_clip(
        CLIPS["smol_ok_a"],
        p,
        max_s=20.0,
        caption="SmolVLA Sync · native delay · place success",
        label="B0 SmolVLA Sync  ep005",
    )
    segments.append((p, "SmolVLA Sync places successfully at native AMD latency."))

    p = OUT_DIR / "05_smol_ok_b.mp4"
    normalize_clip(
        CLIPS["smol_ok_b"],
        p,
        max_s=18.0,
        caption="Second success · formal Sync-full score: 2/20 place",
        label="B0 SmolVLA Sync  ep016",
    )
    segments.append((p, "Formal Sync-full result: two place successes out of twenty."))

    p = OUT_DIR / "06_sync_d200.mp4"
    normalize_clip(
        CLIPS["sync_d200"],
        p,
        max_s=18.0,
        caption="+200 ms · Sync freezes while waiting for chunks",
        label="Sync +200 ms",
    )
    segments.append((p, "Same protocol at +200 ms: Sync freezes on every replan."))

    p = OUT_DIR / "06b_sync_d200.mp4"
    normalize_clip(
        CLIPS["sync_d200_b"],
        p,
        max_s=14.0,
        caption="Sync +200 ms collapses to 0/20 place (freeze-on-replan)",
        label="Sync +200 ms",
    )
    segments.append((p, "Under delay, Sync place success collapses to zero."))

    p = OUT_DIR / "07_async_ok.mp4"
    normalize_clip(
        CLIPS["async_ok"],
        p,
        max_s=22.0,
        caption="+200 ms · Async queue keeps moving · 1/20 place, 4/20 lift",
        label="Async +200 ms  ep016",
    )
    segments.append((p, "Async keeps acting while the next chunk is computed."))

    p = OUT_DIR / "08_rtc_note.mp4"
    make_card(
        p,
        [
            ("RTC vs Async — honest result", 34, True),
            ("RTC E=10 @ +200 ms: 0/20 place (continuous, freeze=0)", 20, False),
            ("Async E=10 @ +200 ms: 1/20 place · 4/20 lift", 20, False),
            ("Main lever here: do not stall — not guidance alone", 20, False),
        ],
        14.0,
    )
    segments.append(
        (p, "On this static task, Async beats RTC on place. We report that honestly.")
    )

    p = OUT_DIR / "08b_rtc_clip.mp4"
    normalize_clip(
        CLIPS["rtc_fail"],
        p,
        max_s=16.0,
        caption="RTC continuous motion · guidance ≤ Async on place",
        label="RTC +200 ms",
    )
    segments.append(
        (p, "RTC removes freezes, but guidance did not raise place success.")
    )

    p = OUT_DIR / "09_pi05_card.mp4"
    make_card(
        p,
        [
            ("π0.5 adaptation on AMD", 34, True),
            ("Expert-only fine-tune: 0/20 place (never grasped)", 22, False),
            ("B1d: unfreeze vision + full train → 1/20 place", 22, False),
            ("Peak train VRAM: 32.3 GB on the 48 GB Radeon", 20, False),
        ],
        12.0,
    )
    segments.append(
        (p, "Expert-only π0.5 failed; unfreezing vision unlocked a place.")
    )

    p = OUT_DIR / "09b_pi05_ok.mp4"
    normalize_clip(
        CLIPS["pi05_ok"],
        p,
        max_s=16.0,
        caption="π0.5 B1d Sync · first closed-loop place success",
        label="π0.5 B1d Sync  ep003",
    )
    segments.append((p, "Here is the π0.5 B1d place success under Sync-full."))

    p = OUT_DIR / "09c_envb_card.mp4"
    make_card(
        p,
        [
            ("Env-B: held-out runtime shift", 34, True),
            ("Same seed nominal poses as Env-A, then |Δxy| ∼ U[3,5] cm", 20, False),
            ("Never in training · basket fixed · Sync-full only", 20, False),
            ("Result: SmolVLA & π0.5 place → 0/20 (pose-sensitive)", 20, False),
        ],
        11.0,
    )
    segments.append(
        (p, "Env-B shifts the fruit 3 to 5 centimeters at eval time only.")
    )

    p = OUT_DIR / "09d_envb_fail.mp4"
    normalize_clip(
        CLIPS["envb_fail"],
        p,
        max_s=14.0,
        caption="Same ep003 pose + 4.9 cm shift · place fails (paired)",
        label="Env-B  π0.5 B1d  ep003",
    )
    segments.append(
        (p, "The Env-A place winner fails under its paired Env-B shift.")
    )

    p = OUT_DIR / "10_fig_latency.mp4"
    make_figure_slide(CLIPS["fig_latency"], p, "Latency story (SmolVLA)", 10.0)
    segments.append((p, "Under +200 ms, Async recovers place and lift versus Sync freeze."))

    p = OUT_DIR / "10b_fig_rtc.mp4"
    make_figure_slide(CLIPS["fig_rtc"], p, "RTC story — place success", 8.0)
    segments.append((p, "RTC continuity helps; place success stays below Async here."))

    p = OUT_DIR / "10c_fig_pi05.mp4"
    make_figure_slide(CLIPS["fig_pi05"], p, "π0.5 optimization unlocks grasp", 8.0)
    segments.append((p, "Vision unfreeze is what unlocked π0.5 closed-loop grasp."))

    p = OUT_DIR / "10d_fig_envb.mp4"
    make_figure_slide(CLIPS["fig_envb"], p, "Env-A vs Env-B (held-out shift)", 9.0)
    segments.append((p, "Held-out 3–5 cm shift zeros place for both policies."))

    p = OUT_DIR / "11_results.mp4"
    make_card(
        p,
        [
            ("Frozen formal results (seed=99)", 32, True),
            ("SmolVLA Sync native: 2/20 · +200 Async: 1/20 place", 18, False),
            ("π0.5 expert-only 0/20 → B1d 1/20 place", 18, False),
            ("Env-B (3–5 cm): both policies 0/20 place", 18, False),
            ("Chunk P50 ≈ 305 / 343 ms · B1d train VRAM 32.3 GB", 18, False),
        ],
        14.0,
    )
    segments.append((p, "Numbers from frozen formal eval — no invented gains."))

    p = OUT_DIR / "12_end.mp4"
    make_card(
        p,
        [
            ("Full loop on one AMD Radeon (48 GB)", 30, True),
            ("Data · Train · Infer · Eval — all on ROCm", 22, False),
            ("artifacts/technical-report.pdf", 18, False),
            ("artifacts/demo-video.mp4  +  README.md", 18, False),
            ("Track 3, Latency-Aware VLA", 24, True),
        ],
        10.0,
    )
    segments.append(
        (p, "Code, technical report, and demo video are in the submission.")
    )

    srt_entries = []
    t = 0.0
    concat_list = OUT_DIR / "concat.txt"
    lines = []
    for path, sub in segments:
        dur = probe(path)
        srt_entries.append((t, t + dur, sub))
        t += dur
        lines.append(f"file '{path.resolve()}'\n")
    concat_list.write_text("".join(lines))
    write_srt(srt_entries, SRT)

    tmp = OUT_DIR / "concat_raw.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(FPS),
            str(tmp),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    FINAL.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(tmp),
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20",
            "-movflags", "+faststart",
            str(FINAL),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    meta = {
        "output": str(FINAL),
        "srt": str(SRT),
        "duration_s": t,
        "duration_min": round(t / 60, 2),
        "segments": [
            {"file": str(p), "subtitle": s, "t0": a, "t1": b}
            for (a, b, s), (p, _) in zip(srt_entries, segments)
        ],
        "target_minutes": "3-5",
        "in_range": 180 <= t <= 300,
    }
    (OUT_DIR / "build_meta.json").write_text(json.dumps(meta, indent=2))
    print(f"[demo] {FINAL} duration={t:.1f}s ({t/60:.2f} min) in_range={meta['in_range']}")
    print(f"[demo] SRT {SRT}")
    if not meta["in_range"]:
        raise SystemExit("duration outside 3–5 min")


if __name__ == "__main__":
    main()
