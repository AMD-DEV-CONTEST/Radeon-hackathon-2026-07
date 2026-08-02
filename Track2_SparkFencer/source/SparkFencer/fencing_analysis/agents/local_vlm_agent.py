"""Local VLM backend via any OpenAI-compatible /v1/chat/completions endpoint
(works with ollama and vLLM, e.g. Qwen2.5-VL running on the DGX Spark)."""

import os

import requests

from .base import VisionAgent, encode_image
from ..security import require_model_endpoint


class LocalVLMAgent(VisionAgent):
    name = "local-vlm"

    def __init__(self, cfg):
        # Per-run UI settings take priority; environment variables remain the
        # secure deployment default when the user leaves a field blank.
        self.base_url = (cfg.get("base_url") or os.environ.get(
            "VLM_BASE_URL", "http://127.0.0.1:11434/v1")).rstrip("/")
        require_model_endpoint(self.base_url)
        self.model = cfg.get("model") or os.environ.get("VLM_MODEL", "qwen2.5vl:7b")
        self.api_key = cfg.get("api_key") or os.environ.get("VLM_API_KEY", "none")
        # 300s was measured too short for qwen3-vl:32b's thinking-channel
        # overhead on this hardware (observed read-timeouts on both per-event
        # review calls and the longer final report call at max_tokens=4000).
        self.timeout = cfg.get("timeout", 1200)
        # Thinking VLMs (e.g. qwen3-vl) spend part of the budget on a separate
        # reasoning channel, so give enough headroom for the JSON answer too.
        self.max_tokens = cfg.get("max_tokens", 4000)

    def query(self, prompt, image_paths=None, system=None):
        content = []
        for path in image_paths or []:
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{encode_image(path)}"},
            })
        content.append({"type": "text", "text": prompt})

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": content})

        response = requests.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"model": self.model, "messages": messages, "max_tokens": self.max_tokens},
            timeout=self.timeout,
        )
        response.raise_for_status()
        message = response.json()["choices"][0]["message"]
        # Fall back to the reasoning channel if the answer content was truncated
        # away (thinking models can exhaust the budget before emitting content).
        return message.get("content") or message.get("reasoning") or ""
