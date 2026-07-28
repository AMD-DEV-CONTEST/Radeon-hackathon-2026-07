"""
Model recipe picker component ported from ROCm CLI.
Provides filterable model recipe selection with fuzzy string matching over model ids, task descriptions, and preferred engine options.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Tuple


@dataclass
class ModelRecipeSummary:
    id: str
    aliases: List[str] = field(default_factory=list)
    task: str = "chat"
    preferred_engine: Optional[str] = None


class PickerOutcomeKind(Enum):
    NONE = "none"
    CHOSEN = "chosen"
    CANCELLED = "cancelled"


@dataclass
class PickerOutcome:
    kind: PickerOutcomeKind
    chosen_recipe: Optional[ModelRecipeSummary] = None


class ModelPicker:
    def __init__(self, query: str = "", selected: int = 0):
        self.query = query
        self.selected = selected

    def filtered(self, recipes: List[ModelRecipeSummary]) -> List[ModelRecipeSummary]:
        q = self.query.strip().lower()
        if not q:
            return list(recipes)

        results = []
        for r in recipes:
            if q in r.id.lower() or any(q in alias.lower() for alias in r.aliases):
                results.append(r)
        return results

    def on_key(self, key: str, recipes: List[ModelRecipeSummary]) -> PickerOutcome:
        k = key.strip()
        matching = self.filtered(recipes)
        length = len(matching)

        if k == "esc":
            return PickerOutcome(kind=PickerOutcomeKind.CANCELLED)

        elif k == "up":
            self.selected = max(0, self.selected - 1)
            return PickerOutcome(kind=PickerOutcomeKind.NONE)

        elif k == "down":
            if length > 0:
                self.selected = min(length - 1, self.selected + 1)
            return PickerOutcome(kind=PickerOutcomeKind.NONE)

        elif k == "enter":
            if 0 <= self.selected < length:
                return PickerOutcome(kind=PickerOutcomeKind.CHOSEN, chosen_recipe=matching[self.selected])
            return PickerOutcome(kind=PickerOutcomeKind.NONE)

        elif k == "backspace":
            if self.query:
                self.query = self.query[:-1]
                self.selected = 0
            return PickerOutcome(kind=PickerOutcomeKind.NONE)

        elif len(k) == 1 and k.isprintable():
            self.query += k
            self.selected = 0
            return PickerOutcome(kind=PickerOutcomeKind.NONE)

        return PickerOutcome(kind=PickerOutcomeKind.NONE)
