#!/usr/bin/env python3
"""Generate synthetic test fixture videos for PolicyCut.

Creates three short (<= 20 s) 640x360 25 fps clips in tests/fixtures/:

- street.mp4    two moving cartoon faces, a car with a fake license plate
                "AB-123-CD", and a foreground pole that occludes the faces.
- interview.mp4 a static cartoon face, a fake ID-card rectangle and a
                phone-screen rectangle; spoken audio "my phone number is
                five five five zero one two three four".
- office.mp4    two monitor rectangles, a hard cut mid-clip, spoken audio
                "I live at one two three Main Street".

ALL PII IS FAKE AND SYNTHETIC. No real faces, plates, numbers or addresses.

Speech is synthesized with `say` (macOS) or `espeak` (Linux) when available;
otherwise a tone placeholder is used. Video frames are drawn with OpenCV and
muxed/transcoded with ffmpeg. If ffmpeg is missing, silent OpenCV-only videos
are produced and the manifest records the degradation. If OpenCV is missing,
the script exits gracefully with a message.

Usage:
    python scripts/make_fixtures.py [--out tests/fixtures] [--force]
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import struct
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = PROJECT_ROOT / "tests" / "fixtures"

W, H, FPS = 640, 360, 25


# ----------------------------------------------------------------------------
# drawing helpers
# ----------------------------------------------------------------------------

def draw_face(cv2, frame, cx: int, cy: int, r: int, skin=(140, 180, 240)):
    """Draw a simple cartoon face (circle + eyes + smile)."""
    cv2.circle(frame, (cx, cy), r, skin, -1)
    cv2.circle(frame, (cx, cy), r, (60, 90, 140), 2)
    eye_dx, eye_dy = r // 3, r // 4
    for sx in (-1, 1):
        cv2.circle(frame, (cx + sx * eye_dx, cy - eye_dy), max(2, r // 8), (40, 40, 40), -1)
    cv2.ellipse(frame, (cx, cy + r // 4), (r // 2, r // 3), 0, 20, 160, (40, 40, 40), 2)


def draw_plate(cv2, frame, x: int, y: int, w: int, h: int, text: str = "AB-123-CD"):
    cv2.rectangle(frame, (x, y), (x + w, y + h), (250, 250, 250), -1)
    cv2.rectangle(frame, (x, y), (x + w, y + h), (20, 20, 20), 2)
    cv2.putText(frame, text, (x + 6, y + h - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (20, 20, 20), 2)


def draw_monitor(cv2, frame, x: int, y: int, w: int, h: int, screen=(120, 80, 40)):
    """Dark bezel + colored screen with fake text lines (looks like a display)."""
    cv2.rectangle(frame, (x - 8, y - 8), (x + w + 8, y + h + 8), (35, 35, 35), -1)
    cv2.rectangle(frame, (x, y), (x + w, y + h), screen, -1)
    for i in range(4):
        ly = y + 20 + i * (h - 30) // 4
        cv2.rectangle(frame, (x + 12, ly), (x + w - 20 - (i * 17) % 60, ly + 8), (230, 230, 230), -1)
    # stand
    cv2.rectangle(frame, (x + w // 2 - 12, y + h + 8), (x + w // 2 + 12, y + h + 26), (35, 35, 35), -1)


# ----------------------------------------------------------------------------
# scene renderers: fn(frame_index) -> frame (numpy array)
# ----------------------------------------------------------------------------

def street_frame(cv2, np, i: int, n: int):
    frame = np.full((H, W, 3), 200, dtype=np.uint8)
    frame[:150] = (235, 206, 135)                      # sky
    frame[220:] = (105, 105, 105)                      # road
    cv2.line(frame, (0, 290), (W, 290), (255, 255, 255), 3)
    t = i / max(n - 1, 1)
    # car with fake plate, slowly rolling right
    car_x = int(40 + 120 * t)
    cv2.rectangle(frame, (car_x, 240), (car_x + 220, 320), (60, 60, 180), -1)
    cv2.rectangle(frame, (car_x + 30, 215), (car_x + 180, 245), (90, 90, 200), -1)
    draw_plate(cv2, frame, car_x + 60, 288, 110, 26, "AB-123-CD")
    # two moving cartoon faces (walking pedestrians)
    f1x = int(60 + (W - 140) * t)                      # left -> right
    f2x = int(W - 80 - (W - 160) * t)                  # right -> left
    f1y = 150 + int(6 * math.sin(t * 12 * math.pi))
    f2y = 185 + int(5 * math.sin(3 + t * 10 * math.pi))
    draw_face(cv2, frame, f1x, f1y, 34)
    draw_face(cv2, frame, f2x, f2y, 28, skin=(150, 200, 220))
    # foreground pole occludes the faces as they pass behind it
    cv2.rectangle(frame, (300, 60), (330, 340), (50, 70, 80), -1)
    return frame


def interview_frame(cv2, np, i: int, n: int):
    frame = np.full((H, W, 3), 190, dtype=np.uint8)
    frame[:, :] = (170, 190, 200)
    cv2.rectangle(frame, (0, 300), (W, H), (90, 120, 140), -1)   # desk
    # static interviewee face
    draw_face(cv2, frame, 170, 150, 48)
    cv2.rectangle(frame, (120, 198), (220, 310), (100, 60, 60), -1)  # torso
    # fake ID card held up
    cx, cy, cw, ch = 380, 90, 190, 110
    cv2.rectangle(frame, (cx, cy), (cx + cw, cy + ch), (245, 245, 245), -1)
    cv2.rectangle(frame, (cx, cy), (cx + cw, cy + ch), (30, 30, 30), 2)
    cv2.putText(frame, "ID CARD", (cx + 10, cy + 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (30, 30, 130), 2)
    cv2.putText(frame, "JANE DOE", (cx + 10, cy + 52), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (30, 30, 30), 1)
    cv2.putText(frame, "NO: 555-0123", (cx + 10, cy + 76), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (30, 30, 30), 1)
    cv2.circle(frame, (cx + cw - 32, cy + 40), 20, (180, 200, 230), -1)  # photo blob
    # phone with bright screen on the desk
    px, py = 420, 230
    cv2.rectangle(frame, (px, py), (px + 70, py + 115), (30, 30, 30), -1)
    cv2.rectangle(frame, (px + 6, py + 10), (px + 64, py + 105), (250, 230, 180), -1)
    cv2.putText(frame, "555-", (px + 12, py + 45), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (40, 40, 40), 1)
    cv2.putText(frame, "0123", (px + 12, py + 70), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (40, 40, 40), 1)
    return frame


def office_frame(cv2, np, i: int, n: int):
    cut = n // 2  # hard cut at mid-clip
    if i < cut:
        frame = np.full((H, W, 3), 210, dtype=np.uint8)
        frame[:, :] = (200, 210, 210)
        cv2.rectangle(frame, (0, 260), (W, H), (120, 140, 150), -1)  # desk
        draw_monitor(cv2, frame, 80, 80, 200, 140)
        draw_monitor(cv2, frame, 360, 80, 200, 140, screen=(60, 110, 60))
    else:
        # scene B after the hard cut: different room, one monitor + a face
        frame = np.full((H, W, 3), 150, dtype=np.uint8)
        frame[:, :] = (150, 160, 185)
        cv2.rectangle(frame, (0, 280), (W, H), (90, 100, 120), -1)
        draw_monitor(cv2, frame, 230, 90, 220, 150, screen=(140, 90, 50))
        draw_face(cv2, frame, 110, 170, 40)
    return frame


# ----------------------------------------------------------------------------
# audio helpers
# ----------------------------------------------------------------------------

def write_tone_wav(path: Path, duration_s: float, freq: float = 440.0, sr: int = 16000):
    """Placeholder audio: short beeps pattern (no speech)."""
    n = int(duration_s * sr)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        frames = bytearray()
        for i in range(n):
            t = i / sr
            on = (t % 1.0) < 0.25  # 250 ms beep each second
            val = int(0.3 * 32767 * math.sin(2 * math.pi * freq * t)) if on else 0
            frames += struct.pack("<h", val)
        wf.writeframes(bytes(frames))


def synth_speech(text: str, out_wav: Path, ffmpeg: str | None) -> str:
    """Synthesize speech to a 16 kHz mono wav. Returns the source used."""
    tmp_dir = Path(tempfile.mkdtemp(prefix="policycut_tts_"))
    try:
        if shutil.which("say") and ffmpeg:
            aiff = tmp_dir / "tts.aiff"
            r = subprocess.run(["say", "-o", str(aiff), text], capture_output=True, timeout=60)
            if r.returncode == 0 and aiff.exists():
                r2 = subprocess.run(
                    [ffmpeg, "-y", "-i", str(aiff), "-ar", "16000", "-ac", "1", str(out_wav)],
                    capture_output=True, timeout=60,
                )
                if r2.returncode == 0 and out_wav.exists():
                    return "say"
        if shutil.which("espeak"):
            r = subprocess.run(
                ["espeak", "-w", str(out_wav), "-s", "140", text],
                capture_output=True, timeout=60,
            )
            if r.returncode == 0 and out_wav.exists():
                return "espeak"
    except Exception:
        pass
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    write_tone_wav(out_wav, 4.0)
    return "tone_placeholder"


# ----------------------------------------------------------------------------
# video writing / muxing
# ----------------------------------------------------------------------------

def render_frames(cv2, np, path: Path, frame_fn, duration_s: float) -> bool:
    n = int(duration_s * FPS)
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (W, H))
    if not writer.isOpened():
        print(f"  [skip] cv2.VideoWriter could not open {path.name}")
        return False
    for i in range(n):
        writer.write(frame_fn(cv2, np, i, n))
    writer.release()
    return True


def finalize(ffmpeg: str | None, raw_video: Path, wav: Path | None, out: Path,
             duration_s: float, speech_delay_ms: int = 1000) -> str:
    """Transcode to H.264 and mux optional audio. Returns a note string."""
    if not ffmpeg:
        shutil.copy2(raw_video, out)
        return "no ffmpeg: mp4v video, no audio"
    cmd = [ffmpeg, "-y", "-i", str(raw_video)]
    if wav is not None:
        cmd += ["-i", str(wav),
                "-filter_complex", f"[1:a]adelay={speech_delay_ms}:all=1,apad[a]",
                "-map", "0:v", "-map", "[a]", "-c:a", "aac", "-ar", "48000"]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-t", f"{duration_s:.3f}", str(out)]
    r = subprocess.run(cmd, capture_output=True, timeout=300)
    if r.returncode == 0 and out.exists():
        return "h264+aac" if wav else "h264 silent"
    # fallback: let ffmpeg pick its default codec (libx264 may be unavailable)
    cmd2 = [ffmpeg, "-y", "-i", str(raw_video)]
    if wav is not None:
        cmd2 += ["-i", str(wav), "-filter_complex", f"[1:a]adelay={speech_delay_ms}:all=1,apad[a]",
                 "-map", "0:v", "-map", "[a]"]
    cmd2 += ["-pix_fmt", "yuv420p", "-t", f"{duration_s:.3f}", str(out)]
    r2 = subprocess.run(cmd2, capture_output=True, timeout=300)
    if r2.returncode == 0 and out.exists():
        return "ffmpeg default codec"
    shutil.copy2(raw_video, out)
    return f"ffmpeg failed ({r.stderr.decode(errors='ignore')[-120:].strip()}); kept mp4v silent video"


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate PolicyCut synthetic fixtures (all PII fake)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="output directory")
    parser.add_argument("--force", action="store_true", help="regenerate even if files exist")
    args = parser.parse_args(argv)

    try:
        import cv2
        import numpy as np
    except Exception as exc:
        print(f"OpenCV/numpy unavailable ({exc}) — cannot generate fixtures. Skipping gracefully.")
        return 0

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        print("ffmpeg not found: fixtures will be silent mp4v videos (graceful degradation).")

    out_dir = args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="policycut_fixtures_"))

    specs = [
        {
            "name": "street.mp4",
            "duration_s": 10.0,
            "frame_fn": street_frame,
            "speech": None,
            "description": "Two moving cartoon faces, fake license plate 'AB-123-CD' on a car, "
                           "foreground pole occlusion. Silent.",
            "expected": {
                "visual": ["face x2 (moving, occluded by pole)", "license_plate 'AB-123-CD' (fake)"],
                "audio_pii": [],
            },
        },
        {
            "name": "interview.mp4",
            "duration_s": 10.0,
            "frame_fn": interview_frame,
            "speech": "my phone number is five five five zero one two three four",
            "description": "Static cartoon face, fake ID card, phone screen. "
                           "Spoken fake phone number (spoken digits).",
            "expected": {
                "visual": ["face (static)", "id_document (fake ID card)", "screen (phone)"],
                "audio_pii": ["phone: spoken 'five five five zero one two three four' (fake)"],
            },
        },
        {
            "name": "office.mp4",
            "duration_s": 12.0,
            "frame_fn": office_frame,
            "speech": "I live at one two three Main Street",
            "description": "Two monitor screens, hard cut at 6 s to a second room. "
                           "Spoken fake address.",
            "expected": {
                "visual": ["screen x2 (scene A)", "screen + face (scene B after hard cut)"],
                "audio_pii": ["address: spoken 'one two three Main Street' (fake)"],
            },
        },
    ]

    manifest = {
        "note": "Synthetic PolicyCut test fixtures. ALL PII IS FAKE (cartoon faces, "
                "invented plate/phone/address). Safe for redistribution.",
        "resolution": f"{W}x{H}",
        "fps": FPS,
        "fixtures": [],
    }

    for spec in specs:
        out_path = out_dir / spec["name"]
        entry = {
            "file": spec["name"],
            "duration_s": spec["duration_s"],
            "description": spec["description"],
            "expected": spec["expected"],
            "audio_source": "none",
            "encoding": "",
        }
        if out_path.exists() and not args.force:
            print(f"[keep] {out_path.name} already exists (use --force to regenerate)")
            entry["encoding"] = "pre-existing"
            manifest["fixtures"].append(entry)
            continue

        print(f"[make] {spec['name']} ({spec['duration_s']:.0f}s) ...")
        raw = work / ("raw_" + spec["name"])
        if not render_frames(cv2, np, raw, spec["frame_fn"], spec["duration_s"]):
            entry["encoding"] = "failed: cv2 writer"
            manifest["fixtures"].append(entry)
            continue

        wav = None
        if spec["speech"] and ffmpeg:
            wav = work / (spec["name"] + ".wav")
            entry["audio_source"] = synth_speech(spec["speech"], wav, ffmpeg)
            entry["spoken_text"] = spec["speech"]
        elif spec["speech"]:
            entry["audio_source"] = "skipped (no ffmpeg to mux)"

        entry["encoding"] = finalize(ffmpeg, raw, wav, out_path, spec["duration_s"])
        if out_path.exists():
            entry["size_bytes"] = out_path.stat().st_size
            print(f"  -> {out_path} ({entry['size_bytes']:,} bytes, {entry['encoding']}, "
                  f"audio: {entry['audio_source']})")
        manifest["fixtures"].append(entry)

    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))
    print(f"\nManifest written to {manifest_path}")
    shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
