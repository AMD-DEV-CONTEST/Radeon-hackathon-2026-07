"""
Unit tests for Aetheris CLI folder browser component.
Verifies directory entry listing, cursor movement, navigation, and directory selection outcomes.
"""

from pathlib import Path
from aetheris_cli.commands.folder_browser import (
    FolderBrowser,
    FolderEntryKind,
    FolderOutcomeKind,
    build_entries,
)


def test_build_entries_structure(tmp_path):
    d1 = tmp_path / "alpha"
    d1.mkdir()
    f1 = tmp_path / "note.txt"
    f1.write_text("test")

    entries = build_entries(tmp_path)
    assert entries[0].kind == FolderEntryKind.USE_CURRENT
    assert entries[-1].kind == FolderEntryKind.NEW_CHILD

    dir_entries = [e for e in entries if e.kind == FolderEntryKind.DIRECTORY]
    assert len(dir_entries) == 1
    assert dir_entries[0].label == "alpha/"


def test_folder_browser_navigation(tmp_path):
    fb = FolderBrowser("Test", tmp_path)
    outcome = fb.on_key("enter")
    assert outcome.kind == FolderOutcomeKind.CHOSEN
    assert outcome.chosen_path == tmp_path.resolve()


def test_folder_browser_esc_cancels(tmp_path):
    fb = FolderBrowser("Test", tmp_path)
    outcome = fb.on_key("esc")
    assert outcome.kind == FolderOutcomeKind.CANCELLED
