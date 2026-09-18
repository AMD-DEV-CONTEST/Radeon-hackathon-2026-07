"""Create and constrain the local runtime workspace."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from buildguard.config import Settings
from buildguard.logging_system.jsonl_writer import atomic_write_json
from buildguard.logging_system.run_manifest import RunManifest


class WorkspaceManager:
    """Resolve all runtime artifacts beneath a single trusted root."""

    DIRECTORIES = (
        "uploads",
        "projects",
        "knowledge",
        "cameras",
        "cameras/normal_frames",
        "events/images",
        "events/clips",
        "events/masks",
        "reports",
        "indexes",
        "database",
        "logs/agent",
        "logs/tools",
        "logs/security",
        "logs/performance",
        "runs",
    )

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def resolve(self, relative_path: str | Path) -> Path:
        candidate = (self.root / relative_path).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise ValueError(f"Path escapes workspace: {relative_path}") from exc
        return candidate

    def initialize(self) -> dict[str, Path]:
        self.root.mkdir(parents=True, exist_ok=True)
        paths: dict[str, Path] = {}
        for relative in self.DIRECTORIES:
            path = self.resolve(relative)
            path.mkdir(parents=True, exist_ok=True)
            paths[relative] = path
        return paths

    @staticmethod
    def generate_run_id() -> str:
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        return f"{timestamp}-{uuid4().hex[:12]}"

    def start_run(self, settings: Settings) -> RunManifest:
        self.initialize()
        run_id = self.generate_run_id()
        run_directory = self.resolve(Path("runs") / run_id)
        run_directory.mkdir(parents=True, exist_ok=False)
        snapshot_path = run_directory / "config_snapshot.json"
        manifest_path = run_directory / "run_manifest.json"
        atomic_write_json(snapshot_path, settings.safe_dump())
        manifest = RunManifest(
            run_id=run_id,
            project_name=settings.app.name,
            environment=settings.app.environment,
            workspace_path=self.root,
            config_snapshot_path=snapshot_path,
        )
        atomic_write_json(manifest_path, manifest)
        return manifest

