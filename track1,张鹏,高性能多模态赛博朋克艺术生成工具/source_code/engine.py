# -*- coding: utf-8 -*-
import os
import shutil
import gc
from typing import Any, Optional, Tuple

import numpy as np
import torch
from diffusers import (
    StableDiffusionImg2ImgPipeline,
    StableDiffusionPipeline,
    TextToVideoSDPipeline,
    StableDiffusion3Pipeline,
)
try:
    from diffusers import StableDiffusion3Img2ImgPipeline
    _SD3_IMG2IMG_AVAILABLE = True
except Exception:
    StableDiffusion3Img2ImgPipeline = None
    _SD3_IMG2IMG_AVAILABLE = False
try:
    from diffusers import (
        StableDiffusionXLPipeline,
        StableDiffusionXLImg2ImgPipeline,
    )
    _SDXL_AVAILABLE = True
except Exception as _sdxl_err:
    # Older diffusers may not ship SDXL pipelines; degrade gracefully.
    StableDiffusionXLPipeline = None
    StableDiffusionXLImg2ImgPipeline = None
    _SDXL_AVAILABLE = False
    print(f"WARNING: SDXL pipelines unavailable: {_sdxl_err}")
from diffusers.utils import export_to_video, export_to_gif
from PIL import Image


def _free_disk_gb(path: str) -> float:
    """Free disk space (GB) on the filesystem holding `path`.

    Walks up to an existing ancestor so it works even before `path` is
    created. Returns inf on any error (so callers treat 'unknown' as 'allow').
    """
    p = path or "."
    while p and not os.path.exists(p):
        parent = os.path.dirname(p)
        if parent == p:
            break
        p = parent
    try:
        return shutil.disk_usage(p).free / (1024 ** 3)
    except Exception:
        return float("inf")


# ================================================================
# Cross-version wrappers for diffusers video/gif exporters
# ----------------------------------------------------------------
# diffusers changed signatures multiple times:
#   export_to_video(frames, output_path=..., fps=...)   (new, 0.32+)
#   export_to_video(frames, video_path=...,  fps=...)   (old, <0.30)
#   export_to_video(frames, fps=...) -> bytes          (oldest / forks)
# Same for export_to_gif(output_path / gif_path / return bytes).
# We inspect the signature lazily on first call and remember which
# convention works, then always fall back to writing bytes ourselves
# as the last resort (so we never crash over naming differences).
# ================================================================
import re
import inspect as _inspect

# ----------------------------------------------------------------
# Helpers: CLIP prompt truncation (legacy SD / damo-vilab T2V)
# Legacy TextToVideoSDPipeline uses CLIP text encoder with max 77 tokens.
# Chinese / long prompts blow past 77, print a harsh warning, and most
# importantly produce a broken embedding tensor that, in some diffusers +
# ROCm/driver combos, hangs the first denoising kernel at 0%.  We pre-truncate
# to safe length by counting CLIP subword tokens with a best-effort tokenizer
# probe (fallback to char count if tokenizer not loaded).
# ----------------------------------------------------------------
_CLIP_MAX_TOKENS = 77
_CLIP_BOS_EOS = 2  # <bos> + <eos> reserve
_CLIP_CHAR_PER_TOKEN_EST = 3.2  # English subword conservative ratio


def _truncate_for_clip(prompt: str, max_tokens: int = _CLIP_MAX_TOKENS) -> str:
    """Best-effort CLIP-aware truncation.  Returns a prompt string that should
    fit inside `max_tokens` CLIP subword tokens including BOS/EOS."""
    if not prompt:
        return ""
    budget = max_tokens - _CLIP_BOS_EOS
    if budget <= 0:
        budget = 1

    # Try real CLIP tokenizer if we can cheaply access it (already loaded)
    tok = None
    try:
        pipe = globals().get("self")  # can't use self here; fall through below
    except Exception:
        pipe = None

    # Best-effort: try to import CLIPTokenizer, pretrained via common weights
    # (cached loads are free; uncached we don't want to download 500MB just
    #  for truncation - catch OSError and switch to char estimate)
    if tok is None:
        try:
            # If pipeline already loaded, read tokenizer, else don't download
            import transformers  # noqa: F401
        except Exception:
            pass

    # Heuristic: comma separated qualifiers; drop rightmost first until short.
    # This works well with our "subject, style, quality, detail, detail, ..." form.
    parts = [p.strip() for p in re.split(r"[,?]", prompt) if p.strip()]
    if len(parts) <= 1:
        # Fallback: simple char-based truncate; try to keep whole words
        max_chars = int(budget * _CLIP_CHAR_PER_TOKEN_EST)
        if len(prompt) > max_chars:
            # cut at last space before max_chars
            head = prompt[:max_chars]
            cut = head.rfind(" ")
            if cut > max_chars // 2:
                head = head[:cut]
            return head
        return prompt

    # Iteratively drop the *last* quality keyword until we're under budget.
    # Use 2 tokens per comma-part as rough estimate.
    while True:
        estimated = max(1, sum(max(2, len(p) // 4) for p in parts))
        if estimated <= budget or len(parts) <= 2:
            break
        parts.pop()
    result = ", ".join(parts)
    # Final safety net: char-based hard cap
    max_chars = int(budget * _CLIP_CHAR_PER_TOKEN_EST)
    if len(result) > max_chars:
        result = result[:max_chars]
        # try not to split in the middle of a word
        sp = result.rfind(" ")
        if sp > max_chars // 2:
            result = result[:sp]
    return result

_E_VIDEO_KWARG = None   # 'output_path' | 'video_path' | '' (bytes-only)
_E_GIF_KWARG = None     # 'output_path' | 'gif_path'   | '' (bytes-only)


def _probe_exporter(fn, preferred_names):
    """Return the right kwarg name for fn(), or '' if it only returns bytes."""
    try:
        sig = _inspect.signature(fn)
    except (TypeError, ValueError):
        return ''
    params = set(sig.parameters.keys())
    for name in preferred_names:
        if name in params:
            return name
    return ''


def _normalize_video_frames(frames):
    """Convert various video-pipeline frame outputs into a flat list of PIL.Image.

    Handles the combinations returned by different diffusers versions:
      - list[list[PIL.Image]]  (batched, outer list is batch)
      - list[PIL.Image]        (flat)
      - np.ndarray 5D (1, N, H, W, 3) or 4D (N, H, W, 3) float/uint8
      - Any other iterable of ndarray / PIL.Image
    Raises ValueError on empty.
    """
    import numpy as _np
    from PIL import Image as _Image

    # 1) Quick return if already list of PIL.Image
    if (
        isinstance(frames, list)
        and len(frames) > 0
        and isinstance(frames[0], _Image.Image)
    ):
        return frames

    # 2) Nested list of PIL (batch=1): unwrap once
    if (
        isinstance(frames, list)
        and len(frames) > 0
        and isinstance(frames[0], list)
        and len(frames[0]) > 0
        and isinstance(frames[0][0], _Image.Image)
    ):
        return frames[0]

    # 3) Numpy array: 5D (B, N, H, W, C) / 4D (N, H, W, C) / 5D (B, N, C, H, W) etc
    if isinstance(frames, _np.ndarray):
        arr = frames
        # squeeze leading batch-1 dim
        if arr.ndim == 5 and arr.shape[0] == 1:
            arr = arr[0]
        # (N, H, W, C) ? normal
        if arr.ndim != 4:
            raise ValueError(f"Unexpected video ndarray shape after squeeze: {arr.shape}")
        out = []
        for i in range(arr.shape[0]):
            a = arr[i]
            # (C, H, W) channel-first possible too
            if a.ndim == 3 and a.shape[0] in (1, 3, 4) and a.shape[-1] not in (1, 3, 4):
                a = _np.transpose(a, (1, 2, 0))
            if a.dtype != _np.uint8:
                a = _np.clip(a * 255.0, 0, 255).astype(_np.uint8)
            out.append(_Image.fromarray(a))
        return out

    # 4) Fallback: generic iterable - try to convert each element
    out = []
    for f in frames:
        if isinstance(f, _Image.Image):
            out.append(f)
        elif isinstance(f, _np.ndarray):
            a = f
            if a.ndim == 3 and a.shape[0] in (1, 3, 4) and a.shape[-1] not in (1, 3, 4):
                a = _np.transpose(a, (1, 2, 0))
            if a.dtype != _np.uint8:
                a = _np.clip(a * 255.0, 0, 255).astype(_np.uint8)
            out.append(_Image.fromarray(a))
        elif isinstance(f, list):
            # nested iterable: recurse
            out.extend(_normalize_video_frames(f))
        else:
            raise TypeError(
                f"_normalize_video_frames: unsupported element type {type(f).__name__}"
            )
    return out


def _safe_export_to_video(frames, output_path, fps=8):
    frames = _normalize_video_frames(frames)
    global _E_VIDEO_KWARG
    if _E_VIDEO_KWARG is None:
        _E_VIDEO_KWARG = _probe_exporter(
            export_to_video, ('output_path', 'video_path')
        )
    path = os.path.abspath(str(output_path))
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)

    def _write_bytes_or_return(ret):
        # Accept either:
        #  - str/Path -> returned written path
        #  - bytes/bytearray -> write to path ourselves
        if isinstance(ret, (bytes, bytearray)):
            with open(path, 'wb') as f:
                f.write(bytes(ret))
            return path
        if hasattr(ret, '__fspath__'):
            return os.fspath(ret)
        if isinstance(ret, str) and ret and os.path.exists(ret):
            return ret
        # fn likely returned the path we asked for or None; confirm file exists
        if os.path.exists(path) and os.path.getsize(path) > 0:
            return path
        # Last-ditch: whatever it is, return canonical path
        return path

    tried = []
    if _E_VIDEO_KWARG:
        try:
            tried.append(_E_VIDEO_KWARG)
            return _write_bytes_or_return(
                export_to_video(frames, fps=fps, **{_E_VIDEO_KWARG: path})
            )
        except TypeError as _e:
            # signature changed after probe? fall through & try the other name.
            tried.append(f'{_E_VIDEO_KWARG}=>TypeError:{_e}')

    for name in ('output_path', 'video_path'):
        if name in tried:
            continue
        tried.append(name)
        try:
            return _write_bytes_or_return(
                export_to_video(frames, fps=fps, **{name: path})
            )
        except TypeError:
            continue

    # Bytes-only / unknown signature.
    tried.append('positional-bytes')
    try:
        ret = export_to_video(frames, fps=fps)
        return _write_bytes_or_return(ret)
    except TypeError:
        # Oldest positional: export_to_video(frames, path, fps)
        try:
            ret = export_to_video(frames, path, fps)
            return _write_bytes_or_return(ret)
        except Exception as _e:
            raise RuntimeError(
                f"export_to_video() failed with all conventions (tried={tried}): {_e}"
            ) from _e


def _safe_export_to_gif(frames, output_path, fps=8):
    frames = _normalize_video_frames(frames)
    global _E_GIF_KWARG
    if _E_GIF_KWARG is None:
        _E_GIF_KWARG = _probe_exporter(
            export_to_gif, ('output_path', 'gif_path')
        )
    path = os.path.abspath(str(output_path))
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)

    def _write_bytes_or_return(ret):
        if isinstance(ret, (bytes, bytearray)):
            with open(path, 'wb') as f:
                f.write(bytes(ret))
            return path
        if hasattr(ret, '__fspath__'):
            return os.fspath(ret)
        if isinstance(ret, str) and ret and os.path.exists(ret):
            return ret
        if os.path.exists(path) and os.path.getsize(path) > 0:
            return path
        return path

    tried = []
    if _E_GIF_KWARG:
        try:
            tried.append(_E_GIF_KWARG)
            return _write_bytes_or_return(
                export_to_gif(frames, fps=fps, **{_E_GIF_KWARG: path})
            )
        except TypeError:
            tried.append(f'{_E_GIF_KWARG}=>TypeError')
    for name in ('output_path', 'gif_path'):
        if name in tried:
            continue
        tried.append(name)
        try:
            return _write_bytes_or_return(
                export_to_gif(frames, fps=fps, **{name: path})
            )
        except TypeError:
            continue
    tried.append('positional-bytes')
    try:
        ret = export_to_gif(frames, fps=fps)
        return _write_bytes_or_return(ret)
    except TypeError:
        try:
            ret = export_to_gif(frames, path, fps)
            return _write_bytes_or_return(ret)
        except Exception as _e:
            raise RuntimeError(
                f"export_to_gif() failed with all conventions (tried={tried}): {_e}"
            ) from _e

# LTX-Video text-to-video pipeline (DiT + T5-XXL, fast + long prompts, ROCm-native)
# Uses diffusers LTXPipeline (Lightricks/LTX-Video, Apache-2.0, non-gated).
# T5-XXL text encoder supports 512 tokens (vs CLIP's 77), so prompts are effectively
# unlimited. Real-time capable on a single GPU — far faster than legacy damo-vilab.
_LTX_VIDEO_AVAILABLE = False
_LTX_IMPORT_ERROR: Optional[str] = None
try:
    from diffusers import LTXPipeline  # type: ignore
    _LTX_VIDEO_AVAILABLE = True
except Exception as _ltx_e:
    _LTX_IMPORT_ERROR = f"{type(_ltx_e).__name__}: {_ltx_e}"
    print(f"WARNING: LTX-Video pipeline not importable: {_LTX_IMPORT_ERROR}")
    print("  Install/upgrade: pip install -U diffusers (needs >= 0.33)")


# Wan2.2-TI2V-5B text-to-video pipeline (DiT, umt5-xxl, native Chinese, 720P@24fps)
# Uses diffusers WanPipeline (Wan-AI/Wan2.2-TI2V-5B-Diffusers, Apache-2.0, non-gated).
# umt5-xxl text encoder is multilingual (incl. Chinese) -> no translation layer needed.
_WAN_T2V_AVAILABLE = False
_WAN_IMPORT_ERROR: Optional[str] = None
try:
    from diffusers import WanPipeline  # type: ignore
    _WAN_T2V_AVAILABLE = True
except Exception as _wan_e:
    _WAN_IMPORT_ERROR = f"{type(_wan_e).__name__}: {_wan_e}"
    print(f"WARNING: Wan2.2-TI2V-5B pipeline not importable: {_WAN_IMPORT_ERROR}")
    print("  Install/upgrade: pip install -U diffusers (needs >= 0.33)")


DEFAULT_T2V_MODEL = "damo-vilab/text-to-video-ms-1.7b"
DEFAULT_SD_MODEL = "runwayml/stable-diffusion-v1-5"
DEFAULT_SDXL_MODEL = "stabilityai/stable-diffusion-xl-base-1.0"
# 默认使用开源、非 gated 的 Stable Diffusion 3.5 Medium（Community License，可直接下载）。
# SD3.5-Medium 使用 MMDiT 架构，三路文本编码器（CLIP-L + CLIP-G + T5-XXL），
# 画质与 Flux.1 接近但体积更小（~10GB），支持负向提示词，48GB 显存轻松运行。
SD3_MEDIUM_MODEL = "stabilityai/stable-diffusion-3.5-medium"
SD3_LARGE_MODEL = "stabilityai/stable-diffusion-3.5-large"
SD3_LARGE_TURBO_MODEL = "stabilityai/stable-diffusion-3.5-large-turbo"
DEFAULT_SD3_MODEL = SD3_MEDIUM_MODEL


def _resolve_sd_default_model() -> str:
    """Resolve the default SD-class image model, honoring AETHER_SD_MODEL.

    Accepts:
      'sdxl' (DEFAULT, ~7GB, non-gated, clearly better than v1.5)
      'v1.5' (~4GB, legacy / weakest)
      any other string -> treated as an explicit HF repo id or local path
    """
    env_val = os.environ.get("AETHER_SD_MODEL", "").strip()
    if not env_val:
        return DEFAULT_SDXL_MODEL
    low = env_val.lower()
    if low in ("sdxl", "xl"):
        return DEFAULT_SDXL_MODEL
    if low in ("v1.5", "sd15", "sd1.5", "v15", "1.5"):
        return DEFAULT_SD_MODEL
    return env_val


def _is_sdxl_model(model_id: str) -> bool:
    """Best-effort detection of whether a model_id refers to an SDXL-class model."""
    return "xl" in (model_id or "").lower()


def _resolve_sd3_default_model() -> str:
    """Resolve the default SD3 model, honoring AETHER_SD3_MODEL env override.

    Accepts:
      'medium' (DEFAULT, non-gated, ~10GB, MMDiT) -> stabilityai/stable-diffusion-3.5-medium
      'large' (~16GB, higher quality) -> stabilityai/stable-diffusion-3.5-large
      'turbo' (~16GB, 4-step fast) -> stabilityai/stable-diffusion-3.5-large-turbo
      any other string -> treated as an explicit HF repo id or local path
    NOTE: SD3.5 系列均为 Community License，可直接下载、无需授权 token。
    48GB 显存可流畅运行 SD3.5-Medium；磁盘不足时自动跳过（SDXL / SD v1.5 仍可用）。
    """
    env_val = os.environ.get("AETHER_SD3_MODEL", "").strip()
    if not env_val:
        # Also check legacy AETHER_FLUX_MODEL for backward compatibility
        legacy = os.environ.get("AETHER_FLUX_MODEL", "").strip()
        if legacy:
            low = legacy.lower()
            if low in ("medium", "sd3-medium", "sd3.5-medium"):
                return SD3_MEDIUM_MODEL
            if low in ("large", "sd3-large", "sd3.5-large"):
                return SD3_LARGE_MODEL
            if low in ("turbo", "sd3-turbo", "sd3.5-large-turbo"):
                return SD3_LARGE_TURBO_MODEL
        return DEFAULT_SD3_MODEL
    low = env_val.lower()
    if low in ("medium", "sd3-medium", "sd3.5-medium"):
        return SD3_MEDIUM_MODEL
    if low in ("large", "sd3-large", "sd3.5-large"):
        return SD3_LARGE_MODEL
    if low in ("turbo", "sd3-turbo", "sd3.5-large-turbo"):
        return SD3_LARGE_TURBO_MODEL
    return env_val

_LOCAL_MODELS_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")
LOCAL_SD3_MODEL_DIR = os.path.join(_LOCAL_MODELS_ROOT, "stable-diffusion-3.5-medium")   # 默认 SD3.5-Medium
LOCAL_SD3_LARGE_DIR = os.path.join(_LOCAL_MODELS_ROOT, "stable-diffusion-3.5-large")    # 可选 Large
LOCAL_SD3_TURBO_DIR = os.path.join(_LOCAL_MODELS_ROOT, "stable-diffusion-3.5-large-turbo")  # 可选 Turbo
LOCAL_LEGACY_T2V_DIR = os.path.join(_LOCAL_MODELS_ROOT, "text-to-video-ms-1.7b")
LOCAL_SD_DIR = os.path.join(_LOCAL_MODELS_ROOT, "stable-diffusion-v1-5")
LOCAL_SDXL_DIR = os.path.join(_LOCAL_MODELS_ROOT, "stable-diffusion-xl-base-1.0")

# LTX-Video Text-to-Video pipeline — primary T2V backend (fast + long-text + ROCm)
# Lightricks/LTX-Video, Apache-2.0, non-gated. Uses T5-XXL text encoder (512 tokens).
# Approximately 15GB (2B transformer + VAE + T5-XXL fp16), fits 48GB VRAM / 100GB disk.
DEFAULT_LTX_T2V_MODEL = "Lightricks/LTX-Video"
LOCAL_LTX_T2V_DIR = os.path.join(_LOCAL_MODELS_ROOT, "LTX-Video")
# 实测 LTX-Video diffusers 权重：transformer ~10GB + VAE ~1.7GB + T5-XXL text_encoder ~19GB
# 合计约 31GB；门控按 32GB + 4GB 余量 = 36GB 估算，避免下载中途磁盘满导致权重损坏。
LTX_VIDEO_SIZE_GB = 32.0

# Wan2.2-TI2V-5B Text-to-Video pipeline — primary T2V backend (native Chinese, 720P@24fps)
# Wan-AI/Wan2.2-TI2V-5B-Diffusers, Apache-2.0, non-gated. Uses umt5-xxl text encoder
# (multilingual incl. Chinese) so Chinese prompts work natively — no translation layer.
# ~34GB (5B transformer + VAE + umt5-xxl). Fits 48GB VRAM with room to spare.
DEFAULT_WAN_T2V_MODEL = "Wan-AI/Wan2.2-TI2V-5B-Diffusers"
LOCAL_WAN_T2V_DIR = os.path.join(_LOCAL_MODELS_ROOT, "Wan2.2-TI2V-5B")
# 实测 Wan2.2-TI2V-5B diffusers 权重约 34GB；门控按 1.5× + 4GB 余量 = 55GB 估算。
WAN22_TI2V_5B_SIZE_GB = 34.0
# diffusers 组件白名单（与 LTX 同构：transformer/vae/text_encoder/scheduler/tokenizer）。
_WAN_ALLOW_PATTERNS = [
    "model_index.json",
    "scheduler/*",
    "tokenizer/*",
    "text_encoder/*",
    "vae/*",
    "transformer/*",
]

# diffusers 组件白名单：只下载 model_index.json 引用的子目录，
# 排除根目录下 13B/旧版 2B 单文件 checkpoint（合计 100GB+）。
_LTX_ALLOW_PATTERNS = [
    "model_index.json",
    "scheduler/*",
    "tokenizer/*",
    "text_encoder/*",
    "vae/*",
    "transformer/*",
]

# 加载前校验这些关键文件存在且非空（避免 disk-full 中断后残留半成品）。
_LTX_REQUIRED_COMPONENTS = [
    ("transformer", ["config.json", "diffusion_pytorch_model-00001-of-00002.safetensors"]),
    ("vae", ["config.json", "diffusion_pytorch_model.safetensors"]),
    ("text_encoder", ["config.json", "model-00001-of-00004.safetensors", "model.safetensors.index.json"]),
    ("tokenizer", ["tokenizer_config.json"]),
    ("scheduler", ["scheduler_config.json"]),
]

# Chinese -> English translation for LTX-Video (T5-XXL is English-centric).
# Uses Helsinki-NLP/opus-mt-zh-en (~400MB) via transformers pipeline.
_ZH_EN_TRANSLATOR_MODEL = "Helsinki-NLP/opus-mt-zh-en"
_zh_en_translator: Optional[Any] = None
_zh_en_translator_error: Optional[str] = None


def _contains_chinese(text: str) -> bool:
    """Return True if text contains any CJK character."""
    for ch in text:
        if "\u4e00" <= ch <= "\u9fff":
            return True
    return False


def _get_zh_en_translator() -> Optional[Any]:
    """Lazy-load Chinese->English translator. Returns None on failure.

    Loads in fp32 (never fp16): on ROCm, MarianMT in fp16 is prone to
    load-time crashes, which would silently disable Chinese translation.
    Tries GPU(fp32) first, then falls back to CPU(fp32) — CPU is bulletproof
    and fast enough for short prompts. The failure is cached so we don't
    retry an unrecoverable download error every call.
    """
    global _zh_en_translator, _zh_en_translator_error
    if _zh_en_translator is not None:
        return _zh_en_translator
    if _zh_en_translator_error is not None:
        return None
    # 允许通过环境变量彻底关闭翻译（用于调试 / 弱网环境）。
    if os.environ.get("AETHER_T2V_NO_TRANSLATE", "").strip().lower() in ("1", "true", "yes", "on"):
        _zh_en_translator_error = "disabled via AETHER_T2V_NO_TRANSLATE"
        print("  [LTX-Video] 翻译已按 AETHER_T2V_NO_TRANSLATE 关闭；将直接使用原始 prompt。")
        return None
    try:
        from transformers import pipeline  # type: ignore

        print(f"  [LTX-Video] 正在加载中文->英文翻译模型：{_ZH_EN_TRANSLATOR_MODEL}（约 400MB，首次需下载）...")
        # 关键：统一 fp32。先试 GPU(fp32)，崩了就回退 CPU(fp32)。
        try:
            _zh_en_translator = pipeline(
                "translation",
                model=_ZH_EN_TRANSLATOR_MODEL,
                tokenizer=_ZH_EN_TRANSLATOR_MODEL,
                torch_dtype=torch.float32,
                device=0 if torch.cuda.is_available() else -1,
            )
        except Exception as _gpu_err:
            print(f"  [LTX-Video] GPU 加载翻译模型失败（{type(_gpu_err).__name__}），改走 CPU...")
            _zh_en_translator = pipeline(
                "translation",
                model=_ZH_EN_TRANSLATOR_MODEL,
                tokenizer=_ZH_EN_TRANSLATOR_MODEL,
                torch_dtype=torch.float32,
                device=-1,
            )
        print("  [LTX-Video] 翻译模型加载完成。")
        return _zh_en_translator
    except Exception as e:
        _zh_en_translator_error = f"{type(e).__name__}: {e}"
        print(f"  [LTX-Video] 翻译模型加载失败：{_zh_en_translator_error}")
        print("  [LTX-Video] 将原样使用 prompt；建议直接用英文输入以获得最佳效果。")
        return None


def _translate_zh_to_en(text: str) -> str:
    """Translate Chinese prompt to English for T5-XXL.

    Falls back to original text if translator unavailable or translation fails.
    Long prompts are split by sentences to stay within the model's max length.
    """
    if not _contains_chinese(text):
        return text
    translator = _get_zh_en_translator()
    if translator is None:
        return text
    try:
        # Split by common Chinese sentence delimiters to keep chunks short.
        import re

        chunks = [c.strip() for c in re.split(r"[。！？\n]", text) if c.strip()]
        if not chunks:
            chunks = [text]
        translated: list[str] = []
        for chunk in chunks:
            out = translator(chunk, max_length=512, truncation=True)
            if out and isinstance(out, list) and "translation_text" in out[0]:
                translated.append(out[0]["translation_text"].strip())
            else:
                translated.append(chunk)
        return " ".join(translated)
    except Exception as e:
        print(f"  [LTX-Video] 翻译失败：{e}；将原样使用中文 prompt。")
        return text


def _ltx_weights_look_complete(local_dir: str) -> bool:
    """Check that LTX-Video local cache has the key diffusers files.

    Does NOT validate checksums — only presence and non-zero size — which is
    enough to catch the common "disk full during download" case.
    """
    if not os.path.isdir(local_dir):
        return False
    for subdir, files in _LTX_REQUIRED_COMPONENTS:
        d = os.path.join(local_dir, subdir)
        if not os.path.isdir(d):
            return False
        for f in files:
            p = os.path.join(d, f)
            if not os.path.isfile(p) or os.path.getsize(p) == 0:
                return False
    return True


def _purge_ltx_cache(local_dir: str) -> None:
    """Remove a possibly-corrupt LTX-Video local cache."""
    if local_dir and os.path.isdir(local_dir):
        try:
            shutil.rmtree(local_dir, ignore_errors=True)
            print(f"  [LTX-Video] 已清理可能损坏的本地缓存：{local_dir}")
        except Exception as _e:
            print(f"  [LTX-Video] 清理缓存失败（可手动删除）: {_e}")


def _wan_weights_look_complete(local_dir: str) -> bool:
    """Check that Wan2.2-TI2V-5B local cache has the key diffusers files."""
    if not os.path.isdir(local_dir):
        return False
    if not os.path.isfile(os.path.join(local_dir, "model_index.json")):
        return False
    for sub in ("transformer", "vae", "text_encoder", "tokenizer", "scheduler"):
        d = os.path.join(local_dir, sub)
        if not os.path.isdir(d):
            return False
        if sub in ("transformer", "vae", "text_encoder"):
            try:
                if not any(fn.endswith(".safetensors") for fn in os.listdir(d)):
                    return False
            except Exception:
                return False
    return True


# (Legacy damo-vilab/text-to-video-ms-1.7b kept as fallback — see DEFAULT_T2V_MODEL)

# Approx download sizes (GB) — used to honor the "best model that fits the
# current disk quota" rule so we never kick off a download that will fail with
# ENOSPC / quota-exceeded halfway through.
SD3_MEDIUM_SIZE_GB = 10.0
SD3_LARGE_SIZE_GB = 16.0
SD3_TURBO_SIZE_GB = 16.0
SDXL_SIZE_GB = 7.0
SD15_SIZE_GB = 5.0
# 注：snapshot_download 下载期间会先在 HF 缓存写一份、再复制到本地目录，
# 因此下载峰值占用约为模型体积的 2 倍；下面的门控统一用 2× 体积 + 余量来判断，
# 避免出现「空间只够放一份、却触发一次 2 倍峰值下载 → 配额满中断」的死循环。
# (Removed WAN size constants — LTX-Video replaces the entire Wan series)
LEGACY_T2V_SIZE_GB = 6.0


def _resolve_t2v_default_model() -> str:
    """Resolve the default text-to-video model.

    Uses Wan2.2-TI2V-5B (Wan-AI/Wan2.2-TI2V-5B-Diffusers) by default — native Chinese, 720P@24fps, Apache-2.0.
    AETHER_T2V_MODEL env var can override with an explicit HF repo id or local path.
    """
    env_val = os.environ.get("AETHER_T2V_MODEL", "").strip()
    if env_val:
        return env_val
    return DEFAULT_WAN_T2V_MODEL



SD3_RECOMMENDED_WIDTH = 1024
SD3_RECOMMENDED_HEIGHT = 1024
SD3_MIN_WIDTH = 512
SD3_MIN_HEIGHT = 512


_HF_REPO_TO_LOCAL_DIR = {
    SD3_MEDIUM_MODEL: LOCAL_SD3_MODEL_DIR,        # SD3.5-Medium（默认）
    SD3_LARGE_MODEL: LOCAL_SD3_LARGE_DIR,        # SD3.5-Large（可选）
    SD3_LARGE_TURBO_MODEL: LOCAL_SD3_TURBO_DIR,  # SD3.5-Large-Turbo（可选）
    DEFAULT_T2V_MODEL: LOCAL_LEGACY_T2V_DIR,
    DEFAULT_LTX_T2V_MODEL: LOCAL_LTX_T2V_DIR,
    DEFAULT_WAN_T2V_MODEL: LOCAL_WAN_T2V_DIR,
    DEFAULT_SD_MODEL: LOCAL_SD_DIR,
    DEFAULT_SDXL_MODEL: LOCAL_SDXL_DIR,
}


def _resolve_local_cache_dir(model_id: str) -> Optional[str]:
    """Given a HF Repo ID, return the preferred local cache directory; or None if not mapped."""
    if not model_id:
        return None
    if model_id in _HF_REPO_TO_LOCAL_DIR:
        return _HF_REPO_TO_LOCAL_DIR[model_id]
    stripped = model_id.strip()
    if stripped in _HF_REPO_TO_LOCAL_DIR:
        return _HF_REPO_TO_LOCAL_DIR[stripped]
    return None


def _looks_like_huggingface_repo(model_id: str) -> bool:
    """Best-effort heuristic: returns True if model_id looks like a HuggingFace Repo ID
    (org/model or org/model@rev) and NOT an absolute/local filesystem path."""
    if not model_id:
        return False
    s = model_id.strip()
    if os.path.isdir(s):
        return False
    if os.path.isabs(s):
        return False
    if s.startswith("./") or s.startswith(".\\") or s.startswith(".."):
        return False
    if "/" not in s:
        return False
    head, _, _ = s.partition("/")
    if not head:
        return False
    if any(ch in head for ch in "\\: *?\"<>|"):
        return False
    return True


# Only fetch the real weights + small config/text files. Skip redundant
# format variants (fp16/fp32/flax/onnx/openvino/ckpt and SD v1.5/SDXL
# duplicate files) — some HF repos otherwise inflate to 2-3x their true
# size (e.g. SD v1.5 blows up to ~10GB instead of ~4.5GB).
MODEL_IGNORE_PATTERNS = [
    "*.ckpt",
    "*fp16*",
    "*flax*",
    "*onnx*",
    "*openvino*",
    "model.safetensors",            # root duplicate of the sharded weights (SD v1.5)
    "pytorch_model.bin",
    "pytorch_model.fp16.bin",
    "sd_xl_base_1.0_0.9vae*",       # SDXL VAE variant we don't need
    "v1-5-pruned*",                 # SD v1.5 pruned duplicates
]

# 视频模型（damo-vilab / LTX-Video）下载时排除冗余格式。
# - *.bin  : diffusers from_pretrained 优先加载 .safetensors，.bin 是纯冗余。
#            damo-vilab/text-to-video-ms-1.7b 同时含 fp32 bin(5.65G) + safetensors(5.65G)
#            + fp16 bin(2.82G)，排除 .bin 后仅保留 safetensors，节省约 11GB。
# - *.ckpt / *flax* / *onnx* / *openvino* : 同理去冗余。
T2V_IGNORE_PATTERNS = [
    "*.ckpt",
    "*.bin",
    "*flax*",
    "*onnx*",
    "*openvino*",
]


# ===========================================================================
# 统一策略：模型「加载失败」必须先清盘，再尝试下一个模型
# ---------------------------------------------------------------------------
# 背景：磁盘配额有限（测试机 ~75GB）。如果某个模型加载失败却把半成品/损坏的
# 权重留在盘上，后续每一个备选模型都会因为「没空间」而连锁失败，最终一个 Tab
# 都跑不起来。因此规则是：**只要加载失败，立刻删除该模型占用的全部磁盘**
# （models/ 本地目录 + HuggingFace hub 缓存副本），再去下载下一个备选模型。
#
# 两个例外（工程上必须保留，否则反而有害）：
#   1) OOM（显存不足）：权重文件本身是完整的，删了纯属浪费带宽，下次换更小
#      分辨率或更小模型即可直接复用。
#   2) 非引擎托管目录：用户通过 AETHER_*_MODEL=/abs/path 手工指定的外部权重
#      目录绝不删除，只跳过并提示——那是用户的资产，不是引擎的缓存。
# ===========================================================================

_OOM_HINTS = (
    "out of memory",
    "cuda oom",
    "hip out of memory",
    "not enough memory",
    "insufficient memory",
    "alloc failed",
)


def _err_is_oom(exc) -> bool:
    """判断异常是否为显存/内存不足（这类失败不该删权重）。"""
    try:
        msg = str(exc).lower()
    except Exception:
        return False
    return any(h in msg for h in _OOM_HINTS)


def _dir_size_gb(path: str) -> float:
    """统计目录占用（GB），用于报告清理释放了多少空间。"""
    total = 0
    try:
        for root, _dirs, files in os.walk(path):
            for name in files:
                fp = os.path.join(root, name)
                try:
                    if not os.path.islink(fp):
                        total += os.path.getsize(fp)
                except OSError:
                    continue
    except Exception:
        return 0.0
    return total / (1024 ** 3)


def _hf_hub_cache_root() -> str:
    return os.environ.get("HF_HUB_CACHE") or os.path.expanduser(
        "~/.cache/huggingface/hub"
    )


def _purge_failed_model(
    model_ref: str,
    model_label: str = "model",
    exc: Optional[BaseException] = None,
    force: bool = False,
    extra_dirs: Optional[list] = None,
) -> float:
    """模型加载失败后清盘：删除其本地目录与 HF hub 缓存副本，返回释放的 GB 数。

    - model_ref:  HF Repo ID 或已解析出的本地目录路径，两者都能处理
    - exc:        导致失败的异常；若判定为 OOM 则跳过删除（除非 force=True）
    - force:      True 时无视 OOM 判定，强制删除
    - extra_dirs: 额外要一并清理的目录（如调用方自定义的 force_local_dir）
    """
    if exc is not None and not force and _err_is_oom(exc):
        print(
            f"  [{model_label}] 本次失败属于显存/内存不足(OOM)，权重文件完好，"
            f"保留不删除（换更小分辨率或更小模型即可直接复用）。"
        )
        return 0.0

    ref = (model_ref or "").strip()
    candidates = [d for d in (extra_dirs or []) if d]
    if not ref and not candidates:
        return 0.0

    if ref:
        if os.path.isdir(ref):
            candidates.append(ref)
        mapped = _resolve_local_cache_dir(ref)
        if mapped:
            candidates.append(mapped)
        if _looks_like_huggingface_repo(ref):
            bare = ref.split("@", 1)[0]
            # _ensure_model_local_dir 未命中映射表时的两种 slug 规则都要覆盖
            candidates.append(
                os.path.join(_LOCAL_MODELS_ROOT, bare.replace("/", "__").replace("\\", "__"))
            )
            candidates.append(os.path.join(_LOCAL_MODELS_ROOT, bare.replace("/", "--")))
            candidates.append(
                os.path.join(_hf_hub_cache_root(), "models--" + bare.replace("/", "--"))
            )

    try:
        models_root = os.path.abspath(_LOCAL_MODELS_ROOT)
    except Exception:
        models_root = _LOCAL_MODELS_ROOT
    try:
        hub_root = os.path.abspath(_hf_hub_cache_root())
    except Exception:
        hub_root = _hf_hub_cache_root()

    freed = 0.0
    seen = set()
    for cand in candidates:
        if not cand:
            continue
        try:
            abs_path = os.path.abspath(cand)
        except Exception:
            continue
        if abs_path in seen:
            continue
        seen.add(abs_path)
        if not os.path.isdir(abs_path):
            continue
        # 安全护栏：仅清理引擎托管的两个根目录之下的内容，且不允许删除根目录本身
        managed = abs_path.startswith(models_root + os.sep) or abs_path.startswith(
            hub_root + os.sep
        )
        if not managed:
            print(
                f"  [{model_label}] 跳过清理（非引擎托管目录，疑为你手工放置的权重）: {abs_path}"
            )
            continue
        size = _dir_size_gb(abs_path)
        shutil.rmtree(abs_path, ignore_errors=True)
        if os.path.isdir(abs_path):
            print(f"  [{model_label}] 清理未完全成功（可能有文件被占用）: {abs_path}")
            continue
        freed += size
        print(f"  [{model_label}] 已删除失败模型: {abs_path}（释放约 {size:.1f}GB）")

    if freed > 0:
        print(
            f"  [{model_label}] 清盘完成，共释放约 {freed:.1f}GB；"
            f"当前剩余 {_free_disk_gb(_LOCAL_MODELS_ROOT):.1f}GB，继续尝试下一个模型。"
        )
    else:
        print(
            f"  [{model_label}] 未找到可清理的本地权重（尚未落盘或已被清理）；"
            f"当前剩余 {_free_disk_gb(_LOCAL_MODELS_ROOT):.1f}GB。"
        )
    return freed


def _ensure_model_local_dir(
    model_id: str,
    model_label: str = "model",
    marker_file: str = "model_index.json",
    force_local_dir: Optional[str] = None,
    ignore_patterns: Optional[list] = None,
) -> str:
    """Unified helper: if `model_id` looks like a HuggingFace Repo ID, snapshot-download
    it into a local cache directory and return the local path. If it's already a local
    directory, validate marker_file and return it as-is.

    - model_label: short name used only for logging (e.g. "SD3.5", "LTX-Video")
    - marker_file: required sentinel file inside the directory (diffusers format uses model_index.json,
      some legacy checkpoints only have model.safetensors/index.html; callers can loosen it)
    - force_local_dir: if provided, always prefer this local directory when downloading a HF Repo ID.
    """
    import os as _os

    if not model_id:
        raise ValueError("model_id 不能为空")

    is_local_dir = _os.path.isdir(model_id)

    if is_local_dir:
        if marker_file:
            marker_path = _os.path.join(model_id, marker_file)
            if not _os.path.isfile(marker_path):
                alt_markers = (
                    "model.safetensors",
                    "pytorch_model.bin",
                    "config.json",
                )
                found_alt = any(
                    _os.path.isfile(_os.path.join(model_id, m)) for m in alt_markers
                )
                if not found_alt:
                    raise FileNotFoundError(
                        f"本地模型目录 {model_id} 下找不到 {marker_file}，"
                        f"请确认是完整的 diffusers / transformers 格式模型目录。"
                    )
        print(f"[{model_label}] 使用本地模型目录: {model_id}")
        return model_id

    looks_like_hf = _looks_like_huggingface_repo(model_id)
    if not looks_like_hf:
        return model_id

    preferred_local = force_local_dir or _resolve_local_cache_dir(model_id)
    if preferred_local is None:
        slug = model_id.strip().replace("/", "__").replace("\\", "__")
        preferred_local = _os.path.join(_LOCAL_MODELS_ROOT, slug)

    os.makedirs(preferred_local, exist_ok=True)
    marker_path = (
        _os.path.join(preferred_local, marker_file) if marker_file else None
    )

    if marker_path and _os.path.isfile(marker_path):
        print(f"[{model_label}] 本地已缓存 {preferred_local}，直接加载（跳过下载）")
        return preferred_local
    if not marker_file:
        if any(
            _os.path.isfile(_os.path.join(preferred_local, m))
            for m in ("model_index.json", "config.json", "model.safetensors", "pytorch_model.bin")
        ):
            print(f"[{model_label}] 本地已缓存 {preferred_local}，直接加载（跳过下载）")
            return preferred_local

    print(f"[{model_label}] 检测到 HF Repo ID: {model_id}")
    print(f"[{model_label}] 即将下载权重到本地目录: {preferred_local}")
    print(f"[{model_label}] 首次下载取决于网络带宽，请耐心等待...")
    try:
        from huggingface_hub import snapshot_download
        snapshot_download(
            repo_id=model_id.strip().split("@", 1)[0],
            revision=None if "@" not in model_id.strip() else model_id.strip().split("@", 1)[1],
            local_dir=preferred_local,
            local_dir_use_symlinks=False,
            ignore_patterns=ignore_patterns if ignore_patterns is not None else MODEL_IGNORE_PATTERNS,
        )
    except ImportError:
        print(f"[{model_label}] huggingface_hub.snapshot_download 不可用，回退到 diffusers 在线缓存模式")
        return model_id
    except Exception as _e:
        _emsg = str(_e).lower()
        _is_gated = (
            "403" in _emsg
            or "gated" in _emsg
            or "restricted" in _emsg
            or "authorized" in _emsg
            or "not in the authorized" in _emsg
        )
        if _is_gated:
            print(
                f"[{model_label}] 下载被拒绝（模型需授权 / gated）：{_e}\n"
                f"[{model_label}] 解决途径：\n"
                f"[{model_label}]   (1) 去 https://huggingface.co/{model_id} 申请访问，"
                f"再 `huggingface-cli login` 用已授权账号的 token；\n"
                f"[{model_label}]   (2) 或改用非 gated 模型（仅 SD3）："
                f"`export AETHER_SD3_MODEL=stabilityai/stable-diffusion-3.5-medium` 后重启；\n"
                f"[{model_label}]   (3) 或把已授权的权重放到本地目录，用 "
                f"`export AETHER_SD3_MODEL=/abs/path/to/sd3-model` 指向它。"
            )
        else:
            print(
                f"[{model_label}] snapshot_download 失败（{_e}）；"
                f"不回退到 diffusers 在线缓存模式（避免同一模型被下载两遍），"
                f"将由调用方切换到下一个可用模型。"
            )
        # 清理本次下载产生的半成品目录 + HF hub 缓存副本，回收被占用的磁盘配额，
        # 然后向上抛出，交由各调用方（SD3 / SD / Legacy T2V）回退到备选模型，
        # 而不是用 from_pretrained(repo_id) 把同一份权重再下到 HF 缓存造成双份占用。
        try:
            _purge_failed_model(
                model_id,
                model_label=model_label,
                force=True,
                extra_dirs=[preferred_local],
            )
        except Exception:
            pass
        raise

    post_download_ok = True
    if marker_path and not _os.path.isfile(marker_path):
        alt_markers = (
            "model.safetensors",
            "pytorch_model.bin",
            "config.json",
        )
        if not any(
            _os.path.isfile(_os.path.join(preferred_local, m)) for m in alt_markers
        ):
            post_download_ok = False
    if not post_download_ok:
        # 下完了却没有 marker（典型：仓库不是 diffusers 格式，或下载被截断）。
        # 这份权重永远加载不了，必须立刻删掉，否则会白占十几 GB 拖垮后续备选模型。
        try:
            _purge_failed_model(
                model_id,
                model_label=model_label,
                force=True,
                extra_dirs=[preferred_local],
            )
        except Exception:
            pass
        raise RuntimeError(
            f"下载完成但 {preferred_local} 下找不到 {marker_file}（已删除该无效模型，"
            f"磁盘已回收）；将切换到下一个备选模型。"
        )

    print(f"[{model_label}] 下载完成，从本地目录加载: {preferred_local}")

    # 回收 HuggingFace hub 缓存中的副本：snapshot_download 已经把权重完整复制到
    # local_dir（preferred_local），hub 缓存里那份是冗余的。删除它可回收约一倍空间，
    # 这是之前磁盘被占满（全格式变体 + 双份缓存）的另一半根因。删除后不影响使用，
    # 因为后续 from_pretrained 直接读 local_dir，且再次启动会因 marker 命中而跳过下载。
    try:
        _hf_cache = os.environ.get("HF_HUB_CACHE") or os.path.expanduser(
            "~/.cache/huggingface/hub"
        )
        _repo_slug = "models--" + model_id.strip().split("@", 1)[0].replace("/", "--")
        _repo_cache = os.path.join(_hf_cache, _repo_slug)
        if os.path.isdir(_repo_cache):
            shutil.rmtree(_repo_cache, ignore_errors=True)
            print(f"[{model_label}] 已回收 HF hub 缓存副本，释放约一倍磁盘空间")
    except Exception:
        pass

    return preferred_local


class ROCmAIGCEngine:
    def __init__(
        self,
        model_id: str = DEFAULT_SD_MODEL,
        sd3_model_id: Optional[str] = None,
        enable_sd3: bool = True,
        t2v_model_id: Optional[str] = None,
        enable_t2v: bool = True,
    ):
        # ---- Env toggles: let operators skip heavy/gated models entirely ----
        _sd3_env = os.environ.get("AETHER_ENABLE_SD3", "").strip().lower()
        # Also check legacy AETHER_ENABLE_FLUX for backward compatibility
        if not _sd3_env:
            _sd3_env = os.environ.get("AETHER_ENABLE_FLUX", "").strip().lower()
        _t2v_env = os.environ.get("AETHER_ENABLE_T2V", "").strip().lower()
        # Also check legacy AETHER_ENABLE_WAN for backward compatibility
        if not _t2v_env:
            _t2v_env = os.environ.get("AETHER_ENABLE_WAN", "").strip().lower()
        _off_tokens = ("0", "false", "no", "off")
        if _sd3_env in _off_tokens:
            enable_sd3 = False
        if _t2v_env in _off_tokens:
            enable_t2v = False

        print("Initializing AMD ROCm accelerated inference engine...")
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"Using device: {self.device}")
        self.model_id = _resolve_sd_default_model()
        self.sd3_model_id = sd3_model_id or _resolve_sd3_default_model()
        if t2v_model_id:
            resolved_t2v_id = t2v_model_id
        else:
            resolved_t2v_id = _resolve_t2v_default_model()
        self.t2v_model_id = resolved_t2v_id
        self.ltx_t2v_model_id = DEFAULT_LTX_T2V_MODEL
        # 主模型 = Wan2.2-TI2V-5B（若可导入），LTX-Video 作为自动回退；两者任一可用即视为 T2V 可用。
        self._t2v_available = enable_t2v and (
            (_WAN_T2V_AVAILABLE and bool(resolved_t2v_id))
            or (_LTX_VIDEO_AVAILABLE and bool(self.ltx_t2v_model_id))
        )

        dtype = torch.float16 if self.device == "cuda" else torch.float32

        # ---- SD-class image model (default image generator) ----
        # AETHER_SD_MODEL selects which SD-class model powers Img2Img + Txt2Img:
        #   'sdxl' (DEFAULT, ~7GB, non-gated, clearly better than v1.5)
        #   'v1.5' (~4GB, legacy / weakest)
        #   any other string -> explicit HF repo id or local path
        # Falls back to SD v1.5 automatically if the chosen model can't load,
        # so image generation never fully breaks (matches the "don't fail" goal).
        sd_model_id = _resolve_sd_default_model()
        self._sd_model_id = sd_model_id
        # SDXL is only usable if its pipeline class actually imported (a numpy
        # ABI mismatch, e.g. "numpy.dtype size changed", leaves it as None).
        is_sdxl = _is_sdxl_model(sd_model_id) and _SDXL_AVAILABLE
        if is_sdxl:
            img2img_cls = StableDiffusionXLImg2ImgPipeline
            t2i_cls = StableDiffusionXLPipeline
            native_size = 1024
        else:
            # SDXL import failed or not requested -> degrade to SD v1.5 and
            # DON'T download SDXL (avoids wasting ~7GB on an unusable model).
            if _is_sdxl_model(sd_model_id):
                print(
                    "  NOTE: SDXL pipeline 未能导入（常见原因：numpy 二进制不兼容，"
                    "见 'numpy.dtype size changed'）。自动改用 SD v1.5，避免无谓下载 SDXL。"
                )
                sd_model_id = DEFAULT_SD_MODEL
                self._sd_model_id = sd_model_id
            img2img_cls = StableDiffusionImg2ImgPipeline
            t2i_cls = StableDiffusionPipeline
            native_size = 512

        print(f"Loading SD-class image model: {sd_model_id} (SDXL={is_sdxl}) ...")
        if os.path.isdir(sd_model_id):
            sd_load_path = sd_model_id
        elif _looks_like_huggingface_repo(sd_model_id):
            force_local = _resolve_local_cache_dir(sd_model_id)
            try:
                sd_load_path = _ensure_model_local_dir(
                    sd_model_id,
                    model_label="SD image",
                    marker_file="model_index.json",
                    force_local_dir=force_local,
                )
            except Exception as _e:
                print(f"  SD 模型下载/校验失败：{_e}；将尝试回退 SD v1.5")
                sd_load_path = None
        else:
            sd_load_path = sd_model_id  # let from_pretrained attempt it

        self._sd_is_sdxl = is_sdxl
        self._sd_native_size = native_size
        self._sd_load_path = sd_load_path
        self._sd_t2i_cls = t2i_cls
        self._sd_img2img_cls = img2img_cls

        try:
            if sd_load_path is None:
                raise ValueError("no resolvable SD model path")
            self.pipeline = img2img_cls.from_pretrained(
                sd_load_path,
                torch_dtype=dtype,
                safety_checker=None,
            ).to(self.device)
        except Exception as _e:
            # Graceful fallback to SD v1.5 so image gen still works
            print(f"  WARNING: 加载 {sd_model_id} 失败（{_e}）；先删除该模型再回退到 SD v1.5")
            # 规则：加载失败 → 先清盘 → 再下载下一个模型，避免坏权重占着配额
            _purge_failed_model(
                sd_model_id,
                model_label="SD image",
                exc=_e,
                extra_dirs=[sd_load_path],
            )
            fb_path = _ensure_model_local_dir(
                DEFAULT_SD_MODEL,
                model_label="SD v1.5",
                marker_file="model_index.json",
                force_local_dir=LOCAL_SD_DIR,
            )
            self.pipeline = StableDiffusionImg2ImgPipeline.from_pretrained(
                fb_path,
                torch_dtype=dtype,
                safety_checker=None,
            ).to(self.device)
            self._sd_is_sdxl = False
            self._sd_native_size = 512
            self._sd_load_path = fb_path
            self._sd_t2i_cls = StableDiffusionPipeline
            self._sd_img2img_cls = StableDiffusionImg2ImgPipeline

        try:
            self.pipeline.enable_attention_slicing()
            print("SD: Attention slicing optimization enabled")
        except Exception as e:
            print(f"SD attention slicing hint: {e}")

        if self.device == "cuda":
            try:
                self.pipeline.enable_model_cpu_offload()
                print("SD: Model CPU offload enabled")
            except Exception as e:
                print(f"SD CPU offload hint: {e}")

        # ---- Reusable SD Txt2Img pipeline (cached, no more repeated load!) ----
        self._t2i_pipeline = None
        self._build_sd_t2i_pipeline(dtype)

        # ---- SD3 (Stable Diffusion 3) pipeline (for high-quality Txt2Img) ----
        self.sd3_pipeline: Optional[StableDiffusion3Pipeline] = None
        self.sd3_img2img_pipeline = None
        self._sd3_loaded = False
        if enable_sd3 and sd3_model_id:
            # Only attempt SD3 if it is already cached locally, or it's an
            # explicit local path, or there is enough free disk for the download.
            _local_sd3_dir = _HF_REPO_TO_LOCAL_DIR.get(
                self.sd3_model_id,
                os.path.join(_LOCAL_MODELS_ROOT, self.sd3_model_id.replace("/", "--")),
            )
            _sd3_cached = (
                os.path.isdir(_local_sd3_dir)
                and os.path.isfile(os.path.join(_local_sd3_dir, "model_index.json"))
            )
            _sd3_is_local = not _looks_like_huggingface_repo(self.sd3_model_id)
            _sd3_free = _free_disk_gb(_LOCAL_MODELS_ROOT)
            _sd3_size = SD3_LARGE_SIZE_GB if "large" in self.sd3_model_id.lower() else SD3_MEDIUM_SIZE_GB
            if _sd3_cached or _sd3_is_local or _sd3_free >= 2 * _sd3_size + 4:
                try:
                    self._load_sd3_pipeline(self.sd3_model_id, dtype)
                except Exception as e:
                    print(f"WARNING: Failed to load SD3 model: {e}")
                    _purge_failed_model(
                        self.sd3_model_id,
                        model_label="SD3",
                        exc=e,
                        extra_dirs=[_local_sd3_dir],
                    )
                    print("  -> SD3 Txt2Img 已禁用，文生图改用 SDXL / SD v1.5。")
                    self._sd3_loaded = False
            else:
                print(
                    f"  [auto] 磁盘剩余约 {_sd3_free:.1f}GB < SD3 所需 ~{_sd3_size:.0f}GB，"
                    f"自动跳过；文生图/图生图使用 SDXL（仍在配置允许范围内选最优）。"
                )
                self._sd3_loaded = False

        _sd3_label = (
            "SD3.5-Large-Turbo"
            if (self.sd3_model_id and "turbo" in self.sd3_model_id.lower())
            else (
                "SD3.5-Large"
                if (self.sd3_model_id and "large" in self.sd3_model_id.lower())
                else "SD3.5-Medium"
            )
        )
        self._image_model_label = (
            _sd3_label
            if (self._sd3_loaded and self.sd3_pipeline is not None)
            else ("SDXL" if self._sd_is_sdxl else "SD v1.5")
        )

        # ---- Wan2.2-TI2V-5B text-to-video pipeline (primary, lazy) ----
        self.wan_t2v_pipeline = None  # WanPipeline or None
        self._wan_t2v_loaded = False
        self._t2v_last_backend = None  # "wan" | "ltx" | "legacy" — 最近一次成功生成的引擎

        # ---- LTX-Video text-to-video pipeline (fallback, lazy) ----
        self.ltx_pipeline = None  # LTXPipeline or None
        self._ltx_loaded = False

        # ---- Legacy damo-vilab T2V pipeline (fallback via diffusers) ----
        # Lazily loaded by _ensure_video_pipeline() when LTX-Video is unavailable.
        self.video_pipeline = None
        self._video_model_id = None

    # ================================================================
    # SD Txt2Img cache
    # ================================================================
    def _build_sd_t2i_pipeline(self, dtype):
        print("Building cached SD Txt2Img pipeline ...")
        try:
            t2i_cls = self._sd_t2i_cls
            self._t2i_pipeline = t2i_cls.from_pretrained(
                self._sd_load_path,
                torch_dtype=dtype,
                safety_checker=None,
            ).to(self.device)
            try:
                self._t2i_pipeline.enable_attention_slicing()
            except Exception:
                pass
            if self.device == "cuda":
                try:
                    self._t2i_pipeline.enable_model_cpu_offload()
                    print("SD Txt2Img: CPU offload enabled")
                except Exception:
                    pass
            print("SD Txt2Img pipeline cached (reuse across calls)")
        except Exception as e:
            print(f"WARNING: Failed to build SD Txt2Img cache: {e}")
            self._t2i_pipeline = None

    # ================================================================
    # SD3 (Stable Diffusion 3) loader
    # ================================================================
    def _load_sd3_pipeline(self, model_id: str, dtype):
        print(f"Loading SD3 model: {model_id} ...")
        print("  NOTE: SD3.5-Medium is ~10GB, SD3.5-Large is ~16GB, first download may take several minutes.")

        # Map a HF repo id to its dedicated local dir
        force_local = _resolve_local_cache_dir(model_id) if not os.path.isdir(model_id) else model_id
        resolved_path = _ensure_model_local_dir(
            model_id,
            model_label="SD3",
            marker_file="model_index.json",
            force_local_dir=force_local,
        )
        self.sd3_model_id = resolved_path

        if self.device == "cuda":
            pipe = StableDiffusion3Pipeline.from_pretrained(
                resolved_path,
                torch_dtype=torch.bfloat16,
            ).to(self.device)
            try:
                pipe.enable_model_cpu_offload()
                print("SD3: Model CPU offload enabled (saves VRAM)")
            except Exception as e:
                print(f"SD3 CPU offload hint: {e}")
            try:
                pipe.enable_vae_slicing()
                print("SD3: VAE slicing enabled")
            except Exception:
                pass
        else:
            print("WARNING: CPU mode for SD3 is extremely slow, not recommended.")
            pipe = StableDiffusion3Pipeline.from_pretrained(
                resolved_path,
                torch_dtype=torch.float32,
            ).to(self.device)
        self.sd3_pipeline = pipe
        self._sd3_loaded = True
        print(f"SD3 pipeline ready. Use sd3_generate_text_to_image() for best quality.")

    # ================================================================
    # LTX-Video Text-to-Video pipeline loader (lazy on first generation)
    # ================================================================
    def _ensure_ltx_pipeline(self, model_id: Optional[str] = None) -> bool:
        """Ensure LTX-Video T2V pipeline is loaded. Returns True if usable."""
        target_id = model_id or self.ltx_t2v_model_id
        if not target_id:
            return False
        if not _LTX_VIDEO_AVAILABLE:
            print("  LTX-Video pipeline not importable (diffusers < 0.33 或未安装).")
            print("  Install/upgrade: pip install -U diffusers")
            if _LTX_IMPORT_ERROR:
                print(f"  导入错误详情：{_LTX_IMPORT_ERROR}")
            return False
        if self._ltx_loaded and self.ltx_pipeline is not None:
            return True

        print(f"Loading LTX-Video pipeline: {target_id} ...")
        print(
            "  NOTE: LTX-Video-2B + T5-XXL 约 31GB（transformer ~10GB + VAE ~1.7GB + T5-XXL ~19GB）。\n"
            "  仅下载 diffusers 组件，不会拉取仓库里 13B 巨型单文件变体（100GB+）。\n"
            "  首次下载可能需 10~30 分钟，请耐心等待；切勿在下载中途 kill 进程。"
        )
        self.ltx_t2v_model_id = target_id

        # 默认 LTX 模型固定缓存到 models/LTX-Video；自定义 HF repo id 用 slug 目录，避免冲突。
        # 如果 target_id 本身就是本地目录，则直接当缓存目录用。
        if os.path.isdir(target_id):
            local_dir = target_id
        elif target_id.strip().split("@", 1)[0] == DEFAULT_LTX_T2V_MODEL:
            local_dir = LOCAL_LTX_T2V_DIR
        else:
            slug = target_id.strip().replace("/", "__").replace("\\", "__")
            local_dir = os.path.join(_LOCAL_MODELS_ROOT, slug)

        # 如果检测到本地缓存不完整（常见于上次 disk-full 中断），先清理再下载。
        if os.path.isdir(local_dir) and not _ltx_weights_look_complete(local_dir):
            print("  [LTX-Video] 检测到本地缓存可能损坏，准备清理后重新下载...")
            _purge_ltx_cache(local_dir)

        try:
            # 使用 snapshot_download + allow_patterns 只拉 diffusers 组件。
            # 这样既能直接落到本地目录（便于校验），又不会拉 13B 单文件把盘撑爆。
            if not _ltx_weights_look_complete(local_dir):
                print(f"  [LTX-Video] 开始下载到 {local_dir} ...")
                from huggingface_hub import snapshot_download

                snapshot_download(
                    repo_id=target_id.strip().split("@", 1)[0],
                    revision=None if "@" not in target_id.strip() else target_id.strip().split("@", 1)[1],
                    local_dir=local_dir,
                    local_dir_use_symlinks=False,
                    allow_patterns=_LTX_ALLOW_PATTERNS,
                )
                if not _ltx_weights_look_complete(local_dir):
                    raise RuntimeError(
                        "下载完成后关键文件缺失或为空，可能是磁盘满或网络中断。"
                    )
                print("  [LTX-Video] 下载/校验完成，开始加载 pipeline...")
            else:
                print(f"  [LTX-Video] 本地缓存完整，直接加载：{local_dir}")

            # LTX-Video 官方推荐 bfloat16；fp16 会在内部 VAE/rope 等 float32 运算点报
            # "expected scalar type Float but found Half" 直接崩溃。ROCm RDNA3 (gfx1100)
            # 原生支持 bf16，故默认 bf16；小显存/旧卡可改用 AETHER_T2V_DTYPE=fp32。
            _dtype_env = os.environ.get("AETHER_T2V_DTYPE", "").strip().lower()
            if _dtype_env in ("fp32", "float32"):
                dtype = torch.float32
            elif _dtype_env in ("bf16", "bfloat16"):
                dtype = torch.bfloat16
            elif _dtype_env in ("fp16", "float16"):
                dtype = torch.float16
            else:
                dtype = torch.bfloat16 if self.device == "cuda" else torch.float32

            pipe = LTXPipeline.from_pretrained(
                local_dir,
                torch_dtype=dtype,
            )
            print(f"  [LTX-Video] 权重精度：{dtype} (可用 AETHER_T2V_DTYPE=fp32/fp16/bf16 覆盖)")

            # 48GB 显存放得下 ~31GB 模型参数，全程驻留 GPU 避免 CPU offload 逐步搬运拖慢推理。
            # 仅在小显存机器上启用 offload。
            try:
                _vram_gb = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
            except Exception:
                _vram_gb = 0.0
            if _vram_gb >= 48.0:
                pipe = pipe.to(self.device)
            elif _vram_gb >= 24.0:
                try:
                    pipe.enable_model_cpu_offload()
                except Exception:
                    pipe = pipe.to(self.device)
            else:
                try:
                    pipe.enable_sequential_cpu_offload()
                except Exception:
                    pipe.enable_model_cpu_offload()
            self.ltx_pipeline = pipe
            self._ltx_loaded = True
            print("LTX-Video pipeline ready.")
            return True
        except Exception as _load_e:
            print(
                f"  [LTX-Video] 加载失败：{_load_e}\n"
                f"  [LTX-Video] 常见原因 = 网络无法下载 / 磁盘配额满 / diffusers 版本过低。\n"
                f"  [LTX-Video] 可尝试：rm -rf {local_dir} ~/.cache/huggingface/hub/*LTX*"
            )
            self.ltx_pipeline = None
            self._ltx_loaded = False
            return False

    # ================================================================
    # Wan2.2-TI2V-5B Text-to-Video pipeline (primary, native Chinese)
    # ================================================================
    def _ensure_wan_t2v_pipeline(self, model_id: Optional[str] = None) -> bool:
        """Ensure Wan2.2-TI2V-5B T2V pipeline is loaded. Returns True if usable."""
        target_id = model_id or self.t2v_model_id
        if not target_id:
            return False
        if not _WAN_T2V_AVAILABLE:
            print("  Wan2.2-TI2V-5B pipeline not importable (diffusers < 0.33 或未安装).")
            print("  Install/upgrade: pip install -U diffusers")
            if _WAN_IMPORT_ERROR:
                print(f"  导入错误详情：{_WAN_IMPORT_ERROR}")
            return False
        if self._wan_t2v_loaded and self.wan_t2v_pipeline is not None:
            return True

        print(f"Loading Wan2.2-TI2V-5B pipeline: {target_id} ...")
        print(
            "  NOTE: Wan2.2-TI2V-5B 约 34GB（5B transformer + VAE + umt5-xxl）。\n"
            "  首次下载可能需 10~20 分钟，请耐心等待；切勿在下载中途 kill 进程。\n"
            "  中文提示词由 umt5-xxl 原生理解，无需翻译。"
        )

        if os.path.isdir(target_id):
            local_dir = target_id
        elif target_id.strip().split("@", 1)[0] == DEFAULT_WAN_T2V_MODEL:
            local_dir = LOCAL_WAN_T2V_DIR
        else:
            slug = target_id.strip().replace("/", "__").replace("\\", "__")
            local_dir = os.path.join(_LOCAL_MODELS_ROOT, slug)

        if os.path.isdir(local_dir) and not _wan_weights_look_complete(local_dir):
            print("  [Wan] 检测到本地缓存可能损坏，准备清理后重新下载...")
            try:
                shutil.rmtree(local_dir, ignore_errors=True)
            except Exception as _e:
                print(f"  [Wan] 清理缓存失败（可手动删除）: {_e}")

        try:
            if not _wan_weights_look_complete(local_dir):
                print(f"  [Wan] 开始下载到 {local_dir} ...")
                from huggingface_hub import snapshot_download

                snapshot_download(
                    repo_id=target_id.strip().split("@", 1)[0],
                    revision=None if "@" not in target_id.strip() else target_id.strip().split("@", 1)[1],
                    local_dir=local_dir,
                    local_dir_use_symlinks=False,
                    allow_patterns=_WAN_ALLOW_PATTERNS,
                )
                if not _wan_weights_look_complete(local_dir):
                    raise RuntimeError("下载完成后关键文件缺失或为空，可能是磁盘满或网络中断。")
                print("  [Wan] 下载/校验完成，开始加载 pipeline...")
            else:
                print(f"  [Wan] 本地缓存完整，直接加载：{local_dir}")

            _dtype_env = os.environ.get("AETHER_T2V_DTYPE", "").strip().lower()
            if _dtype_env in ("fp32", "float32"):
                dtype = torch.float32
            elif _dtype_env in ("fp16", "float16"):
                dtype = torch.float16
            elif _dtype_env in ("bf16", "bfloat16"):
                dtype = torch.bfloat16
            else:
                dtype = torch.bfloat16 if self.device == "cuda" else torch.float32

            pipe = WanPipeline.from_pretrained(local_dir, torch_dtype=dtype)
            print(f"  [Wan] 权重精度：{dtype} (可用 AETHER_T2V_DTYPE=fp32/fp16/bf16 覆盖)")

            try:
                _vram_gb = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
            except Exception:
                _vram_gb = 0.0
            if _vram_gb >= 24.0:
                pipe = pipe.to(self.device)
            else:
                try:
                    pipe.enable_model_cpu_offload()
                except Exception:
                    pipe = pipe.to(self.device)
            self.wan_t2v_pipeline = pipe
            self._wan_t2v_loaded = True
            print("Wan2.2-TI2V-5B pipeline ready.")
            return True
        except Exception as _load_e:
            print(
                f"  [Wan2.2-TI2V-5B] 加载失败：{_load_e}\n"
                f"  [Wan] 常见原因 = 网络无法下载 / 磁盘配额满 / diffusers 版本过低。\n"
                f"  [Wan] 可尝试：rm -rf {local_dir} ~/.cache/huggingface/hub/*Wan*"
            )
            self.wan_t2v_pipeline = None
            self._wan_t2v_loaded = False
            return False

    def _generate_wan_video(
        self,
        prompt: str,
        steps: int = 50,
        guidance_scale: float = 6.0,
        num_frames: int = 81,
        width: int = 832,
        height: int = 480,
        fps: int = 24,
        negative_prompt: str = "",
        output_path: Optional[str] = None,
        export_gif: bool = False,
        seed: Optional[int] = None,
    ) -> Tuple[str, Optional[str], int]:
        assert self.wan_t2v_pipeline is not None

        # Wan2.2-TI2V-5B 使用 umt5-xxl 文本编码器（多语言，含中文）——中文原生支持，无需翻译。
        _user_prompt = (prompt or "").strip()
        enhanced_prompt = _user_prompt or (
            "A glowing red robot walking through a futuristic city at sunset, "
            "cinematic shot, smooth camera motion, high quality"
        )
        if negative_prompt and str(negative_prompt).strip():
            _neg = str(negative_prompt).strip()
        else:
            _neg = (
                "blurry, low quality, distorted, ugly, watermark, pixelated, "
                "noisy, grainy, compression artifacts, color bleeding, oversaturated, "
                "smearing, motion blur, duplicated frames, flickering, deformed, "
                "floating objects, bad anatomy, bad motion, unnatural lighting"
            )

        # Wan 约束：宽高须被 16 整除；(num_frames-1) 须被 4 整除。
        _w = max(16, (width // 16) * 16)
        _h = max(16, (height // 16) * 16)
        _f = max(5, ((num_frames - 1) // 4) * 4 + 1)

        _prompt_preview = enhanced_prompt[:80].replace("\n", " ")
        print(
            f"Wan2.2-TI2V-5B generating | prompt='{_prompt_preview}...' | "
            f"prompt_len={len(enhanced_prompt)} | frames={_f} | {_w}x{_h} | "
            f"steps={steps} | guidance={guidance_scale} | fps={fps}"
        )

        generator = None
        if self.device == "cuda" and seed is not None:
            generator = torch.Generator(device=self.device).manual_seed(int(seed))

        with torch.inference_mode():
            result = self.wan_t2v_pipeline(
                prompt=enhanced_prompt,
                negative_prompt=_neg,
                height=_h,
                width=_w,
                num_frames=_f,
                num_inference_steps=int(steps),
                guidance_scale=float(guidance_scale),
                generator=generator,
                output_type="pil",
            )

        frames = self._wan_result_to_pil_frames(result)
        frame_count = len(frames)
        if frame_count == 0:
            raise RuntimeError("Wan2.2-TI2V-5B pipeline produced zero frames")

        if output_path is None:
            out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs")
            os.makedirs(out_dir, exist_ok=True)
            from datetime import datetime
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = os.path.join(out_dir, f"wan_t2v_{fps}fps_{ts}.mp4")

        os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)

        mp4_path = _safe_export_to_video(frames, output_path=output_path, fps=fps)
        gif_path = None
        if export_gif:
            gif_path = os.path.splitext(mp4_path)[0] + ".gif"
            try:
                _safe_export_to_gif(frames, gif_path, fps=fps)
            except Exception as e:
                print(f"GIF export skipped (non-fatal): {e}")
                gif_path = None

        if self.device == "cuda":
            torch.cuda.empty_cache()
        gc.collect()
        return mp4_path, gif_path, frame_count

    def _wan_result_to_pil_frames(self, result) -> list:
        """Normalize WanPipeline output to a flat list of PIL Images."""
        frames = getattr(result, "frames", None)
        if frames is None:
            frames = result
        if isinstance(frames, list):
            if frames and isinstance(frames[0], Image.Image):
                return frames
            if frames and isinstance(frames[0], list):
                return frames[0]
            return frames
        if isinstance(frames, torch.Tensor):
            # 形状: (1, c, f, h, w) 或 (f, c, h, w)，值域 [-1, 1]。
            t = frames[0] if frames.dim() == 5 else frames  # (c, f, h, w)
            out = []
            for i in range(t.shape[1]):
                frm = t[:, i, :, :]  # (c, h, w)
                if frm.is_floating_point():
                    frm = frm.clamp(-1, 1)
                    frm = (frm * 0.5 + 0.5).clamp(0, 1)
                    frm = (frm * 255).round().to(torch.uint8)
                out.append(Image.fromarray(frm.permute(1, 2, 0).cpu().numpy()))
            return out
        return _normalize_video_frames(frames)

    def reload_t2v(self, model_id: Optional[str] = None):
        """Unload + reload the primary T2V model (Wan2.2-TI2V-5B default, LTX-Video fallback)."""
        target = model_id or self.t2v_model_id
        # 卸载旧管线，释放显存
        for _pipe_attr, _loaded_attr in (
            ("wan_t2v_pipeline", "_wan_t2v_loaded"),
            ("ltx_pipeline", "_ltx_loaded"),
        ):
            if getattr(self, _pipe_attr, None) is not None:
                delattr(self, _pipe_attr)
                setattr(self, _pipe_attr, None)
                setattr(self, _loaded_attr, False)
        if self.device == "cuda":
            torch.cuda.empty_cache()
        gc.collect()
        # 决定后端：Wan 优先（含原生中文），否则 LTX
        if _WAN_T2V_AVAILABLE and (target is None or "wan" in str(target).lower() or target == DEFAULT_WAN_T2V_MODEL):
            _wan_id = target if (target and "wan" in str(target).lower()) else self.t2v_model_id
            self._ensure_wan_t2v_pipeline(_wan_id)
        elif _LTX_VIDEO_AVAILABLE:
            self._ensure_ltx_pipeline(target if target else self.ltx_t2v_model_id)

    # ================================================================
    # Img2Img (SD-class: SDXL default / SD v1.5 fallback, style transfer)
    # ================================================================
    def generate_cyberpunk_art(
        self,
        init_image: Image.Image,
        prompt: str,
        strength: float = 0.75,
        steps: int = 30,
        guidance_scale: float = 7.5,
        negative_prompt: str = "blurry, low quality, distorted, ugly, watermark",
    ) -> Image.Image:
        # Route to the best available image model for Img2Img too.
        if self._sd3_loaded and self.sd3_pipeline is not None:
            return self._sd3_img2img(init_image, prompt, strength, steps, guidance_scale)
        return self._sd_img2img(init_image, prompt, strength, steps, guidance_scale, negative_prompt)

    def _sd_img2img(
        self,
        init_image: Image.Image,
        prompt: str,
        strength: float,
        steps: int,
        guidance_scale: float,
        negative_prompt: str,
    ) -> Image.Image:
        size = getattr(self, "_sd_native_size", 512)
        init_image = init_image.convert("RGB").resize((size, size))

        enhanced_prompt = (
            f"{prompt}, cyberpunk style, neon lights, highly detailed, "
            f"8k resolution, cinematic lighting, vibrant colors, "
            f"rendered on AMD ROCm"
        )

        generator = None
        if self.device == "cuda":
            generator = torch.Generator(device=self.device).manual_seed(42)

        with torch.inference_mode():
            result = self.pipeline(
                prompt=enhanced_prompt,
                negative_prompt=negative_prompt,
                image=init_image,
                strength=strength,
                num_inference_steps=steps,
                guidance_scale=guidance_scale,
                generator=generator,
            )
            image = result.images[0]

        return image

    def _sd3_img2img(
        self,
        init_image: Image.Image,
        prompt: str,
        strength: float,
        steps: int,
        guidance_scale: float,
    ) -> Image.Image:
        _fb_neg = "blurry, low quality, distorted, ugly, watermark"
        if self.sd3_img2img_pipeline is None and _SD3_IMG2IMG_AVAILABLE:
            try:
                self.sd3_img2img_pipeline = StableDiffusion3Img2ImgPipeline.from_pretrained(
                    self.sd3_model_id,
                    torch_dtype=torch.bfloat16,
                ).to(self.device)
                try:
                    self.sd3_img2img_pipeline.enable_model_cpu_offload()
                except Exception:
                    pass
                try:
                    self.sd3_img2img_pipeline.enable_vae_slicing()
                except Exception:
                    pass
            except Exception as _e:
                print(f"  SD3 Img2Img 加载失败，回退 SD 图生图：{_e}")
                return self._sd_img2img(init_image, prompt, strength, steps, guidance_scale, _fb_neg)
        if self.sd3_img2img_pipeline is None:
            return self._sd_img2img(init_image, prompt, strength, steps, guidance_scale, _fb_neg)

        size = 1024
        img = init_image.convert("RGB").resize((size, size))
        enhanced_prompt = (
            f"{prompt}, cyberpunk style, neon lights, highly detailed, "
            f"8k resolution, cinematic lighting, vibrant colors, rendered on AMD ROCm"
        )
        generator = None
        if self.device == "cuda":
            generator = torch.Generator(device=self.device).manual_seed(42)
        with torch.inference_mode():
            result = self.sd3_img2img_pipeline(
                prompt=enhanced_prompt,
                image=img,
                strength=float(strength),
                num_inference_steps=int(steps),
                guidance_scale=float(guidance_scale),
                generator=generator,
            )
            image = result.images[0]
        if self.device == "cuda":
            torch.cuda.empty_cache()
        gc.collect()
        return image

    # ================================================================
    # Txt2Img  →  SD-class (SDXL default / SD v1.5 fallback)
    # ================================================================
    def generate_text_to_image(
        self,
        prompt: str,
        steps: int = 30,
        guidance_scale: float = 7.5,
        width: Optional[int] = None,
        height: Optional[int] = None,
        negative_prompt: str = "blurry, low quality, distorted, ugly, watermark, bad anatomy",
    ) -> Image.Image:
        # Route to the best available image model: if SD3 is loaded we use
        # it (highest quality); otherwise fall through to the SD-class pipeline.
        if self._sd3_loaded and self.sd3_pipeline is not None:
            return self.sd3_generate_text_to_image(
                prompt=prompt,
                steps=steps,
                guidance_scale=guidance_scale,
                width=width or SD3_RECOMMENDED_WIDTH,
                height=height or SD3_RECOMMENDED_HEIGHT,
                seed=42,
            )
        pipe = self._t2i_pipeline
        if pipe is None:
            t2i_cls = self._sd_t2i_cls
            dtype = torch.float16 if self.device == "cuda" else torch.float32
            pipe = t2i_cls.from_pretrained(
                self._sd_load_path,
                torch_dtype=dtype,
                safety_checker=None,
            ).to(self.device)

        if width is None or width <= 0:
            width = self._sd_native_size
        if height is None or height <= 0:
            height = self._sd_native_size

        enhanced_prompt = (
            f"{prompt}, cyberpunk style, neon lights, highly detailed, "
            f"8k resolution, rendered on AMD ROCm"
        )

        generator = None
        if self.device == "cuda":
            generator = torch.Generator(device=self.device).manual_seed(42)

        with torch.inference_mode():
            result = pipe(
                prompt=enhanced_prompt,
                negative_prompt=negative_prompt,
                num_inference_steps=steps,
                guidance_scale=guidance_scale,
                width=width,
                height=height,
                generator=generator,
            )
            image = result.images[0]

        if self.device == "cuda":
            torch.cuda.empty_cache()
        return image

    # ================================================================
    # Txt2Img  →  SD3 (Stable Diffusion 3, PREMIUM QUALITY, recommended)
    # ================================================================
    def sd3_generate_text_to_image(
        self,
        prompt: str,
        steps: int = 28,
        guidance_scale: float = 5.0,
        width: int = SD3_RECOMMENDED_WIDTH,
        height: int = SD3_RECOMMENDED_HEIGHT,
        seed: Optional[int] = 42,
        negative_prompt: str = "",
    ) -> Image.Image:
        if not self._sd3_loaded or self.sd3_pipeline is None:
            raise RuntimeError(
                "SD3 model is not loaded. "
                f"Please ensure {DEFAULT_SD3_MODEL} is available or call engine.reload_sd3()."
            )

        # Validate native SD3 resolutions (multiples of 8, min 512)
        if width % 8 != 0 or height % 8 != 0:
            width = max(SD3_MIN_WIDTH, (width // 8) * 8)
            height = max(SD3_MIN_HEIGHT, (height // 8) * 8)
            print(f"SD3: auto-adjusted size to {width}x{height} (multiple of 8)")

        enhanced_prompt = (
            f"{prompt}. "
            f"cyberpunk aesthetic, neon lights, cinematic composition, "
            f"masterpiece, best quality, ultra detailed, 8k resolution, "
            f"rich depth of field, dramatic lighting, vibrant color palette, "
            f"sharp focus, intricate details, rendered on AMD ROCm GPU"
        )

        generator = None
        if self.device == "cuda" and seed is not None:
            generator = torch.Generator(device=self.device).manual_seed(int(seed))

        print(
            f"SD3 generating {width}x{height} image | "
            f"steps={steps} guidance={guidance_scale}"
        )

        with torch.inference_mode():
            call_kwargs = dict(
                prompt=enhanced_prompt,
                num_inference_steps=int(steps),
                guidance_scale=float(guidance_scale),
                width=int(width),
                height=int(height),
                generator=generator,
            )
            if negative_prompt and str(negative_prompt).strip():
                call_kwargs["negative_prompt"] = negative_prompt
            result = self.sd3_pipeline(**call_kwargs)
            image = result.images[0]

        if self.device == "cuda":
            torch.cuda.empty_cache()
        gc.collect()
        return image

    # ================================================================
    # Lazy re-loader for SD3
    # ================================================================
    def reload_sd3(self, model_id: Optional[str] = None):
        if model_id:
            self.sd3_model_id = model_id
        dtype = torch.bfloat16 if self.device == "cuda" else torch.float32
        if self.sd3_pipeline is not None:
            del self.sd3_pipeline
            self.sd3_pipeline = None
            self._sd3_loaded = False
            if self.device == "cuda":
                torch.cuda.empty_cache()
            gc.collect()
        self._load_sd3_pipeline(self.sd3_model_id, dtype)
        # keep the human-readable label in sync after a (re)load
        _sd3_label = (
            "SD3.5-Large-Turbo"
            if (self.sd3_model_id and "turbo" in self.sd3_model_id.lower())
            else (
                "SD3.5-Large"
                if (self.sd3_model_id and "large" in self.sd3_model_id.lower())
                else "SD3.5-Medium"
            )
        )
        if self._sd3_loaded and self.sd3_pipeline is not None:
            self._image_model_label = _sd3_label

    # ================================================================
    # Legacy SD T2V pipeline loader (kept as fallback)
    # ================================================================
    def _load_legacy_t2v(self, path: str):
        """Robustly load the legacy damo-vilab T2V pipeline.

        Tries variant="fp16" first (uses fp16 .bin if present); if that is
        unavailable (e.g. .bin excluded by ignore_patterns, or partial
        download), retries without variant — diffusers loads the default
        .safetensors (fp32) and casts to fp16 via torch_dtype.
        Returns None on total failure.
        """
        attempts = []
        if self.device == "cuda":
            for variant in ("fp16", None):
                try:
                    if variant:
                        pipe = TextToVideoSDPipeline.from_pretrained(
                            path, torch_dtype=torch.float16, variant="fp16"
                        )
                    else:
                        pipe = TextToVideoSDPipeline.from_pretrained(
                            path, torch_dtype=torch.float16
                        )
                    # 显存充足（>=16GB）则全程驻留 GPU，避免 CPU offload 每步 PCIe 搬运拖慢推理。
                    # 仅在小显存机器上启用 offload。ROCm 首次推理本就要编译内核，offload 会雪上加霜。
                    try:
                        _total_vram_gb = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
                    except Exception:
                        _total_vram_gb = 0.0
                    if _total_vram_gb >= 16.0:
                        pipe = pipe.to(self.device)
                    else:
                        try:
                            pipe.enable_model_cpu_offload()
                        except Exception:
                            pipe = pipe.to(self.device)
                    try:
                        pipe.enable_vae_slicing()
                    except Exception:
                        pass
                    return pipe
                except Exception as _e:
                    attempts.append(f"variant={variant}: {_e}")
                    continue
        else:
            try:
                pipe = TextToVideoSDPipeline.from_pretrained(
                    path, torch_dtype=torch.float32
                ).to(self.device)
                try:
                    pipe.enable_vae_slicing()
                except Exception:
                    pass
                return pipe
            except Exception as _e:
                attempts.append(f"cpu: {_e}")
        print(f"  T2V legacy 加载失败（已尝试的变体）：{attempts}")
        return None

    def _ensure_video_pipeline(self, model_id: str = DEFAULT_T2V_MODEL):
        if self.video_pipeline is None or self._video_model_id != model_id:
            force_local_dir = None
            if _looks_like_huggingface_repo(model_id):
                force_local_dir = _resolve_local_cache_dir(model_id)
            else:
                try:
                    same_as_default = (
                        os.path.abspath(model_id.rstrip("/\\"))
                        == os.path.abspath(LOCAL_LEGACY_T2V_DIR.rstrip("/\\"))
                    )
                except Exception:
                    same_as_default = False
                if same_as_default:
                    marker = os.path.join(LOCAL_LEGACY_T2V_DIR, "model_index.json")
                    if not (os.path.isdir(LOCAL_LEGACY_T2V_DIR) and os.path.isfile(marker)):
                        model_id = DEFAULT_T2V_MODEL
                        force_local_dir = LOCAL_LEGACY_T2V_DIR

            try:
                resolved_path = _ensure_model_local_dir(
                    model_id,
                    model_label="Legacy-T2V",
                    marker_file="model_index.json",
                    force_local_dir=force_local_dir,
                    # 视频模型权重本身是 fp16，不能用全局 *fp16* 排除规则
                    ignore_patterns=T2V_IGNORE_PATTERNS,
                )
            except Exception as _e:
                print(
                    f"  Legacy T2V: 预下载/校验失败：{_e}；"
                    f"不再回退到在线缓存（避免重复下载），交由上层切换模型"
                )
                raise

            print(f"Loading legacy text-to-video model: {resolved_path} ...")
            self._video_model_id = resolved_path
            pipe = self._load_legacy_t2v(resolved_path)

            # Self-heal: 若本地缓存是不完整的旧下载（之前被 *fp16* 规则误删了权重），
            # 删除后重新下载一份完整的，再试一次。
            if pipe is None and force_local_dir is not None and os.path.isdir(resolved_path):
                print(
                    f"  T2V legacy 首次加载失败，疑似本地缓存不完整，删除后重新下载：{resolved_path}"
                )
                try:
                    _purge_failed_model(
                        model_id,
                        model_label="Legacy-T2V",
                        force=True,
                        extra_dirs=[resolved_path, force_local_dir],
                    )
                    resolved_path = _ensure_model_local_dir(
                        model_id,
                        model_label="Legacy-T2V",
                        marker_file="model_index.json",
                        force_local_dir=force_local_dir,
                        ignore_patterns=T2V_IGNORE_PATTERNS,
                    )
                    pipe = self._load_legacy_t2v(resolved_path)
                except Exception as _heal_e:
                    print(f"  T2V legacy 自愈重试失败：{_heal_e}")

            if pipe is None:
                # 重下一次仍加载失败 → 这份权重没救了，删掉再让上层换模型
                _purge_failed_model(
                    model_id,
                    model_label="Legacy-T2V",
                    force=True,
                    extra_dirs=[resolved_path, force_local_dir],
                )
                raise RuntimeError(
                    "Legacy T2V 模型加载失败（权重不完整 / 下载中断 / 磁盘配额满），"
                    "已删除该模型并回收磁盘；视频引擎将尝试其他可用模型。"
                )
            self.video_pipeline = pipe

    # ================================================================
    # Text-to-Video  →  LTX-Video (DEFAULT, fast + long-text T5)
    # With automatic fallback to legacy damo-vilab diffusers pipeline.
    # ================================================================
    def generate_text_to_video(
        self,
        prompt: str,
        steps: int = 50,
        guidance_scale: float = 6.0,
        num_frames: int = 81,
        width: int = 832,
        height: int = 480,
        fps: int = 24,
        negative_prompt: str = (
            "blurry, low quality, distorted, ugly, watermark, "
            "pixelated, duplicated frames, flickering, deformed, "
            "floating objects, bad anatomy, bad motion"
        ),
        output_path: Optional[str] = None,
        export_gif: bool = False,
        seed: Optional[int] = None,
    ) -> Tuple[str, Optional[str], int]:
        _fail_reasons: list[str] = []

        # ---- 0) Wan2.2-TI2V-5B (primary, native Chinese, 720P@24fps) ----
        if not (_WAN_T2V_AVAILABLE and self._t2v_available):
            if not _WAN_T2V_AVAILABLE:
                print("  [Wan2.2-TI2V-5B] 跳过：diffusers 版本过低或未安装 WanPipeline（需 >=0.33）")
                _fail_reasons.append("Wan2.2-TI2V-5B: diffusers 版本过低或未安装 WanPipeline（需 >=0.33）")
            elif not self._t2v_available:
                print("  [Wan2.2-TI2V-5B] 跳过：enable_t2v=False（被 AETHER_ENABLE_T2V=0 禁用）")
                _fail_reasons.append("Wan2.2-TI2V-5B: enable_t2v=False（AETHER_ENABLE_T2V=0）")
        elif self.t2v_model_id and "ltx" in self.t2v_model_id.lower():
            print("  [Wan2.2-TI2V-5B] 跳过：AETHER_T2V_MODEL 显式指定了 LTX 模型，交由 LTX 回退处理")
        else:
            target_id = self.t2v_model_id or DEFAULT_WAN_T2V_MODEL
            if os.path.isdir(target_id):
                _wan_local_dir = target_id
            elif target_id.strip().split("@", 1)[0] == DEFAULT_WAN_T2V_MODEL:
                _wan_local_dir = LOCAL_WAN_T2V_DIR
            else:
                _slug = target_id.strip().replace("/", "__").replace("\\", "__")
                _wan_local_dir = os.path.join(_LOCAL_MODELS_ROOT, _slug)
            _wan_cached = _wan_weights_look_complete(_wan_local_dir)
            _free_wan = _free_disk_gb(_LOCAL_MODELS_ROOT)
            _wan_need = 4 if _wan_cached else int(WAN22_TI2V_5B_SIZE_GB * 1.5) + 4
            if _free_wan < _wan_need:
                print(
                    f"  [Wan2.2-TI2V-5B] 跳过：磁盘空间不足 "
                    f"(剩余 {_free_wan:.1f}GB < 需要 {_wan_need}GB)"
                )
                _fail_reasons.append(
                    f"Wan2.2-TI2V-5B: 磁盘不足 (剩余 {_free_wan:.1f}GB < 需要 {_wan_need}GB)"
                )
            else:
                try:
                    if self._ensure_wan_t2v_pipeline(self.t2v_model_id) and self.wan_t2v_pipeline is not None:
                        self._t2v_last_backend = "wan"
                        return self._generate_wan_video(
                            prompt=prompt,
                            steps=steps,
                            guidance_scale=guidance_scale,
                            num_frames=num_frames,
                            width=width,
                            height=height,
                            fps=fps,
                            negative_prompt=negative_prompt,
                            output_path=output_path,
                            export_gif=export_gif,
                            seed=seed,
                        )
                    _fail_reasons.append(
                        "Wan2.2-TI2V-5B: pipeline 加载失败（详见上方日志，常见=网络下载失败/磁盘不足）"
                    )
                except Exception as _e:
                    print(f"  [Wan2.2-TI2V-5B] 不可用，尝试 LTX-Video：{_e}")
                    _fail_reasons.append(f"Wan2.2-TI2V-5B: {_e}")

        # ---- 1) LTX-Video (fallback) ----
        if not _LTX_VIDEO_AVAILABLE:
            _fail_reasons.append("LTX-Video: diffusers 版本过低或未安装 LTXPipeline（需 >=0.33）")
        else:
            target_id = self.ltx_t2v_model_id or DEFAULT_LTX_T2V_MODEL
            if os.path.isdir(target_id):
                _ltx_local_dir = target_id
            elif target_id.strip().split("@", 1)[0] == DEFAULT_LTX_T2V_MODEL:
                _ltx_local_dir = LOCAL_LTX_T2V_DIR
            else:
                _slug = target_id.strip().replace("/", "__").replace("\\", "__")
                _ltx_local_dir = os.path.join(_LOCAL_MODELS_ROOT, _slug)
            _ltx_cached = _ltx_weights_look_complete(_ltx_local_dir)
            _free_ltx = _free_disk_gb(_LOCAL_MODELS_ROOT)
            _ltx_need = 4 if _ltx_cached else int(LTX_VIDEO_SIZE_GB * 1.5) + 4
            if _free_ltx < _ltx_need:
                print(
                    f"  [LTX-Video] 跳过：磁盘空间不足 "
                    f"(剩余 {_free_ltx:.1f}GB < 需要 {_ltx_need}GB)"
                )
                _fail_reasons.append(
                    f"LTX-Video: 磁盘不足 (剩余 {_free_ltx:.1f}GB < 需要 {_ltx_need}GB)"
                )
            else:
                try:
                    if self._ensure_ltx_pipeline(self.ltx_t2v_model_id) and self.ltx_pipeline is not None:
                        self._t2v_last_backend = "ltx"
                        return self._generate_ltx_video(
                            prompt=prompt,
                            steps=steps,
                            guidance_scale=guidance_scale,
                            num_frames=num_frames,
                            width=width,
                            height=height,
                            fps=fps,
                            negative_prompt=negative_prompt,
                            output_path=output_path,
                            export_gif=export_gif,
                            seed=seed,
                        )
                    _fail_reasons.append(
                        "LTX-Video: pipeline 加载失败（详见上方日志，常见=网络下载失败/磁盘不足）"
                    )
                except Exception as _e:
                    print(f"  [LTX-Video] 不可用，尝试 Legacy T2V：{_e}")
                    _fail_reasons.append(f"LTX-Video: {_e}")

        # ---- 2) Legacy damo-vilab T2V (fallback) ----
        _free_gb = _free_disk_gb(_LOCAL_MODELS_ROOT)
        _need_gb = 2 * LEGACY_T2V_SIZE_GB + 4  # 16 GB
        if _free_gb < _need_gb:
            print(
                f"  [Legacy T2V] 跳过：磁盘空间不足 "
                f"(剩余 {_free_gb:.1f}GB < 需要 {_need_gb}GB)"
            )
            print(
                "  → 修复：清理磁盘（rm -rf models/Wan2.2-TI2V-5B models/LTX-Video "
                "~/.cache/huggingface/hub outputs/*）"
                "  或  pip install -U diffusers 后走 Wan/LTX 主路径"
            )
            _fail_reasons.append(
                f"Legacy T2V: 磁盘不足 (剩余 {_free_gb:.1f}GB < 需要 {_need_gb}GB)"
            )
        else:
            try:
                _legacy_params = dict(
                    prompt=prompt, steps=steps, guidance_scale=guidance_scale,
                    num_frames=num_frames, width=width, height=height, fps=fps,
                    negative_prompt=negative_prompt, output_path=output_path, export_gif=export_gif,
                )
                self._ensure_video_pipeline()
                if self.video_pipeline is not None:
                    self._t2v_last_backend = "legacy"
                    return self._generate_legacy_t2v_video(**_legacy_params)
                _fail_reasons.append("Legacy T2V: pipeline 加载后仍为 None")
            except Exception as _e:
                print(f"  [Legacy T2V] 不可用：{_e}")
                _fail_reasons.append(f"Legacy T2V: {_e}")

        raise RuntimeError(
            "视频生成不可用，所有引擎均失败：\n  - "
            + "\n  - ".join(_fail_reasons)
            + "\n\n建议：\n"
            "  ① 升级 diffusers: pip install -U diffusers（需 >=0.33 以支持 Wan2.2-TI2V-5B / LTX-Video）\n"
            "  ② 清理磁盘后重试（Legacy 需 16GB 空闲）\n"
            "  ③ 或先用「SD3 文生图」Tab 生成静态图"
        )

    # ---- Internal: LTX-Video generation --------------------------------
    def _generate_ltx_video(
        self,
        prompt: str,
        steps: int = 30,
        guidance_scale: float = 5.0,
        num_frames: int = 16,
        width: int = 512,
        height: int = 512,
        fps: int = 8,
        negative_prompt: str = "",
        output_path: Optional[str] = None,
        export_gif: bool = False,
        seed: Optional[int] = None,
    ) -> Tuple[str, Optional[str], int]:
        assert self.ltx_pipeline is not None

        # LTX-Video uses T5-XXL — effectively unlimited prompt length (capped at 512 tokens).
        # T5-XXL is English-centric: Chinese prompts are auto-translated to English.
        # Respect the user's prompt; only fall back to a distinctive default if empty.
        _user_prompt = prompt.strip()
        if _user_prompt and _contains_chinese(_user_prompt):
            _translated = _translate_zh_to_en(_user_prompt)
            if _translated != _user_prompt:
                print(f"  [LTX-Video] 中文提示词已翻译：{_translated[:120]}...")
            _user_prompt = _translated
        enhanced_prompt = _user_prompt or (
            "A glowing red robot walking through a futuristic city at sunset, "
            "sci-fi cinematic shot, smooth camera motion, high quality"
        )
        if negative_prompt:
            _neg = str(negative_prompt).strip()
            if _contains_chinese(_neg):
                _neg_translated = _translate_zh_to_en(_neg)
                if _neg_translated != _neg:
                    print(f"  [LTX-Video] 负向提示词已翻译：{_neg_translated[:120]}...")
                enhanced_neg = _neg_translated
            else:
                enhanced_neg = _neg
        else:
            enhanced_neg = (
                "blurry, low quality, distorted, ugly, watermark, "
                "pixelated, duplicated frames, flickering, deformed, "
                "floating objects, bad anatomy, bad motion"
            )

        # LTX-Video constraints: spatial dims divisible by 32; (num_frames-1) divisible by 8.
        _w = max(32, (width // 32) * 32)
        _h = max(32, (height // 32) * 32)
        _f = max(9, (((num_frames - 1) // 8) * 8) + 1)

        _prompt_preview = enhanced_prompt[:80].replace("\n", " ")
        print(
            f"LTX-Video generating | prompt='{_prompt_preview}...' | "
            f"prompt_len={len(enhanced_prompt)} | "
            f"frames={_f} | {_w}x{_h} | steps={steps} | guidance={guidance_scale} | fps={fps}"
        )

        generator = None
        if self.device == "cuda" and seed is not None:
            generator = torch.Generator(device=self.device).manual_seed(int(seed))

        with torch.inference_mode():
            try:
                # max_sequence_length (T5-XXL long-text) is accepted by newer diffusers
                # LTXPipeline; on older versions it raises TypeError — drop it and retry.
                result = self.ltx_pipeline(
                    prompt=enhanced_prompt,
                    negative_prompt=enhanced_neg,
                    num_frames=_f,
                    width=_w,
                    height=_h,
                    num_inference_steps=int(steps),
                    guidance_scale=float(guidance_scale),
                    generator=generator,
                    max_sequence_length=512,
                    output_type="pil",
                )
            except TypeError as _kw_err:
                if "max_sequence_length" not in str(_kw_err):
                    raise
                print("  [LTX-Video] 当前 diffusers 版本不支持 max_sequence_length，已忽略（默认 512 token）。")
                result = self.ltx_pipeline(
                    prompt=enhanced_prompt,
                    negative_prompt=enhanced_neg,
                    num_frames=_f,
                    width=_w,
                    height=_h,
                    num_inference_steps=int(steps),
                    guidance_scale=float(guidance_scale),
                    generator=generator,
                    output_type="pil",
                )

        frames = self._ltx_result_to_pil_frames(result)
        frame_count = len(frames)
        if frame_count == 0:
            raise RuntimeError("LTX-Video pipeline produced zero frames")

        if output_path is None:
            out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs")
            os.makedirs(out_dir, exist_ok=True)
            from datetime import datetime
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = os.path.join(out_dir, f"ltx_t2v_{fps}fps_{ts}.mp4")

        os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)

        mp4_path = _safe_export_to_video(frames, output_path=output_path, fps=fps)
        gif_path = None
        if export_gif:
            gif_path = os.path.splitext(mp4_path)[0] + ".gif"
            try:
                _safe_export_to_gif(frames, gif_path, fps=fps)
            except Exception as e:
                print(f"GIF export skipped (non-fatal): {e}")
                gif_path = None

        if self.device == "cuda":
            torch.cuda.empty_cache()
        gc.collect()
        return mp4_path, gif_path, frame_count

    def _ltx_result_to_pil_frames(self, result) -> list:
        """Normalize LTXPipeline output (tensor or list-of-lists of PIL) to a flat list of PIL Images."""
        frames = getattr(result, "frames", None)
        if frames is None:
            raise RuntimeError("LTX-Video pipeline returned no frames")
        if isinstance(frames, torch.Tensor):
            arr = frames[0]  # (f, c, h, w)
            out = []
            for i in range(arr.shape[0]):
                t = arr[i]
                if t.is_floating_point():
                    t = t.clamp(-1, 1)
                    t = (t * 0.5 + 0.5).clamp(0, 1)
                    t = (t * 255).round().to(torch.uint8)
                out.append(Image.fromarray(t.permute(1, 2, 0).cpu().numpy()))
            return out
        if isinstance(frames, list):
            if frames and isinstance(frames[0], list):
                return frames[0]
            return frames
        # numpy / other fallback
        return _normalize_video_frames(frames)

    # ---- Internal: legacy SD T2V fallback ------------------------------
    def _generate_legacy_t2v_video(
        self,
        prompt: str,
        steps: int,
        guidance_scale: float,
        num_frames: int,
        width: int,
        height: int,
        fps: int,
        negative_prompt: str,
        output_path: Optional[str],
        export_gif: bool,
    ) -> Tuple[str, Optional[str], int]:
        self._ensure_video_pipeline()
        assert self.video_pipeline is not None

        # damo-vilab uses CLIP, which is also English-centric. Translate Chinese.
        # Respect the user's prompt; only fall back to a distinctive default if empty.
        _user_prompt = prompt.strip()
        if _user_prompt and _contains_chinese(_user_prompt):
            _translated = _translate_zh_to_en(_user_prompt)
            if _translated != _user_prompt:
                print(f"  [Legacy T2V] 中文提示词已翻译：{_translated[:120]}...")
            _user_prompt = _translated
        enhanced_prompt = _user_prompt or (
            "A glowing red robot walking through a futuristic city at sunset, "
            "sci-fi cinematic shot, smooth motion, high quality"
        )
        # Translate Chinese negative prompt as well (CLIP is English-centric).
        _neg = str(negative_prompt or "").strip()
        if _neg and _contains_chinese(_neg):
            _neg_translated = _translate_zh_to_en(_neg)
            if _neg_translated != _neg:
                print(f"  [Legacy T2V] 负向提示词已翻译：{_neg_translated[:120]}...")
            negative_prompt = _neg_translated

        # CLIP (used by legacy damo-vilab pipeline) only accepts 77 subword tokens.
        # Chinese characters + our long quality string can easily hit 170+ tokens,
        # which triggers embeddings truncation inside diffusers and, combined with
        # certain ROCm driver builds, causes the first denoising kernel to hang
        # at 0%.  We use a 3-layer defense:
        #   (1) char-based heuristic comma-aware cuts from the right, for both
        #       prompt and negative_prompt;
        #   (2) real tokenizer-enforced truncation through pipeline.tokenizer if
        #       already loaded;
        #   (3) max_tokens is set to 60 for prompt + 40 for negative to leave
        #       headroom for BOS/EOS/padding.
        truncated_prompt = _truncate_for_clip(enhanced_prompt, max_tokens=60)
        truncated_neg = _truncate_for_clip(negative_prompt, max_tokens=40)
        _before_total = len(enhanced_prompt) + len(negative_prompt)
        enhanced_prompt = truncated_prompt
        negative_prompt = truncated_neg
        _after_total = len(enhanced_prompt) + len(negative_prompt)
        if _after_total < _before_total:
            print(
                f"  [Legacy T2V] prompt+neg truncated "
                f"{_before_total - _after_total} chars "
                f"(heuristic) to stay under CLIP 77-token limit."
            )
        try:
            real_tok = getattr(self.video_pipeline, "tokenizer", None)
            if real_tok is not None:
                _real_max = min(77, int(getattr(real_tok, "model_max_length") or 77))

                def _clip(text: str, cap: int):
                    if not text:
                        return ""
                    out = real_tok(
                        text,
                        truncation=True,
                        max_length=cap,
                        padding=False,
                    )
                    ids = out["input_ids"]
                    # strip bos/eos from edges if present
                    if len(ids) >= 1 and ids[0] == real_tok.bos_token_id:
                        ids = ids[1:]
                    if len(ids) >= 1 and ids[-1] == real_tok.eos_token_id:
                        ids = ids[:-1]
                    if len(ids) > cap:
                        ids = ids[:cap]
                    try:
                        s = real_tok.decode(ids, skip_special_tokens=True).strip()
                        return s if s else text
                    except Exception:
                        return text

                _p_old, _n_old = enhanced_prompt, negative_prompt
                enhanced_prompt = _clip(enhanced_prompt, 55)
                negative_prompt = _clip(negative_prompt, 35)
                if len(enhanced_prompt) < len(_p_old) or len(negative_prompt) < len(_n_old):
                    print(
                        f"  [Legacy T2V] tokenizer-enforced clip done "
                        f"(prompt {len(_p_old)}→{len(enhanced_prompt)}, "
                        f"neg {len(_n_old)}→{len(negative_prompt)})."
                    )
        except Exception:
            pass

        # Legacy damo-vilab was trained on 256x256; it degrades badly above
        # ~576px and simply produces brown noise at 1024x576. Clamp to a
        # safe max dimension and align to 64 for SD1.5 UNet.
        _legacy_w = int(width)
        _legacy_h = int(height)
        _max_side = 576
        if _legacy_w > _max_side or _legacy_h > _max_side:
            _scale = _max_side / max(_legacy_w, _legacy_h)
            _legacy_w = int(_legacy_w * _scale)
            _legacy_h = int(_legacy_h * _scale)
            print(
                f"  [Legacy T2V] 分辨率 {width}x{height} 超出 damo-vilab 训练分布，"
                f"已等比缩放至 {_legacy_w}x{_legacy_h}。"
            )
        _legacy_w = max(256, (_legacy_w // 64) * 64)
        _legacy_h = max(256, (_legacy_h // 64) * 64)
        print(f"  [Legacy T2V] 最终推理分辨率：{_legacy_w}x{_legacy_h}")

        generator = None
        if self.device == "cuda":
            generator = torch.Generator(device=self.device).manual_seed(42)

        with torch.inference_mode():
            result = self.video_pipeline(
                prompt=enhanced_prompt,
                negative_prompt=negative_prompt,
                num_inference_steps=int(steps),
                guidance_scale=float(guidance_scale),
                num_frames=int(num_frames),
                width=_legacy_w,
                height=_legacy_h,
                generator=generator,
            )
            frames = result.frames

        # Normalize frames: legacy SD T2V pipeline's .frames can be ndarray
        # (N, H, W, 3), list of PIL.Image, or nested list for batch.  All
        # cases unified before taking frame_count.
        frames = _normalize_video_frames(frames)
        frame_count = len(frames)

        if output_path is None:
            out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs")
            os.makedirs(out_dir, exist_ok=True)
            from datetime import datetime
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = os.path.join(out_dir, f"t2v_{fps}fps_{ts}.mp4")

        os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)

        mp4_path = _safe_export_to_video(frames, output_path=output_path, fps=fps)
        gif_path = None
        if export_gif:
            gif_path = os.path.splitext(mp4_path)[0] + ".gif"
            try:
                _safe_export_to_gif(frames, gif_path, fps=fps)
            except Exception as e:
                print(f"GIF export skipped (non-fatal): {e}")
                gif_path = None

        if self.device == "cuda":
            torch.cuda.empty_cache()

        return mp4_path, gif_path, frame_count


if __name__ == "__main__":
    engine = ROCmAIGCEngine()
    print("=" * 60)
    print("Engine status summary:")
    print(f"  Device:               {engine.device}")
    print(f"  SD3 available:        {engine._sd3_loaded}")
    print(f"  LTX-Video importable: {_LTX_VIDEO_AVAILABLE}")
    if not _LTX_VIDEO_AVAILABLE and _LTX_IMPORT_ERROR:
        print(f"    import error: {_LTX_IMPORT_ERROR}")
    print(f"  T2V available:        {engine._t2v_available}")
    print(f"  T2V configured model: {engine.t2v_model_id}")
    _free = _free_disk_gb(_LOCAL_MODELS_ROOT)
    print(f"  Free disk (models/):  {_free:.1f} GB")
    if not _LTX_VIDEO_AVAILABLE:
        print()
        print("  >>> LTX-Video 不可用！视频生成主路径失效。")
        print("  >>> 修复: pip install -U diffusers (需 >=0.33)")
    print("=" * 60)
    print("Text-to-video: LTX-Video (default) + Legacy SD T2V (fallback, lazy)")
