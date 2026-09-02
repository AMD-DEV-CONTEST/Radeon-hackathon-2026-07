"""降级链（Degradation Chain）—— 声明式容错编排。

将「Agent 失败 → 降级 → 报告」从硬编码提升为可配置的降级链。
每条链由多个 Step 组成，按序尝试，前一步失败自动进入下一步。

配置格式见 degradation_chain.yaml。

用法：
  from core.degradation_chain import DegradationChain, StepResult

  chain = DegradationChain()
  chain.load_from_yaml("degradation_chain.yaml")

  result = chain.execute("file-agent", {
      "dispatch": lambda ctx: dispatch_task(ctx),
      "shell": lambda ctx: shell_executor(ctx),
      "report": lambda ctx: notify_user(ctx),
  }, context={"task": "读取 report.pdf"})
"""

from __future__ import annotations

import os
import time
import threading
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------

class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    OK = "ok"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class StepDefinition:
    """降级链中一个步骤的声明。"""
    target: str            # 执行目标名称（对应 fn_map 中的 key）
    action: str = "direct" # "dispatch" / "direct" / "notify"
    retry: int = 1         # 最大重试次数
    timeout_s: float = 30  # 超时秒数
    fallback_reason: str = ""  # 进入此步的原因说明

    @classmethod
    def from_dict(cls, d: dict) -> "StepDefinition":
        return cls(
            target=d.get("target", "unknown"),
            action=d.get("action", "direct"),
            retry=d.get("retry", 1),
            timeout_s=d.get("timeout_s", 30),
            fallback_reason=d.get("fallback_reason", ""),
        )


@dataclass
class StepResult:
    """单步执行结果。"""
    step_index: int
    target: str
    action: str
    status: StepStatus = StepStatus.PENDING
    output: Any = None
    error: str = ""
    retries_used: int = 0
    elapsed_s: float = 0.0
    ts: float = field(default_factory=time.time)


@dataclass
class ChainResult:
    """降级链整体执行结果。"""
    agent_name: str
    success: bool = False
    final_step: int = -1      # 最终执行到的步骤序号（0-based），-1 表示未执行
    steps: List[StepResult] = field(default_factory=list)
    total_elapsed_s: float = 0.0

    @property
    def final_output(self) -> Any:
        for step in reversed(self.steps):
            if step.status == StepStatus.OK and step.output is not None:
                return step.output
        return None

    @property
    def last_error(self) -> str:
        for step in reversed(self.steps):
            if step.error:
                return step.error
        return ""


# ---------------------------------------------------------------------------
# 降级链定义
# ---------------------------------------------------------------------------

@dataclass
class _ChainConfig:
    """单条降级链的配置。"""
    name: str
    description: str = ""
    steps: List[StepDefinition] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 引擎
# ---------------------------------------------------------------------------

class DegradationChain:
    """降级链引擎。

    加载声明式配置，将 agent 名称映射到降级步骤序列。
    执行时按序尝试每一步，记录详细结果。
    """

    def __init__(self):
        self._chains: Dict[str, _ChainConfig] = {}
        self._lock = threading.Lock()
        self._history: Dict[str, List[ChainResult]] = {}  # agent_name → 历史

    # ----- 配置加载 -----

    def load_from_yaml(self, path: str) -> "DegradationChain":
        """从 YAML 配置文件加载降级链定义。"""
        import yaml
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        self._parse_config(data)
        return self

    def load_from_dict(self, data: dict) -> "DegradationChain":
        """从字典加载降级链定义（用于编程式配置）。"""
        self._parse_config(data)
        return self

    def _parse_config(self, data: dict):
        with self._lock:
            chains_raw = data.get("chains", data)  # 兼容顶层有/无 chains key
            for agent_name, cfg in chains_raw.items():
                if not isinstance(cfg, dict):
                    continue
                steps_raw = cfg.get("steps", [])
                steps = [StepDefinition.from_dict(s) for s in steps_raw]
                self._chains[agent_name] = _ChainConfig(
                    name=agent_name,
                    description=cfg.get("description", ""),
                    steps=steps,
                )

    def add_chain(self, agent_name: str, steps: List[StepDefinition],
                  description: str = ""):
        """编程式添加一条降级链。"""
        with self._lock:
            self._chains[agent_name] = _ChainConfig(
                name=agent_name, description=description, steps=steps,
            )

    # ----- 查询 -----

    def has_chain(self, agent_name: str) -> bool:
        with self._lock:
            return agent_name in self._chains

    def get_chain(self, agent_name: str) -> Optional[_ChainConfig]:
        with self._lock:
            return self._chains.get(agent_name)

    def list_chains(self) -> List[str]:
        with self._lock:
            return list(self._chains.keys())

    def get_history(self, agent_name: str) -> List[ChainResult]:
        with self._lock:
            return self._history.get(agent_name, [])[:]

    # ----- 执行 -----

    def execute(self, agent_name: str,
                fn_map: Dict[str, Callable[[Dict[str, Any]], Any]],
                context: Optional[Dict[str, Any]] = None) -> ChainResult:
        """执行指定 agent 的降级链。

        Args:
            agent_name: 要执行的降级链名称
            fn_map:     target → 调用函数的映射。函数签名为 fn(context) → Any
            context:    透传给每一步函数的上下文字典（可包含 task / params 等）

        Returns:
            ChainResult，包含每一步的详细结果和最终输出
        """
        ctx = context or {}
        start_ts = time.time()

        with self._lock:
            chain = self._chains.get(agent_name)

        result = ChainResult(agent_name=agent_name)

        if not chain or not chain.steps:
            result.total_elapsed_s = time.time() - start_ts
            result.steps.append(StepResult(
                step_index=0, target="none", action="fail",
                status=StepStatus.FAILED,
                error=f"未找到 agent '{agent_name}' 的降级链定义",
            ))
            self._record(agent_name, result)
            return result

        for idx, step_def in enumerate(chain.steps):
            step_result = StepResult(
                step_index=idx, target=step_def.target,
                action=step_def.action,
            )

            fn = fn_map.get(step_def.target)
            if fn is None:
                step_result.status = StepStatus.SKIPPED
                step_result.error = f"未注册执行函数: {step_def.target}"
                result.steps.append(step_result)
                continue

            # 重试循环
            step_ok = False
            for attempt in range(step_def.retry):
                step_ts = time.time()
                try:
                    step_result.status = StepStatus.RUNNING
                    # 注入步骤元信息到 context
                    ctx["_step"] = {
                        "index": idx, "target": step_def.target,
                        "action": step_def.action, "attempt": attempt + 1,
                        "fallback_reason": step_def.fallback_reason,
                    }
                    step_result.output = fn(ctx)
                    step_result.status = StepStatus.OK
                    step_result.retries_used = attempt
                    step_result.elapsed_s = time.time() - step_ts
                    step_ok = True
                    break
                except Exception as e:
                    step_result.error = f"{type(e).__name__}: {e}"
                    if attempt + 1 < step_def.retry:
                        continue  # 重试
                    step_result.status = StepStatus.FAILED
                    step_result.retries_used = attempt + 1
                    step_result.elapsed_s = time.time() - step_ts

            result.steps.append(step_result)
            if step_ok:
                result.success = True
                result.final_step = idx
                break
            else:
                result.final_step = idx

        result.total_elapsed_s = time.time() - start_ts
        self._record(agent_name, result)
        return result

    def _record(self, agent_name: str, result: ChainResult):
        """记录执行历史。"""
        with self._lock:
            if agent_name not in self._history:
                self._history[agent_name] = []
            self._history[agent_name].append(result)
            # 只保留最近 20 条
            if len(self._history[agent_name]) > 20:
                self._history[agent_name] = self._history[agent_name][-20:]

    # ----- 步骤状态查询 -----

    def step_status(self, agent_name: str) -> Dict[str, Any]:
        """查询某 agent 降级链的当前步骤状态。"""
        with self._lock:
            history = self._history.get(agent_name, [])
        if not history:
            return {"agent": agent_name, "status": "no_history"}
        last = history[-1]
        steps_summary = []
        for s in last.steps:
            steps_summary.append({
                "index": s.step_index,
                "target": s.target,
                "action": s.action,
                "status": s.status.value,
                "elapsed_s": s.elapsed_s,
                "retries": s.retries_used,
            })
        return {
            "agent": agent_name,
            "success": last.success,
            "final_step": last.final_step,
            "total_elapsed_s": last.total_elapsed_s,
            "steps": steps_summary,
        }


# ---------------------------------------------------------------------------
# 全局单例
# ---------------------------------------------------------------------------

_global_chain: Optional[DegradationChain] = None
_global_chain_lock = threading.Lock()


def global_chain(config_path: Optional[str] = None) -> DegradationChain:
    """获取全局降级链单例。首次调用时可传入配置文件路径。"""
    global _global_chain
    if _global_chain is None:
        with _global_chain_lock:
            if _global_chain is None:
                _global_chain = DegradationChain()
                if config_path:
                    _global_chain.load_from_yaml(config_path)
    return _global_chain
