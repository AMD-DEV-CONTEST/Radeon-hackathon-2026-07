# -*- coding: utf-8 -*-
"""LLM 推理封装层：统一 chat 接口，支持 ollama / llama_cpp 后端。

本地（Windows/NVIDIA）用 ollama + qwen3:8b 开发；
AMD ROCm 环境可切到 llama_cpp（GGML_HIP=ON 编译）或 ollama-roc 服务。

qwen3 等模型原生支持 function calling，通过 tools 参数触发，
返回结构化 {'content': str, 'tool_calls': [...]}，供 Agent 执行。
"""
import os
import time
from typing import Optional

import yaml

with open("config.yaml", "r", encoding="utf-8") as f:
    CFG = yaml.safe_load(f)

# 容器/远程部署时用环境变量覆盖 Ollama 地址（docker compose 里指向 ollama 服务名）
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")


class LLMBackend:
    """统一推理后端：ollama（默认）/ llama_cpp / openai_compat(vLLM)。

    - ollama: 本地 Ollama 服务（Windows/Linux 通用，开发最方便）
    - llama_cpp: AMD ROCm 编译版（GGML_HIP=ON）
    - openai_compat: vLLM 的 OpenAI 兼容 API（Radeon Cloud 工作区预装 vLLM，性能好、支持大模型）
    """

    def __init__(self, name: Optional[str] = None):
        self.name = name or CFG["model"]["name"]
        self.backend = CFG["model"].get("backend", "ollama")
        self.temperature = CFG["model"].get("temperature", 0.3)
        self.max_tokens = CFG["model"].get("max_tokens", 2048)
        self.top_p = CFG["model"].get("top_p", 0.9)
        self.base_url = CFG["model"].get("base_url", "http://localhost:8000/v1")

        if self.backend == "ollama":
            import ollama
            self._ollama = ollama.Client(host=OLLAMA_HOST)
            self._check_ollama()
        elif self.backend == "llama_cpp":
            from llama_cpp import Llama
            # AMD ROCm 路径：需要真实 GGUF 文件路径（config: model.model_path）。
            # 注意：不能把 Ollama 标签（如 qwen3:8b）当 model_path 传给 Llama()。
            model_path = CFG["model"].get("model_path") or name
            if not model_path or os.path.splitext(model_path)[1].lower() not in (".gguf", ".bin"):
                raise ValueError(
                    "llama_cpp 后端需要真实的 GGUF 模型路径（config.yaml 的 model.model_path），"
                    f"当前为 {model_path!r}。AMD 示例：Qwen2.5-7B-Instruct-Q4_K_M.gguf")
            self._llama = Llama(model_path=model_path, n_gpu_layers=-1, verbose=False)
        elif self.backend in ("openai_compat", "vllm"):
            from openai import OpenAI
            self._client = OpenAI(base_url=self.base_url, api_key="EMPTY")
        else:
            raise ValueError(f"unknown backend: {self.backend}")

    def _check_ollama(self):
        try:
            models = [m.get("name") or m.get("model") for m in self._ollama.list().get("models", [])]
        except Exception:
            models = []
        if not any(self.name in (m or "") for m in models):
            print(f"[warn] Ollama 未找到模型 {self.name}，可用模型: {models}")
            print(f"       请先运行: ollama pull {self.name}")

    def chat(self, messages: list, tools: Optional[list] = None,
             temperature: Optional[float] = None, max_tokens: Optional[int] = None) -> dict:
        """统一 chat 入口。

        Args:
            messages: [{'role','content'}, ...]
            tools: [OpenAI 风格 function schema]，提供时启用原生 tool calling

        Returns:
            {'content': str, 'tool_calls': [{'name','arguments'(dict)}]}
            tool_calls 为空列表表示模型直接回答了。
        """
        t0 = time.time()
        result = {"content": "", "tool_calls": []}

        if self.backend == "ollama":
            kwargs = dict(
                model=self.name,
                messages=messages,
                options={
                    "temperature": temperature if temperature is not None else self.temperature,
                    "num_predict": max_tokens or self.max_tokens,
                    "top_p": self.top_p,
                },
            )
            if tools:
                kwargs["tools"] = tools
            resp = self._ollama.chat(**kwargs)
            msg = resp["message"]
            result["content"] = msg.get("content") or ""
            # 暴露真实 token 计数（供基准测试精确计算吞吐）
            result["_eval_count"] = resp.get("eval_count")
            result["_prompt_eval_count"] = resp.get("prompt_eval_count")
            for tc in msg.get("tool_calls", []) or []:
                result["tool_calls"].append({
                    "name": tc["function"]["name"],
                    "arguments": tc["function"]["arguments"],
                })
        elif self.backend == "llama_cpp":
            kwargs = dict(messages=messages)
            if tools:
                kwargs["tools"] = [{"type": "function", "function": t["function"]} for t in tools]
                kwargs["tool_choice"] = "auto"
            resp = self._llama.create_chat_completion(**kwargs)
            msg = resp["choices"][0]["message"]
            result["content"] = msg.get("content") or ""
            for tc in (msg.get("tool_calls") or []):
                result["tool_calls"].append({
                    "name": tc["function"]["name"],
                    "arguments": tc["function"].get("arguments") or "",
                })
        elif self.backend in ("openai_compat", "vllm"):
            tools_arg = None
            if tools:
                tools_arg = [{"type": "function", "function": t["function"]} for t in tools]
            resp = self._client.chat.completions.create(
                model=self.name,
                messages=messages,
                temperature=temperature if temperature is not None else self.temperature,
                max_tokens=max_tokens or self.max_tokens,
                top_p=self.top_p,
                tools=tools_arg,
            )
            msg = resp.choices[0].message
            result["content"] = msg.content or ""
            result["_eval_count"] = getattr(resp, "usage", None) and resp.usage.completion_tokens
            for tc in (msg.tool_calls or []):
                result["tool_calls"].append({
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                })
        else:
            raise ValueError(f"unknown backend: {self.backend}")
        return result

    def chat_stream(self, messages: list, temperature: Optional[float] = None,
                    max_tokens: Optional[int] = None):
        """流式 chat：逐块 yield 文本（无工具调用，用于最终回答的打字机效果）。

        Yields:
            str 文本块。调用方拼接即得完整回答。
        """
        for ev in self.chat_stream_full(messages, tools=None, temperature=temperature,
                                        max_tokens=max_tokens):
            if ev["delta"]:
                yield ev["delta"]

    def chat_stream_full(self, messages: list, tools: Optional[list] = None,
                         temperature: Optional[float] = None,
                         max_tokens: Optional[int] = None):
        """单遍流式 chat：同时产出文本增量与工具调用（累积完整后于结尾给全量）。

        解决了旧实现"先用非流式探测结果、再流式重生成一遍"的双倍生成延迟。
        只调一次模型，就能既打字机式输出、又拿到完整工具调用。

        Yields:
            {"delta": str, "tool_calls": [...]}   # tool_calls 结尾才非空
        """
        acc_tool_calls = []
        if self.backend == "ollama":
            for chunk in self._ollama.chat(
                model=self.name,
                messages=messages,
                stream=True,
                tools=tools or None,
                options={
                    "temperature": temperature if temperature is not None else self.temperature,
                    "num_predict": max_tokens or self.max_tokens,
                    "top_p": self.top_p,
                },
            ):
                msg = chunk.get("message") if isinstance(chunk, dict) else getattr(chunk, "message", None)
                if msg is None:
                    continue
                piece = ""
                tcs = []
                if isinstance(msg, dict):
                    if msg.get("thinking"):
                        piece = ""
                    piece = msg.get("content") or ""
                    tcs = msg.get("tool_calls") or []
                else:
                    if getattr(msg, "thinking", None):
                        piece = ""
                    piece = msg.content or ""
                    tcs = getattr(msg, "tool_calls", None) or []
                for tc in tcs:
                    fn = tc["function"]
                    args = fn["arguments"]
                    if isinstance(args, str):
                        import json as _json
                        try:
                            args = _json.loads(args)
                        except Exception:
                            args = {}
                    acc_tool_calls.append({"name": fn["name"], "arguments": args})
                yield {"delta": piece, "tool_calls": []}
            # 结尾补发完整工具调用
            if acc_tool_calls:
                yield {"delta": "", "tool_calls": acc_tool_calls}
            return
        if self.backend in ("openai_compat", "vllm"):
            tools_arg = None
            if tools:
                tools_arg = [{"type": "function", "function": t["function"]} for t in tools]
            stream = self._client.chat.completions.create(
                model=self.name,
                messages=messages,
                stream=True,
                tools=tools_arg,
                temperature=temperature if temperature is not None else self.temperature,
                max_tokens=max_tokens or self.max_tokens,
                top_p=self.top_p,
            )
            # vLLM 增量参数：按 index 累积 JSON 片段
            _buf: dict = {}
            _id: dict = {}
            _name: dict = {}
            for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                piece = (delta.content if hasattr(delta, "content") else "") or ""
                for tc in (delta.tool_calls or []):
                    i = tc.index
                    _buf[i] = _buf.get(i, "") + (tc.function.arguments or "")
                    _id[i] = tc.id or _id.get(i, "")
                    _name[i] = _name.get(i, "") + (tc.function.name or "")  # 追加，避免分片颠倒
                yield {"delta": piece, "tool_calls": []}
            # 结尾解析完整工具调用
            if _buf:
                import json as _json
                for i in sorted(_buf):
                    try:
                        args = _json.loads(_buf[i])
                    except Exception:
                        args = {"raw": _buf[i]}
                    acc_tool_calls.append({"name": _name.get(i, ""), "arguments": args})
                yield {"delta": "", "tool_calls": acc_tool_calls}
            return
        # llama_cpp / 其它：降级为非流式（保留 tools 以支持 RAG 工具调用）
        r = self.chat(messages, tools=tools)
        yield {"delta": r["content"], "tool_calls": r.get("tool_calls", [])}

    def embed(self, text: str) -> list:
        """返回 embedding 向量。用独立 embedding 模型（如 bge-m3）更佳。

        embedding 后端独立配置（CFG.embedding.backend），可与模型后端不同：
        - ollama: 用独立 embedding 模型（如 bge-m3）
        - sentence_transformers: 本地 HF 模型（RC 无 ollama 时用，走 CPU）
        - openai_compat / vllm: vLLM 需同时加载 embedding 模型

        当模型后端是 llama_cpp / vllm（没有 ollama 客户端）而 embedding 仍配置为
        ollama 时，自动回退到 sentence_transformers，避免 AttributeError 崩溃。
        """
        emb_cfg = CFG.get("embedding", {})
        emb_backend = emb_cfg.get("backend", "ollama")
        emb_name = emb_cfg.get("name", self.name)

        if emb_backend == "sentence_transformers":
            from sentence_transformers import SentenceTransformer
            model = getattr(self, "_st_model", None)
            if model is None:
                model = SentenceTransformer(emb_name)
                self._st_model = model
            return model.encode(text, normalize_embeddings=True).tolist()
        if emb_backend == "ollama":
            if not hasattr(self, "_ollama"):
                # 模型后端是 llama_cpp/vllm（无 ollama 客户端）→ 回退本地 embedding
                return self._embed_st_fallback(text, emb_name)
            resp = self._ollama.embeddings(model=emb_name, prompt=text)
            return resp["embedding"]
        if emb_backend in ("openai_compat", "vllm"):
            if not hasattr(self, "_client"):
                return self._embed_st_fallback(text, emb_name)
            resp = self._client.embeddings.create(model=emb_name, input=text)
            return resp.data[0].embedding
        raise NotImplementedError(
            f"embedding backend {emb_backend} 未实现，可用: ollama / sentence_transformers / vllm")

    def _embed_st_fallback(self, text: str, model_name: str) -> list:
        """无 ollama/vllm 客户端时的本地 embedding 兜底（sentence_transformers）。"""
        from sentence_transformers import SentenceTransformer
        model = getattr(self, "_st_model", None)
        if model is None:
            model = SentenceTransformer(model_name)
            self._st_model = model
        return model.encode(text, normalize_embeddings=True).tolist()


if __name__ == "__main__":
    llm = LLMBackend()
    print("== 自测 ==")
    r = llm.chat([{"role": "user", "content": "用一句话介绍你自己"}])
    print("chat:", r["content"][:80])
    r2 = llm.chat(
        [{"role": "user", "content": "请调用天气工具查询北京的天气"}],
        tools=[{"type": "function", "function": {
            "name": "get_weather", "description": "查询天气",
            "parameters": {"type": "object", "properties": {"city": {"type": "string"}},
                           "required": ["city"]}}}],
    )
    print("tool_calls:", r2["tool_calls"])
    print("content:", r2["content"][:80])
    emb = llm.embed("测试 embedding")
    print("embedding dim:", len(emb))
