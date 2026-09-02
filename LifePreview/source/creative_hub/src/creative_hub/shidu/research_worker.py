"""Durable single-transaction worker for queued Shidu research jobs."""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from uuid import UUID

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from creative_hub.db.models import ResearchJobRecord
from creative_hub.runtime_bootstrap import database_url
from creative_hub.shidu.evidence_extractor import (
    EvidenceExtractionTransport,
    EvidenceExtractor,
)
from creative_hub.shidu.evidence_validator import (
    ConflictAdjudicationTransport,
    ConflictAdjudicator,
    EvidencePackCompiler,
    EvidenceValidator,
)
from creative_hub.shidu.glm_research_transport import (
    GLM_RESEARCH_MODEL,
    GlmConflictAdjudicationTransport,
    GlmAICompletionTransport,
    GlmEvidenceExtractionTransport,
    GlmResearchTransportError,
    GlmStructuredModelClient,
    GlmTrialScriptTransport,
)
from creative_hub.shidu.mcp_transport import HttpMCPTransport
from creative_hub.shidu.providers import (
    CodingPlanPageReaderMCPProvider,
    CodingPlanSearchMCPProvider,
    PageReaderProvider,
    SearchProvider,
)
from creative_hub.shidu.provider_trace import StructuredLoggingProviderTraceSink
from creative_hub.shidu.query_planner import QueryPlanner, QueryPlanningModel
from creative_hub.shidu.qwen_research_transport import (
    QwenStructuredModelClient,
    RateLimitFailoverStructuredModelClient,
)
from creative_hub.shidu.repository import ShiduRepository
from creative_hub.shidu.research_service import ResearchService
from creative_hub.shidu.resonance import ResonanceService
from creative_hub.shidu.safety_cards import BookSafetyCategory
from creative_hub.shidu.trial_methodology import TrialMethodologyService
from creative_hub.shidu.trial_script_compiler import (
    AICompletedTrialScriptTransport,
    TrialScriptCompiler,
    TrialScriptSafetyBlocked,
    TrialScriptTransport,
)
from creative_hub.shidu.trial_script_validator import TrialScriptError
from creative_hub.shidu.url_security import ReaderURLGuard
from creative_hub.shidu.schemas import EvidenceClaimDraft, SourceDocumentRevision


LOGGER = logging.getLogger("creative_hub.shidu.research_worker")
_ACTIVE_RESEARCH_TYPES = frozenset(
    {"plot_node", "emotional_reaction", "reader_fit"}
)
_AI_COMPLETION_SECTIONS = (
    ("情节梗概：", "情绪脉络：", "plot_node", "light", "AI 补全情节概述为"),
    (
        "情绪脉络：",
        "适读提示：",
        "emotional_reaction",
        "light",
        "AI 补全情绪脉络为",
    ),
    ("适读提示：", "不确定性说明：", "reader_fit", "none", "AI 补全适读提示为"),
)


def _ai_completion_claims(
    source: SourceDocumentRevision,
) -> tuple[EvidenceClaimDraft, ...]:
    """Turn the fixed AI completion schema into low-confidence local claims."""

    if source.source_type != "ai_generated":
        return ()
    drafts: list[EvidenceClaimDraft] = []
    for (
        marker,
        following,
        claim_type,
        spoiler_level,
        disclosure_prefix,
    ) in _AI_COMPLETION_SECTIONS:
        marker_start = source.content.find(marker)
        following_start = source.content.find(following)
        if marker_start < 0 or following_start <= marker_start + len(marker):
            continue
        raw_start = marker_start + len(marker)
        raw_excerpt = source.content[raw_start:following_start]
        excerpt = raw_excerpt.strip()
        if not excerpt:
            continue
        start = source.content.find(excerpt, raw_start, following_start)
        excerpt = excerpt[:900]
        end = start + len(excerpt)
        normalized = f"{disclosure_prefix}：{' '.join(excerpt.split())}"
        if start < 0 or not normalized:
            continue
        drafts.append(
            EvidenceClaimDraft(
                project_id=source.project_id,
                research_job_id=source.research_job_id,
                source_document_revision_id=source.id,
                claim_type=claim_type,
                normalized_claim=normalized,
                source_span_start=start,
                source_span_end=end,
                excerpt_digest=hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
                is_direct_quote=False,
                spoiler_level=spoiler_level,
                confidence=0.35,
                conflict_key=None,
                conflict_severity=None,
            )
        )
    return tuple(drafts)


class ResearchPipelineError(RuntimeError):
    """A ready research job could not produce a complete public projection."""

    def __init__(self, message: str, *, terminal_status: str) -> None:
        if terminal_status not in {"insufficient", "retryable_failed", "failed"}:
            raise ValueError("research pipeline terminal status is invalid")
        super().__init__(message)
        self.terminal_status = terminal_status


@dataclass(frozen=True, slots=True)
class ResearchWorkerTick:
    status: str
    job_id: UUID | None = None
    source_count: int = 0
    evidence_count: int = 0
    direction_count: int = 0
    script_count: int = 0
    error_code: str | None = None


SessionFactory = Callable[[], Session]


class ShiduResearchWorker:
    """Claim one queued row and publish the complete durable projection atomically."""

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        project_id: UUID,
        search_provider: SearchProvider,
        reader_provider: PageReaderProvider,
        evidence_transport: EvidenceExtractionTransport,
        conflict_transport: ConflictAdjudicationTransport,
        evidence_model_id: str,
        trial_transport: TrialScriptTransport,
        trial_model_version: str,
        query_planner: QueryPlanner | None = None,
        url_guard: ReaderURLGuard | None = None,
        book_safety_category: BookSafetyCategory | str = BookSafetyCategory.FICTION,
        ai_completion_provider=None,
    ) -> None:
        if not isinstance(project_id, UUID):
            raise ValueError("project_id must be a UUID")
        if not evidence_model_id.strip() or len(evidence_model_id) > 160:
            raise ValueError("evidence_model_id is invalid")
        if not trial_model_version.strip() or len(trial_model_version) > 160:
            raise ValueError("trial_model_version is invalid")
        self._sessions = session_factory
        self._project_id = project_id
        self._search = search_provider
        self._reader = reader_provider
        self._evidence_transport = evidence_transport
        self._conflict_transport = conflict_transport
        self._evidence_model_id = evidence_model_id
        self._trial_transport = trial_transport
        self._trial_model_version = trial_model_version
        self._planner = query_planner or QueryPlanner()
        self._url_guard = url_guard or ReaderURLGuard()
        self._book_safety_category = BookSafetyCategory(book_safety_category)
        self._ai_completion_provider = ai_completion_provider

    def _claim_next(self, session: Session) -> UUID | None:
        return session.scalar(
            select(ResearchJobRecord.id)
            .where(
                ResearchJobRecord.project_id == self._project_id,
                ResearchJobRecord.status == "queued",
            )
            .order_by(ResearchJobRecord.created_at, ResearchJobRecord.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )

    def _mark_queued_terminal(self, job_id: UUID, status: str) -> str:
        """Record a terminal projection after the paid transaction rolled back."""

        with self._sessions() as session, session.begin():
            repository = ShiduRepository(session)
            job = repository.get_research_job(job_id)
            if job.status != "queued":
                return job.status
            current = "queued"
            for following in (
                "resolving",
                "searching",
                "reading",
                "extracting",
                "synthesizing",
                status,
            ):
                repository.transition_research_job(job_id, current, following)
                current = following
            return current

    def run_once(self) -> ResearchWorkerTick:
        claimed_job_id: UUID | None = None
        try:
            with self._sessions() as session, session.begin():
                claimed_job_id = self._claim_next(session)
                if claimed_job_id is None:
                    return ResearchWorkerTick(status="idle")
                repository = ShiduRepository(session)
                result = ResearchService(
                    repository=repository,
                    planner=self._planner,
                    search_provider=self._search,
                    reader_provider=self._reader,
                    url_guard=self._url_guard,
                    minimum_independent_sources=3,
                    ai_completion_provider=self._ai_completion_provider,
                ).run(claimed_job_id)
                if result.status != "ready":
                    return ResearchWorkerTick(
                        status=result.status,
                        job_id=claimed_job_id,
                        source_count=result.source_count,
                    )

                validator = EvidenceValidator(repository)
                extractor = EvidenceExtractor(
                    repository=repository,
                    transport=self._evidence_transport,
                    model_id=self._evidence_model_id,
                )
                for source in result.sources:
                    drafts = (
                        _ai_completion_claims(source)
                        if source.source_type == "ai_generated"
                        else extractor.extract(source.id)
                    )
                    for draft in drafts:
                        validator.validate(
                            draft,
                            command_key=(
                                f"ai-evidence:{source.id}:{draft.claim_type}"
                                if source.source_type == "ai_generated"
                                else None
                            ),
                        )
                claims = repository.list_evidence_claims(claimed_job_id)
                present_types = {item.claim_type for item in claims}
                if not _ACTIVE_RESEARCH_TYPES.issubset(present_types):
                    raise ResearchPipelineError(
                        "required_claim_type_missing",
                        terminal_status="insufficient",
                    )

                adjudicator = ConflictAdjudicator(
                    repository=repository,
                    transport=self._conflict_transport,
                    model_id=self._evidence_model_id,
                )
                pack = EvidencePackCompiler(
                    repository,
                    project_id=self._project_id,
                    adjudicator=adjudicator,
                ).freeze(claimed_job_id)
                if not pack.publishable:
                    reasons = ",".join(pack.insufficiency_reason_codes) or "unknown"
                    raise ResearchPipelineError(
                        f"evidence_pack_not_publishable:{reasons}",
                        terminal_status="insufficient",
                    )
                resonance = ResonanceService(repository=repository)
                directions = resonance.publish(pack.id)
                if not directions:
                    gaps = ",".join(resonance.last_gap_codes) or "no_direction"
                    raise ResearchPipelineError(
                        f"direction_not_publishable:{gaps}",
                        terminal_status="insufficient",
                    )

                job = repository.get_research_job(claimed_job_id)
                methodology = TrialMethodologyService(repository).freeze(
                    self._project_id
                )
                ai_completed_pack = (
                    pack.coverage.get("content_mode") == "ai_completed"
                    and int(
                        pack.coverage.get("ai_generated_source_count", 0)
                    )
                    > 0
                )
                compiler = TrialScriptCompiler(
                    repository=repository,
                    transport=(
                        AICompletedTrialScriptTransport()
                        if ai_completed_pack
                        else self._trial_transport
                    ),
                    model_version=(
                        "ai-completion-deterministic-v1"
                        if ai_completed_pack
                        else self._trial_model_version
                    ),
                )
                scripts = tuple(
                    compiler.compile(
                        project_id=self._project_id,
                        book_id=job.book_id,
                        direction_revision_id=direction.id,
                        methodology_revision_id=methodology.id,
                        command_key=f"research:{claimed_job_id}:trial:{direction.digest}",
                        book_category=self._book_safety_category,
                    )
                    for direction in directions
                )
                return ResearchWorkerTick(
                    status="completed",
                    job_id=claimed_job_id,
                    source_count=result.source_count,
                    evidence_count=len(claims),
                    direction_count=len(directions),
                    script_count=len(scripts),
                )
        except Exception as error:
            # Never log provider text, source URLs/content, or credentials.
            error_code = type(error).__name__
            if isinstance(
                error,
                (
                    ResearchPipelineError,
                    GlmResearchTransportError,
                    TrialScriptError,
                    TrialScriptSafetyBlocked,
                ),
            ):
                LOGGER.error(
                    "research pipeline transaction rolled back job=%s "
                    "error_code=%s pipeline_reason=%s",
                    claimed_job_id,
                    error_code,
                    str(error),
                )
            else:
                LOGGER.error(
                    "research pipeline transaction rolled back job=%s error_code=%s",
                    claimed_job_id,
                    error_code,
                )
            terminal_status = (
                error.terminal_status
                if isinstance(error, ResearchPipelineError)
                else (
                    "insufficient"
                    if isinstance(error, TrialScriptSafetyBlocked)
                    else "retryable_failed"
                )
            )
            if claimed_job_id is not None:
                try:
                    terminal_status = self._mark_queued_terminal(
                        claimed_job_id, terminal_status
                    )
                except Exception:
                    LOGGER.error(
                        "research terminal projection failed job=%s error_code=%s",
                        claimed_job_id,
                        error_code,
                    )
                    terminal_status = "failed"
            else:
                terminal_status = "failed"
            return ResearchWorkerTick(
                status=terminal_status,
                job_id=claimed_job_id,
                error_code=error_code,
            )

    def healthcheck(self) -> None:
        with self._sessions() as session:
            if session.execute(select(1)).scalar_one() != 1:
                raise RuntimeError("research worker database healthcheck failed")

    def run_forever(self, *, poll_interval_seconds: float) -> None:
        if not 0.1 <= poll_interval_seconds <= 60.0:
            raise ValueError("poll interval is invalid")
        failure_delay = poll_interval_seconds
        while True:
            tick = self.run_once()
            if tick.status == "failed":
                failure_delay = min(max(failure_delay * 2, 1.0), 30.0)
                time.sleep(failure_delay)
            else:
                failure_delay = poll_interval_seconds
                if tick.status == "idle":
                    time.sleep(poll_interval_seconds)


def _read_secret(path: str) -> str:
    try:
        value = Path(path).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        raise RuntimeError("research worker configuration is invalid") from None
    if (
        not value
        or len(value) > 4_096
        or any(ord(character) < 33 or ord(character) == 127 for character in value)
    ):
        raise RuntimeError("research worker configuration is invalid")
    return value


def build_production_worker() -> ShiduResearchWorker:
    try:
        project_id = UUID(os.environ["SHIDU_PROJECT_ID"])
        glm_api_key = _read_secret(os.environ["SHIDU_ZHIPU_API_KEY_FILE"])
        qwen_api_key = _read_secret(os.environ["SHIDU_QWEN_API_KEY_FILE"])
        category = BookSafetyCategory(
            os.getenv("SHIDU_BOOK_SAFETY_CATEGORY", BookSafetyCategory.FICTION.value)
        )
    except (KeyError, ValueError):
        raise RuntimeError("research worker configuration is invalid") from None
    model_id = os.getenv("SHIDU_RESEARCH_MODEL", GLM_RESEARCH_MODEL)
    primary_model = GlmStructuredModelClient(
        api_key=glm_api_key,
        model_id=model_id,
    )
    fallback_model = QwenStructuredModelClient(api_key=qwen_api_key)
    model = RateLimitFailoverStructuredModelClient(
        primary=primary_model,
        fallback=fallback_model,
        trace_sink=StructuredLoggingProviderTraceSink(LOGGER),
    )
    engine = create_engine(
        os.getenv("CREATIVE_ORCHESTRATION_DATABASE_URL")
        or database_url("CREATIVE_ORCHESTRATION"),
        pool_pre_ping=True,
    )
    sessions = sessionmaker(engine, expire_on_commit=False)
    search = CodingPlanSearchMCPProvider(
        HttpMCPTransport(
            os.getenv(
                "SHIDU_SEARCH_MCP_ENDPOINT",
                "http://shidu-search-mcp:18110/invoke",
            )
        )
    )
    reader = CodingPlanPageReaderMCPProvider(
        HttpMCPTransport(
            os.getenv(
                "SHIDU_READER_MCP_ENDPOINT",
                "http://shidu-reader-mcp:18111/invoke",
            )
        )
    )
    return ShiduResearchWorker(
        session_factory=sessions,
        project_id=project_id,
        search_provider=search,
        reader_provider=reader,
        evidence_transport=GlmEvidenceExtractionTransport(model),
        conflict_transport=GlmConflictAdjudicationTransport(model),
        evidence_model_id=model.model_id,
        trial_transport=GlmTrialScriptTransport(model),
        trial_model_version=f"structured:{model.model_id}",
        book_safety_category=category,
        ai_completion_provider=GlmAICompletionTransport(model),
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Consume queued Shidu research jobs atomically"
    )
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--healthcheck", action="store_true")
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=float(os.getenv("SHIDU_RESEARCH_POLL_INTERVAL_SECONDS", "2")),
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    worker = build_production_worker()
    if args.healthcheck:
        worker.healthcheck()
    elif args.once:
        tick = worker.run_once()
        if tick.status == "failed":
            raise SystemExit(1)
    else:
        worker.run_forever(poll_interval_seconds=args.poll_interval)


__all__ = [
    "ResearchPipelineError",
    "ResearchWorkerTick",
    "ShiduResearchWorker",
    "build_production_worker",
    "main",
]


if __name__ == "__main__":
    main()
