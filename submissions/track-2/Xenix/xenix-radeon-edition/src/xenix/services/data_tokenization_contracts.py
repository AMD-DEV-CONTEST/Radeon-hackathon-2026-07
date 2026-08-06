from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


ColumnIndex = Annotated[int, Field(strict=True, ge=0)]


class TokenizeDatasetInput(BaseModel):
    """Validated command passed from the Agent boundary into tokenization."""

    model_config = ConfigDict(extra="forbid", strict=True)

    source_path: str
    name: str
    text_column: str | None = None
    text_column_index: ColumnIndex | None = None
    output: Literal["token_text", "token_rows"] = "token_text"
    tokenizer_profile: Literal["zh_business_v1"] = "zh_business_v1"
    id_columns: list[str] | None = None
    id_column_indexes: list[ColumnIndex] | None = None


class TokenizeDatasetResult(BaseModel):
    output_path: str
    report: dict[str, object] = Field(default_factory=dict)
