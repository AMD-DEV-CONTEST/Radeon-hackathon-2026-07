"""Claude API backend (Anthropic SDK).

Requires ANTHROPIC_API_KEY (or an `ant auth login` profile) in the
environment of the machine running the pipeline.
"""

import anthropic

from .base import VisionAgent, encode_image


class ClaudeAgent(VisionAgent):
    name = "claude"

    def __init__(self, cfg):
        self.model = cfg.get("model", "claude-opus-4-8")
        self.max_tokens = cfg.get("max_tokens", 4000)
        self.client = anthropic.Anthropic()

    def query(self, prompt, image_paths=None, system=None):
        content = []
        for path in image_paths or []:
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": encode_image(path),
                },
            })
        content.append({"type": "text", "text": prompt})

        kwargs = {}
        if system:
            kwargs["system"] = system
        response = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            messages=[{"role": "user", "content": content}],
            **kwargs,
        )
        if response.stop_reason == "refusal":
            return '{"verdict": "uncertain", "confidence": 0, "reasoning": "模型拒绝了该请求"}'
        return "".join(block.text for block in response.content if block.type == "text")
