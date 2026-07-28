"""Cheap, deterministic, no-LLM structural extraction (Cartographer stage
A): function/class/import names per file, by regex, language-inferred
from extension. Deliberately not tree-sitter -- a heavy new dependency
this hackathon-scoped feature doesn't need; false negatives on exotic
syntax are acceptable, this feeds an LLM summarizer next (stage B), not a
compiler or a linter.
"""

from __future__ import annotations

import re
from typing import Dict, List

_PY_DEF_RE = re.compile(r"^[ \t]*(def|class)\s+(\w+)", re.MULTILINE)
_PY_IMPORT_RE = re.compile(r"^[ \t]*(?:from\s+\S+\s+)?import\s+.+$", re.MULTILINE)

_DART_RE = re.compile(r"^[ \t]*(?:class|abstract class)\s+(\w+)|^[ \t]*(?:Future(?:<[^>]*>)?|void|Widget|Stream(?:<[^>]*>)?)\s+(\w+)\s*\(", re.MULTILINE)

_JS_TS_RE = re.compile(r"^[ \t]*(?:export\s+)?(?:default\s+)?(class|function)\s+(\w+)", re.MULTILINE)

_GENERIC_EXTENSIONS = {
    "java": re.compile(r"^[ \t]*(?:public|private|protected)?\s*(?:static\s+)?(?:class|interface)\s+(\w+)", re.MULTILINE),
    "go": re.compile(r"^func\s+(?:\([^)]*\)\s*)?(\w+)", re.MULTILINE),
    "rs": re.compile(r"^[ \t]*(?:pub\s+)?(?:fn|struct|enum)\s+(\w+)", re.MULTILINE),
}


def extract_structure(rel_path: str, text: str) -> Dict:
    """Never raises -- garbage/binary input just yields an empty result,
    since the caller (Cartographer's mapping pass) must keep going across
    an entire codebase without one odd file aborting the whole pass."""
    ext = rel_path.rsplit(".", 1)[-1].lower() if "." in rel_path else ""
    functions: List[str] = []
    classes: List[str] = []
    imports: List[str] = []

    try:
        if ext == "py":
            for kind, name in _PY_DEF_RE.findall(text):
                (classes if kind == "class" else functions).append(name)
            imports = [m.strip() for m in _PY_IMPORT_RE.findall(text)][:20]
        elif ext == "dart":
            for cls, fn in _DART_RE.findall(text):
                if cls:
                    classes.append(cls)
                elif fn:
                    functions.append(fn)
        elif ext in ("js", "jsx", "ts", "tsx"):
            for kind, name in _JS_TS_RE.findall(text):
                (classes if kind == "class" else functions).append(name)
        elif ext in _GENERIC_EXTENSIONS:
            for name in _GENERIC_EXTENSIONS[ext].findall(text):
                classes.append(name)
    except Exception:
        pass

    return {
        "functions": functions[:50],
        "classes": classes[:50],
        "imports": imports,
        "line_count": text.count("\n") + 1,
    }
