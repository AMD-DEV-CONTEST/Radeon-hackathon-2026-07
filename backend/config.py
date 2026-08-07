"""
NodeFlow 配置中心 — 模型注册表、风格预设、比例映射、许可证映射

本文件是纯数据文件,不依赖任何外部库 (torch / diffusers / PIL)。
所有模型、风格、比例、许可证的元数据集中管理,供 adapters 和 model_manager 引用。

支持的架构:
    - sdxl       : Stable Diffusion XL 系列 (Lightning / Animagine / Illustrious)
    - flux2klein : FLUX.2 Klein 系列 (distilled / base)

模式:
    - fast   : 快速版,主打速度 (蒸馏模型,少步推理)
    - expert : 专家版,主打质量 (完整模型,可调参数)
"""

# ---------------------------------------------------------------------------
# 1. 模型注册表
# ---------------------------------------------------------------------------

MODEL_REGISTRY: dict[str, dict] = {
    # === Fast 模式 ===

    "sdxl_lightning_4step": {
        "id": "sdxl_lightning_4step",
        "name": "SDXL Lightning 4-Step",
        "mode": "fast",
        "architecture": "sdxl",
        "hf_path": "ByteDance/SDXL-Lightning",
        "license": "open_rail_pp_m",
        "commercial_use": True,
        "vram_gb": 7,
        "is_distilled": True,
        "single_file_checkpoint": "sdxl_lightning_4step.safetensors",
        "supports_img2img": True,
        "supports_strength": True,
        "default_params": {
            "num_inference_steps": 4,
            "guidance_scale": 1.5,
            "negative_prompt": (
                "lowres, bad anatomy, bad hands, text, error, missing fingers, "
                "extra digit, fewer digits, cropped, worst quality, low quality, "
                "jpeg artifacts, signature, watermark, blurry"
            ),
        },
        "param_ranges": {
            "num_inference_steps": {"min": 4, "max": 4, "locked": True},
            "guidance_scale": {"min": 1.0, "max": 2.5, "locked": False},
            "strength": {"min": 0.1, "max": 1.0, "locked": False},
        },
        "supported_ratios": ["1:1", "3:4", "4:3", "3:2", "16:9"],
    },

    "sdxl_lightning_8step": {
        "id": "sdxl_lightning_8step",
        "name": "SDXL Lightning 8-Step",
        "mode": "fast",
        "architecture": "sdxl",
        "hf_path": "ByteDance/SDXL-Lightning",
        "license": "open_rail_pp_m",
        "commercial_use": True,
        "vram_gb": 7,
        "is_distilled": True,
        "single_file_checkpoint": "sdxl_lightning_8step.safetensors",
        "supports_img2img": True,
        "supports_strength": True,
        "default_params": {
            "num_inference_steps": 8,
            "guidance_scale": 2.0,
            "negative_prompt": (
                "lowres, bad anatomy, bad hands, text, error, missing fingers, "
                "extra digit, fewer digits, cropped, worst quality, low quality, "
                "jpeg artifacts, signature, watermark, blurry"
            ),
        },
        "param_ranges": {
            "num_inference_steps": {"min": 8, "max": 8, "locked": True},
            "guidance_scale": {"min": 1.5, "max": 3.0, "locked": False},
            "strength": {"min": 0.1, "max": 1.0, "locked": False},
        },
        "supported_ratios": ["1:1", "3:4", "4:3", "3:2", "16:9"],
    },

    # === Expert 模式 ===

    "flux2klein_distilled": {
        "id": "flux2klein_distilled",
        "name": "FLUX.2 Klein Distilled",
        "mode": "expert",
        "architecture": "flux2klein",
        "hf_path": "black-forest-labs/FLUX.2-klein-4B",
        "license": "apache_2_0",
        "commercial_use": True,
        "vram_gb": 8,
        "is_distilled": True,
        "supports_img2img": True,
        "supports_strength": False,  # Flux2Klein 图像编辑无 strength 参数
        "default_params": {
            "num_inference_steps": 4,
            "guidance_scale": 1.0,
        },
        "param_ranges": {
            "num_inference_steps": {"min": 4, "max": 4, "locked": True},
            "guidance_scale": {"min": 1.0, "max": 1.0, "locked": True},
        },
        "supported_ratios": ["1:1", "3:4", "4:3", "16:9", "9:16"],
    },

    "flux2klein_base": {
        "id": "flux2klein_base",
        "name": "FLUX.2 Klein Base",
        "mode": "expert",
        "architecture": "flux2klein",
        "hf_path": "black-forest-labs/FLUX.2-klein-4B",
        "license": "apache_2_0",
        "commercial_use": True,
        "vram_gb": 8,
        "is_distilled": False,
        "supports_img2img": True,
        "supports_strength": False,  # Flux2Klein 图像编辑无 strength 参数
        "default_params": {
            "num_inference_steps": 50,
            "guidance_scale": 4.0,
        },
        "param_ranges": {
            "num_inference_steps": {"min": 20, "max": 100, "locked": False},
            "guidance_scale": {"min": 1.0, "max": 10.0, "locked": False},
        },
        "supported_ratios": ["1:1", "3:4", "4:3", "16:9", "9:16"],
    },

    "animagine_xl": {
        "id": "animagine_xl",
        "name": "Animagine XL 4.0",
        "mode": "expert",
        "architecture": "sdxl",
        "hf_path": "cagliostrolab/animagine-xl-4.0",
        "license": "sdxl_license",
        "commercial_use": True,
        "vram_gb": 7,
        "is_distilled": False,
        "supports_img2img": True,
        "supports_strength": True,
        "default_params": {
            "num_inference_steps": 25,
            "guidance_scale": 7.0,
            "negative_prompt": (
                "lowres, bad anatomy, bad hands, text, error, missing fingers, "
                "extra digit, fewer digits, cropped, worst quality, low quality, "
                "normal quality, jpeg artifacts, signature, watermark, "
                "username, blurry"
            ),
        },
        "param_ranges": {
            "num_inference_steps": {"min": 20, "max": 50, "locked": False},
            "guidance_scale": {"min": 1.0, "max": 12.0, "locked": False},
            "strength": {"min": 0.1, "max": 1.0, "locked": False},
        },
        "supported_ratios": ["1:1", "3:4", "4:3", "3:2", "16:9"],
    },

    "illustrious_xl": {
        "id": "illustrious_xl",
        "name": "Illustrious XL",
        "mode": "expert",
        "architecture": "sdxl",
        "hf_path": "OnomaAIResearch/Illustrious-xl-early-release-v0",
        "license": "fair_ai",
        "commercial_use": False,
        "vram_gb": 7,
        "is_distilled": False,
        "supports_img2img": True,
        "supports_strength": True,
        "default_params": {
            "num_inference_steps": 28,
            "guidance_scale": 7.0,
            "negative_prompt": (
                "lowres, bad anatomy, bad hands, text, error, missing fingers, "
                "extra digit, fewer digits, cropped, worst quality, low quality, "
                "normal quality, jpeg artifacts, signature, watermark, blurry, "
                "artist name"
            ),
        },
        "param_ranges": {
            "num_inference_steps": {"min": 20, "max": 50, "locked": False},
            "guidance_scale": {"min": 1.0, "max": 12.0, "locked": False},
            "strength": {"min": 0.1, "max": 1.0, "locked": False},
        },
        "supported_ratios": ["1:1", "3:4", "4:3", "3:2", "16:9"],
    },

    "noobai_xl": {
        "id": "noobai_xl",
        "name": "NoobAI XL 1.0",
        "mode": "expert",
        "architecture": "sdxl",
        "hf_path": "Laxhar/noobai-XL-1.0",
        "license": "fair_ai",
        "commercial_use": False,
        "vram_gb": 7,
        "is_distilled": False,
        "supports_img2img": True,
        "supports_strength": True,
        "default_params": {
            "num_inference_steps": 28,
            "guidance_scale": 7.0,
            "negative_prompt": (
                "lowres, bad anatomy, bad hands, text, error, missing fingers, "
                "extra digit, fewer digits, cropped, worst quality, low quality, "
                "normal quality, jpeg artifacts, signature, watermark, blurry, "
                "artist name"
            ),
        },
        "param_ranges": {
            "num_inference_steps": {"min": 20, "max": 50, "locked": False},
            "guidance_scale": {"min": 1.0, "max": 12.0, "locked": False},
            "strength": {"min": 0.1, "max": 1.0, "locked": False},
        },
        "supported_ratios": ["1:1", "3:4", "4:3", "3:2", "16:9"],
    },
}


# ---------------------------------------------------------------------------
# 2. 风格预设 — 与原 engine.py 中的 8 种风格保持一致
# ---------------------------------------------------------------------------

STYLE_PRESETS: dict[str, str] = {
    "cyberpunk": "cyberpunk style, neon lights, futuristic, high-tech, dramatic lighting,",
    "anime": "anime style, vibrant colors, cel shading, studio ghibli inspired,",
    "watercolor": "watercolor painting, soft brush strokes, artistic, pastel colors,",
    "oil_painting": "oil painting, classical art style, rich textures, rembrandt lighting,",
    "3d_render": "3D render, octane render, photorealistic, cinematic lighting,",
    "pixel_art": "pixel art, 8-bit style, retro game aesthetic,",
    "concept_art": "concept art, digital painting, fantasy art, epic composition,",
    "minimalist": "minimalist design, clean lines, simple, elegant,",
}


# ---------------------------------------------------------------------------
# 3. 比例映射 — 两套尺寸映射 (SDXL 系 & Flux 系)
# ---------------------------------------------------------------------------

RATIO_MAPPINGS: dict[str, dict[str, dict]] = {
    # SDXL 系: 尺寸为 64 的倍数,总像素约 1024^2
    "sdxl": {
        "1:1": {"ratio": "1:1", "width": 1024, "height": 1024, "recommended": True},
        "3:4": {"ratio": "3:4", "width": 896, "height": 1152, "recommended": True},
        "4:3": {"ratio": "4:3", "width": 1152, "height": 896, "recommended": True},
        "3:2": {"ratio": "3:2", "width": 1216, "height": 832, "recommended": True},
        "16:9": {"ratio": "16:9", "width": 1344, "height": 768, "recommended": False},
    },
    # Flux 系: 尺寸为 16 的倍数
    "flux": {
        "1:1": {"ratio": "1:1", "width": 1024, "height": 1024, "recommended": True},
        "3:4": {"ratio": "3:4", "width": 896, "height": 1152, "recommended": True},
        "4:3": {"ratio": "4:3", "width": 1152, "height": 896, "recommended": True},
        "16:9": {"ratio": "16:9", "width": 1344, "height": 768, "recommended": True},
        "9:16": {"ratio": "9:16", "width": 768, "height": 1344, "recommended": True},
    },
}


# ---------------------------------------------------------------------------
# 4. 许可证信息 — 许可证到商用许可的映射表
# ---------------------------------------------------------------------------

LICENSE_INFO: dict[str, dict] = {
    "open_rail_pp_m": {
        "name": "CreativeML Open RAIL++-M License",
        "commercial_use": True,
        "description": (
            "开放许可,允许商用,但需遵守使用限制条款 "
            "(禁止生成违法/有害内容)。适用于 SDXL-Lightning。"
        ),
        "url": "https://github.com/StabilityAI/stablediffusion/blob/main/LICENSE-MODEL",
    },
    "apache_2_0": {
        "name": "Apache License 2.0",
        "commercial_use": True,
        "description": (
            "Apache 2.0 开源许可,允许商用、修改、分发,需保留版权声明。"
            "适用于 FLUX.2-klein-4B。"
        ),
        "url": "https://www.apache.org/licenses/LICENSE-2.0",
    },
    "sdxl_license": {
        "name": "SDXL License (CreativeML Open RAIL++-M)",
        "commercial_use": True,
        "description": (
            "SDXL 模型许可,基于 Open RAIL++-M,允许商用。"
            "适用于 Animagine XL 4.0。"
        ),
        "url": "https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/blob/main/LICENSE.md",
    },
    "fair_ai": {
        "name": "Fair AI Public License",
        "commercial_use": False,
        "description": (
            "Fair AI 公共许可证,限制商用。适用于 Illustrious XL。"
            "如需商用请单独联系版权方获取授权。"
        ),
        "url": "https://github.com/OnomaAI/Illustrious-xl/blob/main/LICENSE",
    },
    "cdla-permissive-2.0": {
        "name": "Community Data License Agreement – Permissive, Version 2.0",
        "commercial_use": True,
        "description": (
            "CDLA-Permissive 许可协议,允许商用和非商用使用、修改、分发。"
            "适用于 Detail Tweaker XL。"
        ),
        "url": "https://cdla.io/permissive-2-0/",
    },
    "flux-1-dev-non-commercial-license": {
        "name": "FLUX.1-dev Non-Commercial License",
        "commercial_use": False,
        "description": (
            "FLUX.1-dev 非商业许可,仅允许非商业研究用途。"
            "禁止用于商业目的。适用于 FLUX.1-dev 衍生 LoRA。"
        ),
        "url": "https://huggingface.co/black-forest-labs/FLUX.1-dev/blob/main/LICENSE.md",
    },
}


# ---------------------------------------------------------------------------
# 5. 辅助常量
# ---------------------------------------------------------------------------

# 生成超时 (秒)
GENERATION_TIMEOUT_SEC: int = 120

# 尺寸约束
MIN_RESOLUTION: int = 256
MAX_RESOLUTION: int = 1536

# SDXL 尺寸对齐 (64 的倍数)
SDXL_SIZE_ALIGNMENT: int = 64

# Flux2Klein 尺寸对齐 (16 的倍数)
FLUX_SIZE_ALIGNMENT: int = 16

# 架构到比例映射族的对应关系
ARCHITECTURE_RATIO_FAMILY: dict[str, str] = {
    "sdxl": "sdxl",
    "flux2klein": "flux",
}


# ===========================================================================
# 6. 应用层共享常量 (API 层 / engine 兼容层引用)
# ---------------------------------------------------------------------------
# 以下常量供 main.py (FastAPI 端点) 与 engine.py (兼容门面) 使用。
# 为避免与上面的模型注册表/比例映射冲突,集中放在文件末尾。
# 注意:ASPECT_RATIOS 由 RATIO_MAPPINGS 自动派生,保持与比例映射同步。
# ===========================================================================

# 双模式
DEFAULT_MODE: str = "fast"
SUPPORTED_MODES: list[str] = ["fast", "expert"]

# 默认宽高比
DEFAULT_ASPECT_RATIO: str = "1:1"

# 宽高比 -> (width, height),由 RATIO_MAPPINGS 自动派生 (取并集,首个命中优先)
ASPECT_RATIOS: dict[str, tuple[int, int]] = {}
for _ratio_family in RATIO_MAPPINGS.values():
    for _ratio_key, _ratio_info in _ratio_family.items():
        ASPECT_RATIOS.setdefault(
            _ratio_key, (_ratio_info["width"], _ratio_info["height"])
        )
del _ratio_family, _ratio_key, _ratio_info  # 清理临时变量,避免污染模块命名空间

# engine.py 兼容门面使用的默认推理参数 (仅作为签名默认值;
# 实际生成时 ModelManager 会使用各模型 default_params 中的值覆盖)
DEFAULT_NUM_STEPS: int = 4
DEFAULT_GUIDANCE_SCALE: float = 0.0

# 默认 (快速版) 模型 ID — 与 MODEL_REGISTRY 中的 fast 条目对应
DEFAULT_FAST_MODEL_ID: str = "sdxl_lightning_4step"

# 请求体校验约束
MAX_PROMPT_LENGTH: int = 2000
MAX_IMAGE_SIZE_MB: int = 10
ALLOWED_IMAGE_TYPES: set[str] = {"image/png", "image/jpeg", "image/webp"}


# ===========================================================================
# 7. LoRA 注册表
# ---------------------------------------------------------------------------
# 每个 LoRA 条目字段说明:
#   id            : 唯一标识 (用于 API / 前端引用)
#   name          : 展示名
#   category      : "general_quality" (通用优化) | "style" (风格化)
#   architecture  : 目标架构 "sdxl" | "flux" (决定能否加载到当前模型)
#   base_hf       : HuggingFace 仓库 ID (用于 load_lora_weights 直接加载)
#   file_name     : 仓库内具体 .safetensors 文件名 (可为 None 表示用默认)
#   download_url  : 直链下载地址 (resolve URL, curl -L 即可下载)
#   target_path   : 推荐本地保存路径 (相对 backend 或绝对路径)
#   default_weight: 推荐默认权重 (快速版会自动降权)
#   license       : 许可证标识 (对应 LICENSE_INFO)
#   commercial_use: 是否可商用
#   note          : 说明 / 限制
#
# NOTE on FLUX:
#   FLUX.1-dev 系 LoRA 均为 "flux-1-dev-non-commercial-license" (非商用),
#   且与 FLUX.2-klein-4B 架构不通用——FLUX.2-klein 的 LoRA 生态尚不成熟,
#   当前 FLUX 条目暂以 FLUX.1-dev 通用优化为主,实际加载需在 klein 上验证兼容性。
# ===========================================================================

LORA_REGISTRY: dict[str, dict] = {
    # ---------------------------------------------------------------
    # 通用优化 LoRA (提升细节 / 质感,不改变风格)
    # ---------------------------------------------------------------
    "sdxl_detail_tweaker": {
        "id": "sdxl_detail_tweaker",
        "name": "Detail Tweaker XL (SDXL 通用细节)",
        "category": "general_quality",
        "architecture": "sdxl",
        "base_hf": "LengXuXu/Detail_Tweaker_XL",
        "file_name": "add-detail-xl.safetensors",
        "download_url": (
            "https://huggingface.co/LengXuXu/Detail_Tweaker_XL/resolve/main/"
            "add-detail-xl.safetensors"
        ),
        "target_path": "/persistent/loras/sdxl/add-detail-xl.safetensors",
        "default_weight": 0.6,
        "license": "cdla-permissive-2.0",
        "commercial_use": True,
        "note": (
            "SDXL 通用细节增强,权重可双向调节 (正=增强细节,负=平滑)。"
            "推荐 -3~3 区间,常用 0.6。"
        ),
    },
    "flux_add_details": {
        "id": "flux_add_details",
        "name": "FLUX.1-dev Add Details (通用细节)",
        "category": "general_quality",
        "architecture": "flux",
        "base_hf": "Shakker-Labs/FLUX.1-dev-LoRA-add-details",
        "file_name": "FLUX-dev-lora-add_details.safetensors",
        "download_url": (
            "https://huggingface.co/Shakker-Labs/FLUX.1-dev-LoRA-add-details/"
            "resolve/main/FLUX-dev-lora-add_details.safetensors"
        ),
        "target_path": "/persistent/loras/flux/FLUX.1-dev-LoRA-add-details.safetensors",
        "default_weight": 1.0,
        "license": "flux-1-dev-non-commercial-license",
        "commercial_use": False,
        "note": (
            "FLUX.1-dev 通用细节增强,增强写实与皮肤质感。"
            "注意:非商用许可,且需在 FLUX.2-klein 上验证兼容性。"
        ),
    },
    "flux_realistic_lora": {
        "id": "flux_realistic_lora",
        "name": "FLUX.1-dev Realistic (写实)",
        "category": "general_quality",
        "architecture": "flux",
        "base_hf": "pablobonilla/flux-realistic-lora",
        "file_name": "lora.safetensors",
        "download_url": (
            "https://huggingface.co/pablobonilla/flux-realistic-lora/resolve/main/"
            "lora.safetensors"
        ),
        "target_path": "/persistent/loras/flux/flux-realistic-lora.safetensors",
        "default_weight": 0.8,
        "license": "flux-1-dev-non-commercial-license",
        "commercial_use": False,
        "note": (
            "FLUX.1-dev 写实摄影 LoRA,已确认文件名为 lora.safetensors。"
        ),
    },

    # ---------------------------------------------------------------
    # 风格化 LoRA (覆盖 base_family 的"主题"维度)
    # 注意:Civitai 下载链接带 token 鉴权,需 CIVITAI_API_TOKEN;
    #       HuggingFace resolve 链接无需鉴权。
    # ---------------------------------------------------------------
    "sdxl_cyberpunk": {
        "id": "sdxl_cyberpunk",
        "name": "Cyberpunk (SDXL)",
        "category": "style",
        "architecture": "sdxl",
        "base_hf": "issaccyj/lora-sdxl-cyberpunk",
        "file_name": "pytorch_lora_weights.safetensors",
        "download_url": (
            "https://huggingface.co/issaccyj/lora-sdxl-cyberpunk/resolve/main/"
            "pytorch_lora_weights.safetensors"
        ),
        "target_path": "/persistent/loras/sdxl/cyberpunk.safetensors",
        "default_weight": 0.8,
        "license": "openrail++",
        "commercial_use": True,
        "note": "Cyberpunk 风格 LoRA,触发词: cyberpunk style。",
    },
    "sdxl_anime": {
        "id": "sdxl_anime",
        "name": "Anime Style (SDXL)",
        "category": "style",
        "architecture": "sdxl",
        "base_hf": "DarkAngelH/Models_100_AnimeLoRA_SDXL",
        "file_name": "anime_sdxl_v1.safetensors",
        "download_url": (
            "https://huggingface.co/DarkAngelH/Models_100_AnimeLoRA_SDXL/resolve/main/"
            "anime_sdxl_v1.safetensors"
        ),
        "target_path": "/persistent/loras/sdxl/anime.safetensors",
        "default_weight": 0.7,
        "license": "openrail++",
        "commercial_use": True,
        "note": "通用 Anime 风 LoRA,用于 Lightning 等非 anime 底座。",
    },
    "sdxl_watercolor": {
        "id": "sdxl_watercolor",
        "name": "Watercolor (SDXL)",
        "category": "style",
        "architecture": "sdxl",
        "base_hf": "ostris/watercolor_style_lora_sdxl",
        "file_name": "watercolor_v1_sdxl.safetensors",
        "download_url": (
            "https://huggingface.co/ostris/watercolor_style_lora_sdxl/resolve/main/"
            "watercolor_v1_sdxl.safetensors"
        ),
        "target_path": "/persistent/loras/sdxl/watercolor.safetensors",
        "default_weight": 0.8,
        "license": "apache_2_0",
        "commercial_use": True,
        "note": "水彩风格 LoRA,无需触发词,自动转换。",
    },
    "sdxl_oil_painting": {
        "id": "sdxl_oil_painting",
        "name": "Oil Painting (SDXL)",
        "category": "style",
        "architecture": "sdxl",
        "base_hf": "chuckma/sdxl-oil-painting-lora",
        "file_name": "oil-painting.safetensors",
        "download_url": (
            "https://huggingface.co/chuckma/sdxl-oil-painting-lora/resolve/main/"
            "oil-painting.safetensors"
        ),
        "target_path": "/persistent/loras/sdxl/oil_painting.safetensors",
        "default_weight": 0.8,
        "license": "apache_2_0",
        "commercial_use": True,
        "note": "油画风格 LoRA,触发词: oil painting style。",
    },
    "sdxl_3d_render": {
        "id": "sdxl_3d_render",
        "name": "3D Render (SDXL)",
        "category": "style",
        "architecture": "sdxl",
        "base_hf": "suholee/3dAnimation-SDXL-LoRA-v1-50",
        "file_name": "3dAnimation-SDXL-LoRA-v1-50.safetensors",
        "download_url": (
            "https://huggingface.co/suholee/3dAnimation-SDXL-LoRA-v1-50/resolve/main/"
            "3dAnimation-SDXL-LoRA-v1-50.safetensors"
        ),
        "target_path": "/persistent/loras/sdxl/3d_render.safetensors",
        "default_weight": 0.8,
        "license": "openrail++",
        "commercial_use": True,
        "note": "3D 动画渲染风格 LoRA,触发词: 3d rendering style。",
    },
    "sdxl_pixel_art": {
        "id": "sdxl_pixel_art",
        "name": "Pixel Art (SDXL)",
        "category": "style",
        "architecture": "sdxl",
        "base_hf": "nerijs/pixel-art-xl",
        "file_name": "pixel-art-xl.safetensors",
        "download_url": (
            "https://huggingface.co/nerijs/pixel-art-xl/resolve/main/"
            "pixel-art-xl.safetensors"
        ),
        "target_path": "/persistent/loras/sdxl/pixel_art.safetensors",
        "default_weight": 0.8,
        "license": "creativeml-openrail-m",
        "commercial_use": True,
        "note": "像素风 LoRA,生成后需 8x 下采样 (Nearest) 获得像素效果。",
    },
    "sdxl_concept_art": {
        "id": "sdxl_concept_art",
        "name": "Concept Art (SDXL)",
        "category": "style",
        "architecture": "sdxl",
        "base_hf": "nncyberpunk/SDXL1.0_LoRA_ConceptArt_EclipseStyle_Pony",
        "file_name": "SDXL1.0_LoRA_ConceptArt_EclipseStyle_Pony.safetensors",
        "download_url": (
            "https://huggingface.co/nncyberpunk/SDXL1.0_LoRA_ConceptArt_EclipseStyle_Pony/"
            "resolve/main/SDXL1.0_LoRA_ConceptArt_EclipseStyle_Pony.safetensors"
        ),
        "target_path": "/persistent/loras/sdxl/concept_art.safetensors",
        "default_weight": 0.8,
        "license": "openrail++",
        "commercial_use": True,
        "note": "概念艺术/黄昏风格 LoRA,适用于 SDXL 底座。",
    },
    "sdxl_minimalist": {
        "id": "sdxl_minimalist",
        "name": "Minimalist (SDXL)",
        "category": "style",
        "architecture": "sdxl",
        "base_hf": "e-n-v-y/envy-shadow-minimalism-xl-01",
        "file_name": "EnvyShadowMinimalismXL01.safetensors",
        "download_url": (
            "https://huggingface.co/e-n-v-y/envy-shadow-minimalism-xl-01/resolve/main/"
            "EnvyShadowMinimalismXL01.safetensors"
        ),
        "target_path": "/persistent/loras/sdxl/minimalist.safetensors",
        "default_weight": 0.8,
        "license": "bespoke-lora-trained-license",
        "commercial_use": "unknown",
        "note": "极简主义/阴影风格 LoRA,适用于建筑、人物剪影等。",
    },
}


# 已确认可下载的 LoRA (含 download_url 且非 None) 的 ID 集合
# 用于下载脚本 / 商店展示,与 LORA_REGISTRY 保持一致。
DOWNLOADABLE_LORA_IDS: list[str] = [
    lora_id
    for lora_id, lora_cfg in LORA_REGISTRY.items()
    if lora_cfg.get("download_url")
]
