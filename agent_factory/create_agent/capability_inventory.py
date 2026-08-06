from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from agent_factory.tooling.builtins.registry import get_builtin_tool_specs
from agent_factory.tooling.spec import ToolSpec


class CapabilityItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    source: str
    description: str = ""
    runtime_inheritable: bool = False


def _default_package_authoring_capabilities() -> list[CapabilityItem]:
    return [
        CapabilityItem(
            id="package_python_tool",
            source="package_authoring",
            description=(
                "Produced agents can gain local Python-script capabilities by authoring package tools "
                "under tools/<tool_id>/ with a manifest, declared schemas, dependencies, resources, and a successful probe."
            ),
            runtime_inheritable=True,
        ),
        CapabilityItem(
            id="package_resource_state_operations",
            source="package_authoring",
            description=(
                "Package tools can read and update declared package resources, state files, knowledge files, "
                "and artifacts through package-relative paths and resource bindings."
            ),
            runtime_inheritable=True,
        ),
        CapabilityItem(
            id="package_api_wrapper_tool",
            source="package_authoring",
            description=(
                "Package tools can wrap user-confirmed external APIs or services when endpoints, credentials, "
                "network needs, dependencies, and approval behavior are declared explicitly."
            ),
            runtime_inheritable=True,
        ),
    ]


class SchedulerCapabilities(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schedule_types: list[str] = Field(default_factory=lambda: ["cron", "interval", "date"])
    target_types: list[str] = Field(default_factory=lambda: ["graph_run", "script_run", "tool_call"])
    feedback_modes: list[str] = Field(default_factory=lambda: ["llm_summary"])
    failure_actions: list[str] = Field(default_factory=lambda: ["pause"])


class CapabilityInventory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = "capability_inventory.v0"
    manufacturing_tools: list[CapabilityItem] = Field(default_factory=list)
    factory_extension_tools: list[CapabilityItem] = Field(default_factory=list)
    runtime_builtin_candidates: list[CapabilityItem] = Field(default_factory=list)
    package_authoring_capabilities: list[CapabilityItem] = Field(default_factory=_default_package_authoring_capabilities)
    inherited_extension_candidates: list[CapabilityItem] = Field(default_factory=list)
    scheduler_capabilities: SchedulerCapabilities = Field(default_factory=SchedulerCapabilities)
    boundary_note: str = (
        "Capabilities not present in confirmed runtime tools, package-authorable runtime capabilities, "
        "inherited extension candidates, or verified package tools are not supported yet. Do not promise them, and do not ask "
        "the user for accounts, tokens, or configuration for them as if they already exist."
    )


def build_capability_inventory(
    *,
    manufacturing_specs: list[ToolSpec],
    extension_specs: list[ToolSpec],
) -> CapabilityInventory:
    manufacturing_tools = [
        _tool_item(spec, source="manufacturing", runtime_inheritable=False)
        for spec in manufacturing_specs
    ]
    factory_extension_tools = [
        _tool_item(spec, source=_extension_source(spec), runtime_inheritable=False)
        for spec in extension_specs
    ]
    runtime_builtin_candidates = [
        _tool_item(spec, source="runtime_builtin_candidate", runtime_inheritable=True)
        for spec in get_builtin_tool_specs()
    ]
    inherited_extension_candidates = [
        _tool_item(spec, source=_extension_source(spec), runtime_inheritable=True)
        for spec in extension_specs
    ]
    return CapabilityInventory(
        manufacturing_tools=_dedupe_items(manufacturing_tools),
        factory_extension_tools=_dedupe_items(factory_extension_tools),
        runtime_builtin_candidates=_dedupe_items(runtime_builtin_candidates),
        inherited_extension_candidates=_dedupe_items(inherited_extension_candidates),
    )


def render_static_capability_inventory(inventory: dict[str, Any] | CapabilityInventory) -> str:
    value = inventory if isinstance(inventory, CapabilityInventory) else CapabilityInventory.model_validate(inventory)
    lines = [
        "Runtime Capability Inventory:",
        "Boundary rule: before asking the user for a resource or account, check this inventory. "
        "If a capability is not listed as a confirmed runtime capability, inherited extension candidate, "
        "or verified package tool, describe it as not yet confirmed/supported instead of asking for its credentials.",
        "",
        "Manufacturing tools (create-agent only; do not expose by default to the produced Agent):",
        *_item_lines(value.manufacturing_tools, empty="none"),
        "",
        "Factory extension tools currently available during manufacturing:",
        *_item_lines(value.factory_extension_tools, empty="none"),
        "",
        "Runtime builtin candidates (usable only if the produced package declares them in contracts/tools.json):",
        *_item_lines(value.runtime_builtin_candidates, empty="none"),
        "",
        "Package-authorable runtime capabilities (supported when implemented, validated, and probed in the produced package):",
        *_item_lines(value.package_authoring_capabilities, empty="none"),
        "",
        "Inherited MCP/Skill extension candidates (candidate only until tools_system chooses to inherit them):",
        *_item_lines(value.inherited_extension_candidates, empty="none"),
        "",
        "Scheduler capabilities:",
        f"- schedule_types={value.scheduler_capabilities.schedule_types}",
        f"- target_types={value.scheduler_capabilities.target_types}",
        f"- feedback_modes={value.scheduler_capabilities.feedback_modes}",
        f"- failure_actions={value.scheduler_capabilities.failure_actions}",
        "",
        f"Boundary note: {value.boundary_note}",
    ]
    return "\n".join(lines)


def _tool_item(spec: ToolSpec, *, source: str, runtime_inheritable: bool) -> CapabilityItem:
    return CapabilityItem(
        id=spec.id,
        source=source,
        description=_compact(spec.description, limit=140),
        runtime_inheritable=runtime_inheritable,
    )


def _extension_source(spec: ToolSpec) -> str:
    if spec.entrypoint.startswith("mcp:"):
        return "mcp_extension_candidate"
    return "skill_or_extension_candidate"


def _dedupe_items(items: list[CapabilityItem]) -> list[CapabilityItem]:
    seen: set[str] = set()
    result: list[CapabilityItem] = []
    for item in sorted(items, key=lambda value: value.id):
        if item.id in seen:
            continue
        seen.add(item.id)
        result.append(item)
    return result


def _item_lines(items: list[CapabilityItem], *, empty: str) -> list[str]:
    if not items:
        return [f"- {empty}"]
    lines: list[str] = []
    for item in items[:24]:
        suffix = _item_suffix(item)
        description = f" | {item.description}" if item.description else ""
        lines.append(f"- {item.id} [{item.source}; {suffix}]{description}")
    if len(items) > 24:
        lines.append(f"- ... {len(items) - 24} more")
    return lines


def _item_suffix(item: CapabilityItem) -> str:
    if item.source == "package_authoring":
        return "runtime capability after package implementation"
    return "runtime-inheritable candidate" if item.runtime_inheritable else "manufacturing only"


def _compact(value: Any, *, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 1)]}…"
