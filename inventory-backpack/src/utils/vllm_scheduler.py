# utils/vllm_scheduler.py 优化建议

import asyncio
import time
from collections import deque
from typing import Optional, List, Dict
from dataclasses import dataclass
import heapq

@dataclass
class QueuedRequest:
    priority: float  # 优先级分数（越小越优先）
    arrival_time: float
    request_id: str
    estimated_prefill_tokens: int
    payload: dict
    
    def __lt__(self, other):
        return self.priority < other.priority


class VLLMScheduler:
    """
    平滑调度器：消除请求突发，稳定TTFT
    """
    def __init__(
        self,
        max_batch_size: int = 16,
        max_prefill_batch_tokens: int = 4096,
        target_ttfb_ms: float = 200.0,  # 目标首token延迟
        smoothing_window: float = 0.1,  # 平滑窗口（秒）
        enable_priority_queue: bool = True,
    ):
        self.max_batch_size = max_batch_size
        self.max_prefill_batch_tokens = max_prefill_batch_tokens
        self.target_ttfb_ms = target_ttfb_ms
        self.smoothing_window = smoothing_window
        self.enable_priority_queue = enable_priority_queue
        
        # 请求队列（优先级队列）
        self._queue: List[QueuedRequest] = []
        self._simple_queue: deque = deque()  # 非优先级模式
        
        # 速率控制
        self._last_dispatch_time = 0.0
        self._dispatch_interval = 0.01  # 最小调度间隔10ms
        
        # 统计
        self._recent_ttfb: deque = deque(maxlen=100)
        self._lock = asyncio.Lock()
    
    async def submit(self, request: dict) -> str:
        """提交请求到调度队列"""
        # 估算prefill长度（用于优先级排序）
        estimated_tokens = self._estimate_prefill_tokens(request)
        
        # 计算优先级：短请求优先，避免长请求阻塞
        priority = self._calculate_priority(estimated_tokens, time.time())
        
        queued = QueuedRequest(
            priority=priority,
            arrival_time=time.time(),
            request_id=request.get("id", f"req_{time.time()}"),
            estimated_prefill_tokens=estimated_tokens,
            payload=request,
        )
        
        async with self._lock:
            if self.enable_priority_queue:
                heapq.heappush(self._queue, queued)
            else:
                self._simple_queue.append(queued)
        
        return queued.request_id
    
    def _calculate_priority(self, prefill_tokens: int, arrival_time: float) -> float:
        """
        优先级计算：
        - 短prefill优先（减少TTFT方差）
        - 早到达优先（FCFS基础）
        """
        # 时间戳作为基础（保证FCFS）
        time_component = arrival_time
        
        # 长度惩罚：长请求优先级降低
        # 使用对数避免极端惩罚
        length_penalty = 0.001 * prefill_tokens * (prefill_tokens ** 0.5)
        
        return time_component + length_penalty
    
    async def get_batch(self, max_wait_ms: float = 5.0) -> Optional[List[dict]]:
        """
        获取一批请求，实现平滑出队
        
        策略：
        1. 等待小批量积累（但不超过max_wait_ms）
        2. 控制batch的prefill token总数
        3. 避免单个长请求阻塞整个batch
        """
        start_time = time.time()
        max_wait = max_wait_ms / 1000.0
        
        collected = []
        total_prefill_tokens = 0
        
        while len(collected) < self.max_batch_size:
            elapsed = time.time() - start_time
            
            # 检查队列
            async with self._lock:
                if not self._queue and not self._simple_queue:
                    if elapsed < max_wait:
                        await asyncio.sleep(0.001)
                        continue
                    break
                
                # 获取下一个请求
                if self.enable_priority_queue and self._queue:
                    next_req = heapq.heappop(self._queue)
                elif self._simple_queue:
                    next_req = self._simple_queue.popleft()
                else:
                    break
                
                # 检查prefill token限制
                if (total_prefill_tokens + next_req.estimated_prefill_tokens 
                    > self.max_prefill_batch_tokens and collected):
                    # 放回队列，下次处理
                    heapq.heappush(self._queue, next_req)
                    break
                
                collected.append(next_req)
                total_prefill_tokens += next_req.estimated_prefill_tokens
        
        if not collected:
            return None
        
        # 记录调度信息
        self._last_dispatch_time = time.time()
        
        return [req.payload for req in collected]
    
    def _estimate_prefill_tokens(self, request: dict) -> int:
        """估算请求的prefill token数"""
        # 从prompt估算
        prompt = request.get("prompt", "")
        if isinstance(prompt, list):
            # Chat format
            text = " ".join([p.get("content", "") for p in prompt])
        else:
            text = prompt
        
        # 粗略估算：1 token ≈ 4 chars (英文) 或 1 token ≈ 1 char (中文)
        # 更精确应该用tokenizer，但这里快速估算
        return max(1, len(text) // 4 + 1)
    
    def update_ttfb_feedback(self, actual_ttfb_ms: float):
        """接收TTFB反馈，动态调整"""
        self._recent_ttfb.append(actual_ttfb_ms)
        
        # 如果TTFB持续高于目标，减小batch size
        if len(self._recent_ttfb) >= 10:
            avg_ttfb = sum(self._recent_ttfb) / len(self._recent_ttfb)
            if avg_ttfb > self.target_ttfb_ms * 1.5:
                self.max_batch_size = max(1, self.max_batch_size - 1)
                self.max_prefill_batch_tokens = int(self.max_prefill_batch_tokens * 0.9)
            elif avg_ttfb < self.target_ttfb_ms * 0.5:
                self.max_batch_size = min(64, self.max_batch_size + 2)
                self.max_prefill_batch_tokens = int(self.max_prefill_batch_tokens * 1.1)