from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .contracts import (
    AudiencePulse,
    AuditFinding,
    CampaignRequest,
    CampaignState,
    Claim,
    CreativeAsset,
    CreativeBrief,
)


class EvidenceMiner(Protocol):
    def extract(self, request: CampaignRequest) -> list[Claim]: ...


class CreativeDirector(Protocol):
    def plan(self, state: CampaignState) -> list[CreativeBrief]: ...


class Studio(Protocol):
    def create(self, state: CampaignState) -> list[CreativeAsset]: ...


class ReleaseAuditor(Protocol):
    def audit(self, state: CampaignState) -> list[AuditFinding]: ...


class RepairPlanner(Protocol):
    def repair(self, state: CampaignState) -> list[CreativeAsset]: ...


class CampaignExporter(Protocol):
    def export(self, state: CampaignState) -> list[str]: ...


class AudienceCritic(Protocol):
    def review(self, brief: CreativeBrief) -> AudiencePulse: ...


@dataclass(frozen=True)
class AdapterBundle:
    evidence: EvidenceMiner
    director: CreativeDirector
    studio: Studio
    auditor: ReleaseAuditor
    repairer: RepairPlanner
    exporter: CampaignExporter
    audience: AudienceCritic
