"""Stage J — Backup & Recovery Service.

Creates timestamped backups of the SQLite database, vector index, and
project configuration.  Supports on-demand backup, scheduled auto-backup,
backup listing, and recovery (restore from a backup point).
"""

from __future__ import annotations

import gzip
import json
import logging
import shutil
import time
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import Settings

logger = logging.getLogger("projectpack.backup")


class BackupService:
    """Manages backup creation, listing, cleanup, and recovery."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._backup_root = settings.backup_root
        self._backup_root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # backup creation
    # ------------------------------------------------------------------

    def create_backup(self, label: str = "") -> dict[str, Any]:
        """Create a full backup and return metadata.

        Backs up:
        1. SQLite database
        2. Vector DB directory
        3. Project configuration
        """
        if label and not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", label):
            raise ValueError("Backup label may contain only letters, digits, underscores, and hyphens")
        ts = datetime.now(timezone.utc)
        stamp = ts.strftime("%Y%m%dT%H%M%SZ")
        dir_name = f"backup-{stamp}" + (f"-{label}" if label else "")
        backup_dir = self._backup_root / dir_name
        suffix = 1
        while backup_dir.exists():
            backup_dir = self._backup_root / f"{dir_name}-{suffix}"
            suffix += 1
        backup_dir.mkdir(parents=True, exist_ok=False)

        files_backed_up: list[str] = []
        errors: list[str] = []
        total_size = 0

        # 1. SQLite DB
        try:
            sqlite_path = self._settings.sqlite_path
            if sqlite_path.is_dir():
                sqlite_path = sqlite_path / "projectpack.db"
            if sqlite_path.exists():
                dest = backup_dir / "database.db"
                shutil.copy2(sqlite_path, dest)
                total_size += dest.stat().st_size
                files_backed_up.append(str(sqlite_path))
        except Exception as exc:
            logger.error("Backup: failed to copy SQLite: %s", exc)
            errors.append(f"sqlite: {exc}")

        # 2. Vector DB
        try:
            vector_src = self._settings.vector_db_root
            vector_dest = backup_dir / "vector_db"
            if vector_src.exists():
                shutil.copytree(
                    vector_src,
                    vector_dest,
                    dirs_exist_ok=True,
                )
                total_size += sum(
                    f.stat().st_size
                    for f in vector_dest.rglob("*")
                    if f.is_file()
                )
                files_backed_up.append(str(vector_src))
        except Exception as exc:
            logger.error("Backup: failed to copy vector DB: %s", exc)
            errors.append(f"vector_db: {exc}")

        # 3. Project root metadata (config files only, not full content)
        try:
            project_src = self._settings.project_root
            if project_src.exists():
                # Copy only .json and .yaml config files
                for ext in ("*.json", "*.yaml", "*.yml", "*.toml"):
                    for p in project_src.glob(ext):
                        rel = p.relative_to(project_src)
                        dest = backup_dir / "projects" / rel
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(p, dest)
                        total_size += dest.stat().st_size
                        files_backed_up.append(str(p))
        except Exception as exc:
            logger.error("Backup: failed to copy project configs: %s", exc)
            errors.append(f"projects: {exc}")

        # 4. Write backup manifest
        manifest = {
            "timestamp": stamp,
            "label": label,
            "files": files_backed_up,
            "total_size_bytes": total_size,
            "errors": errors,
            "status": "success" if not errors else "partial",
        }
        (backup_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )

        logger.info(
            "Backup created: %s (%d files, %d bytes, %d errors)",
            dir_name,
            len(files_backed_up),
            total_size,
            len(errors),
        )
        return manifest

    # ------------------------------------------------------------------
    # listing
    # ------------------------------------------------------------------

    def list_backups(self) -> list[dict[str, Any]]:
        """List all available backups sorted by timestamp (newest first)."""
        results: list[dict[str, Any]] = []
        for entry in sorted(
            self._backup_root.iterdir(), key=lambda p: p.name, reverse=True
        ):
            if entry.is_dir() and entry.name.startswith("backup-"):
                manifest = entry / "manifest.json"
                if manifest.exists():
                    try:
                        data = json.loads(manifest.read_text(encoding="utf-8"))
                        data["backup_dir"] = str(entry)
                        results.append(data)
                    except Exception:
                        results.append(
                            {
                                "backup_dir": str(entry),
                                "name": entry.name,
                                "status": "corrupt",
                            }
                        )
                else:
                    results.append(
                        {
                            "backup_dir": str(entry),
                            "name": entry.name,
                            "status": "no_manifest",
                        }
                    )
        return results

    # ------------------------------------------------------------------
    # recovery
    # ------------------------------------------------------------------

    def restore(self, backup_dir: str, *, dry_run: bool = False) -> dict[str, Any]:
        """Restore from a backup directory.

        Args:
            backup_dir: Path to the backup directory.
            dry_run: If True, only validate without writing.

        Returns:
            Dict with restore results.
        """
        bp = Path(backup_dir).resolve()
        backup_root = self._backup_root.resolve()
        try:
            bp.relative_to(backup_root)
        except ValueError as exc:
            raise ValueError("Backup directory must be located under the configured backup root") from exc
        if not bp.name.startswith("backup-"):
            raise ValueError("Backup directory has an invalid name")
        if not bp.exists():
            raise FileNotFoundError(f"Backup directory not found: {backup_dir}")

        manifest_path = bp / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError("Backup manifest not found")

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        results: dict[str, Any] = {
            "manifest": manifest,
            "restored": [],
            "errors": [],
            "dry_run": dry_run,
        }

        # 1. Restore SQLite
        db_src = bp / "database.db"
        if db_src.exists():
            try:
                sqlite_dest = self._settings.sqlite_path
                if sqlite_dest.is_dir():
                    sqlite_dest = sqlite_dest / "projectpack.db"
                if not dry_run:
                    sqlite_dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(db_src, sqlite_dest)
                results["restored"].append(str(sqlite_dest))
            except Exception as exc:
                results["errors"].append(f"sqlite: {exc}")

        # 2. Restore Vector DB
        vector_src = bp / "vector_db"
        if vector_src.exists():
            try:
                vector_dest = self._settings.vector_db_root
                if not dry_run:
                    vector_dest.mkdir(parents=True, exist_ok=True)
                    shutil.copytree(
                        vector_src, vector_dest, dirs_exist_ok=True
                    )
                results["restored"].append(str(vector_dest))
            except Exception as exc:
                results["errors"].append(f"vector_db: {exc}")

        # 3. Restore project configs
        projects_src = bp / "projects"
        if projects_src.exists():
            try:
                projects_dest = self._settings.project_root
                if not dry_run:
                    projects_dest.mkdir(parents=True, exist_ok=True)
                    for f in projects_src.rglob("*"):
                        if f.is_file():
                            rel = f.relative_to(projects_src)
                            dest = projects_dest / rel
                            dest.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(f, dest)
                results["restored"].append(str(projects_dest))
            except Exception as exc:
                results["errors"].append(f"projects: {exc}")

        results["status"] = (
            "success" if not results["errors"] else "partial"
        )
        logger.info(
            "Restore %s: %d items, %d errors",
            "simulated" if dry_run else "completed",
            len(results["restored"]),
            len(results["errors"]),
        )
        return results

    # ------------------------------------------------------------------
    # cleanup
    # ------------------------------------------------------------------

    def cleanup_old_backups(self) -> int:
        """Remove backups older than ``backup_retention_days``.

        Returns:
            Number of backup directories removed.
        """
        max_age = self._settings.backup_retention_days * 86400
        now = time.time()
        removed = 0

        for entry in self._backup_root.iterdir():
            if entry.is_dir() and entry.name.startswith("backup-"):
                try:
                    mtime = entry.stat().st_mtime
                    if (now - mtime) > max_age:
                        shutil.rmtree(entry)
                        removed += 1
                        logger.info("Removed old backup: %s", entry.name)
                except Exception as exc:
                    logger.warning("Failed to remove backup %s: %s", entry.name, exc)

        return removed


# Module-level singleton
_backup_instance: BackupService | None = None


def get_backup(settings: Settings | None = None) -> BackupService:
    global _backup_instance
    if _backup_instance is None:
        if settings is None:
            settings = Settings()
        _backup_instance = BackupService(settings)
    return _backup_instance
