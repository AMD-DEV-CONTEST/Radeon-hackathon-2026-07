from glass_gateway.config import Settings
from glass_gateway.providers.llm.base import LLMProvider

import httpx
import re

from glass_gateway.providers.llm.qwen_options import apply_qwen_request_options


class OpenAICompatibleLLMProvider(LLMProvider):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def complete(self, text: str) -> str:
        stripped = (text or "").strip()
        if self.settings.llm_base_url and self.settings.llm_api_key:
            answer = await self._complete_openai_compatible(stripped)
            if answer:
                return answer
        if stripped in {"你好", "你好。", "hello", "Hello"}:
            return self.settings.llm_fixed_reply
        if not stripped:
            return "我没听清，请再说一遍。"
        return f"我听到的是：{stripped}"

    async def _complete_openai_compatible(self, text: str) -> str:
        base_url = self.settings.llm_base_url.rstrip("/")
        url = f"{base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.settings.llm_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.settings.llm_model or "MiniMaxAI",
            "messages": [
                {
                    "role": "system",
                    "content": "你是海狸 AI 眼镜助手。回答要简短，适合显示在光波导屏幕上，优先使用中文。",
                },
                {"role": "user", "content": text},
            ],
            "temperature": 0.4,
            "max_tokens": 180,
        }
        apply_qwen_request_options(
            payload,
            model=self.settings.llm_model or "MiniMaxAI",
        )

        try:
            async with httpx.AsyncClient(timeout=30.0, trust_env=False) as client:
                response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
        except Exception:
            return ""

        choices = data.get("choices")
        if isinstance(choices, list) and choices:
            message = choices[0].get("message", {})
            content = message.get("content")
            if isinstance(content, str):
                return _sanitize_content(content)
        return ""


def _sanitize_content(content: str) -> str:
    cleaned = re.sub(r"<think>.*?</think>\s*", "", content, flags=re.DOTALL | re.IGNORECASE)
    return cleaned.strip()
