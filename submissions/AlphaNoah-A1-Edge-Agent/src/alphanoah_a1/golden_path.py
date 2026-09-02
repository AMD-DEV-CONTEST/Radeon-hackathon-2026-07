"""Application composition for the synthetic restaurant-aircon golden path."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping, Sequence

from .exceptions import ProviderInputError
from .knowledge import (
    ContextBuilder,
    DeterministicKnowledgeRetriever,
    JsonKnowledgeRepository,
)
from .knowledge.models import KnowledgeContext
from .knowledge.retrieval import (
    KnowledgeMatch,
    KnowledgeQuery,
    KnowledgeRetriever,
)
from .models import (
    AnalysisResult,
    Decision,
    Event,
    Evidence,
    HookResult,
    HumanReview,
    HumanReviewOutcome,
    PostReviewResult,
    Review,
    Task,
)
from .providers import ReliabilityPolicy, ReliableAnalysisProvider
from .qr_input import QRIncidentInputAdapter
from .runtime import AlphaNoahRuntime
from .skill import SkillContext
from .skills.demo import DEMO_SKILL_DEFINITIONS
from .skills.resolver import DeterministicSkillResolver

if TYPE_CHECKING:
    from .providers.base import AnalysisProvider

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RESTAURANT_KNOWLEDGE_FILE = (
    REPOSITORY_ROOT / "examples" / "skill_demo_knowledge.json"
)

SCENARIO_ID = "synthetic-restaurant-aircon-troubleshooting"
SCENARIO_SKILL_ID = "restaurant-aircon-troubleshooting"
SCENARIO_SKILL_VERSION = "1.0-demo"
SCENARIO_EVENT_TYPE = "equipment_fault_report"
SCENARIO_ASSET_TYPE = "air_conditioner"

DEMO_REVIEWER = "human:demo-restaurant-reviewer"
DEMO_TASK_ASSIGNEE = "demo:restaurant-duty-operator"
DEMO_EVIDENCE_REVIEWER = "human:demo-evidence-reviewer"
DEMO_TASK_DEADLINE = "2026-12-31T23:59:00+08:00"
DEMO_EVIDENCE_TYPE = "synthetic_state_verification"
DEMO_EVIDENCE_REF = "synthetic://restaurant/aircon/state-after-action"
WEB_EVIDENCE_TYPE = "synthetic_text_statement"


def restaurant_aircon_form_fields() -> dict[str, str]:
    """Return a fresh bounded payload accepted by the existing QR adapter."""

    return {
        "event_type": SCENARIO_EVENT_TYPE,
        "asset_id": "A08-AIRCON",
        "location": "Restaurant-Private-Room-A08",
        "reporter": "synthetic:equipment-operator",
        "description": (
            "Synthetic equipment report: the A08 air conditioner "
            "is operating abnormally."
        ),
        "attachments": "",
    }


def restaurant_aircon_event_metadata() -> dict[str, str]:
    """Return trusted application metadata, never user-supplied form data."""

    return {
        "asset_type": SCENARIO_ASSET_TYPE,
        "scenario_id": SCENARIO_ID,
    }


def restaurant_aircon_task_template() -> dict[str, str]:
    """Return the synthetic approved-work template for the existing Runtime."""

    return {
        "task_type": "restaurant_aircon_fault_inspection",
        "assignee": DEMO_TASK_ASSIGNEE,
        "description": (
            "An authorized maintenance operator inspects the reported "
            "air-conditioner anomaly using approved safe procedures."
        ),
        "expected_result": (
            "Synthetic evidence records the observed air-conditioner state "
            "after an authorized inspection."
        ),
    }


class RestaurantAirconFakeAnalysisProvider:
    """Offline deterministic backend for the formal reliability boundary."""

    provider_id = "fake:restaurant-aircon-golden-path"
    model = "fixture:restaurant-aircon-v1"
    prompt_version = "fixture-restaurant-aircon-golden-path-v1"

    def __init__(self) -> None:
        self.calls = 0
        self.last_skill_context: SkillContext | None = None
        self.last_knowledge_context: KnowledgeContext | None = None

    def analyze(self, event: Event) -> AnalysisResult:
        raise ProviderInputError(
            "The restaurant golden path requires explicit SkillContext.",
            code="skill_context_required",
        )

    def analyze_with_context(
        self,
        event: Event,
        knowledge_context: KnowledgeContext,
    ) -> AnalysisResult:
        raise ProviderInputError(
            "The restaurant golden path requires explicit SkillContext.",
            code="skill_context_required",
        )

    def analyze_with_contexts(
        self,
        event: Event,
        skill_context: SkillContext,
        knowledge_context: KnowledgeContext,
    ) -> AnalysisResult:
        if skill_context.skill_id != SCENARIO_SKILL_ID:
            raise ProviderInputError(
                "The resolved Skill does not match the restaurant scenario.",
                code="unexpected_demo_skill",
            )
        self.calls += 1
        self.last_skill_context = skill_context
        self.last_knowledge_context = knowledge_context
        return AnalysisResult(
            detected_issue=(
                "Synthetic air conditioner fault requires inspection."
            ),
            decision_type="ai_assisted_incident_analysis",
            reasoning_summary=(
                "The synthetic report describes an equipment anomaly. An "
                "authorized human must inspect the equipment and review any "
                "recommended action before maintenance proceeds."
            ),
            evidence=[
                "Synthetic QR incident report",
                "Bounded restaurant-aircon Skill Context",
                (
                    "Bounded Knowledge Context "
                    f"({len(knowledge_context.documents)} document(s))"
                ),
            ],
            model_or_rule=self.provider_id,
            confidence=0.88,
            requires_human_review=True,
            severity="HIGH",
        )


class RecordingKnowledgeRetriever:
    """Read-only application wrapper that records actual retriever evidence."""

    def __init__(self, retriever: KnowledgeRetriever):
        if not callable(getattr(retriever, "retrieve", None)):
            raise TypeError("retriever must implement retrieve")
        self.retriever = retriever
        self.last_query: KnowledgeQuery | None = None
        self.last_matches: tuple[KnowledgeMatch, ...] = ()

    def reset(self) -> None:
        self.last_query = None
        self.last_matches = ()

    def retrieve(
        self,
        query: KnowledgeQuery,
    ) -> Sequence[KnowledgeMatch]:
        matches = tuple(self.retriever.retrieve(query))
        self.last_query = query
        self.last_matches = matches
        return matches


@dataclass(frozen=True, slots=True)
class GoldenPathKnowledgeMatch:
    """Safe application projection of one actual KnowledgeMatch."""

    document_id: str
    source: str
    version: str
    score: int
    matched_fields: tuple[str, ...]
    matched_keywords: tuple[str, ...]

    @classmethod
    def from_match(cls, match: KnowledgeMatch) -> GoldenPathKnowledgeMatch:
        return cls(
            document_id=match.document.id,
            source=match.document.source,
            version=match.document.version,
            score=match.score,
            matched_fields=match.matched_fields,
            matched_keywords=match.matched_keywords,
        )


@dataclass(frozen=True, slots=True)
class GoldenPathAnalysisSummary:
    """Safe application result after the formal provider/runtime path."""

    event_id: str
    trace_id: str
    event_status: str
    decision_id: str
    decision_status: str
    selected_skill_id: str
    selected_skill_version: str
    knowledge_matches: tuple[GoldenPathKnowledgeMatch, ...]
    validation_status: str
    provider_name: str
    model_name: str


@dataclass(frozen=True, slots=True)
class GoldenPathTimelineEntry:
    """Bounded read-only projection of one persisted AuditRecord."""

    sequence: int
    timestamp: str
    action: str
    actor: str
    entity_type: str
    entity_id: str
    status: str
    summary: str
    metadata: tuple[tuple[str, str], ...] = ()


_TIMELINE_DETAIL_FIELDS = (
    "hook_action",
    "skill_id",
    "skill_version",
    "skill_resolution",
    "validation_status",
    "provider_name",
    "model_name",
    "context_count",
)
_TIMELINE_COLLECTION_FIELDS = (
    "knowledge_sources",
    "knowledge_statuses",
)


class RestaurantAirconGoldenPath:
    """Application orchestration over existing AlphaNoah public boundaries."""

    def __init__(
        self,
        *,
        runtime: AlphaNoahRuntime,
        input_adapter: QRIncidentInputAdapter,
        skill_resolver: DeterministicSkillResolver,
        provider: ReliableAnalysisProvider,
        recording_retriever: RecordingKnowledgeRetriever,
    ):
        self.runtime = runtime
        self.input_adapter = input_adapter
        self.skill_resolver = skill_resolver
        self.provider = provider
        self.recording_retriever = recording_retriever

    def submit_incident(
        self,
        form_fields: Mapping[str, object] | None = None,
    ) -> Event:
        """Enter through the exact application adapter used by QR HTTP POST."""

        return self.input_adapter.submit(
            restaurant_aircon_form_fields()
            if form_fields is None
            else form_fields
        )

    def analyze(self, event_id: str) -> GoldenPathAnalysisSummary:
        """Resolve Skill/knowledge and invoke the formal reliable provider."""

        self.recording_retriever.reset()
        decision, _hook = self.runtime.analyze_event_with_provider(
            event_id,
            provider=self.provider,
            skill_resolver=self.skill_resolver,
        )
        event = self.runtime.store.get_event(event_id)
        skill = self.skill_resolver.resolve(event)
        metadata = self.provider.get_audit_metadata()
        return GoldenPathAnalysisSummary(
            event_id=event.event_id,
            trace_id=event.trace_id,
            event_status=event.status.value,
            decision_id=decision.decision_id,
            decision_status=decision.status.value,
            selected_skill_id=skill.skill_id,
            selected_skill_version=skill.skill_version,
            knowledge_matches=tuple(
                GoldenPathKnowledgeMatch.from_match(match)
                for match in self.recording_retriever.last_matches
            ),
            validation_status=str(
                metadata.get("validation_status", "NOT_VALIDATED")
            ),
            provider_name=str(metadata.get("provider_name", "unknown")),
            model_name=str(metadata.get("model_name", "unknown")),
        )

    def submit_human_review(
        self,
        decision_id: str,
        *,
        outcome: HumanReviewOutcome,
        reviewer: str = DEMO_REVIEWER,
        comment: str,
    ) -> HumanReview:
        """Apply only an explicit caller-selected human outcome."""

        return self.runtime.submit_human_review(
            decision_id,
            reviewer=reviewer,
            outcome=outcome,
            comment=comment,
        )

    def create_approved_task(
        self,
        decision_id: str,
        *,
        actor: str = DEMO_REVIEWER,
    ) -> Task:
        """Create an air-conditioner task through the existing Runtime API."""

        return self.runtime.create_task(
            decision_id,
            actor=actor,
            deadline=DEMO_TASK_DEADLINE,
            task_template=restaurant_aircon_task_template(),
        )

    def start_task(self, task_id: str) -> Task:
        return self.runtime.start_task(
            task_id,
            actor=DEMO_TASK_ASSIGNEE,
        )

    def submit_synthetic_evidence(self, task_id: str) -> Evidence:
        """Submit a bounded synthetic reference; no file or device access."""

        return self.runtime.submit_evidence(
            task_id,
            evidence_type=DEMO_EVIDENCE_TYPE,
            file_or_data_ref=DEMO_EVIDENCE_REF,
            submitted_by=DEMO_TASK_ASSIGNEE,
            description=(
                "Synthetic evidence: an authorized demo operator recorded "
                "the verified post-action air-conditioner state."
            ),
            idempotency_key=f"task05a-evidence:{task_id}",
        )

    def submit_text_evidence(
        self,
        task_id: str,
        *,
        description: str,
    ) -> Evidence:
        """Submit bounded text evidence through the existing Runtime API."""

        digest = hashlib.sha256(description.encode("utf-8")).hexdigest()
        return self.runtime.submit_evidence(
            task_id,
            evidence_type=WEB_EVIDENCE_TYPE,
            file_or_data_ref=f"synthetic://web-adapter/{task_id}/statement",
            submitted_by=DEMO_TASK_ASSIGNEE,
            description=description,
            idempotency_key=f"task05c1-evidence:{task_id}:{digest}",
        )

    def begin_evidence_review(self, task_id: str) -> Task:
        return self.runtime.begin_review(
            task_id,
            actor=DEMO_EVIDENCE_REVIEWER,
        )

    def review_evidence(
        self,
        task_id: str,
        *,
        result: PostReviewResult,
        reviewer: str = DEMO_EVIDENCE_REVIEWER,
        comment: str,
    ) -> Review:
        """Close only when the existing Runtime accepts explicit review."""

        return self.runtime.review_task(
            task_id,
            reviewer_or_model=reviewer,
            result=result,
            comment=comment,
        )

    def timeline(self, event_id: str) -> tuple[GoldenPathTimelineEntry, ...]:
        """Project actual persisted audits without adding synthetic history."""

        event = self.runtime.store.get_event(event_id)
        entries: list[GoldenPathTimelineEntry] = []
        for sequence, record in enumerate(
            self.runtime.store.list_audit(event.trace_id),
            1,
        ):
            metadata = self._safe_metadata(record.details)
            transition = (
                f"{record.previous_state or '-'} -> "
                f"{record.new_state or '-'}"
            )
            entries.append(
                GoldenPathTimelineEntry(
                    sequence=sequence,
                    timestamp=record.timestamp,
                    action=record.action,
                    actor=record.actor,
                    entity_type=record.object_type,
                    entity_id=record.object_id,
                    status=record.new_state or "",
                    summary=transition,
                    metadata=metadata,
                )
            )
        return tuple(entries)

    @staticmethod
    def _safe_metadata(
        details: Mapping[str, Any],
    ) -> tuple[tuple[str, str], ...]:
        safe: dict[str, str] = {}
        for field in _TIMELINE_DETAIL_FIELDS:
            value = details.get(field)
            if isinstance(value, (str, int)) and not isinstance(value, bool):
                safe[field] = str(value)
        model_metadata = details.get("model_metadata")
        if isinstance(model_metadata, Mapping):
            for field in _TIMELINE_DETAIL_FIELDS:
                value = model_metadata.get(field)
                if isinstance(value, (str, int)) and not isinstance(
                    value,
                    bool,
                ):
                    safe[field] = str(value)
            for field in _TIMELINE_COLLECTION_FIELDS:
                value = model_metadata.get(field)
                if (
                    isinstance(value, list)
                    and len(value) <= 10
                    and all(
                        isinstance(item, str) and len(item) <= 200
                        for item in value
                    )
                ):
                    safe[field] = ",".join(value)
        return tuple(sorted(safe.items()))


def build_restaurant_aircon_golden_path(
    database_path: str | Path,
    *,
    raw_provider: AnalysisProvider | None = None,
    knowledge_file: str | Path = DEFAULT_RESTAURANT_KNOWLEDGE_FILE,
    reliability_policy: ReliabilityPolicy | None = None,
) -> RestaurantAirconGoldenPath:
    """Compose Task 05A from frozen Runtime, Skill and knowledge components."""

    runtime = AlphaNoahRuntime(str(database_path))
    input_adapter = QRIncidentInputAdapter(
        runtime,
        trusted_metadata=restaurant_aircon_event_metadata(),
    )
    skill_resolver = DeterministicSkillResolver(DEMO_SKILL_DEFINITIONS)
    repository = JsonKnowledgeRepository(knowledge_file)
    recording_retriever = RecordingKnowledgeRetriever(
        DeterministicKnowledgeRetriever(repository)
    )
    provider_backend = raw_provider or RestaurantAirconFakeAnalysisProvider()
    reliable_provider = ReliableAnalysisProvider(
        provider_backend,
        policy=reliability_policy or ReliabilityPolicy(),
        context_builder=ContextBuilder(recording_retriever),
    )
    return RestaurantAirconGoldenPath(
        runtime=runtime,
        input_adapter=input_adapter,
        skill_resolver=skill_resolver,
        provider=reliable_provider,
        recording_retriever=recording_retriever,
    )
