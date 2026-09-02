"""阶段 8 — 视频片段 agent(ComfyUI, Wan2.2 I2V, 镜头级并行)。

把每个镜头的关键帧 + 运动提示词喂给 Wan2.2 I2V, 生成 3-6 秒片段。
48G 单卡建议 480p / FP8(或 GGUF 量化); 两张卡并行翻倍产能。
工作流: i2v_wan22_api.json。占位符: {{REF_IMAGE}} {{POS_PROMPT}} {{NEG_PROMPT}}
{{FRAMES}} {{FPS}} {{SEED}} {{WIDTH}} {{HEIGHT}}。
"""
from __future__ import annotations

from pathlib import Path

from .base import Agent
from ..runtime import DramaCancelled
from ..seeding import derive_legacy_seed
from ..schemas import Shot
from ..video_providers import (
    ComfyWanProvider,
    ProviderState,
    VideoRequest,
    wait_for_provider,
)


class VideoGenerator(Agent):
    name = "视频生成"

    def __init__(self, ctx, shot_list=None):
        super().__init__(ctx)
        self.shot_list = shot_list   # 用于"接上一镜末帧"时定位上一镜
        self.wf_path = ctx.workflow_path(
            ctx.cfg("workflows", "i2v", default="i2v_wan22_api.json"))

    def _seed_for(self, shot: Shot) -> int:
        """I2V seed: explicit reroll override, otherwise stable SHA-256."""
        if int(getattr(shot, "clip_seed", 0)):
            return int(shot.clip_seed) & 0x7FFFFFFF
        return derive_legacy_seed("i2v", shot.shot_id).resolved_seed

    def _start_image(self, shot: Shot) -> str:
        """I2V 起始帧: continue_from_prev 且上一镜已成片 → 取上一镜末帧(动作连贯);
        否则(切镜头/上一镜未就绪)用本镜关键帧。"""
        if (getattr(shot, "continue_from_prev", False)
                and self.shot_list and not self.ctx.dry_run):
            shots = self.shot_list.shots
            idx = next((k for k, s in enumerate(shots) if s.shot_id == shot.shot_id), 0)
            if idx > 0:
                prev = shots[idx - 1]
                if prev.clip_path and Path(prev.clip_path).exists():
                    try:
                        from ..utils import last_frame
                        out = (self.ctx.paths.clips / shot.episode_id
                               / f"{shot.shot_id}_prevend.png")
                        last_frame(prev.clip_path, out)
                        return str(out)
                    except Exception as e:  # noqa: BLE001
                        self.warn(f"{shot.shot_id} 取上一镜末帧失败, 回退关键帧: {e}")
        return shot.keyframe_path

    def __call__(self, shot: Shot, shard: int) -> None:
        if not shot.keyframe_path:
            raise RuntimeError("缺少关键帧, 无法 I2V")
        out_dir = self.ctx.paths.clips / shot.episode_id
        start_img = self._start_image(shot)
        provider_name = str(
            self.ctx.cfg("video", "provider", default="comfy_wan")
        ).strip()
        request = VideoRequest(
            shot_id=shot.shot_id,
            image_path=Path(start_img),
            prompt=shot.video_prompt_en,
            negative_prompt=shot.negative_prompt,
            duration_seconds=shot.duration_sec,
            output_directory=out_dir,
            seed=self._seed_for(shot),
        )
        if provider_name == "comfy_wan":
            provider = ComfyWanProvider(self._generate_comfy)
        else:
            provider = self.ctx.video_providers.get(provider_name)
            if provider is None:
                raise RuntimeError("视频 Provider 未配置")
        shot.video_provider = provider_name
        shot.provider_state = ProviderState.QUEUED.value
        try:
            submitted = provider.submit(request, gpu_index=shard)
            shot.provider_job_id = submitted.provider_job_id
            shot.provider_state = submitted.state.value
            result = wait_for_provider(
                provider,
                submitted.provider_job_id,
                self.ctx.cancellation,
                poll_interval=float(
                    self.ctx.cfg("video", "provider_poll_seconds", default=1.0)
                ),
            )
            shot.provider_state = result.state.value
            shot.provider_error_code = result.safe_error_code or ""
            if result.state is not ProviderState.SUCCEEDED:
                raise RuntimeError("视频 Provider 未成功")
            suffix = result.output_path.suffix if result.output_path is not None else ".mp4"
            output = provider.fetch(
                result.provider_job_id,
                out_dir / f"{shot.shot_id}_{provider_name}{suffix}",
            )
        except DramaCancelled:
            if shot.provider_job_id:
                provider.cancel(shot.provider_job_id)
            shot.provider_state = ProviderState.CANCELLED.value
            raise
        except BaseException:
            shot.provider_state = ProviderState.FAILED.value
            shot.provider_error_code = shot.provider_error_code or "generation_failed"
            raise
        shot.clip_path = str(output)
        shot.status = "clip_ok"

    def _generate_comfy(self, request: VideoRequest, shard: int) -> Path:
        comfy = self.ctx.comfy(
            shard, model_name="wan2.2-i2v", min_vram_mib=24576
        )
        out_dir = request.output_directory

        fps = self.ctx.cfg("video", "model_fps", default=16)
        frames = int(round(request.duration_seconds * fps))
        # 限制在模型稳定区间
        frames = max(self.ctx.cfg("video", "min_frames", default=49),
                     min(frames, self.ctx.cfg("video", "max_frames", default=121)))

        params = {
            "REF_IMAGE": request.image_path.name,
            "POS_PROMPT": request.prompt,
            "NEG_PROMPT": request.negative_prompt,
            "FRAMES": frames, "FPS": fps,
            "SEED": request.seed,
            "WIDTH": self.ctx.cfg("video", "gen_width", default=480),
            "HEIGHT": self.ctx.cfg("video", "gen_height", default=832),
        }
        if not self.ctx.dry_run and self.wf_path.exists():
            comfy.upload_image(request.image_path)

        wf = comfy.load_workflow(self.wf_path) if self.wf_path.exists() else {}
        wf = comfy.inject(wf, params) if wf else {}
        self.ctx.progress.start_shot(
            request.shot_id,
            "clip",
            shard,
            comfy.base,
            episode=request.shot_id.split("_S", 1)[0],
        )
        try:
            paths = comfy.run(wf, out_dir, save_node_types=("videos", "gifs", "images"),
                              prefix=request.shot_id,
                              progress_cb=lambda v, m, node: self.ctx.progress.update_step(
                                  request.shot_id, node, v, m))
        finally:
            self.ctx.progress.finish_shot(request.shot_id)
        vids = [p for p in paths if p.suffix.lower() in (".mp4", ".webm", ".gif")] or paths
        if not vids:
            raise RuntimeError("I2V 无视频产物")
        return vids[0]
