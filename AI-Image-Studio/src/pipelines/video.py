# -*- coding: utf-8 -*-
"""AI 视频超分增强：拆帧 → Real-ESRGAN 逐帧放大 → 无损合成（保留原音轨）。

- 帧解码：OpenCV（随 requirements 安装）
- 视频合成：imageio-ffmpeg 自带的 ffmpeg 二进制（免系统安装）
- 定位：短视频增强（默认限 30 秒 / 720p 以内，可用环境变量调整）
"""
from __future__ import annotations

import os
import subprocess
import tempfile

import cv2
from PIL import Image

from ..device import Timer, peak_memory_gb, reset_peak_memory


def _ffmpeg_exe() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def _probe(video_path: str):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError("无法读取视频文件，请确认格式（建议 mp4）。")
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    return fps, frames, w, h


def run_video_upscale(manager, video_path: str, quality: str = "fast",
                      target_scale: float = 2.0, progress_cb=None):
    """视频超分。返回 (输出视频路径, 性能信息)。"""
    if not video_path or not os.path.exists(video_path):
        raise ValueError("请先上传视频文件。")

    settings = manager.settings
    fps, total, w, h = _probe(video_path)
    seconds = total / max(fps, 1)
    if seconds > settings.max_video_seconds:
        raise ValueError(
            f"视频时长 {seconds:.0f}s 超过限制 {settings.max_video_seconds:.0f}s。"
            f"演示版聚焦短视频增强，可用 AISTUDIO_MAX_VIDEO_SECONDS 调整。")

    # 超高输入先降到上限，再放大数据（控制显存与耗时）
    shrink_note = ""
    if h > settings.max_video_height:
        ratio = settings.max_video_height / h
        w, h = int(w * ratio) // 2 * 2, settings.max_video_height
        shrink_note = f"输入已按限制预缩至 {w}×{h}；"

    upscaler = manager.get_upscaler(quality)
    out_dir = tempfile.mkdtemp(prefix="video_sr_")
    frames_dir = os.path.join(out_dir, "frames")
    os.makedirs(frames_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "upscaled.mp4")

    cap = cv2.VideoCapture(video_path)
    reset_peak_memory()
    done = 0
    with Timer() as t:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if shrink_note:
                frame = cv2.resize(frame, (w, h), interpolation=cv2.INTER_AREA)
            img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            sr = upscaler.upscale_image(img, target_scale=target_scale)
            sr.save(os.path.join(frames_dir, f"{done:06d}.jpg"), quality=92)
            done += 1
            if progress_cb and done % 5 == 0:
                progress_cb(min(done / max(total, 1), 0.99), f"超分帧 {done}/{total}")
        cap.release()

        # 合成：原 fps + 原音轨
        cmd = [
            _ffmpeg_exe(), "-y", "-framerate", f"{fps:.6f}",
            "-i", os.path.join(frames_dir, "%06d.jpg"),
            "-i", video_path,
            "-map", "0:v:0", "-map", "1:a?",
            "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
            "-c:a", "copy", "-shortest", out_path,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        if proc.returncode != 0 or not os.path.exists(out_path):
            raise RuntimeError(f"ffmpeg 合成失败：{proc.stderr[-300:]}")

    info = {
        "总帧数": str(done),
        "总耗时": f"{t.elapsed:.2f} s",
        "单帧均耗": f"{t.elapsed / max(done, 1) * 1000:.0f} ms",
        "处理速度": f"{done / max(t.elapsed, 1e-6):.1f} 帧/s",
        "峰值显存": f"{peak_memory_gb():.2f} GB" if manager.info.device.type == "cuda" else "CPU 推理",
        "输出": f"{int(w * target_scale)}×{int(h * target_scale)} @ {fps:.0f}fps（保留原音轨）",
        "备注": shrink_note or "—",
    }
    return out_path, info
