"""
Enforcement test: no module except corpus_manager.py may write directly to corpus JSONL files.
This is a static grep-based check that runs as part of the test suite.
It catches future contributors bypassing the CorpusManager signature requirement.
"""

from __future__ import annotations

import re
from pathlib import Path

# Root of the project
_ROOT = Path(__file__).parent.parent
_SCRIPTS = _ROOT / "scripts"

# The one allowed module
_ALLOWED_CORPUS_WRITER = "scripts/corpus/corpus_manager.py"

# Pattern that detects direct JSONL open-for-append to corpus paths
_DIRECT_WRITE_PATTERNS: list[re.Pattern] = [
    # open("...corpus...jsonl", "a") or open("...corpus...jsonl", "ab")
    re.compile(
        r'open\s*\([^)]*(?:corpus|verdict_corpus|safety_refusal|terminal_trace|browser_trace|desktop_trace|mobile_trace|visual_repair)[^)]*\.jsonl[^)]*,\s*["\']a',
        re.I,
    ),
    # .write to a .jsonl file with "corpus" in the path outside manager
    re.compile(r"\.write\([^)]*\.jsonl"),
    # jsonlines.open / jsonlines.Writer on corpus paths
    re.compile(r"jsonlines\.(open|Writer)[^)]*corpus"),
]

# Files that are allowed to do corpus-pattern writes (the manager itself)
_ALLOWED_FILES: frozenset[str] = frozenset(
    {
        "scripts/corpus/corpus_manager.py",
        "scripts/pb_verdict_corpus.py",  # compatibility wrapper — allowed, but must route to manager
    }
)


def _relative(path: Path) -> str:
    try:
        return str(path.relative_to(_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def _scan_file(path: Path) -> list[str]:
    violations = []
    rel = _relative(path)
    if rel in _ALLOWED_FILES:
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []
    for i, line in enumerate(text.splitlines(), 1):
        for pattern in _DIRECT_WRITE_PATTERNS:
            if pattern.search(line):
                violations.append(f"{rel}:{i}: {line.strip()}")
    return violations


def test_no_raw_corpus_writes():
    """No module except corpus_manager.py and pb_verdict_corpus.py may write corpus JSONL directly."""
    violations = []
    for py_file in _SCRIPTS.rglob("*.py"):
        violations.extend(_scan_file(py_file))
    # Also check bench_adapters
    bench = _ROOT / "bench_adapters"
    if bench.exists():
        for py_file in bench.rglob("*.py"):
            violations.extend(_scan_file(py_file))

    assert not violations, (
        f"Found {len(violations)} raw corpus write(s) — all corpus writes must go through CorpusManager:\n"
        + "\n".join(violations)
    )
