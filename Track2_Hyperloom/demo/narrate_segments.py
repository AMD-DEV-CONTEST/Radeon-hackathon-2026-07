#!/usr/bin/env python3
"""
narrate_segments.py — speak the LOCAL model's narration and mux it onto the
sped-up segments. All on the AMD Radeon R9700: the script was written by
Qwen-AgentWorld-35B-A3B (see generate_narration.py), the voice is kokoro-v1,
both served by Lemonade on the same card. No cloud TTS.

Placement is SEQUENTIAL, not hand-timed: each line starts after the previous
one finishes plus a small gap. That makes overlap structurally impossible,
which matters because the 1.75x speed-up leaves ~75% speech density and very
little slack. If the narration does not fit the runtime, this REPORTS it and
refuses to mux rather than quietly truncating the tail.

Usage: python3 narrate_segments.py [segment ...]
"""
import json, subprocess, sys, urllib.request
from pathlib import Path

URL   = "http://localhost:13305"
VOICE = "af_sky"
HERE  = Path(__file__).resolve().parent
SEG   = HERE / "self-narrated"
CUES  = SEG / "narration-cues.json"
LEAD  = 1.0     # silence before the first line
GAP   = 0.55    # breath between lines

def dur(p: Path) -> float:
    return float(subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(p)]).strip())

def tts(text: str, out: Path) -> float:
    req = urllib.request.Request(URL + "/api/v1/audio/speech",
        data=json.dumps({"model": "kokoro-v1", "input": text, "voice": VOICE}).encode(),
        headers={"Content-Type": "application/json"})
    out.write_bytes(urllib.request.urlopen(req, timeout=300).read())
    if out.stat().st_size < 800:
        raise RuntimeError(f"kokoro returned {out.stat().st_size}B for {text[:40]!r}")
    return dur(out)

def build(name: str, cues: list) -> bool:
    vid = SEG / f"{name}-fast.mp4"
    if not vid.exists():
        print(f"  !! {vid.name} missing"); return False
    if not cues:
        print(f"  !! no cues for {name}"); return False
    vlen = dur(vid)
    work = SEG / f".narr-{name}"; work.mkdir(exist_ok=True)
    print(f"\n=== {name}  (video {vlen:.1f}s, {len(cues)} lines) ===")

    placed, t = [], LEAD
    for i, line in enumerate(cues):
        mp3 = work / f"{i:02d}.mp3"
        d = tts(line, mp3)
        placed.append((t, mp3, d, line))
        print(f"  [{i}] {t:6.1f}s +{d:5.1f}s -> {t+d:6.1f}s   {line[:62]}")
        t += d + GAP

    total = t - GAP
    if total > vlen:
        over = total - vlen
        print(f"  !! NARRATION OVERRUNS VIDEO by {over:.1f}s "
              f"({total:.1f}s speech vs {vlen:.1f}s video)")
        print(f"     drop ~{int(over/4)+1} line(s) or lower the speed factor. NOT muxing.")
        return False
    print(f"  fits: {total:.1f}s speech in {vlen:.1f}s video "
          f"({total/vlen*100:.0f}% density, {vlen-total:.1f}s headroom)")

    inputs, filters, labels = [], [], []
    for i, (t0, mp3, _, _) in enumerate(placed):
        inputs += ["-i", str(mp3)]
        filters.append(f"[{i+1}:a]adelay={int(t0*1000)}|{int(t0*1000)}[a{i}]")
        labels.append(f"[a{i}]")
    fc = ";".join(filters) + ";" + "".join(labels) + \
         f"amix=inputs={len(placed)}:duration=longest:normalize=0,volume=2.0,apad[aout]"
    out = SEG / f"{name}-narrated.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(vid)] + inputs +
                   ["-filter_complex", fc, "-map", "0:v", "-map", "[aout]",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                    "-shortest", str(out)], check=True)
    print(f"  wrote {out.name}  ({out.stat().st_size/1048576:.1f} MB, {dur(out):.1f}s)")
    return True

if __name__ == "__main__":
    allcues = json.loads(CUES.read_text())
    names = sys.argv[1:] or list(allcues)
    ok = True
    for n in names:
        ok &= build(n, allcues.get(n, []))
    sys.exit(0 if ok else 1)
