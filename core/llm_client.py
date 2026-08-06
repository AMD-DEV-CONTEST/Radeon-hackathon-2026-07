"""CodeRisk Agent - LLM Client

Two local backends:
1. Local llama-server (HTTP)
2. Local llama-cpp-python (direct GGUF load)

Unified interface with auto-retry. No cloud API calls.
"""

from __future__ import annotations

import json
import time
from typing import Optional

import httpx
from rich.console import Console

from core.models import LLMBackend, LLMConfig

console = Console()

def find_gguf_model() -> str:
    """Auto-discover GGUF model file."""
    import os
    from pathlib import Path
    # 1. Environment variable
    if path := os.getenv("CODERISK_MODEL_PATH"):
        return path
    # 2. Common paths
    search_paths = [
        Path.home() / ".coderisk" / "models",
        Path("/workspace/models"),
        Path("/mnt/agents/output"),
    ]
    for dir_path in search_paths:
        if dir_path.exists():
            ggufs = sorted(dir_path.glob("*.gguf"), key=lambda p: p.stat().st_size, reverse=True)
            if ggufs:
                return str(ggufs[0])
    return ""


DEFAULT_CONFIGS = {
    LLMBackend.LOCAL_HTTP: LLMConfig(
        backend=LLMBackend.LOCAL_HTTP,
        api_url="http://localhost:8080",
        model="qwen2.5-coder-32b-instruct",
        temperature=0.1,
        max_tokens=8192,
    ),
    LLMBackend.LOCAL_LLAMA_CPP: LLMConfig(
        backend=LLMBackend.LOCAL_LLAMA_CPP,
        model_path=find_gguf_model() or "/workspace/models/qwen2.5-coder-32b-instruct-q4_k_m.gguf",
        model="qwen2.5-coder-32b-instruct",
        temperature=0.1,
        max_tokens=8192,
    ),
}

MAX_RETRIES = 3
RETRY_BASE_DELAY = 1.0

# Qwen2.5 ChatML special tokens
_IM_START = "<im_start>"
_IM_END = "</im_end>"
_ENDOFTEXT = "<|endoftext|>"


class LLMClient:
    """Unified LLM client with retry support."""

    def __init__(self, config: Optional[LLMConfig] = None, backend: Optional[LLMBackend] = None):
        import os
        if config:
            self.config = config
        else:
            env_backend = os.getenv("LLM_BACKEND", "")
            if env_backend:
                try:
                    b = LLMBackend(env_backend)
                except ValueError:
                    console.print(
                        f"[yellow]Invalid LLM_BACKEND '{env_backend}', "
                        f"falling back to local_llama_cpp[/]"
                    )
                    b = backend or LLMBackend.LOCAL_LLAMA_CPP
            else:
                b = backend or LLMBackend.LOCAL_LLAMA_CPP
            self.config = DEFAULT_CONFIGS[b].model_copy()
            # API key only needed for authenticated local_http (optional)
            # No cloud API keys required for local inference

        self._client: Optional[httpx.Client] = None
        self._local_llm = None
        self._request_count = 0
        self._total_tokens = 0

        if self.config.backend == LLMBackend.LOCAL_HTTP:
            self._client = httpx.Client(timeout=self.config.timeout)
        elif self.config.backend == LLMBackend.LOCAL_LLAMA_CPP:
            self._init_llama_cpp()

    def _init_llama_cpp(self):
        try:
            from llama_cpp import Llama
        except ImportError:
            console.print("[red]llama-cpp-python not installed. Run: pip install llama-cpp-python[/]")
            raise

        if not self.config.model_path:
            raise ValueError("LOCAL_LLAMA_CPP requires model_path in config")

        # Detect GPU availability
        gpu_layers = self.config.n_gpu_layers
        try:
            import subprocess
            result = subprocess.run(
                ["rocm-smi", "--showmeminfo", "vram"],
                capture_output=True, text=True, timeout=5,
            )
            if "N/A" in result.stdout or result.returncode != 0:
                console.print("[yellow]GPU not detected, falling back to CPU inference[/]")
                gpu_layers = 0
            else:
                console.print("[green]AMD GPU detected, offloading layers[/]")
        except Exception:
            console.print("[yellow]rocm-smi not found, falling back to CPU inference[/]")
            gpu_layers = 0

        console.print(f"[dim]Loading local model: {self.config.model_path}[/]")
        self._local_llm = Llama(
            model_path=self.config.model_path,
            n_gpu_layers=gpu_layers,
            verbose=False,
            n_ctx=4096,
        )
        console.print("[green]Local model loaded.[/]")

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        response_format: Optional[dict] = None,
        stream: bool = False,
        on_token: Optional[callable] = None,
    ) -> str:
        """Send chat request with auto-retry.

        Args:
            stream: Enable streaming for HTTP backends.
            on_token: Callback for each token when streaming (token: str) -> None.
        """
        temp = temperature if temperature is not None else self.config.temperature
        tokens = max_tokens if max_tokens is not None else self.config.max_tokens

        last_err = None
        for attempt in range(MAX_RETRIES):
            try:
                if self.config.backend == LLMBackend.LOCAL_LLAMA_CPP:
                    return self._chat_local(messages, temp, tokens)
                elif stream:
                    return self._chat_stream(messages, temp, tokens, on_token)
                else:
                    return self._chat_http(messages, temp, tokens, response_format)
            except Exception as e:
                last_err = e
                if attempt < MAX_RETRIES - 1:
                    delay = RETRY_BASE_DELAY * (2 ** attempt)
                    console.print(
                        f"[yellow]Retry {attempt + 1}/{MAX_RETRIES} after {delay}s: {e}[/]"
                    )
                    time.sleep(delay)
        raise last_err

    def _chat_http(
        self,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        response_format: Optional[dict] = None,
    ) -> str:
        """HTTP API call (local llama-server only)."""
        payload = {
            "model": self.config.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format:
            payload["response_format"] = response_format

        url = f"{self.config.api_url}/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"

        start = time.monotonic()
        resp = self._client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

        elapsed_ms = int((time.monotonic() - start) * 1000)
        self._request_count += 1

        content = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        self._total_tokens += usage.get("total_tokens", 0)

        console.print(
            f"[dim]LLM [{self.config.backend.value}] "
            f"{elapsed_ms}ms | "
            f"tokens: {usage.get('prompt_tokens', '?')}->{usage.get('completion_tokens', '?')} | "
            f"total: {self._total_tokens}[/]"
        )
        return content

    def _chat_local(
        self,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> str:
        """llama-cpp-python direct inference."""
        prompt = self._messages_to_prompt(messages)

        start = time.monotonic()
        result = self._local_llm(
            prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            stop=[_IM_END, "<|endoftext|>"],
        )
        elapsed_ms = int((time.monotonic() - start) * 1000)
        self._request_count += 1

        text = result["choices"][0]["text"]
        tokens_used = result.get("usage", {}).get("total_tokens", 0)
        self._total_tokens += tokens_used

        console.print(
            f"[dim]LLM [local_llama_cpp] "
            f"{elapsed_ms}ms | "
            f"tokens: {tokens_used} | "
            f"total: {self._total_tokens}[/]"
        )
        return text

    def chat_json(
        self,
        messages: list[dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        schema: Optional[type] = None,
    ) -> dict:
        """Send chat request, parse JSON with auto-retry and optional schema validation.

        Args:
            schema: Pydantic model class for output validation.
                    If provided, validates the parsed JSON against the schema.
        """
        last_err = None
        msgs = list(messages)
        for attempt in range(3):
            # response_format not supported by llama-server
            # We rely on prompt engineering and JSON extraction instead
            response_format = None

            raw = self.chat(msgs, temperature, max_tokens, response_format=response_format)
            try:
                parsed = _extract_json(raw)
                if schema is not None:
                    # Validate against Pydantic schema
                    validated = schema.model_validate(parsed)
                    return validated.model_dump(exclude_none=True)
                return parsed
            except Exception as e:
                last_err = e
                if attempt < 2:
                    schema_hint = ""
                    if schema is not None:
                        import json as _json
                        schema_hint = f" Expected schema: {_json.dumps(schema.model_json_schema(), indent=2)}"
                    msgs = list(messages) + [{"role": "user", "content":
                        f"Your response was not valid JSON. Error: {e}.{schema_hint} Respond with valid JSON only."}]
                    console.print(f"[yellow]JSON parse failed, retry {attempt+1}/3[/]")
        raise ValueError(f"Failed to get valid JSON after 3 attempts: {last_err}")

    def _chat_stream(
        self,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        on_token: Optional[callable] = None,
    ) -> str:
        """Streaming HTTP API call (local llama-server only)."""
        payload = {
            "model": self.config.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }

        url = f"{self.config.api_url}/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"

        start = time.monotonic()
        full_content = ""

        with self._client.stream("POST", url, json=payload, headers=headers) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line or not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str.strip() == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    token = delta.get("content", "")
                    if token:
                        full_content += token
                        if on_token:
                            on_token(token)
                except json.JSONDecodeError:
                    continue

        elapsed_ms = int((time.monotonic() - start) * 1000)
        self._request_count += 1
        console.print(
            f"[dim]LLM [stream] {elapsed_ms}ms | chars: {len(full_content)} | total_reqs: {self._request_count}[/]"
        )
        return full_content

    @property
    def stats(self) -> dict:
        return {
            "backend": self.config.backend.value,
            "model": self.config.model,
            "requests": self._request_count,
            "total_tokens": self._total_tokens,
        }

    @staticmethod
    def _escape_content(content: str) -> str:
        "Escape special tokens to prevent prompt injection."
        return content.replace('<im_start>', '<|im_start_ESCAPED>') \
                      .replace('<im_end>', '<|im_end_ESCAPED>') \
                      .replace('</im_end>', '<|im_end_ESCAPED>') \
                      .replace('<im|start>', '<|im_start_ESCAPED>') \
                      .replace('<im|end>', '<|im_end_ESCAPED>') \
                      .replace('</im|end>', '<|im_end_ESCAPED>')

    @staticmethod
    def _messages_to_prompt(messages: list[dict[str, str]]) -> str:
        """Convert OpenAI-style messages to Qwen2.5 ChatML format."""
        parts = []
        for msg in messages:
            role = msg.get("role", "user")
            content = LLMClient._escape_content(msg.get("content", ""))
            parts.append(f"{_IM_START}{role}\n{content}{_IM_END}")
        parts.append(f"{_IM_START}assistant\n")
        return "\n".join(parts)

    def close(self):
        if self._client:
            self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def _extract_json(text: str) -> dict:
    """Extract JSON from LLM response with multiple fallback strategies."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    if "```json" in text:
        start = text.index("```json") + 7
        end = text.index("```", start)
        try:
            return json.loads(text[start:end].strip())
        except json.JSONDecodeError:
            pass

    depth = 0
    start = -1
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    return json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    start = -1

    # Try to repair truncated JSON by closing brackets
    stripped = text.strip()
    if stripped.startswith("{"):
        # Count open vs close braces
        opens = stripped.count("{")
        closes = stripped.count("}")
        if opens > closes:
            repair = stripped + "}" * (opens - closes)
            try:
                return json.loads(repair)
            except json.JSONDecodeError:
                pass

    raise ValueError(f"Failed to extract JSON from LLM response:\n{text[:300]}...")
