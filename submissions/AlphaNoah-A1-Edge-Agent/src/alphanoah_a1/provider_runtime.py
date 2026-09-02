"""Provider construction and stateless readiness smoke checks."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import Mapping

from .ai_reliability import AnalysisResultGuard
from .knowledge.models import KnowledgeContext
from .models import AnalysisResult, Event
from .provider_config import AIRuntimeConfig, ProviderKind
from .providers import (
    OllamaAnalysisProvider,
    OpenAICompatibleAnalysisProvider,
    ReadinessFakeAnalysisProvider,
)
from .skill import SkillContext


class ProviderFactoryError(ValueError):
    """Raised when a selected provider cannot be safely constructed."""


class AnalysisProviderFactory:
    """Build a selected provider outside AlphaNoahRuntime."""

    def __init__(
        self,
        *,
        environment: Mapping[str, str] | None = None,
        timeout_seconds: float | None = None,
    ):
        self._environment = os.environ if environment is None else environment
        if timeout_seconds is not None and (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(float(timeout_seconds))
            or not 0 < float(timeout_seconds) <= 1_800
        ):
            raise ValueError(
                "timeout_seconds must be a finite number between 0 and 1800"
            )
        self.timeout_seconds = (
            None if timeout_seconds is None else float(timeout_seconds)
        )

    def create(
        self,
        config: AIRuntimeConfig,
        kind: ProviderKind | str,
    ) -> object:
        try:
            provider_kind = ProviderKind(kind)
        except (TypeError, ValueError) as exc:
            raise ProviderFactoryError("Provider kind is invalid.") from exc
        settings = config.get(provider_kind)
        if settings is None or not settings.enabled:
            raise ProviderFactoryError(
                f"Provider {provider_kind.value} is not enabled."
            )
        if provider_kind is ProviderKind.FAKE:
            return ReadinessFakeAnalysisProvider()
        if not settings.endpoint:
            raise ProviderFactoryError(
                f"Provider {provider_kind.value} requires an endpoint."
            )
        if not settings.model:
            raise ProviderFactoryError(
                f"Provider {provider_kind.value} requires a model."
            )
        timeout_seconds = (
            settings.timeout_seconds
            if self.timeout_seconds is None
            else self.timeout_seconds
        )
        if provider_kind is ProviderKind.OLLAMA:
            return OllamaAnalysisProvider(
                base_url=settings.endpoint,
                model=settings.model,
                total_timeout_seconds=timeout_seconds,
                connect_timeout_seconds=min(5.0, timeout_seconds),
                model_digest=settings.model_digest,
            )
        api_key = ""
        if (
            provider_kind is ProviderKind.OPENAI_COMPATIBLE
            and not settings.api_key_env
        ):
            raise ProviderFactoryError(
                "OpenAI-compatible provider requires a credential "
                "environment variable reference."
            )
        if settings.api_key_env:
            api_key = self._environment.get(settings.api_key_env, "")
            if not api_key:
                raise ProviderFactoryError(
                    "Configured provider credential environment variable "
                    "is absent."
                )
        return OpenAICompatibleAnalysisProvider(
            endpoint=settings.endpoint,
            model=settings.model,
            provider_kind=provider_kind,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
        )


@dataclass(frozen=True, slots=True)
class ProviderSmokeResult:
    """Outcome of a no-persistence provider and guard check."""

    provider_id: str
    validation_status: str
    result: AnalysisResult
    runtime_state_changed: bool = False


class ProviderSmokeTester:
    """Call Provider -> guard only; never create Runtime state or Decisions."""

    def __init__(self, guard: AnalysisResultGuard | None = None):
        self._guard = guard or AnalysisResultGuard()

    def run(
        self,
        provider: object,
        event: Event,
        skill_context: SkillContext,
        knowledge_context: KnowledgeContext,
    ) -> ProviderSmokeResult:
        analyze = getattr(provider, "analyze_with_contexts", None)
        if not callable(analyze):
            raise TypeError(
                "Provider does not support Skill and Knowledge contexts."
            )
        candidate = analyze(event, skill_context, knowledge_context)
        validated = self._guard.validate(candidate)
        provider_id = getattr(provider, "provider_id", "")
        if not isinstance(provider_id, str) or not provider_id:
            raise TypeError("Provider identity is invalid.")
        return ProviderSmokeResult(
            provider_id=provider_id,
            validation_status="VALID",
            result=validated,
        )
