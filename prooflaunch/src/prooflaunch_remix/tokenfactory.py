from __future__ import annotations

import hashlib
import json
import math
import os
import re
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Callable, Mapping, Protocol, Sequence


TOKEN_FACTORY_PROVIDER = "amd_radeon_token_factory"
TOKEN_FACTORY_BASE_URL = "https://developer.amd.com.cn/radeon/api/v1"
TOKEN_FACTORY_CHAT_URL = f"{TOKEN_FACTORY_BASE_URL}/chat/completions"
TOKEN_FACTORY_API_KEY_ENV = "RADEON_TOKEN_FACTORY_API_KEY"
TOKEN_FACTORY_PUBLIC_MODELS = (
    "Qwen3.6-35B-A3B",
    "DeepSeek-V4-Flash",
    "MiniCPM5-1B",
)
TOKEN_FACTORY_POLICY_SCHEMA = "ProofLaunchTokenFactoryPolicyV1"
TOKEN_FACTORY_RECEIPT_SCHEMA = "ProofLaunchTokenFactoryReceiptV1"
TOKEN_FACTORY_DAILY_BUDGET_USD = 10.0
TOKEN_FACTORY_DAILY_RESERVE_USD = 0.0001
TOKEN_FACTORY_PROVIDER_RPM_LIMIT = 30
TOKEN_FACTORY_CLIENT_RPM_LIMIT = 24
TOKEN_FACTORY_MAX_TOKENS_PER_REQUEST = 4096
TOKEN_FACTORY_MAX_ATTEMPTS_PER_COMPLETION = 6
TOKEN_FACTORY_DEFAULT_ESTIMATED_COST_PER_ATTEMPT_USD = 0.005

_RETRYABLE_HTTP_STATUSES = {0, 408, 409, 425, 429, 500, 502, 503, 504}
_AUTH_HTTP_STATUSES = {401, 403}
_SECRET_PATTERN = re.compile(
    r"(?i)(?:bearer\s+|api[_-]?key[\"'=:\s]+)([A-Za-z0-9._-]{8,})"
)


class TokenFactoryError(RuntimeError):
    """Base error for the exclusive AMD Radeon Token Factory gateway."""


class TokenFactoryConfigurationError(TokenFactoryError):
    pass


class TokenFactoryQuotaError(TokenFactoryConfigurationError):
    pass


class TokenFactoryCallError(TokenFactoryError):
    def __init__(self, message: str, receipt: Mapping[str, object]) -> None:
        super().__init__(message)
        self.receipt = dict(receipt)


@dataclass(frozen=True)
class TokenFactoryHttpResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


class TokenFactoryTransport(Protocol):
    def post_json(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, object],
        timeout_seconds: float,
    ) -> TokenFactoryHttpResponse: ...


class UrllibTokenFactoryTransport:
    def post_json(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, object],
        timeout_seconds: float,
    ) -> TokenFactoryHttpResponse:
        request = urllib.request.Request(
            url=url,
            data=json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8"),
            headers=dict(headers),
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=timeout_seconds,
            ) as response:
                return TokenFactoryHttpResponse(
                    status=int(response.status),
                    headers=dict(response.headers.items()),
                    body=response.read(),
                )
        except urllib.error.HTTPError as error:
            return TokenFactoryHttpResponse(
                status=int(error.code),
                headers=dict(error.headers.items()) if error.headers else {},
                body=error.read(),
            )
        except urllib.error.URLError:
            return TokenFactoryHttpResponse(
                status=0,
                headers={},
                body=b"",
            )


@dataclass(frozen=True)
class TokenFactoryResult:
    provider: str
    model: str
    content: str
    response_id: str | None
    finish_reason: str | None
    usage: Mapping[str, object]
    receipt: Mapping[str, object]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class TokenFactoryQuotaPolicy:
    daily_budget_usd: float = TOKEN_FACTORY_DAILY_BUDGET_USD
    daily_reserve_usd: float = TOKEN_FACTORY_DAILY_RESERVE_USD
    provider_rpm_limit: int = TOKEN_FACTORY_PROVIDER_RPM_LIMIT
    client_rpm_limit: int = TOKEN_FACTORY_CLIENT_RPM_LIMIT
    max_tokens_per_request: int = TOKEN_FACTORY_MAX_TOKENS_PER_REQUEST
    max_attempts_per_completion: int = (
        TOKEN_FACTORY_MAX_ATTEMPTS_PER_COMPLETION
    )
    default_estimated_cost_per_attempt_usd: float = (
        TOKEN_FACTORY_DEFAULT_ESTIMATED_COST_PER_ATTEMPT_USD
    )

    def __post_init__(self) -> None:
        for name, value in (
            ("daily_budget_usd", self.daily_budget_usd),
            ("daily_reserve_usd", self.daily_reserve_usd),
            (
                "default_estimated_cost_per_attempt_usd",
                self.default_estimated_cost_per_attempt_usd,
            ),
        ):
            if not math.isfinite(value) or value < 0:
                raise TokenFactoryQuotaError(
                    f"{name} must be finite and non-negative"
                )
        if self.daily_budget_usd <= 0:
            raise TokenFactoryQuotaError("daily_budget_usd must be positive")
        if self.daily_reserve_usd >= self.daily_budget_usd:
            raise TokenFactoryQuotaError(
                "daily_reserve_usd must be below daily_budget_usd"
            )
        if self.provider_rpm_limit <= 0:
            raise TokenFactoryQuotaError(
                "provider_rpm_limit must be positive"
            )
        if not 0 < self.client_rpm_limit <= self.provider_rpm_limit:
            raise TokenFactoryQuotaError(
                "client_rpm_limit must be positive and no greater than "
                "provider_rpm_limit"
            )
        if self.max_tokens_per_request <= 0:
            raise TokenFactoryQuotaError(
                "max_tokens_per_request must be positive"
            )
        if self.max_attempts_per_completion <= 0:
            raise TokenFactoryQuotaError(
                "max_attempts_per_completion must be positive"
            )

    @property
    def spendable_daily_usd(self) -> float:
        return self.daily_budget_usd - self.daily_reserve_usd


@dataclass(frozen=True)
class TokenFactoryQuotaSnapshot:
    used_usd: float
    remaining_usd: float
    tokens_today: int
    reset_at: str
    observed_at: str

    def __post_init__(self) -> None:
        if (
            not math.isfinite(self.used_usd)
            or not math.isfinite(self.remaining_usd)
            or self.used_usd < 0
            or self.remaining_usd < 0
        ):
            raise TokenFactoryQuotaError(
                "quota snapshot spend values must be finite and non-negative"
            )
        if self.tokens_today < 0:
            raise TokenFactoryQuotaError(
                "quota snapshot tokens_today cannot be negative"
            )
        for name, value in (
            ("reset_at", self.reset_at),
            ("observed_at", self.observed_at),
        ):
            try:
                datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as error:
                raise TokenFactoryQuotaError(
                    f"quota snapshot {name} must be ISO-8601"
                ) from error


class TokenFactoryQuotaGuard:
    """Conservative in-process guard for the provider's daily/RPM limits.

    The provider profile remains the authority for cross-process spend.  A
    fresh profile snapshot can seed the guard before a batch; every attempted
    request then reserves a conservative cost estimate and one RPM slot.
    """

    def __init__(
        self,
        policy: TokenFactoryQuotaPolicy | None = None,
        *,
        snapshot: TokenFactoryQuotaSnapshot | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.policy = policy or TokenFactoryQuotaPolicy()
        self._snapshot = snapshot
        self._estimated_used_usd = snapshot.used_usd if snapshot else 0.0
        self._attempt_times: deque[float] = deque()
        self._monotonic = monotonic
        self._lock = threading.Lock()

    def reseed(self, snapshot: TokenFactoryQuotaSnapshot) -> None:
        with self._lock:
            self._snapshot = snapshot
            self._estimated_used_usd = snapshot.used_usd

    def _trim(self, now: float) -> None:
        while self._attempt_times and now - self._attempt_times[0] >= 60:
            self._attempt_times.popleft()

    def ensure_completion_capacity(
        self,
        *,
        maximum_attempts: int,
        max_tokens: int,
        estimated_cost_per_attempt_usd: float,
    ) -> None:
        if maximum_attempts > self.policy.max_attempts_per_completion:
            raise TokenFactoryQuotaError(
                "completion attempt ceiling exceeds the quota policy"
            )
        if max_tokens > self.policy.max_tokens_per_request:
            raise TokenFactoryQuotaError(
                f"max_tokens exceeds the {self.policy.max_tokens_per_request} "
                "per-request quota policy"
            )
        if (
            not math.isfinite(estimated_cost_per_attempt_usd)
            or estimated_cost_per_attempt_usd <= 0
        ):
            raise TokenFactoryQuotaError(
                "estimated_cost_per_attempt_usd must be positive and finite"
            )
        with self._lock:
            now = self._monotonic()
            self._trim(now)
            if (
                len(self._attempt_times) + maximum_attempts
                > self.policy.client_rpm_limit
            ):
                raise TokenFactoryQuotaError(
                    "completion could exceed the conservative client RPM limit"
                )
            projected = self._estimated_used_usd + (
                maximum_attempts * estimated_cost_per_attempt_usd
            )
            if projected > self.policy.spendable_daily_usd:
                raise TokenFactoryQuotaError(
                    "completion could consume the protected daily reserve"
                )

    def authorize_attempt(
        self,
        *,
        estimated_cost_usd: float,
    ) -> None:
        with self._lock:
            now = self._monotonic()
            self._trim(now)
            if len(self._attempt_times) >= self.policy.client_rpm_limit:
                raise TokenFactoryQuotaError(
                    "conservative client RPM limit reached"
                )
            projected = self._estimated_used_usd + estimated_cost_usd
            if projected > self.policy.spendable_daily_usd:
                raise TokenFactoryQuotaError(
                    "protected daily reserve would be consumed"
                )
            self._attempt_times.append(now)
            self._estimated_used_usd = projected

    def receipt(self) -> dict[str, object]:
        with self._lock:
            now = self._monotonic()
            self._trim(now)
            return {
                "daily_budget_usd": self.policy.daily_budget_usd,
                "daily_reserve_usd": self.policy.daily_reserve_usd,
                "spendable_daily_usd": self.policy.spendable_daily_usd,
                "provider_rpm_limit": self.policy.provider_rpm_limit,
                "client_rpm_limit": self.policy.client_rpm_limit,
                "max_tokens_per_request": (
                    self.policy.max_tokens_per_request
                ),
                "max_attempts_per_completion": (
                    self.policy.max_attempts_per_completion
                ),
                "estimated_used_usd": round(
                    self._estimated_used_usd,
                    8,
                ),
                "attempts_in_rolling_minute": len(self._attempt_times),
                "provider_profile_snapshot_required_before_large_batch": True,
                "snapshot_observed_at": (
                    self._snapshot.observed_at
                    if self._snapshot is not None
                    else None
                ),
            }


def tokenfactory_policy() -> dict[str, object]:
    """Return the immutable official-first boundary for online inference."""

    return {
        "schema": TOKEN_FACTORY_POLICY_SCHEMA,
        "external_inference_priority": [
            TOKEN_FACTORY_PROVIDER,
            "approved_third_party_fallback",
        ],
        "official_base_url": TOKEN_FACTORY_BASE_URL,
        "official_chat_completions_url": TOKEN_FACTORY_CHAT_URL,
        "api_key_env": TOKEN_FACTORY_API_KEY_ENV,
        "allowed_public_models": list(TOKEN_FACTORY_PUBLIC_MODELS),
        "other_online_model_apis_allowed": "approved_fallback_only",
        "fallback_activation": (
            "all_official_public_models_unavailable_or_invalid"
        ),
        "fallback_quality_contract": (
            "radeon-official-finetuning-extreme-v1"
        ),
        "competition_core_path": "local_radeon_only",
        "external_output_evidence_class": "advisory_not_local_execution",
        "secret_persistence_allowed": False,
        "quota": {
            "daily_budget_usd": TOKEN_FACTORY_DAILY_BUDGET_USD,
            "daily_reserve_usd": TOKEN_FACTORY_DAILY_RESERVE_USD,
            "provider_rpm_limit": TOKEN_FACTORY_PROVIDER_RPM_LIMIT,
            "client_rpm_limit": TOKEN_FACTORY_CLIENT_RPM_LIMIT,
            "max_tokens_per_request": (
                TOKEN_FACTORY_MAX_TOKENS_PER_REQUEST
            ),
            "max_attempts_per_completion": (
                TOKEN_FACTORY_MAX_ATTEMPTS_PER_COMPLETION
            ),
            "profile_snapshot_required_before_large_batch": True,
        },
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _request_hash(messages: Sequence[Mapping[str, object]]) -> str:
    canonical = json.dumps(
        list(messages),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _error_code(response: TokenFactoryHttpResponse) -> str:
    if response.status == 0:
        return "network_error"
    if response.status == 502:
        return "model_gateway_unavailable"
    if response.status in _AUTH_HTTP_STATUSES:
        return "authentication_rejected"
    if response.status == 429:
        return "rate_limited"
    return f"http_{response.status}"


def _safe_request_id(headers: Mapping[str, str]) -> str | None:
    lowered = {str(key).lower(): str(value) for key, value in headers.items()}
    for key in ("x-request-id", "request-id", "x-amzn-requestid"):
        value = lowered.get(key)
        if value:
            return _SECRET_PATTERN.sub("[REDACTED]", value)[:256]
    return None


def _validate_messages(
    messages: Sequence[Mapping[str, object]],
) -> tuple[Mapping[str, object], ...]:
    if isinstance(messages, (str, bytes)) or not messages:
        raise TokenFactoryConfigurationError("messages must be a non-empty sequence")
    validated: list[Mapping[str, object]] = []
    for message in messages:
        if not isinstance(message, Mapping):
            raise TokenFactoryConfigurationError("each message must be an object")
        role = message.get("role")
        if role not in {"system", "user", "assistant", "tool"}:
            raise TokenFactoryConfigurationError(f"unsupported message role: {role}")
        if "content" not in message:
            raise TokenFactoryConfigurationError("each message requires content")
        validated.append(dict(message))
    return tuple(validated)


class TokenFactoryClient:
    """Exclusive online-inference client for the official Radeon endpoint.

    The endpoint cannot be overridden. Prompts, outputs, and credentials are
    deliberately excluded from receipts; only a request hash and operational
    metadata are recorded.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        transport: TokenFactoryTransport | None = None,
        quota_guard: TokenFactoryQuotaGuard | None = None,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], str] = _utc_now,
    ) -> None:
        selected_key = api_key or os.environ.get(TOKEN_FACTORY_API_KEY_ENV)
        if not selected_key or not selected_key.strip():
            raise TokenFactoryConfigurationError(
                f"missing {TOKEN_FACTORY_API_KEY_ENV}; credentials are never "
                "stored in project files"
            )
        self._api_key = selected_key.strip()
        self._transport = transport or UrllibTokenFactoryTransport()
        self._quota_guard = quota_guard or TokenFactoryQuotaGuard()
        self._sleep = sleep
        self._now = now

    def complete(
        self,
        messages: Sequence[Mapping[str, object]],
        *,
        models: Sequence[str] = TOKEN_FACTORY_PUBLIC_MODELS,
        purpose: str,
        temperature: float = 0.2,
        max_tokens: int = 1024,
        timeout_seconds: float = 45.0,
        retry_rounds: int = 1,
        retry_backoff_seconds: float = 0.5,
        estimated_cost_per_attempt_usd: float = (
            TOKEN_FACTORY_DEFAULT_ESTIMATED_COST_PER_ATTEMPT_USD
        ),
        enable_thinking: bool = False,
    ) -> TokenFactoryResult:
        validated_messages = _validate_messages(messages)
        selected_models = tuple(dict.fromkeys(models))
        if not selected_models:
            raise TokenFactoryConfigurationError("at least one model is required")
        unknown = set(selected_models) - set(TOKEN_FACTORY_PUBLIC_MODELS)
        if unknown:
            raise TokenFactoryConfigurationError(
                "only public models exposed by the official Radeon Token Factory "
                f"policy are allowed: {', '.join(sorted(unknown))}"
            )
        if not purpose.strip():
            raise TokenFactoryConfigurationError("purpose is required for audit")
        if not math.isfinite(temperature) or not 0 <= temperature <= 2:
            raise TokenFactoryConfigurationError(
                "temperature must be finite and between 0 and 2"
            )
        if not isinstance(max_tokens, int) or max_tokens <= 0:
            raise TokenFactoryConfigurationError("max_tokens must be positive")
        if not isinstance(enable_thinking, bool):
            raise TokenFactoryConfigurationError(
                "enable_thinking must be a boolean"
            )
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise TokenFactoryConfigurationError("timeout_seconds must be positive")
        if not isinstance(retry_rounds, int) or retry_rounds < 0:
            raise TokenFactoryConfigurationError("retry_rounds cannot be negative")
        if (
            not math.isfinite(retry_backoff_seconds)
            or retry_backoff_seconds < 0
        ):
            raise TokenFactoryConfigurationError(
                "retry_backoff_seconds cannot be negative"
            )
        maximum_attempts = len(selected_models) * (retry_rounds + 1)
        self._quota_guard.ensure_completion_capacity(
            maximum_attempts=maximum_attempts,
            max_tokens=max_tokens,
            estimated_cost_per_attempt_usd=(
                estimated_cost_per_attempt_usd
            ),
        )

        request_sha256 = _request_hash(validated_messages)
        started_at = self._now()
        attempts: list[dict[str, object]] = []
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "ProofLaunch-TokenFactory/1.0",
        }

        for round_index in range(retry_rounds + 1):
            for model in selected_models:
                self._quota_guard.authorize_attempt(
                    estimated_cost_usd=estimated_cost_per_attempt_usd,
                )
                attempt_started = time.monotonic()
                response = self._transport.post_json(
                    url=TOKEN_FACTORY_CHAT_URL,
                    headers=headers,
                    payload={
                        "model": model,
                        "messages": list(validated_messages),
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                        "chat_template_kwargs": {
                            "enable_thinking": enable_thinking,
                        },
                    },
                    timeout_seconds=timeout_seconds,
                )
                duration_ms = round(
                    (time.monotonic() - attempt_started) * 1000,
                    3,
                )
                attempt = {
                    "attempt": len(attempts) + 1,
                    "round": round_index + 1,
                    "provider": TOKEN_FACTORY_PROVIDER,
                    "model": model,
                    "endpoint": TOKEN_FACTORY_CHAT_URL,
                    "http_status": response.status,
                    "error_code": (
                        None if response.status == 200 else _error_code(response)
                    ),
                    "request_id": _safe_request_id(response.headers),
                    "duration_ms": duration_ms,
                }
                attempts.append(attempt)

                if response.status == 200:
                    try:
                        payload = json.loads(response.body.decode("utf-8"))
                        choice = payload["choices"][0]
                        message = choice["message"]
                        content = message["content"]
                        reasoning = message.get("reasoning")
                        if not isinstance(content, str):
                            raise TypeError("response content is not text")
                    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, IndexError, TypeError):
                        attempt["error_code"] = "invalid_response_contract"
                        continue
                    attempt["finish_reason"] = choice.get("finish_reason")
                    attempt["output_nonempty"] = bool(content.strip())
                    attempt["reasoning_field_present"] = isinstance(
                        reasoning,
                        str,
                    ) and bool(reasoning)
                    if not content.strip():
                        attempt["error_code"] = (
                            "reasoning_budget_exhausted"
                            if (
                                attempt["reasoning_field_present"]
                                and choice.get("finish_reason") == "length"
                            )
                            else "empty_response_content"
                        )
                        continue
                    receipt = {
                        "schema": TOKEN_FACTORY_RECEIPT_SCHEMA,
                        "status": "passed",
                        "provider": TOKEN_FACTORY_PROVIDER,
                        "official_endpoint": TOKEN_FACTORY_CHAT_URL,
                        "purpose": purpose.strip(),
                        "request_sha256": request_sha256,
                        "started_at": started_at,
                        "completed_at": self._now(),
                        "selected_model": model,
                        "attempt_count": len(attempts),
                        "attempts": attempts,
                        "credential": {
                            "source": TOKEN_FACTORY_API_KEY_ENV,
                            "persisted": False,
                            "redacted": True,
                        },
                        "quota": self._quota_guard.receipt(),
                        "evidence_boundary": "external_advisory_not_local_radeon_execution",
                    }
                    return TokenFactoryResult(
                        provider=TOKEN_FACTORY_PROVIDER,
                        model=model,
                        content=content,
                        response_id=(
                            str(payload["id"]) if payload.get("id") is not None else None
                        ),
                        finish_reason=(
                            str(choice["finish_reason"])
                            if choice.get("finish_reason") is not None
                            else None
                        ),
                        usage=(
                            dict(payload["usage"])
                            if isinstance(payload.get("usage"), Mapping)
                            else {}
                        ),
                        receipt=receipt,
                    )

                if response.status in _AUTH_HTTP_STATUSES:
                    break

            if attempts and attempts[-1]["http_status"] in _AUTH_HTTP_STATUSES:
                break
            if round_index < retry_rounds and any(
                attempt["http_status"] in _RETRYABLE_HTTP_STATUSES
                for attempt in attempts
            ):
                self._sleep(retry_backoff_seconds * (2**round_index))

        receipt = {
            "schema": TOKEN_FACTORY_RECEIPT_SCHEMA,
            "status": "blocked",
            "provider": TOKEN_FACTORY_PROVIDER,
            "official_endpoint": TOKEN_FACTORY_CHAT_URL,
            "purpose": purpose.strip(),
            "request_sha256": request_sha256,
            "started_at": started_at,
            "completed_at": self._now(),
            "selected_model": None,
            "attempt_count": len(attempts),
            "attempts": attempts,
            "credential": {
                "source": TOKEN_FACTORY_API_KEY_ENV,
                "persisted": False,
                "redacted": True,
            },
            "quota": self._quota_guard.receipt(),
            "evidence_boundary": "external_advisory_not_local_radeon_execution",
        }
        raise TokenFactoryCallError(
            "all official Radeon Token Factory model attempts failed",
            receipt,
        )
