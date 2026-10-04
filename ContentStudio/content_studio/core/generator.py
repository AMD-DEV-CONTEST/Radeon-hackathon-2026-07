"""生成编排：调 LLM + JSON 解析 + 降级。"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional

from content_studio.core import models, prompts


@dataclass
class WeChatContent:
    title: str = ""
    summary: str = ""
    cover_prompt: str = ""
    body_html: str = ""
    image_captions: list[str] = field(default_factory=list)
    image_prompts: list[str] = field(default_factory=list)
    raw: str = ""
    fell_back: bool = False


@dataclass
class XHSContent:
    title: str = ""
    body: str = ""
    hashtags: list[str] = field(default_factory=list)
    cover_text: str = ""
    raw: str = ""
    fell_back: bool = False


def build_material(user_text: str, ocr_text: str = "", image_count: int = 0) -> str:
    parts: list[str] = []
    if user_text.strip():
        parts.append(user_text.strip())
    if ocr_text.strip():
        parts.append(f"[图片中识别的文字]\n{ocr_text.strip()}")
    if image_count:
        parts.append(f"[附图 {image_count} 张]")
    return "\n\n".join(parts) if parts else "(无素材)"


def _parse_json(content: str) -> Optional[dict]:
    s = (content or "").strip()
    if s.startswith("```"):  # 去掉 ```json ... ``` 围栏
        lines = s.splitlines()
        lines = lines[1:]  # 去首行 ```xxx
        if lines and lines[-1].strip().endswith("```"):
            lines[-1] = lines[-1].strip()[:-3]
        s = "\n".join(lines).strip()
    try:
        return json.loads(s)
    except Exception:
        pass
    # 模型在 JSON 外面带了说明文字时，提取最外层 {...}
    start, end = s.find("{"), s.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(s[start:end + 1])
        except Exception:
            return None
    return None


class Generator:
    def __init__(self, client: models.LLMClient):
        self.client = client

    def _complete_and_parse(self, system: str, user: str, images: list[str] | None = None) -> tuple[Optional[dict], str]:
        content = self.client.complete_json(system, user, images=images)
        parsed = _parse_json(content)
        if parsed is None:
            fix_user = "上一次返回不是合法 JSON，请只输出合法 JSON。\n\n" + user
            content = self.client.complete_json(system, fix_user, images=images)
            parsed = _parse_json(content)
        return parsed, content

    def generate_wechat(self, material: str, style=None, images: list[str] | None = None) -> WeChatContent:
        system, user = prompts.build_wechat_prompt(material, style)
        parsed, raw = self._complete_and_parse(system, user, images=images)
        if parsed is None:
            return WeChatContent(title="(解析失败)", body_html=raw, raw=raw, fell_back=True)
        return WeChatContent(
            title=parsed.get("title", ""),
            summary=parsed.get("summary", ""),
            cover_prompt=parsed.get("cover_prompt", ""),
            body_html=parsed.get("body_html", ""),
            image_captions=list(parsed.get("image_captions") or []),
            image_prompts=list(parsed.get("image_prompts") or []),
            raw=raw,
        )

    def generate_xhs(self, material: str) -> XHSContent:
        system, user = prompts.build_xhs_prompt(material)
        parsed, raw = self._complete_and_parse(system, user)
        if parsed is None:
            return XHSContent(title="(解析失败)", body=raw, raw=raw, fell_back=True)
        return XHSContent(
            title=parsed.get("title", ""),
            body=parsed.get("body", ""),
            hashtags=list(parsed.get("hashtags") or []),
            cover_text=parsed.get("cover_text", ""),
            raw=raw,
        )
