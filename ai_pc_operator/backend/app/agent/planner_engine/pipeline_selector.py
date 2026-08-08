"""Pipeline Selector — chooses the right execution pipeline for a task set.

A pipeline is a named execution strategy. Different intents benefit from
different pipelines:

  - "sequential": tasks run one after another (default)
  - "approval-gated": pauses for approval before risky tasks
  - "verify-each": verifies each task before continuing
  - "best-effort": continues even if optional tasks fail
  - "research": multi-site research with text extraction
  - "interactive": pauses for user input between steps

The selector picks based on:
  - Intent type
  - Risk level
  - Whether approval is required
  - Whether the goal is reversible
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .task_decomposer import Task


@dataclass
class PipelineSpec:
    """Specification for an execution pipeline."""
    name: str
    strategy: str  # "sequential" | "approval-gated" | "verify-each" | "best-effort" | "research" | "interactive"
    description: str
    config: Dict[str, Any] = field(default_factory=dict)
    applicable_intents: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "strategy": self.strategy,
            "description": self.description,
            "config": self.config,
            "applicable_intents": self.applicable_intents,
        }


class PipelineSelector:
    """Selects the right pipeline for a task set."""

    PIPELINES = {
        "sequential": PipelineSpec(
            name="sequential",
            strategy="sequential",
            description="Run tasks one after another, stop on first failure",
            config={"stop_on_failure": True},
            applicable_intents=["open_app", "list_files", "system_status"],
        ),
        "approval-gated": PipelineSpec(
            name="approval-gated",
            strategy="approval-gated",
            description="Pause for approval before risky tasks",
            config={"approval_before": ["delete", "quarantine", "credential", "download"]},
            applicable_intents=["delete_files", "login", "download_file"],
        ),
        "verify-each": PipelineSpec(
            name="verify-each",
            strategy="verify-each",
            description="Verify each task result before continuing",
            config={"verify_after_each": True},
            applicable_intents=["screen_click", "open_website"],
        ),
        "best-effort": PipelineSpec(
            name="best-effort",
            strategy="best-effort",
            description="Continue even if optional tasks fail",
            config={"continue_on_optional_failure": True},
            applicable_intents=["browser_session"],
        ),
        "research": PipelineSpec(
            name="research",
            strategy="research",
            description="Multi-site research with text extraction",
            config={"max_sites": 10, "extract_text": True, "save_report": True},
            applicable_intents=["research_collect"],
        ),
        "interactive": PipelineSpec(
            name="interactive",
            strategy="interactive",
            description="Pause for user input between steps",
            config={"pause_between_steps": True},
            applicable_intents=["login"],
        ),
    }

    def select(
        self,
        intent: str,
        tasks: List[Task],
        risk_level: int = 0,
        requires_approval: bool = False,
    ) -> PipelineSpec:
        """Select the best pipeline for the given intent and tasks."""
        # 1. Check intent-specific pipelines first
        for pipeline in self.PIPELINES.values():
            if intent in pipeline.applicable_intents:
                return pipeline

        # 2. If approval is required, use approval-gated
        if requires_approval:
            return self.PIPELINES["approval-gated"]

        # 3. If risk is high, use verify-each
        if risk_level >= 3:
            return self.PIPELINES["verify-each"]

        # 4. If any task is optional, use best-effort
        if any(t.optional for t in tasks):
            return self.PIPELINES["best-effort"]

        # 5. Default to sequential
        return self.PIPELINES["sequential"]

    def list_pipelines(self) -> List[str]:
        """List all available pipeline names."""
        return list(self.PIPELINES.keys())

    def get_pipeline(self, name: str) -> Optional[PipelineSpec]:
        """Get a pipeline by name."""
        return self.PIPELINES.get(name)
