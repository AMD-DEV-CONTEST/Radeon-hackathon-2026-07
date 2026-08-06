from __future__ import annotations

from datetime import date, datetime
import logging
import math
from pathlib import Path
from time import perf_counter
from typing import Any

try:
    import polars as pl
except Exception:  # pragma: no cover - depends on local runtime state
    pl = None
from pydantic import ConfigDict, Field
from sqlmodel import SQLModel

from ..exceptions import ValidationError
from ..observability import record_counter, record_histogram, start_span
from .dataset_inspection import detect_source_format
from .storage.models import DatasetSourceFormat
from .tabular import TabularRuntimeError, load_tabular_frame


_DEFAULT_TOP_N = 10
_MAX_TOP_N = 20
_DEFAULT_CORRELATION_COLUMN_LIMIT = 8
_MAX_CORRELATION_COLUMN_LIMIT = 12
_MAX_FIELD_ROWS_IN_MARKDOWN = 20
_MAX_FREQUENCY_COLUMNS = 8
_MAX_TARGET_GROUP_ROWS = 30
LOGGER = logging.getLogger("xenix.services.analysis_profile")


class ProfileDatasetInput(SQLModel):
    model_config = ConfigDict(extra="forbid")

    source_path: str
    dataset_name: str
    target_columns: list[str] = Field(default_factory=list)
    top_n: int = _DEFAULT_TOP_N
    correlation_column_limit: int = _DEFAULT_CORRELATION_COLUMN_LIMIT


class ProfileDatasetResult(SQLModel):
    profile: dict[str, Any] = Field(default_factory=dict)
    markdown: str


class AnalysisProfileService:
    def profile_dataset(self, input_data: ProfileDatasetInput) -> ProfileDatasetResult:
        started_at = perf_counter()
        with start_span("analysis.profile"):
            source_path = self._resolve_source_path(input_data.source_path)
            top_n = self._normalize_int(
                input_data.top_n,
                field_name="top_n",
                minimum=1,
                maximum=_MAX_TOP_N,
            )
            correlation_column_limit = self._normalize_int(
                input_data.correlation_column_limit,
                field_name="correlation_column_limit",
                minimum=2,
                maximum=_MAX_CORRELATION_COLUMN_LIMIT,
            )
            frame = self._load_frame(source_path)
            dataset_name = input_data.dataset_name.strip() or source_path.stem

            column_groups = self._column_groups(frame)
            target_columns = self._normalize_target_columns(
                frame,
                input_data.target_columns,
                column_groups["continuous_numeric"],
            )
            profile = {
                "dataset": {
                    "name": dataset_name,
                    "file_name": source_path.name,
                },
                "limits": {
                    "top_n": top_n,
                    "correlation_column_limit": correlation_column_limit,
                },
                "basic_info": self._basic_info(frame),
                "field_info": self._field_info(frame),
                "field_type_summary": self._field_type_summary(column_groups),
                "numeric_statistics": self._numeric_statistics(frame, column_groups["continuous_numeric"]),
                "binary_frequencies": self._frequencies(frame, column_groups["binary"], top_n),
                "category_frequencies": self._frequencies(frame, column_groups["non_numeric"], top_n),
                "datetime_statistics": self._datetime_statistics(frame, column_groups["datetime"]),
                "correlation_matrix": self._correlation_matrix(
                    frame,
                    column_groups["continuous_numeric"],
                    correlation_column_limit,
                ),
                "target_group_statistics": self._target_group_statistics(
                    frame,
                    target_columns,
                    [*column_groups["binary"], *column_groups["non_numeric"]],
                    top_n,
                ),
            }
            self._record_operation("analysis.profile", started_at)
            return ProfileDatasetResult(
                profile=profile,
                markdown=self._profile_markdown(profile),
            )

    def _record_operation(self, operation: str, started_at: float) -> None:
        attributes = {"analysis.operation": operation, "status": "succeeded"}
        record_counter("xenix.analysis.operation.count", attributes=attributes)
        record_histogram(
            "xenix.analysis.operation.duration",
            (perf_counter() - started_at) * 1000,
            attributes=attributes,
            unit="ms",
        )

    def _resolve_source_path(self, raw_path: str) -> Path:
        source_path = Path(raw_path).expanduser()
        if not source_path.is_absolute():
            raise ValidationError("Dataset source path must be absolute.")
        if not source_path.exists() or not source_path.is_file():
            raise ValidationError("Dataset source path must point to an existing file.")
        return source_path.resolve()

    def _load_frame(self, source_path: Path) -> pl.DataFrame:
        source_format = detect_source_format(source_path)
        if source_format is DatasetSourceFormat.UNKNOWN:
            raise ValidationError("Only .csv, .parquet, .xlsx, and .xls dataset files are supported.")
        if pl is None:
            raise self._tabular_runtime_validation_error(
                source_path=source_path,
                source_format=source_format,
                exc=RuntimeError("Polars could not be imported."),
                phase="import",
            )
        try:
            frame = load_tabular_frame(source_path, source_format)
        except TabularRuntimeError as exc:
            LOGGER.exception("Dataset profile could not load the tabular runtime for %s.", source_path)
            raise self._tabular_runtime_validation_error(
                source_path=source_path,
                source_format=source_format,
                exc=exc,
            ) from exc
        frame = frame.rename({column: str(column) for column in frame.columns})
        if frame.width == 0:
            raise ValidationError("Dataset file must contain at least one column.")
        if frame.height == 0:
            raise ValidationError("Dataset file must contain at least one data row.")
        return frame

    def _tabular_runtime_validation_error(
        self,
        *,
        source_path: Path,
        source_format: DatasetSourceFormat,
        exc: Exception,
        phase: str | None = None,
    ) -> ValidationError:
        tabular_error_details = getattr(exc, "error_details", None)
        details = {
            "operation": "analysis.profile",
            "source_path": str(source_path),
            "source_format": source_format.value,
            "exception_type": type(exc).__name__,
            "exception_message": str(exc),
        }
        if isinstance(tabular_error_details, dict) and tabular_error_details:
            details["tabular"] = tabular_error_details
        if phase:
            details["phase"] = phase
        return ValidationError(
            "Dataset analysis profile is unavailable because the Polars runtime could not load this dataset.",
            error_code="tabular_runtime_unavailable",
            error_details=details,
            repair_hints=[
                "Use data.query for a smaller schema or preview query when you only need basic evidence.",
                "Repair the local environment so `polars` and `polars-runtime-*` are the same version, then retry.",
            ],
            retryable=True,
        )

    def _normalize_int(self, value: Any, *, field_name: str, minimum: int, maximum: int) -> int:
        try:
            normalized = int(value)
        except (TypeError, ValueError) as exc:
            raise ValidationError(f"{field_name} must be an integer.") from exc
        if normalized < minimum or normalized > maximum:
            raise ValidationError(f"{field_name} must be between {minimum} and {maximum}.")
        return normalized

    def _column_groups(self, frame: pl.DataFrame) -> dict[str, list[str]]:
        binary_columns = [column for column in frame.columns if self._is_binary_column(frame[column])]
        datetime_columns = [
            column
            for column in frame.columns
            if column not in binary_columns and self._is_datetime_column(frame[column])
        ]
        numeric_columns = [
            column
            for column in frame.columns
            if column not in binary_columns
            and column not in datetime_columns
            and frame[column].dtype.is_numeric()
        ]
        non_numeric_columns = [
            column
            for column in frame.columns
            if column not in binary_columns
            and column not in datetime_columns
            and column not in numeric_columns
        ]
        return {
            "continuous_numeric": [str(column) for column in numeric_columns],
            "binary": [str(column) for column in binary_columns],
            "non_numeric": [str(column) for column in non_numeric_columns],
            "datetime": [str(column) for column in datetime_columns],
        }

    def _is_binary_column(self, series: pl.Series) -> bool:
        if series.dtype == pl.Boolean:
            return True
        values = series.drop_nulls().unique().to_list()
        if len(values) == 0 or len(values) > 2:
            return False
        normalized_values = {self._binary_value(value) for value in values}
        return None not in normalized_values and normalized_values.issubset({0, 1})

    def _binary_value(self, value: Any) -> int | None:
        try:
            if value == 0:
                return 0
            if value == 1:
                return 1
        except ValueError:
            return None
        return None

    def _is_datetime_column(self, series: pl.Series) -> bool:
        if series.dtype.is_temporal():
            return True
        if series.dtype.is_numeric():
            return False
        values = series.drop_nulls()
        if values.is_empty():
            return False
        parsed = self._to_datetime_series(values)
        if parsed.is_empty():
            return False
        valid_count = int(parsed.is_not_null().sum())
        return bool(valid_count / len(parsed) >= 0.8)

    def _normalize_target_columns(
        self,
        frame: pl.DataFrame,
        raw_columns: list[str],
        numeric_columns: list[str],
    ) -> list[str]:
        normalized: list[str] = []
        numeric_set = set(numeric_columns)
        for raw_column in raw_columns:
            column = str(raw_column or "").strip()
            if not column or column in normalized:
                continue
            if column not in frame.columns:
                raise ValidationError(f"target_columns contains unknown column '{column}'.")
            if column not in numeric_set:
                raise ValidationError(f"target column '{column}' must be a continuous numeric column.")
            normalized.append(column)
        return normalized

    def _basic_info(self, frame: pl.DataFrame) -> dict[str, int]:
        return {
            "row_count": int(frame.height),
            "column_count": int(frame.width),
            "duplicate_row_count": int(frame.height - frame.unique().height),
        }

    def _field_info(self, frame: pl.DataFrame) -> list[dict[str, Any]]:
        row_count = max(int(frame.height), 1)
        fields: list[dict[str, Any]] = []
        for column in frame.columns:
            series = frame[column]
            missing_count = self._missing_count(series)
            fields.append(
                {
                    "column": str(column),
                    "dtype": str(series.dtype),
                    "non_null_count": int(row_count - missing_count),
                    "missing_count": missing_count,
                    "missing_ratio": self._number(missing_count / row_count),
                    "unique_count": self._unique_count(series),
                }
            )
        return fields

    def _field_type_summary(self, column_groups: dict[str, list[str]]) -> dict[str, dict[str, Any]]:
        return {
            "continuous_numeric": self._field_type_entry(column_groups["continuous_numeric"]),
            "binary": self._field_type_entry(column_groups["binary"]),
            "non_numeric": self._field_type_entry(column_groups["non_numeric"]),
            "datetime": self._field_type_entry(column_groups["datetime"]),
        }

    def _field_type_entry(self, columns: list[str]) -> dict[str, Any]:
        return {"count": len(columns), "columns": columns}

    def _numeric_statistics(self, frame: pl.DataFrame, numeric_columns: list[str]) -> list[dict[str, Any]]:
        summaries: list[dict[str, Any]] = []
        for column in numeric_columns:
            series = self._numeric_series(frame[column])
            mode = series.mode()
            mean = series.mean() if not series.is_empty() else None
            std = series.std() if not series.is_empty() else None
            summaries.append(
                {
                    "column": column,
                    "count": int(series.len()),
                    "mean": self._number(mean),
                    "std": self._number(std),
                    "min": self._number(series.min() if not series.is_empty() else None),
                    "q1": self._number(series.quantile(0.25) if not series.is_empty() else None),
                    "median": self._number(series.median() if not series.is_empty() else None),
                    "q3": self._number(series.quantile(0.75) if not series.is_empty() else None),
                    "max": self._number(series.max() if not series.is_empty() else None),
                    "mode": self._number(mode[0] if not mode.is_empty() else None),
                    "skew": self._number(series.skew() if len(series) >= 3 else None),
                    "kurtosis": self._number(series.kurtosis() if len(series) >= 4 else None),
                    "coefficient_of_variation": self._coefficient_of_variation(mean, std),
                }
            )
        return summaries

    def _coefficient_of_variation(self, mean: Any, std: Any) -> float | None:
        mean_value = self._number(mean)
        std_value = self._number(std)
        if mean_value in {None, 0} or std_value is None:
            return None
        return self._number(std_value / mean_value)

    def _frequencies(self, frame: pl.DataFrame, columns: list[str], top_n: int) -> list[dict[str, Any]]:
        summaries: list[dict[str, Any]] = []
        row_count = max(int(frame.height), 1)
        for column in columns[:_MAX_FREQUENCY_COLUMNS]:
            counts = frame[column].value_counts(sort=True).head(top_n)
            value_column = counts.columns[0]
            values = [
                {
                    "value": self._display_value(row[value_column]),
                    "count": int(count),
                    "ratio": self._number(int(count) / row_count),
                }
                for row in counts.to_dicts()
                for count in [row["count"]]
            ]
            summaries.append({"column": column, "values": values})
        return summaries

    def _datetime_statistics(self, frame: pl.DataFrame, datetime_columns: list[str]) -> list[dict[str, Any]]:
        summaries: list[dict[str, Any]] = []
        for column in datetime_columns:
            series = self._to_datetime_series(frame[column]).drop_nulls()
            min_value = series.min() if not series.is_empty() else None
            max_value = series.max() if not series.is_empty() else None
            span_days = None
            if min_value is not None and max_value is not None:
                span = max_value - min_value
                span_days = getattr(span, "days", None)
            summaries.append(
                {
                    "column": column,
                    "min": self._display_value(min_value),
                    "max": self._display_value(max_value),
                    "span_days": span_days,
                }
            )
        return summaries

    def _correlation_matrix(
        self,
        frame: pl.DataFrame,
        numeric_columns: list[str],
        column_limit: int,
    ) -> dict[str, Any]:
        selected_columns = numeric_columns[:column_limit]
        if len(selected_columns) < 2:
            return {"columns": selected_columns, "rows": [], "truncated": False}
        matrix = frame.select(selected_columns).corr()
        rows = [
            {
                "column": row_column,
                "values": {
                    column: self._number(matrix[row_index, column_index])
                    for column_index, column in enumerate(selected_columns)
                },
            }
            for row_index, row_column in enumerate(selected_columns)
        ]
        return {
            "columns": selected_columns,
            "rows": rows,
            "truncated": len(numeric_columns) > len(selected_columns),
        }

    def _target_group_statistics(
        self,
        frame: pl.DataFrame,
        target_columns: list[str],
        group_columns: list[str],
        top_n: int,
    ) -> list[dict[str, Any]]:
        summaries: list[dict[str, Any]] = []
        for target_column in target_columns:
            for group_column in group_columns[:_MAX_FREQUENCY_COLUMNS]:
                if self._unique_count(frame[group_column]) > top_n:
                    continue
                grouped = (
                    frame.group_by(group_column, maintain_order=True)
                    .agg(
                        [
                            pl.col(target_column).count().alias("count"),
                            pl.col(target_column).mean().alias("mean"),
                            pl.col(target_column).median().alias("median"),
                            pl.col(target_column).std().alias("std"),
                            pl.col(target_column).min().alias("min"),
                            pl.col(target_column).max().alias("max"),
                        ]
                    )
                    .sort("count", descending=True)
                    .head(top_n)
                )
                for row in grouped.to_dicts():
                    summaries.append(
                        {
                            "target_column": target_column,
                            "group_column": group_column,
                            "group_value": self._display_value(row.get(group_column)),
                            "count": int(row.get("count") or 0),
                            "mean": self._number(row.get("mean")),
                            "median": self._number(row.get("median")),
                            "std": self._number(row.get("std")),
                            "min": self._number(row.get("min")),
                            "max": self._number(row.get("max")),
                        }
                    )
                    if len(summaries) >= _MAX_TARGET_GROUP_ROWS:
                        return summaries
        return summaries

    def _profile_markdown(self, profile: dict[str, Any]) -> str:
        dataset = profile["dataset"]
        basic = profile["basic_info"]
        lines = [
            f"# Dataset profile: {dataset['name']}",
            "",
            "## Basic information",
            "",
            "| Metric | Value |",
            "| --- | --- |",
            f"| Rows | {basic['row_count']} |",
            f"| Columns | {basic['column_count']} |",
            f"| Duplicate rows | {basic['duplicate_row_count']} |",
            "",
            "## Field types",
            "",
            "| Type | Count | Columns |",
            "| --- | ---: | --- |",
        ]
        type_labels = {
            "continuous_numeric": "Continuous numeric",
            "binary": "Binary",
            "non_numeric": "Categorical/text",
            "datetime": "Datetime",
        }
        for key, label in type_labels.items():
            entry = profile["field_type_summary"][key]
            columns = ", ".join(entry["columns"]) if entry["columns"] else "-"
            lines.append(f"| {label} | {entry['count']} | {self._markdown_cell(columns)} |")

        self._append_field_info(lines, profile["field_info"])
        self._append_numeric_statistics(lines, profile["numeric_statistics"])
        self._append_frequency_section(lines, "Binary frequencies", profile["binary_frequencies"])
        self._append_frequency_section(lines, "Categorical/text top values", profile["category_frequencies"])
        self._append_datetime_statistics(lines, profile["datetime_statistics"])
        self._append_correlation_matrix(lines, profile["correlation_matrix"])
        self._append_target_group_statistics(lines, profile["target_group_statistics"])
        return "\n".join(lines)

    def _append_field_info(self, lines: list[str], field_info: list[dict[str, Any]]) -> None:
        lines.extend(
            [
                "",
                "## Missing values and cardinality",
                "",
                "| Column | Type | Missing | Missing ratio | Unique values |",
                "| --- | --- | ---: | ---: | ---: |",
            ]
        )
        sorted_fields = sorted(field_info, key=lambda item: item["missing_count"], reverse=True)
        for field in sorted_fields[:_MAX_FIELD_ROWS_IN_MARKDOWN]:
            lines.append(
                "| "
                + " | ".join(
                    [
                        self._markdown_cell(field["column"]),
                        self._markdown_cell(field["dtype"]),
                        str(field["missing_count"]),
                        self._percent(field["missing_ratio"]),
                        str(field["unique_count"]),
                    ]
                )
                + " |"
            )
        if len(sorted_fields) > _MAX_FIELD_ROWS_IN_MARKDOWN:
            lines.append(f"\nOnly the first {_MAX_FIELD_ROWS_IN_MARKDOWN} fields are shown.")

    def _append_numeric_statistics(self, lines: list[str], rows: list[dict[str, Any]]) -> None:
        lines.extend(["", "## Numeric statistics", ""])
        if not rows:
            lines.append("No continuous numeric columns were detected.")
            return
        lines.extend(
            [
                "| Column | Count | Mean | Std | Min | Q1 | Median | Q3 | Max | Skew |",
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for row in rows[:_MAX_FIELD_ROWS_IN_MARKDOWN]:
            lines.append(
                "| "
                + " | ".join(
                    [
                        self._markdown_cell(row["column"]),
                        str(row["count"]),
                        self._markdown_cell(row["mean"]),
                        self._markdown_cell(row["std"]),
                        self._markdown_cell(row["min"]),
                        self._markdown_cell(row["q1"]),
                        self._markdown_cell(row["median"]),
                        self._markdown_cell(row["q3"]),
                        self._markdown_cell(row["max"]),
                        self._markdown_cell(row["skew"]),
                    ]
                )
                + " |"
            )

    def _append_frequency_section(self, lines: list[str], title: str, summaries: list[dict[str, Any]]) -> None:
        lines.extend(["", f"## {title}", ""])
        if not summaries:
            lines.append("No matching columns were detected.")
            return
        for summary in summaries:
            lines.append(f"### {summary['column']}")
            lines.extend(["", "| Value | Count | Ratio |", "| --- | ---: | ---: |"])
            for value in summary["values"]:
                lines.append(
                    f"| {self._markdown_cell(value['value'])} | {value['count']} | {self._percent(value['ratio'])} |"
                )
            lines.append("")

    def _append_datetime_statistics(self, lines: list[str], rows: list[dict[str, Any]]) -> None:
        lines.extend(["", "## Datetime statistics", ""])
        if not rows:
            lines.append("No datetime columns were detected.")
            return
        lines.extend(["| Column | Earliest | Latest | Span days |", "| --- | --- | --- | ---: |"])
        for row in rows:
            lines.append(
                f"| {self._markdown_cell(row['column'])} | {self._markdown_cell(row['min'])} | "
                f"{self._markdown_cell(row['max'])} | {self._markdown_cell(row['span_days'])} |"
            )

    def _append_correlation_matrix(self, lines: list[str], matrix: dict[str, Any]) -> None:
        lines.extend(["", "## Correlation matrix", ""])
        columns = matrix.get("columns") or []
        rows = matrix.get("rows") or []
        if len(columns) < 2 or not rows:
            lines.append("At least two continuous numeric columns are required.")
            return
        header = "| Column | " + " | ".join(self._markdown_cell(column) for column in columns) + " |"
        separator = "| --- | " + " | ".join("---:" for _column in columns) + " |"
        lines.extend([header, separator])
        for row in rows:
            values = row.get("values") or {}
            lines.append(
                "| "
                + self._markdown_cell(row["column"])
                + " | "
                + " | ".join(self._markdown_cell(values.get(column)) for column in columns)
                + " |"
            )
        if matrix.get("truncated"):
            lines.append("\nThe matrix was truncated to the configured column limit.")

    def _append_target_group_statistics(self, lines: list[str], rows: list[dict[str, Any]]) -> None:
        lines.extend(["", "## Target group statistics", ""])
        if not rows:
            lines.append("No target columns were requested.")
            return
        lines.extend(
            [
                "| Target | Group column | Group value | Count | Mean | Median | Std | Min | Max |",
                "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for row in rows:
            lines.append(
                "| "
                + " | ".join(
                    [
                        self._markdown_cell(row["target_column"]),
                        self._markdown_cell(row["group_column"]),
                        self._markdown_cell(row["group_value"]),
                        str(row["count"]),
                        self._markdown_cell(row["mean"]),
                        self._markdown_cell(row["median"]),
                        self._markdown_cell(row["std"]),
                        self._markdown_cell(row["min"]),
                        self._markdown_cell(row["max"]),
                    ]
                )
                + " |"
            )

    def _missing_count(self, series: pl.Series) -> int:
        missing_count = int(series.null_count())
        if series.dtype.is_float():
            missing_count += int(series.is_nan().sum())
        return missing_count

    def _unique_count(self, series: pl.Series) -> int:
        values = series.drop_nulls()
        if values.dtype.is_float():
            values = values.filter(~values.is_nan())
        return int(values.n_unique())

    def _numeric_series(self, series: pl.Series) -> pl.Series:
        values = series.cast(pl.Float64, strict=False).drop_nulls()
        return values.filter(~values.is_nan())

    def _to_datetime_series(self, series: pl.Series) -> pl.Series:
        if series.dtype == pl.Date:
            return series.cast(pl.Datetime)
        if series.dtype.is_temporal():
            return series
        values = series.cast(pl.String, strict=False)
        for datetime_format in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", None):
            try:
                return values.str.to_datetime(format=datetime_format, strict=False)
            except pl.exceptions.ComputeError:
                continue
        return pl.Series(series.name, [None] * len(series), dtype=pl.Datetime)

    def _number(self, value: Any, *, digits: int = 4) -> float | int | None:
        if value is None:
            return None
        if isinstance(value, float) and math.isnan(value):
            return None
        if hasattr(value, "item"):
            value = value.item()
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        try:
            return round(float(value), digits)
        except (TypeError, ValueError):
            return None

    def _display_value(self, value: Any) -> str:
        if value is None:
            return "<missing>"
        if isinstance(value, float) and math.isnan(value):
            return "<missing>"
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, date):
            return datetime.combine(value, datetime.min.time()).isoformat()
        return str(value)

    def _percent(self, ratio: Any) -> str:
        value = self._number(ratio)
        if value is None:
            return ""
        return f"{round(float(value) * 100, 2)}%"

    def _markdown_cell(self, value: Any) -> str:
        if value is None:
            return ""
        return str(value).replace("\n", " ").replace("|", "\\|")
