from __future__ import annotations

import ast
import json
from pathlib import Path
import platform
import shutil
import sys
from typing import Any

from agent_factory.assembly.schema import AgentAssemblySpec
from agent_factory.create_agent.contract_catalog import base_contract_paths, default_contract_payload
from agent_factory.create_agent.mcp_inheritance import materialize_referenced_factory_mcp
from agent_factory.create_agent.model_tool_access import model_tool_ids_from_package_root
from agent_factory.create_agent.models import (
    KNOWLEDGE_SOURCES_FILE,
    PackageKnowledgeSourceEvidence,
    PackageKnowledgeSourceRecord,
)
from agent_factory.create_agent.stage_sync import sync_authoring_stage
from agent_factory.create_agent.workspace import CreateAgentWorkspace
from agent_factory.environment_system.python_requirements import merge_python_requirements
from agent_factory.runtime_kernel.activation import PLAN_AND_EXECUTE_ACTIVATION_FIELDS
from agent_factory.runtime_contracts.schema import (
    AgentIdentitySpec,
    AgentPackageManifest,
    DependenciesContract,
    ModelContract,
    ResourceDescriptor,
    ResourcesContract,
    SchedulerSeedContract,
    ToolsContract,
)
from agent_factory.scheduler_system.schema import SchedulerSeedPlan
from agent_factory.tooling.envelope import tool_envelope
from agent_factory.tooling.package_tool_spec import (
    package_tool_entrypoint,
    package_tool_directory_path,
    package_tool_manifest_path,
    package_tool_source_path,
    validate_package_tool_source,
)
from agent_factory.tooling.spec import ToolRiskEvaluatorConfig, ToolRiskResult, ToolSpec
from agent_factory.tooling.runtime_resources import PACKAGE_TOOL_SYSTEM_RESOURCE_IDS


CREATE_AGENT_AUTHORING_TOOL_ID = "create_agent_authoring"
DEFAULT_INHERITED_RUNTIME_TOOL_IDS = ("knowledge", "scheduler")
DEFAULT_CASUAL_REACT_TOOL_IDS = ("glob", "ls", "read")
DEFAULT_EXECUTOR_READ_TOOL_IDS = ("glob", "ls", "read")
DEFAULT_EXECUTOR_FALLBACK_TOOL_IDS = ("shell", "write", "edit")
CREATE_AGENT_AUTHORING_ACTIONS = {
    "configure_model_bindings",
    "configure_dependencies",
    "inspect_runtime_environment",
    "reset_contract",
    "materialize_mcp_inheritance",
    "remove_package_tool",
    "remove_knowledge_file",
    "set_identity",
    "configure_pattern_assembly",
    "upsert_knowledge_file",
    "upsert_package_tool",
    "upsert_resources",
    "upsert_scheduler_seed",
}
SUPPORTED_PATTERN_IDS = {"react_agent", "plan_and_execute"}
RESETTABLE_CONTRACT_KEYS = frozenset(base_contract_paths())
REACT_AGENT_PROMPT_KEYS = frozenset({"answer"})
PLAN_AND_EXECUTE_PROMPT_KEYS = frozenset({"planner", "executor", "final_answer"})
PLAN_AND_EXECUTE_OPTIONAL_PROMPT_KEYS = frozenset({"casual"})
PACKAGE_KNOWLEDGE_PURPOSES = ("curated_facts", "domain_reference", "operational_reference")
PACKAGE_KNOWLEDGE_SOURCE_KINDS = (
    "authorized_public_source",
    "project_asset",
    "skill_asset",
    "user_provided",
)


def _prompt_object_schema(keys: frozenset[str], *, optional_keys: frozenset[str] = frozenset()) -> dict[str, Any]:
    all_keys = sorted(keys | optional_keys)
    return {
        "type": "object",
        "properties": {key: {"type": "string", "minLength": 1} for key in all_keys},
        "required": sorted(keys),
        "additionalProperties": False,
    }


def build_create_agent_authoring_tool_spec() -> ToolSpec:
    return ToolSpec(
        id=CREATE_AGENT_AUTHORING_TOOL_ID,
        description=(
            "Inspects the local runtime and deterministically writes coherent AgentPackage authoring increments. "
            "Use inspect_runtime_environment before choosing external dependencies, then use this tool instead of manually "
            "hand-editing cross-file contracts for identity, built-in pattern assembly, package tools, scheduler seeds, "
            "runtime resources, confirmed package knowledge files, or package state. Package knowledge is opt-in and "
            "requires authoritative, distributable source evidence; identity, persona, prompts, and tool instructions "
            "do not belong in knowledge/."
        ),
        entrypoint="agent_factory.create_agent.authoring_tool:run",
        input_schema={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": sorted(CREATE_AGENT_AUTHORING_ACTIONS)},
                "agent": _agent_identity_authoring_schema(),
                "pattern_id": {"type": "string", "enum": sorted(SUPPORTED_PATTERN_IDS)},
                "prompts": {
                    "type": "object",
                    "description": (
                        "Pattern-specific prompt templates. react_agent requires answer. "
                        "plan_and_execute requires planner, executor, and final_answer, and may include casual. "
                        "Unknown keys are rejected."
                    ),
                    "additionalProperties": {"type": "string"},
                },
                "activation": {
                    "type": "object",
                    "properties": {
                        key: {"type": "string", "minLength": 1}
                        for key in sorted(PLAN_AND_EXECUTE_ACTIVATION_FIELDS)
                    },
                    "required": sorted(PLAN_AND_EXECUTE_ACTIVATION_FIELDS),
                    "additionalProperties": False,
                },
                "allowed_tool_ids": {"type": "array", "items": {"type": "string"}},
                "tool_spec": _tool_spec_authoring_schema(),
                "tool_id": {"type": "string"},
                "tool_source": {"type": "string"},
                "python_requirements": {
                    "type": "array",
                    "description": (
                        "Installable Python distribution requirements. Names and markers are normalized; a later "
                        "declaration for the same distribution and marker replaces the earlier constraint."
                    ),
                    "items": {"type": "string"},
                },
                "npm_requirements": {"type": "array", "items": {"type": "string"}},
                "system_binaries": {
                    "type": "array",
                    "description": (
                        "Host commands required by the produced capability. With inspect_runtime_environment these are "
                        "checked without installation; with authoring actions they are recorded as runtime capabilities."
                    ),
                    "items": {"type": "string"},
                },
                "platform_architectures": {"type": "array", "items": {"type": "string", "enum": ["amd64", "arm64"]}},
                "verification_commands": {"type": "array", "items": {"type": "array", "items": {"type": "string"}}},
                "install_timeout_seconds": {
                    "type": "integer",
                    "minimum": 1,
                    "description": (
                        "Maximum dependency-builder interval without observable output or progress, in seconds. "
                        "This is a stall guard rather than an installation ETA."
                    ),
                },
                "expose_to_nodes": {"type": "array", "items": {"type": "string"}},
                "seed": {"type": "object", "additionalProperties": True},
                "resource_descriptors": {
                    "type": "array",
                    "description": (
                        "Deployment-time Resource Descriptors consumed by this capability. For upsert_package_tool, "
                        "descriptors are validated and written as one coherent increment with ToolSpec resource selectors. "
                        "Runtime values and placeholder credentials are never accepted here."
                    ),
                    "items": _resource_descriptor_authoring_schema(),
                },
                "knowledge_path": {
                    "type": "string",
                    "description": "Package-relative target under knowledge/ for confirmed retrievable reference material.",
                },
                "knowledge_content": {"type": "string"},
                "knowledge_purpose": {
                    "type": "string",
                    "enum": list(PACKAGE_KNOWLEDGE_PURPOSES),
                    "description": "Why this material must be retrieved at runtime instead of living in identity, prompts, config, or tools.",
                },
                "knowledge_source": {
                    "type": "object",
                    "description": "Authoritative provenance and redistribution evidence for package-bundled knowledge.",
                    "properties": {
                        "source_kind": {"type": "string", "enum": list(PACKAGE_KNOWLEDGE_SOURCE_KINDS)},
                        "reference": {
                            "type": "string",
                            "minLength": 1,
                            "description": "Concrete user message, repository asset, Skill asset, or authorized public source reference.",
                        },
                        "distributable": {"const": True},
                    },
                    "required": ["source_kind", "reference", "distributable"],
                    "additionalProperties": False,
                },
                "contract_key": {"type": "string", "enum": sorted(RESETTABLE_CONTRACT_KEYS)},
                "bindings": {
                    "type": "object",
                    "description": "Model bindings keyed by runtime role. Use source=model_pool with profile_id or source=env without a profile_id.",
                    "properties": {
                        role: {
                            "type": "object",
                            "properties": {
                                "profile_id": {"type": "string"},
                                "source": {"type": "string", "enum": ["model_pool", "env"]},
                                "selection_source": {"type": "string", "enum": ["auto", "manual"]},
                                "reason": {"type": "string"},
                                "required_capabilities": {"type": "object", "additionalProperties": True},
                                "overrides": {
                                    "type": "object",
                                    "properties": {
                                        "temperature": {"type": "number", "minimum": 0},
                                        "max_output_tokens": {"type": "integer", "minimum": 1},
                                    },
                                    "additionalProperties": False,
                                },
                            },
                            "additionalProperties": False,
                        }
                        for role in ["main", "task", "compression"]
                    },
                    "additionalProperties": False,
                },
                "tool_bindings": {
                    "type": "object",
                    "description": "Auxiliary model tools keyed by the system tool id exposed to the main model or executor.",
                    "additionalProperties": {
                        "type": "object",
                        "properties": {
                            "profile_id": {"type": "string"},
                            "source": {"type": "string", "enum": ["model_pool", "env"]},
                            "capability": {
                                "type": "string",
                                "enum": ["image_input", "image_output", "image_edit", "audio_input", "audio_output"],
                            },
                            "selection_source": {"type": "string", "enum": ["auto", "manual"]},
                            "reason": {"type": "string"},
                            "required_capabilities": {"type": "object", "additionalProperties": True},
                            "description": {"type": "string"},
                            "overrides": {
                                "type": "object",
                                "properties": {
                                    "temperature": {"type": "number", "minimum": 0},
                                    "max_output_tokens": {"type": "integer", "minimum": 1},
                                },
                                "additionalProperties": False,
                            },
                        },
                        "required": ["capability"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["action"],
            "allOf": [
                {"if": {"properties": {"action": {"const": "set_identity"}}}, "then": {"required": ["agent"]}},
                {
                    "if": {"properties": {"action": {"const": "configure_pattern_assembly"}}},
                    "then": {"required": ["pattern_id", "prompts", "allowed_tool_ids"]},
                },
                {
                    "if": {
                        "required": ["pattern_id"],
                        "properties": {
                            "action": {"const": "configure_pattern_assembly"},
                            "pattern_id": {"const": "react_agent"},
                        }
                    },
                    "then": {"properties": {"prompts": _prompt_object_schema(REACT_AGENT_PROMPT_KEYS)}},
                },
                {
                    "if": {
                        "required": ["pattern_id"],
                        "properties": {
                            "action": {"const": "configure_pattern_assembly"},
                            "pattern_id": {"const": "plan_and_execute"},
                        }
                    },
                    "then": {
                        "required": ["activation"],
                        "properties": {
                            "prompts": _prompt_object_schema(
                                PLAN_AND_EXECUTE_PROMPT_KEYS,
                                optional_keys=PLAN_AND_EXECUTE_OPTIONAL_PROMPT_KEYS,
                            )
                        },
                    },
                },
                {
                    "if": {"properties": {"action": {"const": "upsert_package_tool"}}},
                    "then": {"required": ["tool_spec", "tool_source", "python_requirements", "expose_to_nodes"]},
                },
                {
                    "if": {"properties": {"action": {"const": "configure_dependencies"}}},
                    "then": {
                        "anyOf": [
                            {"required": ["python_requirements"]},
                            {"required": ["npm_requirements"]},
                            {"required": ["system_binaries"]},
                            {"required": ["platform_architectures"]},
                            {"required": ["verification_commands"]},
                            {"required": ["install_timeout_seconds"]},
                        ]
                    },
                },
                {"if": {"properties": {"action": {"const": "remove_package_tool"}}}, "then": {"required": ["tool_id"]}},
                {"if": {"properties": {"action": {"const": "remove_knowledge_file"}}}, "then": {"required": ["knowledge_path"]}},
                {"if": {"properties": {"action": {"const": "upsert_scheduler_seed"}}}, "then": {"required": ["seed"]}},
                {"if": {"properties": {"action": {"const": "upsert_resources"}}}, "then": {"required": ["resource_descriptors"]}},
                {
                    "if": {"properties": {"action": {"const": "upsert_knowledge_file"}}},
                    "then": {
                        "required": [
                            "knowledge_path",
                            "knowledge_content",
                            "knowledge_purpose",
                            "knowledge_source",
                        ]
                    },
                },
                {"if": {"properties": {"action": {"const": "reset_contract"}}}, "then": {"required": ["contract_key"]}},
                {
                    "if": {"properties": {"action": {"const": "configure_model_bindings"}}},
                    "then": {"required": ["bindings"]},
                },
            ],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "action": {"type": "string"},
                "changed_files": {"type": "array", "items": {"type": "string"}},
                "summary": {"type": "string"},
                "written": {"type": "object", "additionalProperties": True},
            },
            "required": ["action", "changed_files", "summary"],
            "additionalProperties": True,
        },
        resources={"workspace": "create_agent_workspace"},
        risk_level="medium",
        risk_evaluator=ToolRiskEvaluatorConfig(hard="agent_factory.create_agent.authoring_tool:evaluate_risk"),
        concurrent=False,
    )


def _tool_spec_authoring_schema() -> dict[str, Any]:
    schema_object = {"type": "object", "additionalProperties": True}
    compression_action_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "mode": {"type": "string", "enum": ["structured_json", "deterministic"]},
            "prompt": {"type": "string"},
            "schema": schema_object,
        },
        "additionalProperties": False,
    }
    compression_config_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action_argument": {"type": "string"},
            "actions": {
                "type": "object",
                "additionalProperties": compression_action_schema,
            },
        },
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "description": (
            "Package tool authoring payload. Provide only business-controlled fields: id, description, "
            "input_schema, output_schema, resources, risk_level, concurrent, and optional output_compression. "
            "System-controlled fields such as entrypoint, risk_evaluator, permission_scope, and permission_tags "
            "are generated by create_agent_authoring."
        ),
        "properties": {
            "id": {"type": "string"},
            "description": {"type": "string"},
            "input_schema": schema_object,
            "output_schema": schema_object,
            "resources": {
                "type": "object",
                "description": (
                    "Map local resource names to runtime selectors. Common selectors include artifacts_root, "
                    "workdir_root, runtime_root, package_root, and workspace_root. Values must be strings."
                ),
                "additionalProperties": {"type": "string"},
            },
            "risk_level": {"type": "string", "enum": ["low", "medium", "high"]},
            "concurrent": {"type": "boolean"},
            "output_compression": compression_config_schema,
        },
        "required": [
            "id",
            "description",
            "input_schema",
            "output_schema",
            "resources",
            "risk_level",
            "concurrent",
        ],
        "additionalProperties": False,
    }


def _resource_descriptor_authoring_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "description": (
            "Deployment-time resource contract. value_schema is JSON Schema for values collected after publication; "
            "do not use a schema alias and do not include real or placeholder credentials."
        ),
        "properties": {
            "resource_id": {"type": "string", "minLength": 1},
            "description": {"type": "string"},
            "required": {"type": "boolean"},
            "value_schema": {"type": "object", "additionalProperties": True},
            "default_value": {},
            "secret_fields": {"type": "array", "items": {"type": "string", "minLength": 1}},
            "used_by": {"type": "array", "items": {"type": "string", "minLength": 1}},
            "sandbox_access_expectation": {"type": "string"},
        },
        "required": ["resource_id", "description", "value_schema", "secret_fields", "used_by"],
        "additionalProperties": False,
    }


def _agent_identity_authoring_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "description": (
            "Produced Agent identity. Only id, name, description, and version are accepted. "
            "Do not include author, tags, category, capabilities, tools, metadata, or other descriptive fields here."
        ),
        "properties": {
            "id": {
                "type": "string",
                "minLength": 1,
                "description": "Stable snake_case Agent id.",
            },
            "name": {
                "type": "string",
                "description": "Human-readable Agent name.",
            },
            "description": {
                "type": "string",
                "description": "Short user-facing Agent description.",
            },
            "version": {
                "type": "string",
                "description": "Semantic package version, for example 0.1.0.",
            },
        },
        "required": ["id"],
        "additionalProperties": False,
    }


def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    workspace = _workspace(resources)
    action = str(arguments.get("action") or "").strip()
    if action not in CREATE_AGENT_AUTHORING_ACTIONS:
        raise ValueError(f"unsupported create-agent authoring action: {action}")
    if action == "inspect_runtime_environment":
        result = _inspect_runtime_environment(arguments)
    elif action == "set_identity":
        result = _set_identity(workspace, arguments)
    elif action == "configure_model_bindings":
        result = _configure_model_bindings(workspace, arguments)
    elif action == "configure_pattern_assembly":
        result = _configure_pattern_assembly(workspace, arguments)
    elif action == "upsert_package_tool":
        result = _upsert_package_tool(workspace, arguments)
    elif action == "configure_dependencies":
        result = _configure_dependencies(workspace, arguments)
    elif action == "remove_package_tool":
        result = _remove_package_tool(workspace, arguments)
    elif action == "upsert_scheduler_seed":
        result = _upsert_scheduler_seed(workspace, arguments)
    elif action == "upsert_resources":
        result = _upsert_resources(workspace, arguments)
    elif action == "upsert_knowledge_file":
        result = _upsert_knowledge_file(workspace, arguments)
    elif action == "remove_knowledge_file":
        result = _remove_knowledge_file(workspace, arguments)
    elif action == "reset_contract":
        result = _reset_contract(workspace, arguments)
    elif action == "materialize_mcp_inheritance":
        result = _materialize_mcp_inheritance(workspace)
    else:
        raise ValueError(f"unsupported create-agent authoring action: {action}")
    if result["changed_files"]:
        sync_authoring_stage(workspace, action)
    return tool_envelope(result, evidence={"authoring": result}, summary=result["summary"])


def evaluate_risk(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    del context
    action = str(arguments.get("action") or "").strip()
    if action not in CREATE_AGENT_AUTHORING_ACTIONS:
        return ToolRiskResult(action="deny", risk_level="medium", reasons=["unknown create-agent authoring action"]).model_dump(mode="json")
    if action == "inspect_runtime_environment":
        return ToolRiskResult(
            action="allow",
            risk_level="low",
            reasons=["runtime environment inspection is read-only and does not install host packages"],
            facts={"action": action},
        ).model_dump(mode="json")
    return ToolRiskResult(
        action="allow",
        risk_level="medium",
        reasons=["create-agent authoring performs controlled package-relative writes"],
        facts={"action": action},
    ).model_dump(mode="json")


def _inspect_runtime_environment(arguments: dict[str, Any]) -> dict[str, Any]:
    requested_binaries = _string_list(arguments.get("system_binaries"))
    binary_capabilities: list[dict[str, Any]] = []
    for command in requested_binaries:
        resolved_path = shutil.which(command)
        binary_capabilities.append({
            "command": command,
            "available": resolved_path is not None,
            "resolved_path": resolved_path,
        })
    written = {
        "platform": {
            "system": platform.system().lower(),
            "release": platform.release(),
            "machine": platform.machine().lower(),
        },
        "python": {
            "implementation": platform.python_implementation().lower(),
            "version": platform.python_version(),
            "executable": sys.executable,
        },
        "requested_host_capabilities": binary_capabilities,
        "dependency_management": {
            "python_requirements": "local_shared_pool",
            "npm_requirements": "local_shared_pool",
            "system_binaries": "host_capability_check_only",
            "host_package_installation": "not_available",
        },
    }
    return _result(
        "inspect_runtime_environment",
        [],
        "Inspected the local runtime without changing the host.",
        written=written,
    )


def _set_identity(workspace: CreateAgentWorkspace, arguments: dict[str, Any]) -> dict[str, Any]:
    agent = AgentIdentitySpec.model_validate(_required_dict(arguments, "agent"))
    manifest_path = workspace.root / "agent_package.json"
    assembly_path = workspace.root / "assembly_spec.json"
    manifest = _read_json(manifest_path)
    assembly = _read_json(assembly_path)
    payload = agent.model_dump(mode="json", exclude_none=True)
    manifest["agent"] = payload
    assembly["agent"] = payload
    manifest_payload = AgentPackageManifest.model_validate(manifest).model_dump(mode="json", exclude_none=True)
    assembly_payload = _validated_assembly(assembly)
    _write_json(manifest_path, manifest_payload)
    _write_json(assembly_path, assembly_payload)
    return _result("set_identity", ["agent_package.json", "assembly_spec.json"], f"Updated produced Agent identity: {agent.id}.")


def _configure_pattern_assembly(workspace: CreateAgentWorkspace, arguments: dict[str, Any]) -> dict[str, Any]:
    pattern_id = str(arguments.get("pattern_id") or "").strip()
    if pattern_id not in SUPPORTED_PATTERN_IDS:
        raise ValueError("pattern_id must be react_agent or plan_and_execute")
    prompts = _pattern_prompts(pattern_id=pattern_id, value=arguments.get("prompts"))
    allowed_tool_ids = _runtime_tool_ids_for_assembly(
        workspace,
        _string_list(arguments.get("allowed_tool_ids")),
    )
    manifest_path = workspace.root / "agent_package.json"
    assembly_path = workspace.root / "assembly_spec.json"
    manifest = _read_json(manifest_path)
    assembly = _read_json(assembly_path)
    manifest.setdefault("runtime", {})["pattern_id"] = pattern_id
    assembly.setdefault("runtime", {})["pattern_id"] = pattern_id
    agent_config = assembly.setdefault("runtime", {}).setdefault("agent_config", {})
    if pattern_id == "plan_and_execute":
        agent_config["activation"] = _activation_payload(arguments.get("activation"))
    else:
        agent_config.pop("activation", None)
    if isinstance(manifest.get("agent"), dict):
        assembly["agent"] = manifest["agent"]
    assembly["bindings"] = _standard_bindings(pattern_id=pattern_id, prompts=prompts, allowed_tool_ids=allowed_tool_ids)
    manifest_payload = AgentPackageManifest.model_validate(manifest).model_dump(mode="json", exclude_none=True)
    assembly_payload = _validated_assembly(assembly)
    _write_json(manifest_path, manifest_payload)
    _write_json(assembly_path, assembly_payload)
    written = _configured_pattern_written_summary(
        pattern_id=pattern_id,
        agent_config=agent_config,
        prompts=prompts,
        bindings=assembly_payload.get("bindings") if isinstance(assembly_payload.get("bindings"), dict) else {},
    )
    return _result(
        "configure_pattern_assembly",
        ["agent_package.json", "assembly_spec.json"],
        f"Configured standard {pattern_id} assembly.",
        written=written,
    )


def _activation_payload(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError(
            "activation is required for plan_and_execute and must define workflow_goal, start_when, and ask_when_missing"
        )
    payload: dict[str, str] = {}
    for key in PLAN_AND_EXECUTE_ACTIVATION_FIELDS:
        text = str(value.get(key) or "").strip()
        if not text:
            raise ValueError(f"activation.{key} is required for plan_and_execute")
        payload[key] = text
    return payload


def _pattern_prompts(*, pattern_id: str, value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError("prompts must be an object")
    expected = REACT_AGENT_PROMPT_KEYS if pattern_id == "react_agent" else PLAN_AND_EXECUTE_PROMPT_KEYS
    optional = frozenset() if pattern_id == "react_agent" else PLAN_AND_EXECUTE_OPTIONAL_PROMPT_KEYS
    actual = {str(key) for key in value}
    unknown = sorted(actual - expected - optional)
    missing = sorted(key for key in expected if not str(value.get(key) or "").strip())
    if unknown:
        raise ValueError(
            "unsupported prompt keys for "
            f"{pattern_id}: {', '.join(unknown)}. Expected keys: {', '.join(sorted(expected))}."
        )
    if missing:
        raise ValueError(
            "missing required prompt keys for "
            f"{pattern_id}: {', '.join(missing)}. Expected keys: {', '.join(sorted(expected))}."
        )
    prompts = {key: str(value[key]).strip() for key in sorted(expected)}
    for key in sorted(optional):
        text = str(value.get(key) or "").strip()
        if text:
            prompts[key] = text
    return prompts


def _upsert_package_tool(workspace: CreateAgentWorkspace, arguments: dict[str, Any]) -> dict[str, Any]:
    spec_payload = _required_tool_spec_payload(arguments)
    tool_id = _package_tool_id(str(spec_payload.get("id") or ""))
    spec = ToolSpec.model_validate(spec_payload)
    source = str(arguments.get("tool_source") or "")
    if not source.strip():
        raise ValueError("tool_source is required")
    source_tree = validate_package_tool_source(source)
    resources_contract_path = workspace.root / "contracts" / "resources.json"
    resources_contract = ResourcesContract.model_validate(_read_json(resources_contract_path))
    supplied_descriptors = [
        ResourceDescriptor.model_validate(item)
        for item in (arguments.get("resource_descriptors") if isinstance(arguments.get("resource_descriptors"), list) else [])
    ]
    descriptor_by_id = {
        descriptor.resource_id: descriptor
        for descriptor in [*resources_contract.config.resource_descriptors, *supplied_descriptors]
    }
    _validate_package_tool_resource_contract(tool_id=tool_id, spec=spec, descriptors=descriptor_by_id)
    resources_contract_payload = resources_contract.model_copy(
        update={
            "config": resources_contract.config.model_copy(
                update={"resource_descriptors": list(descriptor_by_id.values())}
            )
        }
    ).model_dump(mode="json")
    python_requirements = _string_list(arguments.get("python_requirements"))
    npm_requirements = _string_list(arguments.get("npm_requirements"))
    system_binaries = _string_list(arguments.get("system_binaries"))
    third_party_imports = _third_party_import_roots(source_tree)
    if third_party_imports and not python_requirements:
        raise ValueError(
            "python_requirements is required before package tool files are written because tool_source imports third-party modules: "
            + ", ".join(sorted(third_party_imports))
        )
    manifest_path = workspace.root / "agent_package.json"
    tools_contract_path = workspace.root / "contracts" / "tools.json"
    dependencies_path = workspace.root / "contracts" / "dependencies.json"
    assembly_path = workspace.root / "assembly_spec.json"
    tool_dir = workspace.root / package_tool_directory_path(tool_id)
    tool_manifest_path = tool_dir / "manifest.json"
    tool_source_path = tool_dir / "tool.py"
    manifest = _read_json(manifest_path)
    _append_unique(manifest.setdefault("tools", []), package_tool_manifest_path(tool_id))
    manifest_payload = AgentPackageManifest.model_validate(manifest).model_dump(mode="json", exclude_none=True)

    tools_contract = _read_json(tools_contract_path)
    tools_config = tools_contract.setdefault("config", {})
    tools_config["package_tools_enabled"] = True
    tools_config.setdefault("builtin_tools_enabled", True)
    tools_config.setdefault("builtin_tool_ids", [])
    tools_contract_payload = ToolsContract.model_validate(tools_contract).model_dump(mode="json")

    dependencies = _read_json(dependencies_path)
    dependency_config = dependencies.setdefault("config", {})
    _merge_dependency_config(
        dependency_config,
        python_requirements=python_requirements,
        npm_requirements=npm_requirements,
        system_binaries=system_binaries,
        platform_architectures=_string_list(arguments.get("platform_architectures")),
        verification_commands=_string_matrix(arguments.get("verification_commands")),
        install_timeout_seconds=arguments.get("install_timeout_seconds"),
    )
    dependencies_payload = DependenciesContract.model_validate(dependencies).model_dump(mode="json")

    assembly = _read_json(assembly_path)
    tools = assembly.setdefault("tools", [])
    _upsert_by_id(tools, spec.model_dump(mode="json"))
    _add_tool_access(assembly, tool_id, expose_to_nodes=_string_list(arguments.get("expose_to_nodes")))
    assembly_payload = _validated_assembly(assembly)
    tool_dir.mkdir(parents=True, exist_ok=True)
    _write_json(tool_manifest_path, spec.model_dump(mode="json"))
    tool_source_path.write_text(source, encoding="utf-8")
    _write_json(manifest_path, manifest_payload)
    _write_json(tools_contract_path, tools_contract_payload)
    _write_json(dependencies_path, dependencies_payload)
    _write_json(assembly_path, assembly_payload)
    if supplied_descriptors:
        _write_json(resources_contract_path, resources_contract_payload)
    changed = [
        package_tool_manifest_path(tool_id),
        package_tool_source_path(tool_id),
        "agent_package.json",
        "contracts/tools.json",
        "contracts/dependencies.json",
        "assembly_spec.json",
        *(["contracts/resources.json"] if supplied_descriptors else []),
    ]
    return _result("upsert_package_tool", changed, f"Upserted package tool {tool_id}.")


def _validate_package_tool_resource_contract(
    *,
    tool_id: str,
    spec: ToolSpec,
    descriptors: dict[str, ResourceDescriptor],
) -> None:
    package_resource_ids = {
        selector.split(".", 1)[0]
        for selector in spec.resources.values()
        if selector.split(".", 1)[0] not in PACKAGE_TOOL_SYSTEM_RESOURCE_IDS
    }
    undeclared = sorted(package_resource_ids - set(descriptors))
    if undeclared:
        raise ValueError(
            "package tool resource selectors require matching Resource Descriptors before any files are written: "
            + ", ".join(undeclared)
        )
    missing_usage = sorted(
        resource_id
        for resource_id in package_resource_ids
        if tool_id not in descriptors[resource_id].used_by
    )
    if missing_usage:
        raise ValueError(
            f"Resource Descriptors consumed by package tool {tool_id!r} must include that tool id in used_by: "
            + ", ".join(missing_usage)
        )


def _required_tool_spec_payload(arguments: dict[str, Any]) -> dict[str, Any]:
    payload = _required_dict(arguments, "tool_spec")
    system_fields = sorted(
        field
        for field in {
            "entrypoint",
            "risk_evaluator",
            "permission_scope",
            "permission_tags",
        }
        if field in payload
    )
    if system_fields:
        raise ValueError(
            "tool_spec contains system-controlled fields generated by create_agent_authoring: "
            + ", ".join(system_fields)
        )
    required_fields = {
        "id",
        "description",
        "input_schema",
        "output_schema",
        "resources",
        "risk_level",
        "concurrent",
    }
    missing = sorted(field for field in required_fields if field not in payload)
    if missing:
        raise ValueError(
            "tool_spec must include package tool business fields: " + ", ".join(sorted(required_fields))
            + f". Missing: {', '.join(missing)}"
        )
    input_schema = payload.get("input_schema")
    if isinstance(input_schema, dict):
        misplaced = _misplaced_tool_spec_fields(input_schema)
        if misplaced:
            raise ValueError(
                "ToolSpec fields must be top-level tool_spec fields, not nested inside tool_spec.input_schema or "
                "tool_spec.input_schema.properties: "
                + ", ".join(misplaced)
            )
    resources = payload.get("resources")
    if isinstance(resources, dict):
        non_string_resources = sorted(
            str(key)
            for key, value in resources.items()
            if not isinstance(value, str) or not value.strip()
        )
        if non_string_resources:
            raise ValueError(
                "tool_spec.resources must map local resource names to string runtime selectors, "
                "for example {'artifacts_root': 'artifacts_root'}. Invalid keys: "
                + ", ".join(non_string_resources)
            )
    tool_id = _package_tool_id(str(payload.get("id") or ""))
    normalized = dict(payload)
    normalized["entrypoint"] = package_tool_entrypoint(tool_id)
    normalized["risk_evaluator"] = {"llm_mode": "disabled"}
    normalized["permission_scope"] = "package"
    normalized.setdefault("permission_tags", [])
    return normalized


def _misplaced_tool_spec_fields(input_schema: dict[str, Any]) -> list[str]:
    reserved = {
        "entrypoint",
        "output_schema",
        "resources",
        "risk_level",
        "risk_evaluator",
        "concurrent",
        "output_compression",
    }
    misplaced = set(input_schema) & reserved
    properties = input_schema.get("properties")
    if isinstance(properties, dict):
        misplaced.update(set(properties) & reserved)
    return sorted(misplaced)


def _configure_dependencies(workspace: CreateAgentWorkspace, arguments: dict[str, Any]) -> dict[str, Any]:
    dependencies_path = workspace.root / "contracts" / "dependencies.json"
    dependencies = _read_json(dependencies_path)
    dependency_config = dependencies.setdefault("config", {})
    _merge_dependency_config(
        dependency_config,
        python_requirements=_string_list(arguments.get("python_requirements")),
        npm_requirements=_string_list(arguments.get("npm_requirements")),
        system_binaries=_string_list(arguments.get("system_binaries")),
        platform_architectures=_string_list(arguments.get("platform_architectures")),
        verification_commands=_string_matrix(arguments.get("verification_commands")),
        install_timeout_seconds=arguments.get("install_timeout_seconds"),
    )
    dependencies_payload = DependenciesContract.model_validate(dependencies).model_dump(mode="json")
    _write_json(dependencies_path, dependencies_payload)
    return _result(
        "configure_dependencies",
        ["contracts/dependencies.json"],
        "Updated package dependency contract.",
        written={"dependencies": dependencies_payload.get("config", {})},
    )


def _configure_model_bindings(workspace: CreateAgentWorkspace, arguments: dict[str, Any]) -> dict[str, Any]:
    bindings = _required_dict(arguments, "bindings")
    if "tool_bindings" in bindings:
        raise ValueError("tool_bindings must be passed as a top-level create_agent_authoring argument, not inside bindings")
    tool_bindings = arguments.get("tool_bindings")
    if tool_bindings is not None and not isinstance(tool_bindings, dict):
        raise ValueError("tool_bindings must be an object")
    contract = ModelContract.model_validate(
        {
            "type": "model",
            "version": "model_contract.v1",
            "enabled": True,
            "config": {
                "bindings": bindings,
                "tool_bindings": tool_bindings or {},
            },
        }
    )
    payload = contract.model_dump(mode="json")
    path = workspace.root / "contracts" / "model.json"
    _write_json(path, payload)
    changed_files = ["contracts/model.json"]
    assembly_path = workspace.root / "assembly_spec.json"
    if assembly_path.is_file():
        assembly = _read_json(assembly_path)
        if _model_tools_need_assembly_sync(assembly):
            _add_runtime_model_tool_access(assembly, sorted(contract.config.tool_bindings))
            assembly_payload = _validated_assembly(assembly)
            _write_json(assembly_path, assembly_payload)
            changed_files.append("assembly_spec.json")
    return _result(
        "configure_model_bindings",
        changed_files,
        "Updated model pool profile bindings.",
        written={"model": payload.get("config", {})},
    )


def _merge_dependency_config(
    config: dict[str, Any],
    *,
    python_requirements: list[str],
    npm_requirements: list[str],
    system_binaries: list[str],
    platform_architectures: list[str],
    verification_commands: list[list[str]],
    install_timeout_seconds: Any,
) -> None:
    requirements = merge_python_requirements(
        _dependency_list(config, "python_requirements"),
        python_requirements,
    )
    config["python_requirements"] = requirements
    npm_packages = _dependency_list(config, "npm_requirements")
    for requirement in npm_requirements:
        _append_unique(npm_packages, requirement)
    binaries = _dependency_list(config, "system_binaries")
    for binary in system_binaries:
        _append_unique(binaries, binary)
    if platform_architectures:
        config["platform_architectures"] = platform_architectures
    if verification_commands:
        config["verification_commands"] = verification_commands
    if install_timeout_seconds is not None:
        config["install_timeout_seconds"] = _positive_int(install_timeout_seconds, "install_timeout_seconds")
    if (requirements or npm_packages) and config.get("install_timeout_seconds") is None:
        raise ValueError(
            "install_timeout_seconds is required when declaring Python or npm dependencies; "
            "estimate a task-appropriate positive number of seconds."
        )


def _dependency_list(config: dict[str, Any], key: str) -> list[Any]:
    value = config.get(key)
    if not isinstance(value, list):
        value = []
        config[key] = value
    return value


def _string_matrix(value: Any) -> list[list[str]]:
    if not isinstance(value, list):
        return []
    return [row for row in (_string_list(item) for item in value) if row]


def _remove_package_tool(workspace: CreateAgentWorkspace, arguments: dict[str, Any]) -> dict[str, Any]:
    tool_id = _package_tool_id(str(arguments.get("tool_id") or ""))
    manifest_path = workspace.root / "agent_package.json"
    assembly_path = workspace.root / "assembly_spec.json"
    manifest = _read_json(manifest_path)
    assembly = _read_json(assembly_path)
    manifest["tools"] = [
        item
        for item in (manifest.get("tools") if isinstance(manifest.get("tools"), list) else [])
        if str(item) != package_tool_manifest_path(tool_id)
    ]
    assembly["tools"] = [
        item
        for item in (assembly.get("tools") if isinstance(assembly.get("tools"), list) else [])
        if not (isinstance(item, dict) and str(item.get("id") or "") == tool_id)
    ]
    if tool_id not in model_tool_ids_from_package_root(workspace.root):
        _remove_tool_access(assembly, tool_id)
    manifest_payload = AgentPackageManifest.model_validate(manifest).model_dump(mode="json", exclude_none=True)
    assembly_payload = _validated_assembly(assembly)
    tool_dir = workspace.root / package_tool_directory_path(tool_id)
    _write_json(manifest_path, manifest_payload)
    _write_json(assembly_path, assembly_payload)
    if tool_dir.exists():
        shutil.rmtree(tool_dir)
    return _result(
        "remove_package_tool",
        ["agent_package.json", "assembly_spec.json", package_tool_directory_path(tool_id)],
        f"Removed package tool {tool_id}.",
    )


def _third_party_import_roots(tree: ast.AST) -> set[str]:
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(_import_root(alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                continue
            imports.add(_import_root(node.module or ""))
    return {name for name in imports if _requires_declared_dependency(name)}


def _import_root(value: str) -> str:
    return value.split(".", 1)[0].strip()


def _requires_declared_dependency(name: str) -> bool:
    if not name:
        return False
    if name in sys.stdlib_module_names:
        return False
    if name in {"agent_factory", "tools"}:
        return False
    return True


def _upsert_scheduler_seed(workspace: CreateAgentWorkspace, arguments: dict[str, Any]) -> dict[str, Any]:
    seed = SchedulerSeedPlan.model_validate(_required_dict(arguments, "seed"))
    path = workspace.root / "contracts" / "scheduler_seed.json"
    contract = _read_json(path)
    config = contract.setdefault("config", {})
    seeds = config.setdefault("seeds", [])
    _upsert_by_key(seeds, seed.model_dump(mode="json"), key="seed_id")
    contract["type"] = "scheduler_seed"
    contract["version"] = "scheduler_seed_contract.v0"
    contract.setdefault("enabled", True)
    _write_json(path, SchedulerSeedContract.model_validate(contract).model_dump(mode="json"))
    return _result("upsert_scheduler_seed", ["contracts/scheduler_seed.json"], f"Upserted scheduler seed {seed.seed_id}.")


def _upsert_resources(workspace: CreateAgentWorkspace, arguments: dict[str, Any]) -> dict[str, Any]:
    descriptors = [
        ResourceDescriptor.model_validate(item).model_dump(mode="json")
        for item in (arguments.get("resource_descriptors") if isinstance(arguments.get("resource_descriptors"), list) else [])
    ]
    if not descriptors:
        raise ValueError("resource_descriptors must contain at least one deployment-time descriptor")
    contract_path = workspace.root / "contracts" / "resources.json"
    contract = _read_json(contract_path)
    config = contract.setdefault("config", {})
    descriptor_list = config.setdefault("resource_descriptors", [])
    for descriptor in descriptors:
        _upsert_by_key(descriptor_list, descriptor, key="resource_id")
    contract_payload = ResourcesContract.model_validate(contract).model_dump(mode="json")
    _write_json(contract_path, contract_payload)
    return _result("upsert_resources", ["contracts/resources.json"], "Upserted package resource descriptors.")


def _upsert_knowledge_file(workspace: CreateAgentWorkspace, arguments: dict[str, Any]) -> dict[str, Any]:
    relative_path = _knowledge_relative_path(str(arguments.get("knowledge_path") or ""))
    content = str(arguments.get("knowledge_content") or "")
    if not content.strip():
        raise ValueError("knowledge_content is required")
    source = PackageKnowledgeSourceEvidence.model_validate(_required_dict(arguments, "knowledge_source"))
    record = PackageKnowledgeSourceRecord.model_validate(
        {
            "knowledge_path": relative_path,
            "purpose": str(arguments.get("knowledge_purpose") or ""),
            "source": source,
        }
    )
    registry = workspace.read_knowledge_sources()
    records = [item for item in registry.records if item.knowledge_path != relative_path]
    target = workspace.root / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    workspace.write_knowledge_sources(registry.model_copy(update={"records": [*records, record]}))
    return _result(
        "upsert_knowledge_file",
        [relative_path, KNOWLEDGE_SOURCES_FILE],
        f"Upserted sourced package knowledge file {relative_path}.",
        knowledge_source=record.model_dump(mode="json"),
    )


def _remove_knowledge_file(workspace: CreateAgentWorkspace, arguments: dict[str, Any]) -> dict[str, Any]:
    relative_path = _knowledge_relative_path(str(arguments.get("knowledge_path") or ""))
    registry = workspace.read_knowledge_sources()
    remaining_records = [record for record in registry.records if record.knowledge_path != relative_path]
    target = workspace.root / relative_path
    if target.is_file():
        target.unlink()
        _remove_empty_knowledge_directories(target.parent, root=workspace.root / "knowledge")
    if remaining_records:
        workspace.write_knowledge_sources(registry.model_copy(update={"records": remaining_records}))
    elif workspace.knowledge_sources_path.exists():
        workspace.knowledge_sources_path.unlink()
    return _result(
        "remove_knowledge_file",
        [relative_path, KNOWLEDGE_SOURCES_FILE],
        f"Removed package knowledge file {relative_path} and its source evidence.",
    )


def _remove_empty_knowledge_directories(path: Path, *, root: Path) -> None:
    current = path
    while current != root and root in current.parents:
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent


def _reset_contract(workspace: CreateAgentWorkspace, arguments: dict[str, Any]) -> dict[str, Any]:
    contract_key = str(arguments.get("contract_key") or "").strip()
    if contract_key not in RESETTABLE_CONTRACT_KEYS:
        raise ValueError("contract_key is not a resettable scaffold contract")
    relative = f"contracts/{contract_key}.json"
    _write_json(workspace.root / relative, default_contract_payload(contract_key))
    return _result("reset_contract", [relative], f"Reset scaffold contract {contract_key}.")


def _materialize_mcp_inheritance(workspace: CreateAgentWorkspace) -> dict[str, Any]:
    result = materialize_referenced_factory_mcp(workspace.root)
    changed_files = list(result.changed_files)
    inherited = ", ".join(result.inherited_tool_ids) if result.inherited_tool_ids else "none"
    summary = f"Materialized inherited MCP extension config for referenced tools: {inherited}."
    if not changed_files and not result.inherited_tool_ids:
        summary = "No referenced factory MCP candidates require inheritance materialization."
    return {
        "action": "materialize_mcp_inheritance",
        "changed_files": changed_files,
        "summary": summary,
        "mcp_inheritance": result.model_dump(),
    }


def _standard_bindings(*, pattern_id: str, prompts: dict[str, Any], allowed_tool_ids: list[str]) -> dict[str, Any]:
    inherited_tool_ids = _default_inherited_tool_ids(allowed_tool_ids)
    if pattern_id == "react_agent":
        answer_prompt = str(prompts["answer"])
        return {
            "services": [],
            "node_bindings": [
                _prompt_binding("answer", "cognitive.answer", "answer_prompt", answer_prompt),
                _tool_access_binding("answer", "cognitive.answer", inherited_tool_ids),
                _model_binding("answer", "cognitive.answer", "answer_prompt"),
            ],
            "hooks": [],
        }
    planner_prompt = str(prompts["planner"])
    executor_prompt = str(prompts["executor"])
    final_prompt = str(prompts["final_answer"])
    casual_prompt = str(
        prompts.get("casual")
        or "Handle non-main-workflow user requests with normal ReAct tool use. Use available tools to inspect workspace context when needed. If read reports a missing file or the path is uncertain, inspect the parent or nearby directory with ls before retrying read with the exact path. Ask a concise clarification only when tool/context discovery cannot identify a safe target, and do not create or update runtime_plan."
    )
    executor_tools = _unique_strings(
        [
            "runtime_plan",
            *[tool_id for tool_id in inherited_tool_ids if tool_id != "runtime_plan"],
            *DEFAULT_EXECUTOR_READ_TOOL_IDS,
            *DEFAULT_EXECUTOR_FALLBACK_TOOL_IDS,
        ]
    )
    final_answer_tools = _unique_strings([tool_id for tool_id in executor_tools if tool_id != "runtime_plan"])
    planner_tools = ["runtime_plan"]
    casual_tools = _unique_strings(
        [
            *DEFAULT_CASUAL_REACT_TOOL_IDS,
            *[tool_id for tool_id in inherited_tool_ids if tool_id != "runtime_plan"],
        ]
    )
    return {
        "services": [],
        "node_bindings": [
            _prompt_binding("planner", "cognitive.answer", "planner_prompt", planner_prompt),
            _tool_access_binding("planner", "cognitive.answer", planner_tools),
            _model_binding("planner", "cognitive.answer", "planner_prompt"),
            _prompt_binding("executor", "cognitive.answer", "executor_prompt", executor_prompt),
            _tool_access_binding("executor", "cognitive.answer", executor_tools),
            _model_binding("executor", "cognitive.answer", "executor_prompt"),
            _prompt_binding("casual_react", "cognitive.answer", "casual_react_prompt", casual_prompt),
            _tool_access_binding("casual_react", "cognitive.answer", casual_tools),
            _model_binding("casual_react", "cognitive.answer", "casual_react_prompt"),
            _prompt_binding("final_answer", "cognitive.answer", "final_answer_prompt", final_prompt),
            _tool_access_binding("final_answer", "cognitive.answer", final_answer_tools),
            _model_binding("final_answer", "cognitive.answer", "final_answer_prompt"),
        ],
        "hooks": [],
    }


def _runtime_tool_ids_for_assembly(workspace: CreateAgentWorkspace, allowed_tool_ids: list[str]) -> list[str]:
    return _unique_strings([*allowed_tool_ids, *sorted(model_tool_ids_from_package_root(workspace.root))])


def _model_tools_need_assembly_sync(assembly: dict[str, Any]) -> bool:
    pattern_id = str((assembly.get("runtime") if isinstance(assembly.get("runtime"), dict) else {}).get("pattern_id") or "")
    if pattern_id not in SUPPORTED_PATTERN_IDS:
        return False
    bindings = assembly.get("bindings") if isinstance(assembly.get("bindings"), dict) else {}
    node_bindings = bindings.get("node_bindings")
    return isinstance(node_bindings, list) and any(
        isinstance(binding, dict) and binding.get("binding_type") == "tool_access"
        for binding in node_bindings
    )


def _add_runtime_model_tool_access(assembly: dict[str, Any], tool_ids: list[str]) -> None:
    pattern_id = str((assembly.get("runtime") if isinstance(assembly.get("runtime"), dict) else {}).get("pattern_id") or "react_agent")
    nodes = _execution_tool_nodes(pattern_id)
    for tool_id in _unique_strings(tool_ids):
        _add_tool_access(assembly, tool_id, expose_to_nodes=nodes)


def _execution_tool_nodes(pattern_id: str) -> list[str]:
    if pattern_id == "plan_and_execute":
        return ["executor", "casual_react", "final_answer"]
    return ["answer"]


def _prompt_binding(node_id: str, impl: str, prompt_id: str, template: str) -> dict[str, Any]:
    return {
        "binding_id": f"{node_id}_prompt",
        "binding_type": "prompt",
        "target": {"node_id": node_id, "impl": impl},
        "payload": {"prompt_id": prompt_id, "template": template, "variables": []},
    }


def _tool_access_binding(node_id: str, impl: str, allowed_tool_ids: list[str]) -> dict[str, Any]:
    return {
        "binding_id": f"{node_id}_tool_access",
        "binding_type": "tool_access",
        "target": {"node_id": node_id, "impl": impl},
        "payload": {"allowed_tool_ids": _unique_strings(allowed_tool_ids), "approval_policy": "allow_below_high"},
    }


def _default_inherited_tool_ids(allowed_tool_ids: list[str]) -> list[str]:
    return _unique_strings([*DEFAULT_INHERITED_RUNTIME_TOOL_IDS, *allowed_tool_ids])


def _configured_pattern_written_summary(
    *,
    pattern_id: str,
    agent_config: dict[str, Any],
    prompts: dict[str, str],
    bindings: dict[str, Any],
) -> dict[str, Any]:
    return {
        "pattern_id": pattern_id,
        "activation": agent_config.get("activation") if isinstance(agent_config.get("activation"), dict) else None,
        "prompts": prompts,
        "tool_access": _tool_access_summary(bindings),
    }


def _tool_access_summary(bindings: dict[str, Any]) -> dict[str, list[str]]:
    summary: dict[str, list[str]] = {}
    node_bindings = bindings.get("node_bindings") if isinstance(bindings.get("node_bindings"), list) else []
    for binding in node_bindings:
        if not isinstance(binding, dict) or binding.get("binding_type") != "tool_access":
            continue
        target = binding.get("target") if isinstance(binding.get("target"), dict) else {}
        payload = binding.get("payload") if isinstance(binding.get("payload"), dict) else {}
        node_id = str(target.get("node_id") or "")
        if not node_id:
            continue
        summary[node_id] = _unique_strings(payload.get("allowed_tool_ids") if isinstance(payload.get("allowed_tool_ids"), list) else [])
    return summary


def _model_binding(node_id: str, impl: str, prompt_id: str) -> dict[str, Any]:
    return {
        "binding_id": f"{node_id}_model_operation",
        "binding_type": "model_operation",
        "target": {"node_id": node_id, "impl": impl},
        "payload": {
            "operation": "tool_bound_chat",
            "model_role": "main",
            "output_schema": {"type": "object", "additionalProperties": True},
            "write_target": {"section": "context"},
            "max_attempts": 3,
            "prompt_id": prompt_id,
        },
    }


def _add_tool_access(assembly: dict[str, Any], tool_id: str, *, expose_to_nodes: list[str]) -> None:
    pattern_id = str((assembly.get("runtime") or {}).get("pattern_id") or "react_agent")
    default_nodes = ["executor", "casual_react"] if pattern_id == "plan_and_execute" else ["answer"]
    node_ids = expose_to_nodes or default_nodes
    if pattern_id == "plan_and_execute":
        valid_nodes = {"executor", "casual_react", "final_answer"}
        invalid_nodes = sorted({node_id for node_id in node_ids if node_id not in valid_nodes})
        if invalid_nodes:
            raise ValueError(
                "plan_and_execute tools can only be exposed to executor, casual_react, or final_answer; "
                f"invalid expose_to_nodes: {', '.join(invalid_nodes)}"
            )
    bindings = assembly.setdefault("bindings", {}).setdefault("node_bindings", [])
    impl_by_node = {
        "answer": "cognitive.answer",
        "planner": "cognitive.answer",
        "executor": "cognitive.answer",
        "casual_react": "cognitive.answer",
        "final_answer": "cognitive.answer",
    }
    for node_id in node_ids:
        binding = _find_tool_access_binding(bindings, node_id)
        if binding is None:
            binding = _tool_access_binding(node_id, impl_by_node.get(node_id, "cognitive.answer"), [])
            bindings.append(binding)
        allowed = binding.setdefault("payload", {}).setdefault("allowed_tool_ids", [])
        _append_unique(allowed, tool_id)
        binding["payload"]["allowed_tool_ids"] = _unique_strings(allowed)


def _find_tool_access_binding(bindings: list[Any], node_id: str) -> dict[str, Any] | None:
    for binding in bindings:
        if not isinstance(binding, dict) or binding.get("binding_type") != "tool_access":
            continue
        target = binding.get("target") if isinstance(binding.get("target"), dict) else {}
        if target.get("node_id") == node_id:
            return binding
    return None


def _remove_tool_access(assembly: dict[str, Any], tool_id: str) -> None:
    bindings = assembly.setdefault("bindings", {}).setdefault("node_bindings", [])
    for binding in bindings:
        if not isinstance(binding, dict) or binding.get("binding_type") != "tool_access":
            continue
        payload = binding.setdefault("payload", {})
        allowed = payload.get("allowed_tool_ids")
        if isinstance(allowed, list):
            payload["allowed_tool_ids"] = [item for item in _unique_strings(allowed) if item != tool_id]


def _workspace(resources: dict[str, Any]) -> CreateAgentWorkspace:
    raw = resources.get("workspace")
    if isinstance(raw, str):
        return CreateAgentWorkspace(raw)
    if isinstance(raw, dict) and isinstance(raw.get("root"), str):
        return CreateAgentWorkspace(raw["root"])
    raise ValueError("create_agent workspace resource is missing")


def _required_dict(arguments: dict[str, Any], key: str) -> dict[str, Any]:
    value = arguments.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"{key} must be an object")
    return value


def _positive_int(value: Any, key: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{key} must be a positive integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be a positive integer") from exc
    if parsed < 1:
        raise ValueError(f"{key} must be a positive integer")
    return parsed


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return payload


def _knowledge_relative_path(value: str) -> str:
    requested = Path(value.strip())
    if requested.is_absolute() or not value.strip():
        raise ValueError("knowledge_path must be a non-empty package-relative path under knowledge/")
    normalized = requested.as_posix()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    if normalized == "knowledge":
        raise ValueError("knowledge_path must identify a file under knowledge/")
    if normalized.startswith("knowledge/"):
        relative = normalized
    else:
        relative = f"knowledge/{normalized}"
    resolved = Path(relative)
    if any(part in {"", ".", ".."} for part in resolved.parts):
        raise ValueError("knowledge_path must not contain empty, current, or parent directory segments")
    return resolved.as_posix()


def _package_tool_id(value: str) -> str:
    tool_id = value.strip()
    if not tool_id:
        raise ValueError("tool_id is required")
    path = Path(tool_id)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("tool_id must be a simple package tool id")
    if "/" in tool_id or "\\" in tool_id:
        raise ValueError("tool_id must not contain path separators")
    return tool_id


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _validated_assembly(payload: dict[str, Any]) -> dict[str, Any]:
    return AgentAssemblySpec.model_validate(payload).model_dump(mode="json", exclude_none=True)


def _append_unique(values: list[Any], value: str) -> None:
    if value and value not in values:
        values.append(value)


def _unique_strings(values: list[Any]) -> list[str]:
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _string_list(value: Any) -> list[str]:
    return _unique_strings(value if isinstance(value, list) else [])


def _upsert_by_id(values: list[Any], payload: dict[str, Any]) -> None:
    _upsert_by_key(values, payload, key="id")


def _upsert_by_key(values: list[Any], payload: dict[str, Any], *, key: str) -> None:
    target = str(payload.get(key) or "")
    for index, item in enumerate(values):
        if isinstance(item, dict) and str(item.get(key) or "") == target:
            values[index] = payload
            return
    values.append(payload)


def _result(action: str, changed_files: list[str], summary: str, **extra: Any) -> dict[str, Any]:
    return {"action": action, "changed_files": changed_files, "summary": summary, **extra}
