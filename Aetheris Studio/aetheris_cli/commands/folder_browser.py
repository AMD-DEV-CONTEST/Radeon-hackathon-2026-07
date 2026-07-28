"""
Folder browser component ported from ROCm CLI.
Models directory navigation primitives including UseCurrent, NewChild, Parent, and Directory entries with keybinding handlers.
"""

from dataclasses import dataclass
from enum import Enum
import os
from pathlib import Path
from typing import List, Optional, Tuple, Union


class FolderEntryKind(Enum):
    USE_CURRENT = "use_current"
    NEW_CHILD = "new_child"
    PARENT = "parent"
    DIRECTORY = "directory"


@dataclass
class FolderEntry:
    label: str
    path: Path
    kind: FolderEntryKind


class FolderOutcomeKind(Enum):
    NONE = "none"
    NAVIGATED = "navigated"
    CHOSEN = "chosen"
    CANCELLED = "cancelled"


@dataclass
class FolderOutcome:
    kind: FolderOutcomeKind
    chosen_path: Optional[Path] = None


def build_entries(dir_path: Path) -> List[FolderEntry]:
    resolved = dir_path.resolve()
    entries = [
        FolderEntry(
            label="[ use this folder ]",
            path=resolved,
            kind=FolderEntryKind.USE_CURRENT,
        )
    ]

    if resolved.parent != resolved:
        entries.append(
            FolderEntry(
                label="..",
                path=resolved.parent,
                kind=FolderEntryKind.PARENT,
            )
        )

    child_dirs: List[Path] = []
    try:
        if resolved.exists() and resolved.is_dir():
            for item in resolved.iterdir():
                if item.is_dir():
                    child_dirs.append(item)
    except Exception:
        pass

    child_dirs.sort(key=lambda p: p.name.lower())

    for child in child_dirs:
        entries.append(
            FolderEntry(
                label=f"{child.name}/",
                path=child,
                kind=FolderEntryKind.DIRECTORY,
            )
        )

    entries.append(
        FolderEntry(
            label="[ + new folder ]",
            path=resolved / "new-folder",
            kind=FolderEntryKind.NEW_CHILD,
        )
    )

    return entries


class FolderBrowser:
    def __init__(self, title: str, start_path: Path):
        self.title = title
        self.current_dir = start_path.resolve()
        self.entries: List[FolderEntry] = []
        self.selected: int = 0
        self.refresh()

    def refresh(self) -> None:
        self.entries = build_entries(self.current_dir)
        if self.selected >= len(self.entries):
            self.selected = max(0, len(self.entries) - 1)

    def move_sel(self, delta: int) -> None:
        if not self.entries:
            return
        self.selected = max(0, min(len(self.entries) - 1, self.selected + delta))

    def navigate_to(self, dir_path: Path) -> None:
        self.current_dir = dir_path.resolve()
        self.selected = 0
        self.refresh()

    def activate(self) -> FolderOutcome:
        if not self.entries or self.selected >= len(self.entries):
            return FolderOutcome(kind=FolderOutcomeKind.NONE)

        entry = self.entries[self.selected]
        if entry.kind in (FolderEntryKind.USE_CURRENT, FolderEntryKind.NEW_CHILD):
            return FolderOutcome(kind=FolderOutcomeKind.CHOSEN, chosen_path=entry.path)
        elif entry.kind in (FolderEntryKind.PARENT, FolderEntryKind.DIRECTORY):
            self.navigate_to(entry.path)
            return FolderOutcome(kind=FolderOutcomeKind.NAVIGATED)

        return FolderOutcome(kind=FolderOutcomeKind.NONE)

    def on_key(self, key: str) -> FolderOutcome:
        k = key.strip()
        if k in ("up", "shift+tab"):
            self.move_sel(-1)
            return FolderOutcome(kind=FolderOutcomeKind.NONE)
        elif k in ("down", "tab"):
            self.move_sel(1)
            return FolderOutcome(kind=FolderOutcomeKind.NONE)
        elif k == "home":
            self.selected = 0
            return FolderOutcome(kind=FolderOutcomeKind.NONE)
        elif k == "end":
            self.selected = max(0, len(self.entries) - 1)
            return FolderOutcome(kind=FolderOutcomeKind.NONE)
        elif k in ("left", "backspace"):
            if self.current_dir.parent != self.current_dir:
                self.navigate_to(self.current_dir.parent)
                return FolderOutcome(kind=FolderOutcomeKind.NAVIGATED)
            return FolderOutcome(kind=FolderOutcomeKind.NONE)
        elif k == "esc":
            return FolderOutcome(kind=FolderOutcomeKind.CANCELLED)
        elif k == "enter":
            return self.activate()

        return FolderOutcome(kind=FolderOutcomeKind.NONE)
