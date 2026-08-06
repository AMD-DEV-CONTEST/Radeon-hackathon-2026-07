"""AMD-private bridges to capability-owned managed projection commands.

Each capability keeps authority over its provider catalog and selection.  These
participants merely translate one verified, exact AMD component generation into
the small owner-neutral projection that the matching domain accepts.  They do
not contain a deployment state machine, a runtime binding, or a fallback.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..embedding_settings import (
    EmbeddingProviderProjection,
    EmbeddingSettingsService,
    ManagedEmbeddingProviderRef,
    ManagedEmbeddingProjectionStatus,
    managed_embedding_provider_id,
)
from ..llm.settings import (
    LLMSettingsService,
    ManagedLlmProviderProjection,
    ManagedLlmProviderProjectionStatus,
    ManagedLlmProviderRef,
)
from ..ocr.settings import (
    ManagedOcrProviderProjectionStatus,
    ManagedOcrProviderRef,
    OcrProviderProjection,
    OcrSettingsService,
    managed_ocr_provider_id,
)
from .manifests import ComponentManifest, ManifestCapability

AMD_MANAGER_ID = "amd-rocm"


class AmdParticipantError(RuntimeError):
    """A verified AMD generation cannot be projected safely to its owner."""


class AmdParticipantProjectionConflictError(AmdParticipantError):
    """A capability already assigned the exact ID to incompatible content."""


@dataclass(frozen=True, slots=True)
class AmdProjectionStatus:
    """Redacted status the deployment coordinator may use for derivation."""

    exists: bool
    retiring: bool
    selected: bool


class AmdComponentParticipant(Protocol):
    """One capability-specific projection bridge for the deployment facade."""

    @property
    def capability(self) -> ManifestCapability: ...

    def ensure(
        self,
        *,
        installation_id: str,
        component_generation_id: str,
        manifest: ComponentManifest,
    ) -> AmdProjectionStatus: ...

    def mark_retiring(
        self,
        *,
        installation_id: str,
        component_generation_id: str,
    ) -> AmdProjectionStatus: ...

    def remove(
        self,
        *,
        installation_id: str,
        component_generation_id: str,
    ) -> AmdProjectionStatus: ...

    def status(
        self,
        *,
        installation_id: str,
        component_generation_id: str,
    ) -> AmdProjectionStatus: ...


def _require_capability(manifest: ComponentManifest, expected: ManifestCapability) -> None:
    if manifest.capability is not expected:
        raise AmdParticipantError(f"AMD {expected.value} participant received the wrong component manifest.")


def _component_model_name(manifest: ComponentManifest) -> str:
    """Use the explicit served-model contract, not a transport profile name."""

    value = manifest.launch.served_model_name.strip()
    if not value or "/" in value:
        raise AmdParticipantError("AMD component manifest has an invalid served model name.")
    return value


def _single_model(manifest: ComponentManifest):
    if len(manifest.models) != 1:
        raise AmdParticipantError("AMD component manifest must describe exactly one served model.")
    return manifest.models[0]


@dataclass(frozen=True, slots=True)
class AmdLlmParticipant:
    settings: LLMSettingsService

    @property
    def capability(self) -> ManifestCapability:
        return ManifestCapability.CHAT

    def ensure(
        self,
        *,
        installation_id: str,
        component_generation_id: str,
        manifest: ComponentManifest,
    ) -> AmdProjectionStatus:
        _require_capability(manifest, self.capability)
        model = _single_model(manifest)
        reference = ManagedLlmProviderRef(
            manager_id=AMD_MANAGER_ID,
            installation_id=installation_id,
            component_generation_id=component_generation_id,
        )
        projection = ManagedLlmProviderProjection(
            reference=reference,
            display_name=f"AMD Radeon · {model.model_id.rsplit('/', maxsplit=1)[-1]}",
            models=[_component_model_name(manifest)],
            manifest_digest=manifest.manifest_digest,
            model_compatibility={
                "capability": self.capability.value,
                "model_id": model.model_id,
                "model_revision": model.revision,
                "protocol": manifest.protocol.protocol_id,
                "protocol_version": manifest.protocol.protocol_version,
            },
        )
        try:
            self.settings.ensure_managed_provider(projection)
        except Exception as exc:
            raise _participant_error(exc) from exc
        return self.status(
            installation_id=installation_id,
            component_generation_id=component_generation_id,
        )

    def mark_retiring(
        self,
        *,
        installation_id: str,
        component_generation_id: str,
    ) -> AmdProjectionStatus:
        reference = _llm_reference(installation_id, component_generation_id)
        current = self.status(
            installation_id=installation_id,
            component_generation_id=component_generation_id,
        )
        if not current.exists:
            return current
        try:
            self.settings.mark_managed_provider_retiring(reference)
        except Exception as exc:
            raise _participant_error(exc) from exc
        return self.status(installation_id=installation_id, component_generation_id=component_generation_id)

    def remove(
        self,
        *,
        installation_id: str,
        component_generation_id: str,
    ) -> AmdProjectionStatus:
        reference = _llm_reference(installation_id, component_generation_id)
        current = self.status(
            installation_id=installation_id,
            component_generation_id=component_generation_id,
        )
        if not current.exists:
            return current
        try:
            self.settings.remove_managed_provider(reference)
        except Exception as exc:
            raise _participant_error(exc) from exc
        return self.status(installation_id=installation_id, component_generation_id=component_generation_id)

    def status(
        self,
        *,
        installation_id: str,
        component_generation_id: str,
    ) -> AmdProjectionStatus:
        status: ManagedLlmProviderProjectionStatus = self.settings.projection_status(
            _llm_reference(installation_id, component_generation_id)
        )
        return AmdProjectionStatus(
            exists=status.exists,
            retiring=status.retiring,
            selected=(status.default_selected or status.turn_completion_guard_selected or status.thread_title_selected),
        )


@dataclass(frozen=True, slots=True)
class AmdEmbeddingParticipant:
    settings: EmbeddingSettingsService

    @property
    def capability(self) -> ManifestCapability:
        return ManifestCapability.EMBEDDING

    def ensure(
        self,
        *,
        installation_id: str,
        component_generation_id: str,
        manifest: ComponentManifest,
    ) -> AmdProjectionStatus:
        _require_capability(manifest, self.capability)
        model = _single_model(manifest)
        if model.output_dimensions is None or model.tokenizer_id is None or model.tokenizer_revision is None:
            raise AmdParticipantError("AMD Embedding manifest has incomplete vector-space identity.")
        reference = ManagedEmbeddingProviderRef(
            manager_id=AMD_MANAGER_ID,
            installation_id=installation_id,
            component_generation_id=component_generation_id,
        )
        projection = EmbeddingProviderProjection(
            id=managed_embedding_provider_id(reference),
            display_name=f"AMD Radeon · {manifest.protocol.profile_id}",
            model=_component_model_name(manifest),
            dimensions=model.output_dimensions,
            tokenizer_identity=f"{model.tokenizer_id}@{model.tokenizer_revision}",
            manifest_digest=manifest.manifest_digest,
            target=reference,
            read_only=True,
        )
        try:
            self.settings.ensure_managed_provider(projection)
        except Exception as exc:
            raise _participant_error(exc) from exc
        return self.status(installation_id=installation_id, component_generation_id=component_generation_id)

    def mark_retiring(
        self,
        *,
        installation_id: str,
        component_generation_id: str,
    ) -> AmdProjectionStatus:
        reference = _embedding_reference(installation_id, component_generation_id)
        current = self.status(
            installation_id=installation_id,
            component_generation_id=component_generation_id,
        )
        if not current.exists:
            return current
        try:
            self.settings.mark_managed_provider_retiring(reference)
        except Exception as exc:
            raise _participant_error(exc) from exc
        return self.status(installation_id=installation_id, component_generation_id=component_generation_id)

    def remove(
        self,
        *,
        installation_id: str,
        component_generation_id: str,
    ) -> AmdProjectionStatus:
        reference = _embedding_reference(installation_id, component_generation_id)
        current = self.status(
            installation_id=installation_id,
            component_generation_id=component_generation_id,
        )
        if not current.exists:
            return current
        try:
            self.settings.remove_managed_provider(reference)
        except Exception as exc:
            raise _participant_error(exc) from exc
        return self.status(installation_id=installation_id, component_generation_id=component_generation_id)

    def status(
        self,
        *,
        installation_id: str,
        component_generation_id: str,
    ) -> AmdProjectionStatus:
        status: ManagedEmbeddingProjectionStatus = self.settings.projection_status(
            _embedding_reference(installation_id, component_generation_id)
        )
        return AmdProjectionStatus(
            exists=status.exists,
            retiring=status.retiring,
            selected=status.active,
        )


@dataclass(frozen=True, slots=True)
class AmdOcrParticipant:
    settings: OcrSettingsService

    @property
    def capability(self) -> ManifestCapability:
        return ManifestCapability.OCR

    def ensure(
        self,
        *,
        installation_id: str,
        component_generation_id: str,
        manifest: ComponentManifest,
    ) -> AmdProjectionStatus:
        _require_capability(manifest, self.capability)
        _single_model(manifest)
        reference = ManagedOcrProviderRef(
            manager_id=AMD_MANAGER_ID,
            installation_id=installation_id,
            component_generation_id=component_generation_id,
        )
        projection = OcrProviderProjection(
            id=managed_ocr_provider_id(reference),
            display_name=f"AMD Radeon · {manifest.protocol.profile_id}",
            model=_component_model_name(manifest),
            descriptor_fingerprint=manifest.manifest_digest,
            target=reference,
            read_only=True,
        )
        try:
            self.settings.ensure_managed_provider(projection)
        except Exception as exc:
            raise _participant_error(exc) from exc
        return self.status(installation_id=installation_id, component_generation_id=component_generation_id)

    def mark_retiring(
        self,
        *,
        installation_id: str,
        component_generation_id: str,
    ) -> AmdProjectionStatus:
        reference = _ocr_reference(installation_id, component_generation_id)
        current = self.status(
            installation_id=installation_id,
            component_generation_id=component_generation_id,
        )
        if not current.exists:
            return current
        try:
            self.settings.mark_managed_provider_retiring(reference)
        except Exception as exc:
            raise _participant_error(exc) from exc
        return self.status(installation_id=installation_id, component_generation_id=component_generation_id)

    def remove(
        self,
        *,
        installation_id: str,
        component_generation_id: str,
    ) -> AmdProjectionStatus:
        reference = _ocr_reference(installation_id, component_generation_id)
        current = self.status(
            installation_id=installation_id,
            component_generation_id=component_generation_id,
        )
        if not current.exists:
            return current
        try:
            self.settings.remove_managed_provider(reference)
        except Exception as exc:
            raise _participant_error(exc) from exc
        return self.status(installation_id=installation_id, component_generation_id=component_generation_id)

    def status(
        self,
        *,
        installation_id: str,
        component_generation_id: str,
    ) -> AmdProjectionStatus:
        status: ManagedOcrProviderProjectionStatus = self.settings.projection_status(
            _ocr_reference(installation_id, component_generation_id)
        )
        return AmdProjectionStatus(
            exists=status.exists,
            retiring=status.retiring,
            selected=status.active,
        )


def _participant_error(exc: BaseException) -> AmdParticipantError:
    code = getattr(exc, "error_code", None)
    if code in {
        "llm_provider_owner_conflict",
        "llm_provider_projection_conflict",
        "embedding_provider_owner_conflict",
        "ocr_provider_owner_conflict",
        "ocr_provider_projection_conflict",
    }:
        return AmdParticipantProjectionConflictError("Managed provider projection conflicts with current settings.")
    return AmdParticipantError("The capability provider catalog rejected the AMD managed projection.")


def _llm_reference(installation_id: str, component_generation_id: str) -> ManagedLlmProviderRef:
    return ManagedLlmProviderRef(
        manager_id=AMD_MANAGER_ID,
        installation_id=installation_id,
        component_generation_id=component_generation_id,
    )


def _embedding_reference(installation_id: str, component_generation_id: str) -> ManagedEmbeddingProviderRef:
    return ManagedEmbeddingProviderRef(
        manager_id=AMD_MANAGER_ID,
        installation_id=installation_id,
        component_generation_id=component_generation_id,
    )


def _ocr_reference(installation_id: str, component_generation_id: str) -> ManagedOcrProviderRef:
    return ManagedOcrProviderRef(
        manager_id=AMD_MANAGER_ID,
        installation_id=installation_id,
        component_generation_id=component_generation_id,
    )


__all__ = [
    "AMD_MANAGER_ID",
    "AmdComponentParticipant",
    "AmdEmbeddingParticipant",
    "AmdLlmParticipant",
    "AmdOcrParticipant",
    "AmdParticipantError",
    "AmdParticipantProjectionConflictError",
    "AmdProjectionStatus",
]
