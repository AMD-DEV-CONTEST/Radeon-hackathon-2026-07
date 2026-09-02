"""Regression guard for the eval_index / lock-board UTF-8 reader bug.

The board files (corpus/programbench/eval_index.json, logs/programbench_lock_board.json)
are valid UTF-8 and contain non-ASCII characters (em-dashes, arrows, ≥/≤). On Windows,
Python's default open()/Path.read_text() uses the cp1252 codec, which crashes on those
bytes (UnicodeDecodeError: 'charmap' codec can't decode byte 0x9d ...).

Two guards:
1. The board files must be strict-UTF-8 parseable JSON.
2. No PB script may read a board/index file with a *bare* read (no encoding=); every
   board reader must pass encoding="utf-8". This is the regression that broke readers
   on Windows and is the purpose of the mojibake-and-count-fix branch.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"

BOARD_FILES = [
    REPO / "corpus" / "programbench" / "eval_index.json",
    REPO / "logs" / "programbench_lock_board.json",
]


@pytest.mark.parametrize("path", BOARD_FILES, ids=lambda p: p.name)
def test_board_is_strict_utf8_json(path: Path) -> None:
    if not path.exists():
        pytest.skip(f"{path.name} not present in this checkout")
    raw = path.read_bytes()
    # Strict UTF-8 — no errors=replace. Catches genuine corruption AND proves the file
    # is fine so the only correct fix is reader-side encoding="utf-8".
    text = raw.decode("utf-8")
    data = json.loads(text)
    assert data, f"{path.name} parsed empty"


# Lines that read a board/index file with a bare read (no encoding=) are the bug.
_BARE_READ_TEXT = re.compile(r"\.read_text\(\s*\)")
_BARE_OPEN = re.compile(r"json\.load\(\s*open\([^)]*\)\s*\)")
_BOARD_HINT = re.compile(r"(eval_index|BOARD|INDEX_FILE|EVAL_INDEX|lock_board)", re.IGNORECASE)


def test_no_bare_board_reads() -> None:
    offenders: list[str] = []
    for py in SCRIPTS.rglob("*.py"):
        if "__pycache__" in py.parts:
            continue
        try:
            lines = py.read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        for i, line in enumerate(lines, 1):
            if not _BOARD_HINT.search(line):
                continue
            if _BARE_READ_TEXT.search(line) or (_BARE_OPEN.search(line) and "encoding" not in line):
                offenders.append(f"{py.relative_to(REPO)}:{i}: {line.strip()}")
    assert not offenders, (
        "Board/index files must be read with encoding='utf-8' "
        "(cp1252 default crashes on Windows):\n" + "\n".join(offenders)
    )
