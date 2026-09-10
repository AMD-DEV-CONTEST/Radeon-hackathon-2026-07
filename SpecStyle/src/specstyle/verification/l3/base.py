"""Domain plugin protocol and applicability."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

from specstyle.domain.identifiers import ArtifactId
from specstyle.errors import DomainError
from specstyle.verification.rule_models import RuleResult

DomainProfile = Literal["product_instance", "face_identity", "structure_only"]
Applicability = Literal["APPLICABLE", "NOT_APPLICABLE"]


@dataclass(frozen=True, slots=True)
class DomainContext:
    domain_profile: DomainProfile
    plugin_id: str
    plugin_revision: str

    def __post_init__(self) -> None:
        if self.domain_profile not in (
            "product_instance",
            "face_identity",
            "structure_only",
        ):
            raise DomainError("invalid domain profile")
        if type(self.plugin_id) is not str or not self.plugin_id:
            raise DomainError("invalid plugin id")
        if type(self.plugin_revision) is not str or not self.plugin_revision:
            raise DomainError("invalid plugin revision")


@runtime_checkable
class DomainPlugin(Protocol):
    plugin_id: str
    supported_domains: tuple[DomainProfile, ...]

    def applicability(self, context: DomainContext, /) -> Applicability: ...

    def verify(
        self,
        artifact_id: ArtifactId,
        context: DomainContext,
        /,
    ) -> RuleResult: ...


def resolve_applicability(
    plugin: DomainPlugin, context: DomainContext
) -> Applicability:
    if type(context) is not DomainContext:
        raise DomainError("invalid domain context")
    if context.domain_profile not in plugin.supported_domains:
        return "NOT_APPLICABLE"
    if context.plugin_id != plugin.plugin_id:
        return "NOT_APPLICABLE"
    return plugin.applicability(context)
