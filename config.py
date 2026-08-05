"""FrameForge 全局配置.

集中管理模型路径、ComfyUI 地址、默认参数等。所有模块通过此文件读取配置,
避免硬编码。路径可根据实际部署环境通过环境变量覆盖。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent

# ComfyUI 后端地址
COMFYUI_URL = os.environ.get("COMFYUI_URL", "http://127.0.0.1:8188")

# ComfyUI 安装目录 (用于定位 models 目录与 output 目录)
COMFYUI_DIR = Path(os.environ.get("COMFYUI_DIR", PROJECT_ROOT.parent / "ComfyUI"))

# 输出目录
OUTPUT_DIR = PROJECT_ROOT / "outputs"
FRAMES_DIR = OUTPUT_DIR / "frames"
EDITED_DIR = OUTPUT_DIR / "edited"
MASKS_DIR = OUTPUT_DIR / "masks"
PROPAGATED_DIR = OUTPUT_DIR / "propagated"
FINAL_DIR = OUTPUT_DIR / "final"

# 工作流模板目录
WORKFLOWS_DIR = PROJECT_ROOT / "backend" / "workflows"

# 模型目录 (本地 RAFT 等独立模型, ComfyUI 模型在 COMFYUI_DIR/models 下)
MODELS_DIR = PROJECT_ROOT / "models"
RAFT_MODEL_PATH = MODELS_DIR / "raft-things.pth"


@dataclass
class GenerationConfig:
    """视频生成模块默认参数."""

    backend: str = "wan21"             # wan21 | minimax_h3
    duration: int = 4                  # 视频时长 (秒)
    resolution: tuple[int, int] = (832, 480)
    fps: int = 16                      # 输出帧率 (H3 使用 24)
    seed: int = -1                     # -1 表示随机
    negative_prompt: str = (
        "blurry, low quality, distorted, watermark, text, deformed, "
        "disfigured, bad anatomy, lowres"
    )
    guidance_scale: float = 7.5
    num_inference_steps: int = 30  # Wan2.1 默认; H3 在 BACKEND_WORKFLOWS 中覆盖为 15


# 各后端的工作流文件名与节点 ID 映射
BACKEND_WORKFLOWS = {
    "wan21": {
        "t2v": "wan21_i2v.json",
        "node_prompt_pos": "6",
        "node_prompt_neg": "7",
        "node_load_image": "15",
        "node_ksampler": "17",
        "node_model": "16",       # WanImageToVideo 节点
        "node_video_out": "20",
        "fps": 16,
        # Wan2.1 要求 num_frames = 4k+1
        "frame_align": lambda n: ((n - 1) // 4) * 4 + 1,
    },
    "minimax_h3": {
        "t2v": "minimax_h3_t2v.json",
        "default_steps": 15,
        "node_prompt_pos": "104",    # MiniMaxH3ImageToVideo: prompt 字段
        "node_prompt_neg": "14",     # CLIPTextEncode: text 字段 (负向)
        "node_load_image": "15",
        "node_ksampler": "17",
        "node_model": "104",         # MiniMaxH3ImageToVideo 节点
        "node_video_out": "92",      # SaveImage 节点
        "node_sigma_shift": "19",    # MiniMaxH3SigmaShift 节点
        "fps": 24,
        # H3 要求 num_frames = 17k+5, 向上取整 (与 ComfyUI align_frame_count 一致)
        "frame_align": lambda n: ((n + 11) // 17) * 17 + 5 if n >= 5 else 5,
    },
}


@dataclass
class EditConfig:
    """帧级编辑模块默认参数."""

    backend: str = "sdxl"              # sdxl | minimax_h3
    controlnet_type: str = "canny"     # canny | depth
    denoising_strength: float = 0.75
    controlnet_strength: float = 0.8
    controlnet_end: float = 0.8
    use_sam2_refine: bool = False      # MVP 默认关闭 SAM2
    inpaint_steps: int = 30
    cfg_scale: float = 7.5


@dataclass
class PropagationConfig:
    """编辑传播引擎默认参数."""

    propagation_range: int = 8         # 前后各 N 帧
    feather_sigma: float = 5.0         # 高斯羽化
    ssim_threshold: float = 0.6        # 低于此值标记为低质量
    raft_model_path: str = str(RAFT_MODEL_PATH)


@dataclass
class ComposerConfig:
    """视频合成模块默认参数."""

    fps: int = 16
    crf: int = 18                      # x264 质量 (越小越高)
    preset: str = "medium"
    pix_fmt: str = "yuv420p"


@dataclass
class AppConfig:
    """应用整体配置 (聚合)."""

    comfyui_url: str = COMFYUI_URL
    comfyui_dir: Path = COMFYUI_DIR
    output_dir: Path = OUTPUT_DIR
    generation: GenerationConfig = field(default_factory=GenerationConfig)
    edit: EditConfig = field(default_factory=EditConfig)
    propagation: PropagationConfig = field(default_factory=PropagationConfig)
    composer: ComposerConfig = field(default_factory=ComposerConfig)


# 默认单例
CONFIG = AppConfig()


def ensure_dirs() -> None:
    """创建所有输出子目录 (幂等)."""
    for d in (
        OUTPUT_DIR, FRAMES_DIR, EDITED_DIR, MASKS_DIR,
        PROPAGATED_DIR, FINAL_DIR, MODELS_DIR,
    ):
        d.mkdir(parents=True, exist_ok=True)


# 帧命名模板: frame_00001.png
FRAME_NAME_TEMPLATE = "frame_{:05d}.png"
