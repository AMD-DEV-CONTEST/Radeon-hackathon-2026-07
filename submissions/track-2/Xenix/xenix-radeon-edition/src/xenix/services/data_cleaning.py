from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4

import pandas as pd
from pandas.api.types import is_bool_dtype, is_numeric_dtype
from pydantic import ConfigDict, Field
from sqlmodel import SQLModel

from ..config import AppPaths
from ..exceptions import ValidationError
from ..observability import record_counter, record_histogram, start_span
from .dataset_inspection import detect_source_format
from .preprocessing_worker import LocalPreprocessingWorkerRunner, PreprocessingWorkerRunner
from .storage.models import DatasetSourceFormat
from .tabular import (
    load_pandas_frame_with_schema,
    resolve_tabular_column_index,
    resolve_tabular_schema,
)


KEEP_SCHEMA = {"type": "string", "enum": ["first", "last", "false"]}
COLUMN_NAMES_SCHEMA = {"type": "array", "items": {"type": "string"}}
COLUMN_INDEXES_SCHEMA = {"type": "array", "items": {"type": "integer", "minimum": 0}}
COLUMN_NAME_SCHEMA = {"type": "string"}
COLUMN_INDEX_SCHEMA = {"type": "integer", "minimum": 0}
COLUMN_LIST_REFERENCE_PROPERTIES = {
    "column_indexes": COLUMN_INDEXES_SCHEMA,
    "column_names": COLUMN_NAMES_SCHEMA,
}
COLUMN_REFERENCE_PROPERTIES = {
    "column_index": COLUMN_INDEX_SCHEMA,
    "column_name": COLUMN_NAME_SCHEMA,
}
ACTION_SCHEMA = {"type": "string", "enum": ["report_only", "drop_rows"]}
BOOLEAN_SCHEMA = {"type": "boolean"}


_CLEANING_OPERATION_GROUPS: dict[str, dict[str, Any]] = {
    "schema": {
        "description": "Normalize dataset schema details such as column names.",
        "operations": [
            {
                "operation": "schema.normalize_column_names",
                "description": (
                    "Normalize column names algorithmically while preserving business-readable "
                    "Unicode letters and numbers."
                ),
                "params_schema": {
                    "type": "object",
                    "properties": {
                        "style": {"type": "string", "enum": ["snake_case"]},
                        "ascii_lower": BOOLEAN_SCHEMA,
                    },
                    "additionalProperties": False,
                },
                "example": {
                    "operation": "schema.normalize_column_names",
                    "params": {"style": "snake_case", "ascii_lower": True},
                },
            },
        ],
    },
    "duplicates": {
        "description": "Remove duplicate rows.",
        "operations": [
            {
                "operation": "duplicate.exact_rows",
                "description": "Remove rows that are exact duplicates across all columns.",
                "params_schema": {
                    "type": "object",
                    "properties": {"keep": KEEP_SCHEMA},
                    "additionalProperties": False,
                },
                "example": {"operation": "duplicate.exact_rows", "params": {"keep": "first"}},
            },
            {
                "operation": "duplicate.key_columns",
                "description": "Remove duplicate rows based on selected key columns.",
                "column_ref": "many",
                "params_schema": {
                    "type": "object",
                    "properties": {**COLUMN_LIST_REFERENCE_PROPERTIES, "keep": KEEP_SCHEMA},
                    "additionalProperties": False,
                },
                "example": {
                    "operation": "duplicate.key_columns",
                    "params": {"column_indexes": [0], "keep": "first"},
                },
            },
        ],
    },
    "missing": {
        "description": "Fill missing values or drop rows with missing values.",
        "operations": [
            {
                "operation": "missing.fill_mean",
                "description": "Fill missing numeric values with each column mean.",
                "column_ref": "many",
                "params_schema": {
                    "type": "object",
                    "properties": {**COLUMN_LIST_REFERENCE_PROPERTIES},
                    "additionalProperties": False,
                },
                "example": {"operation": "missing.fill_mean", "params": {"column_indexes": [1]}},
            },
            {
                "operation": "missing.fill_median",
                "description": "Fill missing numeric values with each column median.",
                "column_ref": "many",
                "params_schema": {
                    "type": "object",
                    "properties": {**COLUMN_LIST_REFERENCE_PROPERTIES},
                    "additionalProperties": False,
                },
                "example": {"operation": "missing.fill_median", "params": {"column_indexes": [1]}},
            },
            {
                "operation": "missing.fill_mode",
                "description": "Fill missing values with each column mode.",
                "column_ref": "many",
                "params_schema": {
                    "type": "object",
                    "properties": {**COLUMN_LIST_REFERENCE_PROPERTIES},
                    "additionalProperties": False,
                },
                "example": {"operation": "missing.fill_mode", "params": {"column_indexes": [2]}},
            },
            {
                "operation": "missing.fill_constant",
                "description": "Fill missing values with a constant value.",
                "column_ref": "many",
                "params_schema": {
                    "type": "object",
                    "properties": {**COLUMN_LIST_REFERENCE_PROPERTIES, "value": {}},
                    "required": ["value"],
                    "additionalProperties": False,
                },
                "example": {"operation": "missing.fill_constant", "params": {"column_indexes": [1], "value": 0}},
            },
            {
                "operation": "missing.forward_fill",
                "description": "Fill missing values from the previous non-empty row value.",
                "column_ref": "many",
                "params_schema": {
                    "type": "object",
                    "properties": {**COLUMN_LIST_REFERENCE_PROPERTIES},
                    "additionalProperties": False,
                },
                "example": {"operation": "missing.forward_fill", "params": {"column_indexes": [2]}},
            },
            {
                "operation": "missing.drop_rows",
                "description": "Drop rows where any selected column is missing.",
                "column_ref": "many",
                "params_schema": {
                    "type": "object",
                    "properties": {**COLUMN_LIST_REFERENCE_PROPERTIES},
                    "additionalProperties": False,
                },
                "example": {"operation": "missing.drop_rows", "params": {"column_indexes": [1]}},
            },
            {
                "operation": "missing.drop_high_missing_columns",
                "description": "Drop columns whose missing ratio is greater than an explicit threshold.",
                "column_ref": "many_optional",
                "params_schema": {
                    "type": "object",
                    "properties": {
                        **COLUMN_LIST_REFERENCE_PROPERTIES,
                        "threshold": {"type": "number", "minimum": 0, "maximum": 1},
                    },
                    "required": ["threshold"],
                    "additionalProperties": False,
                },
                "example": {
                    "operation": "missing.drop_high_missing_columns",
                    "params": {"threshold": 0.5},
                },
            },
        ],
    },
    "types": {
        "description": "Convert column types.",
        "operations": [
            {
                "operation": "type.convert",
                "description": "Convert one column to a target type.",
                "column_ref": "one",
                "params_schema": {
                    "type": "object",
                    "properties": {
                        **COLUMN_REFERENCE_PROPERTIES,
                        "target_type": {
                            "type": "string",
                            "enum": ["numeric", "integer", "datetime", "text", "boolean"],
                        },
                        "date_format": {"type": "string"},
                    },
                    "required": ["target_type"],
                    "additionalProperties": False,
                },
                "example": {
                    "operation": "type.convert",
                    "params": {"column_index": 1, "target_type": "numeric"},
                },
            },
        ],
    },
    "text": {
        "description": "Standardize text column values.",
        "operations": [
            {
                "operation": "text.trim",
                "description": "Strip leading and trailing whitespace.",
                "column_ref": "many",
                "params_schema": {
                    "type": "object",
                    "properties": {**COLUMN_LIST_REFERENCE_PROPERTIES},
                    "additionalProperties": False,
                },
                "example": {"operation": "text.trim", "params": {"column_indexes": [2]}},
            },
            {
                "operation": "text.lowercase",
                "description": "Convert text to lowercase.",
                "column_ref": "many",
                "params_schema": {
                    "type": "object",
                    "properties": {**COLUMN_LIST_REFERENCE_PROPERTIES},
                    "additionalProperties": False,
                },
                "example": {"operation": "text.lowercase", "params": {"column_indexes": [2]}},
            },
            {
                "operation": "text.uppercase",
                "description": "Convert text to uppercase.",
                "column_ref": "many",
                "params_schema": {
                    "type": "object",
                    "properties": {**COLUMN_LIST_REFERENCE_PROPERTIES},
                    "additionalProperties": False,
                },
                "example": {"operation": "text.uppercase", "params": {"column_indexes": [2]}},
            },
            {
                "operation": "text.collapse_whitespace",
                "description": "Collapse repeated whitespace into one space.",
                "column_ref": "many",
                "params_schema": {
                    "type": "object",
                    "properties": {**COLUMN_LIST_REFERENCE_PROPERTIES},
                    "additionalProperties": False,
                },
                "example": {"operation": "text.collapse_whitespace", "params": {"column_indexes": [2]}},
            },
            {
                "operation": "text.empty_to_null",
                "description": "Convert empty text values to null.",
                "column_ref": "many",
                "params_schema": {
                    "type": "object",
                    "properties": {**COLUMN_LIST_REFERENCE_PROPERTIES},
                    "additionalProperties": False,
                },
                "example": {"operation": "text.empty_to_null", "params": {"column_indexes": [2]}},
            },
            {
                "operation": "text.map_values",
                "description": "Replace text values through an exact value map.",
                "column_ref": "many",
                "params_schema": {
                    "type": "object",
                    "properties": {**COLUMN_LIST_REFERENCE_PROPERTIES, "value_map": {"type": "object"}},
                    "required": ["value_map"],
                    "additionalProperties": False,
                },
                "example": {
                    "operation": "text.map_values",
                    "params": {"column_indexes": [2], "value_map": {"n": "north"}},
                },
            },
        ],
    },
    "validation": {
        "description": "Report invalid values or drop rows that violate a rule.",
        "operations": [
            {
                "operation": "validation.not_null",
                "description": "Find rows where a column is null.",
                "column_ref": "one",
                "params_schema": {
                    "type": "object",
                    "properties": {**COLUMN_REFERENCE_PROPERTIES, "action": ACTION_SCHEMA, "name": {"type": "string"}},
                    "additionalProperties": False,
                },
                "example": {"operation": "validation.not_null", "params": {"column_index": 1}},
            },
            {
                "operation": "validation.non_negative",
                "description": "Find rows where a numeric column is below zero.",
                "column_ref": "one",
                "params_schema": {
                    "type": "object",
                    "properties": {**COLUMN_REFERENCE_PROPERTIES, "action": ACTION_SCHEMA, "name": {"type": "string"}},
                    "additionalProperties": False,
                },
                "example": {
                    "operation": "validation.non_negative",
                    "params": {"column_index": 1, "action": "drop_rows"},
                },
            },
            {
                "operation": "validation.min",
                "description": "Find rows where a numeric column is below a minimum value.",
                "column_ref": "one",
                "params_schema": {
                    "type": "object",
                    "properties": {
                        **COLUMN_REFERENCE_PROPERTIES,
                        "value": {},
                        "action": ACTION_SCHEMA,
                        "name": {"type": "string"},
                    },
                    "required": ["value"],
                    "additionalProperties": False,
                },
                "example": {"operation": "validation.min", "params": {"column_index": 1, "value": 0}},
            },
            {
                "operation": "validation.max",
                "description": "Find rows where a numeric column is above a maximum value.",
                "column_ref": "one",
                "params_schema": {
                    "type": "object",
                    "properties": {
                        **COLUMN_REFERENCE_PROPERTIES,
                        "value": {},
                        "action": ACTION_SCHEMA,
                        "name": {"type": "string"},
                    },
                    "required": ["value"],
                    "additionalProperties": False,
                },
                "example": {"operation": "validation.max", "params": {"column_index": 1, "value": 1000}},
            },
            {
                "operation": "validation.allowed_values",
                "description": "Find rows where a value is outside an allowed set.",
                "column_ref": "one",
                "params_schema": {
                    "type": "object",
                    "properties": {
                        **COLUMN_REFERENCE_PROPERTIES,
                        "values": {"type": "array"},
                        "action": ACTION_SCHEMA,
                        "name": {"type": "string"},
                    },
                    "required": ["values"],
                    "additionalProperties": False,
                },
                "example": {
                    "operation": "validation.allowed_values",
                    "params": {"column_index": 2, "values": ["open", "closed"]},
                },
            },
            {
                "operation": "validation.regex",
                "description": "Find rows where text does not match a regular expression.",
                "column_ref": "one",
                "params_schema": {
                    "type": "object",
                    "properties": {
                        **COLUMN_REFERENCE_PROPERTIES,
                        "value": {},
                        "action": ACTION_SCHEMA,
                        "name": {"type": "string"},
                    },
                    "required": ["value"],
                    "additionalProperties": False,
                },
                "example": {
                    "operation": "validation.regex",
                    "params": {"column_index": 0, "value": r"^[^@]+@[^@]+$"},
                },
            },
        ],
    },
    "outliers": {
        "description": "Handle numeric outliers.",
        "operations": [
            {
                "operation": "outlier.clip_iqr",
                "description": "Clip numeric values outside IQR-derived bounds to the nearest bound.",
                "column_ref": "many",
                "params_schema": {
                    "type": "object",
                    "properties": {
                        **COLUMN_LIST_REFERENCE_PROPERTIES,
                        "multiplier": {"type": "number", "exclusiveMinimum": 0},
                    },
                    "additionalProperties": False,
                },
                "example": {
                    "operation": "outlier.clip_iqr",
                    "params": {"column_indexes": [1], "multiplier": 1.5},
                },
            },
        ],
    },
    "encoding": {
        "description": "Encode categorical columns for downstream analysis or modeling.",
        "operations": [
            {
                "operation": "encoding.one_hot",
                "description": "Expand categorical columns into deterministic one-hot indicator columns.",
                "column_ref": "many",
                "params_schema": {
                    "type": "object",
                    "properties": {
                        **COLUMN_LIST_REFERENCE_PROPERTIES,
                        "drop_first": BOOLEAN_SCHEMA,
                        "max_categories": {"type": "integer", "minimum": 1},
                    },
                    "additionalProperties": False,
                },
                "example": {
                    "operation": "encoding.one_hot",
                    "params": {"column_indexes": [2], "drop_first": False, "max_categories": 50},
                },
            },
        ],
    },
    "scaling": {
        "description": "Scale numeric columns for downstream analysis or modeling.",
        "operations": [
            {
                "operation": "scaling.minmax",
                "description": "Scale numeric columns into a configured feature range.",
                "column_ref": "many",
                "params_schema": {
                    "type": "object",
                    "properties": {
                        **COLUMN_LIST_REFERENCE_PROPERTIES,
                        "feature_range": {
                            "type": "array",
                            "items": {"type": "number"},
                            "minItems": 2,
                            "maxItems": 2,
                        },
                    },
                    "additionalProperties": False,
                },
                "example": {
                    "operation": "scaling.minmax",
                    "params": {"column_indexes": [1], "feature_range": [0, 1]},
                },
            },
            {
                "operation": "scaling.standard",
                "description": "Standardize numeric columns using mean and standard deviation.",
                "column_ref": "many",
                "params_schema": {
                    "type": "object",
                    "properties": {**COLUMN_LIST_REFERENCE_PROPERTIES},
                    "additionalProperties": False,
                },
                "example": {"operation": "scaling.standard", "params": {"column_indexes": [1]}},
            },
        ],
    },
}


# Keep the provider-facing catalog semantic without copying the verbose
# implementation descriptions into every result.  These labels are
# deliberately short: the full descriptions remain source-owned above, while
# metadata only needs enough language to route an unfamiliar operation.
_CLEANING_GROUP_SUMMARIES = {
    "schema": "Normalize names",
    "duplicates": "Drop duplicates",
    "missing": "Fill/drop missing",
    "types": "Convert types",
    "text": "Clean text",
    "validation": "Check values",
    "outliers": "Clip outliers",
    "encoding": "One-hot encode",
    "scaling": "Scale values",
}
_CLEANING_OPERATION_SUMMARIES = {
    "schema.normalize_column_names": "Normalize names",
    "duplicate.exact_rows": "Drop duplicates",
    "duplicate.key_columns": "Drop key duplicates",
    "missing.fill_mean": "Fill mean",
    "missing.fill_median": "Fill median",
    "missing.fill_mode": "Fill mode",
    "missing.fill_constant": "Fill constant",
    "missing.forward_fill": "Forward-fill gaps",
    "missing.drop_rows": "Drop missing rows",
    "missing.drop_high_missing_columns": "Drop sparse columns",
    "type.convert": "Convert type",
    "text.trim": "Trim text",
    "text.lowercase": "Lowercase",
    "text.uppercase": "Uppercase",
    "text.collapse_whitespace": "Collapse spaces",
    "text.empty_to_null": "Empty to null",
    "text.map_values": "Map text",
    "validation.not_null": "Find nulls",
    "validation.non_negative": "Find negatives",
    "validation.min": "Find below min",
    "validation.max": "Find above max",
    "validation.allowed_values": "Find disallowed",
    "validation.regex": "Find regex misses",
    "outlier.clip_iqr": "Clip outliers by IQR",
    "encoding.one_hot": "One-hot encode",
    "scaling.minmax": "Scale to range",
    "scaling.standard": "Standardize",
}
_COLUMN_INDEX_INVALIDATING_OPERATIONS = frozenset(
    {
        "missing.drop_high_missing_columns",
        "encoding.one_hot",
    }
)


def cleaning_operation_group_names() -> tuple[str, ...]:
    """Return the stable, provider-advertised cleaning metadata group names."""

    return tuple(_CLEANING_OPERATION_GROUPS)


def cleaning_operation_metadata(groups: list[str] | None = None) -> dict[str, Any]:
    selected_groups, invalid_groups = _normalize_groups(groups)
    payload = {
        "column_reference": {
            "index_base": 0,
            "single": "column_index preferred; column_name fallback; choose one",
            "multiple": "column_indexes preferred; column_names fallback; choose one",
        },
        "groups": [
            {
                "group": group,
                "summary": _cleaning_group_summary(group),
                "operations": [
                    _compact_cleaning_operation_metadata(operation)
                    for operation in _CLEANING_OPERATION_GROUPS[group]["operations"]
                ],
            }
            for group in selected_groups
        ],
        "group_names": list(cleaning_operation_group_names()),
        "operation_count": sum(len(_CLEANING_OPERATION_GROUPS[group]["operations"]) for group in selected_groups),
    }
    if invalid_groups:
        payload["invalid_groups"] = [
            {"group": group, "error_code": "unknown_group"}
            for group in invalid_groups
        ]
    return payload


def _compact_cleaning_operation_metadata(operation: dict[str, Any]) -> dict[str, Any]:
    operation_name = str(operation.get("operation") or "")
    params_schema = operation.get("params_schema")
    if not isinstance(params_schema, dict):
        return {
            "operation": operation_name,
            "summary": _cleaning_operation_summary(operation_name, operation),
            "params": [],
        }
    properties = params_schema.get("properties")
    if not isinstance(properties, dict):
        properties = {}
    required = {
        str(name)
        for name in params_schema.get("required", [])
        if isinstance(name, str)
    }
    params: list[str] = []
    column_ref = str(operation.get("column_ref") or "")
    if column_ref == "one":
        params.append("single_column")
    elif column_ref == "many":
        params.append("multiple_columns")
    elif column_ref == "many_optional":
        params.append("multiple_columns?")
    for name, schema in properties.items():
        if name in {
            "column_index",
            "column_name",
            "column_indexes",
            "column_names",
        }:
            continue
        params.append(_compact_cleaning_parameter_signature(str(name), schema, required=name in required))
    return {
        "operation": operation_name,
        "summary": _cleaning_operation_summary(operation_name, operation),
        "params": params,
    }


def _cleaning_group_summary(group: str) -> str:
    summary = _CLEANING_GROUP_SUMMARIES.get(group)
    if summary:
        return summary
    description = _CLEANING_OPERATION_GROUPS.get(group, {}).get("description")
    return _cleaning_summary_fallback(description, fallback="Cleaning operations")


def _cleaning_operation_summary(operation_name: str, operation: dict[str, Any]) -> str:
    summary = _CLEANING_OPERATION_SUMMARIES.get(operation_name)
    if summary:
        return summary
    return _cleaning_summary_fallback(
        operation.get("description"),
        fallback="Apply a cleaning operation",
    )


def _cleaning_summary_fallback(value: Any, *, fallback: str) -> str:
    normalized = re.sub(r"\s+", " ", str(value or "")).strip()
    if not normalized:
        return fallback
    # Descriptions are implementation-owned and may grow; metadata remains a
    # bounded routing hint even for a newly added operation without a map entry.
    return normalized[:72].rstrip(" .,;:")


def _compact_cleaning_parameter_signature(name: str, schema: Any, *, required: bool) -> str:
    label = name if required else f"{name}?"
    if not isinstance(schema, dict):
        return label
    enum = schema.get("enum")
    if isinstance(enum, list) and enum:
        values = "|".join(str(value) for value in enum)
        return f"{label}: {values}"
    value_type = schema.get("type")
    if value_type == "array":
        items = schema.get("items")
        item_type = str(items.get("type") or "value") if isinstance(items, dict) else "value"
        min_items = schema.get("minItems")
        max_items = schema.get("maxItems")
        if isinstance(min_items, int) and min_items == max_items:
            return f"{label}: {item_type}[{min_items}]"
        return f"{label}: {item_type}[]"
    if value_type == "number":
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if isinstance(minimum, (int, float)) and isinstance(maximum, (int, float)):
            return f"{label}: number {minimum}..{maximum}"
    if isinstance(value_type, str) and value_type:
        return f"{label}: {value_type}"
    return label


def _normalize_groups(groups: list[str] | None) -> tuple[list[str], list[str]]:
    if not groups:
        return list(_CLEANING_OPERATION_GROUPS), []
    normalized: list[str] = []
    invalid: list[str] = []
    for group in groups:
        value = str(group or "").strip()
        if not value or value in normalized or value in invalid:
            continue
        if value not in _CLEANING_OPERATION_GROUPS:
            invalid.append(value)
            continue
        normalized.append(value)
    if not normalized and not invalid:
        return list(_CLEANING_OPERATION_GROUPS), []
    return normalized, invalid


class CleanOperation(SQLModel):
    model_config = ConfigDict(extra="forbid")

    operation: str
    params: dict[str, Any] = Field(default_factory=dict)


class CleanDatasetInput(SQLModel):
    model_config = ConfigDict(extra="forbid")

    source_path: str
    name: str
    operations: list[CleanOperation] = Field(default_factory=list)


class CleanDatasetResult(SQLModel):
    output_path: str
    report: dict[str, Any] = Field(default_factory=dict)


class DataCleaningService:
    def __init__(
        self,
        paths: AppPaths,
        *,
        worker_runner: PreprocessingWorkerRunner | None = None,
    ) -> None:
        self._paths = paths
        self._worker_runner = worker_runner or LocalPreprocessingWorkerRunner()

    def clean_dataset(self, input_data: CleanDatasetInput) -> CleanDatasetResult:
        payload = self._worker_runner.run(
            "data.clean",
            {"input": input_data.model_dump(mode="json")},
            paths=self._paths,
        )
        return CleanDatasetResult.model_validate(payload)

    def _clean_dataset_in_process(self, input_data: CleanDatasetInput) -> CleanDatasetResult:
        started_at = perf_counter()
        with start_span("data.clean"):
            source_path = Path(input_data.source_path).expanduser()
            if not source_path.is_absolute():
                raise ValidationError("Dataset source path must be absolute.")
            if not source_path.exists() or not source_path.is_file():
                raise ValidationError("Dataset source path must point to an existing file.")

            source_format = detect_source_format(source_path)
            if source_format is DatasetSourceFormat.UNKNOWN:
                raise ValidationError("Only .csv, .parquet, .xlsx, and .xls dataset files are supported.")

            loaded = load_pandas_frame_with_schema(source_path, source_format, preserve_types=True)
            frame = loaded.frame
            if len(frame.columns) == 0:
                raise ValidationError("Dataset file must contain at least one column.")

            report: dict[str, Any] = {
                "row_count_before": int(len(frame.index)),
                "row_count_after": int(len(frame.index)),
                "operations": [],
                "validation_rules": [],
                "warnings": [],
            }

            if not input_data.operations:
                report["rows_removed"] = 0
                report["no_op"] = True
                self._record_operation(started_at)
                return CleanDatasetResult(output_path=str(source_path.resolve()), report=report)

            index_reference_invalidated_by: str | None = None
            for operation in input_data.operations:
                operation_name = str(operation.operation or "").strip()
                if index_reference_invalidated_by and self._uses_index_reference(operation.params):
                    raise ValidationError(
                        f"{operation_name or 'cleaning operation'}.params cannot use column_index(es) "
                        f"after '{index_reference_invalidated_by}' may add or remove columns in the same "
                        "data.clean call; use column_name(s), or start a new data.query/data.clean call."
                    )
                frame = self._apply_operation(frame, operation, report)
                if operation_name in _COLUMN_INDEX_INVALIDATING_OPERATIONS:
                    # Be conservative even when the operation happens to be a
                    # no-op (for example, one-hot skips a high-cardinality
                    # column): the caller cannot safely know the post-op index
                    # mapping while planning one atomic call.
                    index_reference_invalidated_by = operation_name

            output_dir = self._paths.artifacts / "datasets" / "cleaned"
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = output_dir / f"{self._slug(input_data.name)}-{uuid4().hex[:12]}.parquet"
            self._write_parquet(frame, output_path)

            report["row_count_after"] = int(len(frame.index))
            report["rows_removed"] = int(report["row_count_before"] - report["row_count_after"])
            report["no_op"] = False
            self._record_operation(started_at)
            return CleanDatasetResult(output_path=str(output_path.resolve()), report=report)

    def _write_parquet(self, frame: pd.DataFrame, output_path: Path) -> None:
        import duckdb

        with duckdb.connect(database=":memory:") as connection:
            connection.register("cleaned_frame", frame)
            connection.execute(
                "COPY cleaned_frame TO ? (FORMAT PARQUET)",
                [str(output_path)],
            )

    def _record_operation(self, started_at: float) -> None:
        attributes = {"data.operation": "data.clean", "status": "succeeded"}
        record_counter("xenix.data.operation.count", attributes=attributes)
        record_histogram(
            "xenix.data.operation.duration",
            (perf_counter() - started_at) * 1000,
            attributes=attributes,
            unit="ms",
        )

    def _apply_operation(
        self,
        frame: pd.DataFrame,
        operation: CleanOperation,
        report: dict[str, Any],
    ) -> pd.DataFrame:
        operation_name = str(operation.operation or "").strip()
        params = dict(operation.params or {})
        if not operation_name:
            raise ValidationError("cleaning operation cannot be empty.")

        if operation_name.startswith("schema."):
            return self._apply_schema_operation(frame, operation_name, params, report)
        if operation_name == "duplicate.exact_rows":
            return self._apply_duplicate_exact_rows(frame, operation_name, params, report)
        if operation_name == "duplicate.key_columns":
            return self._apply_duplicate_key_columns(frame, operation_name, params, report)
        if operation_name.startswith("missing."):
            return self._apply_missing_operation(frame, operation_name, params, report)
        if operation_name == "type.convert":
            return self._apply_type_convert(frame, operation_name, params, report)
        if operation_name.startswith("text."):
            return self._apply_text_operation(frame, operation_name, params, report)
        if operation_name.startswith("validation."):
            return self._apply_validation_operation(frame, operation_name, params, report)
        if operation_name.startswith("outlier."):
            return self._apply_outlier_operation(frame, operation_name, params, report)
        if operation_name.startswith("encoding."):
            return self._apply_encoding_operation(frame, operation_name, params, report)
        if operation_name.startswith("scaling."):
            return self._apply_scaling_operation(frame, operation_name, params, report)
        raise ValidationError(f"Unsupported cleaning operation '{operation_name}'.")

    @staticmethod
    def _uses_index_reference(params: dict[str, Any]) -> bool:
        return any(
            key in params and params.get(key) is not None
            for key in ("column_index", "column_indexes")
        )

    def _apply_schema_operation(
        self,
        frame: pd.DataFrame,
        operation_name: str,
        params: dict[str, Any],
        report: dict[str, Any],
    ) -> pd.DataFrame:
        if operation_name != "schema.normalize_column_names":
            raise ValidationError(f"Unsupported cleaning operation '{operation_name}'.")
        style = self._one_of(
            str(params.get("style") or "snake_case"),
            {"snake_case"},
            f"{operation_name}.params.style",
        )
        ascii_lower = self._bool_param(params, "ascii_lower", default=True, operation_name=operation_name)
        original_columns = [str(column) for column in frame.columns]
        bases: list[str] = []
        generated_empty: list[dict[str, Any]] = []
        for index, column in enumerate(original_columns):
            base, was_empty = self._normalize_column_name_base(column, index, ascii_lower=ascii_lower)
            bases.append(base)
            if was_empty:
                generated_empty.append({"column_index": index, "new": base})
        new_columns, duplicate_collisions = self._dedupe_normalized_names(bases)
        cleaned = frame.copy()
        cleaned.columns = new_columns
        mapping = [
            {"old": old, "new": new}
            for old, new in zip(original_columns, new_columns, strict=False)
        ]
        report["operations"].append(
            {
                "operation": operation_name,
                "style": style,
                "ascii_lower": ascii_lower,
                "columns_changed": sum(1 for old, new in zip(original_columns, new_columns, strict=False) if old != new),
                "mapping": mapping,
                "generated_empty_names": generated_empty,
                "duplicate_collisions": duplicate_collisions,
            }
        )
        return cleaned

    def _apply_duplicate_exact_rows(
        self,
        frame: pd.DataFrame,
        operation_name: str,
        params: dict[str, Any],
        report: dict[str, Any],
    ) -> pd.DataFrame:
        keep = self._keep_value(params, operation_name)
        before = int(len(frame.index))
        cleaned = frame.drop_duplicates(keep=keep)
        report["operations"].append(
            {
                "operation": operation_name,
                "rows_removed": before - int(len(cleaned.index)),
            }
        )
        return cleaned

    def _apply_duplicate_key_columns(
        self,
        frame: pd.DataFrame,
        operation_name: str,
        params: dict[str, Any],
        report: dict[str, Any],
    ) -> pd.DataFrame:
        columns = self._params_columns(frame, params, operation_name)
        keep = self._keep_value(params, operation_name)
        before = int(len(frame.index))
        cleaned = frame.drop_duplicates(subset=columns, keep=keep)
        report["operations"].append(
            {
                "operation": operation_name,
                "columns": columns,
                "rows_removed": before - int(len(cleaned.index)),
            }
        )
        return cleaned

    def _apply_missing_operation(
        self,
        frame: pd.DataFrame,
        operation_name: str,
        params: dict[str, Any],
        report: dict[str, Any],
    ) -> pd.DataFrame:
        strategy_by_operation = {
            "missing.fill_mean": "mean",
            "missing.fill_median": "median",
            "missing.fill_mode": "mode",
            "missing.fill_constant": "constant",
            "missing.forward_fill": "forward_fill",
            "missing.drop_rows": "drop_rows",
            "missing.drop_high_missing_columns": "drop_high_missing_columns",
        }
        strategy = strategy_by_operation.get(operation_name)
        if strategy is None:
            raise ValidationError(f"Unsupported cleaning operation '{operation_name}'.")
        if strategy == "drop_high_missing_columns":
            return self._apply_drop_high_missing_columns(frame, operation_name, params, report)

        columns = self._params_columns(frame, params, operation_name)
        if strategy == "drop_rows":
            before = int(len(frame.index))
            mask = frame[columns].isna().any(axis=1)
            cleaned = frame.loc[~mask].copy()
            report["operations"].append(
                {
                    "operation": operation_name,
                    "columns": columns,
                    "rows_removed": before - int(len(cleaned.index)),
                }
            )
            return cleaned

        if strategy == "constant" and "value" not in params:
            raise ValidationError(f"{operation_name}.params.value is required.")
        for column in columns:
            missing_before = int(frame[column].isna().sum())
            if missing_before == 0:
                continue
            if strategy == "forward_fill":
                frame[column] = frame[column].ffill()
            else:
                fill_value = self._resolve_fill_value(frame[column], strategy, column, params.get("value"), report)
                frame[column] = frame[column].fillna(fill_value)
            report["operations"].append(
                {
                    "operation": operation_name,
                    "column": column,
                    "cells_filled": missing_before - int(frame[column].isna().sum()),
                }
            )
        return frame

    def _apply_drop_high_missing_columns(
        self,
        frame: pd.DataFrame,
        operation_name: str,
        params: dict[str, Any],
        report: dict[str, Any],
    ) -> pd.DataFrame:
        threshold = self._ratio_param(params, "threshold", operation_name)
        columns = self._params_optional_columns(frame, params, operation_name)
        ratios = {column: float(frame[column].isna().mean()) for column in columns}
        dropped_columns = [column for column, ratio in ratios.items() if ratio > threshold]
        cleaned = frame.drop(columns=dropped_columns) if dropped_columns else frame
        report["operations"].append(
            {
                "operation": operation_name,
                "threshold": threshold,
                "evaluated_columns": columns,
                "missing_ratios": ratios,
                "dropped_columns": dropped_columns,
                "columns_removed": len(dropped_columns),
            }
        )
        return cleaned

    def _resolve_fill_value(
        self,
        series: pd.Series,
        strategy: str,
        column: str,
        value: Any,
        report: dict[str, Any],
    ) -> Any:
        if strategy == "constant":
            return "" if value is None else value
        if strategy in {"mean", "median"} and not is_numeric_dtype(series):
            raise ValidationError(f"Column '{column}' must be numeric for {strategy} fill.")
        if strategy == "mean":
            fill_value = series.mean()
        elif strategy == "median":
            fill_value = series.median()
        elif strategy == "mode":
            mode = series.dropna().mode()
            fill_value = "" if mode.empty else mode.iloc[0]
        else:
            raise ValidationError(f"Unsupported missing strategy '{strategy}'.")
        if pd.isna(fill_value):
            report["warnings"].append(
                f"Column '{column}' has no non-empty values for {strategy} fill; missing values were left empty."
            )
            return ""
        return fill_value

    def _apply_type_convert(
        self,
        frame: pd.DataFrame,
        operation_name: str,
        params: dict[str, Any],
        report: dict[str, Any],
    ) -> pd.DataFrame:
        column = self._params_column(frame, params, operation_name)
        target_type = self._one_of(
            str(params.get("target_type") or ""),
            {"numeric", "integer", "datetime", "text", "boolean"},
            f"{operation_name}.params.target_type",
        )
        before_notna = frame[column].notna()
        if target_type == "numeric":
            converted = pd.to_numeric(frame[column], errors="coerce")
        elif target_type == "integer":
            converted = pd.to_numeric(frame[column], errors="coerce").round().astype("Int64")
        elif target_type == "datetime":
            date_format = str(params.get("date_format") or "").strip() or None
            converted = pd.to_datetime(frame[column], errors="coerce", format=date_format)
        elif target_type == "text":
            converted = frame[column].astype("string")
        else:
            converted = self._to_boolean(frame[column])
        coerced_to_null = int((before_notna & converted.isna()).sum())
        frame[column] = converted
        report["operations"].append(
            {
                "operation": operation_name,
                "column": column,
                "target_type": target_type,
                "coerced_to_null": coerced_to_null,
            }
        )
        return frame

    def _apply_text_operation(
        self,
        frame: pd.DataFrame,
        operation_name: str,
        params: dict[str, Any],
        report: dict[str, Any],
    ) -> pd.DataFrame:
        columns = self._params_columns(frame, params, operation_name)
        value_map = params.get("value_map")
        if operation_name == "text.map_values" and not isinstance(value_map, dict):
            raise ValidationError(f"{operation_name}.params.value_map must be an object.")

        for column in columns:
            original = frame[column].copy()
            values = frame[column].astype("string")
            if operation_name == "text.trim":
                values = values.str.strip()
            elif operation_name == "text.lowercase":
                values = values.str.lower()
            elif operation_name == "text.uppercase":
                values = values.str.upper()
            elif operation_name == "text.collapse_whitespace":
                values = values.str.replace(r"\s+", " ", regex=True)
            elif operation_name == "text.empty_to_null":
                values = values.replace(r"^\s*$", pd.NA, regex=True)
            elif operation_name == "text.map_values":
                values = values.replace(value_map)
            else:
                raise ValidationError(f"Unsupported cleaning operation '{operation_name}'.")
            frame[column] = values
            changed = int((original.astype("string") != frame[column].astype("string")).fillna(False).sum())
            report["operations"].append(
                {
                    "operation": operation_name,
                    "column": column,
                    "cells_changed": changed,
                }
            )
        return frame

    def _apply_validation_operation(
        self,
        frame: pd.DataFrame,
        operation_name: str,
        params: dict[str, Any],
        report: dict[str, Any],
    ) -> pd.DataFrame:
        column = self._params_column(frame, params, operation_name)
        action = self._one_of(
            str(params.get("action") or "report_only"),
            {"report_only", "drop_rows"},
            f"{operation_name}.params.action",
        )
        mask = self._validation_mask(frame[column], operation_name, params)
        violations = int(mask.sum())
        entry = {
            "name": str(params.get("name") or operation_name).strip() or operation_name,
            "column": column,
            "operation": operation_name,
            "action": action,
            "violations": violations,
        }
        if action == "drop_rows" and violations:
            frame = frame.loc[~mask].copy()
            entry["rows_removed"] = violations
        report["validation_rules"].append(entry)
        return frame

    def _validation_mask(self, series: pd.Series, operation_name: str, params: dict[str, Any]) -> pd.Series:
        if operation_name == "validation.not_null":
            return series.isna()
        if operation_name == "validation.non_negative":
            return pd.to_numeric(series, errors="coerce") < 0
        if operation_name == "validation.min":
            return pd.to_numeric(series, errors="coerce") < self._float_param(params, operation_name)
        if operation_name == "validation.max":
            return pd.to_numeric(series, errors="coerce") > self._float_param(params, operation_name)
        if operation_name == "validation.allowed_values":
            values = params.get("values")
            if not isinstance(values, list):
                raise ValidationError(f"{operation_name}.params.values must be a list.")
            return ~series.isin(values)
        if operation_name == "validation.regex":
            if "value" not in params:
                raise ValidationError(f"{operation_name}.params.value is required.")
            pattern = re.compile(str(params.get("value") or ""))
            return ~series.astype("string").fillna("").str.match(pattern)
        raise ValidationError(f"Unsupported cleaning operation '{operation_name}'.")

    def _apply_outlier_operation(
        self,
        frame: pd.DataFrame,
        operation_name: str,
        params: dict[str, Any],
        report: dict[str, Any],
    ) -> pd.DataFrame:
        if operation_name != "outlier.clip_iqr":
            raise ValidationError(f"Unsupported cleaning operation '{operation_name}'.")
        columns = self._params_columns(frame, params, operation_name)
        multiplier = self._positive_float_param(params, "multiplier", operation_name, default=1.5)
        summaries: list[dict[str, Any]] = []
        for column in columns:
            self._require_numeric_column(frame, column, operation_name)
            series = frame[column]
            q1 = series.quantile(0.25)
            q3 = series.quantile(0.75)
            if pd.isna(q1) or pd.isna(q3):
                report["warnings"].append(f"Column '{column}' has no numeric values for IQR clipping.")
                summaries.append(
                    {
                        "column": column,
                        "q1": None,
                        "q3": None,
                        "iqr": None,
                        "lower_bound": None,
                        "upper_bound": None,
                        "cells_clipped": 0,
                    }
                )
                continue
            iqr = q3 - q1
            lower_bound = q1 - multiplier * iqr
            upper_bound = q3 + multiplier * iqr
            clipped = series.clip(lower=lower_bound, upper=upper_bound)
            cells_clipped = int((series.notna() & (series != clipped)).sum())
            frame[column] = clipped
            summaries.append(
                {
                    "column": column,
                    "q1": float(q1),
                    "q3": float(q3),
                    "iqr": float(iqr),
                    "lower_bound": float(lower_bound),
                    "upper_bound": float(upper_bound),
                    "cells_clipped": cells_clipped,
                }
            )
        report["operations"].append(
            {
                "operation": operation_name,
                "columns": columns,
                "multiplier": multiplier,
                "columns_summary": summaries,
            }
        )
        return frame

    def _apply_encoding_operation(
        self,
        frame: pd.DataFrame,
        operation_name: str,
        params: dict[str, Any],
        report: dict[str, Any],
    ) -> pd.DataFrame:
        if operation_name != "encoding.one_hot":
            raise ValidationError(f"Unsupported cleaning operation '{operation_name}'.")
        columns = self._params_columns(frame, params, operation_name)
        drop_first = self._bool_param(params, "drop_first", default=False, operation_name=operation_name)
        max_categories = self._positive_int_param(params, "max_categories", operation_name, default=50)
        used_columns = {str(column) for column in frame.columns if str(column) not in columns}
        generated_frames: list[pd.DataFrame] = []
        encoded_columns: list[str] = []
        skipped_columns: list[dict[str, Any]] = []
        summaries: list[dict[str, Any]] = []

        for column in columns:
            series = frame[column]
            categories = sorted(series.dropna().unique().tolist(), key=lambda value: str(value))
            if len(categories) > max_categories:
                skipped_columns.append(
                    {
                        "column": column,
                        "category_count": len(categories),
                        "max_categories": max_categories,
                        "reason": "too_many_categories",
                    }
                )
                report["warnings"].append(
                    f"Column '{column}' has {len(categories)} categories, above max_categories={max_categories}; it was not encoded."
                )
                continue
            emitted_categories = categories[1:] if drop_first else categories
            generated_data: dict[str, pd.Series] = {}
            generated_names: list[str] = []
            category_columns: list[dict[str, str]] = []
            for category in emitted_categories:
                raw_name = f"{column}_{category}"
                generated_name = self._normalized_unique_column_name(raw_name, used_columns)
                used_columns.add(generated_name)
                generated_data[generated_name] = series.eq(category).fillna(False).astype(int)
                generated_names.append(generated_name)
                category_columns.append({"category": str(category), "column": generated_name})
            if generated_data:
                generated_frames.append(pd.DataFrame(generated_data, index=frame.index))
            encoded_columns.append(column)
            summaries.append(
                {
                    "column": column,
                    "category_count": len(categories),
                    "encoded_category_count": len(emitted_categories),
                    "drop_first": drop_first,
                    "generated_columns": generated_names,
                    "category_columns": category_columns,
                }
            )

        cleaned = frame.drop(columns=encoded_columns) if encoded_columns else frame
        if generated_frames:
            cleaned = pd.concat([cleaned, *generated_frames], axis=1)
        report["operations"].append(
            {
                "operation": operation_name,
                "columns": columns,
                "drop_first": drop_first,
                "max_categories": max_categories,
                "encoded_columns": encoded_columns,
                "skipped_columns": skipped_columns,
                "columns_summary": summaries,
            }
        )
        return cleaned

    def _apply_scaling_operation(
        self,
        frame: pd.DataFrame,
        operation_name: str,
        params: dict[str, Any],
        report: dict[str, Any],
    ) -> pd.DataFrame:
        columns = self._params_columns(frame, params, operation_name)
        if operation_name == "scaling.minmax":
            feature_min, feature_max = self._feature_range_param(params, operation_name)
            summaries = []
            for column in columns:
                self._require_numeric_column(frame, column, operation_name)
                series = frame[column]
                original_min = series.min()
                original_max = series.max()
                if pd.isna(original_min) or pd.isna(original_max) or original_min == original_max:
                    report["warnings"].append(
                        f"Column '{column}' is empty or constant; minmax scaling left it unchanged."
                    )
                    summaries.append(
                        {
                            "column": column,
                            "original_min": None if pd.isna(original_min) else float(original_min),
                            "original_max": None if pd.isna(original_max) else float(original_max),
                            "target_min": feature_min,
                            "target_max": feature_max,
                            "scaled": False,
                        }
                    )
                    continue
                frame[column] = ((series - original_min) / (original_max - original_min)) * (
                    feature_max - feature_min
                ) + feature_min
                summaries.append(
                    {
                        "column": column,
                        "original_min": float(original_min),
                        "original_max": float(original_max),
                        "target_min": feature_min,
                        "target_max": feature_max,
                        "scaled": True,
                    }
                )
            report["operations"].append(
                {
                    "operation": operation_name,
                    "columns": columns,
                    "feature_range": [feature_min, feature_max],
                    "columns_summary": summaries,
                }
            )
            return frame

        if operation_name == "scaling.standard":
            summaries = []
            for column in columns:
                self._require_numeric_column(frame, column, operation_name)
                series = frame[column]
                mean = series.mean()
                std = series.std(ddof=0)
                if pd.isna(mean) or pd.isna(std) or std == 0:
                    report["warnings"].append(
                        f"Column '{column}' is empty or constant; standard scaling left it unchanged."
                    )
                    summaries.append(
                        {
                            "column": column,
                            "mean": None if pd.isna(mean) else float(mean),
                            "std": None if pd.isna(std) else float(std),
                            "scaled": False,
                        }
                    )
                    continue
                frame[column] = (series - mean) / std
                summaries.append(
                    {
                        "column": column,
                        "mean": float(mean),
                        "std": float(std),
                        "scaled": True,
                    }
                )
            report["operations"].append(
                {
                    "operation": operation_name,
                    "columns": columns,
                    "columns_summary": summaries,
                }
            )
            return frame

        raise ValidationError(f"Unsupported cleaning operation '{operation_name}'.")

    def _float_param(self, params: dict[str, Any], operation_name: str) -> float:
        if "value" not in params:
            raise ValidationError(f"{operation_name}.params.value is required.")
        try:
            return float(params.get("value"))
        except (TypeError, ValueError) as exc:
            raise ValidationError(f"{operation_name}.params.value must be numeric.") from exc

    def _ratio_param(self, params: dict[str, Any], key: str, operation_name: str) -> float:
        if key not in params:
            raise ValidationError(f"{operation_name}.params.{key} is required.")
        try:
            value = float(params.get(key))
        except (TypeError, ValueError) as exc:
            raise ValidationError(f"{operation_name}.params.{key} must be numeric.") from exc
        if value < 0 or value > 1:
            raise ValidationError(f"{operation_name}.params.{key} must be between 0 and 1.")
        return value

    def _positive_float_param(
        self,
        params: dict[str, Any],
        key: str,
        operation_name: str,
        *,
        default: float,
    ) -> float:
        raw_value = params.get(key, default)
        try:
            value = float(raw_value)
        except (TypeError, ValueError) as exc:
            raise ValidationError(f"{operation_name}.params.{key} must be numeric.") from exc
        if value <= 0:
            raise ValidationError(f"{operation_name}.params.{key} must be greater than 0.")
        return value

    def _positive_int_param(
        self,
        params: dict[str, Any],
        key: str,
        operation_name: str,
        *,
        default: int,
    ) -> int:
        raw_value = params.get(key, default)
        if isinstance(raw_value, bool):
            raise ValidationError(f"{operation_name}.params.{key} must be an integer.")
        try:
            value = int(raw_value)
        except (TypeError, ValueError) as exc:
            raise ValidationError(f"{operation_name}.params.{key} must be an integer.") from exc
        if value < 1:
            raise ValidationError(f"{operation_name}.params.{key} must be greater than 0.")
        return value

    def _bool_param(
        self,
        params: dict[str, Any],
        key: str,
        *,
        default: bool,
        operation_name: str,
    ) -> bool:
        if key not in params:
            return default
        value = params.get(key)
        if not isinstance(value, bool):
            raise ValidationError(f"{operation_name}.params.{key} must be a boolean.")
        return value

    def _feature_range_param(self, params: dict[str, Any], operation_name: str) -> tuple[float, float]:
        raw_value = params.get("feature_range", [0, 1])
        if not isinstance(raw_value, list) or len(raw_value) != 2:
            raise ValidationError(f"{operation_name}.params.feature_range must be a two-number list.")
        try:
            feature_min = float(raw_value[0])
            feature_max = float(raw_value[1])
        except (TypeError, ValueError) as exc:
            raise ValidationError(f"{operation_name}.params.feature_range values must be numeric.") from exc
        if feature_min >= feature_max:
            raise ValidationError(f"{operation_name}.params.feature_range first value must be less than second value.")
        return feature_min, feature_max

    def _keep_value(self, params: dict[str, Any], operation_name: str) -> str | bool:
        keep = self._one_of(str(params.get("keep") or "first"), {"first", "last", "false"}, f"{operation_name}.params.keep")
        return False if keep == "false" else keep

    def _params_columns(self, frame: pd.DataFrame, params: dict[str, Any], operation_name: str) -> list[str]:
        return self._resolve_column_list_reference(
            frame,
            params,
            operation_name,
            required=True,
        )

    def _params_optional_columns(self, frame: pd.DataFrame, params: dict[str, Any], operation_name: str) -> list[str]:
        return self._resolve_column_list_reference(
            frame,
            params,
            operation_name,
            required=False,
        )

    def _params_column(self, frame: pd.DataFrame, params: dict[str, Any], operation_name: str) -> str:
        active_keys = self._active_reference_keys(
            params,
            ("column_index", "column_name", "column"),
        )
        if len(active_keys) > 1:
            raise ValidationError(
                f"{operation_name}.params must use either column_index or column_name, not both."
            )
        if not active_keys:
            raise ValidationError(f"{operation_name}.params requires column_index or column_name.")
        key = active_keys[0]
        if key == "column_index":
            return self._column_at_index(
                frame,
                params.get(key),
                f"{operation_name}.params.column_index",
            )
        return self._require_column(frame, str(params.get(key) or ""), f"{operation_name}.params.{key}")

    def _resolve_column_list_reference(
        self,
        frame: pd.DataFrame,
        params: dict[str, Any],
        operation_name: str,
        *,
        required: bool,
    ) -> list[str]:
        active_keys = self._active_reference_keys(
            params,
            ("column_indexes", "column_names", "columns"),
        )
        if len(active_keys) > 1:
            raise ValidationError(
                f"{operation_name}.params must use either column_indexes or column_names, not both."
            )
        if not active_keys:
            if required:
                raise ValidationError(f"{operation_name}.params requires column_indexes or column_names.")
            return [str(column) for column in frame.columns]
        key = active_keys[0]
        values = params.get(key)
        if not isinstance(values, list):
            raise ValidationError(f"{operation_name}.params.{key} must be a list.")
        if key == "column_indexes":
            if not values:
                raise ValidationError(f"{operation_name}.params.column_indexes cannot be empty.")
            return [
                self._column_at_index(frame, value, f"{operation_name}.params.column_indexes")
                for value in values
            ]
        return self._require_columns(frame, values, f"{operation_name}.params.{key}")

    @staticmethod
    def _active_reference_keys(params: dict[str, Any], keys: tuple[str, ...]) -> list[str]:
        return [key for key in keys if key in params and params.get(key) is not None]

    def _column_at_index(self, frame: pd.DataFrame, value: Any, field_name: str) -> str:
        schema = resolve_tabular_schema(frame.columns)
        return resolve_tabular_column_index(schema, value, field_name=field_name)

    def _require_numeric_column(self, frame: pd.DataFrame, column: str, operation_name: str) -> None:
        if not is_numeric_dtype(frame[column]) or is_bool_dtype(frame[column]):
            raise ValidationError(f"Column '{column}' must be numeric for {operation_name}.")

    def _normalize_column_name_base(
        self,
        value: str,
        index: int,
        *,
        ascii_lower: bool = True,
    ) -> tuple[str, bool]:
        normalized = unicodedata.normalize("NFKC", str(value or "").strip())
        parts: list[str] = []
        previous_was_separator = False
        for char in normalized:
            if char.isalnum():
                if ascii_lower and "A" <= char <= "Z":
                    char = char.lower()
                parts.append(char)
                previous_was_separator = False
            elif not previous_was_separator:
                parts.append("_")
                previous_was_separator = True
        candidate = "".join(parts).strip("_")
        if not candidate:
            return f"column_{index + 1}", True
        return candidate, False

    def _dedupe_normalized_names(self, bases: list[str]) -> tuple[list[str], list[dict[str, Any]]]:
        used: set[str] = set()
        seen_by_base: dict[str, int] = {}
        names: list[str] = []
        collisions: list[dict[str, Any]] = []
        for index, base in enumerate(bases):
            count = seen_by_base.get(base, 0) + 1
            seen_by_base[base] = count
            candidate = base if count == 1 else f"{base}_{count}"
            while candidate in used:
                count += 1
                seen_by_base[base] = count
                candidate = f"{base}_{count}"
            if candidate != base:
                collisions.append(
                    {
                        "column_index": index,
                        "base_name": base,
                        "resolved_name": candidate,
                    }
                )
            names.append(candidate)
            used.add(candidate)
        return names, collisions

    def _normalized_unique_column_name(self, value: str, used_names: set[str]) -> str:
        base, _was_empty = self._normalize_column_name_base(value, len(used_names), ascii_lower=True)
        candidate = base
        suffix = 2
        while candidate in used_names:
            candidate = f"{base}_{suffix}"
            suffix += 1
        return candidate

    def _to_boolean(self, series: pd.Series) -> pd.Series:
        true_values = {"true", "t", "yes", "y", "1"}
        false_values = {"false", "f", "no", "n", "0"}

        def convert(value: Any) -> bool | None:
            if pd.isna(value):
                return None
            if isinstance(value, bool):
                return value
            normalized = str(value).strip().lower()
            if normalized in true_values:
                return True
            if normalized in false_values:
                return False
            return None

        return series.map(convert).astype("boolean")

    def _require_columns(self, frame: pd.DataFrame, columns: list[str], field_name: str) -> list[str]:
        normalized = [self._require_column(frame, column, field_name) for column in columns if str(column).strip()]
        if not normalized:
            raise ValidationError(f"{field_name} cannot be empty.")
        return normalized

    def _require_column(self, frame: pd.DataFrame, column: str, field_name: str) -> str:
        normalized = str(column or "").strip()
        if not normalized:
            raise ValidationError(f"{field_name} cannot be empty.")
        if normalized not in frame.columns:
            raise ValidationError(f"Column '{normalized}' does not exist.")
        return normalized

    def _one_of(self, value: str, allowed: set[str], field_name: str) -> str:
        normalized = str(value or "").strip()
        if normalized not in allowed:
            raise ValidationError(f"{field_name} must be one of: {', '.join(sorted(allowed))}.")
        return normalized

    def _slug(self, value: str) -> str:
        normalized = "".join(char.lower() if char.isalnum() else "-" for char in value).strip("-")
        return normalized or "dataset"
