"""超长任务执行内核 `xai-grok-runner`（§10 设计落地）。

机制：把超长任务拆成里程碑，逐步走 control_loop，每步落盘 checkpoint，
里程碑处过质量门，失败回退到上一 checkpoint。支持断点续跑（进程崩/关机可恢复）。
这是 XAI 的 "workflow 级" 执行能力，与 orchestra(编排)/画布(可视化) 三位一体。
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field, asdict
from typing import Callable, Optional


@dataclass
class StepResult:
    milestone: str
    output: str
    passed: bool
    notes: str = ""


@dataclass
class RunState:
    goal: str
    milestones: list[str] = field(default_factory=list)
    current: int = 0
    history: list[dict] = field(default_factory=list)
    done: bool = False


class Runner:
    """超长任务执行器：分步 + checkpoint + 质量门 + 续跑。"""

    def __init__(self, state_path: str = ".xai_runner_state.json"):
        self.state_path = state_path
        self.state: Optional[RunState] = None

    # ---- 生命周期 ----
    def plan(self, goal: str, milestones: list[str]) -> RunState:
        self.state = RunState(goal=goal, milestones=milestones, current=0)
        self._save()
        return self.state

    def resume(self) -> bool:
        """从磁盘恢复。返回是否成功恢复已有任务。"""
        if not os.path.exists(self.state_path):
            return False
        with open(self.state_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.state = RunState(**data)
        return True

    def _save(self) -> None:
        with open(self.state_path, "w", encoding="utf-8") as f:
            json.dump(asdict(self.state), f, ensure_ascii=False, indent=2)

    # ---- 单步执行 ----
    def step(self, exec_fn: Callable[[str], str],
             quality_gate: Callable[[StepResult], bool]) -> StepResult:
        """执行当前里程碑一步，过质量门；失败回退（不前进）。"""
        if self.state is None:
            raise RuntimeError("未 plan 也未 resume")
        if self.state.done or self.state.current >= len(self.state.milestones):
            raise RuntimeError("任务已完成，无更多步骤")
        m = self.state.milestones[self.state.current]
        output = exec_fn(m)
        res = StepResult(milestone=m, output=output, passed=quality_gate(StepResult(m, output, True)))
        if res.passed:
            self.state.history.append({"milestone": m, "output": output, "passed": True})
            self.state.current += 1
            if self.state.current >= len(self.state.milestones):
                self.state.done = True
        else:
            # 回退：不前进，记录失败（复用 .bak 思路，不污染已完成部分）
            self.state.history.append({"milestone": m, "output": output, "passed": False,
                                       "notes": "质量门未过，已回退"})
        self._save()
        return res

    def run(self, exec_fn: Callable[[str], str],
            quality_gate: Callable[[StepResult], bool]) -> list[StepResult]:
        """一次性跑完所有里程碑（含续跑场景）。"""
        results: list[StepResult] = []
        while self.state and not self.state.done and self.state.current < len(self.state.milestones):
            results.append(self.step(exec_fn, quality_gate))
        return results

    def reset(self) -> None:
        if os.path.exists(self.state_path):
            shutil.move(self.state_path, self.state_path + ".bak")
        self.state = None
