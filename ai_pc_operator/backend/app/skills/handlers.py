"""Skill handlers - thin async wrappers around existing tools.

Each handler is a small async function that takes the skill's declared
inputs and returns a dict of declared outputs. Handlers are looked up
by dotted path from the skill registry.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Files domain
# ----------------------------------------------------------------------


async def file_list(path: str = "", max_entries: int = 500) -> Dict[str, Any]:
    """List a directory."""
    from app.tools.file_tools import FileTools

    tools = FileTools()
    target = path or os.path.expanduser("~")
    result = await asyncio.to_thread(tools.list_dir, target, max_entries)
    return {
        "path": target,
        "entries": result.get("entries", []),
        "count": result.get("count", 0),
    }


async def file_scan(path: str = "") -> Dict[str, Any]:
    """Scan a directory for size and file count."""
    from app.tools.file_tools import FileTools

    tools = FileTools()
    target = path or os.path.expanduser("~")
    result = await asyncio.to_thread(tools.scan, target)
    return {"path": target, **result}


async def file_quarantine(path: str, command_id: Optional[int] = None) -> Dict[str, Any]:
    """Move a file to quarantine."""
    from app.tools.file_tools import FileTools

    tools = FileTools()
    result = await asyncio.to_thread(tools.quarantine, path, command_id)
    return {"original_path": path, **result}


async def file_restore(quarantine_id: int) -> Dict[str, Any]:
    """Restore a quarantined file."""
    from app.tools.file_tools import FileTools

    tools = FileTools()
    result = await asyncio.to_thread(tools.restore, quarantine_id)
    return {"quarantine_id": quarantine_id, **result}


async def file_read(path: str, max_bytes: int = 1_000_000) -> Dict[str, Any]:
    """Read a text file (bounded)."""
    p = Path(path)
    if not p.exists():
        return {"path": path, "error": "not found", "content": ""}
    data = p.read_bytes()[:max_bytes]
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("utf-8", errors="ignore")
    return {"path": path, "content": text, "size": p.stat().st_size}


# ----------------------------------------------------------------------
# OS / system domain
# ----------------------------------------------------------------------


async def system_status() -> Dict[str, Any]:
    """Return system status snapshot."""
    from app.tools.system_tools import SystemTools

    tools = SystemTools()
    return await asyncio.to_thread(tools.status)


async def system_disk_usage(path: str = "C:\\") -> Dict[str, Any]:
    """Return disk usage for a path."""
    from app.tools.system_tools import SystemTools

    tools = SystemTools()
    return await asyncio.to_thread(tools.disk_usage, path)


async def system_ram_usage() -> Dict[str, Any]:
    """Return RAM usage."""
    from app.tools.system_tools import SystemTools

    tools = SystemTools()
    return await asyncio.to_thread(tools.ram_usage)


async def system_processes(limit: int = 50) -> Dict[str, Any]:
    """Return top processes."""
    from app.tools.system_tools import SystemTools

    tools = SystemTools()
    return await asyncio.to_thread(tools.processes, limit)


async def system_open_app(name: str) -> Dict[str, Any]:
    """Open an application by name."""
    from app.tools.system_tools import SystemTools

    tools = SystemTools()
    return await asyncio.to_thread(tools.open_app, name)


# ----------------------------------------------------------------------
# Browser domain
# ----------------------------------------------------------------------


async def browser_open(url: str) -> Dict[str, Any]:
    """Open a URL in the browser."""
    from app.tools.browser_tools import BrowserTools

    tools = BrowserTools()
    return await asyncio.to_thread(tools.open, url)


async def browser_search(query: str, engine: str = "google") -> Dict[str, Any]:
    """Search the web."""
    from app.tools.browser_tools import BrowserTools

    tools = BrowserTools()
    return await asyncio.to_thread(tools.search, query, engine)


async def browser_close() -> Dict[str, Any]:
    """Close the browser."""
    from app.tools.browser_tools import BrowserTools

    tools = BrowserTools()
    return await asyncio.to_thread(tools.close)


# ----------------------------------------------------------------------
# Screen / UI domain
# ----------------------------------------------------------------------


async def screen_scan() -> Dict[str, Any]:
    """Scan the screen for actionable controls."""
    from app.tools.screen_tools import ScreenTools

    tools = ScreenTools()
    return await asyncio.to_thread(tools.scan)


async def screen_click_text(text: str, dry_run: bool = True) -> Dict[str, Any]:
    """Click a UI element by visible text."""
    from app.tools.screen_tools import ScreenTools

    tools = ScreenTools()
    return await asyncio.to_thread(tools.click_text, text, dry_run)


# ----------------------------------------------------------------------
# Auth / vault domain
# ----------------------------------------------------------------------


async def vault_unlock(master_key: str) -> Dict[str, Any]:
    """Unlock the password vault."""
    from app.tools.auth_tools import AuthTools

    tools = AuthTools()
    return await asyncio.to_thread(tools.unlock_vault, master_key)


async def vault_lock() -> Dict[str, Any]:
    """Lock the password vault."""
    from app.tools.auth_tools import AuthTools

    tools = AuthTools()
    return await asyncio.to_thread(tools.lock_vault)


async def vault_list() -> Dict[str, Any]:
    """List vault entries (no secrets)."""
    from app.tools.auth_tools import AuthTools

    tools = AuthTools()
    return await asyncio.to_thread(tools.list_entries)


# ----------------------------------------------------------------------
# Meta / utility domain
# ----------------------------------------------------------------------


async def meta_echo(text: str = "") -> Dict[str, Any]:
    """Echo back the input (useful for testing the pipeline)."""
    return {"echo": text}


async def meta_sleep(seconds: float = 1.0) -> Dict[str, Any]:
    """Sleep for N seconds (testing/timing)."""
    await asyncio.sleep(max(0.0, float(seconds)))
    return {"slept": float(seconds)}
