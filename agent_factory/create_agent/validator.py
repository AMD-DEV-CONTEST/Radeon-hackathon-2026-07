from __future__ import annotations

import ast
import json
from pathlib import Path
import py_compile
import sys
from typing import Any

from pydantic import ValidationError
from ruamel.yaml import YAML

from agent_factory.assembly.compiler import AgentAssemblyCompiler
from agent_factory.create_agent.contract_catalog import system_resources
from agent_factory.create_agent.mcp_inheritance import factory_mcp_tool_ids, materialized_package_mcp_tool_ids
from agent_factory.create_agent.model_tool_access import model_tool_ids_from_contract
from agent_factory.create_agent.validation_state import package_fingerprint, package_tool_digest
from agent_factory.create_agent.models import (
    KNOWLEDGE_SOURCES_FILE,
    PackageKnowledgeSourceRegistry,
    PackageToolProbeState,
    PackageValidationIssue,
    PackageValidationReport,
)
from agent_factory.environment_system import EnvironmentResolutionError, EnvironmentResolver
from agent_factory.runtime_contracts import AgentPackageLoader, RuntimeBuildPlanner
from agent_factory.runtime_contracts.builtins import default_runtime_contract_registry
from agent_factory.runtime_contracts.schema import (
    AgentPackageManifest,
    DependenciesContract,
    PACKAGE_INFRASTRUCTURE_CONTRACTS,
    REQUIRED_AGENT_PACKAGE_CONTRACTS,
    SchedulerSeedContract,
    ResourcesContract,
    ToolsContract,
)
from agent_factory.runtime_kernel.kernel import RuntimeKernelFacade
from agent_factory.runtime_kernel.persistence import LangGraphCheckpointerConfig, LangGraphStoreConfig
from agent_factory.runtime_kernel.activation import normalize_plan_and_execute_activation
from agent_factory.runtime_kernel.planning import PLAN_AND_EXECUTE_PATTERN_ID, RUNTIME_PLAN_TOOL_ID
from agent_factory.tooling.builtins.registry import get_builtin_tool_ids
from agent_factory.tooling.package_tool_spec import (
    package_tool_directory_path,
    package_tool_manifest_path,
    package_tool_source_path,
)
from agent_factory.tooling.providers import PackageToolProvider, ToolProviderContext
from agent_factory.tooling.runtime_resources import PACKAGE_TOOL_SYSTEM_RESOURCE_IDS
from agent_factory.tooling.skills import SKILL_TOOL_ID
from agent_factory.tooling.skills.schema import SkillGatewayState


ValidationScope = str
CREATE_AGENT_RUNTIME_PATTERN_ID = "react_agent"
CREATE_AGENT_RUNTIME_PATTERN_IDS = {CREATE_AGENT_RUNTIME_PATTERN_ID, PLAN_AND_EXECUTE_PATTERN_ID}


class CreateAgentPackageValidator:
    def validate(
        self,
        package_root: str | Path,
        *,
        scope: ValidationScope = "full_static",
        changed_files: list[str] | None = None,
    ) -> PackageValidationReport:
        root = Path(package_root).expanduser().resolve()
        changed = list(changed_files or [])
        hygiene = _workspace_hygiene(root, changed)
        if hygiene is not None:
            return _with_scope(hygiene, scope=scope, changed_files=changed)
        if scope == "workspace_hygiene":
            return _passed(root, scope=scope, changed_files=changed, summary="Workspace hygiene checks passed.")
        manifest_path = root / "agent_package.json"
        if not manifest_path.exists():
            return _with_scope(
                PackageValidationReport(
                    package_root=str(root),
                    summary="agent_package.json is missing.",
                    issues=[
                        PackageValidationIssue(
                            where="package.manifest",
                            summary="agent_package.json is missing",
                            message="The workspace does not contain agent_package.json.",
                            path="agent_package.json",
                            expected="agent_package.json exists at the package root",
                            actual="missing",
                            repair_hint="Create agent_package.json with package-relative contract and assembly references.",
                            target_files=["agent_package.json"],
                            recommended_skill=_recommended_skill("package.manifest", ["agent_package.json"]),
                            recommended_resources=_recommended_resources("01-package-identity-system", ["agent_package.json"]),
                        )
                    ],
                ),
                scope=scope,
                changed_files=changed,
            )
        manifest_shape_report = _manifest_shape_report(root, manifest_path, scope=scope, changed_files=changed)
        if manifest_shape_report is not None:
            return manifest_shape_report

        # JSON syntax validation: check all JSON files before attempting to load
        json_syntax_report = _json_syntax_report(root, scope=scope, changed_files=changed)
        if json_syntax_report is not None:
            return json_syntax_report
        if scope == "package_shape":
            try:
                AgentPackageManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
            except Exception as exc:
                return _failed(root, "package.manifest", exc, ["agent_package.json"], scope=scope, changed_files=changed)
            return _passed(root, scope=scope, changed_files=changed, summary="Package shape checks passed.")

        try:
            package = AgentPackageLoader().load_path(manifest_path)
        except Exception as exc:
            load_report = _package_load_schema_report(root, exc, scope=scope, changed_files=changed)
            if load_report is not None:
                return load_report
            return _failed(root, "package.load", exc, ["agent_package.json"], scope=scope, changed_files=changed)
        runtime_path_report = _runtime_path_report(root, package, scope=scope, changed_files=changed)
        if runtime_path_report is not None:
            return runtime_path_report
        file_contract_report = _package_file_contract_report(root, package, scope=scope, changed_files=changed)
        if file_contract_report is not None:
            return file_contract_report
        knowledge_source_report = _package_knowledge_source_report(
            root,
            scope=scope,
            changed_files=changed,
        )
        if knowledge_source_report is not None:
            return knowledge_source_report
        resource_binding_report = _package_tool_resource_binding_report(
            root,
            scope=scope,
            changed_files=changed,
        )
        if resource_binding_report is not None:
            return resource_binding_report
        if scope in {"python_syntax", "full_static"}:
            syntax_report = _python_syntax(root, changed)
            if syntax_report is not None:
                return _with_scope(syntax_report, scope=scope, changed_files=changed)
        try:
            compiler = _static_validation_compiler()
            runtime_build = RuntimeBuildPlanner(registry=default_runtime_contract_registry()).build(
                package,
                base_services=compiler.facade.instance.services,
            )
        except Exception as exc:
            runtime_contract_report = _runtime_contract_build_report(root, package, exc, scope=scope, changed_files=changed)
            if runtime_contract_report is not None:
                return runtime_contract_report
            return _failed(root, "runtime_contracts.build", exc, ["agent_package.json", "contracts"], scope=scope, changed_files=changed)
        if scope == "runtime_contract_build":
            return _passed(root, scope=scope, changed_files=changed, summary="Runtime contract build checks passed.")
        try:
            binding_target_report = _binding_target_report(
                root,
                package,
                compiler.facade.instance.pattern_registry,
                scope=scope,
                changed_files=changed,
            )
            if binding_target_report is not None:
                return binding_target_report
            compiler.compile(package.assembly_spec, runtime_build=runtime_build)
        except Exception as exc:
            return _failed(root, "assembly.compile", exc, ["assembly_spec.json"], scope=scope, changed_files=changed)
        if scope != "full_static":
            return _passed(root, scope=scope, changed_files=changed, summary="Assembly compile checks passed.")
        # Full static: semantic completeness gate
        semantic_report = _semantic_completeness_report(root, package, scope=scope, changed_files=changed)
        if semantic_report is not None:
            return semantic_report
        environment_report = _environment_readiness_report(
            root,
            scope=scope,
            changed_files=changed,
        )
        if environment_report is not None:
            return environment_report
        probe_report = _package_tool_probe_report(root, package, scope=scope, changed_files=changed)
        if probe_report is not None:
            return probe_report
        return _passed(root, scope=scope, changed_files=changed, summary="Package static validation passed.")


def _environment_readiness_report(
    root: Path,
    *,
    scope: ValidationScope,
    changed_files: list[str],
) -> PackageValidationReport | None:
    try:
        EnvironmentResolver().require_ready(root)
    except EnvironmentResolutionError as exc:
        return _issues_report(
            root,
            [
                PackageValidationIssue(
                    where="dependencies.environment_lock",
                    summary="package dependency environment is not prepared",
                    message=str(exc),
                    path="environment.lock.json",
                    expected=(
                        "environment.lock.json matches contracts/dependencies.json and all referenced "
                        "dependency-pool artifacts are available"
                    ),
                    actual=exc.status,
                    repair_hint=(
                        "Run a successful asynchronous package-tool probe for the current dependency "
                        "contract, then rerun full_static validation."
                    ),
                    target_files=["contracts/dependencies.json", "environment.lock.json"],
                    recommended_skill="10-package-tool-system",
                )
            ],
            scope=scope,
            changed_files=changed_files,
            summary="Package dependency environment is not publish-ready.",
        )
    return None


def _static_validation_compiler() -> AgentAssemblyCompiler:
    return AgentAssemblyCompiler(
        facade=RuntimeKernelFacade(
            checkpointer_config=LangGraphCheckpointerConfig(backend="memory"),
            memory_store_config=LangGraphStoreConfig(backend="memory"),
        )
    )


def _package_tool_resource_binding_report(
    root: Path,
    *,
    scope: ValidationScope,
    changed_files: list[str],
) -> PackageValidationReport | None:
    contract = ResourcesContract.model_validate_json(
        (root / "contracts" / "resources.json").read_text(encoding="utf-8")
    )
    descriptors = {item.resource_id: item for item in contract.config.resource_descriptors}
    issues: list[PackageValidationIssue] = []
    package_tools = PackageToolProvider().discover(ToolProviderContext(package_root=root)).tool_specs
    for spec in package_tools:
        package_resource_ids = {
            selector.split(".", 1)[0]
            for selector in spec.resources.values()
            if selector.split(".", 1)[0] not in PACKAGE_TOOL_SYSTEM_RESOURCE_IDS
        }
        for resource_id in sorted(package_resource_ids):
            descriptor = descriptors.get(resource_id)
            if descriptor is None:
                issues.append(
                    PackageValidationIssue(
                        where="package_tool.resource_descriptor",
                        summary=f"package tool {spec.id} references undeclared resource {resource_id}",
                        message="Every package-owned resource selector must resolve to a published Resource Descriptor.",
                        path=f"tools/{spec.id}/manifest.json",
                        expected=f"contracts/resources.json declares {resource_id} and names {spec.id} in used_by.",
                        actual="resource descriptor is missing",
                        repair_hint="Re-run create_agent_authoring(action='upsert_package_tool') with the matching resource_descriptors in the same coherent authoring call.",
                        target_files=[f"tools/{spec.id}/manifest.json", "contracts/resources.json"],
                        recommended_skill="10-package-tool-system",
                    )
                )
            elif spec.id not in descriptor.used_by:
                issues.append(
                    PackageValidationIssue(
                        where="package_tool.resource_usage",
                        summary=f"resource {resource_id} does not declare package tool {spec.id} as a consumer",
                        message="Resource Descriptor used_by must match ToolSpec resource selectors.",
                        path="contracts/resources.json",
                        expected=f"{resource_id}.used_by contains {spec.id}.",
                        actual=", ".join(descriptor.used_by) or "empty",
                        repair_hint="Re-run create_agent_authoring(action='upsert_package_tool') with an aligned descriptor and ToolSpec selector.",
                        target_files=["contracts/resources.json", f"tools/{spec.id}/manifest.json"],
                        recommended_skill="05-resources-system",
                    )
                )
    if not issues:
        return None
    return PackageValidationReport(
        package_root=str(root),
        validation_scope=scope,  # type: ignore[arg-type]
        changed_files=changed_files,
        summary="Package Tool resource selectors and Resource Descriptors are inconsistent.",
        issues=issues,
    )


def _passed(root: Path, *, scope: ValidationScope, changed_files: list[str], summary: str) -> PackageValidationReport:
    return PackageValidationReport(
        status="passed",
        package_root=str(root),
        validation_scope=scope,  # type: ignore[arg-type]
        changed_files=changed_files,
        summary=summary,
    )


def _failed(
    root: Path,
    where: str,
    exc: Exception,
    target_files: list[str],
    *,
    scope: ValidationScope,
    changed_files: list[str],
) -> PackageValidationReport:
    recommended_skill = _recommended_skill(where, target_files)
    return PackageValidationReport(
        package_root=str(root),
        validation_scope=scope,  # type: ignore[arg-type]
        changed_files=changed_files,
        summary=f"{where} failed: {type(exc).__name__}: {exc}",
        issues=[
            PackageValidationIssue(
                where=where,
                summary=f"{type(exc).__name__}: {exc}",
                message=str(exc),
                path=target_files[0] if target_files else "",
                expected=_expected_for_where(where),
                actual=f"{type(exc).__name__}: {exc}",
                repair_hint=_repair_hint_for_where(where),
                target_files=target_files,
                recommended_skill=recommended_skill,
                recommended_resources=_recommended_resources(recommended_skill, target_files),
                details=_exception_details(exc),
            )
        ],
    )


def _package_load_schema_report(
    root: Path,
    exc: Exception,
    *,
    scope: ValidationScope,
    changed_files: list[str],
) -> PackageValidationReport | None:
    if not isinstance(exc, ValidationError):
        return None
    issues: list[PackageValidationIssue] = []
    for error in exc.errors():
        issue = _schema_repair_issue_from_pydantic_error(error)
        if issue is not None:
            issues.append(issue)
    if not issues:
        return None
    return PackageValidationReport(
        package_root=str(root),
        validation_scope=scope,  # type: ignore[arg-type]
        changed_files=changed_files,
        summary="package.load.schema failed: package files do not match executable runtime schemas.",
        issues=issues,
    )


def _schema_repair_issue_from_pydantic_error(error: dict[str, Any]) -> PackageValidationIssue | None:
    loc = tuple(str(item) for item in error.get("loc", ()))
    error_type = str(error.get("type") or "")
    message = str(error.get("msg") or "")
    input_value = error.get("input")
    if _loc_contains(loc, "tools"):
        index = _loc_index_after(loc, "tools")
        invalid_path = "assembly_spec.json:/tools" + (f"/{index}" if index is not None else "")
        return PackageValidationIssue(
            where="package.load.schema.assembly_tools",
            summary="assembly_spec.json tools entries must be ToolSpec objects",
            message=message,
            path="assembly_spec.json",
            expected="AgentAssemblySpec.tools is an array of ToolSpec objects.",
            actual=_compact_actual(input_value),
            repair_hint="Regenerate the package tool through create_agent_authoring(action='upsert_package_tool') so ToolSpec, manifest, package index, dependencies, and assembly tool access stay aligned.",
            target_files=["assembly_spec.json", "tools/"],
            recommended_skill="12-assembly-pattern-system",
            recommended_resources=[
                "examples/assembly_pattern_system.capability.json",
            ],
            schema_path="AgentAssemblySpec.tools[]",
            invalid_value_path=invalid_path,
            expected_shape=_tool_spec_expected_shape(),
            repair_template=_tool_spec_repair_template(),
            replace_strategy="replace_array_item",
            details={"pydantic_error": error, "error_type": error_type},
        )
    if _loc_contains(loc, "node_bindings"):
        index = _loc_index_after(loc, "node_bindings")
        invalid_path = "assembly_spec.json:/bindings/node_bindings" + (f"/{index}" if index is not None else "")
        return PackageValidationIssue(
            where="package.load.schema.node_binding",
            summary="assembly_spec.json node_bindings entries must be NodeBinding objects",
            message=message,
            path="assembly_spec.json",
            expected="BindingSet.node_bindings is an array of NodeBinding objects with binding_id, binding_type, target, and payload.",
            actual=_compact_actual(input_value),
            repair_hint="Regenerate built-in pattern bindings through create_agent_authoring(action='configure_pattern_assembly') instead of hand-writing NodeBinding objects.",
            target_files=["assembly_spec.json"],
            recommended_skill="12-assembly-pattern-system",
            recommended_resources=[
                "examples/assembly_pattern_system.capability.json",
                "references/final_validation.repair_mappings.json",
            ],
            schema_path="AgentAssemblySpec.bindings.node_bindings[]",
            invalid_value_path=invalid_path,
            expected_shape=_node_binding_expected_shape(),
            repair_template=_node_binding_repair_template(),
            replace_strategy="replace_array_item",
            details={"pydantic_error": error, "error_type": error_type},
        )
    if _loc_contains(loc, "contracts"):
        return PackageValidationIssue(
            where="package.load.schema.manifest_contracts",
            summary="agent_package.json contracts must use package-relative file references",
            message=message,
            path="agent_package.json",
            expected="agent_package.json contracts is an object mapping required contract keys to package-relative paths.",
            actual=_compact_actual(input_value),
            repair_hint="Restore scaffold-owned manifest contract references through package scaffold regeneration or create_agent_authoring reset_contract for malformed scaffold contracts; do not hand-write ad hoc contract paths.",
            target_files=["agent_package.json"],
            recommended_skill="01-package-identity-system",
            recommended_resources=["references/package_identity.schema.json"],
            schema_path="AgentPackageManifest.contracts",
            invalid_value_path="agent_package.json:/contracts",
            expected_shape={"contracts": {"tools": "contracts/tools.json"}},
            repair_template={"contracts": {"<required_contract_key>": "contracts/<required_contract_key>.json"}},
            replace_strategy="replace_object",
            details={"pydantic_error": error, "error_type": error_type},
        )
    return None


def _loc_contains(loc: tuple[str, ...], segment: str) -> bool:
    return segment in loc


def _loc_index_after(loc: tuple[str, ...], segment: str) -> str | None:
    try:
        value = loc[loc.index(segment) + 1]
    except (ValueError, IndexError):
        return None
    return value if value.isdigit() else None


def _compact_actual(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)[:500]
    except TypeError:
        return str(value)[:500]


def _tool_spec_expected_shape() -> dict[str, Any]:
    return {
        "id": "snake_case_tool_id",
        "description": "What the tool does.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        "output_schema": {"type": "object", "properties": {}, "additionalProperties": True},
        "resources": {},
        "risk_level": "low|medium|high",
        "concurrent": True,
        "output_compression": {
            "action_argument": "action",
            "actions": {
                "run": {
                    "mode": "structured_json",
                    "prompt": "<optional action-specific compression prompt>",
                    "schema": {"type": "object", "properties": {}, "additionalProperties": False},
                }
            },
        },
    }


def _tool_spec_repair_template() -> dict[str, Any]:
    return {
        "tool": "create_agent_authoring",
        "arguments": {
            "action": "upsert_package_tool",
            "tool_spec": {
                "id": "<tool_id>",
                "description": "<specific runtime capability>",
                "input_schema": {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
                "output_schema": {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": True,
                },
                "resources": {},
                "risk_level": "low",
                "concurrent": True,
                "output_compression": {
                    "action_argument": "action",
                    "actions": {
                        "run": {
                            "mode": "structured_json",
                            "prompt": "<optional action-specific compression prompt>",
                            "schema": {"type": "object", "properties": {}, "additionalProperties": False},
                        }
                    },
                },
            },
            "tool_source": "<complete tool.py source>",
            "python_requirements": [],
            "expose_to_nodes": ["answer"],
        },
    }


def _node_binding_expected_shape() -> dict[str, Any]:
    return {
        "binding_id": "snake_case_binding_id",
        "binding_type": "prompt|tool_access|model_operation|strategy_profile|output_formatter|custom",
        "target": {"node_id": "pattern_node_id", "impl": "node.impl"},
        "payload": {},
    }


def _node_binding_repair_template() -> dict[str, Any]:
    return {
        "tool": "create_agent_authoring",
        "arguments": {
            "action": "configure_pattern_assembly",
            "pattern_id": "react_agent",
            "prompts": {
                "answer": "<runtime system prompt>",
            },
            "allowed_tool_ids": ["<tool_id>"],
        },
    }


def _manifest_shape_report(
    root: Path,
    manifest_path: Path,
    *,
    scope: ValidationScope,
    changed_files: list[str],
) -> PackageValidationReport | None:
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    contracts = payload.get("contracts")
    if not isinstance(contracts, dict):
        return None
    contract_keys = {str(key) for key in contracts}
    missing_contracts = sorted(REQUIRED_AGENT_PACKAGE_CONTRACTS - contract_keys)
    infrastructure_contracts = sorted(PACKAGE_INFRASTRUCTURE_CONTRACTS & contract_keys)
    missing_files = [
        (str(key), str(value))
        for key, value in sorted(contracts.items())
        if isinstance(value, str) and value.strip() and not (root / value).is_file()
    ]
    if not missing_contracts and not infrastructure_contracts and not missing_files:
        return None
    target_files = sorted(
        {
            "agent_package.json",
            *(f"contracts/{contract_key}.json" for contract_key in missing_contracts),
            *(f"contracts/{contract_key}.json" for contract_key in infrastructure_contracts),
            *(relative_path for _contract_key, relative_path in missing_files),
        }
    )
    summary_parts = []
    if missing_contracts:
        summary_parts.append("missing required contracts: " + ", ".join(missing_contracts))
    if infrastructure_contracts:
        summary_parts.append(
            "runtime infrastructure contracts must not be package-declared: "
            + ", ".join(infrastructure_contracts)
        )
    if missing_files:
        summary_parts.append("missing referenced package files: " + ", ".join(path for _key, path in missing_files))
    summary = "; ".join(summary_parts)
    issue = PackageValidationIssue(
        where="package.manifest_contracts",
        summary=summary,
        message=summary,
        path="agent_package.json",
        expected="agent_package.json declares all RuntimeKernel required contracts and every referenced file exists.",
        actual=summary,
        repair_hint="Restore the scaffolded required contract files or regenerate the package structure through the deterministic scaffold/authoring path.",
        target_files=target_files,
        recommended_skill="01-package-identity-system",
        recommended_resources=list(system_resources("package_identity")),
        details={
            "missing_contracts": missing_contracts,
            "infrastructure_contracts": infrastructure_contracts,
            "missing_files": [{"contract_key": key, "target_file": path} for key, path in missing_files],
        },
    )
    return _with_scope(
        PackageValidationReport(
            package_root=str(root),
            summary=f"package.manifest_contracts failed: {summary}",
            issues=[issue],
        ),
        scope=scope,
        changed_files=changed_files,
    )

def _runtime_path_report(
    root: Path,
    package: Any,
    *,
    scope: ValidationScope,
    changed_files: list[str],
) -> PackageValidationReport | None:
    issues = _runtime_path_issues(root, package)
    if not issues:
        return None
    return _with_scope(
        PackageValidationReport(
            package_root=str(root),
            summary="runtime_contracts.path failed: runtime contract paths must be package-relative.",
            issues=issues,
        ),
        scope=scope,
        changed_files=changed_files,
    )


RUNTIME_CONTRACT_PATH_FIELDS: dict[str, tuple[str, ...]] = {
    "scheduler": ("config.store_path",),
    "tools": ("config.instance_extension_root",),
}


def _runtime_path_issues(root: Path, package: Any) -> list[PackageValidationIssue]:
    issues: list[PackageValidationIssue] = []
    for contract_key, fields in sorted(RUNTIME_CONTRACT_PATH_FIELDS.items()):
        payload = package.contracts.get(contract_key)
        if payload is None:
            continue
        contract_payload = payload.model_dump(mode="json") if hasattr(payload, "model_dump") else payload
        if not isinstance(contract_payload, dict):
            continue
        target_file = package.manifest.contracts.get(contract_key, f"contracts/{contract_key}.json")
        for field_path in fields:
            current = _get_nested_value(contract_payload, field_path)
            if not isinstance(current, str) or _path_resolves_inside(root, current):
                continue
            issues.append(
                PackageValidationIssue(
                    where="runtime_contracts.path",
                    summary=f"{contract_key}.{field_path} escapes package workspace",
                    message=f"{contract_key}.{field_path} is {current!r}; runtime paths must stay package-relative.",
                    path=target_file,
                    expected="Runtime contract filesystem paths resolve inside the package workspace.",
                    actual=current,
                    repair_hint="Restore the scaffolded package-relative runtime path for this contract or reconfigure the capability through its deterministic authoring path.",
                    target_files=[target_file],
                    recommended_skill=_recommended_skill("runtime_contracts.path", [target_file]),
                    recommended_resources=_recommended_resources(_recommended_skill("runtime_contracts.path", [target_file]), [target_file]),
                    details={"contract_key": contract_key, "field_path": field_path, "current_value": current},
                )
            )
    return issues


def _get_nested_value(payload: dict[str, Any], field_path: str) -> Any:
    value: Any = payload
    for part in field_path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _path_resolves_inside(root: Path, value: str) -> bool:
    raw = value.strip()
    if not raw:
        return False
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        candidate.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _runtime_contract_build_report(
    root: Path,
    package: Any,
    exc: Exception,
    *,
    scope: ValidationScope,
    changed_files: list[str],
) -> PackageValidationReport | None:
    if not isinstance(exc, ValidationError):
        return None
    issues: list[PackageValidationIssue] = []
    for error in exc.errors():
        issue = _runtime_contract_issue_from_pydantic_error(package, error)
        if issue is not None:
            issues.append(issue)
    if not issues:
        return None
    return _issues_report(
        root,
        issues,
        scope=scope,
        changed_files=changed_files,
        summary="Runtime contract build check failed: " + "; ".join(issue.summary for issue in issues[:3]),
    )


def _runtime_contract_issue_from_pydantic_error(package: Any, error: dict[str, Any]) -> PackageValidationIssue | None:
    loc = tuple(str(item) for item in error.get("loc", ()))
    message = str(error.get("msg") or "")
    input_value = error.get("input")
    if _scheduler_seed_error(loc=loc, message=message, input_value=input_value):
        invalid_path = _scheduler_seed_invalid_path(loc)
        summary = _scheduler_seed_summary(loc=loc, message=message)
        return PackageValidationIssue(
            where="scheduler_seed.target_payload",
            summary=summary,
            message=message,
            path=_contract_path(package, "scheduler_seed"),
            expected="SchedulerSeedContract graph_run targets use payload.message to describe the scheduled agent run.",
            actual=_compact_actual(input_value),
            repair_hint="Regenerate this scheduler seed with create_agent_authoring(action='upsert_scheduler_seed') using a graph_run target payload that includes message.",
            target_files=[_contract_path(package, "scheduler_seed")],
            recommended_skill="15-scheduler-seed-system",
            recommended_resources=[
                "examples/scheduler_seed_system.capability.json",
                "references/scheduler_seed_system.repair_hints.md",
            ],
            schema_path="SchedulerSeedContract.config.seeds[].target.payload.message",
            invalid_value_path=invalid_path,
            expected_shape={
                "target": {
                    "target_type": "graph_run",
                    "payload": {
                        "message": "Natural-language instruction for the scheduled agent run.",
                    },
                }
            },
            repair_template={
                "tool": "create_agent_authoring",
                "arguments": {
                    "action": "upsert_scheduler_seed",
                    "seed": {
                        "seed_id": "<seed_id>",
                        "title": "<schedule title>",
                        "human_schedule": "<human schedule>",
                        "schedule_type": "cron",
                        "schedule_expr": "<cron expression>",
                        "timezone": "<timezone>",
                        "target": {
                            "target_type": "graph_run",
                            "payload": {
                                "message": "<scheduled task instruction from task_content/user request>",
                            },
                        },
                        "task_content": "<scheduled task instruction>",
                    },
                },
            },
            replace_strategy="replace_object",
            details={"pydantic_error": error},
        )
    if _loc_contains(loc, "seeds"):
        return PackageValidationIssue(
            where="scheduler_seed.schema",
            summary="contracts/scheduler_seed.json does not match SchedulerSeedContract",
            message=message,
            path=_contract_path(package, "scheduler_seed"),
            expected="contracts/scheduler_seed.json follows scheduler_seed_contract.v0.",
            actual=_compact_actual(input_value),
            repair_hint="Regenerate the scheduler seed through create_agent_authoring(action='upsert_scheduler_seed') using the validator evidence.",
            target_files=[_contract_path(package, "scheduler_seed")],
            recommended_skill="15-scheduler-seed-system",
            recommended_resources=[
                "examples/scheduler_seed_system.capability.json",
                "references/scheduler_seed_system.repair_hints.md",
            ],
            schema_path="SchedulerSeedContract.config.seeds[]",
            invalid_value_path=_scheduler_seed_invalid_path(loc),
            details={"pydantic_error": error},
        )
    return None


def _scheduler_seed_error(*, loc: tuple[str, ...], message: str, input_value: Any) -> bool:
    if not _loc_contains(loc, "target"):
        return False
    if "graph_run target payload requires message" in message:
        return True
    if isinstance(input_value, dict):
        payload = input_value.get("payload")
        return input_value.get("target_type") == "graph_run" and isinstance(payload, dict) and "message" not in payload
    return False


def _scheduler_seed_summary(*, loc: tuple[str, ...], message: str) -> str:
    index = _loc_index_after(loc, "seeds")
    seed_label = f"seed {index}" if index is not None else "scheduler seed"
    if "payload requires message" in message:
        return f"{seed_label} graph_run target payload is missing message"
    return f"{seed_label} target payload is invalid"


def _scheduler_seed_invalid_path(loc: tuple[str, ...]) -> str:
    path = "contracts/scheduler_seed.json"
    if loc:
        path += ":/" + "/".join(loc)
    return path


def _contract_path(package: Any, contract_key: str) -> str:
    manifest = getattr(package, "manifest", None)
    contracts = getattr(manifest, "contracts", {}) if manifest is not None else {}
    if isinstance(contracts, dict):
        value = contracts.get(contract_key)
        if isinstance(value, str) and value.strip():
            return value
    return f"contracts/{contract_key}.json"


def _with_scope(report: PackageValidationReport, *, scope: ValidationScope, changed_files: list[str]) -> PackageValidationReport:
    return report.model_copy(update={"validation_scope": scope, "changed_files": changed_files})


def _workspace_hygiene(root: Path, changed_files: list[str]) -> PackageValidationReport | None:
    yaml = YAML(typ="safe")
    for relative in changed_files:
        path = root / relative
        if not path.exists() or not path.is_file():
            continue
        try:
            if path.suffix == ".json":
                json.loads(path.read_text(encoding="utf-8"))
            elif path.suffix in {".yaml", ".yml"}:
                yaml.load(path.read_text(encoding="utf-8"))
        except Exception as exc:
            recommended_skill = _recommended_skill("workspace_hygiene.parse", [relative])
            return PackageValidationReport(
                package_root=str(root),
                summary=f"{relative} is not parseable: {type(exc).__name__}: {exc}",
                issues=[
                    PackageValidationIssue(
                        where="workspace_hygiene.parse",
                        summary=f"{relative} is not parseable",
                        message=str(exc),
                        path=relative,
                        expected="valid JSON or YAML syntax",
                        actual=f"{type(exc).__name__}: {exc}",
                        repair_hint="Repair the file syntax before continuing package validation.",
                        target_files=[relative],
                        recommended_skill=recommended_skill,
                        recommended_resources=_recommended_resources(recommended_skill, [relative]),
                        details=_exception_details(exc),
                    )
                ],
            )
    return None


def _package_knowledge_source_report(
    root: Path,
    *,
    scope: ValidationScope,
    changed_files: list[str],
) -> PackageValidationReport | None:
    if scope != "full_static":
        return None
    knowledge_root = root / "knowledge"
    knowledge_files = (
        sorted(path.relative_to(root).as_posix() for path in knowledge_root.rglob("*") if path.is_file())
        if knowledge_root.is_dir()
        else []
    )
    registry_path = root / KNOWLEDGE_SOURCES_FILE
    if not knowledge_files and not registry_path.exists():
        return None
    try:
        registry = (
            PackageKnowledgeSourceRegistry.model_validate_json(registry_path.read_text(encoding="utf-8"))
            if registry_path.is_file()
            else PackageKnowledgeSourceRegistry()
        )
    except Exception as exc:
        return _failed(
            root,
            "knowledge.source_registry",
            exc,
            [KNOWLEDGE_SOURCES_FILE],
            scope=scope,
            changed_files=changed_files,
        )
    recorded_paths = [record.knowledge_path for record in registry.records]
    missing = sorted(set(knowledge_files) - set(recorded_paths))
    stale = sorted(set(recorded_paths) - set(knowledge_files))
    duplicates = sorted(path for path in set(recorded_paths) if recorded_paths.count(path) > 1)
    invalid = sorted(path for path in recorded_paths if not path.startswith("knowledge/"))
    if not any((missing, stale, duplicates, invalid)):
        return None
    details = {
        "missing_source_evidence": missing,
        "stale_source_evidence": stale,
        "duplicate_source_evidence": duplicates,
        "invalid_knowledge_paths": invalid,
    }
    return _with_scope(
        PackageValidationReport(
            package_root=str(root),
            summary="Package knowledge requires one authoritative source record per bundled knowledge file.",
            issues=[
                PackageValidationIssue(
                    where="knowledge.source_evidence",
                    summary="Package knowledge source evidence is incomplete",
                    message=str(details),
                    path=KNOWLEDGE_SOURCES_FILE,
                    expected="Every knowledge/* file has exactly one authoritative, distributable source record.",
                    actual=str(details),
                    repair_hint=(
                        "Remove identity, persona, prompt, tool instruction, or unsupported generated files with "
                        "create_agent_authoring(action='remove_knowledge_file', knowledge_path=...). For real bundled "
                        "reference material, call "
                        "create_agent_authoring(action='upsert_knowledge_file', knowledge_path=..., "
                        "knowledge_content=..., knowledge_purpose=..., knowledge_source={source_kind, reference, "
                        "distributable: true})."
                    ),
                    target_files=["knowledge/", KNOWLEDGE_SOURCES_FILE],
                    recommended_skill="08-knowledge-system",
                    details=details,
                )
            ],
        ),
        scope=scope,
        changed_files=changed_files,
    )


def _json_syntax_report(
    root: Path,
    *,
    scope: ValidationScope,
    changed_files: list[str],
) -> PackageValidationReport | None:
    """Validate JSON syntax of all critical package files.

    This catches common LLM-generated JSON errors (trailing commas, extra braces)
    before they cause runtime loading failures.
    """
    critical_json_files = [
        ("agent_package.json", None),
        ("assembly_spec.json", None),
        (".factory/skill_gateway_state.json", SkillGatewayState),
        (".factory/todo.json", None),
        (".factory/action.json", None),
    ]

    # Add contract files
    manifest_path = root / "agent_package.json"
    if manifest_path.exists():
        try:
            manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(manifest_data.get("contracts"), dict):
                for contract_key, contract_path in manifest_data["contracts"].items():
                    critical_json_files.append((contract_path, None))
        except (json.JSONDecodeError, FileNotFoundError):
            pass  # Will be caught by per-file check below

    for relative_path, model_class in critical_json_files:
        file_path = root / relative_path
        if not file_path.exists():
            continue

        try:
            content = file_path.read_text(encoding="utf-8")
            # First check: raw JSON syntax
            parsed = json.loads(content)

            # Second check: if model class provided, validate schema
            if model_class is not None:
                model_class.model_validate(parsed)

        except json.JSONDecodeError as exc:
            # Extract helpful error context
            error_msg = str(exc)
            repair_hint = _json_error_repair_hint(error_msg)
            recommended_skill = _recommended_skill("json_syntax", [relative_path])

            return _with_scope(
                PackageValidationReport(
                    package_root=str(root),
                    summary=f"JSON syntax error in {relative_path}: {error_msg}",
                    issues=[
                        PackageValidationIssue(
                            where="json_syntax",
                            summary=f"Invalid JSON syntax in {relative_path}",
                            message=error_msg,
                            path=relative_path,
                            expected="Valid JSON syntax without trailing commas, extra braces, or unterminated strings",
                            actual=f"JSONDecodeError: {error_msg}",
                            repair_hint=repair_hint,
                            target_files=[relative_path],
                            recommended_skill=recommended_skill,
                            recommended_resources=_recommended_resources(recommended_skill, [relative_path]),
                            details={"line": getattr(exc, "lineno", None), "column": getattr(exc, "colno", None)},
                        )
                    ],
                ),
                scope=scope,
                changed_files=changed_files,
            )
        except ValidationError as exc:
            # Pydantic schema validation failed
            recommended_skill = _recommended_skill("json_schema", [relative_path])

            return _with_scope(
                PackageValidationReport(
                    package_root=str(root),
                    summary=f"JSON schema validation error in {relative_path}",
                    issues=[
                        PackageValidationIssue(
                            where="json_schema",
                            summary=f"Invalid JSON schema in {relative_path}",
                            message=str(exc),
                            path=relative_path,
                            expected=f"Valid {model_class.__name__} schema",
                            actual=f"ValidationError: {exc}",
                            repair_hint=_json_schema_repair_hint(relative_path),
                            target_files=[relative_path],
                            recommended_skill=recommended_skill,
                            recommended_resources=_recommended_resources(recommended_skill, [relative_path]),
                            details=_exception_details(exc),
                        )
                    ],
                ),
                scope=scope,
                changed_files=changed_files,
            )

    return None


def _json_error_repair_hint(error_msg: str) -> str:
    """Generate specific repair hints based on JSON error message."""
    error_lower = error_msg.lower()

    if "trailing comma" in error_lower or "expecting property name" in error_lower:
        return "Remove trailing commas before closing braces/brackets. Example: {\"a\": 1,} → {\"a\": 1}"

    if "trailing characters" in error_lower or "extra data" in error_lower:
        return "Remove extra characters after the closing brace. Check for duplicate closing braces or commas outside the JSON structure."

    if "unterminated string" in error_lower:
        return "Add missing closing quote for string values. Check for unescaped quotes inside strings."

    if "expecting" in error_lower:
        return "Check for missing commas between object properties or array elements, or missing closing braces/brackets."

    return "Fix JSON syntax. Common issues: trailing commas, extra/missing braces, unescaped quotes, missing commas."


def _json_schema_repair_hint(relative_path: str) -> str:
    if relative_path == "agent_package.json":
        return "Use create_agent_authoring(action='set_identity') or create_agent_authoring(action='configure_pattern_assembly') for manifest-owned fields; reset malformed scaffold contract files with create_agent_authoring(action='reset_contract', contract_key=...)."
    if relative_path == "assembly_spec.json":
        return "Regenerate built-in pattern assembly through create_agent_authoring(action='configure_pattern_assembly') so prompt, model_operation, tool_access, and activation stay coherent."
    if relative_path == "contracts/resources.json":
        return "Regenerate runtime resource descriptors through create_agent_authoring(action='upsert_resources') instead of hand-editing resource contract shape."
    if relative_path == "contracts/scheduler_seed.json":
        return "Regenerate scheduler seeds through create_agent_authoring(action='upsert_scheduler_seed') instead of hand-editing scheduler seed contract shape."
    if relative_path.startswith("contracts/"):
        contract_key = Path(relative_path).stem
        return f"Reset scaffold-owned contract shape with create_agent_authoring(action='reset_contract', contract_key='{contract_key}') unless a capability-specific authoring action applies."
    return "Repair only the validator-indicated target path. Prefer create_agent_authoring for stable package surfaces; use generic file edits only for capability content not covered by authoring actions."


def _python_syntax(root: Path, changed_files: list[str]) -> PackageValidationReport | None:
    candidates = [root / item for item in changed_files if item.endswith(".py")]
    if not candidates and (root / "tools").exists():
        candidates.extend(sorted((root / "tools").glob("**/*.py")))
    if not candidates and (root / "nodes").exists():
        candidates.extend(sorted((root / "nodes").glob("**/*.py")))
    for path in candidates:
        if not path.exists() or not path.is_file():
            continue
        try:
            py_compile.compile(str(path), doraise=True)
        except Exception as exc:
            relative = _relative(root, path)
            recommended_skill = _recommended_skill("python_syntax.compile", [relative])
            return PackageValidationReport(
                package_root=str(root),
                summary=f"{relative} failed Python syntax validation: {type(exc).__name__}: {exc}",
                issues=[
                    PackageValidationIssue(
                        where="python_syntax.compile",
                        summary=f"{relative} failed Python syntax validation",
                        message=str(exc),
                        path=relative,
                        expected="valid Python syntax",
                        actual=f"{type(exc).__name__}: {exc}",
                        repair_hint="Fix the generated Python entrypoint syntax and keep dependencies declared in the package.",
                        target_files=[relative],
                        recommended_skill=recommended_skill,
                        recommended_resources=_recommended_resources(recommended_skill, [relative]),
                        details=_exception_details(exc),
                    )
                ],
            )
    return None


def _package_file_contract_report(
    root: Path,
    package: Any,
    *,
    scope: ValidationScope,
    changed_files: list[str],
) -> PackageValidationReport | None:
    issues: list[PackageValidationIssue] = []
    manifest = package.manifest
    package_result = PackageToolProvider().discover(ToolProviderContext(package_root=root))
    package_tools = {spec.id: spec for spec in package_result.tool_specs}
    for diagnostic in package_result.diagnostics:
        if diagnostic.level == "error":
            manifest_path = str(diagnostic.details.get("manifest_path") or "tools/")
            issues.append(_contract_issue(
                where="package_tool.manifest_load",
                summary=diagnostic.message,
                message=str(diagnostic.details.get("error") or diagnostic.message),
                path=_relative(root, Path(manifest_path)),
                expected="Every tools/<id>/manifest.json loads as a ToolSpec.",
                actual=str(diagnostic.details.get("error") or diagnostic.message),
                repair_hint="Repair the package tool manifest so PackageToolProvider can load it.",
                target_files=[_relative(root, Path(manifest_path))],
                recommended_skill="10-package-tool-system",
            ))
    issues.extend(_agent_identity_alignment_issues(package))
    issues.extend(_runtime_pattern_alignment_issues(package))
    issues.extend(_manifest_asset_index_issues(root, manifest, package_tools))
    issues.extend(_tools_contract_issues(package))
    issues.extend(_tool_dependency_issues(root, package, package_tools))
    issues.extend(_assembly_tool_issues(package, package_tools))
    inherited_mcp_tools = _inherited_mcp_tool_ids()
    model_tool_ids = model_tool_ids_from_contract(package.contracts.get("model"))
    issues.extend(_tool_access_issues(package, package_tools, inherited_mcp_tools, model_tool_ids))
    issues.extend(_mcp_inheritance_materialization_issues(root, package, inherited_mcp_tools))
    issues.extend(_scheduler_tool_target_issues(package, package_tools, inherited_mcp_tools, model_tool_ids))
    if not issues:
        return None
    return _issues_report(
        root,
        issues,
        scope=scope,
        changed_files=changed_files,
        summary="Package file contract check failed: " + "; ".join(issue.summary for issue in issues[:3]),
    )


def _runtime_pattern_alignment_issues(package: Any) -> list[PackageValidationIssue]:
    manifest_pattern = str((getattr(package.manifest, "runtime", {}) or {}).get("pattern_id") or "")
    assembly_pattern = str(getattr(getattr(package.assembly_spec, "runtime", None), "pattern_id", "") or "")
    if manifest_pattern == assembly_pattern:
        return []
    return [
        _contract_issue(
            where="package.runtime_pattern_alignment",
            summary="agent_package.json runtime pattern does not match assembly_spec.json runtime pattern",
            message="The package manifest and assembly spec must point to the same built-in runtime pattern.",
            path="agent_package.json",
            expected="agent_package.json.runtime.pattern_id equals assembly_spec.json.runtime.pattern_id.",
            actual=f"agent_package.json={manifest_pattern or '<empty>'}; assembly_spec.json={assembly_pattern or '<empty>'}",
            repair_hint="Call create_agent_authoring(action='configure_pattern_assembly') with the selected built-in pattern so manifest and assembly stay aligned.",
            target_files=["agent_package.json", "assembly_spec.json"],
            recommended_skill="01-package-identity-system",
        )
    ]


def _agent_identity_alignment_issues(package: Any) -> list[PackageValidationIssue]:
    manifest_agent = getattr(package.manifest, "agent", None)
    assembly_agent = getattr(package.assembly_spec, "agent", None)
    fields = ("id", "name", "description", "version")
    mismatches = [
        field
        for field in fields
        if str(getattr(manifest_agent, field, "") or "") != str(getattr(assembly_agent, field, "") or "")
    ]
    if not mismatches:
        return []
    manifest_payload = {field: getattr(manifest_agent, field, None) for field in fields}
    assembly_payload = {field: getattr(assembly_agent, field, None) for field in fields}
    return [
        _contract_issue(
            where="package.agent_identity_alignment",
            summary="agent_package.json agent identity does not match assembly_spec.json agent identity",
            message="The package manifest and assembly spec must describe the same produced Agent identity.",
            path="agent_package.json",
            expected="agent_package.json.agent equals assembly_spec.json.agent for id, name, description, and version.",
            actual=f"mismatched fields: {', '.join(mismatches)}",
            repair_hint="Use create_agent_authoring(action='set_identity') so agent_package.json and assembly_spec.json identity stay aligned.",
            target_files=["agent_package.json", "assembly_spec.json"],
            recommended_skill="01-package-identity-system",
            expected_shape={"agent": manifest_payload},
            repair_template={
                "tool": "create_agent_authoring",
                "arguments": {
                    "action": "set_identity",
                    "agent": manifest_payload,
                },
            },
            details={
                "mismatched_fields": mismatches,
                "agent_package_json_agent": manifest_payload,
                "assembly_spec_json_agent": assembly_payload,
            },
        )
    ]


def _binding_target_report(
    root: Path,
    package: Any,
    pattern_registry: Any,
    *,
    scope: ValidationScope,
    changed_files: list[str],
) -> PackageValidationReport | None:
    issues = _binding_target_issues(package, pattern_registry)
    if not issues:
        return None
    return _issues_report(
        root,
        issues,
        scope=scope,
        changed_files=changed_files,
        summary="Assembly binding target check failed: " + "; ".join(issue.summary for issue in issues[:3]),
    )


def _binding_target_issues(package: Any, pattern_registry: Any) -> list[PackageValidationIssue]:
    pattern_id = str(getattr(getattr(package.assembly_spec, "runtime", None), "pattern_id", "") or "")
    if pattern_id not in CREATE_AGENT_RUNTIME_PATTERN_IDS:
        return [
            _contract_issue(
                where="assembly.binding_target.pattern",
                summary="create-agent currently supports only built-in react_agent and plan_and_execute runtime patterns",
                message=(
                    "Use a supported built-in runtime pattern and express capability through prompt bindings, tool access, package tools, knowledge, memory, scheduler, and resources."
                ),
                path="assembly_spec.json",
                expected='assembly_spec.runtime.pattern_id is "react_agent" or "plan_and_execute".',
                actual=pattern_id or "<empty>",
                repair_hint="Call create_agent_authoring(action='configure_pattern_assembly') with react_agent or plan_and_execute.",
                target_files=["assembly_spec.json", "agent_package.json"],
                recommended_skill="12-assembly-pattern-system",
            )
        ]
    try:
        pattern = pattern_registry.get(pattern_id)
    except Exception as exc:
        return [
            _contract_issue(
                where="assembly.binding_target.pattern",
                summary=f"assembly runtime pattern {pattern_id or '<empty>'} is not available",
                message=f"Cannot validate binding targets because the runtime pattern cannot be loaded: {type(exc).__name__}: {exc}",
                path="assembly_spec.json",
                expected="assembly_spec.runtime.pattern_id references a supported built-in runtime pattern.",
                actual=pattern_id or "<empty>",
                repair_hint="Call create_agent_authoring(action='configure_pattern_assembly') with react_agent or plan_and_execute.",
                target_files=["assembly_spec.json"],
                recommended_skill="12-assembly-pattern-system",
            )
        ]
    node_impls = {node.id: node.impl for node in pattern.nodes}
    issues: list[PackageValidationIssue] = []
    prompt_bindings: dict[tuple[str, str, str], Any] = {}
    for index, binding in enumerate(package.assembly_spec.bindings.node_bindings):
        target = getattr(binding, "target", None)
        node_id = str(getattr(target, "node_id", "") or "")
        impl = str(getattr(target, "impl", "") or "")
        actual_impl = node_impls.get(node_id)
        if actual_impl is None:
            issues.append(_binding_target_issue(
                index=index,
                binding=binding,
                expected=f"target.node_id is one of: {', '.join(sorted(node_impls))}",
                actual=f"{node_id or '<empty>'}.{impl or '<empty>'}",
                summary=f"binding {binding.binding_id} targets unknown pattern node {node_id or '<empty>'}",
                message=f"The selected pattern {pattern.pattern_id} has no node id {node_id or '<empty>'}.",
                repair_template=_node_binding_repair_template(),
            ))
            continue
        if impl != actual_impl:
            issues.append(_binding_target_issue(
                index=index,
                binding=binding,
                expected=f"target.impl for node {node_id} is {actual_impl}",
                actual=impl or "<empty>",
                summary=f"binding {binding.binding_id} target impl does not match pattern node {node_id}",
                message=f"The selected pattern {pattern.pattern_id} defines node {node_id} with impl {actual_impl}, but the binding targets {impl or '<empty>'}.",
                repair_template=_node_binding_repair_template(),
            ))
            continue
        if binding.binding_type == "prompt":
            payload = getattr(binding, "payload", None)
            prompt_id = str(getattr(payload, "prompt_id", "") or "")
            if prompt_id:
                prompt_bindings[(node_id, impl, prompt_id)] = binding
    for index, binding in enumerate(package.assembly_spec.bindings.node_bindings):
        if binding.binding_type != "model_operation":
            continue
        target = getattr(binding, "target", None)
        node_id = str(getattr(target, "node_id", "") or "")
        impl = str(getattr(target, "impl", "") or "")
        actual_impl = node_impls.get(node_id)
        if actual_impl != impl:
            continue
        payload = getattr(binding, "payload", None)
        prompt_id = str(getattr(payload, "prompt_id", "") or "").strip()
        if not prompt_id:
            continue
        if (node_id, impl, prompt_id) in prompt_bindings:
            continue
        issues.append(_binding_target_issue(
            index=index,
            binding=binding,
            expected=f"a prompt binding with target {node_id}.{impl} and payload.prompt_id={prompt_id}",
            actual="missing prompt binding for model_operation.prompt_id",
            summary=f"model_operation binding {binding.binding_id} references missing prompt_id {prompt_id}",
            message="Prompt bindings are node-scoped; model_operation.prompt_id must resolve to a prompt binding on the same pattern node and impl.",
            repair_template=_node_binding_repair_template(),
        ))
    if pattern_id == PLAN_AND_EXECUTE_PATTERN_ID:
        issues.extend(_plan_and_execute_binding_issues(package))
    return issues


def _plan_and_execute_binding_issues(package: Any) -> list[PackageValidationIssue]:
    bindings = list(package.assembly_spec.bindings.node_bindings)
    issues: list[PackageValidationIssue] = []
    activation = getattr(package.assembly_spec.runtime, "agent_config", {}).get("activation")
    if not _valid_plan_activation(activation):
        issues.append(_contract_issue(
            where="assembly.plan_and_execute.activation",
            summary="plan_and_execute activation is missing or incomplete",
            message=(
                "The plan_and_execute runtime needs activation guidance so casual or incomplete inputs do not "
                "start planner/executor work."
            ),
            path="assembly_spec.json",
            expected="runtime.agent_config.activation has workflow_goal, start_when, and ask_when_missing.",
            actual="missing or incomplete",
            repair_hint="Call create_agent_authoring(action='configure_pattern_assembly') for plan_and_execute with activation.",
            target_files=["assembly_spec.json"],
            recommended_skill="12-assembly-pattern-system",
        ))
    for node_id in ("planner", "executor", "casual_react", "final_answer"):
        if not _has_binding(bindings, node_id=node_id, binding_type="prompt"):
            issues.append(_missing_plan_binding_issue(node_id=node_id, binding_type="prompt"))
        if not _has_binding(bindings, node_id=node_id, binding_type="model_operation"):
            issues.append(_missing_plan_binding_issue(node_id=node_id, binding_type="model_operation"))
    planner_tools = _tool_access_for_node(bindings, node_id="planner")
    if planner_tools != [RUNTIME_PLAN_TOOL_ID]:
        issues.append(_contract_issue(
            where="assembly.plan_and_execute.planner_tools",
            summary="plan_and_execute planner must only expose runtime_plan",
            message="The planner creates dynamic plan state and must not call business tools.",
            path="assembly_spec.json",
            expected='planner tool_access.allowed_tool_ids is ["runtime_plan"].',
            actual=", ".join(planner_tools) if planner_tools else "<missing>",
            repair_hint="Call create_agent_authoring(action='configure_pattern_assembly') for plan_and_execute so planner/executor/final_answer bindings are regenerated coherently.",
            target_files=["assembly_spec.json"],
            recommended_skill="12-assembly-pattern-system",
        ))
    executor_tools = _tool_access_for_node(bindings, node_id="executor")
    if RUNTIME_PLAN_TOOL_ID not in executor_tools:
        issues.append(_contract_issue(
            where="assembly.plan_and_execute.executor_tools",
            summary="plan_and_execute executor must expose runtime_plan",
            message="The executor updates dynamic plan state through runtime_plan while executing current steps.",
            path="assembly_spec.json",
            expected='executor tool_access.allowed_tool_ids includes "runtime_plan".',
            actual=", ".join(executor_tools) if executor_tools else "<missing>",
            repair_hint="Call create_agent_authoring(action='configure_pattern_assembly') for plan_and_execute so executor tool access includes runtime_plan coherently.",
            target_files=["assembly_spec.json"],
            recommended_skill="12-assembly-pattern-system",
        ))
    casual_tools = _tool_access_for_node(bindings, node_id="casual_react")
    if RUNTIME_PLAN_TOOL_ID in casual_tools:
        issues.append(_contract_issue(
            where="assembly.plan_and_execute.casual_react_tools",
            summary="plan_and_execute casual_react must not expose runtime_plan",
            message="The casual_react node handles non-main-workflow ReAct requests and must not mutate the main runtime plan.",
            path="assembly_spec.json",
            expected='casual_react tool_access.allowed_tool_ids excludes "runtime_plan".',
            actual=", ".join(casual_tools),
            repair_hint="Call create_agent_authoring(action='configure_pattern_assembly') for plan_and_execute so casual_react bindings are regenerated coherently.",
            target_files=["assembly_spec.json"],
            recommended_skill="12-assembly-pattern-system",
        ))
    final_tools = _tool_access_for_node(bindings, node_id="final_answer")
    if RUNTIME_PLAN_TOOL_ID in final_tools:
        issues.append(_contract_issue(
            where="assembly.plan_and_execute.final_answer_tools",
            summary="plan_and_execute final_answer must not expose runtime_plan",
            message=(
                "The final_answer node may use delivery tools for final artifacts, but it must not mutate "
                "dynamic plan state through runtime_plan."
            ),
            path="assembly_spec.json",
            expected='final_answer tool_access.allowed_tool_ids excludes "runtime_plan".',
            actual=", ".join(final_tools),
            repair_hint="Call create_agent_authoring(action='configure_pattern_assembly') for plan_and_execute so final_answer delivery tools are regenerated coherently.",
            target_files=["assembly_spec.json"],
            recommended_skill="12-assembly-pattern-system",
        ))
    return issues


def _valid_plan_activation(value: Any) -> bool:
    return bool(normalize_plan_and_execute_activation(value))


def _has_binding(bindings: list[Any], *, node_id: str, binding_type: str) -> bool:
    for binding in bindings:
        target = getattr(binding, "target", None)
        if str(getattr(target, "node_id", "") or "") != node_id:
            continue
        if binding.binding_type == binding_type:
            return True
    return False


def _tool_access_for_node(bindings: list[Any], *, node_id: str) -> list[str]:
    ids: list[str] = []
    for binding in bindings:
        if binding.binding_type != "tool_access":
            continue
        target = getattr(binding, "target", None)
        if str(getattr(target, "node_id", "") or "") != node_id:
            continue
        payload = getattr(binding, "payload", None)
        ids.extend(str(item) for item in (getattr(payload, "allowed_tool_ids", []) or []))
    return ids


def _missing_plan_binding_issue(*, node_id: str, binding_type: str) -> PackageValidationIssue:
    return _contract_issue(
        where="assembly.plan_and_execute.binding",
        summary=f"plan_and_execute {node_id} is missing {binding_type} binding",
        message=f"The plan_and_execute pattern requires {node_id} to have a {binding_type} binding.",
        path="assembly_spec.json",
        expected=f"{node_id} has a {binding_type} binding targeting cognitive.answer.",
        actual="missing",
        repair_hint="Regenerate plan_and_execute bindings through create_agent_authoring(action='configure_pattern_assembly').",
        target_files=["assembly_spec.json"],
        recommended_skill="12-assembly-pattern-system",
    )


def _binding_target_issue(
    *,
    index: int,
    binding: Any,
    expected: str,
    actual: str,
    summary: str,
    message: str,
    repair_template: dict[str, Any],
) -> PackageValidationIssue:
    return PackageValidationIssue(
        where="assembly.binding_target",
        summary=summary,
        message=message,
        path="assembly_spec.json",
        expected=expected,
        actual=actual,
        repair_hint="Align binding.target with the selected runtime pattern node table, then rerun create_agent_validate.",
        target_files=["assembly_spec.json"],
        recommended_skill="12-assembly-pattern-system",
        recommended_resources=["examples/assembly_pattern_system.capability.json"],
        schema_path="AgentAssemblySpec.bindings.node_bindings[].target",
        invalid_value_path=f"assembly_spec.json:/bindings/node_bindings/{index}/target",
        expected_shape={
            "target": {"node_id": "pattern node id", "impl": "exact impl from selected pattern node"},
        },
        repair_template=repair_template,
        replace_strategy="replace_object",
        details={"binding_id": str(getattr(binding, "binding_id", "") or ""), "binding_type": str(getattr(binding, "binding_type", "") or "")},
    )


def _package_tool_probe_report(
    root: Path,
    package: Any,
    *,
    scope: ValidationScope,
    changed_files: list[str],
) -> PackageValidationReport | None:
    if scope != "full_static":
        return None
    package_result = PackageToolProvider().discover(ToolProviderContext(package_root=root))
    package_tools = {spec.id: spec for spec in package_result.tool_specs}
    if not package_tools:
        return None
    state = _read_probe_state(root)
    latest = state.latest_by_tool()
    current_fingerprint = package_fingerprint(root)
    issues: list[PackageValidationIssue] = []
    scheduler_tool_ids = set(_scheduler_package_tool_ids(package, package_tools))
    required_tool_ids = sorted(set(package_tools) | scheduler_tool_ids)
    for tool_id in required_tool_ids:
        record = latest.get(tool_id)
        if record is None:
            issues.append(_probe_issue(
                tool_id=tool_id,
                summary=f"package tool {tool_id} has not been probed",
                actual="missing probe evidence",
                repair_hint=(
                    "Use create_agent_probe_tool(action='inspect'), then start an asynchronous "
                    "create_agent_probe_tool(action='call', tool_id=..., arguments=..., prompt=..., "
                    "tool_goal=..., timeout_seconds=<task-appropriate-positive-seconds>) job with realistic "
                    "arguments. Query its job_id with action='status' until it reaches a terminal state."
                ),
            ))
            continue
        current_tool_digest = package_tool_digest(root, tool_id, fingerprint=current_fingerprint)
        if record.tool_digest != current_tool_digest:
            issues.append(_probe_issue(
                tool_id=tool_id,
                summary=f"package tool {tool_id} probe is stale",
                actual="probe tool digest does not match current tool files",
                repair_hint="The tool implementation changed after the last probe. Call create_agent_probe_tool again for this tool.",
                details={
                    "recorded_tool_digest": record.tool_digest,
                    "current_tool_digest": current_tool_digest,
                    "tool_digest_kind": record.tool_digest_kind,
                },
            ))
            continue
        if record.status == "configuration_required":
            continue
        if record.status != "passed":
            issues.append(_probe_issue(
                tool_id=tool_id,
                summary=f"package tool {tool_id} probe failed",
                actual=f"{record.observation_status} {record.contract_status}: {record.message}",
                repair_hint=(
                    "Repair the package tool using the probe observation, then start a new asynchronous "
                    "create_agent_probe_tool call and inspect its terminal status."
                ),
                details=record.model_dump(mode="json"),
            ))
            continue
        if record.probe_kind != "success_path" or record.only_error_handling_verified or not record.tool_returned_business_output:
            issues.append(_probe_issue(
                tool_id=tool_id,
                summary=f"package tool {tool_id} lacks successful-path probe evidence",
                actual=(
                    f"probe_kind={record.probe_kind}, "
                    f"only_error_handling_verified={record.only_error_handling_verified}, "
                    f"tool_returned_business_output={record.tool_returned_business_output}"
                ),
                repair_hint=(
                    "Run create_agent_probe_tool(action='call', tool_id=..., probe_kind='success_path', "
                    "arguments=..., prompt=..., tool_goal=..., timeout_seconds=<task-appropriate-positive-seconds>) with realistic successful-path inputs. "
                    "Query the returned job_id with action='status' until it reaches a terminal state. "
                    "If no successful input is available, ask the user for the missing resource instead of publishing."
                ),
                details=record.model_dump(mode="json"),
            ))
    if not issues:
        return None
    return _issues_report(
        root,
        issues,
        scope=scope,
        changed_files=changed_files,
        summary="Package tool probe check failed: " + "; ".join(issue.summary for issue in issues[:3]),
    )


def _manifest_asset_index_issues(root: Path, manifest: Any, package_tools: dict[str, Any]) -> list[PackageValidationIssue]:
    issues: list[PackageValidationIssue] = []
    expected_tools = {package_tool_manifest_path(tool_id) for tool_id in package_tools}
    issues.extend(_asset_index_issues(
        root,
        field_name="tools",
        declared=set(getattr(manifest, "tools", []) or []),
        expected=expected_tools,
        recommended_skill="10-package-tool-system",
    ))
    return issues


def _asset_index_issues(
    root: Path,
    *,
    field_name: str,
    declared: set[str],
    expected: set[str],
    recommended_skill: str,
) -> list[PackageValidationIssue]:
    issues: list[PackageValidationIssue] = []
    missing = sorted(expected - declared)
    dangling = sorted(path for path in declared if not (root / path).is_file())
    if missing:
        issues.append(_contract_issue(
            where=f"package_manifest.{field_name}_index",
            summary=f"agent_package.json {field_name} index is missing package assets",
            message=f"Missing {field_name} entries: {missing}",
            path="agent_package.json",
            expected=f"agent_package.json.{field_name} indexes every generated {field_name} asset.",
            actual=", ".join(missing),
            repair_hint="Regenerate the package tool through create_agent_authoring(action='upsert_package_tool') so the manifest index stays aligned.",
            target_files=["agent_package.json", *missing],
            recommended_skill=recommended_skill,
        ))
    if dangling:
        issues.append(_contract_issue(
            where=f"package_manifest.{field_name}_index",
            summary=f"agent_package.json {field_name} index references missing files",
            message=f"Dangling {field_name} entries: {dangling}",
            path="agent_package.json",
            expected=f"Every agent_package.json.{field_name} entry exists in the package.",
            actual=", ".join(dangling),
            repair_hint="Regenerate the package tool through create_agent_authoring(action='upsert_package_tool') or remove the stale package tool with create_agent_authoring(action='remove_package_tool', tool_id=...).",
            target_files=["agent_package.json", *dangling],
            recommended_skill=recommended_skill,
        ))
    return issues


def _assembly_tool_issues(package: Any, package_tools: dict[str, Any]) -> list[PackageValidationIssue]:
    issues: list[PackageValidationIssue] = []
    assembly_tools = {spec.id: spec for spec in package.assembly_spec.tools}
    for tool_id, package_spec in package_tools.items():
        assembly_spec = assembly_tools.get(tool_id)
        if assembly_spec is None:
            issues.append(_contract_issue(
                where="assembly.tools_index",
                summary=f"assembly_spec.json does not declare package tool {tool_id}",
                message=f"Package tool {tool_id} exists but assembly_spec.tools has no matching ToolSpec.",
                path="assembly_spec.json",
                expected="assembly_spec.tools contains a ToolSpec object for every package tool manifest.",
                actual=f"missing {tool_id}",
                repair_hint="Regenerate the package tool through create_agent_authoring(action='upsert_package_tool') so assembly_spec.tools matches the package tool manifest.",
                target_files=["assembly_spec.json", package_tool_manifest_path(tool_id)],
                recommended_skill="12-assembly-pattern-system",
            ))
            continue
        mismatches = _tool_spec_mismatches(package_spec, assembly_spec)
        if mismatches:
            mismatch_details = _tool_spec_mismatch_details(package_spec, assembly_spec, mismatches)
            issues.append(_contract_issue(
                where="assembly.tools_manifest_mismatch",
                summary=f"assembly ToolSpec for {tool_id} does not match package manifest",
                message=f"Mismatched ToolSpec fields: {', '.join(mismatches)}",
                path="assembly_spec.json",
                expected="assembly_spec.tools ToolSpec fields match tools/<id>/manifest.json.",
                actual=", ".join(mismatches),
                repair_hint="Regenerate the package tool through create_agent_authoring(action='upsert_package_tool') so assembly_spec.tools and the package tool manifest match.",
                target_files=["assembly_spec.json", package_tool_manifest_path(tool_id)],
                recommended_skill="12-assembly-pattern-system",
                details={"mismatches": mismatch_details},
            ))
    return issues


def _tools_contract_issues(package: Any) -> list[PackageValidationIssue]:
    contract = package.contracts.get("tools")
    if not isinstance(contract, ToolsContract):
        return []
    legal_builtin_ids = set(get_builtin_tool_ids())
    blocked_ids = _manufacturing_tool_ids()
    issues: list[PackageValidationIssue] = []
    for tool_id in contract.config.builtin_tool_ids:
        if tool_id in blocked_ids or tool_id.startswith("create_agent_"):
            issues.append(_contract_issue(
                where="tools_contract.manufacturing_tool",
                summary=f"contracts/tools.json exposes create-agent manufacturing tool {tool_id}",
                message="Produced AgentPackage must not expose create-agent manufacturing tools as runtime builtins.",
                path="contracts/tools.json",
                expected="contracts/tools.json builtin_tool_ids contains only runtime builtin tool ids.",
                actual=tool_id,
                repair_hint="Regenerate runtime tool exposure through create_agent_authoring(action='configure_pattern_assembly') without create-agent manufacturing tool ids.",
                target_files=["contracts/tools.json"],
                recommended_skill="09-tools-system",
            ))
        elif tool_id not in legal_builtin_ids:
            issues.append(_contract_issue(
                where="tools_contract.unknown_builtin_tool",
                summary=f"contracts/tools.json references unknown runtime builtin tool {tool_id}",
                message=f"{tool_id} is not an implemented runtime builtin tool.",
                path="contracts/tools.json",
                expected="contracts/tools.json builtin_tool_ids contains implemented runtime builtin tool ids.",
                actual=tool_id,
                repair_hint="Regenerate runtime tool exposure through create_agent_authoring(action='configure_pattern_assembly') with implemented runtime builtin, package, or inherited MCP tool ids only.",
                target_files=["contracts/tools.json"],
                recommended_skill="09-tools-system",
            ))
    return issues


def _tool_dependency_issues(root: Path, package: Any, package_tools: dict[str, Any]) -> list[PackageValidationIssue]:
    if not package_tools:
        return []
    contract = package.contracts.get("dependencies")
    if not isinstance(contract, DependenciesContract):
        return []
    imports_by_tool = _package_tool_external_imports(root=root, tool_ids=set(package_tools))
    issues: list[PackageValidationIssue] = []
    if contract.config.system_packages:
        issues.append(_contract_issue(
            where="dependencies.system_packages",
            summary="legacy operating-system package dependencies are not supported by the local runtime",
            message=(
                "contracts/dependencies.json still declares Linux/Docker-era system_packages. "
                "The local runtime resolves application dependencies through shared Python/npm pools and only checks "
                "explicit host commands through system_binaries."
            ),
            path="contracts/dependencies.json",
            expected="system_packages is empty and required host commands are declared through system_binaries.",
            actual=contract.config.system_packages,
            repair_hint=(
                "Inspect required commands with create_agent_authoring(action='inspect_runtime_environment'), then "
                "rewrite dependencies through create_agent_authoring(action='configure_dependencies')."
            ),
            target_files=["contracts/dependencies.json"],
            recommended_skill="10-package-tool-system",
        ))
    if (
        (contract.config.python_requirements or contract.config.npm_requirements)
        and contract.config.install_timeout_seconds is None
    ):
        issues.append(_contract_issue(
            where="dependencies.install_timeout_seconds",
            summary="dependency installation timeout is not declared",
            message="contracts/dependencies.json declares installable dependencies without config.install_timeout_seconds for dependency-pool resolution.",
            path="contracts/dependencies.json",
            expected="A task-appropriate positive install_timeout_seconds for dependency-pool resolution.",
            actual="install_timeout_seconds is missing",
            repair_hint="Use create_agent_authoring(action='configure_dependencies') and estimate a timeout from dependency size, platform, and network conditions.",
            target_files=["contracts/dependencies.json"],
            recommended_skill="10-package-tool-system",
        ))
    for tool_id, imports in sorted(imports_by_tool.items()):
        external_imports = sorted(imports)
        if not external_imports or contract.config.python_requirements:
            continue
        source_files = sorted({path for module in external_imports for path in imports[module]})
        issues.append(_contract_issue(
            where="dependencies.package_tool_imports",
            summary=f"package tool {tool_id} imports undeclared Python dependencies",
            message=(
                f"{package_tool_directory_path(tool_id)} imports third-party modules but contracts/dependencies.json "
                f"config.python_requirements is empty. External imports: {', '.join(external_imports)}"
            ),
            path="contracts/dependencies.json",
            expected="Package tools with external imports declare installable Python distributions in dependencies.config.python_requirements.",
            actual="python_requirements is empty",
            repair_hint=(
                "Regenerate the package tool through create_agent_authoring(action='upsert_package_tool') with the required installable distributions in requirements, then probe it in the local runtime."
            ),
            target_files=["contracts/dependencies.json", *source_files],
            recommended_skill="10-package-tool-system",
            expected_shape={
                "type": "dependencies",
                "version": "dependencies_contract.v1",
                "enabled": True,
                "config": {
                    "python_requirements": ["<installable-distribution-name>"],
                    "system_binaries": [],
                },
            },
            repair_template={
                "tool": "create_agent_authoring",
                "arguments": {
                    "action": "upsert_package_tool",
                    "tool_spec": {
                        "id": tool_id,
                        "description": "<specific runtime capability>",
                        "input_schema": {"type": "object", "additionalProperties": True},
                        "output_schema": {"type": "object", "additionalProperties": True},
                        "resources": {},
                        "risk_level": "low",
                        "concurrent": True,
                    },
                    "tool_source": "<current corrected tool.py source>",
                    "python_requirements": ["<installable-distribution-name>"],
                    "install_timeout_seconds": "<task-appropriate-positive-seconds>",
                    "expose_to_nodes": ["answer"],
                },
            },
            details={
                "tool_id": tool_id,
                "external_imports": external_imports,
                "declared_python_requirements": list(contract.config.python_requirements),
                "source_files": source_files,
            },
        ))
    return issues


def _package_tool_external_imports(*, root: Path, tool_ids: set[str]) -> dict[str, dict[str, list[str]]]:
    result: dict[str, dict[str, list[str]]] = {}
    tools_root = root / "tools"
    for tool_id in sorted(tool_ids):
        tool_root = tools_root / tool_id
        if not tool_root.is_dir():
            continue
        for source in sorted(tool_root.glob("**/*.py")):
            modules = _external_imports_for_file(root=root, source=source)
            if not modules:
                continue
            relative = _relative(root, source)
            bucket = result.setdefault(tool_id, {})
            for module in modules:
                bucket.setdefault(module, []).append(relative)
    return result


def _external_imports_for_file(*, root: Path, source: Path) -> set[str]:
    try:
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    except SyntaxError:
        return set()
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = _top_level_module(alias.name)
                if _is_external_tool_import(root=root, source=source, module=top):
                    modules.add(top)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                continue
            top = _top_level_module(node.module or "")
            if _is_external_tool_import(root=root, source=source, module=top):
                modules.add(top)
    return modules


def _top_level_module(value: str) -> str:
    return str(value or "").split(".", 1)[0].strip()


def _is_external_tool_import(*, root: Path, source: Path, module: str) -> bool:
    if not module:
        return False
    if module == "__future__":
        return False
    if module == "agent_factory":
        return False
    if module in sys.builtin_module_names:
        return False
    stdlib_modules = getattr(sys, "stdlib_module_names", set())
    if module in stdlib_modules:
        return False
    if _local_module_exists(root=root, source=source, module=module):
        return False
    return True


def _local_module_exists(*, root: Path, source: Path, module: str) -> bool:
    candidates = [
        source.parent / f"{module}.py",
        source.parent / module / "__init__.py",
        root / f"{module}.py",
        root / module / "__init__.py",
    ]
    return any(candidate.exists() for candidate in candidates)


def _tool_access_issues(
    package: Any,
    package_tools: dict[str, Any],
    inherited_mcp_tools: set[str],
    model_tool_ids: set[str],
) -> list[PackageValidationIssue]:
    issues: list[PackageValidationIssue] = []
    legal_tool_ids = _legal_runtime_tool_ids(
        package_tools=package_tools,
        inherited_mcp_tools=inherited_mcp_tools,
        model_tool_ids=model_tool_ids,
    )
    pattern_id = str(getattr(getattr(package.assembly_spec, "runtime", None), "pattern_id", "") or "")
    if pattern_id == PLAN_AND_EXECUTE_PATTERN_ID:
        legal_tool_ids.add(RUNTIME_PLAN_TOOL_ID)
    blocked_ids = _manufacturing_tool_ids()
    for binding in package.assembly_spec.bindings.node_bindings:
        if binding.binding_type != "tool_access":
            continue
        allowed_tool_ids = list(getattr(binding.payload, "allowed_tool_ids", []) or [])
        for tool_id in allowed_tool_ids:
            if tool_id in blocked_ids or tool_id.startswith("create_agent_"):
                issues.append(_contract_issue(
                    where="assembly.tool_access.manufacturing_tool",
                    summary=f"tool_access exposes create-agent manufacturing tool {tool_id}",
                    message="Produced AgentPackage must not expose create-agent manufacturing tools.",
                    path="assembly_spec.json",
                    expected="Only runtime builtin tools, package tools, and inherited MCP tools are exposed to produced agents.",
                    actual=tool_id,
                    repair_hint="Regenerate pattern assembly through create_agent_authoring(action='configure_pattern_assembly') without create-agent manufacturing tool ids.",
                    target_files=["assembly_spec.json"],
                    recommended_skill="12-assembly-pattern-system",
                ))
            elif tool_id not in legal_tool_ids:
                issues.append(_contract_issue(
                    where="assembly.tool_access.unknown_tool",
                    summary=f"tool_access references unknown tool {tool_id}",
                    message=f"{tool_id} is not an implemented runtime builtin, model, MCP, skill, or package tool.",
                    path="assembly_spec.json",
                    expected="tool_access.allowed_tool_ids contains runtime builtin, model, generated package, inherited MCP, or runtime skill tool ids.",
                    actual=tool_id,
                    repair_hint="Use create_agent_authoring(action='configure_pattern_assembly') with implemented runtime builtin, model, generated package, inherited MCP, or runtime skill tool ids. If the tool is an auxiliary model tool, bind it through create_agent_authoring(action='configure_model_bindings', tool_bindings=...). If the tool should be package-owned, create it through create_agent_authoring(action='upsert_package_tool') first; if it is a SkillHub skill, install it with skillhub when the skill should be bundled now.",
                    target_files=["assembly_spec.json", "contracts/tools.json", "tools/"],
                    recommended_skill="09-tools-system",
                ))
    return issues


def _legal_runtime_tool_ids(
    *,
    package_tools: dict[str, Any],
    inherited_mcp_tools: set[str],
    model_tool_ids: set[str],
) -> set[str]:
    return set(get_builtin_tool_ids()) | set(package_tools) | set(inherited_mcp_tools) | set(model_tool_ids) | {SKILL_TOOL_ID}


def _mcp_inheritance_materialization_issues(root: Path, package: Any, inherited_mcp_tools: set[str]) -> list[PackageValidationIssue]:
    referenced = _referenced_tool_access_ids(package)
    referenced_candidates = sorted(tool_id for tool_id in referenced if tool_id in inherited_mcp_tools)
    if not referenced_candidates:
        return []
    try:
        materialized = materialized_package_mcp_tool_ids(root)
    except Exception as exc:
        return [
            _contract_issue(
                where="mcp_inheritance.inspect",
                summary="referenced MCP tool inheritance could not be inspected",
                message=f"Unable to inspect package MCP extension materialization: {type(exc).__name__}: {exc}",
                path="extensions/extension_bindings.json",
                expected="Referenced registry MCP candidates are bound to the package before validation.",
                actual=f"{type(exc).__name__}: {exc}",
                repair_hint="Call create_agent_authoring(action='materialize_mcp_inheritance') after configuring MCP tool access, then rerun create_agent_validate.",
                target_files=["contracts/tools.json", "extensions/extension_bindings.json"],
                recommended_skill="09-tools-system",
            )
        ]
    missing = sorted(set(referenced_candidates) - set(materialized))
    if not missing:
        return []
    return [
        _contract_issue(
            where="mcp_inheritance.materialized",
            summary="referenced MCP tools have not been inherited into the package",
            message=f"tool_access references factory MCP candidates that are not materialized in package extensions: {', '.join(missing)}",
            path="extensions/extension_bindings.json",
            expected="create_agent_authoring(action='materialize_mcp_inheritance') has written the package MCP registry bindings.",
            actual=", ".join(missing),
            repair_hint="Call create_agent_authoring(action='materialize_mcp_inheritance') before full_static validation or publish.",
            target_files=["contracts/tools.json", "extensions/extension_bindings.json"],
            recommended_skill="09-tools-system",
            repair_template={
                "tool": "create_agent_authoring",
                "arguments": {"action": "materialize_mcp_inheritance"},
            },
        )
    ]


def _referenced_tool_access_ids(package: Any) -> set[str]:
    ids: set[str] = set()
    for binding in package.assembly_spec.bindings.node_bindings:
        if binding.binding_type != "tool_access":
            continue
        ids.update(str(tool_id).strip() for tool_id in (getattr(binding.payload, "allowed_tool_ids", []) or []) if str(tool_id).strip())
    return ids


def _scheduler_tool_target_issues(
    package: Any,
    package_tools: dict[str, Any],
    inherited_mcp_tools: set[str],
    model_tool_ids: set[str],
) -> list[PackageValidationIssue]:
    issues: list[PackageValidationIssue] = []
    legal_tool_ids = _legal_runtime_tool_ids(
        package_tools=package_tools,
        inherited_mcp_tools=inherited_mcp_tools,
        model_tool_ids=model_tool_ids,
    )
    contract = package.contracts.get("scheduler_seed")
    if not isinstance(contract, SchedulerSeedContract):
        return issues
    for seed in contract.config.seeds:
        if seed.target.target_type != "tool_call":
            continue
        tool_id = str(seed.target.payload.get("tool_id") or "").strip()
        if tool_id and tool_id not in legal_tool_ids:
            issues.append(_contract_issue(
                where="scheduler_seed.target_tool",
                summary=f"scheduler seed {seed.seed_id} targets unknown tool {tool_id}",
                message="scheduler_seed tool_call targets must point to an executable runtime builtin, package tool, inherited MCP tool, or runtime skill tool.",
                path="contracts/scheduler_seed.json",
                expected="scheduler_seed.target.payload.tool_id is executable.",
                actual=tool_id,
                repair_hint="Regenerate the scheduler seed through create_agent_authoring(action='upsert_scheduler_seed') after creating the referenced package tool or choosing an executable runtime tool id.",
                target_files=["contracts/scheduler_seed.json", "tools/"],
                recommended_skill="15-scheduler-seed-system",
            ))
    return issues


def _scheduler_package_tool_ids(package: Any, package_tools: dict[str, Any]) -> list[str]:
    contract = package.contracts.get("scheduler_seed")
    if not isinstance(contract, SchedulerSeedContract):
        return []
    ids: list[str] = []
    for seed in contract.config.seeds:
        if seed.target.target_type == "tool_call":
            tool_id = str(seed.target.payload.get("tool_id") or "").strip()
            if tool_id in package_tools:
                ids.append(tool_id)
    return ids


def _tool_spec_mismatches(left: Any, right: Any) -> list[str]:
    left_payload = left.model_dump(mode="json") if hasattr(left, "model_dump") else dict(left)
    right_payload = right.model_dump(mode="json") if hasattr(right, "model_dump") else dict(right)
    keys = ("description", "entrypoint", "input_schema", "output_schema", "resources", "risk_level", "concurrent")
    return [key for key in keys if left_payload.get(key) != right_payload.get(key)]


def _tool_spec_mismatch_details(left: Any, right: Any, keys: list[str]) -> dict[str, dict[str, Any]]:
    left_payload = left.model_dump(mode="json") if hasattr(left, "model_dump") else dict(left)
    right_payload = right.model_dump(mode="json") if hasattr(right, "model_dump") else dict(right)
    return {
        key: {
            "package_manifest": left_payload.get(key),
            "assembly_spec": right_payload.get(key),
        }
        for key in keys
    }


def _manufacturing_tool_ids() -> set[str]:
    return {
        "create_agent_authoring",
        "create_agent_control",
        "create_agent_stage",
        "create_agent_probe_tool",
    }


def _inherited_mcp_tool_ids() -> set[str]:
    try:
        return factory_mcp_tool_ids()
    except Exception:
        return set()


def _read_probe_state(root: Path) -> PackageToolProbeState:
    path = root / ".factory" / "tool_probe.json"
    if not path.is_file():
        return PackageToolProbeState()
    try:
        return PackageToolProbeState.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception:
        return PackageToolProbeState()


def _contract_issue(
    *,
    where: str,
    summary: str,
    message: str,
    severity: str = "blocking",
    path: str,
    expected: str,
    actual: str,
    repair_hint: str,
    target_files: list[str],
    recommended_skill: str,
    recommended_resources: list[str] | None = None,
    schema_path: str = "",
    invalid_value_path: str = "",
    expected_shape: dict[str, Any] | None = None,
    repair_template: dict[str, Any] | None = None,
    replace_strategy: str = "",
    details: dict[str, Any] | None = None,
) -> PackageValidationIssue:
    return PackageValidationIssue(
        where=where,
        summary=summary,
        message=message,
        severity=severity,  # type: ignore[arg-type]
        path=path,
        expected=expected,
        actual=actual,
        repair_hint=repair_hint,
        target_files=target_files,
        recommended_skill=recommended_skill,
        recommended_resources=recommended_resources or [],
        schema_path=schema_path,
        invalid_value_path=invalid_value_path,
        expected_shape=expected_shape or {},
        repair_template=repair_template or {},
        replace_strategy=replace_strategy,  # type: ignore[arg-type]
        details=details or {},
    )


def _probe_issue(
    *,
    tool_id: str,
    summary: str,
    actual: str,
    repair_hint: str,
    details: dict[str, Any] | None = None,
) -> PackageValidationIssue:
    return _contract_issue(
        where="package_tool_probe",
        summary=summary,
        message=summary,
        path=package_tool_directory_path(tool_id),
        expected="Generated package tools have fresh successful-path create_agent_probe_tool evidence before publish.",
        actual=actual,
        repair_hint=repair_hint,
        target_files=[package_tool_manifest_path(tool_id), package_tool_source_path(tool_id), "assembly_spec.json"],
        recommended_skill="10-package-tool-system",
        details=details,
    )


def _issues_report(
    root: Path,
    issues: list[PackageValidationIssue],
    *,
    scope: ValidationScope,
    changed_files: list[str],
    summary: str,
) -> PackageValidationReport:
    return _with_scope(
        PackageValidationReport(
            package_root=str(root),
            summary=summary,
            issues=issues,
        ),
        scope=scope,
        changed_files=changed_files,
    )


def _relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.name

def _exception_details(exc: Exception) -> dict[str, Any]:
    return {"exception_type": type(exc).__name__}


def _recommended_skill(where: str, target_files: list[str]) -> str:
    targets = " ".join(target_files)
    if where == "assembly.compile":
        return "12-assembly-pattern-system"
    if "tools/" in targets:
        return "10-package-tool-system"
    if where == "runtime_contracts.build" or where.startswith("runtime_contracts."):
        return _skill_for_targets(target_files)
    if where == "python_syntax.compile":
        return "10-package-tool-system" if "tools/" in targets else "17-final-validation-repair"
    return _skill_for_targets(target_files) if target_files else "17-final-validation-repair"


def _recommended_resources(skill: str, target_files: list[str]) -> list[str]:
    del target_files
    if skill == "01-package-identity-system":
        return [
            "references/package_identity.schema.json",
            "references/package_identity.repair_hints.md",
        ]
    if skill == "10-package-tool-system":
        return [
            "references/package_tool_system.schema.json",
            "examples/package_tool_system.capability.json",
            "references/package_tool_system.repair_hints.md",
        ]
    if skill == "12-assembly-pattern-system":
        return [
            "references/assembly_pattern_system.schema.json",
            "examples/assembly_pattern_system.capability.json",
            "references/assembly_pattern_system.repair_hints.md",
        ]
    artifact = {
        "02-model-system": "model_system",
        "05-resources-system": "resources_system",
        "06-context-system": "context_system",
        "08-knowledge-system": "knowledge_system",
        "09-tools-system": "tools_system",
        "14-scheduler-system": "scheduler_system",
        "15-scheduler-seed-system": "scheduler_seed_system",
        "17-final-validation-repair": "final_validation",
    }.get(skill, skill.replace("-", "_"))
    return [f"references/{artifact}.repair_hints.md"]


def _skill_for_targets(target_files: list[str]) -> str:
    targets = " ".join(target_files)
    pairs = [
        ("contracts/model", "02-model-system"),
        ("contracts/dependencies", "02-model-system"),
        ("contracts/resources", "05-resources-system"),
        ("contracts/context", "06-context-system"),
        ("knowledge/", "08-knowledge-system"),
        ("contracts/tools", "10-package-tool-system"),
        ("contracts/scheduler_seed", "15-scheduler-seed-system"),
        ("contracts/scheduler", "14-scheduler-system"),
        ("agent_package.json", "01-package-identity-system"),
        ("assembly_spec.json", "12-assembly-pattern-system"),
    ]
    for needle, skill in pairs:
        if needle in targets:
            return skill
    return "17-final-validation-repair"


def _expected_for_where(where: str) -> str:
    return {
        "package.load": "AgentPackageLoader can load agent_package.json and referenced package files.",
        "runtime_contracts.build": "RuntimeBuildPlanner can build all declared RuntimeContracts.",
        "assembly.compile": "AgentAssemblyCompiler can compile the declared assembly and patterns.",
    }.get(where, "validation check passes")


def _repair_hint_for_where(where: str) -> str:
    return {
        "package.load": "Repair manifest paths and package structure, then rerun package validation.",
        "runtime_contracts.build": "Repair contract schema through create_agent_authoring. For scaffold-owned contracts, use create_agent_authoring(action='reset_contract', contract_key=...).",
        "assembly.compile": "Repair assembly through create_agent_authoring or the target files indicated by validator evidence.",
    }.get(where, "Repair the target files indicated by the validation issue.")


def _semantic_completeness_report(
    root: Path,
    package: Any,
    *,
    scope: ValidationScope,
    changed_files: list[str],
) -> PackageValidationReport | None:
    """Check that the package has actual logic, not just empty scaffold defaults."""
    issues: list[PackageValidationIssue] = []

    bindings = package.assembly_spec.bindings
    bindings_dict = bindings.model_dump(mode="json") if hasattr(bindings, "model_dump") else (dict(bindings) if bindings else {})
    has_bindings = any(v for v in bindings_dict.values() if v)
    if not has_bindings:
        issues.append(PackageValidationIssue(
            where="semantic.bindings_empty",
            summary="assembly_spec has empty bindings",
            message="The assembly must bind model and tool services to function.",
            path="assembly_spec.json",
            expected="assembly_spec.bindings with model and/or tool service bindings",
            actual="bindings are empty or all null",
            repair_hint="Configure the selected built-in pattern through create_agent_authoring(action='configure_pattern_assembly').",
            target_files=["assembly_spec.json"],
            recommended_skill="12-assembly-pattern-system",
        ))

    if not issues:
        return None

    return _with_scope(
        PackageValidationReport(
            package_root=str(root),
            summary="Semantic completeness check failed: " + "; ".join(issue.summary for issue in issues[:3]),
            issues=issues,
        ),
        scope=scope,
        changed_files=changed_files,
    )
