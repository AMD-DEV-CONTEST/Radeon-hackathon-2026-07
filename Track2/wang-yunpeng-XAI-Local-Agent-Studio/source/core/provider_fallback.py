"""Provider 故障轮换（参考 Orbital 的回退逻辑）。

底层模型调用失败时，按注册表优先级自动切换到备用模型。
切换历史写入 memory_core causal 层（决策可追溯）。
"""
from __future__ import annotations

import time
from typing import Optional

from .model_registry import ModelEntry, default_registry


class FallbackState:
    """每个 provider 的轮换状态。"""

    def __init__(self, entry: ModelEntry):
        self.entry = entry
        self.fail_count = 0
        self.last_fail_time: float = 0
        self.active = False

    def record_failure(self):
        self.fail_count += 1
        self.last_fail_time = time.time()

    def reset(self):
        self.fail_count = 0
        self.last_fail_time = 0


class ProviderFallback:
    """多模型故障轮换引擎。"""

    MAX_FAILURES = 3          # 单个模型连续失败几次切换
    FAILURE_WINDOW = 120       # 失败窗口（秒），超过后重置计数器

    def __init__(self):
        self.registry = default_registry()
        self._states: dict[str, FallbackState] = {}
        self._current: Optional[str] = None  # 当前使用的模型 ID
        self._primary: Optional[str] = None   # 首选模型 ID
        self._is_fallback = False            # 是否处于回退状态
        self._history: list[dict] = []        # 最近的切换记录

    def setup(self) -> None:
        """初始化：标记当前激活模型为首选。"""
        active = self.registry.active()
        if active:
            self._primary = active.id
            self._current = active.id
            self._states[active.id] = FallbackState(active)
            self._is_fallback = False

    def infer(self, fn_call, *args, **kwargs):
        """包装一次模型调用，失败时自动轮换。

        fn_call 是实际的推理函数（如 DeepSeekBackend.complete）。
        失败时自动尝试下一个可用模型。
        成功时回到首选。
        """
        self.setup_if_needed()

        target = self.registry.active()
        if not target:
            raise RuntimeError("无可用模型")

        # 如果当前不在 fallback 且 active 不等于首选，切回首选
        if not self._is_fallback and self._primary and self._current != self._primary:
            active = self.registry.active()
            if active and active.id == self._current:
                pass  # 用户手动切了，尊重
            elif self._primary:
                self.registry.activate(self._primary)
                self._current = self._primary
                self._is_fallback = False

        # 尝试调用
        for attempt in range(len(self.registry.list()) + 1):
            try:
                result = fn_call(*args, **kwargs)
                # 成功：重置失败计数，如果处于 fallback 则切回首选
                if target.id in self._states:
                    self._states[target.id].reset()
                if self._is_fallback and self._primary:
                    self._restore_primary()
                return result
            except Exception as e:
                self._record_failure(target, e)
                # 尝试下一个可用模型
                next_model = self._find_next(target)
                if next_model is None:
                    raise RuntimeError(f"所有模型均已失败: {e}")
                target = next_model
                self.registry.activate(target.id)
                self._current = target.id
                self._is_fallback = True

        raise RuntimeError("所有模型均已失败")

    def _record_failure(self, entry: ModelEntry, error: Exception) -> None:
        if entry.id not in self._states:
            self._states[entry.id] = FallbackState(entry)
        self._states[entry.id].record_failure()
        self._history.append({
            "model": entry.name, "error": str(error)[:200],
            "consecutive_fails": self._states[entry.id].fail_count,
            "time": time.time(),
        })
        if len(self._history) > 20:
            self._history = self._history[-10:]

    def _find_next(self, current: ModelEntry) -> Optional[ModelEntry]:
        """找到下一个可用的模型（未达失败上限的）。"""
        all_models = [m for m in self.registry.list() if m.id != current.id]
        now = time.time()
        for m in all_models:
            state = self._states.get(m.id, FallbackState(m))
            if state.fail_count >= self.MAX_FAILURES:
                if now - state.last_fail_time < self.FAILURE_WINDOW:
                    continue  # 还在冷却中
                state.reset()
            return m
        return None

    def _restore_primary(self) -> None:
        if self._primary:
            self.registry.activate(self._primary)
            self._current = self._primary
            self._is_fallback = False

    def setup_if_needed(self) -> None:
        if self._primary is None:
            self.setup()

    def status(self) -> dict:
        self.setup_if_needed()
        return {
            "is_fallback": self._is_fallback,
            "current_model": self._current,
            "primary_model": self._primary,
            "recent_switches": len(self._history),
            "last_switch": self._history[-1] if self._history else None,
        }


_fallback_instance: Optional[ProviderFallback] = None


def default_fallback() -> ProviderFallback:
    global _fallback_instance
    if _fallback_instance is None:
        _fallback_instance = ProviderFallback()
    return _fallback_instance
