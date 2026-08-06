"""Add structured methodology profiles, snapshots, and prompt lineage.

Revision ID: orch_0025
Revises: orch_0024

The new facts are expand-only.  Existing fragment-based Skill revisions and
run snapshots remain readable, but only approved structured ``rule-card.v1``
content can be frozen into an executable methodology snapshot by application
code.
"""

from __future__ import annotations

import hashlib
import json
import uuid

from alembic import op
import sqlalchemy as sa


revision = "orch_0025"
down_revision = "orch_0024"
branch_labels = None
depends_on = None

SCHEMA = "orchestration"
ROLE = "creative_orchestrator_app"
SHA256 = "length({column}) = 64"


def _canonical_digest(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


BUILTIN_RULE_CARDS = (
    (
        "creative-directing-core.v1",
        {
            "schema_version": "rule-card.v1",
            "title": "通用导演方法论核心",
            "summary": "将创作意图转换为单一叙事任务、可见动作链和一致的镜头调度。",
            "applicability": {
                "project_types": [],
                "stages": ["text_analysis", "shot_planning", "video_prompt", "repair"],
                "operations": [],
                "target_model_families": [],
                "modes": [],
            },
            "clauses": [
                {
                    "rule_id": "safety.observation-honesty",
                    "authority_tier": "safety_rights",
                    "when": ["来源或生成结果未被当前执行器实际检查"],
                    "directive": "不得声称观察、听取、测量或验证未被实际检查的素材；把用户描述标记为用户报告。",
                    "required_outputs": ["source_mapping", "safety_warnings"],
                    "forbidden": ["虚构已观察状态"],
                    "compression_priority": 100,
                },
                {
                    "rule_id": "directing.one-visible-beat",
                    "authority_tier": "causality_legibility",
                    "when": [],
                    "directive": "每个镜头只承担一个可见叙事动作，写明初态、触发、决定性变化、反应、跟随动作和局部终点。",
                    "required_outputs": ["narrative_job", "action_chain"],
                    "forbidden": ["一个镜头堆叠多个互相竞争的情节转折"],
                    "compression_priority": 98,
                },
                {
                    "rule_id": "directing.intent-coherence",
                    "authority_tier": "camera_editorial",
                    "when": [],
                    "directive": "先命名一个 felt_intent，再让镜头、表演、光线和声音共同服务它，所有运动必须有叙事动机。",
                    "required_outputs": ["felt_intent", "composition", "camera", "performance", "lighting", "sound"],
                    "forbidden": ["无动机的电影感形容词堆砌"],
                    "compression_priority": 95,
                },
                {
                    "rule_id": "continuity.no-replay-or-leak",
                    "authority_tier": "continuity",
                    "when": ["多镜头或续接项目"],
                    "directive": "已完成情节不得重演，保留情节不得提前泄露；已接受的观察状态高于原计划状态。",
                    "required_outputs": ["continuity_locks", "completed_beats", "reserved_beats"],
                    "forbidden": ["从被拒绝镜头继承连续性"],
                    "compression_priority": 97,
                },
                {
                    "rule_id": "reference.single-dimension-owner",
                    "authority_tier": "reference_authority",
                    "when": ["存在一个或多个参考素材"],
                    "directive": "每个受控维度只能由一个参考素材拥有，并明确必须保留和不得迁移的内容；没有职责的参考必须移除。",
                    "required_outputs": ["reference_duties"],
                    "forbidden": ["按上传顺序或文件类型推断参考权威"],
                    "compression_priority": 99,
                },
                {
                    "rule_id": "repair.one-variable",
                    "authority_tier": "causality_legibility",
                    "when": ["质检失败或人工要求返工"],
                    "directive": "先定位根因，再在一次返工中只改变一个主要变量，并保留其他已接受状态。",
                    "required_outputs": ["capability_warnings", "continuity_locks"],
                    "forbidden": ["用更多形容词掩盖失败根因"],
                    "compression_priority": 94,
                },
            ],
            "examples": [],
            "counter_examples": [],
            "risks": ["若目标能力未过滤，模型专属规则可能跨模态泄漏。"],
            "source": {
                "methodology": "seedance-20",
                "source_version": "6.6.0",
                "transformation": "model-neutral directing extraction",
            },
        },
    ),
    (
        "creative-visual-core.v1",
        {
            "schema_version": "rule-card.v1",
            "title": "静态关键帧方法论核心",
            "summary": "从导演合同分别构造首帧和尾帧，保持参考职责、构图和可见状态。",
            "applicability": {
                "project_types": [],
                "stages": ["image_prompt"],
                "operations": [],
                "target_model_families": ["qwen-image"],
                "modes": [],
            },
            "clauses": [
                {
                    "rule_id": "image.distinct-endpoint-frames",
                    "authority_tier": "causality_legibility",
                    "when": ["首尾帧视频生成"],
                    "directive": "首帧只描述动作初态，尾帧只描述局部终点；两者分别编译，不复用同一提示词。",
                    "required_outputs": ["first-frame", "last-frame"],
                    "forbidden": ["在静态图提示词中写镜头运动、音效或对白时序"],
                    "compression_priority": 100,
                },
                {
                    "rule_id": "image.reference-authority",
                    "authority_tier": "reference_authority",
                    "when": ["存在身份、服装、场景或产品参考"],
                    "directive": "按维度声明参考职责，并阻止身份、服装、场景和风格在未授权维度间串扰。",
                    "required_outputs": ["reference_duties", "continuity_locks"],
                    "forbidden": ["把视频或音频专属绑定语法写入图像提示词"],
                    "compression_priority": 99,
                },
            ],
            "examples": [],
            "counter_examples": [],
            "risks": ["首尾帧复用会抹去动作端点差异。"],
            "source": {
                "methodology": "seedance-20",
                "source_version": "6.6.0",
                "transformation": "image-safe directing extraction",
            },
        },
    ),
)


def _project_fk(name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["project_id"],
        [f"{SCHEMA}.projects.id"],
        name=name,
        ondelete="RESTRICT",
    )


def upgrade() -> None:
    op.create_table(
        "project_skill_profile_revisions",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column(
            "previous_revision_id", sa.Uuid(as_uuid=True), nullable=True
        ),
        sa.Column(
            "command_idempotency_key", sa.String(255), nullable=False
        ),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("created_by_actor", sa.String(100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "revision > 0", name="ck_orch_project_skill_profiles_positive"
        ),
        sa.CheckConstraint(
            "length(command_idempotency_key) BETWEEN 1 AND 255",
            name="ck_orch_project_skill_profiles_command_length",
        ),
        sa.CheckConstraint(
            SHA256.format(column="digest"),
            name="ck_orch_project_skill_profiles_digest",
        ),
        _project_fk("fk_orch_project_skill_profiles_project"),
        sa.ForeignKeyConstraint(
            ["previous_revision_id", "project_id"],
            [
                f"{SCHEMA}.project_skill_profile_revisions.id",
                f"{SCHEMA}.project_skill_profile_revisions.project_id",
            ],
            name="fk_orch_project_skill_profiles_previous",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "project_id",
            "revision",
            name="uq_orch_project_skill_profiles_number",
        ),
        sa.UniqueConstraint(
            "project_id",
            "command_idempotency_key",
            name="uq_orch_project_skill_profiles_command",
        ),
        sa.UniqueConstraint(
            "id", "project_id", name="uq_orch_project_skill_profiles_scope"
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_project_skill_profiles_project_revision",
        "project_skill_profile_revisions",
        ["project_id", "revision"],
        schema=SCHEMA,
    )

    op.create_table(
        "methodology_snapshots",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("work_unit_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column(
            "profile_revision_id", sa.Uuid(as_uuid=True), nullable=True
        ),
        sa.Column("workflow_run_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("snapshot_key", sa.String(255), nullable=False),
        sa.Column("purpose", sa.String(120), nullable=False),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default="FROZEN",
        ),
        sa.Column("ordered_cards", sa.JSON(), nullable=False),
        sa.Column("legacy_items", sa.JSON(), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("created_by_actor", sa.String(100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "status IN ('FROZEN', 'STALE')",
            name="ck_orch_methodology_snapshots_status",
        ),
        sa.CheckConstraint(
            "length(snapshot_key) BETWEEN 1 AND 255",
            name="ck_orch_methodology_snapshots_key_length",
        ),
        sa.CheckConstraint(
            "length(purpose) BETWEEN 1 AND 120",
            name="ck_orch_methodology_snapshots_purpose_length",
        ),
        sa.CheckConstraint(
            SHA256.format(column="digest"),
            name="ck_orch_methodology_snapshots_digest",
        ),
        _project_fk("fk_orch_methodology_snapshots_project"),
        sa.ForeignKeyConstraint(
            ["work_unit_id", "project_id"],
            [f"{SCHEMA}.work_units.id", f"{SCHEMA}.work_units.project_id"],
            name="fk_orch_methodology_snapshots_work_unit",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["profile_revision_id", "project_id"],
            [
                f"{SCHEMA}.project_skill_profile_revisions.id",
                f"{SCHEMA}.project_skill_profile_revisions.project_id",
            ],
            name="fk_orch_methodology_snapshots_profile",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_run_id", "project_id"],
            [f"{SCHEMA}.workflow_runs.id", f"{SCHEMA}.workflow_runs.project_id"],
            name="fk_orch_methodology_snapshots_run",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "project_id",
            "snapshot_key",
            name="uq_orch_methodology_snapshots_key",
        ),
        sa.UniqueConstraint(
            "id", "project_id", name="uq_orch_methodology_snapshots_scope"
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_methodology_snapshots_project_work_unit",
        "methodology_snapshots",
        ["project_id", "work_unit_id", "created_at"],
        schema=SCHEMA,
    )

    op.create_table(
        "prompt_compilations",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("work_unit_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column(
            "methodology_snapshot_id", sa.Uuid(as_uuid=True), nullable=False
        ),
        sa.Column(
            "shot_plan_revision_id", sa.Uuid(as_uuid=True), nullable=True
        ),
        sa.Column("workflow_run_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("unit_key", sa.String(200), nullable=True),
        sa.Column("operation", sa.String(120), nullable=False),
        sa.Column("target_model_family", sa.String(120), nullable=False),
        sa.Column("modality", sa.String(16), nullable=False),
        sa.Column("compilation_mode", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("compiler_model", sa.String(120), nullable=False),
        sa.Column("compiler_model_version", sa.String(120), nullable=False),
        sa.Column(
            "credential_revision_ref", sa.String(200), nullable=True
        ),
        sa.Column("adapter_key", sa.String(120), nullable=False),
        sa.Column("adapter_version", sa.String(120), nullable=False),
        sa.Column("input_digest", sa.String(64), nullable=False),
        sa.Column("cache_key", sa.String(64), nullable=False),
        sa.Column("methodology_brief", sa.JSON(), nullable=False),
        sa.Column(
            "direction_contract", sa.JSON(none_as_null=True), nullable=True
        ),
        sa.Column("applied_rules", sa.JSON(), nullable=False),
        sa.Column("omitted_rules", sa.JSON(), nullable=False),
        sa.Column(
            "compiled_bundle", sa.JSON(none_as_null=True), nullable=True
        ),
        sa.Column("failure", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("created_by_actor", sa.String(100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "status IN ('SUCCEEDED', 'FAILED')",
            name="ck_orch_prompt_compilations_status",
        ),
        sa.CheckConstraint(
            "compilation_mode IN ('legacy', 'shadow', 'enforced')",
            name="ck_orch_prompt_compilations_mode",
        ),
        sa.CheckConstraint(
            "modality IN ('text', 'image', 'video')",
            name="ck_orch_prompt_compilations_modality",
        ),
        sa.CheckConstraint(
            "length(operation) BETWEEN 1 AND 120",
            name="ck_orch_prompt_compilations_operation_length",
        ),
        sa.CheckConstraint(
            "length(target_model_family) BETWEEN 1 AND 120",
            name="ck_orch_prompt_compilations_target_length",
        ),
        sa.CheckConstraint(
            SHA256.format(column="input_digest"),
            name="ck_orch_prompt_compilations_input_digest",
        ),
        sa.CheckConstraint(
            SHA256.format(column="cache_key"),
            name="ck_orch_prompt_compilations_cache_key",
        ),
        sa.CheckConstraint(
            "(status = 'SUCCEEDED' AND direction_contract IS NOT NULL "
            "AND compiled_bundle IS NOT NULL AND failure IS NULL) OR "
            "(status = 'FAILED' AND compiled_bundle IS NULL "
            "AND failure IS NOT NULL)",
            name="ck_orch_prompt_compilations_result_shape",
        ),
        _project_fk("fk_orch_prompt_compilations_project"),
        sa.ForeignKeyConstraint(
            ["work_unit_id", "project_id"],
            [f"{SCHEMA}.work_units.id", f"{SCHEMA}.work_units.project_id"],
            name="fk_orch_prompt_compilations_work_unit",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["methodology_snapshot_id", "project_id"],
            [
                f"{SCHEMA}.methodology_snapshots.id",
                f"{SCHEMA}.methodology_snapshots.project_id",
            ],
            name="fk_orch_prompt_compilations_snapshot",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["shot_plan_revision_id", "project_id"],
            [
                f"{SCHEMA}.shot_plan_revisions.id",
                f"{SCHEMA}.shot_plan_revisions.project_id",
            ],
            name="fk_orch_prompt_compilations_shot_plan",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_run_id", "project_id"],
            [f"{SCHEMA}.workflow_runs.id", f"{SCHEMA}.workflow_runs.project_id"],
            name="fk_orch_prompt_compilations_run",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "project_id",
            "cache_key",
            name="uq_orch_prompt_compilations_cache",
        ),
        sa.UniqueConstraint(
            "id", "project_id", name="uq_orch_prompt_compilations_scope"
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_prompt_compilations_project_work_unit",
        "prompt_compilations",
        ["project_id", "work_unit_id", "created_at"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_prompt_compilations_snapshot_operation",
        "prompt_compilations",
        ["methodology_snapshot_id", "operation"],
        schema=SCHEMA,
    )

    immutable_tables = (
        "project_skill_profile_revisions",
        "methodology_snapshots",
        "prompt_compilations",
    )
    for table_name in immutable_tables:
        op.execute(
            f"""
            CREATE TRIGGER trg_{table_name}_immutable
            BEFORE UPDATE OR DELETE ON {SCHEMA}.{table_name}
            FOR EACH ROW
            EXECUTE FUNCTION {SCHEMA}.reject_immutable_fact_mutation()
            """
        )
    op.execute(
        "REVOKE ALL ON TABLE "
        + ", ".join(f"{SCHEMA}.{table}" for table in immutable_tables)
        + " FROM PUBLIC"
    )
    table_list = ", ".join(
        f"{SCHEMA}.{table}" for table in immutable_tables
    )
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{ROLE}') THEN
                GRANT USAGE ON SCHEMA {SCHEMA} TO {ROLE};
                GRANT SELECT, INSERT ON TABLE {table_list} TO {ROLE};
            END IF;
        END
        $$;
        """
    )

    # Register versioned, model-neutral extractions from seedance-20.  They are
    # available for explicit project selection but are never auto-bound.
    bind = op.get_bind()
    for skill_key, card in BUILTIN_RULE_CARDS:
        skill_id = uuid.uuid5(
            uuid.NAMESPACE_URL, f"orchestration:skills:{skill_key}"
        )
        revision_id = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"orchestration:skill-revisions:{skill_key}@1",
        )
        card_json = json.dumps(
            card, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        )
        evidence_json = json.dumps(
            {
                "source": "seedance-20@6.6.0",
                "normalization": "system-authored structured extraction",
                "auto_bound": False,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        bind.execute(
            sa.text(
                f"""
                INSERT INTO {SCHEMA}.skills (
                    id, skill_key, lifecycle, current_revision, state_version
                )
                SELECT CAST(:skill_id AS uuid),
                       CAST(:skill_key AS varchar(160)),
                       'APPROVED', 1, 1
                WHERE NOT EXISTS (
                    SELECT 1 FROM {SCHEMA}.skills
                    WHERE skill_key = CAST(:skill_key AS varchar(160))
                )
                """
            ),
            {"skill_id": skill_id, "skill_key": skill_key},
        )
        bind.execute(
            sa.text(
                f"""
                INSERT INTO {SCHEMA}.skill_revisions (
                    id, skill_id, revision, status, content, evidence,
                    applicability, risks, digest, created_by_actor
                )
                SELECT CAST(:revision_id AS uuid), s.id, 1, 'APPROVED',
                       CAST(:content AS jsonb), CAST(:evidence AS jsonb),
                       CAST(:applicability AS jsonb), CAST(:risks AS jsonb),
                       CAST(:digest AS varchar(64)),
                       'system.methodology-normalizer'
                FROM {SCHEMA}.skills s
                WHERE s.skill_key = CAST(:skill_key AS varchar(160))
                  AND s.id = CAST(:skill_id AS uuid)
                  AND NOT EXISTS (
                    SELECT 1 FROM {SCHEMA}.skill_revisions r
                    WHERE r.skill_id = s.id AND r.revision = 1
                )
                """
            ),
            {
                "revision_id": revision_id,
                "skill_id": skill_id,
                "skill_key": skill_key,
                "content": card_json,
                "evidence": evidence_json,
                "applicability": json.dumps(
                    card["applicability"]["stages"],
                    separators=(",", ":"),
                ),
                "risks": json.dumps(
                    card["risks"], ensure_ascii=False, separators=(",", ":")
                ),
                "digest": _canonical_digest(card),
            },
        )


def downgrade() -> None:
    for table_name in (
        "prompt_compilations",
        "methodology_snapshots",
        "project_skill_profile_revisions",
    ):
        op.execute(
            f"DROP TRIGGER IF EXISTS trg_{table_name}_immutable "
            f"ON {SCHEMA}.{table_name}"
        )
        op.drop_table(table_name, schema=SCHEMA)
