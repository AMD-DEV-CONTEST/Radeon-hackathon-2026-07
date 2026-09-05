"""Repository-seam proof for T04 role projection and lexical indexing."""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.experience_asset.domain.enums import (
    ConfirmationState,
    EvidenceStrength,
    Milestone,
    MilestoneState,
    ReviewStatus,
    StatementStatus,
)
from app.experience_asset.domain.factory import new_empty_asset
from app.experience_asset.domain.m4 import (
    InsightBoundaryMapV1,
    InsightEntryV1,
    InsightStatementV1,
)
from app.experience_asset.domain.models import (
    ExperienceAssetV1,
    InsightRecord,
    MilestoneArtifact,
    Statement,
)
from app.experience_asset.domain.relation import (
    KnowledgeCardReadinessRecordV1,
    RoleGraphEdgeV1,
    RoleGraphNodeV1,
    RoleGraphProjectionV1,
    compute_projection_hash,
)
from app.experience_asset.persistence import SQLiteAssetRepository
from app.experience_asset.persistence.relation_ledger import (
    ProjectionHashMismatchError,
    StaleBindingError,
)
from app.experience_asset.retrieval import SQLiteSummaryLexicalRepository
from app.experience_asset.role_graph import (
    CJK_NGRAM_SIZE,
    LATIN_CASEFOLD,
    LEXICAL_NORMALIZATION_VERSION,
    UNICODE_DATA_VERSION,
    UNICODE_NORMALIZATION_FORM,
    build_role_graph_projection,
    normalize_lexical_text,
)

NOW = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
ROLES = (
    "LESSON",
    "SUPPORT",
    "COUNTERFACTUAL",
    "LIMITATION",
    "COUNTEREXAMPLE",
    "APPLICABILITY",
)


def _ready_asset() -> tuple[
    ExperienceAssetV1, InsightBoundaryMapV1, KnowledgeCardReadinessRecordV1
]:
    base = new_empty_asset(now=NOW)
    decision_id = uuid4()
    insight_id = uuid4()
    statement_ids = {role: uuid4() for role in ROLES}
    text = {
        "LESSON": "Cache changes need a P99 baseline",
        "SUPPORT": "两轮采样支持该结论",
        "COUNTERFACTUAL": "没有基线就无法判断收益",
        "LIMITATION": "促销流量结构变化时不适用",
        "COUNTEREXAMPLE": "一次突发流量使基线失效",
        "APPLICABILITY": "适用于流量稳定的在线服务",
    }
    canonical_statements = [
        Statement(
            statement_id=statement_ids[role],
            text=text[role],
            status=StatementStatus.USER_JUDGMENT,
            confirmation=ConfirmationState.CONFIRMED,
            evidence_strength=EvidenceStrength.SELF_REPORTED,
            created_in_version=base.version_id,
            last_changed_in_version=base.version_id,
        )
        for role in ROLES
    ]
    artifact_id = uuid4()
    run_id = uuid4()
    artifact = InsightBoundaryMapV1(
        artifact_id=artifact_id,
        asset_id=base.asset_id,
        base_m3_artifact_id=uuid4(),
        base_canonical_version_id=base.version_id,
        generated_by_run_id=run_id,
        state=MilestoneState.CONFIRMED,
        entries=[
            InsightEntryV1(
                insight_id=insight_id,
                title=text["LESSON"],
                source_decision_ids=[decision_id],
                statements=[
                    InsightStatementV1(
                        statement_id=statement_ids[role],
                        role=role,
                        text=text[role],
                        status=StatementStatus.USER_JUDGMENT,
                        source_decision_ids=[decision_id],
                    )
                    for role in ROLES
                ],
            )
        ],
        dependency_decision_ids=[decision_id],
        created_at=NOW,
        updated_at=NOW,
    )
    m4_reference = MilestoneArtifact(
        artifact_id=uuid4(),
        artifact_type="M4_INSIGHT_BOUNDARY_MAP_REFERENCE",
        asset_id=base.asset_id,
        version_id=base.version_id,
        milestone=Milestone.M4,
        state=MilestoneState.CONFIRMED,
        statement_ids=sorted(statement_ids.values(), key=str),
        generated_by_run_id=run_id,
        user_review_status=ReviewStatus.ACCEPTED,
        created_at=NOW,
        updated_at=NOW,
        payload={"m4_artifact_id": str(artifact_id)},
    )
    asset = ExperienceAssetV1.model_validate(
        base.model_dump(mode="python")
        | {
            "goal": "Reduce CACHE tail latency",
            "current_milestone": Milestone.M5,
            "statements": canonical_statements,
            "insights": [
                InsightRecord(
                    insight_id=insight_id,
                    lesson=text["LESSON"],
                    support_statement_ids=[statement_ids["SUPPORT"]],
                    counterfactual_statement_ids=[statement_ids["COUNTERFACTUAL"]],
                    limitation_statement_ids=[statement_ids["LIMITATION"]],
                    counterexample_statement_ids=[statement_ids["COUNTEREXAMPLE"]],
                    applicability_statement_ids=[statement_ids["APPLICABILITY"]],
                )
            ],
            "milestone_states": {
                **base.milestone_states,
                Milestone.M4: MilestoneState.CONFIRMED,
            },
            "milestone_artifacts": [m4_reference],
        }
    )
    card_hash = SQLiteAssetRepository._snapshot_hash(asset)
    readiness = KnowledgeCardReadinessRecordV1(
        readiness_id=uuid4(),
        asset_id=asset.asset_id,
        version_id=asset.version_id,
        m4_artifact_id=artifact.artifact_id,
        knowledge_card_hash=card_hash,
        milestone_state=MilestoneState.CONFIRMED,
        accepted_at=NOW,
    )
    return asset, artifact, readiness


def _persist_ready_inputs(
    repository: SQLiteAssetRepository,
    asset: ExperienceAssetV1,
    artifact: InsightBoundaryMapV1,
    readiness: KnowledgeCardReadinessRecordV1,
) -> None:
    repository.create(asset)
    connection = sqlite3.connect(repository.database_path)
    connection.execute("PRAGMA foreign_keys = ON")
    m2_id = str(uuid4())
    m3_id = str(artifact.base_m3_artifact_id)
    connection.execute(
        "INSERT INTO m2_artifacts VALUES (?, ?, NULL, ?, '{}', ?)",
        (m2_id, str(asset.asset_id), str(asset.version_id), NOW.isoformat()),
    )
    connection.execute(
        "INSERT INTO m3_artifacts VALUES (?, ?, NULL, ?, ?, '{}', ?)",
        (
            m3_id,
            str(asset.asset_id),
            m2_id,
            str(asset.version_id),
            NOW.isoformat(),
        ),
    )
    connection.execute(
        "INSERT INTO m4_artifacts VALUES (?, ?, NULL, ?, ?, ?, ?)",
        (
            str(artifact.artifact_id),
            str(asset.asset_id),
            m3_id,
            str(asset.version_id),
            artifact.model_dump_json(),
            NOW.isoformat(),
        ),
    )
    connection.execute(
        "INSERT INTO m4_current VALUES (?, ?)",
        (str(asset.asset_id), str(artifact.artifact_id)),
    )
    connection.execute(
        """INSERT INTO knowledge_card_readiness(
            readiness_id, asset_id, version_id, m4_artifact_id,
            knowledge_card_hash, milestone_state, content_json,
            lifecycle, accepted_at
        ) VALUES (?, ?, ?, ?, ?, 'CONFIRMED', ?, 'ACTIVE', ?)""",
        (
            str(readiness.readiness_id),
            str(asset.asset_id),
            str(asset.version_id),
            str(artifact.artifact_id),
            readiness.knowledge_card_hash,
            readiness.model_dump_json(),
            NOW.isoformat(),
        ),
    )
    connection.commit()
    connection.close()


def test_normalization_records_and_reproduces_english_and_chinese_policy() -> None:
    assert LEXICAL_NORMALIZATION_VERSION == "e5-lexical-normalization/v1"
    assert UNICODE_NORMALIZATION_FORM == "NFKC"
    assert UNICODE_DATA_VERSION == "15.0.0"
    assert CJK_NGRAM_SIZE == 2
    assert LATIN_CASEFOLD is True
    assert normalize_lexical_text("\uff23\uff21\uff23\uff28\uff25cache P99缓存策略") == (
        "cachecache",
        "p99",
        "缓存",
        "存策",
        "策略",
    )
    assert normalize_lexical_text("HAS_LIMITATION") == ("has_limitation",)


def test_projection_rebuild_has_stable_identifiers_content_and_hash() -> None:
    asset, artifact, readiness = _ready_asset()
    first = build_role_graph_projection(
        asset=asset,
        m4_artifact=artifact,
        readiness=readiness,
        created_at=NOW,
    )
    rebuilt = build_role_graph_projection(
        asset=asset,
        m4_artifact=artifact,
        readiness=readiness,
        created_at=NOW + timedelta(minutes=1),
    )

    assert rebuilt.projection_id == first.projection_id
    assert rebuilt.projection_hash == first.projection_hash
    assert [node.node_id for node in rebuilt.nodes] == [node.node_id for node in first.nodes]
    assert [edge.edge_id for edge in rebuilt.edges] == [edge.edge_id for edge in first.edges]
    assert {edge.edge_type.value for edge in first.edges} == {
        "HAS_SUPPORT",
        "HAS_COUNTERFACTUAL",
        "HAS_LIMITATION",
        "HAS_COUNTEREXAMPLE",
        "HAS_APPLICABILITY",
    }


def test_accepted_visible_gap_is_not_projected_or_indexable() -> None:
    asset, artifact, readiness = _ready_asset()
    gap_id = artifact.entries[0].statements[4].statement_id
    gap_text = artifact.entries[0].statements[4].text
    statements = [
        statement.model_copy(
            update={
                "status": StatementStatus.UNRESOLVED,
                "confirmation": ConfirmationState.UNCONFIRMED,
                "evidence_strength": EvidenceStrength.NONE,
            }
        )
        if statement.statement_id == gap_id
        else statement
        for statement in asset.statements
    ]
    gap_artifact = InsightBoundaryMapV1.model_validate(
        artifact.model_dump(mode="python")
        | {
            "state": MilestoneState.COMPLETE_WITH_GAPS,
            "entries": [
                artifact.entries[0].model_copy(
                    update={
                        "statements": [
                            statement.model_copy(
                                update={
                                    "status": StatementStatus.UNRESOLVED,
                                    "source_decision_ids": [],
                                    "is_visible_gap": True,
                                    "gap_reason": "The evidence remains unresolved.",
                                }
                            )
                            if statement.statement_id == gap_id
                            else statement
                            for statement in artifact.entries[0].statements
                        ]
                    }
                )
            ],
        }
    )
    gap_asset = ExperienceAssetV1.model_validate(
        asset.model_dump(mode="python")
        | {
            "statements": statements,
            "milestone_states": {
                **asset.milestone_states,
                Milestone.M4: MilestoneState.COMPLETE_WITH_GAPS,
            },
            "milestone_artifacts": [
                asset.milestone_artifacts[0].model_copy(
                    update={
                        "state": MilestoneState.COMPLETE_WITH_GAPS,
                        "user_review_status": ReviewStatus.ACCEPTED_WITH_GAPS,
                    }
                )
            ],
        }
    )
    gap_readiness = KnowledgeCardReadinessRecordV1(
        readiness_id=uuid4(),
        asset_id=gap_asset.asset_id,
        version_id=gap_asset.version_id,
        m4_artifact_id=gap_artifact.artifact_id,
        knowledge_card_hash=SQLiteAssetRepository._snapshot_hash(gap_asset),
        milestone_state=MilestoneState.COMPLETE_WITH_GAPS,
        accepted_gap_statement_ids=[gap_id],
        accepted_at=NOW,
    )

    projection = build_role_graph_projection(
        asset=gap_asset,
        m4_artifact=gap_artifact,
        readiness=gap_readiness,
        created_at=NOW,
    )
    assert gap_text not in {node.summary_text for node in projection.nodes}
    assert gap_id not in {
        statement_id
        for provenance in projection.provenance
        for statement_id in provenance.statement_ids
    }


def test_activation_search_rebuild_and_invalidation_are_one_durable_boundary(
    tmp_path,
) -> None:
    repository = SQLiteAssetRepository(tmp_path / "projection.sqlite3")
    repository.initialize()
    asset, artifact, readiness = _ready_asset()
    _persist_ready_inputs(repository, asset, artifact, readiness)
    projection = build_role_graph_projection(
        asset=asset,
        m4_artifact=artifact,
        readiness=readiness,
        created_at=NOW,
    )

    repository.activate_projection(projection)
    repository.activate_projection(projection)  # unchanged rebuild is idempotent
    eligible = repository.list_eligible_projections(current_asset_id=uuid4())
    assert [item.projection_hash for item in eligible] == [projection.projection_hash]

    search = SQLiteSummaryLexicalRepository(repository)
    english = search.search(query="cache P99", current_asset_id=uuid4())
    chinese = search.search(query="促销流量", current_asset_id=uuid4())
    absent = search.search(query="quantum banana", current_asset_id=uuid4())
    absent_role = search.search(query="HAS_CUE", current_asset_id=uuid4())
    assert [hit.projection_id for hit in english.hits] == [projection.projection_id]
    assert [hit.projection_id for hit in chinese.hits] == [projection.projection_id]
    assert absent.no_match is True and absent.hits == []
    assert absent_role.no_match is True and absent_role.hits == []

    repository.invalidate_projection(projection.projection_id, reason="canonical correction")
    assert repository.list_eligible_projections(current_asset_id=uuid4()) == []
    assert search.search(query="cache", current_asset_id=uuid4()).no_match is True
    connection = sqlite3.connect(repository.database_path)
    assert connection.execute(
        "SELECT count(*) FROM relation_summary_fts WHERE projection_id=?",
        (str(projection.projection_id),),
    ).fetchone()[0] == 0


def test_activation_rejects_a_non_ready_card_without_partial_rows(tmp_path) -> None:
    repository = SQLiteAssetRepository(tmp_path / "stale.sqlite3")
    repository.initialize()
    asset, artifact, readiness = _ready_asset()
    _persist_ready_inputs(repository, asset, artifact, readiness)
    projection = build_role_graph_projection(
        asset=asset,
        m4_artifact=artifact,
        readiness=readiness,
        created_at=NOW,
    )
    connection = sqlite3.connect(repository.database_path)
    connection.execute(
        """UPDATE knowledge_card_readiness
        SET lifecycle='STALE', invalidated_at=?, invalidation_reason='corrected'""",
        (NOW.isoformat(),),
    )
    connection.commit()

    with pytest.raises(StaleBindingError):
        repository.activate_projection(projection)
    assert connection.execute("SELECT count(*) FROM role_graph_projections").fetchone()[0] == 0
    assert connection.execute("SELECT count(*) FROM relation_summary_fts").fetchone()[0] == 0


def test_activation_rejects_self_consistent_but_noncanonical_summary(tmp_path) -> None:
    repository = SQLiteAssetRepository(tmp_path / "tamper.sqlite3")
    repository.initialize()
    asset, artifact, readiness = _ready_asset()
    _persist_ready_inputs(repository, asset, artifact, readiness)
    projection = build_role_graph_projection(
        asset=asset,
        m4_artifact=artifact,
        readiness=readiness,
        created_at=NOW,
    )
    payload = projection.model_dump(mode="python")
    payload["nodes"][0]["summary_text"] = "Unconfirmed material injected into memory"
    payload["nodes"][0]["summary_text_hash"] = hashlib.sha256(
        payload["nodes"][0]["summary_text"].encode()
    ).hexdigest()
    nodes = [RoleGraphNodeV1.model_validate(node) for node in payload["nodes"]]
    edges = [RoleGraphEdgeV1.model_validate(edge) for edge in payload["edges"]]
    payload["projection_hash"] = compute_projection_hash(
        asset_id=projection.asset_id,
        version_id=projection.version_id,
        knowledge_card_hash=projection.knowledge_card_hash,
        projection_schema_version=projection.projection_schema_version,
        nodes=nodes,
        edges=edges,
        provenance=projection.provenance,
    )
    forged = RoleGraphProjectionV1.model_validate(payload)

    with pytest.raises(ProjectionHashMismatchError):
        repository.activate_projection(forged)
    connection = sqlite3.connect(repository.database_path)
    assert connection.execute("SELECT count(*) FROM role_graph_projections").fetchone()[0] == 0
    assert connection.execute("SELECT count(*) FROM relation_summary_fts").fetchone()[0] == 0


def test_equal_bm25_scores_are_ordered_by_projection_id(tmp_path) -> None:
    repository = SQLiteAssetRepository(tmp_path / "ties.sqlite3")
    repository.initialize()
    projections = []
    for _ in range(2):
        asset, artifact, readiness = _ready_asset()
        _persist_ready_inputs(repository, asset, artifact, readiness)
        projection = build_role_graph_projection(
            asset=asset,
            m4_artifact=artifact,
            readiness=readiness,
            created_at=NOW,
        )
        repository.activate_projection(projection)
        projections.append(projection)

    result = SQLiteSummaryLexicalRepository(repository).search(
        query="cache P99", current_asset_id=uuid4()
    )
    assert [hit.projection_id for hit in result.hits] == sorted(
        (projection.projection_id for projection in projections), key=str
    )
    assert result.hits[0].bm25_score == result.hits[1].bm25_score


def test_raw_user_text_never_reaches_the_cross_asset_index(tmp_path) -> None:
    """AC-7: only accepted canonical material becomes cross-asset memory.

    `goal` and `context` are free text the user typed while still working the
    problem out. The projection's own invariant is that it reads accepted
    canonical records and extracts no new facts from raw text, and the index is
    built from the projection — so a marker that appears only in those two
    fields must be unfindable. Pinning it matters because the existing search
    tests query terms that also occur in accepted statements, which cannot tell
    a projected hit from a raw-text one.
    """
    marker = "kumquatzzz"
    repository = SQLiteAssetRepository(tmp_path / "raw-text.sqlite3")
    repository.initialize()
    asset, artifact, readiness = _ready_asset()
    asset = ExperienceAssetV1.model_validate(
        asset.model_dump(mode="python")
        | {"goal": f"{marker} tail latency", "context": f"背景里也有 {marker}"}
    )
    readiness = readiness.model_copy(
        update={"knowledge_card_hash": SQLiteAssetRepository._snapshot_hash(asset)}
    )
    _persist_ready_inputs(repository, asset, artifact, readiness)
    projection = build_role_graph_projection(
        asset=asset, m4_artifact=artifact, readiness=readiness, created_at=NOW
    )
    repository.activate_projection(projection)

    assert marker in asset.goal and marker in asset.context
    assert not any(marker in node.summary_text for node in projection.nodes)

    search = SQLiteSummaryLexicalRepository(repository)
    assert search.search(query=marker, current_asset_id=uuid4()).no_match is True
    # The accepted material from the same asset is still reachable, so the
    # assertion above is about provenance rather than an empty index.
    assert search.search(query="促销流量", current_asset_id=uuid4()).hits != []
