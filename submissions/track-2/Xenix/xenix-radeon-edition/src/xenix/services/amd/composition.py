"""Explicit application composition for the Radeon Edition deployment slice.

This module is the one place where the AMD control plane is joined to
capability-owned settings and factory registries.  Importing it is inert:
resource loading, registration, and construction happen only when
``build_amd_composition`` is called by the application composition root.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from ..ocr.contracts import OcrRuntimeDescriptor
from ..ocr.settings import ManagedOcrProviderRef, OcrProviderProjection
from .adapters import AmdEmbeddingAdapter, AmdLlmAdapter, AmdOcrAdapter, AmdOcrDescriptorMismatchError
from .capability_deployment import AmdCapabilityDeploymentAdapter
from .deployment import AmdAiDeploymentService
from .guided_capability import AmdCapabilityGuidedDeploymentService
from .manifests import ComponentManifest, ManifestCapability, ManifestCatalog
from .participants import AMD_MANAGER_ID, AmdEmbeddingParticipant, AmdLlmParticipant, AmdOcrParticipant
from .placements.local import LocalAmdPlacement
from .placements.private import PrivateSshRecipePlacement
from .placements.ssh import PrivateSshAmdPlacement
from .placements.wsl import WslAmdPlacement, WslTargetRecipe
from .placements.wsl_recipes import CatalogWslLoopbackVerifier, LocalWslRecipePlacement
from .profile_catalog import load_product_manifest_catalog
from .recipes import target_recipe_programs
from .runtime import AmdRuntimeDirectory
from .ssh_security import (
    AmdSettingsSshCredentialResolver,
    AmdSettingsSshTrustResolver,
    AmdSqliteSshTargetResolver,
    AmdSshSecurityStore,
)
from .ssh_trust import OpenSshHostTrustProbe
from ..storage.repositories.amd_installations import AmdInstallationRepository

if TYPE_CHECKING:
    from sqlmodel import Session

    from ..embedding_provider_factory import EmbeddingProviderFactoryRegistry
    from ..embedding_settings import EmbeddingSettingsService
    from ..llm.provider_factory import LLMProviderFactoryRegistry
    from ..llm.settings import LLMSettingsService
    from ..ocr.settings import OcrProviderFactoryRegistry, OcrSettingsService
    from ..settings_store import SettingsStore


class AmdCompositionError(RuntimeError):
    """The Radeon deployment composition could not be initialized safely."""


@dataclass(slots=True)
class AmdComposition:
    """App-owned handles for the Radeon deployment control plane.

    ``catalog`` is exposed read-only so an AMD UI can select the fixed product
    profile without independently reloading manifest resources.  The shared
    settings store and generic factory registries remain app-owned and are not
    closed or otherwise mutated by :meth:`close`.
    """

    catalog: ManifestCatalog
    deployment: AmdAiDeploymentService
    capability_deployments: dict[ManifestCapability, AmdCapabilityDeploymentAdapter]
    capability_guided_deployments: dict[ManifestCapability, AmdCapabilityGuidedDeploymentService]
    ssh_security: AmdSshSecurityStore
    ssh_target_resolver: AmdSqliteSshTargetResolver
    _closed: bool = field(default=False, init=False, repr=False)

    def close(self) -> None:
        """Close only live AMD deployment sessions before the settings store closes."""

        if self._closed:
            return
        try:
            # First fence the only owner that can schedule a target action.
            # Its retirement workers may still be unwinding an existing session;
            # closing their resolvers first would turn orderly shutdown into a
            # race against app-owned settings/SQLite dependencies.
            self.deployment.close()
            self.ssh_target_resolver.close()
            self.ssh_security.close()
        except Exception:
            raise AmdCompositionError("AMD deployment shutdown could not complete.") from None
        self._closed = True


def build_amd_composition(
    *,
    session_factory: Callable[[], Session],
    settings_store: SettingsStore,
    llm_settings_service: LLMSettingsService,
    embedding_settings_service: EmbeddingSettingsService,
    ocr_settings_service: OcrSettingsService,
    llm_provider_factory_registry: LLMProviderFactoryRegistry,
    embedding_provider_factory_registry: EmbeddingProviderFactoryRegistry,
    ocr_provider_factory_registry: OcrProviderFactoryRegistry,
    local_cache_root: Path,
    temporary_root: Path,
) -> AmdComposition:
    """Compose one app-lifetime AMD control plane at the explicit app edge.

    The caller owns the supplied SettingsStore, settings services, registries,
    and paths.  This builder does not create directories, inspect a target, or
    start a process.  It only reads the bundled product catalog and registers
    three factory contributions with the already-established registries.
    """

    if not callable(session_factory):
        raise AmdCompositionError("AMD composition requires a session factory.")
    local_root = _resolve_private_root(local_cache_root, label="local cache")
    temporary_parent = _resolve_private_root(temporary_root, label="temporary")
    try:
        catalog = load_product_manifest_catalog()
        repository = AmdInstallationRepository()
        runtime_directory = AmdRuntimeDirectory()
        _require_factory_slots_available(
            llm_provider_factory_registry,
            embedding_provider_factory_registry,
            ocr_provider_factory_registry,
        )

        ssh_security = AmdSshSecurityStore(settings_store)
        ssh_target_resolver = AmdSqliteSshTargetResolver(session_factory, repository)
        private_ssh = PrivateSshAmdPlacement(
            target_resolver=ssh_target_resolver,
            credential_resolver=AmdSettingsSshCredentialResolver(ssh_security),
            trust_resolver=AmdSettingsSshTrustResolver(ssh_security),
            temporary_parent=temporary_parent,
        )
        private_ssh_recipes = PrivateSshRecipePlacement(private_ssh)
        wsl_recipes = {
            recipe_id: WslTargetRecipe(recipe_id=recipe_id, script=script)
            for recipe_id, script in target_recipe_programs().items()
        }
        wsl_operation = WslAmdPlacement(
            recipes=wsl_recipes,
            loopback_verifier=CatalogWslLoopbackVerifier(catalog),
        )
        local_wsl = LocalWslRecipePlacement(wsl_operation)
        historical_local = LocalAmdPlacement(product_root=local_root)

        deployment = AmdAiDeploymentService(
            session_factory=session_factory,
            catalog=catalog,
            placements={
                private_ssh_recipes.placement_kind: private_ssh_recipes,
                local_wsl.placement_kind: local_wsl,
                # No Local install route is exposed.  The controller remains
                # solely as the exact cleanup owner for historical generations.
                historical_local.placement_kind: historical_local,
            },
            participants={
                ManifestCapability.CHAT: AmdLlmParticipant(llm_settings_service),
                ManifestCapability.EMBEDDING: AmdEmbeddingParticipant(embedding_settings_service),
                ManifestCapability.OCR: AmdOcrParticipant(ocr_settings_service),
            },
            runtime_directory=runtime_directory,
            repository=repository,
            new_installation_placements=frozenset({"private_ssh", "local_wsl"}),
        )
        capability_deployments = {
            capability: AmdCapabilityDeploymentAdapter(
                capability=capability,
                catalog=catalog,
                deployment=deployment,
            )
            for capability in ManifestCapability
        }
        host_trust_probe = OpenSshHostTrustProbe(temporary_parent=temporary_parent)
        capability_guided_deployments = {
            capability: AmdCapabilityGuidedDeploymentService(
                adapter=adapter,
                deployment=deployment,
                ssh_security=ssh_security,
                host_trust_probe=host_trust_probe,
                wsl_operation=wsl_operation,
            )
            for capability, adapter in capability_deployments.items()
        }

        llm_provider_factory_registry.register_managed_factory(
            AMD_MANAGER_ID,
            AmdLlmAdapter(runtime_directory),
        )
        embedding_provider_factory_registry.register_managed_factory(
            AMD_MANAGER_ID,
            AmdEmbeddingAdapter(runtime_directory),
        )
        ocr_provider_factory_registry.register_managed(
            AMD_MANAGER_ID,
            AmdOcrAdapter(
                runtime_directory,
                _ocr_descriptor_resolver(
                    catalog,
                    session_factory=session_factory,
                    repository=repository,
                ),
            ),
        )
    except AmdCompositionError:
        raise
    except Exception:
        raise AmdCompositionError("AMD deployment composition could not be initialized.") from None

    return AmdComposition(
        catalog=catalog,
        deployment=deployment,
        capability_deployments=capability_deployments,
        capability_guided_deployments=capability_guided_deployments,
        ssh_security=ssh_security,
        ssh_target_resolver=ssh_target_resolver,
    )


def _ocr_descriptor_resolver(
    catalog: ManifestCatalog,
    *,
    session_factory: Callable[[], Session],
    repository: AmdInstallationRepository,
) -> Callable[
    [ManagedOcrProviderRef, OcrProviderProjection],
    OcrRuntimeDescriptor,
]:
    """Build the pure catalog-to-OCR-provenance resolver required by the adapter."""

    def resolve(
        reference: ManagedOcrProviderRef,
        projection: OcrProviderProjection,
    ) -> OcrRuntimeDescriptor:
        if (
            not isinstance(reference, ManagedOcrProviderRef)
            or reference.manager_id != AMD_MANAGER_ID
            or not isinstance(projection, OcrProviderProjection)
            or projection.target != reference
        ):
            raise AmdOcrDescriptorMismatchError()
        try:
            with session_factory() as session:
                installation = repository.get_installation(session, reference.installation_id)
                generation = repository.get_generation(session, reference.component_generation_id)
        except Exception:
            raise AmdOcrDescriptorMismatchError() from None
        if (
            installation is None
            or generation is None
            or installation.id != reference.installation_id
            or generation.id != reference.component_generation_id
            or generation.installation_id != installation.id
            or generation.capability != ManifestCapability.OCR.value
            or generation.manifest_digest != projection.descriptor_fingerprint
        ):
            raise AmdOcrDescriptorMismatchError()
        try:
            manifest = catalog.component(projection.descriptor_fingerprint)
        except Exception:
            raise AmdOcrDescriptorMismatchError() from None
        if (
            manifest.capability is not ManifestCapability.OCR
            or manifest.manifest_digest != projection.descriptor_fingerprint
            or manifest.launch.served_model_name != projection.model
        ):
            raise AmdOcrDescriptorMismatchError()
        try:
            return OcrRuntimeDescriptor(
                generation_id=reference.component_generation_id,
                runtime_id=manifest.runtime.runtime_id,
                model_pack_id=manifest.launch.served_model_name,
                engine=manifest.runtime.framework_id,
                engine_version=manifest.runtime.framework_version,
                protocol=_stable_protocol_string(manifest),
                manifest_digest=manifest.manifest_digest,
            )
        except Exception:
            raise AmdOcrDescriptorMismatchError() from None

    return resolve


def _stable_protocol_string(manifest: ComponentManifest) -> str:
    """Represent the immutable protocol identity without any live binding data."""

    return f"{manifest.protocol.protocol_id}@{manifest.protocol.protocol_version}"


def _require_factory_slots_available(
    llm_provider_factory_registry: LLMProviderFactoryRegistry,
    embedding_provider_factory_registry: EmbeddingProviderFactoryRegistry,
    ocr_provider_factory_registry: OcrProviderFactoryRegistry,
) -> None:
    """Preflight all three composition slots before publishing any factory."""

    registered = (
        llm_provider_factory_registry.registered_manager_ids,
        embedding_provider_factory_registry.registered_manager_ids,
        ocr_provider_factory_registry.registered_manager_ids,
    )
    if any(AMD_MANAGER_ID in manager_ids for manager_ids in registered):
        raise AmdCompositionError("AMD provider factories are already registered.")


def _resolve_private_root(value: Path, *, label: str) -> Path:
    """Accept a caller-owned absolute root without exposing its rendered path."""

    try:
        path = Path(value)
    except (OSError, TypeError, ValueError):
        raise AmdCompositionError(f"AMD composition requires a valid {label} root.") from None
    if not path.is_absolute():
        raise AmdCompositionError(f"AMD composition requires an absolute {label} root.")
    try:
        return path.resolve(strict=False)
    except (OSError, RuntimeError):
        raise AmdCompositionError(f"AMD composition could not resolve its {label} root.") from None


__all__ = [
    "AmdComposition",
    "AmdCompositionError",
    "build_amd_composition",
]
