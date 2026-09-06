"""Build the Track 3 demonstration video from the raw screen recording.

Layout: the JupyterLab terminal capture (1582x1668, nearly square) is scaled to the full
1080 height on the left, and the free space on the right carries a panel with the current
step and the numbers being shown. That way nothing overlaps the terminal text, which is the
actual evidence the video exists to show.

Everything is declarative: edit SEGMENTS and re-run. Narration is macOS `say`, subtitles and
panels are PIL-rendered PNGs overlaid with ffmpeg (this ffmpeg build has neither drawtext nor
libass, and PNG overlays give better control anyway).

    python build.py            # full build
    python build.py --seg 5    # rebuild one segment only (fast iteration)
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W = Path(__file__).resolve().parent
SRC = W / "src_20260805.mov"
REAL = Path("/Users/omiya/devlop/franka/franka_fruit_pick_demo/outputs/real_videos/"
            "cotrain2_020000/real_ep000.mp4")
OUT_DIR = W / "clips"
CANVAS = (1920, 1080)
TERM_W = 1024                      # 1582x1668 scaled to 1080 height
PANEL_X = TERM_W + 40
PANEL_W = CANVAS[0] - PANEL_X - 40

BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
REG = "/System/Library/Fonts/Supplemental/Arial.ttf"
FG = (238, 242, 248)
DIM = (150, 162, 178)
ACCENT = (46, 230, 168)
BG = (13, 17, 23)


@dataclass
class Seg:
    name: str
    dur: float                      # output duration in seconds
    src: tuple[float, float] | None = None   # (start, end) in the recording; None = card only
    title: str = ""
    lines: list[str] = field(default_factory=list)
    say: str = ""
    source: str = "term"            # term | real | card
    box: tuple[int, int, int, int, float, float] | None = None  # x,y,w,h,t0,t1 (canvas coords)
    # "side": near-square terminal on the left, text panel on the right.
    # "full": wide footage across the whole frame, text in a strip underneath — used for the
    #         real-robot shot, which is the result the video exists to show.
    layout: str = "side"


SEGMENTS: list[Seg] = [
    Seg("00_title", 11.0, None, source="card",
        title="Cheap Sim2Real",
        lines=["Teaching a $150 SO-101 arm",
               "with 10 real demonstrations",
               "",
               "Genesis · LeRobot ACT · AMD Radeon / ROCm",
               "",
               "Everything after this card is a real session."],
        say="Cheap Sim to Real. Teaching a one hundred fifty dollar robot arm with only ten "
            "real demonstrations, on a single AMD Radeon GPU. Everything you see from here is "
            "a real recorded session."),

    Seg("01_problem", 13.0, None, source="card",
        title="The cost is human time",
        lines=["Imitation learning wants ~50 demos per task.",
               "On real hardware that is 2-3 hours of a person",
               "driving a leader arm. Per task.",
               "",
               "So: generate the bulk in simulation,",
               "spend human time only where it must be spent."],
        say="Imitation learning normally wants about fifty demonstrations per task. On real "
            "hardware that is two to three hours of a person driving the arm, for every new "
            "task. So we generate the bulk in simulation, and spend human time only where it "
            "has to be spent."),

    Seg("02_clone", 9.0, (40, 66), title="1 · Get the project",
        lines=["git clone the submission branch",
               "cd .../submission",
               "",
               "The SO-101 URDF and meshes are bundled,",
               "so nothing else needs downloading."],
        say="We start from a fresh Radeon Cloud instance and clone the submission repository."),

    Seg("03_setup_start", 10.0, (66, 90), title="2 · bash setup.sh",
        lines=["1/5  system libraries (EGL, ffmpeg)",
               "2/5  verifying torch sees the Radeon GPU",
               "",
               "torch must come from the ROCm build —",
               "the PyPI wheel is CUDA and cannot see it."],
        say="One script sets the environment up. It first checks that this Python's torch can "
            "actually see the Radeon GPU, and refuses to continue if it cannot."),

    Seg("04_setup_deps", 11.0, (90, 310), title="3/5 · dependencies",
        lines=["~3 minutes, shown at 20x",
               "",
               "numpy 2.2.6 · scikit-image 0.25.2",
               "lerobot 0.6.0 · transformers 5.14.1",
               "",
               "These versions are pinned together:",
               "moving numpy alone breaks the image stack."],
        say="Dependencies take about three minutes here, shown sped up. The versions are "
            "pinned as a set, because numpy, scikit-image and lerobot have to agree."),

    Seg("05_smoke", 15.0, (310, 392), title="5/5 · smoke test",
        lines=["torch + ROCm → AMD Radeon Graphics",
               "PYOPENGL_PLATFORM = egl",
               "Genesis scene build → SO-101 + table + cube",
               "offscreen render → both cameras 640x480",
               "",
               "This proves the machine can run everything",
               "before any GPU hours are spent."],
        say="The last stage is a smoke test. It builds the Genesis scene headlessly and "
            "renders both cameras, so we know the machine can run the whole pipeline before "
            "spending any GPU hours."),

    Seg("06_smoke_ok", 12.0, (392, 404), title="SMOKE_OK",
        lines=["Data collection, training and simulated",
               "evaluation are all runnable on this host.",
               "",
               "Next:  bash run_pipeline.sh --quick"],
        say="Smoke test passed. Data collection, training and evaluation are all runnable on "
            "this host.",
        box=(150, 735, 860, 34, 3.0, 11.0)),

    Seg("07_fetch", 9.0, (404, 440), title="1/4 · fetch the dataset",
        lines=["omiya239532/so101_cube_dr",
               "50 episodes · full domain randomisation",
               "",
               "Collected by a scripted expert with no",
               "human in the loop — this is the step that",
               "replaces hours of teleoperation."],
        say="The pipeline pulls fifty simulated demonstrations, collected by a scripted expert "
            "with no human in the loop."),

    Seg("08_train", 14.0, (440, 502), title="2/4 · ACT training on the Radeon GPU",
        lines=["ACT · chunk 100 · ResNet-18 x2 · VAE",
               "",
               "2.58 step/s   3.9 GB VRAM",
               "data_s 0.002s  vs  updt_s 0.388s",
               "→ 99.5% of wall-clock is compute",
               "",
               "The reported runs are 100k steps, ~11 h each."],
        say="Training runs on the Radeon GPU. Data loading takes two milliseconds against three "
            "hundred eighty eight milliseconds of compute, so the GPU is the bottleneck, which "
            "is what you want. Five such runs went into this submission."),

    Seg("09_eval", 13.0, (502, 735), title="3/4 · closed-loop evaluation",
        lines=["Genesis on backend gs.amdgpu",
               "Device memory 47.98 GB",
               "",
               "Physics, camera rasterisation and policy",
               "inference all on the Radeon GPU.",
               "",
               "gs.cuda is rejected on ROCm — Taichi has",
               "no HIP path — so ask for gs.gpu and let",
               "Genesis resolve the device."],
        say="Evaluation closes the loop in simulation. Genesis runs on the amdgpu backend: "
            "physics, camera rendering and policy inference are all on the Radeon GPU."),

    Seg("10_result", 16.0, (738, 756), title="4/4 · PIPELINE_OK",
        lines=["dataset → ROCm training → closed-loop eval",
               "in about 3 minutes",
               "",
               "0% success is the intended result here:",
               "--quick trains for 100 steps.",
               "It is a plumbing check, not a policy.",
               "",
               "Measured: 25% at 20k steps,",
               "peaks at 60% at 60k, then declines."],
        say="Pipeline OK. The zero percent is the intended result: this quick mode trains for "
            "only one hundred steps, so it checks the plumbing, not the policy. Trained "
            "properly, this task reaches sixty percent in simulation at sixty thousand steps."),

    # Source trimmed to the action: the cube is on the sheet by ~24 s and the rest of the
    # recording is the arm sitting still, which adds nothing.
    Seg("11_real", 18.0, (8, 28), title="On the physical SO-101", source="real", layout="full",
        lines=["Sim-pretrained, then fine-tuned with 10 real teleoperation episodes — about 35 minutes of human time",
               "85% success (17/20)   ·   placement error 1-2 cm   ·   overhead view (left) and wrist camera (right)",
               "The first grasp slips and the policy retries: recovery behaviour learned from the simulated expert"],
        say="And this is the same approach on the physical arm. Sim pretrained, then fine tuned "
            "with only ten real teleoperation episodes. Eighty five percent success over twenty "
            "attempts, placing the cube within one to two centimetres."),

    Seg("12_close", 15.0, None, source="card",
        title="Results",
        lines=["Real robot,  sim + 10 real demos      85%   (17/20)",
               "Real robot,  10 real demos only       25%   (5/20)",
               "                                     Fisher p = 0.00033",
               "",
               "Simulation, 50 scripted demos         60%   at 60k steps",
               "",
               "Colour generalisation tracks object-background RGB",
               "contrast, not hue   (r = 0.879, 20 episodes per colour)",
               "",
               "huggingface.co/omiya239532",
               "AMD AI DevMaster Hackathon · Track 3"],
        say="Eighty five percent on the physical robot with ten real demonstrations, against "
            "twenty five percent without the simulated pretraining. Twenty attempts each, on the "
            "same placements, and the difference is significant. The simulated pretraining is "
            "what makes ten real demonstrations enough. Model and datasets are public. Thank you."),
]


# ---------------------------------------------------------------- rendering helpers

def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


def render_panel(seg: Seg, path: Path) -> None:
    """Right-hand panel: step title plus the numbers on screen."""
    img = Image.new("RGBA", (PANEL_W, CANVAS[1]), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    ft = _font(BOLD, 40)
    fl = _font(REG, 26)
    y = 150
    d.text((0, y), seg.title, font=ft, fill=ACCENT)
    y += 78
    d.line((0, y, 120, y), fill=ACCENT, width=3)
    y += 40
    for line in seg.lines:
        if not line:
            y += 20
            continue
        d.text((0, y), line, font=fl, fill=FG if not line.startswith(("→", "(")) else DIM)
        y += 40
    img.save(path)


def render_strip(seg: Seg, path: Path) -> None:
    """Bottom caption strip for the full-width layout."""
    h = 200
    img = Image.new("RGBA", (CANVAS[0], h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, CANVAS[0], h), fill=(9, 12, 18, 225))
    ft = _font(BOLD, 38)
    fl = _font(REG, 25)
    d.text((80, 16), seg.title, font=ft, fill=ACCENT)
    y = 72
    for line in seg.lines:
        if not line:
            y += 16
            continue
        d.text((80, y), line, font=fl, fill=FG)
        y += 38
    img.save(path)


def render_card(seg: Seg, path: Path) -> None:
    """Full-frame title/summary card."""
    img = Image.new("RGB", CANVAS, BG)
    d = ImageDraw.Draw(img)
    ft = _font(BOLD, 76)
    fl = _font(REG, 34)
    d.text((150, 250), seg.title, font=ft, fill=ACCENT)
    d.line((150, 360, 420, 360), fill=ACCENT, width=4)
    y = 430
    for line in seg.lines:
        if not line:
            y += 26
            continue
        d.text((150, y), line, font=fl, fill=FG)
        y += 52
    img.save(path)


def narrate(text: str, path: Path) -> float:
    """macOS TTS -> aiff; returns duration in seconds."""
    if not text:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                        "-i", "anullsrc=r=48000:cl=stereo", "-t", "0.5", str(path)], check=True)
        return 0.5
    subprocess.run(["say", "-v", "Samantha", "-r", "180", "-o", str(path), text], check=True)
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


# ---------------------------------------------------------------- segment build

def build_segment(i: int, seg: Seg) -> Path:
    OUT_DIR.mkdir(exist_ok=True)
    clip = OUT_DIR / f"{seg.name}.mp4"
    aud = OUT_DIR / f"{seg.name}.aiff"
    ndur = narrate(seg.say, aud)
    dur = max(seg.dur, ndur + 0.8)

    if seg.source == "card":
        card = OUT_DIR / f"{seg.name}_card.png"
        render_card(seg, card)
        vf = f"scale={CANVAS[0]}:{CANVAS[1]},format=yuv420p"
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", str(card),
               "-i", str(aud), "-t", f"{dur}", "-vf", vf, "-r", "30",
               "-c:v", "libx264", "-crf", "20", "-c:a", "aac", "-b:a", "128k",
               "-shortest", str(clip)]
        subprocess.run(cmd, check=True)
        return clip

    t0, t1 = seg.src
    span = t1 - t0
    src = SRC if seg.source == "term" else REAL
    overlay = OUT_DIR / f"{seg.name}_panel.png"
    if seg.layout == "full":
        render_strip(seg, overlay)
        place = f"scale={CANVAS[0]}:-2,setsar=1"
        px, py = 0, CANVAS[1] - 200
    else:
        render_panel(seg, overlay)
        place = f"scale={TERM_W}:{CANVAS[1]},setsar=1"
        px, py = PANEL_X, 0

    fg = OUT_DIR / f"{seg.name}_fg.txt"
    box = ""
    if seg.box:
        bx, by, bw, bh, bt0, bt1 = seg.box
        box = (f",drawbox=x={bx}:y={by}:w={bw}:h={bh}:color=0x2ee6a8@0.95:t=3"
               f":enable='between(t\\,{bt0}\\,{bt1})'")
    fg.write_text(
        f"[0:v]trim=start={t0}:end={t1},setpts=(PTS-STARTPTS)/{span/dur},{place}[term];\n"
        f"color=c=0x0d1117:s={CANVAS[0]}x{CANVAS[1]}:d={dur}[bgc];\n"
        f"[bgc][term]overlay=x=0:y=(H-h)/2:shortest=1{box}[stage];\n"
        f"[stage][1:v]overlay=x={px}:y={py}[v]\n")

    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-i", str(overlay),
           "-i", str(aud), "-filter_complex_script", str(fg),
           "-map", "[v]", "-map", "2:a", "-t", f"{dur}", "-r", "30",
           "-c:v", "libx264", "-crf", "21", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "128k", str(clip)]
    subprocess.run(cmd, check=True)
    return clip


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seg", type=int, default=None, help="build only this segment index")
    ap.add_argument("--no-concat", action="store_true")
    args = ap.parse_args()

    todo = [(args.seg, SEGMENTS[args.seg])] if args.seg is not None else list(enumerate(SEGMENTS))
    clips = []
    for i, seg in todo:
        print(f"[{i:02d}] {seg.name} ...", flush=True)
        clips.append(build_segment(i, seg))
        print(f"     -> {clips[-1].name}", flush=True)

    if args.seg is not None or args.no_concat:
        print("SEGMENT_OK")
        return

    lst = OUT_DIR / "concat.txt"
    lst.write_text("".join(f"file '{c}'\n" for c in clips))
    final = W / "demo_video_20260805.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                    "-i", str(lst), "-c:v", "libx264", "-crf", "21", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(final)],
                   check=True)
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration,size",
                          "-of", "csv=p=0", str(final)], capture_output=True, text=True)
    print("FINAL", final, out.stdout.strip())


if __name__ == "__main__":
    sys.exit(main())
