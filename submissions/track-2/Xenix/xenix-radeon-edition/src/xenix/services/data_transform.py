from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any, Literal
from uuid import uuid4

import duckdb
import pandas as pd
from pydantic import Field
from sqlmodel import SQLModel

from ..config import AppPaths
from ..exceptions import ValidationError
from ..observability import record_counter, record_histogram, start_span
from .dataset_inspection import detect_source_format
from .preprocessing_worker import LocalPreprocessingWorkerRunner, PreprocessingWorkerRunner
from .storage.models import DatasetSourceFormat
from .tabular import (
    LoadedPandasFrame,
    TabularSchema,
    apply_tabular_schema,
    load_pandas_frame_with_schema,
    load_tabular_schema,
    load_tabular_frame,
    resolve_tabular_schema_for_loaded_frame,
    tabular_schema_tool_names,
)


_MAX_SQL_LENGTH = 20_000
_MAX_QUERY_LIMIT = 200
_DEFAULT_QUERY_LIMIT = 50
_ALIAS_RESERVED_WORDS = {
    "all",
    "and",
    "as",
    "by",
    "case",
    "delete",
    "from",
    "group",
    "insert",
    "join",
    "limit",
    "on",
    "or",
    "order",
    "select",
    "set",
    "update",
    "where",
    "with",
}
_DISALLOWED_KEYWORDS = {
    "alter",
    "attach",
    "call",
    "checkpoint",
    "copy",
    "create",
    "delete",
    "detach",
    "drop",
    "export",
    "force",
    "import",
    "insert",
    "install",
    "load",
    "merge",
    "pragma",
    "reset",
    "set",
    "truncate",
    "update",
    "vacuum",
}
_TRANSFORM_DISALLOWED_KEYWORDS = {
    "alter",
    "attach",
    "call",
    "checkpoint",
    "copy",
    "detach",
    "drop",
    "export",
    "force",
    "import",
    "install",
    "load",
    "merge",
    "pragma",
    "reset",
    "set",
    "truncate",
    "vacuum",
}
_DISALLOWED_FUNCTIONS = {
    "arrow_scan",
    "delta_scan",
    "excel_scan",
    "glob",
    "iceberg_scan",
    "json_scan",
    "mysql_scan",
    "parquet_scan",
    "postgres_scan",
    "read_blob",
    "read_csv",
    "read_csv_auto",
    "read_json",
    "read_json_auto",
    "read_ndjson",
    "read_parquet",
    "read_text",
    "read_xlsx",
    "sqlite_scan",
}

ColumnReferenceMode = Literal["names", "indexes"]


class DatasetSqlBinding(SQLModel):
    alias: str
    dataset_id: str
    source_path: str


class DataQueryInput(SQLModel):
    bindings: list[DatasetSqlBinding]
    sql: str
    limit: int = _DEFAULT_QUERY_LIMIT
    column_reference: ColumnReferenceMode = "names"


class DataTransformInput(SQLModel):
    bindings: list[DatasetSqlBinding]
    sql: str
    name: str
    column_reference: ColumnReferenceMode = "names"


class DataQueryResult(SQLModel):
    rows: list[dict[str, Any]] = Field(default_factory=list)
    columns: list[dict[str, str]] = Field(default_factory=list)
    returned_row_count: int = 0
    total_row_count: int = 0
    limit: int = _DEFAULT_QUERY_LIMIT
    truncated: bool = False
    validation_summary: dict[str, Any] = Field(default_factory=dict)


class DataTransformResult(SQLModel):
    output_path: str
    row_count: int = 0
    columns: list[dict[str, str]] = Field(default_factory=list)
    validation_summary: dict[str, Any] = Field(default_factory=dict)
    transform_report: dict[str, Any] = Field(default_factory=dict)


@dataclass(frozen=True)
class _SqlToken:
    kind: str
    value: str

    @property
    def lower(self) -> str:
        return self.value.lower()


class DuckDbSqlValidator:
    def validate(self, sql: str, bindings: list[DatasetSqlBinding]) -> dict[str, Any]:
        normalized_sql = sql.strip()
        if not normalized_sql:
            raise ValidationError("SQL cannot be empty.")
        if len(normalized_sql) > _MAX_SQL_LENGTH:
            raise ValidationError(f"SQL cannot exceed {_MAX_SQL_LENGTH} characters.")
        aliases = self._validate_aliases(bindings)
        tokens = self._tokens(normalized_sql)
        significant = [token for token in tokens if token.kind in {"word", "identifier", "string", "symbol"}]
        word_tokens = [token for token in significant if token.kind == "word"]
        if not word_tokens:
            raise ValidationError("SQL must contain a SELECT or WITH statement.")
        first_word = word_tokens[0].lower
        if first_word in _DISALLOWED_KEYWORDS:
            raise ValidationError(f"SQL contains unsupported statement keyword: {first_word}.")
        if first_word not in {"select", "with"}:
            raise ValidationError("SQL must start with SELECT or WITH.")

        semicolon_indexes = [index for index, token in enumerate(significant) if token.value == ";"]
        if semicolon_indexes:
            if len(semicolon_indexes) > 1 or semicolon_indexes[0] != len(significant) - 1:
                raise ValidationError("SQL must be a single statement.")

        disallowed = sorted({token.lower for token in word_tokens if token.lower in _DISALLOWED_KEYWORDS})
        if disallowed:
            raise ValidationError(f"SQL contains unsupported statement keyword: {disallowed[0]}.")

        for index, token in enumerate(significant):
            if token.kind == "word" and token.lower in _DISALLOWED_FUNCTIONS:
                next_token = significant[index + 1] if index + 1 < len(significant) else None
                if next_token is None or next_token.value == "(":
                    raise ValidationError(f"SQL cannot call DuckDB file scan function '{token.value}'.")
            if token.kind == "string" and self._previous_word(significant, index) in {"from", "join"}:
                raise ValidationError("SQL cannot read direct file paths; use registered dataset bindings.")

        referenced_aliases = sorted(
            {
                token.lower
                for token in word_tokens
                if token.lower in {alias.lower() for alias in aliases}
            }
        )
        if not referenced_aliases:
            raise ValidationError("SQL must reference at least one registered dataset binding.")

        return {
            "statement": first_word,
            "read_only": True,
            "single_statement": True,
            "bindings": aliases,
            "referenced_bindings": referenced_aliases,
        }

    def validate_transform(self, sql: str, bindings: list[DatasetSqlBinding]) -> dict[str, Any]:
        normalized_sql = sql.strip()
        if not normalized_sql:
            raise ValidationError("SQL cannot be empty.")
        if len(normalized_sql) > _MAX_SQL_LENGTH:
            raise ValidationError(f"SQL cannot exceed {_MAX_SQL_LENGTH} characters.")
        aliases = self._validate_aliases(bindings)
        tokens = self._tokens(normalized_sql)
        significant = [token for token in tokens if token.kind in {"word", "identifier", "string", "symbol"}]
        word_tokens = [token for token in significant if token.kind == "word"]
        if not word_tokens:
            raise ValidationError("SQL must contain a transformation statement.")
        first_word = word_tokens[0].lower
        if first_word not in {"select", "with", "create", "insert", "update", "delete"}:
            raise ValidationError("SQL must start with SELECT, WITH, CREATE TEMP, INSERT, UPDATE, or DELETE.")
        disallowed = sorted({token.lower for token in word_tokens if token.lower in _TRANSFORM_DISALLOWED_KEYWORDS})
        if disallowed:
            raise ValidationError(f"SQL contains unsupported statement keyword: {disallowed[0]}.")
        self._validate_no_file_authority(significant)
        self._validate_temporary_creates(significant)
        referenced_aliases = sorted(
            {
                token.lower
                for token in word_tokens
                if token.lower in {alias.lower() for alias in aliases}
            }
        )
        if not referenced_aliases:
            raise ValidationError("SQL must reference at least one registered dataset binding.")
        return {
            "statement": first_word,
            "read_only": False,
            "single_statement": False,
            "requires_output_relation": "output",
            "bindings": aliases,
            "referenced_bindings": referenced_aliases,
        }

    def normalize_sql(self, sql: str) -> str:
        normalized = sql.strip()
        while normalized.endswith(";"):
            normalized = normalized[:-1].rstrip()
        return normalized

    def normalize_alias(self, alias: str) -> str:
        return self._normalize_alias(alias)

    def _validate_aliases(self, bindings: list[DatasetSqlBinding]) -> list[str]:
        if not bindings:
            raise ValidationError("At least one dataset binding is required.")
        aliases: list[str] = []
        seen: set[str] = set()
        for binding in bindings:
            alias = self._normalize_alias(binding.alias)
            lowered = alias.lower()
            if lowered in seen:
                raise ValidationError(f"Dataset binding alias '{alias}' is duplicated.")
            seen.add(lowered)
            aliases.append(alias)
        return aliases

    def _normalize_alias(self, alias: str) -> str:
        normalized = str(alias or "").strip()
        if not normalized:
            raise ValidationError("Dataset binding alias cannot be empty.")
        if normalized.lower() in _ALIAS_RESERVED_WORDS:
            raise ValidationError(f"Dataset binding alias '{normalized}' is reserved.")
        first = normalized[0]
        if not (first.isalpha() or first == "_"):
            raise ValidationError("Dataset binding alias must start with a letter or underscore.")
        if not all(char.isalnum() or char == "_" for char in normalized):
            raise ValidationError("Dataset binding alias must contain only letters, numbers, and underscores.")
        return normalized

    def _previous_word(self, tokens: list[_SqlToken], index: int) -> str | None:
        for token in reversed(tokens[:index]):
            if token.kind == "word":
                return token.lower
        return None

    def _validate_no_file_authority(self, tokens: list[_SqlToken]) -> None:
        for index, token in enumerate(tokens):
            if token.kind == "word" and token.lower in _DISALLOWED_FUNCTIONS:
                next_token = tokens[index + 1] if index + 1 < len(tokens) else None
                if next_token is None or next_token.value == "(":
                    raise ValidationError(f"SQL cannot call DuckDB file scan function '{token.value}'.")
            if token.kind == "string" and self._previous_word(tokens, index) in {"from", "join"}:
                raise ValidationError("SQL cannot read direct file paths; use registered dataset bindings.")

    def _validate_temporary_creates(self, tokens: list[_SqlToken]) -> None:
        for index, token in enumerate(tokens):
            if token.kind != "word" or token.lower != "create":
                continue
            next_words: list[str] = []
            for candidate in tokens[index + 1 :]:
                if candidate.value == ";":
                    break
                if candidate.kind == "word":
                    next_words.append(candidate.lower)
                if len(next_words) >= 4:
                    break
            if "table" not in next_words and "view" not in next_words:
                raise ValidationError("SQL CREATE statements must create TEMP TABLE or TEMP VIEW.")
            if "temp" not in next_words and "temporary" not in next_words:
                raise ValidationError("SQL CREATE statements must create TEMP TABLE or TEMP VIEW.")

    def _tokens(self, sql: str) -> list[_SqlToken]:
        tokens: list[_SqlToken] = []
        index = 0
        while index < len(sql):
            char = sql[index]
            next_char = sql[index + 1] if index + 1 < len(sql) else ""
            if char.isspace():
                index += 1
                continue
            if char == "-" and next_char == "-":
                index = self._consume_line_comment(sql, index + 2)
                continue
            if char == "/" and next_char == "*":
                index = self._consume_block_comment(sql, index + 2)
                continue
            if char == "'":
                value, index = self._consume_quoted(sql, index, "'")
                tokens.append(_SqlToken("string", value))
                continue
            if char in {'"', "`"}:
                value, index = self._consume_quoted(sql, index, char)
                tokens.append(_SqlToken("identifier", value))
                continue
            if char.isalpha() or char == "_":
                start = index
                index += 1
                while index < len(sql) and (sql[index].isalnum() or sql[index] == "_"):
                    index += 1
                tokens.append(_SqlToken("word", sql[start:index]))
                continue
            if char in "();,.":
                tokens.append(_SqlToken("symbol", char))
            index += 1
        return tokens

    def _consume_line_comment(self, sql: str, index: int) -> int:
        while index < len(sql) and sql[index] not in {"\n", "\r"}:
            index += 1
        return index

    def _consume_block_comment(self, sql: str, index: int) -> int:
        while index + 1 < len(sql):
            if sql[index] == "*" and sql[index + 1] == "/":
                return index + 2
            index += 1
        raise ValidationError("SQL block comment is not closed.")

    def _consume_quoted(self, sql: str, index: int, quote: str) -> tuple[str, int]:
        start = index
        index += 1
        while index < len(sql):
            if sql[index] == quote:
                if index + 1 < len(sql) and sql[index + 1] == quote:
                    index += 2
                    continue
                return sql[start : index + 1], index + 1
            index += 1
        raise ValidationError("SQL quoted value is not closed.")


class DataQueryTransformService:
    def __init__(
        self,
        paths: AppPaths,
        *,
        worker_runner: PreprocessingWorkerRunner | None = None,
    ) -> None:
        self._paths = paths
        self._validator = DuckDbSqlValidator()
        self._worker_runner = worker_runner or LocalPreprocessingWorkerRunner()

    def query(self, input_data: DataQueryInput) -> DataQueryResult:
        started_at = perf_counter()
        with start_span("data.query"):
            bindings = self._validate_bindings(input_data.bindings)
            validation_summary = self._validator.validate(input_data.sql, bindings)
            limit = self._normalize_limit(input_data.limit)
            sql = self._validator.normalize_sql(input_data.sql)
            with tempfile.TemporaryDirectory() as temp_dir:
                with duckdb.connect(database=":memory:") as connection:
                    self._register_bindings(
                        connection,
                        bindings,
                        temp_dir=Path(temp_dir),
                        column_reference=input_data.column_reference,
                    )
                    total_row_count = int(
                        connection.execute(
                            f"SELECT COUNT(*) AS total_rows FROM ({sql}) AS xenix_query_result_count"
                        ).fetchone()[0]
                    )
                    frame = connection.execute(
                        f"SELECT * FROM ({sql}) AS xenix_query_result LIMIT {limit}"
                    ).fetchdf()
            rows = self._records(frame)
            result = DataQueryResult(
                rows=rows,
                columns=self._columns(frame),
                returned_row_count=int(len(rows)),
                total_row_count=total_row_count,
                limit=limit,
                truncated=total_row_count > int(len(rows)),
                validation_summary=validation_summary,
            )
            self._record_operation("data.query", "succeeded", started_at)
            return result

    def transform(self, input_data: DataTransformInput) -> DataTransformResult:
        payload = self._worker_runner.run(
            "data.transform",
            {"input": input_data.model_dump(mode="json")},
            paths=self._paths,
        )
        return DataTransformResult.model_validate(payload)

    def _transform_in_process(self, input_data: DataTransformInput) -> DataTransformResult:
        started_at = perf_counter()
        with start_span("data.transform"):
            bindings = self._validate_bindings(input_data.bindings)
            validation_summary = self._validator.validate_transform(input_data.sql, bindings)
            name = input_data.name.strip()
            if not name:
                raise ValidationError("Transform output name cannot be empty.")
            sql = self._validator.normalize_sql(input_data.sql)
            output_dir = self._paths.temp / "datasets" / "transformed"
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = output_dir / f"{self._slug(name)}-{uuid4().hex[:12]}.parquet"
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_output_path = Path(temp_dir) / "transform-output.parquet"
                with duckdb.connect(database=":memory:") as connection:
                    self._register_bindings(
                        connection,
                        bindings,
                        temp_dir=Path(temp_dir),
                        column_reference=input_data.column_reference,
                    )
                    if validation_summary["statement"] in {"select", "with"}:
                        connection.execute(f"CREATE TEMP TABLE output AS {sql}")
                    else:
                        connection.execute(sql)
                    try:
                        columns = self._output_columns(connection)
                        row_count = self._output_row_count(connection)
                        connection.execute(
                            "COPY (SELECT * FROM output) TO ? (FORMAT PARQUET)",
                            [str(temp_output_path)],
                        )
                    except duckdb.CatalogException as exc:
                        raise ValidationError(
                            "Transform SQL scripts must leave a final relation named output."
                        ) from exc
                self._validate_transform_output(temp_output_path)
                temp_output_path.replace(output_path)
            transform_report = {
                "row_count": row_count,
                "columns": columns,
                "sql": sql,
                "bindings": [
                    {"alias": binding.alias, "dataset_id": binding.dataset_id}
                    for binding in bindings
                ],
                "validation_summary": validation_summary,
            }
            result = DataTransformResult(
                output_path=str(output_path.resolve()),
                row_count=row_count,
                columns=columns,
                validation_summary=validation_summary,
                transform_report=transform_report,
            )
            self._record_operation("data.transform", "succeeded", started_at)
            return result

    def _output_columns(self, connection) -> list[dict[str, str]]:
        frame = connection.execute("SELECT * FROM output LIMIT 1").fetchdf()
        return self._columns(frame)

    def _output_row_count(self, connection) -> int:
        return int(connection.execute("SELECT COUNT(*) FROM output").fetchone()[0])

    def _validate_transform_output(self, output_path: Path) -> None:
        frame = load_tabular_frame(output_path, DatasetSourceFormat.PARQUET)
        if frame.width == 0:
            raise ValidationError("Transform output must contain at least one column.")

    def _record_operation(self, operation: str, status: str, started_at: float) -> None:
        attributes = {"data.operation": operation, "status": status}
        record_counter("xenix.data.operation.count", attributes=attributes)
        record_histogram(
            "xenix.data.operation.duration",
            (perf_counter() - started_at) * 1000,
            attributes=attributes,
            unit="ms",
        )

    def _register_bindings(
        self,
        connection,
        bindings: list[DatasetSqlBinding],
        *,
        temp_dir: Path,
        column_reference: ColumnReferenceMode,
    ) -> None:
        if column_reference == "names":
            for binding in bindings:
                self._register_binding(connection, binding, relation_name=binding.alias, temp_dir=temp_dir)
            return

        relation_aliases = {binding.alias.lower() for binding in bindings}
        for binding in bindings:
            source_relation = self._temporary_source_relation_name(relation_aliases)
            relation_aliases.add(source_relation.lower())
            schema = self._register_binding(
                connection,
                binding,
                relation_name=source_relation,
                temp_dir=temp_dir,
            )
            self._create_indexed_binding_view(connection, binding.alias, source_relation, schema)

    def _register_binding(
        self,
        connection,
        binding: DatasetSqlBinding,
        *,
        relation_name: str,
        temp_dir: Path,
    ) -> TabularSchema:
        path = Path(binding.source_path).expanduser()
        source_format = detect_source_format(path)
        if source_format is DatasetSourceFormat.PARQUET:
            return self._register_parquet_binding(connection, relation_name, path)
        if source_format in {DatasetSourceFormat.XLSX, DatasetSourceFormat.XLS}:
            return self._register_excel_binding(
                connection,
                relation_name,
                path,
                source_format,
                temp_dir=temp_dir,
            )
        loaded = self._load_frame_with_schema(path)
        connection.register(relation_name, loaded.frame)
        return loaded.schema

    def _register_parquet_binding(
        self,
        connection,
        relation_name: str,
        path: Path,
    ) -> TabularSchema:
        source_query = f"read_parquet({self._sql_string(str(path))})"
        schema = load_tabular_schema(path, DatasetSourceFormat.PARQUET)
        if not schema.columns:
            raise ValidationError(f"Dataset binding alias '{relation_name}' has no visible columns.")
        source_identifier = self._sql_identifier(relation_name)
        projection = ", ".join(
            f"source.{self._sql_identifier(column.loader_name or column.source_name or column.tool_name)} "
            f"AS {self._sql_identifier(column.tool_name)}"
            for column in schema.columns
        )
        connection.execute(
            f"CREATE TEMP VIEW {source_identifier} AS "
            f"SELECT {projection} FROM {source_query} AS source",
        )
        return schema

    def _register_excel_binding(
        self,
        connection,
        relation_name: str,
        path: Path,
        source_format: DatasetSourceFormat,
        *,
        temp_dir: Path,
    ) -> TabularSchema:
        frame = load_tabular_frame(path, source_format)
        schema = resolve_tabular_schema_for_loaded_frame(path, source_format, frame)
        frame = apply_tabular_schema(frame, schema)
        csv_path = temp_dir / f"{relation_name}.csv"
        frame.write_csv(csv_path)
        connection.execute(
            f"CREATE TEMP TABLE {self._sql_identifier(relation_name)} AS "
            f"SELECT * FROM read_csv({self._sql_string(str(csv_path))}, header=true, all_varchar=true)",
        )
        return schema

    def _create_indexed_binding_view(
        self,
        connection,
        alias: str,
        source_relation: str,
        schema: TabularSchema,
    ) -> None:
        source_identifier = self._sql_identifier(source_relation)
        source_columns = tabular_schema_tool_names(schema)
        if not source_columns:
            raise ValidationError(f"Dataset binding alias '{alias}' has no visible columns.")
        projection = ", ".join(
            f"{source_identifier}.{self._sql_identifier(column)} AS c{index}"
            for index, column in enumerate(source_columns)
        )
        connection.execute(
            f"CREATE TEMP VIEW {self._sql_identifier(alias)} AS "
            f"SELECT {projection} FROM {source_identifier}"
        )

    def _temporary_source_relation_name(self, occupied_aliases: set[str]) -> str:
        while True:
            candidate = f"__xenix_sql_source_{uuid4().hex}"
            if candidate.lower() not in occupied_aliases:
                return candidate

    def _validate_bindings(self, bindings: list[DatasetSqlBinding]) -> list[DatasetSqlBinding]:
        normalized: list[DatasetSqlBinding] = []
        seen_aliases: set[str] = set()
        for binding in bindings:
            source_path = Path(binding.source_path).expanduser()
            if not source_path.is_absolute():
                raise ValidationError("Dataset source path must be absolute.")
            if not source_path.exists() or not source_path.is_file():
                raise ValidationError("Dataset source path must point to an existing file.")
            alias = self._validator.normalize_alias(binding.alias)
            lowered = alias.lower()
            if lowered in seen_aliases:
                raise ValidationError(f"Dataset binding alias '{alias}' is duplicated.")
            seen_aliases.add(lowered)
            normalized.append(
                DatasetSqlBinding(
                    alias=alias,
                    dataset_id=binding.dataset_id,
                    source_path=str(source_path.resolve()),
                )
            )
        if not normalized:
            raise ValidationError("At least one dataset binding is required.")
        return normalized

    def _load_frame(self, path: Path) -> pd.DataFrame:
        return self._load_frame_with_schema(path).frame

    def _load_frame_with_schema(self, path: Path) -> LoadedPandasFrame:
        source_format = detect_source_format(path)
        if source_format is DatasetSourceFormat.UNKNOWN:
            raise ValidationError("Only .csv, .parquet, .xlsx, and .xls dataset files are supported.")
        return load_pandas_frame_with_schema(path, source_format)

    def _normalize_limit(self, limit: int) -> int:
        try:
            normalized = int(limit)
        except (TypeError, ValueError) as exc:
            raise ValidationError("Query limit must be an integer.") from exc
        if normalized < 1 or normalized > _MAX_QUERY_LIMIT:
            raise ValidationError(f"Query limit must be between 1 and {_MAX_QUERY_LIMIT}.")
        return normalized

    def _columns(self, frame: pd.DataFrame) -> list[dict[str, str]]:
        return [{"name": str(column), "type": str(dtype)} for column, dtype in frame.dtypes.items()]

    def _records(self, frame: pd.DataFrame) -> list[dict[str, Any]]:
        cleaned = frame.astype(object).where(pd.notna(frame), None)
        return json.loads(cleaned.to_json(orient="records", date_format="iso"))

    def _slug(self, value: str) -> str:
        normalized = "".join(char.lower() if char.isalnum() else "-" for char in value).strip("-")
        return normalized or "dataset"

    def _sql_string(self, value: str) -> str:
        return "'" + value.replace("'", "''") + "'"

    def _sql_identifier(self, value: str) -> str:
        return '"' + value.replace('"', '""') + '"'
