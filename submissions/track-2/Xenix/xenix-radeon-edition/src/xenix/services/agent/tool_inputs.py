"""Strict typed inputs for production Agent Tools.

These models are the authority for call validation.  Provider JSON Schema is a
portable projection produced by the LLM tooling boundary, never a separately
maintained contract.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from ..knowledge_service import MAX_KNOWLEDGE_QUERY_CHARS


RequiredString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
OptionalString = Annotated[str, StringConstraints(strip_whitespace=True)]
NonNegativeInteger = Annotated[int, Field(ge=0)]


class AgentToolInput(BaseModel):
    """Closed, immutable, strict base for provider-authored Tool arguments."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class DataIntegrateInput(AgentToolInput):
    dataset_ids: Annotated[list[RequiredString], Field(min_length=2)]
    name: OptionalString | None = None


class VegaLiteSpec(BaseModel):
    """Bounded top-level Vega-Lite shape with open nested grammar."""

    model_config = ConfigDict(
        extra="allow",
        frozen=True,
        strict=True,
        populate_by_name=True,
    )

    schema_url: str | None = Field(
        default=None,
        alias="$schema",
        description="Optional Vega-Lite schema URL.",
    )
    width: float | None = Field(default=None, description="Chart width in pixels.")
    height: float | None = Field(default=None, description="Chart height in pixels.")
    title: Any = Field(
        default=None,
        description="Optional chart title string or Vega-Lite title object.",
    )
    mark: Any = Field(
        default=None,
        description="Vega-Lite mark string or mark definition object.",
    )
    encoding: dict[str, Any] | None = Field(
        default=None,
        description="Vega-Lite channel encodings such as x, y, color, tooltip, and text.",
    )
    transform: list[Any] | None = Field(
        default=None,
        description="Optional Vega-Lite transforms for lightweight chart shaping.",
    )
    layer: list[Any] | None = Field(default=None, description="Optional Vega-Lite layers.")
    facet: dict[str, Any] | None = Field(
        default=None,
        description="Optional Vega-Lite facet definition.",
    )
    repeat: dict[str, Any] | None = Field(
        default=None,
        description="Optional Vega-Lite repeat definition.",
    )
    hconcat: list[Any] | None = Field(
        default=None,
        description="Optional horizontal concat views.",
    )
    vconcat: list[Any] | None = Field(
        default=None,
        description="Optional vertical concat views.",
    )
    concat: list[Any] | None = Field(default=None, description="Optional concat views.")
    spec: dict[str, Any] | None = Field(
        default=None,
        description="Nested Vega-Lite view for facet/repeat.",
    )
    config: dict[str, Any] | None = Field(
        default=None,
        description="Optional Vega-Lite configuration.",
    )
    params: list[Any] | None = Field(default=None, description="Optional Vega-Lite params.")


class WordCloudSpec(AgentToolInput):
    title: str | None = Field(default=None, description="Optional visible word-cloud title.")
    word_field: str | None = Field(
        default=None,
        description="Word column name. Default is `word`.",
    )
    count_field: str | None = Field(
        default=None,
        description="Positive count column name. Default is `count`.",
    )
    top_n: Annotated[int, Field(ge=20, le=80)] | None = Field(
        default=None,
        description="Render only the top 20-80 terms for readability. Default is 80.",
    )
    width: Annotated[int, Field(ge=200, le=1600)] | None = Field(
        default=None,
        description="Word-cloud width in pixels.",
    )
    height: Annotated[int, Field(ge=160, le=1200)] | None = Field(
        default=None,
        description="Word-cloud height in pixels.",
    )
    prefer_horizontal: Annotated[float, Field(ge=0.8, le=1.0)] | None = Field(
        default=None,
        description="Keep at least 80% of terms horizontal. Default is 0.85.",
    )
    font_size_range: Annotated[list[float], Field(min_length=2, max_length=2)] | None = Field(
        default=None,
        description=(
            "Optional [min, max] font-size range. Default is [12, 56], or "
            "[10, 42] for denser clouds."
        ),
    )
    color_mode: Literal["rank_tier", "field"] | None = Field(
        default=None,
        description=(
            "Use `rank_tier` for restrained 2-3 color ranking. Use `field` only when "
            "an upstream low-cardinality field already encodes category, sentiment, or source."
        ),
    )
    color_field: str | None = Field(
        default=None,
        description="Required only when color_mode is `field`.",
    )
    palette: list[str] | None = Field(
        default=None,
        description="Optional restrained color palette for rank tiers or semantic groups.",
    )


class AnalysisGraphInput(AgentToolInput):
    dataset_id: RequiredString = Field(
        description=(
            "Use one registered dataset. For word clouds, this dataset should already be a "
            "chart-ready frequency table."
        )
    )
    spec: VegaLiteSpec | None = Field(
        default=None,
        description=(
            "Vega-Lite chart specification. Xenix injects dataset values before rendering. "
            "Use standard Vega-Lite mark, encoding, transform, layer, facet, concat, repeat, "
            "config, and params fields. Do not include data or datasets, and do not use this "
            "field for word clouds."
        ),
    )
    wordcloud_spec: WordCloudSpec | None = Field(
        default=None,
        description=(
            "Dedicated word-cloud configuration. Use data.query or data.transform first to "
            "produce chart-ready rows, usually exact columns `word` and `count`. For Chinese "
            "text, segment upstream first; do not pass raw sentences or expect analysis.graph "
            "to tokenize them."
        ),
    )

    @model_validator(mode="after")
    def _exactly_one_graph_mode(self) -> AnalysisGraphInput:
        if (self.spec is None) == (self.wordcloud_spec is None):
            raise ValueError("analysis.graph requires exactly one of spec or wordcloud_spec.")
        return self


class AnalysisLambdaInput(AgentToolInput):
    code: RequiredString
    datasets: Annotated[dict[str, RequiredString], Field(min_length=1)] = Field(
        description="Mapping from dataset alias to registered dataset_id."
    )
    params: dict[str, Any] = Field(default_factory=dict)
    manifest: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _non_empty_dataset_aliases(self) -> AnalysisLambdaInput:
        if any(not alias.strip() for alias in self.datasets):
            raise ValueError(
                "analysis.lambda datasets must map non-empty aliases to dataset ids."
            )
        return self


class CleaningOperationInput(AgentToolInput):
    operation: RequiredString
    params: dict[str, Any] = Field(default_factory=dict)


class DataCleanInput(AgentToolInput):
    dataset_id: RequiredString
    name: OptionalString | None = None
    operations: list[CleaningOperationInput] = Field(default_factory=list)


class DataCleanMetadataInput(AgentToolInput):
    groups: list[RequiredString] | None = None


class DataTokenizeInput(AgentToolInput):
    dataset_id: RequiredString
    name: OptionalString | None = None
    text_column: RequiredString | None = Field(
        default=None,
        description=(
            "Chinese text column name to segment. Use either text_column or "
            "text_column_index, never both."
        ),
    )
    text_column_index: NonNegativeInteger | None = Field(
        default=None,
        description=(
            "Preferred zero-based Chinese text column index from the source schema. "
            "Use either text_column_index or text_column, never both."
        ),
    )
    id_columns: list[RequiredString] | None = Field(
        default=None,
        description=(
            "Optional identifier column names preserved in token_rows output. Use either "
            "id_columns or id_column_indexes, never both."
        ),
    )
    id_column_indexes: list[NonNegativeInteger] | None = Field(
        default=None,
        description=(
            "Preferred zero-based identifier column indexes from the source schema, "
            "preserved in token_rows output. Use either id_column_indexes or id_columns, "
            "never both."
        ),
    )
    output: Literal["token_text", "token_rows"] = Field(
        default="token_text",
        description=(
            "Choose token_text for model-ready rows or token_rows for "
            "one-token-per-row analysis."
        ),
    )
    tokenizer_profile: Literal["zh_business_v1"] = Field(
        default="zh_business_v1",
        description="Stable Chinese-first tokenization profile owned by Xenix.",
    )

    @model_validator(mode="after")
    def _selector_forms_do_not_overlap(self) -> DataTokenizeInput:
        if self.text_column is not None and self.text_column_index is not None:
            raise ValueError(
                "data.tokenize accepts either text_column or text_column_index, not both."
            )
        if self.text_column is None and self.text_column_index is None:
            raise ValueError("data.tokenize requires text_column or text_column_index.")
        if self.id_columns is not None and self.id_column_indexes is not None:
            raise ValueError(
                "data.tokenize accepts either id_columns or id_column_indexes, not both."
            )
        return self


class DatasetBindingInput(AgentToolInput):
    alias: RequiredString = Field(
        description="SQL table alias for this registered dataset, such as orders or customers."
    )
    dataset_id: RequiredString = Field(
        description="Registered dataset id bound to this SQL alias."
    )


class DataQueryInput(AgentToolInput):
    dataset_id: RequiredString | None = Field(
        default=None,
        description=(
            "Use for one input dataset, which will be available in SQL as input. "
            "Pass either dataset_id or bindings; if both are present, bindings wins."
        ),
    )
    bindings: Annotated[list[DatasetBindingInput], Field(min_length=1)] | None = Field(
        default=None,
        description=(
            "Highest-priority input source. Use for one or more registered datasets "
            "with explicit SQL aliases."
        ),
    )
    sql: RequiredString = Field(description="Read-only SELECT or CTE query to execute.")
    column_reference: Literal["names", "indexes"] = Field(
        default="names",
        description=(
            "names is the default source-header mode. indexes exposes each bound relation "
            "as c0, c1, ... using the zero-based indexes returned by data.query."
        ),
    )
    limit: Annotated[int, Field(ge=1, le=200)] = Field(
        default=50,
        description="Maximum number of rows to return in the bounded result.",
    )

    @model_validator(mode="after")
    def _has_input_source(self) -> DataQueryInput:
        if self.dataset_id is None and self.bindings is None:
            raise ValueError("data.query requires dataset_id or bindings.")
        return self


class DataTransformInput(AgentToolInput):
    dataset_id: RequiredString | None = Field(
        default=None,
        description=(
            "Use for one input dataset, which will be available in SQL as input. "
            "Pass either dataset_id or bindings; if both are present, bindings wins."
        ),
    )
    bindings: Annotated[list[DatasetBindingInput], Field(min_length=1)] | None = Field(
        default=None,
        description=(
            "Highest-priority input source. Use for one or more registered datasets "
            "with explicit SQL aliases."
        ),
    )
    sql: RequiredString = Field(
        description=(
            "DuckDB SQL script. It may use SELECT/CTE or bounded temporary-table steps, "
            "but must leave a final relation named output."
        )
    )
    column_reference: Literal["names", "indexes"] = Field(
        default="names",
        description=(
            "names is the default source-header mode. indexes exposes each bound relation "
            "as c0, c1, ... using the zero-based indexes returned by data.query."
        ),
    )
    name: OptionalString | None = Field(
        default=None,
        description="Optional name for the generated transformed dataset.",
    )

    @model_validator(mode="after")
    def _has_input_source(self) -> DataTransformInput:
        if self.dataset_id is None and self.bindings is None:
            raise ValueError("data.transform requires dataset_id or bindings.")
        return self


class RoleBindingInput(AgentToolInput):
    role: RequiredString = Field(
        description="Semantic role such as feature, target, or partial_target."
    )
    columns: list[RequiredString] | None = Field(
        default=None,
        description="Legacy exact dataset column names assigned to this semantic role.",
    )
    column_indexes: list[NonNegativeInteger] | None = Field(
        default=None,
        description=(
            "Preferred zero-based dataset column indexes returned by data.query. "
            "Use either column_indexes or columns, never both."
        ),
    )


class DataFeatureSelectInput(AgentToolInput):
    dataset_id: RequiredString = Field(
        description="Registered dataset id whose columns will be role-bound."
    )
    model_key: RequiredString | None = Field(
        default=None,
        description=(
            "Optional chosen model key to pre-align role validation and later training."
        ),
    )
    role_bindings: list[RoleBindingInput] = Field(
        description="Semantic role bindings to persist for later model training or apply."
    )


ModelFamilyValue = Literal[
    "supervised",
    "clustering",
    "anomaly_detection",
    "association_rules",
    "recommendation",
    "text_analysis",
]


class ModelMetadataInput(AgentToolInput):
    model_key: RequiredString | None = Field(
        default=None,
        description=(
            "Inspect one chosen model. Accepts a canonical model key or a simple alias. "
            "Returns role schemas and param_schema by default."
        ),
    )
    model_family: ModelFamilyValue | None = Field(
        default=None,
        description=(
            "Browse lightweight candidate models in one family such as supervised, "
            "clustering, anomaly_detection, association_rules, recommendation, "
            "or text_analysis."
        ),
    )
    include_param_grid_schema: bool = Field(
        default=False,
        description=(
            "Only use with model_key. When true, also return param_grid_schema for "
            "hyperparameter tuning."
        ),
    )

    @model_validator(mode="after")
    def _has_model_selector(self) -> ModelMetadataInput:
        if self.model_key is None and self.model_family is None:
            raise ValueError("model.metadata requires model_key or model_family.")
        return self


class ModelTrainInput(AgentToolInput):
    binding_id: RequiredString = Field(
        description="Column role-binding id returned by data.feature.select."
    )
    models: Annotated[list[RequiredString], Field(min_length=1)] = Field(
        description="One or more chosen model keys or aliases to train."
    )
    params_by_model: dict[str, dict[str, Any]] | None = Field(
        default=None,
        description="Optional per-model parameter objects keyed by model key.",
    )
    run_name: OptionalString = Field(
        default="",
        description="Optional human-readable run name.",
    )


class ModelHyperTrainInput(AgentToolInput):
    binding_id: RequiredString = Field(
        description="Column role-binding id returned by data.feature.select."
    )
    param_grids_by_model: Annotated[
        dict[str, dict[str, Any]],
        Field(min_length=1),
    ] = Field(description="Per-model tuning grids keyed by model key.")
    run_name: OptionalString = Field(
        default="",
        description="Optional human-readable run name.",
    )


InlineCell = str | int | float | bool | None


class InlineApplyRowsInput(AgentToolInput):
    header_index_map: dict[str, NonNegativeInteger]
    data: list[list[InlineCell]]


class ModelApplyInput(AgentToolInput):
    trained_model_id: RequiredString
    input_sources: list[RequiredString] = Field(default_factory=list)
    input_rows: InlineApplyRowsInput | None = None

    @model_validator(mode="after")
    def _has_apply_input(self) -> ModelApplyInput:
        if not self.input_sources and self.input_rows is None:
            raise ValueError("model.apply requires input_sources or input_rows.")
        return self


class ModelTaskQueryInput(AgentToolInput):
    task_ids: Annotated[list[RequiredString], Field(min_length=1)] = Field(
        description="One or more explicit ML task ids to inspect."
    )
    include_logs: bool = Field(
        default=False,
        description="Set true to include bounded task logs in the response.",
    )
    max_log_entries: Annotated[int, Field(ge=0, le=1000)] = Field(
        default=200,
        description=(
            "Maximum number of log entries to return per task when include_logs is true."
        ),
    )


class KnowledgeLookupInput(AgentToolInput):
    query: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            min_length=1,
            max_length=MAX_KNOWLEDGE_QUERY_CHARS,
        ),
    ] = Field(
        description=(
            "The business question, rule, definition, assumption, or experience needed "
            "for the current analysis, preprocessing, or modeling task. Do not provide "
            "SQL or internal IDs."
        )
    )
    mode: Literal["auto", "keyword", "semantic", "hybrid"] = Field(
        default="auto",
        description=(
            "Retrieval mode: 'auto' selects the best ready mode; 'keyword' matches "
            "explicit terms and phrases; 'semantic' matches meaning when wording "
            "differs; 'hybrid' combines term and meaning matches. Semantic or hybrid "
            "can return a typed unavailable result when that capability is not ready."
        ),
    )


class AgentSkillActivateInput(AgentToolInput):
    name: RequiredString = Field(
        description="The built-in Agent Skill name to activate."
    )


class AgentSkillResourceInput(AgentToolInput):
    skill_name: RequiredString = Field(
        description="The already activated Agent Skill that owns the resource."
    )
    path: RequiredString = Field(
        description="A catalog-listed resource path returned by the skill activation result."
    )
