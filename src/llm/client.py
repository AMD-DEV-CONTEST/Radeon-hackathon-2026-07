"""Client for a locally-served vLLM model (OpenAI-compatible API).

Points at whatever OpenAI-compatible endpoint is running — by default the
local vLLM server on the Radeon GPU instance (VLLM_PORT), but base_url can
be overridden to point at any other OpenAI-compatible endpoint if needed.
"""
import os
import requests


class LocalLLMClient:
    def __init__(self, base_url: str = None, model: str = None, api_key: str = None):
        port = os.getenv("VLLM_PORT", "8000")
        self.base_url = (base_url or os.getenv("VLLM_BASE_URL") or f"http://localhost:{port}/v1").rstrip("/")
        self.model = model or os.getenv("MODEL_NAME", "Qwen/Qwen3-8B-Instruct")
        self.api_key = api_key or os.getenv("LLM_API_KEY")
        self.timeout = int(os.getenv("LLM_TIMEOUT_SECONDS", "60"))

    def chat(self, messages: list[dict], tools: list[dict] = None) -> dict:
        payload = {"model": self.model, "messages": messages}
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            resp = requests.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=headers,
                timeout=self.timeout,
            )
            resp.raise_for_status()
        except requests.exceptions.RequestException as e:
            raise RuntimeError(
                f"Failed to reach LLM backend at {self.base_url}: {e}\n"
                f"Check that vllm serve is running and VLLM_PORT/VLLM_BASE_URL "
                f"are set correctly."
            ) from e

        data = resp.json()
        choice = data["choices"][0]["message"]
        return {
            "role": choice.get("role", "assistant"),
            "content": choice.get("content"),
            "tool_calls": choice.get("tool_calls"),
        }
