"""Vision agent abstraction.

Two interchangeable backends implement this interface:
  - ClaudeAgent      (Anthropic API, default)
  - LocalVLMAgent    (any OpenAI-compatible endpoint, e.g. ollama / vLLM)
"""

import base64
import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class Verdict:
    verdict: str          # "confirm" | "reject" | "uncertain"
    confidence: float     # 0..1
    reasoning: str
    reviewer: str = ""
    raw: str = ""

    def to_dict(self):
        return {
            "verdict": self.verdict,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "reviewer": self.reviewer,
        }


def encode_image(path):
    with open(path, "rb") as f:
        return base64.standard_b64encode(f.read()).decode("utf-8")


def parse_json_response(text):
    """Extract the first JSON object from a model response."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def parse_verdict(text, reviewer=""):
    data = parse_json_response(text)
    if not data:
        return Verdict("uncertain", 0.0, f"无法解析回复: {text[:200]}", reviewer, text)
    verdict = str(data.get("verdict", "uncertain")).lower()
    if verdict not in ("confirm", "reject", "uncertain"):
        verdict = "uncertain"
    try:
        confidence = float(data.get("confidence", 0.5))
    except (TypeError, ValueError):
        confidence = 0.5
    return Verdict(verdict, max(0.0, min(1.0, confidence)),
                   str(data.get("reasoning", "")), reviewer, text)


class VisionAgent(ABC):
    """An agent that can look at keyframes and answer prompts."""

    name = "vision-agent"

    @abstractmethod
    def query(self, prompt, image_paths=None, system=None):
        """Send a prompt (with optional images) and return the text response."""

    def review(self, role_name, prompt, image_paths):
        text = self.query(prompt, image_paths=image_paths)
        return parse_verdict(text, reviewer=f"{self.name}/{role_name}")


def create_agent(config):
    """Instantiate the configured backend, or return None with a warning."""
    backend = config["agents"]["backend"]
    if backend == "claude" and config.get("privacy", {}).get("local_only", True):
        print("Claude backend blocked by local_only policy; use agents.backend=local.")
        return None
    try:
        if backend == "claude":
            from .claude_agent import ClaudeAgent
            return ClaudeAgent(config["agents"]["claude"])
        if backend == "local":
            from .local_vlm_agent import LocalVLMAgent
            return LocalVLMAgent(config["agents"]["local"])
        print(f"Unknown agent backend: {backend}")
    except Exception as exc:
        print(f"Agent backend '{backend}' unavailable: {exc}")
    return None
