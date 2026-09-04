#!/usr/bin/env python3
"""Smoke-test the local vLLM OpenAI-compatible endpoint."""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.policy.local_only import (  # noqa: E402
    local_api_url,
    require_local_vllm_base_url,
)


def request_json(
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout: int = 300,
) -> tuple[dict[str, Any], float]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        local_api_url(path),
        data=body,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=timeout) as response:
        result = json.loads(response.read().decode("utf-8"))
    return result, time.perf_counter() - started


def model_name() -> str:
    payload, _ = request_json("GET", "/models", timeout=30)
    models = payload.get("data") or []
    if not models or not models[0].get("id"):
        raise AssertionError("/v1/models returned no model id")
    return str(models[0]["id"])


def content_from(response: dict[str, Any]) -> str:
    try:
        return str(response["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError) as exc:
        raise AssertionError(f"Unexpected chat response: {response}") from exc


def strict_json_from(text: str) -> Any:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        starts = [position for position in (stripped.find("{"), stripped.find("[")) if position >= 0]
        if not starts:
            raise
        start = min(starts)
        for end in range(len(stripped), start, -1):
            try:
                return json.loads(stripped[start:end])
            except json.JSONDecodeError:
                continue
        raise


def data_url(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(path)
    mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def chat(model: str, messages: list[dict[str, Any]], max_tokens: int) -> tuple[str, float]:
    response, latency = request_json(
        "POST",
        "/chat/completions",
        {
            "model": model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": max_tokens,
        },
    )
    return content_from(response), latency


def run_models() -> dict[str, Any]:
    payload, latency = request_json("GET", "/models", timeout=30)
    if not payload.get("data"):
        raise AssertionError("No models returned")
    return {"latency_seconds": latency, "models": payload["data"]}


def run_text(model: str) -> dict[str, Any]:
    text, latency = chat(
        model,
        [
            {
                "role": "user",
                "content": (
                    '只输出严格 JSON：{"status":"ok","runtime":"local-vllm"}。'
                    "不要使用 Markdown。"
                ),
            }
        ],
        64,
    )
    parsed = strict_json_from(text)
    if parsed.get("status") != "ok":
        raise AssertionError(f"Unexpected text JSON: {parsed}")
    return {"latency_seconds": latency, "parsed": parsed, "raw": text}


def run_image(model: str, image_path: Path) -> dict[str, Any]:
    text, latency = chat(
        model,
        [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "观察图片，只输出严格 JSON，不要 Markdown。格式："
                            '{"summary":"一句中文描述","visible_objects":["对象"],'
                            '"uncertainty":"无法确认的内容"}'
                        ),
                    },
                    {"type": "image_url", "image_url": {"url": data_url(image_path)}},
                ],
            }
        ],
        256,
    )
    parsed = strict_json_from(text)
    required = {"summary", "visible_objects", "uncertainty"}
    if not required.issubset(parsed):
        raise AssertionError(f"Missing image JSON fields: {required - set(parsed)}")
    return {
        "image": str(image_path),
        "latency_seconds": latency,
        "parsed": parsed,
        "raw": text,
    }


def frame_paths(directory: Path) -> list[Path]:
    supported = {".jpg", ".jpeg", ".png", ".webp"}
    paths = sorted(
        path for path in directory.iterdir() if path.is_file() and path.suffix.lower() in supported
    )
    if len(paths) != 8:
        raise AssertionError(f"Expected exactly 8 frame images, found {len(paths)}")
    return paths


def run_frames(model: str, directory: Path) -> dict[str, Any]:
    paths = frame_paths(directory)
    content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": (
                "以下八张图片按时间先后排列。只输出严格 JSON，不要 Markdown。格式："
                '{"frames":[{"index":1,"observation":"可见事实",'
                '"uncertainty":"不确定点"}],"temporal_summary":"时序变化摘要"}。'
                "frames 必须恰好八项；只描述可见事实，不猜测责任。"
            ),
        }
    ]
    for path in paths:
        content.append({"type": "image_url", "image_url": {"url": data_url(path)}})

    text, latency = chat(model, [{"role": "user", "content": content}], 1024)
    parsed = strict_json_from(text)
    frames = parsed.get("frames")
    if not isinstance(frames, list) or len(frames) != 8:
        raise AssertionError("Temporal JSON must contain exactly 8 frame entries")
    if not parsed.get("temporal_summary"):
        raise AssertionError("Temporal JSON lacks temporal_summary")
    return {
        "frames": [str(path) for path in paths],
        "latency_seconds": latency,
        "parsed": parsed,
        "raw": text,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("test", choices=("models", "text", "image", "frames"))
    parser.add_argument("--image-path", type=Path)
    parser.add_argument("--frames-dir", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts"))
    args = parser.parse_args()

    require_local_vllm_base_url()
    started = datetime.now(timezone.utc)
    record: dict[str, Any] = {
        "test": args.test,
        "started_at_utc": started.isoformat(),
        "endpoint": require_local_vllm_base_url(),
        "status": "failed",
        "failure_reason": "",
        "next_step": "",
    }

    try:
        model = model_name()
        record["model"] = model
        if args.test == "models":
            record["result"] = run_models()
        elif args.test == "text":
            record["result"] = run_text(model)
        elif args.test == "image":
            if args.image_path is None:
                parser.error("--image-path is required for image")
            record["result"] = run_image(model, args.image_path)
        else:
            if args.frames_dir is None:
                parser.error("--frames-dir is required for frames")
            record["result"] = run_frames(model, args.frames_dir)
        record["status"] = "passed"
    except Exception as exc:  # noqa: BLE001 - every smoke-test failure must be logged
        record["failure_reason"] = repr(exc)
        record["next_step"] = (
            "Inspect the vLLM log and environment fingerprint; record this attempt "
            "with scripts/model_gate.py."
        )

    record["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = args.output_dir / (
        f"smoke-{args.test}-{started.strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    output.write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(record, ensure_ascii=False, indent=2))
    print(f"Saved result: {output.resolve()}")
    return 0 if record["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
