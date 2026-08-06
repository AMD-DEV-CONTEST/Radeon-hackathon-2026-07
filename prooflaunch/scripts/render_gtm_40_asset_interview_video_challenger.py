#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageEnhance, ImageOps

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from prooflaunch_remix.files import atomic_write_text, sha256_file
from prooflaunch_remix.local_campaign_pack import _font
from scripts.render_gtm_three_beat_video_challenger import (
    _extract_frame,
    _rms_difference,
    _run,
    _seal,
)


SOURCE = ROOT / "artifacts/gtm-last-mile-pk-v1/image-super-challenger-v1/prooflaunch-rejection-rule-key-visual-v1.png"
AUDIO_RECEIPT = ROOT / "artifacts/gtm-last-mile-pk-v1/audio-candidates-v3-40-asset-interview/audio-candidate-receipt.json"
AUDIO = ROOT / "artifacts/gtm-last-mile-pk-v1/audio-candidates-v3-40-asset-interview/master/voice-interrogator-a-48k-stereo-24bit.wav"
EDITORIAL_RECEIPT = ROOT / "artifacts/gtm-last-mile-pk-v1/platform-native-challengers-v16/b2b-codex-editorial-war-room-receipt.json"
FFMPEG = ROOT.parent / "tapnow-libtv-local-studio/backend-node/node_modules/ffmpeg-static/ffmpeg"
DEFAULT_OUTPUT = ROOT / "artifacts/gtm-last-mile-pk-v1/video-challenger-v8-40-asset-interview"


INK = (4, 7, 16, 255)
PANEL = (8, 11, 25, 242)
WHITE = (249, 249, 253, 255)
MUTED = (190, 194, 214, 255)
PURPLE = (143, 105, 255, 255)
AMBER = (244, 172, 54, 255)
RED = (224, 79, 91, 255)


def _canvas(size: tuple[int, int], *, brightness: float) -> Image.Image:
    with Image.open(SOURCE) as image:
        base = ImageOps.fit(image.convert("RGB"), size, method=Image.Resampling.LANCZOS, centering=(0.72, 0.5))
    base = ImageEnhance.Brightness(base).enhance(brightness).convert("RGBA")
    veil = Image.new("RGBA", size, (4, 7, 16, 152 if size[0] > size[1] else 180))
    base.alpha_composite(veil)
    return base


def _brand(draw: ImageDraw.ImageDraw, size: tuple[int, int]) -> None:
    width, _ = size
    margin = int(width * 0.045)
    badge_width = int(width * (0.18 if width > 2500 else 0.34))
    height = int(width * 0.03 if width > 2500 else width * 0.065)
    draw.rounded_rectangle((margin, margin, margin + badge_width, margin + height), radius=height // 2, fill=PURPLE)
    draw.text((margin + int(height * 0.42), margin + int(height * 0.18)), "PROOFLAUNCH", font=_font(max(28, int(height * 0.34)), bold=True), fill=WHITE)


def _footer(draw: ImageDraw.ImageDraw, size: tuple[int, int], text: str) -> None:
    width, height = size
    margin = int(width * 0.045)
    panel_height = int(height * 0.10)
    y = height - margin - panel_height
    draw.rounded_rectangle((margin, y, width - margin, height - margin), radius=max(28, int(width * 0.012)), fill=PANEL, outline=PURPLE, width=max(3, width // 1100))
    draw.text((margin + int(width * 0.025), y + int(panel_height * 0.31)), text, font=_font(max(34, int(width * 0.015)), bold=True), fill=WHITE)


def _card_grid(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], *, selected: int = 27) -> None:
    left, top, right, bottom = box
    cols, rows = 8, 5
    gap = max(12, int((right - left) * 0.012))
    card_w = int((right - left - gap * (cols - 1)) / cols)
    card_h = int((bottom - top - gap * (rows - 1)) / rows)
    for index in range(cols * rows):
        x = left + (index % cols) * (card_w + gap)
        y = top + (index // cols) * (card_h + gap)
        active = index == selected
        draw.rounded_rectangle(
            (x, y, x + card_w, y + card_h),
            radius=max(12, card_w // 14),
            fill=(19, 23, 40, 244) if not active else (42, 34, 19, 250),
            outline=AMBER if active else (119, 56, 69, 235),
            width=max(2, card_w // 50),
        )
        if active:
            draw.text((x + card_w * 0.15, y + card_h * 0.35), "REVIEW", font=_font(max(18, int(card_w * 0.14)), bold=True), fill=AMBER)
        else:
            draw.line((x + card_w * 0.24, y + card_h * 0.30, x + card_w * 0.76, y + card_h * 0.70), fill=RED, width=max(3, card_w // 24))
            draw.line((x + card_w * 0.76, y + card_h * 0.30, x + card_w * 0.24, y + card_h * 0.70), fill=RED, width=max(3, card_w // 24))


def _landscape_scenes() -> tuple[Image.Image, Image.Image, Image.Image]:
    size = (3840, 2160)
    first = _canvas(size, brightness=0.52)
    draw = ImageDraw.Draw(first)
    _brand(draw, size)
    draw.text((175, 370), "40 ASSETS ISN’T THE TEST.", font=_font(116, bold=True), fill=WHITE)
    draw.text((175, 510), "WHICH 39 SHOULD NEVER SHIP?", font=_font(118, bold=True), fill=AMBER)
    _card_grid(draw, (175, 760, 2450, 1570))
    draw.text((2640, 870), "39", font=_font(205, bold=True), fill=RED)
    draw.text((2640, 1100), "BLOCKED", font=_font(70, bold=True), fill=WHITE)
    draw.text((2640, 1265), "1", font=_font(205, bold=True), fill=AMBER)
    draw.text((2890, 1340), "EARNS REVIEW", font=_font(54, bold=True), fill=WHITE)
    _footer(draw, size, "Output volume is not release judgment.")

    second = _canvas(size, brightness=0.44)
    draw = ImageDraw.Draw(second)
    _brand(draw, size)
    draw.text((175, 340), "RUN THE 40-ASSET INTERVIEW.", font=_font(114, bold=True), fill=WHITE)
    lanes = (("FACT", "SOURCE PRESENT", PURPLE), ("INFERENCE", "EDITORIAL JUDGMENT", (98, 148, 255, 255)), ("HYPOTHESIS", "OUTCOME NOT OBSERVED", AMBER), ("BLOCKED", "NO OWNER OR EVIDENCE", RED))
    for index, (label, detail, color) in enumerate(lanes):
        y = 620 + index * 245
        draw.rounded_rectangle((175, y, 2300, y + 175), radius=38, fill=PANEL, outline=color, width=4)
        draw.text((240, y + 42), label, font=_font(52, bold=True), fill=color)
        draw.text((780, y + 54), detail, font=_font(42, bold=True), fill=WHITE)
    draw.rounded_rectangle((2500, 650, 3590, 1530), radius=54, fill=(5, 8, 18, 242), outline=AMBER, width=4)
    draw.multiline_text((2600, 760), "‘TURN INTEREST\nINTO QUALIFIED\nPIPELINE.’", font=_font(63, bold=True), fill=WHITE, spacing=24)
    draw.text((2600, 1240), "HYPOTHESIS", font=_font(60, bold=True), fill=AMBER)
    draw.text((2600, 1345), "Evidence object: —", font=_font(40), fill=MUTED)
    _footer(draw, size, "If evidence or authority is blank, the sentence stops.")

    third = _canvas(size, brightness=0.66)
    draw = ImageDraw.Draw(third)
    _brand(draw, size)
    draw.text((175, 390), "ONE CARD EARNS REVIEW.", font=_font(124, bold=True), fill=WHITE)
    draw.text((175, 545), "39 REJECTIONS WERE USEFUL WORK.", font=_font(108, bold=True), fill=PURPLE)
    draw.rounded_rectangle((175, 850, 2240, 1450), radius=60, fill=(13, 16, 31, 248), outline=AMBER, width=5)
    draw.text((270, 955), "SUPPORTED CLAUSE", font=_font(48, bold=True), fill=AMBER)
    draw.multiline_text((270, 1060), "Compiles a rights-bound brief\ninto review-ready GTM assets.", font=_font(64, bold=True), fill=WHITE, spacing=24)
    draw.text((270, 1320), "RELEASE OWNER · HUMAN", font=_font(40, bold=True), fill=MUTED)
    _footer(draw, size, "Inspect the proof. Challenge the gap. Approve manually.")
    return first.convert("RGB"), second.convert("RGB"), third.convert("RGB")


def _vertical_scenes() -> tuple[Image.Image, Image.Image, Image.Image]:
    size = (2160, 3840)
    scenes = []
    first = _canvas(size, brightness=0.48)
    draw = ImageDraw.Draw(first)
    _brand(draw, size)
    draw.multiline_text((100, 510), "40 ASSETS\nISN’T THE TEST.", font=_font(118, bold=True), fill=WHITE, spacing=14)
    draw.multiline_text((100, 860), "WHICH 39\nSHOULD NEVER SHIP?", font=_font(104, bold=True), fill=AMBER, spacing=14)
    _card_grid(draw, (100, 1380, 2060, 2920), selected=27)
    draw.text((120, 3060), "39 BLOCKED  ·  1 EARNS REVIEW", font=_font(55, bold=True), fill=WHITE)
    _footer(draw, size, "Output volume is not release judgment.")
    scenes.append(first.convert("RGB"))

    second = _canvas(size, brightness=0.40)
    draw = ImageDraw.Draw(second)
    _brand(draw, size)
    draw.multiline_text((100, 500), "RUN THE\nINTERVIEW.", font=_font(132, bold=True), fill=WHITE, spacing=14)
    lanes = (("FACT", PURPLE), ("INFERENCE", (98, 148, 255, 255)), ("HYPOTHESIS", AMBER), ("BLOCKED", RED))
    for index, (label, color) in enumerate(lanes):
        y = 1150 + index * 360
        draw.rounded_rectangle((100, y, 2060, y + 260), radius=50, fill=PANEL, outline=color, width=5)
        draw.text((180, y + 66), label, font=_font(68, bold=True), fill=color)
    draw.rounded_rectangle((100, 2700, 2060, 3210), radius=54, fill=(5, 8, 18, 248), outline=AMBER, width=5)
    draw.multiline_text((180, 2805), "‘TURN INTEREST INTO\nQUALIFIED PIPELINE.’", font=_font(65, bold=True), fill=WHITE, spacing=18)
    draw.text((180, 3050), "HYPOTHESIS · NO OBSERVED SOURCE", font=_font(40, bold=True), fill=AMBER)
    _footer(draw, size, "Blank evidence means stop.")
    scenes.append(second.convert("RGB"))

    third = _canvas(size, brightness=0.62)
    draw = ImageDraw.Draw(third)
    _brand(draw, size)
    draw.multiline_text((100, 520), "ONE CARD\nEARNS REVIEW.", font=_font(132, bold=True), fill=WHITE, spacing=14)
    draw.multiline_text((100, 940), "39 REJECTIONS\nWERE USEFUL WORK.", font=_font(92, bold=True), fill=PURPLE, spacing=14)
    draw.rounded_rectangle((100, 1580, 2060, 2730), radius=70, fill=(13, 16, 31, 250), outline=AMBER, width=6)
    draw.text((190, 1760), "SUPPORTED CLAUSE", font=_font(54, bold=True), fill=AMBER)
    draw.multiline_text((190, 1930), "Compiles a rights-bound\nbrief into review-ready\nGTM assets.", font=_font(76, bold=True), fill=WHITE, spacing=22)
    draw.text((190, 2520), "RELEASE OWNER · HUMAN", font=_font(47, bold=True), fill=MUTED)
    _footer(draw, size, "Inspect. Challenge. Approve manually.")
    scenes.append(third.convert("RGB"))
    return tuple(scenes)  # type: ignore[return-value]


def _encode(scenes: list[Path], output: Path, *, width: int, height: int) -> None:
    filter_graph = (
        f"[0:v]scale={width}:{height},zoompan=z='min(zoom+0.00030,1.036)':d=120:s={width}x{height}:fps=24,trim=duration=5,setpts=PTS-STARTPTS[v0];"
        f"[1:v]scale={width}:{height},zoompan=z='min(zoom+0.00026,1.032)':d=120:s={width}x{height}:fps=24,trim=duration=5,setpts=PTS-STARTPTS[v1];"
        f"[2:v]scale={width}:{height},zoompan=z='min(zoom+0.00022,1.030)':d=138:s={width}x{height}:fps=24,trim=duration=5.72,setpts=PTS-STARTPTS[v2];"
        "[v0][v1]xfade=transition=fadeblack:duration=0.5:offset=4.5[x1];"
        "[x1][v2]xfade=transition=smoothleft:duration=0.5:offset=9.0,format=yuv420p[v]"
    )
    command = [str(FFMPEG), "-y"]
    for scene in scenes:
        command.extend(("-loop", "1", "-i", str(scene)))
    command.extend(("-i", str(AUDIO), "-filter_complex", filter_graph, "-map", "[v]", "-map", "3:a:0", "-t", "14.72", "-r", "24", "-c:v", "h264_videotoolbox", "-b:v", "28M", "-c:a", "aac", "-b:a", "320k", "-movflags", "+faststart", str(output)))
    result = _run(command, timeout=900)
    if result.returncode != 0 or not output.is_file() or output.stat().st_size < 1024:
        output.unlink(missing_ok=True)
        command[command.index("h264_videotoolbox")] = "libx264"
        command[command.index("-b:v"):command.index("-b:v") + 2] = ["-crf", "18"]
        result = _run(command, timeout=1200)
    if result.returncode != 0 or not output.is_file() or output.stat().st_size < 1024:
        raise RuntimeError(result.stderr[-1600:])


def _probe(video: Path, *, width: int, height: int) -> float:
    result = _run([str(FFMPEG), "-hide_banner", "-i", str(video)], timeout=60)
    text = result.stdout + result.stderr
    match = re.search(r"Duration: (\d+):(\d+):([0-9.]+)", text)
    if not match or f"{width}x{height}" not in text:
        raise RuntimeError(f"video probe failed for {video}")
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def render(output: Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    output.resolve().relative_to(ROOT)
    if output.exists() and any(output.iterdir()):
        raise SystemExit("output directory must be empty")
    for path in (SOURCE, AUDIO_RECEIPT, AUDIO, EDITORIAL_RECEIPT, FFMPEG):
        if not path.is_file():
            raise SystemExit(f"required source is missing: {path}")
    audio_receipt = json.loads(AUDIO_RECEIPT.read_text(encoding="utf-8"))
    selected_audio = next(row for row in audio_receipt["candidates"] if row["candidate_id"] == "voice-interrogator-a")
    if selected_audio["master"]["sha256"] != sha256_file(AUDIO):
        raise SystemExit("audio source binding drifted")
    output.mkdir(parents=True, mode=0o700)
    variants: list[dict[str, Any]] = []
    for variant, size, images in (
        ("landscape_4k", (3840, 2160), _landscape_scenes()),
        ("vertical_4k", (2160, 3840), _vertical_scenes()),
    ):
        variant_root = output / variant
        variant_root.mkdir(mode=0o700)
        scene_paths = []
        for index, image in enumerate(images, 1):
            path = variant_root / f"scene-{index:02d}.png"
            image.save(path, format="PNG", optimize=True)
            scene_paths.append(path)
        video = variant_root / f"prooflaunch-40-asset-interview-{variant}.mp4"
        _encode(scene_paths, video, width=size[0], height=size[1])
        audit_root = variant_root / "audit-frames"
        audit_root.mkdir(mode=0o700)
        audit_paths = []
        for stamp in (1.0, 6.5, 11.5):
            path = audit_root / f"frame-{stamp:.1f}.png"
            _extract_frame(FFMPEG, video, stamp, path)
            audit_paths.append(path)
        differences = [_rms_difference(audit_paths[0], audit_paths[1]), _rms_difference(audit_paths[1], audit_paths[2])]
        if min(differences) < 20:
            raise RuntimeError(f"{variant} temporal diversity gate failed")
        variants.append({
            "variant": variant,
            "width": size[0],
            "height": size[1],
            "duration_seconds": _probe(video, width=size[0], height=size[1]),
            "video": {"path": str(video.relative_to(ROOT)), "bytes": video.stat().st_size, "sha256": sha256_file(video)},
            "scenes": [{"path": str(path.relative_to(ROOT)), "bytes": path.stat().st_size, "sha256": sha256_file(path)} for path in scene_paths],
            "audit_frames": [{"path": str(path.relative_to(ROOT)), "sha256": sha256_file(path)} for path in audit_paths],
            "adjacent_beat_rms_differences": differences,
        })
    captions = output / "prooflaunch-40-asset-interview-captions.vtt"
    atomic_write_text(captions, "WEBVTT\n\n00:00.000 --> 00:15.000\n" + audio_receipt["frozen_script"] + "\n")
    payload = {
        "schema": "ProofLaunchGTM40AssetInterviewVideoChallengerV1",
        "scenario_id": "prooflaunch-b2b-ai-launch-zero-budget-v1",
        "creative_concept": "The 40-Asset Interview",
        "story_beats": [
            "tension: forty polished assets expose volume as the wrong hiring test",
            "mechanism: every claim enters fact, inference, hypothesis or blocked",
            "resolution: one source-bound card earns human review while thirty-nine rejections remain useful work",
        ],
        "variants": variants,
        "captions": {"path": str(captions.relative_to(ROOT)), "sha256": sha256_file(captions)},
        "source_bindings": [
            {"role": "rights_clear_visual_world", "path": str(SOURCE.relative_to(ROOT)), "sha256": sha256_file(SOURCE)},
            {"role": "selected_voice_master", "path": str(AUDIO.relative_to(ROOT)), "sha256": sha256_file(AUDIO)},
            {"role": "audio_receipt", "path": str(AUDIO_RECEIPT.relative_to(ROOT)), "sha256": sha256_file(AUDIO_RECEIPT)},
            {"role": "editorial_war_room_receipt", "path": str(EDITORIAL_RECEIPT.relative_to(ROOT)), "sha256": sha256_file(EDITORIAL_RECEIPT)},
        ],
        "new_image_generation_call_count": 0,
        "open_source_modifications": ["Pillow deterministic 4K title-safe compositor", "pinned ffmpeg-static dual-aspect encoder", "existing Qwen3-TTS local VoiceDesign master", "content-addressed source and frame receipts"],
        "mechanical_dual_aspect_three_beat_gate_passed": True,
        "first_three_second_human_hook_reviewed": False,
        "human_preference_observed": False,
        "completed_named_product_pk_count": 0,
        "candidate_win_count": 0,
        "four_a_quality_proven": False,
        "automatic_publish_enabled": False,
        "truth_boundary": "This receipt proves one content-addressed dual-aspect 4K internal challenger and temporal scene diversity. It does not prove generative motion quality, human preference, named-product superiority, 4A quality, publication effect, conversion or revenue.",
    }
    receipt = _seal(payload)
    atomic_write_text(output / "video-challenger-receipt.json", json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(output), "variant_count": len(variants), "content_sha256": receipt["content_sha256"]}, sort_keys=True))
    return receipt


if __name__ == "__main__":
    render()
