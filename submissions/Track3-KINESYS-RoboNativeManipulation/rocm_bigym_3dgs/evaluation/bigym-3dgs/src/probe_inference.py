#!/usr/bin/env python3
"""Dependency-free health and multipart contract probe for /process_frame."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import struct
import time
import urllib.request
import uuid
import zlib


def png_rgb(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
    signature = b"\x89PNG\r\n\x1a\n"

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    raw = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))
    return (
        signature
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, level=6))
        + chunk(b"IEND", b"")
    )


def multipart(fields: dict[str, str], images: list[bytes]) -> tuple[bytes, str]:
    boundary = f"amd-bigym-inference-{uuid.uuid4().hex}"
    body = bytearray()
    for name, value in fields.items():
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        body.extend(value.encode())
        body.extend(b"\r\n")
    for index, payload in enumerate(images):
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(
            (
                'Content-Disposition: form-data; name="image"; '
                f'filename="camera-{index}.png"\r\n'
            ).encode()
        )
        body.extend(b"Content-Type: image/png\r\n\r\n")
        body.extend(payload)
        body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode())
    return bytes(body), f"multipart/form-data; boundary={boundary}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    with urllib.request.urlopen(f"{base_url}/health", timeout=10) as response:
        health_status = response.status
        health = json.loads(response.read())
    identity = health.get("policy_identity") if isinstance(health, dict) else None
    if (
        not isinstance(health, dict)
        or health.get("status") != "ok"
        or health.get("protocol_version") != 2
        or not isinstance(identity, dict)
        or any(
            not identity.get(key)
            for key in (
                "provider",
                "model_id",
                "model_revision",
                "adapter_source_sha256",
            )
        )
    ):
        raise SystemExit(f"inference health does not implement protocol v2: {health!r}")

    request_id = uuid.uuid4().hex
    images = [
        png_rgb(224, 224, (96, 112, 128)),
        png_rgb(224, 224, (128, 96, 112)),
        png_rgb(224, 224, (112, 128, 96)),
    ]
    payload, content_type = multipart(
        {
            "text": "Unload cutlery from dishwasher to drawer task.",
            "states": json.dumps([0.0] * 16),
            "request_id": request_id,
        },
        images,
    )
    request = urllib.request.Request(
        f"{base_url}/process_frame",
        data=payload,
        headers={"Content-Type": content_type},
        method="POST",
    )
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=180) as response:
        infer_status = response.status
        result = json.loads(response.read())
    latency_ms = (time.perf_counter() - started) * 1000.0

    actions = result.get("response")
    if result.get("request_id") != request_id:
        raise SystemExit("inference response did not echo request_id")
    if not isinstance(actions, list) or len(actions) != 10:
        raise SystemExit(f"expected action chunk 10x16, got {type(actions).__name__}")
    if any(not isinstance(row, list) or len(row) != 16 for row in actions):
        raise SystemExit("action row does not have 16 values")
    if any(not math.isfinite(float(value)) for row in actions for value in row):
        raise SystemExit("action response contains non-finite values")
    required_timings = (
        "image_decode",
        "policy_infer",
        "total_before_serialize",
        "serialization_first_pass",
        "server_total_before_final_serialize",
    )
    timings = result.get("timing_ms")
    if not isinstance(timings, dict) or any(
        not isinstance(timings.get(key), (int, float)) for key in required_timings
    ):
        raise SystemExit(f"inference response timing contract is incomplete: {timings!r}")

    receipt = {
        "status": "inference_contract_passed",
        "health_http_status": health_status,
        "health": health,
        "infer_http_status": infer_status,
        "latency_ms": latency_ms,
        "request_id": request_id,
        "server_timing_ms": timings,
        "action_chunk_shape": [len(actions), len(actions[0])],
        "request": {
            "state_dim": 16,
            "camera_count": 3,
            "camera_image_shape": [224, 224, 3],
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
