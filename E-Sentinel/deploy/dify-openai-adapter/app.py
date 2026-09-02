"""
Dify OpenAI-Compatible API Adapter
===================================
Converts OpenAI-format requests (/v1/chat/completions, /v1/models)
into Dify Service API calls (/v1/chat-messages).

部署方式: Docker 容器，与 Dify 共享网络，通过 nginx 路由接入。
环境变量:
  DIFY_API_URL  - Dify 内部 API 地址 (默认 http://api:5001)
"""

import os
import json
import time
import uuid
import logging
from flask import Flask, request, Response, jsonify, stream_with_context
import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DIFY_API_URL = os.environ.get("DIFY_API_URL", "http://api:5001").rstrip("/")
# 默认模型名 -> Dify App API Key 的映射（也可通过请求中的 Authorization 动态传入）
DEFAULT_DIFY_API_KEY = os.environ.get("DIFY_API_KEY", "").strip()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("openai-adapter")

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def extract_query(messages: list[dict]) -> str:
    """从 OpenAI messages 数组中提取最后一条 user 消息作为 Dify query."""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            return msg.get("content", "")
    return ""


def extract_system_prompt(messages: list[dict]) -> str | None:
    """从 OpenAI messages 数组中提取 system 消息."""
    for msg in messages:
        if msg.get("role") == "system":
            return msg.get("content", "")
    return None


def get_dify_api_key() -> str:
    """从请求头获取 Dify API Key，或使用默认值。"""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        key = auth[7:].strip()
        if key:
            return key
    if DEFAULT_DIFY_API_KEY:
        return DEFAULT_DIFY_API_KEY
    return ""


def build_openai_chunk(content: str | None, finish_reason: str | None,
                       model: str, index: int = 0,
                       role: str = "assistant") -> dict:
    """构建 OpenAI 兼容的 streaming chunk."""
    choice = {"index": index, "delta": {}}
    if content is not None:
        choice["delta"]["content"] = content
    if role is not None:
        choice["delta"]["role"] = role
    if finish_reason is not None:
        choice["finish_reason"] = finish_reason
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [choice],
    }


# ---------------------------------------------------------------------------
# Models endpoint
# ---------------------------------------------------------------------------

@app.route("/v1/models", methods=["GET"])
def list_models():
    """返回可用模型列表。"""
    api_key = get_dify_api_key()
    if not api_key:
        return jsonify({"error": {"message": "No API key configured", "type": "auth_error"}}), 401

    # 尝试从 Dify 获取 app 信息以构建模型列表
    # 如果失败，返回默认模型
    models = [
        {
            "id": "dify-chat",
            "object": "model",
            "created": 1718000000,
            "owned_by": "dify",
        },
    ]

    # 尝试从 Dify 获取 app 参数信息
    try:
        resp = requests.get(
            f"{DIFY_API_URL}/v1/parameters",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=5,
        )
        if resp.status_code == 200:
            # 如果能拿到参数，说明 API Key 有效，补充更多模型信息
            pass
    except Exception:
        pass

    return jsonify({"object": "list", "data": models})


# ---------------------------------------------------------------------------
# Chat completions endpoint
# ---------------------------------------------------------------------------

@app.route("/v1/chat/completions", methods=["POST"])
def chat_completions():
    """
    OpenAI 兼容的 chat completions 端点。
    将请求转换为 Dify Service API 格式并代理调用。
    """
    api_key = get_dify_api_key()
    if not api_key:
        return jsonify({
            "error": {
                "message": "No API key provided. Use Authorization: Bearer <dify-app-api-key>",
                "type": "auth_error",
            }
        }), 401

    body = request.get_json(silent=True)
    if not body:
        return jsonify({"error": {"message": "Invalid JSON body", "type": "invalid_request_error"}}), 400

    messages = body.get("messages", [])
    if not messages:
        return jsonify({"error": {"message": "messages is required", "type": "invalid_request_error"}}), 400

    model = body.get("model", "dify-chat")
    stream = body.get("stream", False)
    temperature = body.get("temperature")
    max_tokens = body.get("max_tokens")

    # 构建 Dify 请求
    query = extract_query(messages)
    system_prompt = extract_system_prompt(messages)

    dify_inputs = {}
    if system_prompt:
        dify_inputs["system_prompt"] = system_prompt

    dify_body = {
        "inputs": dify_inputs,
        "query": query,
        "response_mode": "streaming" if stream else "blocking",
        "user": body.get("user", f"openai-user-{uuid.uuid4().hex[:8]}"),
    }

    if temperature is not None:
        dify_body["inputs"]["temperature"] = str(temperature)
    if max_tokens is not None:
        dify_body["inputs"]["max_tokens"] = str(max_tokens)

    logger.info("Dify request: model=%s stream=%s query_len=%d", model, stream, len(query))

    try:
        if stream:
            return _handle_streaming(dify_body, api_key, model)
        else:
            return _handle_blocking(dify_body, api_key, model)
    except requests.exceptions.Timeout:
        return jsonify({"error": {"message": "Dify API timeout", "type": "server_error"}}), 504
    except requests.exceptions.ConnectionError:
        return jsonify({"error": {"message": "Dify API unreachable", "type": "server_error"}}), 502


def _handle_blocking(dify_body: dict, api_key: str, model: str):
    """处理非流式请求。"""
    resp = requests.post(
        f"{DIFY_API_URL}/v1/chat-messages",
        json=dify_body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        timeout=120,
    )

    if resp.status_code != 200:
        logger.error("Dify blocking error: %s %s", resp.status_code, resp.text[:500])
        return jsonify({
            "error": {
                "message": f"Dify API error: {resp.text[:200]}",
                "type": "upstream_error",
            }
        }), resp.status_code

    dify_result = resp.json()
    answer = dify_result.get("answer", "")

    openai_response = {
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": answer,
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": dify_result.get("metadata", {}).get("usage", {}).get("prompt_tokens", 0),
            "completion_tokens": dify_result.get("metadata", {}).get("usage", {}).get("completion_tokens", 0),
            "total_tokens": dify_result.get("metadata", {}).get("usage", {}).get("total_tokens", 0),
        },
    }
    return jsonify(openai_response)


def _handle_streaming(dify_body: dict, api_key: str, model: str):
    """处理流式请求，将 Dify SSE 转为 OpenAI SSE 格式。"""
    def generate():
        try:
            resp = requests.post(
                f"{DIFY_API_URL}/v1/chat-messages",
                json=dify_body,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                timeout=120,
                stream=True,
            )

            if resp.status_code != 200:
                error_chunk = build_openai_chunk(
                    f"Dify API error: HTTP {resp.status_code}", "error", model
                )
                yield f"data: {json.dumps(error_chunk)}\n\n"
                yield "data: [DONE]\n\n"
                return

            full_answer = ""
            for line in resp.iter_lines(decode_unicode=True):
                if not line:
                    continue
                # Dify SSE format: "data: {...}"
                if not line.startswith("data: "):
                    continue

                try:
                    event = json.loads(line[6:])
                except json.JSONDecodeError:
                    continue

                event_type = event.get("event", "")

                if event_type == "message" or event_type == "agent_message":
                    # 增量文本
                    chunk_content = event.get("answer", "")
                    if chunk_content:
                        full_answer += chunk_content
                        yield f"data: {json.dumps(build_openai_chunk(chunk_content, None, model, role=None))}\n\n"

                elif event_type == "message_end":
                    # 消息结束
                    usage = event.get("metadata", {}).get("usage", {})
                    final_chunk = build_openai_chunk(None, "stop", model, role=None)
                    yield f"data: {json.dumps(final_chunk)}\n\n"
                    logger.info("Stream complete: answer_len=%d tokens=%s", len(full_answer), usage)

                elif event_type == "error":
                    error_chunk = build_openai_chunk(
                        event.get("message", "Dify streaming error"), "error", model
                    )
                    yield f"data: {json.dumps(error_chunk)}\n\n"

            yield "data: [DONE]\n\n"

        except requests.exceptions.Timeout:
            error_chunk = build_openai_chunk("Dify API timeout", "error", model)
            yield f"data: {json.dumps(error_chunk)}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as exc:
            logger.exception("Streaming error")
            error_chunk = build_openai_chunk(str(exc), "error", model)
            yield f"data: {json.dumps(error_chunk)}\n\n"
            yield "data: [DONE]\n\n"

    return Response(
        stream_with_context(generate()),
        content_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "dify_api_url": DIFY_API_URL})


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    debug = os.environ.get("DEBUG", "").lower() == "true"

    if debug:
        app.run(host="0.0.0.0", port=port, debug=True)
    else:
        # Production: use gunicorn
        from gunicorn.app.base import BaseApplication

        class FlaskApp(BaseApplication):
            def __init__(self, app, opts=None):
                self.application = app
                self.options = opts or {}
                super().__init__()

            def load_config(self):
                for k, v in self.options.items():
                    if k in self.cfg.settings and v is not None:
                        self.cfg.set(k.lower(), v)

            def load(self):
                return self.application

        options = {
            "bind": f"0.0.0.0:{port}",
            "workers": 2,
            "worker_class": "sync",
            "timeout": 120,
            "accesslog": "-",
            "errorlog": "-",
        }
        FlaskApp(app, options).run()
