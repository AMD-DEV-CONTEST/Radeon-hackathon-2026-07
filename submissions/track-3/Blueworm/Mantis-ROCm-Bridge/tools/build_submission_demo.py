#!/usr/bin/env python3
"""Build the polished Mantis-ROCm Bridge submission demo.

The builder is intentionally fail-closed: inputs are read-only, the output
directory must not exist, and the learned-policy clip is always labelled as a
pipeline smoke rather than task success.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

try:
    from PIL import Image, ImageDraw, ImageFont
except ModuleNotFoundError:  # Source-contract tests run without media dependencies.
    Image = ImageDraw = ImageFont = None


WIDTH = 1280
HEIGHT = 720
FPS = 30
SUBTITLE_BAND_TOP = 636
BG = (11, 14, 18)
PANEL = (24, 29, 35)
PANEL_2 = (34, 40, 47)
TEXT = (241, 244, 246)
MUTED = (157, 167, 178)
CORAL = (240, 95, 62)
GREEN = (62, 191, 133)
YELLOW = (232, 186, 72)
BLUE = (74, 139, 204)
RED = (218, 76, 76)


@dataclass(frozen=True)
class Segment:
    key: str
    kind: str
    duration: int
    narration: str
    caption: str


SEGMENTS = (
    Segment(
        "live_intro",
        "live",
        10,
        "Mantis-ROCm Bridge ports a custom dual-arm robot into Genesis on AMD Radeon, then runs an ACT policy directly in the three-bowl task.",
        "A custom dual-arm robot, running policy-in-loop on AMD ROCm.",
    ),
    Segment(
        "porting_thesis",
        "card",
        16,
        "The hard part of a robot port is rarely one API call. Joint order, cameras, clocks, grippers, controllers, safety, and assets all hide assumptions.",
        "Robot ports fail at hidden interfaces, not at one API call.",
    ),
    Segment(
        "contract_architecture",
        "card",
        20,
        "We make those assumptions explicit. A source task contract feeds a robot profile, a URDF-to-ROCm compiler, a policy adapter, and evidence gates that fail closed.",
        "Source semantics -> robot profile -> ROCm port -> policy adapter -> evidence gate.",
    ),
    Segment(
        "amd_runtime",
        "card",
        14,
        "The runtime is one AMD Radeon GPU with ROCm 7.2.1, PyTorch 2.9.1, Genesis 1.3.0, and the native G S AMD G P U backend.",
        "One Radeon GPU. ROCm 7.2.1. PyTorch 2.9.1. Genesis 1.3.0. gs.amdgpu.",
    ),
    Segment(
        "expert_data",
        "expert",
        18,
        "These successful scripted episodes were generated on the 4090 development host, transferred to AMD, and used as expert data. They are demonstrations, not policy results.",
        "Successful scripted expert data, generated on 4090 and transferred to AMD.",
    ),
    Segment(
        "learning_interface",
        "card",
        18,
        "The adapter maps eighteen physical joints to a sixteen-dimensional learning interface. ACT consumes one environment camera and two simulated wrist cameras. These are not physical calibrations.",
        "18D robot <-> 16D ACT, with three simulated camera observations.",
    ),
    Segment(
        "training_evidence",
        "card",
        17,
        "On the current AMD worker, a fresh fifty-step run proves the training pipeline. The historical official baseline reached sixty thousand steps. Loss and finite actions do not prove task success.",
        "AMD training and open-loop inference are evidence levels, not task success.",
    ),
    Segment(
        "live_result",
        "live",
        16,
        "Here the saved ACT processor and checkpoint run inside the Genesis loop on AMD. The robot is upright and the three bowls are present, but this short smoke checkpoint does not complete the task.",
        "AMD policy-in-loop smoke: correct scene and flow; task not completed.",
    ),
    Segment(
        "honest_result",
        "card",
        18,
        "Our strict official evaluation remains zero successes out of ten: eight timeouts and two collision-safety stops. We report that failure instead of turning a loss curve into a success claim.",
        "Official strict G3: 0/10. Eight timeouts. Two collision-safety stops.",
    ),
    Segment(
        "what_ships",
        "card",
        13,
        "What ships is the reusable bridge: declarative contracts, the robot-port compiler, the LeRobot adapter, safety gates, reproducible commands, and evidence that separates availability from capability.",
        "The deliverable is a reusable, auditable robot-porting bridge.",
    ),
    Segment(
        "live_close",
        "live",
        8,
        "Mantis-ROCm Bridge is a practical path from custom robot assets to auditable learning experiments on AMD ROCm.",
        "Mantis-ROCm Bridge | Zhiwen Su | Team Blueworm | Track 3",
    ),
)

TOTAL_DURATION = sum(segment.duration for segment in SEGMENTS)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live-infer-clip", required=True)
    parser.add_argument("--expert-parquet", required=True)
    parser.add_argument("--expert-outcomes", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--narration-dir")
    parser.add_argument("--ffmpeg", default="/usr/bin/ffmpeg")
    parser.add_argument("--ffprobe", default="/usr/bin/ffprobe")
    return parser.parse_args()


def absolute_file(value: str, label: str) -> Path:
    path = Path(value)
    if not path.is_absolute() or not path.is_file() or path.is_symlink():
        raise ValueError(f"{label} must be an absolute regular file: {value}")
    return path


def command(argv: list[str]) -> None:
    subprocess.run(argv, check=True)


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if ImageFont is None:
        raise RuntimeError("Pillow is required to build the submission demo")
    candidates = (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
        if bold
        else "/System/Library/Fonts/Supplemental/Arial.ttf",
    )
    for candidate in candidates:
        if Path(candidate).is_file():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def wrap(draw: ImageDraw.ImageDraw, text: str, xy: tuple[int, int], width: int, size: int, fill=TEXT, bold=False, spacing=10) -> int:
    words = text.split()
    lines: list[str] = []
    current = ""
    selected_font = font(size, bold=bold)
    for word in words:
        trial = f"{current} {word}".strip()
        if draw.textlength(trial, font=selected_font) <= width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    x, y = xy
    line_height = size + spacing
    for line in lines:
        draw.text((x, y), line, font=selected_font, fill=fill)
        y += line_height
    return y


def base_card(kicker: str, title: str) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    if Image is None or ImageDraw is None:
        raise RuntimeError("Pillow is required to build the submission demo")
    image = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 12, HEIGHT), fill=CORAL)
    draw.text((64, 54), kicker.upper(), font=font(18, True), fill=CORAL)
    draw.text((64, 92), title, font=font(44, True), fill=TEXT)
    draw.line((64, 158, WIDTH - 64, 158), fill=PANEL_2, width=2)
    return image, draw


def rounded_panel(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], outline=PANEL_2, fill=PANEL) -> None:
    draw.rounded_rectangle(box, radius=8, fill=fill, outline=outline, width=2)


def arrow(draw: ImageDraw.ImageDraw, start: tuple[int, int], end: tuple[int, int], color=MUTED) -> None:
    draw.line((*start, *end), fill=color, width=4)
    x, y = end
    draw.polygon(((x, y), (x - 12, y - 8), (x - 12, y + 8)), fill=color)


def render_porting_thesis() -> Image.Image:
    image, draw = base_card("01 / The thesis", "A robot port is a contract problem")
    items = (
        ("Embodiment", "joint order, limits, grippers", CORAL),
        ("Perception", "camera keys, shapes, transforms", BLUE),
        ("Execution", "clocks, controllers, safety", YELLOW),
        ("Evidence", "what ran, where, and what it proves", GREEN),
    )
    for index, (title, detail, color) in enumerate(items):
        x = 64 + (index % 2) * 580
        y = 205 + (index // 2) * 190
        rounded_panel(draw, (x, y, x + 540, y + 148))
        draw.rectangle((x, y, x + 8, y + 148), fill=color)
        draw.text((x + 34, y + 25), title, font=font(26, True), fill=TEXT)
        wrap(draw, detail, (x + 34, y + 72), 460, 20, MUTED)
    draw.text((64, 584), "Make hidden assumptions explicit before execution.", font=font(23, True), fill=CORAL)
    return image


def render_contract_architecture() -> Image.Image:
    image, draw = base_card("02 / Architecture", "One path from source semantics to evidence")
    labels = (
        ("SOURCE TASK", "stack_bowls_three", BLUE),
        ("ROBOT PROFILE", "joints + cameras", CORAL),
        ("ROCm PORT", "URDF compiler", YELLOW),
        ("POLICY ADAPTER", "LeRobot ACT", GREEN),
        ("EVIDENCE GATE", "fail closed", RED),
    )
    y = 270
    box_width = 198
    gap = 34
    for index, (title, detail, color) in enumerate(labels):
        x = 48 + index * (box_width + gap)
        rounded_panel(draw, (x, y, x + box_width, y + 170), outline=color)
        draw.rectangle((x, y, x + box_width, y + 8), fill=color)
        draw.text((x + 18, y + 34), title, font=font(17, True), fill=color)
        wrap(draw, detail, (x + 18, y + 82), box_width - 36, 20, TEXT, bold=True)
        if index < len(labels) - 1:
            arrow(draw, (x + box_width + 6, y + 85), (x + box_width + gap - 7, y + 85))
    draw.text((64, 544), "Availability  !=  optimization  !=  open-loop inference  !=  task success", font=font(25, True), fill=TEXT)
    draw.text((64, 594), "Each level earns its own receipt.", font=font(22), fill=MUTED)
    return image


def render_amd_runtime() -> Image.Image:
    image, draw = base_card("03 / Runtime", "Native Genesis execution on AMD Radeon")
    metrics = (
        ("1", "Radeon GPU", CORAL),
        ("7.2.1", "ROCm / HIP", GREEN),
        ("2.9.1", "PyTorch ROCm", BLUE),
        ("1.3.0", "Genesis", YELLOW),
    )
    for index, (value, label, color) in enumerate(metrics):
        x = 64 + index * 292
        rounded_panel(draw, (x, 220, x + 258, 430), outline=color)
        draw.text((x + 26, 258), value, font=font(48, True), fill=color)
        draw.text((x + 26, 336), label, font=font(21, True), fill=TEXT)
    draw.text((64, 512), "Backend", font=font(18, True), fill=MUTED)
    draw.text((64, 546), "gs.amdgpu", font=font(38, True), fill=TEXT)
    draw.text((340, 557), "torch.cuda API exposes the AMD HIP device", font=font(20), fill=MUTED)
    return image


def render_learning_interface() -> Image.Image:
    image, draw = base_card("04 / Interface", "Preserve task semantics across embodiments")
    rounded_panel(draw, (70, 222, 340, 480), outline=CORAL)
    draw.text((106, 258), "MANTIS", font=font(24, True), fill=CORAL)
    draw.text((112, 318), "18D", font=font(58, True), fill=TEXT)
    draw.text((102, 400), "physical joints", font=font(19), fill=MUTED)
    arrow(draw, (360, 350), (470, 350), CORAL)
    rounded_panel(draw, (490, 222, 760, 480), outline=GREEN)
    draw.text((576, 258), "ACT", font=font(24, True), fill=GREEN)
    draw.text((552, 318), "16D", font=font(58, True), fill=TEXT)
    draw.text((530, 400), "state + action", font=font(19), fill=MUTED)
    arrow(draw, (780, 350), (885, 350), GREEN)
    rounded_panel(draw, (905, 202, 1200, 505), outline=BLUE)
    draw.text((942, 238), "3 SIM CAMERAS", font=font(20, True), fill=BLUE)
    for index, label in enumerate(("environment", "left wrist", "right wrist")):
        y = 290 + index * 66
        draw.rectangle((943, y, 979, y + 24), outline=TEXT, width=2)
        draw.ellipse((953, y + 6, 969, y + 22), outline=TEXT, width=2)
        draw.text((998, y - 2), label, font=font(19), fill=TEXT)
    draw.text((64, 584), "Simulation mounts only. No physical camera calibration claim.", font=font(23, True), fill=YELLOW)
    return image


def render_training_evidence() -> Image.Image:
    image, draw = base_card("05 / Learning", "Train and infer on AMD, without inflating the claim")
    rows = (
        ("CURRENT PIPELINE", "50 steps", "fresh AMD smoke", GREEN),
        ("OFFICIAL BASELINE", "60,000 steps", "natural exit", BLUE),
        ("OPEN LOOP", "12 / 12", "finite actions", YELLOW),
    )
    for index, (label, value, note, color) in enumerate(rows):
        y = 210 + index * 126
        rounded_panel(draw, (64, y, 930, y + 98), outline=color)
        draw.text((92, y + 20), label, font=font(17, True), fill=color)
        draw.text((340, y + 15), value, font=font(34, True), fill=TEXT)
        draw.text((650, y + 27), note, font=font(20), fill=MUTED)
    rounded_panel(draw, (970, 210, 1200, 560), outline=RED)
    draw.text((1008, 248), "EVIDENCE", font=font(18, True), fill=RED)
    draw.text((1043, 308), "!=", font=font(54, True), fill=TEXT)
    draw.text((1005, 390), "TASK", font=font(26, True), fill=TEXT)
    draw.text((995, 430), "SUCCESS", font=font(26, True), fill=TEXT)
    return image


def render_honest_result() -> Image.Image:
    image, draw = base_card("06 / Result", "The strict result is negative, and useful")
    draw.text((72, 214), "0 / 10", font=font(104, True), fill=RED)
    draw.text((78, 340), "official strict G3 successes", font=font(23, True), fill=TEXT)
    rounded_panel(draw, (550, 220, 820, 470), outline=YELLOW)
    draw.text((606, 260), "8", font=font(72, True), fill=YELLOW)
    draw.text((605, 358), "timeouts", font=font(24, True), fill=TEXT)
    rounded_panel(draw, (865, 220, 1195, 470), outline=CORAL)
    draw.text((930, 260), "2", font=font(72, True), fill=CORAL)
    draw.text((905, 358), "collision-safety", font=font(23, True), fill=TEXT)
    draw.text((72, 548), "We publish the failure instead of turning loss into a success claim.", font=font(26, True), fill=TEXT)
    draw.text((72, 602), "Next improvement target: better demonstrations and policy quality.", font=font(20), fill=MUTED)
    return image


def render_what_ships() -> Image.Image:
    image, draw = base_card("07 / Contribution", "A reusable bridge, not a one-off screenshot")
    items = (
        ("Contracts", "task, robot, cameras, clocks", CORAL),
        ("Compiler", "URDF -> executable ROCm port", YELLOW),
        ("Adapter", "LeRobot ACT + 18D/16D mapping", GREEN),
        ("Evidence", "runtime, training, inference, evaluation", BLUE),
    )
    for index, (title, detail, color) in enumerate(items):
        x = 64 + (index % 2) * 580
        y = 210 + (index // 2) * 175
        rounded_panel(draw, (x, y, x + 540, y + 132), outline=color)
        draw.text((x + 26, y + 22), title, font=font(25, True), fill=color)
        draw.text((x + 26, y + 72), detail, font=font(19), fill=TEXT)
    draw.text((64, 594), "Raw third-party robot assets stay external to the public package.", font=font(21, True), fill=MUTED)
    return image


CARD_RENDERERS: dict[str, Callable[[], Image.Image]] = {
    "porting_thesis": render_porting_thesis,
    "contract_architecture": render_contract_architecture,
    "amd_runtime": render_amd_runtime,
    "learning_interface": render_learning_interface,
    "training_evidence": render_training_evidence,
    "honest_result": render_honest_result,
    "what_ships": render_what_ships,
}


def validate_expert_outcomes(path: Path) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    episodes = data.get("episodes")
    if not isinstance(episodes, list):
        raise ValueError("expert outcomes must contain episodes")
    episode = next((item for item in episodes if item.get("episode_index") == 0), None)
    if not episode or episode.get("success") is not True or episode.get("frame_count") != 1152:
        raise ValueError("episode 0 must be the accepted 1,152-frame successful expert episode")


def extract_expert_frames(parquet_path: Path, destination: Path) -> int:
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    table = pq.read_table(
        parquet_path,
        columns=["observation.images.env_cam", "episode_index", "frame_index"],
    )
    table = table.filter(pc.equal(table["episode_index"], 0)).sort_by("frame_index")
    rows = table.to_pylist()
    if len(rows) != 1152:
        raise ValueError(f"expected 1,152 expert frames, got {len(rows)}")
    destination.mkdir()
    for index, row in enumerate(rows):
        payload = row["observation.images.env_cam"]
        if not isinstance(payload, dict) or not isinstance(payload.get("bytes"), bytes):
            raise ValueError(f"missing embedded env camera bytes at frame {index}")
        (destination / f"frame_{index:06d}.png").write_bytes(payload["bytes"])
    return len(rows)


def make_overlay(key: str, destination: Path) -> None:
    image = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((960, 0, WIDTH, HEIGHT), fill=(*BG, 255))
    draw.rectangle((960, 0, 972, HEIGHT), fill=(*CORAL, 255))
    if key == "expert_data":
        kicker, title, lines, status, color = (
            "SCRIPTED EXPERT DATA",
            "Successful trajectory",
            ("Seed 1001", "1,152 frames", "4090 generated", "transferred to AMD"),
            "NOT POLICY OUTPUT",
            GREEN,
        )
    elif key == "live_close":
        kicker, title, lines, status, color = (
            "MANTIS-ROCm BRIDGE",
            "Track 3",
            ("Zhiwen Su", "Team Blueworm", "AMD Radeon", "Genesis + LeRobot"),
            "HONEST EVIDENCE",
            CORAL,
        )
    else:
        kicker, title, lines, status, color = (
            "AMD POLICY-IN-LOOP",
            "Three-bowl task",
            ("Genesis 1.3.0", "gs.amdgpu", "ACT checkpoint", "50-step smoke"),
            "TASK NOT COMPLETED",
            CORAL,
        )
    draw.text((1002, 55), kicker, font=font(17, True), fill=color)
    wrap(draw, title, (1002, 98), 238, 34, TEXT, bold=True, spacing=8)
    y = 245
    for line in lines:
        draw.ellipse((1004, y + 7, 1014, y + 17), fill=color)
        draw.text((1032, y), line, font=font(19), fill=TEXT)
        y += 58
    draw.rounded_rectangle((997, 553, 1244, 624), radius=7, outline=color, width=2)
    draw.text((1015, 577), status, font=font(16, True), fill=color)
    destination.parent.mkdir(parents=True, exist_ok=True)
    image.save(destination)


def make_card_segment(ffmpeg: Path, image: Path, duration: int, output: Path) -> None:
    command([
        str(ffmpeg), "-nostdin", "-y", "-hide_banner", "-loglevel", "error",
        "-loop", "1", "-i", str(image), "-t", str(duration),
        "-vf", f"fps={FPS},format=yuv420p", "-c:v", "libx264", "-preset", "veryfast",
        "-crf", "18", "-an", str(output),
    ])


def make_live_segment(ffmpeg: Path, source: Path, overlay: Path, duration: int, output: Path) -> None:
    filter_graph = (
        f"[0:v]scale=960:{HEIGHT}:flags=lanczos,fps={FPS},format=rgba," 
        f"pad={WIDTH}:{HEIGHT}:0:0:color=0x0B0E12[base];"
        "[base][1:v]overlay=0:0,format=yuv420p[outv]"
    )
    command([
        str(ffmpeg), "-nostdin", "-y", "-hide_banner", "-loglevel", "error",
        "-stream_loop", "-1", "-i", str(source), "-loop", "1", "-i", str(overlay),
        "-t", str(duration), "-filter_complex", filter_graph, "-map", "[outv]",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-an", str(output),
    ])


def make_expert_clip(ffmpeg: Path, frames: Path, output: Path) -> None:
    command([
        str(ffmpeg), "-nostdin", "-y", "-hide_banner", "-loglevel", "error",
        "-framerate", "64", "-i", str(frames / "frame_%06d.png"),
        "-vf", f"fps={FPS},format=yuv420p", "-c:v", "libx264", "-preset", "veryfast",
        "-crf", "18", "-an", str(output),
    ])


def make_narration(ffmpeg: Path, narration_dir: Path, output: Path) -> None:
    inputs: list[str] = []
    filters: list[str] = []
    for index, segment in enumerate(SEGMENTS, start=1):
        audio = narration_dir / f"{index:02d}.aiff"
        if not audio.is_file():
            raise ValueError(f"missing narration segment: {audio}")
        inputs.extend(("-i", str(audio)))
        filters.append(
            f"[{index - 1}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"apad=pad_dur={segment.duration},atrim=0:{segment.duration}[a{index - 1}]"
        )
    joined = "".join(f"[a{index}]" for index in range(len(SEGMENTS)))
    filters.append(f"{joined}concat=n={len(SEGMENTS)}:v=0:a=1[outa]")
    command([
        str(ffmpeg), "-nostdin", "-y", "-hide_banner", "-loglevel", "error",
        *inputs, "-filter_complex", ";".join(filters), "-map", "[outa]",
        "-c:a", "aac", "-b:a", "160k", str(output),
    ])


def srt_time(seconds: int) -> str:
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},000"


def write_srt(path: Path) -> None:
    elapsed = 0
    blocks = []
    for index, segment in enumerate(SEGMENTS, start=1):
        blocks.append(
            f"{index}\n{srt_time(elapsed)} --> {srt_time(elapsed + segment.duration)}\n{segment.caption}\n"
        )
        elapsed += segment.duration
    path.write_text("\n".join(blocks), encoding="utf-8")


def probe_video(ffprobe: Path, video: Path) -> dict:
    completed = subprocess.run(
        [
            str(ffprobe), "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=codec_name,width,height,r_frame_rate,pix_fmt",
            "-show_entries", "format=duration", "-of", "json", str(video),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    data = json.loads(completed.stdout)
    stream = data["streams"][0]
    duration = float(data["format"]["duration"])
    if stream["codec_name"] != "h264" or stream["width"] != WIDTH or stream["height"] != HEIGHT:
        raise ValueError(f"unexpected final video stream: {stream}")
    if stream["r_frame_rate"] != f"{FPS}/1" or stream["pix_fmt"] != "yuv420p":
        raise ValueError(f"unexpected frame rate or pixel format: {stream}")
    if not math.isclose(duration, TOTAL_DURATION, abs_tol=0.15):
        raise ValueError(f"unexpected duration: {duration}")
    return data


def main() -> int:
    args = parse_args()
    live_clip = absolute_file(args.live_infer_clip, "--live-infer-clip")
    expert_parquet = absolute_file(args.expert_parquet, "--expert-parquet")
    expert_outcomes = absolute_file(args.expert_outcomes, "--expert-outcomes")
    ffmpeg = absolute_file(args.ffmpeg, "--ffmpeg")
    ffprobe = absolute_file(args.ffprobe, "--ffprobe")
    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute() or output_dir.exists():
        raise ValueError("--output-dir must be an absolute path that does not exist")
    narration_dir = Path(args.narration_dir) if args.narration_dir else None
    if narration_dir is not None and (not narration_dir.is_absolute() or not narration_dir.is_dir()):
        raise ValueError("--narration-dir must be an absolute directory")

    validate_expert_outcomes(expert_outcomes)
    output_dir.mkdir(parents=False)
    cards = output_dir / "cards"
    overlays = output_dir / "overlays"
    segments_dir = output_dir / "segments"
    cards.mkdir()
    overlays.mkdir()
    segments_dir.mkdir()

    expert_frames = output_dir / "expert_frames"
    expert_count = extract_expert_frames(expert_parquet, expert_frames)
    expert_raw = output_dir / "expert_env_episode0.mp4"
    make_expert_clip(ffmpeg, expert_frames, expert_raw)

    segment_files: list[Path] = []
    for index, segment in enumerate(SEGMENTS, start=1):
        destination = segments_dir / f"{index:02d}_{segment.key}.mp4"
        if segment.kind == "card":
            image_path = cards / f"{index:02d}_{segment.key}.png"
            CARD_RENDERERS[segment.key]().save(image_path)
            make_card_segment(ffmpeg, image_path, segment.duration, destination)
        else:
            overlay = overlays / f"{index:02d}_{segment.key}.png"
            make_overlay(segment.key, overlay)
            source = expert_raw if segment.kind == "expert" else live_clip
            make_live_segment(ffmpeg, source, overlay, segment.duration, destination)
        segment_files.append(destination)

    concat_list = output_dir / "concat.txt"
    concat_list.write_text("".join(f"file '{path}'\n" for path in segment_files), encoding="utf-8")
    concat_video = output_dir / "video_no_captions.mp4"
    command([
        str(ffmpeg), "-nostdin", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "concat", "-safe", "0", "-i", str(concat_list), "-c", "copy", str(concat_video),
    ])

    subtitles = output_dir / "captions.srt"
    write_srt(subtitles)
    narration = None
    if narration_dir is not None:
        narration = output_dir / "narration.m4a"
        make_narration(ffmpeg, narration_dir, narration)

    final = output_dir / "Mantis_ROCm_Bridge_submission_demo_20260806_v2.mp4"
    escaped_srt = str(subtitles).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
    final_command = [
        str(ffmpeg), "-nostdin", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(concat_video),
    ]
    if narration is not None:
        final_command.extend(("-i", str(narration)))
    final_command.extend((
        "-vf",
        f"drawbox=x=0:y={SUBTITLE_BAND_TOP}:w=iw:h=ih-{SUBTITLE_BAND_TOP}:"
        "color=0x0B0E12@0.94:t=fill,"
        "subtitles='" + escaped_srt + "':force_style='FontName=DejaVu Sans,FontSize=12,"
        "PrimaryColour=&H00FFFFFF,BorderStyle=1,Outline=0,Shadow=0,Alignment=2,"
        "MarginL=40,MarginR=40,MarginV=18'",
        "-map", "0:v:0", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-pix_fmt", "yuv420p",
    ))
    if narration is not None:
        final_command.extend(("-map", "1:a:0", "-c:a", "aac", "-b:a", "160k"))
    else:
        final_command.append("-an")
    final_command.extend(("-t", str(TOTAL_DURATION), str(final)))
    command(final_command)

    probe = probe_video(ffprobe, final)
    receipt = {
        "schema_version": 1,
        "status": "BUILT_PENDING_VISUAL_REVIEW",
        "video": final.name,
        "duration_seconds": TOTAL_DURATION,
        "resolution": [WIDTH, HEIGHT],
        "fps": FPS,
        "expert_episode": {"episode_index": 0, "frames": expert_count, "success": True},
        "narration_included": narration is not None,
        "segment_order": [segment.key for segment in SEGMENTS],
        "probe": probe,
        "claim_boundary": (
            "The video shows one successful scripted expert episode and one AMD policy-in-loop smoke. "
            "The expert is not learned-policy output; the 50-step smoke did not complete the task; "
            "official strict G3 remains 0/10. Visual acceptance is still required."
        ),
    }
    (output_dir / "build_receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"BUILD_OK {final}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
