from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


EvolutionTargetSurface = Literal["multi_system", "runtime_blocker"]


@dataclass(frozen=True, slots=True)
class EvolutionTargetPlan:
    surface: EvolutionTargetSurface
    write_strategy: str
    allowed_authoring_actions: list[str]
    target_files: list[str]
    required_first_reads: list[str]
    requires_probe: bool
    validation_scope: str = "full_static"
    runtime_blocker: dict[str, Any] | None = None
    rationale: str = ""
    constraints: list[str] = field(default_factory=list)

    def to_context(self) -> dict[str, Any]:
        return {
            "surface": self.surface,
            "write_strategy": self.write_strategy,
            "allowed_authoring_actions": self.allowed_authoring_actions,
            "target_files": self.target_files,
            "required_first_reads": self.required_first_reads,
            "requires_probe": self.requires_probe,
            "validation_scope": self.validation_scope,
            "runtime_blocker": self.runtime_blocker,
            "rationale": self.rationale,
            "constraints": self.constraints,
        }


def decide_evolution_target(
    *,
    task_analysis: dict[str, Any],
    trace_context: dict[str, Any],
    error_pack: dict[str, Any],
) -> EvolutionTargetPlan:
    affected_systems = _normalized_texts(task_analysis.get("affected_systems"))
    blocker = _runtime_blocker(error_pack=error_pack, trace_context=trace_context)
    if blocker is not None and "runtime_infrastructure" in affected_systems:
        return EvolutionTargetPlan(
            surface="runtime_blocker",
            write_strategy="stop_and_report_runtime_blocker",
            allowed_authoring_actions=[],
            target_files=[],
            required_first_reads=[],
            requires_probe=False,
            runtime_blocker=blocker,
            rationale="Structured evolution analysis identifies a runtime-infrastructure goal that package authoring cannot satisfy.",
            constraints=["Do not modify package files to compensate for RuntimeKernel, local runtime, or model infrastructure failures."],
        )
    capability_changes = _normalized_texts(task_analysis.get("capability_changes"))
    return EvolutionTargetPlan(
        surface="multi_system",
        write_strategy="stage_guided_create_agent_authoring",
        allowed_authoring_actions=[],
        target_files=["package surfaces selected by structured evolution task analysis and current stage guidance"],
        required_first_reads=["agent_package.json", "assembly_spec.json"],
        requires_probe=bool(capability_changes),
        rationale="Evolution uses the shared authoring state machine; structured analysis and stage guidance select coherent package surfaces.",
        constraints=[
            "Preserve systems listed in task_analysis.preserved_systems.",
            "Use model tools, inherited MCP, or verified SkillHub capabilities before authoring a package-owned tool.",
            "When a package tool changes, probe its success path before full validation.",
        ],
    )


def _normalized_texts(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [text for item in value if (text := str(item or "").strip())]


def _error_text(error_pack: dict[str, Any]) -> str:
    parts: list[str] = []
    for item in error_pack.get("error_chain") if isinstance(error_pack.get("error_chain"), list) else []:
        if isinstance(item, dict):
            parts.extend(str(item.get(key) or "") for key in ("message", "where", "type"))
    return " ".join(parts).casefold()


def _runtime_blocker(*, error_pack: dict[str, Any], trace_context: dict[str, Any]) -> dict[str, Any] | None:
    text = f"{_error_text(error_pack)} {trace_context}".casefold()
    markers = ("local_runtime_unavailable", "local.preflight", "runtime_root", "model contract", "response_format")
    if any(marker in text for marker in markers):
        return {"kind": "runtime_infrastructure", "evidence": text[:1000]}
    return None
