from __future__ import annotations

import importlib.metadata
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import duckdb

from ..exceptions import ValidationError
from .storage.models import DatasetSourceFormat


class TabularRuntimeError(RuntimeError):
    def __init__(self, message: str, *, error_details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.error_details = dict(error_details or {})


@dataclass(frozen=True)
class TabularColumnSchema:
    index: int
    tool_name: str
    source_name: str | None
    loader_name: str | None
    name_source: str


@dataclass(frozen=True)
class TabularSchema:
    columns: list[TabularColumnSchema]
    resolver_version: int = 1


@dataclass(frozen=True)
class LoadedPandasFrame:
    frame: pd.DataFrame
    schema: TabularSchema


_PANDAS_UNNAMED_PATTERN = re.compile(r"^Unnamed:\s*\d+(?:_level_\d+)?$")
_POLARS_UNNAMED_PATTERN = re.compile(r"^__UNNAMED__\d+$")
_PANDAS_DUPLICATE_SUFFIX_PATTERN = re.compile(r"^(?P<base>.+)\.(?P<suffix>[1-9]\d*)$")
_POLARS_DUPLICATE_SUFFIX_PATTERN = re.compile(r"^(?P<base>.+)_duplicated_(?P<suffix>\d+)$")
_MAX_STABLE_COLUMN_NAME_LENGTH = 120


def tabular_runtime_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for package_name in ("polars", "polars-runtime-32", "polars-runtime-64", "fastexcel"):
        try:
            versions[package_name] = importlib.metadata.version(package_name)
        except importlib.metadata.PackageNotFoundError:
            continue
    return versions


def load_tabular_frame(path: Path, source_format: DatasetSourceFormat):
    try:
        import polars as pl
    except Exception as exc:  # pragma: no cover - depends on local runtime state
        raise TabularRuntimeError(
            "Polars import failed.",
            error_details=_tabular_runtime_error_details(
                path=path,
                source_format=source_format,
                exc=exc,
                phase="import",
            ),
        ) from exc

    try:
        if source_format is DatasetSourceFormat.CSV:
            return pl.read_csv(path, try_parse_dates=False, infer_schema_length=None)
        if source_format is DatasetSourceFormat.PARQUET:
            return pl.read_parquet(path)
        if source_format in {DatasetSourceFormat.XLSX, DatasetSourceFormat.XLS}:
            return pl.read_excel(path, engine="calamine")
    except Exception as exc:  # pragma: no cover - depends on local runtime state
        raise TabularRuntimeError(
            "Polars failed to read the dataset file.",
            error_details=_tabular_runtime_error_details(
                path=path,
                source_format=source_format,
                exc=exc,
                phase="read",
            ),
        ) from exc

    raise ValidationError("Only .csv, .parquet, .xlsx, and .xls dataset files are supported.")


def load_pandas_frame_with_schema(
    path: Path,
    source_format: DatasetSourceFormat,
    *,
    preserve_types: bool = False,
) -> LoadedPandasFrame:
    """Load a pandas frame and project its columns into the shared schema.

    Spreadsheet reads default to the historical string-preserving tool shape.
    Type-sensitive local operations may opt into pandas' native dtype/NA
    inference with ``preserve_types=True`` without changing query behavior.
    """

    frame = _load_pandas_frame_for_tools(path, source_format, preserve_types=preserve_types)
    schema = resolve_tabular_schema(frame.columns)
    return LoadedPandasFrame(frame=apply_tabular_schema(frame, schema), schema=schema)


def load_tabular_schema(
    path: Path,
    source_format: DatasetSourceFormat,
    *,
    sheet_name: str | int | None = None,
) -> TabularSchema:
    """Resolve a file's schema through the authoritative pandas header route.

    The route reads headers only and is useful to consumers that need the
    source-column order without materializing all rows.  ``sheet_name`` may
    select a workbook sheet by name or zero-based index.  Loader-derived
    pandas suffixes are normalized by :func:`resolve_tabular_schema`, which
    also recognizes Polars/calamine suffixes when a Polars frame is supplied
    directly.
    """

    if source_format is DatasetSourceFormat.XLS:
        # The native tabular loader supports legacy BIFF workbooks through
        # Calamine, while pandas may not have an XLS engine installed.  Keep
        # the supported-loader boundary intact even though this fallback must
        # inspect the loaded frame rather than only its header.
        frame = load_tabular_frame(path, source_format)
        return resolve_tabular_schema(frame.columns)

    frame = _load_pandas_frame_for_tools(
        path,
        source_format,
        preserve_types=False,
        header_only=True,
        sheet_name=sheet_name,
    )
    return resolve_tabular_schema(frame.columns)


def resolve_tabular_schema_for_loaded_frame(
    path: Path,
    source_format: DatasetSourceFormat,
    frame: Any,
    *,
    sheet_name: str | int | None = None,
) -> TabularSchema:
    """Return the canonical schema that can safely be applied to ``frame``.

    A header-only schema preserves pandas' stable treatment of spreadsheet
    headers, including numeric cells.  Some malformed workbooks, however,
    have trailing blank header cells which pandas omits while Calamine still
    exposes as data columns.  The loaded frame is then the authority for the
    visible width; its extra positions receive the same canonical treatment
    as loader placeholders.  Legacy ``.xls`` files use the already-loaded
    frame directly so supported Calamine reads do not depend on pandas/XLRD.
    """

    if not hasattr(frame, "columns"):
        raise TypeError("resolve_tabular_schema_for_loaded_frame expects a tabular frame.")
    loaded_columns = list(frame.columns)
    if source_format is DatasetSourceFormat.XLS:
        return resolve_tabular_schema(loaded_columns)
    header_schema = load_tabular_schema(path, source_format, sheet_name=sheet_name)
    return reconcile_tabular_schema_to_loaded_columns(header_schema, loaded_columns)


def reconcile_tabular_schema_to_loaded_columns(
    header_schema: TabularSchema,
    loaded_columns: list[Any],
) -> TabularSchema:
    """Keep header authority where possible, but never name invisible columns.

    ``loaded_columns`` may come from an already-loaded Pandas/Polars frame or
    from a lightweight spreadsheet header scan.  It is only used to reconcile
    visible positional width when the header-only reader omitted trailing
    malformed cells.
    """

    if len(header_schema.columns) == len(loaded_columns):
        return header_schema

    loaded_schema = resolve_tabular_schema(loaded_columns)
    if len(loaded_columns) < len(header_schema.columns):
        return loaded_schema

    merged_columns = [
        *header_schema.columns,
        *loaded_schema.columns[len(header_schema.columns):],
    ]
    normalized_names = [_normalize_column_name(column.tool_name) for column in merged_columns]
    if len(set(normalized_names)) != len(normalized_names):
        return loaded_schema
    return TabularSchema(
        columns=merged_columns,
        resolver_version=header_schema.resolver_version,
    )


def resolve_tabular_schema(column_names: Any) -> TabularSchema:
    raw_columns = list(column_names)
    inspected = [_inspect_column_name(value, index) for index, value in enumerate(raw_columns)]
    duplicate_names = _duplicate_normalized_names(inspected)
    pandas_duplicate_indexes = _pandas_duplicate_suffix_indexes(inspected)
    proposed: list[dict[str, Any]] = []
    for item in inspected:
        generated_reason = _generated_name_reason(item, duplicate_names, pandas_duplicate_indexes)
        if generated_reason:
            tool_name = _generated_column_name(item["index"])
            name_source = generated_reason
            source_name = None if item["is_loader_placeholder"] or item["is_empty"] else item["text"]
        else:
            tool_name = item["text"]
            name_source = "preserved_source_name"
            source_name = item["text"]
        proposed.append(
            {
                **item,
                "tool_name": tool_name,
                "source_name": source_name,
                "name_source": name_source,
            }
        )

    conflicted = _duplicate_tool_names(proposed)
    if conflicted:
        proposed = [
            {
                **item,
                "tool_name": _generated_column_name(item["index"]),
                "name_source": "generated_tool_name_conflict",
            }
            if _normalize_column_name(item["tool_name"]) in conflicted
            else item
            for item in proposed
        ]

    return TabularSchema(
        columns=[
            TabularColumnSchema(
                index=item["index"],
                tool_name=item["tool_name"],
                source_name=item["source_name"],
                loader_name=item["loader_name"],
                name_source=item["name_source"],
            )
            for item in proposed
        ]
    )


def tabular_schema_tool_names(schema: TabularSchema) -> list[str]:
    """Return canonical executable names in their source-column order."""

    return [column.tool_name for column in schema.columns]


def apply_tabular_schema(frame: Any, schema: TabularSchema) -> Any:
    """Apply canonical names by position, preserving duplicate loader columns safely.

    A mapping-based rename is intentionally not used here: loaders may expose
    duplicate labels, in which case a dict can collapse multiple source
    columns before the canonical schema is applied.  The schema's ordered
    columns are the authority for the output labels.  Pandas uses ``set_axis``;
    Polars uses its positional ``columns`` setter on a cloned frame.
    """

    _validate_tabular_schema_shape(frame, schema)
    names = tabular_schema_tool_names(schema)
    if isinstance(frame, pd.DataFrame):
        return frame.set_axis(names, axis="columns")
    if frame.__class__.__module__.startswith("polars"):
        return apply_tabular_schema_to_polars(frame, names)
    raise TypeError("apply_tabular_schema expects a pandas or Polars DataFrame.")


def apply_tabular_schema_to_polars(frame: Any, names_or_schema: list[str] | TabularSchema) -> Any:
    """Apply canonical names to a Polars DataFrame by position.

    Polars' ``columns`` setter is positional and therefore remains safe when
    the loader supplied duplicate labels.  A clone keeps this utility's
    projection semantics aligned with pandas ``set_axis`` (the input is not
    mutated).  The helper intentionally avoids importing Polars at module
    import time.
    """

    if not frame.__class__.__module__.startswith("polars"):
        raise TypeError("apply_tabular_schema_to_polars expects a Polars DataFrame.")
    if isinstance(names_or_schema, TabularSchema):
        _validate_tabular_schema_shape(frame, names_or_schema)
    names = (
        tabular_schema_tool_names(names_or_schema)
        if isinstance(names_or_schema, TabularSchema)
        else list(names_or_schema)
    )
    if len(frame.columns) != len(names):
        raise ValidationError(
            "Tabular schema column count does not match the Polars frame column count."
        )
    clone = frame.clone()
    clone.columns = names
    return clone


def _validate_tabular_schema_shape(frame: Any, schema: TabularSchema) -> None:
    if not hasattr(frame, "columns"):
        raise TypeError("apply_tabular_schema expects a pandas or Polars DataFrame.")
    if len(frame.columns) != len(schema.columns):
        raise ValidationError("Tabular schema column count does not match the frame column count.")
    expected_indexes = list(range(len(schema.columns)))
    actual_indexes = [column.index for column in schema.columns]
    if actual_indexes != expected_indexes:
        raise ValidationError("Tabular schema column indexes must be strict zero-based positions.")


def resolve_tabular_column_index(
    schema: TabularSchema,
    value: Any,
    field_name: str = "column_index",
) -> str:
    """Resolve one strict zero-based index to a canonical ``tool_name``.

    Selection policies (for example duplicate selected indexes or a text/ID
    collision) belong to the caller.  This primitive only validates the
    index's type and range and supplies field-specific error context.
    """

    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError(f"{field_name} must be a zero-based integer column index.")
    if value < 0 or value >= len(schema.columns):
        raise ValidationError(
            f"{field_name} index {value} is outside the available zero-based column range."
        )
    return schema.columns[value].tool_name


def tabular_schema_payload(schema: TabularSchema) -> dict[str, Any]:
    return {
        "resolver_version": schema.resolver_version,
        "columns": [
            {
                "index": column.index,
                "tool_name": column.tool_name,
                "source_name": column.source_name,
                "loader_name": column.loader_name,
                "name_source": column.name_source,
            }
            for column in schema.columns
        ],
    }


def preview_rows(frame: Any, *, limit: int) -> list[list[str]]:
    return [
        [format_value(value) for value in row]
        for row in frame.head(limit).iter_rows()
    ]


def format_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return str(value)


def format_column(value: Any, index: int) -> str:
    text = format_value(value)
    if text:
        return text
    return f"Unnamed: {index}"


def _load_pandas_frame_for_tools(
    path: Path,
    source_format: DatasetSourceFormat,
    *,
    preserve_types: bool = False,
    header_only: bool = False,
    sheet_name: str | int | None = None,
) -> pd.DataFrame:
    if source_format is DatasetSourceFormat.CSV:
        return pd.read_csv(path, nrows=0) if header_only else pd.read_csv(path)
    if source_format is DatasetSourceFormat.PARQUET:
        query = "SELECT * FROM read_parquet(?) LIMIT 0" if header_only else "SELECT * FROM read_parquet(?)"
        return duckdb.connect(database=":memory:").execute(
            query,
            [str(path)],
        ).fetchdf()
    if source_format in {DatasetSourceFormat.XLSX, DatasetSourceFormat.XLS}:
        read_options: dict[str, Any] = {"nrows": 0} if header_only else {}
        if sheet_name is not None:
            read_options["sheet_name"] = sheet_name
        if preserve_types:
            return pd.read_excel(path, **read_options)
        return pd.read_excel(path, dtype=str, keep_default_na=False, **read_options)
    raise ValidationError("Only .csv, .parquet, .xlsx, and .xls dataset files are supported.")


def _inspect_column_name(value: Any, index: int) -> dict[str, Any]:
    is_empty = value is None or (isinstance(value, str) and not value.strip())
    text = "" if value is None else str(value).strip()
    is_loader_placeholder = _is_known_loader_placeholder(text)
    return {
        "index": index,
        "raw": value,
        "text": text,
        "loader_name": None if is_empty else str(value),
        "is_empty": is_empty,
        "is_loader_placeholder": is_loader_placeholder,
        "is_unstable": _is_unstable_column_name(value, text),
    }


def _generated_name_reason(
    item: dict[str, Any],
    duplicate_names: set[str],
    pandas_duplicate_indexes: set[int],
) -> str | None:
    normalized = _normalize_column_name(item["text"])
    if item["is_empty"]:
        return "generated_empty_name"
    if item["is_loader_placeholder"]:
        return "generated_loader_placeholder"
    if item["index"] in pandas_duplicate_indexes:
        return "generated_loader_duplicate"
    if normalized in duplicate_names:
        return "generated_duplicate_name"
    if item["is_unstable"]:
        return "generated_unstable_name"
    return None


def _is_known_loader_placeholder(value: str) -> bool:
    return bool(_PANDAS_UNNAMED_PATTERN.match(value) or _POLARS_UNNAMED_PATTERN.match(value))


def _is_unstable_column_name(raw_value: Any, text: str) -> bool:
    if not isinstance(raw_value, str):
        return True
    if len(text) > _MAX_STABLE_COLUMN_NAME_LENGTH:
        return True
    if "\n" in text or "\r" in text:
        return True
    return any(ord(char) < 32 for char in text)


def _duplicate_normalized_names(items: list[dict[str, Any]]) -> set[str]:
    counts: dict[str, int] = {}
    for item in items:
        normalized = _normalize_column_name(item["text"])
        if normalized:
            counts[normalized] = counts.get(normalized, 0) + 1
    return {name for name, count in counts.items() if count > 1}


def _pandas_duplicate_suffix_indexes(items: list[dict[str, Any]]) -> set[int]:
    normalized_names = {_normalize_column_name(item["text"]) for item in items}
    duplicate_indexes: set[int] = set()
    for item in items:
        match = _PANDAS_DUPLICATE_SUFFIX_PATTERN.match(item["text"])
        polars_match = _POLARS_DUPLICATE_SUFFIX_PATTERN.match(item["text"])
        base = match.group("base") if match else polars_match.group("base") if polars_match else None
        if base is not None and _normalize_column_name(base) in normalized_names:
            duplicate_indexes.add(item["index"])
    return duplicate_indexes


def _duplicate_tool_names(items: list[dict[str, Any]]) -> set[str]:
    counts: dict[str, int] = {}
    for item in items:
        normalized = _normalize_column_name(item["tool_name"])
        counts[normalized] = counts.get(normalized, 0) + 1
    return {name for name, count in counts.items() if count > 1}


def _normalize_column_name(value: str) -> str:
    return value.strip().casefold()


def _generated_column_name(index: int) -> str:
    return f"column_{index + 1}"


def _tabular_runtime_error_details(
    *,
    path: Path,
    source_format: DatasetSourceFormat,
    exc: Exception,
    phase: str,
) -> dict[str, Any]:
    return {
        "engine": "polars",
        "phase": phase,
        "source_path": str(path),
        "source_format": source_format.value,
        "exception_type": type(exc).__name__,
        "exception_message": str(exc),
        "package_versions": tabular_runtime_versions(),
    }
