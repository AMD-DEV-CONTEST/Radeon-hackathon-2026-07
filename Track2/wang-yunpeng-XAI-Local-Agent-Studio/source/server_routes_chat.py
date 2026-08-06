"""XAI 后端路由处理器（S5-1 自动迁移，按领域拆分）。
方法体原属 server_xai.XAIHandler，统一签名 fn(h)，h 即 XAIHandler 实例。
共享单例经 server_xai import *（惰性，bootstrap 在文件末尾，循环导入安全）+ server_runtime。
"""
from __future__ import annotations
import base64
import os
import re as _re
import threading
from server_xai import *   # 共享单例 / 辅助（惰性导入，安全）
from server_runtime import get_engine, get_knowledge_adapter, _CAPABILITIES

# 资源上限护栏（T1 · 六维验收·维度二）：限制并发对话生成数量，
# 避免瞬时高并发把模型后端打爆；超过容量的请求排队等待而非失败。
_CHAT_SEM = threading.Semaphore(20)

# 图片扩展名 → MIME（用于视觉多模态 content 构造）
_IMAGE_EXT_MIME = {
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
    "gif": "image/gif", "webp": "image/webp", "bmp": "image/bmp",
}
_MAX_VISION_BYTES = 8 * 1024 * 1024  # 单图上限 8MB（base64 约 10.7MB）

# 魔数 → (扩展名, MIME)，用于无扩展名文件的图片探测（替代已移除的 imghdr）
_MAGIC_IMAGE = [
    (b"\x89PNG\r\n\x1a\n", "png", "image/png"),
    (b"\xff\xd8\xff", "jpg", "image/jpeg"),
    (b"GIF87a", "gif", "image/gif"),
    (b"GIF89a", "gif", "image/gif"),
    (b"BM", "bmp", "image/bmp"),
    (b"RIFF", "webp", "image/webp"),  # 后接 ....WEBP，下面二次确认
]


def _detect_image(head: bytes) -> str | None:
    """返回图片 MIME，非图片返回 None。"""
    for magic, ext, mime in _MAGIC_IMAGE:
        if head.startswith(magic):
            if ext == "webp":
                # RIFF 后 4 字节为 'WEBP'
                if len(head) >= 12 and head[8:12] == b"WEBP":
                    return mime
                return None
            return mime
    return None


def _is_image_file(path: str) -> bool:
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    if ext in _IMAGE_EXT_MIME:
        return True
    try:
        with open(path, "rb") as f:
            head = f.read(12)
        return _detect_image(head) is not None
    except Exception:
        return False


def _image_mime(path: str) -> str:
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    if ext in _IMAGE_EXT_MIME:
        return _IMAGE_EXT_MIME[ext]
    try:
        with open(path, "rb") as f:
            head = f.read(12)
        return _detect_image(head) or "image/png"
    except Exception:
        pass
    return "image/png"


def _read_base64(path: str) -> str | None:
    try:
        if os.path.getsize(path) > _MAX_VISION_BYTES:
            return None
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("ascii")
    except Exception:
        return None


def _handle_chat(h, stream: bool = True):
    try:
        length = int(h.headers.get("Content-Length", "0"))
        body = h.rfile.read(length).decode("utf-8")
        data = json.loads(body)
        text = data.get("text", data.get("task", ""))
        session = data.get("session", "default")
        attachments = data.get("attachments", None)
        kernel = data.get("kernel", "")  # 手动覆盖执行器：""=自动, "hermes" 或 "grok_build"
        # 请求体可显式声明是否走 SSE：{"stream": false} → 一次性 JSON 返回。
        # 此前该字段被忽略，导致所有客户端（含自动化测试/脚本调用）恒收到 text/event-stream，
        # JSON 解析必然失败。契约以 body 为准，缺省沿用路由默认值。
        if isinstance(data.get("stream"), bool):
            stream = data["stream"]
    except Exception:
        h._json_response(400, {"error": "无效请求体，需要 JSON: {\"text\": \"...\"}"})
        return

    if not text:
        h._json_response(400, {"error": "text 不能为空"})
        return

    engine = get_engine()

    # ── @file: 前缀解析：分图片 / 文本两类处理 ──
    # 图片 + 当前模型支持视觉 → 构造多模态 vision_parts（不进文本）
    # 图片 + 不支持视觉   → 仅作附件记录（模型看不见图）
    # 文本文件            → 读取内容注入 prompt（原行为）
    _file_refs = _re.findall(r'@file:(\S+)', text)
    text_contexts: list[str] = []
    image_refs: list[str] = []
    active = engine.model_registry.active() if hasattr(engine, "model_registry") else None
    model_vision = bool(active.is_vision()) if active else False

    for fp in _file_refs[:8]:
        if _is_image_file(fp):
            if model_vision:
                image_refs.append(fp)
            else:
                text_contexts.append(
                    f"[图片: {fp}（当前模型不支持视觉，已作为附件记录，模型无法看见图片内容）]"
                )
        else:
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    content = f.read(4096)
                text_contexts.append(f"[文件: {fp}]\n{content}")
            except Exception:
                text_contexts.append(f"[文件: {fp} - 无法读取]")

    vision_parts = None
    if image_refs:
        # 从 prompt 中剥离已转为视觉的图片 @file: 引用
        for fp in image_refs:
            text = _re.sub(r'@file:' + _re.escape(fp) + r'\S*', "", text).strip()
            text = _re.sub(r'@file:' + _re.escape(fp) + r'$', "", text).strip()
        text = text.strip()
        parts: list[dict] = []
        if text:
            parts.append({"type": "text", "text": text})
        for fp in image_refs:
            b64 = _read_base64(fp)
            if b64:
                parts.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{_image_mime(fp)};base64,{b64}"},
                })
        if parts:
            vision_parts = parts

    if text_contexts:
        text = "\n\n".join(text_contexts) + "\n\n---\n" + text

    if stream:
        with _CHAT_SEM:
            h._sse_response(engine, text, session, attachments, kernel_override=kernel, vision_parts=vision_parts)
    else:
        chunks = []
        errors = []
        with _CHAT_SEM:
            for ev in engine.chat(text, session, attachments=attachments, kernel_override=kernel, vision_parts=vision_parts):
                if ev.get("type") == "answer":
                    chunks.append(ev.get("answer", ""))
                elif ev.get("type") == "token":
                    chunks.append(ev.get("text", ""))
                elif ev.get("type") == "error":
                    errors.append(ev.get("error", ""))
                elif ev.get("type") == "approval":
                    errors.append(f"[需审批] {ev.get('message', ev.get('action', ''))}")
        payload = {"answer": "".join(chunks), "session": session}
        if errors:
            payload["errors"] = errors
        h._json_response(200, payload)

def register(router) -> None:
    router.add("POST", "/api/chat", _handle_chat)
    router.add("POST", "/api/chat/send", _handle_chat)
