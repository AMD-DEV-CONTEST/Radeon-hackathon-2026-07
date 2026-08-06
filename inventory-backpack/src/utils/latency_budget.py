# utils/latency_budget.py

import time
import asyncio
from typing import Optional
from dataclasses import dataclass


@dataclass
class LatencyBudget:
    """
    端到端延迟预算分配
    """
    total_budget_ms: float = 3000.0      # 总预算3秒
    
    # 各阶段预算（毫秒）
    queue_wait_ms: float = 100.0          # 队列等待
    network_ms: float = 50.0              # 网络传输
    prefill_ms: float = 200.0             # prefill计算
    first_token_ms: float = 300.0         # 首token目标
    decode_per_token_ms: float = 20.0     # 每token解码
    
    def is_budget_violation(self, actual_ttfb_ms: float) -> bool:
        """检查是否超出延迟预算"""
        return actual_ttfb_ms > (self.queue_wait_ms + self.network_ms + 
                                  self.prefill_ms + self.first_token_ms)
    
    def get_remaining_for_decode(self, used_ttfb_ms: float) -> float:
        """计算留给decode的预算"""
        return self.total_budget_ms - used_ttfb_ms


class LatencyBudgetEnforcer:
    """
    延迟预算强制执行：超预算请求降级处理
    """
    def __init__(self, budget: LatencyBudget):
        self.budget = budget
        self._violation_count = 0
        self._total_count = 0
    
    def check_request(self, estimated_complexity: float) -> tuple[bool, Optional[str]]:
        """
        检查请求是否在预算内
        返回: (是否接受, 拒绝原因)
        """
        self._total_count += 1
        
        # 根据复杂度估算TTFB
        estimated_ttfb = self._estimate_ttfb(estimated_complexity)
        
        if estimated_ttfb > self.budget.first_token_ms * 2:
            self._violation_count += 1
            return False, f"Estimated TTFB {estimated_ttfb:.0f}ms exceeds budget"
        
        return True, None
    
    def _estimate_ttfb(self, complexity: float) -> float:
        """
        根据请求复杂度估算TTFB
        complexity: 输入token数的估计值
        """
        # 简化的线性模型，实际应基于历史数据
        base_prefill = 0.1 * complexity  # 0.1ms/token
        return (self.budget.queue_wait_ms + self.budget.network_ms + 
                base_prefill + self.budget.first_token_ms)
    
    @property
    def violation_rate(self) -> float:
        if self._total_count == 0:
            return 0.0
        return self._violation_count / self._total_count