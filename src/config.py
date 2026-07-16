"""AMD Radeon Studio - global configuration.

All paths are computed relative to the project root so the same code works
whether you run it from a notebook (cwd=notebooks/) or from src/ as a module.

Model registry: see `docs/decisions/0001-why-sdxl.md` (SDXL chosen as base).
"""
from pathlib import Path

# ---- Paths ----
PROJECT_ROOT = Path(__file__).resolve().parent.parent
NOTEBOOKS_DIR = PROJECT_ROOT / "notebooks"
SRC_DIR = PROJECT_ROOT / "src"
DATA_DIR = PROJECT_ROOT / "data"
OUTPUTS_DIR = PROJECT_ROOT / "outputs"
WORKFLOWS_DIR = PROJECT_ROOT / "comfyui_workflows"
DOCS_DIR = PROJECT_ROOT / "docs"

OUTPUTS_DIR.mkdir(exist_ok=True)

# ---- Compute ----
# ROCm uses the 'cuda' device alias in PyTorch (see src.core.device).
# We default to "cuda" and let device.py auto-detect ROCm vs NVIDIA at runtime.
DEVICE = "cuda"
DTYPE = "float16"  # FP16 is the safe default on Radeon; try BF16 on MI300X.

# ---- Model registry (see ADR 0001, 0002) ----
# `*_dev` = smaller / faster for iteration; `*_prod` = quality-first for demos.
MODELS = {
    # ---- Text-to-image base ----
    "sdxl_base":      "stabilityai/stable-diffusion-xl-base-1.0",  # ~6.5GB, default
    "sd_turbo":       "stabilityai/sd-turbo",                      # ~2GB, smoke test only

    # ---- IP-Adapter for style transfer (ADR 0002) ----
    "ip_adapter_sdxl": "h94/IP-Adapter",                            # ~1.5GB
    "ip_adapter_img":  "h94/IP-Adapter",  # alias; uses ip_adapter.bin

    # ---- ControlNet (img2img structural control, v0.1 暂不集成) ----
    "controlnet_canny": "diffusers/controlnet-canny-sdxl-1.0",

    # ---- v0.2+ 预留(本版本不实现)----
    # "i2v":    "Wan-AI/Wan2.1-I2V-14B-720P",   # 图生视频
    # "esrgan": "ai-forever/Real-ESRGAN",       # 画质增强
}

DEFAULT_T2I = MODELS["sdxl_base"]
DEFAULT_STYLE_ADAPTER = MODELS["ip_adapter_sdxl"]
DEFAULT_DTYPE = DTYPE

# ---- Generation defaults ----
DEFAULT_HEIGHT = 1024
DEFAULT_WIDTH = 1024
DEFAULT_STEPS = 30
DEFAULT_GUIDANCE = 7.5

# IP-Adapter 默认强度(用户可在 UI 调)
DEFAULT_IP_ADAPTER_SCALE = 0.6

# img2img 默认 strength(修改力度, 0.1-1.0)
DEFAULT_IMG2IMG_STRENGTH = 0.6

# ---- Cloud LLM (auxiliary, optional) ----
# Used only for the agent planning layer, not for core generation.
# 在 AMD Radeon Cloud 上跑项目时,可填 .env 的 AMD_LLM_* 变量启用。
LLM_CONFIG = {
    "provider": "amd",
    "base_url_env": "AMD_LLM_BASE_URL",
    "model_env": "AMD_LLM_MODEL",
    "api_key_env": "AMD_LLM_API_KEY",
    "default_base_url": "https://developer.amd.com.cn/radeon/api/v1",
    "default_model": "Qwen3.6-35B-A3B",
}

# ---- Logging ----
import logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
log = logging.getLogger("radeon_studio")
