"""Explicit policies for allowed trust-label data flows."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from buildguard.exceptions import BuildGuardError
from buildguard.schemas.common import StrictSchema
from buildguard.security.advanced.taint import TaintTrace
from buildguard.security.advanced.trust_labels import (
    TRUSTED_CONTROL_LABELS,
    LabeledData,
    TrustLabel,
)

FlowDestination = Literal[
    "data",
    "tool_name",
    "read_path",
    "write_path",
    "resource_id",
    "network_enable",
    "network_payload",
]


class DataPolicyViolation(BuildGuardError):
    """A labeled value attempted to cross a forbidden data-flow boundary."""


class DataPolicyDecision(StrictSchema):
    allowed: bool
    reason: str = Field(min_length=1, max_length=2000)
    destination: FlowDestination


def _labels(value: LabeledData | TaintTrace) -> set[TrustLabel]:
    if isinstance(value, LabeledData):
        return {value.label}
    return set(value.labels)


def _trusted_for_control(value: LabeledData | TaintTrace) -> bool:
    return _labels(value).issubset(TRUSTED_CONTROL_LABELS)


class DataFlowPolicy:
    """Keep untrusted content in declared data slots, never control slots."""

    def check(
        self,
        value: LabeledData | TaintTrace,
        destination: FlowDestination,
    ) -> DataPolicyDecision:
        labels = _labels(value)
        if destination == "data":
            return DataPolicyDecision(
                allowed=True,
                reason="Labeled content may fill a declared data parameter",
                destination=destination,
            )
        if destination == "network_payload" and value.sensitive:
            return DataPolicyDecision(
                allowed=False,
                reason="Sensitive data must not flow to a network tool",
                destination=destination,
            )
        if destination == "network_payload":
            return DataPolicyDecision(
                allowed=True,
                reason="Non-sensitive payload does not alter network control state",
                destination=destination,
            )
        if destination == "network_enable":
            allowed = labels.issubset(
                {
                    TrustLabel.TRUSTED_POLICY,
                    TrustLabel.TRUSTED_CONFIRMATION,
                }
            )
            return DataPolicyDecision(
                allowed=allowed,
                reason=(
                    "Network state requires trusted policy or explicit confirmation"
                    if not allowed
                    else "Trusted policy/confirmation permits the network control value"
                ),
                destination=destination,
            )
        if destination in {
            "tool_name",
            "read_path",
            "write_path",
            "resource_id",
        }:
            allowed = _trusted_for_control(value)
            return DataPolicyDecision(
                allowed=allowed,
                reason=(
                    f"Untrusted data cannot control {destination}"
                    if not allowed
                    else f"Trusted control source may set {destination}"
                ),
                destination=destination,
            )
        return DataPolicyDecision(
            allowed=False,
            reason=f"Unknown data-flow destination: {destination}",
            destination=destination,
        )

    def enforce(
        self,
        value: LabeledData | TaintTrace,
        destination: FlowDestination,
    ) -> None:
        decision = self.check(value, destination)
        if not decision.allowed:
            raise DataPolicyViolation(decision.reason)

    @staticmethod
    def destination_for_parameter(parameter: str) -> FlowDestination:
        normalized = parameter.casefold()
        if normalized == "tool_name":
            return "tool_name"
        if normalized in {"network", "enable_network", "allow_network"}:
            return "network_enable"
        if normalized in {"resource_id", "resource_ids"}:
            return "resource_id"
        if normalized in {"output_path", "write_path", "report_path"}:
            return "write_path"
        if (
            normalized in {"path", "directory", "root", "image_path", "video_path"}
            or normalized.endswith(("_path", "_paths"))
        ):
            return "read_path"
        return "data"
