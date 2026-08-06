"""Guided commands for one capability-scoped Radeon deployment adapter.

This facade owns only cross-authority user commands: explicit host-trust
discovery, durable SSH enrollment/checkpoints, Local WSL distribution choice,
and progress reporting.  It does not select providers or issue inference
requests.  Each instance is fixed to one capability adapter.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from .capability_deployment import (
    AmdCapabilityDeploymentAdapter,
    AmdCapabilityDeploymentOption,
    AmdCapabilityInstallation,
)
from .deployment import AmdAiDeploymentService, AmdDeploymentError, AmdPrivateTargetSpec, AmdRetirementRequest
from .manifests import ManifestCapability
from .placements.ssh import PinnedHostKey, SshTargetEnrollment, SshTargetResolutionError
from .placements.wsl import WslAmdPlacement, WslPlacementError
from .progress import AmdProgressMilestone, AmdProgressSink, report_progress
from .ssh_security import AmdSshSecurityError, AmdSshSecurityStore
from .ssh_trust import AmdSshHostTrustChallenge, AmdSshHostTrustDiscoveryError, OpenSshHostTrustProbe
from .status import AmdInstallationStatus


class AmdGuidedInputField(StrEnum):
    """Focusable fields that can receive one redacted guided error."""

    HOST = "host"
    USER = "user"
    PORT = "port"
    IDENTITY_FILE = "identity_file"
    WSL_DISTRIBUTION = "wsl_distribution"


class AmdGuidedDeploymentError(RuntimeError):
    """A safe guided-command failure suitable for UI projection."""

    def __init__(self, error_code: str, *, field: AmdGuidedInputField | None = None) -> None:
        super().__init__(error_code)
        self.error_code = error_code
        self.field = field


@dataclass(frozen=True, slots=True)
class AmdPrivateSshInstallCommand:
    """One user-approved fresh Private SSH enrollment and install intent."""

    installation_id: str
    target_id: str
    host: str = field(repr=False)
    user: str = field(repr=False)
    port: int = field(repr=False)
    identity_file: Path | None = field(repr=False)
    option_id: str | None = None


@dataclass(frozen=True, slots=True)
class AmdExistingPrivateSshInstallCommand:
    """Install this capability on an already enrolled Private SSH target."""

    installation_id: str
    target_id: str
    option_id: str | None = None


@dataclass(frozen=True, slots=True)
class AmdLocalWslInstallCommand:
    """Install this capability in one explicitly chosen Local WSL2 distribution."""

    installation_id: str
    distribution: str = field(repr=False)
    option_id: str | None = None


@dataclass(frozen=True, slots=True)
class AmdGuidedPrivateTarget:
    """Safe existing-target projection for choosing an additional capability."""

    target_id: str
    host: str = field(repr=False)
    user: str = field(repr=False)
    port: int = field(repr=False)
    security_enrolled: bool


@dataclass(frozen=True, slots=True)
class AmdGuidedCapabilityInstallation:
    """UI-safe status projection for one adapter-owned installation."""

    installation_id: str
    placement: str
    desired_presence: bool
    lifecycle_state: str
    status: AmdInstallationStatus = field(repr=False)
    target_id: str | None = field(default=None, repr=False)
    local_wsl_distribution: str | None = field(default=None, repr=False)
    security_enrolled: bool = False
    option: AmdCapabilityDeploymentOption | None = None


class AmdCapabilityGuidedDeploymentService:
    """Deep AMD-only guided facade fixed to one deployment capability."""

    def __init__(
        self,
        *,
        adapter: AmdCapabilityDeploymentAdapter,
        deployment: AmdAiDeploymentService,
        ssh_security: AmdSshSecurityStore,
        host_trust_probe: OpenSshHostTrustProbe,
        wsl_operation: WslAmdPlacement,
    ) -> None:
        if not isinstance(adapter, AmdCapabilityDeploymentAdapter):
            raise TypeError("Guided AMD deployment requires a capability adapter.")
        if not isinstance(wsl_operation, WslAmdPlacement):
            raise TypeError("Guided AMD deployment requires a Local WSL operation.")
        self._adapter = adapter
        self._deployment = deployment
        self._ssh_security = ssh_security
        self._host_trust_probe = host_trust_probe
        self._wsl_operation = wsl_operation
        self._lock = threading.RLock()

    @property
    def capability(self) -> ManifestCapability:
        return self._adapter.capability

    def inventory(self) -> tuple[AmdGuidedCapabilityInstallation, ...]:
        records: list[AmdGuidedCapabilityInstallation] = []
        for item in self._adapter.inventory():
            records.append(self._project_installation(item))
        return tuple(records)

    def deployment_options(self, placement: str | None = None) -> tuple[AmdCapabilityDeploymentOption, ...]:
        """Return the adapter-owned immutable option projection without target I/O."""

        return self._adapter.deployment_options(placement)

    def private_targets(self) -> tuple[AmdGuidedPrivateTarget, ...]:
        """List reusable enrolled targets, without network activity."""

        targets: dict[str, AmdGuidedPrivateTarget] = {}
        try:
            enrollments = self._deployment.private_targets()
        except AmdDeploymentError as exc:
            raise AmdGuidedDeploymentError(exc.error_code) from None
        for enrollment in enrollments:
            if enrollment.target_id in targets:
                continue
            try:
                secured = self._ssh_security.contains_target(enrollment.target_id)
            except AmdSshSecurityError as exc:
                raise AmdGuidedDeploymentError(exc.error_code) from None
            targets[enrollment.target_id] = AmdGuidedPrivateTarget(
                target_id=enrollment.target_id,
                host=enrollment.host,
                user=enrollment.user,
                port=enrollment.port,
                security_enrolled=secured,
            )
        return tuple(sorted(targets.values(), key=lambda target: target.target_id))

    def local_wsl_distributions(self) -> tuple[str, ...]:
        try:
            return self._wsl_operation.list_distributions()
        except WslPlacementError as exc:
            raise AmdGuidedDeploymentError(exc.error_code, field=AmdGuidedInputField.WSL_DISTRIBUTION) from None

    def validate_private_fields(self, command: AmdPrivateSshInstallCommand) -> None:
        self._validate_private(command, require_identity_available=False)

    def validate_private(self, command: AmdPrivateSshInstallCommand) -> None:
        self._validate_private(command, require_identity_available=True)

    def discover_private_host_trust(
        self,
        command: AmdPrivateSshInstallCommand,
        *,
        progress: AmdProgressSink | None = None,
    ) -> AmdSshHostTrustChallenge:
        self._validate_private(command, require_identity_available=True)
        report_progress(progress, AmdProgressMilestone.INPUT_VALIDATED)
        report_progress(progress, AmdProgressMilestone.HOST_KEY_DISCOVERY_STARTED)
        try:
            challenge = self._host_trust_probe.discover(host=command.host, port=command.port)
        except AmdSshHostTrustDiscoveryError as exc:
            raise AmdGuidedDeploymentError(exc.error_code) from None
        report_progress(progress, AmdProgressMilestone.HOST_KEY_DISCOVERED)
        report_progress(progress, AmdProgressMilestone.HOST_TRUST_AWAITING)
        return challenge

    def install_private(
        self,
        command: AmdPrivateSshInstallCommand,
        *,
        accepted_trust: AmdSshHostTrustChallenge,
        progress: AmdProgressSink | None = None,
    ) -> AmdInstallationStatus:
        with self._lock:
            validated = self._validate_private(command, require_identity_available=True)
            host_key = _validated_trust_challenge(command, accepted_trust)
            report_progress(progress, AmdProgressMilestone.HOST_TRUST_ACCEPTED)
            try:
                identity_reference, host_key_reference = self._ssh_security.references_for_target(command.target_id)
            except AmdSshSecurityError as exc:
                raise AmdGuidedDeploymentError(exc.error_code) from None
            target = AmdPrivateTargetSpec(
                target_id=command.target_id,
                host=command.host,
                user=command.user,
                port=command.port,
                pinned_host_key=host_key_reference,
                identity_file_reference=identity_reference,
            )
            report_progress(progress, AmdProgressMilestone.INSTALL_INTENT_SAVING)
            try:
                self._adapter.install_private_intent(
                    installation_id=command.installation_id,
                    target=target,
                    option_id=command.option_id,
                )
            except AmdDeploymentError as exc:
                raise AmdGuidedDeploymentError(exc.error_code) from None
            report_progress(progress, AmdProgressMilestone.INSTALL_INTENT_SAVED)
            report_progress(progress, AmdProgressMilestone.SSH_SECURITY_SAVING)
            try:
                self._ssh_security.record(
                    target_id=command.target_id,
                    identity_file=validated.identity_file,
                    host_key=host_key,
                )
            except AmdSshSecurityError as exc:
                raise AmdGuidedDeploymentError(exc.error_code) from None
            report_progress(progress, AmdProgressMilestone.SSH_SECURITY_SAVED)
            try:
                return self._adapter.install_private(
                    installation_id=command.installation_id,
                    target=target,
                    option_id=command.option_id,
                    progress=progress,
                )
            except AmdDeploymentError as exc:
                raise AmdGuidedDeploymentError(exc.error_code) from None

    def install_existing_private(
        self,
        command: AmdExistingPrivateSshInstallCommand,
        *,
        progress: AmdProgressSink | None = None,
    ) -> AmdInstallationStatus:
        if not isinstance(command, AmdExistingPrivateSshInstallCommand):
            raise AmdGuidedDeploymentError("amd_request_invalid")
        with self._lock:
            try:
                secured = self._ssh_security.contains_target(command.target_id)
            except AmdSshSecurityError as exc:
                raise AmdGuidedDeploymentError(exc.error_code) from None
            if not secured:
                raise AmdGuidedDeploymentError("amd_ssh_enrollment_incomplete")
            try:
                target = self._deployment.private_target(command.target_id)
                return self._adapter.install_private(
                    installation_id=command.installation_id,
                    target=target,
                    option_id=command.option_id,
                    progress=progress,
                )
            except AmdDeploymentError as exc:
                raise AmdGuidedDeploymentError(exc.error_code) from None

    def install_local_wsl(
        self,
        command: AmdLocalWslInstallCommand,
        *,
        progress: AmdProgressSink | None = None,
    ) -> AmdInstallationStatus:
        if not isinstance(command, AmdLocalWslInstallCommand):
            raise AmdGuidedDeploymentError("amd_request_invalid")
        distributions = self.local_wsl_distributions()
        if command.distribution not in distributions:
            raise AmdGuidedDeploymentError(
                "amd_wsl_distribution_unavailable",
                field=AmdGuidedInputField.WSL_DISTRIBUTION,
            )
        try:
            return self._adapter.install_local_wsl(
                installation_id=command.installation_id,
                distribution=command.distribution,
                option_id=command.option_id,
                progress=progress,
            )
        except AmdDeploymentError as exc:
            raise AmdGuidedDeploymentError(exc.error_code) from None

    def repair(
        self,
        installation_id: str,
        *,
        progress: AmdProgressSink | None = None,
    ) -> AmdInstallationStatus:
        try:
            return self._adapter.repair(installation_id, progress=progress)
        except AmdDeploymentError as exc:
            raise AmdGuidedDeploymentError(exc.error_code) from None

    def request_retirement(self, installation_id: str) -> AmdRetirementRequest:
        try:
            return self._adapter.request_retirement(installation_id)
        except AmdDeploymentError as exc:
            raise AmdGuidedDeploymentError(exc.error_code) from None

    def retire(self, installation_id: str, *, drain_timeout_seconds: float | None = None) -> AmdInstallationStatus:
        try:
            return self._adapter.retire(installation_id, drain_timeout_seconds=drain_timeout_seconds)
        except AmdDeploymentError as exc:
            raise AmdGuidedDeploymentError(exc.error_code) from None

    def _project_installation(self, item: AmdCapabilityInstallation) -> AmdGuidedCapabilityInstallation:
        security_enrolled = False
        if item.target_id is not None:
            try:
                security_enrolled = self._ssh_security.contains_target(item.target_id)
            except AmdSshSecurityError:
                security_enrolled = False
        return AmdGuidedCapabilityInstallation(
            installation_id=item.installation_id,
            placement=item.placement,
            desired_presence=item.desired_presence,
            lifecycle_state=item.lifecycle_state,
            status=item.status,
            target_id=item.target_id,
            local_wsl_distribution=item.local_wsl_distribution,
            security_enrolled=security_enrolled,
            option=item.option,
        )

    @staticmethod
    def _validate_private(
        command: AmdPrivateSshInstallCommand,
        *,
        require_identity_available: bool,
    ) -> "_ValidatedPrivateInstall":
        if not isinstance(command, AmdPrivateSshInstallCommand):
            raise AmdGuidedDeploymentError("amd_request_invalid")
        if not isinstance(command.host, str) or not command.host.strip():
            raise AmdGuidedDeploymentError("amd_ssh_host_required", field=AmdGuidedInputField.HOST)
        if not isinstance(command.user, str) or not command.user.strip():
            raise AmdGuidedDeploymentError("amd_ssh_user_required", field=AmdGuidedInputField.USER)
        if command.identity_file is None:
            raise AmdGuidedDeploymentError("amd_ssh_identity_required", field=AmdGuidedInputField.IDENTITY_FILE)
        try:
            SshTargetEnrollment(
                target_id=command.target_id,
                host=command.host,
                user=command.user,
                port=command.port,
                pinned_host_key_reference="guided-validation",
                identity_file_reference="guided-validation",
            )
        except SshTargetResolutionError as exc:
            field_by_code = {
                "amd_ssh_host_invalid": AmdGuidedInputField.HOST,
                "amd_ssh_user_invalid": AmdGuidedInputField.USER,
                "amd_ssh_port_invalid": AmdGuidedInputField.PORT,
            }
            raise AmdGuidedDeploymentError(exc.error_code, field=field_by_code.get(exc.error_code)) from None
        return _ValidatedPrivateInstall(
            command=command,
            identity_file=_validated_identity_file(command.identity_file, require_available=require_identity_available),
        )


@dataclass(frozen=True, slots=True)
class _ValidatedPrivateInstall:
    command: AmdPrivateSshInstallCommand = field(repr=False)
    identity_file: Path = field(repr=False)


def _validated_trust_challenge(
    command: AmdPrivateSshInstallCommand,
    challenge: AmdSshHostTrustChallenge,
) -> PinnedHostKey:
    if (
        not isinstance(challenge, AmdSshHostTrustChallenge)
        or challenge.host != command.host
        or challenge.port != command.port
    ):
        raise AmdGuidedDeploymentError("amd_ssh_host_trust_challenge_invalid")
    return challenge.host_key


def _validated_identity_file(value: Path, *, require_available: bool) -> Path:
    try:
        path = Path(value)
        rendered = str(path)
    except (OSError, TypeError, ValueError):
        raise AmdGuidedDeploymentError("amd_ssh_identity_invalid", field=AmdGuidedInputField.IDENTITY_FILE) from None
    if (
        not path.is_absolute()
        or not rendered
        or len(rendered) > 2_048
        or rendered.startswith(("\\\\", "//"))
        or "\x00" in rendered
        or "\r" in rendered
        or "\n" in rendered
    ):
        raise AmdGuidedDeploymentError("amd_ssh_identity_invalid", field=AmdGuidedInputField.IDENTITY_FILE)
    if require_available:
        try:
            available = path.is_file()
        except OSError:
            available = False
        if not available:
            raise AmdGuidedDeploymentError("amd_ssh_identity_unavailable", field=AmdGuidedInputField.IDENTITY_FILE)
    return path


__all__ = [
    "AmdCapabilityGuidedDeploymentService",
    "AmdCapabilityDeploymentOption",
    "AmdExistingPrivateSshInstallCommand",
    "AmdGuidedCapabilityInstallation",
    "AmdGuidedDeploymentError",
    "AmdGuidedInputField",
    "AmdGuidedPrivateTarget",
    "AmdLocalWslInstallCommand",
    "AmdPrivateSshInstallCommand",
    "AmdSshHostTrustChallenge",
]
