"""Intent-to-tool learning heat map."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
HEATMAP_PATH = ROOT / "ai_pc_operator" / "data" / "memory" / "tool_heatmap.json"


class ToolHeatMap:
    """Learns which tools tend to follow each intent."""

    def __init__(self, path: Path = HEATMAP_PATH) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.counts: dict[str, Counter[str]] = defaultdict(Counter)
        self._load()

    def record_plan(self, intent: str, steps: list[dict]) -> None:
        for step in steps:
            tool = step.get("tool")
            if tool:
                self.counts[intent][tool] += 1
        self.save()

    def hot_tools(self, intent: str, limit: int = 3) -> list[str]:
        return [tool for tool, _ in self.counts.get(intent, Counter()).most_common(limit)]

    def hot_models_for_intent(self, intent: str) -> list[str]:
        tools = self.hot_tools(intent)
        models: list[str] = []
        if any(tool.startswith("browser.") for tool in tools):
            models.append("browser-warmup")
        if any(tool.startswith("auth.") for tool in tools):
            models.append("vault-crypto")
        if intent in {"open_website", "search_web", "login"}:
            models.append("browser-warmup")
        if intent in {"click_text", "screen_click"}:
            models.extend(["ocr-mobile", "ui-detector-int8"])
        return list(dict.fromkeys(models))

    def save(self) -> None:
        payload = {
            intent: dict(counter)
            for intent, counter in self.counts.items()
        }
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return
        for intent, tools in payload.items():
            self.counts[intent].update(tools)

