"""Conservative age-based artifact cleanup."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import BaseModel, Field

from buildguard.config import RetentionConfig
from buildguard.workspace.manager import WorkspaceManager


class RetentionResult(BaseModel):
    dry_run: bool
    candidates: list[Path] = Field(default_factory=list)
    deleted: list[Path] = Field(default_factory=list)
    errors: dict[str, str] = Field(default_factory=dict)


class RetentionCleaner:
    """Delete only regular files in explicitly mapped workspace directories."""

    def __init__(self, manager: WorkspaceManager, config: RetentionConfig) -> None:
        self.manager = manager
        self.config = config

    def cleanup(self, *, dry_run: bool = True, now: datetime | None = None) -> RetentionResult:
        if not dry_run and not self.config.enabled:
            raise ValueError("Retention deletion is disabled by configuration")
        current = now or datetime.now(UTC)
        result = RetentionResult(dry_run=dry_run)
        policies = {
            "events/images": self.config.event_images_days,
            "events/clips": self.config.event_clips_days,
            "cameras/normal_frames": self.config.normal_frames_days,
            "logs/performance": self.config.performance_logs_days,
            "logs/security": self.config.audit_logs_days,
        }
        for relative, days in policies.items():
            directory = self.manager.resolve(relative)
            if not directory.exists():
                continue
            cutoff = current - timedelta(days=days)
            for path in directory.rglob("*"):
                if not path.is_file():
                    continue
                modified = datetime.fromtimestamp(path.stat().st_mtime, UTC)
                if modified > cutoff:
                    continue
                resolved = self.manager.resolve(path.relative_to(self.manager.root))
                result.candidates.append(resolved)
                if dry_run:
                    continue
                try:
                    resolved.unlink()
                    result.deleted.append(resolved)
                except OSError as exc:
                    result.errors[str(resolved)] = str(exc)
        return result
