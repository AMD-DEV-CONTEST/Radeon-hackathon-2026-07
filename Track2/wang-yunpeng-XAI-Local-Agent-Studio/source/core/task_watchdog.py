"""任务看门狗 — 监控子 Agent 派发超时，自动降级回退到主 Agent 接管。

架构：
  主 Agent dispatch_task → watch() 注册任务（带超时）
  └─ 超时触发 → _fallback_handler 降级执行
  └─ 正常完成 → resolve() 清理

用法：
  from core.task_watchdog import global_watchdog
  task_id = global_watchdog.watch("dispatch", timeout_s=45, fallback=my_fallback)
  # ... dispatch_task ...
  global_watchdog.resolve(task_id)
"""

import time
import threading
import uuid
from typing import Callable, Optional, Dict, Any
from dataclasses import dataclass, field


@dataclass
class TaskRecord:
    task_id: str
    task_type: str          # "dispatch" | "execute" | "file_op"
    started_at: float
    timeout_s: float
    fallback: Optional[Callable] = None
    resolved: bool = False
    result: Optional[Any] = None
    error: Optional[str] = None


class TaskWatchdog:
    """后台监控线程，定期扫描超时任务并触发降级。"""

    def __init__(self, scan_interval: float = 2.0):
        self._tasks: Dict[str, TaskRecord] = {}
        self._lock = threading.Lock()
        self._scan_interval = scan_interval
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._fallback_log: list = []  # 降级历史（最近 100 条）

    # ---- 公共 API ----

    def watch(self, task_type: str, timeout_s: float = 45,
              fallback: Optional[Callable] = None) -> str:
        """注册一个监视任务，返回 task_id。"""
        task_id = f"watch_{uuid.uuid4().hex[:8]}"
        record = TaskRecord(
            task_id=task_id,
            task_type=task_type,
            started_at=time.time(),
            timeout_s=timeout_s,
            fallback=fallback,
        )
        with self._lock:
            self._tasks[task_id] = record
        self._ensure_running()
        return task_id

    def resolve(self, task_id: str, result: Any = None) -> bool:
        """标记任务完成。"""
        with self._lock:
            record = self._tasks.get(task_id)
            if record:
                record.resolved = True
                record.result = result
                return True
        return False

    def fail(self, task_id: str, error: str) -> bool:
        """标记任务失败。"""
        with self._lock:
            record = self._tasks.get(task_id)
            if record:
                record.resolved = True
                record.error = error
                return True
        return False

    def status(self) -> dict:
        """返回当前监控状态。"""
        with self._lock:
            active = [r for r in self._tasks.values() if not r.resolved]
            return {
                "active_count": len(active),
                "active_tasks": [
                    {
                        "task_id": r.task_id,
                        "type": r.task_type,
                        "elapsed_s": round(time.time() - r.started_at, 1),
                        "timeout_s": r.timeout_s,
                    }
                    for r in active
                ],
                "fallback_count": len(self._fallback_log),
                "total_tracked": len(self._tasks),
            }

    def history(self, limit: int = 20) -> list:
        """最近降级记录。"""
        return self._fallback_log[-limit:]

    def stop(self):
        """停止后台线程。"""
        self._running = False

    # ---- 内部 ----

    def _ensure_running(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._scan_loop, daemon=True)
        self._thread.start()

    def _scan_loop(self):
        while self._running:
            time.sleep(self._scan_interval)
            self._scan()

    def _scan(self):
        now = time.time()
        expired = []
        with self._lock:
            for tid, record in list(self._tasks.items()):
                if record.resolved:
                    continue
                if now - record.started_at > record.timeout_s:
                    expired.append(record)

        for record in expired:
            self._trigger_fallback(record)

    def _trigger_fallback(self, record: TaskRecord):
        """触发降级回调。"""
        msg = (
            f"[WATCHDOG] 任务 {record.task_id} ({record.task_type}) "
            f"超时 {record.timeout_s}s，触发降级"
        )
        self._fallback_log.append({
            "ts": time.time(),
            "task_id": record.task_id,
            "type": record.task_type,
            "message": msg,
        })
        # 只保留最近 100 条
        if len(self._fallback_log) > 100:
            self._fallback_log = self._fallback_log[-100:]

        try:
            if record.fallback:
                result = record.fallback()
                record.result = result
            record.resolved = True
        except Exception as e:
            record.error = str(e)
            record.resolved = True


# 全局单例
global_watchdog = TaskWatchdog(scan_interval=3.0)
