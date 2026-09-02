"""阶段 10 — 对口型 agent(InfiniteTalk + Wan, ComfyUI)。

对“有台词的近景人物镜头”, 用关键帧 + 配音音频驱动 InfiniteTalk 生成口型同步视频,
替换掉原 I2V 片段。非对话镜头沿用 I2V 片段。镜头级并行(占卡, 走两实例)。
工作流: infinitetalk_api.json。占位符: {{REF_IMAGE}} {{AUDIO}} {{POS_PROMPT}} {{SEED}}。
"""
from __future__ import annotations

from pathlib import Path

from .base import Agent
from ..seeding import derive_legacy_seed
from ..schemas import Shot


class LipsyncAgent(Agent):
    name = "对口型"

    def __init__(self, ctx):
        super().__init__(ctx)
        self.enabled = ctx.cfg("lipsync", "enabled", default=True)
        self.wf_path = ctx.workflow_path(
            ctx.cfg("workflows", "lipsync", default="infinitetalk_api.json"))

    def __call__(self, shot: Shot, shard: int) -> None:
        # 不需要对口型 -> 沿用 I2V 片段
        if not (self.enabled and shot.needs_lipsync and shot.voice_path and shot.dialogue):
            shot.final_clip_path = shot.clip_path
            shot.status = "done"
            return

        comfy = self.ctx.comfy(
            shard, model_name="infinitetalk-wan", min_vram_mib=24576
        )
        out_dir = self.ctx.paths.clips / shot.episode_id / "lipsync"
        ref = shot.keyframe_path or shot.clip_path
        params = {
            "REF_IMAGE": Path(ref).name,
            "AUDIO": Path(shot.voice_path).name,
            "POS_PROMPT": shot.video_prompt_en,
            "SEED": derive_legacy_seed(
                "lipsync",
                shot.shot_id,
            ).resolved_seed,
        }
        if not self.ctx.dry_run and self.wf_path.exists():
            comfy.upload_image(ref)
            # 音频走 upload_audio(底层同 /upload/image, 落进 input/ 供 LoadAudio 加载)
            comfy.upload_audio(shot.voice_path)

        wf = comfy.load_workflow(self.wf_path) if self.wf_path.exists() else {}
        wf = comfy.inject(wf, params) if wf else {}
        paths = comfy.run(wf, out_dir, save_node_types=("videos", "gifs", "images"))
        vids = [p for p in paths if p.suffix.lower() in (".mp4", ".webm")] or paths
        if vids:
            shot.final_clip_path = str(vids[0])
            shot.status = "done"
        else:
            # 对口型失败时降级用原片段, 不阻塞成片
            self.warn(f"{shot.shot_id} 对口型失败, 降级使用 I2V 片段")
            shot.final_clip_path = shot.clip_path
            shot.status = "done"
