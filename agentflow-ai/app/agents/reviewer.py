from __future__ import annotations

from app.services.ollama_client import OllamaClient


REVIEWER_SYSTEM = """You are the Reviewer Agent in AgentFlow AI.
Return a polished final answer that is concise, actionable, and grounded in the provided workflow artifacts.
Call out assumptions, mention evidence from local files when present, and include next steps.
"""


class ReviewerAgent:
    def __init__(self, ollama: OllamaClient) -> None:
        self.ollama = ollama

    def run(self, draft: str, requested_model: str | None = None) -> tuple[str, str | None, str | None]:
        prompt = f"Review and improve this draft response without changing its meaning:\n\n{draft}"
        try:
            response = self.ollama.generate_text(
                prompt=prompt,
                system=REVIEWER_SYSTEM,
                requested_model=requested_model,
                temperature=0.15,
            )
            return response["content"], response.get("model"), None
        except Exception as exc:
            return draft, None, str(exc)
