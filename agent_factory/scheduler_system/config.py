from __future__ import annotations

import hashlib
import os
from pathlib import Path

from agent_factory.paths import project_root
from agent_factory.scheduler_system.schema import SchedulerContractConfig, SchedulerFailurePolicy


def default_factory_scheduler_config() -> SchedulerContractConfig:
    return SchedulerContractConfig(
        store_backend=os.getenv("AGENTFACTORY_SCHEDULER_STORE_BACKEND", "sqlite"),
        store_path=_env_path(
            "AGENTFACTORY_SCHEDULER_STORE_PATH",
            str(project_root() / ".agentfactory" / "scheduler" / "factory.sqlite"),
        ),
        timezone=os.getenv("AGENTFACTORY_SCHEDULER_TIMEZONE", "Asia/Shanghai"),
        default_timeout_seconds=_env_int("AGENTFACTORY_SCHEDULER_DEFAULT_TIMEOUT_SECONDS", 900),
        unattended_policy=os.getenv(
            "AGENTFACTORY_SCHEDULER_UNATTENDED_POLICY",
            "deny_if_approval_required",
        ),
        default_failure_policy=SchedulerFailurePolicy(
            enabled=_env_bool("AGENTFACTORY_SCHEDULER_FAILURE_AUTO_PAUSE_ENABLED", True),
            max_consecutive_failures=_env_int("AGENTFACTORY_SCHEDULER_MAX_CONSECUTIVE_FAILURES", 3),
        ),
    )


def scheduler_enabled_from_env() -> bool:
    raw = os.getenv("AGENTFACTORY_SCHEDULER_ENABLED", "true").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def factory_scheduler_owner_id() -> str:
    root = str(project_root().resolve())
    digest = hashlib.sha1(root.encode("utf-8")).hexdigest()[:12]
    return f"{project_root().name}-{digest}"


def _env_path(name: str, default: str) -> str:
    value = os.getenv(name, default).strip()
    return str(Path(value).expanduser()) if value else default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(value, 1)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return default
