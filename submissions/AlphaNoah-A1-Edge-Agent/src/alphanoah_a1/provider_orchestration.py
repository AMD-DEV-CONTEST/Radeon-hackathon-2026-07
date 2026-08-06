"""Thin startup orchestration over the existing Provider components."""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import Mapping

from .exceptions import ProviderTransportError
from .knowledge.models import KnowledgeContext
from .models import AnalysisResult, Event
from .provider_config import (
    AIRuntimeConfig,
    ProviderKind,
    ProviderSettings,
    default_runtime_config,
    load_runtime_config,
)
from .provider_discovery import (
    DiscoveryStatus,
    ProviderDiscovery,
    ProviderDiscoveryResult,
    ProviderSelectionError,
    ProviderSelector,
)
from .provider_runtime import AnalysisProviderFactory, ProviderFactoryError
from .skill import SkillContext

RUNTIME_STATUS_VERSION = "runtime-status-v1"

ENV_PROVIDER = "ALPHANOAH_AI_PROVIDER"
ENV_MODEL = "ALPHANOAH_AI_MODEL"
ENV_BASE_URL = "ALPHANOAH_AI_BASE_URL"
ENV_TIMEOUT_SECONDS = "ALPHANOAH_AI_TIMEOUT_SECONDS"
ENV_MODEL_DIGEST = "ALPHANOAH_AI_MODEL_DIGEST"
ENV_CREDENTIAL_ENV = "ALPHANOAH_AI_CREDENTIAL_ENV"

LEGACY_OLLAMA_BASE_URL = "ALPHANOAH_OLLAMA_BASE_URL"
LEGACY_OLLAMA_MODEL = "ALPHANOAH_OLLAMA_MODEL"
LEGACY_OLLAMA_MODEL_DIGEST = "ALPHANOAH_OLLAMA_MODEL_DIGEST"


class ProviderRuntimeStatus(StrEnum):
    """Safe top-level startup state exposed by the runtime projection."""

    READY = "ready"
    UNCONFIGURED = "unconfigured"
    UNAVAILABLE = "unavailable"
    INVALID_CONFIGURATION = "invalid_configuration"
    DEGRADED = "degraded"


class ProviderExecutionMode(StrEnum):
    """Safe product execution label without endpoint details."""

    LOCAL = "local"
    REMOTE = "remote"
    DEMO = "demo"
    NONE = "none"


class ProviderSelectionSource(StrEnum):
    """Auditable selection origin after precedence resolution."""

    COMMAND_LINE = "command_line"
    ENVIRONMENT = "environment"
    SAVED_CONFIG = "saved_config"
    INJECTED = "injected"
    NONE = "none"


class ProviderHealthStatus(StrEnum):
    """Safe health vocabulary for the public runtime projection."""

    HEALTHY = "healthy"
    SYNTHETIC = "synthetic"
    NOT_CONFIGURED = "not_configured"
    UNAVAILABLE = "unavailable"
    INVALID_CONFIGURATION = "invalid_configuration"
    DEGRADED = "degraded"


@dataclass(frozen=True, slots=True)
class StartupProviderOptions:
    """Explicit command-line provider values; absent fields remain unset."""

    provider: ProviderKind | str | None = None
    model: str | None = None
    base_url: str | None = None
    timeout_seconds: float | None = None
    model_digest: str | None = None
    credential_env: str | None = None

    @property
    def supplied(self) -> bool:
        return any(
            value is not None
            for value in (
                self.provider,
                self.model,
                self.base_url,
                self.timeout_seconds,
                self.model_digest,
                self.credential_env,
            )
        )


@dataclass(frozen=True, slots=True)
class ResolvedProviderRuntime:
    """One resolved Provider plus only non-secret startup metadata."""

    provider_instance: object | None
    provider_type: ProviderKind | None
    model: str | None
    execution_mode: ProviderExecutionMode
    selection_source: ProviderSelectionSource
    health_status: ProviderHealthStatus
    status: ProviderRuntimeStatus
    discovery: tuple[ProviderDiscoveryResult, ...] = ()
    diagnostic_code: str = ""

    @property
    def ready(self) -> bool:
        return (
            self.status is ProviderRuntimeStatus.READY
            and self.provider_instance is not None
        )

    def to_public_dict(self) -> dict[str, object]:
        """Return the exact credential-free `runtime-status-v1` contract."""

        return {
            "version": RUNTIME_STATUS_VERSION,
            "status": self.status.value,
            "provider": (
                self.provider_type.value
                if self.provider_type is not None
                else None
            ),
            "model": _public_model(self.model),
            "execution": self.execution_mode.value,
            "selection_source": self.selection_source.value,
            "health": self.health_status.value,
        }

    @classmethod
    def injected(cls, provider: object) -> "ResolvedProviderRuntime":
        """Describe an explicitly injected test/application Provider."""

        provider_id = str(getattr(provider, "provider_id", ""))
        prefix = provider_id.partition(":")[0]
        try:
            kind = ProviderKind(prefix)
        except ValueError:
            return cls(
                provider_instance=provider,
                provider_type=None,
                model=None,
                execution_mode=ProviderExecutionMode.NONE,
                selection_source=ProviderSelectionSource.INJECTED,
                health_status=ProviderHealthStatus.DEGRADED,
                status=ProviderRuntimeStatus.DEGRADED,
                diagnostic_code="injected_provider_identity_unknown",
            )
        return cls(
            provider_instance=provider,
            provider_type=kind,
            # Application injection is a test/composition seam, not a trusted
            # configuration source. Never project arbitrary object text.
            model=None,
            execution_mode=_execution_mode(kind),
            selection_source=ProviderSelectionSource.INJECTED,
            health_status=(
                ProviderHealthStatus.SYNTHETIC
                if kind is ProviderKind.FAKE
                else ProviderHealthStatus.HEALTHY
            ),
            status=ProviderRuntimeStatus.READY,
        )


class UnavailableAnalysisProvider:
    """Non-functional Provider port used for an explicit unavailable Web mode."""

    provider_id = "unavailable:provider-runtime"
    prompt_version = "unavailable-provider-v1"

    @staticmethod
    def _raise() -> AnalysisResult:
        raise ProviderTransportError(
            "AI provider runtime is unavailable.",
            code="provider_unavailable",
        )

    def analyze(self, event: Event) -> AnalysisResult:
        return self._raise()

    def analyze_with_context(
        self,
        event: Event,
        knowledge_context: KnowledgeContext,
    ) -> AnalysisResult:
        return self._raise()

    def analyze_with_contexts(
        self,
        event: Event,
        skill_context: SkillContext,
        knowledge_context: KnowledgeContext,
    ) -> AnalysisResult:
        return self._raise()


class ProviderRuntimeOrchestrator:
    """Resolve startup Provider state without mutating config or Runtime."""

    def __init__(
        self,
        *,
        environment: Mapping[str, str] | None = None,
        discovery: ProviderDiscovery | None = None,
        selector: ProviderSelector | None = None,
        factory: AnalysisProviderFactory | None = None,
        discovery_timeout_seconds: float = 2.0,
    ):
        self._environment = os.environ if environment is None else environment
        self._discovery = discovery or ProviderDiscovery(
            environment=self._environment,
            timeout_seconds=discovery_timeout_seconds,
        )
        self._selector = selector or ProviderSelector()
        self._factory = factory or AnalysisProviderFactory(
            environment=self._environment,
        )

    def resolve(
        self,
        config_path: str | Path,
        *,
        options: StartupProviderOptions | None = None,
    ) -> ResolvedProviderRuntime:
        """Resolve one Provider using CLI, environment and saved precedence."""

        startup = options or StartupProviderOptions()
        try:
            config = load_runtime_config(config_path)
            environment_options = self._environment_options()
            (
                config,
                requested_kind,
                selection_source,
            ) = self._resolve_configuration(
                config,
                environment_options,
                startup,
            )
        except (OSError, TypeError, ValueError):
            return self._failure(
                ProviderRuntimeStatus.INVALID_CONFIGURATION,
                ProviderHealthStatus.INVALID_CONFIGURATION,
                diagnostic_code="invalid_provider_configuration",
            )

        try:
            discovery = self._discovery.discover(config)
        except OSError:
            return self._failure(
                ProviderRuntimeStatus.UNAVAILABLE,
                ProviderHealthStatus.UNAVAILABLE,
                kind=requested_kind,
                source=selection_source,
                diagnostic_code="provider_discovery_failed",
            )
        except Exception:
            return self._failure(
                ProviderRuntimeStatus.DEGRADED,
                ProviderHealthStatus.DEGRADED,
                kind=requested_kind,
                source=selection_source,
                diagnostic_code="provider_discovery_internal_error",
            )

        if requested_kind is None:
            return self._failure(
                ProviderRuntimeStatus.UNCONFIGURED,
                ProviderHealthStatus.NOT_CONFIGURED,
                discovery=discovery,
                diagnostic_code="provider_selection_required",
            )

        settings = config.get(requested_kind)
        model = (
            settings.model
            if settings is not None and settings.model
            else None
        )
        try:
            selection = self._selector.select(
                config,
                discovery,
                explicit=(
                    requested_kind
                    if selection_source
                    in {
                        ProviderSelectionSource.COMMAND_LINE,
                        ProviderSelectionSource.ENVIRONMENT,
                    }
                    else None
                ),
            )
        except ProviderSelectionError:
            result = next(
                (
                    item
                    for item in discovery
                    if item.kind is requested_kind
                ),
                None,
            )
            invalid = (
                result is None
                or result.status
                in {
                    DiscoveryStatus.DISABLED,
                    DiscoveryStatus.NOT_CONFIGURED,
                }
            )
            return self._failure(
                (
                    ProviderRuntimeStatus.INVALID_CONFIGURATION
                    if invalid
                    else ProviderRuntimeStatus.UNAVAILABLE
                ),
                (
                    ProviderHealthStatus.INVALID_CONFIGURATION
                    if invalid
                    else ProviderHealthStatus.UNAVAILABLE
                ),
                kind=requested_kind,
                model=model,
                source=selection_source,
                discovery=discovery,
                diagnostic_code=(
                    "provider_configuration_incomplete"
                    if invalid
                    else "provider_validation_failed"
                ),
            )

        try:
            provider = self._factory.create(config, selection.kind)
        except (ProviderFactoryError, TypeError, ValueError):
            return self._failure(
                ProviderRuntimeStatus.INVALID_CONFIGURATION,
                ProviderHealthStatus.INVALID_CONFIGURATION,
                kind=selection.kind,
                model=model,
                source=selection_source,
                discovery=discovery,
                diagnostic_code="provider_construction_failed",
            )

        return ResolvedProviderRuntime(
            provider_instance=provider,
            provider_type=selection.kind,
            model=model,
            execution_mode=_execution_mode(selection.kind),
            selection_source=selection_source,
            health_status=(
                ProviderHealthStatus.SYNTHETIC
                if selection.kind is ProviderKind.FAKE
                else ProviderHealthStatus.HEALTHY
            ),
            status=ProviderRuntimeStatus.READY,
            discovery=discovery,
        )

    def _resolve_configuration(
        self,
        config: AIRuntimeConfig,
        environment: StartupProviderOptions,
        command_line: StartupProviderOptions,
    ) -> tuple[
        AIRuntimeConfig,
        ProviderKind | None,
        ProviderSelectionSource,
    ]:
        command_kind = self._kind(command_line.provider)
        environment_kind = self._kind(environment.provider)
        if (
            command_line.supplied
            and command_kind is None
            and environment_kind is None
            and config.selected is None
        ):
            raise ValueError(
                "command-line provider overrides require a selected provider"
            )

        if command_kind is not None:
            source = ProviderSelectionSource.COMMAND_LINE
            kind = command_kind
        elif environment_kind is not None:
            source = ProviderSelectionSource.ENVIRONMENT
            kind = environment_kind
        elif config.selected is not None:
            source = ProviderSelectionSource.SAVED_CONFIG
            kind = config.selected
        else:
            return config, None, ProviderSelectionSource.NONE

        settings = config.get(kind)
        if settings is None:
            settings = default_runtime_config().get(kind)
        if settings is None:
            settings = ProviderSettings(kind=kind)

        if environment_kind is kind:
            settings = self._apply_options(settings, environment)
        settings = self._apply_options(settings, command_line)
        config = self._replace_settings(config, settings)
        return config, kind, source

    def _environment_options(self) -> StartupProviderOptions:
        environment = self._environment
        provider = environment.get(ENV_PROVIDER)
        legacy_ollama = any(
            name in environment
            for name in (
                LEGACY_OLLAMA_BASE_URL,
                LEGACY_OLLAMA_MODEL,
                LEGACY_OLLAMA_MODEL_DIGEST,
            )
        )
        if provider is None and legacy_ollama:
            provider = ProviderKind.OLLAMA.value
        ollama_selected = provider == ProviderKind.OLLAMA.value
        base_url = environment.get(ENV_BASE_URL)
        model = environment.get(ENV_MODEL)
        model_digest = environment.get(ENV_MODEL_DIGEST)
        if ollama_selected:
            base_url = base_url or environment.get(LEGACY_OLLAMA_BASE_URL)
            model = model or environment.get(LEGACY_OLLAMA_MODEL)
            model_digest = model_digest or environment.get(
                LEGACY_OLLAMA_MODEL_DIGEST
            )
        timeout = environment.get(ENV_TIMEOUT_SECONDS)
        return StartupProviderOptions(
            provider=provider,
            model=model,
            base_url=base_url,
            timeout_seconds=(
                float(timeout) if timeout is not None else None
            ),
            model_digest=model_digest,
            credential_env=environment.get(ENV_CREDENTIAL_ENV),
        )

    @staticmethod
    def _kind(value: ProviderKind | str | None) -> ProviderKind | None:
        if value is None:
            return None
        return ProviderKind(value)

    @staticmethod
    def _apply_options(
        settings: ProviderSettings,
        options: StartupProviderOptions,
    ) -> ProviderSettings:
        values: dict[str, object] = {}
        if options.model is not None:
            values["model"] = options.model
        if options.base_url is not None:
            values["endpoint"] = options.base_url
        if options.timeout_seconds is not None:
            values["timeout_seconds"] = options.timeout_seconds
        if options.model_digest is not None:
            values["model_digest"] = options.model_digest
        if options.credential_env is not None:
            values["api_key_env"] = options.credential_env
        return replace(settings, **values) if values else settings

    @staticmethod
    def _replace_settings(
        config: AIRuntimeConfig,
        settings: ProviderSettings,
    ) -> AIRuntimeConfig:
        providers = tuple(
            item for item in config.providers if item.kind is not settings.kind
        ) + (settings,)
        return replace(config, providers=providers)

    @staticmethod
    def _failure(
        status: ProviderRuntimeStatus,
        health: ProviderHealthStatus,
        *,
        kind: ProviderKind | None = None,
        model: str | None = None,
        source: ProviderSelectionSource = ProviderSelectionSource.NONE,
        discovery: tuple[ProviderDiscoveryResult, ...] = (),
        diagnostic_code: str,
    ) -> ResolvedProviderRuntime:
        return ResolvedProviderRuntime(
            provider_instance=None,
            provider_type=kind,
            model=model,
            execution_mode=(
                _execution_mode(kind)
                if kind is not None
                else ProviderExecutionMode.NONE
            ),
            selection_source=source,
            health_status=health,
            status=status,
            discovery=discovery,
            diagnostic_code=diagnostic_code,
        )


def _execution_mode(kind: ProviderKind) -> ProviderExecutionMode:
    if kind is ProviderKind.FAKE:
        return ProviderExecutionMode.DEMO
    if kind in {ProviderKind.OLLAMA, ProviderKind.VLLM}:
        return ProviderExecutionMode.LOCAL
    return ProviderExecutionMode.REMOTE


def _public_model(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        return ProviderSettings(
            kind=ProviderKind.VLLM,
            model=value,
        ).model
    except (TypeError, ValueError):
        return None
