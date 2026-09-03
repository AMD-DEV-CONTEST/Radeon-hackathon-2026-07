#!/usr/bin/env python3
"""Minimal localhost-only OpenAI-compatible preview server for a PEFT adapter.

This is deliberately a preview service rather than the competition deployment:
it lets the local YIJIAN workbench exercise the freshly trained BF16 adapter
without overwriting the stable 27B service.  It exposes only /health,
/v1/models and /v1/chat/completions on loopback.
"""

from __future__ import annotations

import argparse
import json
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-model", required=True)
    parser.add_argument("--adapter", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8083)
    parser.add_argument("--alias", default="YIJIAN-Qwen3-14B-LoRA-preview")
    return parser.parse_args()


class PreviewModel:
    def __init__(self, args: argparse.Namespace) -> None:
        self.alias = args.alias
        self.tokenizer = AutoTokenizer.from_pretrained(args.adapter, trust_remote_code=True)
        base = AutoModelForCausalLM.from_pretrained(
            args.base_model,
            torch_dtype=torch.bfloat16,
            device_map="cuda",
            trust_remote_code=True,
        )
        self.model = PeftModel.from_pretrained(base, args.adapter)
        self.model.eval()

    @torch.inference_mode()
    def complete(self, payload: dict) -> dict:
        messages = payload.get("messages") or []
        if not isinstance(messages, list) or not messages:
            raise ValueError("messages must be a non-empty list")
        normalized = []
        for message in messages:
            if not isinstance(message, dict):
                continue
            role = str(message.get("role") or "user")
            content = message.get("content") or ""
            if isinstance(content, list):
                content = "\n".join(
                    str(part.get("text") or "") for part in content if isinstance(part, dict)
                )
            normalized.append({"role": role, "content": str(content)})
        if not normalized:
            raise ValueError("no usable messages")

        inputs = self.tokenizer.apply_chat_template(
            normalized,
            add_generation_prompt=True,
            enable_thinking=False,
            return_tensors="pt",
            return_dict=True,
        )
        inputs = {key: value.to(self.model.device) for key, value in inputs.items()}
        # The workbench asks for up to 640 tokens because its stable 27B can
        # afford lengthy prose.  This direct Transformers preview is for
        # interactive review on one W7900: a compact, evidence-first answer is
        # both more readable and avoids leaving a player waiting a minute.
        max_tokens = min(max(int(payload.get("max_tokens") or 256), 1), 256)
        temperature = float(payload.get("temperature") or 0.0)
        generation = self.model.generate(
            **inputs,
            max_new_tokens=max_tokens,
            use_cache=True,
            repetition_penalty=1.05,
            do_sample=temperature > 0,
            temperature=max(temperature, 0.01) if temperature > 0 else None,
            top_p=0.9 if temperature > 0 else None,
            pad_token_id=self.tokenizer.eos_token_id,
            eos_token_id=self.tokenizer.eos_token_id,
        )
        new_tokens = generation[0][inputs["input_ids"].shape[-1] :]
        content = self.tokenizer.decode(new_tokens, skip_special_tokens=True).strip()
        return {
            "id": f"yijian-lora-preview-{int(time.time() * 1000)}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": self.alias,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }],
            "usage": {
                "prompt_tokens": int(inputs["input_ids"].shape[-1]),
                "completion_tokens": int(new_tokens.shape[-1]),
                "total_tokens": int(generation.shape[-1]),
            },
        }


def make_handler(service: PreviewModel):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, _format: str, *_args) -> None:
            return

        def send_json(self, status: int, value: dict) -> None:
            body = json.dumps(value, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/health":
                self.send_json(HTTPStatus.OK, {"status": "ok", "model": service.alias})
            elif self.path == "/v1/models":
                self.send_json(HTTPStatus.OK, {
                    "object": "list",
                    "data": [{"id": service.alias, "object": "model", "owned_by": "yijian"}],
                })
            else:
                self.send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/v1/chat/completions":
                self.send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                self.send_json(HTTPStatus.OK, service.complete(payload))
            except Exception as exc:  # The client needs a useful JSON error, never a traceback.
                self.send_json(HTTPStatus.BAD_REQUEST, {"error": {"message": str(exc)}})

    return Handler


def main() -> None:
    args = parse_args()
    print("Loading base model and YIJIAN LoRA adapter…", flush=True)
    service = PreviewModel(args)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(service))
    print(f"YIJIAN LoRA preview ready on http://{args.host}:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
