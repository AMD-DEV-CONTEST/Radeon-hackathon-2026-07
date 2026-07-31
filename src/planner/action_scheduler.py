"""
Module 6: Action Scheduler
Sequence actions with preconditions and postconditions.
"""
from typing import List, Dict, Optional


class ActionScheduler:
    def __init__(self):
        self.current_plan = []
        self.current_index = 0
        self.executed = []

    def load_plan(self, actions: List[Dict]):
        self.current_plan = actions
        self.current_index = 0
        self.executed = []

    def next_action(self) -> Optional[Dict]:
        if self.current_index < len(self.current_plan):
            action = self.current_plan[self.current_index]
            self.current_index += 1
            return action
        return None

    def peek(self, n: int = 1) -> List[Dict]:
        return self.current_plan[self.current_index:self.current_index + n]

    def mark_done(self, action: Dict):
        self.executed.append(action)

    def is_complete(self) -> bool:
        return self.current_index >= len(self.current_plan)

    def get_progress(self) -> Dict:
        return {
            "total": len(self.current_plan),
            "completed": len(self.executed),
            "current": self.current_index,
            "percent": (len(self.executed) / len(self.current_plan) * 100) if self.current_plan else 0,
        }

    def reset(self):
        self.current_index = 0
        self.executed = []
