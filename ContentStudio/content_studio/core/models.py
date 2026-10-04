"""LLM 客户端（OpenAI 兼容，带重试）。"""
from __future__ import annotations

import time
from typing import Any, Callable

from content_studio.config import ProviderConfig


class LLMError(Exception):
    pass


def _encode_image(path: str, max_dim: int = 1280, quality: int = 80) -> str:
    """读图、缩放、转 base64 data URL（用于视觉模型）。"""
    import base64
    import io
    from PIL import Image
    im = Image.open(path).convert("RGB")
    if max(im.size) > max_dim:
        im.thumbnail((max_dim, max_dim))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=quality)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def _looks_like_vision_unsupported(msg: str) -> bool:
    """错误信息是否表明『模型不支持图片输入』（用于自动退回纯文本）。"""
    m = (msg or "").lower()
    if not any(k in m for k in ["400", "badrequest", "1210", "invalid", "不支持"]):
        return False
    return any(k in m for k in ["content.type", "image", "vision", "multimodal", "图片"])


class LLMClient:
    def __init__(
        self,
        provider: ProviderConfig,
        client: Any = None,
        max_retries: int = 3,
        sleeper: Callable[[float], None] = time.sleep,
    ):
        # openai 延迟到真正构造/使用客户端时才导入（启动时不导入，省约 1.5s）
        import openai
        self._retryable = (
            getattr(openai, "APITimeoutError", object),
            getattr(openai, "APIConnectionError", object),
            getattr(openai, "RateLimitError", object),
            getattr(openai, "InternalServerError", object),
        )
        self.provider = provider
        self.max_retries = max_retries
        self._sleep = sleeper
        if client is not None:
            self._client = client
        else:
            self._client = openai.OpenAI(
                base_url=provider.base_url, api_key=provider.api_key or "missing-key",
                timeout=180,  # 不再等 openai 默认 600s；超时给明确提示
            )

    def complete_json(self, system: str, user: str, images: list[str] | None = None) -> str:
        last_err: Exception | None = None
        imgs = images
        for attempt in range(self.max_retries):
            try:
                resp = self._one_call(system, user, imgs)
                return resp.choices[0].message.content
            except self._retryable as e:
                last_err = e
                self._sleep(0.5 * (2 ** attempt))
            except Exception as e:
                # 模型若不支持图片输入，自动退回纯文本再试
                if imgs is not None and _looks_like_vision_unsupported(str(e)):
                    imgs = None
                    continue
                raise LLMError(str(e)) from e
        raise LLMError(f"重试 {self.max_retries} 次后仍失败: {last_err}")

    def _one_call(self, system: str, user: str, images: list[str] | None = None):
        if images:
            content = [{"type": "text", "text": user}] + [
                {"type": "image_url", "image_url": {"url": _encode_image(p)}} for p in images
            ]
            messages = [{"role": "system", "content": system}, {"role": "user", "content": content}]
            return self._client.chat.completions.create(
                model=self.provider.model, messages=messages, temperature=0.8
            )  # 视觉调用不强制 json_object（部分视觉模型不支持）
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        return self._client.chat.completions.create(
            model=self.provider.model, messages=messages,
            response_format={"type": "json_object"}, temperature=0.8,
        )
