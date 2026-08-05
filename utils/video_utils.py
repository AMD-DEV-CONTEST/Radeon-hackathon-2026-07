"""视频处理工具 (FFmpeg + OpenCV).

提供拆帧、合帧、视频信息查询等无状态工具函数。
"""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


class VideoError(RuntimeError):
    """视频处理异常."""


@dataclass
class VideoInfo:
    """视频元信息."""
    width: int
    height: int
    fps: float
    frame_count: int
    duration: float
    has_audio: bool


def _check_ffmpeg() -> None:
    if shutil.which("ffmpeg") is None:
        raise VideoError("未找到 ffmpeg, 请先安装 (apt install ffmpeg)")


def get_video_info(video_path: str | Path) -> VideoInfo:
    """读取视频元信息 (用 OpenCV)."""
    video_path = str(video_path)
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise VideoError(f"无法打开视频: {video_path}")
    try:
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS) or 16.0
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    finally:
        cap.release()
    duration = frame_count / fps if fps > 0 else 0.0

    # 检测音轨 (用 ffprobe)
    has_audio = False
    if shutil.which("ffprobe"):
        try:
            r = subprocess.run(
                ["ffprobe", "-v", "error", "-select_streams", "a",
                 "-show_entries", "stream=codec_type", "-of",
                 "csv=p=0", video_path],
                capture_output=True, text=True, timeout=15,
            )
            has_audio = "audio" in r.stdout
        except subprocess.SubprocessError:
            pass
    return VideoInfo(width, height, fps, frame_count, duration, has_audio)


def split_video_to_frames(
    video_path: str | Path,
    output_dir: str | Path,
    name_template: str = "frame_{:05d}.png",
    start_index: int = 1,
) -> list[Path]:
    """用 FFmpeg 将视频拆为 PNG 帧序列.

    Returns
    -------
    list[Path]
        拆出的帧文件路径列表 (有序)。
    """
    _check_ffmpeg()
    video_path = str(video_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 清理旧帧
    for old in output_dir.glob("frame_*.png"):
        old.unlink()

    # FFmpeg 模板: frame_%05d.png
    ffmpeg_tmpl = name_template.replace("{:05d}", "%05d").replace("{:d}", "%d")
    out_pattern = str(output_dir / ffmpeg_tmpl)
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-start_number", str(start_index),
        "-vsync", "0",
        out_pattern,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise VideoError(f"拆帧失败: {r.stderr[-500:]}")

    frames = sorted(output_dir.glob("frame_*.png"))
    return frames


def frames_to_video(
    frames_dir: str | Path,
    output_path: str | Path,
    fps: int = 16,
    name_pattern: str = "frame_%05d.png",
    audio_path: str | Path | None = None,
    crf: int = 18,
    preset: str = "medium",
    pix_fmt: str = "yuv420p",
) -> Path:
    """用 FFmpeg 将 PNG 帧序列合成为 MP4.

    Parameters
    ----------
    audio_path : Path, optional
        如提供, 将其音轨合并到输出视频。
    """
    _check_ffmpeg()
    frames_dir = Path(frames_dir)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    input_pattern = str(frames_dir / name_pattern)
    cmd = [
        "ffmpeg", "-y",
        "-framerate", str(fps),
        "-i", input_pattern,
    ]
    if audio_path is not None:
        cmd += ["-i", str(audio_path)]
    cmd += [
        "-c:v", "libx264",
        "-preset", preset,
        "-crf", str(crf),
        "-pix_fmt", pix_fmt,
    ]
    if audio_path is not None:
        cmd += ["-c:a", "aac", "-b:a", "192k", "-shortest"]
    cmd += ["-movflags", "+faststart", str(output_path)]

    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise VideoError(f"合帧失败: {r.stderr[-500:]}")
    return output_path


def extract_audio(video_path: str | Path,
                  output_path: str | Path) -> Path:
    """从视频中抽取音轨 (AAC)."""
    _check_ffmpeg()
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-i", str(video_path),
        "-vn", "-acodec", "aac", "-b:a", "192k",
        str(output_path),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise VideoError(f"抽取音轨失败: {r.stderr[-500:]}")
    return output_path


def read_frame(frame_path: str | Path) -> np.ndarray:
    """读取单帧为 RGB ndarray (HxWx3, uint8)."""
    img = cv2.imread(str(frame_path), cv2.IMREAD_COLOR)
    if img is None:
        raise VideoError(f"读取帧失败: {frame_path}")
    return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)


def write_frame(frame_path: str | Path, image: np.ndarray) -> Path:
    """写入 RGB ndarray 为图像文件 (按扩展名)."""
    frame_path = Path(frame_path)
    frame_path.parent.mkdir(parents=True, exist_ok=True)
    bgr = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
    cv2.imwrite(str(frame_path), bgr)
    return frame_path


def make_thumbnail_grid(
    frames: list[np.ndarray],
    cols: int = 8,
    thumb_size: tuple[int, int] = (80, 45),
) -> np.ndarray:
    """将多帧拼成缩略图网格 (用于时间轴预览)."""
    if not frames:
        raise VideoError("无帧可拼")
    rows = (len(frames) + cols - 1) // cols
    tw, th = thumb_size
    canvas = np.zeros((th * rows, tw * cols, 3), dtype=np.uint8)
    for i, frame in enumerate(frames):
        r, c = divmod(i, cols)
        thumb = cv2.resize(frame, (tw, th))
        canvas[r * th:(r + 1) * th, c * tw:(c + 1) * tw] = thumb
    return canvas
