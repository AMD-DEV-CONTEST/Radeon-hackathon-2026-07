"""
统一AI引擎 — 同时支持Ollama本地API + OpenAI兼容API。
根据模型配置自动切换后端，零硬编码。
作者: timo.cao | 邮箱: miscdd@163.com | 生成: 大帅教练系统
"""
import json
import urllib.request
from typing import Dict, Any, Optional


class EngineError(Exception):
    """AI引擎调用失败。携带模型/后端上下文，供调用方捕获后降级或返回结构化错误。"""

    def __init__(self, message: str, model: str = "", provider: str = ""):
        super().__init__(message)
        self.model = model
        self.provider = provider


class AIEngine:
    """统一AI引擎。本地Ollama / 云端API 自动适配。"""

    def __init__(self, model_config: Dict[str, Any]):
        self.config = model_config
        self.provider = model_config.get("provider", "ollama")
        self.model_name = model_config.get("name", "qwen2.5:3b")
        self.model_id = model_config.get("model_id", self.model_name)
        self.api_url = model_config.get("api_url", "http://localhost:11434")
        self.api_key = model_config.get("api_key", "")

    def chat(self, prompt: str, system: str = "", system_prompt: str = "",
             temperature: float = 0.1, max_tokens: int = 1024) -> str:
        """统一聊天接口。自动路由到对应后端。"""
        # 兼容两种参数名: system 和 system_prompt
        sys_msg = system or system_prompt
        if self.provider == "ollama":
            return self._ollama_chat(prompt, sys_msg, temperature, max_tokens)
        elif self.provider == "openai":
            return self._openai_chat(prompt, sys_msg, temperature, max_tokens)
        return ""

    def chat_json(self, prompt: str, system: str = "", system_prompt: str = "",
                  temperature: float = 0.1, max_tokens: int = 1024) -> dict:
        """返回JSON的聊天调用。"""
        text = self.chat(prompt, system=system, system_prompt=system_prompt,
                         temperature=temperature, max_tokens=max_tokens)
        try:
            m = __import__("re").search(r'\{(?:[^{}]|\{[^{}]*\})*\}', text, __import__("re").DOTALL)
            if m:
                return json.loads(m.group())
        except Exception:
            pass
        return {}

    def _ollama_chat(self, prompt: str, system: str, temperature: float,
                     max_tokens: int) -> str:
        """调用Ollama /api/generate。"""
        full_prompt = f"{system}\n{prompt}" if system else prompt
        body = json.dumps({
            "model": self.model_name,
            "prompt": full_prompt,
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens}
        }).encode()
        req = urllib.request.Request(
            f"{self.api_url}/api/generate",
            data=body,
            headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode('utf-8'))
            return data.get("response", "")
        except Exception as e:
            raise EngineError(
                f"Ollama调用失败 (model={self.model_name}, url={self.api_url}): {e}",
                model=self.model_name, provider="ollama") from e

    def _openai_chat(self, prompt: str, system: str, temperature: float,
                     max_tokens: int) -> str:
        """调用OpenAI兼容API (DeepSeek/GLM/通义等)。"""
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        body = json.dumps({
            "model": self.model_id,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False
        }).encode()
        req = urllib.request.Request(
            self.api_url.rstrip("/") + "/chat/completions",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}"
            }
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode('utf-8'))
            return data.get("choices", [{}])[0].get("message", {}).get("content", "")
        except Exception as e:
            raise EngineError(
                f"云端调用失败 (model={self.model_id}, url={self.api_url}): {e}",
                model=self.model_id, provider="openai") from e
