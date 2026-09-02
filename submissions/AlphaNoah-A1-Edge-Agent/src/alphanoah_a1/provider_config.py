"""Secret-free configuration contract for AI runtime provider composition."""

from __future__ import annotations

import json
import math
import os
import re
import tempfile
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping, Self
from urllib.parse import urlsplit

CONFIG_SCHEMA_VERSION = "ai-runtime-config-v1"
DEFAULT_CONFIG_FILENAME = "ai_runtime_config.json"
_ENVIRONMENT_NAME = re.compile(r"[A-Z_][A-Z0-9_]{0,127}")
_MODEL_NAME = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9._/-]*(?::[A-Za-z0-9][A-Za-z0-9._-]*)?"
)
_SECRET_SHAPED_MODEL = re.compile(
    r"(?i)^(?:sk-|github_pat_|gh[opurs]_|xox[baprsce]-|AKIA|ASIA)"
)
_MODEL_DIGEST = re.compile(r"[a-fA-F0-9]{64}")


class ProviderKind(StrEnum):
    """Provider implementations supported by the composition layer."""

    OLLAMA = "ollama"
    VLLM = "vllm"
    OPENAI_COMPATIBLE = "openai_compatible"
    FAKE = "fake"


class RuntimeSelectionMode(StrEnum):
    """Whether an unselected configuration may use deterministic discovery."""

    AUTO = "auto"
    MANUAL = "manual"


@dataclass(frozen=True, slots=True)
class ProviderSettings:
    """One provider's non-secret endpoint and model configuration."""

    kind: ProviderKind
    enabled: bool = True
    endpoint: str = ""
    model: str = ""
    api_key_env: str = ""
    timeout_seconds: float = 60.0
    model_digest: str | None = None

    def __post_init__(self) -> None:
        try:
            kind = ProviderKind(self.kind)
        except (TypeError, ValueError) as exc:
            raise ValueError("provider kind is invalid") from exc
        if not isinstance(self.enabled, bool):
            raise ValueError("provider enabled must be boolean")
        endpoint = self._trimmed_text(self.endpoint, "endpoint", 500)
        model = self._trimmed_text(self.model, "model", 200)
        api_key_env = self._trimmed_text(
            self.api_key_env,
            "api_key_env",
            128,
        )
        timeout_seconds = self.timeout_seconds
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(float(timeout_seconds))
            or not 0 < float(timeout_seconds) <= 1_800
        ):
            raise ValueError(
                "provider timeout_seconds must be a finite number "
                "between 0 and 1800"
            )
        model_digest = self.model_digest
        if model_digest is not None:
            if (
                not isinstance(model_digest, str)
                or _MODEL_DIGEST.fullmatch(model_digest) is None
            ):
                raise ValueError(
                    "provider model_digest must be a full SHA-256 digest"
                )
            if kind is not ProviderKind.OLLAMA:
                raise ValueError(
                    "provider model_digest is supported only for ollama"
                )
            model_digest = model_digest.lower()
        if model and (
            _MODEL_NAME.fullmatch(model) is None
            or _SECRET_SHAPED_MODEL.search(model) is not None
        ):
            raise ValueError("provider model is invalid")
        if api_key_env and _ENVIRONMENT_NAME.fullmatch(api_key_env) is None:
            raise ValueError("api_key_env must be an environment variable name")
        if endpoint:
            self._validate_endpoint(endpoint)
            parsed = urlsplit(endpoint)
            if kind is ProviderKind.OLLAMA and (
                parsed.scheme != "http"
                or parsed.hostname not in {
                    "127.0.0.1",
                    "localhost",
                    "::1",
                }
                or parsed.path not in {"", "/"}
            ):
                raise ValueError(
                    "ollama endpoint must be an HTTP loopback base URL"
                )
        if kind is ProviderKind.FAKE and (
            endpoint or model or api_key_env
        ):
            raise ValueError("fake provider does not accept endpoint settings")
        if kind is ProviderKind.OLLAMA and api_key_env:
            raise ValueError("ollama provider does not accept an API key")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "endpoint", endpoint)
        object.__setattr__(self, "model", model)
        object.__setattr__(self, "api_key_env", api_key_env)
        object.__setattr__(self, "timeout_seconds", float(timeout_seconds))
        object.__setattr__(self, "model_digest", model_digest)

    @property
    def configured(self) -> bool:
        if not self.enabled:
            return False
        if self.kind is ProviderKind.FAKE:
            return True
        return bool(self.endpoint and self.model)

    @staticmethod
    def _trimmed_text(value: object, field: str, maximum: int) -> str:
        if not isinstance(value, str):
            raise ValueError(f"provider {field} must be text")
        if (
            value != value.strip()
            or len(value) > maximum
            or "\x00" in value
            or any(ord(character) < 32 for character in value)
        ):
            raise ValueError(f"provider {field} is invalid")
        return value

    @staticmethod
    def _validate_endpoint(endpoint: str) -> None:
        parsed = urlsplit(endpoint)
        try:
            parsed.port
        except ValueError as exc:
            raise ValueError("provider endpoint port is invalid") from exc
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "provider endpoint must be an HTTP(S) URL without credentials"
            )


@dataclass(frozen=True, slots=True)
class AIRuntimeConfig:
    """Versioned provider composition configuration without secret values."""

    mode: RuntimeSelectionMode = RuntimeSelectionMode.AUTO
    selected: ProviderKind | None = None
    providers: tuple[ProviderSettings, ...] = ()
    schema_version: str = CONFIG_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != CONFIG_SCHEMA_VERSION:
            raise ValueError(
                f"AI runtime config schema must be {CONFIG_SCHEMA_VERSION}"
            )
        try:
            mode = RuntimeSelectionMode(self.mode)
        except (TypeError, ValueError) as exc:
            raise ValueError("AI runtime selection mode is invalid") from exc
        selected = self.selected
        if selected is not None:
            try:
                selected = ProviderKind(selected)
            except (TypeError, ValueError) as exc:
                raise ValueError("selected provider is invalid") from exc
        providers = tuple(self.providers)
        if any(
            not isinstance(item, ProviderSettings) for item in providers
        ):
            raise ValueError(
                "providers must contain ProviderSettings objects"
            )
        identities = [item.kind for item in providers]
        if len(identities) != len(set(identities)):
            raise ValueError("provider configuration contains duplicates")
        if selected is not None and selected not in identities:
            raise ValueError(
                "selected provider has no configuration section"
            )
        object.__setattr__(self, "mode", mode)
        object.__setattr__(self, "selected", selected)
        object.__setattr__(
            self,
            "providers",
            tuple(sorted(providers, key=lambda item: item.kind.value)),
        )

    def get(self, kind: ProviderKind | str) -> ProviderSettings | None:
        provider_kind = ProviderKind(kind)
        return next(
            (
                item
                for item in self.providers
                if item.kind is provider_kind
            ),
            None,
        )

    def with_selected(self, kind: ProviderKind | str) -> Self:
        provider_kind = ProviderKind(kind)
        if self.get(provider_kind) is None:
            raise ValueError("selected provider has no configuration section")
        return replace(self, selected=provider_kind)

    def to_dict(self) -> dict[str, Any]:
        """Return only persistable non-secret configuration."""

        provider_payload: dict[str, dict[str, Any]] = {}
        for settings in self.providers:
            values: dict[str, Any] = {
                "enabled": settings.enabled,
                "timeout_seconds": settings.timeout_seconds,
            }
            if settings.endpoint:
                values["endpoint"] = settings.endpoint
            if settings.model:
                values["model"] = settings.model
            if settings.api_key_env:
                values["api_key_env"] = settings.api_key_env
            if settings.model_digest is not None:
                values["model_digest"] = settings.model_digest
            provider_payload[settings.kind.value] = values
        return {
            "schema_version": self.schema_version,
            "mode": self.mode.value,
            "selected": (
                self.selected.value if self.selected is not None else None
            ),
            "providers": provider_payload,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        if not isinstance(data, Mapping):
            raise ValueError("AI runtime config must be a JSON object")
        allowed = {"schema_version", "mode", "selected", "providers"}
        unknown = set(data) - allowed
        if unknown:
            raise ValueError(
                "AI runtime config has unknown fields: "
                + ", ".join(sorted(str(item) for item in unknown))
            )
        raw_providers = data.get("providers")
        if not isinstance(raw_providers, Mapping):
            raise ValueError("AI runtime providers must be a JSON object")
        providers: list[ProviderSettings] = []
        for raw_kind, raw_settings in raw_providers.items():
            try:
                kind = ProviderKind(raw_kind)
            except (TypeError, ValueError) as exc:
                raise ValueError("AI runtime provider name is invalid") from exc
            if not isinstance(raw_settings, Mapping):
                raise ValueError(
                    f"{kind.value} provider settings must be an object"
                )
            settings_allowed = {
                "enabled",
                "endpoint",
                "model",
                "api_key_env",
                "timeout_seconds",
                "model_digest",
            }
            settings_unknown = set(raw_settings) - settings_allowed
            if settings_unknown:
                raise ValueError(
                    f"{kind.value} provider has unknown fields: "
                    + ", ".join(
                        sorted(str(item) for item in settings_unknown)
                    )
                )
            providers.append(
                ProviderSettings(
                    kind=kind,
                    enabled=raw_settings.get("enabled", True),
                    endpoint=raw_settings.get("endpoint", ""),
                    model=raw_settings.get("model", ""),
                    api_key_env=raw_settings.get("api_key_env", ""),
                    timeout_seconds=raw_settings.get(
                        "timeout_seconds",
                        60.0,
                    ),
                    model_digest=raw_settings.get("model_digest"),
                )
            )
        return cls(
            schema_version=data.get("schema_version", ""),
            mode=data.get("mode", RuntimeSelectionMode.AUTO.value),
            selected=data.get("selected"),
            providers=tuple(providers),
        )


def default_runtime_config() -> AIRuntimeConfig:
    """Return safe defaults that can discover local services and Fake."""

    return AIRuntimeConfig(
        providers=(
            ProviderSettings(
                kind=ProviderKind.OLLAMA,
                endpoint="http://127.0.0.1:11434",
            ),
            ProviderSettings(
                kind=ProviderKind.VLLM,
                endpoint="http://127.0.0.1:8000/v1",
            ),
            ProviderSettings(
                kind=ProviderKind.OPENAI_COMPATIBLE,
                enabled=False,
            ),
            ProviderSettings(kind=ProviderKind.FAKE),
        )
    )


def load_runtime_config(path: str | Path) -> AIRuntimeConfig:
    config_path = Path(path)
    if not config_path.exists():
        return default_runtime_config()
    try:
        if config_path.stat().st_size > 262_144:
            raise ValueError("AI runtime config exceeds 262144 bytes")
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError(
            f"invalid AI runtime config: {config_path.name}"
        ) from exc
    return AIRuntimeConfig.from_dict(payload)


def save_runtime_config(
    path: str | Path,
    config: AIRuntimeConfig,
) -> None:
    """Atomically save config; API keys exist only in the environment."""

    if not isinstance(config, AIRuntimeConfig):
        raise TypeError("config must be AIRuntimeConfig")
    config_path = Path(path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(
        config.to_dict(),
        ensure_ascii=False,
        allow_nan=False,
        indent=2,
        sort_keys=True,
    )
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=config_path.parent,
            prefix=f".{config_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(encoded)
            temporary.write("\n")
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, config_path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            try:
                temporary_path.unlink()
            except OSError:
                pass
