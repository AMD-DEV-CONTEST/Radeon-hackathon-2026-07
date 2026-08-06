"""Agent 基类。每个 agent 是流水线的一个阶段，输入/输出都是落盘的结构化资产。"""
from __future__ import annotations

from ..context import Context


class Agent:
    name: str = "agent"
    #: 该 agent 默认使用的模型档位(可被子类覆盖)，体现“按复杂度选模型”
    tier: str = "structure"

    def __init__(self, ctx: Context):
        self.ctx = ctx
        self.log = ctx.log

    def info(self, msg: str) -> None:
        self.log.info(f"[{self.name}] {msg}")

    def warn(self, msg: str) -> None:
        self.log.warning(f"[{self.name}] {msg}")

    def run(self, *args, **kwargs):  # noqa: D401
        raise NotImplementedError
