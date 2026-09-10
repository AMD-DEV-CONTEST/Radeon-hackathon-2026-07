"""Trusted production compiler-context bootstrap for interactive services."""

from __future__ import annotations

import os
import stat
from typing import Any

from specstyle.errors import DomainError, InfrastructureError
from specstyle.generation.model_approval import verify_pipeline_supply
from specstyle.observability.environment import capture_environment
from specstyle.production.context_config import (
    load_production_context_config,
    make_production_compiler_context_factory,
)
from specstyle.production.supply_config import load_production_supply_config
from specstyle.spec.compiled_models import CompilerContext
from specstyle.workflow.production_service import load_production_compiler_context

__all__ = ("load_production_ui_compiler_context",)


def _validate_roots(descriptors: tuple[object, ...]) -> tuple[int, int, int]:
    if any(type(fd) is not int or fd < 0 for fd in descriptors):
        raise DomainError("invalid production bootstrap roots")
    identities: list[tuple[int, int]] = []
    try:
        for fd in descriptors:
            info = os.fstat(fd)
            if not stat.S_ISDIR(info.st_mode):
                raise DomainError("invalid production bootstrap roots")
            identities.append((info.st_dev, info.st_ino))
    except OSError:
        raise InfrastructureError("production bootstrap unavailable") from None
    if len(set(identities)) != len(identities):
        raise DomainError("production bootstrap roots must be distinct")
    return descriptors  # type: ignore[return-value]


def load_production_ui_compiler_context(
    config_root_fd: int,
    evidence_root_fd: int,
    model_root_fd: int,
    /,
    *,
    torch_module: Any | None = None,
    diffusers_module: Any | None = None,
) -> CompilerContext:
    """Build a detached context and close only the verified supply it creates."""
    config_fd, evidence_fd, models_fd = _validate_roots(
        (config_root_fd, evidence_root_fd, model_root_fd)
    )
    context_config = load_production_context_config(config_fd, evidence_fd)
    supply_config = load_production_supply_config(config_fd)
    supply = verify_pipeline_supply(
        models_fd,
        supply_config.graph,
        supply_config.manifests,
        supply_config.approvals,
    )
    primary: BaseException | None = None
    try:
        environment = capture_environment()
        factory = make_production_compiler_context_factory(
            context_config, environment, supply_config.graph
        )
        return load_production_compiler_context(
            supply,
            supply_config.graph,
            environment,
            factory,
            torch_module=torch_module,
            diffusers_module=diffusers_module,
        )
    except BaseException as error:
        primary = error
        raise
    finally:
        try:
            supply.close()
        except (DomainError, InfrastructureError):
            if primary is None:
                raise
            primary.add_note("production supply cleanup failed")
