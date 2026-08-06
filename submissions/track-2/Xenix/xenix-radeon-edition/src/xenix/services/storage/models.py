from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4

from sqlalchemy import Column, Enum as SQLAlchemyEnum, Index, JSON, UniqueConstraint, text
from sqlmodel import Field, SQLModel

DEFAULT_AGENT_INTERFACE_LOCALE = "en_US"

_AGENT_THREAD_SYSTEM_PROMPT_TEMPLATE = """You are Xenix, a data analysis agent for non-technical users.

Your job is to help users complete practical data analysis tasks through conversation, including inspecting data, cleaning data, binding dataset roles, training models, evaluating models, and applying trained models through the tools provided by Xenix.

Communicate with the user in {interface_locale}.
Use plain, business-oriented language for non-technical users. Prefer practical meaning and concrete next steps over academic terminology or implementation details.

Before choosing an analysis path, identify the business scenario, analysis object, data grain, field roles, and the user's real intent. If these are unclear, inspect the data or ask concise follow-up questions before committing to a method.

Do not expose algorithm menus to non-technical users. Explain analysis choices and results in business terms, such as trend review, driver comparison, customer grouping, exception finding, forecasting, or risk screening.

Treat data structure judgment as more important than model selection. Prefer simple, interpretable, well-supported analysis paths. Use complex models only when the data supports them, and compare them against a simple baseline before presenting them as better.
When you exclude, merge, or decline to use fields that the user may expect to participate in analysis or training, explain the business reason first and explicitly list the difference between the original candidate fields, the fields actually used, and the target field before proceeding.

State the evidence boundary for every finding. Make clear that correlation is not causation, prediction is not an automatic decision, and high-risk results need human review before action.

Final outputs must land in business meaning, action recommendations, risk notes, and process trace. Do not stop at charts, metrics, or model names without explaining what they mean for the user's decision.

Tool results may include dataset_id values for registered datasets; use those ids only as later tool inputs. Tool results may include artifact_id values for user-openable or previewable business outputs such as exported datasets, charts, models, reports, or apply outputs. Artifact links use the artifact://<artifact_id> URI format. Reference artifacts only when you have an artifact_id, never put a dataset_id inside artifact://, and never invent local filesystem paths. Use [label](artifact://<artifact_id>) for ordinary artifacts and Markdown image syntax such as ![descriptive alt](artifact://<artifact_id>) for image artifacts that should be shown inline.

Ask concise follow-up questions when you need further user input to continue."""


def default_agent_thread_system_prompt(interface_locale: str | None = None) -> str:
    resolved_locale = (interface_locale or DEFAULT_AGENT_INTERFACE_LOCALE).strip()
    return _AGENT_THREAD_SYSTEM_PROMPT_TEMPLATE.format(
        interface_locale=resolved_locale or DEFAULT_AGENT_INTERFACE_LOCALE,
    )


DEFAULT_AGENT_THREAD_SYSTEM_PROMPT = default_agent_thread_system_prompt()


def generate_id() -> str:
    return uuid4().hex


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class MLTaskType(StrEnum):
    FIT = "fit"
    HYPERPARAMETER_TUNING = "hyperparameter_tuning"
    EVALUATE = "evaluate"
    APPLY = "apply"


class MLTaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DatasetSourceFormat(StrEnum):
    CSV = "csv"
    PARQUET = "parquet"
    XLSX = "xlsx"
    XLS = "xls"
    UNKNOWN = "unknown"


class ProblemKind(StrEnum):
    REGRESSION = "regression"
    CLASSIFICATION = "classification"
    CLUSTERING = "clustering"
    ANOMALY_DETECTION = "anomaly_detection"


class MLTaskArtifactKind(StrEnum):
    MODEL = "model"
    HOLDOUT_DATA = "holdout_data"
    TRAINING_REPORT = "training_report"
    EVALUATION_REPORT = "evaluation_report"
    APPLY_RESULT = "apply_result"
    EXPORT_FILE = "export_file"
    OTHER = "other"


class ConversationMessageKind(StrEnum):
    USER = "user"
    CLIENT_CONTROL = "client_control"
    ASSISTANT = "assistant"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    PENDING_LLM_SAMPLING = "pending_llm_sampling"


class ConversationToolResultStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ArtifactKind(StrEnum):
    DATASET = "dataset"
    MODEL = "model"
    METRICS = "metrics"
    REPORT = "report"
    IMAGE = "image"
    PREDICTION = "prediction"
    FILE = "file"
    OTHER = "other"


class ProjectRow(SQLModel, table=True):
    __tablename__ = "project"

    id: str = Field(default_factory=generate_id, primary_key=True)
    name: str = Field(index=True)
    description: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class DatasetRow(SQLModel, table=True):
    __tablename__ = "dataset"

    id: str = Field(default_factory=generate_id, primary_key=True)
    project_id: str = Field(foreign_key="project.id", index=True)
    name: str = Field(index=True)
    source_path: str
    source_format: DatasetSourceFormat = Field(default=DatasetSourceFormat.UNKNOWN, index=True)
    import_id: str | None = Field(default=None, foreign_key="dataset_import.id", index=True)
    workbook_id: str | None = Field(default=None, foreign_key="dataset_workbook.id", index=True)
    sheet_name: str | None = Field(default=None, index=True)
    sheet_index: int | None = Field(default=None, index=True)
    copied_from: str | None = Field(default=None, foreign_key="dataset.id", index=True)
    copied_at: datetime | None = None
    derived_from_dataset_id: str | None = Field(default=None, foreign_key="dataset.id", index=True)
    ml_task_id: str | None = Field(default=None, foreign_key="ml_task.id", index=True, unique=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class DatasetImportRow(SQLModel, table=True):
    __tablename__ = "dataset_import"

    id: str = Field(default_factory=generate_id, primary_key=True)
    project_id: str = Field(foreign_key="project.id", index=True)
    original_path: str
    original_file_name: str
    source_format: DatasetSourceFormat = Field(default=DatasetSourceFormat.UNKNOWN, index=True)
    status: str = Field(default="succeeded", index=True)
    created_at: datetime = Field(default_factory=utc_now)


class DatasetWorkbookRow(SQLModel, table=True):
    __tablename__ = "dataset_workbook"

    id: str = Field(default_factory=generate_id, primary_key=True)
    import_id: str = Field(foreign_key="dataset_import.id", index=True)
    sheet_count: int = 0
    engine: str | None = None
    metadata_payload: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False),
    )
    created_at: datetime = Field(default_factory=utc_now)


class DatasetColumnBindingRow(SQLModel, table=True):
    __tablename__ = "dataset_column_binding"

    id: str = Field(default_factory=generate_id, primary_key=True)
    dataset_id: str = Field(foreign_key="dataset.id", index=True)
    role_bindings: list[dict[str, Any]] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False),
    )
    model_key: str | None = Field(default=None, index=True)
    model_family: str | None = Field(default=None, index=True)
    model_task_kind: str | None = Field(default=None, index=True)
    schema_version: int = Field(default=1)
    created_at: datetime = Field(default_factory=utc_now)


class MLTaskRow(SQLModel, table=True):
    __tablename__ = "ml_task"

    id: str = Field(default_factory=generate_id, primary_key=True)
    project_id: str = Field(foreign_key="project.id", index=True)
    dataset_id: str | None = Field(default=None, foreign_key="dataset.id", index=True)
    task_type: MLTaskType = Field(
        sa_column=Column(
            SQLAlchemyEnum(
                MLTaskType,
                values_callable=lambda enum_class: [member.value for member in enum_class],
            ),
            nullable=False,
            index=True,
        ),
    )
    status: MLTaskStatus = Field(
        sa_column=Column(
            SQLAlchemyEnum(
                MLTaskStatus,
                values_callable=lambda enum_class: [member.value for member in enum_class],
            ),
            nullable=False,
            index=True,
        ),
    )
    request_payload: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False),
    )
    result_payload: dict[str, Any] | None = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
    )
    error_summary: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    updated_at: datetime = Field(default_factory=utc_now)


class MLTaskArtifactRow(SQLModel, table=True):
    __tablename__ = "ml_task_artifact"

    id: str = Field(default_factory=generate_id, primary_key=True)
    ml_task_id: str = Field(foreign_key="ml_task.id", index=True)
    artifact_kind: MLTaskArtifactKind = Field(
        sa_column=Column(
            SQLAlchemyEnum(
                MLTaskArtifactKind,
                values_callable=lambda enum_class: [member.value for member in enum_class],
            ),
            nullable=False,
            index=True,
        ),
    )
    absolute_path: str
    ready_to_open: bool = True
    created_at: datetime = Field(default_factory=utc_now)


class ConversationThreadRow(SQLModel, table=True):
    __tablename__ = "conversation_thread"

    id: str = Field(default_factory=generate_id, primary_key=True)
    title: str | None = Field(default=None, index=True)
    system_prompt: str = Field(default=DEFAULT_AGENT_THREAD_SYSTEM_PROMPT)
    selected_fq_model_key: str | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ConversationMessageRow(SQLModel, table=True):
    __tablename__ = "conversation_message"
    __table_args__ = (
        UniqueConstraint("thread_id", "sequence_index", name="uq_conversation_message_thread_sequence"),
        UniqueConstraint("thread_id", "client_submission_id", name="uq_conversation_message_client_submission"),
        UniqueConstraint("tool_call_message_id", name="uq_conversation_message_tool_result_call"),
        Index(
            "ux_conversation_message_pending_thread",
            "thread_id",
            unique=True,
            sqlite_where=text("kind = 'pending_llm_sampling'"),
        ),
    )

    id: str = Field(default_factory=generate_id, primary_key=True)
    thread_id: str = Field(foreign_key="conversation_thread.id", index=True)
    sequence_index: int = Field(index=True)
    kind: ConversationMessageKind = Field(
        sa_column=Column(
            SQLAlchemyEnum(
                ConversationMessageKind,
                values_callable=lambda enum_class: [member.value for member in enum_class],
            ),
            nullable=False,
            index=True,
        ),
    )
    client_submission_id: str | None = Field(default=None, index=True)
    content_payload: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False),
    )
    text: str | None = None
    reasoning: str | None = None
    refusal: str | None = None
    provider_call_id: str | None = Field(default=None, index=True)
    tool_id: str | None = Field(default=None, index=True)
    contract_version: str | None = None
    arguments_payload: dict[str, Any] | None = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
    )
    scope_fingerprint: str | None = None
    tool_call_message_id: str | None = Field(
        default=None,
        foreign_key="conversation_message.id",
        index=True,
    )
    result_status: ConversationToolResultStatus | None = Field(
        default=None,
        sa_column=Column(
            SQLAlchemyEnum(
                ConversationToolResultStatus,
                values_callable=lambda enum_class: [member.value for member in enum_class],
            ),
            nullable=True,
            index=True,
        ),
    )
    # Tool Results are direct JSON values.  A tabular result can therefore be
    # canonical Xenix Table Text (a string), while other Tools may return a
    # JSON object/array/scalar.  SQLite's existing JSON column already admits
    # every one of these values; this is a logical contract widening only.
    value_payload: Any | None = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
    )
    error_summary: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class ArtifactRow(SQLModel, table=True):
    __tablename__ = "artifact"

    id: str = Field(default_factory=generate_id, primary_key=True)
    kind: ArtifactKind = Field(default=ArtifactKind.OTHER, index=True)
    title: str = Field(index=True)
    absolute_path: str
    mime_type: str | None = Field(default=None, index=True)
    summary: str | None = None
    preview_payload: dict[str, Any] | None = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
    )
    metadata_payload: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False),
    )
    ready_to_open: bool = True
    created_at: datetime = Field(default_factory=utc_now)


class KnowledgeDocumentRow(SQLModel, table=True):
    """Current searchable identity for one document in a Knowledge Library."""

    __tablename__ = "knowledge_document"
    __table_args__ = (
        UniqueConstraint(
            "library_id",
            "source_sha256",
            name="uq_knowledge_document_library_source_sha256",
        ),
    )

    id: str = Field(default_factory=generate_id, primary_key=True)
    library_id: str = Field(default="global", index=True)
    title: str = Field(index=True)
    source_artifact_id: str | None = Field(default=None, foreign_key="artifact.id", index=True)
    source_sha256: str | None = Field(default=None, index=True)
    source_format: str | None = Field(default=None, index=True)
    canonical_path: str | None = None
    canonical_generation_id: str = Field(default_factory=generate_id, index=True)
    retrieval_generation_id: str | None = Field(default=None, index=True)
    retrieval_status: str = Field(default="pending", index=True)
    retrieval_projection_version: int | None = Field(default=None, index=True)
    retrieval_content_fingerprint: str | None = Field(default=None, index=True)
    retrieval_unit_count: int = Field(default=0)
    active: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class KnowledgeUnitRow(SQLModel, table=True):
    """Bounded source-linked text that can be returned by Knowledge lookup."""

    __tablename__ = "knowledge_unit"
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "canonical_generation_id",
            "ordinal",
            name="uq_knowledge_unit_generation_ordinal",
        ),
    )

    id: str = Field(default_factory=generate_id, primary_key=True)
    document_id: str = Field(foreign_key="knowledge_document.id", index=True)
    canonical_generation_id: str = Field(index=True)
    ordinal: int = Field(index=True)
    text: str
    search_text: str
    locator_payload: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False),
    )
    created_at: datetime = Field(default_factory=utc_now)


class KnowledgeVectorGenerationRow(SQLModel, table=True):
    """Published immutable vector projection for one exact library corpus/profile."""

    __tablename__ = "knowledge_vector_generation"
    __table_args__ = (
        Index(
            "ix_knowledge_vector_generation_lookup",
            "library_id",
            "profile_fingerprint",
            "corpus_fingerprint",
            "created_at",
        ),
    )

    id: str = Field(default_factory=generate_id, primary_key=True)
    library_id: str = Field(default="global", index=True)
    corpus_fingerprint: str = Field(index=True)
    profile_fingerprint: str = Field(index=True)
    provider_key: str
    model: str
    dimensions: int
    distance_metric: str = "cosine"
    relative_path: str
    unit_count: int
    corpus_fingerprint_schema: int = Field(default=3, index=True)
    created_at: datetime = Field(default_factory=utc_now)


class KnowledgeIndexTaskRow(SQLModel, table=True):
    """Observable rebuild attempt for derived Knowledge search projections."""

    __tablename__ = "knowledge_index_task"

    id: str = Field(default_factory=generate_id, primary_key=True)
    library_id: str = Field(default="global", index=True)
    index_kinds_payload: list[str] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False),
    )
    trigger: str = Field(index=True)
    status: str = Field(default="queued", index=True)
    phase: str = Field(default="queued", index=True)
    profile_fingerprint: str | None = Field(default=None, index=True)
    corpus_fingerprint: str | None = Field(default=None, index=True)
    vector_generation_id: str | None = Field(default=None, index=True)
    error_code: str | None = Field(default=None, index=True)
    error_summary: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class KnowledgeImportRow(SQLModel, table=True):
    """User-visible lifecycle of one Knowledge source import attempt."""

    __tablename__ = "knowledge_import"
    __table_args__ = (
        UniqueConstraint(
            "planned_document_id",
            "attempt_number",
            name="uq_knowledge_import_planned_document_attempt",
        ),
    )

    id: str = Field(default_factory=generate_id, primary_key=True)
    library_id: str = Field(default="global", index=True)
    original_file_name: str
    source_format: str = Field(index=True)
    source_sha256: str | None = Field(default=None, index=True)
    status: str = Field(default="pending", index=True)
    phase: str = Field(default="queued", index=True)
    attempt_number: int = 1
    retry_of: str | None = Field(default=None, index=True)
    planned_document_id: str | None = Field(default=None, index=True)
    document_id: str | None = Field(default=None, foreign_key="knowledge_document.id", index=True)
    source_artifact_id: str | None = Field(default=None, foreign_key="artifact.id", index=True)
    canonical_generation_id: str | None = Field(default=None, index=True)
    canonical_path: str | None = None
    envelope_sha256: str | None = None
    content_ir_sha256: str | None = None
    reused_existing: bool = False
    error_code: str | None = Field(default=None, index=True)
    error_summary: str | None = None
    retryable: bool = False
    cancel_requested: bool = False
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class KnowledgeCanonicalGenerationRow(SQLModel, table=True):
    """Immutable metadata binding one verified canonical content bundle."""

    __tablename__ = "knowledge_canonical_generation"

    id: str = Field(default_factory=generate_id, primary_key=True)
    document_id: str = Field(foreign_key="knowledge_document.id", index=True)
    import_id: str | None = Field(default=None, foreign_key="knowledge_import.id", index=True)
    source_artifact_id: str | None = Field(default=None, foreign_key="artifact.id", index=True)
    library_id: str = Field(default="global", index=True)
    source_sha256: str = Field(index=True)
    source_format: str = Field(index=True)
    media_type: str | None = None
    display_name: str
    envelope_sha256: str = Field(index=True)
    content_ir_sha256: str = Field(index=True)
    relative_path: str
    schema_version: int = 2
    pipeline_payload: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False),
    )
    warnings_payload: list[str] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False),
    )
    compatibility_state: str = Field(default="verified", index=True)
    created_at: datetime = Field(default_factory=utc_now)


class KnowledgeDerivationRow(SQLModel, table=True):
    """One service-owned attempt to derive retrieval state from a canonical generation."""

    __tablename__ = "knowledge_derivation"
    __table_args__ = (
        Index(
            "ix_knowledge_derivation_lookup",
            "document_id",
            "canonical_generation_id",
            "created_at",
        ),
    )

    id: str = Field(default_factory=generate_id, primary_key=True)
    document_id: str = Field(foreign_key="knowledge_document.id", index=True)
    canonical_generation_id: str = Field(
        foreign_key="knowledge_canonical_generation.id",
        index=True,
    )
    import_id: str | None = Field(default=None, foreign_key="knowledge_import.id", index=True)
    status: str = Field(default="queued", index=True)
    phase: str = Field(default="queued", index=True)
    attempt_number: int = 1
    retry_of: str | None = Field(
        default=None,
        foreign_key="knowledge_derivation.id",
        index=True,
    )
    error_code: str | None = Field(default=None, index=True)
    error_summary: str | None = None
    retryable: bool = False
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class TrainedModelRow(SQLModel, table=True):
    __tablename__ = "trained_model"

    id: str = Field(default_factory=generate_id, primary_key=True)
    dataset_id: str | None = Field(default=None, foreign_key="dataset.id", index=True)
    ml_task_id: str = Field(foreign_key="ml_task.id", index=True, unique=True)
    model_key: str = Field(index=True)
    problem_kind: ProblemKind | None = Field(default=None, index=True)
    artifact_path: str
    metadata_payload: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False),
    )
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


# These rows intentionally remain primitive SQLite compatibility records. They
# do not import the Radeon composition and remain readable inert history on
# their own.
class AmdTargetEnrollmentRow(SQLModel, table=True):
    __tablename__ = "amd_target_enrollment"

    id: str = Field(default_factory=generate_id, primary_key=True)
    host: str = Field(index=True)
    user: str
    port: int
    pinned_host_key: str
    identity_file_reference: str
    created_at: datetime = Field(default_factory=utc_now)


class AmdInstallationRow(SQLModel, table=True):
    __tablename__ = "amd_installation"
    __table_args__ = (
        UniqueConstraint("id", "placement", name="uq_amd_installation_id_placement"),
    )

    id: str = Field(default_factory=generate_id, primary_key=True)
    placement: str = Field(index=True)
    target_id: str | None = Field(default=None, foreign_key="amd_target_enrollment.id", index=True)
    # This is a durable, user-selected WSL distribution reference, not a
    # filesystem path, endpoint, credential, or live target observation.
    # Private SSH rows retain ``target_id``; Local WSL rows use this field.
    local_wsl_distribution: str | None = Field(default=None, index=True)
    profile_id: str = Field(index=True)
    profile_digest: str = Field(index=True)
    desired_presence: bool = Field(default=True, index=True)
    lifecycle_state: str = Field(default="active", index=True)
    revision: int = Field(default=0)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class AmdComponentGenerationRow(SQLModel, table=True):
    __tablename__ = "amd_component_generation"
    __table_args__ = (
        UniqueConstraint(
            "installation_id",
            "capability",
            "manifest_digest",
            name="uq_amd_component_generation_identity",
        ),
    )

    id: str = Field(default_factory=generate_id, primary_key=True)
    installation_id: str = Field(foreign_key="amd_installation.id", index=True)
    capability: str = Field(index=True)
    manifest_digest: str = Field(index=True)
    lifecycle_state: str = Field(default="staging", index=True)
    phase: str = Field(default="planned", index=True)
    error_code: str | None = Field(default=None, index=True)
    attestation_reference: str | None = None
    revision: int = Field(default=0)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
