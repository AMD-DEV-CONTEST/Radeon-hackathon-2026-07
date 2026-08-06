from __future__ import annotations

import json
import math
import re
from typing import Any


NULL_MARKER = "∅"
XENIX_TABLE_TEXT_TOOLS_WITH_GENERATED_DATASET_PREVIEW = {
    "data.integrate",
    "data.transform",
    "data.clean",
    "data.tokenize",
}
_RECORDS_COLUMN_THRESHOLD = 8
_RECORDS_LONG_CELL_THRESHOLD = 80
_MARKDOWN_SPECIAL_CHARS = str.maketrans(
    {
        "\\": "\\\\",
        "|": "\\|",
        "\r": " ",
        "\n": " ",
    }
)
_SAFE_YAML_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def render_xenix_table_tool_result(
    *,
    tool_name: str,
    status: str,
    payload: dict[str, Any],
    error_summary: str | None = None,
) -> str | None:
    if status != "succeeded" or error_summary:
        return None
    if tool_name == "data.query":
        return _render_data_query(payload)
    if tool_name in XENIX_TABLE_TEXT_TOOLS_WITH_GENERATED_DATASET_PREVIEW:
        return _render_generated_dataset_preview(tool_name, payload)
    return None


def _render_data_query(payload: dict[str, Any]) -> str | None:
    columns = _query_columns(payload.get("columns"))
    if columns is None:
        return None
    rows = _query_rows(payload.get("rows"), columns)
    if rows is None:
        return None
    returned_rows = _integer(payload.get("returned_row_count"), default=len(rows))
    total_rows = _integer(payload.get("total_row_count"))
    truncated = _boolean(payload.get("truncated"))
    if total_rows is None and truncated is False:
        total_rows = returned_rows
    notes = []
    if total_rows is None:
        notes.append("total_rows is unavailable for this historical tool result.")
    return _render_table_text(
        columns=columns,
        rows=rows,
        returned_rows=returned_rows,
        total_rows=total_rows,
        truncated=truncated,
        sample=f"head({returned_rows})",
        notes=notes,
    )


def _render_generated_dataset_preview(tool_name: str, payload: dict[str, Any]) -> str | None:
    inspection = payload.get("inspection")
    if not isinstance(inspection, dict):
        return None
    preview_columns = inspection.get("preview_columns")
    preview_rows = inspection.get("preview_rows")
    if not isinstance(preview_columns, list) or not isinstance(preview_rows, list):
        return None
    column_types = _inspection_column_types(inspection.get("columns"))
    columns = [
        {"name": str(column), "type": column_types.get(str(column), "unknown")}
        for column in preview_columns
    ]
    rows = [
        [item if item != "" else None for item in row]
        for row in preview_rows
        if isinstance(row, list)
    ]
    returned_rows = len(rows)
    total_rows = _integer(inspection.get("row_count"), default=returned_rows)
    prefix: list[str] = []
    _append_metadata(prefix, "tool", tool_name)
    _append_metadata(prefix, "dataset_id", payload.get("dataset_id"))
    _append_metadata(prefix, "artifact_id", payload.get("artifact_id"))
    _append_metadata(prefix, "summary", payload.get("summary"))
    _append_generated_dataset_metadata(prefix, tool_name, payload)
    table_text = _render_table_text(
        columns=columns,
        rows=rows,
        returned_rows=returned_rows,
        total_rows=total_rows,
        truncated=total_rows > returned_rows,
        sample=f"head({returned_rows})",
        notes=[
            "data is a preview of the generated dataset; use dataset_id for follow-up tools and artifact_id for the user-openable workbook."
        ],
    )
    if not prefix:
        return table_text
    return "\n".join(prefix) + "\n\n" + table_text


def _render_table_text(
    *,
    columns: list[dict[str, str]],
    rows: list[list[Any]],
    returned_rows: int,
    total_rows: int | None,
    truncated: bool,
    sample: str,
    notes: list[str] | None = None,
) -> str:
    column_count = len(columns)
    rows = [_normalize_row(row, column_count) for row in rows]
    lines = [
        f"shape: {returned_rows} rows × {column_count} columns",
        f"returned_rows: {returned_rows}",
        "total_rows: " + (str(total_rows) if total_rows is not None else "unknown"),
        f"truncated: {_yaml_bool(truncated)}",
        f"sample: {sample}",
        f"null: {NULL_MARKER}",
        "",
        "schema:",
    ]
    for column in columns:
        lines.append(f"  {_yaml_key(column['name'])}: {_yaml_scalar(column.get('type') or 'unknown')}")
    lines.extend(["", _table_body_label(columns, rows)])
    if _should_render_records(columns, rows):
        lines.extend(_records_block(columns, rows))
    else:
        lines.extend(_markdown_table(columns, rows))
    if notes:
        lines.extend(["", "notes:"])
        for note in notes:
            lines.append(f"  - {_yaml_scalar(note)}")
    return "\n".join(lines)


def _table_body_label(columns: list[dict[str, str]], rows: list[list[Any]]) -> str:
    return "records:" if _should_render_records(columns, rows) else "data:"


def _should_render_records(columns: list[dict[str, str]], rows: list[list[Any]]) -> bool:
    if len(columns) > _RECORDS_COLUMN_THRESHOLD:
        return True
    if len(rows) == 1 and len(columns) > 5:
        return True
    return any(len(_display_value(value)) > _RECORDS_LONG_CELL_THRESHOLD for row in rows for value in row)


def _markdown_table(columns: list[dict[str, str]], rows: list[list[Any]]) -> list[str]:
    headers = ["#", *[column["name"] for column in columns]]
    alignments = ["---:", *[_markdown_alignment(column.get("type") or "") for column in columns]]
    lines = [
        "| " + " | ".join(_markdown_cell(header) for header in headers) + " |",
        "|" + "|".join(alignments) + "|",
    ]
    for row_index, row in enumerate(rows, start=1):
        values = [row_index, *row]
        lines.append("| " + " | ".join(_markdown_cell(value) for value in values) + " |")
    return lines


def _records_block(columns: list[dict[str, str]], rows: list[list[Any]]) -> list[str]:
    lines = [""]
    for row_index, row in enumerate(rows, start=1):
        if row_index > 1:
            lines.append("")
        lines.append(f"[{row_index}]")
        for column, value in zip(columns, row, strict=False):
            lines.append(f"{column['name']} = {_record_value(value)}")
    return lines


def _append_generated_dataset_metadata(lines: list[str], tool_name: str, payload: dict[str, Any]) -> None:
    _append_metadata(lines, "input_dataset_ids", payload.get("input_dataset_ids"))
    _append_metadata(lines, "source_dataset_id", payload.get("source_dataset_id"))
    _append_metadata(lines, "row_count", payload.get("row_count"))
    _append_metadata(lines, "row_count_before", payload.get("row_count_before"))
    _append_metadata(lines, "row_count_after", payload.get("row_count_after"))
    if tool_name == "data.clean":
        _append_cleaning_metadata(lines, payload.get("cleaning_report"))
    if tool_name == "data.tokenize":
        _append_tokenization_metadata(lines, payload.get("tokenization_report"))


def _append_cleaning_metadata(lines: list[str], report: Any) -> None:
    if not isinstance(report, dict):
        return
    _append_metadata(lines, "rows_removed", report.get("rows_removed"))
    operations = report.get("operations")
    if isinstance(operations, list):
        operation_names = [
            str(operation.get("operation"))
            for operation in operations
            if isinstance(operation, dict) and operation.get("operation")
        ]
        _append_metadata(lines, "operations", operation_names)
    warnings = report.get("warnings")
    if isinstance(warnings, list) and warnings:
        _append_metadata(lines, "warnings", [str(warning) for warning in warnings])


def _append_tokenization_metadata(lines: list[str], report: Any) -> None:
    if not isinstance(report, dict):
        return
    for key in (
        "output",
        "source_row_count",
        "output_row_count",
        "tokenized_row_count",
        "empty_token_row_count",
    ):
        _append_metadata(lines, key, report.get(key))


def _query_columns(value: Any) -> list[dict[str, str]] | None:
    if isinstance(value, list):
        columns = []
        for item in value:
            if not isinstance(item, dict):
                return None
            name = str(item.get("name") or "")
            if not name:
                return None
            columns.append({"name": name, "type": str(item.get("type") or "unknown")})
        return columns
    if not isinstance(value, dict):
        return None
    schema = value.get("_schema")
    data = value.get("data")
    if not isinstance(schema, dict) or not isinstance(data, list):
        return None
    name_index = schema.get("name")
    type_index = schema.get("type")
    index_index = schema.get("index")
    if not isinstance(name_index, int) or not isinstance(type_index, int):
        return None
    parsed: list[tuple[int, dict[str, str]]] = []
    for position, row in enumerate(data):
        if not isinstance(row, list) or len(row) <= max(name_index, type_index):
            return None
        column_index = position
        if isinstance(index_index, int) and len(row) > index_index:
            column_index = _integer(row[index_index], default=position)
        name = str(row[name_index])
        parsed.append((column_index, {"name": name, "type": str(row[type_index])}))
    return [column for _index, column in sorted(parsed, key=lambda item: item[0])]


def _query_rows(value: Any, columns: list[dict[str, str]]) -> list[list[Any]] | None:
    if isinstance(value, list):
        rows = []
        for item in value:
            if isinstance(item, list):
                rows.append(item)
            elif isinstance(item, dict):
                rows.append([item.get(column["name"]) for column in columns])
            else:
                return None
        return rows
    if not isinstance(value, dict):
        return None
    schema = value.get("_schema")
    data = value.get("data")
    if not isinstance(schema, dict) or not isinstance(data, list):
        return None
    indexes = []
    for column in columns:
        column_index = schema.get(column["name"])
        if not isinstance(column_index, int):
            return None
        indexes.append(column_index)
    rows = []
    for row in data:
        if not isinstance(row, list):
            return None
        rows.append([row[index] if index < len(row) else None for index in indexes])
    return rows


def _normalize_row(row: list[Any], column_count: int) -> list[Any]:
    if len(row) >= column_count:
        return row[:column_count]
    return [*row, *([None] * (column_count - len(row)))]


def _inspection_column_types(value: Any) -> dict[str, str]:
    if not isinstance(value, list):
        return {}
    result: dict[str, str] = {}
    for item in value:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "")
        if name:
            result[name] = str(item.get("kind") or item.get("type") or "unknown")
    return result


def _append_metadata(lines: list[str], key: str, value: Any) -> None:
    if value is None:
        return
    if isinstance(value, str) and not value.strip():
        return
    if isinstance(value, list) and not value:
        return
    lines.append(f"{key}: {_yaml_scalar(value)}")


def _markdown_alignment(type_name: str) -> str:
    lower = type_name.lower()
    if any(token in lower for token in ("int", "float", "double", "decimal", "numeric", "number")):
        return "---:"
    return "---"


def _markdown_cell(value: Any) -> str:
    return _display_value(value).translate(_MARKDOWN_SPECIAL_CHARS)


def _display_value(value: Any) -> str:
    if _is_null(value):
        return NULL_MARKER
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return str(value)
    return str(value)


def _record_value(value: Any) -> str:
    if _is_null(value):
        return NULL_MARKER
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return _display_value(value)
    return json.dumps(str(value), ensure_ascii=False)


def _yaml_key(value: str) -> str:
    if _SAFE_YAML_KEY.fullmatch(value):
        return value
    return json.dumps(value, ensure_ascii=False)


def _yaml_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return _yaml_bool(value)
    if isinstance(value, (int, float)):
        return _display_value(value)
    if isinstance(value, list):
        return "[" + ", ".join(_yaml_scalar(item) for item in value) + "]"
    text = str(value).replace("\r", " ").replace("\n", " ").strip()
    if not text:
        return json.dumps(text, ensure_ascii=False)
    return text


def _yaml_bool(value: bool) -> str:
    return "true" if value else "false"


def _boolean(value: Any) -> bool:
    return bool(value)


def _integer(value: Any, *, default: int | None = None) -> int | None:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _is_null(value: Any) -> bool:
    if value is None:
        return True
    return isinstance(value, float) and math.isnan(value)
