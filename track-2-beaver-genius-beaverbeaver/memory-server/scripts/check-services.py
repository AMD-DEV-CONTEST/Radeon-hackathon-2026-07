#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
import base64
import json
import struct
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class Service:
    name: str
    url: str
    api_key: str = ""
    required: bool = True
    payload: dict[str, object] | None = None


def _env(name: str, default: str = "") -> str:
    """Read the canonical name, falling back to the legacy GLASS_ alias."""
    return os.getenv(name, os.getenv(f"GLASS_{name}", default))


def _enabled(name: str, default: bool = True) -> bool:
    value = _env(name)
    if not value:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _join(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def _models_url(endpoint: str) -> str:
    parsed = urlsplit(endpoint)
    parts = [part for part in parsed.path.split("/") if part]
    if "v1" in parts:
        parts = parts[: parts.index("v1") + 1]
    else:
        parts = []
    path = "/" + "/".join([*parts, "models"])
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def configured_services() -> list[Service]:
    embedding_key = _env("MEMORY_SEARCH_EMBEDDING_API_KEY")
    reranker_key = _env("MEMORY_SEARCH_RERANKER_API_KEY")
    silence_wav = (
        b"RIFF" + struct.pack("<I", 36 + 3200) + b"WAVEfmt "
        + struct.pack("<IHHIIHH", 16, 1, 1, 16000, 32000, 2, 16)
        + b"data" + struct.pack("<I", 3200) + bytes(3200)
    )
    services = [
        Service(
            "EverOS",
            _join(_env("EVEROS_BASE_URL"), "/health")
            if _env("EVEROS_BASE_URL")
            else "",
        ),
        Service(
            "Qwen-Text",
            _join(_env("MEMORY_CONTEXT_BASE_URL"), "/chat/completions")
            if _env("MEMORY_CONTEXT_BASE_URL")
            else "",
            _env("MEMORY_CONTEXT_API_KEY"),
            _enabled("MEMORY_CONTEXT_ENABLED"),
            {
                "model": _env("MEMORY_CONTEXT_MODEL"),
                "messages": [{"role": "user", "content": "只回答OK"}],
                "max_tokens": 4,
                "enable_thinking": False,
            },
        ),
        Service(
            "Qwen-Omni",
            _join(_env("MEMORY_SCENE_BASE_URL"), "/chat/completions")
            if _env("MEMORY_SCENE_BASE_URL")
            else "",
            _env("MEMORY_SCENE_API_KEY"),
            True,
            {
                "model": _env("MEMORY_SCENE_MODEL"),
                "messages": [{"role": "user", "content": "只回答OK"}],
                "modalities": ["text"],
                "stream": True,
                "max_tokens": 4,
            },
        ),
        Service(
            "ASR",
            _env("MEMORY_ASR_BASE_URL"),
            _env("MEMORY_ASR_API_KEY"),
            True,
            {
                "model": _env("MEMORY_ASR_MODEL"),
                "input": {"messages": [{"role": "user", "content": [{
                    "type": "input_audio",
                    "input_audio": {"data": "data:audio/wav;base64," + base64.b64encode(silence_wav).decode("ascii")},
                }]}]},
                "parameters": {"format": "wav", "sample_rate": "16000"},
            },
        ),
        Service(
            "Embedding",
            _env("MEMORY_SEARCH_EMBEDDING_URL"),
            embedding_key,
            True,
            {
                "model": _env("MEMORY_SEARCH_EMBEDDING_MODEL"),
                "input": {"contents": [{"text": "健康检查"}]},
                "parameters": {"dimension": 1024},
            },
        ),
        Service(
            "Reranking",
            _env("MEMORY_SEARCH_RERANKER_URL"),
            reranker_key,
            True,
            {
                "model": _env("MEMORY_SEARCH_RERANKER_MODEL"),
                "input": {
                    "query": {"text": "健康检查"},
                    "documents": [{"text": "系统健康检查"}],
                },
                "parameters": {"return_documents": True, "top_n": 1},
            },
        ),
        Service(
            "YOLOE",
            _join(_env("OBJECT_PERCEPTION_BASE_URL"), "/health")
            if _env("OBJECT_PERCEPTION_BASE_URL")
            else "",
            _env("OBJECT_PERCEPTION_API_KEY"),
            _enabled("OBJECT_PERCEPTION_ENABLED"),
        ),
        Service(
            "Face",
            _join(_env("IDENTITY_BASE_URL"), "/health")
            if _env("IDENTITY_BASE_URL")
            else "",
            _env("IDENTITY_API_KEY"),
            _enabled("IDENTITY_PERCEPTION_ENABLED"),
        ),
        Service(
            "Voice",
            _join(_env("VOICE_BASE_URL"), "/health")
            if _env("VOICE_BASE_URL")
            else "",
            _env("VOICE_API_KEY"),
            _enabled("VOICE_PERCEPTION_ENABLED"),
        ),
    ]
    return services


def check(service: Service, *, timeout: float) -> tuple[str, str]:
    if not service.required:
        return "DISABLED", "not required"
    if not service.url:
        return "UNCONFIGURED", "missing URL"
    headers = {"Accept": "application/json", "User-Agent": "beaver-memory-check/1"}
    if service.api_key:
        headers["Authorization"] = f"Bearer {service.api_key}"
    body = (
        json.dumps(service.payload, ensure_ascii=False).encode("utf-8")
        if service.payload is not None
        else None
    )
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = Request(
        service.url,
        data=body,
        headers=headers,
        method="POST" if body is not None else "GET",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            status = int(response.status)
        if 200 <= status < 300:
            return "READY", f"HTTP {status}"
        return "DEGRADED", f"HTTP {status}"
    except HTTPError as exc:
        return "DEGRADED", f"HTTP {exc.code}"
    except (URLError, TimeoutError, OSError) as exc:
        return "DEGRADED", type(exc).__name__


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Beaver Memory external service readiness"
    )
    parser.add_argument("--timeout", type=float, default=5.0)
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")

    failed = False
    for service in configured_services():
        status, detail = check(service, timeout=args.timeout)
        print(f"{status:<12} {service.name:<12} {detail}")
        if service.required and status != "READY":
            failed = True
    return 2 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
