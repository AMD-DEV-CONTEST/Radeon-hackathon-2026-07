from __future__ import annotations

from agent_factory.runtime_defaults import DEFAULT_BUILTIN_WORKSPACE_ROOT
from agent_factory.tooling.spec import ToolRiskEvaluatorConfig, ToolSpec


_STRING = {"type": "string"}
_INTEGER = {"type": "integer"}
_BOOLEAN = {"type": "boolean"}
_CHANGE_SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "before_bytes": _INTEGER,
        "after_bytes": _INTEGER,
        "before_lines": _INTEGER,
        "after_lines": _INTEGER,
        "added_lines": _INTEGER,
        "removed_lines": _INTEGER,
    },
    "required": [
        "before_bytes",
        "after_bytes",
        "before_lines",
        "after_lines",
        "added_lines",
        "removed_lines",
    ],
    "additionalProperties": False,
}
_FILESYSTEM_RESOURCE = {"filesystem": "filesystem"}
_FS_MODULE = "agent_factory.tooling.builtins.filesystem"
_PATH_BOUNDARY_DESCRIPTION = (
    "Paths are restricted to the current tool workspace root. Prefer relative paths or absolute paths "
    f"inside that root. The default sandbox workspace root is {DEFAULT_BUILTIN_WORKSPACE_ROOT}. "
    "Do not use /tmp, host paths, or arbitrary absolute paths unless the runtime explicitly allows external paths."
)
_READ_MISSING_GUIDANCE = (
    "If read reports a missing or uncertain path, do not conclude that the file is unavailable. "
    "Use ls on the parent or nearby directory to confirm the exact name, case, extension, and hierarchy before retrying."
)
_READ_PATH_DESCRIPTION = f"Path of the file to read. {_PATH_BOUNDARY_DESCRIPTION}{_READ_MISSING_GUIDANCE}"
_LS_PATH_DESCRIPTION = f"Path of the directory to list. {_PATH_BOUNDARY_DESCRIPTION}"
_WRITE_PATH_DESCRIPTION = (
    f"Path of the file to write. {_PATH_BOUNDARY_DESCRIPTION}"
    "Write new files directly inside the workspace, for example report.md or "
    f"{DEFAULT_BUILTIN_WORKSPACE_ROOT}/report.md。"
)
_BASE_PATH_DESCRIPTION = f"Optional search root. {_PATH_BOUNDARY_DESCRIPTION}"


FILESYSTEM_TOOL_SPECS: list[ToolSpec] = [
    ToolSpec(
        id="read",
        description=(
            "Reads a text file inside the workspace boundary and returns a controlled line range."
            f"{_READ_MISSING_GUIDANCE}"
        ),
        entrypoint="agent_factory.tooling.builtins.filesystem.read:run",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": _READ_PATH_DESCRIPTION},
                "start_line": {"type": "integer", "minimum": 1, "default": 1, "description": "One-based starting line."},
                "limit": {"type": "integer", "minimum": 1, "maximum": 2000, "default": 200, "description": "Maximum number of lines to read."},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "path": _STRING,
                "content": _STRING,
                "start_line": _INTEGER,
                "end_line": _INTEGER,
                "total_lines": _INTEGER,
                "truncated": _BOOLEAN,
                "content_hash": _STRING,
            },
            "required": ["path", "content", "start_line", "end_line", "total_lines", "truncated", "content_hash"],
            "additionalProperties": False,
        },
        resources=_FILESYSTEM_RESOURCE,
        risk_level="low",
        risk_evaluator=ToolRiskEvaluatorConfig(hard=f"{_FS_MODULE}.read:evaluate_risk"),
        concurrent=True,
    ),
    ToolSpec(
        id="write",
        description=(
            "Creates or fully replaces a text file inside the workspace boundary. The call must include "
            "the complete file body in content; the tool does not read text from assistant messages. "
            "Use edit for a local change to an existing UTF-8 file."
        ),
        schema_error_guidance=(
            "A write call must provide both path and content. content must be the complete target file text; "
            "do not omit it or assume the tool can read a previous response."
        ),
        entrypoint="agent_factory.tooling.builtins.filesystem.write:run",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": _WRITE_PATH_DESCRIPTION},
                "content": {
                    "type": "string",
                    "description": "Complete text content to write.",
                },
                "create_dirs": {
                    "type": "boolean",
                    "default": True,
                    "description": "Whether to create missing parent directories.",
                },
            },
            "required": ["path", "content"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "path": _STRING,
                "created": _BOOLEAN,
                "bytes_written": _INTEGER,
                "before_hash": {"type": ["string", "null"]},
                "after_hash": _STRING,
                "change_summary": _CHANGE_SUMMARY_SCHEMA,
            },
            "required": ["path", "created", "bytes_written", "before_hash", "after_hash", "change_summary"],
            "additionalProperties": False,
        },
        resources=_FILESYSTEM_RESOURCE,
        risk_level="medium",
        risk_evaluator=ToolRiskEvaluatorConfig(hard=f"{_FS_MODULE}.write:evaluate_risk"),
        concurrent=False,
    ),
    ToolSpec(
        id="edit",
        description="Performs an exact text replacement in one UTF-8 file inside the workspace boundary.",
        schema_error_guidance=(
            "Provide path, old_text, and new_text. old_text must match exactly once by default; set "
            "replace_all=true explicitly to replace every match."
        ),
        entrypoint="agent_factory.tooling.builtins.filesystem.edit:run",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": _WRITE_PATH_DESCRIPTION},
                "old_text": {"type": "string", "description": "Complete original text to replace."},
                "new_text": {"type": "string", "description": "Replacement text, which may be empty."},
                "replace_all": {
                    "type": "boolean",
                    "default": False,
                    "description": "Whether to replace all matches.",
                },
            },
            "required": ["path", "old_text", "new_text"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "path": _STRING,
                "replacements": _INTEGER,
                "before_hash": _STRING,
                "after_hash": _STRING,
                "change_summary": _CHANGE_SUMMARY_SCHEMA,
            },
            "required": ["path", "replacements", "before_hash", "after_hash", "change_summary"],
            "additionalProperties": False,
        },
        resources=_FILESYSTEM_RESOURCE,
        risk_level="medium",
        risk_evaluator=ToolRiskEvaluatorConfig(hard=f"{_FS_MODULE}.edit:evaluate_risk"),
        concurrent=False,
    ),
    ToolSpec(
        id="glob",
        description="Finds file paths by glob pattern inside the workspace boundary.",
        entrypoint="agent_factory.tooling.builtins.filesystem.glob:run",
        input_schema={
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Glob pattern."},
                "base_path": {"type": "string", "default": ".", "description": _BASE_PATH_DESCRIPTION},
                "max_results": {"type": "integer", "minimum": 1, "maximum": 5000, "default": 100, "description": "Optional maximum result count."},
            },
            "required": ["pattern"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "matches": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "path": _STRING,
                            "name": _STRING,
                            "type": {"type": "string", "enum": ["file", "directory", "other"]},
                            "size_bytes": {"type": ["integer", "null"]},
                            "modified_at": _STRING,
                        },
                        "required": ["path", "name", "type", "size_bytes", "modified_at"],
                        "additionalProperties": False,
                    },
                },
                "truncated": _BOOLEAN,
            },
            "required": ["matches", "truncated"],
            "additionalProperties": False,
        },
        resources=_FILESYSTEM_RESOURCE,
        risk_level="low",
        risk_evaluator=ToolRiskEvaluatorConfig(hard=f"{_FS_MODULE}.glob:evaluate_risk"),
        concurrent=True,
    ),
    ToolSpec(
        id="grep",
        description="Searches file contents for text or a regular expression inside the workspace boundary.",
        entrypoint="agent_factory.tooling.builtins.filesystem.grep:run",
        input_schema={
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Search text or regular expression."},
                "base_path": {"type": "string", "default": ".", "description": _BASE_PATH_DESCRIPTION},
                "include": {
                    "oneOf": [
                        {"type": "string"},
                        {"type": "array", "items": _STRING},
                    ],
                    "description": "Optional file include pattern or pattern list.",
                },
                "exclude": {
                    "oneOf": [
                        {"type": "string"},
                        {"type": "array", "items": _STRING},
                    ],
                    "description": "Optional file exclusion pattern or pattern list.",
                },
                "case_sensitive": {"type": "boolean", "default": True},
                "regex": {"type": "boolean", "default": True},
                "context_before": {"type": "integer", "minimum": 0, "maximum": 20, "default": 0},
                "context_after": {"type": "integer", "minimum": 0, "maximum": 20, "default": 0},
                "max_file_bytes": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 20000000,
                    "default": 2000000,
                },
                "max_results": {"type": "integer", "minimum": 1, "maximum": 5000, "default": 100},
            },
            "required": ["pattern"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "matches": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "path": _STRING,
                            "line": _STRING,
                            "line_number": _INTEGER,
                            "before": {"type": "array", "items": _STRING},
                            "after": {"type": "array", "items": _STRING},
                        },
                        "required": ["path", "line", "line_number", "before", "after"],
                        "additionalProperties": False,
                    },
                },
                "truncated": _BOOLEAN,
                "files_searched": _INTEGER,
            },
            "required": ["matches", "truncated", "files_searched"],
            "additionalProperties": False,
        },
        resources=_FILESYSTEM_RESOURCE,
        risk_level="low",
        risk_evaluator=ToolRiskEvaluatorConfig(hard=f"{_FS_MODULE}.grep:evaluate_risk"),
        concurrent=True,
    ),
    ToolSpec(
        id="ls",
        description="Lists a directory inside the workspace boundary.",
        entrypoint="agent_factory.tooling.builtins.filesystem.ls:run",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": _LS_PATH_DESCRIPTION},
                "recursive": {"type": "boolean", "default": False},
                "max_entries": {"type": "integer", "minimum": 1, "maximum": 5000, "default": 200},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "entries": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "path": _STRING,
                            "name": _STRING,
                            "type": {"type": "string", "enum": ["file", "directory", "other"]},
                            "size_bytes": {"type": ["integer", "null"]},
                            "modified_at": _STRING,
                        },
                        "required": ["path", "name", "type", "size_bytes", "modified_at"],
                        "additionalProperties": False,
                    },
                },
                "truncated": _BOOLEAN,
            },
            "required": ["entries", "truncated"],
            "additionalProperties": False,
        },
        resources=_FILESYSTEM_RESOURCE,
        risk_level="low",
        risk_evaluator=ToolRiskEvaluatorConfig(hard=f"{_FS_MODULE}.ls:evaluate_risk"),
        concurrent=True,
    ),
]


def get_filesystem_tool_specs() -> list[ToolSpec]:
    return [tool.model_copy(deep=True) for tool in FILESYSTEM_TOOL_SPECS]
