"""Agent Loop 五重安全闸门（参考 Orbital 设计方案，融入 Guardian 治理体系）。

与 Guardian 的关系：Guardian 做"操作前审批"（P0/P1/P2 危险动作拦截），
LoopSafety 做"运行中模式保护"（检测异常执行模式）。

5 重闸门均独立可配置，支持 3 档预设（推荐/严格/宽松）+ 自定义数值。
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import threading
from dataclasses import dataclass, field, asdict
from typing import Optional


SAFETY_CONFIG_PATH = os.path.join(
    os.environ.get("XAI_HOME", os.path.expanduser("~/.xai")), "loop_safety.json"
)

# 预设方案
PRESETS = {
    "recommended": {
        "token_budget": 200_000_000,
        "repetition_limit": 5,
        "ping_pong_limit": 3,
        "error_consecutive_limit": 3,
        "context_overflow_limit": 3,
    },
    "strict": {
        "token_budget": 50_000_000,
        "repetition_limit": 3,
        "ping_pong_limit": 2,
        "error_consecutive_limit": 2,
        "context_overflow_limit": 2,
    },
    "relaxed": {
        "token_budget": 500_000_000,
        "repetition_limit": 10,
        "ping_pong_limit": 5,
        "error_consecutive_limit": 5,
        "context_overflow_limit": 5,
    },
}


@dataclass
class SafetyConfig:
    token_budget: int = 200_000_000
    repetition_limit: int = 5
    ping_pong_limit: int = 3
    error_consecutive_limit: int = 3
    context_overflow_limit: int = 3

    def to_dict(self) -> dict:
        return asdict(self)


class LoopSafety:
    """Agent 循环五重安全闸门。"""

    def __init__(self, config: Optional[SafetyConfig] = None, config_path: str = SAFETY_CONFIG_PATH):
        self.config_path = config_path
        self.config = config or self._load()
        self._lock = threading.Lock()
        # 运行时计数器
        self._token_usage: int = 0
        self._action_hashes: list[str] = []
        self._last_results: list[str] = []
        self._consecutive_errors: int = 0
        self._locked_tools: set[str] = set()
        self._context_overflows: int = 0

    def _load(self) -> SafetyConfig:
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return SafetyConfig(**{k: data.get(k, getattr(SafetyConfig(), k)) for k in SafetyConfig.__dataclass_fields__})
            except Exception:
                pass
        return SafetyConfig()

    def save(self, preset: str | None = None, **overrides) -> SafetyConfig:
        if preset and preset in PRESETS:
            self.config = SafetyConfig(**PRESETS[preset])
        for k, v in overrides.items():
            if hasattr(self.config, k):
                setattr(self.config, k, v)
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(self.config.to_dict(), f, indent=2)
        return self.config

    def reset(self):
        """每次新会话或用户重新输入时调用。"""
        with self._lock:
            self._token_usage = 0
            self._action_hashes.clear()
            self._last_results.clear()
            self._consecutive_errors = 0
            self._context_overflows = 0

    def _hash_action(self, action_type: str, params: str) -> str:
        return hashlib.md5(f"{action_type}:{params[:200]}".encode()).hexdigest()[:12]

    def check(self, action_type: str = "", params: str = "", tokens: int = 0) -> dict:
        """在每次循环迭代前调用。返回 {ok, reason, action} 供 Caller 处理。"""
        with self._lock:
            self._token_usage += tokens

            # 1) Token 预算
            if self._token_usage > self.config.token_budget:
                return {"ok": False, "reason": f"Token 预算耗尽（{self._token_usage}/{self.config.token_budget}）", "action": "hard_stop"}

            # 2) 重复检测
            if action_type:
                h = self._hash_action(action_type, params)
                self._action_hashes.append(h)
                if len(self._action_hashes) >= self.config.repetition_limit:
                    recent = self._action_hashes[-self.config.repetition_limit:]
                    if len(set(recent)) == 1:
                        self._action_hashes = self._action_hashes[-1:]
                        return {"ok": False, "reason": f"重复动作 {self.config.repetition_limit} 次（{action_type}），强制换方案", "action": "force_new_approach"}

            # 3) 乒乓球检测
            if len(self._last_results) >= self.config.ping_pong_limit * 2:
                pair = tuple(self._last_results[-(self.config.ping_pong_limit * 2):])
                half = self.config.ping_pong_limit
                if pair[:half] == pair[half:]:
                    return {"ok": False, "reason": f"乒乓球循环 {self.config.ping_pong_limit} 次相同来回，打断循环", "action": "break_cycle"}

        return {"ok": True, "reason": "", "action": "continue"}

    def record_error(self, tool_name: str = "", error: str = "") -> dict:
        """记录连续错误，触发断路器。"""
        with self._lock:
            self._consecutive_errors += 1
            if self._consecutive_errors >= self.config.error_consecutive_limit and tool_name:
                self._locked_tools.add(tool_name)
                return {"ok": False, "reason": f"断路器触发：{tool_name} 连续 {self._consecutive_errors} 次错误，已锁定", "action": "lock_tool"}
            return {"ok": False, "reason": f"错误 #{self._consecutive_errors}", "action": "continue"}

    def record_result(self, result_summary: str) -> None:
        with self._lock:
            self._last_results.append(result_summary)
            if len(self._last_results) > 50:
                self._last_results = self._last_results[-30:]

    def check_context(self) -> dict:
        with self._lock:
            self._context_overflows += 1
            if self._context_overflows >= self.config.context_overflow_limit:
                return {"ok": False, "reason": f"上下文溢出 {self._context_overflows} 次，硬停", "action": "hard_stop"}
            return {"ok": True, "reason": f"上下文压缩 #{self._context_overflows}", "action": "compress"}

    def unlock_tool(self, tool_name: str) -> None:
        with self._lock:
            self._locked_tools.discard(tool_name)

    def is_tool_locked(self, tool_name: str) -> bool:
        with self._lock:
            return tool_name in self._locked_tools

    def status(self) -> dict:
        with self._lock:
            return {
                "config": self.config.to_dict(),
                "runtime": {
                    "token_usage": self._token_usage,
                    "locked_tools": list(self._locked_tools),
                    "consecutive_errors": self._consecutive_errors,
                    "context_overflows": self._context_overflows,
                },
                "presets": list(PRESETS.keys()),
            }


_singleton: Optional[LoopSafety] = None
_singleton_lock = threading.Lock()


def default_safety() -> LoopSafety:
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = LoopSafety()
    return _singleton
