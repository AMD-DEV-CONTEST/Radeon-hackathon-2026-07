"""阶段 11 — 字幕 agent。

按镜头时长顺序累加时间轴, 把每个镜头的台词写成 .srt。
(更精确可对每条配音跑 Whisper 对齐; 此处用配音实际时长累加即可满足短剧。)
"""
from __future__ import annotations

from .base import Agent
from ..schemas import ShotList
from ..utils import write_srt, probe_duration


class SubtitleAgent(Agent):
    name = "字幕"

    def run(self, shot_list: ShotList) -> str:
        entries = []
        t = 0.0
        for shot in shot_list.shots:
            clip = shot.final_clip_path or shot.clip_path
            dur = probe_duration(clip) if clip else shot.duration_sec
            if dur <= 0:
                dur = shot.duration_sec
            if shot.dialogue.strip():
                entries.append((t, t + dur, shot.dialogue.strip()))
            t += dur
        out = self.ctx.paths.subtitles / f"{shot_list.episode_id}.srt"
        write_srt(entries, out)
        self.info(f"{shot_list.episode_id}: {len(entries)} 条字幕, 总时长 {t:.1f}s")
        return str(out)
