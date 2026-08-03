# -*- coding: utf-8 -*-
"""Server-side APIMart media gateway for the Yijian asset workshop.

The browser never receives the provider token.  This module intentionally keeps
the request surface small and model names allow-listed so the local UI cannot be
used as an unrestricted proxy.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


DEFAULT_BASE_URL = "https://api.apimart.ai/v1"
TASK_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,160}$")
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _load_local_env() -> None:
    """Load the project's ignored .env.local without an extra dependency."""
    path = os.path.join(PROJECT_ROOT, ".env.local")
    if not os.path.isfile(path):
        return
    with open(path, "r", encoding="utf-8-sig") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            name = name.strip()
            value = value.strip().strip('"').strip("'")
            if name and name not in os.environ:
                os.environ[name] = value


_load_local_env()

MODEL_CATALOG = [
    {"id": "gpt-image-2", "kind": "image", "label": "GPT Image 2", "tier": "精修"},
    {
        "id": "gpt-image-1.5-official",
        "kind": "image",
        "label": "GPT Image 1.5 Official",
        "tier": "精修",
    },
    {
        "id": "gemini-3-pro-image-preview",
        "kind": "image",
        "label": "Gemini 3 Pro Image Preview",
        "tier": "构图",
    },
    {
        "id": "gemini-3.1-flash-image-preview",
        "kind": "image",
        "label": "Gemini 3.1 Flash Image Preview",
        "tier": "迭代",
    },
    {
        "id": "gemini-2.5-flash-image-preview",
        "kind": "image",
        "label": "Gemini 2.5 Flash Image Preview",
        "tier": "迭代",
    },
    {
        "id": "doubao-seedream-5-0-pro",
        "kind": "image",
        "label": "Seedream 5.0 Pro",
        "tier": "一致性",
    },
    {
        "id": "doubao-seedream-5-0-lite",
        "kind": "image",
        "label": "Seedream 5.0 Lite",
        "tier": "草图",
    },
    {"id": "wan2.7-image", "kind": "image", "label": "Wan 2.7 Image", "tier": "场景"},
    {"id": "midjourney", "kind": "image", "label": "Midjourney", "tier": "概念"},
    {
        "id": "imagen-4.0-apimart",
        "kind": "image",
        "label": "Imagen 4.0",
        "tier": "写实",
    },
    {
        "id": "grok-imagine-1.5-edit-apimart",
        "kind": "image",
        "label": "Grok Imagine 1.5 Edit",
        "tier": "编辑",
    },
    {"id": "qwen-image-2.0", "kind": "image", "label": "Qwen Image 2.0", "tier": "中文"},
    {"id": "z-image-turbo", "kind": "image", "label": "Z Image Turbo", "tier": "草图"},
    {
        "id": "flux-kontext-max",
        "kind": "image",
        "label": "Flux Kontext Max",
        "tier": "编辑",
    },
    {"id": "flux-2-flex", "kind": "image", "label": "Flux 2 Flex", "tier": "迭代"},
    {
        "id": "doubao-seedance-4-5",
        "kind": "video",
        "label": "Seedance 4.5",
        "tier": "运镜",
    },
    {
        "id": "doubao-seedance-4-0",
        "kind": "video",
        "label": "Seedance 4.0",
        "tier": "运镜",
    },
]

MODELS_BY_ID = {item["id"]: item for item in MODEL_CATALOG}


class MediaGatewayError(RuntimeError):
    def __init__(self, status_code: int, message: str, detail: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail


def _api_key() -> str:
    _load_local_env()
    value = os.getenv("APIMART_API_KEY", "").strip()
    if not value:
        raise MediaGatewayError(
            503,
            "APIMART_API_KEY 未配置。请把 Key 写入后端进程环境变量后重启服务。",
        )
    return value


def _base_url() -> str:
    _load_local_env()
    value = os.getenv("APIMART_BASE_URL", DEFAULT_BASE_URL).strip().rstrip("/")
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise MediaGatewayError(500, "APIMART_BASE_URL 必须是有效的 HTTPS 地址。")
    return value


def status() -> dict[str, Any]:
    _load_local_env()
    configured = bool(os.getenv("APIMART_API_KEY", "").strip())
    parsed = urllib.parse.urlparse(
        os.getenv("APIMART_BASE_URL", DEFAULT_BASE_URL).strip()
    )
    return {
        "provider": "APIMart",
        "configured": configured,
        "host": parsed.netloc or "api.apimart.ai",
        "secretLocation": "server-env",
    }


def _provider_request(
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = None
    headers = {
        "Authorization": f"Bearer {_api_key()}",
        "Accept": "application/json",
    }
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"

    timeout = min(max(int(os.getenv("APIMART_TIMEOUT_SECONDS", "60")), 5), 180)
    request = urllib.request.Request(
        f"{_base_url()}{path}",
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            return json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(raw)
        except json.JSONDecodeError:
            detail = {"message": raw[:600]}
        message = (
            detail.get("error", {}).get("message")
            if isinstance(detail, dict)
            else None
        ) or f"APIMart 请求失败（HTTP {exc.code}）"
        raise MediaGatewayError(exc.code, message, detail) from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise MediaGatewayError(502, f"无法连接 APIMart：{exc}") from exc


def _compact(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if value is not None and value != "" and value != []
    }


def _validate_media_ref(value: str) -> str:
    if len(value) > 7_000_000:
        raise MediaGatewayError(413, "单张参考图过大，请压缩到约 5 MB 以内。")
    if value.startswith("data:image/"):
        return value
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise MediaGatewayError(400, "参考图必须是 HTTP(S) URL 或 image Data URL。")
    return value


def submit(request_data: dict[str, Any]) -> dict[str, Any]:
    model_id = request_data["model"]
    kind = request_data["kind"]
    model = MODELS_BY_ID.get(model_id)
    if not model or model["kind"] != kind:
        raise MediaGatewayError(400, "模型不在当前素材工坊白名单中。")

    common = {
        "model": model_id,
        "prompt": request_data["prompt"].strip(),
        "negative_prompt": request_data.get("negativePrompt"),
        "seed": request_data.get("seed"),
    }
    image_urls = [
        _validate_media_ref(value)
        for value in (request_data.get("imageUrls") or [])
    ]
    last_frame_url = request_data.get("lastFrameUrl")
    if last_frame_url:
        last_frame_url = _validate_media_ref(last_frame_url)

    if kind == "image":
        payload = {
            **common,
            "n": request_data.get("n", 1),
            "size": request_data.get("size", "16:9"),
            "resolution": request_data.get("resolution", "2k"),
            "image_urls": image_urls,
        }
        path = "/images/generations"
    else:
        payload = {
            **common,
            "duration": request_data.get("duration", 5),
            "aspect_ratio": request_data.get("size", "16:9"),
            "resolution": request_data.get("resolution", "1080p"),
            "audio": request_data.get("audio", False),
            "image_urls": image_urls,
            "last_frame_image": last_frame_url,
        }
        path = "/videos/generations"

    result = _provider_request("POST", path, _compact(payload))
    task_id = None
    if isinstance(result.get("data"), list) and result["data"]:
        task_id = result["data"][0].get("task_id")
    return {
        "provider": "APIMart",
        "kind": kind,
        "model": model_id,
        "taskId": task_id,
        "upstream": result,
    }


def task(task_id: str) -> dict[str, Any]:
    if not TASK_ID_RE.fullmatch(task_id):
        raise MediaGatewayError(400, "任务 ID 格式无效。")
    return _provider_request(
        "GET",
        f"/tasks/{urllib.parse.quote(task_id)}?language=zh",
    )
