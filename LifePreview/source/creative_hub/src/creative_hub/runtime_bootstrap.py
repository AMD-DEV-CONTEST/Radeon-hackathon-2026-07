"""Shared runtime configuration for Shidu workers and API adapters.

This module intentionally contains no HTTP application construction.  The
remaining deployment only needs database configuration, the frozen atomic
capability registry, and cost-budget policy loading.
"""

from __future__ import annotations

import importlib.metadata
import os
from pathlib import Path

from atomic_runtime import (
    CapabilityDiscoveryError,
    CapabilityRegistry,
    discover_and_register,
)
from sqlalchemy import URL

from .cost_budgets import BudgetConfigurationError, CostBudgetPolicy


def _read_secret(path_value: str) -> str:
    value = Path(path_value).read_text(encoding="utf-8").strip()
    if not value or any(
        ord(character) < 32 or ord(character) == 127
        for character in value
    ):
        raise RuntimeError("runtime configuration is invalid")
    return value


def database_url(prefix: str) -> str:
    """Resolve one database URL without importing a retired HTTP surface."""

    direct = os.getenv(f"{prefix}_DATABASE_URL")
    if direct:
        return direct
    try:
        username = _read_secret(os.environ[f"{prefix}_POSTGRES_USER_FILE"])
        password = _read_secret(
            os.environ[f"{prefix}_POSTGRES_PASSWORD_FILE"]
        )
        database = _read_secret(os.environ[f"{prefix}_POSTGRES_DB_FILE"])
    except (KeyError, OSError, UnicodeError, RuntimeError):
        raise RuntimeError("runtime configuration is invalid") from None
    return URL.create(
        "postgresql+psycopg",
        username=username,
        password=password,
        host=os.getenv(f"{prefix}_POSTGRES_HOST", "postgres"),
        port=5432,
        database=database,
    ).render_as_string(hide_password=False)


def load_cost_budget_policy() -> CostBudgetPolicy:
    policy_path = os.getenv("CREATIVE_HUB_COST_BUDGET_POLICY_FILE")
    if not policy_path:
        return CostBudgetPolicy(())
    try:
        return CostBudgetPolicy.from_json_file(policy_path)
    except BudgetConfigurationError:
        raise RuntimeError("runtime configuration is invalid") from None


def load_atomic_capability_registry(
    *,
    development_source_fallback: bool = False,
) -> CapabilityRegistry:
    """Load only the capability plugins required by the retained DAG."""

    registry = CapabilityRegistry()
    allowlist = [
        "douyin-creative-hub",
        "douyin-drama-factory",
    ]
    try:
        importlib.metadata.distribution("douyin-personal-analysis")
    except importlib.metadata.PackageNotFoundError:
        pass
    else:
        allowlist.append("douyin-personal-analysis")
    try:
        discover_and_register(
            registry,
            allowlist=tuple(allowlist),
            freeze=False,
        )
    except CapabilityDiscoveryError:
        if not development_source_fallback:
            raise
        from drama.atomic_plugin import build_plugin as build_drama_plugin

        from .h3_atomic_runtime import build_plugin as build_h3_plugin
        from .quality_atomic import build_plugin as build_quality_plugin

        plugins = [
            build_quality_plugin(),
            build_drama_plugin(),
            build_h3_plugin(),
        ]
        try:
            from douyin_analysis.atomic_plugin import (
                build_plugin as build_analysis_plugin,
            )
        except ImportError:
            pass
        else:
            plugins.append(build_analysis_plugin())
        registry.register_plugins_and_freeze(plugins)
    else:
        from .h3_atomic_runtime import H3_OPERATION_TYPES, build_plugin

        installed = {
            registration.spec.op_type
            for registration in registry.registrations.values()
        }
        missing_h3_operations = set(H3_OPERATION_TYPES) - installed
        if missing_h3_operations:
            if missing_h3_operations != set(H3_OPERATION_TYPES):
                raise RuntimeError("H3 capability registration is incomplete")
            registry.register_plugin(build_plugin())
        registry.freeze()
    return registry


__all__ = [
    "database_url",
    "load_atomic_capability_registry",
    "load_cost_budget_policy",
]
