"""
Approval gate modal data structures and keyboard event handler ported from ROCm CLI.
Renders approval requests and evaluates user keybindings (Y, N, Tab, Esc, Enter) into explicit verdicts.
"""

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Tuple


class ApprovalChoice(Enum):
    APPROVE = "approve"
    DENY = "deny"

    def toggle(self) -> "ApprovalChoice":
        return ApprovalChoice.DENY if self == ApprovalChoice.APPROVE else ApprovalChoice.APPROVE


class ApprovalVerdict(Enum):
    APPROVE = "approve"
    DENY = "deny"
    CANCEL = "cancel"


@dataclass
class ApprovalRequest:
    title: str
    body: List[str]


def handle_approval_key(key: str, choice: ApprovalChoice) -> Tuple[ApprovalChoice, Optional[ApprovalVerdict]]:
    k = key.strip()

    if k in ("tab", "up", "down", "shift+tab"):
        return choice.toggle(), None

    if k in ("y", "Y"):
        return choice, ApprovalVerdict.APPROVE

    if k in ("n", "N"):
        return choice, ApprovalVerdict.DENY

    if k in ("esc", "q", "Q"):
        return choice, ApprovalVerdict.CANCEL

    if k == "enter":
        verdict = ApprovalVerdict.APPROVE if choice == ApprovalChoice.APPROVE else ApprovalVerdict.DENY
        return choice, verdict

    return choice, None
