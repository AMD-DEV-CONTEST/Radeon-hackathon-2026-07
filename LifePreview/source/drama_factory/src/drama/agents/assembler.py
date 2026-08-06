"""阶段 12 — 合成 agent(FFmpeg)。

流程: 每镜头(片段+配音)混音 -> 统一 normalize 为 1080x1920/24fps/H.264
-> concat 拼接 -> 烧字幕 -> 输出成片 Episode。
"""
from __future__ import annotations

from pathlib import Path

from .base import Agent
from ..schemas import ShotList, Episode
from ..utils import normalize_clip, concat_clips, mux_audio, burn_subtitles, probe_duration


class Assembler(Agent):
    name = "合成"

    def run(self, shot_list: ShotList, subtitle_path: str = "") -> Episode:
        eid = shot_list.episode_id
        W = self.ctx.cfg("output", "width", default=1080)
        H = self.ctx.cfg("output", "height", default=1920)
        FPS = self.ctx.cfg("output", "fps", default=24)
        work = self.ctx.paths.output / eid / "_norm"
        work.mkdir(parents=True, exist_ok=True)

        # 真实成片必须镜头齐全。过去这里逐镜 warning 后继续，GPU 实例崩溃时会把
        # 缺镜头的短片误当成最终成片；在任何 ffmpeg 写入前统一阻断。
        if not self.ctx.dry_run:
            missing = []
            for shot in shot_list.shots:
                clip = shot.final_clip_path or shot.clip_path
                if not clip or not Path(clip).is_file():
                    missing.append(shot.shot_id)
            if missing:
                raise RuntimeError(
                    "成片阻断：以下镜头没有可用片段：" + ", ".join(missing)
                )

        normalized: list[Path] = []
        for shot in shot_list.shots:
            clip = shot.final_clip_path or shot.clip_path
            if not clip or not Path(clip).exists():
                if self.ctx.dry_run:  # dry-run 下产物是占位 txt, 跳过真实 ffmpeg
                    continue
                raise RuntimeError(f"成片阻断：{shot.shot_id} 没有可用片段")
            tmp = work / f"{shot.shot_id}.mp4"
            if self.ctx.dry_run:
                tmp.write_text("mock-normalized", encoding="utf-8"); normalized.append(tmp); continue
            # 有配音则先混音; 无配音的片段补静音轨, 保证所有片段都有音轨(否则 concat 丢声)
            has_voice = bool(shot.voice_path and Path(shot.voice_path).exists())
            if has_voice:
                muxed = work / f"{shot.shot_id}_av.mp4"
                clip_dur = probe_duration(clip)  # 以画面时长为准对齐配音(过长加速/过短补静音)
                mux_audio(clip, shot.voice_path, muxed, target_sec=clip_dur)
                clip = str(muxed)
            normalize_clip(clip, tmp, width=W, height=H, fps=FPS,
                           add_silent_audio=not has_voice)
            normalized.append(tmp)

        final = self.ctx.paths.output / eid / f"{eid}_final.mp4"
        has_subtitles = False
        if self.ctx.dry_run:
            final.write_text("mock-final-episode", encoding="utf-8")
            duration = sum(s.duration_sec for s in shot_list.shots)
        elif normalized:
            raw = self.ctx.paths.output / eid / f"{eid}_raw.mp4"
            concat_clips(normalized, raw)
            if subtitle_path and Path(subtitle_path).is_file():
                try:
                    has_subtitles = bool(
                        Path(subtitle_path).read_text(
                            encoding="utf-8-sig"
                        ).strip()
                    )
                except (OSError, UnicodeError) as exc:
                    raise RuntimeError(
                        f"字幕文件不可读: {subtitle_path}"
                    ) from exc
            if has_subtitles:
                burn_subtitles(raw, subtitle_path, final)
            else:
                raw.replace(final)
            duration = probe_duration(final)
        else:
            raise RuntimeError("没有可合成的片段")

        ep = Episode(
            episode_id=eid, novel_title=shot_list.novel_title, title=eid,
            shot_count=len(shot_list.shots), duration_sec=round(duration, 1),
            resolution=f"{W}x{H}", fps=FPS, final_path=str(final),
            subtitle_path=subtitle_path if has_subtitles else "")
        ep.save(self.ctx.paths.output / eid / f"{eid}_episode.json")
        self.info(f"{eid} 成片: {final}  ({duration:.1f}s)")
        return ep
