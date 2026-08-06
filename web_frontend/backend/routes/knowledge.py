from __future__ import annotations

import json
from pathlib import PurePosixPath
import shutil
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from agent_factory.document_processing import accepted_file_extensions, document_processing_capabilities
from agent_factory.factory_graph.frontend_bridge.runtime_adapter_types import SYSTEM_CHAT_PACKAGE_ID
from agent_factory.knowledge_system.identifiers import new_source_id
from agent_factory.paths import factory_artifact_path
from web_frontend.backend.runtime_bridge import RuntimeBridge
from web_frontend.backend.routes.utils import optional_package, optional_resource_mode, resource_command


def create_knowledge_router(runtime_bridge: RuntimeBridge) -> APIRouter:
    router = APIRouter(prefix="/api/knowledge")

    @router.get("/capabilities")
    async def get_knowledge_capabilities():
        return document_processing_capabilities().to_public_dict()

    @router.get("/sources")
    async def list_knowledge_sources(package_id: str | None = None, resource_mode: str | None = None):
        event = await resource_command(
            runtime_bridge,
            "knowledge_manage",
            {"action": "list_sources", **optional_package(package_id), **optional_resource_mode(resource_mode)},
            {"knowledge_sources_listed"},
        )
        return {"event": event}

    @router.post("/sources")
    async def create_knowledge_source(payload: dict[str, Any]):
        event = await resource_command(
            runtime_bridge,
            "knowledge_manage",
            {"action": "confirm_source", **payload},
            {"knowledge_source_registered"},
            timeout_seconds=120.0,
        )
        return {"event": event}

    @router.post("/sources/upload")
    async def upload_knowledge_source(
        source: str = Form(...),
        package_id: str | None = Form(default=None),
        resource_mode: str | None = Form(default=None),
        files: list[UploadFile] = File(...),
    ):
        source_payload = _source_payload_from_form(source)
        unsupported_files = _unsupported_upload_files(files)
        if unsupported_files:
            capabilities = document_processing_capabilities()
            raise HTTPException(
                status_code=415,
                detail={
                    "message": "One or more files cannot be processed by the configured knowledge parsers.",
                    "unsupported_files": unsupported_files,
                    "accepted_extensions": list(capabilities.knowledge_extensions),
                },
            )
        resolved_package_id = package_id or str(source_payload.get("package_id") or "").strip() or SYSTEM_CHAT_PACKAGE_ID
        display_name = str(source_payload.get("display_name") or "uploaded_source").strip()
        source_id = new_source_id()
        upload_root = _knowledge_upload_root(resolved_package_id, source_id)
        if upload_root.exists():
            shutil.rmtree(upload_root)
        upload_root.mkdir(parents=True, exist_ok=True)
        saved = []
        for upload in files:
            relative_path = _safe_upload_relative_path(upload.filename or "uploaded_file")
            target = upload_root / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            size_bytes = 0
            with target.open("wb") as handle:
                while chunk := await upload.read(1024 * 1024):
                    size_bytes += len(chunk)
                    handle.write(chunk)
            saved.append({"path": relative_path.as_posix(), "size_bytes": size_bytes, "content_type": upload.content_type})
        source_payload.pop("kind", None)
        metadata = dict(source_payload.get("metadata") or {})
        metadata.update(
            {
                "display_name": display_name,
                "managed_upload": True,
                "original_uri": f"upload://{source_id}",
                "upload_file_count": len(saved),
                "upload_files": saved[:50],
            }
        )
        source_payload.update(
            {
                "source_id": source_id,
                "source_type": "filesystem",
                "display_name": display_name,
                "uri": str(upload_root),
                "original_uri": f"upload://{source_id}",
                "metadata": metadata,
            }
        )
        event = await resource_command(
            runtime_bridge,
            "knowledge_manage",
            {
                "action": "confirm_source",
                "source": source_payload,
                **optional_package(package_id),
                **optional_resource_mode(resource_mode),
            },
            {"knowledge_source_registered"},
            timeout_seconds=120.0,
        )
        return {"event": event}

    @router.delete("/sources/{source_id}")
    async def delete_knowledge_source(source_id: str, package_id: str | None = None, resource_mode: str | None = None):
        event = await resource_command(
            runtime_bridge,
            "knowledge_manage",
            {"action": "remove_source", "source_id": source_id, **optional_package(package_id), **optional_resource_mode(resource_mode)},
            {"knowledge_source_removed"},
        )
        return {"event": event}

    @router.post("/sources/{source_id}/reindex")
    async def reindex_knowledge_source(source_id: str, package_id: str | None = None, resource_mode: str | None = None):
        event = await resource_command(
            runtime_bridge,
            "knowledge_manage",
            {"action": "reindex", "source_id": source_id, **optional_package(package_id), **optional_resource_mode(resource_mode)},
            {"knowledge_source_reindex_requested"},
            timeout_seconds=120.0,
        )
        return {"event": event}

    @router.get("/documents")
    async def list_knowledge_documents(source_id: str, package_id: str | None = None, resource_mode: str | None = None):
        event = await resource_command(
            runtime_bridge,
            "knowledge_manage",
            {"action": "list_documents", "source_id": source_id, **optional_package(package_id), **optional_resource_mode(resource_mode)},
            {"knowledge_documents_listed"},
        )
        return {"event": event}

    @router.get("/search")
    async def search_knowledge(
        query: str,
        source_id: str | None = None,
        package_id: str | None = None,
        resource_mode: str | None = None,
    ):
        payload = {"action": "search", "query": query, **optional_package(package_id), **optional_resource_mode(resource_mode)}
        if source_id:
            payload["source_id"] = source_id
        event = await resource_command(runtime_bridge, "knowledge_manage", payload, {"knowledge_search_completed"})
        return {"event": event}

    @router.get("/document")
    async def read_knowledge_document(document_id: str, package_id: str | None = None, resource_mode: str | None = None):
        event = await resource_command(
            runtime_bridge,
            "knowledge_manage",
            {"action": "read", "document_id": document_id, **optional_package(package_id), **optional_resource_mode(resource_mode)},
            {"knowledge_document_read"},
        )
        return {"event": event}

    return router


def _source_payload_from_form(value: str) -> dict[str, Any]:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="source form field must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="source form field must be a JSON object")
    return payload


def _knowledge_upload_root(package_id: str, source_id: str):
    return factory_artifact_path(
        "agent_runtime",
        package_id,
        ".agent_runtime",
        "knowledge",
        "sources",
        "uploads",
        source_id,
    )


def _safe_upload_relative_path(filename: str):
    parts = []
    for part in str(filename or "uploaded_file").replace("\\", "/").split("/"):
        safe = _safe_path_part(part)
        if safe:
            parts.append(safe)
    if not parts:
        parts = ["uploaded_file"]
    return PurePosixPath(*parts)


def _safe_path_part(value: str) -> str:
    text = str(value or "").strip()
    if text in {"", ".", ".."}:
        return ""
    cleaned = "".join("_" if char in {"/", "\\"} or not char.isprintable() else char for char in text).strip()
    return cleaned if cleaned not in {"", ".", ".."} else ""


def _unsupported_upload_files(files: list[UploadFile]) -> list[str]:
    accepted = accepted_file_extensions()
    return [
        str(upload.filename or "uploaded_file")
        for upload in files
        if PurePosixPath(str(upload.filename or "uploaded_file").replace("\\", "/")).suffix.lower() not in accepted
    ]
