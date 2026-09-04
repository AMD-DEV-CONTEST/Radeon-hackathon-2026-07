from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from policyseal.application.analysis import AnalysisResult, AnalysisService
from policyseal.application.matrix import evaluate_xlsx
from policyseal.documents.base import ParsedDocument
from policyseal.domain.enums import Action, FileKind, RevisionStatus
from policyseal.domain.errors import AnalysisFailed
from policyseal.domain.models import DisclosureContext, PolicyDecision
from policyseal.policy.evaluator import evaluate_region
from policyseal.storage.file_store import FileNamespace


@dataclass(frozen=True, slots=True)
class SimulationResult:
    id: str
    task_id: str
    base_revision_id: str
    context: DisclosureContext
    status: RevisionStatus
    decisions: tuple[PolicyDecision, ...]
    created_at: datetime
    downloadable: bool = False


class SimulationService:
    def __init__(self, analysis: AnalysisService) -> None:
        self.analysis = analysis
        self._simulations: dict[str, SimulationResult] = {}

    def simulate(self, task_id: str, context: DisclosureContext) -> SimulationResult:
        revisions = self.analysis.repository.list_revisions(task_id)
        if not revisions:
            raise AnalysisFailed("task has no formal revision")
        base = revisions[-1]
        regions = self.analysis.repository.list_regions(base.id)
        if not regions:
            raise AnalysisFailed("formal revision must be analyzed before simulation")
        if base.context.policy_version != context.policy_version:
            raise AnalysisFailed("simulation policy version must match the formal revision")
        if self.analysis.repository.get_task(task_id).file_kind is FileKind.XLSX:
            parsed = self.analysis.get_result(base.id)
            source_path = self.analysis.file_store.path_for(
                FileNamespace.SOURCES,
                parsed.task.source_storage_id,
            )
            document = ParsedDocument(
                source_path,
                parsed.task.source,
                FileKind.XLSX,
                regions,
                self.analysis.adapters[FileKind.XLSX].preflight(source_path),
            )
            decisions = evaluate_xlsx(document, self.analysis.policy_pack, context)
        else:
            decisions = tuple(
                evaluate_region(self.analysis.policy_pack, context, region) for region in regions
            )
        if any(decision.action is Action.BLOCK for decision in decisions):
            status = RevisionStatus.BLOCKED
        elif any(decision.action is Action.REQUIRE_APPROVAL for decision in decisions):
            status = RevisionStatus.AWAITING_APPROVAL
        else:
            status = RevisionStatus.EXPORTABLE
        simulation = SimulationResult(
            id=f"simulation-{uuid.uuid4().hex}",
            task_id=task_id,
            base_revision_id=base.id,
            context=context,
            status=status,
            decisions=decisions,
            created_at=datetime.now(UTC),
        )
        self._simulations[simulation.id] = simulation
        return simulation

    def get(self, simulation_id: str) -> SimulationResult:
        try:
            return self._simulations[simulation_id]
        except KeyError as error:
            raise AnalysisFailed("simulation does not exist") from error

    def confirm_formal(self, simulation_id: str, *, actor: str) -> AnalysisResult:
        simulation = self.get(simulation_id)
        draft = self.analysis.create_revision(
            simulation.task_id,
            context=simulation.context,
            actor=actor,
        )
        return self.analysis.analyze_revision(draft.revision.id)
