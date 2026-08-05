"""Runtime resolution of llama.cpp binaries and source tree.

Configs may name exact paths (they win when they exist), but those
paths are machine-specific — /opt/llama.cpp only exists on the contest
image. Resolution order: configured path, then $LLAMA_CPP_HOME, then
common install locations. Failure names everything that was tried.
"""

import os
import sys
from pathlib import Path

from .config import REPO_ROOT

_EXE_SUFFIX = ".exe" if sys.platform == "win32" else ""

COMMON_HOMES = [
    Path("/opt/llama.cpp"),
    Path.home() / "llama.cpp",
    REPO_ROOT / "tools" / "llama.cpp",
]


def _homes(extra=None):
    homes = []
    env = os.environ.get("LLAMA_CPP_HOME")
    if env:
        homes.append(Path(env))
    homes.extend(COMMON_HOMES)
    # local source checkouts like tools/llama.cpp-b10043
    tools = REPO_ROOT / "tools"
    if tools.is_dir():
        homes.extend(sorted(p for p in tools.glob("llama.cpp-*") if p.is_dir()))
    if extra:
        homes.extend(extra)
    return homes


def _binary_candidates(home: Path, name: str):
    fname = name + _EXE_SUFFIX
    return [home / "build" / "bin" / fname, home / "bin" / fname,
            home / fname]


def resolve_binary(configured, name: str) -> Path:
    """Find a llama.cpp binary (llama-server, llama-bench, ...)."""
    tried = []
    if configured:
        p = Path(configured)
        # configured path may name the server; derive the sibling binary
        candidate = p if p.stem == name else p.parent / (name + _EXE_SUFFIX)
        for c in (candidate, p.parent / (name + p.suffix)):
            if c.exists():
                return c
            tried.append(c)
    for home in _homes():
        for c in _binary_candidates(home, name):
            if c.exists():
                return c
            tried.append(c)
    raise RuntimeError(
        f"could not find llama.cpp binary '{name}'. Tried:\n  "
        + "\n  ".join(str(t) for t in dict.fromkeys(tried))
        + "\nFix: set teacher.server_exe in the config, or export "
          "LLAMA_CPP_HOME to your llama.cpp directory.")


def resolve_src(configured=None) -> Path:
    """Find the llama.cpp source tree (for convert_hf_to_gguf.py)."""
    tried = []
    candidates = ([Path(configured)] if configured else []) + _homes()
    for home in candidates:
        script = Path(home) / "convert_hf_to_gguf.py"
        if script.exists():
            return Path(home)
        tried.append(script)
    raise RuntimeError(
        "could not find llama.cpp source tree (convert_hf_to_gguf.py). "
        "Tried:\n  " + "\n  ".join(str(t) for t in dict.fromkeys(tried))
        + "\nFix: set export.llama_src in the config, or export "
          "LLAMA_CPP_HOME to a llama.cpp checkout.")
