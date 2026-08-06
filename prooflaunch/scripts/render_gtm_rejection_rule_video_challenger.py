#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageEnhance

from prooflaunch_remix.files import atomic_write_text, sha256_file
from prooflaunch_remix.local_campaign_pack import _font


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.render_gtm_three_beat_video_challenger import (
    _brand,
    _encode,
    _extract_frame,
    _footer,
    _gradient_overlay,
    _rms_difference,
    _run,
    _seal,
)


SOURCE_ROOT = ROOT / "artifacts/gtm-last-mile-pk-v1/image-super-challenger-v1"
BEAT_ONE = SOURCE_ROOT / "rejection-rule-film-beat-01-v1.png"
BEAT_TWO = SOURCE_ROOT / "prooflaunch-rejection-rule-key-visual-v1.png"
BEAT_THREE = SOURCE_ROOT / "rejection-rule-film-beat-03-v1.png"
AUDIO_RECEIPT = ROOT / "artifacts/gtm-last-mile-pk-v1/audio-candidates-v2/audio-candidate-receipt.json"
AUDIO = ROOT / "artifacts/gtm-last-mile-pk-v1/audio-candidates-v2/master/voice-restraint-a-48k-stereo-24bit.wav"
TEXT_EVIDENCE = ROOT / "evidence/v10/gtm-text-named-pk-super-challenger-v1.json"
FFMPEG = ROOT.parent / "tapnow-libtv-local-studio/backend-node/node_modules/ffmpeg-static/ffmpeg"
DEFAULT_OUTPUT = ROOT / "artifacts/gtm-last-mile-pk-v1/video-challenger-v6-rejection-rule"
VIDEO_NAME = "prooflaunch-rejection-rule-three-beat-4k.mp4"


def _background(path: Path, *, brightness: float = 0.66) -> Image.Image:
    with Image.open(path) as image:
        frame = image.convert("RGB").resize((3840, 2160), Image.Resampling.LANCZOS)
    frame = ImageEnhance.Brightness(frame).enhance(brightness).convert("RGBA")
    frame.alpha_composite(_gradient_overlay(frame.size, left_alpha=248, right_alpha=38))
    return frame


def _scene_one() -> Image.Image:
    frame = _background(BEAT_ONE, brightness=0.62)
    draw = ImageDraw.Draw(frame)
    _brand(draw)
    draw.text((175, 420), "THE MOST DANGEROUS SENTENCE", font=_font(106, bold=True), fill=(250, 250, 253))
    draw.text((175, 555), "IS THE SMOOTHEST ONE.", font=_font(122, bold=True), fill=(242, 171, 58))
    draw.rounded_rectangle((175, 820, 1740, 1250), radius=48, fill=(6, 9, 20, 235), outline=(212, 146, 42, 240), width=4)
    draw.multiline_text((245, 900), "‘This campaign will turn interest\ninto qualified pipeline.’", font=_font(65), fill=(247, 247, 251), spacing=20)
    draw.text((245, 1120), "REJECTED · OUTCOME NOT OBSERVED", font=_font(34, bold=True), fill=(242, 171, 58))
    _footer(draw, "A polished sentence is not an observed result.")
    return frame.convert("RGB")


def _scene_two() -> Image.Image:
    frame = _background(BEAT_TWO, brightness=0.70)
    draw = ImageDraw.Draw(frame)
    _brand(draw)
    draw.text((175, 360), "RUN THE REJECTION RULE.", font=_font(124, bold=True), fill=(250, 250, 253))
    rows = (
        ("01", "EXACT SUPPORTED CLAUSE"),
        ("02", "EVIDENCE OBJECT"),
        ("03", "REMAINING HYPOTHESIS"),
        ("04", "NAMED RELEASE OWNER"),
    )
    for index, (number, label) in enumerate(rows):
        y = 650 + index * 230
        draw.rounded_rectangle((175, y, 1680, y + 170), radius=36, fill=(7, 10, 23, 238), outline=(124, 96, 215, 240), width=3)
        draw.text((235, y + 37), number, font=_font(56, bold=True), fill=(242, 171, 58))
        draw.text((430, y + 52), label, font=_font(43, bold=True), fill=(241, 241, 248))
    _footer(draw, "If evidence or authority is blank, the asset does not pass.")
    return frame.convert("RGB")


def _scene_three() -> Image.Image:
    frame = _background(BEAT_THREE, brightness=0.76)
    draw = ImageDraw.Draw(frame)
    _brand(draw)
    draw.text((175, 390), "A USEFUL GTM EMPLOYEE", font=_font(105, bold=True), fill=(250, 250, 253))
    draw.text((175, 525), "HELPS YOU REJECT THE SENTENCE", font=_font(108, bold=True), fill=(173, 145, 255))
    draw.text((175, 665), "BEFORE IT HELPS YOU SCALE IT.", font=_font(105, bold=True), fill=(250, 250, 253))
    draw.rounded_rectangle((175, 980, 1680, 1325), radius=48, fill=(6, 9, 20, 236), outline=(124, 96, 215, 240), width=3)
    draw.text((245, 1055), "APPROVED FACT CONTINUES", font=_font(48, bold=True), fill=(243, 243, 249))
    draw.text((245, 1155), "UNPROVEN OUTCOME STAYS OUT", font=_font(44, bold=True), fill=(242, 171, 58))
    _footer(draw, "Run the rejection test. See what remains unproven.")
    return frame.convert("RGB")


def render(output: Path) -> dict[str, Any]:
    output.resolve().relative_to(ROOT)
    if output.exists() and any(output.iterdir()):
        raise SystemExit("output directory must be empty")
    for path in (BEAT_ONE, BEAT_TWO, BEAT_THREE, AUDIO, AUDIO_RECEIPT, TEXT_EVIDENCE, FFMPEG):
        if not path.is_file():
            raise SystemExit(f"required source is missing: {path}")
    audio_receipt = json.loads(AUDIO_RECEIPT.read_text(encoding="utf-8"))
    selected_audio = next(row for row in audio_receipt["candidates"] if row["candidate_id"] == "voice-restraint-a")
    if selected_audio["master"]["sha256"] != sha256_file(AUDIO):
        raise SystemExit("selected audio binding drifted")
    output.mkdir(parents=True, mode=0o700)
    scenes = (_scene_one(), _scene_two(), _scene_three())
    scene_paths = []
    for index, scene in enumerate(scenes, 1):
        path = output / f"scene-{index:02d}-4k.png"
        scene.save(path, format="PNG", optimize=True)
        scene_paths.append(path)
    captions = output / "prooflaunch-rejection-rule-captions.vtt"
    atomic_write_text(captions, "WEBVTT\n\n00:00.000 --> 00:15.000\n" + audio_receipt["frozen_script"] + "\n")
    video = output / VIDEO_NAME
    _encode(FFMPEG, scene_paths, AUDIO, video)
    audit_root = output / "audit-frames"
    audit_root.mkdir(mode=0o700)
    audit_paths = []
    for stamp in (1.0, 6.5, 11.5):
        path = audit_root / f"frame-{stamp:.1f}.png"
        _extract_frame(FFMPEG, video, stamp, path)
        audit_paths.append(path)
    differences = [_rms_difference(audit_paths[0], audit_paths[1]), _rms_difference(audit_paths[1], audit_paths[2])]
    if min(differences) < 20:
        raise RuntimeError("three-beat temporal diversity gate failed")
    probe = _run([str(FFMPEG), "-hide_banner", "-i", str(video)], timeout=60)
    probe_text = probe.stdout + probe.stderr
    match = re.search(r"Duration: (\d+):(\d+):([0-9.]+)", probe_text)
    if not match or "3840x2160" not in probe_text:
        raise RuntimeError("encoded video probe gate failed")
    hours, minutes, seconds = match.groups()
    duration = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    payload = {
        "schema": "ProofLaunchGTMRejectionRuleVideoChallengerV1",
        "scenario_id": "prooflaunch-b2b-ai-launch-zero-budget-v1",
        "creative_concept": "The Rejection Rule Is the Product",
        "story_beats": [
            "tension: the smooth unsupported sentence approaches release",
            "mechanism: clause, evidence, hypothesis and owner are inspected",
            "resolution: the approved fact continues while the unobserved outcome remains quarantined",
        ],
        "source_assets": [
            {"role": "film_beat_01", "path": str(BEAT_ONE.relative_to(ROOT)), "sha256": sha256_file(BEAT_ONE)},
            {"role": "film_beat_02", "path": str(BEAT_TWO.relative_to(ROOT)), "sha256": sha256_file(BEAT_TWO)},
            {"role": "film_beat_03", "path": str(BEAT_THREE.relative_to(ROOT)), "sha256": sha256_file(BEAT_THREE)},
            {"role": "selected_voice_master", "path": str(AUDIO.relative_to(ROOT)), "sha256": sha256_file(AUDIO)},
            {"role": "audio_receipt", "path": str(AUDIO_RECEIPT.relative_to(ROOT)), "sha256": sha256_file(AUDIO_RECEIPT)},
            {"role": "text_campaign_evidence", "path": str(TEXT_EVIDENCE.relative_to(ROOT)), "sha256": sha256_file(TEXT_EVIDENCE)},
        ],
        "scene_assets": [{"path": str(path.relative_to(ROOT)), "sha256": sha256_file(path), "bytes": path.stat().st_size} for path in scene_paths],
        "video": {"path": str(video.relative_to(ROOT)), "sha256": sha256_file(video), "bytes": video.stat().st_size, "width": 3840, "height": 2160, "fps": 24, "duration_seconds": duration, "codec": "h264"},
        "captions": {"path": str(captions.relative_to(ROOT)), "sha256": sha256_file(captions)},
        "audit_frames": [{"path": str(path.relative_to(ROOT)), "sha256": sha256_file(path)} for path in audit_paths],
        "adjacent_beat_rms_differences": differences,
        "image_generation_call_count_for_visual_world": 3,
        "sound_picture_contract": "The selected frozen voice script states the same evidence-before-outcome principle; on-screen copy is complementary rather than a word-for-word duplication.",
        "open_source_modifications": ["existing Pillow title-safe compositor", "pinned ffmpeg-static 4K encoder", "Qwen3-TTS local VoiceDesign master", "content-addressed frame and audio receipts"],
        "opponent_stress_tests": {
            "Veo": "story causality, physical continuity and cinematic finish",
            "Runway": "shot control, editability and coherent art direction",
            "Firefly Video": "production workflow, rights and brand-safe variation",
            "Kling": "motion realism, object persistence and camera control",
            "Hailuo": "expressive motion without identity or mechanism drift",
            "Luma": "cinematic camera language and scene coherence",
            "Pika": "fast controllable transformations without gimmick-first effects",
            "HeyGen": "message delivery and multilingual production without synthetic spokesperson dependence",
            "Synthesia": "enterprise narrative clarity, accessibility and revision control",
            "Seedance": "multi-shot continuity, prompt fidelity and visual rhythm"
        },
        "mechanical_three_beat_gate_passed": True,
        "first_three_second_human_hook_reviewed": False,
        "human_preference_observed": False,
        "completed_named_product_pk_count": 0,
        "candidate_win_count": 0,
        "four_a_quality_proven": False,
        "automatic_publish_enabled": False,
        "truth_boundary": "This receipt proves one content-addressed 4K three-beat internal challenger, source provenance and temporal scene diversity. It does not prove generative motion quality, named-product preference, 4A quality, publication effect, conversion or revenue."
    }
    receipt = _seal(payload)
    atomic_write_text(output / "video-challenger-receipt.json", json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return receipt


def main() -> int:
    result = render(DEFAULT_OUTPUT)
    print(json.dumps({"output": str(DEFAULT_OUTPUT), "video_sha256": result["video"]["sha256"], "duration_seconds": result["video"]["duration_seconds"], "adjacent_beat_rms_differences": result["adjacent_beat_rms_differences"], "human_preference_observed": False, "content_sha256": result["content_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
