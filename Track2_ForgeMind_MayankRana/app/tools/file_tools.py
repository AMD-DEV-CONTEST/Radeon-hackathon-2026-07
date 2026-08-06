"""
ForgeMind Tools - All local file operations
"""
import os
import pathlib
import subprocess
from typing import List, Dict

BASE_DIR = pathlib.Path(".").resolve()  # Will be set to workspace

def set_workspace(path: str):
    global BASE_DIR
    BASE_DIR = pathlib.Path(path).resolve()
    print(f"[Tools] Workspace set to {BASE_DIR}")

def file_tree(max_depth: int = 3) -> str:
    """List files in workspace"""
    out = []
    for root, dirs, files in os.walk(BASE_DIR):
        level = root.replace(str(BASE_DIR), '').count(os.sep)
        if level > max_depth:
            continue
        # Skip hidden and venv
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ['venv', 'venv_rocm', '__pycache__', 'node_modules']]
        indent = ' ' * 2 * level
        out.append(f"{indent}{os.path.basename(root)}/")
        subindent = ' ' * 2 * (level + 1)
        for f in files[:30]:
            if not f.startswith('.'):
                out.append(f"{subindent}{f}")
    return "\n".join(out)

def read_file(path: str) -> str:
    full = BASE_DIR / path
    if not full.exists():
        return f"Error: File {path} not found"
    try:
        # Security: prevent path traversal
        if not str(full.resolve()).startswith(str(BASE_DIR)):
            return "Error: Path traversal not allowed"
        return full.read_text(encoding='utf-8', errors='ignore')[:20000]  # limit
    except Exception as e:
        return f"Error reading {path}: {e}"

def write_file(path: str, content: str) -> str:
    full = BASE_DIR / path
    try:
        if not str(full.resolve()).startswith(str(BASE_DIR)):
            return "Error: Path traversal not allowed"
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content, encoding='utf-8')
        return f"Successfully wrote {len(content)} chars to {path}"
    except Exception as e:
        return f"Error writing {path}: {e}"

def run_terminal(cmd: str, timeout: int = 30) -> str:
    """Sandboxed terminal - only inside workspace"""
    try:
        result = subprocess.run(
            cmd, shell=True, cwd=str(BASE_DIR),
            capture_output=True, text=True, timeout=timeout
        )
        output = result.stdout + "\n" + result.stderr
        return f"Exit Code: {result.returncode}\nOutput:\n{output[:10000]}"
    except subprocess.TimeoutExpired:
        return f"Error: Command timed out after {timeout}s"
    except Exception as e:
        return f"Error: {e}"
