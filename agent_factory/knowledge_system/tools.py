from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_factory.knowledge_system.runtime import KnowledgeRuntime
from agent_factory.knowledge_system.schema import KnowledgeSourceInput
from agent_factory.tooling.envelope import tool_envelope, tool_failure
from agent_factory.tooling.workspace_paths import workspace_path_candidate


_FILESYSTEM_SOURCE_TYPES = frozenset({"filesystem", "codebase", "skill", "artifact_report"})


def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    runtime = resources.get("knowledge_runtime")
    if not isinstance(runtime, KnowledgeRuntime):
        return tool_failure(
            "knowledge runtime is not configured",
            output={"status": "failed"},
        )
    action = str(arguments.get("action") or "").strip()
    try:
        if action == "list_sources":
            return tool_envelope({
                "status": "completed",
                "sources": [source.model_dump(mode="json") for source in runtime.list_sources()],
            })
        if action == "describe_source":
            return tool_envelope({"status": "completed", **runtime.describe_source(_source_id(arguments))})
        if action == "prepare_source":
            preview = runtime.prepare_source(_source_payload(arguments, resources))
            return tool_envelope({"status": "completed", "preview": preview.model_dump(mode="json")})
        if action == "confirm_source":
            job = runtime.confirm_source(_source_payload(arguments, resources))
            return tool_envelope({"status": "completed", "job": job.model_dump(mode="json")})
        if action == "list_documents":
            return tool_envelope({
                "status": "completed",
                "documents": [
                    document.model_dump(mode="json")
                    for document in runtime.list_documents(arguments.get("source_id"))
                ],
            })
        if action == "search":
            results = runtime.search(
                query=str(arguments.get("query") or ""),
                source_id=arguments.get("source_id"),
                mode=str(arguments.get("mode") or "auto"),
                top_k=int(arguments.get("top_k") or 8),
            )
            return tool_envelope({"status": "completed", "results": [result.model_dump(mode="json") for result in results]})
        if action == "open":
            return tool_envelope({
                "status": "completed",
                **runtime.open(
                    source_id=arguments.get("source_id"),
                    document_id=arguments.get("document_id"),
                    chunk_id=arguments.get("chunk_id"),
                ),
            })
        if action == "read":
            return tool_envelope({
                "status": "completed",
                **runtime.read(
                    document_id=arguments.get("document_id"),
                    chunk_id=arguments.get("chunk_id"),
                ),
            })
        if action == "reindex":
            job = runtime.reindex_source(_source_id(arguments))
            return tool_envelope({"status": "completed", "job": job.model_dump(mode="json")})
        if action == "remove_source":
            return tool_envelope({"status": "completed", "removed": runtime.remove_source(_source_id(arguments))})
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        return tool_failure(error, output={"status": "failed"})
    error = f"unsupported knowledge action: {action}"
    return tool_failure(error, output={"status": "failed"})


def evaluate_risk(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    del context
    action = str(arguments.get("action") or "").strip()
    if action in {"list_sources", "describe_source", "list_documents", "search", "open", "read"}:
        return {"action": "allow", "risk_level": "low", "reasons": ["read-only knowledge action"]}
    if action in {"prepare_source", "confirm_source", "reindex"}:
        return {"action": "ask", "risk_level": "medium", "reasons": [f"knowledge action requires review: {action}"]}
    if action == "remove_source":
        return {"action": "ask", "risk_level": "high", "reasons": ["knowledge source removal is destructive"]}
    return {"action": "deny", "risk_level": "medium", "reasons": [f"unknown knowledge action: {action}"]}


def _source_id(arguments: dict[str, Any]) -> str:
    source_id = str(arguments.get("source_id") or "").strip()
    if not source_id:
        raise ValueError("knowledge action requires source_id")
    return source_id


def _source_payload(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    source = arguments.get("source")
    if not isinstance(source, dict):
        raise ValueError("knowledge action requires source object")
    payload = KnowledgeSourceInput.model_validate(source).model_dump(mode="json", exclude_none=True)
    if payload["source_type"] not in _FILESYSTEM_SOURCE_TYPES:
        return payload
    locator_key = next((key for key in ("path", "uri") if str(payload.get(key) or "").strip()), None)
    if locator_key is None:
        return payload
    workspace_root_value = str(resources.get("workspace_root") or "").strip()
    if not workspace_root_value:
        raise ValueError("knowledge filesystem source requires workspace_root")
    workspace_root = Path(workspace_root_value).expanduser()
    original_locator = str(payload[locator_key]).strip()
    resolved = workspace_path_candidate(original_locator, root=workspace_root).resolve(strict=False)
    metadata = dict(payload.get("metadata") or {})
    metadata.setdefault("original_uri", original_locator)
    payload["metadata"] = metadata
    payload["uri"] = str(resolved)
    payload.pop("path", None)
    return payload
