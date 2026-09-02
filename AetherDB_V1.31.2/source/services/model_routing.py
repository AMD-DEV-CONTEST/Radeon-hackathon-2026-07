"""Unique model resolution and routed execution."""

import asyncio
import json
import os
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Any, AsyncIterator

from services.model_execution.requests import ModelTaskRequest
from services.model_execution.results import ModelTaskResult
from services.model_execution.results import normalize_provider_response
from services.model_registry import (
    find_bindings,
    get_model_profile,
    get_provider,
    list_model_profiles,
    record_model_usage,
)
from services.model_reliability import (
    FallbackPolicy,
    FallbackRequired,
    ModelExecutionError,
    RetryPolicy,
    normalize_model_error,
)


class RouteStatus(str, Enum):
    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    UNAVAILABLE = "unavailable"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class RouteCandidate:
    model_profile_id: str
    score: float
    reason: tuple[str, ...]


@dataclass(frozen=True)
class RouteResult:
    status: RouteStatus
    selected_model_profile_id: str | None
    candidates: tuple[RouteCandidate, ...]
    reason: str
    requires_user_confirmation: bool


class ModelRouteError(RuntimeError):
    def __init__(self, result: RouteResult):
        super().__init__(f"Model route is {result.status.value}: {result.reason}")
        self.result = result


_DEFAULT_SECURE_STORE = object()
OLLAMA_PROVIDER_TYPES = {"local", "local_ollama", "ollama"}
TTS_TASK_TYPES = {
    "audio.tts.preview",
    "audio.tts.segment",
    "audio.tts.chapter",
}
TTS_MODEL_TYPES = {
    "audio",
    "tts",
    "text_to_speech",
    "audio_generation",
    "multimodal_audio",
}
TEXT_TASK_TYPES = {
    "text.polish",
    "text.expand",
    "text.continue",
    "text.assist",
    "text.rewrite",
    "text.translate",
    "text.summarize",
    "text.logic_check",
    "chapter.analyze",
    "chapter.extract",
    "context.reason",
    "world.consistency_check",
    "prompt.compose",
    "changeset.build",
    "changeset.review",
    "rag.text.query",
    "rag.text.index",
    "rag.hybrid.query",
}
TEXT_MODEL_TYPES = {
    "chat",
    "text",
    "llm",
    "language",
    "generation",
    "text_generation",
    "multimodal",
    "multimodal_text",
}


class CredentialResolver:
    def __init__(self, env=None, secure_store=_DEFAULT_SECURE_STORE):
        self._env = env if env is not None else os.environ
        if secure_store is _DEFAULT_SECURE_STORE:
            try:
                from services.credential_store import get_model_credential_store

                secure_store = get_model_credential_store()
            except Exception:
                secure_store = None
        self._secure_store = secure_store

    def resolve(self, credential_ref: str | None) -> str | None:
        if not credential_ref:
            return None
        if credential_ref.startswith("env:"):
            credential = self._env.get(credential_ref.removeprefix("env:"))
            if credential is None:
                raise ValueError("Credential reference is not configured")
            return credential
        if credential_ref.startswith("secure:") and self._secure_store is not None:
            return self._secure_store.get_secret(credential_ref.removeprefix("secure:"))
        raise ValueError("Unsupported or unavailable credential_ref")


def _candidate_state(profile: dict, request: ModelTaskRequest):
    provider = get_provider(profile["provider_id"])
    if not provider:
        return "unavailable", "provider_missing"
    if not provider or not provider["enabled"] or not profile["enabled"]:
        return "unavailable", "disabled"
    if provider["health_status"] in {"unhealthy", "blocked"}:
        return "unavailable", "provider_unhealthy"
    if profile["health_status"] in {"unhealthy", "blocked"} or profile["remote_status"] == "unavailable":
        return "unavailable", "model_unhealthy"
    if request.canonical_task_type in TTS_TASK_TYPES:
        if provider["provider_type"] in OLLAMA_PROVIDER_TYPES:
            return "blocked", "ollama_tts_unsupported"
        if str(profile.get("model_type") or "").strip().lower() not in TTS_MODEL_TYPES:
            return "unavailable", "tts_capability_required"
    if request.canonical_task_type in TEXT_TASK_TYPES:
        if str(profile.get("model_type") or "").strip().lower() not in TEXT_MODEL_TYPES:
            return "unavailable", "text_capability_required"
    if request.requires_json and not profile["supports_json_mode"]:
        return "unavailable", "json_mode_required"
    if request.requires_streaming and not profile["supports_streaming"]:
        return "unavailable", "streaming_required"
    if request.privacy_level in {"local_only", "strict_local"} and profile["privacy_level"] != "local_only":
        return "blocked", "privacy_policy"
    cost_rank = {"free": 0, "low": 1, "medium": 2, "high": 3}
    profile_cost = cost_rank.get(profile["cost_level"])
    maximum_cost = cost_rank.get(request.max_cost_level)
    if profile_cost is not None and maximum_cost is not None and profile_cost > maximum_cost:
        return "blocked", "cost_policy"
    return "eligible", "compatible"


class UniqueModelRouter:
    def resolve(self, request: ModelTaskRequest) -> RouteResult:
        if request.user_selected_model_id:
            return self._resolve_ids(
                request,
                [request.user_selected_model_id],
                "single_request_selection",
            )

        scopes = []
        if request.session_id:
            scopes.append(("session", request.session_id))
        if request.book_id:
            scopes.append(("book", f"{request.database_id}/{request.book_id}"))
        scopes.extend((("database", request.database_id), ("global", None)))

        for scope_type, scope_id in scopes:
            for binding_task_type in request.binding_task_types:
                bindings = find_bindings(scope_type, scope_id, binding_task_type)
                if not bindings:
                    continue
                top_priority = bindings[0]["priority"]
                target_ids = list(dict.fromkeys(
                    binding["target_id"] for binding in bindings if binding["priority"] == top_priority
                ))
                binding_kind = (
                    "legacy_exact" if binding_task_type == request.legacy_task_type else "canonical"
                )
                return self._resolve_ids(
                    request,
                    target_ids,
                    f"{scope_type}_binding:{binding_kind}",
                )

        return self._resolve_ids(
            request,
            [profile["id"] for profile in list_model_profiles()],
            "eligible_candidates",
        )

    def _resolve_ids(self, request: ModelTaskRequest, profile_ids: list[str], reason: str) -> RouteResult:
        eligible = []
        blocked_reasons = []
        for profile_id in profile_ids:
            profile = get_model_profile(profile_id)
            if not profile:
                continue
            state, state_reason = _candidate_state(profile, request)
            if state == "eligible":
                eligible.append(RouteCandidate(profile_id, 1.0, (reason, state_reason)))
            elif state == "blocked":
                blocked_reasons.append(state_reason)

        if len(eligible) == 1:
            return RouteResult(RouteStatus.RESOLVED, eligible[0].model_profile_id, tuple(eligible), reason, False)
        if len(eligible) > 1:
            return RouteResult(RouteStatus.AMBIGUOUS, None, tuple(eligible[:5]), "multiple_candidates", True)
        status = RouteStatus.BLOCKED if blocked_reasons else RouteStatus.UNAVAILABLE
        result_reason = blocked_reasons[0] if blocked_reasons else "no_compatible_model"
        return RouteResult(status, None, (), result_reason, False)


class ExistingProviderAdapter:
    async def complete(self, provider: dict, model_profile: dict, messages: list, options: dict):
        credential = options.pop("credential", None)
        task_request = options.pop("_aetherdb_request", None)
        provider_type = provider["provider_type"]
        if (
            provider_type in {"local", "local_ollama", "ollama"}
            and task_request is not None
        ):
            from services.ollama_execution import (
                get_ollama_execution_coordinator,
            )

            return await get_ollama_execution_coordinator().execute(
                provider,
                model_profile,
                task_request,
                options,
            )

        def call_provider():
            from services.llm_provider import (
                ClaudeProvider,
                GeminiProvider,
                OllamaProvider,
                OpenAIProvider,
            )

            model_name = model_profile["provider_model_name"]
            if provider_type in {"local", "local_ollama", "ollama"}:
                client = OllamaProvider(provider["base_url"], model_name)
            elif provider_type == "claude":
                client = ClaudeProvider(credential, model_name)
            elif provider_type == "gemini":
                client = GeminiProvider(credential, model_name)
            else:
                client = OpenAIProvider(provider["base_url"], credential, model_name)
            content = client.chat(messages, model=model_name, **options)
            return {"content": content, "usage": {}, "provider_request_id": None}

        return await asyncio.to_thread(call_provider)


class RoutedModelExecutionGateway:
    def __init__(
        self,
        router=None,
        adapter=None,
        credential_resolver=None,
        retry_policy=None,
        fallback_policy=FallbackPolicy.ASK,
    ):
        self._router = router or UniqueModelRouter()
        self._adapter = adapter or ExistingProviderAdapter()
        self._credential_resolver = credential_resolver or CredentialResolver()
        self._retry_policy = retry_policy or RetryPolicy()
        self._fallback_policy = fallback_policy

    async def execute(self, request: ModelTaskRequest) -> ModelTaskResult:
        return await self._execute(request, allow_fallback=True, fallback_used=False)

    def resolve(self, request: ModelTaskRequest) -> RouteResult:
        return self._router.resolve(request)

    async def execute_resolved(self, request: ModelTaskRequest, route: RouteResult) -> ModelTaskResult:
        if route.status is not RouteStatus.RESOLVED:
            raise ModelRouteError(route)
        return await self._execute(
            request,
            allow_fallback=True,
            fallback_used=False,
            route=route,
        )

    async def execute_fallback(
        self,
        request: ModelTaskRequest,
        model_profile_id: str,
        *,
        confirmed: bool,
    ) -> ModelTaskResult:
        if not confirmed:
            raise PermissionError("Fallback requires explicit confirmation")
        fallback_request = replace(request, user_selected_model_id=model_profile_id)
        return await self._execute(fallback_request, allow_fallback=False, fallback_used=True)

    async def _execute(self, request, *, allow_fallback: bool, fallback_used: bool, route=None):
        started_at = datetime.now(timezone.utc).isoformat()
        route = route or self._router.resolve(request)
        if route.status is not RouteStatus.RESOLVED:
            raise ModelRouteError(route)
        profile = get_model_profile(route.selected_model_profile_id)
        if not profile:
            raise ModelRouteError(
                RouteResult(RouteStatus.UNAVAILABLE, None, (), "model_missing", False)
            )
        state, state_reason = _candidate_state(profile, request)
        if state != "eligible":
            status = RouteStatus.BLOCKED if state == "blocked" else RouteStatus.UNAVAILABLE
            raise ModelRouteError(RouteResult(status, None, (), state_reason, False))
        provider = get_provider(profile["provider_id"])
        credential = self._credential_resolver.resolve(provider.get("credential_ref"))
        options = {"credential": credential}
        if profile.get("max_output_tokens"):
            options["max_tokens"] = profile["max_output_tokens"]
        if (
            request.requires_json
            and profile.get("supports_json_mode")
            and provider["provider_type"] not in OLLAMA_PROVIDER_TYPES
        ):
            options["response_format"] = {"type": "json_object"}
        raw = None
        last_error = None
        for attempt in range(1, self._retry_policy.max_attempts + 1):
            try:
                attempt_options = dict(options)
                if (
                    isinstance(self._adapter, ExistingProviderAdapter)
                    and provider["provider_type"]
                    in {"local", "local_ollama", "ollama"}
                ):
                    attempt_options["_aetherdb_request"] = request
                provider_raw = await self._adapter.complete(
                    provider,
                    profile,
                    list(request.messages),
                    attempt_options,
                )
                normalized = normalize_provider_response(provider_raw)
                raw = {
                    "content": normalized.content,
                    "thinking_content": normalized.thinking_content,
                    "usage": dict(normalized.usage),
                    "finish_reason": normalized.finish_reason,
                    "provider_request_id": normalized.provider_request_id,
                    "warnings": normalized.warnings,
                    "execution_evidence": (
                        dict(provider_raw.get("execution_evidence") or {})
                        if isinstance(provider_raw, dict)
                        else {}
                    ),
                }
                await asyncio.to_thread(
                    self._record_attempt,
                    request,
                    route,
                    provider,
                    profile,
                    raw.get("usage") or {},
                    attempt,
                    fallback_used,
                    True,
                    None,
                )
                break
            except Exception as exc:
                last_error = normalize_model_error(exc)
                await asyncio.to_thread(
                    self._record_attempt,
                    request,
                    route,
                    provider,
                    profile,
                    {},
                    attempt,
                    fallback_used,
                    False,
                    last_error.code.value,
                )
                if not self._retry_policy.should_retry(last_error, attempt):
                    break
                await asyncio.sleep(self._retry_policy.delay_seconds(last_error, attempt))

        if raw is None:
            if allow_fallback and self._fallback_policy is FallbackPolicy.ASK:
                candidates = self._fallback_candidates(request, profile["id"])
                if candidates:
                    raise FallbackRequired(last_error, candidates, profile["id"])
            raise last_error

        usage = raw.get("usage") or {}
        return ModelTaskResult(
            task_id=request.task_id,
            model_profile_id=profile["id"],
            provider_id=provider["id"],
            content=raw.get("content", ""),
            usage=usage,
            raw_provider_request_id=raw.get("provider_request_id"),
            provider_model_name=profile["provider_model_name"],
            thinking_content=raw.get("thinking_content", ""),
            finish_reason=raw.get("finish_reason"),
            warnings=tuple(raw.get("warnings") or ()),
            task_type=request.canonical_task_type,
            legacy_task_type=request.legacy_task_type,
            runtime=provider["provider_type"],
            model_revision=profile.get("model_revision"),
            status="completed",
            execution_evidence={
                "provider_id": provider["id"],
                "provider_model_name": profile["provider_model_name"],
                "route_reason": route.reason,
                "attempts": attempt,
                **dict(raw.get("execution_evidence") or {}),
            },
            fallback_used=fallback_used,
            created_at=started_at,
            completed_at=datetime.now(timezone.utc).isoformat(),
        )

    @staticmethod
    def _fallback_candidates(request, excluded_profile_id):
        candidates = []
        for profile in list_model_profiles():
            if profile["id"] == excluded_profile_id:
                continue
            state, _ = _candidate_state(profile, request)
            if state == "eligible":
                candidates.append(profile["id"])
        return tuple(candidates[:5])

    @staticmethod
    def _record_attempt(
        request, route, provider, profile, usage, attempt, fallback_used, success, error_code,
    ):
        record_model_usage(
            task_id=request.task_id,
            task_type=request.canonical_task_type,
            provider_id=provider["id"],
            model_profile_id=profile["id"],
            provider_model_name=profile["provider_model_name"],
            route_reason=route.reason,
            usage=usage,
            success=success,
            attempt_id=f"{profile['id']}:{attempt}",
            fallback_used=fallback_used,
            error_code=error_code,
        )
        try:
            from services.audit_log import log_event
            from services.db import get_db

            db = get_db(request.database_id)
            try:
                log_event(
                    db,
                    "model.execute" if success else "model.execute.failed",
                    "Model task executed" if success else "Model task failed",
                    target=request.task_id,
                    database_id=request.database_id,
                    book_id=request.book_id or "",
                    details=json.dumps(
                        {
                            "provider_id": provider["id"],
                            "model_profile_id": profile["id"],
                            "provider_model_name": profile["provider_model_name"],
                            "task_type": request.canonical_task_type,
                            "legacy_task_type": request.legacy_task_type,
                            "error_code": error_code,
                        },
                        ensure_ascii=False,
                    ),
                )
            finally:
                db.close()
        except Exception:
            pass

    async def stream(self, request: ModelTaskRequest) -> AsyncIterator[dict[str, Any]]:
        from services.model_streaming import stream_model_task

        async for event in stream_model_task(self, request):
            yield event.model_dump()
