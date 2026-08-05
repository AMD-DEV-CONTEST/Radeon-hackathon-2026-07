from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "scripts"))

from swe_agent.rag import _entry_patch_text  # noqa: E402


def test_entry_patch_text_supports_current_flywheel_output_field() -> None:
    assert _entry_patch_text({"output": "diff --git\n"}) == "diff --git\n"


def test_entry_patch_text_keeps_legacy_patch_field() -> None:
    assert _entry_patch_text({"patch": "legacy patch"}) == "legacy patch"


def test_entry_patch_text_prefers_current_output_field() -> None:
    assert _entry_patch_text({"output": "current", "patch": "legacy"}) == "current"
