from __future__ import annotations

import hashlib
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from creative_hub.db.models import (
    EvidenceClaimRecord,
    EvidencePackRevisionRecord,
    ProjectRecord,
    ResearchJobRecord,
    ResonanceDirectionRevisionRecord,
    SearchQueryRecord,
    SourceDocumentRevisionRecord,
    TrialScriptRevisionRecord,
)
from creative_hub.models import OrchestrationBase
from creative_hub.shidu.providers import (
    ReaderSecurityAttestation,
    ReaderSecurityCapabilities,
    SearchHit,
    SourceDocumentPayload,
)
from creative_hub.shidu.query_planner import QueryPlanner
from creative_hub.shidu.repository import ShiduRepository
from creative_hub.shidu.research_service import AICompletedContent
from creative_hub.shidu.research_worker import ShiduResearchWorker
import creative_hub.shidu.research_worker as research_worker_module
from creative_hub.shidu.schemas import CreateBook, CreateResearchJob
from creative_hub.shidu.trial_script_compiler import DeterministicTrialScriptTransport
from creative_hub.shidu.url_security import ReaderURLGuard


class SearchFixture:
    def search(self, _request):
        return (
            SearchHit(
                title="Lincoln archive",
                url="https://history.example.edu/lincoln",
                snippet="not evidence",
            ),
            SearchHit(
                title="Lincoln review",
                url="https://bookreview.example.org/lincoln",
                snippet="not evidence",
            ),
            SearchHit(
                title="Lincoln readers",
                url="https://archive.example.net/lincoln",
                snippet="not evidence",
            ),
        )


class NoHitSearch:
    def search(self, _request):
        return ()


class ReaderFixture:
    security_capabilities = ReaderSecurityCapabilities.secure_default()
    _content = {
        "history.example.edu": "主人公推开门并面对眼前的选择。记录关键词：冷雨、钥匙、门外、推开门。史料页甲。",
        "bookreview.example.org": "评论者感到克制而紧张，这种情绪来自人物的选择。评论页乙。",
        "archive.example.net": "这段经历适合关注人物在压力下如何作出选择的读者。读者页丙。",
    }

    def read(self, request):
        host = request.url.split("/", 3)[2]
        address = request.approved_resolved_addresses[0]
        return SourceDocumentPayload(
            url=request.url,
            title=host,
            content=self._content[host],
            content_digest=hashlib.sha256(
                self._content[host].encode("utf-8")
            ).hexdigest(),
            content_type="text/plain",
            security=ReaderSecurityAttestation(
                resolved_address=address,
                redirect_chain=(request.url,),
                redirect_policy="forbid",
                prefetch_policy="connect-approved-address-only",
            ),
        )


class ExtractionFixture:
    def extract(self, request):
        content = request.document_bytes.decode("utf-8")
        if "冷雨" in content:
            claim_type = "plot_node"
            excerpt = "主人公推开门"
            normalized = "主人公推开门并面对眼前必须承担代价的选择"
        elif "评论者" in content:
            claim_type = "emotional_reaction"
            excerpt = "评论者感到克制而紧张"
            normalized = "读者会感到克制而紧张"
        else:
            claim_type = "reader_fit"
            excerpt = "适合关注人物在压力下如何作出选择的读者"
            normalized = excerpt
        start = content.index(excerpt)
        return {
            "claims": [
                {
                    "claim_type": claim_type,
                    "normalized_claim": normalized,
                    "source_span_start": start,
                    "source_span_end": start + len(excerpt),
                    "excerpt_digest": hashlib.sha256(excerpt.encode()).hexdigest(),
                    "is_direct_quote": False,
                    "spoiler_level": "light",
                    "confidence": 0.9,
                    "conflict_key": None,
                    "conflict_severity": None,
                }
            ]
        }


class BrokenExtraction:
    def extract(self, _request):
        raise RuntimeError("provider response must not escape logs")


class AICompletionFixture:
    model_id = "fixture-ai-completion-v1"

    def complete(self, *, book, sources):
        assert book.title
        assert sources == ()
        return AICompletedContent(
            content=(
                "情节梗概：主人公在冷雨里推门进入安静的房间，雨水沿袖口滴在地板上；"
                "他把钥匙摊在掌心，听见门外脚步逼近和越来越急的呼吸，随后把钥匙放上桌面并推开门；"
                "门轴响起，眼前的关系发生变化，他最终停在门槛上，握紧发冷的手。"
                "情绪脉络：叙事从迟疑和失落逐步转向承担，保留人物处境中的复杂性。"
                "适读提示：适合关注人物选择、命运变化和内在成长的读者谨慎试读。"
                "不确定性说明：以上为 AI 基于书目信息补全的梗概，不是原文，也可能存在偏差。"
            ),
            model_id=self.model_id,
        )


class PlotOnlyExtraction:
    def extract(self, request):
        content = request.document_bytes.decode("utf-8")
        excerpt = content[:8]
        return {
            "claims": [
                {
                    "claim_type": "plot_node",
                    "normalized_claim": "人物面对眼前的选择",
                    "source_span_start": 0,
                    "source_span_end": len(excerpt),
                    "excerpt_digest": hashlib.sha256(excerpt.encode()).hexdigest(),
                    "is_direct_quote": False,
                    "spoiler_level": "light",
                    "confidence": 0.7,
                    "conflict_key": None,
                    "conflict_severity": None,
                }
            ]
        }


class NoConflictFixture:
    def adjudicate(self, _request):
        return {"decisions": []}


@pytest.fixture()
def database():
    engine = create_engine(
        "sqlite+pysqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def attach(connection, _record):
        connection.execute("ATTACH DATABASE ':memory:' AS orchestration")
        connection.execute("PRAGMA foreign_keys = ON")

    OrchestrationBase.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    project_id = uuid4()
    with sessions() as session, session.begin():
        session.add(
            ProjectRecord(
                id=project_id,
                project_key=f"research-worker-{project_id}",
                title="Research worker",
                config={},
                config_digest="0" * 64,
            )
        )
        repository = ShiduRepository(session)
        book = repository.create_or_reuse_book(
            CreateBook(
                project_id=project_id,
                title="The Life of Abraham Lincoln",
                author="Henry Ketcham",
                language="en",
                edition="",
                translator="",
                command_key="book:lincoln",
            )
        ).value
        job = repository.create_or_reuse_research_job(
            CreateResearchJob(
                project_id=project_id,
                book_id=book.id,
                provider_version="test-provider-v1",
                command_key="research:lincoln",
            )
        ).value
    yield sessions, project_id, job.id
    engine.dispose()


def build_worker(
    database,
    extraction,
    *,
    search_provider=None,
    ai_completion_provider=None,
):
    sessions, project_id, _job_id = database
    return ShiduResearchWorker(
        session_factory=sessions,
        project_id=project_id,
        search_provider=search_provider or SearchFixture(),
        reader_provider=ReaderFixture(),
        evidence_transport=extraction,
        conflict_transport=NoConflictFixture(),
        evidence_model_id="fixture-evidence-v1",
        trial_transport=DeterministicTrialScriptTransport(),
        trial_model_version="fixture-trial-v1",
        query_planner=QueryPlanner(
            lambda _book: {
                "queries": ["Lincoln biography review"],
                "evidence_gaps": [],
            }
        ),
        url_guard=ReaderURLGuard(resolver=lambda _host: ("8.8.8.8",)),
        ai_completion_provider=ai_completion_provider,
    )


def test_worker_atomically_publishes_research_directions_and_preview_scripts(database):
    sessions, _project_id, job_id = database
    worker = build_worker(database, ExtractionFixture())

    tick = worker.run_once()

    assert tick.status == "completed"
    assert tick.job_id == job_id
    assert tick.source_count == 3
    assert tick.evidence_count == 3
    assert tick.direction_count == 1
    assert tick.script_count == 1
    with sessions() as session:
        assert session.get(ResearchJobRecord, job_id).status == "ready"
        assert session.scalar(select(func.count()).select_from(SourceDocumentRevisionRecord)) == 3
        assert session.scalar(select(func.count()).select_from(EvidenceClaimRecord)) == 3
        pack = session.scalar(select(EvidencePackRevisionRecord))
        assert pack is not None and pack.publishable
        assert session.scalar(select(func.count()).select_from(ResonanceDirectionRevisionRecord)) == 1
        assert session.scalar(select(func.count()).select_from(TrialScriptRevisionRecord)) == 1

    assert worker.run_once().status == "idle"


def test_model_failure_rolls_back_the_entire_ready_projection(database):
    sessions, _project_id, job_id = database
    worker = build_worker(database, BrokenExtraction())

    tick = worker.run_once()

    assert tick.status == "retryable_failed"
    assert tick.error_code == "EvidenceExtractionError"
    with sessions() as session:
        assert session.get(ResearchJobRecord, job_id).status == "retryable_failed"
        assert session.scalar(select(func.count()).select_from(SearchQueryRecord)) == 0
        assert session.scalar(select(func.count()).select_from(SourceDocumentRevisionRecord)) == 0
        assert session.scalar(select(func.count()).select_from(EvidencePackRevisionRecord)) == 0
    assert worker.run_once().status == "idle"


def test_evidence_gap_becomes_terminal_insufficient_without_paid_retry(database):
    sessions, _project_id, job_id = database
    worker = build_worker(database, PlotOnlyExtraction())

    tick = worker.run_once()

    assert tick.status == "insufficient"
    assert tick.error_code == "ResearchPipelineError"
    with sessions() as session:
        assert session.get(ResearchJobRecord, job_id).status == "insufficient"
        assert session.scalar(select(func.count()).select_from(EvidenceClaimRecord)) == 0
    assert worker.run_once().status == "idle"


def test_ai_completion_uses_fixed_sections_for_complete_downstream_projection(
    database,
) -> None:
    sessions, _project_id, job_id = database
    worker = build_worker(
        database,
        BrokenExtraction(),
        search_provider=NoHitSearch(),
        ai_completion_provider=AICompletionFixture(),
    )

    tick = worker.run_once()

    assert tick.status == "completed"
    assert tick.job_id == job_id
    assert tick.source_count == 1
    assert tick.evidence_count == 3
    assert tick.direction_count == 1
    assert tick.script_count == 1
    with sessions() as session:
        source = session.scalar(select(SourceDocumentRevisionRecord))
        assert source is not None and source.source_type == "ai_generated"
        claims = session.scalars(select(EvidenceClaimRecord)).all()
        assert {claim.claim_type for claim in claims} == {
            "plot_node",
            "emotional_reaction",
            "reader_fit",
        }
        assert all(not claim.is_direct_quote for claim in claims)
        pack = session.scalar(select(EvidencePackRevisionRecord))
        assert pack is not None
        assert pack.coverage["content_mode"] == "ai_completed"
        assert pack.coverage["ai_generated_source_count"] == 1


def test_search_query_contract_matches_the_real_gateway_limit():
    planner = QueryPlanner(
        lambda _book: {"queries": ["x" * 71], "evidence_gaps": []}
    )

    with pytest.raises(ValueError, match="invalid item"):
        planner.plan(object())


def test_default_query_plan_requests_independent_reference_sources():
    plan = QueryPlanner().plan(
        SimpleNamespace(
            title="The Life of Abraham Lincoln",
            author="Henry Ketcham",
        )
    )

    assert any("gutenberg.org" in query for query in plan.queries)
    assert any("archive.org" in query for query in plan.queries)
    assert any("site:.edu" in query for query in plan.queries)
    assert all(len(query) <= 70 for query in plan.queries)

def test_production_research_worker_wires_a_provider_trace_sink(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _StopAfterFailoverWiring(RuntimeError):
        pass

    captured: dict[str, object] = {}

    def capture_failover(**kwargs: object) -> object:
        captured.update(kwargs)
        raise _StopAfterFailoverWiring

    monkeypatch.setenv("SHIDU_PROJECT_ID", "11111111-1111-4111-8111-111111111111")
    monkeypatch.setenv("SHIDU_ZHIPU_API_KEY_FILE", "zhipu.secret")
    monkeypatch.setenv("SHIDU_QWEN_API_KEY_FILE", "qwen.secret")
    monkeypatch.setattr(research_worker_module, "_read_secret", lambda _path: "secret")
    monkeypatch.setattr(
        research_worker_module,
        "GlmStructuredModelClient",
        lambda **_kwargs: object(),
    )
    monkeypatch.setattr(
        research_worker_module,
        "QwenStructuredModelClient",
        lambda **_kwargs: object(),
    )
    monkeypatch.setattr(
        research_worker_module,
        "RateLimitFailoverStructuredModelClient",
        capture_failover,
    )

    with pytest.raises(_StopAfterFailoverWiring):
        research_worker_module.build_production_worker()

    assert captured["trace_sink"] is not None
    assert callable(getattr(captured["trace_sink"], "record", None))
