"""Stage J — Log Rotation Service.

Rotates application log files when they exceed a configured size threshold.
Old logs are optionally compressed and retained for a configurable period.
"""

from __future__ import annotations

import gzip
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from app.config import Settings

logger = logging.getLogger("projectpack.log_rotation")


class LogRotationService:
    """Rotates log files based on size and retention policy."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._log_root = settings.log_root
        self._log_root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # rotation
    # ------------------------------------------------------------------

    def rotate(self, log_file_name: str = "app.log") -> dict[str, object]:
        """Rotate a single log file if it exceeds the max size.

        Args:
            log_file_name: The log file name relative to ``log_root``.

        Returns:
            Dict with rotation results.
        """
        candidate = Path(log_file_name)
        if candidate.is_absolute() or candidate.name != log_file_name:
            raise ValueError("log_file must be a simple file name inside the log directory")
        log_path = (self._log_root / candidate).resolve()
        try:
            log_path.relative_to(self._log_root.resolve())
        except ValueError as exc:
            raise ValueError("log_file escapes the configured log directory") from exc
        if not log_path.exists():
            return {"rotated": False, "reason": "file_not_found", "path": str(log_path)}

        max_bytes = self._settings.log_max_size_mb * 1024 * 1024
        current_size = log_path.stat().st_size

        if current_size < max_bytes:
            return {
                "rotated": False,
                "reason": "under_threshold",
                "size_mb": round(current_size / (1024 * 1024), 2),
                "max_mb": self._settings.log_max_size_mb,
                "path": str(log_path),
            }

        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        rotated_name = f"{log_path.stem}-{ts}{log_path.suffix}"
        rotated_path = self._log_root / rotated_name

        try:
            log_path.rename(rotated_path)
            # Optionally compress
            if self._settings.log_compression_enabled:
                self._compress(rotated_path)

            # Create a fresh empty log file
            log_path.touch()

            logger.info("Rotated log %s → %s", log_file_name, rotated_name)
            return {
                "rotated": True,
                "old_path": str(rotated_path),
                "new_path": str(log_path),
                "size_mb": round(current_size / (1024 * 1024), 2),
                "compressed": self._settings.log_compression_enabled,
            }
        except Exception as exc:
            logger.error("Log rotation failed for %s: %s", log_file_name, exc)
            return {"rotated": False, "reason": str(exc)}

    def rotate_all(self) -> list[dict[str, object]]:
        """Rotate all log files in the log root directory."""
        results: list[dict[str, object]] = []
        for entry in self._log_root.iterdir():
            if entry.is_file() and entry.suffix in (".log", ".txt"):
                result = self.rotate(entry.name)
                results.append(result)
        return results

    # ------------------------------------------------------------------
    # cleanup
    # ------------------------------------------------------------------

    def cleanup_old_logs(self) -> int:
        """Remove rotated/compressed logs older than retention period.

        Returns:
            Number of files removed.
        """
        max_age_seconds = self._settings.log_retention_days * 86400
        now = time.time()
        removed = 0

        for entry in self._log_root.iterdir():
            if not entry.is_file():
                continue
            # Only clean rotated/compressed logs, not the active log
            if entry.name == "app.log":
                continue
            try:
                if (now - entry.stat().st_mtime) > max_age_seconds:
                    entry.unlink()
                    removed += 1
            except Exception as exc:
                logger.warning("Failed to remove old log %s: %s", entry.name, exc)

        return removed

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _compress(file_path: Path) -> Path:
        """Gzip-compress *file_path* and return the compressed path."""
        compressed_path = file_path.with_suffix(file_path.suffix + ".gz")
        with open(file_path, "rb") as f_in:
            with gzip.open(compressed_path, "wb") as f_out:
                f_out.write(f_in.read())
        file_path.unlink()  # remove original
        return compressed_path


# Module-level singleton
_log_rotation_instance: LogRotationService | None = None


def get_log_rotation(settings: Settings | None = None) -> LogRotationService:
    global _log_rotation_instance
    if _log_rotation_instance is None:
        if settings is None:
            settings = Settings()
        _log_rotation_instance = LogRotationService(settings)
    return _log_rotation_instance
