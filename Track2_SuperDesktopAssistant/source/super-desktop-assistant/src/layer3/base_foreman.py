"""
Layer 3: 领域工头基类（v2.0）

所有工头（LLMForeman、ImageForeman、TTSForeman）继承自此抽象基类。

v2.0 共有特性：
- 独立的策略缓存（Prompt 模板库）
- 独立的工作区隔离（workspaces），按 task_id 隔离
- 独立的重试与降级策略
- 负责向公共记忆写入最终结果摘要及结构化经验片段
- 异步并发调用（向第4层同时下发多个指令）
- 根据 reset_context 信号决定是否清空工作区上下文
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any
from loguru import logger

from ..layer4.mcp_contract import MCPError, MCPResponse, mcp_error_factory, is_retryable, get_timeout_for_type
from ..memory.public_memory import get_public_memory, MemoryType, MemoryEntry


# ═══════════════════════════════════════════════════════════════
# 工作区
# ═══════════════════════════════════════════════════════════════

@dataclass
class Workspace:
    """单个任务的工作区。"""
    task_id: str
    task_type: str = ""
    context: list[dict] = field(default_factory=list)      # 对话/任务历史
    last_summary: str = ""                                   # 进度摘要
    created_at: float = field(default_factory=time.time)
    reset_count: int = 0                                     # 上下文重置次数
    # v3 P0b: 单次单 API 锁定 —— 任务生命周期内锁定的供应商/模型，禁止中途切换
    api_provider: str | None = None
    api_model: str | None = None

    def clear_context(self):
        """清空上下文（收到 reset_context 信号时）。"""
        self.context.clear()
        self.last_summary = ""
        self.reset_count += 1
        logger.info(f"[WS] [{self.task_id}] 上下文已清空 (reset #{self.reset_count})")


# ═══════════════════════════════════════════════════════════════
# 基类
# ═══════════════════════════════════════════════════════════════

class BaseForeman(ABC):
    """
    领域工头抽象基类。

    子类必须实现：
    - foreman_type: 工头类型标识
    - _execute_impl(): 实际执行逻辑
    """

    # 工头配置
    foreman_type: str = "base"
    max_retries: int = 2
    base_timeout: float = 30.0
    max_context_turns: int = 6        # 最大保留历史轮次

    def __init__(self):
        self._workspaces: dict[str, Workspace] = {}
        self._strategy_cache: dict[str, str] = {}   # Prompt 模板缓存

    # ── 主入口 ──

    async def execute(self, task: dict) -> dict:
        """
        执行工头任务。

        Args:
            task: 第2层下发的任务包
                {
                    "task_id": str,
                    "task_type": "image|text|audio",
                    "user_input": str,
                    "entities": dict,
                    "reset_context": bool,
                    "memory_manifest": dict,
                    "depends_on": list,
                }

        Returns:
            {"status": "success|error", "data": ..., "experience": MemoryEntry|None}
        """
        task_id = task.get("task_id", "unknown")
        task_type = task.get("task_type", self.foreman_type)
        user_input = task.get("user_input", "")
        reset_context = task.get("reset_context", False)

        # 获取或创建工作区
        ws = self._get_workspace(task_id, task_type)

        # 上下文重置
        if reset_context:
            ws.clear_context()

        # 执行
        # H4 修复：executor 路径下由 Executor 统一重试，工头不再自试（避免双重重试/费用翻倍）
        no_retry = task.get("no_retry", False)
        t_start = time.perf_counter()
        try:
            if no_retry:
                result = await self._execute_impl(task, ws)
            else:
                result = await self._execute_with_retry(task, ws)
            elapsed = (time.perf_counter() - t_start) * 1000
            logger.info(f"[FM:{self.foreman_type}] [{task_id}] 完成 ({elapsed:.0f}ms)")

            # 写入结果摘要到公共记忆
            memory_entry = self._write_result_memory(task, result, elapsed)

            return {
                "status": "success",
                "data": result,
                "elapsed_ms": elapsed,
                "memory_entry_id": memory_entry.memory_id if memory_entry else None,
            }

        except Exception as e:
            elapsed = (time.perf_counter() - t_start) * 1000
            logger.error(f"[FM:{self.foreman_type}] [{task_id}] 失败 ({elapsed:.0f}ms): {e}")

            # 尝试写入经验记忆
            self._write_experience_memory(task, str(e))

            mcp_err = mcp_error_factory(e, node_id=task_id)
            return {
                "status": "error",
                "error": {
                    "code": mcp_err.code,
                    "message": mcp_err.message,
                    "retryable": mcp_err.retryable,
                    "suggested_action": mcp_err.suggested_action,
                },
                "elapsed_ms": elapsed,
            }

    # ── 重试逻辑 ──

    async def _execute_with_retry(self, task: dict, ws: Workspace) -> Any:
        """带重试的执行。永久错误直接抛出，瞬态错误重试。"""
        last_error = None

        for attempt in range(self.max_retries + 1):
            try:
                return await self._execute_impl(task, ws)
            except Exception as e:
                last_error = e
                # 永久错误不重试
                if not is_retryable(mcp_error_factory(e)):
                    raise

                if attempt < self.max_retries:
                    delay = 0.5 * (2 ** attempt)  # 指数退避
                    import asyncio
                    logger.warning(
                        f"[FM:{self.foreman_type}] 重试 {attempt + 1}/{self.max_retries} ({delay:.1f}s): {e}"
                    )
                    await asyncio.sleep(delay)
                else:
                    raise

        raise last_error

    # ── 子类必须实现 ──

    @abstractmethod
    async def _execute_impl(self, task: dict, ws: Workspace) -> Any:
        """实际执行逻辑。由具体工头实现。"""
        ...

    # ── 工作区管理 ──

    def _get_workspace(self, task_id: str, task_type: str = "") -> Workspace:
        """获取或创建任务工作区。"""
        if task_id not in self._workspaces:
            self._workspaces[task_id] = Workspace(
                task_id=task_id,
                task_type=task_type,
            )
            logger.info(f"[FM:{self.foreman_type}] 新工作区: {task_id}")
        return self._workspaces[task_id]

    def clear_workspace(self, task_id: str):
        """清空指定任务的工作区。"""
        if task_id in self._workspaces:
            self._workspaces[task_id].clear_context()

    def clear_all_workspaces(self):
        """清空所有工作区。"""
        self._workspaces.clear()
        logger.info(f"[FM:{self.foreman_type}] 所有工作区已清空")

    # ── 策略缓存 ──

    def get_cached_strategy(self, key: str) -> str | None:
        """从策略缓存中获取 Prompt 模板。"""
        return self._strategy_cache.get(key)

    def set_cached_strategy(self, key: str, template: str):
        """存入策略缓存。"""
        self._strategy_cache[key] = template

    # ── 记忆写入 ──

    def _write_result_memory(self, task: dict, result: Any, elapsed_ms: float) -> MemoryEntry | None:
        """写入结果摘要到公共记忆。"""
        try:
            mem = get_public_memory()
            task_id = task.get("task_id", "")
            task_type = task.get("task_type", self.foreman_type)
            user_input = task.get("user_input", "")

            # 摘要化：结果太长就截断
            result_str = str(result)[:500]

            return mem.write_result(
                task_id=task_id,
                task_type=task_type,
                content=f"[{elapsed_ms:.0f}ms] {user_input[:100]} → {result_str[:200]}",
                subject=user_input[:50],
                tags=[self.foreman_type, "completed"],
                created_by=self.foreman_type,
            )
        except Exception as e:
            logger.warning(f"[FM:{self.foreman_type}] 写入结果记忆失败: {e}")
            return None

    def _write_experience_memory(self, task: dict, error_msg: str):
        """写入失败经验到公共记忆。"""
        try:
            mem = get_public_memory()
            task_type = task.get("task_type", self.foreman_type)
            user_input = task.get("user_input", "")

            # 提取关键错误信息
            error_short = error_msg[:200]

            mem.write_experience(
                task_type=task_type,
                subject=user_input[:60],
                content=f"失败原因: {error_short}",
                tags=["failure", self.foreman_type, "ineffective"],
                created_by=self.foreman_type,
            )
        except Exception as e:
            logger.warning(f"[FM:{self.foreman_type}] 写入经验记忆失败: {e}")

    # ── Prompt 注入防护 ──

    @staticmethod
    def _sanitize_input(text: str) -> str:
        """
        安全过滤用户输入，防止 Prompt 注入。

        移除或转义常见的注入模式：
        - 系统指令覆盖 ("system:", "you are now")
        - 角色重置 ("ignore previous", "forget all")
        - 代码块注入 ("```system")
        """
        if not text:
            return text

        # 简单白名单方式：移除明确危险的模式
        dangerous_patterns = [
            ("ignore all previous instructions", "[FILTERED]"),
            ("ignore previous", "[FILTERED]"),
            ("forget all", "[FILTERED]"),
            ("```system", "[FILTERED]"),
            ("<|im_start|>system", "[FILTERED]"),
            ("<|im_end|>", "[FILTERED]"),
        ]

        sanitized = text
        for pattern, replacement in dangerous_patterns:
            sanitized = sanitized.replace(pattern, replacement)
            sanitized = sanitized.replace(pattern.upper(), replacement)

        return sanitized
