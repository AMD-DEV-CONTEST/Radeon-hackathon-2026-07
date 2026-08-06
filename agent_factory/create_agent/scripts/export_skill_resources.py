from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from agent_factory.create_agent.models import PackageValidationReport, SystemManufacturingState, initial_system_manufacturing_state
from agent_factory.create_agent.package_scaffold import materialize_empty_agent_package
from agent_factory.runtime_contracts.builtins import (
    default_context_contract,
    default_dependencies_contract,
    default_model_contract,
    default_resources_contract,
    default_scheduler_contract,
    default_tools_contract,
)
from agent_factory.runtime_contracts.schema import AgentPackageManifest
from agent_factory.tooling.package_tool_spec import package_tool_manifest_path, package_tool_source_path


ROOT = Path(__file__).resolve().parents[3]
SKILLS_ROOT = ROOT / "agent_factory" / "create_agent" / "skills"
RESOURCE_IDS = {
    "00-manufacturing-control": "manufacturing_control",
    "01-package-identity-system": "package_identity",
    "02-model-system": "model_system",
    "05-resources-system": "resources_system",
    "06-context-system": "context_system",
    "09-tools-system": "tools_system",
    "10-package-tool-system": "package_tool_system",
    "12-assembly-pattern-system": "assembly_pattern_system",
    "14-scheduler-system": "scheduler_system",
    "15-scheduler-seed-system": "scheduler_seed_system",
    "17-final-validation-repair": "final_validation",
}
CAPABILITY_EXAMPLE_SKILLS = frozenset(
    {
        "10-package-tool-system",
        "12-assembly-pattern-system",
        "15-scheduler-seed-system",
        "17-final-validation-repair",
    }
)
SCAFFOLD_RUN_ID = "factory_run"
SCAFFOLD_USER_INPUT = "Generated RuntimeKernel AgentPackage."
STATIC_EXAMPLE_UPDATED_AT = "2026-01-01T00:00:00+00:00"


def main() -> None:
    scaffold = _scaffold_example_files()
    exports = {
        "00-manufacturing-control": _export(
            title="Manufacturing control state",
            files={".factory/system_state.json": (SystemManufacturingState, _manufacturing_control_example())},
        ),
        "01-package-identity-system": _export(
            title="Agent package manifest",
            files={"agent_package.json": (AgentPackageManifest, scaffold["agent_package.json"])},
        ),
        "02-model-system": _export(
            title="Model and dependency contracts",
            files={
                "contracts/model.json": (type(default_model_contract()), scaffold["contracts/model.json"]),
                "contracts/dependencies.json": (type(default_dependencies_contract()), scaffold["contracts/dependencies.json"]),
            },
        ),
        "05-resources-system": _export(
            title="Resources contract and resource facts",
            files={
                "contracts/resources.json": (type(default_resources_contract()), scaffold["contracts/resources.json"]),
                ".factory/resources.json": (
                    dict,
                    {"version": "resource_facts.v0", "facts": []},
                ),
            },
        ),
        "06-context-system": _export(
            title="Context contract",
            files={"contracts/context.json": (type(default_context_contract()), default_context_contract())},
        ),
        "09-tools-system": _export(
            title="Tools contract",
            files={"contracts/tools.json": (type(default_tools_contract()), default_tools_contract())},
        ),
        "10-package-tool-system": _export(
            title="Package tool authoring call",
            files=_package_tool_example_files(),
        ),
        "12-assembly-pattern-system": _export(
            title="Assembly pattern authoring call",
            files={
                "assembly_pattern_authoring": (dict, _assembly_pattern_authoring_example()),
            },
        ),
        "14-scheduler-system": _export(
            title="Scheduler contract",
            files={"contracts/scheduler.json": (type(default_scheduler_contract()), default_scheduler_contract())},
        ),
        "15-scheduler-seed-system": _export(
            title="Scheduler seed authoring call",
            files={"scheduler_seed_authoring": (dict, _scheduler_seed_capability_example())},
        ),
        "17-final-validation-repair": _export(
            title="Package validation report",
            files={".factory/validation.json": (PackageValidationReport, PackageValidationReport(package_root="."))},
        ),
    }
    for skill_name, payload in exports.items():
        system_id = RESOURCE_IDS[skill_name]
        skill_root = SKILLS_ROOT / skill_name
        _write_json(skill_root / "references" / f"{system_id}.schema.json", payload["schema"])
        example_path = skill_root / "examples" / f"{system_id}.capability.json"
        if skill_name in CAPABILITY_EXAMPLE_SKILLS:
            _write_json(example_path, payload["example"])
        elif example_path.exists():
            example_path.unlink()

def _export(*, title: str, files: dict[str, tuple[type[Any], Any]]) -> dict[str, Any]:
    if len(files) == 1:
        model_or_type, example = next(iter(files.values()))
        return {
            "schema": _schema_for(model_or_type, title=title),
            "example": _dump_example(example),
        }
    return {
        "schema": {
            "type": "object",
            "title": title,
            "description": "System resource map. Each property is the schema for the named package file.",
            "additionalProperties": False,
            "properties": {path: _schema_for(model, title=path) for path, (model, _example) in files.items()},
            "required": list(files),
        },
        "example": {path: _dump_example(example) for path, (_model, example) in files.items()},
    }


def _scheduler_seed_capability_example() -> Any:
    return {
        "purpose": "Create or update scheduler seed configuration through the deterministic authoring tool.",
        "authoring_call": {
            "tool": "create_agent_authoring",
            "arguments": {
                "action": "upsert_scheduler_seed",
                "seed": {
                    "seed_id": "daily_runtime_task",
                    "title": "Daily runtime task",
                    "human_schedule": "Every weekday at 09:00 Asia/Shanghai",
                    "schedule_type": "cron",
                    "schedule_expr": "0 9 * * 1-5",
                    "timezone": "Asia/Shanghai",
                    "target": {
                        "target_type": "graph_run",
                        "payload": {
                            "message": "Run the scheduled agent task using the package's implemented runtime capability."
                        },
                    },
                    "task_content": "Run the package's implemented scheduled task and produce the configured user-facing output.",
                    "enabled_on_apply": True,
                    "failure_policy": {"enabled": True, "max_consecutive_failures": 3, "action": "pause"},
                    "feedback": {"enabled": True, "mode": "llm_summary"},
                    "source_slot_id": "user_confirmed_schedule",
                    "concurrency_policy": "skip",
                    "max_concurrent_runs": 1,
                    "timeout_seconds": 900,
                    "unattended_policy": "deny_if_approval_required",
                },
            },
            "writes": ["contracts/scheduler_seed.json"],
        },
        "rules": [
            "Do not hand-write contracts/scheduler_seed.json during normal production.",
            "Only create scheduler seeds after the schedule and task content are known or confirmed.",
            "Use graph_run when the scheduled task should run the agent itself.",
        ],
    }


def _schema_for(model_or_type: type[Any], *, title: str) -> dict[str, Any]:
    if hasattr(model_or_type, "model_json_schema"):
        schema = model_or_type.model_json_schema()
        schema["title"] = title
        return schema
    if model_or_type is str:
        return {
            "type": "string",
            "title": title,
        }
    if model_or_type is list:
        return {
            "type": "array",
            "title": title,
            "items": {},
        }
    return {
        "type": "object",
        "title": title,
        "additionalProperties": True,
    }


def _dump_example(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", by_alias=True, exclude_none=True)
    return value


def _scaffold_example_files() -> dict[str, Any]:
    with TemporaryDirectory() as tmp:
        package_root = Path(tmp)
        materialize_empty_agent_package(
            package_root,
            factory_run_id=SCAFFOLD_RUN_ID,
            user_input=SCAFFOLD_USER_INPUT,
            pattern_id="react_agent",
        )
        result: dict[str, Any] = {}
        for path in sorted(item for item in package_root.rglob("*") if item.is_file()):
            relative = path.relative_to(package_root).as_posix()
            result[relative] = json.loads(path.read_text(encoding="utf-8"))
        return result


def _package_tool_example_files() -> dict[str, tuple[type[Any], Any]]:
    tool_spec = {
        "id": "package_action",
        "description": "Performs one package-defined runtime action.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
        "output_schema": {
            "type": "object",
            "properties": {"result": {"type": "string"}},
            "required": ["result"],
            "additionalProperties": True,
        },
        "resources": {"workspace_root": "workspace_root"},
        "risk_level": "low",
        "concurrent": True,
    }
    source = (
        "from pathlib import Path\n"
        "import json\n\n\n"
        "def _output_path(resources):\n"
        "    return Path(str(resources[\"workspace_root\"])) / \"package_action.json\"\n\n\n"
        "def run(arguments, resources):\n"
        "    query = str(arguments.get(\"query\") or \"\").strip()\n"
        "    path = _output_path(resources)\n"
        "    path.parent.mkdir(parents=True, exist_ok=True)\n"
        "    history = []\n"
        "    if path.is_file():\n"
        "        history = json.loads(path.read_text(encoding=\"utf-8\"))\n"
        "    history.append({\"query\": query})\n"
        "    path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding=\"utf-8\")\n"
        "    result = query if query else \"No query provided.\"\n"
        "    return {\"result\": result}\n"
    )
    return {
        "package_tool_authoring": (
            dict,
            {
                "purpose": "Create or update a package tool through the deterministic authoring tool.",
                "authoring_call": {
                    "tool": "create_agent_authoring",
                    "arguments": {
                        "action": "upsert_package_tool",
                        "tool_spec": tool_spec,
                        "tool_source": source,
                        "python_requirements": [],
                        "install_timeout_seconds": "<task-appropriate-positive-seconds when dependencies are declared>",
                        "expose_to_nodes": ["answer"],
                    },
                    "writes": [
                        package_tool_manifest_path("package_action"),
                        package_tool_source_path("package_action"),
                        "agent_package.json",
                        "assembly_spec.json",
                        "contracts/tools.json",
                        "contracts/dependencies.json",
                    ],
                },
                "probe_after_write": {
                    "tool": "create_agent_probe_tool",
                    "inspect": {"action": "inspect"},
                    "call": {
                        "action": "call",
                        "tool_id": "package_action",
                        "prompt": "Please run the package action for this sample user request and tell me whether it succeeded.",
                        "tool_goal": "Return a useful final answer after the package action runs and records its state.",
                        "arguments": {"query": "sample request"},
                        "timeout_seconds": "<task-appropriate-positive-seconds>",
                    },
                },
                "rules": [
                    "Do not manually update agent_package.json, assembly_spec.json, contracts/tools.json, or contracts/dependencies.json for package tool registration during normal production.",
                    "Declare external Python dependencies in python_requirements when the source imports third-party packages, and set install_timeout_seconds as the maximum dependency-builder interval without observable output rather than as an ETA.",
                    "Remove stale package tools through create_agent_authoring(action=\"remove_package_tool\", tool_id=...).",
                    "Use resources passed to the tool entrypoint for runtime paths instead of assuming os.getcwd(); generated files should use workspace_root.",
                ],
            },
        ),
    }


def _manufacturing_control_example() -> SystemManufacturingState:
    state = initial_system_manufacturing_state()
    active = state.stages[0]
    next_stage = state.stages[1]
    return state.model_copy(
        update={
            "stages": [active, next_stage],
            "active_focus_id": active.system_id,
            "updated_at": STATIC_EXAMPLE_UPDATED_AT,
        }
    )


def _assembly_pattern_authoring_example() -> dict[str, Any]:
    return {
        "purpose": "Configure the selected built-in runtime pattern through the deterministic authoring tool.",
        "react_agent": {
            "tool": "create_agent_authoring",
            "arguments": {
                "action": "configure_pattern_assembly",
                "pattern_id": "react_agent",
                "prompts": {
                    "answer": "Answer the user using the package knowledge, runtime context, and approved tools. Ask a concise follow-up only when required information is missing.",
                },
                "allowed_tool_ids": ["package_action"],
            },
            "writes": ["agent_package.json", "assembly_spec.json"],
        },
        "plan_and_execute": {
            "tool": "create_agent_authoring",
            "arguments": {
                "action": "configure_pattern_assembly",
                "pattern_id": "plan_and_execute",
                "prompts": {
                    "planner": "Create and maintain an outcome-oriented plan with runtime_plan before execution. Plan steps must describe analysis, verification, construction, or delivery objectives rather than raw tool calls. Put useful tool ids in tool_hints and define acceptance_criteria for each step. Do not call business tools from the planner.",
                    "executor": "Execute the current plan step with package/domain tools first, then update runtime_plan with the result. Use glob, ls, and read for workspace inspection. If read reports a missing file or the path is uncertain, inspect the parent or nearby directory with ls before retrying read with the exact path. Use shell only when available package/runtime tools cannot complete the step, and include fallback_reason when calling it. Use write or edit normally for workspace deliverables.",
                    "casual": "Handle non-main-workflow requests with normal ReAct tool use. Inspect workspace context with tools when needed. If read reports a missing file or the path is uncertain, inspect the parent or nearby directory with ls before retrying read with the exact path. Ask only when discovery cannot identify a safe target, and do not update runtime_plan.",
                    "final_answer": "Summarize the completed plan, use delivery tools if the final artifact still needs generation or verification, and deliver the final user-facing answer.",
                },
                "activation": {
                    "workflow_goal": "complete the user's multi-step workflow",
                    "start_when": "the user supplies the concrete input needed to begin the workflow",
                    "ask_when_missing": "Please provide the input needed to start this workflow.",
                },
                "allowed_tool_ids": ["package_action"],
            },
            "writes": ["agent_package.json", "assembly_spec.json"],
        },
        "rules": [
            "Do not hand-write node_bindings for built-in patterns during normal production.",
            "Use package tool ids only after the tool exists or will be created through create_agent_authoring.",
            "Do not write concrete plan steps into AgentPackage files; plan state is runtime state managed by runtime_plan.",
        ],
    }


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
