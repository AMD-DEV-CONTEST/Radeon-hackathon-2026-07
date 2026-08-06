#!/usr/bin/env python3
"""Generate the checked-in E5 instance and scenario fixtures.

Wave 1 runs tickets 02, 04, 06 and 08 concurrently against the frozen contracts.
Without a worked instance of each intermediate artifact, each of those tickets
would invent its own — ticket 08 would design the bilateral provenance shape it
exists to render correctly, and the divergence would surface only when the real
producer landed.

Every fixture here is built by constructing the frozen model, so an invalid
fixture cannot be written in the first place. `tests/unit/test_e5_fixtures.py`
re-validates the checked-in files, so a later contract change that would
invalidate them fails loudly instead of leaving stale examples in the tree.

Run `python3 scripts/export_e5_fixtures.py` to regenerate and
`--check` to verify the tree is current.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.experience_asset.domain.enums import (  # noqa: E402
    DiscoveryFailureClass,
    DiscoveryOutcome,
    MilestoneState,
    ProjectionEdgeType,
    ProjectionLifecycle,
    ProjectionRootKind,
    RelationLifecycle,
    RelationType,
    StatementStatus,
)
from app.experience_asset.domain.m4 import (  # noqa: E402
    InsightBoundaryMapV1,
    InsightEntryV1,
    InsightStatementV1,
)
from app.experience_asset.domain.relation import (  # noqa: E402
    DISCOVERY_INTENT_VERSION,
    compute_projection_hash,
    role_graph_edge_id,
    role_graph_member_node_id,
    role_graph_root_node_id,
    PROJECTION_SCHEMA_VERSION,
    RELATION_CONTRACT_VERSION,
    ConfirmedAssetRelationV1,
    DiscoveryAttemptV1,
    DiscoveryFingerprintV1,
    KnowledgeCardReadinessRecordV1,
    NodeProvenanceV1,
    RelationCandidateDecisionV1,
    RelationCandidateV1,
    RelationNodeMappingV1,
    RelationProvenanceRefV1,
    RoleGraphEdgeV1,
    RoleGraphNodeV1,
    RoleGraphProjectionV1,
)

OUT_DIR = ROOT / "contracts" / "examples" / "e5"
AT = datetime(2026, 8, 2, 0, 0, tzinfo=UTC)


def uid(tag: str) -> UUID:
    """Deterministic identifier, so regeneration produces no spurious diff."""
    return UUID(bytes=hashlib.sha256(tag.encode()).digest()[:16], version=4)


def sha(tag: str) -> str:
    return hashlib.sha256(tag.encode()).hexdigest()


# --------------------------------------------------------------------------
# Three sanitized assets: A is current, B relates to A across topics, C does not.
# --------------------------------------------------------------------------

ASSET_A, ASSET_B, ASSET_C = uid("asset-a"), uid("asset-b"), uid("asset-c")
VERSION_A, VERSION_B, VERSION_C = uid("ver-a"), uid("ver-b"), uid("ver-c")
CARD_A, CARD_B, CARD_C = sha("card-a"), sha("card-b"), sha("card-c")


def insight_statement(
    tag: str, role: str, text: str, *, gap: bool = False
) -> InsightStatementV1:
    if gap:
        return InsightStatementV1(
            statement_id=uid(tag),
            role=role,
            text=text,
            status=StatementStatus.UNRESOLVED,
            is_visible_gap=True,
            gap_reason="来源材料未记录该项，用户已确认保留为可见缺口。",
        )
    return InsightStatementV1(
        statement_id=uid(tag),
        role=role,
        text=text,
        status=StatementStatus.USER_JUDGMENT,
        source_decision_ids=[uid(f"{tag}-decision")],
        source_statement_ids=[uid(f"{tag}-src")],
    )


def build_m4_map() -> InsightBoundaryMapV1:
    """One accepted map: a lesson that ships with the boundary making it reusable."""
    decision_id = uid("a-lesson-decision")
    statements = [
        insight_statement("a-lesson", "LESSON", "先量化尾延迟再改缓存策略，避免改完无法判断是否变好。"),
        insight_statement("a-support", "SUPPORT", "改动前后各采集一轮 P99，差异可归因到该次改动。"),
        insight_statement("a-counterfactual", "COUNTERFACTUAL", "若未先采集基线，回滚决策将只能凭感觉。"),
        insight_statement("a-limitation", "LIMITATION", "该做法依赖稳定的流量结构，促销期不适用。"),
        insight_statement("a-counterexample", "COUNTEREXAMPLE", "一次灰度期间流量结构骤变，基线对照失效。"),
        insight_statement("a-applicability", "APPLICABILITY", "适用于读多写少且流量结构稳定的服务。"),
    ]
    statements = [
        statement.model_copy(update={"source_decision_ids": [decision_id]})
        if not statement.is_visible_gap
        else statement
        for statement in statements
    ]
    entry = InsightEntryV1(
        insight_id=uid("a-insight"),
        title="改缓存前先量化尾延迟",
        source_decision_ids=[decision_id],
        statements=statements,
    )
    return InsightBoundaryMapV1(
        artifact_id=uid("a-m4"),
        asset_id=ASSET_A,
        base_m3_artifact_id=uid("a-m3"),
        base_canonical_version_id=VERSION_A,
        generated_by_run_id=uid("a-run"),
        state=MilestoneState.CONFIRMED,
        entries=[entry],
        dependency_decision_ids=[decision_id],
        dependency_statement_ids=[uid("a-lesson-src")],
        created_at=AT,
        updated_at=AT,
    )


def build_readiness() -> KnowledgeCardReadinessRecordV1:
    return KnowledgeCardReadinessRecordV1(
        readiness_id=uid("a-readiness"),
        asset_id=ASSET_A,
        version_id=VERSION_A,
        m4_artifact_id=uid("a-m4"),
        knowledge_card_hash=CARD_A,
        milestone_state=MilestoneState.CONFIRMED,
        accepted_at=AT,
        lifecycle=ProjectionLifecycle.ACTIVE,
    )


def build_projection(
    *, side: str, asset_id: UUID, version_id: UUID, card_hash: str, roots: dict
) -> RoleGraphProjectionV1:
    """Build one deterministic role-graph projection.

    `roots` maps a root kind to its label plus its member roles. A projection
    spans more than one root kind because the admissibility rules do: a method
    lives on a decision record while an applicability condition lives on an
    insight record, so a single-root projection could not express
    `METHOD_REUSE` at all.

    Only membership edges are emitted. No edge claims that one record caused
    another, because statement order and similarity cannot prove causation and a
    causal label would carry the same visual authority as the user's own account.
    """
    projection_id = uid(f"{side}-projection")
    nodes: list[RoleGraphNodeV1] = []
    edges: list[RoleGraphEdgeV1] = []
    provenance: list[NodeProvenanceV1] = []
    order = 0
    for root_kind, spec in roots.items():
        record_id = uid(f"{side}-{root_kind.value.lower()}")
        root_id = role_graph_root_node_id(
            root_kind=root_kind, canonical_record_id=record_id
        )
        nodes.append(
            RoleGraphNodeV1(
                node_id=root_id,
                projection_id=projection_id,
                root_kind=root_kind,
                canonical_record_id=record_id,
                is_root=True,
                display_order=order,
                summary_text=spec["label"],
                summary_text_hash=sha(spec["label"]),
            )
        )
        provenance.append(
            NodeProvenanceV1(
                node_id=root_id,
                projection_id=projection_id,
                statement_ids=[uid(f"{side}-{root_kind.value}-root-stmt")],
                source_refs=[f"{side}:source:{root_kind.value.lower()}"],
            )
        )
        order += 1
        for role, text in spec["members"].items():
            node_id = role_graph_member_node_id(
                root_kind=root_kind,
                canonical_record_id=record_id,
                role=ProjectionEdgeType(role),
                display_order=order,
            )
            nodes.append(
                RoleGraphNodeV1(
                    node_id=node_id,
                    projection_id=projection_id,
                    root_kind=root_kind,
                    canonical_record_id=record_id,
                    is_root=False,
                    role=ProjectionEdgeType(role),
                    display_order=order,
                    summary_text=text,
                    summary_text_hash=sha(text),
                )
            )
            edges.append(
                RoleGraphEdgeV1(
                    edge_id=role_graph_edge_id(
                        root_node_id=root_id,
                        member_node_id=node_id,
                        edge_type=ProjectionEdgeType(role),
                    ),
                    projection_id=projection_id,
                    edge_type=ProjectionEdgeType(role),
                    root_node_id=root_id,
                    member_node_id=node_id,
                    canonical_record_id=record_id,
                )
            )
            provenance.append(
                NodeProvenanceV1(
                    node_id=node_id,
                    projection_id=projection_id,
                    statement_ids=[uid(f"{side}-{role}-stmt")],
                    source_refs=[f"{side}:source:{role.lower()}"],
                )
            )
            order += 1
    return RoleGraphProjectionV1(
        projection_id=projection_id,
        asset_id=asset_id,
        version_id=version_id,
        knowledge_card_hash=card_hash,
        projection_schema_version=PROJECTION_SCHEMA_VERSION,
        projection_hash=compute_projection_hash(
            asset_id=asset_id,
            version_id=version_id,
            knowledge_card_hash=card_hash,
            projection_schema_version=PROJECTION_SCHEMA_VERSION,
            nodes=nodes,
            edges=edges,
            provenance=provenance,
        ),
        lifecycle=ProjectionLifecycle.ACTIVE,
        nodes=nodes,
        edges=edges,
        provenance=provenance,
        created_at=AT,
    )


DECISION = ProjectionRootKind.DECISION_RECORD
INSIGHT = ProjectionRootKind.INSIGHT_RECORD

CURRENT_ROOTS = {
    DECISION: {
        "label": "把缓存策略从 LRU 换成分段 TTL",
        "members": {
            "HAS_REASON": "尾延迟在高峰期不可预测，需要先有可比基线。",
            "HAS_ACTION": "改动前后各采集一轮 P99，差异归因到该次改动。",
            "HAS_RESULT": "P99 下降且波动收窄。",
        },
    },
    INSIGHT: {
        "label": "改缓存前先量化尾延迟",
        "members": {
            "HAS_SUPPORT": "两轮 P99 采样支持该结论。",
            "HAS_APPLICABILITY": "适用于读多写少且流量结构稳定的服务。",
            "HAS_LIMITATION": "依赖稳定流量结构，促销期不适用。",
        },
    },
}

POSITIVE_ROOTS = {
    DECISION: {
        "label": "按 P99 目标反推限流阈值",
        "members": {
            "HAS_ACTION": "先定住 P99 目标，再反推阈值并灰度放量。",
            "HAS_RESULT": "超时率下降，阈值不再靠手感调。",
        },
    },
    INSIGHT: {
        "label": "先定指标再动可调参数",
        "members": {
            "HAS_APPLICABILITY": "适用于可观测到分位延迟的在线服务。",
            "HAS_LIMITATION": "离线批处理没有可比的分位指标。",
        },
    },
}

NEGATIVE_ROOTS = {
    INSIGHT: {
        "label": "一次团队排班表的重做",
        "members": {
            "HAS_SUPPORT": "排班冲突下降后成员反馈更稳定。",
            "HAS_APPLICABILITY": "适用于固定班次的小团队。",
            "HAS_LIMITATION": "跨时区团队无法照搬。",
        },
    }
}


def build_fingerprint(
    current_projection_hash: str, eligible: list[str]
) -> DiscoveryFingerprintV1:
    return DiscoveryFingerprintV1(
        current_asset_id=ASSET_A,
        current_version_id=VERSION_A,
        current_knowledge_card_hash=CARD_A,
        current_projection_hash=current_projection_hash,
        eligible_projection_hashes=sorted(eligible),
        model_identity="Qwen/Qwen2.5-14B-Instruct",
        model_revision="frozen-revision-placeholder",
        prompt_version="e5-discovery-prompt/v1",
        role_contract_version=PROJECTION_SCHEMA_VERSION,
        validation_contract_version=RELATION_CONTRACT_VERSION,
        discovery_intent_version=DISCOVERY_INTENT_VERSION,
        inference_parameters_hash=sha("inference-parameters"),
        prefilter_config_version="e5-prefilter/v1",
    )


def node_of(
    projection: RoleGraphProjectionV1, role: str, root_kind: ProjectionRootKind
) -> str:
    """Look a node up by role rather than hard-coding its identifier."""
    for node in projection.nodes:
        if node.root_kind is root_kind and node.role and node.role.value == role:
            return node.node_id
    raise KeyError(f"{role} not present under {root_kind} in {projection.projection_id}")


def statement_of(projection: RoleGraphProjectionV1, node_id: str) -> list:
    for entry in projection.provenance:
        if entry.node_id == node_id:
            return list(entry.statement_ids)
    raise KeyError(node_id)


def build_candidate(
    current: RoleGraphProjectionV1, historical: RoleGraphProjectionV1
) -> RelationCandidateV1:
    """The cross-topic positive: different subject matter, one defensible mapping.

    `METHOD_REUSE` is admissible because a current-side reason maps onto a
    historical-side applicability, and the current-side boundary resolves
    through `HAS_LIMITATION`. Without that boundary the candidate must abstain:
    similarity alone would invite transferring the lesson into a situation the
    original experience never covered.
    """
    current_action = node_of(current, "HAS_ACTION", DECISION)
    historical_applicability = node_of(historical, "HAS_APPLICABILITY", INSIGHT)
    current_limitation = node_of(current, "HAS_LIMITATION", INSIGHT)
    historical_limitation = node_of(historical, "HAS_LIMITATION", INSIGHT)
    return RelationCandidateV1(
        candidate_id=uid("candidate-positive"),
        discovery_fingerprint=sha("fingerprint-positive"),
        current_asset_id=ASSET_A,
        current_projection_id=current.projection_id,
        related_asset_id=ASSET_B,
        historical_projection_id=historical.projection_id,
        relation_type=RelationType.METHOD_REUSE,
        title="调限流阈值前先定住 P99 目标",
        summary="另一段经验同样先把分位指标定死，再动可调参数。",
        node_mappings=[
            RelationNodeMappingV1(
                current_node_id=current_action,
                historical_node_id=historical_applicability,
                current_role=ProjectionEdgeType.HAS_ACTION,
                historical_role=ProjectionEdgeType.HAS_APPLICABILITY,
            )
        ],
        current_boundary_node_ids=[current_limitation],
        historical_boundary_node_ids=[historical_limitation],
        provenance=[
            RelationProvenanceRefV1(
                side="CURRENT",
                node_id=current_action,
                statement_ids=statement_of(current, current_action),
                source_refs=["current:source:has_action"],
            ),
            RelationProvenanceRefV1(
                side="HISTORICAL",
                node_id=historical_applicability,
                statement_ids=statement_of(historical, historical_applicability),
                source_refs=["positive:source:has_applicability"],
            ),
        ],
        lifecycle=RelationLifecycle.PROPOSED,
        created_at=AT,
    )


def build_attempt(
    outcome: DiscoveryOutcome, tag: str, current_projection_id, **extra
) -> DiscoveryAttemptV1:
    return DiscoveryAttemptV1(
        attempt_id=uid(f"attempt-{tag}"),
        run_id=uid(f"run-{tag}"),
        asset_id=ASSET_A,
        discovery_fingerprint=sha(f"fingerprint-{tag}"),
        current_projection_id=current_projection_id,
        eligible_set_hash=sha(f"eligible-{tag}"),
        attempt_number=1,
        outcome=outcome,
        started_at=AT,
        finished_at=AT,
        elapsed_ms=1200,
        **extra,
    )


def build_fixtures() -> dict[Path, dict]:
    current_projection = build_projection(
        side="current",
        asset_id=ASSET_A,
        version_id=VERSION_A,
        card_hash=CARD_A,
        roots=CURRENT_ROOTS,
    )
    positive_projection = build_projection(
        side="positive",
        asset_id=ASSET_B,
        version_id=VERSION_B,
        card_hash=CARD_B,
        roots=POSITIVE_ROOTS,
    )
    candidate = build_candidate(current_projection, positive_projection)
    negative_projection = build_projection(
        side="negative",
        asset_id=ASSET_C,
        version_id=VERSION_C,
        card_hash=CARD_C,
        roots=NEGATIVE_ROOTS,
    )
    return {
        # --- Wave-1 instance fixtures -------------------------------------
        OUT_DIR / "instance" / "m4-insight-boundary-map.json": build_m4_map().model_dump(
            mode="json"
        ),
        OUT_DIR / "instance" / "knowledge-card-readiness.json": build_readiness().model_dump(
            mode="json"
        ),
        OUT_DIR
        / "instance"
        / "role-graph-projection-current.json": current_projection.model_dump(
            mode="json"
        ),
        OUT_DIR
        / "instance"
        / "role-graph-projection-historical.json": positive_projection.model_dump(
            mode="json"
        ),
        OUT_DIR / "instance" / "discovery-fingerprint.json": build_fingerprint(
            current_projection.projection_hash,
            [positive_projection.projection_hash, negative_projection.projection_hash],
        ).model_dump(mode="json"),
        OUT_DIR / "instance" / "discovery-attempt.json": build_attempt(
            DiscoveryOutcome.CANDIDATE,
            "positive",
            current_projection.projection_id,
            candidate_id=candidate.candidate_id,
        ).model_dump(mode="json"),
        OUT_DIR / "instance" / "relation-candidate.json": candidate.model_dump(mode="json"),
        OUT_DIR / "instance" / "confirmed-asset-relation.json": ConfirmedAssetRelationV1(
            relation_id=uid("relation-positive"),
            source_candidate_id=candidate.candidate_id,
            relation_type=candidate.relation_type,
            current_asset_id=ASSET_A,
            current_version_id=VERSION_A,
            current_projection_id=current_projection.projection_id,
            current_knowledge_card_hash=CARD_A,
            related_asset_id=ASSET_B,
            related_version_id=VERSION_B,
            historical_projection_id=positive_projection.projection_id,
            lifecycle=RelationLifecycle.CONFIRMED,
            confirmed_at=AT,
        ).model_dump(mode="json"),
        OUT_DIR / "instance" / "relation-candidate-decision.json": (
            RelationCandidateDecisionV1(
                decision_id=uid("decision-positive"),
                candidate_id=candidate.candidate_id,
                current_asset_id=ASSET_A,
                current_version_id=VERSION_A,
                current_knowledge_card_hash=CARD_A,
                related_asset_id=ASSET_B,
                user_action="CONFIRM",
                decided_at=AT,
            ).model_dump(mode="json")
        ),
        # --- Three sanitized scenarios ------------------------------------
        OUT_DIR / "scenario" / "cross-topic-positive.json": {
            "scenario": "cross-topic-positive",
            "intent": (
                "A 与 B 主题不同，但存在一条有来源支撑的角色映射和一条明确的迁移边界；"
                "C 无可辩护关系。期望恰好一个候选，指向 B，且 C 永不出现。"
            ),
            "expected_outcome": DiscoveryOutcome.CANDIDATE.value,
            "expected_candidate_count": 1,
            "expected_related_asset_id": str(ASSET_B),
            "expected_relation_type": RelationType.METHOD_REUSE.value,
            "current_projection": "instance/role-graph-projection-current.json",
            "eligible_projections": [
                "instance/role-graph-projection-historical.json",
                "scenario/hard-negative-projection.json",
            ],
            "grag_ids": ["GRAG-03", "GRAG-05"],
        },
        OUT_DIR / "scenario" / "hard-negative-corpus.json": {
            "scenario": "hard-negative-corpus",
            "intent": (
                "两个历史资产都没有可辩护的关系包。期望语义 NO_MATCH 与零候选，"
                "并且必须与技术失败区分开——把停机缓存成 no-match 会让一条可能存在的"
                "关系永久消失。"
            ),
            "expected_outcome": DiscoveryOutcome.NO_MATCH.value,
            "expected_candidate_count": 0,
            "must_not_be": DiscoveryOutcome.TECHNICAL_FAILURE.value,
            "current_projection": "instance/role-graph-projection-current.json",
            "eligible_projections": ["scenario/hard-negative-projection.json"],
            "grag_ids": ["GRAG-04"],
        },
        OUT_DIR / "scenario" / "hard-negative-projection.json": (
            negative_projection.model_dump(mode="json")
        ),
        OUT_DIR / "scenario" / "invalid-false-association.json": {
            "scenario": "invalid-false-association",
            "intent": (
                "模型提案违反合同的六种方式。每一种都必须表现为校验或技术失败并且不展示"
                "任何候选；报成 NO_MATCH 会把一次传输事故记成一个语义结论并被缓存。"
            ),
            "expected_outcome": DiscoveryOutcome.TECHNICAL_FAILURE.value,
            "expected_candidate_count": 0,
            "must_not_be": DiscoveryOutcome.NO_MATCH.value,
            "expected_failure_class": (
                DiscoveryFailureClass.RUNTIME_VALIDATION_REJECTED.value
            ),
            "invalid_proposals": [
                {
                    "id": "forbidden-label",
                    "defect": "关系类型不在冻结的六种之内",
                    "why_rejected": "闭合词表之外的标签没有可采性规则，用户无从判断它主张了什么",
                },
                {
                    "id": "nonexistent-node",
                    "defect": "映射引用了投影中不存在的节点",
                    "why_rejected": "Runtime 只能对照已存储的投影校验标识符，无法校验凭空的节点",
                },
                {
                    "id": "wrong-side-node",
                    "defect": "把当前侧节点当作历史侧提交",
                    "why_rejected": "错侧映射会把同一份证据同时算作双边支撑",
                },
                {
                    "id": "missing-boundary",
                    "defect": "缺少当前侧迁移边界节点",
                    "why_rejected": "无边界的关系邀请用户把结论迁移到原经验从未覆盖的情境",
                },
                {
                    "id": "one-sided-provenance",
                    "defect": "只有一侧的溯源",
                    "why_rejected": "单侧溯源无法支撑双边解释，用户没有可对照检查的另一半",
                },
                {
                    "id": "inadmissible-role-pair",
                    "defect": "角色对不满足所选关系的可采性规则",
                    "why_rejected": "标签与角色形状不符时，关系名称与其实际结构不是一回事",
                },
            ],
            "grag_ids": ["GRAG-06", "GRAG-17"],
        },
    }


def rendered(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    stale: list[Path] = []
    for path, value in build_fixtures().items():
        content = rendered(value)
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != content:
                stale.append(path.relative_to(ROOT))
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    if stale:
        for path in stale:
            print(f"stale E5 fixture: {path}")
        return 1
    print("E5 fixtures are current" if args.check else "E5 fixtures generated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
