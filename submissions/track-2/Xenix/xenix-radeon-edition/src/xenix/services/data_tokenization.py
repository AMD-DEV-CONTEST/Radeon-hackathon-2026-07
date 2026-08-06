from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from time import perf_counter
from uuid import uuid4

import jieba
import pandas as pd

from ..config import AppPaths
from ..exceptions import ValidationError
from ..observability import record_counter, record_histogram, start_span
from .data_tokenization_contracts import TokenizeDatasetInput, TokenizeDatasetResult
from .dataset_inspection import detect_source_format
from .storage.models import DatasetSourceFormat
from .tabular import (
    TabularSchema,
    load_pandas_frame_with_schema,
    resolve_tabular_column_index,
)

_TOKENIZER_PROFILE = "zh_business_v1"
_TOKEN_KEEP_RE = re.compile(r"[\u4e00-\u9fffA-Za-z0-9]+")
_ZH_BUSINESS_STOPWORDS = {
    "的",
    "了",
    "是",
    "也",
    "很",
    "比较",
    "有点",
    "没有",
    "这家",
    "这次",
    "整体",
    "感觉",
    "一个",
    "一下",
    "还是",
    "但是",
    "不过",
    "非常",
    "不太",
    "中规中矩",
    "特别",
    "正常",
    "适合",
    "明显",
    "问题",
}


class DataTokenizationService:
    def __init__(self, paths: AppPaths) -> None:
        self._paths = paths

    def tokenize_dataset(self, input_data: TokenizeDatasetInput) -> TokenizeDatasetResult:
        started_at = perf_counter()
        with start_span("data.tokenize"):
            source_path = Path(input_data.source_path).expanduser()
            if not source_path.is_absolute():
                raise ValidationError("Dataset source path must be absolute.")
            if not source_path.exists() or not source_path.is_file():
                raise ValidationError("Dataset source path must point to an existing file.")

            source_format = detect_source_format(source_path)
            if source_format is DatasetSourceFormat.UNKNOWN:
                raise ValidationError("Only .csv, .parquet, .xlsx, and .xls dataset files are supported.")

            output_mode = input_data.output
            tokenizer_profile = input_data.tokenizer_profile
            loaded = load_pandas_frame_with_schema(source_path, source_format)
            frame = loaded.frame
            if len(frame.columns) == 0:
                raise ValidationError("Dataset file must contain at least one column.")
            schema = loaded.schema

            text_column = self._text_column(
                frame,
                schema,
                input_data.text_column,
                input_data.text_column_index,
            )
            id_columns = self._id_columns(
                frame,
                schema,
                input_data.id_columns,
                input_data.id_column_indexes,
                text_column=text_column,
            )
            tokenized_rows = [self._tokenize_value(value) for value in frame[text_column].tolist()]

            if output_mode == "token_text":
                output_frame = self._token_text_frame(frame, tokenized_rows)
            else:
                output_frame = self._token_rows_frame(frame, tokenized_rows, id_columns=id_columns)

            output_dir = self._paths.artifacts / "datasets" / "tokenized"
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = output_dir / f"{self._slug(input_data.name)}-{uuid4().hex[:12]}.csv"
            output_frame.to_csv(output_path, index=False)

            non_empty_rows = sum(1 for tokens in tokenized_rows if tokens)
            total_tokens = sum(len(tokens) for tokens in tokenized_rows)
            report = {
                "text_column": text_column,
                "id_columns": id_columns,
                "output": output_mode,
                "tokenizer_profile": tokenizer_profile,
                "source_row_count": int(len(frame.index)),
                "output_row_count": int(len(output_frame.index)),
                "tokenized_row_count": int(non_empty_rows),
                "empty_token_row_count": int(len(frame.index) - non_empty_rows),
                "token_count": int(total_tokens),
            }
            self._record_operation(started_at)
            return TokenizeDatasetResult(output_path=str(output_path.resolve()), report=report)

    def _record_operation(self, started_at: float) -> None:
        attributes = {"data.operation": "data.tokenize", "status": "succeeded"}
        record_counter("xenix.data.operation.count", attributes=attributes)
        record_histogram(
            "xenix.data.operation.duration",
            (perf_counter() - started_at) * 1000,
            attributes=attributes,
            unit="ms",
        )

    def _text_column(
        self,
        frame: pd.DataFrame,
        schema: TabularSchema,
        raw_column: str | None,
        raw_index: int | None,
    ) -> str:
        if raw_column is not None and raw_index is not None:
            raise ValidationError("data.tokenize must use either text_column or text_column_index, not both.")
        if raw_index is not None:
            return self._column_at_index(schema, raw_index, "text_column_index")
        if raw_column is None:
            raise ValidationError("data.tokenize requires text_column or text_column_index.")
        return self._required_column(frame, raw_column, field_name="text_column")

    def _required_column(self, frame: pd.DataFrame, raw_column: str, *, field_name: str) -> str:
        column = str(raw_column or "").strip()
        if not column:
            raise ValidationError(f"data.tokenize {field_name} cannot be empty.")
        if column not in frame.columns:
            raise ValidationError(f"data.tokenize {field_name} '{column}' was not found in the dataset.")
        return column

    def _id_columns(
        self,
        frame: pd.DataFrame,
        schema: TabularSchema,
        raw_columns: list[str] | None,
        raw_indexes: list[int] | None,
        *,
        text_column: str,
    ) -> list[str]:
        if raw_columns is not None and raw_indexes is not None:
            raise ValidationError("data.tokenize must use either id_columns or id_column_indexes, not both.")
        if raw_indexes is not None:
            normalized = [
                self._column_at_index(schema, value, "id_column_indexes")
                for value in raw_indexes
            ]
        else:
            normalized = []
            for raw_column in raw_columns or []:
                normalized.append(self._required_column(frame, raw_column, field_name="id_columns"))

        seen: set[str] = set()
        for column in normalized:
            if column == text_column:
                raise ValidationError("data.tokenize id_columns cannot include text_column.")
            if column in seen:
                raise ValidationError("data.tokenize id_columns cannot contain duplicates.")
            seen.add(column)
        return normalized

    def _column_at_index(self, schema: TabularSchema, value: int, field_name: str) -> str:
        return resolve_tabular_column_index(
            schema,
            value,
            field_name=f"data.tokenize {field_name}",
        )

    def _tokenize_value(self, value: object) -> list[str]:
        if value is None or pd.isna(value):
            return []
        text = unicodedata.normalize("NFKC", str(value))
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            return []
        tokens: list[str] = []
        for raw_token in jieba.lcut(text):
            token = "".join(_TOKEN_KEEP_RE.findall(str(raw_token or ""))).strip()
            if not token:
                continue
            if token.isascii():
                token = token.lower()
            if len(token) < 2:
                continue
            if token in _ZH_BUSINESS_STOPWORDS:
                continue
            tokens.append(token)
        return tokens

    def _token_text_frame(self, frame: pd.DataFrame, tokenized_rows: list[list[str]]) -> pd.DataFrame:
        output_frame = frame.copy()
        output_frame["token_text"] = [" ".join(tokens) for tokens in tokenized_rows]
        output_frame["token_count"] = [len(tokens) for tokens in tokenized_rows]
        return output_frame

    def _token_rows_frame(
        self,
        frame: pd.DataFrame,
        tokenized_rows: list[list[str]],
        *,
        id_columns: list[str],
    ) -> pd.DataFrame:
        rows: list[dict[str, object]] = []
        for row_number, tokens in enumerate(tokenized_rows, start=1):
            if not tokens:
                continue
            base_payload = {"source_row_number": row_number}
            for column in id_columns:
                base_payload[column] = frame.iloc[row_number - 1][column]
            for token_index, token in enumerate(tokens, start=1):
                rows.append(
                    {
                        **base_payload,
                        "token_index": token_index,
                        "token": token,
                    }
                )
        return pd.DataFrame(rows, columns=["source_row_number", *id_columns, "token_index", "token"])

    def _slug(self, value: str) -> str:
        normalized = "".join(char.lower() if char.isalnum() else "-" for char in value).strip("-")
        return normalized or "tokenized-dataset"
