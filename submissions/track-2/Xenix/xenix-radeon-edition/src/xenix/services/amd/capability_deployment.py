"""Capability-scoped AMD deployment adapters.

Each adapter is fixed to exactly one product capability.  It is a control-plane
boundary, not an inference adapter: it resolves one immutable deployment option
for an explicit execution location and delegates durable lifecycle work to the shared
coordinator.  SSH trust, credentials, Settings selection, and live bindings
remain outside this module.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .deployment import (
    AmdAiDeploymentService,
    AmdDeploymentError,
    AmdInstallationSpec,
    AmdPrivateTargetSpec,
    AmdRetirementRequest,
)
from .manifests import ExecutionProfileManifest, ExecutionProfilePlacement, ManifestCapability, ManifestCatalog
from .progress import AmdProgressSink
from .status import AmdInstallationStatus


class AmdCapabilityDeploymentError(AmdDeploymentError):
    """A lifecycle request crossed a capability adapter boundary incorrectly."""

    def __init__(self, message: str = "AMD capability deployment is unavailable.", *, error_code: str = "amd_capability_unavailable") -> None:
        super().__init__(message, error_code=error_code)


@dataclass(frozen=True, slots=True)
class AmdCapabilityDeploymentOption:
    """UI-safe projection of one current, admitted capability recipe."""

    option_id: str
    display_name: str
    model_id: str
    placement: str
    served_model_name: str
    license_spdx: str
    context_limit: int | None
    minimum_free_vram_bytes: int | None
    required_persistent_bytes: int | None
    supports_streaming: bool
    supports_tool_calls: bool
    supports_reasoning: bool
    variant: str | None = None


@dataclass(frozen=True, slots=True)
class AmdCapabilityInstallation:
    """One bounded inventory projection owned by a capability adapter."""

    installation_id: str
    placement: str
    desired_presence: bool
    lifecycle_state: str
    status: AmdInstallationStatus = field(repr=False)
    target_id: str | None = field(default=None, repr=False)
    local_wsl_distribution: str | None = field(default=None, repr=False)
    option: AmdCapabilityDeploymentOption | None = None


class AmdCapabilityDeploymentAdapter:
    """Deploy exactly one capability over Private SSH or Local WSL2."""

    def __init__(
        self,
        *,
        capability: ManifestCapability,
        catalog: ManifestCatalog,
        deployment: AmdAiDeploymentService,
    ) -> None:
        if not isinstance(capability, ManifestCapability):
            raise TypeError("AMD capability deployment requires a capability.")
        self._capability = capability
        self._catalog = catalog
        self._deployment = deployment
        self._profiles = _current_profiles_for_capability(catalog, capability)
        self._options_by_profile_digest = {
            profile.manifest_digest: _deployment_option(catalog, profile)
            for profile in catalog.profiles
            if _profile_has_capability(catalog, profile, capability)
        }

    @property
    def capability(self) -> ManifestCapability:
        return self._capability

    def deployment_options(self, placement: str | None = None) -> tuple[AmdCapabilityDeploymentOption, ...]:
        """Return current admitted recipes without exposing manifest authority."""

        try:
            typed_placement = ExecutionProfilePlacement(placement) if placement is not None else None
        except (TypeError, ValueError):
            return ()
        options = (
            _deployment_option(self._catalog, profile)
            for profile in self._profiles.values()
            if typed_placement is None or profile.placement is typed_placement
        )
        return tuple(sorted(options, key=_deployment_option_sort_key))

    def profile_for(self, placement: str, option_id: str | None = None) -> ExecutionProfileManifest:
        try:
            typed_placement = ExecutionProfilePlacement(placement)
        except (TypeError, ValueError):
            raise AmdCapabilityDeploymentError(
                "This Radeon capability has no profile for the selected location.",
                error_code="amd_capability_profile_unavailable",
            ) from None
        candidates = tuple(
            profile
            for (candidate_placement, _profile_id), profile in self._profiles.items()
            if candidate_placement is typed_placement
        )
        if option_id is not None:
            candidates = tuple(profile for profile in candidates if profile.profile_id == option_id)
        elif candidates:
            candidates = (
                min(
                    candidates,
                    key=lambda profile: _deployment_option_sort_key(
                        _deployment_option(self._catalog, profile)
                    ),
                ),
            )
        if len(candidates) != 1:
            error_code = (
                "amd_capability_profile_unavailable"
                if option_id is None
                else "amd_capability_option_unavailable"
            )
            raise AmdCapabilityDeploymentError(
                "This Radeon deployment option is unavailable for the selected location.",
                error_code=error_code,
            )
        return candidates[0]

    def install_private_intent(
        self,
        *,
        installation_id: str,
        target: AmdPrivateTargetSpec,
        option_id: str | None = None,
    ) -> None:
        profile = self.profile_for("private_ssh", option_id)
        self._deployment.ensure_private_install_intent(
            target=target,
            installation=AmdInstallationSpec(
                installation_id=installation_id,
                placement="private_ssh",
                profile_digest=profile.manifest_digest,
                target_id=target.target_id,
            ),
        )

    def install_private(
        self,
        *,
        installation_id: str,
        target: AmdPrivateTargetSpec,
        option_id: str | None = None,
        progress: AmdProgressSink | None = None,
    ) -> AmdInstallationStatus:
        self.install_private_intent(installation_id=installation_id, target=target, option_id=option_id)
        return self._deployment.reconcile(installation_id, progress=progress)

    def install_local_wsl(
        self,
        *,
        installation_id: str,
        distribution: str,
        option_id: str | None = None,
        progress: AmdProgressSink | None = None,
    ) -> AmdInstallationStatus:
        profile = self.profile_for("local_wsl", option_id)
        return self._deployment.prepare(
            AmdInstallationSpec(
                installation_id=installation_id,
                placement="local_wsl",
                profile_digest=profile.manifest_digest,
                local_wsl_distribution=distribution,
            ),
            progress=progress,
        )

    def repair(
        self,
        installation_id: str,
        *,
        progress: AmdProgressSink | None = None,
    ) -> AmdInstallationStatus:
        self._require_owned(installation_id)
        return self._deployment.repair(installation_id, progress=progress)

    def request_retirement(self, installation_id: str) -> AmdRetirementRequest:
        self._require_owned(installation_id)
        return self._deployment.request_retirement(installation_id)

    def retire(
        self,
        installation_id: str,
        *,
        drain_timeout_seconds: float | None = 0.0,
    ) -> AmdInstallationStatus:
        self._require_owned(installation_id)
        return self._deployment.retire(installation_id, drain_timeout_seconds=drain_timeout_seconds)

    def status(self, installation_id: str) -> AmdInstallationStatus:
        return self._require_owned(installation_id)

    def inventory(self) -> tuple[AmdCapabilityInstallation, ...]:
        """List only current single-capability installations owned by this adapter."""

        records: list[AmdCapabilityInstallation] = []
        private_targets = {
            enrollment.installation_id: enrollment.target_id
            for enrollment in self._deployment.private_installations()
        }
        for item in self._deployment.installations():
            if item.lifecycle_state == "removed":
                continue
            try:
                status = self._deployment.status(item.installation_id)
            except AmdDeploymentError:
                continue
            if not _is_capability_status(status, self._capability):
                continue
            records.append(
                AmdCapabilityInstallation(
                    installation_id=item.installation_id,
                    placement=item.placement,
                    desired_presence=item.desired_presence,
                    lifecycle_state=item.lifecycle_state,
                    status=status,
                    target_id=private_targets.get(item.installation_id, item.target_id),
                    local_wsl_distribution=item.local_wsl_distribution,
                    option=self._options_by_profile_digest.get(status.profile_digest),
                )
            )
        return tuple(records)

    def _require_owned(self, installation_id: str) -> AmdInstallationStatus:
        try:
            status = self._deployment.status(installation_id)
        except AmdDeploymentError:
            raise
        if not _is_capability_status(status, self._capability):
            raise AmdCapabilityDeploymentError(
                "AMD installation belongs to a different capability or historical profile.",
                error_code="amd_capability_installation_mismatch",
            )
        return status


def _current_profiles_for_capability(
    catalog: ManifestCatalog,
    capability: ManifestCapability,
) -> dict[tuple[ExecutionProfilePlacement, str], ExecutionProfileManifest]:
    profiles: dict[tuple[ExecutionProfilePlacement, str], ExecutionProfileManifest] = {}
    for profile in catalog.profiles:
        if not _profile_has_capability(catalog, profile, capability):
            continue
        identity = (profile.placement, profile.profile_id)
        previous = profiles.get(identity)
        if previous is None or _profile_version(profile) > _profile_version(previous):
            profiles[identity] = profile
        elif _profile_version(profile) == _profile_version(previous):
            raise AmdCapabilityDeploymentError(
                "AMD capability profile catalog is ambiguous.",
                error_code="amd_capability_profile_ambiguous",
            )
    if not profiles:
        raise AmdCapabilityDeploymentError(
            "AMD capability profile catalog is incomplete.",
            error_code="amd_capability_profile_incomplete",
        )
    return profiles


def _profile_has_capability(
    catalog: ManifestCatalog,
    profile: ExecutionProfileManifest,
    capability: ManifestCapability,
) -> bool:
    if profile.placement is ExecutionProfilePlacement.LEGACY:
        return False
    components = catalog.profile_components(profile)
    return len(components) == 1 and components[0].capability is capability


def _profile_version(profile: ExecutionProfileManifest) -> tuple[int, ...]:
    parts = profile.profile_version.split(".")
    if not parts or any(not part.isdigit() for part in parts):
        raise AmdCapabilityDeploymentError(
            "Selectable AMD profile versions must be numeric.",
            error_code="amd_capability_profile_ambiguous",
        )
    return tuple(int(part) for part in parts)


def _deployment_option(catalog: ManifestCatalog, profile: ExecutionProfileManifest) -> AmdCapabilityDeploymentOption:
    component = catalog.profile_components(profile)[0]
    if len(component.models) != 1:
        raise AmdCapabilityDeploymentError(
            "A selectable Radeon capability must serve exactly one model.",
            error_code="amd_capability_profile_ambiguous",
        )
    model = component.models[0]
    field_names = {rule.field_name for rule in component.protocol.field_rules}
    context_limit = _launch_integer_argument(component.launch.arguments, "--max-model-len=")
    variant = {
        "Qwen/Qwen3.5-9B": "recommended",
        "Qwen/Qwen3.5-4B": "lightweight",
    }.get(model.model_id)
    return AmdCapabilityDeploymentOption(
        option_id=profile.profile_id,
        display_name=model.model_id.rsplit("/", maxsplit=1)[-1],
        model_id=model.model_id,
        placement=profile.placement.value,
        served_model_name=component.launch.served_model_name,
        license_spdx=model.license_spdx,
        context_limit=context_limit,
        minimum_free_vram_bytes=profile.capacity.min_free_vram_bytes,
        required_persistent_bytes=profile.capacity.required_persistent_bytes,
        supports_streaming="stream" in field_names,
        supports_tool_calls="tools" in field_names,
        supports_reasoning="reasoning" in field_names,
        variant=variant,
    )


def _launch_integer_argument(arguments: tuple[str, ...], prefix: str) -> int | None:
    values = tuple(argument.removeprefix(prefix) for argument in arguments if argument.startswith(prefix))
    if len(values) != 1:
        return None
    try:
        return int(values[0])
    except ValueError:
        return None


def _deployment_option_sort_key(option: AmdCapabilityDeploymentOption) -> tuple[int, str, str]:
    rank = {"recommended": 0, "lightweight": 1}.get(option.variant, 2)
    return rank, option.display_name.casefold(), option.placement


def _is_capability_status(status: AmdInstallationStatus, capability: ManifestCapability) -> bool:
    components = tuple(status.components)
    return len(components) == 1 and components[0].capability is capability


__all__ = [
    "AmdCapabilityDeploymentAdapter",
    "AmdCapabilityDeploymentError",
    "AmdCapabilityInstallation",
    "AmdCapabilityDeploymentOption",
]
