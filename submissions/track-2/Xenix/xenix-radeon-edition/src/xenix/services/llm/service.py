"""LLM inference facade over read-only settings and explicit provider scopes."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager

from ...exceptions import NotFoundError, ValidationError
from .provider_factory import (
    LLMProviderFactoryRegistry,
    ProviderImplementationUnavailableError,
    ProviderOperationScope,
    create_builtin_llm_provider_factory_registry,
)
from .providers import (
    AgentProvider,
    LLMRequestMetadata,
    LLMRetryEvent,
    ProviderMessage,
    ProviderResponse,
    ProviderStreamEvent,
    redact_provider_error_text,
)
from .settings import (
    DEFAULT_FQ_MODEL_KEY,
    DEFAULT_MODEL_KEY,
    DEFAULT_PROVIDER_KEY,
    PACKAGED_TRIAL_SECRET_SOURCE,
    SETTINGS_FILE_NAME,
    TRIAL_PROVIDER_DISPLAY_NAME,
    TRIAL_PROVIDER_KEY,
    TRIAL_LLM_BASE_URL_FALLBACK,
    TRIAL_LLM_MODEL_FALLBACK,
    FrozenLLMSettingsSource,
    LLMDialect,
    LLMModelOption,
    LLMModelRef,
    LLMProviderConfig,
    LLMSettings,
    LLMSettingsSource,
    LLMSettingsService,
    PackagedTrialLLMConfig,
    StaticLlmTarget,
    default_llm_settings,
    fq_model_key,
    is_managed_llm_provider_instance_id,
    load_packaged_trial_llm_config,
    model_options_from_settings,
    parse_fq_model_key,
    sanitize_settings_for_save,
)
from .tooling import AgentToolSpec


class LLMService:
    """Inference-only LLM facade.

    The service has no full-document settings write API.  It receives a narrow
    settings reader and one app-scoped factory registry; construction, retries,
    and streaming then share one exact operation scope.
    """

    def __init__(
        self,
        settings_service: LLMSettingsSource,
        *,
        provider_factory_registry: LLMProviderFactoryRegistry | None = None,
    ) -> None:
        self._settings_service = settings_service
        # The compatibility default is a fresh explicit registry, not a module
        # global.  Optional managers must be contributed by app composition.
        self._provider_factory_registry = (
            provider_factory_registry or create_builtin_llm_provider_factory_registry()
        )

    @property
    def settings_service(self) -> LLMSettingsSource:
        return self._settings_service

    @property
    def provider_factory_registry(self) -> LLMProviderFactoryRegistry:
        return self._provider_factory_registry

    def load_settings(self) -> LLMSettings:
        return self._settings_service.load()

    def default_fq_model_key(self) -> str:
        return self.load_settings().default_fq_model_key

    def model_options(self) -> list[LLMModelOption]:
        return self.model_options_from_settings(self.load_settings())

    @contextmanager
    def provider_scope(self, fq_model_key: str | None = None) -> Iterator[ProviderOperationScope]:
        """Enter one provider operation scope for an exact selected model.

        Callers that dispatch directly should keep this context around their
        complete semantic operation.  ``complete`` and ``stream`` do this
        internally and additionally keep it around their full retry lifetime.
        """

        settings = self.load_settings()
        provider, model_key = self._resolve_provider_from_settings(settings, fq_model_key)
        scope = self._provider_factory_registry.provider_scope(provider, model_key=model_key)
        with scope:
            yield scope

    def complete(
        self,
        *,
        fq_model_key: str | None = None,
        messages: list[ProviderMessage],
        tools: list[AgentToolSpec],
        retry_callback: Callable[[LLMRetryEvent], None] | None = None,
        before_provider_request: Callable[[], None] | None = None,
    ) -> ProviderResponse:
        settings = self.load_settings()
        provider, model_key = self._resolve_provider_from_settings(settings, fq_model_key)
        scope = self._provider_factory_registry.provider_scope(provider, model_key=model_key)
        with scope:
            return self._complete_with_retry(
                provider=scope.provider,
                operation_scope=scope,
                messages=messages,
                tools=tools,
                max_attempts=settings.retry_attempts,
                retry_callback=retry_callback,
                before_provider_request=before_provider_request,
            )

    def stream(
        self,
        *,
        fq_model_key: str | None = None,
        messages: list[ProviderMessage],
        tools: list[AgentToolSpec],
        before_provider_request: Callable[[], None] | None = None,
    ) -> Iterator[ProviderStreamEvent | LLMRetryEvent]:
        """Stream one operation, releasing its exact scope on close/abandonment."""

        settings = self.load_settings()
        provider, model_key = self._resolve_provider_from_settings(settings, fq_model_key)
        max_attempts = self._max_attempts(settings.retry_attempts)
        previous_error: Exception | None = None
        scope = self._provider_factory_registry.provider_scope(provider, model_key=model_key)
        # This ``with`` remains active across every yield.  Python unwinds it in
        # generator.close()/abandonment as well as normal completion.
        with scope:
            for attempt_number in range(1, max_attempts + 1):
                if previous_error is not None:
                    yield self._retry_event(
                        attempt_number=attempt_number,
                        max_attempts=max_attempts,
                        exc=previous_error,
                    )
                if before_provider_request is not None:
                    before_provider_request()
                try:
                    stream_method = getattr(scope.provider, "stream", None)
                    if callable(stream_method):
                        buffered_events: list[ProviderStreamEvent] = []
                        for event in stream_method(messages, tools):
                            # A received provider event proves this attempt has
                            # crossed dispatch.  A later loss must not replay it.
                            scope.mark_dispatch_may_have_happened()
                            if self._is_live_tool_call_progress(event):
                                yield event
                                continue
                            buffered_events.append(event)
                    else:
                        response = scope.provider.complete(messages, tools)
                        buffered_events = [ProviderStreamEvent(response=response)]
                    yield from buffered_events
                    return
                except Exception as exc:
                    if not self._should_retry(
                        exc,
                        attempt_number=attempt_number,
                        max_attempts=max_attempts,
                        operation_scope=scope,
                    ):
                        redacted = self._redacted_exception(exc)
                        if redacted is exc:
                            raise
                        raise redacted from None
                    previous_error = exc

    def request_metadata(self, fq_model_key: str | None = None) -> LLMRequestMetadata:
        settings = self.load_settings()
        provider, model_key = self._resolve_provider_from_settings(settings, fq_model_key)
        return LLMRequestMetadata(provider_name=provider.provider_id, model=model_key)

    def turn_completion_guard_fq_model_key(self) -> str | None:
        value = self.load_settings().turn_completion_guard_fq_model_key.strip()
        return value or None

    def thread_title_fq_model_key(self) -> str | None:
        value = self.load_settings().thread_title_fq_model_key.strip()
        return value or None

    def build_provider(self, fq_model_key: str | None = None) -> AgentProvider:
        """Compatibility construction helper for ordinary static callers.

        New inference code should call ``complete``/``stream`` or retain
        ``provider_scope`` itself.  A managed target gets a small operation-backed
        adapter so a permit is never detached from a semantic request.
        """

        settings = self.load_settings()
        provider, model_key = self._resolve_provider_from_settings(settings, fq_model_key)
        selected_key = fq_model_key or settings.default_fq_model_key
        if not isinstance(provider.target, StaticLlmTarget):
            return _OperationBackedProvider(self, selected_key)
        scope = self._provider_factory_registry.provider_scope(provider, model_key=model_key)
        try:
            return scope.provider
        finally:
            scope.close()

    def build_turn_completion_guard_provider(self) -> AgentProvider | None:
        fq_model_key = self.turn_completion_guard_fq_model_key()
        if fq_model_key is None:
            return None
        return self.build_provider(fq_model_key)

    def build_thread_title_provider(self) -> AgentProvider | None:
        fq_model_key = self.thread_title_fq_model_key()
        if fq_model_key is None:
            return None
        return self.build_provider(fq_model_key)

    def validate_fq_model_key(self, fq_model_key: str) -> str:
        normalized = fq_model_key.strip()
        provider, _ = self._resolve_provider_from_settings(self.load_settings(), normalized)
        if not self._provider_factory_registry.has_factory_for(provider):
            raise ProviderImplementationUnavailableError()
        return normalized

    @staticmethod
    def fq_model_key(provider_key: str, model_key: str) -> str:
        return fq_model_key(provider_key, model_key)

    @staticmethod
    def parse_fq_model_key(fq_model_key: str) -> LLMModelRef:
        return parse_fq_model_key(fq_model_key)

    @staticmethod
    def model_options_from_settings(settings: LLMSettings) -> list[LLMModelOption]:
        return model_options_from_settings(settings)

    def _resolve_provider_from_settings(
        self,
        settings: LLMSettings,
        requested_key: str | None,
    ) -> tuple[LLMProviderConfig, str]:
        selected_key = (requested_key or settings.default_fq_model_key).strip()
        reference = parse_fq_model_key(selected_key)
        provider = self._provider_for_key(settings, reference.provider_key)
        if provider is None:
            self._raise_missing_reference(selected_key, reference.provider_key)
        if reference.model_key not in provider.models:
            if provider.is_managed:
                raise ValidationError(
                    "The exact managed LLM model reference is stale.",
                    error_code="llm_model_reference_stale",
                )
            raise NotFoundError(f"LLM model '{selected_key}' was not found.")
        if provider.retiring:
            raise ValidationError(
                "The exact managed LLM model reference is stale.",
                error_code="llm_model_reference_stale",
            )
        return provider, reference.model_key

    @staticmethod
    def _raise_missing_reference(selected_key: str, provider_key: str) -> None:
        if is_managed_llm_provider_instance_id(provider_key):
            raise ValidationError(
                "The exact managed LLM model reference is stale.",
                error_code="llm_model_reference_stale",
            )
        raise NotFoundError(f"LLM model '{selected_key}' was not found.")

    @staticmethod
    def _provider_for_key(settings: LLMSettings, provider_key: str) -> LLMProviderConfig | None:
        return settings.provider_for_id(provider_key)

    def _complete_with_retry(
        self,
        *,
        provider: AgentProvider,
        operation_scope: ProviderOperationScope | None = None,
        messages: list[ProviderMessage],
        tools: list[AgentToolSpec],
        max_attempts: int,
        retry_callback: Callable[[LLMRetryEvent], None] | None,
        before_provider_request: Callable[[], None] | None,
    ) -> ProviderResponse:
        attempts = self._max_attempts(max_attempts)
        retry_scope = operation_scope or ProviderOperationScope(provider)
        previous_error: Exception | None = None
        for attempt_number in range(1, attempts + 1):
            if previous_error is not None and retry_callback is not None:
                retry_callback(
                    self._retry_event(
                        attempt_number=attempt_number,
                        max_attempts=attempts,
                        exc=previous_error,
                    )
                )
            if before_provider_request is not None:
                before_provider_request()
            try:
                return provider.complete(messages, tools)
            except Exception as exc:
                if not self._should_retry(
                    exc,
                    attempt_number=attempt_number,
                    max_attempts=attempts,
                    operation_scope=retry_scope,
                ):
                    redacted = self._redacted_exception(exc)
                    if redacted is exc:
                        raise
                    raise redacted from None
                previous_error = exc
        raise AssertionError("LLM retry loop exited without a response or exception.")

    def _should_retry(
        self,
        exc: Exception,
        *,
        attempt_number: int,
        max_attempts: int,
        operation_scope: ProviderOperationScope | None = None,
    ) -> bool:
        if attempt_number >= max_attempts or getattr(exc, "retryable", None) is not True:
            return False
        if operation_scope is not None and not operation_scope.retry_allowed_after(exc):
            return False
        return True

    @staticmethod
    def _is_live_tool_call_progress(event: ProviderStreamEvent) -> bool:
        return event.is_tool_call_delta and not event.delta_text and event.response is None

    @staticmethod
    def _retry_event(*, attempt_number: int, max_attempts: int, exc: Exception) -> LLMRetryEvent:
        error_code = getattr(exc, "error_code", None)
        return LLMRetryEvent(
            attempt_number=attempt_number,
            max_attempts=max_attempts,
            reason="retryable_error",
            error_summary=redact_provider_error_text(exc),
            error_code=error_code if isinstance(error_code, str) else None,
        )

    @staticmethod
    def _redacted_exception(exc: Exception) -> Exception:
        redacted = redact_provider_error_text(exc)
        if redacted == str(exc):
            return exc
        return ValidationError(
            redacted,
            error_code=getattr(exc, "error_code", None),
            retryable=getattr(exc, "retryable", None),
        )

    @staticmethod
    def _max_attempts(value: int) -> int:
        if isinstance(value, bool):
            return 1
        return max(1, min(int(value), 20))


class _OperationBackedProvider:
    """Legacy ``AgentProvider`` projection that preserves managed scope lifetime."""

    def __init__(self, service: LLMService, fq_model_key: str) -> None:
        self._service = service
        self._fq_model_key = fq_model_key

    def complete(
        self,
        messages: list[ProviderMessage],
        tools: list[AgentToolSpec],
    ) -> ProviderResponse:
        return self._service.complete(
            fq_model_key=self._fq_model_key,
            messages=messages,
            tools=tools,
        )

    def stream(
        self,
        messages: list[ProviderMessage],
        tools: list[AgentToolSpec],
    ) -> Iterator[ProviderStreamEvent | LLMRetryEvent]:
        yield from self._service.stream(
            fq_model_key=self._fq_model_key,
            messages=messages,
            tools=tools,
        )


__all__ = [
    "DEFAULT_FQ_MODEL_KEY",
    "DEFAULT_MODEL_KEY",
    "DEFAULT_PROVIDER_KEY",
    "FrozenLLMSettingsSource",
    "LLMDialect",
    "LLMModelOption",
    "LLMModelRef",
    "LLMProviderConfig",
    "LLMService",
    "LLMSettings",
    "LLMSettingsService",
    "LLMSettingsSource",
    "PACKAGED_TRIAL_SECRET_SOURCE",
    "PackagedTrialLLMConfig",
    "SETTINGS_FILE_NAME",
    "TRIAL_LLM_BASE_URL_FALLBACK",
    "TRIAL_LLM_MODEL_FALLBACK",
    "TRIAL_PROVIDER_DISPLAY_NAME",
    "TRIAL_PROVIDER_KEY",
    "default_llm_settings",
    "load_packaged_trial_llm_config",
    "sanitize_settings_for_save",
]
