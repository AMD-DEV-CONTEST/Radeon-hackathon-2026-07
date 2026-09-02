"""FFmpeg 封装：统一转码、拼接、混音、烧字幕。

短剧成片的关键坑：各镜头片段编码/分辨率/帧率不一致时直接 concat 会黑屏/无声，
因此先 normalize 再 concat。所有命令通过 subprocess 调用系统 ffmpeg。
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path


def _run(cmd: list[str]) -> None:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError as e:
        raise RuntimeError(
            f"找不到 {cmd[0]}：请安装 ffmpeg 并加入系统 PATH(`ffmpeg -version` 可验证)。"
        ) from e
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg 失败:\n命令: {' '.join(cmd)}\n{proc.stderr[-1500:]}")


def probe_duration(path: str | Path) -> float:
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration",
           "-of", "json", str(path)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        # ffprobe 未安装/不在 PATH：优雅降级(调用方会回退到 shot.duration_sec)
        return 0.0
    if proc.returncode != 0:
        return 0.0
    try:
        return float(json.loads(proc.stdout)["format"]["duration"])
    except Exception:  # noqa: BLE001
        return 0.0


def normalize_clip(src: str | Path, dst: str | Path,
                   width: int = 1080, height: int = 1920, fps: int = 24,
                   add_silent_audio: bool = False) -> Path:
    """统一为竖屏 1080x1920 / 24fps / H.264 / yuv420p，保证可无缝拼接。

    add_silent_audio=True：给无音轨的片段补一条静音轨——这样【每个】片段都带音轨，
    concat -c copy 才不会因为"有的有音轨有的没有"而把整条成片的声音丢掉。
    """
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    vf = (f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
          f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black,fps={fps}")
    cmd = ["ffmpeg", "-y", "-i", str(src)]
    if add_silent_audio:
        cmd += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
    cmd += ["-vf", vf, "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-pix_fmt", "yuv420p"]
    if add_silent_audio:
        cmd += ["-map", "0:v:0", "-map", "1:a:0", "-shortest"]
    cmd += ["-c:a", "aac", "-b:a", "192k", "-ar", "48000", str(dst)]
    _run(cmd)
    return dst


def mux_audio(video: str | Path, audio: str | Path, dst: str | Path,
              target_sec: float | None = None, max_speedup: float = 1.5,
              shortest: bool = True) -> Path:
    """把配音轨混入视频(替换原音轨)。

    target_sec 给定时(=该片段画面时长)：把配音『对齐到画面时长』——配音过长则轻微
    加速(上限 max_speedup, 默认 1.5x)以免旁白被切断半句; 配音过短则补静音, 绝不缩短
    画面。这样成片画面时长稳定、字幕时间轴也不漂移。未给 target_sec 时退回旧 -shortest。
    """
    dst = Path(dst)
    if target_sec and target_sec > 0:
        v = probe_duration(audio)
        tempo = min(v / target_sec, max_speedup) if v > target_sec else 1.0
        af = f"[1:a]atempo={tempo:.4f},apad[a]" if tempo > 1.001 else "[1:a]apad[a]"
        _run(["ffmpeg", "-y", "-i", str(video), "-i", str(audio),
              "-filter_complex", af, "-map", "0:v:0", "-map", "[a]",
              "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
              "-t", f"{target_sec:.3f}", str(dst)])
        return dst
    cmd = ["ffmpeg", "-y", "-i", str(video), "-i", str(audio),
           "-c:v", "copy", "-c:a", "aac", "-map", "0:v:0", "-map", "1:a:0"]
    if shortest:
        cmd.append("-shortest")
    cmd.append(str(dst))
    _run(cmd)
    return dst


def concat_clips(clips: list[str | Path], dst: str | Path) -> Path:
    """concat demuxer 拼接(要求各片段已 normalize 为相同参数)。"""
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    listfile = dst.parent / "_concat_list.txt"
    # 用绝对路径：concat demuxer 的 file '...' 是相对【列表文件所在目录】解析的，
    # 写相对路径会被二次拼接成错误路径(找不到文件)。
    listfile.write_text(
        "\n".join(f"file '{Path(c).resolve().as_posix()}'" for c in clips), encoding="utf-8")
    _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listfile),
          "-c", "copy", str(dst)])
    return dst


def burn_subtitles(video: str | Path, srt: str | Path, dst: str | Path,
                   font_size: int = 16) -> Path:
    """硬字幕烧录(短剧多为硬字幕)。"""
    dst = Path(dst)
    srt_path = Path(srt).as_posix().replace(":", "\\:")
    try:
        # 首选硬字幕烧录(需 ffmpeg 编译了 libass 的 subtitles 滤镜)。
        _run(["ffmpeg", "-y", "-i", str(video),
              "-vf", f"subtitles={srt_path}",
              "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
              "-c:a", "copy", str(dst)])
    except RuntimeError:
        # 该 ffmpeg 没编 libass(无 subtitles 滤镜)：退而求其次，把 .srt 作为软字幕轨
        # (mov_text)封进 mp4，播放器可选显示；要硬烧字幕请装带 libass 的 ffmpeg。
        _run(["ffmpeg", "-y", "-i", str(video), "-i", str(srt),
              "-map", "0:v", "-map", "0:a?", "-map", "1",  # 0:a? 保留音轨(有则带上)
              "-c", "copy", "-c:s", "mov_text",
              "-metadata:s:s:0", "language=chi", str(dst)])
    return dst


def last_frame(video: str | Path, dst: str | Path) -> Path:
    """抽取视频最后一帧 PNG —— 用于"接上一镜末帧"做下一镜 I2V 的起始帧, 让连续动作镜头衔接。"""
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    # -sseof -0.2: 从结尾前 0.2s 开始取一帧(取绝对最后一帧在部分封装上不稳, 倒数 0.2s 稳)
    _run(["ffmpeg", "-y", "-sseof", "-0.2", "-i", str(video),
          "-frames:v", "1", "-update", "1", str(dst)])
    return dst
