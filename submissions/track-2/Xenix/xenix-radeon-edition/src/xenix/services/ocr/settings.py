"""Capability-owned OCR provider catalog and parent-side attempt factory."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal, Protocol

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError as PydanticValidationError,
    field_validator,
    model_validator,
)

from ...config import AppPaths
from ...exceptions import ValidationError
from ..settings_store import SettingsConflictError, SettingsSnapshot, SettingsStore, SettingsStoreError
from .composition import LocalPaddleOcrAttemptFactory
from .contracts import OcrAttempt, OcrAttemptFactory, OcrFailure

OCR_SETTINGS_DOCUMENT_ID = "ocr_settings.json"
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$")


class LocalPaddleTarget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["local_paddle"] = "local_paddle"


class ManagedOcrProviderRef(BaseModel):
    """Owner-neutral exact managed reference; it deliberately contains no AMD type."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["managed"] = "managed"
    manager_id: str
    installation_id: str
    component_generation_id: str

    @field_validator("manager_id", "installation_id", "component_generation_id")
    @classmethod
    def _validate_identifier(cls, value: str) -> str:
        if not _IDENTIFIER.fullmatch(value):
            raise ValueError("Managed OCR reference identifier is invalid.")
        return value


OcrProviderTarget = Annotated[
    LocalPaddleTarget | ManagedOcrProviderRef,
    Field(discriminator="kind"),
]


class OcrProviderProjection(BaseModel):
    """One immutable selected-provider candidate, owned by the OCR settings domain."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    display_name: str
    model: str
    descriptor_fingerprint: str
    target: OcrProviderTarget
    read_only: bool = False
    retiring: bool = False

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value: str) -> str:
        if not _IDENTIFIER.fullmatch(value):
            raise ValueError("OCR provider ID is invalid.")
        return value

    @field_validator("display_name", "model", "descriptor_fingerprint")
    @classmethod
    def _validate_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or len(normalized) > 240:
            raise ValueError("OCR provider projection is invalid.")
        return normalized

    @model_validator(mode="after")
    def _managed_is_read_only(self) -> OcrProviderProjection:
        if isinstance(self.target, ManagedOcrProviderRef):
            if not self.read_only:
                raise ValueError("Managed OCR provider projections are read-only.")
            return self
        if self.read_only or self.retiring:
            raise ValueError("Local OCR providers cannot be manager-owned or retiring.")
        return self

    @property
    def is_managed(self) -> bool:
        return isinstance(self.target, ManagedOcrProviderRef)


def managed_ocr_provider_id(reference: ManagedOcrProviderRef) -> str:
    """Return the immutable generation-specific OCR provider identity."""

    canonical = json.dumps(
        {
            "owner": "ocr",
            "manager_id": reference.manager_id,
            "installation_id": reference.installation_id,
            "component_generation_id": reference.component_generation_id,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "ocr-managed-" + hashlib.sha256(canonical).hexdigest()[:40]


def _default_provider() -> OcrProviderProjection:
    return OcrProviderProjection(
        id="local-paddle",
        display_name="Local Paddle OCR",
        model="paddle-general-ocr",
        descriptor_fingerprint="local-paddle-v1",
        target=LocalPaddleTarget(),
    )


class OcrSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    active_provider_id: str = "local-paddle"
    providers: tuple[OcrProviderProjection, ...] = Field(default_factory=lambda: (_default_provider(),))

    @field_validator("active_provider_id")
    @classmethod
    def _validate_active_provider_id(cls, value: str) -> str:
        if not _IDENTIFIER.fullmatch(value):
            raise ValueError("Active OCR provider ID is invalid.")
        return value

    @model_validator(mode="after")
    def _validate_unique_provider_ids(self) -> OcrSettings:
        provider_ids = [provider.id for provider in self.providers]
        if not provider_ids or len(provider_ids) != len(set(provider_ids)):
            raise ValueError("OCR provider IDs must be unique and non-empty.")
        # Deliberately allow an active ID absent from the catalog.  A removal or
        # absent optional manager becomes a typed unavailable/stale projection;
        # it must never silently select another provider.
        return self

    def provider(self, provider_id: str) -> OcrProviderProjection | None:
        return next((provider for provider in self.providers if provider.id == provider_id), None)


@dataclass(frozen=True, slots=True)
class OcrSettingsView:
    settings: OcrSettings
    revision: int


@dataclass(frozen=True, slots=True)
class ManagedOcrProviderProjectionStatus:
    """Redacted OCR-domain status for one exact managed projection."""

    exists: bool
    retiring: bool
    active: bool


class OcrSettingsError(ValidationError):
    """Bounded OCR settings-domain error."""


class OcrSettingsReadView(Protocol):
    def load(self) -> OcrSettings: ...

    def load_view(self) -> OcrSettingsView: ...


class OcrSettingsUserCommands(Protocol):
    def replace_user_settings(
        self,
        settings: OcrSettings,
        *,
        expected_revision: int,
    ) -> OcrSettingsView: ...

    def set_active_provider(
        self,
        provider_id: str,
        *,
        expected_revision: int,
    ) -> OcrSettingsView: ...


class ManagedOcrProviderCommands(Protocol):
    def ensure_managed_provider(
        self,
        projection: OcrProviderProjection,
    ) -> OcrSettingsView: ...

    def mark_managed_provider_retiring(
        self,
        reference: ManagedOcrProviderRef,
    ) -> OcrSettingsView: ...

    def remove_managed_provider(
        self,
        reference: ManagedOcrProviderRef,
    ) -> OcrSettingsView: ...

    def projection_status(
        self,
        reference: ManagedOcrProviderRef,
    ) -> ManagedOcrProviderProjectionStatus: ...


class OcrSettingsService:
    """OCR catalog authority over one revisioned JSON document."""

    def __init__(self, paths: AppPaths | None = None, *, store: SettingsStore | None = None) -> None:
        if paths is None and store is None:
            raise TypeError("OCR settings require AppPaths or the app settings writer.")
        self._owns_store = store is None
        self._store = store or SettingsStore(paths.config)

    @property
    def settings_path(self) -> Path:
        return self._store.root / OCR_SETTINGS_DOCUMENT_ID

    def close(self) -> None:
        if self._owns_store:
            self._store.close()

    def load_view(self) -> OcrSettingsView:
        try:
            snapshot = self._store.load(OCR_SETTINGS_DOCUMENT_ID)
            return _view_from_snapshot(snapshot)
        except (SettingsStoreError, PydanticValidationError) as exc:
            raise OcrSettingsError("OCR settings could not be loaded.", error_code="ocr_settings_invalid") from exc

    def load(self) -> OcrSettings:
        return self.load_view().settings

    def save(self, settings: OcrSettings, *, expected_revision: int | None = None) -> OcrSettingsView:
        view = self.load_view()
        revision = view.revision if expected_revision is None else expected_revision
        incoming = OcrSettings.model_validate(settings)
        return self.replace_user_settings(incoming, expected_revision=revision)

    def replace_user_settings(
        self,
        settings: OcrSettings,
        *,
        expected_revision: int,
    ) -> OcrSettingsView:
        incoming = OcrSettings.model_validate(settings)
        return self._cas(
            expected_revision,
            lambda payload: _merge_user_settings(_settings_from_payload(payload), incoming).model_dump(mode="json"),
        )

    apply_user_settings = replace_user_settings

    def ensure_managed_projection(
        self,
        projection: OcrProviderProjection,
        *,
        expected_revision: int,
    ) -> OcrSettingsView:
        """Legacy revision-bound spelling retained for existing callers.

        New manager composition calls :meth:`ensure_managed_provider`, whose
        idempotent command owns its own retry over concurrent UI changes.
        """

        self._validate_managed_projection(projection)
        return self._cas(
            expected_revision,
            lambda payload: self._ensure_projection(_settings_from_payload(payload), projection).model_dump(
                mode="json"
            ),
        )

    def ensure_managed_provider(self, projection: OcrProviderProjection) -> OcrSettingsView:
        self._validate_managed_projection(projection)
        return self._manager_cas(lambda current: self._ensure_projection(current, projection))

    ensure_managed_projection_idempotent = ensure_managed_provider

    def mark_managed_provider_retiring(
        self,
        reference: ManagedOcrProviderRef,
    ) -> OcrSettingsView:
        provider_id = managed_ocr_provider_id(reference)

        def transform(current: OcrSettings) -> OcrSettings:
            existing = current.provider(provider_id)
            if existing is None:
                return current
            if existing.target != reference:
                raise OcrSettingsError(
                    "OCR provider ID belongs to a different projection.",
                    error_code="ocr_provider_owner_conflict",
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

        return self._manager_cas(transform)

    retire_managed_provider = mark_managed_provider_retiring

    def managed_provider_removal_blockers(
        self,
        reference: ManagedOcrProviderRef,
    ) -> tuple[str, ...]:
        provider_id = managed_ocr_provider_id(reference)
        current = self.load()
        projection = current.provider(provider_id)
        if projection is None or projection.target != reference:
            return ()
        return ("active_provider_id",) if current.active_provider_id == provider_id else ()

    def remove_managed_provider(
        self,
        reference: ManagedOcrProviderRef,
    ) -> OcrSettingsView:
        provider_id = managed_ocr_provider_id(reference)

        def transform(current: OcrSettings) -> OcrSettings:
            existing = current.provider(provider_id)
            if existing is None:
                return current
            if existing.target != reference:
                raise OcrSettingsError(
                    "OCR provider ID belongs to a different projection.",
                    error_code="ocr_provider_owner_conflict",
                )
            if current.active_provider_id == provider_id:
                raise OcrSettingsError(
                    "The active OCR provider cannot be removed.",
                    error_code="ocr_provider_removal_blocked",
                )
            return current.model_copy(
                update={"providers": tuple(provider for provider in current.providers if provider.id != provider_id)}
            )

        return self._manager_cas(transform)

    remove_managed_projection = remove_managed_provider

    def projection_status(
        self,
        reference: ManagedOcrProviderRef,
    ) -> ManagedOcrProviderProjectionStatus:
        current = self.load()
        projection = current.provider(managed_ocr_provider_id(reference))
        if projection is None or projection.target != reference:
            return ManagedOcrProviderProjectionStatus(False, False, False)
        return ManagedOcrProviderProjectionStatus(
            exists=True,
            retiring=projection.retiring,
            active=current.active_provider_id == projection.id,
        )

    def remove_provider(self, provider_id: str, *, expected_revision: int) -> OcrSettingsView:
        def transform(payload: object) -> object:
            current = _settings_from_payload(payload)
            if current.active_provider_id == provider_id:
                raise OcrSettingsError("The active OCR provider cannot be removed.")
            providers = tuple(provider for provider in current.providers if provider.id != provider_id)
            if len(providers) == len(current.providers):
                return current.model_dump(mode="json")
            return current.model_copy(update={"providers": providers}).model_dump(mode="json")

        return self._cas(expected_revision, transform)

    def set_active_provider(self, provider_id: str, *, expected_revision: int) -> OcrSettingsView:
        def transform(payload: object) -> object:
            current = _settings_from_payload(payload)
            projection = current.provider(provider_id)
            if projection is None:
                raise OcrSettingsError("OCR provider is unavailable.", error_code="ocr_provider_unavailable")
            if projection.retiring:
                raise OcrSettingsError("OCR provider is retiring.", error_code="ocr_provider_retiring")
            return current.model_copy(update={"active_provider_id": provider_id}).model_dump(mode="json")

        return self._cas(expected_revision, transform)

    @staticmethod
    def _validate_managed_projection(projection: OcrProviderProjection) -> None:
        target = projection.target
        if not isinstance(target, ManagedOcrProviderRef):
            raise OcrSettingsError("Only managed OCR projections can be registered this way.")
        if projection.id != managed_ocr_provider_id(target):
            raise OcrSettingsError("Managed OCR provider ID is not generation-specific.")
        if projection.retiring:
            raise OcrSettingsError("A newly ensured OCR provider cannot be retiring.")

    @staticmethod
    def _ensure_projection(
        current: OcrSettings,
        projection: OcrProviderProjection,
    ) -> OcrSettings:
        existing = current.provider(projection.id)
        if existing is None:
            return current.model_copy(update={"providers": (*current.providers, projection)})
        if existing != projection:
            raise OcrSettingsError(
                "OCR provider ID already belongs to a different projection.",
                error_code="ocr_provider_projection_conflict",
            )
        return current

    def _cas(self, expected_revision: int, transform: Callable[[object], object]) -> OcrSettingsView:
        try:
            result = self._store.compare_and_swap(OCR_SETTINGS_DOCUMENT_ID, expected_revision, transform)
            return _view_from_snapshot(result.snapshot)
        except SettingsConflictError:
            raise
        except OcrSettingsError:
            raise
        except (SettingsStoreError, PydanticValidationError) as exc:
            raise OcrSettingsError("OCR settings could not be saved.", error_code="ocr_settings_save_failed") from exc

    def _manager_cas(
        self,
        transform: Callable[[OcrSettings], OcrSettings],
    ) -> OcrSettingsView:
        """Apply an idempotent manager projection without owning UI revisions."""

        for _attempt in range(8):
            current = self.load_view()
            try:
                return self._cas(
                    current.revision,
                    lambda payload: transform(_settings_from_payload(payload)).model_dump(mode="json"),
                )
            except SettingsConflictError:
                continue
        raise OcrSettingsError(
            "OCR settings changed repeatedly; retry the manager command.",
            error_code="ocr_settings_conflict",
        )


class OcrProviderFactory(Protocol):
    def prepare(self, projection: OcrProviderProjection) -> OcrAttempt: ...


ManagedOcrFactory = Callable[[ManagedOcrProviderRef, OcrProviderProjection], OcrAttempt]


class OcrProviderFactoryRegistry:
    """App-scoped construction registry; it owns no settings or selection state."""

    def __init__(self) -> None:
        self._managed: dict[str, ManagedOcrFactory] = {}
        self._local_paddle = LocalPaddleOcrAttemptFactory()

    def register_managed(self, manager_id: str, factory: ManagedOcrFactory) -> None:
        if not _IDENTIFIER.fullmatch(manager_id) or not callable(factory):
            raise ValueError("OCR managed factory registration is invalid.")
        if manager_id in self._managed:
            raise ValueError("OCR managed factory is already registered.")
        self._managed[manager_id] = factory

    @property
    def registered_manager_ids(self) -> tuple[str, ...]:
        """Expose composition occupancy without exposing factory implementations."""

        return tuple(self._managed)

    def prepare(self, projection: OcrProviderProjection) -> OcrAttempt:
        if projection.retiring:
            raise OcrFailure(
                "OCR provider is retiring.",
                error_code="ocr_provider_retiring",
            )
        target = projection.target
        if isinstance(target, LocalPaddleTarget):
            return self._local_paddle.prepare()
        factory = self._managed.get(target.manager_id)
        if factory is None:
            raise OcrFailure(
                "OCR provider implementation is unavailable.",
                error_code="provider_implementation_unavailable",
            )
        return factory(target, projection)


class ConfiguredOcrAttemptFactory(OcrAttemptFactory):
    """Resolve the selected OCR provider in the parent before a child is spawned."""

    def __init__(self, settings: OcrSettingsService, registry: OcrProviderFactoryRegistry) -> None:
        self._settings = settings
        self._registry = registry

    def prepare(self) -> OcrAttempt:
        view = self._settings.load_view()
        projection = view.settings.provider(view.settings.active_provider_id)
        if projection is None:
            raise OcrFailure("OCR provider reference is stale.", error_code="ocr_provider_reference_stale")
        return self._registry.prepare(projection)


def _view_from_snapshot(snapshot: SettingsSnapshot) -> OcrSettingsView:
    return OcrSettingsView(settings=_settings_from_payload(snapshot.payload), revision=snapshot.revision)


def _settings_from_payload(payload: object) -> OcrSettings:
    if payload == {}:
        return OcrSettings()
    return OcrSettings.model_validate(payload)


def _merge_user_settings(current: OcrSettings, incoming: OcrSettings) -> OcrSettings:
    """Preserve manager-owned projections across a revisioned user command."""

    user_providers = tuple(provider for provider in incoming.providers if not provider.is_managed)
    managed_providers = tuple(provider for provider in current.providers if provider.is_managed)
    if not user_providers:
        raise OcrSettingsError("At least one user-owned OCR provider is required.")
    user_ids = {provider.id for provider in user_providers}
    managed_ids = {provider.id for provider in managed_providers}
    if user_ids & managed_ids:
        raise OcrSettingsError("A user-owned OCR provider conflicts with a managed provider.")
    providers = (*user_providers, *managed_providers)
    active = incoming.active_provider_id
    selected = next((provider for provider in providers if provider.id == active), None)
    if selected is None:
        raise OcrSettingsError("OCR provider is unavailable.", error_code="ocr_provider_unavailable")
    if selected.retiring:
        raise OcrSettingsError("OCR provider is retiring.", error_code="ocr_provider_retiring")
    return OcrSettings(providers=providers, active_provider_id=active)


__all__ = [
    "ConfiguredOcrAttemptFactory",
    "LocalPaddleTarget",
    "ManagedOcrProviderRef",
    "ManagedOcrProviderCommands",
    "ManagedOcrProviderProjectionStatus",
    "OcrProviderFactoryRegistry",
    "OcrProviderProjection",
    "OcrSettings",
    "OcrSettingsError",
    "OcrSettingsReadView",
    "OcrSettingsService",
    "OcrSettingsUserCommands",
    "OcrSettingsView",
    "OCR_SETTINGS_DOCUMENT_ID",
    "managed_ocr_provider_id",
]
