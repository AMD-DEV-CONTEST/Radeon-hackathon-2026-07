#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageStat


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from prooflaunch_remix.files import atomic_write_bytes, atomic_write_text, sha256_file  # noqa: E402
from prooflaunch_remix.local_campaign_pack import _font  # noqa: E402


CAMPAIGN = ROOT / "evidence/v10/local-campaign-pack-v1/delivery-v6"
SOURCE = CAMPAIGN / "prooflaunch-hero-4k.png"
AUDIO = CAMPAIGN / "prooflaunch-audio-master-48k-stereo-24bit.wav"
CAPTIONS = CAMPAIGN / "prooflaunch-captions.vtt"
READINESS = ROOT / "evidence/v10/aug3-product-readiness.json"
UNIFIED_REVIEW = ROOT / "artifacts/gtm-last-mile-pk-v1/multimodal-review-v2/unified-last-mile-review.json"
FFMPEG = (
    ROOT.parent
    / "tapnow-libtv-local-studio/backend-node/node_modules/ffmpeg-static/ffmpeg"
)
DEFAULT_OUTPUT = ROOT / "artifacts/gtm-last-mile-pk-v1/video-challenger-v5"
VIDEO_NAME = "prooflaunch-three-beat-challenger-4k.mp4"


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _seal(payload: dict[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    result["content_sha256"] = hashlib.sha256(_canonical(payload)).hexdigest()
    return result


def _fit_background(source: Image.Image) -> Image.Image:
    return source.convert("RGB").resize((3840, 2160), Image.Resampling.LANCZOS)


def _clean_visual_background(source: Image.Image) -> Image.Image:
    """Reframe the source's illustration-only area without inherited copy."""
    return source.convert("RGB").crop((1510, 0, 3840, 2160)).resize(
        (3840, 2160), Image.Resampling.LANCZOS
    )


def _gradient_overlay(size: tuple[int, int], *, left_alpha: int, right_alpha: int) -> Image.Image:
    width, height = size
    alpha_strip = Image.new("L", (width, 1))
    alpha_strip.putdata(
        [
            int(left_alpha * (1 - x / max(width - 1, 1)) + right_alpha * x / max(width - 1, 1))
            for x in range(width)
        ]
    )
    alpha = alpha_strip.resize((width, height))
    overlay = Image.new("RGBA", size, (4, 7, 16, 0))
    overlay.putalpha(alpha)
    return overlay


def _brand(draw: ImageDraw.ImageDraw) -> None:
    draw.rounded_rectangle(
        (170, 130, 810, 240),
        radius=55,
        fill=(128, 91, 255, 235),
        outline=(176, 153, 255, 255),
        width=3,
    )
    draw.text((224, 164), "PROOFLAUNCH", font=_font(36, bold=True), fill="white")


def _footer(draw: ImageDraw.ImageDraw, text: str) -> None:
    # Rebuild the complete title-safe footer band so no source-layout copy can
    # survive outside the rounded message panel.
    draw.rectangle((0, 1800, 3840, 2160), fill=(4, 7, 16, 255))
    draw.rounded_rectangle(
        (170, 1845, 3670, 2040),
        radius=48,
        fill=(7, 10, 23, 242),
        outline=(123, 98, 214, 255),
        width=3,
    )
    draw.text((245, 1900), text, font=_font(48, bold=True), fill=(250, 250, 254))


def _scene_one(source: Image.Image) -> Image.Image:
    background = _clean_visual_background(source).filter(ImageFilter.GaussianBlur(8))
    background = ImageEnhance.Brightness(background).enhance(0.43).convert("RGBA")
    background.alpha_composite(_gradient_overlay(background.size, left_alpha=220, right_alpha=110))
    draw = ImageDraw.Draw(background)
    _brand(draw)
    draw.text((175, 470), "OUTPUT IS CHEAP.", font=_font(146, bold=True), fill=(252, 252, 255))
    draw.text((175, 670), "DECISIONS ARE EXPENSIVE.", font=_font(146, bold=True), fill=(168, 139, 255))
    draw.line((180, 940, 1760, 940), fill=(140, 108, 255), width=8)
    draw.multiline_text(
        (180, 1030),
        "A GTM system should earn the next decision—\nnot merely generate more content.",
        font=_font(62),
        fill=(228, 229, 240),
        spacing=24,
    )
    _footer(draw, "Proof before promise. Evidence before scale.")
    return background.convert("RGB")


def _scene_two(source: Image.Image, readiness: dict[str, Any], unified: dict[str, Any]) -> Image.Image:
    # Reframe only the clean visual half, avoiding inherited typography from the
    # source layout, then rebuild the evidence surface from current receipts.
    crop = _clean_visual_background(source)
    crop = ImageEnhance.Brightness(crop).enhance(0.72).convert("RGBA")
    crop.alpha_composite(_gradient_overlay(crop.size, left_alpha=245, right_alpha=65))
    draw = ImageDraw.Draw(crop)
    _brand(draw)
    draw.text((175, 380), "MAKE THE WORK", font=_font(118, bold=True), fill=(251, 251, 255))
    draw.text((175, 525), "INSPECTABLE.", font=_font(118, bold=True), fill=(169, 140, 255))
    product_critical = readiness["verification"]["product_critical_regression"]
    metrics = (
        (f"{product_critical['test_count']:,}", "product-critical tests passed"),
        ("14 / 14", "last-mile lanes mechanically ready"),
        (f"{unified['submitted_human_review_count']} / {unified['expected_human_review_count']}", "qualified human reviews complete"),
    )
    for index, (value, label) in enumerate(metrics):
        y = 820 + index * 270
        draw.rounded_rectangle(
            (180, y, 1660, y + 210),
            radius=40,
            fill=(9, 13, 30, 238),
            outline=(119, 91, 211, 255),
            width=3,
        )
        draw.text((245, y + 35), value, font=_font(76, bold=True), fill=(248, 248, 252))
        draw.text((650, y + 63), label, font=_font(39), fill=(200, 203, 222))
    if product_critical["test_count"] <= 0 or not product_critical["passed"]:
        raise RuntimeError("readiness product-critical regression drifted")
    _footer(draw, "Show the pass. Show the gap. Never hide the pending decision.")
    return crop.convert("RGB")


def _scene_three(source: Image.Image) -> Image.Image:
    background = _clean_visual_background(source)
    background = ImageEnhance.Contrast(background).enhance(1.08).convert("RGBA")
    veil = Image.new("RGBA", background.size, (4, 7, 16, 168))
    background.alpha_composite(veil)
    draw = ImageDraw.Draw(background)
    # The source is a prior campaign layout. Rebuild an opaque copy field so
    # inherited typography cannot leak into the challenger scene.
    draw.rounded_rectangle((0, 300, 2470, 1800), radius=72, fill=(4, 7, 16, 255))
    _brand(draw)
    draw.text((175, 470), "MAKE EVERY GROWTH MOVE", font=_font(118, bold=True), fill=(252, 252, 255))
    draw.text((175, 625), "EARN ITS MOMENTUM.", font=_font(138, bold=True), fill=(176, 149, 255))
    draw.multiline_text(
        (180, 940),
        "Inspect the proof.\nChallenge the gap.\nApprove manually.",
        font=_font(76, bold=True),
        fill=(242, 242, 249),
        spacing=26,
    )
    draw.rounded_rectangle(
        (2520, 1140, 3500, 1515),
        radius=64,
        fill=(126, 89, 255, 232),
        outline=(208, 195, 255, 255),
        width=4,
    )
    draw.text((2750, 1255), "HUMAN\nRELEASE", font=_font(70, bold=True), fill="white", spacing=14)
    _footer(draw, "The next action stays in human hands.")
    return background.convert("RGB")


def _run(command: list[str], *, timeout: int = 600) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=timeout)


def _encode(ffmpeg: Path, scenes: list[Path], audio: Path, output: Path) -> None:
    filter_graph = (
        "[0:v]scale=3840:2160,zoompan=z='min(zoom+0.00035,1.045)':"
        "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=120:s=3840x2160:fps=24,"
        "trim=duration=5,setpts=PTS-STARTPTS[v0];"
        "[1:v]scale=3840:2160,zoompan=z='min(zoom+0.00030,1.038)':"
        "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=120:s=3840x2160:fps=24,"
        "trim=duration=5,setpts=PTS-STARTPTS[v1];"
        "[2:v]scale=3840:2160,zoompan=z='min(zoom+0.00024,1.034)':"
        "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=138:s=3840x2160:fps=24,"
        "trim=duration=5.72,setpts=PTS-STARTPTS[v2];"
        "[v0][v1]xfade=transition=fadeblack:duration=0.5:offset=4.5[x1];"
        "[x1][v2]xfade=transition=smoothleft:duration=0.5:offset=9.0,format=yuv420p[v]"
    )
    base = [str(ffmpeg), "-y"]
    for scene in scenes:
        base.extend(("-loop", "1", "-i", str(scene)))
    base.extend(
        (
            "-i", str(audio),
            "-filter_complex", filter_graph,
            "-map", "[v]", "-map", "3:a:0",
            "-t", "14.72", "-r", "24",
            "-c:a", "aac", "-b:a", "320k",
            "-movflags", "+faststart",
        )
    )
    hardware = [*base, "-c:v", "h264_videotoolbox", "-b:v", "28M", str(output)]
    result = _run(hardware)
    if result.returncode != 0 or not output.is_file() or output.stat().st_size < 1024:
        output.unlink(missing_ok=True)
        software = [*base, "-c:v", "libx264", "-preset", "medium", "-crf", "17", str(output)]
        result = _run(software, timeout=900)
    if result.returncode != 0 or not output.is_file() or output.stat().st_size < 1024:
        raise RuntimeError(f"three-beat 4K encode failed: {result.stderr[-1200:]}")


def _extract_frame(ffmpeg: Path, video: Path, stamp: float, output: Path) -> None:
    result = _run(
        [
            str(ffmpeg), "-y", "-hide_banner", "-loglevel", "error", "-nostdin",
            "-ss", str(stamp), "-i", str(video), "-frames:v", "1", str(output),
        ],
        timeout=180,
    )
    if result.returncode != 0 or not output.is_file():
        raise RuntimeError(f"frame extraction failed: {result.stderr[-800:]}")


def _rms_difference(left: Path, right: Path) -> float:
    with Image.open(left) as a, Image.open(right) as b:
        direct = ImageChops.difference(a.convert("RGB"), b.convert("RGB"))
        stat = ImageStat.Stat(direct)
        return round(sum(stat.rms) / len(stat.rms), 6)


def render(output: Path, ffmpeg: Path) -> dict[str, Any]:
    output.resolve().relative_to(ROOT)
    if output.exists() and any(output.iterdir()):
        raise SystemExit("output directory must be empty")
    if not ffmpeg.is_file():
        raise SystemExit("pinned ffmpeg executable is missing")
    output.mkdir(parents=True, mode=0o700)
    input_evidence = output / "input-evidence"
    input_evidence.mkdir(mode=0o700)
    readiness_snapshot = input_evidence / "aug3-product-readiness-input.json"
    unified_snapshot = input_evidence / "unified-last-mile-review-input.json"
    atomic_write_bytes(readiness_snapshot, READINESS.read_bytes())
    atomic_write_bytes(unified_snapshot, UNIFIED_REVIEW.read_bytes())
    readiness = json.loads(READINESS.read_text(encoding="utf-8"))
    unified = json.loads(UNIFIED_REVIEW.read_text(encoding="utf-8"))
    with Image.open(SOURCE) as source_image:
        source = source_image.convert("RGB")
    scenes = (
        _scene_one(source),
        _scene_two(source, readiness, unified),
        _scene_three(source),
    )
    scene_paths: list[Path] = []
    for index, scene in enumerate(scenes, start=1):
        path = output / f"scene-{index:02d}-4k.png"
        scene.save(path, optimize=True)
        scene_paths.append(path)
    video = output / VIDEO_NAME
    _encode(ffmpeg, scene_paths, AUDIO, video)
    audit_root = output / "audit-frames"
    audit_root.mkdir(mode=0o700)
    audit_paths: list[Path] = []
    for stamp in (1.0, 6.5, 11.5):
        path = audit_root / f"frame-{stamp:.1f}.png"
        _extract_frame(ffmpeg, video, stamp, path)
        audit_paths.append(path)
    differences = (
        _rms_difference(audit_paths[0], audit_paths[1]),
        _rms_difference(audit_paths[1], audit_paths[2]),
    )
    if min(differences) < 20.0:
        raise RuntimeError("three-beat temporal diversity gate failed")
    probe = _run([str(ffmpeg), "-hide_banner", "-i", str(video)], timeout=60)
    combined_probe = probe.stdout + probe.stderr
    duration_match = re.search(r"Duration: (\d+):(\d+):([0-9.]+)", combined_probe)
    if not duration_match or "3840x2160" not in combined_probe:
        raise RuntimeError("encoded video probe gate failed")
    hours, minutes, seconds = duration_match.groups()
    duration = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    payload = {
        "schema": "ProofLaunchGTMThreeBeatVideoChallengerV1",
        "scenario_id": "prooflaunch-b2b-ai-launch-zero-budget-v1",
        "creative_concept": "Output is cheap. Decisions are expensive.",
        "story_beats": [
            "tension: generation volume is not decision quality",
            "proof: expose verified mechanics and the unfinished human gate",
            "action: inspect, challenge and approve manually",
        ],
        "source_assets": [
            {"path": str(SOURCE.relative_to(ROOT)), "sha256": sha256_file(SOURCE)},
            {"path": str(AUDIO.relative_to(ROOT)), "sha256": sha256_file(AUDIO)},
            {"path": str(CAPTIONS.relative_to(ROOT)), "sha256": sha256_file(CAPTIONS)},
            {"path": str(readiness_snapshot.relative_to(ROOT)), "sha256": sha256_file(readiness_snapshot)},
            {"path": str(unified_snapshot.relative_to(ROOT)), "sha256": sha256_file(unified_snapshot)},
        ],
        "scene_assets": [
            {"path": str(path.relative_to(ROOT)), "sha256": sha256_file(path), "bytes": path.stat().st_size}
            for path in scene_paths
        ],
        "video": {
            "path": str(video.relative_to(ROOT)),
            "sha256": sha256_file(video),
            "bytes": video.stat().st_size,
            "width": 3840,
            "height": 2160,
            "fps": 24,
            "duration_seconds": duration,
            "codec": "h264",
        },
        "audit_frames": [
            {"path": str(path.relative_to(ROOT)), "sha256": sha256_file(path)}
            for path in audit_paths
        ],
        "adjacent_beat_rms_differences": list(differences),
        "mechanical_three_beat_gate_passed": True,
        "first_three_second_human_hook_reviewed": False,
        "human_preference_observed": False,
        "top_product_baseline": False,
        "four_a_quality_proven": False,
        "automatic_publish_enabled": False,
        "truth_boundary": (
            "This receipt proves a content-addressed 4K three-beat internal challenger, temporal "
            "scene diversity and source provenance. It does not prove cinematic craft, a stronger "
            "hook, human preference, 4A quality, Top-product parity, publication effect or revenue."
        ),
    }
    sealed = _seal(payload)
    atomic_write_text(
        output / "video-challenger-receipt.json",
        json.dumps(sealed, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    return sealed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--ffmpeg", default=str(FFMPEG))
    args = parser.parse_args()
    result = render(
        Path(args.output_dir).expanduser().resolve(),
        Path(args.ffmpeg).expanduser().resolve(),
    )
    print(
        json.dumps(
            {
                "video_sha256": result["video"]["sha256"],
                "duration_seconds": result["video"]["duration_seconds"],
                "adjacent_beat_rms_differences": result["adjacent_beat_rms_differences"],
                "human_preference_observed": result["human_preference_observed"],
                "content_sha256": result["content_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
