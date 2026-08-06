from __future__ import annotations

import hashlib
import math
from dataclasses import replace
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from creative_hub.db.models import (
    BookRecord,
    ProjectRecord,
)
from creative_hub.models import OrchestrationBase
from creative_hub.shidu.evidence_validator import (
    ConflictAdjudicator,
    EvidencePackCompiler,
    EvidenceValidator,
)
from creative_hub.shidu.repository import (
    EvidencePackNotPublishable,
    IdempotencyConflict,
    ShiduRepository,
)
from creative_hub.shidu.resonance import (
    ClusterProposal,
    DirectionPenalties,
    DirectionSignals,
    GroundedText,
    ResonancePolicy,
    ResonanceScorer,
    ResonanceService,
)
from creative_hub.shidu.resonance_validator import (
    DIRECTION_SCORE_VERSION,
    ResonanceValidationError,
    parse_cluster_proposals,
)
from creative_hub.shidu.schemas import (
    CreateResearchJob,
    DirectionDraft,
    EvidenceClaimDraft,
    PublishDirections,
    StoreSourceDocument,
)


PROJECT_ID = UUID("11111111-1111-4111-8111-111111111111")
OTHER_PROJECT_ID = UUID("22222222-2222-4222-8222-222222222222")


class FakeConflictTransport:
    def __init__(self, payload: object | None = None) -> None:
        self.payload = payload if payload is not None else {"decisions": []}

    def adjudicate(self, _request: object) -> object:
        return self.payload


class FakeClusterTransport:
    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.requests: list[object] = []
        self.raise_on_call = False

    def propose(self, request: object) -> object:
        self.requests.append(request)
        if self.raise_on_call:
            raise AssertionError("replay must not consume model quota")
        return self.payload


@pytest.fixture()
def session() -> Session:
    engine = create_engine(
        "sqlite+pysqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def attach(connection, _record) -> None:
        connection.execute("ATTACH DATABASE ':memory:' AS orchestration")
        connection.execute("PRAGMA foreign_keys = ON")

    OrchestrationBase.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as value:
        for project_id in (PROJECT_ID, OTHER_PROJECT_ID):
            value.add(
                ProjectRecord(
                    id=project_id,
                    project_key=f"project-{project_id}",
                    title=f"Project {project_id}",
                    config={},
                    config_digest="0" * 64,
                )
            )
        value.commit()
        yield value
    engine.dispose()


def _job(session: Session, repository: ShiduRepository, suffix: str = "1"):
    book_id = uuid4()
    session.add(
        BookRecord(
            id=book_id,
            project_id=PROJECT_ID,
            identity_digest=hashlib.sha256(f"book-{suffix}".encode()).hexdigest(),
            title="活着",
            author="余华",
            language="zh-CN",
            edition="default",
            translator="",
            command_idempotency_key=f"book:{suffix}",
        )
    )
    session.flush()
    return repository.create_or_reuse_research_job(
        CreateResearchJob(
            project_id=PROJECT_ID,
            book_id=book_id,
            provider_version="research@v1",
            command_key=f"research:{suffix}",
        )
    ).value


def _source(
    repository: ShiduRepository,
    job,
    *,
    suffix: str,
    host: str,
    source_type: str,
    interaction_signal: float | None = None,
):
    content = "门外下着冷雨，我握住门把手，还是推开了门。"
    return repository.store_source_revision(
        StoreSourceDocument(
            project_id=PROJECT_ID,
            research_job_id=job.id,
            canonical_url=f"https://{host}/reviews/{suffix}",
            content=content,
            command_key=f"source:{suffix}",
            source_type=source_type,
            interaction_metrics=(
                {"likes": round(interaction_signal * 1000)}
                if interaction_signal is not None
                else None
            ),
        )
    )


def _claim(
    repository: ShiduRepository,
    source,
    *,
    suffix: str,
    claim_type: str,
    text: str,
    spoiler_level: str = "light",
    is_direct_quote: bool = False,
    conflict_key: str | None = None,
    conflict_severity: str | None = None,
):
    excerpt = "我握住门把手"
    start = source.content.index(excerpt)
    draft = EvidenceClaimDraft(
        project_id=PROJECT_ID,
        research_job_id=source.research_job_id,
        source_document_revision_id=source.id,
        claim_type=claim_type,
        normalized_claim=text,
        source_span_start=start,
        source_span_end=start + len(excerpt),
        excerpt_digest=hashlib.sha256(excerpt.encode()).hexdigest(),
        is_direct_quote=is_direct_quote,
        spoiler_level=spoiler_level,
        confidence=0.8,
        conflict_key=conflict_key,
        conflict_severity=conflict_severity,
    )
    return EvidenceValidator(repository).validate(
        draft, command_key=f"claim:{suffix}"
    )


def _freeze(
    repository: ShiduRepository,
    job,
    claims,
    *,
    conflict_payload: object | None = None,
):
    adjudicator = ConflictAdjudicator(
        repository=repository,
        transport=FakeConflictTransport(conflict_payload),
        model_id="conflict-model-v1",
    )
    return EvidencePackCompiler(
        repository, project_id=PROJECT_ID, adjudicator=adjudicator
    ).freeze(job.id, evidence_ids=tuple(item.id for item in claims))


def _seed_publishable_pack(
    session: Session,
    *,
    hosts: tuple[str, ...] = ("a.example", "b.example", "c.example"),
    source_types: tuple[str, ...] = ("publisher", "media", "publisher"),
    interaction_signal: float | None = None,
    cluster_count: int = 1,
    unresolved_critical: bool = False,
):
    repository = ShiduRepository(session)
    job = _job(session, repository)
    sources = tuple(
        _source(
            repository,
            job,
            suffix=str(index),
            host=host,
            source_type=source_types[index - 1],
            interaction_signal=interaction_signal,
        )
        for index, host in enumerate(hosts, start=1)
    )
    claims = tuple(
        claim
        for index in range(cluster_count)
        for claim in (
            _claim(
                repository,
                sources[0],
                suffix=f"plot:{index}",
                claim_type="plot_node",
                text=f"主人公在冷雨里决定推开第{index}扇门",
            ),
            _claim(
                repository,
                sources[1],
                suffix=f"emotion:{index}",
                claim_type="emotional_reaction",
                text=f"读者对第{index}次选择感到害怕又决绝",
            ),
            _claim(
                repository,
                sources[2],
                suffix=f"fit:{index}",
                claim_type="reader_fit",
                text=f"第{index}个方向适合喜欢克制成长故事的读者",
            ),
        )
    )
    conflict_payload = None
    if unresolved_critical:
        conflict_payload = {
            "decisions": [
                {
                    "member_evidence_ids": [
                        str(claims[0].id),
                        str(claims[1].id),
                    ],
                    "severity": "critical",
                    "status": "unresolved",
                }
            ]
        }
    return (
        repository,
        _freeze(
            repository,
            job,
            claims,
            conflict_payload=conflict_payload,
        ),
        claims,
    )


def _proposal(claims, *, key: str = "door", **updates) -> ClusterProposal:
    evidence_ids = tuple(item.id for item in claims)
    values = {
        "cluster_key": key,
        "evidence_ids": evidence_ids,
        "title": "推开那扇门之前",
        "factual_statements": (
            GroundedText("主人公在冷雨里决定离开", (claims[0].id,)),
        ),
        "first_person_entry": GroundedText(
            "我听见冷雨敲门，手还握着门把手。", (claims[0].id,)
        ),
        "perceived_detail": GroundedText(
            "冷雨敲门", (claims[0].id,)
        ),
        "fit_for": (
            GroundedText("喜欢克制成长故事的读者", (claims[2].id,)),
        ),
        "not_fit_for": (
            GroundedText("期待轻松喜剧的读者", (claims[2].id,)),
        ),
        "spoiler_level": "light",
    }
    values.update(updates)
    return ClusterProposal(**values)


def _service(repository, proposal, **updates) -> ResonanceService:
    values = {
        "repository": repository,
        "proposal_transport": FakeClusterTransport(
            {"clusters": [proposal.model_dump(mode="json")]}
        ),
        "model_version": "cluster-model-v1",
        "prompt_version": "resonance-prompt-v1",
    }
    values.update(updates)
    return ResonanceService(**values)


def test_score_uses_exact_frozen_formula_and_missing_interaction_renormalizes() -> None:
    scorer = ResonanceScorer()
    signals = DirectionSignals(
        cross_source_repetition=0.8,
        independent_source_diversity=0.7,
        emotion_specificity=0.6,
        experiential_cinematic_fit=0.5,
        interaction_signal=0.4,
        source_reliability=0.9,
    )
    penalties = DirectionPenalties(
        spoiler=0.01, copyright=0.02, conflict=0.03
    )
    expected = (
        0.30 * 0.8
        + 0.20 * 0.7
        + 0.20 * 0.6
        + 0.15 * 0.5
        + 0.10 * 0.4
        + 0.05 * 0.9
        - 0.06
    )
    assert scorer.score(signals, penalties) == pytest.approx(expected)

    missing = replace(signals, interaction_signal=None)
    expected_missing = (
        0.30 * 0.8
        + 0.20 * 0.7
        + 0.20 * 0.6
        + 0.15 * 0.5
        + 0.05 * 0.9
    ) / 0.90 - 0.06
    assert scorer.score(missing, penalties) == pytest.approx(expected_missing)
    assert scorer.score(replace(signals, interaction_signal=0.0), penalties) != (
        scorer.score(missing, penalties)
    )


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf, -0.01, 1.01])
def test_score_rejects_nonfinite_and_out_of_range_signals(bad: float) -> None:
    with pytest.raises(ValueError, match="bounded finite"):
        ResonanceScorer().score(
            DirectionSignals(
                cross_source_repetition=bad,
                independent_source_diversity=0.5,
                emotion_specificity=0.5,
                experiential_cinematic_fit=0.5,
                interaction_signal=None,
                source_reliability=0.5,
            ),
            DirectionPenalties(),
        )


@pytest.mark.parametrize("bad", [math.nan, math.inf, -0.01, 1.01])
def test_score_rejects_nonfinite_and_out_of_range_penalties(bad: float) -> None:
    with pytest.raises(ValueError, match="bounded finite"):
        ResonanceScorer().score(
            DirectionSignals(0.5, 0.5, 0.5, 0.5, None, 0.5),
            DirectionPenalties(spoiler=bad),
        )


def test_model_boundary_rejects_extra_fields_and_tool_or_provider_selection() -> None:
    base = {
        "cluster_key": "door",
        "evidence_ids": [str(uuid4())],
        "title": "方向",
        "factual_statements": [],
        "first_person_entry": {"text": "我看见门", "evidence_ids": [str(uuid4())]},
        "perceived_detail": {"text": "门", "evidence_ids": [str(uuid4())]},
        "fit_for": [],
        "not_fit_for": [],
        "spoiler_level": "light",
    }
    for field in ("tool", "provider", "project_id", "research_job_id", "score"):
        with pytest.raises(ResonanceValidationError, match="structured output"):
            parse_cluster_proposals({"clusters": [{**base, field: "forged"}]})


def test_publish_rejects_same_registered_domain_and_missing_source_type(
    session: Session,
) -> None:
    repository, pack, claims = _seed_publishable_pack(
        session,
        hosts=("one.example.com", "two.example.com", "three.example.com"),
        source_types=("web", "web", "web"),
    )
    service = _service(repository, _proposal(claims))
    assert service.publish(pack.id) == ()
    assert service.last_gap_codes == (
        "independent_sources_insufficient",
        "source_types_insufficient",
    )


def test_ai_completed_pack_waives_external_diversity_for_selected_claims(
    session: Session,
) -> None:
    repository = ShiduRepository(session)
    job = _job(session, repository)
    external_sources = tuple(
        _source(
            repository,
            job,
            suffix=f"external:{index}",
            host="same.example",
            source_type="web",
        )
        for index in range(3)
    )
    generated_source = _source(
        repository,
        job,
        suffix="generated",
        host="completion.internal",
        source_type="ai_generated",
    )
    selected_claims = (
        _claim(
            repository,
            external_sources[0],
            suffix="ai-pack:plot",
            claim_type="plot_node",
            text="主人公在冷雨里决定离开",
        ),
        _claim(
            repository,
            external_sources[1],
            suffix="ai-pack:emotion",
            claim_type="emotional_reaction",
            text="读者对这次选择感到害怕又决绝",
        ),
        _claim(
            repository,
            external_sources[2],
            suffix="ai-pack:fit",
            claim_type="reader_fit",
            text="这个方向适合喜欢克制成长故事的读者",
        ),
    )
    generated_claim = _claim(
        repository,
        generated_source,
        suffix="ai-pack:generated",
        claim_type="plot_node",
        text="AI 补全内容保留不确定性",
    )
    pack = _freeze(
        repository,
        job,
        (*selected_claims, generated_claim),
    )

    assert pack.coverage["content_mode"] == "ai_completed"
    assert pack.coverage["ai_generated_source_count"] == 1
    service = _service(repository, _proposal(selected_claims))

    assert service.publish(pack.id)
    assert "independent_sources_insufficient" not in service.last_gap_codes
    assert "source_types_insufficient" not in service.last_gap_codes


def test_publish_rejects_missing_required_claim_type(session: Session) -> None:
    repository, pack, claims = _seed_publishable_pack(session)
    proposal = _proposal(
        claims,
        evidence_ids=(claims[0].id, claims[1].id),
        fit_for=(GroundedText("适合慢节奏读者", (claims[1].id,)),),
        not_fit_for=(GroundedText("不适合喜剧读者", (claims[1].id,)),),
    )
    service = _service(repository, proposal)
    assert service.publish(pack.id) == ()
    assert "reader_fit_missing" in service.last_gap_codes


@pytest.mark.parametrize(
    ("change", "gap"),
    [
        ({"first_person_entry": GroundedText("多年后我才知道结局", ())}, "pov_entry_not_grounded"),
        (
            {
                "first_person_entry": GroundedText(
                    "我看见一艘飞船落在门外。", ()
                ),
                "perceived_detail": GroundedText(
                    "飞船落在门外", ()
                ),
            },
            "pov_entry_not_grounded",
        ),
        ({"fit_for": ()}, "fit_for_missing"),
        ({"not_fit_for": ()}, "not_fit_for_missing"),
        ({"spoiler_level": "moderate"}, "spoiler_policy_exceeded"),
    ],
)
def test_direction_gate_omits_invalid_cluster_with_stable_gap(
    session: Session, change: dict, gap: str
) -> None:
    repository, pack, claims = _seed_publishable_pack(session)
    service = _service(repository, _proposal(claims, **change))
    assert service.publish(pack.id) == ()
    assert gap in service.last_gap_codes


def test_foreign_duplicate_and_unverified_quote_evidence_are_rejected(
    session: Session,
) -> None:
    repository, pack, claims = _seed_publishable_pack(session)
    foreign = uuid4()
    proposals = (
        _proposal(claims, evidence_ids=(*tuple(c.id for c in claims), foreign)),
        _proposal(claims, evidence_ids=(claims[0].id, claims[0].id)),
        _proposal(
            claims,
            factual_statements=(
                GroundedText('“原文很长而且未经验证”', (claims[0].id,), "verified_quote"),
            ),
        ),
        _proposal(
            claims,
            factual_statements=(
                GroundedText(
                    "门外下着冷雨，我握住门把手，还是推开了门。",
                    (claims[0].id,),
                ),
            ),
        ),
    )
    expected = (
        "foreign_evidence_id",
        "duplicate_evidence_id",
        "unverified_direct_quote",
        "copyright_risk",
    )
    for proposal, gap in zip(proposals, expected, strict=True):
        service = _service(repository, proposal)
        assert service.publish(pack.id) == ()
        assert gap in service.last_gap_codes


def test_publish_is_sorted_capped_not_padded_and_replay_uses_no_model_quota(
    session: Session,
) -> None:
    repository, pack, claims = _seed_publishable_pack(
        session, cluster_count=6
    )
    proposals = [
        _proposal(claims[index : index + 3], key=f"k{index // 3}")
        for index in range(0, len(claims), 3)
    ]
    transport = FakeClusterTransport(
        {"clusters": [item.model_dump(mode="json") for item in reversed(proposals)]}
    )
    service = ResonanceService(
        repository=repository,
        proposal_transport=transport,
        model_version="cluster-model-v1",
        prompt_version="resonance-prompt-v1",
    )
    first = service.publish(pack.id)
    assert len(first) == 4
    assert tuple((item.payload["score"], item.direction_key) for item in first) == tuple(
        sorted(
            ((item.payload["score"], item.direction_key) for item in first),
            key=lambda item: (-item[0], item[1]),
        )
    )
    transport.raise_on_call = True
    replay = service.publish(pack.id)
    assert tuple(item.id for item in replay) == tuple(item.id for item in first)
    assert all(item.payload["score_version"] == DIRECTION_SCORE_VERSION for item in first)


@pytest.mark.parametrize(
    ("interaction_signal", "observed", "expected"),
    [(None, False, None), (0.0, True, 0.0)],
)
def test_direction_distinguishes_missing_interaction_from_observed_zero(
    session: Session,
    interaction_signal: float | None,
    observed: bool,
    expected: float | None,
) -> None:
    repository, pack, claims = _seed_publishable_pack(
        session, interaction_signal=interaction_signal
    )
    direction = _service(repository, _proposal(claims)).publish(pack.id)[0]
    interaction = direction.payload["signals"]["interaction_signal"]
    assert interaction["observed"] is observed
    assert interaction["value"] == expected


def test_repository_rejects_forged_score_or_foreign_evidence(
    session: Session,
) -> None:
    repository, pack, claims = _seed_publishable_pack(session)
    direction = _service(repository, _proposal(claims)).publish(pack.id)[0]
    forged = dict(direction.payload)
    forged["score"] = 1.0 - float(forged["score"])
    with pytest.raises(ValueError, match="score"):
        repository.validate_direction_payload(
            pack.id, direction.direction_key, forged
        )
    forged = dict(direction.payload)
    forged["evidence_ids"] = [str(uuid4())]
    with pytest.raises(ValueError, match="evidence"):
        repository.validate_direction_payload(
            pack.id, direction.direction_key, forged
        )

    changed = dict(direction.payload)
    changed["title"] = "同一个命令键下被篡改的方向"
    with pytest.raises(IdempotencyConflict, match="different directions"):
        repository.publish_directions(
            PublishDirections(
                project_id=PROJECT_ID,
                evidence_pack_revision_id=pack.id,
                directions=(DirectionDraft(direction.direction_key, changed),),
                command_key=direction.command_key,
            )
        )


def test_interaction_metrics_are_public_counts_not_model_supplied_scores(
    session: Session,
) -> None:
    repository = ShiduRepository(session)
    job = _job(session, repository)
    with pytest.raises(ValueError, match="interaction_metrics"):
        _source(
            repository,
            job,
            suffix="bad-interaction",
            host="metrics.example",
            source_type="web",
            interaction_signal=-0.1,
        )


def test_nonpublishable_pack_returns_stable_critical_conflict_gap(
    session: Session,
) -> None:
    repository, pack, claims = _seed_publishable_pack(
        session, unresolved_critical=True
    )
    service = _service(repository, _proposal(claims))
    assert service.publish(pack.id) == ()
    assert service.last_gap_codes == ("critical_conflict_unresolved",)


def test_source_interaction_and_direction_columns_match_migration() -> None:
    from creative_hub.db.models import (
        ResonanceDirectionRevisionRecord,
        SourceDocumentRevisionRecord,
    )

    source_columns = set(SourceDocumentRevisionRecord.__table__.columns.keys())
    direction_columns = set(
        ResonanceDirectionRevisionRecord.__table__.columns.keys()
    )
    assert {
        "interaction_observed",
        "interaction_signal",
        "interaction_metrics",
        "interaction_normalization_version",
    } <= source_columns
    assert {
        "evidence_count",
        "score",
        "score_version",
        "validator_version",
    } <= direction_columns

    migration = Path(
        "creative_hub/orchestration_migrations/versions/orch_0026_shidu_domain.py"
    ).read_text(encoding="utf-8")
    for column in (
        "interaction_observed",
        "interaction_signal",
        "interaction_metrics",
        "interaction_normalization_version",
        "evidence_count",
        "score_version",
        "validator_version",
    ):
        assert column in migration
