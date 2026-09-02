#!/usr/bin/env python3
"""build_unified_video.py — one screen, one recording: the product running its own demo.

Replaces the split-screen cut. Ryan: "why does the left side the ide not show the right? ...
we have a terminal in the ide that could show it both running. this is very disjointed and
very wierd and i wouldnt chose this for anything to win."

He was right twice over. The two panes were unrelated captures composited side by side, and
the reason the IDE could not show the work was that its terminal appeared dead — no prompt,
no output, no error. That was a stale stack, not a bug: `invokeSafe` swallows a missing
command silently, and `frontend/src-tauri/target/debug/determinex.exe` predates
`pty_terminal.rs` by four days with zero occurrences of `pty_spawn`. Against the current
backend the terminal is a real PTY that streams.

So there is nothing to composite. `ui_record_unified_demo.mjs` drives the actual app: Work
cockpit on screen, the IDE's own terminal opened over it as a restored dock, and
`submission_demo.py` running INSIDE that terminal against the live Radeon. This adds a
header, the on-screen rationale, and narration aligned to the section banners the viewer
can read for themselves.

    python scripts/dev/build_unified_video.py
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import wave
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1920, 1080
FPS = 10
BG = (8, 9, 13)
ACCENT = (0, 220, 130)
DIM = (120, 132, 148)
NOTE_H = 116
HEAD_H = 56
LANCZOS = getattr(Image, "LANCZOS", getattr(getattr(Image, "Resampling", None), "LANCZOS", 1))

SRC = Path("C:/tmp/unified")
OUT = Path("C:/tmp/unified_video")
FINAL = Path.home() / "OneDrive/Desktop/DETERMINEX-UPLOAD" / "1-MAIN-DEMO.mp4"
AUDIO = Path("C:/tmp/narration2")


def _ffmpeg() -> str:
    """ffmpeg from PATH, or DETERMINEX_FFMPEG, or a winget install if one is present.

    The first version of this hardcoded an absolute path under a specific user profile, which
    the no-hardcoded-paths guard rejected the moment the hooks actually started running --
    a good demonstration that the guard earns its place, since that path works on exactly one
    machine and fails silently everywhere else.
    """
    found = shutil.which("ffmpeg") or os.environ.get("DETERMINEX_FFMPEG")
    if found and Path(found).exists():
        return found
    local = Path.home() / "AppData/Local/Microsoft/WinGet/Packages"
    if local.is_dir():
        for exe in local.glob("Gyan.FFmpeg*/**/bin/ffmpeg.exe"):
            return str(exe)
    raise SystemExit("ffmpeg not found — put it on PATH or set DETERMINEX_FFMPEG")


FFMPEG = _ffmpeg()

#: (section, on-screen note, narration). Narration is deliberately close in length to the
#: footage it sits over: where speech runs far past the footage the last frame has to be
#: held, and holding a terminal still for a minute looks broken however true the words are.
SECTIONS: list[tuple[str, str, str]] = [
    (
        "0",
        "Decomposes the request, calls real tools, retrieves from its own corpus, remembers only verifier-confirmed cases. An idea in, an oracle synthesised (3 checks, sound: true), a program verified against it — no model judged itself.",
        "This is Determinex, a coding agent that runs entirely on hardware you control. It decomposes a request into steps, calls real tools, retrieves from a local corpus built from its own past work, and keeps a memory of solved cases that only accepts what a verifier confirmed. Nothing leaves the machine unless you send it, and when you do, every identifier is obfuscated first. One rule holds everywhere: no model judges its own output. A real compiler decides.",
    ),
    (
        "1",
        "K=6 costs almost exactly what K=1 costs. Qwen2.5-Coder-32B, AWQ 4-bit, vLLM on ROCm. The sixth candidate is nearly free — which is what makes verifying every candidate affordable.",
        "Accuracy is bounded by how fast the G P U batches candidates, not by how good the model is. Here is what the Kth candidate costs on the Radeon, served by Qwen two point five Coder on ROCm, quantized to four bit. One candidate, then six. Six verified candidates return in almost the same wall clock as one: five and a half times the throughput for seven percent more time, across six runs on five instances.",
    ),
    (
        "2",
        "A failed check is a turn, not a stop: the error is re-injected and the plan revised, up to 5 attempts, each one recorded. The concurrency ceiling that bounds K is measured here, not read from vLLM's boot-time declaration.",
        "Every step is a turn, and a failed check does not end the conversation. The error goes back in, the plan is revised, and it tries again — up to five times, each attempt recorded. That loop is the interaction. Its ceiling is measured, not assumed: vLLM publishes a concurrency figure at boot, and a number declared at start up is not what enforces the limit under load. So it sweeps the machine and derives K from what it measures.",
    ),
    (
        "3",
        "Verified search sends K prompts identical but for temperature. Read the cache column: 93% hits shared, about 1% when one distinct token is prepended.",
        "The access pattern is itself a G P U optimisation. Verified search sends K prompts identical but for temperature, where an ordinary agent sends K different ones. Read the cache column, measured by vLLM on the card. The shared prefix is computed once and reused: ninety three percent hits. Prepend one distinct token per request and it collapses to about one percent, and the clock follows the cache.",
    ),
    (
        "4",
        "Where it works AND where it does not. At p=1 there is nothing to amplify; at p=0 no K helps at all, because 1-(1-0)^K = 0. Both boundaries are measured.",
        "This is where it works and where it does not. The middle row is the productive case: a model failing more than half its attempts reaches ninety nine point five percent at K of eight. But at p equals one there is nothing to amplify, and at p equals zero no K helps at all. Verified search multiplies capability. It cannot manufacture it.",
    ),
    (
        "5",
        "It refuses what it cannot verify, then earns it. Source is public, AGPL, and the reproduction command is one line in the README.",
        "Finally, the behaviour that matters most. Given a vague idea with nothing a test could assert, it refuses, and says why. Pin it down with three examples and it synthesises real checks, generates against them on the Radeon, and returns a program that passed. A system that answers everything is a system whose answers mean nothing. It will not report success unless a verifier said so, and where a capability is partial the roadmap says partial. All of it reproduces from four commands in the read me.",
    ),
]


def _font(size: int):
    for n in ("seguisb.ttf", "segoeui.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(n, size)
        except OSError:
            continue
    return ImageFont.load_default()


#: Human recordings live here, one per line, and BEAT the synthetic voice whenever present.
#: Ryan: "that voice on the video is horrible ... if you give me the script i can record it
#: and you can chop it and place it." Offline Windows SAPI is never going to stop sounding
#: synthetic, so the pipeline takes a real take when one exists and falls back per line, not
#: all-or-nothing -- which means takes can be recorded a few at a time without the video
#: breaking in between.
#: Searched in order. The Desktop folder is first because that is where the takes will
#: actually be recorded -- asking someone to drop files into C:/tmp is asking them to
#: navigate somewhere they never otherwise go, and the friction is the whole reason a
#: synthetic voice would end up shipping instead.
VO_DIRS = [
    Path.home() / "OneDrive/Desktop/DETERMINEX-RECORD-THESE/takes",
    Path.home() / "Desktop/DETERMINEX-RECORD-THESE/takes",
    #: The repo root, because that is where the first take actually landed. Telling someone
    #: their file is in the wrong folder is a worse answer than looking in the folder they
    #: chose - a phone-to-desktop transfer drops a file wherever it drops it. Derived from
    #: this file rather than written out: the no-hardcoded-paths hook rejected the literal,
    #: and it was right to, since a literal repo path resolves on exactly one machine.
    Path(__file__).resolve().parents[2],
    Path("C:/tmp/vo"),
]
VO_DIR = VO_DIRS[-1]  # where converted wavs are written


#: Cleanup applied to every human take, tuned by measurement against the first real one rather
#: than by reputation. The recordings come off a noise-cancelling headset - no studio mic - so
#: they arrive around -20 LUFS over a broadband floor near -34 dB.
#:
#: What actually moved the number, floor-to-speech separation on that take:
#:     original                        13.1 dB
#:     afftdn alone, nr=12 or nr=24    13.7 dB   (spectral denoise contributes ~nothing here)
#:     highpass 95 Hz + afftdn nr=20   14.7 dB   <- shipped
#: Almost the entire win is the highpass removing low-frequency rumble. That is worth stating
#: plainly because the obvious move is to reach for a stronger denoiser, and on this material
#: a stronger denoiser buys 0.0 dB while chewing consonants.
#:
#: Two filters were tried and REMOVED:
#:   agate    gated the gaps, but loudnorm's dynamic mode then pumped the floor straight back
#:            up, so the measurement showed no improvement at all - the gate was undone
#:            downstream by the very next filter.
#:   anlmdn   0.1 dB, for a large amount of CPU.
_VO_DENOISE = "highpass=f=95,afftdn=nr=20:nf=-38"
_VO_TARGET = "I=-16:TP=-1.5:LRA=11"


def human_take(stem: str) -> Path | None:
    """A human recording for this line, cleaned and converted to the wav the pipeline wants."""
    for ext in (".wav", ".mp3", ".m4a", ".ogg", ".flac"):
        src = next((d / f"{stem}{ext}" for d in VO_DIRS if (d / f"{stem}{ext}").exists()), None)
        if src is None:
            continue
        #: A .wav is no longer passed through untouched. It used to be, on the assumption that
        #: wav meant "already prepared", but a wav straight off a recorder needs the same
        #: levelling as an m4a - and the inconsistency would show up as one section of the
        #: finished video being noticeably quieter than the rest.
        conv = VO_DIR / f"{stem}.converted.wav"
        if not conv.exists() or conv.stat().st_mtime < src.stat().st_mtime:
            VO_DIR.mkdir(parents=True, exist_ok=True)
            _clean_take(src, conv)
        return conv
    return None


def _clean_take(src: Path, dst: Path) -> None:
    """Denoise and level one take to broadcast loudness.

    Two passes, because one pass is wrong in a way that hides itself. loudnorm with no
    measured input runs in dynamic mode, which lifts quiet passages toward the target - so it
    raises the room tone back up by roughly whatever the denoiser just removed, and the
    finished file measures as though the cleanup never happened. Measuring first and passing
    the values back makes the second pass apply a single linear gain, which leaves the
    floor-to-speech separation intact.
    """
    probe = subprocess.run(
        [
            FFMPEG,
            "-hide_banner",
            "-nostats",
            "-i",
            str(src),
            "-af",
            f"{_VO_DENOISE},ebur128=framelog=quiet",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    found = re.findall(r"^\s*I:\s*(-?[\d.]+)\s*LUFS", probe.stderr or "", re.M)
    gain = f"volume={-16.0 - float(found[-1]):.2f}dB," if found else ""
    subprocess.run(
        [
            FFMPEG,
            "-y",
            "-i",
            str(src),
            #: A measured gain, not loudnorm. loudnorm falls back to its dynamic mode whenever a
            #: linear gain would breach the true-peak ceiling, and these takes peak at +3.8 dBTP,
            #: so it fell back every time - silently, while still reporting the target loudness it
            #: was asked for. The floor came back up with everything else and the denoise upstream
            #: was cancelled out. A flat gain into a limiter cannot do that: the limiter touches
            #: the handful of samples over the ceiling and nothing else moves.
            "-af",
            f"{_VO_DENOISE},{gain}alimiter=limit=0.9",
            "-ac",
            "1",
            "-ar",
            #: 48 kHz, not the 22050 this used to write. The takes arrive full band
            #: at 44.1 kHz and 22050 caps everything at 11 kHz, which strips the air
            #: out of a voice and makes a good recording sound like a phone call.
            #: Ryan, on the first cut carrying real narration: "the sound is ass".
            "48000",
            str(dst),
        ],
        check=True,
        capture_output=True,
    )


def narrate(text: str, path: Path) -> float:
    if path.exists():
        with wave.open(str(path)) as w:
            return w.getnframes() / float(w.getframerate())
    ps = (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        "$s.SelectVoice('Microsoft David Desktop'); $s.Rate = 0; "
        f"$s.SetOutputToWaveFile('{path.as_posix()}'); "
        f"$s.Speak(@'\n{text}\n'@); $s.Dispose()"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True, capture_output=True)
    with wave.open(str(path)) as w:
        return w.getnframes() / float(w.getframerate())


def wrap(d, text: str, font, max_w: int) -> list[str]:
    out, cur = [], ""
    for word in text.split():
        t = f"{cur} {word}".strip()
        if d.textlength(t, font=font) <= max_w:
            cur = t
        else:
            out.append(cur)
            cur = word
    if cur:
        out.append(cur)
    return out


def main() -> int:
    run = json.loads((SRC / "run.json").read_text(encoding="utf-8"))
    frames = sorted(SRC.glob("f*.png"))
    if not frames:
        print(f"no frames in {SRC} — run ui_record_unified_demo.mjs first")
        return 1
    src_fps = run.get("fps", 4)
    at = {k: float(v) for k, v in run.get("sectionAt", {}).items()}
    if not at:
        print("run.json has no sectionAt — re-record with the timing capture")
        return 1
    total_s = run.get("seconds", len(frames) / src_fps)

    OUT.mkdir(parents=True, exist_ok=True)
    AUDIO.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("u_*.png"):
        old.unlink()

    f_note, f_title, f_small = _font(23), _font(30), _font(19)
    keys = [s[0] for s in SECTIONS]
    idx = 0
    segs: list[tuple[Path, int]] = []

    for i, (key, note, speech) in enumerate(SECTIONS):
        if key not in at:
            print(f"  section {key}: never appeared in the recording — skipped")
            continue
        t0 = at[key]
        t1 = at[keys[i + 1]] if i + 1 < len(keys) and keys[i + 1] in at else total_s
        span = max(t1 - t0, 0.8)

        # A real take wins whenever one exists; otherwise synthesise this line only.
        wav = human_take(f"main_{key}") or AUDIO / f"u{key}.wav"
        speak = narrate(speech, wav)
        dur = max(span, speak + 0.8)
        hold = dur - span
        n_frames = int(dur * FPS)

        # Section 0's own footage is 4s of the terminal starting, so its 28s of narration
        # would freeze on a banner for 24 of them. The Quick Verify build footage is the
        # right thing to show under that narration anyway: an idea typed in, an oracle
        # synthesised from it, and a verified program — the loop the words describe.
        alt = sorted(Path("C:/tmp/liveframes").glob("f*.png")) if key == "0" else []

        # Sections whose narration outruns their footage would otherwise sit frozen for half
        # a minute, which reads as exactly the "all static" the last showcase was rejected
        # for. Rather than hold, cut to the surface the narration is actually describing:
        # the corpus/benchmark screen while the p-value table is discussed, the Proof screen
        # while refuse-then-earn is. Motion AND relevance, instead of a still frame.
        # Sections whose narration outruns their terminal footage cut to a SCROLLING pass
        # over the surface the narration is describing, not to a still. A still is a still
        # however relevant it is -- that was the "nothing really changes on this window"
        # note. Scrolling is motion and it also lets the viewer read the rest of the panel
        # instead of its top 40% held for half a minute.
        # Section 1 was the one section with no pool at all, so its surplus was a genuine 15s
        # frozen frame. The showcase capture of the Proof surface is real footage of this
        # product and it is what the K-cost narration leads into, so it fills rather than holds.
        HOLD_SCROLL = {
            "1": "C:/tmp/showcase/proof",
            "2": "C:/tmp/scroll_trace",
            "4": "C:/tmp/scroll_benchmark",
        }
        cut_img = None
        cut_seq = []
        if hold > 6 and key in HOLD_SCROLL:
            cut_seq = sorted(Path(HOLD_SCROLL[key]).glob("f*.png"))
        # Section 5 closes on the VERIFIED BUILD, not the Proof ledger. The ledger was the
        # obvious choice and it was wrong: with no session run against this workspace it
        # renders its empty state -- "No runs yet", "No evidence yet" -- so the final thirty
        # seconds of the video said "it refuses what it cannot verify, then earns it" over a
        # screen showing nothing earned. The last frame of the live build is the thing the
        # sentence is about: an oracle synthesised, three checks, verified.
        # Section 5 does not cut to a still — it PLAYS the tail of the build footage:
        # the program being generated, the verdict landing, and the walk to Proof where the
        # ledger now carries it. A single held frame was still a frozen screen, which is the
        # "nothing really changes on this window" note; a sequence is motion, and it is the
        # motion the sentence is describing.
        if hold > 6 and key == "5":
            live = sorted(Path("C:/tmp/liveframes").glob("f*.png"))
            cut_seq = live[int(len(live) * 0.45) :] if live else []
        cut_at = span + 3.0  # let the final numbers sit briefly, then move

        # Report whether the surplus is FILLED with moving footage or genuinely held. Saying
        # "holds 34s" about a section that scrolls for 26 of them would be the log lying
        # about the exact thing the log exists to warn me about.
        filled = bool(alt) or bool(cut_seq)
        tail = ""
        if hold > 3:
            tail = f"  ({'fills' if filled else 'HOLDS'} {hold:.0f}s)"
        print(f"  section {key}: footage {span:5.1f}s  speech {speak:5.1f}s  -> {dur:5.1f}s{tail}")

        for k in range(n_frames):
            if alt:
                # Spread the pool across the WHOLE section. The 1.35 here meant the 90 frames
                # were consumed by 74% of the run, and the last quarter -- fifteen seconds --
                # was a still. A frame-difference scan of the finished cut found it: 0.00% of
                # pixels changing between samples five seconds apart.
                fi = min(int((k / max(n_frames - 1, 1)) * len(alt)), len(alt) - 1)
                shot = Image.open(alt[fi]).convert("RGB")
            elif cut_seq and (k / FPS) > cut_at:
                # Stretch the tail across the remaining narration so it plays rather than holds.
                into = (k / FPS) - cut_at
                remain = max(dur - cut_at, 0.1)
                si = min(int((into / remain) * len(cut_seq)), len(cut_seq) - 1)
                shot = Image.open(cut_seq[si]).convert("RGB")
            elif cut_img is not None and (k / FPS) > cut_at:
                shot = cut_img
            else:
                t = t0 + min(k / FPS, span)  # play at real speed, then hold the last frame
                fi = min(int(t * src_fps), len(frames) - 1)
                shot = Image.open(frames[fi]).convert("RGB")

            # A very slow push-in across each section, so no frame is ever pixel-identical to
            # the one before it. Every other fix here is per-section and depends on a pool
            # being present and long enough; this one cannot fail that way. It is deliberately
            # small -- 4% over half a minute reads as a camera settling, not as an effect --
            # and it exists because a terminal waiting on the GPU is genuinely motionless, so
            # even correctly-played real footage can sit still for ten seconds at a time.
            prog = k / max(n_frames - 1, 1)
            z = 1.0 - 0.04 * prog
            cw, ch = int(shot.width * z), int(shot.height * z)
            ox = int((shot.width - cw) * 0.5)
            oy = int((shot.height - ch) * prog)
            shot = shot.crop((ox, oy, ox + cw, oy + ch)).resize((shot.width, shot.height), LANCZOS)

            canvas = Image.new("RGB", (W, H), BG)
            d = ImageDraw.Draw(canvas)
            avail_h = H - NOTE_H - HEAD_H - 16
            scale = min((W - 48) / shot.width, avail_h / shot.height)
            shot = shot.resize((int(shot.width * scale), int(shot.height * scale)), LANCZOS)
            canvas.paste(shot, ((W - shot.width) // 2, HEAD_H + (avail_h - shot.height) // 2))

            d.text((44, 12), "DETERMINEX", font=f_title, fill=ACCENT)
            d.text((262, 22), "compiler-verified AI agents on AMD Radeon", font=f_small, fill=DIM)
            d.text((W - 300, 22), f"section {key} of 5", font=f_small, fill=DIM)

            y = H - NOTE_H
            d.rectangle([0, y, W, H], fill=(13, 16, 21))
            d.line([(0, y), (W, y)], fill=(30, 40, 36), width=2)
            for j, ln in enumerate(wrap(d, note, f_note, W - 96)[:3]):
                d.text((48, y + 20 + j * 30), ln, font=f_note, fill=(214, 222, 232))

            canvas.save(OUT / f"u_{idx:06d}.png")
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
            str(OUT / "u_%06d.png"),
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
