from __future__ import annotations

import os
from importlib import import_module
from typing import Mapping
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator


RELEASES_OSS_PUBLIC_URL_ENV = "RELEASES_OSS_PUBLIC_URL"
TRIAL_LLM_BASE_URL_ENV = "XENIX_TRIAL_LLM_BASE_URL"
TRIAL_LLM_API_KEY_ENV = "XENIX_TRIAL_LLM_API_KEY"
TRIAL_LLM_MODEL_ENV = "XENIX_TRIAL_LLM_MODEL"
TRIAL_LOCK_DAYS_ENV = "XENIX_TRIAL_LOCK_DAYS"
TRIAL_LOCK_STATE_SECRET_ENV = "XENIX_TRIAL_LOCK_STATE_SECRET"
TRIAL_PURCHASE_URL_ENV = "XENIX_TRIAL_PURCHASE_URL"

_GENERATED_MODULE = "xenix._generated_release_config"
_OTEL_EXACT_NAMES = frozenset({"OTEL_SDK_DISABLED"})
_OTEL_PREFIXES = ("OTEL_EXPORTER_", "XENIX_OTEL_")


def _normalized_http_url(value: str, *, name: str) -> str:
    cleaned = value.strip().rstrip("/")
    if not cleaned:
        return ""
    parsed = urlsplit(cleaned)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{name} must be an absolute HTTP(S) URL.")
    if parsed.query or parsed.fragment:
        raise ValueError(f"{name} cannot contain a query string or fragment.")
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


def _is_otel_environment_name(name: str) -> bool:
    return name in _OTEL_EXACT_NAMES or name.startswith(_OTEL_PREFIXES)


class ReleaseConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    releases_oss_public_url: str = ""
    trial_llm_base_url: str = "https://api.openai.com"
    trial_llm_api_key: str = ""
    trial_llm_model: str = "gpt-4o-mini"
    trial_lock_days: int = Field(default=0, ge=0)
    trial_lock_state_secret: str = ""
    trial_lock_build_id: str = "development"
    trial_purchase_url: str = ""
    otel_environment: dict[str, str] = Field(default_factory=dict)

    @field_validator(
        "releases_oss_public_url",
        "trial_llm_base_url",
        "trial_purchase_url",
        mode="before",
    )
    @classmethod
    def _normalize_urls(cls, value: object, info: ValidationInfo) -> str:
        return _normalized_http_url(str(value or ""), name=info.field_name or "URL")

    @field_validator(
        "trial_llm_api_key",
        "trial_llm_model",
        "trial_lock_state_secret",
        "trial_lock_build_id",
        mode="before",
    )
    @classmethod
    def _strip_strings(cls, value: object) -> str:
        return str(value or "").strip()

    @field_validator("otel_environment", mode="before")
    @classmethod
    def _validate_otel_environment(cls, value: object) -> dict[str, str]:
        if value is None:
            return {}
        if not isinstance(value, Mapping):
            raise ValueError("otel_environment must be a mapping.")
        result: dict[str, str] = {}
        for raw_name, raw_value in value.items():
            name = str(raw_name).strip()
            if not _is_otel_environment_name(name):
                raise ValueError(f"Unsupported embedded telemetry setting: {name}")
            setting = str(raw_value).strip()
            if setting:
                result[name] = setting
        return result

    @model_validator(mode="after")
    def _validate_trial_lock(self) -> ReleaseConfig:
        if self.trial_lock_days > 0 and not self.trial_lock_state_secret:
            raise ValueError(
                f"{TRIAL_LOCK_STATE_SECRET_ENV} is required when {TRIAL_LOCK_DAYS_ENV} is enabled."
            )
        return self

    @property
    def update_feed_url(self) -> str:
        return self.releases_oss_public_url

    @property
    def setup_url(self) -> str:
        if not self.releases_oss_public_url:
            return ""
        return f"{self.releases_oss_public_url}/Xenix-Setup.exe"

    def artifact_url(self, artifact_name: str) -> str:
        """Resolve one catalog-owned immutable release artifact."""

        name = str(artifact_name).strip()
        if (
            not self.releases_oss_public_url
            or not name
            or "/" in name
            or "\\" in name
            or name in {".", ".."}
        ):
            return ""
        return f"{self.releases_oss_public_url}/{name}"

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
        *,
        release_build: bool = False,
        public_release_build: bool = False,
        build_commit: str = "development",
    ) -> ReleaseConfig:
        values = environment if environment is not None else os.environ
        raw_days = str(values.get(TRIAL_LOCK_DAYS_ENV, "") or "").strip()
        try:
            trial_lock_days = int(raw_days, 10) if raw_days else 0
        except ValueError as exc:
            raise ValueError(f"{TRIAL_LOCK_DAYS_ENV} must be a non-negative integer.") from exc

        config = cls(
            releases_oss_public_url=values.get(RELEASES_OSS_PUBLIC_URL_ENV, ""),
            trial_llm_base_url=values.get(TRIAL_LLM_BASE_URL_ENV, "https://api.openai.com"),
            trial_llm_api_key=values.get(TRIAL_LLM_API_KEY_ENV, ""),
            trial_llm_model=values.get(TRIAL_LLM_MODEL_ENV, "gpt-4o-mini"),
            trial_lock_days=trial_lock_days,
            trial_lock_state_secret=values.get(TRIAL_LOCK_STATE_SECRET_ENV, ""),
            trial_lock_build_id=build_commit,
            trial_purchase_url=values.get(TRIAL_PURCHASE_URL_ENV, ""),
            otel_environment={
                name: value
                for name, value in values.items()
                if _is_otel_environment_name(name) and str(value).strip()
            },
        )
        config._validate_build_requirements(
            values,
            release_build=release_build,
            public_release_build=public_release_build,
        )
        return config

    def _validate_build_requirements(
        self,
        environment: Mapping[str, str],
        *,
        release_build: bool,
        public_release_build: bool,
    ) -> None:
        if release_build:
            required = (
                TRIAL_LLM_BASE_URL_ENV,
                TRIAL_LLM_API_KEY_ENV,
                TRIAL_LLM_MODEL_ENV,
                TRIAL_LOCK_DAYS_ENV,
                TRIAL_LOCK_STATE_SECRET_ENV,
                TRIAL_PURCHASE_URL_ENV,
            )
            missing = [name for name in required if not str(environment.get(name, "") or "").strip()]
            if missing:
                raise ValueError(f"Formal release build is missing required setting(s): {', '.join(missing)}")
            if self.trial_lock_days <= 0:
                raise ValueError(f"Formal release builds require a positive {TRIAL_LOCK_DAYS_ENV}.")
            for name, value in (
                (TRIAL_LLM_BASE_URL_ENV, self.trial_llm_base_url),
                (TRIAL_PURCHASE_URL_ENV, self.trial_purchase_url),
            ):
                if urlsplit(value).scheme != "https":
                    raise ValueError(f"Formal release builds require HTTPS for {name}.")
        if public_release_build:
            if not self.releases_oss_public_url:
                raise ValueError(f"Public release builds require {RELEASES_OSS_PUBLIC_URL_ENV}.")
            if urlsplit(self.releases_oss_public_url).scheme != "https":
                raise ValueError(f"Public release builds require HTTPS for {RELEASES_OSS_PUBLIC_URL_ENV}.")


def _generated_payload() -> dict[str, object] | None:
    try:
        generated = import_module(_GENERATED_MODULE)
    except ModuleNotFoundError as exc:
        if exc.name != _GENERATED_MODULE:
            raise
        return None
    payload = getattr(generated, "RELEASE_CONFIG", None)
    if not isinstance(payload, dict):
        raise ValueError("Generated release configuration is missing RELEASE_CONFIG.")
    return payload


def load_release_config() -> ReleaseConfig:
    payload = _generated_payload()
    if payload is not None:
        return ReleaseConfig.model_validate(payload)
    return ReleaseConfig.from_environment()


def apply_frozen_otel_environment() -> None:
    payload = _generated_payload()
    if payload is None:
        return
    config = ReleaseConfig.model_validate(payload)
    for name in tuple(os.environ):
        if _is_otel_environment_name(name):
            os.environ.pop(name, None)
    os.environ.update(config.otel_environment)
