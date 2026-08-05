#!/usr/bin/env python3
"""
record_terminal_segment.py — turn a real command's output into a video, deterministically.

Not a screen grab. A window-title capture records the screen REGION a window occupies, so
whatever is in front lands in the take — this project has a 120-second recording of somebody
else's chat window, produced by a pipeline that reported success at every step.

This runs the command for real, timestamps every line as it arrives, then renders those exact
lines to frames. The output cannot contain a desktop, cannot be cropped by a window manager,
and is reproducible from the captured log. The timings on screen are the timings that
happened: a line that took 12 seconds to arrive sits on screen for 12 seconds.

    python scripts/dev/record_terminal_segment.py --out C:/tmp/seg --title "..." -- <cmd...>
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FPS = 10
COLS_PX = 9
ROW_PX = 20
PAD = 24
WIDTH = 1280
HEIGHT = 760
BG = (10, 12, 16)
FG = (198, 214, 205)
ACCENT = (0, 220, 130)
DIM = (110, 125, 118)
RED = (232, 62, 78)


def _font(size: int = 15) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in ("consola.ttf", "DejaVuSansMono.ttf", "cour.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def capture(cmd: list[str], cwd: Path) -> list[tuple[float, str]]:
    """Run the command, returning (elapsed_seconds, line) for every line of output."""
    t0 = time.monotonic()
    lines: list[tuple[float, str]] = []
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        encoding="utf-8",
        errors="replace",
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        el = time.monotonic() - t0
        lines.append((el, line.rstrip("\n")))
        print(f"  [{el:6.1f}s] {line.rstrip()}", flush=True)
    proc.wait()
    return lines


def colour_for(line: str) -> tuple[int, int, int]:
    s = line.strip()
    if s.startswith("==") or s.isupper() and len(s) > 8:
        return ACCENT
    if "refused" in s or "LESS headroom" in s or "degraded" in s or "FELL" in s:
        return RED
    if s.startswith("$") or s.startswith("#"):
        return DIM
    return FG


def render(
    lines: list[tuple[float, str]], out_dir: Path, title: str, tail: float = 3.0
) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("f_*.png"):
        old.unlink()
    font = _font()
    title_font = _font(17)
    visible_rows = (HEIGHT - PAD * 2 - 44) // ROW_PX
    total = (lines[-1][0] if lines else 0) + tail
    n_frames = int(total * FPS) + 1

    for i in range(n_frames):
        t = i / FPS
        shown = [ln for (el, ln) in lines if el <= t]
        img = Image.new("RGB", (WIDTH, HEIGHT), BG)
        d = ImageDraw.Draw(img)
        d.text((PAD, PAD - 6), title, font=title_font, fill=ACCENT)
        d.line([(PAD, PAD + 22), (WIDTH - PAD, PAD + 22)], fill=(40, 52, 46), width=1)
        for row, ln in enumerate(shown[-visible_rows:]):
            y = PAD + 34 + row * ROW_PX
            d.text((PAD, y), ln[: (WIDTH - PAD * 2) // COLS_PX], font=font, fill=colour_for(ln))
        img.save(out_dir / f"f_{i:05d}.png")
    return n_frames


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="frames dir; the mp4 lands beside it")
    ap.add_argument("--title", default="")
    ap.add_argument("--cwd", default=".")
    ap.add_argument("cmd", nargs=argparse.REMAINDER)
    a = ap.parse_args()
    cmd = [c for c in a.cmd if c != "--"]
    if not cmd:
        print("no command given")
        return 2

    print(f"running: {' '.join(cmd)}")
    lines = capture(cmd, Path(a.cwd).resolve())
    if not lines:
        print("the command produced no output -- nothing to record")
        return 1

    out_dir = Path(a.out)
    n = render(lines, out_dir, a.title)
    log = out_dir.with_suffix(".log.json")
    log.write_text(json.dumps([{"t": round(e, 3), "line": ln} for e, ln in lines], indent=1))

    mp4 = out_dir.with_suffix(".mp4")
    ff = shutil.which("ffmpeg")
    if not ff:
        print(f"rendered {n} frames to {out_dir}; ffmpeg not found, not encoding")
        return 0
    subprocess.run(
        [ff, "-y", "-framerate", str(FPS), "-i", str(out_dir / "f_%05d.png"),
         "-vf", "format=yuv420p", "-r", "30", "-c:v", "libx264", "-preset", "slow",
         "-crf", "20", "-movflags", "+faststart", str(mp4)],
        check=True,
        capture_output=True,
    )
    print(f"\n  {n} frames -> {mp4}")
    print(f"  raw timed log -> {log}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
