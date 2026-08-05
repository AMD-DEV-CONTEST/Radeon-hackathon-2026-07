"""模块一: 视频生成模块.

接收提示词和参考图, 通过 ComfyUI 调用视频生成模型 (Wan2.1 或 MiniMax H3),
再用 FFmpeg 拆为帧序列。
"""
from __future__ import annotations

import time
import uuid
from pathlib import Path

from backend.comfyui_client import ComfyUIClient, ComfyUIError
from config import CONFIG, GenerationConfig, BACKEND_WORKFLOWS
from core.frame_utils import ensure_session_dirs
from utils.video_utils import (
    VideoError,
    get_video_info,
    split_video_to_frames,
)


class VideoGenerator:
    """视频生成模块 (支持 Wan2.1 i2v 和 MiniMax H3)."""

    def __init__(self, comfyui_url: str | None = None,
                 client: ComfyUIClient | None = None):
        self.client = client or ComfyUIClient(
            comfyui_url or CONFIG.comfyui_url,
            output_dir=CONFIG.output_dir / "raw",
        )

    def generate(
        self,
        prompt: str,
        reference_image: str | Path | None = None,
        duration: int = 4,
        resolution: tuple[int, int] = (832, 480),
        seed: int = -1,
        negative_prompt: str | None = None,
        steps: int | None = None,
        cfg: float | None = None,
        fps: int = 16,
        session_id: str | None = None,
        progress_callback=None,
        backend: str | None = None,
    ) -> dict:
        """生成视频并自动拆帧.

        Parameters
        ----------
        backend : str, optional
            ``wan21`` 或 ``minimax_h3``; 不提供则从配置读取。
        progress_callback : callable, optional
            ``cb(event_dict) -> None``, 用于 UI 进度显示。
        session_id : str, optional
            会话 ID; 不提供则自动生成。

        Returns
        -------
        dict
            ``{"video_path", "frames_dir", "frame_count", "fps", "session_id"}``
        """
        def _cb(ev):
            if progress_callback:
                progress_callback(ev)

        gen_cfg = GenerationConfig()
        backend = backend or gen_cfg.backend
        if backend not in BACKEND_WORKFLOWS:
            raise ValueError(f"未知后端: {backend}, 可选: {list(BACKEND_WORKFLOWS)}")
        be = BACKEND_WORKFLOWS[backend]
        backend_fps = be["fps"]
        # 如果调用方未指定 fps, 使用后端默认值
        if fps == 16 and backend == "minimax_h3":
            fps = backend_fps

        session_id = session_id or uuid.uuid4().hex[:12]
        dirs = ensure_session_dirs(session_id)

        _cb({"type": "status", "message": f"加载 {backend} 工作流..."})
        workflow = self.client.load_workflow(be["t2v"])

        # 设置提示词
        neg = negative_prompt or gen_cfg.negative_prompt
        if backend == "minimax_h3":
            # H3: prompt 在 MiniMaxH3ImageToVideo 节点, negative 在 CLIPTextEncode 节点
            self.client.set_node_param(workflow, be["node_prompt_pos"],
                                       "prompt", prompt)
            self.client.set_node_param(workflow, be["node_prompt_neg"],
                                       "text", neg)
        else:
            # Wan2.1: CLIPTextEncode 的 text 字段
            self.client.set_node_param(workflow, be["node_prompt_pos"],
                                       "text", prompt)
            self.client.set_node_param(workflow, be["node_prompt_neg"],
                                       "text", neg)

        # 设置分辨率与帧数
        width, height = resolution
        num_frames = max(5, int(duration * fps))
        # 按后端要求对齐帧数
        num_frames = be["frame_align"](num_frames)
        self.client.set_node_param(workflow, be["node_model"], "width", width)
        self.client.set_node_param(workflow, be["node_model"], "height", height)
        if backend == "minimax_h3":
            self.client.set_node_param(workflow, be["node_model"],
                                       "length", num_frames)
        else:
            self.client.set_node_param(workflow, be["node_model"],
                                       "length", num_frames)

        # 步数与 CFG
        self.client.set_node_param(
            workflow, be["node_ksampler"], "steps",
            steps if steps is not None else gen_cfg.num_inference_steps,
        )
        self.client.set_node_param(
            workflow, be["node_ksampler"], "cfg",
            cfg if cfg is not None else gen_cfg.guidance_scale,
        )

        # 输出帧率 (仅 Wan2.1 的 SaveVideo 有此参数)
        if backend != "minimax_h3":
            self.client.set_node_param(workflow, be["node_video_out"],
                                       "frame_rate", fps)

        # 参考图
        if reference_image is not None:
            _cb({"type": "status", "message": "上传参考图..."})
            ref_name = self.client.upload_image(reference_image)
            self.client.set_node_param(workflow, be["node_load_image"],
                                       "image", ref_name)
        elif backend == "minimax_h3":
            # H3 无参考图时移除 first_frame 连接 (纯 T2V)
            node_104 = workflow.get("104", {})
            node_104["inputs"].pop("first_frame", None)

        # 种子
        actual_seed = seed if seed is not None and seed >= 0 else int(time.time()) % (2**31)
        self.client.set_node_param(workflow, be["node_ksampler"],
                                   "seed", actual_seed)

        # 提交
        model_name = "MiniMax H3" if backend == "minimax_h3" else "Wan2.1"
        _cb({"type": "status", "message": f"提交生成任务 (seed={actual_seed})..."})
        prompt_id = self.client.queue_prompt(workflow)

        # 等待 (用进度迭代器)
        _cb({"type": "status", "message": f"{model_name} 生成中..."})
        outputs: list[Path] = []
        for ev in self.client.iter_progress(prompt_id, timeout=1800):
            if ev["type"] == "progress":
                _cb({"type": "progress", "value": ev["value"],
                     "message": f"采样中 {int(ev['value'] * 100)}%"})
            elif ev["type"] == "executing":
                _cb({"type": "status", "message": f"执行节点 {ev.get('node')}"})
            elif ev["type"] == "done":
                outputs = ev["outputs"]
                _cb({"type": "progress", "value": 1.0, "message": "生成完成"})
            elif ev["type"] == "error":
                raise ComfyUIError(f"生成失败: {ev.get('message')}")

        if not outputs:
            raise ComfyUIError("未获得输出文件")

        # H3 输出的是帧序列 (SaveImage), Wan2.1 输出视频文件
        video_path = _pick_video(outputs)
        if video_path is not None:
            # 视频文件 -> FFmpeg 拆帧
            _cb({"type": "status", "message": "FFmpeg 拆帧..."})
            frames = split_video_to_frames(video_path, dirs["frames"])
        else:
            # 帧序列 -> 直接复制到 frames 目录
            _cb({"type": "status", "message": "整理帧序列..."})
            import shutil
            frames = []
            for i, fp in enumerate(sorted(outputs), start=1):
                dst = dirs["frames"] / f"frame_{i:06d}.png"
                shutil.copy2(fp, dst)
                frames.append(dst)
            # 如果没有独立视频文件, 合成一个用于回放
            video_path = _frames_to_mp4(dirs["frames"], fps,
                                        CONFIG.output_dir / f"{session_id}.mp4")

        info = get_video_info(video_path)
        _cb({"type": "done", "message": "视频生成与拆帧完成"})
        return {
            "video_path": str(video_path),
            "frames_dir": str(dirs["frames"]),
            "frame_count": len(frames),
            "fps": int(info.fps) if info.fps > 0 else fps,
            "session_id": session_id,
            "seed": actual_seed,
            "backend": backend,
        }


def _pick_video(outputs: list[Path]) -> Path | None:
    """从输出中挑选视频文件 (mp4/webm/mov)."""
    for p in outputs:
        if p.suffix.lower() in (".mp4", ".webm", ".mov", ".mkv"):
            return p
    return None


def _to_mp4(src: Path, dst: Path) -> Path:
    """用 ffmpeg 将任意媒体转为 mp4 (无音轨)."""
    import subprocess
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-i", str(src),
        "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-crf", "18", str(dst),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise VideoError(f"转 mp4 失败: {r.stderr[-300:]}")
    return dst


def _frames_to_mp4(frames_dir: Path, fps: int, dst: Path) -> Path:
    """用 ffmpeg 将帧序列合成为 mp4 (用于回放)."""
    import subprocess
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-framerate", str(fps),
        "-i", str(frames_dir / "frame_%06d.png"),
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-crf", "18", str(dst),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise VideoError(f"帧序列合成 mp4 失败: {r.stderr[-300:]}")
    return dst
