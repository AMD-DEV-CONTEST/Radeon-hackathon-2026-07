"""
Abstract base class and decision outcome data structures for tool authorization.
Provides the core contract for evaluating tool confirmation requests.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum


class DecisionOutcome(Enum):
    ALLOW = "allow"
    DENY = "deny"


@dataclass
class Decision:
    outcome: DecisionOutcome
    reason: str = ""
    is_automated: bool = False

    @property
    def is_allowed(self) -> bool:
        return self.outcome == DecisionOutcome.ALLOW


@dataclass
class ToolRequest:
    tool: str
    content: str
    round_num: int = 1
    session_id: str = ""


class Authorizer(ABC):
    @abstractmethod
    def decide(self, request: ToolRequest) -> Decision:
        pass
