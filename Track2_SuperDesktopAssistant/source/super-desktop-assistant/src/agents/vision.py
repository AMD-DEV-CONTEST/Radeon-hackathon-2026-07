"""
👁️ 视觉执行 Agent —— 分析图片/视频/音频内容。
"""
import asyncio
import os
from pathlib import Path
from ..orchestration.executor import register_agent
from ..orchestration.dag import NodeType
from ..api.vision import analyze, analyze_media
from loguru import logger


@register_agent(NodeType.VISION)
async def execute_vision(node, prompt: str, context: dict) -> str:
    logger.info(f"[VIS] [{node.id}] {prompt[:60]}...")

    image_path, image_url, media_path = _find_source_media(node, context)

    if media_path:
        result = await asyncio.to_thread(analyze_media, media_path, prompt=prompt)
    elif image_path or image_url:
        result = await asyncio.to_thread(
            analyze,
            image_path=image_path,
            image_url=image_url,
            prompt=prompt,
        )
    else:
        return "[WARN] 没有可用的图片/视频/音频。请先上传媒体文件，或确保前置节点生成了媒体文件。"

    logger.debug(f"[VIS] [{node.id}] -> {len(result)} chars")
    return result


def _find_source_media(node, context: dict) -> tuple[str | None, str | None, str | None]:
    """定位待分析媒体，返回 (image_path, image_url, media_path)。

    优先级：用户视频 > 用户音频 > 用户图片 > 依赖节点产物（音视频优先）> 图片 URL。
    media_path 非空时表示音频/视频文件，走 analyze_media。
    """
    for key in ("_user_video", "_user_audio"):
        p = context.get(key)
        if p and os.path.isfile(str(p)):
            return None, None, str(p)

    image_path, image_url = _find_source_image(node, context)
    if image_path or image_url:
        return image_path, image_url, None

    # 依赖节点产出的音频/视频（图片已被 _find_source_image 处理）
    for dep_id in node.depends_on:
        dep_result = context.get(dep_id)
        if dep_result and isinstance(dep_result, str) and os.path.isfile(dep_result):
            if Path(dep_result).suffix.lower() not in _IMG_EXTS:
                return None, None, dep_result
    return None, None, None


def _find_source_image(node, context: dict) -> tuple[str | None, str | None]:
    """定位待分析的图片（E1 修复）。

    优先用户上传的图片，其次依赖节点（如 image_gen）生成的图片，
    最后用户上传的图片 URL。镜像 image_gen.py 的 _find_source_image。
    """
    _IMG_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")

    # 1. 用户上传的本地图片
    user_image = context.get("_user_image")
    if user_image and os.path.isfile(str(user_image)):
        return str(user_image), None

    # 2. 依赖节点生成的图片（image_gen_1 → vision_1）
    for dep_id in node.depends_on:
        dep_result = context.get(dep_id)
        if dep_result and isinstance(dep_result, str):
            p = str(dep_result)
            if os.path.isfile(p) and Path(p).suffix.lower() in _IMG_EXTS:
                return p, None

    # 3. 用户上传的图片 URL
    image_url = context.get("_user_image_url")
    if image_url:
        return None, str(image_url)

    return None, None
