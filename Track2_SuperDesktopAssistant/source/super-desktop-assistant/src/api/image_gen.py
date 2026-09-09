"""
生图 API —— 文生图。
使用分配给 "image_gen" 功能的供应商/模型。
"""
import httpx
from pathlib import Path
from loguru import logger
from ._client import get_client_for
from ..config import get_config


def _resolve(provider: str | None = None, model: str | None = None):
    cfg = get_config()
    if provider and model:
        p = cfg.get_provider(provider)
        if not p: raise ValueError(f"供应商不存在: {provider}")
        m = p.get_model(model)
        if not m: raise ValueError(f"模型 {model} 不存在")
        return p, m, model

    resolved = cfg.resolve("image_gen")
    if not resolved:
        raise ValueError("image_gen 功能未分配供应商/模型")
    p, m = resolved
    return p, m, m.id


def generate(
    prompt: str,
    size: str | None = None,
    quality: str | None = None,
    style: str | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> list[str]:
    """
    文生图。

    Args:
        prompt: 图片描述（英文效果更好）
        size: 尺寸
        quality: standard / hd
        style: vivid / natural
        provider/model: 覆盖配置

    Returns:
        图片 URL 列表
    """
    p, m, model_id = _resolve(provider, model)
    client = get_client_for(p.name)

    # 参数: 显式 > 模型默认
    params = dict(m.default_params)
    if size: params["size"] = size
    if quality: params["quality"] = quality
    if style: params["style"] = style

    kwargs = dict(model=model_id, prompt=prompt, n=1)

    # DALL-E 3 特有参数
    if model_id.startswith("dall-e-3"):
        kwargs["size"] = params.get("size", "1024x1024")
        kwargs["quality"] = params.get("quality", "standard")
        kwargs["style"] = params.get("style", "vivid")
    elif "size" in params:
        kwargs["size"] = params["size"]

    logger.debug(f"🎨 ImageGen [{p.name}/{model_id}]: {prompt[:80]}...")

    response = client.images.generate(**kwargs)
    # 兼容仅返回 b64_json（无 URL）的供应商
    urls = []
    for img in response.data:
        if getattr(img, "url", None):
            urls.append(img.url)
        elif getattr(img, "b64_json", None):
            urls.append(f"data:image/png;base64,{img.b64_json}")
    logger.debug(f"🎨 → {len(urls)} image(s)")
    return urls


def download_image(url: str, output_path: str) -> str:
    """下载生成的图片到本地（支持 HTTP URL 与 data URI）。"""
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    if url.startswith("data:image"):
        import base64
        b64_data = url.split(",", 1)[1]
        with open(output_path, "wb") as f:
            f.write(base64.b64decode(b64_data))
        logger.debug(f"📥 图片已保存: {output_path}")
        return output_path

    resp = httpx.get(url, timeout=60)
    resp.raise_for_status()

    with open(output_path, "wb") as f:
        f.write(resp.content)

    logger.debug(f"📥 图片已保存: {output_path}")
    return output_path
