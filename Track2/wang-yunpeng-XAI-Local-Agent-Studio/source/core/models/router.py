"""XAI 模型路由 `xai-grok-router`（吸收 superagent-base 的 Model Router）。

节点级多模型路由：按 能力 / 成本 / 延迟 三维约束筛选，打分选最优，并支持 fallback。
模型无关：注册任意 ModelBackend 的"画像"即可，底座仍是 Grok。

这是"多模型路由=节点级"的工程落点（用户拍板项之一）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ModelProfile:
    name: str
    provider: str
    capability: float = 0.7   # 推理能力自评 [0,1]
    cost_per_1k: float = 0.01  # 每 1k token 成本（相对值）
    latency_ms: float = 800.0  # 预估延迟
    tags: list[str] = field(default_factory=list)


class ModelRouter:
    """能力/成本/延迟 三维路由 + fallback。"""

    def __init__(self):
        self.models: dict[str, ModelProfile] = {}
        self._history: list[tuple[str, bool]] = []  # (name, success)

    def register(self, p: ModelProfile) -> None:
        self.models[p.name] = p

    def _score(self, p: ModelProfile, req_cap: float, max_cost: Optional[float],
               max_lat: Optional[float], prefer_tags: list[str]) -> Optional[float]:
        # 硬约束：能力/成本/延迟 不满足则淘汰
        if p.capability < req_cap:
            return None
        if max_cost is not None and p.cost_per_1k > max_cost:
            return None
        if max_lat is not None and p.latency_ms > max_lat:
            return None
        if prefer_tags and not any(t in p.tags for t in prefer_tags):
            return None
        # 软打分：能力↑好，成本↓好，延迟↓好（归一化加权）
        cap = p.capability
        cost = 1.0 / (1.0 + p.cost_per_1k)
        lat = 1.0 / (1.0 + p.latency_ms / 1000.0)
        return 0.5 * cap + 0.25 * cost + 0.25 * lat

    def route(self, require_capability: float = 0.0, max_cost: Optional[float] = None,
              max_latency: Optional[float] = None, prefer_tags: Optional[list[str]] = None) -> Optional[str]:
        """返回最优模型名；无满足约束者返回 None。"""
        if not self.models:
            return None
        prefer_tags = prefer_tags or []
        scored = [(n, self._score(p, require_capability, max_cost, max_latency, prefer_tags))
                  for n, p in self.models.items()]
        scored = [(n, s) for n, s in scored if s is not None]
        if not scored:
            return None
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[0][0]

    def fallback(self, primary: str, error: Exception) -> Optional[str]:
        """主模型失败时的 fallback：记录失败，选剩余中能力最高者。"""
        self._history.append((primary, False))
        if primary in self.models:
            del self.models[primary]
        if not self.models:
            return None
        best = max(self.models.values(), key=lambda p: p.capability)
        return best.name

    def record_success(self, name: str) -> None:
        self._history.append((name, True))
