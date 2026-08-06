"""Permission control: directory whitelist + scope filtering."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# default whitelist directories (relative to the workspace root)
DEFAULT_ALLOWED_DIRS = ["downloads", "artifacts", "reports"]


def check_path_allowed(file_path: str, workspace_root: str | Path, allowed_dirs: list[str] | None = None) -> bool:
    """Check whether a file path is within the whitelisted directories.
    
    Args:
        file_path: the file path to check
        workspace_root: the Workspace root directory
        allowed_dirs: the list of allowed directories
        
    Returns:
        True if the path is within the whitelist, False otherwise
    """
    if allowed_dirs is None:
        allowed_dirs = DEFAULT_ALLOWED_DIRS
    
    try:
        workspace_root = Path(workspace_root).resolve()
        target = Path(file_path).resolve()
        
        # check whether the target is under the workspace
        try:
            target.relative_to(workspace_root)
        except ValueError:
            logger.warning("path %s is not inside the workspace root", file_path)
            return False
        
        # check whether it is in a whitelisted directory
        relative = target.relative_to(workspace_root)
        first_dir = relative.parts[0] if relative.parts else ""
        if first_dir not in allowed_dirs:
            logger.warning("directory %s is not in the whitelist %s", first_dir, allowed_dirs)
            return False
        
        return True
    except Exception as e:
        logger.error("path check failed: %s", e)
        return False


def filter_by_scope(
    records: list[dict],
    scope: dict[str, str],
) -> list[dict]:
    """Filter records by scope, returning only the matching ones.
    
    Args:
        records: the record list
        scope: scope filter conditions, e.g. {"tenant_id": "tenant-a", "namespace": "insurance"}
        
    Returns:
        the filtered record list
    """
    if not scope:
        return records
    
    filtered = []
    for record in records:
        record_scope = record.get("scope", {})
        if all(record_scope.get(k) == v for k, v in scope.items()):
            filtered.append(record)
    
    logger.debug("scope filtering: %d → %d records", len(records), len(filtered))
    return filtered
