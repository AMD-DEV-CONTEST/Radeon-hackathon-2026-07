#!/usr/bin/env python3
"""Serve the optimized DM0.5 policy through the BiGym inference v2 contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from collections.abc import Callable
from email import policy as email_policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, HTTPServer
from io import BytesIO
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

CAMERA_KEYS = ("camera_top", "camera_wrist_left", "camera_wrist_right")
MAX_REQUEST_BYTES = 32 * 1024 * 1024
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class RequestError(ValueError):
    """A client request violates the inference v2 wire contract."""


def parse_multipart(
    content_type: str, body: bytes
) -> tuple[dict[str, str], list[bytes]]:
    header = (f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n").encode(
        "ascii"
    )
    message = BytesParser(policy=email_policy.default).parsebytes(header + body)
    if not message.is_multipart():
        raise RequestError("request must use multipart/form-data")

    fields: dict[str, str] = {}
    images: list[bytes] = []
    for part in message.iter_parts():
        if part.get_content_disposition() != "form-data":
            continue
        name = part.get_param("name", header="content-disposition")
        payload = part.get_payload(decode=True) or b""
        if name == "image":
            images.append(payload)
        elif name in {"text", "states", "request_id"}:
            charset = part.get_content_charset() or "utf-8"
            fields[name] = payload.decode(charset)
    return fields, images


def decode_request(
    content_type: str, body: bytes
) -> tuple[str, str, np.ndarray, dict[str, np.ndarray], float]:
    decode_started = time.perf_counter()
    fields, image_payloads = parse_multipart(content_type, body)
    request_id = fields.get("request_id", "")
    if not request_id:
        raise RequestError("request_id is required")
    prompt = fields.get("text", "")
    try:
        state = np.asarray(json.loads(fields.get("states", "[]")), dtype=np.float32)
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        raise RequestError(f"states is not valid JSON: {error}") from error
    if state.shape != (16,) or not np.isfinite(state).all():
        raise RequestError(f"states must contain 16 finite numbers, got {state.shape}")
    if len(image_payloads) != 3:
        raise RequestError(f"expected three image fields, got {len(image_payloads)}")

    images: dict[str, np.ndarray] = {}
    for name, payload in zip(CAMERA_KEYS, image_payloads, strict=True):
        try:
            with Image.open(BytesIO(payload)) as decoded:
                images[name] = np.asarray(decoded.convert("RGB"), dtype=np.uint8).copy()
        except Exception as error:
            raise RequestError(f"invalid {name} image: {error}") from error
    decode_ms = (time.perf_counter() - decode_started) * 1000.0
    return request_id, prompt, state, images, decode_ms


class ProviderApp:
    def __init__(
        self,
        infer: Callable[[dict[str, Any], str], np.ndarray],
        identity: dict[str, str],
        response_actions: int = 10,
    ):
        self.infer = infer
        self.identity = identity
        self.response_actions = response_actions

    def health(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "protocol_version": 2,
            "backend": "pytorch-rocm",
            "policy_identity": self.identity,
        }

    def process(self, content_type: str, body: bytes) -> dict[str, Any]:
        request_started = time.perf_counter()
        request_id, prompt, state, images, decode_ms = decode_request(
            content_type, body
        )
        infer_started = time.perf_counter()
        actions = np.asarray(
            self.infer({"state": state, **images}, prompt), dtype=np.float32
        )
        infer_ms = (time.perf_counter() - infer_started) * 1000.0
        if actions.ndim != 2 or actions.shape[1] != 16:
            raise RuntimeError(
                f"policy actions must have shape (N, 16), got {actions.shape}"
            )
        if actions.shape[0] < self.response_actions:
            raise RuntimeError(
                f"policy returned {actions.shape[0]} actions; "
                f"protocol requires {self.response_actions}"
            )
        actions = actions[: self.response_actions]
        if not np.isfinite(actions).all():
            raise RuntimeError("policy returned non-finite actions")

        response: dict[str, Any] = {
            "request_id": request_id,
            "response": actions.tolist(),
            "timing_ms": {
                "image_decode": decode_ms,
                "policy_infer": infer_ms,
                "total_before_serialize": (time.perf_counter() - request_started)
                * 1000.0,
                "serialization_first_pass": 0.0,
                "server_total_before_final_serialize": 0.0,
            },
        }
        serialize_started = time.perf_counter()
        json.dumps(response, allow_nan=False)
        response["timing_ms"]["serialization_first_pass"] = (
            time.perf_counter() - serialize_started
        ) * 1000.0
        response["timing_ms"]["server_total_before_final_serialize"] = (
            time.perf_counter() - request_started
        ) * 1000.0
        return response


def handler_for(app: ProviderApp) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def write_json(self, status: int, payload: dict[str, Any]) -> None:
            encoded = json.dumps(payload, allow_nan=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def do_GET(self) -> None:
            if self.path != "/health":
                self.write_json(404, {"error": "not found"})
                return
            self.write_json(200, app.health())

        def do_POST(self) -> None:
            if self.path != "/process_frame":
                self.write_json(404, {"error": "not found"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > MAX_REQUEST_BYTES:
                    raise RequestError("invalid Content-Length")
                payload = app.process(
                    self.headers.get("Content-Type", ""), self.rfile.read(length)
                )
                self.write_json(200, payload)
            except RequestError as error:
                self.write_json(400, {"error": str(error)})
            except Exception as error:  # noqa: BLE001 - return protocol JSON on faults.
                self.write_json(500, {"error": f"{type(error).__name__}: {error}"})

        def log_message(self, format_string: str, *args: Any) -> None:
            print(
                f"{self.address_string()} [{self.log_date_time_string()}] "
                + format_string % args,
                flush=True,
            )

    return Handler


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--model-revision", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7891)
    parser.add_argument("--chunk-size", type=int, default=16)
    parser.add_argument("--response-actions", type=int, default=10)
    parser.add_argument("--diffusion-steps", type=int, default=10)
    parser.add_argument("--model-max-length", type=int, default=896)
    parser.add_argument(
        "--prompt", default="Unload cutlery from dishwasher to drawer task."
    )
    parser.add_argument(
        "--reuse-kv-workspace",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    lora = parser.add_mutually_exclusive_group()
    lora.add_argument(
        "--use-lora-wrapper", dest="use_lora_wrapper", action="store_true"
    )
    lora.add_argument(
        "--no-lora-wrapper", dest="use_lora_wrapper", action="store_false"
    )
    parser.set_defaults(use_lora_wrapper=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    model_path = args.model_path.expanduser().resolve()
    if not model_path.is_dir():
        raise NotADirectoryError(model_path)
    if args.chunk_size < args.response_actions or args.response_actions != 10:
        raise ValueError(
            "inference v2 requires 10 response actions and chunk-size >= 10"
        )

    from opendm_policy import OpenDMPolicy

    provider = OpenDMPolicy(
        model_path=model_path,
        chunk_size=args.chunk_size,
        prompt=args.prompt,
        diffusion_steps=args.diffusion_steps,
        model_max_length=args.model_max_length,
        use_lora_wrapper=args.use_lora_wrapper,
        reuse_kv_workspace=args.reuse_kv_workspace,
    )
    source_sha256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    if not SHA256_PATTERN.fullmatch(source_sha256):
        raise RuntimeError("failed to calculate adapter source SHA-256")
    identity = {
        "provider": "opendm-dm05",
        "model_id": args.model_id,
        "model_revision": args.model_revision,
        "adapter_source_sha256": source_sha256,
    }
    app = ProviderApp(provider.infer, identity, args.response_actions)
    server = HTTPServer((args.host, args.port), handler_for(app))
    print(
        json.dumps(
            {
                "status": "ready",
                "listen": f"http://{args.host}:{args.port}",
                "policy_identity": identity,
            }
        ),
        flush=True,
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
