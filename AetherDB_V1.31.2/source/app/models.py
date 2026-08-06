"""Pydantic data models for the Worldview Database API."""
from __future__ import annotations
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator
from typing import Any, Literal, Optional, List
import json
import re
from urllib.parse import urlparse

class EntityCreate(BaseModel):
    entity_type: str = "character"
    _valid_types = {"character", "faction", "location", "rule", "event", "item", "concept", "system"}
    _field_re = re.compile(r"^[a-zA-Z_]+$")
    title: str
    content: str = ""
    full_content: Optional[str] = None
    ai_summary: Optional[str] = None
    tags: List[str] = []
    timeline_year: Optional[int] = None
    timeline_era: Optional[str] = None
    importance: int = 5
    references: List[str] = []
    book_id: Optional[str] = None


    # V-010: Input validation
    @classmethod
    def validate_entity_type(cls, v):
        if v and v not in cls._valid_types:
            raise ValueError(f"Invalid entity_type: {v}")
        return v

    @classmethod
    def validate_title(cls, v):
        if v and len(v) > 500:
            raise ValueError("Title too long (max 500)")
        if v and len(v) < 1:
            raise ValueError("Title too short")
        return v


class EntityUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    full_content: Optional[str] = None
    ai_summary: Optional[str] = None
    tags: Optional[List[str]] = None
    timeline_year: Optional[int] = None
    timeline_era: Optional[str] = None
    importance: Optional[int] = None
    references: Optional[List[str]] = None

class RelationCreate(BaseModel):
    source_id: str
    target_id: str
    relation_type: str
    description: Optional[str] = None

class SearchQuery(BaseModel):
    keyword: str
    _max_keyword = 200
    entity_type: Optional[str] = None
    tags: Optional[List[str]] = None
    fuzzy: bool = True
    limit: int = 20
    book_id: Optional[str] = None

# ============================================================
# 数据模型 - LLM导入
# ============================================================
class ImportPreviewEntity(BaseModel):
    title: str
    type: str = "concept"
    content: str = ""
    tags: list[str] = Field(default_factory=list)
    importance: int = 3

class ImportPreviewRelation(BaseModel):
    source: str
    target: str
    relation_type: str = "related_to"
    description: str = ""

class ImportPreviewRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1_500_000)
    extractor_config: Optional[dict] = None

class ImportConfirmRequest(BaseModel):
    entities: list[ImportPreviewEntity]
    relations: list[ImportPreviewRelation] = Field(default_factory=list)


IMPORT_MODES = {"auto", "quick_notes", "chapters", "full_book", "world_setting", "entity_data"}


class ImportTaskCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    database_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    book_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    text: str = Field(min_length=1, max_length=1_500_000)
    mode: Literal["auto", "quick_notes", "chapters", "full_book", "world_setting", "entity_data"] = "auto"
    source_format: Literal["auto", "text", "markdown", "html"] = "auto"
    file_refs: list[str] = Field(default_factory=list, max_length=16)
    options: dict[str, Any] = Field(default_factory=dict)

    @field_validator("file_refs")
    @classmethod
    def validate_file_refs(cls, values: list[str]) -> list[str]:
        for value in values:
            if not re.fullmatch(r"[A-Za-z0-9._:-]{1,160}", value):
                raise ValueError("file_refs must contain opaque server-side identifiers")
        return values

    @field_validator("options")
    @classmethod
    def validate_options(cls, value: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "language", "default_entity_type", "chapter_pattern",
            "analyze_after_confirm", "analysis_mode",
        }
        unknown = set(value) - allowed
        if unknown:
            raise ValueError("unsupported import option")
        if len(json.dumps(value, ensure_ascii=False)) > 4096:
            raise ValueError("import options are too large")
        if "analyze_after_confirm" in value and not isinstance(value["analyze_after_confirm"], bool):
            raise ValueError("analyze_after_confirm must be boolean")
        if value.get("analysis_mode") not in {None, "local_rules", "cloud_model"}:
            raise ValueError("unsupported analysis_mode")
        if value.get("analyze_after_confirm") and not value.get("analysis_mode"):
            raise ValueError("analysis_mode is required when automatic analysis is enabled")
        return value


class AnalysisPreferencesUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_mode: Literal["ask", "local_rules", "cloud_model"]


class ImportTaskAnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    analysis_mode: Literal["local_rules", "cloud_model"] | None = None


class ProviderCredentialUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_key: SecretStr = Field(min_length=1, max_length=8192)

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, value: SecretStr) -> SecretStr:
        secret = value.get_secret_value()
        if any(ord(character) < 32 or ord(character) == 127 for character in secret):
            raise ValueError("api_key contains control characters")
        return value


class CloudProviderQuickSetup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_url: str = Field(min_length=1, max_length=512)
    api_key: SecretStr = Field(min_length=1, max_length=8192)

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        value = value.strip()
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("cloud model base_url must use https")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("base_url must not contain credentials, query, or fragment")
        path = parsed.path.rstrip("/")
        for endpoint in ("/chat/completions", "/responses", "/models"):
            if path.lower().endswith(endpoint):
                path = path[: -len(endpoint)].rstrip("/")
                break
        return parsed._replace(path=path).geturl().rstrip("/")

    _validate_api_key = field_validator("api_key")(ProviderCredentialUpdate.validate_api_key.__func__)


class ImportTaskEntitySelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str = Field(pattern=r"^imp-[a-f0-9]{16}-\d{4}$")
    title: str = Field(min_length=1, max_length=500)
    type: Literal["character", "faction", "location", "rule", "event", "item", "concept", "system"] = "concept"
    content: str = Field(default="", max_length=200_000)
    tags: list[str] = Field(default_factory=list, max_length=100)
    importance: int = Field(default=3, ge=1, le=10)

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, tags: list[str]) -> list[str]:
        cleaned = []
        for tag in tags:
            tag = tag.strip()
            if not tag or len(tag) > 100 or re.search(r"[\x00-\x1f\x7f]", tag):
                raise ValueError("invalid import tag")
            if tag not in cleaned:
                cleaned.append(tag)
        return cleaned


class ImportTaskChapterSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str = Field(pattern=r"^imp-ch-[a-f0-9]{12}-\d{4}$")
    title: str = Field(min_length=1, max_length=500)
    content: str = Field(default="", max_length=1_500_000)


class ImportTaskRelationSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str = Field(pattern=r"^imp-rel-[a-f0-9]{16}-\d{4}$")
    source: str = Field(min_length=1, max_length=500)
    target: str = Field(min_length=1, max_length=500)
    relation_type: str = Field(default="related_to", min_length=1, max_length=80)
    description: str = Field(default="", max_length=2000)


class ImportTaskConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preview_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    entity_selections: list[ImportTaskEntitySelection] = Field(default_factory=list, max_length=500)
    chapter_selections: list[ImportTaskChapterSelection] = Field(default_factory=list, max_length=5000)
    relation_selections: list[ImportTaskRelationSelection] = Field(default_factory=list, max_length=1000)

    @model_validator(mode="after")
    def validate_selection(self):
        if bool(self.entity_selections) == bool(self.chapter_selections):
            raise ValueError("select either entities or chapters")
        values = self.entity_selections or self.chapter_selections
        ids = [item.candidate_id for item in values]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate import candidate")
        relation_ids = [item.candidate_id for item in self.relation_selections]
        if len(relation_ids) != len(set(relation_ids)):
            raise ValueError("duplicate import relation candidate")
        return self


TEMPORAL_CONFIDENCE = {"confirmed", "inferred", "uncertain", "conflicting"}


class TemporalAnchorCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    database_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    book_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    timeline_id: Optional[str] = Field(default=None, pattern=r"^[A-Za-z0-9:._-]{2,128}$")
    branch_id: Optional[str] = Field(default=None, max_length=128, pattern=r"^[A-Za-z0-9:._-]{1,128}$")
    anchor_type: Literal["exact", "range", "chapter", "event", "phase", "relative", "order_only", "unknown"]
    label: str = Field(min_length=1, max_length=300)
    chapter_id: Optional[str] = Field(default=None, max_length=128)
    event_id: Optional[str] = Field(default=None, max_length=128)
    phase_id: Optional[str] = Field(default=None, max_length=128)
    absolute_time: Optional[str] = Field(default=None, max_length=160)
    order_hint: Optional[float] = Field(default=None, ge=-1_000_000_000, le=1_000_000_000)
    confidence: Literal["confirmed", "inferred", "uncertain", "conflicting"] = "confirmed"

    @model_validator(mode="after")
    def validate_anchor_reference(self):
        required = {
            "exact": self.absolute_time,
            "range": self.absolute_time,
            "chapter": self.chapter_id,
            "event": self.event_id,
            "phase": self.phase_id,
        }
        if self.anchor_type in required and not required[self.anchor_type]:
            raise ValueError("anchor type requires its matching reference")
        return self


class TemporalRelationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    database_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    book_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    timeline_id: str = Field(pattern=r"^[A-Za-z0-9:._-]{2,128}$")
    branch_id: Optional[str] = Field(default=None, max_length=128, pattern=r"^[A-Za-z0-9:._-]{1,128}$")
    source_anchor_id: str = Field(pattern=r"^TA_[A-F0-9]{24}$")
    relation_type: Literal["before", "after", "simultaneous", "overlaps", "approximately_before", "approximately_after", "unknown"]
    target_anchor_id: str = Field(pattern=r"^TA_[A-F0-9]{24}$")
    confidence: Literal["confirmed", "inferred", "uncertain", "conflicting"] = "confirmed"
    source_chapter_id: Optional[str] = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def reject_self_relation(self):
        if self.source_anchor_id == self.target_anchor_id:
            raise ValueError("temporal relation cannot reference the same anchor")
        return self


class ChapterTemporalContextUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    database_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    book_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    timeline_id: Optional[str] = Field(default=None, pattern=r"^[A-Za-z0-9:._-]{2,128}$")
    branch_id: Optional[str] = Field(default=None, max_length=128, pattern=r"^[A-Za-z0-9:._-]{1,128}$")
    anchor_id: Optional[str] = Field(default=None, pattern=r"^TA_[A-F0-9]{24}$")
    phase_id: Optional[str] = Field(default=None, max_length=128)
    viewpoint_entity_id: Optional[str] = Field(default=None, max_length=128)
    include_future_knowledge: bool = False


class EntityStateSegmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    database_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    book_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    entity_id: str = Field(min_length=1, max_length=128)
    timeline_id: Optional[str] = Field(default=None, pattern=r"^[A-Za-z0-9:._-]{2,128}$")
    branch_id: Optional[str] = Field(default=None, max_length=128, pattern=r"^[A-Za-z0-9:._-]{1,128}$")
    valid_from_anchor_id: Optional[str] = Field(default=None, pattern=r"^TA_[A-F0-9]{24}$")
    valid_to_anchor_id: Optional[str] = Field(default=None, pattern=r"^TA_[A-F0-9]{24}$")
    state_type: Literal[
        "physical", "realm", "location", "identity", "faction", "injury", "equipment",
        "ownership", "relationship", "psychological", "behavior_logic", "knowledge", "goal", "life_status"
    ]
    state_payload: dict[str, Any]
    source_chapter_id: Optional[str] = Field(default=None, max_length=128)
    source_event_id: Optional[str] = Field(default=None, max_length=128)
    confidence: Literal["confirmed", "inferred", "uncertain", "conflicting"] = "confirmed"
    supersedes_segment_id: Optional[str] = Field(default=None, pattern=r"^ES_[A-F0-9]{24}$")

    @field_validator("state_payload")
    @classmethod
    def validate_state_payload(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not value or len(json.dumps(value, ensure_ascii=False)) > 32_000:
            raise ValueError("state payload must be non-empty and at most 32 KB")
        return value


class TimelineCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    database_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    book_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=200)
    parent_timeline_id: Optional[str] = Field(default=None, pattern=r"^[A-Za-z0-9:._-]{2,128}$")
    divergence_anchor_id: Optional[str] = Field(default=None, pattern=r"^TA_[A-F0-9]{24}$")
    status: Literal["active", "draft", "archived"] = "active"

    @model_validator(mode="after")
    def validate_divergence(self):
        if bool(self.parent_timeline_id) != bool(self.divergence_anchor_id):
            raise ValueError("child timeline requires both parent and divergence anchor")
        return self


class TemporalEventMetadataUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    database_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    book_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    timeline_id: str = Field(pattern=r"^[A-Za-z0-9:._-]{2,128}$")
    branch_id: Optional[str] = Field(default=None, max_length=128, pattern=r"^[A-Za-z0-9:._-]{1,128}$")
    world_anchor_id: Optional[str] = Field(default=None, pattern=r"^TA_[A-F0-9]{24}$")
    subjective_sequence: Optional[float] = Field(default=None, ge=-1_000_000_000, le=1_000_000_000)
    viewpoint_entity_id: Optional[str] = Field(default=None, max_length=128)
    causal_parent_event_id: Optional[str] = Field(default=None, max_length=128)


class ProviderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{1,63}$")
    display_name: str = Field(min_length=1, max_length=80)
    provider_type: str = Field(min_length=1, max_length=40)
    base_url: str = Field(min_length=1, max_length=512)
    api_format: str = Field(min_length=1, max_length=40)
    credential_ref: Optional[str] = Field(default=None, max_length=128)
    models_endpoint: Optional[str] = Field(default=None, max_length=256)
    enabled: bool = True
    supports_model_discovery: bool = False

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("base_url must use http or https")
        if parsed.username or parsed.password:
            raise ValueError("base_url must not contain credentials")
        return value.rstrip("/")

    @field_validator("models_endpoint")
    @classmethod
    def validate_models_endpoint(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        if not value.startswith("/") or "://" in value:
            raise ValueError("models_endpoint must be a relative path")
        return value

    @field_validator("credential_ref")
    @classmethod
    def validate_credential_ref(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        if not re.fullmatch(r"(?:env|secure):[A-Za-z_][A-Za-z0-9_.-]{0,119}", value):
            raise ValueError("credential_ref must use env: or secure:")
        return value


class ProviderUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: Optional[str] = Field(default=None, min_length=1, max_length=80)
    provider_type: Optional[str] = Field(default=None, min_length=1, max_length=40)
    base_url: Optional[str] = Field(default=None, min_length=1, max_length=512)
    api_format: Optional[str] = Field(default=None, min_length=1, max_length=40)
    credential_ref: Optional[str] = Field(default=None, max_length=128)
    models_endpoint: Optional[str] = Field(default=None, max_length=256)
    enabled: Optional[bool] = None
    supports_model_discovery: Optional[bool] = None

    _validate_base_url = field_validator("base_url")(ProviderCreate.validate_base_url.__func__)
    _validate_models_endpoint = field_validator("models_endpoint")(ProviderCreate.validate_models_endpoint.__func__)
    _validate_credential_ref = field_validator("credential_ref")(ProviderCreate.validate_credential_ref.__func__)


class ModelProfileCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9:._-]{1,127}$")
    provider_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{1,63}$")
    provider_model_name: str = Field(min_length=1, max_length=256)
    display_name: str = Field(min_length=1, max_length=100)
    model_type: str = Field(min_length=1, max_length=40)
    enabled: bool = True
    context_length: Optional[int] = Field(default=None, ge=1024, le=10_000_000)
    max_output_tokens: Optional[int] = Field(default=None, ge=1, le=1_000_000)
    supports_streaming: bool = False
    supports_tools: bool = False
    supports_json_mode: bool = False
    cost_level: str = Field(default="unknown", max_length=40)
    privacy_level: str = Field(default="cloud_upload", max_length=40)

    @field_validator("provider_model_name", "display_name")
    @classmethod
    def reject_control_characters(cls, value: str) -> str:
        value = value.strip()
        if re.search(r"[\x00-\x1f\x7f]", value):
            raise ValueError("control characters are not allowed")
        return value


class ModelProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    provider_model_name: Optional[str] = Field(default=None, min_length=1, max_length=256)
    display_name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    model_type: Optional[str] = Field(default=None, min_length=1, max_length=40)
    enabled: Optional[bool] = None
    context_length: Optional[int] = Field(default=None, ge=1024, le=10_000_000)
    max_output_tokens: Optional[int] = Field(default=None, ge=1, le=1_000_000)
    supports_streaming: Optional[bool] = None
    supports_tools: Optional[bool] = None
    supports_json_mode: Optional[bool] = None
    cost_level: Optional[str] = Field(default=None, max_length=40)
    privacy_level: Optional[str] = Field(default=None, max_length=40)

    _reject_provider_model_control_characters = field_validator("provider_model_name")(
        ModelProfileCreate.reject_control_characters.__func__
    )
    _reject_display_name_control_characters = field_validator("display_name")(
        ModelProfileCreate.reject_control_characters.__func__
    )


from services.model_execution.task_types import accepted_task_types


TASK_TYPES = accepted_task_types()


class ModelTaskBindingCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9:._-]{1,127}$")
    scope_type: str
    scope_id: Optional[str] = Field(default=None, max_length=256)
    task_type: str
    target_id: str = Field(pattern=r"^[a-z0-9][a-z0-9:._-]{1,127}$")
    priority: int = Field(default=0, ge=-1000, le=1000)
    enabled: bool = True

    @field_validator("scope_type")
    @classmethod
    def validate_scope_type(cls, value: str) -> str:
        if value not in {"global", "database", "book", "session"}:
            raise ValueError("unsupported binding scope")
        return value

    @field_validator("task_type")
    @classmethod
    def validate_task_type(cls, value: str) -> str:
        if value not in TASK_TYPES:
            raise ValueError("unsupported task type")
        return value


class ModelTaskBindingUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_id: Optional[str] = Field(default=None, pattern=r"^[a-z0-9][a-z0-9:._-]{1,127}$")
    priority: Optional[int] = Field(default=None, ge=-1000, le=1000)
    enabled: Optional[bool] = None


class TokenBudget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_context_tokens: int = Field(ge=1024, le=10_000_000)
    reserved_instruction: int = Field(ge=0)
    reserved_current_text: int = Field(ge=0)
    reserved_evidence: int = Field(ge=1)
    reserved_output: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_total(self):
        used = (
            self.reserved_instruction
            + self.reserved_current_text
            + self.reserved_evidence
            + self.reserved_output
        )
        if used > self.total_context_tokens:
            raise ValueError("token budget exceeds total context")
        return self


class MediaEvidenceBudget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_items: int = Field(default=4, ge=0, le=32)
    allowed_modalities: list[Literal["image", "audio", "video"]] = Field(
        default_factory=lambda: ["image", "audio", "video"],
        max_length=3,
    )

    @field_validator("allowed_modalities")
    @classmethod
    def modalities_must_be_unique(cls, values):
        if len(values) != len(set(values)):
            raise ValueError("duplicate media modality")
        return values


class ModelMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    role: str = Field(pattern=r"^(system|user|assistant)$")
    content: str = Field(min_length=1, max_length=50_000)


class ModelExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    task_id: Optional[str] = Field(default=None, pattern=r"^[A-Za-z0-9:._-]{1,128}$")
    task_type: str
    database_id: str = Field(min_length=1, max_length=100)
    book_id: Optional[str] = Field(default=None, max_length=100)
    chapter_id: Optional[str] = Field(default=None, max_length=100)
    session_id: Optional[str] = Field(default=None, max_length=128)
    user_selected_model_id: Optional[str] = Field(default=None, max_length=128)
    recovery_ticket: Optional[str] = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    data_manifest_id: Optional[str] = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    selected_asset_ids: list[str] = Field(default_factory=list, max_length=32)
    messages: list[ModelMessage] = Field(min_length=1, max_length=100)
    requires_json: bool = False
    context_task_id: Optional[str] = Field(default=None, pattern=r"^[A-Za-z0-9:._-]{1,128}$")
    evidence_budget: Optional[TokenBudget] = None
    evidence_media_budget: Optional[MediaEvidenceBudget] = None

    _validate_execute_task_type = field_validator("task_type")(
        ModelTaskBindingCreate.validate_task_type.__func__
    )

    @field_validator("selected_asset_ids")
    @classmethod
    def selected_assets_must_be_unique_and_safe(cls, values):
        if len(values) != len(set(values)):
            raise ValueError("duplicate selected asset")
        if any(
            not value
            or len(value) > 128
            or not re.fullmatch(r"[A-Za-z0-9:._-]+", value)
            for value in values
        ):
            raise ValueError("invalid selected asset id")
        return values


class ModelRecoveryConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    model_profile_id: str = Field(min_length=1, max_length=128)


class ContextNeed(BaseModel):
    model_config = ConfigDict(extra="forbid")

    context_type: str = Field(min_length=1, max_length=64)
    query: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=300)
    required: bool = False
    target_type: Optional[Literal[
        "database",
        "book",
        "content_group",
        "chapter",
        "entity",
        "entity_state_segment",
        "event",
        "relation",
        "timeline",
        "temporal_anchor",
        "branch",
    ]] = None
    target_id: Optional[str] = Field(default=None, min_length=1, max_length=160)
    media_modalities: list[Literal["image", "audio", "video"]] = Field(
        default_factory=list,
        max_length=3,
    )

    @model_validator(mode="after")
    def validate_media_scope(self):
        if bool(self.target_type) != bool(self.target_id):
            raise ValueError("target_type and target_id must be provided together")
        if len(self.media_modalities) != len(set(self.media_modalities)):
            raise ValueError("duplicate media modality")
        return self


class ContextMapRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: Optional[str] = Field(default=None, pattern=r"^[A-Za-z0-9:._-]{1,128}$")
    task_type: str
    database_id: str = Field(min_length=1, max_length=100)
    book_id: str = Field(min_length=1, max_length=100)
    timeline_id: Optional[str] = Field(default=None, pattern=r"^[A-Za-z0-9:._-]{2,128}$")
    branch_id: Optional[str] = Field(default=None, max_length=128, pattern=r"^[A-Za-z0-9:._-]{1,128}$")
    chapter_id: Optional[str] = Field(default=None, max_length=128)
    language_code: Optional[str] = Field(
        default=None,
        min_length=2,
        max_length=35,
        pattern=r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8}){0,3}$",
    )
    anchor_id: Optional[str] = Field(default=None, pattern=r"^TA_[A-F0-9]{24}$")
    phase_id: Optional[str] = Field(default=None, max_length=128)
    viewpoint_entity_id: Optional[str] = Field(default=None, max_length=128)
    include_future_knowledge: bool = False
    needs: list[ContextNeed] = Field(min_length=1, max_length=24)

    _validate_context_task_type = field_validator("task_type")(
        ModelTaskBindingCreate.validate_task_type.__func__
    )


class ContextApprovalItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str = Field(pattern=r"^ctx-[a-f0-9]{32}$")
    approved: bool


class ContextApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ContextApprovalItem] = Field(min_length=1, max_length=64)

    @field_validator("items")
    @classmethod
    def candidate_ids_must_be_unique(cls, items):
        ids = [item.candidate_id for item in items]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate candidate_id")
        return items


class EvidencePackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    budget: TokenBudget
    media_budget: MediaEvidenceBudget = Field(default_factory=MediaEvidenceBudget)
