"""FastAPI dependency injection providers for workflows."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from workflows.factory import (
    WorkflowFactory,
    get_interview_graph,
    get_report_graph,
    get_workflow_factory,
)
from workflows.interview_graph import InterviewGraph
from workflows.report_graph import ReportGraph


def provide_workflow_factory() -> WorkflowFactory:
    return get_workflow_factory()


def provide_interview_graph() -> InterviewGraph:
    return get_interview_graph()


def provide_report_graph() -> ReportGraph:
    return get_report_graph()


WorkflowFactoryDep = Annotated[WorkflowFactory, Depends(provide_workflow_factory)]
InterviewGraphDep = Annotated[InterviewGraph, Depends(provide_interview_graph)]
ReportGraphDep = Annotated[ReportGraph, Depends(provide_report_graph)]
