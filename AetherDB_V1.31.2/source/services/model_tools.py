"""Allowlisted model tools executed inside server-owned scope boundaries."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from services.context_engine import build_evidence_pack
from services.database_registry import _get_registry_conn
from services.db import get_db
from services.model_data_boundary import (
    ModelDataBoundaryError,
    PermissionTier,
    content_hash,
    get_model_data_policy,
    validate_selected_assets,
)
from services.model_registry import get_model_profile


class ModelToolError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 409):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class SearchEntitiesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=200)
    limit: int = Field(default=8, ge=1, le=20)


class EntityToolItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_id: str
    entity_type: str
    title: str
    summary: str


class SearchEntitiesOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[EntityToolItem] = Field(max_length=20)


class ReadApprovedContextInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_ids: list[str] = Field(min_length=1, max_length=20)


class ApprovedContextToolItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    source_type: str
    source_id: str
    content: str
    modality: str


class ReadApprovedContextOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ApprovedContextToolItem] = Field(max_length=20)


class ListSelectedAssetsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SelectedAssetToolItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: str
    modality: str
    mime_type: str
    original_filename: str
    lifecycle_status: str


class ListSelectedAssetsOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[SelectedAssetToolItem] = Field(max_length=32)


class ProposedEntity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_type: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(default="", max_length=20_000)


class ProposedRelation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_ref: str = Field(min_length=1, max_length=200)
    target_ref: str = Field(min_length=1, max_length=200)
    relation_type: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=2_000)


class ProposeChangeSetInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entities: list[ProposedEntity] = Field(default_factory=list, max_length=50)
    relations: list[ProposedRelation] = Field(default_factory=list, max_length=100)


class ProposeChangeSetOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal_id: str
    entity_count: int
    relation_count: int
    write_status: str
    next_step: str


@dataclass(frozen=True)
class ToolExecutionContext:
    task_id: str
    model_profile_id: str
    database_id: str
    book_id: str | None
    chapter_id: str | None
    owner_id: str
    context_task_id: str | None = None
    selected_asset_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class _ToolDefinition:
    name: str
    description: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    handler: Callable[[ToolExecutionContext, BaseModel], dict[str, Any]]

    @property
    def handler_id(self) -> str:
        return f"aetherdb.controlled.{self.name}.v1"


class _EvidenceBudget:
    reserved_evidence = 25_000


def _escaped_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _require_book(context: ToolExecutionContext) -> str:
    if not context.book_id:
        raise ModelToolError(
            "TOOL_BOOK_SCOPE_REQUIRED",
            "This tool requires a server-owned book scope.",
            400,
        )
    return context.book_id


def _search_entities(context: ToolExecutionContext, request: SearchEntitiesInput) -> dict:
    book_id = _require_book(context)
    escaped = _escaped_like(request.query)
    db = get_db(context.database_id)
    try:
        rows = db.execute(
            """SELECT entity_id,entity_type,title,ai_summary,content
                 FROM entities
                WHERE book_id=? AND is_active=1
                  AND (title=? OR title LIKE ? ESCAPE '\\'
                       OR content LIKE ? ESCAPE '\\')
                ORDER BY CASE WHEN title=? THEN 0 ELSE 1 END,
                         importance DESC,title
                LIMIT ?""",
            (
                book_id,
                request.query,
                f"%{escaped}%",
                f"%{escaped}%",
                request.query,
                request.limit,
            ),
        ).fetchall()
    finally:
        db.close()
    return {
        "items": [
            {
                "entity_id": row["entity_id"],
                "entity_type": row["entity_type"],
                "title": row["title"],
                "summary": " ".join(
                    (row["ai_summary"] or row["content"] or "").split()
                )[:500],
            }
            for row in rows
        ]
    }


def _read_approved_context(
    context: ToolExecutionContext,
    request: ReadApprovedContextInput,
) -> dict:
    if not context.context_task_id:
        raise ModelToolError(
            "TOOL_CONTEXT_SCOPE_REQUIRED",
            "No approved context task is attached to this execution.",
            400,
        )
    pack = build_evidence_pack(
        context.database_id,
        context.context_task_id,
        context.owner_id,
        _EvidenceBudget(),
        {"max_items": 32, "allowed_modalities": ["image", "audio", "video"]},
    )
    requested = tuple(dict.fromkeys(request.candidate_ids))
    approved = {item["candidate_id"]: item for item in pack["items"]}
    if any(candidate_id not in approved for candidate_id in requested):
        raise ModelToolError(
            "TOOL_CONTEXT_NOT_APPROVED",
            "A requested candidate is not approved in the server-owned context task.",
        )
    return {
        "items": [
            {
                "candidate_id": approved[candidate_id]["candidate_id"],
                "source_type": approved[candidate_id]["source_type"],
                "source_id": approved[candidate_id]["source_id"],
                "content": approved[candidate_id]["content"],
                "modality": approved[candidate_id]["modality"],
            }
            for candidate_id in requested
        ]
    }


def _list_selected_assets(
    context: ToolExecutionContext,
    _: ListSelectedAssetsInput,
) -> dict:
    asset_ids = validate_selected_assets(
        context.database_id,
        context.book_id,
        context.selected_asset_ids,
    )
    if not asset_ids:
        return {"items": []}
    placeholders = ",".join("?" for _ in asset_ids)
    db = get_db(context.database_id)
    try:
        rows = db.execute(
            f"""SELECT asset_id,modality,mime_type,original_filename,lifecycle_status
                  FROM media_assets
                 WHERE database_id=? AND book_id=? AND asset_id IN ({placeholders})
                 ORDER BY asset_id""",
            (context.database_id, context.book_id, *asset_ids),
        ).fetchall()
    finally:
        db.close()
    return {"items": [dict(row) for row in rows]}


def _propose_changeset(
    context: ToolExecutionContext,
    request: ProposeChangeSetInput,
) -> dict:
    _require_book(context)
    proposal_id = "proposal_" + content_hash(
        {
            "task_id": context.task_id,
            "database_id": context.database_id,
            "book_id": context.book_id,
            "chapter_id": context.chapter_id,
            "proposal": request.model_dump(),
        }
    )[:24]
    return {
        "proposal_id": proposal_id,
        "entity_count": len(request.entities),
        "relation_count": len(request.relations),
        "write_status": "not_applied",
        "next_step": "create_and_confirm_changeset",
    }


TOOL_DEFINITIONS = {
    definition.name: definition
    for definition in (
        _ToolDefinition(
            "search_entities",
            "Search active entities inside the server-owned book scope.",
            SearchEntitiesInput,
            SearchEntitiesOutput,
            _search_entities,
        ),
        _ToolDefinition(
            "read_approved_context",
            "Read only approved candidates from the attached context task.",
            ReadApprovedContextInput,
            ReadApprovedContextOutput,
            _read_approved_context,
        ),
        _ToolDefinition(
            "list_selected_assets",
            "List metadata for approved media explicitly selected by the user.",
            ListSelectedAssetsInput,
            ListSelectedAssetsOutput,
            _list_selected_assets,
        ),
        _ToolDefinition(
            "propose_changeset",
            "Validate a write proposal without applying it to formal data.",
            ProposeChangeSetInput,
            ProposeChangeSetOutput,
            _propose_changeset,
        ),
    )
}


def sync_tool_registry() -> None:
    conn = _get_registry_conn()
    try:
        for definition in TOOL_DEFINITIONS.values():
            conn.execute(
                """INSERT INTO model_tool_registry(
                       tool_name,permission_tier,handler_id,description,
                       input_schema_json,output_schema_json,enabled
                   ) VALUES (?,?,?,?,?,?,1)
                   ON CONFLICT(tool_name) DO UPDATE SET
                       permission_tier=excluded.permission_tier,
                       handler_id=excluded.handler_id,
                       description=excluded.description,
                       input_schema_json=excluded.input_schema_json,
                       output_schema_json=excluded.output_schema_json,
                       updated_at=CURRENT_TIMESTAMP""",
                (
                    definition.name,
                    PermissionTier.C_RESTRICTED_TOOLS.value,
                    definition.handler_id,
                    definition.description,
                    json.dumps(
                        definition.input_model.model_json_schema(),
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    json.dumps(
                        definition.output_model.model_json_schema(),
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                ),
            )
        conn.commit()
    finally:
        conn.close()


def list_registered_tools() -> list[dict]:
    sync_tool_registry()
    conn = _get_registry_conn()
    try:
        rows = conn.execute(
            "SELECT tool_name,permission_tier,description,input_schema_json,"
            "output_schema_json,enabled,updated_at FROM model_tool_registry "
            "ORDER BY tool_name"
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            **{
                key: value
                for key, value in dict(row).items()
                if key not in {"input_schema_json", "output_schema_json"}
            },
            "enabled": bool(row["enabled"]),
            "input_schema": json.loads(row["input_schema_json"]),
            "output_schema": json.loads(row["output_schema_json"]),
        }
        for row in rows
    ]


def set_model_tool_policy(
    model_profile_id: str,
    tool_name: str,
    *,
    enabled: bool,
    updated_by: str,
) -> dict:
    sync_tool_registry()
    profile = get_model_profile(model_profile_id)
    if not profile:
        raise ModelToolError("MODEL_NOT_FOUND", "Model profile was not found.", 404)
    conn = _get_registry_conn()
    try:
        tool = conn.execute(
            "SELECT tool_name FROM model_tool_registry WHERE tool_name=?",
            (tool_name,),
        ).fetchone()
        if not tool:
            raise ModelToolError("TOOL_NOT_REGISTERED", "Model tool is not registered.", 404)
        conn.execute(
            """INSERT INTO model_tool_policies(
                   model_profile_id,tool_name,enabled,updated_by
               ) VALUES (?,?,?,?)
               ON CONFLICT(model_profile_id,tool_name) DO UPDATE SET
                   enabled=excluded.enabled,updated_by=excluded.updated_by,
                   updated_at=CURRENT_TIMESTAMP""",
            (model_profile_id, tool_name, int(enabled), updated_by),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM model_tool_policies WHERE model_profile_id=? AND tool_name=?",
            (model_profile_id, tool_name),
        ).fetchone()
    finally:
        conn.close()
    result = dict(row)
    result["enabled"] = bool(result["enabled"])
    return result


def list_model_tool_policies(model_profile_id: str) -> list[dict]:
    sync_tool_registry()
    if not get_model_profile(model_profile_id):
        raise ModelToolError("MODEL_NOT_FOUND", "Model profile was not found.", 404)
    conn = _get_registry_conn()
    try:
        rows = conn.execute(
            """SELECT r.tool_name,r.permission_tier,r.description,r.enabled AS registry_enabled,
                      COALESCE(p.enabled,0) AS policy_enabled,p.updated_at
                 FROM model_tool_registry r
                 LEFT JOIN model_tool_policies p
                   ON p.tool_name=r.tool_name AND p.model_profile_id=?
                ORDER BY r.tool_name""",
            (model_profile_id,),
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            "tool_name": row["tool_name"],
            "permission_tier": row["permission_tier"],
            "description": row["description"],
            "registry_enabled": bool(row["registry_enabled"]),
            "policy_enabled": bool(row["policy_enabled"]),
            "updated_at": row["updated_at"],
        }
        for row in rows
    ]


def enabled_tool_specs(model_profile_id: str) -> list[dict]:
    """Return only explicitly enabled tools in Ollama/OpenAI function format."""
    if (
        get_model_data_policy(model_profile_id)["permission_tier"]
        != PermissionTier.C_RESTRICTED_TOOLS.value
    ):
        return []
    policies = {
        item["tool_name"]: item
        for item in list_model_tool_policies(model_profile_id)
        if item["registry_enabled"] and item["policy_enabled"]
    }
    specs = []
    for tool_name in sorted(policies):
        definition = TOOL_DEFINITIONS.get(tool_name)
        if definition is None:
            continue
        specs.append(
            {
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": definition.description,
                    "parameters": definition.input_model.model_json_schema(),
                },
            }
        )
    return specs


def _assert_tool_allowed(context: ToolExecutionContext, tool_name: str) -> _ToolDefinition:
    sync_tool_registry()
    definition = TOOL_DEFINITIONS.get(tool_name)
    if not definition:
        raise ModelToolError("TOOL_NOT_REGISTERED", "Model tool is not registered.", 404)
    profile = get_model_profile(context.model_profile_id)
    if not profile or not profile["enabled"]:
        raise ModelToolError("MODEL_UNAVAILABLE", "Model profile is unavailable.")
    if not profile["supports_tools"]:
        raise ModelToolError("MODEL_TOOLS_UNSUPPORTED", "Model profile does not support tools.")
    policy = get_model_data_policy(context.model_profile_id)
    if policy["permission_tier"] != PermissionTier.C_RESTRICTED_TOOLS.value:
        raise ModelToolError(
            "MODEL_TOOL_TIER_REQUIRED",
            "The model data policy does not permit controlled tools.",
        )
    conn = _get_registry_conn()
    try:
        row = conn.execute(
            """SELECT r.enabled AS registry_enabled,COALESCE(p.enabled,0) AS policy_enabled
                 FROM model_tool_registry r
                 LEFT JOIN model_tool_policies p
                   ON p.tool_name=r.tool_name AND p.model_profile_id=?
                WHERE r.tool_name=?""",
            (context.model_profile_id, tool_name),
        ).fetchone()
    finally:
        conn.close()
    if not row or not row["registry_enabled"] or not row["policy_enabled"]:
        raise ModelToolError("MODEL_TOOL_DENIED", "The requested model tool is not enabled.")
    return definition


def _record_tool_start(context: ToolExecutionContext, tool_name: str, arguments: object) -> str:
    execution_id = uuid.uuid4().hex
    conn = _get_registry_conn()
    try:
        conn.execute(
            """INSERT INTO model_tool_executions(
                   execution_id,task_id,model_profile_id,tool_name,database_id,
                   book_id,chapter_id,input_hash,status,created_at
               ) VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                execution_id,
                context.task_id,
                context.model_profile_id,
                tool_name,
                context.database_id,
                context.book_id,
                context.chapter_id,
                content_hash(arguments),
                "running",
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return execution_id


def _record_tool_finish(
    execution_id: str,
    *,
    status: str,
    output: object | None = None,
    error_code: str | None = None,
) -> None:
    conn = _get_registry_conn()
    try:
        conn.execute(
            """UPDATE model_tool_executions
                  SET output_hash=?,status=?,error_code=?,completed_at=?
                WHERE execution_id=?""",
            (
                content_hash(output) if output is not None else None,
                status,
                error_code,
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
                execution_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def execute_registered_tool(
    context: ToolExecutionContext,
    tool_name: str,
    arguments: dict[str, Any],
) -> dict:
    definition = _assert_tool_allowed(context, tool_name)
    execution_id = _record_tool_start(context, tool_name, arguments)
    try:
        validated_input = definition.input_model.model_validate(arguments)
        output = definition.handler(context, validated_input)
        validated_output = definition.output_model.model_validate(output).model_dump()
    except ValidationError as exc:
        _record_tool_finish(
            execution_id,
            status="rejected",
            error_code="TOOL_SCHEMA_INVALID",
        )
        raise ModelToolError(
            "TOOL_SCHEMA_INVALID",
            "Model tool input or output failed schema validation.",
            400,
        ) from exc
    except (ModelToolError, ModelDataBoundaryError) as exc:
        _record_tool_finish(
            execution_id,
            status="rejected",
            error_code=exc.code,
        )
        if isinstance(exc, ModelToolError):
            raise
        raise ModelToolError(exc.code, str(exc), exc.status_code) from exc
    except Exception as exc:
        _record_tool_finish(
            execution_id,
            status="failed",
            error_code="TOOL_EXECUTION_FAILED",
        )
        raise ModelToolError(
            "TOOL_EXECUTION_FAILED",
            "Controlled model tool execution failed.",
            500,
        ) from exc
    _record_tool_finish(execution_id, status="completed", output=validated_output)
    return {
        "tool_name": tool_name,
        "execution_id": execution_id,
        "result": validated_output,
    }
