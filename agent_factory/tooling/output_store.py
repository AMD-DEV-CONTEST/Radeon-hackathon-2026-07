from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import re
from typing import Any
from uuid import uuid4

from agent_factory.tooling.output_compressor import compress_tool_output
from agent_factory.tooling.envelope import tool_envelope, tool_failure
from agent_factory.tooling.execution_context import current_tool_output_session_id
from agent_factory.tooling.spec import ToolOutputCompressionActionConfig, ToolOutputCompressionConfig


TOOL_OUTPUT_STORE_RESOURCE = "tool_output_store"
TOOL_OUTPUT_MAX_MODEL_CHARS_ENV = "AGENTFACTORY_TOOL_OUTPUT_MAX_MODEL_CHARS"
DEFAULT_TOOL_OUTPUT_MAX_MODEL_CHARS = 12000
MIN_TOOL_OUTPUT_MAX_MODEL_CHARS = 1000
_OUTPUT_ID_RE = re.compile(r"^toolout_[a-f0-9]{32}$")


@dataclass(frozen=True, slots=True)
class ToolOutputPolicy:
    max_model_chars: int = DEFAULT_TOOL_OUTPUT_MAX_MODEL_CHARS


@dataclass(frozen=True, slots=True)
class ToolOutputProjection:
    output: dict[str, Any]
    output_ref: dict[str, Any] | None = None
    output_summary: str | None = None
    output_truncated: bool = False


class ToolOutputStore:
    """Filesystem-backed, session-scoped store for full tool outputs."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    @property
    def records_dir(self) -> Path:
        session_id = current_tool_output_session_id() or "unscoped"
        records_dir = self.root / "sessions" / session_id / "records"
        records_dir.mkdir(parents=True, exist_ok=True)
        return records_dir

    def write_output(
        self,
        *,
        tool_id: str,
        tool_call_id: str | None,
        output: dict[str, Any],
    ) -> dict[str, Any]:
        output_id = f"toolout_{uuid4().hex}"
        text = _json_text(output)
        created_at = datetime.now(UTC).isoformat()
        record = {
            "type": "tool_output_record",
            "id": output_id,
            "tool_id": tool_id,
            "tool_call_id": tool_call_id or "",
            "created_at": created_at,
            "size_chars": len(text),
            "output": output,
        }
        path = self._record_path(output_id)
        tmp_path = path.with_suffix(".tmp")
        tmp_path.write_text(_json_text(record), encoding="utf-8")
        tmp_path.replace(path)
        return {
            "type": "tool_output_ref",
            "id": output_id,
            "tool_id": tool_id,
            "tool_call_id": tool_call_id or "",
            "created_at": created_at,
            "size_chars": len(text),
        }

    def describe(self, output_id: str) -> dict[str, Any]:
        record = self._read_record(output_id)
        return {
            "type": "tool_output_ref",
            "id": record["id"],
            "tool_id": record["tool_id"],
            "tool_call_id": record.get("tool_call_id", ""),
            "created_at": record["created_at"],
            "size_chars": record["size_chars"],
        }

    def list_outputs(self, *, limit: int = 20) -> list[dict[str, Any]]:
        refs: list[dict[str, Any]] = []
        for path in self.records_dir.glob("toolout_*.json"):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(record, dict) or record.get("type") != "tool_output_record":
                continue
            refs.append(
                {
                    "type": "tool_output_ref",
                    "id": str(record.get("id") or ""),
                    "tool_id": str(record.get("tool_id") or ""),
                    "tool_call_id": str(record.get("tool_call_id") or ""),
                    "created_at": str(record.get("created_at") or ""),
                    "size_chars": int(record.get("size_chars") or 0),
                }
            )
        refs.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
        return refs[: max(limit, 0)]

    def read(
        self,
        *,
        output_id: str,
        path: str | None = None,
        offset: int = 0,
        limit: int = DEFAULT_TOOL_OUTPUT_MAX_MODEL_CHARS,
    ) -> dict[str, Any]:
        record = self._read_record(output_id)
        selected = _select_path(record["output"], path)
        text = _json_text(selected) if not isinstance(selected, str) else selected
        start = max(offset, 0)
        safe_limit = max(limit, 1)
        end = min(start + safe_limit, len(text))
        return {
            "output_id": output_id,
            "path": path or "",
            "offset": start,
            "limit": safe_limit,
            "total_chars": len(text),
            "content": text[start:end],
            "truncated": end < len(text),
        }

    def _read_record(self, output_id: str) -> dict[str, Any]:
        path = self._record_path(output_id)
        if not path.is_file():
            raise FileNotFoundError(f"unknown tool output id: {output_id}")
        record = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(record, dict) or record.get("type") != "tool_output_record":
            raise ValueError(f"invalid tool output record: {output_id}")
        return record

    def _record_path(self, output_id: str) -> Path:
        if not _OUTPUT_ID_RE.fullmatch(output_id):
            raise ValueError("output_id must be a tool output id")
        return self.records_dir / f"{output_id}.json"


def default_tool_output_policy() -> ToolOutputPolicy:
    raw = os.getenv(TOOL_OUTPUT_MAX_MODEL_CHARS_ENV, str(DEFAULT_TOOL_OUTPUT_MAX_MODEL_CHARS)).strip()
    try:
        value = int(raw)
    except ValueError:
        value = DEFAULT_TOOL_OUTPUT_MAX_MODEL_CHARS
    return ToolOutputPolicy(max_model_chars=max(value, MIN_TOOL_OUTPUT_MAX_MODEL_CHARS))


def project_tool_output(
    *,
    output: dict[str, Any],
    tool_id: str,
    tool_call_id: str | None,
    arguments: dict[str, Any] | None = None,
    store: ToolOutputStore | None,
    policy: ToolOutputPolicy | None = None,
    compression_model: Any | None = None,
    compression_config: ToolOutputCompressionConfig | None = None,
) -> ToolOutputProjection:
    effective_policy = policy or default_tool_output_policy()
    effective_max_chars = (
        compression_config.max_model_chars
        if compression_config is not None and compression_config.max_model_chars is not None
        else effective_policy.max_model_chars
    )
    raw_text = _json_text(output)
    if len(raw_text) <= effective_max_chars:
        return ToolOutputProjection(output=output)
    output_ref = (
        store.write_output(tool_id=tool_id, tool_call_id=tool_call_id, output=output)
        if store is not None
        else None
    )
    # Use LLM compression when available, fallback to structural truncation
    compression = compress_tool_output(
        output,
        tool_id=tool_id,
        arguments=arguments or {},
        max_chars=effective_max_chars,
        model=compression_model,
        config=_compression_config_for_arguments(compression_config, arguments or {}),
    )
    output_id = str(output_ref.get("id") or "") if output_ref else ""
    compacted: dict[str, Any] = {
        "compressed_output": compression.compressed_output,
        "output_id": output_id,
        "raw_output_read_hint": _raw_output_read_hint(output_id=output_id),
        "_tool_output_compacted": {
            "original_chars": compression.original_chars,
            "compressed_chars": compression.compressed_chars,
            "model_visible_limit_chars": effective_max_chars,
            "compression_method": compression.method,
            "output_ref": output_ref,
        },
    }
    summary = "Tool output exceeded the model-visible limit; a compressed observation was returned."
    if output_ref is not None:
        summary += f" Full output can be read with tool_output using output_id={output_id}."
    return ToolOutputProjection(
        output=compacted,
        output_ref=output_ref,
        output_summary=summary,
        output_truncated=True,
    )


def _compression_config_for_arguments(
    config: ToolOutputCompressionConfig | None,
    arguments: dict[str, Any],
) -> ToolOutputCompressionActionConfig | None:
    if config is None:
        return None
    action_key = str(config.action_argument or "action")
    action = str(arguments.get(action_key) or "").strip().lower()
    if action:
        return config.actions.get(action)
    if len(config.actions) == 1:
        return next(iter(config.actions.values()))
    return None


def _raw_output_read_hint(*, output_id: str) -> str:
    if not output_id:
        return "The full raw tool output is not available because no tool_output store is configured."
    return (
        "If the compressed observation lacks enough detail, call "
        f"tool_output(action='read', output_id='{output_id}') to inspect the original tool output. "
        "Use the exact output_id; do not infer or rewrite it."
    )


def run_tool_output(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    store = resources.get(TOOL_OUTPUT_STORE_RESOURCE)
    if not isinstance(store, ToolOutputStore):
        raise ValueError("tool_output_store resource is not configured")
    action = str(arguments.get("action") or "").strip()
    output_id = str(arguments.get("output_id") or "").strip()
    if action == "list":
        limit = _optional_int(arguments.get("limit"), default=20)
        return tool_envelope({
            "action": action,
            "status": "completed",
            "message": "Available tool outputs for this workspace.",
            "outputs": store.list_outputs(limit=limit),
        })
    if action == "describe":
        try:
            output = store.describe(output_id)
        except (FileNotFoundError, ValueError):
            failure = _output_ref_not_found(action=action, output_id=output_id, store=store)
            return tool_failure(failure["message"], output=failure, retryable=True)
        return tool_envelope({"action": action, "status": "completed", "output": output})
    if action == "read":
        try:
            output = store.read(
                output_id=output_id,
                path=_optional_string(arguments.get("path")),
                offset=_optional_int(arguments.get("offset"), default=0),
                limit=_optional_int(arguments.get("limit"), default=DEFAULT_TOOL_OUTPUT_MAX_MODEL_CHARS),
            )
        except (FileNotFoundError, ValueError):
            failure = _output_ref_not_found(action=action, output_id=output_id, store=store)
            return tool_failure(failure["message"], output=failure, retryable=True)
        return tool_envelope({"action": action, "status": "completed", "output": output})
    raise ValueError(f"unsupported tool_output action: {action}")


def _output_ref_not_found(*, action: str, output_id: str, store: ToolOutputStore) -> dict[str, Any]:
    return {
        "action": action,
        "status": "output_ref_not_found",
        "message": (
            "The requested output_id is not a readable output for this workspace. "
            "Do not invent output_id values. Call tool_output with action=list and use one of the returned ids."
        ),
        "requested_id": output_id,
        "available_outputs": store.list_outputs(limit=20),
        "suggested_action": "Call tool_output list, then retry with an id from available_outputs.",
    }


def _fit_projection(
    value: dict[str, Any],
    *,
    raw_text: str,
    output_ref: dict[str, Any] | None,
    max_chars: int,
) -> dict[str, Any]:
    if len(_json_text(value)) <= max_chars:
        return value
    preview_budget = max(200, max_chars - 900)
    return {
        "_tool_output_compacted": {
            "original_chars": len(raw_text),
            "model_visible_limit_chars": max_chars,
            "output_ref": output_ref,
        },
        "preview": _text_preview(raw_text, preview_budget),
    }


def _compact_value(value: Any, *, budget: int) -> Any:
    if isinstance(value, dict):
        return _compact_dict(value, budget=budget)
    if isinstance(value, list):
        return _compact_list(value, budget=budget)
    if isinstance(value, str):
        return value if len(value) <= budget else _text_preview(value, budget)
    return value


def _compact_dict(value: dict[str, Any], *, budget: int) -> dict[str, Any]:
    per_field_budget = max(300, budget // max(len(value), 1))
    result: dict[str, Any] = {}
    for key, item in value.items():
        result[key] = _compact_value(item, budget=per_field_budget)
    return result


def _compact_list(value: list[Any], *, budget: int) -> dict[str, Any] | list[Any]:
    if not value:
        return []
    item_budget = max(200, budget // min(len(value), 10))
    retained: list[Any] = []
    retained_chars = 2
    for item in value:
        compact_item = _compact_value(item, budget=item_budget)
        projected = _json_text(compact_item)
        if retained and retained_chars + len(projected) > budget:
            break
        retained.append(compact_item)
        retained_chars += len(projected) + 1
    if len(retained) == len(value):
        return retained
    return {
        "_type": "list_preview",
        "items": retained,
        "original_length": len(value),
        "retained_length": len(retained),
        "truncated": True,
    }


def _text_preview(value: str, budget: int) -> dict[str, Any]:
    safe_budget = max(budget, 100)
    if len(value) <= safe_budget:
        return {"_type": "text_preview", "text": value, "truncated": False, "original_chars": len(value)}
    half = max(50, (safe_budget - 80) // 2)
    return {
        "_type": "text_preview",
        "head": value[:half],
        "tail": value[-half:],
        "truncated": True,
        "original_chars": len(value),
    }


def _select_path(value: Any, path: str | None) -> Any:
    if not path:
        return value
    current = value
    for part in path.split("."):
        if not part:
            continue
        if isinstance(current, dict):
            current = current[part]
            continue
        if isinstance(current, list):
            current = current[int(part)]
            continue
        raise ValueError(f"path cannot descend into {type(current).__name__}: {part}")
    return current


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: Any, *, default: int) -> int:
    if value is None or value == "":
        return default
    return int(value)
