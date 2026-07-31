"""
InventoryDoc Agent — 语音生成工具 (Step 3)

使用 Edge TTS 免费生成中文配音。
支持分段音频、合并音频和 SRT 字幕。
"""

import asyncio
import os
import re
import sys
from pathlib import Path

try:
    import edge_tts
except ImportError:
    print("错误: 请先安装 edge-tts: pip install edge-tts")
    sys.exit(1)


def parse_script(script_path: str) -> list[dict]:
    """解析 narration.md，返回每段配音信息"""
    content = Path(script_path).read_text(encoding="utf-8")
    slides = []
    current_number = 0
    current_title = ""
    current_text: list[str] = []

    for line in content.split("\n"):
        slide_match = re.match(r"^## Slide (\d+):\s*(.*)", line)
        if slide_match:
            if current_number > 0 and current_text:
                slides.append({
                    "number": current_number,
                    "title": current_title,
                    "text": " ".join(current_text).strip(),
                })
            current_number = int(slide_match.group(1))
            current_title = slide_match.group(2).strip()
            current_text = []
        elif line.strip() and not line.startswith("---") and not line.startswith("##"):
            current_text.append(line.strip())

    if current_number > 0 and current_text:
        slides.append({
            "number": current_number,
            "title": current_title,
            "text": " ".join(current_text).strip(),
        })

    return slides


async def generate_slide_audio(
    slide: dict, voice: str, audio_dir: Path
) -> tuple[int, float]:
    """生成单段音频，返回 (slide_number, duration_seconds)"""
    text = slide["text"]
    if not text:
        return slide["number"], 0.0

    filename = f"slide_{slide['number']:02d}.mp3"
    filepath = audio_dir / filename

    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(str(filepath))

    # 估算时长（edge-tts 不直接返回时长，用文件大小估算）
    size_bytes = filepath.stat().st_size
    # MP3 128kbps ≈ 16KB/s
    duration = size_bytes / 16000
    return slide["number"], duration


async def generate_all_audio(script_path: str, voice: str, output_dir: str):
    """生成所有段落音频 + 合并 + 字幕"""
    audio_dir = Path(output_dir)
    audio_dir.mkdir(parents=True, exist_ok=True)

    slides = parse_script(script_path)
    print(f"解析到 {len(slides)} 段配音")
    print(f"音色: {voice}")

    slide_durations: list[tuple[int, float]] = []

    for slide in slides:
        num, dur = await generate_slide_audio(slide, voice, audio_dir)
        slide_durations.append((num, dur))
        text_preview = slide["text"][:50].replace("\n", " ")
        print(f"  Slide {num:02d}: {dur:.1f}s — {text_preview}...")

    # 生成 SRT 字幕
    srt_path = audio_dir / "demo.srt"
    _generate_srt(slides, slide_durations, srt_path)

    # 合并为完整音频
    merged_path = audio_dir / "demo.mp3"
    _merge_audio(audio_dir, slide_durations, merged_path)

    print()
    total_duration = sum(d for _, d in slide_durations)
    print(f"完成! 总时长: {total_duration:.1f} 秒")
    print(f"分段音频: {audio_dir}")
    print(f"合并音频: {merged_path}")
    print(f"字幕文件: {srt_path}")


def _generate_srt(
    slides: list[dict],
    durations: list[tuple[int, float]],
    srt_path: Path,
):
    """生成 SRT 字幕文件"""
    lines = []
    idx = 1
    current_time = 0.0

    for slide, (num, dur) in zip(slides, durations):
        if dur <= 0:
            continue
        start_h = int(current_time // 3600)
        start_m = int((current_time % 3600) // 60)
        start_s = current_time % 60
        end_time = current_time + dur
        end_h = int(end_time // 3600)
        end_m = int((end_time % 3600) // 60)
        end_s = end_time % 60

        lines.append(f"{idx}")
        lines.append(f"{start_h:02d}:{start_m:02d}:{start_s:06.3f} --> {end_h:02d}:{end_m:02d}:{end_s:06.3f}")
        lines.append(slide["text"])
        lines.append("")

        idx += 1
        current_time = end_time

    srt_path.write_text("\n".join(lines, encoding="utf-8"))


def _merge_audio(
    audio_dir: Path,
    durations: list[tuple[int, float]],
    output_path: Path,
):
    """合并所有分段 MP3 为完整音频"""
    try:
        from pydub import AudioSegment
        combined = AudioSegment.empty()
        for num, _ in durations:
            filepath = audio_dir / f"slide_{num:02d}.mp3"
            if filepath.exists():
                combined += AudioSegment.from_mp3(str(filepath))
        combined.export(str(output_path), format="mp3")
        print(f"合并音频: {output_path}")
    except ImportError:
        # 回退到 FFmpeg concat
        filelist_path = audio_dir / "_filelist.txt"
        with open(filelist_path, "w") as f:
            for num, _ in durations:
                filepath = audio_dir / f"slide_{num:02d}.mp3"
                if filepath.exists():
                    f.write(f"file '{filepath.name}'\n")

        import subprocess
        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
             "-i", str(filelist_path),
             "-c", "copy", str(output_path)],
            capture_output=True,
        )


def main():
    import argparse

    parser = argparse.ArgumentParser(description="使用 Edge TTS 生成配音")
    parser.add_argument("--script", default="narration.md", help="脚本文件路径")
    parser.add_argument("--voice", default="zh-CN-YunxiNeural", help="音色 ID")
    parser.add_argument("--output", default="output/audio", help="输出目录")
    args = parser.parse_args()

    if not Path(args.script).exists():
        print(f"错误: 找不到脚本文件 {args.script}")
        print("请先运行 generate_script.py 生成脚本。")
        sys.exit(1)

    asyncio.run(generate_all_audio(args.script, args.voice, args.output))


if __name__ == "__main__":
    main()