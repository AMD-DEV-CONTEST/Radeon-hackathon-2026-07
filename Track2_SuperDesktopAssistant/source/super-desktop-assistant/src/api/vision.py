"""
视觉 API —— 分析图片内容。
支持 OpenAI 兼容多模态 API 与本地推理 API (vLLM/Ollama)。
"""
import base64
import os
from pathlib import Path
from loguru import logger
from ._client import get_client_for
from ..config import get_config, ProviderSpec, ModelSpec

# 安全限制：base64 编码后约 27 MB，接近大多数 API 的 20-30 MB 请求体限制
_MAX_IMAGE_SIZE = 20 * 1024 * 1024  # 20 MB


def _resolve(provider: str | None = None, model: str | None = None):
    cfg = get_config()
    if provider and model:
        p = cfg.get_provider(provider)
        if not p: raise ValueError(f"供应商不存在: {provider}")
        m = p.get_model(model)
        if not m: raise ValueError(f"模型 {model} 不存在")
        return p, m, model

    resolved = cfg.resolve("vision")
    if not resolved:
        raise ValueError("vision 功能未分配供应商/模型")
    p, m = resolved
    return p, m, m.id


def _encode_image(image_path: str) -> str:
    """图片 → base64 data URL（含大小限制检查）。"""
    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"图片不存在: {image_path}")

    # 大小限制
    file_size = os.path.getsize(path)
    if file_size > _MAX_IMAGE_SIZE:
        raise ValueError(
            f"图片过大: {file_size} bytes > {_MAX_IMAGE_SIZE} limit "
            f"（base64 编码后接近 API 请求体限制）"
        )

    ext = path.suffix.lower().lstrip(".")
    mime_map = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "webp": "webp", "gif": "gif"}
    mime = mime_map.get(ext, "jpeg")

    with open(path, "rb") as f:
        data = base64.b64encode(f.read()).decode("utf-8")
    return f"data:image/{mime};base64,{data}"


def analyze(
    image_path: str | None = None,
    image_url: str | None = None,
    prompt: str = "请详细描述这张图片的内容。",
    provider: str | None = None,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> str:
    """
    分析图片内容（兼容本地多模态推理 API）。

    Phase B：委托 ai-coin 多模态（本地图片自动 base64）。

    Args:
        image_path: 本地图片路径
        image_url: 图片 URL
        prompt: 给视觉模型的指令
        provider/model: 覆盖配置中的分配
        temperature: 温度参数（None=使用模型默认值）
        max_tokens: 最大输出 token 数

    Returns:
        分析结果文本
    """
    if not image_path and not image_url:
        raise ValueError("必须提供 image_path 或 image_url")

    from .ai_coin_bridge import analyze_image

    logger.debug(f"Vision (ai-coin): {prompt[:60]}...")
    return analyze_image(
        image_path=image_path, image_url=image_url, prompt=prompt,
        provider=provider, model=model,
        temperature=temperature, max_tokens=max_tokens,
    )


_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
_AUDIO_EXTS = {".mp3", ".wav", ".ogg", ".m4a", ".flac", ".aac"}
_VIDEO_EXTS = {".mp4", ".mov", ".webm", ".avi", ".mkv"}


def analyze_media(media_path: str, prompt: str = "请分析这段媒体内容。",
                  provider: str | None = None, model: str | None = None,
                  temperature: float | None = None, max_tokens: int | None = None) -> str:
    """分析任意媒体文件（图片/音频/视频），按扩展名自动分派。

    图片 → analyze()（多模态 image_url）；音频/视频 → ai-coin 的
    audio_part/video_part（openai_compatible / anthropic 供应商可用）。
    """
    ext = Path(media_path).suffix.lower()
    if ext in _IMAGE_EXTS:
        return analyze(image_path=media_path, prompt=prompt, provider=provider,
                       model=model, temperature=temperature, max_tokens=max_tokens)

    from .ai_coin_bridge import analyze_media as _aicoin_media
    return _aicoin_media(
        audio_path=media_path if ext in _AUDIO_EXTS else None,
        video_path=media_path if ext in _VIDEO_EXTS else None,
        prompt=prompt, provider=provider, model=model,
        temperature=temperature, max_tokens=max_tokens,
    )
