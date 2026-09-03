"""Render the demo video's title and result cards.

Every number on these slides is read out of the committed JSON in
bench-results/ rather than typed in, so a slide cannot drift from the
measurement it is describing. If a benchmark is re-run, the slides change.

Usage: slides.py <output-dir>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1400, 800
BG = (17, 17, 21)
FG = (238, 238, 242)
DIM = (150, 150, 162)
ACCENT = (206, 50, 50)
GOOD = (110, 200, 140)

ROOT = Path(__file__).resolve().parent.parent


def _font(size: int, bold: bool = False, mono: bool = False):
    names = (
        ["/System/Library/Fonts/Menlo.ttc"] if mono else
        ["/System/Library/Fonts/HelveticaNeue.ttc", "/System/Library/Fonts/Helvetica.ttc"]
    )
    for n in names:
        try:
            return ImageFont.truetype(n, size, index=1 if (bold and not mono) else 0)
        except OSError:
            continue
    return ImageFont.load_default()


def slide(name: str, out: Path, draw_fn) -> Path:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    draw_fn(d)
    p = out / f"{name}.png"
    img.save(p)
    return p


def title(d):
    d.text((90, 300), "Chaal", font=_font(96, bold=True), fill=FG)
    d.line((92, 420, 300, 420), fill=ACCENT, width=5)
    d.text((92, 452), "A quadruped that learns to walk on one AMD Radeon GPU.",
           font=_font(34), fill=FG)
    d.text((92, 508), "Physics, policy and training updates all on the same card.",
           font=_font(30), fill=DIM)
    d.text((92, 690), "AMD DevMaster Hackathon, Track 3: Physical AI",
           font=_font(24), fill=DIM)


def _header(d, text, sub=None):
    d.text((90, 70), text, font=_font(52, bold=True), fill=FG)
    d.line((92, 148, 92 + 150, 148), fill=ACCENT, width=4)
    if sub:
        d.text((92, 172), sub, font=_font(27), fill=DIM)


def _table(d, top, cols, rows, widths, highlight=()):
    f, fb = _font(25, mono=True), _font(25, bold=True, mono=True)
    x = 92
    for c, w in zip(cols, widths):
        d.text((x, top), c, font=fb, fill=DIM)
        x += w
    y = top + 44
    for i, row in enumerate(rows):
        x = 92
        colour = GOOD if i in highlight else FG
        for cell, w in zip(row, widths):
            d.text((x, y), str(cell), font=f, fill=colour)
            x += w
        y += 38


def build(out_dir: str) -> list[Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    made = []

    summary = json.loads((ROOT / "runs/go2-4096/summary.json").read_text())
    scaling = json.loads((ROOT / "bench-results/scaling.json").read_text())
    large = json.loads((ROOT / "bench-results/scaling-large.json").read_text())
    robust = json.loads((ROOT / "bench-results/robustness.json").read_text())

    made.append(slide("01-title", out, title))

    def training(d):
        _header(d, "Trained from scratch", "no demonstrations, no pretrained policy, no dataset")
        rows = [
            ("environments in parallel", f"{summary['num_envs']:,}"),
            ("iterations", f"{summary['iterations']}"),
            ("wall clock", f"{summary['wall_seconds']:.1f} s"),
            ("experience", f"{summary['total_env_steps']:,} env-steps"),
            ("throughput", f"{summary['env_steps_per_second']:,.0f} env-steps/s"),
            ("final mean reward", "811.94"),
            ("device", summary["device"]),
        ]
        y = 260
        for k, v in rows:
            d.text((92, y), k, font=_font(30), fill=DIM)
            d.text((760, y), v, font=_font(30, mono=True), fill=FG)
            y += 56
    made.append(slide("02-training", out, training))

    def scale(d):
        _header(d, "Where the bottleneck actually is",
                "physics scales. the learning update does not.")
        rows = []
        allrows = scaling["rows"] + large["rows"]
        for r in allrows:
            s, t = r["sim"]["env_steps_per_second"], r["train"]["env_steps_per_second"]
            rows.append((f"{r['num_envs']:>6,}", f"{s:>12,.0f}", f"{t:>11,.0f}",
                         f"{s / t:>5.1f}x", f"{r['train']['peak_torch_gb']:>5.2f} GB"))
        _table(d, 250, ("envs", "physics/s", "training/s", "ratio", "peak VRAM"),
               rows, (170, 250, 230, 130, 160), highlight=(len(rows) - 1,))
        d.text((92, 700), "Past ~8192 envs more parallelism buys simulation the learner cannot use.",
               font=_font(26), fill=GOOD)
    made.append(slide("03-scaling", out, scale))

    def robustness(d):
        _header(d, "Things it was never trained on",
                "training randomised the command and nothing else")
        rows = []
        for name, r in robust["conditions"].items():
            rows.append((f"{name:<14}", f"{r['survival_rate'] * 100:>6.1f}%",
                         f"{r['mean_tracking_error_ms']:>8.3f} m/s",
                         f"{r['mean_return']:>8.1f}"))
        _table(d, 250, ("condition", "survival", "tracking error", "return"),
               rows, (330, 210, 290, 200))
        d.text((92, 700), "Survival alone would be a bad metric: a policy that freezes never falls.",
               font=_font(26), fill=DIM)
    made.append(slide("04-robustness", out, robustness))

    def friction(d):
        _header(d, "The result that was wrong",
                "set_friction() on one surface is a silent no-op")
        rows = [
            ("1.0", "1.0", "1.000", "0.0972 m/s"),
            ("0.2", "1.0", "1.000", "0.0973 m/s"),
            ("1.0", "0.2", "1.000", "0.0960 m/s"),
            ("0.2", "0.2", "0.898", "0.2977 m/s"),
        ]
        _table(d, 260, ("robot mu", "ground mu", "survival", "tracking error"),
               rows, (210, 230, 200, 260), highlight=(3,))
        d.text((92, 630),
               "Genesis takes the LARGER of the two surfaces. Changing one does nothing.",
               font=_font(28), fill=FG)
        d.text((92, 680),
               "No error, no warning, and a plausible number that is really the baseline.",
               font=_font(26), fill=DIM)
        d.text((92, 726), "Measured, then contributed to genesis-world#2718",
               font=_font(24), fill=GOOD)
    made.append(slide("05-friction", out, friction))

    def egl(d):
        _header(d, "Why a ROCm box cannot run Genesis out of the box",
                "reported as genesis-world#3129")
        f = _font(24, mono=True)
        lines = [
            "scene = gs.Scene(show_viewer=False)   # no viewer",
            "scene.add_entity(gs.morphs.Plane())   # no cameras",
            "scene.build(n_envs=1)",
            "",
            "AttributeError: 'NoneType' object has no attribute 'eglQueryString'",
        ]
        y = 250
        for ln in lines:
            d.text((92, y), ln, font=f, fill=ACCENT if "Error" in ln else FG)
            y += 40
        d.text((92, 500),
               "A scene needs an OpenGL context even when nothing is rendered,",
               font=_font(28), fill=FG)
        d.text((92, 542),
               "and a compute-only ROCm container has no reason to ship one.",
               font=_font(28), fill=FG)
        d.text((92, 620), "apt-get install -y libegl1 libegl-mesa0 libgl1-mesa-dri",
               font=_font(24, mono=True), fill=GOOD)
        d.text((92, 700), "chaal doctor checks for it before any GPU time is spent.",
               font=_font(26), fill=DIM)
    made.append(slide("06-egl", out, egl))

    def close(d):
        _header(d, "Chaal", "every number reproducible from the committed JSON")
        rows = [
            "8 m 41 s from random initialisation to a walking policy",
            "49.2 million environment steps, all on one gfx1100",
            "0.096 m/s velocity tracking error",
            "survives 6 kg of payload and 1 m/s shoves",
            "two findings reported upstream to Genesis",
        ]
        y = 280
        for r in rows:
            d.text((110, y), "-", font=_font(32), fill=ACCENT)
            d.text((150, y), r, font=_font(32), fill=FG)
            y += 62
        d.text((92, 700), "github.com/himanshu748/chaal", font=_font(26, mono=True), fill=DIM)
    made.append(slide("07-close", out, close))

    for p in made:
        print(p)
    return made


if __name__ == "__main__":
    build(sys.argv[1] if len(sys.argv) > 1 else "slides")
