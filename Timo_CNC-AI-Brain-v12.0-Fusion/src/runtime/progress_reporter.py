"""
流式进度报告器 — 向 HMI/日志发送实时进度。
所有消息为标准 JSON。
"""
import json
from datetime import datetime
from typing import Optional
from src.runtime.event_bus import EventBus


class ProgressReporter:
    """向 HMI 发送实时进度的轻量报告器。"""

    CHANNEL = "hmi.meeting_progress"

    def __init__(self, event_bus: EventBus):
        self.bus = event_bus

    def report(self, phase: str, expert: Optional[str] = None, message: str = ""):
        """
        上报进度。
        
        Args:
            phase: 阶段标识 (start/analyzing/done/vetoed/ceo/complete/error)
            expert: 当前专家名称
            message: 可读消息
        """
        payload = {
            "phase": phase,
            "expert": expert,
            "message": message,
            "timestamp": datetime.now().isoformat(),
        }
        self.bus.publish(self.CHANNEL, payload)

    def start(self, message: str = "专家会议开始..."):
        """快捷：开始会议。"""
        self.report("start", message=message)

    def analyzing(self, expert: str):
        """快捷：某专家正在分析。"""
        self.report("analyzing", expert=expert, message=f"{expert} 正在分析...")

    def done(self, expert: str):
        """快捷：某专家分析完成。"""
        self.report("done", expert=expert, message=f"{expert} 分析完成")

    def vetoed(self, by: str):
        """快捷：被否决。"""
        self.report("vetoed", expert=by, message=f"被 {by} 一票否决")

    def ceo_deciding(self):
        """快捷：CEO 裁决中。"""
        self.report("ceo", message="CEO 正在做最终裁决...")

    def complete(self, message: str = "会议决策完成"):
        """快捷：会议完成。"""
        self.report("complete", message=message)

    def error(self, message: str):
        """快捷：异常。"""
        self.report("error", message=message)

    def get_progress_json(self) -> str:
        """获取进度历史的标准 JSON。"""
        return self.bus.to_json(self.CHANNEL)
