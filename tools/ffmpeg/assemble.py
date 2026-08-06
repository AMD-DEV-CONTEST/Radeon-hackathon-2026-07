from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List

logger = logging.getLogger("tools.ffmpeg.assemble")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(name)s: %(message)s")

QUALITY_PRESETS = {
    "720p": (1280, 720),
    "1080p": (1920, 1080),
}
DEFAULT_QUALITY = "720p"
FPS = 30
VIDEO_CODEC = "libx264"
VIDEO_BITRATE = "5M"
AUDIO_CODEC = "aac"
AUDIO_BITRATE = "192k"

FFMPEG_TIMEOUT = 300
MAX_RETRIES = 2
DURATION_EPSILON = 0.05

class FFmpegError(RuntimeError):
    pass

class AssemblyError(RuntimeError):
    pass

def _require_binaries() -> None:
    missing = [b for b in ("ffmpeg", "ffprobe") if shutil.which(b) is None]
    if missing:
        raise AssemblyError(
            f"Required binaries not found on PATH: {', '.join(missing)}."
        )

def _validate_file(path: str, label: str = "file") -> None:
    if not path or not Path(path).is_file():
        raise AssemblyError(f"{label.capitalize()} not found: {path!r}")

def _run(cmd: List[str], step: str, retries: int = MAX_RETRIES) -> subprocess.CompletedProcess:
    attempts = retries + 1
    last_err = None
    for attempt in range(1, attempts + 1):
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=FFMPEG_TIMEOUT
            )
        except FileNotFoundError as exc:
            raise FFmpegError(f"{step}: command not found ({exc})") from exc
        except subprocess.TimeoutExpired:
            last_err = f"{step} timed out after {FFMPEG_TIMEOUT}s (attempt {attempt}/{attempts})"
            logger.warning(last_err)
            continue

        if result.returncode == 0:
            return result

        stderr_tail = " | ".join((result.stderr or "").strip().splitlines()[-5:])
        last_err = (
            f"{step} failed with exit code {result.returncode} "
            f"(attempt {attempt}/{attempts}): {stderr_tail or 'no stderr output'}"
        )
        logger.warning(last_err)

    raise FFmpegError(last_err or f"{step} failed for an unknown reason")

def get_duration(path: str) -> float:
    _validate_file(path, "input")
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", path]
    result = _run(cmd, f"probe duration of '{path}'", retries=1)
    try:
        data = json.loads(result.stdout)
        return float(data["format"]["duration"])
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        raise FFmpegError(f"Could not read duration for '{path}': {exc}") from exc

def get_video_info(path: str) -> dict:
    _validate_file(path, "video")
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,r_frame_rate,codec_name:format=duration",
        "-of", "json", path,
    ]
    result = _run(cmd, f"probe info for '{path}'", retries=1)
    try:
        data = json.loads(result.stdout)
        stream = data["streams"][0]
        duration = float(data["format"]["duration"])
        num_str, _, den_str = stream["r_frame_rate"].partition("/")
        den = float(den_str) if den_str else 1.0
        fps = float(num_str) / den if den else float(num_str)
        return {
            "duration": round(duration, 2),
            "width": int(stream["width"]),
            "height": int(stream["height"]),
            "fps": round(fps, 2),
            "codec": stream.get("codec_name", "unknown"),
        }
    except (KeyError, IndexError, ValueError, ZeroDivisionError, json.JSONDecodeError) as exc:
        raise FFmpegError(f"Could not parse video info for '{path}': {exc}") from exc

def _mux_scene(video: str, audio: str, out_path: str, width: int, height: int) -> None:
    _validate_file(video, "scene video")
    _validate_file(audio, "narration audio")

    video_dur = get_duration(video)
    audio_dur = get_duration(audio)
    diff = audio_dur - video_dur

    video_filters = [
        f"scale={width}:{height}:force_original_aspect_ratio=decrease",
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2",
        "setsar=1",
        f"fps={FPS}",
    ]
    audio_filters = ["aformat=sample_rates=44100:channel_layouts=stereo"]

    if diff > DURATION_EPSILON:
        video_filters.append(f"tpad=stop_mode=clone:stop_duration={diff:.3f}")
    elif diff < -DURATION_EPSILON:
        audio_filters.append(f"apad=whole_dur={video_dur:.3f}")

    filter_complex = (
        f"[0:v]{','.join(video_filters)}[v];"
        f"[1:a]{','.join(audio_filters)}[a]"
    )

    cmd = [
        "ffmpeg", "-y",
        "-i", video,
        "-i", audio,
        "-filter_complex", filter_complex,
        "-map", "[v]", "-map", "[a]",
        "-c:v", VIDEO_CODEC, "-b:v", VIDEO_BITRATE, "-r", str(FPS),
        "-c:a", AUDIO_CODEC, "-b:a", AUDIO_BITRATE,
        "-shortest",
        out_path,
    ]
    _run(cmd, f"mux scene '{Path(video).name}' with '{Path(audio).name}'")

def _write_concat_list(paths: List[str], list_path: str) -> None:
    with open(list_path, "w", encoding="utf-8") as f:
        for p in paths:
            safe = os.path.abspath(p).replace("'", "'\\''")
            f.write(f"file '{safe}'\n")

def _concat(muxed_paths: List[str], output: str) -> None:
    workdir = os.path.dirname(muxed_paths[0])
    list_path = os.path.join(workdir, "concat_list.txt")
    _write_concat_list(muxed_paths, list_path)

    fast_cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path, "-c", "copy", output]
    try:
        _run(fast_cmd, "concat scenes (stream copy)", retries=0)
        return
    except FFmpegError as exc:
        logger.warning("Stream-copy concat failed, falling back to re-encode: %s", exc)

    inputs: List[str] = []
    for p in muxed_paths:
        inputs += ["-i", p]
    n = len(muxed_paths)
    filter_parts = "".join(f"[{i}:v:0][{i}:a:0]" for i in range(n))
    filter_complex = f"{filter_parts}concat=n={n}:v=1:a=1[v][a]"

    fallback_cmd = [
        "ffmpeg", "-y", *inputs,
        "-filter_complex", filter_complex,
        "-map", "[v]", "-map", "[a]",
        "-c:v", VIDEO_CODEC, "-b:v", VIDEO_BITRATE, "-r", str(FPS),
        "-c:a", AUDIO_CODEC, "-b:a", AUDIO_BITRATE,
        output,
    ]
    _run(fallback_cmd, "concat scenes (re-encode)")

def assemble(
    scenes: List[str],
    audios: List[str],
    output: str,
    quality: str = DEFAULT_QUALITY,
) -> str:
    _require_binaries()

    if not scenes:
        raise AssemblyError("No scene videos provided.")
    if len(scenes) != len(audios):
        raise AssemblyError(
            f"Mismatched inputs: {len(scenes)} scene(s) vs {len(audios)} audio track(s)."
        )
    if quality not in QUALITY_PRESETS:
        raise AssemblyError(f"Unknown quality {quality!r}; choose from {list(QUALITY_PRESETS)}.")

    for label, paths in (("scene", scenes), ("narration audio", audios)):
        for p in paths:
            _validate_file(p, label)

    width, height = QUALITY_PRESETS[quality]
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    workdir = tempfile.mkdtemp(prefix="edumanim_ffmpeg_")
    try:
        muxed: List[str] = []
        for i, (video, audio) in enumerate(zip(scenes, audios)):
            muxed_path = os.path.join(workdir, f"scene_{i:03d}_muxed.mp4")
            logger.info("Muxing scene %d/%d", i + 1, len(scenes))
            _mux_scene(video, audio, muxed_path, width, height)
            muxed.append(muxed_path)

        if len(muxed) == 1:
            shutil.copyfile(muxed[0], output_path)
        else:
            logger.info("Concatenating %d scenes", len(muxed))
            _concat(muxed, str(output_path))

        if not output_path.is_file() or output_path.stat().st_size == 0:
            raise AssemblyError("Assembly finished but the output file is missing or empty.")

        return str(output_path)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)