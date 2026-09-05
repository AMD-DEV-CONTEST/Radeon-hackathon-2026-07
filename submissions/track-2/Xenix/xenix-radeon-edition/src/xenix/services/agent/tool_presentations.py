from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToolPresentation:
    icon_key: str
    pending_summary: str
    success_summary: str
    failure_action: str
    cancellation_summary: str

    def summary_for(self, status: Any) -> str:
        status_value = getattr(status, "value", status)
        if status_value == "failed":
            return f"Failed to {self.failure_action}"
        if status_value == "cancelled":
            return self.cancellation_summary
        if status_value in {"requested", "running"}:
            return self.pending_summary
        return self.success_summary


DEFAULT_TOOL_PRESENTATION = ToolPresentation(
    icon_key="tool",
    pending_summary="Running tool...",
    success_summary="Ran tool",
    failure_action="run tool",
    cancellation_summary="Cancelled tool run",
)


TOOL_PRESENTATIONS: dict[str, ToolPresentation] = {
    "knowledge.lookup": ToolPresentation(
        icon_key="search",
        pending_summary="Searching knowledge...",
        success_summary="Searched knowledge",
        failure_action="search knowledge",
        cancellation_summary="Cancelled knowledge search",
    ),
    "data.integrate": ToolPresentation(
        icon_key="merge",
        pending_summary="Integrating data...",
        success_summary="Integrated data",
        failure_action="integrate data",
        cancellation_summary="Cancelled data integration",
    ),
    "analysis.profile": ToolPresentation(
        icon_key="analysis",
        pending_summary="Profiling dataset...",
        success_summary="Profiled dataset",
        failure_action="profile dataset",
        cancellation_summary="Cancelled dataset profile",
    ),
    "analysis.graph": ToolPresentation(
        icon_key="analysis",
        pending_summary="Drawing graph...",
        success_summary="Drew graph",
        failure_action="draw graph",
        cancellation_summary="Cancelled graph drawing",
    ),
    "analysis.lambda": ToolPresentation(
        icon_key="analysis",
        pending_summary="Running analysis function...",
        success_summary="Ran analysis function",
        failure_action="run analysis function",
        cancellation_summary="Cancelled analysis function",
    ),
    "data.clean": ToolPresentation(
        icon_key="sparkles",
        pending_summary="Cleaning dataset...",
        success_summary="Cleaned dataset",
        failure_action="clean dataset",
        cancellation_summary="Cancelled dataset cleaning",
    ),
    "data.clean.metadata": ToolPresentation(
        icon_key="list-tree",
        pending_summary="Loading cleaning metadata...",
        success_summary="Loaded cleaning metadata",
        failure_action="load cleaning metadata",
        cancellation_summary="Cancelled cleaning metadata lookup",
    ),
    "data.tokenize": ToolPresentation(
        icon_key="text",
        pending_summary="Tokenizing text...",
        success_summary="Tokenized text",
        failure_action="tokenize text",
        cancellation_summary="Cancelled text tokenization",
    ),
    "data.query": ToolPresentation(
        icon_key="table-search",
        pending_summary="Querying dataset...",
        success_summary="Queried dataset",
        failure_action="query dataset",
        cancellation_summary="Cancelled dataset query",
    ),
    "data.transform": ToolPresentation(
        icon_key="table-transform",
        pending_summary="Transforming dataset...",
        success_summary="Transformed dataset",
        failure_action="transform dataset",
        cancellation_summary="Cancelled dataset transformation",
    ),
    "data.feature.select": ToolPresentation(
        icon_key="columns",
        pending_summary="Binding dataset columns...",
        success_summary="Bound dataset columns",
        failure_action="bind dataset columns",
        cancellation_summary="Cancelled column binding",
    ),
    "model.metadata": ToolPresentation(
        icon_key="list-tree",
        pending_summary="Loading model metadata...",
        success_summary="Loaded model metadata",
        failure_action="load model metadata",
        cancellation_summary="Cancelled model metadata lookup",
    ),
    "model.train": ToolPresentation(
        icon_key="model",
        pending_summary="Training model...",
        success_summary="Trained model",
        failure_action="train model",
        cancellation_summary="Cancelled model training",
    ),
    "model.hyper_train": ToolPresentation(
        icon_key="sliders",
        pending_summary="Tuning model...",
        success_summary="Tuned model",
        failure_action="tune model",
        cancellation_summary="Cancelled model tuning",
    ),
    "model.apply": ToolPresentation(
        icon_key="prediction",
        pending_summary="Applying model...",
        success_summary="Applied model",
        failure_action="apply model",
        cancellation_summary="Cancelled model apply",
    ),
    "model.task.query": ToolPresentation(
        icon_key="list-tree",
        pending_summary="Checking model task...",
        success_summary="Checked model task",
        failure_action="check model task",
        cancellation_summary="Cancelled model task check",
    ),
}


def tool_presentation_for_name(tool_name: str) -> ToolPresentation:
    return TOOL_PRESENTATIONS.get(tool_name, DEFAULT_TOOL_PRESENTATION)
