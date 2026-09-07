#!/usr/bin/env python3
# ruff: noqa: E501
"""Stitch Edge-TTS subtitle parts and add reviewed Simplified-Chinese lines."""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

TRANSLATIONS = {
    "Radeon V L A Reflex is a language-guided sorting system for the Track Three Physical A I Challenge.": "RadeonVLA-Reflex 是面向 Track 3 Physical AI 挑战赛的语言引导分拣系统。",
    "It combines a vision-language-action policy with an execution layer that checks commands and joint actions before they reach the robot.": "它将视觉语言动作策略与执行层结合，在控制机械臂前检查指令与关节动作。",
    "Our Genesis testbed uses a Franka arm, five Y C B fruits, and four language-addressable bowls.": "我们的 Genesis 测试台包含 Franka 机械臂、五种 YCB 水果和四个语言可指定碗。",
    "White and blue bowls on both sides create twenty exact tasks using the same language as data collection.": "左右两侧的白色和蓝色碗构成二十项任务，并沿用数据采集时的语言。",
    "Smol V L A receives two cameras, nine-dimensional robot state, and language.": "SmolVLA 接收双路相机、九维机器人状态与语言指令。",
    "It predicts absolute joint-position actions for the arm and gripper, while the runtime enforces limits and command authority.": "模型预测机械臂和夹爪的绝对关节位置，运行时同时执行限幅与指令权限检查。",
    "Each command has a version.": "每条指令都有版本号。",
    "When the destination changes, queued actions from the old version lose authority.": "目标改变时，旧版本中排队的动作立即失去执行权限。",
    "The controller clears its cache, holds safely, and continues only with the current instruction.": "控制器清空缓存、安全保持，并仅按当前指令继续执行。",
    "These clips show data collection before training.": "这些画面展示训练前的数据采集过程。",
    "A strict-physics expert approaches, grasps, lifts, transports, releases, and keeps recording until the fruit is visibly settled in the requested bowl.": "严格物理专家依次完成接近、抓取、抬升、搬运与释放，并持续录制至水果在目标碗中稳定。",
    "Physical Two K contains two thousand successful episodes and over four hundred sixty-eight thousand dual-camera frames.": "Physical-2K 包含两千条成功轨迹和超过四十六万八千帧双相机数据。",
    "Every task has one hundred demonstrations, independent seeds, and a validator-checked certificate.": "每项任务都有一百条演示、独立 seed 和通过校验的证书。",
    "Grasp attachment, object teleportation, and placement nudges are disabled.": "抓取粘附、物体瞬移和放置微调均被禁用。",
    "Trajectories preserve contact and gravity through release.": "轨迹从抓取到释放始终保留接触与重力物理。",
    "The website shows successful apple, banana, and plum collection examples with settled endings.": "网站展示苹果、香蕉和李子的成功采集样例，并保留稳定结尾。",
    "Simulation, collection, training, and evaluation run on one AMD Radeon G P U through ROCm.": "仿真、采集、训练和评测通过 ROCm 运行在一张 AMD Radeon GPU 上。",
    "PyTorch, Genesis, and LeRobot export JSON, C S V, video, and SHA two fifty-six evidence.": "PyTorch、Genesis 与 LeRobot 链路输出 JSON、CSV、视频和 SHA256 证据。",
    "The qualitative showcase uses the public twenty-thousand-step checkpoint trained on Physical One K.": "定性展示使用在 Physical-1K 上训练的公开二万步权重。",
    "Fifty-thousand and two-hundred-thousand versions remain separate downloads, letting reviewers compare them without replacing the original.": "五万步和二十万步版本保留为独立下载，便于评审比较且不覆盖原始权重。",
    "Here the twenty K policy receives the collected banana instruction and completes the white-left task first try.": "这里二万步策略接收采集原文，并首次完成香蕉到左侧白碗任务。",
    "Recording continues after release, showing the banana inside the bowl and the withdrawn gripper.": "释放后仍继续录制，可清楚看到香蕉位于碗中且夹爪已经撤离。",
    "A second twenty K rollout completes another command through the same interface.": "第二段二万步回放通过相同接口完成另一条分拣指令。",
    "This walkthrough includes only successful executions, while complete machine-readable evaluation files remain separate from the presentation reel.": "本解说仅展示成功执行，完整机器可读评测文件则与展示视频分开提供。",
    "Quality control checks every final frame.": "质量检查覆盖每段视频的最后一帧。",
    "A clip is published only when the correct object is released into the correct bowl and remains there throughout a two-second simulation dwell.": "仅当正确物体释放进入正确碗，并在两秒仿真观察期间保持稳定时，视频才会发布。",
    "The website provides an evidence console and download center.": "网站提供证据控制台与下载中心。",
    "Physical One K, Physical Two K, twenty K, fifty K, two hundred K, source, evaluations, successful videos, checksums, and this walkthrough have public links.": "Physical-1K、Physical-2K、二万步、五万步、二十万步、源码、评测、成功视频、校验和与本解说均有公开链接。",
    "The result is a complete Radeon workflow from language and vision to physical action, verified data, trained weights, and inspectable evidence.": "最终形成从语言和视觉到物理动作、验证数据、训练权重与可审查证据的完整 Radeon 工作流。",
    "Radeon V L A Reflex demonstrates controllable sorting in Genesis with clear provenance and successful outcomes viewers can verify.": "RadeonVLA-Reflex 在 Genesis 中展示来源清晰、结果可验证的可控分拣。",
}

BLOCK_RE = re.compile(
    r"\d+\s*\n(\d\d:\d\d:\d\d,\d{3})\s+-->\s+(\d\d:\d\d:\d\d,\d{3})\s*\n(.+?)(?=\n\n|\Z)",
    re.DOTALL,
)


def reviewed_translation(english: str) -> str:
    """Resolve either a sentence cue or an Edge-TTS cue containing several sentences."""
    if english in TRANSLATIONS:
        return TRANSLATIONS[english]
    sentences = re.findall(r"[^.!?]+[.!?]", english)
    sentences = [sentence.strip() for sentence in sentences]
    if sentences and " ".join(sentences) == english and all(
        sentence in TRANSLATIONS for sentence in sentences
    ):
        return " ".join(TRANSLATIONS[sentence] for sentence in sentences)
    raise KeyError(f"Missing reviewed translation: {english}")


def to_ms(value: str) -> int:
    hours, minutes, rest = value.split(":")
    seconds, millis = rest.split(",")
    return ((int(hours) * 60 + int(minutes)) * 60 + int(seconds)) * 1000 + int(millis)


def from_ms(value: int) -> str:
    hours, remainder = divmod(max(0, value), 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def duration_ms(path: Path) -> int:
    output = subprocess.check_output(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nk=1:nw=1",
            str(path),
        ],
        text=True,
    )
    return round(float(output.strip()) * 1000)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("parts_dir", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--target-duration", type=float, default=None)
    args = parser.parse_args()

    audio_parts = sorted(args.parts_dir.glob("*.mp3"))
    if not audio_parts:
        raise FileNotFoundError(f"No MP3 parts found in {args.parts_dir}")

    offset = 0
    cues: list[tuple[int, int, str]] = []
    for audio_path in audio_parts:
        srt_path = audio_path.with_suffix(".srt")
        text = srt_path.read_text(encoding="utf-8-sig")
        for match in BLOCK_RE.finditer(text):
            english = " ".join(match.group(3).split())
            reviewed_translation(english)
            cues.append((offset + to_ms(match.group(1)), offset + to_ms(match.group(2)), english))
        offset += duration_ms(audio_path)

    scale = 1.0 if args.target_duration is None else (args.target_duration * 1000) / offset
    blocks = []
    for index, (start, end, english) in enumerate(cues, start=1):
        blocks.append(
            f"{index}\n{from_ms(round(start * scale))} --> {from_ms(round(end * scale))}\n"
            f"{english}\n{reviewed_translation(english)}"
        )
    args.output.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")
    print(f"parts={len(audio_parts)} cues={len(cues)} source_duration_s={offset / 1000:.3f} scale={scale:.6f}")


if __name__ == "__main__":
    main()
