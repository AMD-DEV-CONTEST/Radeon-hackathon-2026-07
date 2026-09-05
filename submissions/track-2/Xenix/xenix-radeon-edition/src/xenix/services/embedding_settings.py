"""Capability-owned Embedding provider catalog and settings commands.

The module deliberately knows provider identity and user-editable configuration,
but not a concrete execution manager.  A managed reference is therefore a
small, owner-neutral value that stays readable after an optional manager has
been removed from the application composition.
"""

from __future__ import annotations

import json
import re
import threading
import unicodedata
import urllib.parse
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from typing import Annotated, Any, Literal, Protocol

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError as PydanticValidationError,
    field_validator,
    model_validator,
)

from ..config import AppPaths
from ..exceptions import ValidationError
from .settings_store import (
    SettingsConflictError,
    SettingsSnapshot,
    SettingsStore,
    SettingsStoreError,
)

SETTINGS_FILE_NAME = "embedding_settings.json"
EMBEDDING_SETTINGS_FILE_NAME = SETTINGS_FILE_NAME
EMBEDDING_SETTINGS_SCHEMA_VERSION = 2
DEFAULT_EMBEDDING_BATCH_SIZE = 20
MAX_EMBEDDING_DIMENSIONS = 65_536
_STATIC_DEFAULT_PROVIDER_ID = "static-openai"
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$")


class EmbeddingDialect(StrEnum):
    OPENAI_COMPATIBLE = "openai_compatible"


class StaticEmbeddingTarget(BaseModel):
    """A user-owned static OpenAI-compatible endpoint configuration."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
    )

    kind: Literal["static"] = "static"
    enabled: bool = False
    provider_key: str = "openai"
    dialect: EmbeddingDialect = EmbeddingDialect.OPENAI_COMPATIBLE
    base_url: str = "https://api.openai.com"
    api_key: str = Field(default="", repr=False)
    model: str = "text-embedding-3-small"
    dimensions: int | None = Field(default=None, ge=1, le=MAX_EMBEDDING_DIMENSIONS)
    batch_size: int = Field(default=DEFAULT_EMBEDDING_BATCH_SIZE, ge=1, le=2_048)
    timeout_seconds: int = Field(default=120, ge=1, le=3_600)

    @field_validator("provider_key", "model")
    @classmethod
    def _normalize_identifier(cls, value: str) -> str:
        return _normalize_required_text(value, "Embedding provider and model identifiers cannot be empty.")

    @field_validator("base_url")
    @classmethod
    def _validate_base_url(cls, value: str) -> str:
        return normalize_embedding_base_url(value)


class ManagedEmbeddingProviderRef(BaseModel):
    """Exact manager-owned reference with no placement or live endpoint facts."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["managed"] = "managed"
    manager_id: str
    installation_id: str
    component_generation_id: str

    @field_validator("manager_id", "installation_id", "component_generation_id")
    @classmethod
    def _validate_identifier(cls, value: str) -> str:
        if not _IDENTIFIER.fullmatch(value):
            raise ValueError("Managed Embedding reference identifier is invalid.")
        return value


EmbeddingProviderTarget = Annotated[
    StaticEmbeddingTarget | ManagedEmbeddingProviderRef,
    Field(discriminator="kind"),
]


class EmbeddingProviderProjection(BaseModel):
    """One immutable catalog entry owned by the Embedding settings domain."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
    )

    id: str
    display_name: str
    model: str
    dimensions: int | None = Field(default=None, ge=1, le=MAX_EMBEDDING_DIMENSIONS)
    batch_size: int = Field(default=DEFAULT_EMBEDDING_BATCH_SIZE, ge=1, le=2_048)
    timeout_seconds: int = Field(default=120, ge=1, le=3_600)
    tokenizer_identity: str | None = None
    manifest_digest: str | None = None
    target: EmbeddingProviderTarget
    read_only: bool = False
    retiring: bool = False

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value: str) -> str:
        if not _IDENTIFIER.fullmatch(value):
            raise ValueError("Embedding provider ID is invalid.")
        return value

    @field_validator("display_name", "model")
    @classmethod
    def _validate_display_text(cls, value: str) -> str:
        normalized = _normalize_required_text(value, "Embedding provider projection is invalid.")
        if len(normalized) > 240:
            raise ValueError("Embedding provider projection is invalid.")
        return normalized

    @field_validator("tokenizer_identity", "manifest_digest")
    @classmethod
    def _validate_optional_metadata(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = _normalize_required_text(value, "Embedding provider metadata is invalid.")
        if len(normalized) > 512:
            raise ValueError("Embedding provider metadata is invalid.")
        return normalized

    @model_validator(mode="after")
    def _validate_target_projection(self) -> EmbeddingProviderProjection:
        target = self.target
        if isinstance(target, StaticEmbeddingTarget):
            if self.read_only or self.retiring:
                raise ValueError("Static Embedding providers cannot be manager-retired.")
            if self.model != target.model:
                raise ValueError("Static Embedding provider model metadata is inconsistent.")
            if self.dimensions != target.dimensions:
                raise ValueError("Static Embedding provider dimensions are inconsistent.")
            if self.batch_size != target.batch_size or self.timeout_seconds != target.timeout_seconds:
                raise ValueError("Static Embedding provider execution settings are inconsistent.")
            if self.tokenizer_identity is not None or self.manifest_digest is not None:
                raise ValueError("Static Embedding providers cannot carry manager metadata.")
            return self

        if not self.read_only:
            raise ValueError("Managed Embedding provider projections are read-only.")
        if self.tokenizer_identity is None or self.manifest_digest is None:
            raise ValueError("Managed Embedding provider metadata is incomplete.")
        return self

    @property
    def is_managed(self) -> bool:
        return isinstance(self.target, ManagedEmbeddingProviderRef)


def managed_embedding_provider_id(reference: ManagedEmbeddingProviderRef) -> str:
    """Return the generation-specific immutable provider-instance identity."""

    encoded = json.dumps(
        {
            "owner": "embedding",
            "manager_id": reference.manager_id,
            "installation_id": reference.installation_id,
            "component_generation_id": reference.component_generation_id,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "embedding-managed-" + sha256(encoded).hexdigest()[:40]


def _default_static_projection() -> EmbeddingProviderProjection:
    target = StaticEmbeddingTarget()
    return EmbeddingProviderProjection(
        id=_STATIC_DEFAULT_PROVIDER_ID,
        display_name="OpenAI-compatible Embedding",
        model=target.model,
        dimensions=target.dimensions,
        batch_size=target.batch_size,
        timeout_seconds=target.timeout_seconds,
        target=target,
    )


class EmbeddingSettings(BaseModel):
    """Revisioned provider catalog with an explicit active provider instance.

    The legacy v1 shape is accepted at the boundary and deterministically
    projected into the v2 catalog.  This preserves the static vector-space
    fingerprint while letting a subsequent CAS publish the revision envelope.
    """

    model_config = ConfigDict(
        extra="forbid",
        hide_input_in_errors=True,
        revalidate_instances="always",
        validate_assignment=True,
    )

    schema_version: Literal[2] = EMBEDDING_SETTINGS_SCHEMA_VERSION
    providers: tuple[EmbeddingProviderProjection, ...] = Field(default_factory=lambda: (_default_static_projection(),))
    active_provider_id: str = _STATIC_DEFAULT_PROVIDER_ID

    @model_validator(mode="before")
    @classmethod
    def _migrate_legacy_payload(cls, value: Any) -> Any:
        if not isinstance(value, Mapping):
            return value
        payload = dict(value)
        if "providers" in payload:
            payload.setdefault("schema_version", EMBEDDING_SETTINGS_SCHEMA_VERSION)
            return payload
        return _legacy_payload_to_catalog(payload)

    @field_validator("active_provider_id")
    @classmethod
    def _validate_active_provider_id(cls, value: str) -> str:
        if not _IDENTIFIER.fullmatch(value):
            raise ValueError("Active Embedding provider ID is invalid.")
        return value

    @model_validator(mode="after")
    def _validate_catalog(self) -> EmbeddingSettings:
        ids = [provider.id for provider in self.providers]
        if not ids or len(ids) != len(set(ids)):
            raise ValueError("Embedding provider IDs must be unique and non-empty.")
        # An active entry may intentionally be absent after exact managed
        # removal.  It is a typed stale reference, never a signal to select a
        # different provider automatically.
        return self

    def provider(self, provider_id: str) -> EmbeddingProviderProjection | None:
        return next((provider for provider in self.providers if provider.id == provider_id), None)

    def active_provider(self) -> EmbeddingProviderProjection | None:
        return self.provider(self.active_provider_id)

    # These properties keep the static pre-catalog UI shape readable during the
    # staged UI migration.  A managed active provider deliberately exposes no
    # endpoint or credential through this compatibility view.
    @property
    def enabled(self) -> bool:
        active = self.active_provider()
        if active is not None and isinstance(active.target, StaticEmbeddingTarget):
            return active.target.enabled
        return active is not None and not active.retiring

    @property
    def provider_key(self) -> str:
        active = self.active_provider()
        if active is not None and isinstance(active.target, StaticEmbeddingTarget):
            return active.target.provider_key
        return ""

    @property
    def dialect(self) -> EmbeddingDialect:
        active = self.active_provider()
        if active is not None and isinstance(active.target, StaticEmbeddingTarget):
            return active.target.dialect
        return EmbeddingDialect.OPENAI_COMPATIBLE

    @property
    def base_url(self) -> str:
        active = self.active_provider()
        if active is not None and isinstance(active.target, StaticEmbeddingTarget):
            return active.target.base_url
        return ""

    @property
    def api_key(self) -> str:
        active = self.active_provider()
        if active is not None and isinstance(active.target, StaticEmbeddingTarget):
            return active.target.api_key
        return ""

    @property
    def model(self) -> str:
        active = self.active_provider()
        return active.model if active is not None else ""

    @property
    def dimensions(self) -> int | None:
        active = self.active_provider()
        return active.dimensions if active is not None else None

    @property
    def batch_size(self) -> int:
        active = self.active_provider()
        return active.batch_size if active is not None else DEFAULT_EMBEDDING_BATCH_SIZE

    @property
    def timeout_seconds(self) -> int:
        active = self.active_provider()
        return active.timeout_seconds if active is not None else 120


@dataclass(frozen=True, slots=True)
class EmbeddingSettingsSnapshot:
    settings: EmbeddingSettings
    revision: int


@dataclass(frozen=True, slots=True)
class ManagedEmbeddingProjectionStatus:
    """Redacted status for a manager-owned exact projection."""

    exists: bool
    retiring: bool
    active: bool


class EmbeddingSettingsError(ValidationError):
    """Bounded Embedding settings-domain failure."""


class EmbeddingSettingsSource(Protocol):
    def load(self) -> EmbeddingSettings: ...


class EmbeddingSettingsReadView(EmbeddingSettingsSource, Protocol):
    def load_snapshot(self) -> EmbeddingSettingsSnapshot: ...


class EmbeddingSettingsUserCommands(Protocol):
    def replace_user_settings(
        self,
        settings: EmbeddingSettings,
        *,
        expected_revision: int,
    ) -> EmbeddingSettingsSnapshot: ...

    def set_active_provider(
        self,
        provider_id: str,
        *,
        expected_revision: int,
    ) -> EmbeddingSettingsSnapshot: ...


class ManagedEmbeddingProviderCommands(Protocol):
    def ensure_managed_provider(
        self,
        projection: EmbeddingProviderProjection,
    ) -> EmbeddingSettingsSnapshot: ...

    def mark_managed_provider_retiring(
        self,
        reference: ManagedEmbeddingProviderRef,
    ) -> EmbeddingSettingsSnapshot: ...

    def remove_managed_provider(
        self,
        reference: ManagedEmbeddingProviderRef,
    ) -> EmbeddingSettingsSnapshot: ...

    def projection_status(
        self,
        reference: ManagedEmbeddingProviderRef,
    ) -> ManagedEmbeddingProjectionStatus: ...


class EmbeddingSettingsService(
    EmbeddingSettingsReadView,
    EmbeddingSettingsUserCommands,
    ManagedEmbeddingProviderCommands,
):
    """The sole Embedding-domain owner for its provider catalog document.

    A direct-path compatibility mode remains only until composition injects the
    one app-lifetime ``SettingsStore``.  It can read legacy files and save the
    ordinary static configuration, but it cannot coexist with manager-owned
    entries.  The store-backed mode has only revision-bound user commands and
    idempotent manager projection commands.
    """

    def __init__(
        self,
        paths: AppPaths | None = None,
        *,
        settings_store: SettingsStore | None = None,
        document_id: str = SETTINGS_FILE_NAME,
    ) -> None:
        if paths is None and settings_store is None:
            raise TypeError("EmbeddingSettingsService requires AppPaths or SettingsStore.")
        if not document_id.endswith(".json"):
            raise ValueError("Embedding settings document ID must be a .json file name.")
        self._settings_store = settings_store
        self._document_id = document_id
        self._settings_path = paths.config / document_id if paths is not None else settings_store.root / document_id
        self._legacy_lock = threading.RLock()

    @property
    def settings_path(self) -> Path:
        return self._settings_path

    @property
    def document_id(self) -> str:
        return self._document_id

    def load(self) -> EmbeddingSettings:
        return self.load_snapshot().settings.model_copy(deep=True)

    def load_snapshot(self) -> EmbeddingSettingsSnapshot:
        try:
            if self._settings_store is not None:
                stored = self._settings_store.load(self._document_id)
                return _view_from_snapshot(stored)
            with self._legacy_lock:
                if not self._settings_path.exists():
                    return EmbeddingSettingsSnapshot(EmbeddingSettings(), revision=0)
                payload = json.loads(self._settings_path.read_text(encoding="utf-8"))
                return EmbeddingSettingsSnapshot(
                    settings=EmbeddingSettings.model_validate(payload),
                    revision=0,
                )
        except (OSError, UnicodeError, json.JSONDecodeError, PydanticValidationError, SettingsStoreError) as exc:
            raise EmbeddingSettingsError(
                "Embedding settings could not be loaded.",
                error_code="embedding_settings_invalid",
            ) from exc

    def save(self, settings: EmbeddingSettings) -> None:
        """Compatibility bridge for the pre-CAS Settings dialog.

        The store-backed mode rejects broad replacement because it cannot prove
        that a stale dialog did not discard a manager-owned projection.
        """

        if self._settings_store is not None:
            raise EmbeddingSettingsError(
                "Embedding settings require a revisioned user command.",
                error_code="embedding_settings_full_save_unsupported",
            )
        try:
            incoming = EmbeddingSettings.model_validate(settings)
            if any(provider.is_managed for provider in incoming.providers):
                raise EmbeddingSettingsError(
                    "Managed Embedding providers require manager commands.",
                    error_code="embedding_settings_full_save_unsupported",
                )
            with self._legacy_lock:
                self._settings_path.parent.mkdir(parents=True, exist_ok=True)
                self._settings_path.write_text(
                    incoming.model_dump_json(indent=2),
                    encoding="utf-8",
                )
        except EmbeddingSettingsError:
            raise
        except (OSError, UnicodeError, PydanticValidationError) as exc:
            raise EmbeddingSettingsError(
                "Embedding settings could not be saved.",
                error_code="embedding_settings_save_failed",
            ) from exc

    def replace_user_settings(
        self,
        settings: EmbeddingSettings,
        *,
        expected_revision: int,
    ) -> EmbeddingSettingsSnapshot:
        incoming = EmbeddingSettings.model_validate(settings)
        return self._compare_and_swap_user(
            expected_revision,
            lambda current: _merge_user_settings(current, incoming),
        )

    # Explicit aliases let UI composition use the semantic command spelling.
    apply_user_settings = replace_user_settings
    replace_user_provider_settings = replace_user_settings

    def set_active_provider(
        self,
        provider_id: str,
        *,
        expected_revision: int,
    ) -> EmbeddingSettingsSnapshot:
        def transform(current: EmbeddingSettings) -> EmbeddingSettings:
            projection = current.provider(provider_id)
            if projection is None:
                raise EmbeddingSettingsError(
                    "Embedding provider is unavailable.",
                    error_code="embedding_provider_unavailable",
                )
            if projection.retiring:
                raise EmbeddingSettingsError(
                    "Embedding provider is retiring.",
                    error_code="embedding_provider_retiring",
                )
            return current.model_copy(update={"active_provider_id": provider_id})

        return self._compare_and_swap_user(expected_revision, transform)

    def ensure_managed_provider(
        self,
        projection: EmbeddingProviderProjection,
    ) -> EmbeddingSettingsSnapshot:
        target = projection.target
        if not isinstance(target, ManagedEmbeddingProviderRef):
            raise EmbeddingSettingsError("Only managed Embedding projections can be registered this way.")
        if projection.id != managed_embedding_provider_id(target):
            raise EmbeddingSettingsError("Managed Embedding provider ID is not generation-specific.")
        if projection.retiring:
            raise EmbeddingSettingsError("A newly ensured Embedding provider cannot be retiring.")

        def transform(current: EmbeddingSettings) -> EmbeddingSettings:
            existing = current.provider(projection.id)
            if existing is None:
                return current.model_copy(update={"providers": (*current.providers, projection)})
            if existing != projection:
                raise EmbeddingSettingsError(
                    "Embedding provider ID already belongs to a different projection.",
                    error_code="embedding_provider_owner_conflict",
                )
            return current

        return self._manager_compare_and_swap(transform)

    def mark_managed_provider_retiring(
        self,
        reference: ManagedEmbeddingProviderRef,
    ) -> EmbeddingSettingsSnapshot:
        provider_id = managed_embedding_provider_id(reference)

        def transform(current: EmbeddingSettings) -> EmbeddingSettings:
            existing = current.provider(provider_id)
            if existing is None:
                return current
            if existing.target != reference:
                raise EmbeddingSettingsError(
                    "Embedding provider ID belongs to a different projection.",
                    error_code="embedding_provider_owner_conflict",
                )
            if existing.retiring:
                return current
            replacement = existing.model_copy(update={"retiring": True})
            return current.model_copy(
                update={
                    "providers": tuple(
                        replacement if provider.id == provider_id else provider for provider in current.providers
                    )
                }
            )

        return self._manager_compare_and_swap(transform)

    def remove_managed_provider(
        self,
        reference: ManagedEmbeddingProviderRef,
    ) -> EmbeddingSettingsSnapshot:
        provider_id = managed_embedding_provider_id(reference)

        def transform(current: EmbeddingSettings) -> EmbeddingSettings:
            existing = current.provider(provider_id)
            if existing is None:
                return current
            if existing.target != reference:
                raise EmbeddingSettingsError(
                    "Embedding provider ID belongs to a different projection.",
                    error_code="embedding_provider_owner_conflict",
                )
            if current.active_provider_id == provider_id:
                raise EmbeddingSettingsError(
                    "The active Embedding provider cannot be removed.",
                    error_code="embedding_provider_active",
                )
            return current.model_copy(
                update={"providers": tuple(provider for provider in current.providers if provider.id != provider_id)}
            )

        return self._manager_compare_and_swap(transform)

    def projection_status(
        self,
        reference: ManagedEmbeddingProviderRef,
    ) -> ManagedEmbeddingProjectionStatus:
        settings = self.load()
        projection = settings.provider(managed_embedding_provider_id(reference))
        if projection is None or projection.target != reference:
            return ManagedEmbeddingProjectionStatus(exists=False, retiring=False, active=False)
        return ManagedEmbeddingProjectionStatus(
            exists=True,
            retiring=projection.retiring,
            active=settings.active_provider_id == projection.id,
        )

    def _compare_and_swap_user(
        self,
        expected_revision: int,
        transform: Callable[[EmbeddingSettings], EmbeddingSettings],
    ) -> EmbeddingSettingsSnapshot:
        if self._settings_store is None:
            raise EmbeddingSettingsError(
                "Embedding settings require the app settings writer.",
                error_code="embedding_settings_revisioned_commands_unavailable",
            )
        try:
            result = self._settings_store.compare_and_swap(
                self._document_id,
                expected_revision,
                lambda payload: transform(_settings_from_payload(payload)).model_dump(mode="json"),
            )
            return _view_from_snapshot(result.snapshot)
        except SettingsConflictError:
            raise
        except EmbeddingSettingsError:
            raise
        except (SettingsStoreError, PydanticValidationError) as exc:
            raise EmbeddingSettingsError(
                "Embedding settings could not be saved.",
                error_code="embedding_settings_save_failed",
            ) from exc

    def _manager_compare_and_swap(
        self,
        transform: Callable[[EmbeddingSettings], EmbeddingSettings],
    ) -> EmbeddingSettingsSnapshot:
        if self._settings_store is None:
            raise EmbeddingSettingsError(
                "Managed Embedding providers require the app settings writer.",
                error_code="embedding_settings_manager_commands_unavailable",
            )
        # A manager command is an idempotent desired projection.  It always
        # starts from the latest document and only retries its own pure transform
        # when another domain command wins the CAS race.
        for _attempt in range(8):
            current = self.load_snapshot()
            try:
                return self._compare_and_swap_user(current.revision, transform)
            except SettingsConflictError:
                continue
        raise EmbeddingSettingsError(
            "Embedding settings changed repeatedly; retry the manager command.",
            error_code="embedding_settings_conflict",
        )


def _legacy_payload_to_catalog(payload: Mapping[str, Any]) -> dict[str, Any]:
    target = {
        "kind": "static",
        "enabled": payload.get("enabled", False),
        "provider_key": payload.get("provider_key", "openai"),
        "dialect": payload.get("dialect", EmbeddingDialect.OPENAI_COMPATIBLE.value),
        "base_url": payload.get("base_url", "https://api.openai.com"),
        "api_key": payload.get("api_key", ""),
        "model": payload.get("model", "text-embedding-3-small"),
        "dimensions": payload.get("dimensions"),
        "batch_size": payload.get("batch_size", DEFAULT_EMBEDDING_BATCH_SIZE),
        "timeout_seconds": payload.get("timeout_seconds", 120),
    }
    return {
        "schema_version": EMBEDDING_SETTINGS_SCHEMA_VERSION,
        "active_provider_id": _STATIC_DEFAULT_PROVIDER_ID,
        "providers": [
            {
                "id": _STATIC_DEFAULT_PROVIDER_ID,
                "display_name": "OpenAI-compatible Embedding",
                "model": target["model"],
                "dimensions": target["dimensions"],
                "batch_size": target["batch_size"],
                "timeout_seconds": target["timeout_seconds"],
                "target": target,
            }
        ],
    }


def _merge_user_settings(
    current: EmbeddingSettings,
    incoming: EmbeddingSettings,
) -> EmbeddingSettings:
    current_managed = tuple(provider for provider in current.providers if provider.is_managed)
    user_providers = tuple(provider for provider in incoming.providers if not provider.is_managed)
    if not user_providers:
        raise EmbeddingSettingsError("At least one user-owned Embedding provider is required.")
    duplicate_ids = {provider.id for provider in user_providers} & {provider.id for provider in current_managed}
    if duplicate_ids:
        raise EmbeddingSettingsError("A user-owned Embedding provider conflicts with a managed provider.")
    providers = (*user_providers, *current_managed)
    provider_ids = {provider.id for provider in providers}
    active = incoming.active_provider_id
    if active not in provider_ids:
        raise EmbeddingSettingsError(
            "Embedding provider is unavailable.",
            error_code="embedding_provider_unavailable",
        )
    chosen = next(provider for provider in providers if provider.id == active)
    if chosen.retiring:
        raise EmbeddingSettingsError(
            "Embedding provider is retiring.",
            error_code="embedding_provider_retiring",
        )
    return EmbeddingSettings(providers=providers, active_provider_id=active)


def _view_from_snapshot(snapshot: SettingsSnapshot) -> EmbeddingSettingsSnapshot:
    return EmbeddingSettingsSnapshot(
        settings=_settings_from_payload(snapshot.payload),
        revision=snapshot.revision,
    )


def _settings_from_payload(payload: object) -> EmbeddingSettings:
    if payload == {}:
        return EmbeddingSettings()
    return EmbeddingSettings.model_validate(payload)


def _normalize_required_text(value: str, error: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip()
    if not normalized:
        raise ValueError(error)
    return normalized


def normalize_embedding_base_url(base_url: str) -> str:
    """Normalize a credential-free HTTP(S) base URL without changing its API path."""

    normalized_input = unicodedata.normalize("NFKC", base_url).strip()
    if not normalized_input:
        raise ValueError("Embedding base URL cannot be empty.")
    try:
        parts = urllib.parse.urlsplit(normalized_input)
        port = parts.port
    except ValueError:
        raise ValueError("Embedding base URL is invalid.") from None
    scheme = parts.scheme.lower()
    if scheme not in {"http", "https"} or parts.hostname is None:
        raise ValueError("Embedding base URL must use HTTP or HTTPS.")
    if parts.username is not None or parts.password is not None:
        raise ValueError("Embedding base URL cannot contain credentials.")
    if parts.query or parts.fragment:
        raise ValueError("Embedding base URL cannot contain a query or fragment.")
    try:
        hostname = parts.hostname.encode("idna").decode("ascii").lower()
    except UnicodeError:
        raise ValueError("Embedding base URL host is invalid.") from None
    if ":" in hostname:
        hostname = f"[{hostname}]"
    if port is not None and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        hostname = f"{hostname}:{port}"
    return urllib.parse.urlunsplit((scheme, hostname, parts.path.rstrip("/"), "", ""))


__all__ = [
    "DEFAULT_EMBEDDING_BATCH_SIZE",
    "EMBEDDING_SETTINGS_FILE_NAME",
    "EMBEDDING_SETTINGS_SCHEMA_VERSION",
    "EmbeddingDialect",
    "EmbeddingProviderProjection",
    "EmbeddingProviderTarget",
    "EmbeddingSettings",
    "EmbeddingSettingsError",
    "EmbeddingSettingsReadView",
    "EmbeddingSettingsService",
    "EmbeddingSettingsSnapshot",
    "EmbeddingSettingsSource",
    "EmbeddingSettingsUserCommands",
    "MAX_EMBEDDING_DIMENSIONS",
    "ManagedEmbeddingProjectionStatus",
    "ManagedEmbeddingProviderCommands",
    "ManagedEmbeddingProviderRef",
    "SETTINGS_FILE_NAME",
    "StaticEmbeddingTarget",
    "managed_embedding_provider_id",
    "normalize_embedding_base_url",
]
