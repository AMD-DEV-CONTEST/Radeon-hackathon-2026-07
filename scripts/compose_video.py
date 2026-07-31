"""
InventoryDoc Agent — 视频合成工具 (Step 4)

将幻灯片图片 + 配音音频合成为 H.264 MP4 视频。
优先使用 FFmpeg 快速合成，缺失时回退 MoviePy。
"""

import os
import re
import subprocess
import sys
from pathlib import Path


def _parse_audio_duration(audio_path: Path) -> float:
    """用 ffprobe 获取音频时长（秒）"""
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(audio_path)],
        capture_output=True, text=True, timeout=30,
    )
    try:
        return float(result.stdout.strip())
    except (ValueError, TypeError):
        return 0.0


def _get_slide_durations(audio_dir: Path) -> list[tuple[int, float]]:
    """从分段音频推断每页时长"""
    durations = []
    for f in sorted(audio_dir.glob("slide_*.mp3")):
        match = re.match(r"slide_(\d+)\.mp3", f.name)
        if match:
            num = int(match.group(1))
            dur = _parse_audio_duration(f)
            durations.append((num, dur))
    # 也检查 wav
    for f in sorted(audio_dir.glob("slide_*.wav")):
        match = re.match(r"slide_(\d+)\.wav", f.name)
        if match:
            num = int(match.group(1))
            if not any(n == num for n, _ in durations):
                dur = _parse_audio_duration(f)
                durations.append((num, dur))
    return sorted(durations, key=lambda x: x[0])


def _compose_ffmpeg(slides_dir: Path, audio_dir: Path, output_path: Path, encoder: str):
    """使用 FFmpeg concat 快速合成"""
    durations = _get_slide_durations(audio_dir)
    if not durations:
        print("错误: 未找到分段音频文件")
        return False

    print(f"检测到 {len(durations)} 段音频")

    # 每张图片也需要对应时长，用 ffmpeg 的 concat 协议
    # 生成 filter 参数
    filter_parts = []
    input_idx = 0
    concat_inputs = []

    for num, dur in durations:
        slide_file = slides_dir / f"slide_{num:02d}.png"
        if not slide_file.exists():
            print(f"警告: 找不到 Slide {num:02d} 图片，跳过")
            continue
        concat_inputs.extend(["-loop", "1", "-t", f"{dur:.3f}", "-i", str(slide_file)])
        filter_parts.append(f"[{input_idx}:v]")
        input_idx += 1

    # 添加音频
    merged_audio = audio_dir / "demo.mp3"
    if not merged_audio.exists():
        print("错误: 找不到合并音频文件")
        return False

    concat_inputs.extend(["-i", str(merged_audio)])

    # 视频拼接 filter
    v_filter = f"{''.join(filter_parts)}concat=n={len(filter_parts)}:v=1:a=0[out]"

    cmd = (
        ["ffmpeg", "-y"]
        + concat_inputs
        + ["-filter_complex", v_filter]
        + ["-map", "[out]"]
        + ["-map", str(input_idx)]  # 音频流
        + ["-c:v", encoder, "-pix_fmt", "yuv420p",
           "-r", "24", "-preset", "medium", "-crf", "23",
           "-c:a", "aac", "-b:a", "192k",
           "-shortest", str(output_path)]
    )

    print("运行 FFmpeg 合成...")
    print(f"编码器: {encoder}")
    print(f"输出: {output_path}")

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        print(f"FFmpeg 错误: {result.stderr[-500:]}")
        return False

    return True


def _compose_moviepy(slides_dir: Path, audio_dir: Path, output_path: Path):
    """回退到 MoviePy 合成"""
    try:
        from moviepy import ImageClip, AudioFileClip, concatenate_videoclips
    except ImportError:
        print("错误: 请先安装 moviepy: pip install moviepy")
        return False

    durations = _get_slide_durations(audio_dir)
    if not durations:
        print("错误: 未找到分段音频文件")
        return False

    clips = []
    for num, dur in durations:
        slide_file = slides_dir / f"slide_{num:02d}.png"
        if not slide_file.exists():
            print(f"警告: 找不到 Slide {num:02d} 图片，跳过")
            continue
        clip = ImageClip(str(slide_file), duration=dur)
        clips.append(clip)

    if not clips:
        print("错误: 没有可用的图片")
        return False

    merged_audio = audio_dir / "demo.mp3"
    if not merged_audio.exists():
        print("错误: 找不到合并音频文件")
        return False

    print("使用 MoviePy 合成...")
    final = concatenate_videoclips(clips, method="compose")
    audio = AudioFileClip(str(merged_audio))
    final = final.with_audio(audio)
    final.write_videofile(
        str(output_path),
        fps=24,
        codec="libx264",
        audio_codec="aac",
        bitrate="3000k",
    )
    return True


def main():
    import argparse

    parser = argparse.ArgumentParser(description="合成演示视频")
    parser.add_argument("--slides", default="output/slides", help="幻灯片图片目录")
    parser.add_argument("--audio", default="output/audio", help="音频目录")
    parser.add_argument("--output", default="output/demo.mp4", help="输出视频文件")
    parser.add_argument("--method", choices=["auto", "ffmpeg", "moviepy"], default="auto",
                        help="合成方法 (默认 auto: 优先 FFmpeg)")
    parser.add_argument("--encoder", default="libx264", help="视频编码器")
    args = parser.parse_args()

    slides_dir = Path(args.slides)
    audio_dir = Path(args.audio)
    output_path = Path(args.output)

    if not slides_dir.exists():
        print(f"错误: 找不到幻灯片目录 {slides_dir}")
        sys.exit(1)
    if not audio_dir.exists():
        print(f"错误: 找不到音频目录 {audio_dir}")
        sys.exit(1)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    success = False
    if args.method in ("auto", "ffmpeg"):
        try:
            subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
            success = _compose_ffmpeg(slides_dir, audio_dir, output_path, args.encoder)
        except (FileNotFoundError, subprocess.CalledProcessError):
            if args.method == "ffmpeg":
                print("错误: FFmpeg 不可用")
                sys.exit(1)
            print("FFmpeg 不可用，回退到 MoviePy...")

    if not success and args.method in ("auto", "moviepy"):
        success = _compose_moviepy(slides_dir, audio_dir, output_path)

    if success:
        size_mb = output_path.stat().st_size / (1024 * 1024)
        print(f"\n成功! 视频已生成: {output_path}")
        print(f"文件大小: {size_mb:.1f} MB")
    else:
        print("错误: 视频合成失败")
        sys.exit(1)


if __name__ == "__main__":
    main()