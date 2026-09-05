"""LLM-owned provider catalog, settings views, and command boundary.

This module owns durable LLM provider identities and selection semantics.  It
does not know how a managed provider is realized: a manager identifier is an
opaque capability reference and construction belongs to ``provider_factory``.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ...config import AppPaths
from ...exceptions import NotFoundError, ValidationError
from ...release_config import load_release_config
from ..settings_store import SettingsConflictError, SettingsStore

SETTINGS_FILE_NAME = "agent_settings.json"
DEFAULT_PROVIDER_KEY = "openai"
DEFAULT_MODEL_KEY = "gpt-4o-mini"
DEFAULT_FQ_MODEL_KEY = f"{DEFAULT_PROVIDER_KEY}/{DEFAULT_MODEL_KEY}"
TRIAL_PROVIDER_KEY = "trial"
TRIAL_PROVIDER_DISPLAY_NAME = "Trial"
PACKAGED_TRIAL_SECRET_SOURCE = "packaged_trial"
TRIAL_LLM_BASE_URL_FALLBACK = "https://api.openai.com"
TRIAL_LLM_MODEL_FALLBACK = DEFAULT_MODEL_KEY
_MANAGED_PROVIDER_ID_PREFIX = "llm-managed-"
_SETTINGS_SCHEMA_VERSION = 2


class LLMDialect(StrEnum):
    OPENAI_COMPATIBLE = "openai_compatible"


class StaticLlmTarget(BaseModel):
    """User-owned static endpoint configuration.

    It is deliberately separate from a managed reference.  Dialect, endpoint,
    and credential details are meaningful only for this target variant.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["static"] = "static"
    dialect: LLMDialect = LLMDialect.OPENAI_COMPATIBLE
    base_url: str = "https://api.openai.com"
    api_key: str = Field(default="", repr=False)
    timeout_seconds: int = Field(default=120, ge=1, le=3600)
    streaming_enabled: bool = True
    dialect_config: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _normalize_kind(cls, value: Any) -> Any:
        if not isinstance(value, Mapping):
            return value
        payload = dict(value)
        raw_kind = payload.pop("target_type", payload.pop("type", payload.get("kind", "static")))
        if str(raw_kind).strip().lower() not in {"", "static", "static_endpoint", "endpoint"}:
            raise ValueError("Static LLM target kind is invalid.")
        payload["kind"] = "static"
        return payload

    @field_validator("base_url")
    @classmethod
    def _normalize_base_url(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        if not normalized:
            raise ValueError("Static LLM base URL cannot be empty.")
        return normalized

    @field_validator("api_key", mode="before")
    @classmethod
    def _normalize_api_key(cls, value: Any) -> str:
        return "" if value is None else str(value)


class ManagedLlmProviderRef(BaseModel):
    """Opaque exact identity of one manager-owned LLM generation.

    ``manager_id`` is intentionally not a deployment-specific concept.  The
    LLM domain needs only a stable routing key plus the exact installation/
    generation pair.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["managed"] = "managed"
    manager_id: str
    installation_id: str
    component_generation_id: str

    @model_validator(mode="before")
    @classmethod
    def _normalize_kind(cls, value: Any) -> Any:
        if not isinstance(value, Mapping):
            return value
        payload = dict(value)
        raw_kind = payload.pop("target_type", payload.pop("type", payload.get("kind", "managed")))
        if str(raw_kind).strip().lower() not in {"", "managed", "managed_provider"}:
            raise ValueError("Managed LLM provider reference kind is invalid.")
        payload["kind"] = "managed"
        return payload

    @field_validator("manager_id", "installation_id", "component_generation_id")
    @classmethod
    def _require_identifier(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Managed LLM provider identifiers cannot be blank.")
        return normalized


LlmProviderTarget = StaticLlmTarget | ManagedLlmProviderRef


def managed_llm_provider_instance_id(
    reference: ManagedLlmProviderRef,
    *,
    owner: str = "llm",
) -> str:
    """Derive an immutable manager-neutral provider instance identifier.

    A digest keeps arbitrary opaque identifiers out of the FQ-model-key grammar
    while binding identity to the capability owner, manager, installation, and
    component generation.  It is not a mutable display key.
    """

    normalized_owner = owner.strip()
    if not normalized_owner:
        raise ValidationError("Managed LLM provider owner cannot be empty.")
    canonical = "\0".join(
        (
            normalized_owner,
            reference.manager_id,
            reference.installation_id,
            reference.component_generation_id,
        )
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"{_MANAGED_PROVIDER_ID_PREFIX}{digest}"


# Shorter aliases make composition adapters readable without introducing a
# second identity rule.
managed_llm_provider_id = managed_llm_provider_instance_id


def is_managed_llm_provider_instance_id(provider_id: str) -> bool:
    return provider_id.strip().startswith(_MANAGED_PROVIDER_ID_PREFIX)


class ManagedLlmProviderProjection(BaseModel):
    """Immutable capability-normalized data accepted from a manager.

    Dynamic binding facts are intentionally impossible to place in the declared
    shape.  Compatibility metadata is JSON-shaped but rejects endpoint/secret/
    runtime-oriented keys recursively as a second line of defense.
    """

    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    reference: ManagedLlmProviderRef
    display_name: str
    models: list[str]
    manifest_digest: str
    model_compatibility: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _normalize_legacy_names(cls, value: Any) -> Any:
        if not isinstance(value, Mapping):
            return value
        payload = dict(value)
        if "reference" not in payload:
            for alias in ("managed_ref", "provider_ref", "target"):
                if alias in payload:
                    payload["reference"] = payload.pop(alias)
                    break
        if "model_compatibility" not in payload:
            for alias in ("compatibility", "compatibility_metadata"):
                if alias in payload:
                    payload["model_compatibility"] = payload.pop(alias)
                    break
        return payload

    @field_validator("display_name")
    @classmethod
    def _normalize_display_name(cls, value: str) -> str:
        return value.strip()

    @field_validator("id")
    @classmethod
    def _normalize_projection_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized or "/" in normalized:
            raise ValueError("Managed LLM provider ID is invalid.")
        return normalized

    @field_validator("models")
    @classmethod
    def _validate_models(cls, value: list[str]) -> list[str]:
        return _unique_model_keys(value)

    @field_validator("manifest_digest")
    @classmethod
    def _require_manifest_digest(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Managed LLM manifest digest cannot be blank.")
        if "://" in normalized:
            raise ValueError("Managed LLM manifest digest cannot be an endpoint URL.")
        return normalized

    @field_validator("model_compatibility")
    @classmethod
    def _validate_compatibility(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _validated_projection_metadata(value)

    @model_validator(mode="after")
    def _validate_exact_id(self) -> "ManagedLlmProviderProjection":
        expected_id = managed_llm_provider_instance_id(self.reference)
        if self.id is None:
            self.id = expected_id
        elif self.id != expected_id:
            raise ValueError("Managed LLM provider ID is not generation-specific.")
        return self

    @property
    def provider_instance_id(self) -> str:
        assert self.id is not None
        return self.id

    @property
    def provider_id(self) -> str:
        return self.provider_instance_id

    @property
    def compatibility_metadata(self) -> dict[str, Any]:
        return dict(self.model_compatibility)

    @property
    def target(self) -> ManagedLlmProviderRef:
        """Catalog-style alias used by optional manager composition code."""

        return self.reference


class LLMProviderConfig(BaseModel):
    """One durable provider-instance catalog entry.

    ``key`` and the flat endpoint properties remain read-compatible projections
    for the current settings UI.  New durable data uses ``provider_id`` and the
    explicit ``target`` tagged union instead.
    """

    model_config = ConfigDict(extra="forbid")

    provider_id: str = ""
    display_name: str = "OpenAI"
    models: list[str] = Field(default_factory=lambda: [DEFAULT_MODEL_KEY])
    target: LlmProviderTarget = Field(default_factory=StaticLlmTarget)
    manifest_digest: str | None = None
    model_compatibility: dict[str, Any] = Field(default_factory=dict)
    read_only: bool = False
    retiring: bool = False

    @model_validator(mode="before")
    @classmethod
    def _migrate_flat_configuration(cls, value: Any) -> Any:
        if not isinstance(value, Mapping):
            return value
        payload = dict(value)
        if "provider_id" not in payload:
            for alias in ("key", "id", "provider_instance_id"):
                if alias in payload:
                    payload["provider_id"] = payload.pop(alias)
                    break

        if "model_compatibility" not in payload:
            for alias in ("compatibility", "compatibility_metadata"):
                if alias in payload:
                    payload["model_compatibility"] = payload.pop(alias)
                    break

        target = payload.get("target")
        if target is None:
            managed_reference = payload.pop("managed_reference", payload.pop("managed_ref", None))
            if managed_reference is not None:
                payload["target"] = managed_reference
            elif {
                "manager_id",
                "installation_id",
                "component_generation_id",
            }.issubset(payload):
                payload["target"] = {
                    "kind": "managed",
                    "manager_id": payload.pop("manager_id"),
                    "installation_id": payload.pop("installation_id"),
                    "component_generation_id": payload.pop("component_generation_id"),
                }
            else:
                static_keys = (
                    "dialect",
                    "base_url",
                    "api_key",
                    "timeout_seconds",
                    "streaming_enabled",
                    "dialect_config",
                )
                static_target = {"kind": "static"}
                for key in static_keys:
                    if key in payload:
                        static_target[key] = payload.pop(key)
                payload["target"] = static_target
        elif isinstance(target, Mapping):
            nested_target = dict(target)
            # Accept old flat fields alongside a newly introduced static target
            # during the compatibility window, but never persist that ambiguity.
            if str(nested_target.get("kind", "static")).strip().lower() in {
                "",
                "static",
                "static_endpoint",
                "endpoint",
            }:
                for key in (
                    "dialect",
                    "base_url",
                    "api_key",
                    "timeout_seconds",
                    "streaming_enabled",
                    "dialect_config",
                ):
                    if key in payload and key not in nested_target:
                        nested_target[key] = payload.pop(key)
            payload["target"] = nested_target
        return payload

    @field_validator("provider_id")
    @classmethod
    def _validate_provider_id(cls, value: str) -> str:
        normalized = value.strip()
        if normalized and "/" in normalized:
            raise ValueError("Provider ID cannot contain '/'.")
        return normalized

    @field_validator("display_name")
    @classmethod
    def _normalize_display_name(cls, value: str) -> str:
        return value.strip()

    @field_validator("models")
    @classmethod
    def _validate_models(cls, value: list[str]) -> list[str]:
        return _unique_model_keys(value)

    @field_validator("manifest_digest")
    @classmethod
    def _normalize_manifest_digest(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("model_compatibility")
    @classmethod
    def _validate_compatibility(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _validated_projection_metadata(value)

    @model_validator(mode="after")
    def _validate_target_identity(self) -> "LLMProviderConfig":
        if isinstance(self.target, ManagedLlmProviderRef):
            expected_id = managed_llm_provider_instance_id(self.target)
            if not self.provider_id:
                self.provider_id = expected_id
            if self.provider_id != expected_id:
                raise ValueError("Managed LLM provider ID does not match its exact reference.")
            if self.manifest_digest is None:
                raise ValueError("Managed LLM provider requires a manifest digest.")
            self.read_only = True
            return self

        if not self.provider_id:
            self.provider_id = DEFAULT_PROVIDER_KEY
        if is_managed_llm_provider_instance_id(self.provider_id):
            raise ValueError("Static LLM provider cannot use a managed provider instance ID.")
        if self.read_only or self.retiring:
            raise ValueError("Static LLM provider cannot be manager-owned or retiring.")
        if self.manifest_digest is not None or self.model_compatibility:
            raise ValueError("Static LLM provider cannot carry managed projection metadata.")
        return self

    @classmethod
    def from_managed_projection(cls, projection: ManagedLlmProviderProjection) -> "LLMProviderConfig":
        return cls(
            provider_id=projection.provider_instance_id,
            display_name=projection.display_name,
            models=list(projection.models),
            target=projection.reference,
            manifest_digest=projection.manifest_digest,
            model_compatibility=dict(projection.model_compatibility),
            read_only=True,
        )

    @property
    def key(self) -> str:
        """Legacy provider-key projection; it is the exact provider instance ID."""

        return self.provider_id

    @property
    def provider_instance_id(self) -> str:
        return self.provider_id

    @property
    def id(self) -> str:
        """Catalog-style alias for the exact provider-instance identity."""

        return self.provider_id

    @property
    def is_managed(self) -> bool:
        return isinstance(self.target, ManagedLlmProviderRef)

    @property
    def managed_reference(self) -> ManagedLlmProviderRef | None:
        return self.target if isinstance(self.target, ManagedLlmProviderRef) else None

    @property
    def dialect(self) -> LLMDialect:
        # The legacy UI reads this projection.  Managed entries are read-only in
        # the domain command boundary, so no endpoint data is synthesized here.
        return self.target.dialect if isinstance(self.target, StaticLlmTarget) else LLMDialect.OPENAI_COMPATIBLE

    @property
    def base_url(self) -> str:
        return self.target.base_url if isinstance(self.target, StaticLlmTarget) else ""

    @property
    def api_key(self) -> str:
        return self.target.api_key if isinstance(self.target, StaticLlmTarget) else ""

    @property
    def timeout_seconds(self) -> int:
        return self.target.timeout_seconds if isinstance(self.target, StaticLlmTarget) else 120

    @property
    def streaming_enabled(self) -> bool:
        return self.target.streaming_enabled if isinstance(self.target, StaticLlmTarget) else True

    @property
    def dialect_config(self) -> dict[str, Any]:
        return dict(self.target.dialect_config) if isinstance(self.target, StaticLlmTarget) else {}


class PackagedTrialLLMConfig(BaseModel):
    base_url: str
    api_key: str = Field(repr=False)
    model: str

    @property
    def enabled(self) -> bool:
        return bool(self.api_key.strip())


class LLMModelRef(BaseModel):
    provider_key: str
    model_key: str


class LLMModelOption(BaseModel):
    fq_model_key: str
    provider_key: str
    model_key: str
    label: str


class LLMSettings(BaseModel):
    """Revisioned-domain payload for the LLM provider catalog."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[2] = _SETTINGS_SCHEMA_VERSION
    providers: list[LLMProviderConfig] = Field(default_factory=lambda: [LLMProviderConfig()])
    default_fq_model_key: str = DEFAULT_FQ_MODEL_KEY
    turn_completion_guard_fq_model_key: str = ""
    thread_title_fq_model_key: str = ""
    retry_attempts: int = Field(default=5, ge=1, le=20)

    @model_validator(mode="before")
    @classmethod
    def _migrate_legacy_payload(cls, value: Any) -> Any:
        if not isinstance(value, Mapping):
            return value
        payload = dict(value)
        if "providers" in payload:
            if "schema_version" not in payload:
                payload["schema_version"] = _SETTINGS_SCHEMA_VERSION
            return payload
        return _legacy_payload_to_settings(payload)

    @model_validator(mode="after")
    def _validate_provider_catalog(self) -> "LLMSettings":
        provider_ids: set[str] = set()
        available: set[str] = set()
        for provider in self.providers:
            if provider.provider_id in provider_ids:
                raise ValueError(f"Provider ID '{provider.provider_id}' is duplicated.")
            provider_ids.add(provider.provider_id)
            for model_key in provider.models:
                available.add(fq_model_key(provider.provider_id, model_key))

        # Preserve old static-file behavior for a malformed/older static default,
        # but never repair a lost generation-specific managed selection.
        if self.default_fq_model_key not in available and not _is_managed_fq_model_key(self.default_fq_model_key):
            static_provider = next(
                (provider for provider in self.providers if not provider.is_managed),
                None,
            )
            if static_provider is not None:
                self.default_fq_model_key = fq_model_key(static_provider.provider_id, static_provider.models[0])

        for field_name in (
            "turn_completion_guard_fq_model_key",
            "thread_title_fq_model_key",
        ):
            selected = getattr(self, field_name).strip()
            if selected and selected not in available and not _is_managed_fq_model_key(selected):
                raise ValueError(f"{field_name} does not match a configured provider model.")
            setattr(self, field_name, selected)
        return self

    def provider_for_id(self, provider_id: str) -> LLMProviderConfig | None:
        normalized = provider_id.strip()
        return next((provider for provider in self.providers if provider.provider_id == normalized), None)

    def model_available(self, fq_key: str) -> bool:
        try:
            reference = parse_fq_model_key(fq_key)
        except ValidationError:
            return False
        provider = self.provider_for_id(reference.provider_key)
        return provider is not None and reference.model_key in provider.models


@dataclass(frozen=True, slots=True)
class LLMSettingsSnapshot:
    """Read-only revision marker paired with a detached domain settings view."""

    settings: LLMSettings
    revision: int


@dataclass(frozen=True, slots=True)
class ManagedLlmProviderProjectionStatus:
    """Redacted settings-side status of one exact managed projection."""

    exists: bool
    retiring: bool
    default_selected: bool
    turn_completion_guard_selected: bool
    thread_title_selected: bool


class LLMSettingsSource(Protocol):
    """Read-only inference port implemented by the LLM settings domain owner."""

    def load(self) -> LLMSettings: ...


class LLMSettingsReadView(LLMSettingsSource, Protocol):
    def load_snapshot(self) -> LLMSettingsSnapshot: ...


class LLMSettingsUserCommands(Protocol):
    def replace_user_settings(
        self,
        settings: LLMSettings,
        *,
        expected_revision: int,
    ) -> LLMSettingsSnapshot: ...

    def set_default_fq_model_key(
        self,
        fq_model_key: str,
        *,
        expected_revision: int,
    ) -> LLMSettingsSnapshot: ...


class ManagedLlmProviderCommands(Protocol):
    def ensure_managed_provider(
        self,
        projection: ManagedLlmProviderProjection,
    ) -> LLMSettingsSnapshot: ...

    def mark_managed_provider_retiring(
        self,
        reference: ManagedLlmProviderRef,
    ) -> LLMSettingsSnapshot: ...

    def remove_managed_provider(
        self,
        reference: ManagedLlmProviderRef,
    ) -> LLMSettingsSnapshot: ...

    def projection_status(
        self,
        reference: ManagedLlmProviderRef,
    ) -> ManagedLlmProviderProjectionStatus: ...


class FrozenLLMSettingsSource:
    """Read-only in-memory settings source for an isolated LLM service."""

    def __init__(self, settings: LLMSettings) -> None:
        self._settings = settings.model_copy(deep=True)

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"

    def load(self) -> LLMSettings:
        return self._settings.model_copy(deep=True)

    def load_snapshot(self) -> LLMSettingsSnapshot:
        return LLMSettingsSnapshot(settings=self.load(), revision=0)

    def save(self, settings: LLMSettings) -> None:
        """Legacy write-shaped call retained as an explicit read-only failure."""

        del settings
        raise ValidationError(
            "LLM settings are read-only for this run.",
            error_code="llm_settings_read_only",
        )


class LLMSettingsService(LLMSettingsReadView, LLMSettingsUserCommands, ManagedLlmProviderCommands):
    """One LLM-domain owner with narrow read, user-command, and manager ports.

    ``SettingsStore`` is optional only while application composition still uses
    the legacy path constructor.  Passing a store makes it the sole writer and
    enables revisioned commands; the direct path remains a compatibility reader
    for pre-TP-03 JSON documents.
    """

    def __init__(
        self,
        paths: AppPaths | None = None,
        *,
        settings_store: SettingsStore | None = None,
        document_id: str = SETTINGS_FILE_NAME,
    ) -> None:
        if settings_store is None and paths is None:
            raise TypeError("LLMSettingsService requires AppPaths or SettingsStore.")
        if not document_id.endswith(".json"):
            raise ValueError("LLM settings document ID must be a .json file name.")
        self._settings_store = settings_store
        self._document_id = document_id
        self._settings_path = (paths.config / document_id) if paths is not None else settings_store.root / document_id
        self._legacy_lock = threading.RLock()

    @property
    def settings_path(self) -> Path:
        return self._settings_path

    @property
    def document_id(self) -> str:
        return self._document_id

    def load(self) -> LLMSettings:
        return self.load_snapshot().settings.model_copy(deep=True)

    def load_snapshot(self) -> LLMSettingsSnapshot:
        if self._settings_store is not None:
            stored = self._settings_store.load(self._document_id)
            settings = _settings_from_payload(stored.payload)
            return LLMSettingsSnapshot(settings=settings, revision=stored.revision)
        with self._legacy_lock:
            if not self._settings_path.exists():
                return LLMSettingsSnapshot(settings=default_llm_settings(), revision=0)
            payload = json.loads(self._settings_path.read_text(encoding="utf-8"))
            return LLMSettingsSnapshot(settings=LLMSettings.model_validate(payload), revision=0)

    def save(self, settings: LLMSettings) -> None:
        """Compatibility bridge for the current direct-path settings dialog.

        It never lets an older full user document replace manager-owned entries.
        The revisioned store path intentionally rejects this broad command; a
        future UI must submit ``replace_user_settings`` with its snapshot revision.
        """

        if self._settings_store is not None:
            raise ValidationError(
                "LLM settings require a revisioned user command.",
                error_code="llm_settings_full_save_unsupported",
            )
        incoming = settings.model_copy(deep=True)
        with self._legacy_lock:
            current = self.load_snapshot().settings
            merged = _merge_user_settings(current, incoming, allow_selection_changes=True)
            self._settings_path.parent.mkdir(parents=True, exist_ok=True)
            sanitized = sanitize_settings_for_save(merged)
            self._settings_path.write_text(
                sanitized.model_dump_json(indent=2),
                encoding="utf-8",
            )

    def replace_user_settings(
        self,
        settings: LLMSettings,
        *,
        expected_revision: int,
    ) -> LLMSettingsSnapshot:
        incoming = settings.model_copy(deep=True)
        return self._compare_and_swap_user(
            expected_revision,
            lambda current: _merge_user_settings(current, incoming, allow_selection_changes=True),
        )

    # Intentional aliases for composition code that calls the boundary by its
    # command shape rather than its historical service name.
    apply_user_settings = replace_user_settings
    replace_user_provider_settings = replace_user_settings

    def set_default_fq_model_key(
        self,
        fq_model_key: str,
        *,
        expected_revision: int,
    ) -> LLMSettingsSnapshot:
        return self._set_selection("default_fq_model_key", fq_model_key, expected_revision=expected_revision)

    def set_turn_completion_guard_fq_model_key(
        self,
        fq_model_key: str | None,
        *,
        expected_revision: int,
    ) -> LLMSettingsSnapshot:
        return self._set_selection(
            "turn_completion_guard_fq_model_key",
            fq_model_key or "",
            expected_revision=expected_revision,
        )

    def set_thread_title_fq_model_key(
        self,
        fq_model_key: str | None,
        *,
        expected_revision: int,
    ) -> LLMSettingsSnapshot:
        return self._set_selection(
            "thread_title_fq_model_key",
            fq_model_key or "",
            expected_revision=expected_revision,
        )

    def ensure_managed_provider(
        self,
        projection: ManagedLlmProviderProjection,
    ) -> LLMSettingsSnapshot:
        desired = LLMProviderConfig.from_managed_projection(projection)

        def transform(current: LLMSettings) -> LLMSettings:
            existing = current.provider_for_id(desired.provider_id)
            if existing is None:
                return current.model_copy(update={"providers": [*current.providers, desired]}, deep=True)
            if existing.managed_reference != desired.managed_reference:
                raise ValidationError(
                    "Managed LLM provider ID is already owned by a different exact reference.",
                    error_code="llm_provider_owner_conflict",
                )
            if _managed_provider_projection_tuple(existing) != _managed_provider_projection_tuple(desired):
                raise ValidationError(
                    "Managed LLM provider projection is immutable once registered.",
                    error_code="llm_provider_projection_conflict",
                )
            return current

        return self._mutate_managed(transform)

    ensure_managed_projection = ensure_managed_provider

    def mark_managed_provider_retiring(
        self,
        reference: ManagedLlmProviderRef,
    ) -> LLMSettingsSnapshot:
        provider_id = managed_llm_provider_instance_id(reference)

        def transform(current: LLMSettings) -> LLMSettings:
            provider = _require_exact_managed_provider(current, provider_id, reference)
            if provider.retiring:
                return current
            providers = [
                item.model_copy(update={"retiring": True}) if item.provider_id == provider_id else item
                for item in current.providers
            ]
            return current.model_copy(update={"providers": providers}, deep=True)

        return self._mutate_managed(transform)

    retire_managed_provider = mark_managed_provider_retiring

    def managed_provider_removal_blockers(
        self,
        reference: ManagedLlmProviderRef,
    ) -> tuple[str, ...]:
        provider_id = managed_llm_provider_instance_id(reference)
        settings = self.load_snapshot().settings
        _require_exact_managed_provider(settings, provider_id, reference)
        return tuple(
            field_name
            for field_name in (
                "default_fq_model_key",
                "turn_completion_guard_fq_model_key",
                "thread_title_fq_model_key",
            )
            if _selection_references_provider(getattr(settings, field_name), provider_id)
        )

    def remove_managed_provider(
        self,
        reference: ManagedLlmProviderRef,
    ) -> LLMSettingsSnapshot:
        provider_id = managed_llm_provider_instance_id(reference)

        def transform(current: LLMSettings) -> LLMSettings:
            _require_exact_managed_provider(current, provider_id, reference)
            blockers = tuple(
                field_name
                for field_name in (
                    "default_fq_model_key",
                    "turn_completion_guard_fq_model_key",
                    "thread_title_fq_model_key",
                )
                if _selection_references_provider(getattr(current, field_name), provider_id)
            )
            if blockers:
                raise ValidationError(
                    "Managed LLM provider is still selected by LLM-owned settings.",
                    error_code="llm_provider_removal_blocked",
                    error_details={"blockers": list(blockers)},
                )
            return current.model_copy(
                update={
                    "providers": [
                        provider for provider in current.providers if provider.provider_id != provider_id
                    ]
                },
                deep=True,
            )

        return self._mutate_managed(transform)

    remove_managed_projection = remove_managed_provider

    def projection_status(
        self,
        reference: ManagedLlmProviderRef,
    ) -> ManagedLlmProviderProjectionStatus:
        provider_id = managed_llm_provider_instance_id(reference)
        settings = self.load_snapshot().settings
        provider = settings.provider_for_id(provider_id)
        if provider is None or provider.managed_reference != reference:
            return ManagedLlmProviderProjectionStatus(
                exists=False,
                retiring=False,
                default_selected=False,
                turn_completion_guard_selected=False,
                thread_title_selected=False,
            )
        return ManagedLlmProviderProjectionStatus(
            exists=True,
            retiring=provider.retiring,
            default_selected=_selection_references_provider(settings.default_fq_model_key, provider_id),
            turn_completion_guard_selected=_selection_references_provider(
                settings.turn_completion_guard_fq_model_key,
                provider_id,
            ),
            thread_title_selected=_selection_references_provider(
                settings.thread_title_fq_model_key,
                provider_id,
            ),
        )

    def _set_selection(
        self,
        field_name: str,
        fq_key: str,
        *,
        expected_revision: int,
    ) -> LLMSettingsSnapshot:
        normalized = fq_key.strip()

        def transform(current: LLMSettings) -> LLMSettings:
            if normalized:
                _validate_selectable_model(current, normalized)
            return current.model_copy(update={field_name: normalized}, deep=True)

        return self._compare_and_swap_user(expected_revision, transform)

    def _compare_and_swap_user(
        self,
        expected_revision: int,
        transform: Any,
    ) -> LLMSettingsSnapshot:
        if not isinstance(expected_revision, int) or isinstance(expected_revision, bool) or expected_revision < 0:
            raise ValueError("Expected LLM settings revision must be a non-negative integer.")
        if self._settings_store is None:
            with self._legacy_lock:
                current = self.load_snapshot()
                if expected_revision != current.revision:
                    raise SettingsConflictError(self._document_id, expected_revision, current.revision)
                next_settings = transform(current.settings)
                self._write_legacy_settings(next_settings)
                return LLMSettingsSnapshot(settings=next_settings.model_copy(deep=True), revision=0)

        result_settings: LLMSettings | None = None

        def store_transform(payload: Any) -> Any:
            nonlocal result_settings
            current = _settings_from_payload(payload)
            result_settings = transform(current)
            return sanitize_settings_for_save(result_settings).model_dump(mode="json")

        result = self._settings_store.compare_and_swap(
            self._document_id,
            expected_revision,
            store_transform,
        )
        settings = _settings_from_payload(result.snapshot.payload)
        return LLMSettingsSnapshot(settings=settings, revision=result.snapshot.revision)

    def _mutate_managed(self, transform: Any) -> LLMSettingsSnapshot:
        """Apply a manager command to the latest document without stale UI state."""

        if self._settings_store is None:
            with self._legacy_lock:
                current = self.load_snapshot()
                next_settings = transform(current.settings)
                self._write_legacy_settings(next_settings)
                return LLMSettingsSnapshot(settings=next_settings.model_copy(deep=True), revision=0)

        # A manager command derives from current authority, so it may retry only
        # a physical CAS race; unlike a UI command it never replays stale fields.
        for _ in range(8):
            current = self.load_snapshot()
            try:
                return self._compare_and_swap_user(current.revision, transform)
            except SettingsConflictError:
                continue
        raise ValidationError(
            "LLM managed provider command conflicted repeatedly; retry from current settings.",
            error_code="llm_settings_conflict",
        )

    def _write_legacy_settings(self, settings: LLMSettings) -> None:
        self._settings_path.parent.mkdir(parents=True, exist_ok=True)
        sanitized = sanitize_settings_for_save(settings)
        self._settings_path.write_text(sanitized.model_dump_json(indent=2), encoding="utf-8")


def default_llm_settings() -> LLMSettings:
    trial_config = load_packaged_trial_llm_config()
    if trial_config.enabled:
        return LLMSettings(
            providers=[
                LLMProviderConfig(
                    key=TRIAL_PROVIDER_KEY,
                    display_name=TRIAL_PROVIDER_DISPLAY_NAME,
                    dialect=LLMDialect.OPENAI_COMPATIBLE,
                    base_url=trial_config.base_url,
                    api_key="",
                    models=[trial_config.model],
                    dialect_config={"secret_source": PACKAGED_TRIAL_SECRET_SOURCE},
                )
            ],
            default_fq_model_key=fq_model_key(TRIAL_PROVIDER_KEY, trial_config.model),
        )
    return LLMSettings(
        providers=[LLMProviderConfig()],
        default_fq_model_key=DEFAULT_FQ_MODEL_KEY,
    )


def load_packaged_trial_llm_config() -> PackagedTrialLLMConfig:
    release_config = load_release_config()
    return PackagedTrialLLMConfig(
        base_url=release_config.trial_llm_base_url or TRIAL_LLM_BASE_URL_FALLBACK,
        api_key=release_config.trial_llm_api_key,
        model=release_config.trial_llm_model or TRIAL_LLM_MODEL_FALLBACK,
    )


def sanitize_settings_for_save(settings: LLMSettings) -> LLMSettings:
    providers: list[LLMProviderConfig] = []
    for provider in settings.providers:
        if (
            isinstance(provider.target, StaticLlmTarget)
            and provider.target.dialect_config.get("secret_source") == PACKAGED_TRIAL_SECRET_SOURCE
        ):
            target = provider.target.model_copy(update={"api_key": ""})
            providers.append(provider.model_copy(update={"target": target}, deep=True))
            continue
        providers.append(provider.model_copy(deep=True))
    return settings.model_copy(update={"providers": providers}, deep=True)


def fq_model_key(provider_key: str, model_key: str) -> str:
    provider = provider_key.strip()
    model = model_key.strip()
    if not provider:
        raise ValidationError("Provider key cannot be empty.")
    if not model:
        raise ValidationError("Model key cannot be empty.")
    if "/" in provider:
        raise ValidationError("Provider key cannot contain '/'.")
    if "/" in model:
        raise ValidationError("Model key cannot contain '/'.")
    return f"{provider}/{model}"


def parse_fq_model_key(value: str) -> LLMModelRef:
    normalized = value.strip()
    parts = normalized.split("/")
    if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
        raise ValidationError("Model key must use 'provider/model' format.")
    return LLMModelRef(provider_key=parts[0].strip(), model_key=parts[1].strip())


def model_options_from_settings(settings: LLMSettings) -> list[LLMModelOption]:
    options: list[LLMModelOption] = []
    for provider in settings.providers:
        if provider.retiring:
            continue
        provider_label = provider.display_name or provider.provider_id
        for model_key in provider.models:
            options.append(
                LLMModelOption(
                    fq_model_key=fq_model_key(provider.provider_id, model_key),
                    provider_key=provider.provider_id,
                    model_key=model_key,
                    label=f"{provider_label} / {model_key}",
                )
            )
    return options


def _settings_from_payload(payload: Any) -> LLMSettings:
    if isinstance(payload, Mapping) and not payload:
        return default_llm_settings()
    return LLMSettings.model_validate(_thaw_json_value(payload))


def _legacy_payload_to_settings(payload: Mapping[str, Any]) -> dict[str, Any]:
    model = str(payload.get("model") or DEFAULT_MODEL_KEY).strip() or DEFAULT_MODEL_KEY
    guard_model = str(payload.get("turn_completion_guard_model") or "").strip()
    title_model = str(payload.get("thread_title_model") or "").strip()
    models = _unique_model_keys([model, guard_model, title_model])
    provider = {
        "provider_id": DEFAULT_PROVIDER_KEY,
        "display_name": "OpenAI-compatible",
        "models": models or [DEFAULT_MODEL_KEY],
        "target": {
            "kind": "static",
            "dialect": LLMDialect.OPENAI_COMPATIBLE.value,
            "base_url": str(payload.get("base_url") or "https://api.openai.com").strip(),
            "api_key": str(payload.get("api_key") or ""),
            "timeout_seconds": payload.get("timeout_seconds", 120),
            "streaming_enabled": payload.get("streaming_enabled", True),
        },
    }
    return {
        "schema_version": _SETTINGS_SCHEMA_VERSION,
        "providers": [provider],
        "default_fq_model_key": fq_model_key(DEFAULT_PROVIDER_KEY, model),
        "turn_completion_guard_fq_model_key": (
            fq_model_key(DEFAULT_PROVIDER_KEY, guard_model) if guard_model else ""
        ),
        "thread_title_fq_model_key": (
            fq_model_key(DEFAULT_PROVIDER_KEY, title_model) if title_model else ""
        ),
        "retry_attempts": payload.get("retry_attempts", 5),
    }


def _merge_user_settings(
    current: LLMSettings,
    requested: LLMSettings,
    *,
    allow_selection_changes: bool,
) -> LLMSettings:
    user_providers = [provider for provider in requested.providers if not provider.is_managed]
    managed_providers = [provider.model_copy(deep=True) for provider in current.providers if provider.is_managed]
    merged = current.model_copy(
        update={
            "providers": [*user_providers, *managed_providers],
            "default_fq_model_key": (
                requested.default_fq_model_key if allow_selection_changes else current.default_fq_model_key
            ),
            "turn_completion_guard_fq_model_key": (
                requested.turn_completion_guard_fq_model_key
                if allow_selection_changes
                else current.turn_completion_guard_fq_model_key
            ),
            "thread_title_fq_model_key": (
                requested.thread_title_fq_model_key
                if allow_selection_changes
                else current.thread_title_fq_model_key
            ),
            "retry_attempts": requested.retry_attempts,
        },
        deep=True,
    )
    for field_name in (
        "default_fq_model_key",
        "turn_completion_guard_fq_model_key",
        "thread_title_fq_model_key",
    ):
        selected = getattr(merged, field_name).strip()
        if selected:
            _validate_selectable_model(merged, selected)
    return merged


def _validate_selectable_model(settings: LLMSettings, selected: str) -> None:
    reference = parse_fq_model_key(selected)
    provider = settings.provider_for_id(reference.provider_key)
    if provider is None or reference.model_key not in provider.models:
        raise NotFoundError(f"LLM model '{selected}' was not found.")
    if provider.retiring:
        raise ValidationError(
            "The selected LLM provider is retiring and cannot accept a new selection.",
            error_code="llm_provider_retiring",
        )


def _require_exact_managed_provider(
    settings: LLMSettings,
    provider_id: str,
    reference: ManagedLlmProviderRef,
) -> LLMProviderConfig:
    provider = settings.provider_for_id(provider_id)
    if provider is None:
        raise NotFoundError("Managed LLM provider was not found.")
    if provider.managed_reference != reference:
        raise ValidationError(
            "Managed LLM provider ID is owned by a different exact reference.",
            error_code="llm_provider_owner_conflict",
        )
    return provider


def _managed_provider_projection_tuple(provider: LLMProviderConfig) -> tuple[Any, ...]:
    return (
        provider.provider_id,
        provider.display_name,
        tuple(provider.models),
        provider.managed_reference,
        provider.manifest_digest,
        _canonical_json(provider.model_compatibility),
    )


def _selection_references_provider(fq_key: str, provider_id: str) -> bool:
    try:
        return parse_fq_model_key(fq_key).provider_key == provider_id
    except ValidationError:
        return False


def _is_managed_fq_model_key(fq_key: str) -> bool:
    try:
        return is_managed_llm_provider_instance_id(parse_fq_model_key(fq_key).provider_key)
    except ValidationError:
        return False


def _unique_model_keys(values: list[str]) -> list[str]:
    models: list[str] = []
    seen: set[str] = set()
    for raw_model in values:
        model_key = str(raw_model).strip()
        if not model_key:
            continue
        if "/" in model_key:
            raise ValueError("Model key cannot contain '/'.")
        if model_key not in seen:
            models.append(model_key)
            seen.add(model_key)
    if not models:
        raise ValueError("Provider must define at least one model.")
    return models


_FORBIDDEN_MANAGED_METADATA_KEYS = frozenset(
    {
        "api_key",
        "authorization",
        "base_url",
        "bearer_token",
        "endpoint",
        "health",
        "incarnation",
        "password",
        "placement",
        "port",
        "runtime_incarnation",
        "secret",
        "token",
        "url",
    }
)


def _validated_projection_metadata(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("Managed LLM compatibility metadata must be an object.")
    normalized = _canonical_json(value)
    _reject_forbidden_metadata_keys(normalized)
    return normalized


def _reject_forbidden_metadata_keys(value: Any) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = str(key).strip().lower().replace("-", "_")
            segments = {segment for segment in normalized.split("_") if segment}
            if (
                normalized in _FORBIDDEN_MANAGED_METADATA_KEYS
                or bool(segments & _FORBIDDEN_MANAGED_METADATA_KEYS)
                or normalized.endswith("url")
            ):
                raise ValueError("Managed LLM projection cannot include dynamic binding data.")
            _reject_forbidden_metadata_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            _reject_forbidden_metadata_keys(nested)
    elif isinstance(value, str) and "://" in value:
        raise ValueError("Managed LLM projection cannot include a dynamic endpoint URL.")


def _canonical_json(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False))
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ValueError("Managed LLM compatibility metadata must be finite JSON.") from exc


def _thaw_json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw_json_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json_value(item) for item in value]
    if isinstance(value, list):
        return [_thaw_json_value(item) for item in value]
    return value


__all__ = [
    "DEFAULT_FQ_MODEL_KEY",
    "DEFAULT_MODEL_KEY",
    "DEFAULT_PROVIDER_KEY",
    "FrozenLLMSettingsSource",
    "LLMDialect",
    "LLMModelOption",
    "LLMModelRef",
    "LLMProviderConfig",
    "LLMSettings",
    "LLMSettingsReadView",
    "LLMSettingsService",
    "LLMSettingsSnapshot",
    "LLMSettingsSource",
    "LLMSettingsUserCommands",
    "LlmProviderTarget",
    "ManagedLlmProviderCommands",
    "ManagedLlmProviderProjection",
    "ManagedLlmProviderProjectionStatus",
    "ManagedLlmProviderRef",
    "PACKAGED_TRIAL_SECRET_SOURCE",
    "PackagedTrialLLMConfig",
    "SETTINGS_FILE_NAME",
    "StaticLlmTarget",
    "TRIAL_PROVIDER_DISPLAY_NAME",
    "TRIAL_PROVIDER_KEY",
    "TRIAL_LLM_BASE_URL_FALLBACK",
    "TRIAL_LLM_MODEL_FALLBACK",
    "default_llm_settings",
    "fq_model_key",
    "is_managed_llm_provider_instance_id",
    "load_packaged_trial_llm_config",
    "managed_llm_provider_id",
    "managed_llm_provider_instance_id",
    "model_options_from_settings",
    "parse_fq_model_key",
    "sanitize_settings_for_save",
]
