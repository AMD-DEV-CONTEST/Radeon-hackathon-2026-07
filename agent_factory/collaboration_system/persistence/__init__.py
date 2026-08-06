"""Persistence boundary for the unified background-task lifecycle."""

from agent_factory.collaboration_system.persistence.event_repository import EventRepository
from agent_factory.collaboration_system.persistence.legacy_migration import (
    LegacyTaskMigrationReport,
    migrate_legacy_background_tasks,
)
from agent_factory.collaboration_system.persistence.schema import ensure_background_task_schema
from agent_factory.collaboration_system.persistence.session_repository import SessionRepository
from agent_factory.collaboration_system.persistence.settings_repository import SchedulerSettingsRepository
from agent_factory.collaboration_system.persistence.task_repository import TaskRepository

__all__ = [
    "EventRepository",
    "LegacyTaskMigrationReport",
    "SchedulerSettingsRepository",
    "SessionRepository",
    "TaskRepository",
    "ensure_background_task_schema",
    "migrate_legacy_background_tasks",
]
