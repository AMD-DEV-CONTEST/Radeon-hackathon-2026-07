#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from prooflaunch_remix.files import atomic_write_text, sha256_file
from prooflaunch_remix.local_campaign_pack import _font
from scripts.render_gtm_three_beat_video_challenger import _extract_frame, _rms_difference, _run, _seal


AUDIO_RECEIPT = ROOT / "artifacts/gtm-last-mile-pk-v1/claim-trial-audio-v1/audio-candidate-receipt.json"
AUDIO = ROOT / "artifacts/gtm-last-mile-pk-v1/claim-trial-audio-v1/master/voice-cross-examiner-a-48k-stereo-24bit.wav"
BRIEF = ROOT / "evidence/v10/prooflaunch-front-stage-brief-v1.json"
FFMPEG = ROOT.parent / "tapnow-libtv-local-studio/backend-node/node_modules/ffmpeg-static/ffmpeg"
OUTPUT = ROOT / "artifacts/gtm-last-mile-pk-v1/claim-trial-video-v1"
SIZE = (2160, 3840)
PAPER = (241, 238, 229)
INK = (9, 9, 8)
RED = (255, 86, 63)
ACID = (232, 255, 54)
BLUE = (61, 90, 254)


def label(draw: ImageDraw.ImageDraw, left: int, top: int, text: str) -> None:
    draw.text((left, top), text, font=_font(43, bold=True), fill=INK)


def brand(draw: ImageDraw.ImageDraw) -> None:
    draw.line((110, 150, 2050, 150), fill=INK, width=8)
    draw.text((110, 74), "PROOFLAUNCH / CLAIM TRIAL", font=_font(39, bold=True), fill=INK)
    draw.text((1680, 79), "SELF-TRIAL 001", font=_font(32, bold=True), fill=INK)


def scene_one() -> Image.Image:
    image = Image.new("RGB", SIZE, PAPER)
    draw = ImageDraw.Draw(image)
    brand(draw)
    label(draw, 110, 440, "WE ASKED OUR OWN AI TO PROVE IT")
    draw.multiline_text((105, 650), "PROVE\nYOU’RE 4A.", font=_font(238, bold=True), fill=INK, spacing=-20)
    draw.rectangle((105, 1770, 2055, 2590), fill=PAPER, outline=INK, width=10)
    draw.multiline_text(
        (185, 1930),
        "“A 4A-grade GTM employee\nthat makes any brand go viral.”",
        font=_font(91), fill=INK, spacing=28,
    )
    draw.rectangle((105, 3170, 2055, 3530), fill=INK)
    draw.text((160, 3273), "THE CLAIM ENTERS UNDER OATH", font=_font(67, bold=True), fill=(255, 255, 255))
    return image


def scene_two() -> Image.Image:
    image = Image.new("RGB", SIZE, RED)
    draw = ImageDraw.Draw(image)
    brand(draw)
    label(draw, 110, 440, "VERDICT")
    draw.multiline_text((105, 650), "NO\nWITNESS.", font=_font(278, bold=True), fill=INK, spacing=-24)
    rows = (
        ("INDEPENDENT PREFERENCE", "MISSING"),
        ("OBSERVED ORGANIC BREAKOUT", "MISSING"),
        ("CONVERSION", "MISSING"),
        ("REVENUE", "MISSING"),
    )
    top = 2060
    for name, status in rows:
        draw.line((110, top, 2050, top), fill=INK, width=6)
        draw.text((110, top + 55), name, font=_font(54, bold=True), fill=INK)
        draw.text((1650, top + 55), status, font=_font(54, bold=True), fill=INK)
        top += 265
    draw.line((110, top, 2050, top), fill=INK, width=6)
    return image


def scene_three(brief: dict[str, Any]) -> Image.Image:
    image = Image.new("RGB", SIZE, PAPER)
    draw = ImageDraw.Draw(image)
    brand(draw)
    label(draw, 110, 430, "THE VERSION THE EVIDENCE CAN CARRY")
    draw.rounded_rectangle((105, 620, 2055, 2160), radius=32, fill=ACID, outline=INK, width=10)
    draw.multiline_text(
        (190, 770),
        "ProofLaunch turns\napproved product evidence\ninto an inspectable,\nhuman-governed GTM\nworkspace and campaign\ndraft pack.",
        font=_font(100, bold=True), fill=INK, spacing=22,
    )
    draw.rectangle((105, 2440, 2055, 3030), fill=BLUE, outline=INK, width=10)
    draw.multiline_text((180, 2570), "PUT YOUR CLAIM\nON TRIAL.", font=_font(150, bold=True), fill=(255, 255, 255), spacing=-2)
    draw.text((110, 3350), "THE MARKET WILL CROSS-EXAMINE IT ANYWAY.", font=_font(53, bold=True), fill=INK)
    return image


def encode(scene_paths: list[Path], output: Path) -> None:
    graph = (
        "[0:v]zoompan=z='min(zoom+0.00024,1.028)':d=120:s=2160x3840:fps=24,trim=duration=5,setpts=PTS-STARTPTS[v0];"
        "[1:v]zoompan=z='min(zoom+0.00020,1.024)':d=120:s=2160x3840:fps=24,trim=duration=5,setpts=PTS-STARTPTS[v1];"
        "[2:v]zoompan=z='min(zoom+0.00018,1.022)':d=144:s=2160x3840:fps=24,trim=duration=6,setpts=PTS-STARTPTS[v2];"
        "[v0][v1]xfade=transition=fadeblack:duration=0.45:offset=4.55[x1];"
        "[x1][v2]xfade=transition=smoothleft:duration=0.45:offset=9.10,format=yuv420p[v]"
    )
    command = [str(FFMPEG), "-y"]
    for scene in scene_paths:
        command += ["-loop", "1", "-i", str(scene)]
    command += ["-i", str(AUDIO), "-filter_complex", graph, "-map", "[v]", "-map", "3:a:0", "-t", "15", "-r", "24", "-c:v", "h264_videotoolbox", "-b:v", "22M", "-c:a", "aac", "-b:a", "320k", "-movflags", "+faststart", str(output)]
    result = _run(command, timeout=900)
    if result.returncode != 0 or not output.is_file() or output.stat().st_size < 1024:
        output.unlink(missing_ok=True)
        command[command.index("h264_videotoolbox")] = "libx264"
        at = command.index("-b:v")
        command[at:at + 2] = ["-crf", "18"]
        result = _run(command, timeout=1200)
    if result.returncode != 0 or not output.is_file() or output.stat().st_size < 1024:
        raise RuntimeError(result.stderr[-2000:])


def duration(video: Path) -> float:
    result = _run([str(FFMPEG), "-hide_banner", "-i", str(video)], timeout=60)
    match = re.search(r"Duration: (\d+):(\d+):([0-9.]+)", result.stdout + result.stderr)
    if not match or "2160x3840" not in result.stdout + result.stderr:
        raise RuntimeError("video probe failed")
    hour, minute, second = match.groups()
    return int(hour) * 3600 + int(minute) * 60 + float(second)


def main() -> None:
    if OUTPUT.exists() and any(OUTPUT.iterdir()):
        raise SystemExit("output directory must be empty")
    for required in (AUDIO_RECEIPT, AUDIO, BRIEF, FFMPEG):
        if not required.is_file():
            raise SystemExit(f"missing required source: {required}")
    receipt = json.loads(AUDIO_RECEIPT.read_text(encoding="utf-8"))
    selected = next(row for row in receipt["candidates"] if row["candidate_id"] == "voice-cross-examiner-a")
    if selected["master"]["sha256"] != sha256_file(AUDIO):
        raise SystemExit("audio binding drifted")
    brief = json.loads(BRIEF.read_text(encoding="utf-8"))
    OUTPUT.mkdir(parents=True, mode=0o700)
    scenes_root = OUTPUT / "scenes"
    audit_root = OUTPUT / "audit-frames"
    scenes_root.mkdir(mode=0o700)
    audit_root.mkdir(mode=0o700)
    images = [scene_one(), scene_two(), scene_three(brief)]
    paths = []
    for index, image in enumerate(images, 1):
        path = scenes_root / f"scene-{index:02d}.png"
        image.save(path, format="PNG", optimize=True)
        paths.append(path)
    video = OUTPUT / "prooflaunch-claim-trial-vertical-4k.mp4"
    encode(paths, video)
    audits = []
    for stamp in (1.0, 6.2, 11.5):
        frame = audit_root / f"frame-{stamp:.1f}.png"
        _extract_frame(FFMPEG, video, stamp, frame)
        audits.append(frame)
    differences = [_rms_difference(audits[0], audits[1]), _rms_difference(audits[1], audits[2])]
    if min(differences) < 35:
        raise RuntimeError("three-beat temporal diversity gate failed")
    captions = OUTPUT / "prooflaunch-claim-trial.vtt"
    atomic_write_text(captions, "WEBVTT\n\n00:00.000 --> 00:15.000\n" + receipt["frozen_script"] + "\n")
    payload = {
        "schema": "ProofLaunchClaimTrialVideoReceiptV1",
        "creative_concept": "Claim Trial",
        "story_beats": ["self-claim enters under oath", "NO WITNESS verdict exposes missing outcome proof", "bounded product truth replaces hype and invites participation"],
        "video": {"path": str(video.relative_to(ROOT)), "sha256": sha256_file(video), "bytes": video.stat().st_size, "duration_seconds": duration(video), "width": 2160, "height": 3840},
        "audio": {"path": str(AUDIO.relative_to(ROOT)), "sha256": sha256_file(AUDIO), "candidate_id": selected["candidate_id"], "human_listening_review_status": "pending"},
        "scenes": [{"path": str(path.relative_to(ROOT)), "sha256": sha256_file(path)} for path in paths],
        "audit_frames": [{"path": str(path.relative_to(ROOT)), "sha256": sha256_file(path)} for path in audits],
        "adjacent_beat_rms_differences": differences,
        "accelerator": "apple_metal_audio_plus_local_deterministic_compositor",
        "mechanical_gate_passed": True,
        "first_three_second_human_hook_reviewed": False,
        "human_preference_observed": False,
        "production_effect_observed": False,
        "completed_named_product_pk_count": 0,
        "named_product_win_count": 0,
        "truth_boundary": "This is a content-addressed internal 4K vertical challenger. It proves local rendering, three distinct beats, audio binding and container mechanics—not human preference, virality, conversion, revenue, 4A quality or named-product superiority."
    }
    sealed = _seal(payload)
    atomic_write_text(OUTPUT / "receipt.json", json.dumps(sealed, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(video), "bytes": video.stat().st_size, "content_sha256": sealed["content_sha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()
