"""Safe, session-local progress vocabulary for AMD deployment commands.

Progress is presentation-only.  It carries no durable identity, endpoint,
credential, target output, path, or exception detail and can never authorize a
lifecycle transition.  Callers may drop events without changing deployment
correctness.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from .manifests import ManifestCapability


class AmdProgressMilestone(StrEnum):
    INPUT_VALIDATED = "input_validated"
    HOST_KEY_DISCOVERY_STARTED = "host_key_discovery_started"
    HOST_KEY_DISCOVERED = "host_key_discovered"
    HOST_TRUST_AWAITING = "host_trust_awaiting"
    HOST_TRUST_ACCEPTED = "host_trust_accepted"
    INSTALL_INTENT_SAVING = "install_intent_saving"
    INSTALL_INTENT_SAVED = "install_intent_saved"
    SSH_SECURITY_SAVING = "ssh_security_saving"
    SSH_SECURITY_SAVED = "ssh_security_saved"
    TARGET_INSPECTION_STARTED = "target_inspection_started"
    TARGET_COMPATIBLE = "target_compatible"
    COMPONENT_PREPARATION_STARTED = "component_preparation_started"
    COMPONENT_PREPARED = "component_prepared"
    RUNTIME_STARTING = "runtime_starting"
    RUNTIME_STARTED = "runtime_started"
    SELF_TEST_STARTED = "self_test_started"
    SELF_TEST_PASSED = "self_test_passed"
    PROVIDER_REGISTRATION_STARTED = "provider_registration_started"
    PROVIDER_REGISTERED = "provider_registered"
    OPERATIONAL = "operational"


@dataclass(frozen=True, slots=True)
class AmdProgressEvent:
    """One closed-vocabulary observation safe to project into the guided UI."""

    milestone: AmdProgressMilestone
    capability: ManifestCapability | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.milestone, AmdProgressMilestone):
            raise TypeError("AMD progress milestone is invalid.")
        if self.capability is not None and not isinstance(
            self.capability,
            ManifestCapability,
        ):
            raise TypeError("AMD progress capability is invalid.")


type AmdProgressSink = Callable[[AmdProgressEvent], None]


def report_progress(
    sink: AmdProgressSink | None,
    milestone: AmdProgressMilestone,
    capability: ManifestCapability | None = None,
) -> None:
    """Best-effort observation; presentation failure cannot fail deployment."""

    if sink is None:
        return
    try:
        sink(AmdProgressEvent(milestone=milestone, capability=capability))
    except Exception:
        return


__all__ = [
    "AmdProgressEvent",
    "AmdProgressMilestone",
    "AmdProgressSink",
    "report_progress",
]
