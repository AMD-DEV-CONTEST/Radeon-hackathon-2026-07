#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from prooflaunch_remix.files import atomic_write_text, sha256_file  # noqa: E402
from prooflaunch_remix.local_campaign_pack import _font  # noqa: E402
from scripts.render_gtm_three_beat_video_challenger import _extract_frame, _rms_difference, _run, _seal  # noqa: E402


FFMPEG = ROOT.parent / "tapnow-libtv-local-studio/backend-node/node_modules/ffmpeg-static/ffmpeg"
AUDIO_RECEIPT = ROOT / "artifacts/gtm-last-mile-pk-v1/claim-trial-audio-v1/audio-candidate-receipt.json"
AUDIO = ROOT / "artifacts/gtm-last-mile-pk-v1/claim-trial-audio-v1/master/voice-founder-c-48k-stereo-24bit.wav"
SCENE = ROOT / "artifacts/gtm-last-mile-pk-v1/claim-trial-share-card-v2/performance-review-scene.png"
CARD_RECEIPT = ROOT / "artifacts/gtm-last-mile-pk-v1/claim-trial-share-card-v2/receipt.json"
PLAN = ROOT / "artifacts/gtm-last-mile-pk-v1/claim-trial-gtm-system-v2/video-15s.json"
OUTPUT = ROOT / "artifacts/gtm-last-mile-pk-v1/claim-trial-video-v2"
SIZE = (2160, 3840)
INK = (8, 8, 7)
PAPER = (246, 239, 222)
ACID = (202, 255, 0)
RED = (255, 78, 56)


def cover(source: Image.Image, *, center: tuple[float, float], brightness: float = 0.64) -> Image.Image:
    image = ImageOps.fit(source, SIZE, method=Image.Resampling.LANCZOS, centering=center)
    image = ImageEnhance.Contrast(image).enhance(1.12)
    image = ImageEnhance.Brightness(image).enhance(brightness)
    return image


def top_rule(draw: ImageDraw.ImageDraw, *, scene: int) -> None:
    draw.line((110, 150, 2050, 150), fill=PAPER, width=5)
    draw.text((110, 75), "PROOFLAUNCH / PERFORMANCE REVIEW", font=_font(39, bold=True), fill=PAPER)
    draw.text((1790, 80), f"0{scene} / 06", font=_font(32, bold=True), fill=ACID)


def super_text(draw: ImageDraw.ImageDraw, lines: list[tuple[str, tuple[int, int, int]]], *, y: int, size: int) -> None:
    top = y
    for text, color in lines:
        draw.text((105, top), text, font=_font(size, bold=True), fill=color, stroke_width=1, stroke_fill=color)
        top += int(size * .79)


def scene_frames(source: Image.Image) -> list[Image.Image]:
    scenes: list[Image.Image] = []

    image = cover(source, center=(.32, .36), brightness=.57)
    draw = ImageDraw.Draw(image)
    top_rule(draw, scene=1)
    super_text(draw, [("OUR AI APPLIED", PAPER), ("FOR A 4A JOB.", ACID)], y=310, size=205)
    draw.text((110, 3420), "THE PERFORMANCE REVIEW STARTS WITH ITS OWN CLAIM.", font=_font(49, bold=True), fill=PAPER)
    scenes.append(image)

    image = cover(source, center=(.45, .68), brightness=.68)
    draw = ImageDraw.Draw(image)
    top_rule(draw, scene=2)
    draw.rounded_rectangle((105, 300, 2055, 1370), radius=22, fill=(8, 8, 7, 230), outline=ACID, width=8)
    super_text(draw, [("26", ACID), ("PLATFORM", PAPER), ("CANDIDATES.", PAPER)], y=390, size=230)
    draw.text((110, 3430), "MORE OUTPUT WAS NOT THE MISSING CAPABILITY.", font=_font(48, bold=True), fill=PAPER)
    scenes.append(image)

    image = cover(source, center=(.30, .70), brightness=.53)
    draw = ImageDraw.Draw(image)
    top_rule(draw, scene=3)
    draw.rectangle((80, 520, 2080, 1830), fill=RED)
    super_text(draw, [("25", INK), ("WENT", INK), ("BACK.", INK)], y=630, size=270)
    draw.text((110, 3430), "RETURN THE WORK BEFORE HUMANS PAY THE REVIEW TAX.", font=_font(45, bold=True), fill=PAPER)
    scenes.append(image)

    image = cover(source, center=(.70, .66), brightness=.74)
    image = image.filter(ImageFilter.GaussianBlur(radius=.35))
    draw = ImageDraw.Draw(image)
    top_rule(draw, scene=4)
    draw.rounded_rectangle((105, 430, 2055, 1790), radius=28, fill=(244, 237, 220), outline=INK, width=10)
    super_text(draw, [("1 IDEA", INK), ("EARNED", INK), ("HUMAN REVIEW.", RED)], y=590, size=185)
    draw.text((110, 3430), "ADMITTED TO REVIEW IS NOT THE SAME AS WINNING.", font=_font(45, bold=True), fill=PAPER)
    scenes.append(image)

    image = Image.new("RGB", SIZE, RED)
    draw = ImageDraw.Draw(image)
    draw.line((110, 150, 2050, 150), fill=INK, width=5)
    draw.text((110, 75), "PROOFLAUNCH / CLAIM TRIAL", font=_font(39, bold=True), fill=INK)
    draw.text((1790, 80), "05 / 06", font=_font(32, bold=True), fill=INK)
    super_text(draw, [("0 WITNESSES.", INK), ("0 WINS", INK), ("CLAIMED.", INK)], y=510, size=245)
    draw.rectangle((105, 2530, 2055, 3160), fill=INK)
    draw.text((165, 2690), "PREFERENCE — MISSING\nBREAKOUT — MISSING\nCONVERSION — MISSING\nREVENUE — MISSING", font=_font(62, bold=True), fill=PAPER, spacing=28)
    scenes.append(image)

    image = Image.new("RGB", SIZE, INK)
    draw = ImageDraw.Draw(image)
    draw.line((110, 150, 2050, 150), fill=PAPER, width=5)
    draw.text((110, 75), "PROOFLAUNCH / PUBLIC PERFORMANCE REVIEW", font=_font(39, bold=True), fill=PAPER)
    draw.text((1790, 80), "06 / 06", font=_font(32, bold=True), fill=ACID)
    super_text(draw, [("PUT ONE", PAPER), ("PUBLIC", PAPER), ("SENTENCE", ACID), ("ON TRIAL.", PAPER)], y=520, size=220)
    draw.rounded_rectangle((105, 2780, 2055, 3150), radius=20, fill=ACID)
    draw.text((175, 2900), "B2B/B2C · STAGE · PUBLIC SENTENCE", font=_font(55, bold=True), fill=INK)
    draw.text((110, 3420), "NO DM. NO DECK. NO LEAD FORM.", font=_font(57, bold=True), fill=RED)
    scenes.append(image)
    return scenes


def encode(scene_paths: list[Path], output: Path) -> None:
    filters = []
    for index in range(len(scene_paths)):
        filters.append(
            f"[{index}:v]zoompan=z='min(zoom+0.00034,1.022)':d=60:s=2160x3840:fps=24,"
            f"trim=duration=2.5,setpts=PTS-STARTPTS[v{index}]"
        )
    concat = "".join(f"[v{index}]" for index in range(len(scene_paths))) + f"concat=n={len(scene_paths)}:v=1:a=0,format=yuv420p[v]"
    graph = ";".join([*filters, concat])
    command = [str(FFMPEG), "-y"]
    for scene in scene_paths:
        command += ["-loop", "1", "-i", str(scene)]
    command += [
        "-i", str(AUDIO), "-filter_complex", graph, "-map", "[v]", "-map", f"{len(scene_paths)}:a:0",
        "-t", "15", "-r", "24", "-c:v", "h264_videotoolbox", "-b:v", "24M", "-c:a", "aac", "-b:a", "320k",
        "-movflags", "+faststart", str(output),
    ]
    result = _run(command, timeout=1200)
    if result.returncode != 0 or not output.is_file() or output.stat().st_size < 1024:
        output.unlink(missing_ok=True)
        command[command.index("h264_videotoolbox")] = "libx264"
        at = command.index("-b:v")
        command[at:at + 2] = ["-crf", "18"]
        result = _run(command, timeout=1800)
    if result.returncode != 0 or not output.is_file() or output.stat().st_size < 1024:
        raise RuntimeError(result.stderr[-3000:])


def duration(video: Path) -> float:
    result = _run([str(FFMPEG), "-hide_banner", "-i", str(video)], timeout=60)
    output = result.stdout + result.stderr
    match = re.search(r"Duration: (\d+):(\d+):([0-9.]+)", output)
    if not match or "2160x3840" not in output:
        raise RuntimeError("video probe failed")
    hour, minute, second = match.groups()
    return int(hour) * 3600 + int(minute) * 60 + float(second)


def main() -> None:
    if OUTPUT.exists() and any(OUTPUT.iterdir()):
        raise SystemExit("output directory must be empty")
    for path in (FFMPEG, AUDIO_RECEIPT, AUDIO, SCENE, CARD_RECEIPT, PLAN):
        if not path.is_file():
            raise SystemExit(f"missing video V2 dependency: {path}")
    audio_receipt = json.loads(AUDIO_RECEIPT.read_text(encoding="utf-8"))
    selected = next(row for row in audio_receipt["candidates"] if row["candidate_id"] == "voice-founder-c")
    if selected["master"]["sha256"] != sha256_file(AUDIO):
        raise SystemExit("voice founder candidate binding drifted")
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    if len(plan["scenes"]) != 6 or plan["duration_seconds"] != 15:
        raise SystemExit("video plan contract drifted")
    OUTPUT.mkdir(parents=True, mode=0o700)
    scene_root = OUTPUT / "scenes"
    audit_root = OUTPUT / "audit-frames"
    scene_root.mkdir(mode=0o700)
    audit_root.mkdir(mode=0o700)
    with Image.open(SCENE) as source_image:
        images = scene_frames(source_image.convert("RGB"))
    scene_paths = []
    for index, image in enumerate(images, 1):
        path = scene_root / f"scene-{index:02d}.png"
        image.save(path, format="PNG", optimize=True)
        scene_paths.append(path)
    video = OUTPUT / "prooflaunch-performance-review-vertical-4k.mp4"
    encode(scene_paths, video)
    audits = []
    for stamp in (1.0, 3.5, 6.0, 8.5, 11.0, 13.8):
        frame = audit_root / f"frame-{stamp:.1f}.png"
        _extract_frame(FFMPEG, video, stamp, frame)
        audits.append(frame)
    differences = [_rms_difference(left, right) for left, right in zip(audits, audits[1:])]
    if min(differences) < 25:
        raise RuntimeError("six-beat temporal diversity gate failed")
    captions = OUTPUT / "prooflaunch-performance-review.vtt"
    atomic_write_text(captions, "WEBVTT\n\n00:00.000 --> 00:15.000\n" + audio_receipt["frozen_script"] + "\n")
    payload = {
        "schema": "ProofLaunchClaimTrialVideoReceiptV2",
        "creative_concept": "AI Employee Performance Review",
        "video": {"path": video.relative_to(ROOT).as_posix(), "sha256": sha256_file(video), "bytes": video.stat().st_size, "duration_seconds": duration(video), "width": 2160, "height": 3840},
        "audio": {"path": AUDIO.relative_to(ROOT).as_posix(), "sha256": sha256_file(AUDIO), "candidate_id": selected["candidate_id"], "human_listening_review_status": "pending"},
        "scene_count": len(scene_paths),
        "scenes": [{"path": path.relative_to(ROOT).as_posix(), "sha256": sha256_file(path)} for path in scene_paths],
        "audit_frames": [{"path": path.relative_to(ROOT).as_posix(), "sha256": sha256_file(path)} for path in audits],
        "adjacent_beat_rms_differences": differences,
        "video_plan_sha256": sha256_file(PLAN),
        "share_card_receipt_sha256": sha256_file(CARD_RECEIPT),
        "mechanical_gate_passed": True,
        "human_hook_review_count": 0,
        "human_listening_review_count": 0,
        "external_publish_executed": False,
        "production_effect_observed": False,
        "named_product_win_count": 0,
        "truth_boundary": "This is a locally rendered 4K vertical campaign master with six inspectable beats and an unselected human-listening candidate. It proves no human preference, retention, organic breakout, conversion, revenue, 4A quality or named-product superiority.",
    }
    sealed = _seal(payload)
    atomic_write_text(OUTPUT / "receipt.json", json.dumps(sealed, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(video), "bytes": video.stat().st_size, "content_sha256": sealed["content_sha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()
