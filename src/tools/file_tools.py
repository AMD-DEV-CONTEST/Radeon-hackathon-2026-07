import os
import glob
import logging
from typing import List, Dict, Any, Union
from .registry import ToolRegistry

logger = logging.getLogger(__name__)

def register_file_tools(registry: ToolRegistry, base_dir: str = "./data/documents") -> None:
    """Register all file tools with the registry.
    
    Args:
        registry: The ToolRegistry instance.
        base_dir: The allowed base directory for file operations.
    """
    os.makedirs(base_dir, exist_ok=True)
    
    registry.register(
        name="file_read",
        func=lambda path: file_read(path, base_dir),
        description="Read the contents of a file.",
        parameters={
            "path": {"type": "string", "description": "The relative path to the file"}
        },
        requires_permission=False
    )
    
    registry.register(
        name="file_write",
        func=lambda path, content: file_write(path, content, base_dir),
        description="Write content to a file.",
        parameters={
            "path": {"type": "string", "description": "The relative path to the file"},
            "content": {"type": "string", "description": "The content to write"}
        },
        requires_permission=True
    )
    
    registry.register(
        name="file_search",
        func=lambda query, recursive=True: file_search(query, base_dir, recursive),
        description="Search files by filename or content substring.",
        parameters={
            "query": {"type": "string", "description": "The search query"},
            "recursive": {"type": "boolean", "description": "Whether to search subdirectories"}
        },
        requires_permission=False
    )
    
    registry.register(
        name="file_list",
        func=lambda directory=".": file_list(directory, base_dir),
        description="List files in a directory.",
        parameters={
            "directory": {"type": "string", "description": "The relative directory path to list"}
        },
        requires_permission=False
    )

def _is_safe_path(base_dir: str, target_path: str) -> bool:
    """Check if the target path is strictly contained within the base directory.

    Uses ``os.path.commonpath`` containment rather than a string-prefix check,
    so sibling-prefix bypasses (``base_dir`` = ``.../data``, target =
    ``.../data_secret``) and absolute-path escapes cannot slip through.
    Both paths are ``realpath``-resolved first, so symlinks that point outside
    ``base_dir`` are rejected too.
    """
    base_abs = os.path.realpath(base_dir)
    target_abs = os.path.realpath(os.path.join(base_dir, target_path))
    try:
        common = os.path.commonpath([base_abs, target_abs])
    except ValueError:
        # Windows: paths on different drives share no common path.
        return False
    return common == base_abs

def file_read(path: str, base_dir: str = "./data/documents") -> str:
    """Read file contents, constrained to base_dir."""
    if not _is_safe_path(base_dir, path):
        raise PermissionError(f"Access to path '{path}' is denied. Must be within base_dir.")
        
    full_path = os.path.join(base_dir, path)
    try:
        with open(full_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        logger.error(f"Error reading file {path}: {e}")
        return f"Error: {e}"

def file_write(path: str, content: str, base_dir: str = "./data/documents") -> str:
    """Write content to file, constrained to base_dir."""
    if not _is_safe_path(base_dir, path):
        raise PermissionError(f"Access to path '{path}' is denied. Must be within base_dir.")
        
    full_path = os.path.join(base_dir, path)
    os.makedirs(os.path.dirname(os.path.realpath(full_path)), exist_ok=True)
    
    try:
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return f"Written {len(content)} bytes to {path}"
    except Exception as e:
        logger.error(f"Error writing file {path}: {e}")
        return f"Error: {e}"

def file_search(query: str, base_dir: str = "./data/documents", recursive: bool = True) -> List[Dict[str, str]]:
    """Search files by filename or content substring."""
    results = []
    base_abs = os.path.realpath(base_dir)
    
    try:
        for root, _, files in os.walk(base_abs):
            for file in files:
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, base_abs)
                
                # Check filename
                if query.lower() in file.lower():
                    results.append({
                        "path": rel_path,
                        "match_type": "filename",
                        "snippet": ""
                    })
                    continue
                
                # Check content
                try:
                    with open(full_path, 'r', encoding='utf-8') as f:
                        for line in f:
                            if query.lower() in line.lower():
                                snippet = line.strip()
                                if len(snippet) > 100:
                                    snippet = snippet[:100] + "..."
                                results.append({
                                    "path": rel_path,
                                    "match_type": "content",
                                    "snippet": snippet
                                })
                                break
                except Exception:
                    # Skip binary files or unreadable files
                    pass
            if not recursive:
                break
    except Exception as e:
        logger.error(f"Error searching files: {e}")
        
    return results

def file_list(directory: str = ".", base_dir: str = "./data/documents") -> List[Dict[str, Union[str, int]]]:
    """List files in directory."""
    if not _is_safe_path(base_dir, directory):
        raise PermissionError(f"Access to directory '{directory}' is denied.")
        
    full_dir = os.path.join(base_dir, directory)
    results = []
    
    try:
        if os.path.exists(full_dir) and os.path.isdir(full_dir):
            for item in os.listdir(full_dir):
                item_path = os.path.join(full_dir, item)
                rel_path = os.path.relpath(item_path, base_dir)
                stat = os.stat(item_path)
                results.append({
                    "name": item,
                    "path": rel_path,
                    "size": stat.st_size,
                    "modified": str(stat.st_mtime)
                })
    except Exception as e:
        logger.error(f"Error listing directory {directory}: {e}")
        
    return results
