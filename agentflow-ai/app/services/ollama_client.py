from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any
from urllib import error, request

from app.config import AppConfig


@dataclass(slots=True)
class OllamaStatus:
    running: bool
    available_models: list[str]
    selected_model: str | None
    message: str


class OllamaClient:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.timeout = 60

    def health(self) -> OllamaStatus:
        try:
            payload = self._get_json("/api/tags")
            models = [item.get("name", "") for item in payload.get("models", []) if item.get("name")]
            selected = self.pick_model(models)
            message = "Ollama is running." if models else "Ollama is running but no models are installed yet."
            return OllamaStatus(True, models, selected, message)
        except RuntimeError as exc:
            return OllamaStatus(
                False,
                [],
                None,
                f"Ollama is unavailable. Start it with 'ollama serve' and pull a model like 'ollama pull qwen2.5:7b'. Details: {exc}",
            )

    def list_models(self) -> list[str]:
        status = self.health()
        return status.available_models

    def pick_model(self, available_models: list[str], requested_model: str | None = None) -> str | None:
        if requested_model and requested_model in available_models:
            return requested_model
        for preferred in self.config.preferred_models:
            if preferred in available_models:
                return preferred
        return available_models[0] if available_models else None

    def generate_text(self, *, prompt: str, system: str, requested_model: str | None = None, temperature: float = 0.2) -> dict[str, Any]:
        status = self.health()
        model = self.pick_model(status.available_models, requested_model=requested_model)
        if not status.running or not model:
            raise RuntimeError(status.message)
        payload = {
            "model": model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "options": {"temperature": temperature},
        }
        response = self._post_json("/api/chat", payload)
        return {
            "model": model,
            "content": (response.get("message") or {}).get("content", "").strip(),
        }

    def generate_json(self, *, prompt: str, system: str, requested_model: str | None = None) -> dict[str, Any]:
        status = self.health()
        model = self.pick_model(status.available_models, requested_model=requested_model)
        if not status.running or not model:
            raise RuntimeError(status.message)
        payload = {
            "model": model,
            "stream": False,
            "format": "json",
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "options": {"temperature": 0.1},
        }
        response = self._post_json("/api/chat", payload)
        content = (response.get("message") or {}).get("content", "{}").strip() or "{}"
        return {
            "model": model,
            "content": json.loads(content),
        }

    def _get_json(self, path: str) -> dict[str, Any]:
        url = self.config.ollama_host.rstrip("/") + path
        req = request.Request(url, method="GET")
        try:
            with request.urlopen(req, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except (error.URLError, error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError(str(exc)) from exc

    def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = self.config.ollama_host.rstrip("/") + path
        data = json.dumps(payload).encode("utf-8")
        req = request.Request(url, data=data, method="POST", headers={"Content-Type": "application/json"})
        try:
            with request.urlopen(req, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except (error.URLError, error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError(str(exc)) from exc
