"""模块二: 帧级编辑模块.

对选定帧在涂抹区域内按新提示词进行局部重绘。
SDXL Inpainting + ControlNet (Canny/Depth), 可选 SAM2 mask 精化。
MiniMax H3 后端使用 instruction-guided edit (无需 mask, 通过提示词描述编辑意图)。
"""
from __future__ import annotations

import time
from pathlib import Path

import numpy as np

from backend.comfyui_client import ComfyUIClient, ComfyUIError
from config import CONFIG, EditConfig
from core.frame_utils import ensure_session_dirs
from utils.image_utils import (
    dilate_mask,
    extract_canny,
    normalize_mask,
    save_mask,
)
from utils.video_utils import read_frame, write_frame


# sdxl_inpaint.json 中可修改的节点 ID
_INP_CHECKPOINT = "4"
_INP_PROMPT_POS = "6"
_INP_PROMPT_NEG = "7"
_INP_LOAD_IMAGE = "9"
_INP_LOAD_MASK = "10"
_INP_KSAMPLER = "11"
_INP_VAEENCODE_INPAINT = "12"

# sdxl_inpaint_controlnet.json 中可修改的节点 ID
_CN_CHECKPOINT = "4"
_CN_PROMPT_POS = "6"
_CN_PROMPT_NEG = "7"
_CN_CONTROLNET_LOADER = "8"
_CN_LOAD_IMAGE = "9"
_CN_LOAD_MASK = "10"
_CN_KSAMPLER = "11"
_CN_CONTROLNET_APPLY = "16"
_CN_CANNY = "20"
_CN_DEPTH = "21"
_CN_SAVE = "15"

# minimax_h3_edit.json 中可修改的节点 ID
_H3_LOAD_IMAGE = "9"
_H3_MODEL_NODE = "104"       # MiniMaxH3ImageToVideo
_H3_KSAMPLER = "17"
_H3_SAVE = "15"


class FrameEditor:
    """帧级编辑模块 (SDXL Inpainting / MiniMax H3)."""

    def __init__(self, comfyui_url: str | None = None,
                 client: ComfyUIClient | None = None):
        self.client = client or ComfyUIClient(
            comfyui_url or CONFIG.comfyui_url,
            output_dir=CONFIG.output_dir / "edited_raw",
        )

    def edit_frame(
        self,
        frame_path: str | Path,
        mask: np.ndarray,
        edit_prompt: str,
        controlnet_type: str = "canny",
        denoising_strength: float = 0.75,
        controlnet_strength: float = 0.8,
        controlnet_end: float = 0.8,
        negative_prompt: str | None = None,
        steps: int | None = None,
        cfg: float | None = None,
        use_controlnet: bool = True,
        seed: int = -1,
        session_id: str | None = None,
        progress_callback=None,
        backend: str | None = None,
    ) -> dict:
        """对单帧进行局部重绘.

        Parameters
        ----------
        backend : str, optional
            ``sdxl`` (默认) 或 ``minimax_h3``。
            H3 使用 instruction-guided edit, mask 仅用于传播参考。
        frame_path : Path
            选定帧路径。
        mask : np.ndarray
            用户涂抹的 mask (二值图或软 mask, 白色为编辑区域)。
        edit_prompt : str
            编辑提示词。
        controlnet_type : str
            ``canny`` / ``depth`` (仅 SDXL)。
        use_controlnet : bool
            是否启用 ControlNet (False 则纯 inpaint, 仅 SDXL)。

        Returns
        -------
        dict
            ``{"edited_frame_path", "mask_path", "seed"}``
        """
        def _cb(ev):
            if progress_callback:
                progress_callback(ev)

        frame_path = Path(frame_path)
        edit_cfg = EditConfig()
        backend = backend or edit_cfg.backend
        controlnet_type = controlnet_type or edit_cfg.controlnet_type

        # 会话目录
        session_id = session_id or "default"
        dirs = ensure_session_dirs(session_id)

        # 归一化 + 轻微膨胀 mask (避免边缘留缝)
        mask_bin = normalize_mask(mask)
        mask_bin = dilate_mask(mask_bin, pixels=3)

        # 保存 mask (所有后端都需要, 用于传播)
        frame_stem = frame_path.stem
        mask_local = dirs["masks"] / f"{frame_stem}_mask.png"
        save_mask(mask_bin, mask_local)

        # 上传帧到 ComfyUI
        _cb({"type": "status", "message": "上传帧..."})
        img_name = self.client.upload_image(frame_path)

        actual_seed = seed if seed is not None and seed >= 0 else int(time.time()) % (2**31)
        n_steps = steps if steps is not None else edit_cfg.inpaint_steps
        n_cfg = cfg if cfg is not None else edit_cfg.cfg_scale
        neg = negative_prompt or "blurry, low quality, watermark, text, deformed"

        if backend == "minimax_h3":
            workflow = self.client.load_workflow("minimax_h3_edit.json")
            self._configure_h3_edit(
                workflow, edit_prompt, neg, img_name,
                actual_seed, n_steps, n_cfg, denoising_strength,
            )
            model_label = "MiniMax H3"
        else:
            # SDXL: 需要 mask
            mask_name = self.client.upload_mask(mask_local)
            workflow_name = (
                "sdxl_inpaint_controlnet.json" if use_controlnet
                else "sdxl_inpaint.json"
            )
            workflow = self.client.load_workflow(workflow_name)
            if use_controlnet:
                self._configure_controlnet(
                    workflow, edit_prompt, neg, img_name, mask_name,
                    actual_seed, n_steps, n_cfg, denoising_strength,
                    controlnet_type, controlnet_strength, controlnet_end,
                )
            else:
                self._configure_inpaint(
                    workflow, edit_prompt, neg, img_name, mask_name,
                    actual_seed, n_steps, n_cfg, denoising_strength,
                )
            model_label = "SDXL"

        # 提交
        _cb({"type": "status", "message": f"提交重绘任务 (seed={actual_seed})..."})
        prompt_id = self.client.queue_prompt(workflow)

        _cb({"type": "status", "message": f"{model_label} 重绘中..."})
        outputs: list[Path] = []
        for ev in self.client.iter_progress(prompt_id, timeout=600):
            if ev["type"] == "progress":
                _cb({"type": "progress", "value": ev["value"],
                     "message": f"采样中 {int(ev['value'] * 100)}%"})
            elif ev["type"] == "executing":
                _cb({"type": "status", "message": f"执行节点 {ev.get('node')}"})
            elif ev["type"] == "done":
                outputs = ev["outputs"]
                _cb({"type": "progress", "value": 1.0, "message": "重绘完成"})
            elif ev["type"] == "error":
                raise ComfyUIError(f"重绘失败: {ev.get('message')}")

        if not outputs:
            raise ComfyUIError("未获得重绘输出")

        # 取第一张图像作为编辑结果
        edited_img_path = outputs[0]
        # 复制到 session edited 目录, 保持帧名一致
        edited_dest = dirs["edited"] / f"{frame_stem}.png"
        edited_img_path = Path(edited_img_path)
        if edited_img_path.suffix.lower() != ".png":
            arr = read_frame(edited_img_path)
            write_frame(edited_dest, arr)
        else:
            import shutil
            shutil.copy2(edited_img_path, edited_dest)

        _cb({"type": "done", "message": "帧级编辑完成"})
        return {
            "edited_frame_path": str(edited_dest),
            "mask_path": str(mask_local),
            "seed": actual_seed,
        }

    # ------------------------------------------------------------------ #
    # 工作流配置辅助
    # ------------------------------------------------------------------ #
    def _configure_h3_edit(
        self, workflow, prompt, negative, img_name,
        seed, steps, cfg, denoise,
    ) -> None:
        """配置 MiniMax H3 编辑工作流 (instruction-guided edit)."""
        # H3 节点用 prompt 字段, 负向用 CLIPTextEncode 的 text 字段
        self.client.set_node_param(workflow, _H3_MODEL_NODE,
                                   "prompt", prompt)
        self.client.set_node_param(workflow, "14",  # CLIPTextEncode
                                   "text", negative)
        self.client.set_node_param(workflow, _H3_LOAD_IMAGE, "image", img_name)
        self.client.set_node_param(workflow, _H3_KSAMPLER, "seed", seed)
        self.client.set_node_param(workflow, _H3_KSAMPLER, "steps", steps)
        self.client.set_node_param(workflow, _H3_KSAMPLER, "cfg", cfg)
        self.client.set_node_param(workflow, _H3_KSAMPLER, "denoise", denoise)

    def _configure_inpaint(
        self, workflow, prompt, negative, img_name, mask_name,
        seed, steps, cfg, denoise,
    ) -> None:
        self.client.set_node_param(workflow, _INP_PROMPT_POS, "text", prompt)
        self.client.set_node_param(workflow, _INP_PROMPT_NEG, "text", negative)
        self.client.set_node_param(workflow, _INP_LOAD_IMAGE, "image", img_name)
        self.client.set_node_param(workflow, _INP_LOAD_MASK, "image", mask_name)
        self.client.set_node_param(workflow, _INP_KSAMPLER, "seed", seed)
        self.client.set_node_param(workflow, _INP_KSAMPLER, "steps", steps)
        self.client.set_node_param(workflow, _INP_KSAMPLER, "cfg", cfg)
        self.client.set_node_param(workflow, _INP_KSAMPLER, "denoise", denoise)

    def _configure_controlnet(
        self, workflow, prompt, negative, img_name, mask_name,
        seed, steps, cfg, denoise,
        controlnet_type, strength, end,
    ) -> None:
        self.client.set_node_param(workflow, _CN_PROMPT_POS, "text", prompt)
        self.client.set_node_param(workflow, _CN_PROMPT_NEG, "text", negative)
        self.client.set_node_param(workflow, _CN_LOAD_IMAGE, "image", img_name)
        self.client.set_node_param(workflow, _CN_LOAD_MASK, "image", mask_name)
        self.client.set_node_param(workflow, _CN_KSAMPLER, "seed", seed)
        self.client.set_node_param(workflow, _CN_KSAMPLER, "steps", steps)
        self.client.set_node_param(workflow, _CN_KSAMPLER, "cfg", cfg)
        self.client.set_node_param(workflow, _CN_KSAMPLER, "denoise", denoise)

        # ControlNet 模型名 (按类型)
        cn_model = (
            "controlnet-canny-sdxl-1.0.safetensors"
            if controlnet_type == "canny"
            else "controlnet-depth-sdxl-1.0.safetensors"
        )
        self.client.set_node_param(workflow, _CN_CONTROLNET_LOADER,
                                   "control_net_name", cn_model)
        self.client.set_node_param(workflow, _CN_CONTROLNET_APPLY,
                                   "strength", strength)
        self.client.set_node_param(workflow, _CN_CONTROLNET_APPLY,
                                   "end_percent", end)

        # 切换预处理节点: canny -> 20, depth -> 21
        if controlnet_type == "depth":
            # 把 ControlNetApply 的 image 输入改为 depth 节点
            workflow[_CN_CONTROLNET_APPLY]["inputs"]["image"] = [_CN_DEPTH, 0]
        else:
            workflow[_CN_CONTROLNET_APPLY]["inputs"]["image"] = [_CN_CANNY, 0]
