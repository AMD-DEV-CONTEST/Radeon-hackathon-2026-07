from __future__ import annotations

import time
from dataclasses import dataclass

from privateops.config import validate_model_endpoint
from privateops.llm import OpenAICompatibleProvider


@dataclass(frozen=True)
class ProviderConfiguration:
    mode: str
    endpoint: str
    model: str
    api_key: str
    allow_remote: bool

    @classmethod
    def from_payload(cls, payload: dict) -> "ProviderConfiguration":
        mode = str(payload.get("mode", "")).strip().lower()
        endpoint = str(payload.get("endpoint", "")).strip()
        model = str(payload.get("model", "")).strip()
        api_key = str(payload.get("api_key", "")).strip()
        if mode not in {"remote", "rocm-local"}:
            raise ValueError("Provider mode must be remote or rocm-local.")
        if not endpoint:
            raise ValueError("Model endpoint is required.")
        allow_remote = mode == "remote"
        endpoint = validate_model_endpoint(endpoint, allow_remote=allow_remote)
        if not model:
            raise ValueError("Model name is required.")
        if allow_remote and not api_key:
            raise ValueError("API key is required for remote mode.")
        return cls(mode, endpoint, model, api_key, allow_remote)

    def build_provider(self) -> OpenAICompatibleProvider:
        return OpenAICompatibleProvider(
            endpoint=self.endpoint,
            model=self.model,
            api_key=self.api_key,
            allow_remote=self.allow_remote,
        )


class RuntimeProviderManager:
    def __init__(self, agent):
        self.agent = agent

    def test(self, payload: dict) -> dict[str, object]:
        configuration = ProviderConfiguration.from_payload(payload)
        provider = configuration.build_provider()
        started = time.perf_counter()
        provider.complete("Reply with OK only.", [], {}, {})
        return self._safe_result(configuration, round((time.perf_counter() - started) * 1000, 3), True)

    def apply(self, payload: dict) -> dict[str, object]:
        configuration = ProviderConfiguration.from_payload(payload)
        provider = configuration.build_provider()
        self.agent.configure_provider(
            provider,
            configuration.endpoint,
            configuration.model,
            configuration.allow_remote,
        )
        result = self.agent.status()
        return {
            "ok": True,
            "provider": result["provider"],
            "runtime_mode": result["runtime_mode"],
            "model_endpoint": result["model_endpoint"],
            "model_name": result["model_name"],
            "core_inference_location": result["core_inference_location"],
            "competition_eligible": result["competition_eligible"],
        }

    @staticmethod
    def _safe_result(
        configuration: ProviderConfiguration,
        latency_ms: float,
        ok: bool,
    ) -> dict[str, object]:
        return {
            "ok": ok,
            "provider": "openai-compatible-amd-cloud" if configuration.allow_remote else "openai-compatible-rocm",
            "runtime_mode": "amd-cloud-api" if configuration.allow_remote else "rocm-local",
            "model_endpoint": configuration.endpoint,
            "model": configuration.model,
            "latency_ms": latency_ms,
            "competition_eligible": not configuration.allow_remote,
        }
