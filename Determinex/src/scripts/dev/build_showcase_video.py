#!/usr/bin/env python3
"""build_showcase_video.py — the product tour, from footage of the product being used.

Ryan on the old one: "product showcase is all static... these are not worthy of anything."
It was six stills of idle panels, several showing a state later work had already fixed.

`ui_record_showcase.mjs` walks the app the way a person does and films it doing so. This
adds narration and the on-screen note per stop. It deliberately reuses `build_unified_video`
for TTS, wrapping, fonts and ffmpeg resolution rather than restating them: two copies of a
narration pipeline is exactly the duplication the repo's conventions forbid, and it is how
the two would drift into disagreeing about the same numbers.

    python scripts/dev/build_showcase_video.py
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw

_spec = importlib.util.spec_from_file_location(
    "build_unified_video", Path(__file__).resolve().parent / "build_unified_video.py"
)
if _spec is None or _spec.loader is None:
    raise SystemExit("cannot load build_unified_video.py")
_u = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_u)

W, H, FPS = _u.W, _u.H, _u.FPS
BG, ACCENT, DIM = _u.BG, _u.ACCENT, _u.DIM
NOTE_H, HEAD_H, LANCZOS, FFMPEG = _u.NOTE_H, _u.HEAD_H, _u.LANCZOS, _u.FFMPEG

SRC = Path("C:/tmp/showcase")
OUT = Path("C:/tmp/showcase_video")
AUDIO = Path("C:/tmp/narration3")
FINAL = Path.home() / "OneDrive/Desktop/DETERMINEX-UPLOAD" / "2-PRODUCT-SHOWCASE.mp4"

#: member -> (on-screen note, narration). Keyed by member so a re-ordered tour still matches.
SAY: dict[str, tuple[str, str]] = {
    "hive": (
        "Ask. Plan. Build. Prove. The request goes in on the left; this screen shows what "
        "happens next, which tools are attached, and where the proof will appear.",
        "Determinex is a local first coding workbench. You describe what you want, it plans, "
        "writes the code, then proves it — and the proof is a real compiler or a real test run, "
        "never another model's opinion. It is for work you cannot paste into a chat window: "
        "private repositories, regulated code, anything under an agreement that does not let it "
        "leave the building. You stay in the conversation the whole way, because every step "
        "reports what it did and what the verifier said about it.",
    ),
    "proof": (
        "The proof ledger. Oracle verdict, pipeline state, file diffs and verifier output — and "
        "empty states that say exactly which proof is missing.",
        "This is the proof ledger. Every run leaves oracle verdicts, diffs and verifier output "
        "here, so a claim traces back to the run that produced it. Where there is no evidence, "
        "it says so rather than showing a green tick it has not earned — including for the "
        "parts that are not finished.",
    ),
    "cloak": (
        "Project Cloak: 1,714,560 identifiers obfuscated before any cloud call, 0 leaks found. "
        "Read from this machine's own audit, not a marketing number.",
        "Project Cloak is the permission boundary. Nothing executes outside a sandbox, and "
        "nothing reaches a hosted model in the clear: every identifier is rewritten before a "
        "request leaves the machine. Over one point seven million cloaked, zero leaks found "
        "among them. Be precise about what that proves — everything Cloak obfuscated stayed "
        "obfuscated. Whether it captured every identifier is a separate property, with its own "
        "separate test.",
    ),
    "benchmark": (
        "Brain and Model Slots — which model plays Oracle, Architect, Builder and Monitor. "
        "Local, API, or hybrid, and swappable.",
        "Roles are explicit. Oracle, Architect, Builder and Monitor are each bound to a model, "
        "and any can be swapped. Three are distilled with LoRA and run locally — a one and a "
        "half billion parameter Builder, a three billion Monitor, a seven billion Architect — "
        "and a quantized hosted model can take any seat instead. Nothing is trusted on its own "
        "word, whichever model produced it, and that is what makes swapping them safe.",
    ),
    "flywheel": (
        "The flywheel. Every oracle-verified solve is distilled into a generalised class and "
        "fed back — failures become training data automatically.",
        "This is the flywheel, and it is where the retrieval comes from. Every verified solve "
        "is distilled into a general pattern and written back into the local corpus, so the "
        "next run retrieves a fix that already worked instead of guessing. Operational failures "
        "become training data with nobody curating by hand. It is the part that compounds — the "
        "system gets better at the work it has already done badly.",
    ),
    "mission": (
        "Mission Control — Determinex's OWN release gates, counted honestly. It guides; it does "
        "not grant readiness.",
        "Mission Control tracks Determinex's own release readiness, and is deliberately not "
        "allowed to grant it. It shows which gates passed, which are blocked, and what evidence "
        "each is still waiting for. Right now it says several are not ready. That is intended. "
        "A readiness board that always says ready is a decoration.",
    ),
    "roadmap": (
        "The roadmap states what is LIVE, PARTIAL, PLANNED and BLOCKED — with the blocker "
        "named. Six partial, one planned, nothing overstated.",
        "The roadmap is written the same way. Each capability is marked live, partial, planned "
        "or blocked, with the blocker named. Six are partial and one is planned, sitting on the "
        "same page as the finished work rather than behind it. A system that reports its own "
        "limits is the only kind whose other claims are worth checking.",
    ),
}


def main() -> int:
    run = json.loads((SRC / "run.json").read_text(encoding="utf-8"))
    marks = run.get("marks", [])
    if not marks:
        print(f"no footage in {SRC} — run ui_record_showcase.mjs first")
        return 1
    # Each stop owns a directory of frames captured while that stop -- and only that stop --
    # was open. There is no timeline arithmetic here on purpose: three previous versions
    # sliced one continuous recording into spans and all three put the wrong screen under
    # the narration, because they inferred what was on screen from a clock rather than from
    # the screen.
    OUT.mkdir(parents=True, exist_ok=True)
    AUDIO.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("s_*.png"):
        old.unlink()

    f_note, f_title, f_small = _u._font(23), _u._font(30), _u._font(19)
    idx = 0
    segs: list[tuple[Path, int]] = []

    for i, m in enumerate(marks):
        member = m["member"]
        if member not in SAY:
            continue
        note, speech = SAY[member]
        stop_frames = sorted((SRC / member).glob("f*.png"))
        if not stop_frames:
            print(f"  {member:<11} NO FRAMES — skipped")
            continue

        # Same rule as the main demo: a human take beats the synthetic one, per line.
        wav = _u.human_take(f"show_{member}") or AUDIO / f"s_{member}.wav"
        speak = _u.narrate(speech, wav)
        dur = speak + 0.8
        n_frames = int(dur * FPS)
        # Capture rate is no longer read: frames are spread across the stop's full length
        # rather than played at the rate they were taken and then held.
        print(f"  {member:<11} {len(stop_frames)} frames  speech {speak:5.1f}s -> {dur:5.1f}s")

        for k in range(n_frames):
            # Play this stop's own frames at their capture rate, then hold the last one.
            # Every frame in here was taken with this surface open, so the hold can only
            # ever be this surface.
            # Spread this stop's frames across the WHOLE stop rather than playing them at
            # capture rate and then holding. At capture rate a 12-second scroll under a
            # 35-second take left 23 seconds of still picture, and a frame-difference scan
            # of the finished cut found eleven such windows -- 0.00% of pixels changing
            # across five seconds.
            fi = min(int((k / max(n_frames - 1, 1)) * len(stop_frames)), len(stop_frames) - 1)
            shot = Image.open(stop_frames[fi]).convert("RGB")

            # Same slow push-in as the main cut, and here for the same reason: spreading the
            # frames helps only while there are frames to spread. This cannot run out.
            prog = k / max(n_frames - 1, 1)
            z = 1.0 - 0.04 * prog
            cw, ch = int(shot.width * z), int(shot.height * z)
            ox = int((shot.width - cw) * 0.5)
            oy = int((shot.height - ch) * prog)
            shot = shot.crop((ox, oy, ox + cw, oy + ch)).resize((shot.width, shot.height), LANCZOS)

            canvas = Image.new("RGB", (W, H), BG)
            d = ImageDraw.Draw(canvas)
            avail = H - NOTE_H - HEAD_H - 16
            sc = min((W - 48) / shot.width, avail / shot.height)
            shot = shot.resize((int(shot.width * sc), int(shot.height * sc)), LANCZOS)
            canvas.paste(shot, ((W - shot.width) // 2, HEAD_H + (avail - shot.height) // 2))

            d.text((44, 12), "DETERMINEX", font=f_title, fill=ACCENT)
            d.text((262, 22), "compiler-verified AI agents on AMD Radeon", font=f_small, fill=DIM)
            d.text(
                (W - 340, 22),
                f"{i + 1} of {len(marks)}  ·  {m['label'][:28]}",
                font=f_small,
                fill=DIM,
            )

            y = H - NOTE_H
            d.rectangle([0, y, W, H], fill=(13, 16, 21))
            d.line([(0, y), (W, y)], fill=(30, 40, 36), width=2)
            for j, ln in enumerate(_u.wrap(d, note, f_note, W - 96)[:3]):
                d.text((48, y + 20 + j * 30), ln, font=f_note, fill=(214, 222, 232))

            canvas.save(OUT / f"s_{idx:06d}.png")
            idx += 1
        segs.append((wav, n_frames))

    print(f"composited {idx} frames ({idx / FPS / 60:.1f} min)")

    parts = []
    for i, (wav, nf) in enumerate(segs):
        pad = AUDIO / f"p{i}.wav"
        s = nf / FPS
        subprocess.run(
            [
                FFMPEG,
                "-y",
                "-i",
                str(wav),
                "-af",
                f"apad=whole_dur={s:.3f}",
                "-t",
                f"{s:.3f}",
                str(pad),
            ],
            check=True,
            capture_output=True,
        )
        parts.append(pad)
    lst = AUDIO / "concat.txt"
    lst.write_text("\n".join(f"file '{p.as_posix()}'" for p in parts), encoding="utf-8")
    voice = AUDIO / "voice.wav"
    subprocess.run(
        [FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(voice)],
        check=True,
        capture_output=True,
    )

    subprocess.run(
        [
            FFMPEG,
            "-y",
            "-framerate",
            str(FPS),
            "-i",
            str(OUT / "s_%06d.png"),
            "-i",
            str(voice),
            "-vf",
            "scale=1920:1080:force_original_aspect_ratio=decrease:flags=lanczos,"
            "pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-ar",
            "48000",
            "-b:a",
            "192k",
            "-b:a",
            "192k",
            "-shortest",
            "-movflags",
            "+faststart",
            str(FINAL),
        ],
        check=True,
    )
    print(f"\n  {FINAL}  ({FINAL.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
