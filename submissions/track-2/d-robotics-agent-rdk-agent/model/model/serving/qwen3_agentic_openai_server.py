#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import logging
import re
import threading
import time
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer


LOGGER = logging.getLogger("qwen3-agentic-openai")
TOOL_CALL_PATTERN = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL)
THINK_PATTERN = re.compile(r"^\s*<think>.*?</think>\s*", re.DOTALL)
MAX_BODY_BYTES = 10 * 1024 * 1024
MAX_CONTEXT_TOKENS = 40960
MAX_COMPLETION_TOKENS = 4096
STREAM_CONTENT_CHARS = 64


def json_bytes(payload: Any) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def sse_bytes(payload: Any) -> bytes:
    return b"data: " + json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n\n"


def iter_stream_payloads(response: dict[str, Any], include_usage: bool) -> Any:
    choice = response["choices"][0]
    message = choice["message"]
    common = {
        "id": response["id"],
        "object": "chat.completion.chunk",
        "created": response["created"],
        "model": response["model"],
        "system_fingerprint": response.get("system_fingerprint"),
    }

    def chunk(delta: dict[str, Any], finish_reason: str | None = None) -> dict[str, Any]:
        return {
            **common,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason, "logprobs": None}],
        }

    yield chunk({"role": "assistant", "content": ""})
    tool_calls = message.get("tool_calls") or []
    if tool_calls:
        for index, tool_call in enumerate(tool_calls):
            yield chunk({
                "tool_calls": [{
                    "index": index,
                    "id": tool_call["id"],
                    "type": tool_call["type"],
                    "function": {
                        "name": tool_call["function"]["name"],
                        "arguments": tool_call["function"]["arguments"],
                    },
                }]
            })
    else:
        content = message.get("content") or ""
        for offset in range(0, len(content), STREAM_CONTENT_CHARS):
            yield chunk({"content": content[offset:offset + STREAM_CONTENT_CHARS]})
    yield chunk({}, choice["finish_reason"])
    if include_usage:
        yield {**common, "choices": [], "usage": response["usage"]}


def openai_error(message: str, error_type: str = "invalid_request_error", code: str | None = None, param: str | None = None) -> dict[str, Any]:
    return {"error": {"message": message, "type": error_type, "param": param, "code": code}}


def normalize_content(content: Any, message_index: int) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        raise ValueError(f"messages[{message_index}].content must be a string or text content-parts array")
    text_parts: list[str] = []
    for part_index, part in enumerate(content):
        if isinstance(part, str):
            text_parts.append(part)
            continue
        if not isinstance(part, dict):
            raise ValueError(f"messages[{message_index}].content[{part_index}] must be a text content part")
        part_type = part.get("type")
        if part_type not in ("text", "input_text") or not isinstance(part.get("text"), str):
            raise ValueError(
                f"messages[{message_index}].content[{part_index}] has unsupported type {part_type!r}; only text is supported"
            )
        text_parts.append(part["text"])
    return "".join(text_parts)


def normalize_messages(messages: Any) -> list[dict[str, Any]]:
    if not isinstance(messages, list) or not messages:
        raise ValueError("messages must be a non-empty array")
    normalized: list[dict[str, Any]] = []
    allowed = {"system", "user", "assistant", "tool"}
    for index, raw in enumerate(messages):
        if not isinstance(raw, dict):
            raise ValueError(f"messages[{index}] must be an object")
        role = raw.get("role")
        if role not in allowed:
            raise ValueError(f"messages[{index}].role is unsupported: {role!r}")
        item = dict(raw)
        item["content"] = normalize_content(item.get("content"), index)
        if role == "assistant" and "tool_calls" in item:
            if not isinstance(item["tool_calls"], list):
                raise ValueError(f"messages[{index}].tool_calls must be an array")
        if role == "tool" and not item.get("tool_call_id"):
            raise ValueError(f"messages[{index}].tool_call_id is required")
        normalized.append(item)
    return normalized


def normalize_tools(tools: Any) -> list[dict[str, Any]]:
    if tools is None:
        return []
    if not isinstance(tools, list):
        raise ValueError("tools must be an array")
    normalized: list[dict[str, Any]] = []
    names: set[str] = set()
    for index, raw in enumerate(tools):
        if not isinstance(raw, dict) or raw.get("type") != "function" or not isinstance(raw.get("function"), dict):
            raise ValueError(f"tools[{index}] must be an OpenAI function tool")
        function = dict(raw["function"])
        name = function.get("name")
        if not isinstance(name, str) or not name or name in names:
            raise ValueError(f"tools[{index}].function.name is missing or duplicated")
        names.add(name)
        parameters = function.get("parameters", {"type": "object", "properties": {}})
        if not isinstance(parameters, dict):
            raise ValueError(f"tools[{index}].function.parameters must be an object")
        function["parameters"] = parameters
        normalized.append({"type": "function", "function": function})
    return normalized


def prepare_tool_choice(messages: list[dict[str, Any]], tools: list[dict[str, Any]], tool_choice: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if tool_choice in (None, "auto"):
        return messages, tools
    if tool_choice == "none":
        return messages, []
    instruction: str
    selected = tools
    if tool_choice == "required":
        if not tools:
            raise ValueError("tool_choice='required' requires at least one tool")
        instruction = "You must call at least one provided tool for this request. Do not answer directly before calling a tool."
    elif isinstance(tool_choice, dict) and tool_choice.get("type") == "function" and isinstance(tool_choice.get("function"), dict):
        name = tool_choice["function"].get("name")
        selected = [tool for tool in tools if tool["function"]["name"] == name]
        if not selected:
            raise ValueError(f"tool_choice references unknown function: {name!r}")
        instruction = f"You must call the function {name!r} for this request."
    else:
        raise ValueError("unsupported tool_choice")
    updated = [dict(message) for message in messages]
    if updated and updated[0]["role"] == "system":
        updated[0]["content"] = (updated[0]["content"].rstrip() + "\n\n" + instruction).strip()
    else:
        updated.insert(0, {"role": "system", "content": instruction})
    return updated, selected


def parse_tool_calls(text: str, allowed_names: set[str]) -> tuple[str, list[dict[str, Any]]]:
    text = THINK_PATTERN.sub("", text, count=1)
    matches = TOOL_CALL_PATTERN.findall(text)
    tool_calls: list[dict[str, Any]] = []
    for raw in matches:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            LOGGER.warning("ignored malformed tool call JSON: %r", raw[:300])
            continue
        if not isinstance(payload, dict) or not isinstance(payload.get("name"), str):
            continue
        name = payload["name"]
        if allowed_names and name not in allowed_names:
            LOGGER.warning("model requested undeclared tool: %s", name)
            continue
        arguments = payload.get("arguments", {})
        if isinstance(arguments, str):
            try:
                parsed_arguments = json.loads(arguments)
            except json.JSONDecodeError:
                continue
            if not isinstance(parsed_arguments, dict):
                continue
            argument_text = json.dumps(parsed_arguments, ensure_ascii=False, separators=(",", ":"))
        elif isinstance(arguments, dict):
            argument_text = json.dumps(arguments, ensure_ascii=False, separators=(",", ":"))
        else:
            continue
        tool_calls.append({
            "id": "call_" + uuid.uuid4().hex[:24],
            "type": "function",
            "function": {"name": name, "arguments": argument_text},
        })
    content = TOOL_CALL_PATTERN.sub("", text).strip()
    return content, tool_calls


class Runtime:
    def __init__(self, model_path: Path, adapter_path: Path, alias: str, api_key_path: Path) -> None:
        self.model_path = model_path
        self.adapter_path = adapter_path
        self.alias = alias
        self.api_key = api_key_path.read_text(encoding="utf-8").strip()
        if not self.api_key:
            raise RuntimeError("API key is empty")
        self.lock = threading.Lock()
        LOGGER.info("loading tokenizer from %s", model_path)
        self.tokenizer = AutoTokenizer.from_pretrained(model_path, local_files_only=True, trust_remote_code=False)
        LOGGER.info("loading 4-bit base model from %s", model_path)
        base = AutoModelForCausalLM.from_pretrained(
            model_path,
            local_files_only=True,
            trust_remote_code=False,
            use_safetensors=True,
            device_map={"": 0},
            dtype=torch.bfloat16,
            attn_implementation="sdpa",
        )
        norm_count = 0
        for module in base.modules():
            if module.__class__.__name__.endswith("RMSNorm"):
                module.to(torch.float32)
                norm_count += 1
        base.config.use_cache = True
        LOGGER.info("loading LoRA adapter from %s", adapter_path)
        self.model = PeftModel.from_pretrained(
            base,
            adapter_path,
            is_trainable=False,
            autocast_adapter_dtype=False,
            low_cpu_mem_usage=False,
            local_files_only=True,
        )
        self.model.eval()
        self.model.config.use_cache = True
        self.model.generation_config.pad_token_id = self.tokenizer.pad_token_id
        configured_eos = self.model.generation_config.eos_token_id
        self.eos_token_id = list(configured_eos) if isinstance(configured_eos, (list, tuple)) else [int(configured_eos)]
        if any(token_id is None for token_id in self.eos_token_id):
            raise RuntimeError("generation eos_token_id contains None")
        if self.eos_token_id != [151645, 151643]:
            raise RuntimeError(f"generation eos_token_id drift: {self.eos_token_id}")
        torch.cuda.synchronize(0)
        LOGGER.info(
            "model loaded alias=%s norms=%d gpu_used_bytes=%d",
            alias,
            norm_count,
            torch.cuda.memory_allocated(0),
        )

    def authorized(self, authorization: str | None) -> bool:
        if not authorization or not authorization.startswith("Bearer "):
            return False
        return hmac.compare_digest(authorization[7:].strip(), self.api_key)

    def complete(self, request: dict[str, Any]) -> dict[str, Any]:
        requested_model = request.get("model")
        if requested_model not in (None, self.alias):
            raise ValueError(f"unknown model: {requested_model!r}")
        messages = normalize_messages(request.get("messages"))
        tools = normalize_tools(request.get("tools"))
        messages, template_tools = prepare_tool_choice(messages, tools, request.get("tool_choice"))
        prompt = self.tokenizer.apply_chat_template(
            messages,
            tools=template_tools or None,
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=False,
        )
        encoded = self.tokenizer(prompt, return_tensors="pt", add_special_tokens=False)
        prompt_tokens = int(encoded["input_ids"].shape[1])
        max_tokens = int(request.get("max_tokens", 512))
        if max_tokens < 1 or max_tokens > MAX_COMPLETION_TOKENS:
            raise ValueError(f"max_tokens must be between 1 and {MAX_COMPLETION_TOKENS}")
        if prompt_tokens + max_tokens > MAX_CONTEXT_TOKENS:
            raise ValueError(f"prompt_tokens + max_tokens exceeds {MAX_CONTEXT_TOKENS}")
        temperature = float(request.get("temperature", 0.0))
        top_p = float(request.get("top_p", 0.95))
        top_k = int(request.get("top_k", 20))
        if temperature < 0:
            raise ValueError("temperature must be non-negative")
        do_sample = temperature > 0
        generate_kwargs: dict[str, Any] = {
            "max_new_tokens": max_tokens,
            "do_sample": do_sample,
            "use_cache": True,
            "pad_token_id": self.tokenizer.pad_token_id,
            "eos_token_id": self.eos_token_id,
        }
        if do_sample:
            generate_kwargs.update(temperature=temperature, top_p=top_p, top_k=top_k)
        if "seed" in request:
            torch.manual_seed(int(request["seed"]))
            torch.cuda.manual_seed_all(int(request["seed"]))
        inputs = {key: value.to("cuda:0") for key, value in encoded.items()}
        started = time.time()
        with self.lock, torch.inference_mode(), torch.autocast(device_type="cuda", dtype=torch.bfloat16):
            output = self.model.generate(**inputs, **generate_kwargs)
            torch.cuda.synchronize(0)
        generated_ids = output[0, prompt_tokens:]
        completion_tokens = int(generated_ids.numel())
        text = self.tokenizer.decode(generated_ids, skip_special_tokens=True)
        stop = request.get("stop")
        stop_items = [stop] if isinstance(stop, str) else stop if isinstance(stop, list) else []
        for item in stop_items:
            if isinstance(item, str) and item and item in text:
                text = text.split(item, 1)[0]
        allowed_names = {tool["function"]["name"] for tool in template_tools}
        content, tool_calls = parse_tool_calls(text, allowed_names)
        message: dict[str, Any] = {"role": "assistant", "content": content or None}
        if tool_calls:
            message["tool_calls"] = tool_calls
            finish_reason = "tool_calls"
        else:
            finish_reason = "length" if completion_tokens >= max_tokens else "stop"
        LOGGER.info(
            "completion prompt_tokens=%d completion_tokens=%d finish=%s elapsed=%.3f",
            prompt_tokens,
            completion_tokens,
            finish_reason,
            time.time() - started,
        )
        return {
            "id": "chatcmpl-" + uuid.uuid4().hex,
            "object": "chat.completion",
            "created": int(time.time()),
            "model": self.alias,
            "choices": [{"index": 0, "message": message, "finish_reason": finish_reason, "logprobs": None}],
            "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens, "total_tokens": prompt_tokens + completion_tokens},
            "system_fingerprint": "checkpoint-000119-" + hashlib.sha256(str(self.adapter_path).encode()).hexdigest()[:12],
        }


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], runtime: Runtime):
        super().__init__(address, Handler)
        self.runtime = runtime


class Handler(BaseHTTPRequestHandler):
    server: Server
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        LOGGER.info("http %s - %s", self.client_address[0], fmt % args)

    def send_json(self, status: int, payload: Any) -> None:
        body = json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def send_sse(self, response: dict[str, Any], include_usage: bool) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            for payload in iter_stream_payloads(response, include_usage):
                self.wfile.write(sse_bytes(payload))
                self.wfile.flush()
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            LOGGER.info("stream client disconnected")
        self.close_connection = True

    def require_auth(self) -> bool:
        if self.server.runtime.authorized(self.headers.get("Authorization")):
            return True
        self.send_json(HTTPStatus.UNAUTHORIZED, openai_error("Invalid authentication credentials", "authentication_error", "invalid_api_key"))
        return False

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Content-Length", "0")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self) -> None:
        if self.path == "/health":
            self.send_json(HTTPStatus.OK, {"status": "ok", "model": self.server.runtime.alias, "checkpoint": "checkpoint-000119"})
            return
        if self.path == "/v1/models":
            if not self.require_auth():
                return
            self.send_json(HTTPStatus.OK, {"object": "list", "data": [{"id": self.server.runtime.alias, "object": "model", "created": int(time.time()), "owned_by": "d-robotics"}]})
            return
        self.send_json(HTTPStatus.NOT_FOUND, openai_error("Not found", "invalid_request_error", "not_found"))

    def do_POST(self) -> None:
        if self.path != "/v1/chat/completions":
            self.send_json(HTTPStatus.NOT_FOUND, openai_error("Not found", "invalid_request_error", "not_found"))
            return
        if not self.require_auth():
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 1 or length > MAX_BODY_BYTES:
                raise ValueError("invalid Content-Length")
            request = json.loads(self.rfile.read(length))
            if not isinstance(request, dict):
                raise ValueError("request body must be a JSON object")
            stream = request.get("stream", False)
            if not isinstance(stream, bool):
                raise ValueError("stream must be a boolean")
            stream_options = request.get("stream_options") or {}
            if not isinstance(stream_options, dict):
                raise ValueError("stream_options must be an object")
            include_usage = bool(stream_options.get("include_usage", False))
            response = self.server.runtime.complete(request)
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            self.send_json(HTTPStatus.BAD_REQUEST, openai_error(str(error)))
            return
        except Exception as error:
            LOGGER.exception("completion failed")
            self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, openai_error(f"Internal inference error: {type(error).__name__}", "server_error", "internal_error"))
            return
        if stream:
            self.send_sse(response, include_usage)
        else:
            self.send_json(HTTPStatus.OK, response)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--alias", required=True)
    parser.add_argument("--api-key-file", type=Path, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    runtime = Runtime(args.model.resolve(strict=True), args.adapter.resolve(strict=True), args.alias, args.api_key_file.resolve(strict=True))
    server = Server((args.host, args.port), runtime)
    LOGGER.info("server ready at http://%s:%d", args.host, args.port)
    server.serve_forever(poll_interval=0.5)


if __name__ == "__main__":
    main()
