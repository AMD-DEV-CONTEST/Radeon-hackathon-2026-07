from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import shutil
from uuid import uuid4
from typing import Any

from agent_factory.assembly.compiler import AgentAssemblyCompiler
from agent_factory.agent_registry import refresh_agent_registry_index
from agent_factory.create_agent.models import CreateAgentPublishDecision
from agent_factory.create_agent.package_paths import is_transient_package_path
from agent_factory.create_agent.stage_sync import sync_publish_stage
from agent_factory.create_agent.validation_state import package_fingerprint
from agent_factory.create_agent.workspace import CreateAgentWorkspace
from agent_factory.environment_system import EnvironmentResolver
from agent_factory.resource_system import ResourceStore
from agent_factory.runtime_contracts import ResourcesContract
from agent_factory.paths import factory_artifact_path
from agent_factory.package_distribution import copy_publishable_package
from agent_factory.runtime_contracts import AgentPackageLoader, RuntimeBuildPlanner
from agent_factory.runtime_contracts.builtins import default_runtime_contract_registry
from agent_factory.runtime_kernel.kernel import RuntimeKernelFacade
from agent_factory.runtime_kernel.persistence import (
    LangGraphCheckpointerConfig,
    LangGraphStoreConfig,
    close_shared_sqlite_checkpointers,
)


CREATE_AGENT_PACKAGE_REGISTRY_RESOURCE = "create_agent_package_registry"


def confirm_and_publish(
    *,
    workspace: CreateAgentWorkspace,
    confirmation: str,
    registry_root: Path | None = None,
) -> dict[str, Any]:
    confirmation_text = str(confirmation or "").strip()
    if not confirmation_text:
        raise ValueError("confirmation is required")
    validation = workspace.read_validation()
    workspace.write_publish_decision(
        CreateAgentPublishDecision(
            decision="approve",
            input_text=confirmation_text,
            package_fingerprint=package_fingerprint(workspace.root),
            validation_scope=validation.validation_scope if validation else "",
            validation_status=validation.status if validation else "",
        )
    )
    return publish_workspace(
        workspace=workspace,
        confirmation=confirmation_text,
        registry_root=registry_root,
    )


def publish_workspace(
    *,
    workspace: CreateAgentWorkspace,
    confirmation: str,
    registry_root: Path | None = None,
) -> dict[str, Any]:
    confirmation_text = str(confirmation or "").strip()
    if not confirmation_text:
        raise ValueError("confirmation is required")
    registry_root = registry_root or factory_artifact_path("packages")
    _assert_publish_ready(workspace)
    package = AgentPackageLoader().load_path(workspace.package_manifest_path())
    package_id = _package_id(package)
    resource_contract = ResourcesContract.model_validate(package.contracts.get("resources") or {})
    target = _safe_child(registry_root, package_id)
    staging_root = _safe_child(registry_root, ".publish_staging")
    staging = staging_root / f"{package_id}-{uuid4().hex}"
    staging_root.mkdir(parents=True, exist_ok=True)
    if staging.exists():
        shutil.rmtree(staging)
    copy_publishable_package(workspace.root, staging)
    environment_resolver = EnvironmentResolver()
    environment_resolver.materialize_lock_without_installation(staging)
    environment_resolver.require_ready(staging)
    _assert_runtime_ready(staging)
    _prune_transient_paths(staging)

    registry_root.mkdir(parents=True, exist_ok=True)
    backup = _safe_child(registry_root, f".publish_backup_{package_id}_{uuid4().hex}")
    try:
        if target.exists():
            target.replace(backup)
        staging.replace(target)
        ResourceStore().transfer(workspace.root.name, package_id, resource_contract.config.resource_descriptors)
    except Exception:
        if target.exists():
            shutil.rmtree(target)
        if backup.exists():
            backup.replace(target)
        raise
    finally:
        if backup.exists():
            shutil.rmtree(backup)
        if staging.exists():
            shutil.rmtree(staging)

    published_at = datetime.now(UTC).isoformat()
    report = {
        "version": "agent_package_publish_report.v0",
        "status": "available",
        "package_id": package_id,
        "source_workspace": str(workspace.root),
        "package_path": str(target),
        "manifest_path": str(target / "agent_package.json"),
        "published_at": published_at,
        "confirmation": confirmation_text,
        "validation": workspace.read_validation().to_digest().model_dump(mode="json") if workspace.read_validation() else None,
        "package_fingerprint": package_fingerprint(target),
    }
    report_path = target / "package_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    workspace.write_publish_report(report)
    sync_publish_stage(workspace)
    agent_registry_refresh = _refresh_agent_registry_index(package_id)
    return {
        "published": True,
        "package_id": package_id,
        "package_path": str(target),
        "manifest_path": str(target / "agent_package.json"),
        "published_at": published_at,
        "report_path": str(report_path),
        "publish_state_path": str(workspace.publish_path),
        "agent_registry_refresh": agent_registry_refresh,
    }


def _refresh_agent_registry_index(package_id: str) -> dict[str, Any]:
    try:
        return refresh_agent_registry_index(package_id)
    except Exception as exc:
        return {"status": "failed", "message": f"{type(exc).__name__}: {exc}"}


def _assert_publish_ready(workspace: CreateAgentWorkspace) -> None:
    active = workspace.read_system_state().active_stage()
    if active is None or active.system_id != "validation_publish":
        raise ValueError("publish requires active focus validation_publish")
    validation = workspace.read_validation()
    if validation is None or validation.status != "passed":
        raise ValueError("publish requires validation to pass")
    validation_state = workspace.read_validation_state()
    if validation_state is None:
        raise ValueError("publish requires validation fingerprint state")
    if validation_state.validation_scope != "full_static":
        raise ValueError("publish requires the latest package-changing validation to be full_static")
    current_fingerprint = package_fingerprint(workspace.root)
    if current_fingerprint != validation_state.package_fingerprint:
        raise ValueError("package files changed after validation; run final validation again before publishing")
    decision = workspace.read_publish_decision()
    if decision.decision != "approve":
        raise ValueError("publish requires explicit user approval from the Web publish API")
    if decision.package_fingerprint != current_fingerprint:
        raise ValueError("package files changed after user approval; run final validation and publish from the Web UI again")
    if decision.validation_scope != "full_static" or decision.validation_status != "passed":
        raise ValueError("publish approval must correspond to a passed full_static validation")
    if not workspace.package_manifest_path().is_file():
        raise ValueError("agent_package.json is missing")


def _assert_runtime_ready(package_root: Path) -> None:
    package = AgentPackageLoader().load_path(package_root / "agent_package.json")
    facade = RuntimeKernelFacade(
        checkpointer_config=LangGraphCheckpointerConfig(backend="memory"),
        memory_store_config=LangGraphStoreConfig(backend="memory"),
    )
    try:
        compiler = AgentAssemblyCompiler(facade=facade)
        runtime_build = RuntimeBuildPlanner(registry=default_runtime_contract_registry()).build(
            package,
            base_services=facade.instance.services,
        )
        compiler.compile(package.assembly_spec, runtime_build=runtime_build)
    finally:
        try:
            facade.shutdown()
        finally:
            close_shared_sqlite_checkpointers(under_root=package_root)


def _package_id(package: Any) -> str:
    value = str(getattr(package.manifest.agent, "id", "") or "").strip()
    if not value or value in {".", ".."} or "/" in value or "\\" in value:
        raise ValueError(f"invalid package id: {value!r}")
    return value


def _safe_child(root: Path, child: str) -> Path:
    target = (root / child).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"path escapes package registry: {child}") from exc
    return target


def _prune_transient_paths(root: Path) -> None:
    for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        try:
            relative = path.relative_to(root).as_posix()
        except ValueError:
            continue
        if not is_transient_package_path(relative):
            continue
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()
