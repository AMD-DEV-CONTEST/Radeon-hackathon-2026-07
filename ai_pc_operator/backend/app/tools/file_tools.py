"""File tools - list, scan, read, move, copy, quarantine, restore."""

from __future__ import annotations

import os
import shutil
import time
import uuid
from pathlib import Path
from typing import Dict, Any, Iterator

from app.db.database import db_session


# Protected folders
PROTECTED_PATHS = [
    "C:\\Windows",
    "C:\\Program Files",
    "C:\\Program Files (x86)",
    "AppData",
    ".ssh",
    ".env",
]

# Quarantine directory
ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
QUARANTINE_DIR = ROOT / "ai_pc_operator" / "data" / "quarantine"
QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)

MAX_SCAN_FILES = 5000
MAX_SCAN_DEPTH = 3
SCAN_TIMEOUT_SEC = 10.0


class FileTools:
    """File control tools."""

    def _is_protected(self, path: str) -> bool:
        """Check if path is protected."""
        path_lower = path.lower()
        for protected in PROTECTED_PATHS:
            if protected.lower() in path_lower:
                return True
        return False

    def _bounded_walk(
        self,
        root: Path,
        max_files: int = MAX_SCAN_FILES,
        max_depth: int = MAX_SCAN_DEPTH,
        timeout_sec: float = SCAN_TIMEOUT_SEC,
    ) -> Iterator[Path]:
        """Yield files under root with hard caps for 4 GB machines."""
        started = time.monotonic()
        yielded = 0
        stack: list[tuple[Path, int]] = [(root, 0)]

        while stack and yielded < max_files:
            if time.monotonic() - started >= timeout_sec:
                break

            current, depth = stack.pop()
            try:
                children = current.iterdir()
            except (PermissionError, OSError):
                continue

            for child in children:
                if time.monotonic() - started >= timeout_sec or yielded >= max_files:
                    break
                try:
                    if child.is_file():
                        yielded += 1
                        yield child
                    elif child.is_dir() and depth < max_depth and not self._is_protected(str(child)):
                        stack.append((child, depth + 1))
                except (PermissionError, OSError):
                    continue

    async def list(self, path: str = ".") -> Dict[str, Any]:
        """List files in directory."""
        try:
            path_obj = Path(path).expanduser().resolve()

            if not path_obj.exists():
                return {
                    "status": "failed",
                    "error": f"Path does not exist: {path}",
                }

            if not path_obj.is_dir():
                return {
                    "status": "failed",
                    "error": f"Not a directory: {path}",
                }

            items = []
            for item in path_obj.iterdir():
                try:
                    stat = item.stat()
                    items.append({
                        "name": item.name,
                        "path": str(item),
                        "is_dir": item.is_dir(),
                        "size": stat.st_size,
                        "modified": stat.st_mtime,
                    })
                except (PermissionError, OSError):
                    continue

            return {
                "status": "success",
                "path": str(path_obj),
                "items": items,
                "count": len(items),
            }
        except Exception as e:
            return {
                "status": "failed",
                "error": str(e),
            }

    async def scan(self, path: str) -> Dict[str, Any]:
        """Scan directory and get summary."""
        try:
            path_obj = Path(path).expanduser().resolve()

            if not path_obj.exists():
                return {
                    "status": "failed",
                    "error": f"Path does not exist: {path}",
                }

            if self._is_protected(str(path_obj)):
                return {
                    "status": "failed",
                    "error": "Protected path requires explicit approval",
                }

            total_files = 0
            total_size = 0
            file_types = {}
            started = time.monotonic()

            for item in self._bounded_walk(path_obj):
                total_files += 1
                total_size += item.stat().st_size
                ext = item.suffix.lower()
                file_types[ext] = file_types.get(ext, 0) + 1

            truncated = total_files >= MAX_SCAN_FILES or (time.monotonic() - started) >= SCAN_TIMEOUT_SEC

            return {
                "status": "success",
                "path": str(path_obj),
                "total_files": total_files,
                "total_size_mb": round(total_size / (1024**2), 2),
                "file_types": file_types,
                "truncated": truncated,
                "limits": {
                    "max_files": MAX_SCAN_FILES,
                    "max_depth": MAX_SCAN_DEPTH,
                    "timeout_sec": SCAN_TIMEOUT_SEC,
                },
            }
        except Exception as e:
            return {
                "status": "failed",
                "error": str(e),
            }

    async def read(self, path: str, max_size: int = 1024 * 1024) -> Dict[str, Any]:
        """Read file contents."""
        try:
            path_obj = Path(path).expanduser().resolve()

            if not path_obj.exists():
                return {
                    "status": "failed",
                    "error": f"File does not exist: {path}",
                }

            if path_obj.stat().st_size > max_size:
                return {
                    "status": "failed",
                    "error": f"File too large (>{max_size} bytes)",
                }

            with open(path_obj, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()

            return {
                "status": "success",
                "path": str(path_obj),
                "content": content,
                "size": len(content),
            }
        except Exception as e:
            return {
                "status": "failed",
                "error": str(e),
            }

    async def move(self, src: str, dst: str) -> Dict[str, Any]:
        """Move file or directory."""
        try:
            if self._is_protected(src) or self._is_protected(dst):
                return {
                    "status": "failed",
                    "error": "Protected path",
                }

            shutil.move(src, dst)
            return {
                "status": "success",
                "message": f"Moved {src} to {dst}",
            }
        except Exception as e:
            return {
                "status": "failed",
                "error": str(e),
            }

    async def copy(self, src: str, dst: str) -> Dict[str, Any]:
        """Copy file or directory."""
        try:
            if self._is_protected(src):
                return {
                    "status": "failed",
                    "error": "Protected path",
                }

            if os.path.isdir(src):
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)

            return {
                "status": "success",
                "message": f"Copied {src} to {dst}",
            }
        except Exception as e:
            return {
                "status": "failed",
                "error": str(e),
            }

    async def quarantine(self, path: str, command_id: int = None) -> Dict[str, Any]:
        """Move file/directory to quarantine (reversible delete)."""
        try:
            path_obj = Path(path).expanduser().resolve()

            if not path_obj.exists():
                return {
                    "status": "failed",
                    "error": f"Path does not exist: {path}",
                }

            # Generate quarantine ID
            quarantine_id = str(uuid.uuid4())
            quarantine_path = QUARANTINE_DIR / quarantine_id

            # Move to quarantine
            shutil.move(str(path_obj), str(quarantine_path))

            # Get size
            if quarantine_path.is_file():
                total_size = quarantine_path.stat().st_size
            else:
                total_size = sum(f.stat().st_size for f in self._bounded_walk(quarantine_path))

            # Save to database
            async with db_session() as db:
                await db.execute(
                    """
                    INSERT INTO quarantine (
                        original_path, quarantine_path, command_id, file_size
                    )
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        str(path_obj),
                        str(quarantine_path),
                        command_id,
                        total_size,
                    ),
                )
                await db.commit()

            return {
                "status": "success",
                "quarantine_id": quarantine_id,
                "original_path": str(path_obj),
                "quarantine_path": str(quarantine_path),
                "size_mb": round(total_size / (1024**2), 2),
                "message": f"Quarantined {path}",
            }
        except Exception as e:
            return {
                "status": "failed",
                "error": str(e),
            }

    async def restore(self, quarantine_id: str) -> Dict[str, Any]:
        """Restore file from quarantine."""
        try:
            async with db_session() as db:
                cursor = await db.execute(
                    """
                    SELECT id, original_path, quarantine_path
                    FROM quarantine
                    WHERE id = ? OR quarantine_path LIKE ?
                    """,
                    (quarantine_id, f"%{quarantine_id}%"),
                )
                row = await cursor.fetchone()

            if not row:
                return {
                    "status": "failed",
                    "error": f"Quarantine entry not found: {quarantine_id}",
                }

            original_path = row["original_path"]
            quarantine_path = row["quarantine_path"]

            # Restore
            shutil.move(quarantine_path, original_path)

            # Update database
            async with db_session() as db:
                await db.execute(
                    """
                    UPDATE quarantine
                    SET restored_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (row["id"],),
                )
                await db.commit()

            return {
                "status": "success",
                "message": f"Restored {original_path}",
                "original_path": original_path,
            }
        except Exception as e:
            return {
                "status": "failed",
                "error": str(e),
            }

    async def delete_permanent(self, path: str) -> Dict[str, Any]:
        """Permanently delete file (REQUIRES SPECIAL APPROVAL)."""
        try:
            path_obj = Path(path).expanduser().resolve()

            if self._is_protected(str(path_obj)):
                return {
                    "status": "failed",
                    "error": "Protected path - cannot delete",
                }

            if path_obj.is_dir():
                shutil.rmtree(path_obj)
            else:
                path_obj.unlink()

            return {
                "status": "success",
                "message": f"Permanently deleted {path}",
            }
        except Exception as e:
            return {
                "status": "failed",
                "error": str(e),
            }

    async def list_quarantine(self) -> Dict[str, Any]:
        """List all quarantined items."""
        try:
            async with db_session() as db:
                cursor = await db.execute(
                    """
                    SELECT id, original_path, quarantine_path, command_id,
                           file_size, created_at, restored_at, deleted_at
                    FROM quarantine
                    WHERE restored_at IS NULL AND deleted_at IS NULL
                    ORDER BY created_at DESC
                    LIMIT 200
                    """
                )
                rows = await cursor.fetchall()

            return {
                "status": "success",
                "items": [dict(row) for row in rows],
                "count": len(rows),
            }
        except Exception as e:
            return {
                "status": "failed",
                "error": str(e),
            }
