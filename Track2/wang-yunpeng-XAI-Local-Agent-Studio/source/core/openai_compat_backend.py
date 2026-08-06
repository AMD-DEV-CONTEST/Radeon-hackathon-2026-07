"""OpenAI 兼容后端基类（DeepSeek / LlamaCpp / Ollama 共用）。

统一处理 OpenAI Chat Completions 协议（/v1/chat/completions + SSE 流式）。
关键修复：base_url 若不以 /chat/completions 结尾则自动补齐，
避免 llama.cpp server（base_url=http://127.0.0.1:11434/v1）被直接 POST 到 /v1 导致 404。

上层（engine / hermes / control_loop）只依赖 ModelBackend 抽象，
因此换后端只需替换子类，73 个单测与架构纹丝不动。
"""

from __future__ import annotations

import json
import math
import time
import urllib.error
import urllib.request
from typing import Iterator, Optional

from .model_backend import ModelBackend, ModelResponse


class OpenAICompatBackend(ModelBackend):
    """OpenAI Chat Completions 协议兼容后端（HTTP 直连，零三方依赖）。"""

    name = "openai_compat"

    def __init__(
        self,
        api_key: Optional[str] = "",
        model: str = "",
        base_url: str = "http://localhost:11434/v1",
        timeout: int = 60,
    ):
        self.api_key = api_key or ""
        self.model = model
        self.base_url = base_url.rstrip("/") if base_url else ""
        self.timeout = timeout

    # ---- 端点归一化（P0-1 修复核心）----
    def _endpoint(self) -> str:
        """返回完整 chat/completions 端点，自动补齐缺失后缀。"""
        base = self.base_url
        if not base:
            base = "http://localhost:11434/v1"
        if base.endswith("/chat/completions"):
            return base
        return base.rstrip("/") + "/chat/completions"

    # ---- 内部 HTTP（可被测桩替换，保持离线可测）----
    def _post(self, payload: dict) -> dict:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(self._endpoint(), data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        if self.api_key:
            req.add_header("Authorization", f"Bearer {self.api_key}")
        req.add_header("Accept", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:  # 4xx/5xx：把服务端 message 透出
            body = e.read().decode("utf-8", "ignore")
            raise RuntimeError(f"HTTP {e.code}: {body[:300]}") from e

    # ---- ModelBackend 接口 ----
    def complete(self, prompt: str, **kwargs) -> str:
        # 视觉多模态：vision_parts 优先（已是 content 数组）
        if kwargs.get("vision_parts"):
            messages = [{"role": "user", "content": kwargs["vision_parts"]}]
        else:
            messages = [{"role": "user", "content": prompt}]
        payload = self._build(messages, kwargs, logprobs=False)
        out = self._post(payload)
        self.last_usage = out.get("usage")  # Token 用量透传（供上层记账）
        msg = out["choices"][0]["message"]
        # V4 reasoning models: 思考在 reasoning_content，答案在 content
        return (msg.get("content") or "") or (msg.get("reasoning_content") or "")

    def complete_with_confidence(self, prompt: str, **kwargs) -> ModelResponse:
        messages = [{"role": "user", "content": prompt}]
        payload = self._build(messages, kwargs, logprobs=True)
        try:
            out = self._post(payload)
            self.last_usage = out.get("usage")  # Token 用量透传
            text = out["choices"][0]["message"]["content"]
            conf = self._conf_from(out)
            return ModelResponse(text=text, confidence=conf)
        except Exception:
            # 服务端不支持 logprobs 时降级：仍返回文本，置信给中性值
            return ModelResponse(text=self.complete(prompt, **kwargs), confidence=0.5)

    def stream_complete(self, prompt: str, **kwargs) -> Iterator[str]:
        """流式生成：逐 token yield（OpenAI SSE）。

        V4 推理模型：reasoning_content（思考链）也 yield，让前端感知模型在思考。
        遇到 [DONE] 结束。任何网络异常抛出，由上层捕获转为 error 事件。
        """
        is_reasoner = self.model and "v4" in self.model.lower()
        messages = [{"role": "user", "content": prompt}]
        payload = self._build(messages, kwargs, logprobs=False)
        payload["stream"] = True
        payload["stream_options"] = {"include_usage": True}  # 尾包携带 usage（Token 记账）
        self.last_usage = None

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(self._endpoint(), data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        if self.api_key:
            req.add_header("Authorization", f"Bearer {self.api_key}")
        req.add_header("Accept", "text/event-stream")
        req.add_header("Cache-Control", "no-cache")

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                for raw in resp:
                    line = raw.decode("utf-8", "ignore").strip()
                    if not line or not line.startswith("data:"):
                        continue
                    data_field = line[len("data:"):].strip()
                    if data_field == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_field)
                    except json.JSONDecodeError:
                        continue
                    if chunk.get("usage"):
                        self.last_usage = chunk.get("usage")  # 流式尾包 usage
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    piece = delta.get("content")
                    reason_piece = delta.get("reasoning_content")
                    # V4 推理模型：先把思考过程也送出（用户能看到模型在工作），再送最终回答
                    if reason_piece and is_reasoner:
                        yield reason_piece
                    if piece:
                        yield piece
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "ignore")
            raise RuntimeError(f"HTTP {e.code}: {body[:300]}") from e
        except Exception as e:
            raise RuntimeError(f"流式推理失败: {e}") from e

    # ---- 工具 ----
    def _build(self, messages: list[dict], kwargs: dict, logprobs: bool) -> dict:
        # 支持多轮：若调用方传入 messages= 则使用（engine 的多轮上下文），
        # 否则由 prompt 构造单条 user 消息。
        if kwargs.get("messages") is not None:
            msgs = kwargs["messages"]
        else:
            msgs = messages if messages else [{"role": "user", "content": kwargs.get("prompt", "")}]
        payload: dict = {
            "model": kwargs.get("model", self.model),
            "messages": msgs,
            "temperature": kwargs.get("temperature", 0.7),
            "stream": False,
        }
        if "max_tokens" in kwargs:
            payload["max_tokens"] = kwargs["max_tokens"]
        if logprobs:
            payload["logprobs"] = True
            payload["top_logprobs"] = 1
        return payload

    @staticmethod
    def _conf_from(out: dict) -> float:
        """用首个 token 的平均 top_logprob 估计自评置信（exp 均值，夹到 [0,1]）。"""
        try:
            lp = out["choices"][0].get("logprobs")
            if lp and lp.get("content"):
                vals = [c["logprob"] for c in lp["content"] if c.get("logprob") is not None]
                if vals:
                    return max(0.0, min(1.0, math.exp(sum(vals) / len(vals))))
        except Exception:
            pass
        return 0.5
