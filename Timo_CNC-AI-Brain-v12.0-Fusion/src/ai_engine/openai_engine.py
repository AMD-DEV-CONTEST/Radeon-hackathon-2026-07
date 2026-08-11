"""
OpenAI 兼容云端推理引擎 — 适用于所有 OpenAI API 格式的云端模型。
包括: DeepSeek, SiliconFlow, Groq, Together, OpenRouter, 中国移动cm-code, etc.
"""
import json
import os
import urllib.request
from typing import Optional, Dict, Any, List

try:
    from .engine import EngineError
except ImportError:  # 非包内导入时的兼容：定义等效 EngineError，避免后续 raise 时 NameError/TypeError
    class EngineError(Exception):
        """等效于 ai_engine.engine.EngineError，携带 model/provider 上下文。"""

        def __init__(self, message: str, model: str = "", provider: str = ""):
            super().__init__(message)
            self.model = model
            self.provider = provider


class OpenAIEngine:
    """OpenAI 兼容云端推理引擎。通过 HTTP API 调用。"""

    def __init__(self, api_key: str, api_url: str, model: str = "gpt-4o"):
        self.api_key = api_key.strip().strip('"').strip("'")
        self.api_url = api_url.strip().rstrip("/")
        if not self.api_url.endswith("/chat/completions"):
            self.api_url = self.api_url + "/chat/completions"
        self.model = model

    def chat(self, prompt: str, system_prompt: str = "",
             temperature: float = 0.3, max_tokens: int = 2048) -> str:
        messages: List[Dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = json.dumps({
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }, ensure_ascii=False).encode("utf-8")

        req = urllib.request.Request(
            self.api_url,
            data=payload,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Authorization": f"Bearer {self.api_key}",
            }
        )

        try:
            print(f"[OpenAIEngine] -> {self.api_url} model={self.model}")
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            return content
        except Exception as e:
            import traceback
            print(f"[OpenAIEngine] ERROR: {e}")
            traceback.print_exc()
            raise EngineError(
                f"云端调用失败 (model={self.model}, url={self.api_url}): {e}",
                model=self.model, provider="openai_compatible") from e

    def chat_json(self, prompt: str, system_prompt: str = "",
                  temperature: float = 0.3, max_tokens: int = 2048) -> Optional[Dict[str, Any]]:
        raw = self.chat(prompt, system_prompt, temperature, max_tokens)
        cleaned = self._extract_json(raw)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return {"_raw": raw, "_error": "json_parse_failed"}

    @staticmethod
    def _extract_json(text: str) -> str:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return text[start:end + 1]
        return text

    def get_info(self) -> Dict[str, Any]:
        return {
            "model": self.model,
            "api_url": self.api_url,
            "provider": "openai_compatible",
            "role": "cloud_engine",
        }

    def to_json(self) -> str:
        return json.dumps(self.get_info(), ensure_ascii=False)
