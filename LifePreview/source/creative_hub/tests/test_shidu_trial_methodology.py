from __future__ import annotations

import hashlib
from copy import deepcopy
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from creative_hub.db.models import ProjectRecord
from creative_hub.models import OrchestrationBase
from creative_hub.shidu.repository import IdempotencyConflict, ShiduRepository
from creative_hub.shidu.schemas import (
    EvidenceClaim,
    EvidencePackRevision,
    FreezeTrialMethodology,
    ResonanceDirectionRevision,
    SourceDocumentRevision,
    StoreTrialScript,
    TrialMethodologyRevision,
    TrialScriptRevision,
)
from creative_hub.shidu.trial_methodology import (
    METHODOLOGY_KEY,
    METHODOLOGY_PROMPT_DIGEST,
    METHODOLOGY_VERSION,
    SHOT_BEATS,
    TRIAL_SCRIPT_SCHEMA_VERSION,
    TRIAL_VALIDATOR_VERSION,
    TrialMethodologyService,
    methodology_v01_payload,
)
from creative_hub.shidu.trial_script_compiler import (
    DeterministicTrialScriptTransport,
    TrialScriptCompiler,
)
from creative_hub.shidu.trial_safety import (
    TrialSafetyGateService,
    TrialScriptSafety,
)
from creative_hub.shidu.trial_script_validator import (
    TRIAL_COMPILER_VERSION,
    TrialScriptError,
    TrialScriptValidator,
    action_skeleton_digest,
    parse_action_skeleton,
)
from test_shidu_resonance import (
    PROJECT_ID,
    _proposal,
    _seed_publishable_pack,
    _service,
)


NOW = datetime(2026, 8, 3, tzinfo=UTC)
PACK_ID = UUID("33333333-3333-4333-8333-333333333333")
DIRECTION_ID = UUID("44444444-4444-4444-8444-444444444444")
METHODOLOGY_ID = UUID("55555555-5555-4555-8555-555555555555")
BOOK_ID = UUID("66666666-6666-4666-8666-666666666666")
PLOT_ID = UUID("77777777-7777-4777-8777-777777777777")
STYLE_ID = UUID("88888888-8888-4888-8888-888888888888")
PLOT_SOURCE_ID = UUID("99999999-9999-4999-8999-999999999999")
STYLE_SOURCE_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")


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
        value.add(
            ProjectRecord(
                id=PROJECT_ID,
                project_key="project-task-8",
                title="Task 8",
                config={},
                config_digest="0" * 64,
            )
        )
        value.commit()
        yield value
    engine.dispose()


def _source(source_id: UUID, content: str, *, source_type: str) -> SourceDocumentRevision:
    return SourceDocumentRevision(
        id=source_id,
        project_id=PROJECT_ID,
        research_job_id=uuid4(),
        canonical_url=f"https://{source_id}.example/review",
        source_type=source_type,
        source_classification_version="shidu-source-type-v1",
        registered_domain=f"{source_id}.example",
        search_hit_id=None,
        revision=1,
        content=content,
        content_digest=hashlib.sha256(content.encode()).hexdigest(),
        digest="1" * 64,
        command_key=f"source:{source_id}",
        created_at=NOW,
    )


def _claim(
    evidence_id: UUID,
    source: SourceDocumentRevision,
    *,
    claim_type: str,
    excerpt: str,
    direct: bool = False,
) -> EvidenceClaim:
    start = source.content.index(excerpt)
    return EvidenceClaim(
        id=evidence_id,
        project_id=PROJECT_ID,
        research_job_id=source.research_job_id,
        source_document_revision_id=source.id,
        claim_type=claim_type,
        normalized_claim=excerpt,
        source_span={"start": start, "end": start + len(excerpt)},
        excerpt_digest=hashlib.sha256(excerpt.encode()).hexdigest(),
        is_direct_quote=direct,
        spoiler_level="light",
        confidence=0.9,
        conflict_group_key=None,
        conflict_severity=None,
        digest="2" * 64,
        command_key=f"claim:{evidence_id}",
        created_at=NOW,
    )


def _context():
    plot_source = _source(
        PLOT_SOURCE_ID,
        "门外冷雨，我握住门把手，推开了门，我看见走廊尽头的灯在风里轻轻晃动。",
        source_type="publisher",
    )
    style_source = _source(
        STYLE_SOURCE_ID,
        "读者感到害怕又决绝，叙述节奏克制而紧张。",
        source_type="review",
    )
    plot = _claim(
        PLOT_ID,
        plot_source,
        claim_type="plot_node",
        excerpt="我握住门把手",
        direct=True,
    )
    style = _claim(
        STYLE_ID,
        style_source,
        claim_type="emotional_reaction",
        excerpt="害怕又决绝",
    )
    pack = EvidencePackRevision(
        id=PACK_ID,
        project_id=PROJECT_ID,
        research_job_id=plot.research_job_id,
        revision=1,
        evidence_ids=(PLOT_ID, STYLE_ID),
        conflict_adjudication_revision_id=uuid4(),
        adjudicator_version="adjudicator-v1",
        conflicts=(),
        coverage={},
        publishable=True,
        insufficiency_reason_codes=(),
        digest="3" * 64,
        command_key="pack:1",
        created_at=NOW,
    )
    direction = ResonanceDirectionRevision(
        id=DIRECTION_ID,
        project_id=PROJECT_ID,
        evidence_pack_revision_id=PACK_ID,
        direction_key="door",
        revision=1,
        publication_ordinal=1,
        evidence_count=2,
        score=0.8,
        score_version="score-v1",
        validator_version="direction-validator-v1",
        payload={
            "evidence_ids": [str(PLOT_ID), str(STYLE_ID)],
            "fit_for": [{"text": "喜欢克制叙事的读者", "evidence_ids": [str(STYLE_ID)]}],
            "not_fit_for": [{"text": "只想知道答案的读者", "evidence_ids": [str(STYLE_ID)]}],
            "spoiler_level": "light",
        },
        digest="4" * 64,
        command_key="direction:1",
        created_at=NOW,
    )
    methodology = TrialMethodologyRevision(
        id=METHODOLOGY_ID,
        project_id=PROJECT_ID,
        methodology_key=METHODOLOGY_KEY,
        methodology_version=METHODOLOGY_VERSION,
        revision=1,
        prompt_digest=METHODOLOGY_PROMPT_DIGEST,
        validator_version=TRIAL_VALIDATOR_VERSION,
        payload=methodology_v01_payload(),
        digest="5" * 64,
        command_key="methodology:1",
        created_at=NOW,
    )
    return methodology, direction, pack, (plot, style), (plot_source, style_source)


def _valid_payload() -> dict:
    methodology, direction, pack, _, _ = _context()
    shots = []
    durations = (7, 9, 10, 10, 10, 8)
    for beat, duration in zip(SHOT_BEATS, durations, strict=True):
        before, after = str(beat["required_change"]).split("→", 1)
        shots.append(
            {
                "ordinal": beat["ordinal"],
                "narrative_task": beat["narrative_task"],
                "action": f"我握住门完成第{beat['ordinal']}个当下动作",
                "composition": "第一人称近景",
                "camera_movement": "缓慢推进",
                "lighting": "冷暖交界",
                "sound": "雨声与呼吸",
                "duration_seconds": duration,
                "state_before": before,
                "state_after": after,
                "factual_evidence_ids": [str(PLOT_ID)],
                "style_evidence_ids": [str(STYLE_ID)],
            }
        )
    cue_texts = ["我握住" + "风" * 27 for _ in range(6)]
    payload = {
        "schema_version": TRIAL_SCRIPT_SCHEMA_VERSION,
        "validator_version": TRIAL_VALIDATOR_VERSION,
        "compiler_version": TRIAL_COMPILER_VERSION,
        "model_version": "model-v1",
        "prompt_version": "prompt-v1",
        "project_id": str(PROJECT_ID),
        "book_id": str(BOOK_ID),
        "evidence_pack_revision_id": str(pack.id),
        "resonance_direction_revision_id": str(direction.id),
        "methodology_revision_id": str(methodology.id),
        "methodology_digest": methodology.digest,
        "direction_digest": direction.digest,
        "action_skeleton_digest": "",
        "generation_order": ["action_skeleton", "narration"],
        "provisional_title": "推开门的一刻",
        "experience_promise": "借我的眼睛经历一次选择",
        "narrator": "此刻的第一人称主人公",
        "continuous_moment": "冷雨夜里从握住门把手到推门的连续片刻",
        "primary_conflict": "我要在退回与承担代价之间选择",
        "known_now": ["门外有人", "钥匙在我手里"],
        "unknown_now": ["门后长期发生什么", "别人没有说出的答案"],
        "emotion_curve": ["警觉", "渴望", "受压", "决断", "震动", "悬停"],
        "shots": shots,
        "opening_line": cue_texts[0][:10],
        "opening_line_kind": "ai_adapted",
        "opening_line_evidence_id": None,
        "narration_cues": [
            {
                "cue_key": f"cue-{index}",
                "shot_ordinal": index,
                "text": text,
                "pause_after_ms": 300,
                "factual_evidence_ids": [str(PLOT_ID)],
                "style_evidence_ids": [str(STYLE_ID)],
            }
            for index, text in enumerate(cue_texts, start=1)
        ],
        "narration_text": "".join(cue_texts),
        "pronunciation_dictionary": {},
        "risk_flags": {
            "spoiler": False,
            "copyright": False,
            "factual_conflict": False,
            "pov": False,
        },
        "fit_for": direction.payload["fit_for"],
        "not_fit_for": direction.payload["not_fit_for"],
        "spoiler_level": "light",
        "spoiler_policy": "light",
    }
    payload["action_skeleton_digest"] = action_skeleton_digest(payload)
    _refresh_safety_gate(payload)
    return payload


def _refresh_safety_gate(payload: dict) -> None:
    _, direction, _, claims, sources = _context()
    safety = TrialSafetyGateService()
    source_passages = tuple(item.content for item in sources)
    pre_gate = safety.evaluate(
        primary_category="fiction",
        phase="pre_compile",
        content_revision_id=f"direction:{direction.id}",
        content={
            "direction": direction.payload,
            "claims": [
                {
                    "claim_type": item.claim_type,
                    "normalized_claim": item.normalized_claim,
                    "spoiler_level": item.spoiler_level,
                }
                for item in claims
                if str(item.id) in set(direction.payload["evidence_ids"])
            ],
        },
        source_passages=source_passages,
    )
    post_gate = safety.evaluate(
        primary_category="fiction",
        phase="post_compile",
        content_revision_id=f"script-candidate:{direction.id}",
        content=payload,
        source_passages=source_passages,
    )
    payload["safety_gate"] = TrialScriptSafety(
        primary_category="fiction",
        safety_cards_manifest_digest=(
            pre_gate.safety_cards_manifest_digest
        ),
        pre_compile=pre_gate,
        post_compile=post_gate,
    ).model_dump(mode="json")


def _validator() -> TrialScriptValidator:
    methodology, direction, pack, claims, sources = _context()
    return TrialScriptValidator(
        methodology=methodology,
        direction=direction,
        pack=pack,
        claims=claims,
        sources=sources,
        book_id=BOOK_ID,
    )


def _refresh_skeleton_digest(payload: dict) -> None:
    payload["action_skeleton_digest"] = action_skeleton_digest(payload)


def test_methodology_v01_is_frozen_and_returns_isolated_payloads() -> None:
    first = methodology_v01_payload()
    second = methodology_v01_payload()
    assert first["methodology_version"] == METHODOLOGY_VERSION == "0.1"
    assert first["generation_order"] == ["action_skeleton", "narration"]
    assert len(first["shot_beats"]) == 6
    first["shot_beats"][0]["narrative_task"] = "forged"
    assert second["shot_beats"][0]["narrative_task"] == "异常进入"


def test_valid_script_has_exact_six_transitions_and_180_chinese_characters() -> None:
    payload = _validator().validate(_valid_payload())
    assert len(payload["shots"]) == 6
    assert len(payload["narration_text"]) == 180


def test_script_rejects_omniscient_future_knowledge() -> None:
    payload = _valid_payload()
    payload["narration_cues"][0]["text"] = "我握住门后来才知道结局" + "风" * 19
    payload["narration_text"] = "".join(
        item["text"] for item in payload["narration_cues"]
    )
    payload["opening_line"] = payload["narration_cues"][0]["text"][:10]
    with pytest.raises(TrialScriptError, match="knowledge_boundary"):
        _validator().validate(payload)


def test_script_rejects_unknown_now_detail_in_action() -> None:
    payload = _valid_payload()
    payload["shots"][2]["action"] = "我看见门后长期发生什么"
    _refresh_skeleton_digest(payload)
    with pytest.raises(TrialScriptError, match="knowledge_boundary"):
        _validator().validate(payload)


def test_script_requires_six_distinct_state_changes() -> None:
    payload = _valid_payload()
    payload["shots"] = payload["shots"][:5]
    _refresh_skeleton_digest(payload)
    with pytest.raises(TrialScriptError, match="six_shots|script_schema"):
        _validator().validate(payload)

    payload = _valid_payload()
    payload["shots"][5]["state_before"] = payload["shots"][0]["state_before"]
    payload["shots"][5]["state_after"] = payload["shots"][0]["state_after"]
    _refresh_skeleton_digest(payload)
    with pytest.raises(TrialScriptError, match="six_shots"):
        _validator().validate(payload)


def test_script_rejects_distinct_but_wrong_frozen_state_transition() -> None:
    payload = _valid_payload()
    payload["shots"][2]["state_before"] = "尚可拖延"
    payload["shots"][2]["state_after"] = "必须立刻回答"
    _refresh_skeleton_digest(payload)
    with pytest.raises(TrialScriptError, match="six_shots"):
        _validator().validate(payload)


@pytest.mark.parametrize("total", [179, 231])
def test_narration_rejects_outside_180_to_230_chinese_characters(total: int) -> None:
    payload = _valid_payload()
    base, remainder = divmod(total, 6)
    texts = ["我握住" + "风" * (base - 3) for _ in range(6)]
    texts[-1] += "风" * remainder
    for cue, text in zip(payload["narration_cues"], texts, strict=True):
        cue["text"] = text
    payload["narration_text"] = "".join(texts)
    payload["opening_line"] = texts[0][:10]
    with pytest.raises(TrialScriptError, match="narration_length"):
        _validator().validate(payload)


def test_verified_quote_must_match_exact_frozen_source_span() -> None:
    payload = _valid_payload()
    quote = "我握住门把手"
    payload["opening_line"] = quote
    payload["opening_line_kind"] = "verified_quote"
    payload["opening_line_evidence_id"] = str(PLOT_ID)
    payload["narration_cues"][0]["text"] = quote + "风" * 24
    payload["narration_text"] = "".join(
        item["text"] for item in payload["narration_cues"]
    )
    _refresh_safety_gate(payload)
    assert _validator().validate(payload)["opening_line_kind"] == "verified_quote"

    payload["opening_line"] = "我握住另一扇门"
    payload["narration_cues"][0]["text"] = payload["opening_line"] + "风" * 23
    payload["narration_text"] = "".join(
        item["text"] for item in payload["narration_cues"]
    )
    with pytest.raises(TrialScriptError, match="exact source span"):
        _validator().validate(payload)


def test_factual_lineage_rejects_invented_action_despite_valid_evidence_id() -> None:
    payload = _valid_payload()
    payload["shots"][0]["action"] = "我驾驶飞船降落在陌生星球"
    _refresh_skeleton_digest(payload)
    with pytest.raises(TrialScriptError, match="ungrounded"):
        _validator().validate(payload)


def test_ai_adapted_narration_rejects_recognizable_long_source_passage() -> None:
    payload = _valid_payload()
    copied = "门外冷雨，我握住门把手，推开了门，我看见走廊尽头的灯在风里轻轻晃动。"
    payload["narration_cues"][0]["text"] = copied
    payload["narration_text"] = "".join(
        item["text"] for item in payload["narration_cues"]
    )
    payload["opening_line"] = copied[:10]
    with pytest.raises(TrialScriptError, match="copyright"):
        _validator().validate(payload)


@pytest.mark.parametrize("surface", ["action", "provisional_title"])
def test_copyright_gate_scans_action_and_title_surfaces(surface: str) -> None:
    payload = _valid_payload()
    copied = "门外冷雨，我握住门把手，推开了门，我看见走廊尽头的灯在风里轻轻晃动。"
    if surface == "action":
        payload["shots"][0]["action"] = copied
    else:
        payload["provisional_title"] = copied
    _refresh_skeleton_digest(payload)
    with pytest.raises(TrialScriptError, match="copyright"):
        _validator().validate(payload)


def test_copyright_gate_detects_source_passage_split_across_cues() -> None:
    payload = _valid_payload()
    copied = "门外冷雨，我握住门把手，推开了门，我看见走廊尽头的灯在风里轻轻晃动。"
    split_at = copied.index("，我看见") + 1
    texts = [
        copied[:split_at],
        copied[split_at:],
        *("我握住" + "风" * 34 for _ in range(4)),
    ]
    texts[-1] += "风" * 2
    for cue, text in zip(payload["narration_cues"], texts, strict=True):
        cue["text"] = text
    payload["narration_text"] = "".join(texts)
    payload["opening_line"] = texts[0][:10]
    with pytest.raises(TrialScriptError, match="copyright"):
        _validator().validate(payload)


def test_model_action_contract_rejects_tool_or_provider_control() -> None:
    payload = _valid_payload()
    skeleton = {
        key: payload[key]
        for key in (
            "provisional_title",
            "experience_promise",
            "narrator",
            "continuous_moment",
            "primary_conflict",
            "known_now",
            "unknown_now",
            "emotion_curve",
            "shots",
        )
    }
    for field in ("tool", "provider", "risk_flags", "opening_line_kind"):
        with pytest.raises(TrialScriptError, match="structured output"):
            parse_action_skeleton({**skeleton, field: "forged"})


def test_repository_revalidates_forged_payload_and_compiler_replays_without_model(
    session: Session,
) -> None:
    repository, pack, claims = _seed_publishable_pack(session)
    direction = _service(repository, _proposal(claims)).publish(pack.id)[0]
    _, _, _, _, book_id = repository.load_direction_context(direction.id)
    methodology = TrialMethodologyService(repository).freeze(PROJECT_ID)
    assert TrialMethodologyService(repository).freeze(PROJECT_ID).id == methodology.id
    forged_methodology = methodology_v01_payload()
    forged_methodology["generation_order"] = ["narration", "action_skeleton"]
    with pytest.raises(ValueError, match="methodology"):
        repository.freeze_trial_methodology(
            FreezeTrialMethodology(
                project_id=PROJECT_ID,
                methodology_key=METHODOLOGY_KEY,
                methodology_version=METHODOLOGY_VERSION,
                prompt_digest=METHODOLOGY_PROMPT_DIGEST,
                validator_version=TRIAL_VALIDATOR_VERSION,
                payload=forged_methodology,
                command_key="methodology:forged",
            )
        )

    class RecordingTransport(DeterministicTrialScriptTransport):
        def __init__(self) -> None:
            self.calls: list[str] = []
            self.fail = False

        def generate_action_skeleton(self, request):
            if self.fail:
                raise AssertionError("idempotent replay consumed model quota")
            self.calls.append("action_skeleton")
            return super().generate_action_skeleton(request)

        def generate_narration(self, request):
            if self.fail:
                raise AssertionError("idempotent replay consumed model quota")
            assert request.action_skeleton_digest == action_skeleton_digest(
                request.action_skeleton
            )
            self.calls.append("narration")
            return super().generate_narration(request)

    transport = RecordingTransport()
    compiler = TrialScriptCompiler(
        repository=repository,
        transport=transport,
        model_version="fake-model-v1",
    )
    script = compiler.compile(
        project_id=PROJECT_ID,
        book_id=book_id,
        direction_revision_id=direction.id,
        methodology_revision_id=methodology.id,
        command_key="script:1",
    )
    assert transport.calls == ["action_skeleton", "narration"]
    assert script.payload["opening_line_kind"] == "ai_adapted"
    assert len(script.payload["shots"]) == 6
    assert script.revision == 1

    transport.fail = True
    replay = compiler.compile(
        project_id=PROJECT_ID,
        book_id=book_id,
        direction_revision_id=direction.id,
        methodology_revision_id=methodology.id,
        command_key="script:1",
    )
    assert replay.id == script.id

    forged = deepcopy(script.payload)
    forged["risk_flags"]["spoiler"] = True
    with pytest.raises(TrialScriptError, match="risk_flags"):
        repository.store_trial_script(
            StoreTrialScript(
                project_id=PROJECT_ID,
                book_id=book_id,
                evidence_pack_revision_id=pack.id,
                resonance_direction_revision_id=direction.id,
                methodology_revision_id=methodology.id,
                payload=forged,
                command_key="script:forged",
            )
        )
    with pytest.raises(IdempotencyConflict, match="different inputs"):
        compiler.compile(
            project_id=PROJECT_ID,
            book_id=book_id,
            direction_revision_id=direction.id,
            methodology_revision_id=methodology.id,
            command_key="script:1",
            opening_line_kind="verified_quote",
        )


def test_compiler_replay_rejects_different_verified_quote_evidence_id() -> None:
    existing_quote_id = uuid4()
    requested_quote_id = uuid4()
    script = TrialScriptRevision(
        id=uuid4(),
        project_id=PROJECT_ID,
        book_id=BOOK_ID,
        evidence_pack_revision_id=PACK_ID,
        resonance_direction_revision_id=DIRECTION_ID,
        methodology_revision_id=METHODOLOGY_ID,
        revision=1,
        validator_version=TRIAL_VALIDATOR_VERSION,
        payload={
            "opening_line_kind": "verified_quote",
            "opening_line_evidence_id": str(existing_quote_id),
            "spoiler_policy": "light",
        },
        digest="d" * 64,
        command_key="script:verified-replay",
        created_at=NOW,
    )

    class ReplayRepository:
        def get_trial_script_for_command(self, project_id, command_key):
            assert project_id == PROJECT_ID
            assert command_key == script.command_key
            return script

    compiler = TrialScriptCompiler(repository=ReplayRepository())  # type: ignore[arg-type]
    with pytest.raises(IdempotencyConflict, match="different inputs"):
        compiler.compile(
            project_id=PROJECT_ID,
            book_id=BOOK_ID,
            direction_revision_id=DIRECTION_ID,
            methodology_revision_id=METHODOLOGY_ID,
            command_key=script.command_key,
            opening_line_kind="verified_quote",
            verified_quote_evidence_id=requested_quote_id,
        )
