"""Alembic launchers retained for the Shidu database closure."""

from __future__ import annotations

import os

from alembic import command
from alembic.config import Config

from .runtime_bootstrap import database_url


def _run_migration(config_path: str, target_database_url: str) -> None:
    configuration = Config(config_path)
    configuration.set_main_option("sqlalchemy.url", target_database_url)
    command.upgrade(configuration, "head")


def migrate_hub() -> None:
    """Upgrade retained hub tables used by credentials and shared metadata."""

    _run_migration(
        os.getenv(
            "CREATIVE_HUB_ALEMBIC_CONFIG",
            "/workspace/creative_hub/alembic.ini",
        ),
        database_url("CREATIVE_HUB_MIGRATION"),
    )


def migrate_orchestration() -> None:
    """Upgrade the orchestration, Shidu, DAG, QC, and artifact schema."""

    _run_migration(
        os.getenv(
            "CREATIVE_ORCHESTRATION_ALEMBIC_CONFIG",
            "/workspace/creative_hub/orchestration-alembic.ini",
        ),
        database_url("CREATIVE_HUB_MIGRATION"),
    )


__all__ = ["migrate_hub", "migrate_orchestration"]
