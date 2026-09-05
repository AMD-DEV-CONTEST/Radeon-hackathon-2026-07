from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Generic, TypeVar, cast

import pandas as pd
from pydantic import ValidationError as PydanticValidationError

from ...config import AppPaths
from ...exceptions import NotFoundError, ValidationError
from ..analysis_graph import AnalysisGraphService, GraphDatasetInput
from ..analysis_lambda import AnalysisLambdaDataset, AnalysisLambdaInput, AnalysisLambdaService
from ..analysis_profile import AnalysisProfileService
from ..artifact_service import (
    ArtifactService,
    RegisterArtifactInput,
    build_artifact_uri,
)
from ..data_cleaning import (
    CleanOperation,
    CleanDatasetInput,
    DataCleaningService,
    cleaning_operation_group_names,
    cleaning_operation_metadata,
)
from ..data_tokenization import DataTokenizationService, TokenizeDatasetInput
from ..data_transform import (
    DataQueryInput,
    DataQueryTransformService,
    DataTransformInput,
    DatasetSqlBinding,
)
from ..dataset_inspection import detect_source_format, load_dataframe
from ..dataset_export_service import DatasetExportService
from ..dataset_service import DatasetService
from ..ml.registry import get_model_catalog_entry, list_model_catalog, list_model_keys
from ..ml.types import EvaluationKind, ModelCatalogEntry, ModelFamily, ModelTaskKind
from ..ml_service import (
    ApplyWithFilesInput,
    CreateColumnBindingInput,
    FitWithEvaluateInput,
    MLService,
    InlineApplyRowsInput as ServiceInlineApplyRowsInput,
    TuneWithEvaluateInput,
)
from ..preprocessing_worker import LocalPreprocessingWorkerRunner, PreprocessingWorkerRunner
from ..storage.models import (
    ArtifactKind,
    MLTaskArtifactKind,
    MLTaskRow,
    MLTaskStatus,
    MLTaskType,
    TrainedModelRow,
)
from ..llm.tooling import (
    AgentTool as TypedAgentTool,
    AgentToolRegistry as LLMToolRegistry,
    AgentToolSpec,
    ToolExecutionContext,
    ToolSuccess,
)
from ..llm.xenix_table_text import render_xenix_table_tool_result
from .tool_inputs import (
    AgentToolInput,
    AnalysisGraphInput,
    AnalysisLambdaInput as AnalysisLambdaToolInput,
    DataCleanInput,
    DataCleanMetadataInput,
    DataFeatureSelectInput,
    DataIntegrateInput,
    DataQueryInput as DataQueryToolInput,
    DataTokenizeInput,
    DataTransformInput as DataTransformToolInput,
    ModelApplyInput,
    ModelHyperTrainInput,
    ModelMetadataInput,
    ModelTaskQueryInput,
    ModelTrainInput,
)
from .tool_presentations import DEFAULT_TOOL_PRESENTATION, ToolPresentation, tool_presentation_for_name


_MODEL_ALIAS_SUFFIXES = {
    "classification",
    "classifier",
    "clustering",
    "regression",
    "regressor",
}
_MODEL_KEY_ALIAS_OVERRIDES = {
    "k_neighbors": "regression.knn",
    "kneighbors": "regression.knn",
    "k_neighbors_classifier": "classification.knn",
    "kneighborsclassifier": "classification.knn",
    "k_neighbors_regressor": "regression.knn",
    "kneighborsregressor": "regression.knn",
}
MODEL_APPLY_GRACE_SECONDS = 30.0
MODEL_TRAIN_GRACE_SECONDS = 60.0
MAX_CLEANING_REPORT_OPERATION_ENTRIES = 12
MAX_CLEANING_REPORT_VALIDATION_ENTRIES = 12
MAX_CLEANING_REPORT_WARNING_ENTRIES = 5
MAX_CLEANING_REPORT_COLUMN_NAMES = 6
MAX_CLEANING_REPORT_WARNING_CHARS = 240
MAX_CLEANING_REPORT_COLUMN_NAME_CHARS = 96
MODEL_HYPER_TRAIN_GRACE_SECONDS = 60.0


ToolInputT = TypeVar("ToolInputT", bound=AgentToolInput)
ToolHandler = Callable[[ToolInputT, ToolExecutionContext], ToolSuccess]


@dataclass(frozen=True)
class ConcreteAgentTool(Generic[ToolInputT]):
    registration: TypedAgentTool[ToolInputT]
    presentation: ToolPresentation = DEFAULT_TOOL_PRESENTATION

    @property
    def spec(self) -> AgentToolSpec:
        return self.registration.spec


def _index_agent_tools(
    tools: Iterable[ConcreteAgentTool[Any]],
) -> dict[str, ConcreteAgentTool[Any]]:
    """Build the concrete Tool index without permitting identity collisions."""

    indexed: dict[str, ConcreteAgentTool[Any]] = {}
    provider_name_owners: dict[str, str] = {}
    for tool in tools:
        tool_name = tool.spec.name
        if tool_name in indexed:
            raise ValidationError(f"Tool '{tool_name}' is already registered.")
        provider_name = tool.spec.provider_name
        owner = provider_name_owners.get(provider_name)
        if owner is not None:
            raise ValidationError(
                f"Provider tool name '{provider_name}' is already registered by '{owner}'."
            )
        indexed[tool_name] = tool
        provider_name_owners[provider_name] = tool_name
    return indexed


def _tool_input_error_message(exc: PydanticValidationError) -> str:
    error: dict[str, Any] = dict(next(iter(exc.errors(include_url=False)), {}))
    context = error.get("ctx")
    if isinstance(context, dict) and isinstance(context.get("error"), ValueError):
        return str(context["error"])
    location = error.get("loc")
    field_name = (
        str(location[0])
        if isinstance(location, tuple | list) and location
        else "Tool input"
    )
    message = str(error.get("msg") or "is invalid.")
    if field_name == "id_columns":
        return "data.tokenize id_columns must be a list of strings."
    if field_name == "text_column_index":
        return "data.tokenize text_column_index must be a zero-based integer."
    if field_name == "id_column_indexes":
        return "data.tokenize id_column_indexes must contain zero-based integers."
    return f"{field_name}: {message}"


class AgentToolRegistry:
    def __init__(
        self,
        *,
        paths: AppPaths,
        dataset_service: DatasetService,
        data_cleaning_service: DataCleaningService,
        data_transform_service: DataQueryTransformService,
        ml_service: MLService,
        artifact_service: ArtifactService,
        dataset_export_service: DatasetExportService | None = None,
        preprocessing_worker_runner: PreprocessingWorkerRunner | None = None,
        data_tokenization_service: DataTokenizationService | None = None,
        analysis_profile_service: AnalysisProfileService | None = None,
        analysis_graph_service: AnalysisGraphService | None = None,
        analysis_lambda_service: AnalysisLambdaService | None = None,
    ) -> None:
        self._paths = paths
        self._dataset_service = dataset_service
        self._data_cleaning_service = data_cleaning_service
        self._data_tokenization_service = data_tokenization_service or DataTokenizationService(paths)
        self._data_transform_service = data_transform_service
        self._analysis_profile_service = analysis_profile_service or AnalysisProfileService()
        self._analysis_graph_service = analysis_graph_service or AnalysisGraphService(paths)
        self._analysis_lambda_service = analysis_lambda_service or AnalysisLambdaService(paths)
        self._ml_service = ml_service
        self._artifact_service = artifact_service
        _ = dataset_export_service
        self._preprocessing_worker_runner = preprocessing_worker_runner or LocalPreprocessingWorkerRunner()
        self._model_key_aliases = self._build_model_key_aliases()
        self._tools = _index_agent_tools(
            (
                self._build_data_integrate_tool(),
                self._build_analysis_graph_tool(),
                # analysis.lambda is intentionally retained in code but not registered
                # in the Agent-facing tool set.
                # self._build_analysis_lambda_tool(),
                self._build_data_clean_tool(),
                self._build_data_clean_metadata_tool(),
                self._build_data_tokenize_tool(),
                self._build_data_query_tool(),
                self._build_data_transform_tool(),
                self._build_data_feature_select_tool(),
                self._build_model_metadata_tool(),
                self._build_model_train_tool(),
                self._build_model_hyper_train_tool(),
                self._build_model_apply_tool(),
                self._build_model_task_query_tool(),
            )
        )

    def list_specs(self) -> list[AgentToolSpec]:
        return [tool.spec for tool in self._tools.values()]

    def register_with_llm(self, registry: LLMToolRegistry) -> None:
        """Inject concrete implementations into the LLM-owned registry.

        This class remains a composition-time factory for domain-backed
        handlers and UI presentation.  It is not a second dispatch authority.
        """

        for tool in self._tools.values():
            registry.register(tool.registration)

    def tool_presentation(self, tool_name: str) -> ToolPresentation:
        tool = self._tools.get(tool_name)
        if tool is None:
            return tool_presentation_for_name(tool_name)
        return tool.presentation

    def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        context: ToolExecutionContext,
    ) -> ToolSuccess:
        self._raise_if_cancelled(context)
        tool = self._tools.get(tool_name)
        if tool is None:
            raise ValidationError(f"Tool '{tool_name}' is not registered.")
        try:
            input_data = tool.registration.input_model.model_validate(arguments)
        except PydanticValidationError as exc:
            raise ValidationError(_tool_input_error_message(exc)) from None
        result = tool.registration.implementation(input_data, context)
        self._raise_if_cancelled(context)
        if not isinstance(result, ToolSuccess):
            raise ValidationError("Concrete Agent Tool returned an unsupported outcome.")
        return result

    def _tool(
        self,
        *,
        name: str,
        provider_name: str,
        description: str,
        input_model: type[ToolInputT],
        handler: ToolHandler[ToolInputT],
        provider_field_enums: tuple[tuple[str, tuple[str, ...]], ...] = (),
    ) -> ConcreteAgentTool[ToolInputT]:
        return ConcreteAgentTool(
            registration=TypedAgentTool(
                name=name,
                provider_name=provider_name,
                description=description,
                input_model=input_model,
                implementation=handler,
                provider_field_enums=provider_field_enums,
            ),
            presentation=tool_presentation_for_name(name),
        )

    def _build_data_integrate_tool(self) -> ConcreteAgentTool[DataIntegrateInput]:
        return self._tool(
            name="data.integrate",
            provider_name="data_integrate",
            description="Combine two or more registered datasets into a generated derived dataset.",
            input_model=DataIntegrateInput,
            handler=self._data_integrate,
        )

    def _build_analysis_graph_tool(self) -> ConcreteAgentTool[AnalysisGraphInput]:
        return self._tool(
            name="analysis.graph",
            provider_name="analysis_graph",
            description=(
                "Draw one bounded static SVG artifact for a registered dataset. Pass exactly one graph mode: "
                "`spec` for ordinary Vega-Lite charts, or `wordcloud_spec` for the dedicated word-cloud path. "
                "`wordcloud_spec` is the dedicated word-cloud path and expects an upstream chart-ready "
                "frequency table from data.query or data.transform."
            ),
            input_model=AnalysisGraphInput,
            handler=self._analysis_graph,
        )

    def _build_analysis_lambda_tool(
        self,
    ) -> ConcreteAgentTool[AnalysisLambdaToolInput]:
        return self._tool(
            name="analysis.lambda",
            provider_name="analysis_lambda",
            description=(
                "Run a one-off Python analysis function over registered datasets. "
                "The code must define analyze(ctx, inputs, params) and return any JSON-serializable dict. "
                "inputs is a mapping from dataset alias to pandas DataFrame; inputs[alias].read() also returns "
                "that DataFrame. Supported imports: pandas/pd, numpy/np, matplotlib/plt, scipy, statsmodels, "
                "sklearn, xgboost, lightgbm, math, statistics, datetime, json, io, collections, itertools, "
                "functools, and typing. Do not import seaborn or arbitrary packages. Use ctx.artifact.create(...) "
                "for generated artifacts: ctx.artifact.create(name, content), ctx.artifact.create(content, name=...), "
                "or ctx.artifact.create(name=..., content=...); content may be a pandas DataFrame, SVG/text string, "
                "bytes/io.BytesIO, or matplotlib Figure. value=... is accepted as an alias for content=...."
            ),
            input_model=AnalysisLambdaToolInput,
            handler=self._analysis_lambda,
        )

    def _build_data_clean_tool(self) -> ConcreteAgentTool[DataCleanInput]:
        return self._tool(
            name="data.clean",
            provider_name="data_clean",
            description=(
                "Create a new derived dataset by applying atomic predefined cleaning operations "
                "to one registered dataset. Prefer zero-based column_index or column_indexes from "
                "data.query; use data.clean.metadata only for unfamiliar operations or parameters. "
                "After missing.drop_high_missing_columns or encoding.one_hot, use names or a new "
                "data.query/data.clean call before using indexes."
            ),
            input_model=DataCleanInput,
            handler=self._data_clean,
        )

    def _build_data_clean_metadata_tool(
        self,
    ) -> ConcreteAgentTool[DataCleanMetadataInput]:
        return self._tool(
            name="data.clean.metadata",
            provider_name="data_clean_metadata",
            description=(
                "Return a compact data.clean operation catalog. Request only relevant groups when an "
                "operation or parameter is uncertain."
            ),
            input_model=DataCleanMetadataInput,
            handler=self._data_clean_metadata,
            provider_field_enums=(
                ("groups", cleaning_operation_group_names()),
            ),
        )

    def _build_data_tokenize_tool(self) -> ConcreteAgentTool[DataTokenizeInput]:
        return self._tool(
            name="data.tokenize",
            provider_name="data_tokenize",
            description=(
                "Create a new derived dataset by tokenizing one Chinese text column with the stable "
                "Xenix profile zh_business_v1. Use output=token_text to keep source rows and append "
                "token_text for downstream text models, or output=token_rows to explode one token per row. "
                "Select the text and optional identifier columns by names or zero-based source indexes; "
                "do not mix the two forms for one selector."
            ),
            input_model=DataTokenizeInput,
            handler=self._data_tokenize,
        )

    def _build_data_query_tool(self) -> ConcreteAgentTool[DataQueryToolInput]:
        return self._tool(
            name="data.query",
            provider_name="data_query",
            description=(
                "Run a read-only SELECT/CTE query over registered datasets. "
                "Pass either dataset_id for one input aliased as input, or bindings for explicit SQL aliases. "
                "At least one input source is required. If both are present, bindings wins. "
                "When column_reference=indexes, each bound relation exposes zero-based c0, c1, ... SQL "
                "columns instead of source names; use this for punctuation-heavy or Unicode headers. "
                "During a cleaning pass, emit at most one data.query call per model response; batch related "
                "evidence in one compact query and wait for its result before any focused follow-up. "
                "Returns bounded rows and does not create a derived dataset or artifact."
            ),
            input_model=DataQueryToolInput,
            handler=self._data_query,
        )

    def _build_data_transform_tool(
        self,
    ) -> ConcreteAgentTool[DataTransformToolInput]:
        return self._tool(
            name="data.transform",
            provider_name="data_transform",
            description=(
                "Create a new derived dataset from bounded DuckDB SQL over registered datasets. "
                "Use dataset_id for one input aliased as input, or bindings for explicit aliases. "
                "At least one input source is required. If both are present, bindings wins. "
                "When column_reference=indexes, each bound relation exposes zero-based c0, c1, ... SQL "
                "columns instead of source names; use this for punctuation-heavy or Unicode headers. "
                "For multi-statement scripts, create or leave a final TEMP relation named output; "
                "Xenix materializes SELECT * FROM output."
            ),
            input_model=DataTransformToolInput,
            handler=self._data_transform,
        )

    def _build_data_feature_select_tool(
        self,
    ) -> ConcreteAgentTool[DataFeatureSelectInput]:
        return self._tool(
            name="data.feature.select",
            provider_name="data_feature_select",
            description=(
                "Bind registered dataset columns to semantic roles required by a model/analyzer. "
                "Prefer per-role zero-based column_indexes from data.query; Xenix resolves them against the "
                "current dataset schema and persists canonical names."
            ),
            input_model=DataFeatureSelectInput,
            handler=self._data_feature_select,
        )

    def _build_model_metadata_tool(self) -> ConcreteAgentTool[ModelMetadataInput]:
        return self._tool(
            name="model.metadata",
            provider_name="model_metadata",
            description=(
                "Browse a lightweight model directory by model_family, or inspect one chosen model's role "
                "and parameter schema with model_key."
            ),
            input_model=ModelMetadataInput,
            handler=self._model_metadata,
        )

    def _build_model_train_tool(self) -> ConcreteAgentTool[ModelTrainInput]:
        return self._tool(
            name="model.train",
            provider_name="model_train",
            description=(
                "Train and evaluate one or more models for a persisted dataset column role binding. "
                "Use model.metadata with model_family to browse candidates, then inspect one model_key for "
                "parameter detail."
            ),
            input_model=ModelTrainInput,
            handler=self._model_train,
        )

    def _build_model_hyper_train_tool(
        self,
    ) -> ConcreteAgentTool[ModelHyperTrainInput]:
        return self._tool(
            name="model.hyper_train",
            provider_name="model_hyper_train",
            description=(
                "Run hyperparameter training for one or more models. "
                "Use model.metadata with model_family to browse candidates, then inspect one model_key with "
                "include_param_grid_schema=true."
            ),
            input_model=ModelHyperTrainInput,
            handler=self._model_hyper_train,
        )

    def _build_model_apply_tool(self) -> ConcreteAgentTool[ModelApplyInput]:
        return self._tool(
            name="model.apply",
            provider_name="model_apply",
            description="Apply a trained model to registered dataset or artifact inputs, or inline rows.",
            input_model=ModelApplyInput,
            handler=self._model_apply,
        )

    def _build_model_task_query_tool(
        self,
    ) -> ConcreteAgentTool[ModelTaskQueryInput]:
        return self._tool(
            name="model.task.query",
            provider_name="model_task_query",
            description="Query ML task status, metadata, artifacts, errors, and logs by explicit task ids.",
            input_model=ModelTaskQueryInput,
            handler=self._model_task_query,
        )

    def _data_integrate(
        self,
        input_data: DataIntegrateInput,
        context: ToolExecutionContext,
    ) -> ToolSuccess:
        self._raise_if_cancelled(context)
        datasets = [
            self._dataset_service.get_dataset(dataset_id)
            for dataset_id in input_data.dataset_ids
        ]
        frames = [self._load_frame(Path(dataset.source_path).expanduser().resolve()) for dataset in datasets]
        output_dir = self._paths.artifacts / "datasets" / "integrated"
        output_dir.mkdir(parents=True, exist_ok=True)
        name = input_data.name or "Integrated dataset"
        output_path = output_dir / f"{self._slug(name)}-{int(time.time())}.csv"
        pd.concat(frames, ignore_index=True).to_csv(output_path, index=False)
        input_dataset_ids = [dataset.id for dataset in datasets]
        payload = self._register_generated_dataset_result(
            context,
            output_path=output_path,
            name=name,
            summary="Integrated dataset created.",
            metadata_payload={"input_dataset_ids": input_dataset_ids},
        )
        payload["input_dataset_ids"] = input_dataset_ids
        return self._tabular_tool_success("data.integrate", payload)

    def _analysis_graph(
        self,
        input_data: AnalysisGraphInput,
        context: ToolExecutionContext,
    ) -> ToolSuccess:
        self._raise_if_cancelled(context)
        dataset = self._dataset_service.get_dataset(input_data.dataset_id)
        raw_spec = (
            input_data.spec.model_dump(by_alias=True, exclude_none=True)
            if input_data.spec is not None
            else None
        )
        raw_wordcloud_spec = (
            input_data.wordcloud_spec.model_dump(exclude_none=True)
            if input_data.wordcloud_spec is not None
            else None
        )
        graph_result = self._analysis_graph_service.graph_dataset(
            GraphDatasetInput(
                source_path=dataset.source_path,
                dataset_name=dataset.name,
                spec=raw_spec,
                wordcloud_spec=raw_wordcloud_spec,
            )
        )
        graph_metadata = graph_result.graph_metadata
        default_title = f"{dataset.name} graph"
        title = str(graph_metadata.get("title") or default_title).strip() or default_title
        spec_format = str(graph_metadata.get("spec_format") or "graph")
        artifact = self._artifact_service.register_artifact(
            RegisterArtifactInput(
                kind=ArtifactKind.IMAGE,
                title=title,
                absolute_path=graph_result.output_path,
                mime_type="image/svg+xml",
                summary=f"Graph generated by analysis.graph ({spec_format}).",
                preview_payload=graph_metadata,
                metadata_payload={
                    "dataset_id": dataset.id,
                    "analysis_graph": graph_metadata,
                },
            )
        )
        payload = {
            "dataset_id": dataset.id,
            "artifact_id": artifact.id,
            "graph": graph_metadata,
        }
        return ToolSuccess(value=payload)

    def _analysis_lambda(
        self,
        input_data: AnalysisLambdaToolInput,
        context: ToolExecutionContext,
    ) -> ToolSuccess:
        self._raise_if_cancelled(context)
        datasets: list[AnalysisLambdaDataset] = []
        for alias, dataset_id in input_data.datasets.items():
            dataset = self._dataset_service.get_dataset(dataset_id)
            datasets.append(
                AnalysisLambdaDataset(
                    alias=alias,
                    dataset_id=dataset.id,
                    dataset_name=dataset.name,
                    source_path=dataset.source_path,
                )
            )

        lambda_result = self._analysis_lambda_service.run_lambda(
            AnalysisLambdaInput(
                code=input_data.code,
                datasets=datasets,
                params=input_data.params,
                manifest=input_data.manifest,
            ),
            cancel_requested=context.cancel_requested,
        )
        artifact_map: dict[str, str] = {}
        artifact_payloads: list[dict[str, Any]] = []
        for descriptor in lambda_result.artifacts:
            kind = self._lambda_artifact_kind(descriptor.kind)
            metadata_payload = {
                "analysis_lambda": {
                    "placeholder_id": descriptor.placeholder_id,
                    "kind": descriptor.kind,
                    "metadata": descriptor.metadata_payload,
                }
            }
            artifact = self._artifact_service.register_artifact(
                RegisterArtifactInput(
                    kind=kind,
                    title=descriptor.title,
                    absolute_path=descriptor.absolute_path,
                    mime_type=descriptor.mime_type,
                    summary=descriptor.summary,
                    metadata_payload=metadata_payload,
                )
            )
            uri = build_artifact_uri(artifact.id)
            artifact_map[descriptor.placeholder_id] = artifact.id
            artifact_payloads.append(
                {
                    "artifact_id": artifact.id,
                    "uri": uri,
                    "title": artifact.title,
                    "kind": artifact.kind.value,
                    "mime_type": artifact.mime_type,
                    "placeholder_id": descriptor.placeholder_id,
                }
            )

        output = self._rewrite_lambda_artifact_uris(lambda_result.output, artifact_map)
        payload = {
            "result": {
                "output": output,
            },
            "artifacts": artifact_payloads,
            "dataset_ids": [dataset.dataset_id for dataset in datasets],
        }
        return ToolSuccess(value=payload)

    def _data_clean(
        self,
        input_data: DataCleanInput,
        context: ToolExecutionContext,
    ) -> ToolSuccess:
        self._raise_if_cancelled(context)
        dataset = self._dataset_service.get_dataset(input_data.dataset_id)
        name = input_data.name or f"{dataset.name} cleaned"
        operations = [
            operation.model_dump(mode="python")
            for operation in input_data.operations
        ]
        if not operations:
            report: dict[str, Any] = {
                "row_count_before": None,
                "row_count_after": None,
                "rows_removed": 0,
                "operations": [],
                "validation_rules": [],
                "warnings": [],
                "no_op": True,
            }
            return self._tabular_tool_success(
                "data.clean",
                {
                    "dataset_id": dataset.id,
                    "source_dataset_id": dataset.id,
                    "cleaning_report": report,
                    "message": "No cleaning operations were requested. Nothing happened.",
                },
            )
        try:
            clean_input = CleanDatasetInput(
                source_path=dataset.source_path,
                name=name,
                operations=[
                    CleanOperation(**operation)
                    for operation in operations
                ],
            )
        except PydanticValidationError as exc:
            raise ValidationError("operations must contain objects with operation and optional params.") from exc
        clean_result = self._data_cleaning_service.clean_dataset(clean_input)
        row_count_before = int(clean_result.report.get("row_count_before", 0))
        row_count_after = int(clean_result.report.get("row_count_after", 0))
        payload = self._register_generated_dataset_result(
            context,
            output_path=Path(clean_result.output_path),
            name=name,
            summary=f"Cleaned dataset created. Rows: {row_count_before} -> {row_count_after}.",
            derived_from_dataset_id=dataset.id,
            metadata_payload={"cleaning_report": clean_result.report},
        )
        payload["row_count_before"] = row_count_before
        payload["row_count_after"] = row_count_after
        payload["cleaning_report"] = self._compact_cleaning_report(clean_result.report)
        return self._tabular_tool_success("data.clean", payload)

    def _data_clean_metadata(
        self,
        input_data: DataCleanMetadataInput,
        context: ToolExecutionContext,
    ) -> ToolSuccess:
        self._raise_if_cancelled(context)
        groups: list[str] = (
            list(input_data.groups)
            if input_data.groups is not None
            else []
        )
        payload = cleaning_operation_metadata(groups)
        return ToolSuccess(value=payload)

    def _data_tokenize(
        self,
        input_data: DataTokenizeInput,
        context: ToolExecutionContext,
    ) -> ToolSuccess:
        self._raise_if_cancelled(context)
        dataset = self._dataset_service.get_dataset(input_data.dataset_id)
        default_name = f"{dataset.name} tokenized"
        name = input_data.name or default_name
        tokenize_result = self._data_tokenization_service.tokenize_dataset(
            TokenizeDatasetInput(
                source_path=dataset.source_path,
                name=name,
                text_column=input_data.text_column,
                text_column_index=input_data.text_column_index,
                id_columns=input_data.id_columns,
                id_column_indexes=input_data.id_column_indexes,
                output=input_data.output,
                tokenizer_profile=input_data.tokenizer_profile,
            )
        )
        raw_row_count = tokenize_result.report.get("output_row_count", 0)
        row_count = (
            raw_row_count
            if isinstance(raw_row_count, int) and not isinstance(raw_row_count, bool)
            else 0
        )
        payload = self._register_generated_dataset_result(
            context,
            output_path=Path(tokenize_result.output_path),
            name=name,
            summary=f"Tokenized dataset created. Rows: {row_count}.",
            derived_from_dataset_id=dataset.id,
            metadata_payload={"tokenization_report": tokenize_result.report},
        )
        payload["row_count"] = row_count
        payload["tokenization_report"] = tokenize_result.report
        return self._tabular_tool_success("data.tokenize", payload)

    def _data_query(
        self,
        input_data: DataQueryToolInput,
        context: ToolExecutionContext,
    ) -> ToolSuccess:
        self._raise_if_cancelled(context)
        bindings = self._resolve_sql_bindings(
            input_data,
        )
        query_result = self._data_transform_service.query(
            DataQueryInput(
                bindings=bindings,
                sql=input_data.sql,
                limit=input_data.limit,
                column_reference=input_data.column_reference,
            )
        )
        payload = {
            "columns": self._query_columns_payload(query_result.columns),
            "rows": self._query_rows_payload(query_result.rows, query_result.columns),
            "returned_row_count": query_result.returned_row_count,
            "total_row_count": query_result.total_row_count,
            "truncated": query_result.truncated,
        }
        return self._tabular_tool_success("data.query", payload)

    def _data_transform(
        self,
        input_data: DataTransformToolInput,
        context: ToolExecutionContext,
    ) -> ToolSuccess:
        self._raise_if_cancelled(context)
        bindings = self._resolve_sql_bindings(input_data)
        input_dataset_ids = [binding.dataset_id for binding in bindings]
        default_name = "Transformed dataset"
        if len(bindings) == 1:
            default_name = f"{self._dataset_service.get_dataset(bindings[0].dataset_id).name} transformed"
        name = input_data.name or default_name
        transform_result = self._data_transform_service.transform(
            DataTransformInput(
                bindings=bindings,
                sql=input_data.sql,
                name=name,
                column_reference=input_data.column_reference,
            )
        )
        derived_from_dataset_id = input_dataset_ids[0] if len(set(input_dataset_ids)) == 1 else None
        payload = self._register_generated_dataset_result(
            context,
            output_path=Path(transform_result.output_path),
            name=name,
            summary=f"Transformed dataset created. Rows: {transform_result.row_count}.",
            derived_from_dataset_id=derived_from_dataset_id,
            metadata_payload={
                "transform_report": transform_result.transform_report,
                "input_dataset_ids": input_dataset_ids,
            },
        )
        payload["row_count"] = transform_result.row_count
        payload["columns"] = transform_result.columns
        payload["transform_report"] = transform_result.transform_report
        payload["input_dataset_ids"] = input_dataset_ids
        return self._tabular_tool_success("data.transform", payload)

    def _data_feature_select(
        self,
        input_data: DataFeatureSelectInput,
        context: ToolExecutionContext,
    ) -> ToolSuccess:
        self._raise_if_cancelled(context)
        binding = self._ml_service.create_column_binding(
            CreateColumnBindingInput(
                dataset_id=input_data.dataset_id,
                model_key=input_data.model_key,
                role_bindings=[
                    role_binding.model_dump(mode="python", exclude_none=True)
                    for role_binding in input_data.role_bindings
                ],
            )
        )
        return ToolSuccess(
            value={
                "binding_id": binding.id,
                "dataset_id": binding.dataset_id,
                "role_bindings": list(binding.role_bindings),
                "model_key": binding.model_key,
                "model_family": binding.model_family,
                "model_task_kind": binding.model_task_kind,
            },
        )

    def _model_metadata(
        self,
        input_data: ModelMetadataInput,
        context: ToolExecutionContext,
    ) -> ToolSuccess:
        self._raise_if_cancelled(context)
        detail_model_key: str | None = None
        if input_data.model_key is not None:
            detail_model_key = self._normalize_model_keys(
                [input_data.model_key],
                field_name="model_key",
            )[0]

        detail_query = detail_model_key is not None

        if detail_query:
            assert detail_model_key is not None
            catalog_entries = [get_model_catalog_entry(detail_model_key)]
        else:
            catalog_entries = list_model_catalog()

        selected_model_family = (
            ModelFamily(input_data.model_family)
            if input_data.model_family is not None
            else None
        )
        if selected_model_family is not None:
            catalog_entries = [
                entry for entry in catalog_entries if entry.model_family == selected_model_family
            ]

        catalog_entries = sorted(
            catalog_entries,
            key=lambda entry: (
                entry.model_family.value,
                entry.model_task_kind.value,
                entry.evaluation_kind.value,
                entry.problem_kind.value if entry.problem_kind is not None else "",
                entry.recommendation_tier,
                entry.model_key,
            ),
        )
        include_param_grid_schema = input_data.include_param_grid_schema
        include_param_schema = detail_query or include_param_grid_schema
        if not detail_query:
            include_param_schema = False
            include_param_grid_schema = False
        models = [
            self._model_catalog_payload(
                entry,
                detail_query=detail_query,
                include_param_schema=include_param_schema,
                include_param_grid_schema=include_param_grid_schema,
            )
            for entry in catalog_entries
        ]
        payload = {
            "model_keys": [model["model_key"] for model in models],
            "models": models,
        }
        return ToolSuccess(value=payload)

    def _model_train(
        self,
        input_data: ModelTrainInput,
        context: ToolExecutionContext,
    ) -> ToolSuccess:
        self._raise_if_cancelled(context)
        binding_id = input_data.binding_id
        models = self._normalize_model_keys(
            input_data.models,
            field_name="models",
        )
        params_by_model = self._normalize_model_mapping(
            input_data.params_by_model,
            field_name="params_by_model",
        )
        binding = self._ml_service.get_column_binding(binding_id)
        dataset_id = binding.dataset_id
        created_task_ids: list[str] = []
        for model_key in models:
            self._raise_if_cancelled(context)
            created = self._ml_service.fit_with_evaluate(
                FitWithEvaluateInput(
                    binding_id=binding_id,
                    run_name=input_data.run_name,
                    model_key=model_key,
                    params=dict(params_by_model.get(model_key) or {}),
                )
            )
            created_task_ids.append(created.id)
        training_result = self._wait_for_training_models_or_none(
            created_task_ids,
            context=context,
            timeout_seconds=MODEL_TRAIN_GRACE_SECONDS,
        )
        if training_result is None:
            return self._training_task_receipt(
                tool_name="model.train",
                dataset_id=dataset_id,
                root_task_ids=created_task_ids,
                operation="fit",
            )
        tasks, trained_models = training_result
        payload = {
            "async_state": "completed",
            "dataset_id": dataset_id,
            "task_ids": [task.id for task in tasks],
            "ml_tasks": [self._ml_task_payload(task) for task in tasks],
            "trained_models": [self._trained_model_payload(model) for model in trained_models],
        }
        return ToolSuccess(value=payload)

    def _model_hyper_train(
        self,
        input_data: ModelHyperTrainInput,
        context: ToolExecutionContext,
    ) -> ToolSuccess:
        self._raise_if_cancelled(context)
        binding_id = input_data.binding_id
        normalized_grids = self._normalize_model_mapping(
            input_data.param_grids_by_model,
            field_name="param_grids_by_model",
            require_hyperparameter_tuning=True,
        )
        binding = self._ml_service.get_column_binding(binding_id)
        dataset_id = binding.dataset_id
        created_task_ids: list[str] = []
        for model_key, grid in normalized_grids.items():
            self._raise_if_cancelled(context)
            created = self._ml_service.tune_with_evaluate(
                TuneWithEvaluateInput(
                    binding_id=binding_id,
                    run_name=input_data.run_name,
                    model_key=model_key,
                    param_grid=dict(grid),
                )
            )
            created_task_ids.append(created.id)
        training_result = self._wait_for_training_models_or_none(
            created_task_ids,
            context=context,
            timeout_seconds=MODEL_HYPER_TRAIN_GRACE_SECONDS,
        )
        if training_result is None:
            return self._training_task_receipt(
                tool_name="model.hyper_train",
                dataset_id=dataset_id,
                root_task_ids=created_task_ids,
                operation="hyperparameter_tuning",
            )
        tasks, trained_models = training_result
        payload = {
            "async_state": "completed",
            "dataset_id": dataset_id,
            "task_ids": [task.id for task in tasks],
            "ml_tasks": [self._ml_task_payload(task) for task in tasks],
            "trained_models": [self._trained_model_payload(model) for model in trained_models],
        }
        return ToolSuccess(value=payload)

    def _model_apply(
        self,
        input_data: ModelApplyInput,
        context: ToolExecutionContext,
    ) -> ToolSuccess:
        self._raise_if_cancelled(context)
        resolved_input_files = self._resolve_apply_input_sources(input_data.input_sources)
        apply_input = ApplyWithFilesInput(
            trained_model_id=input_data.trained_model_id,
            input_files=resolved_input_files,
            input_rows=(
                ServiceInlineApplyRowsInput(
                    **input_data.input_rows.model_dump(mode="python")
                )
                if input_data.input_rows is not None
                else None
            ),
        )
        task = self._ml_service.apply(apply_input)
        completed_task = self._wait_for_task_or_none(
            task.id,
            context=context,
            timeout_seconds=MODEL_APPLY_GRACE_SECONDS,
        )
        if completed_task is None:
            return self._single_task_receipt(
                tool_name="model.apply",
                task_id=task.id,
                operation="apply",
            )
        task = completed_task
        details = self._ml_service.get_task_details(task.id)
        output_artifact = next(
            artifact
            for artifact in details.artifacts
            if artifact.artifact_kind is MLTaskArtifactKind.APPLY_RESULT
        )
        generic_artifact = self._artifact_service.register_artifact(
            RegisterArtifactInput(
                kind=ArtifactKind.FILE,
                title="Apply results",
                absolute_path=output_artifact.absolute_path,
                mime_type="text/csv",
                metadata_payload={"ml_task_id": task.id, "dataset_id": task.dataset_id},
            )
        )
        return ToolSuccess(
            value={
                "async_state": "completed",
                "ml_task_id": task.id,
                "task_ids": [task.id],
                "ml_tasks": [self._ml_task_payload(task)],
                "dataset_id": task.dataset_id,
                "result_dataset_id": details.task.result_payload.get("result_dataset_id") if details.task.result_payload else None,
                "artifact_id": generic_artifact.id,
                "row_count": details.task.result_payload.get("row_count") if details.task.result_payload else None,
            },
        )

    def _resolve_apply_input_sources(self, input_sources: list[str]) -> list[str]:
        return [self._resolve_apply_input_source(input_source) for input_source in input_sources]

    def _resolve_apply_input_source(self, input_source: str) -> str:
        source = input_source.strip()
        if source.startswith("artifact://"):
            artifact = self._artifact_service.resolve_uri(source)
            if not artifact.exists:
                raise ValidationError("Apply input artifact file is missing.")
            return artifact.absolute_path

        try:
            dataset = self._dataset_service.get_dataset(source)
        except NotFoundError:
            raise ValidationError("model.apply input_sources must be registered dataset ids or artifact:// URIs.") from None
        if not Path(dataset.source_path).exists():
            raise ValidationError("Apply input dataset source file is missing.")
        return dataset.source_path

    def _model_task_query(
        self,
        input_data: ModelTaskQueryInput,
        context: ToolExecutionContext,
    ) -> ToolSuccess:
        self._raise_if_cancelled(context)
        tasks = [
            self._ml_task_details_payload(
                task_id,
                include_logs=input_data.include_logs,
                max_log_entries=input_data.max_log_entries,
            )
            for task_id in input_data.task_ids
        ]
        payload = {
            "task_ids": input_data.task_ids,
            "tasks": tasks,
        }
        return ToolSuccess(value=payload)

    def _resolve_sql_bindings(
        self,
        input_data: DataQueryToolInput | DataTransformToolInput,
    ) -> list[DatasetSqlBinding]:
        if input_data.bindings is not None:
            bindings: list[DatasetSqlBinding] = []
            for input_binding in input_data.bindings:
                dataset = self._dataset_service.get_dataset(input_binding.dataset_id)
                bindings.append(
                    DatasetSqlBinding(
                        alias=input_binding.alias,
                        dataset_id=dataset.id,
                        source_path=dataset.source_path,
                    )
                )
            return bindings

        dataset_id = input_data.dataset_id
        if dataset_id is None:
            raise AssertionError("Validated SQL Tool input must own an input source.")
        dataset = self._dataset_service.get_dataset(dataset_id)
        return [
            DatasetSqlBinding(
                alias="input",
                dataset_id=dataset.id,
                source_path=dataset.source_path,
            )
        ]

    def _query_columns_payload(self, columns: list[dict[str, str]]) -> dict[str, Any]:
        rows = [
            [
                str(column.get("name") or ""),
                str(column.get("type") or ""),
                index,
            ]
            for index, column in enumerate(columns)
        ]
        return self._compact_table(["name", "type", "index"], rows)

    def _query_rows_payload(
        self,
        rows: list[dict[str, Any]],
        columns: list[dict[str, str]],
    ) -> dict[str, Any]:
        column_names = [str(column.get("name") or "") for column in columns]
        data = [[row.get(column_name) for column_name in column_names] for row in rows]
        return {
            "_schema": {column_name: index for index, column_name in enumerate(column_names)},
            "data": data,
        }

    def _compact_cleaning_report(self, report: dict[str, Any]) -> dict[str, Any]:
        """Project full execution audit into the bounded next-call facts.

        The complete report is retained in the generated artifact metadata.  A
        provider only needs the operation sequence, aggregate effects, small
        field samples and warnings needed to decide its next Tool call.
        """

        compact: dict[str, Any] = {}
        for key in ("row_count_before", "row_count_after", "rows_removed", "no_op"):
            value = report.get(key)
            if isinstance(value, (str, int, float, bool)) or value is None:
                compact[key] = value

        operations = report.get("operations")
        if isinstance(operations, list):
            compact["operation_count"] = len(operations)
            compact["operations"] = [
                self._compact_cleaning_report_operation(item)
                for item in operations[:MAX_CLEANING_REPORT_OPERATION_ENTRIES]
                if isinstance(item, dict)
            ]
            omitted = len(operations) - len(compact["operations"])
            if omitted:
                compact["omitted_operation_entries"] = omitted

        validation_rules = report.get("validation_rules")
        if isinstance(validation_rules, list):
            compact["validation_rule_count"] = len(validation_rules)
            compact["validation_rules"] = [
                self._compact_cleaning_validation_rule(item)
                for item in validation_rules[:MAX_CLEANING_REPORT_VALIDATION_ENTRIES]
                if isinstance(item, dict)
            ]
            omitted = len(validation_rules) - len(compact["validation_rules"])
            if omitted:
                compact["omitted_validation_rules"] = omitted

        warnings = report.get("warnings")
        if isinstance(warnings, list):
            normalized_warnings = [
                self._bounded_cleaning_text(item, MAX_CLEANING_REPORT_WARNING_CHARS)
                for item in warnings
                if str(item).strip()
            ]
            compact["warning_count"] = len(normalized_warnings)
            if normalized_warnings:
                compact["warnings"] = normalized_warnings[:MAX_CLEANING_REPORT_WARNING_ENTRIES]
                omitted = len(normalized_warnings) - len(compact["warnings"])
                if omitted:
                    compact["omitted_warnings"] = omitted
        return compact

    def _compact_cleaning_report_operation(self, operation: dict[str, Any]) -> dict[str, Any]:
        compact: dict[str, Any] = {}
        name = operation.get("operation")
        if isinstance(name, str) and name:
            compact["operation"] = name
        for key in (
            "column",
            "rows_removed",
            "cells_filled",
            "cells_changed",
            "coerced_to_null",
            "columns_changed",
            "columns_removed",
            "threshold",
            "multiplier",
            "target_type",
            "style",
            "ascii_lower",
            "drop_first",
            "max_categories",
        ):
            value = operation.get(key)
            if isinstance(value, (str, int, float, bool)):
                if key == "column":
                    compact[key] = self._bounded_cleaning_text(
                        value,
                        MAX_CLEANING_REPORT_COLUMN_NAME_CHARS,
                    )
                else:
                    compact[key] = value
        feature_range = operation.get("feature_range")
        if (
            isinstance(feature_range, list)
            and len(feature_range) == 2
            and all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in feature_range)
        ):
            compact["feature_range"] = list(feature_range)
        self._compact_cleaning_report_columns(compact, "columns", operation.get("columns"))
        self._compact_cleaning_report_columns(compact, "dropped_columns", operation.get("dropped_columns"))
        self._compact_cleaning_report_columns(compact, "evaluated_columns", operation.get("evaluated_columns"))
        self._compact_cleaning_report_columns(
            compact,
            "encoded_columns",
            operation.get("encoded_columns"),
            include_empty=True,
        )
        skipped_columns = operation.get("skipped_columns")
        if isinstance(skipped_columns, list):
            self._compact_cleaning_report_columns(
                compact,
                "skipped_columns",
                [
                    item.get("column")
                    for item in skipped_columns
                    if isinstance(item, dict) and item.get("column") is not None
                ],
            )
        columns_summary = operation.get("columns_summary")
        if isinstance(columns_summary, list):
            generated_columns: list[Any] = []
            for summary in columns_summary:
                if isinstance(summary, dict) and isinstance(summary.get("generated_columns"), list):
                    generated_columns.extend(summary["generated_columns"])
            self._compact_cleaning_report_columns(compact, "generated_columns", generated_columns)
        for source_key, count_key in (
            ("mapping", "renamed_column_count"),
            ("generated_empty_names", "generated_column_name_count"),
            ("duplicate_collisions", "duplicate_column_name_count"),
            ("columns_summary", "column_summary_count"),
            ("category_columns", "generated_category_column_count"),
        ):
            value = operation.get(source_key)
            if isinstance(value, (list, dict)):
                compact[count_key] = len(value)
        return compact

    def _compact_cleaning_validation_rule(self, rule: dict[str, Any]) -> dict[str, Any]:
        compact: dict[str, Any] = {}
        for key in ("name", "column", "operation", "action", "violations", "rows_removed"):
            value = rule.get(key)
            if isinstance(value, (str, int, float, bool)):
                if key in {"name", "column"}:
                    compact[key] = self._bounded_cleaning_text(
                        value,
                        MAX_CLEANING_REPORT_COLUMN_NAME_CHARS,
                    )
                else:
                    compact[key] = value
        return compact

    @staticmethod
    def _compact_cleaning_report_columns(
        compact: dict[str, Any],
        key: str,
        value: Any,
        *,
        include_empty: bool = False,
    ) -> None:
        if not isinstance(value, list):
            return
        values = [str(item) for item in value if str(item).strip()]
        if not values:
            if include_empty:
                compact[key] = []
                compact[f"{key}_count"] = 0
            return
        compact[key] = [
            AgentToolRegistry._bounded_cleaning_text(item, MAX_CLEANING_REPORT_COLUMN_NAME_CHARS)
            for item in values[:MAX_CLEANING_REPORT_COLUMN_NAMES]
        ]
        compact[f"{key}_count"] = len(values)
        omitted = len(values) - len(compact[key])
        if omitted:
            compact[f"omitted_{key}"] = omitted

    @staticmethod
    def _bounded_cleaning_text(value: Any, limit: int) -> str:
        text = str(value)
        if len(text) <= limit:
            return text
        if limit <= 1:
            return text[:limit]
        return text[: limit - 1] + "…"

    def _tabular_tool_success(self, tool_name: str, payload: dict[str, Any]) -> ToolSuccess:
        """Return the one canonical value for a tabular Tool.

        The formatter runs while the concrete Tool still owns the raw
        intermediate payload.  Once this method returns, only the XTT text
        (when the payload has a tabular contract) crosses the LLM boundary;
        there is no later raw-payload-to-XTT projection.
        """

        rendered = render_xenix_table_tool_result(
            tool_name=tool_name,
            status="succeeded",
            payload=payload,
        )
        return ToolSuccess(value=rendered if rendered is not None else payload)

    def _register_generated_dataset_result(
        self,
        context: ToolExecutionContext,
        *,
        output_path: Path,
        name: str,
        summary: str,
        derived_from_dataset_id: str | None = None,
        metadata_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        resolved_output_path = output_path.resolve()
        payload = self._preprocessing_worker_runner.run(
            "data.register_generated_dataset",
            {
                "output_path": str(resolved_output_path),
                "name": name,
                "summary": summary,
                "derived_from_dataset_id": derived_from_dataset_id,
                "metadata_payload": dict(metadata_payload or {}),
            },
            paths=self._paths,
        )
        return payload

    def _compact_table(self, keys: list[str], rows: list[list[Any]]) -> dict[str, Any]:
        return {
            "_schema": {key: index for index, key in enumerate(keys)},
            "data": rows,
        }

    def _lambda_artifact_kind(self, raw_kind: str) -> ArtifactKind:
        value = str(raw_kind or "").strip()
        if value == "image":
            return ArtifactKind.IMAGE
        if value == "report":
            return ArtifactKind.REPORT
        if value in {"dataset", "file", "table"}:
            return ArtifactKind.FILE
        try:
            return ArtifactKind(value)
        except ValueError:
            return ArtifactKind.OTHER

    def _rewrite_lambda_artifact_uris(self, value: Any, artifact_map: dict[str, str]) -> Any:
        if isinstance(value, str):
            rewritten = value
            for placeholder_id, artifact_id in artifact_map.items():
                rewritten = rewritten.replace(f"artifact://{placeholder_id}", build_artifact_uri(artifact_id))
            return rewritten
        if isinstance(value, list):
            return [self._rewrite_lambda_artifact_uris(item, artifact_map) for item in value]
        if isinstance(value, dict):
            return {
                key: self._rewrite_lambda_artifact_uris(item, artifact_map)
                for key, item in value.items()
            }
        return value

    def _load_frame(self, path: Path) -> pd.DataFrame:
        source_format = detect_source_format(path)
        if source_format.value == "unknown":
            raise ValidationError("Only .csv, .parquet, .xlsx, and .xls dataset files are supported.")
        return load_dataframe(path, source_format)

    def _wait_for_training_models_or_none(
        self,
        root_task_ids: list[str],
        *,
        context: ToolExecutionContext,
        timeout_seconds: float,
    ) -> tuple[list[MLTaskRow], list[TrainedModelRow]] | None:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            root_tasks = [self._ml_service.get_task_details(task_id).task for task_id in root_task_ids]
            trained_models = self._trained_models_for_root_tasks(root_task_ids)
            related_tasks = self._related_training_tasks(root_tasks, trained_models)
            self._raise_if_cancelled(
                context,
                ml_task_ids=[task.id for task in related_tasks] or root_task_ids,
            )

            failed = [
                task
                for task in related_tasks
                if task.status in {MLTaskStatus.FAILED, MLTaskStatus.CANCELLED}
            ]
            if failed:
                raise ValidationError(f"ML task '{failed[0].id}' finished with status '{failed[0].status.value}'.")

            root_tasks_succeeded = all(task.status is MLTaskStatus.SUCCEEDED for task in root_tasks)
            if root_tasks_succeeded and len(trained_models) == len(root_task_ids):
                pending_evaluation = False
                models_by_root_task = {model.ml_task_id: model for model in trained_models}
                for root_task in root_tasks:
                    model = models_by_root_task.get(root_task.id)
                    if model is None:
                        pending_evaluation = True
                        break
                    if self._training_task_requires_follow_up_evaluation(root_task):
                        evaluation_task_id = self._evaluation_task_id_for_model(model)
                        if not evaluation_task_id:
                            pending_evaluation = True
                            break
                        evaluation_task = self._ml_service.get_task_details(evaluation_task_id).task
                        if evaluation_task.status is not MLTaskStatus.SUCCEEDED:
                            pending_evaluation = True
                            break
                if not pending_evaluation:
                    return self._related_training_tasks(root_tasks, trained_models), trained_models

            time.sleep(0.1)
        return None

    def _wait_for_task(
        self,
        task_id: str,
        *,
        context: ToolExecutionContext,
        timeout_seconds: float = 120.0,
    ) -> MLTaskRow:
        task = self._wait_for_task_or_none(task_id, context=context, timeout_seconds=timeout_seconds)
        if task is None:
            raise ValidationError(f"Timed out waiting for ML task '{task_id}'.")
        return task

    def _wait_for_task_or_none(
        self,
        task_id: str,
        *,
        context: ToolExecutionContext,
        timeout_seconds: float,
    ) -> MLTaskRow | None:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            self._raise_if_cancelled(context, ml_task_ids=[task_id])
            task = self._ml_service.get_task_details(task_id).task
            if task.status in self._terminal_statuses():
                if task.status is not MLTaskStatus.SUCCEEDED:
                    raise ValidationError(f"ML task '{task.id}' finished with status '{task.status.value}'.")
                return task
            time.sleep(0.1)
        return None

    def _raise_if_cancelled(self, context: ToolExecutionContext, *, ml_task_ids: list[str] | None = None) -> None:
        if not context.cancel_requested():
            return
        if ml_task_ids:
            for task_id in ml_task_ids:
                try:
                    self._ml_service.cancel_task(task_id)
                except Exception:
                    continue
        raise ValidationError("Agent run was cancelled.")

    def _terminal_statuses(self) -> set[MLTaskStatus]:
        return {MLTaskStatus.SUCCEEDED, MLTaskStatus.FAILED, MLTaskStatus.CANCELLED}

    def _trained_models_for_root_tasks(self, root_task_ids: list[str]) -> list[TrainedModelRow]:
        models_by_task_id: dict[str, TrainedModelRow] = {}
        for task_id in root_task_ids:
            model = self._ml_service.get_trained_model_by_ml_task(task_id)
            if model is not None:
                models_by_task_id[task_id] = model
        return [models_by_task_id[task_id] for task_id in root_task_ids if task_id in models_by_task_id]

    def _related_training_tasks(
        self,
        root_tasks: list[MLTaskRow],
        trained_models: list[TrainedModelRow],
    ) -> list[MLTaskRow]:
        tasks: list[MLTaskRow] = []
        seen_task_ids: set[str] = set()
        for task in root_tasks:
            tasks.append(task)
            seen_task_ids.add(task.id)
        for model in trained_models:
            evaluation_task_id = self._evaluation_task_id_for_model(model)
            if not evaluation_task_id or evaluation_task_id in seen_task_ids:
                continue
            task = self._ml_service.get_task_details(evaluation_task_id).task
            tasks.append(task)
            seen_task_ids.add(task.id)
        return tasks

    def _evaluation_task_id_for_model(self, model: TrainedModelRow) -> str | None:
        task_id = model.metadata_payload.get("evaluation_ml_task_id")
        if isinstance(task_id, str) and task_id.strip():
            return task_id
        return None

    def _training_task_requires_follow_up_evaluation(self, task: MLTaskRow) -> bool:
        continuation = task.request_payload.get("continuation_plan")
        return isinstance(continuation, dict) and continuation.get("next_operation") == "evaluate"

    def _training_task_receipt(
        self,
        *,
        tool_name: str,
        dataset_id: str,
        root_task_ids: list[str],
        operation: str,
    ) -> ToolSuccess:
        root_tasks = [self._ml_service.get_task_details(task_id).task for task_id in root_task_ids]
        trained_models = self._trained_models_for_root_tasks(root_task_ids)
        tasks = self._related_training_tasks(root_tasks, trained_models)
        task_ids = [task.id for task in tasks] or list(root_task_ids)
        payload = {
            "async_state": "running_background",
            "dataset_id": dataset_id,
            "operation": operation,
            "task_ids": task_ids,
            "root_task_ids": list(root_task_ids),
            "ml_tasks": [self._ml_task_payload(task) for task in tasks],
            "trained_models": [self._trained_model_payload(model) for model in trained_models],
        }
        return ToolSuccess(value=payload)

    def _single_task_receipt(
        self,
        *,
        tool_name: str,
        task_id: str,
        operation: str,
    ) -> ToolSuccess:
        task = self._ml_service.get_task_details(task_id).task
        payload = {
            "async_state": "running_background",
            "operation": operation,
            "ml_task_id": task.id,
            "task_ids": [task.id],
            "root_task_ids": [task.id],
            "dataset_id": task.dataset_id,
            "ml_tasks": [self._ml_task_payload(task)],
        }
        return ToolSuccess(value=payload)

    def _task_receipt_markdown(self, payload: dict[str, Any]) -> str:
        task_ids = [str(task_id) for task_id in payload.get("task_ids", [])]
        lines = ["The ML work is still running in the background."]
        if task_ids:
            lines.append("")
            lines.append("Task ids:")
            lines.extend(f"- `{task_id}`" for task_id in task_ids)
        lines.append("")
        lines.append("Use `model.task.query` with these task ids to inspect status and logs.")
        return "\n".join(lines)

    def _ml_task_payload(self, task: MLTaskRow) -> dict[str, Any]:
        return {
            "task_id": task.id,
            "dataset_id": task.dataset_id,
            "task_type": task.task_type.value,
            "status": task.status.value,
            "model_key": self._model_key_from_task_payload(task.request_payload),
            "error_summary": task.error_summary,
            "created_at": task.created_at.isoformat() if task.created_at else None,
            "started_at": task.started_at.isoformat() if task.started_at else None,
            "finished_at": task.finished_at.isoformat() if task.finished_at else None,
            "updated_at": task.updated_at.isoformat() if task.updated_at else None,
            "follow_up_task_ids": self._follow_up_task_ids(task),
        }

    def _ml_task_details_payload(
        self,
        task_id: str,
        *,
        include_logs: bool,
        max_log_entries: int,
    ) -> dict[str, Any]:
        details = self._ml_service.get_task_details(task_id)
        task_payload = self._ml_task_payload(details.task)
        logs = [log.model_dump(mode="json") for log in details.logs[-max_log_entries:]] if include_logs and max_log_entries else []
        task_payload.update(
            {
                "request": self._task_request_summary(details.task.request_payload),
                "result": dict(details.task.result_payload or {}),
                "artifacts": [
                    {
                        "artifact_id": artifact.id,
                        "artifact_kind": artifact.artifact_kind.value,
                        "absolute_path": artifact.absolute_path,
                        "ready_to_open": artifact.ready_to_open,
                        "created_at": artifact.created_at.isoformat() if artifact.created_at else None,
                    }
                    for artifact in details.artifacts
                ],
                "logs": logs,
            }
        )
        return task_payload

    def _task_request_summary(self, request_payload: dict[str, Any]) -> dict[str, Any]:
        keys = [
            "project_id",
            "dataset_id",
            "evaluation_kind",
            "feature_columns",
            "manual_training",
            "hyperparameter_tuning",
            "evaluate_model",
            "apply_model",
            "input_sources",
        ]
        return {key: request_payload[key] for key in keys if key in request_payload}

    def _model_key_from_task_payload(self, request_payload: dict[str, Any]) -> str | None:
        for key in ("manual_training", "hyperparameter_tuning", "evaluate_model", "apply_model"):
            value = request_payload.get(key)
            if isinstance(value, dict) and isinstance(value.get("model_key"), str):
                return cast(str, value["model_key"])
        return None

    def _follow_up_task_ids(self, task: MLTaskRow) -> list[str]:
        if task.task_type not in {MLTaskType.FIT, MLTaskType.HYPERPARAMETER_TUNING}:
            return []
        model = self._ml_service.get_trained_model_by_ml_task(task.id)
        if model is None:
            return []
        evaluation_task_id = self._evaluation_task_id_for_model(model)
        return [evaluation_task_id] if evaluation_task_id else []

    def _trained_model_payload(self, model: TrainedModelRow) -> dict[str, Any]:
        return {
            "trained_model_id": model.id,
            "dataset_id": model.dataset_id,
            "model_key": model.model_key,
            "artifact_path": model.artifact_path,
            "metadata": dict(model.metadata_payload),
        }

    def _training_summary_markdown(self, payload: dict[str, Any]) -> str:
        models = payload.get("trained_models", [])
        lines = ["Training completed."]
        for model in models:
            metadata = model.get("metadata") if isinstance(model, dict) else None
            metric_text = self._metadata_evaluation_summary(metadata if isinstance(metadata, dict) else {})
            line = f"- `{model['model_key']}` trained model id: `{model['trained_model_id']}`"
            if metric_text:
                line += f"; evaluation: {metric_text}"
            lines.append(line)
        return "\n".join(lines)

    def _model_task_query_markdown(self, tasks: list[dict[str, Any]]) -> str:
        if not tasks:
            return "No ML tasks were found."
        lines = ["ML task status:"]
        for task in tasks:
            task_id = task.get("task_id")
            task_type = task.get("task_type")
            status = task.get("status")
            model_key = task.get("model_key") or "unknown model"
            lines.append(f"- `{task_id}` {task_type} for `{model_key}`: `{status}`")
            error_summary = str(task.get("error_summary") or "").strip()
            if error_summary:
                lines.append(f"  Error: {error_summary}")
            evaluation_lines = self._task_evaluation_summary_lines(task)
            lines.extend(evaluation_lines)
            follow_up_task_ids = task.get("follow_up_task_ids")
            if isinstance(follow_up_task_ids, list) and follow_up_task_ids:
                joined_ids = ", ".join(f"`{task_id}`" for task_id in follow_up_task_ids)
                lines.append(f"  Follow-up task ids: {joined_ids}")
        return "\n".join(lines)

    def _metadata_evaluation_summary(self, metadata: dict[str, Any]) -> str:
        metric_name = metadata.get("evaluation_primary_metric_name")
        metric_value = metadata.get("evaluation_primary_metric_value")
        if not isinstance(metric_name, str) or metric_value is None:
            return ""
        return f"{metric_name}={self._format_metric_value(metric_value)}"

    def _task_evaluation_summary_lines(self, task: dict[str, Any]) -> list[str]:
        if task.get("task_type") != MLTaskType.EVALUATE.value:
            return []
        result = task.get("result")
        if not isinstance(result, dict):
            return []
        evaluation = result.get("evaluation")
        if not isinstance(evaluation, dict):
            return []
        metrics = evaluation.get("metrics")
        if not isinstance(metrics, dict):
            return []

        lines: list[str] = []
        primary_name = evaluation.get("primary_metric_name")
        primary_value = evaluation.get("primary_metric_value")
        if isinstance(primary_name, str) and primary_value is not None:
            lines.append(f"  Primary metric: {primary_name}={self._format_metric_value(primary_value)}")

        metric_names = self._summary_metric_names(str(result.get("evaluation_kind") or ""), metrics)
        metric_text = self._format_metric_list(metrics, metric_names)
        if metric_text:
            lines.append(f"  Key metrics: {metric_text}")

        details = evaluation.get("details")
        if isinstance(details, dict):
            probability_metrics = details.get("probability_metrics")
            if isinstance(probability_metrics, dict) and probability_metrics.get("available") is False:
                reason = probability_metrics.get("reason")
                if isinstance(reason, str) and reason:
                    lines.append(f"  Probability metrics unavailable: {reason}.")
        return lines

    def _summary_metric_names(self, evaluation_kind: str, metrics: dict[str, Any]) -> list[str]:
        if evaluation_kind == EvaluationKind.REGRESSION.value:
            return ["r2", "rmse", "mae", "mape", "explained_variance"]
        if evaluation_kind == EvaluationKind.CLASSIFICATION.value:
            names = [
                "accuracy",
                "balanced_accuracy",
                "f1_macro",
                "f1_weighted",
                "roc_auc",
                "pr_auc",
                "log_loss",
            ]
            return [name for name in names if name in metrics]
        return list(metrics)[:5]

    def _format_metric_list(self, metrics: dict[str, Any], names: list[str]) -> str:
        parts: list[str] = []
        for name in names:
            if name not in metrics:
                continue
            parts.append(f"{name}={self._format_metric_value(metrics[name])}")
        return ", ".join(parts)

    def _format_metric_value(self, value: Any) -> str:
        if isinstance(value, (int, float)):
            return f"{float(value):.4g}"
        return str(value)

    def _model_catalog_payload(
        self,
        entry: ModelCatalogEntry,
        *,
        detail_query: bool,
        include_param_schema: bool,
        include_param_grid_schema: bool,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model_key": entry.model_key,
            "display_name": entry.display_name,
            "description": entry.guidance,
            "problem_kind": entry.problem_kind.value if entry.problem_kind is not None else None,
            "evaluation_kind": entry.evaluation_kind.value,
            "model_family": entry.model_family.value,
            "model_task_kind": entry.model_task_kind.value,
            "family": entry.family,
            "recommendation_tier": entry.recommendation_tier,
            "supports_fit": entry.supports_fit,
            "supports_hyperparameter_tuning": entry.supports_hyperparameter_tuning,
        }
        if detail_query:
            payload.update(
                {
                    "summary_metric_name": entry.summary_metric_name,
                    "requires_target": entry.requires_target,
                    "train_role_schema": entry.train_role_schema.model_dump(mode="json"),
                    "apply_role_schema": entry.apply_role_schema.model_dump(mode="json"),
                    "result_contract": entry.result_contract.model_dump(mode="json"),
                }
            )
        if include_param_schema:
            payload["param_schema"] = entry.param_schema
        if include_param_grid_schema:
            payload["param_grid_schema"] = entry.param_grid_schema
        return payload

    def _model_metadata_markdown(self, models: list[dict[str, Any]]) -> str:
        if not models:
            return "No models match the requested filters."
        lines = ["Available models:"]
        for model in models:
            capabilities = ["fit"] if model["supports_fit"] else []
            if model["supports_hyperparameter_tuning"]:
                capabilities.append("hyperparameter_tuning")
            legacy_problem = f", {model['problem_kind']}" if model["problem_kind"] else ""
            lines.append(
                "- "
                f"`{model['model_key']}` ({model['display_name']}{legacy_problem}); "
                f"evaluation: {model['evaluation_kind']}; "
                f"task: {model['model_task_kind']}; "
                f"capabilities: {', '.join(capabilities)}"
            )
        return "\n".join(lines)

    def _normalize_model_mapping(
        self,
        raw_mapping: Any,
        *,
        field_name: str,
        require_hyperparameter_tuning: bool = False,
    ) -> dict[str, Any]:
        if raw_mapping is None:
            return {}
        if not isinstance(raw_mapping, dict):
            raise ValidationError(f"{field_name} must be an object keyed by model key.")
        normalized: dict[str, Any] = {}
        failures: list[str] = []
        for raw_key, value in raw_mapping.items():
            model_key = self._canonical_model_key(str(raw_key))
            if model_key is None:
                failures.append(str(raw_key))
                continue
            if value is None:
                value = {}
            if not isinstance(value, dict):
                failures.append(f"{raw_key} must map to an object")
                continue
            if require_hyperparameter_tuning:
                catalog = get_model_catalog_entry(model_key)
                if not catalog.supports_hyperparameter_tuning:
                    failures.append(f"{raw_key} lacks hyperparameter_tuning support")
                    continue
            normalized[model_key] = value
        if failures:
            raise ValidationError(self._model_key_error_message(field_name, failures))
        return normalized

    def _normalize_model_keys(
        self,
        raw_keys: list[str],
        *,
        field_name: str,
        require_hyperparameter_tuning: bool = False,
    ) -> list[str]:
        normalized: list[str] = []
        failures: list[str] = []
        for raw_key in raw_keys:
            model_key = self._canonical_model_key(raw_key)
            if model_key is None:
                failures.append(raw_key)
                continue
            if require_hyperparameter_tuning:
                catalog = get_model_catalog_entry(model_key)
                if not catalog.supports_hyperparameter_tuning:
                    failures.append(f"{raw_key} lacks hyperparameter_tuning support")
                    continue
            if model_key not in normalized:
                normalized.append(model_key)
        if failures:
            raise ValidationError(self._model_key_error_message(field_name, failures))
        return normalized

    def _canonical_model_key(self, raw_key: str) -> str | None:
        value = raw_key.strip()
        available = set(list_model_keys())
        if value in available:
            return value
        lowered = value.lower()
        if lowered in available:
            return lowered
        for token in self._model_key_alias_tokens(value):
            aliased = self._model_key_aliases.get(token)
            if aliased in available:
                return aliased
        return None

    def _build_model_key_aliases(self) -> dict[str, str]:
        aliases: dict[str, str] = {}
        priorities: dict[str, int] = {}
        for entry in list_model_catalog():
            priority = self._model_alias_priority(entry)
            for token in self._model_entry_alias_tokens(entry):
                if priority < priorities.get(token, 100):
                    aliases[token] = entry.model_key
                    priorities[token] = priority
        aliases.update(_MODEL_KEY_ALIAS_OVERRIDES)
        return aliases

    def _model_entry_alias_tokens(self, entry: ModelCatalogEntry) -> set[str]:
        leaf_key = entry.model_key.split(".", 1)[-1]
        values = {
            entry.model_key,
            entry.model_key.replace(".", "_"),
            leaf_key,
            entry.display_name,
            f"{entry.evaluation_kind.value}_{leaf_key}",
            f"{entry.model_family.value}_{leaf_key}",
            f"{entry.model_task_kind.value}_{leaf_key}",
        }
        if entry.problem_kind is not None:
            values.add(f"{entry.problem_kind.value}_{leaf_key}")
        tokens: set[str] = set()
        for value in values:
            for token in self._model_key_alias_tokens(value):
                tokens.add(token)
                stripped = self._strip_model_alias_suffix(token)
                if stripped:
                    tokens.update(self._model_key_alias_tokens(stripped))
        return tokens

    def _model_alias_priority(self, entry: ModelCatalogEntry) -> int:
        if entry.evaluation_kind is EvaluationKind.REGRESSION:
            return 0
        if entry.evaluation_kind is EvaluationKind.CLASSIFICATION:
            return 1
        task_order = {
            ModelTaskKind.SEGMENTER: 2,
            ModelTaskKind.ANOMALY_SCORER: 3,
            ModelTaskKind.RULE_MINER: 4,
            ModelTaskKind.RECOMMENDER: 5,
        }
        return task_order.get(entry.model_task_kind, 100)

    def _model_key_alias_tokens(self, value: str) -> list[str]:
        token = "".join(char.lower() if char.isalnum() else "_" for char in value).strip("_")
        while "__" in token:
            token = token.replace("__", "_")
        if not token:
            return []
        compact = token.replace("_", "")
        return [token] if compact == token else [token, compact]

    def _strip_model_alias_suffix(self, token: str) -> str:
        parts = token.split("_")
        if len(parts) > 1 and parts[-1] in _MODEL_ALIAS_SUFFIXES:
            return "_".join(parts[:-1])
        return ""

    def _model_key_error_message(self, field_name: str, failures: list[str]) -> str:
        return (
            f"{field_name} contains unsupported model keys: {', '.join(failures)}. "
            "Call model.metadata to inspect available canonical model keys. "
            f"Available keys: {', '.join(list_model_keys())}."
        )

    def _slug(self, value: str) -> str:
        normalized = "".join(char.lower() if char.isalnum() else "-" for char in value).strip("-")
        return normalized or "dataset"
