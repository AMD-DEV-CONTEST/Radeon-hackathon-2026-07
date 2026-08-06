#!/usr/bin/env python3
"""Recompose an existing Phase 3 run with an English-only teaching layer."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
from pathlib import Path
from typing import Iterable

import av
from PIL import Image, ImageDraw, ImageFont


REGULAR_FONT = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
BOLD_FONT = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")


def decode(path: Path) -> tuple[list[Image.Image], float]:
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        return [frame.to_image().convert("RGB") for frame in container.decode(stream)], float(stream.average_rate)


def encode(path: Path, frames: Iterable[Image.Image], fps: float, width: int, height: int) -> int:
    count = 0
    with av.open(str(path), mode="w") as container:
        stream = container.add_stream("libx264", rate=round(fps))
        stream.width = width
        stream.height = height
        stream.pix_fmt = "yuv420p"
        stream.options = {"preset": "medium", "crf": "18", "movflags": "+faststart"}
        for image in frames:
            for packet in stream.encode(av.VideoFrame.from_image(image.convert("RGB"))):
                container.mux(packet)
            count += 1
        for packet in stream.encode():
            container.mux(packet)
    return count


def font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(path), max(10, size))


def wrap(draw: ImageDraw.ImageDraw, text: str, face: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        if current and draw.textbbox((0, 0), candidate, font=face)[2] > max_width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def text_width(draw: ImageDraw.ImageDraw, text: str, face: ImageFont.FreeTypeFont) -> int:
    box = draw.textbbox((0, 0), text, font=face)
    return box[2] - box[0]


def draw_arrow(draw: ImageDraw.ImageDraw, start: tuple[float, float], end: tuple[float, float], width: int, color: tuple[int, int, int, int]) -> None:
    draw.line((*start, *end), fill=color, width=width)
    angle = math.atan2(end[1] - start[1], end[0] - start[0])
    head = max(7, width * 4)
    spread = math.pi / 6
    left = (end[0] - head * math.cos(angle - spread), end[1] - head * math.sin(angle - spread))
    right = (end[0] - head * math.cos(angle + spread), end[1] - head * math.sin(angle + spread))
    draw.polygon((end, left, right), fill=color)


def make_overlay(size: tuple[int, int], config: dict, copy: dict, index: int, total: int) -> Image.Image:
    width, height = size
    scale = width / 768
    topic_face = font(BOLD_FONT, round(10 * scale + 5))
    stage_face = font(BOLD_FONT, round(10 * scale + 5))
    callout_face = font(BOLD_FONT, round(10 * scale + 5))
    overlay = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    margin = max(9, round(14 * scale))
    topic_pad = max(8, round(10 * scale))
    topic_width = text_width(draw, config["topic"], topic_face) + 2 * topic_pad
    header_height = max(24, round(30 * scale))
    draw.rounded_rectangle((margin, margin, margin + topic_width, margin + header_height), radius=max(5, round(8 * scale)), fill=(7, 38, 41, 205))
    draw.text((margin + topic_pad, margin + max(5, round(7 * scale))), config["topic"], font=topic_face, fill=(225, 244, 235, 255))
    stage = copy["stage"]
    stage_width = text_width(draw, stage, stage_face) + 2 * topic_pad
    stage_left = width - margin - stage_width
    draw.rounded_rectangle((stage_left, margin, width - margin, margin + header_height), radius=max(5, round(8 * scale)), fill=(248, 243, 217, 232))
    draw.text((stage_left + topic_pad, margin + max(5, round(7 * scale))), stage, font=stage_face, fill=(25, 63, 58, 255))
    label_x = round(copy["calloutBox"][0] * width)
    label_y = round(copy["calloutBox"][1] * height)
    label_pad_x = max(7, round(9 * scale))
    label_pad_y = max(4, round(5 * scale))
    label_width = text_width(draw, copy["callout"], callout_face) + 2 * label_pad_x
    label_height = callout_face.size + 2 * label_pad_y
    label_x = min(label_x, width - margin - label_width)
    draw.rounded_rectangle((label_x, label_y, label_x + label_width, label_y + label_height), radius=max(4, round(6 * scale)), fill=(7, 38, 41, 220))
    draw.text((label_x + label_pad_x, label_y + label_pad_y - 1), copy["callout"], font=callout_face, fill=(231, 246, 150, 255))
    target = (round(copy["target"][0] * width), round(copy["target"][1] * height))
    start = (label_x + label_width / 2, label_y + label_height)
    draw_arrow(draw, start, target, max(2, round(3 * scale)), (218, 239, 96, 245))
    return overlay


def add_subtitle(base: Image.Image, text: str) -> Image.Image:
    width, height = base.size
    scale = width / 768
    face = font(BOLD_FONT, round(15 * scale + 7))
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    lines = wrap(draw, text, face, width - max(48, round(80 * scale)))
    line_height = face.size + max(3, round(4 * scale))
    box_height = len(lines) * line_height + max(13, round(18 * scale))
    bottom = height - max(8, round(12 * scale))
    top = bottom - box_height
    side = max(12, round(22 * scale))
    draw.rounded_rectangle((side, top, width - side, bottom), radius=max(6, round(9 * scale)), fill=(0, 0, 0, 168))
    for line_index, line in enumerate(lines):
        x = (width - text_width(draw, line, face)) / 2
        draw.text((x, top + max(6, round(8 * scale)) + line_index * line_height), line, font=face, fill=(255, 255, 255, 255))
    return Image.alpha_composite(base.convert("RGBA"), layer).convert("RGB")


def timestamp(seconds: float) -> str:
    milliseconds = round(seconds * 1000)
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    secs, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def annotate(run: Path, timeline: dict, config: dict) -> list[dict]:
    stages = config["segments"]
    total = len(timeline["segments"])
    results = []
    for segment_index, segment in enumerate(timeline["segments"]):
        segment_id = segment["id"]
        if segment_id not in stages:
            raise RuntimeError(f"missing English copy for {segment_id}")
        copy = stages[segment_id]
        segment_dir = run / "segments" / segment_id
        frames, fps = decode(segment_dir / "video.mp4")
        width, height = frames[0].size
        overlay_dir = segment_dir / "overlay_frames"
        if overlay_dir.exists():
            shutil.rmtree(overlay_dir)
        overlay_dir.mkdir()
        annotated = []
        for frame_index, base in enumerate(frames):
            overlay = make_overlay((width, height), config, copy, segment_index, total)
            overlay.save(overlay_dir / f"frame_{frame_index:04d}.png")
            composed = Image.alpha_composite(base.convert("RGBA"), overlay)
            annotated.append(add_subtitle(composed, copy["subtitle"]))
        Image.open(overlay_dir / "frame_0000.png").save(segment_dir / "overlay_start.png")
        Image.open(overlay_dir / f"frame_{len(frames) - 1:04d}.png").save(segment_dir / "overlay_end.png")
        duration = len(frames) / fps
        (segment_dir / "subtitles.srt").write_text(
            f"1\n{timestamp(0.08)} --> {timestamp(max(0.4, duration - 0.08))}\n{copy['subtitle']}\n",
            encoding="utf-8",
        )
        count = encode(segment_dir / "annotated.mp4", annotated, fps, width, height)
        results.append({"id": segment_id, "frames": count, "fps": fps, "width": width, "height": height})
    return results


def join(run: Path, timeline: dict, name: str, output: Path) -> dict:
    joined: list[Image.Image] = []
    signature = None
    for index, segment in enumerate(timeline["segments"]):
        frames, fps = decode(run / "segments" / segment["id"] / name)
        current = (fps, *frames[0].size)
        if signature is None:
            signature = current
        elif current != signature:
            raise RuntimeError("incompatible segment formats")
        joined.extend(frames if index == 0 else frames[1:])
    fps, width, height = signature
    frames = encode(output, joined, fps, width, height)
    return {"path": str(output), "frames": frames, "fps": fps, "width": width, "height": height}


def contact_sheet(run: Path, timeline: dict) -> Path:
    width, height = 384, 224
    sheet = Image.new("RGB", (width * len(timeline["segments"]), height))
    for index, segment in enumerate(timeline["segments"]):
        frames, _ = decode(run / "segments" / segment["id"] / "annotated.mp4")
        image = frames[len(frames) // 2].resize((width, height), Image.Resampling.LANCZOS)
        sheet.paste(image, (index * width, 0))
    path = run / "preview/final_contact_sheet.png"
    path.parent.mkdir(exist_ok=True)
    sheet.save(path)
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    run = args.run_dir.resolve()
    timeline = json.loads((run / "timeline.json").read_text(encoding="utf-8"))
    config = json.loads((run / "english_delivery.json").read_text(encoding="utf-8"))
    segment_results = annotate(run, timeline, config)
    final = join(run, timeline, "annotated.mp4", run / "final_video.mp4")
    if smoke_id := config.get("smokeSegmentId"):
        shutil.copy2(run / "segments" / smoke_id / "annotated.mp4", run / "smoke_final_video.mp4")
    preview = contact_sheet(run, timeline)
    checks = [run / "base_video.mp4", run / "final_video.mp4", preview]
    checks.extend(run / "segments" / segment["id"] / "annotated.mp4" for segment in timeline["segments"])
    (run / "english_checksums.sha256").write_text(
        "".join(f"{sha256(path)}  {path.relative_to(run)}\n" for path in checks), encoding="utf-8"
    )
    result = {
        "status": "passed",
        "language": "English",
        "gpuRegeneration": False,
        "segments": segment_results,
        "final": final,
        "contactSheet": str(preview),
    }
    (run / "english_validation.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
