"""软件安全闸 (M4.4).

把"模型预测关节角"拍进真机 / 广播总线前, 必须走这层:

1. per-joint abs 限位 (clamp 到 LIMITS_RAD 内)
2. per-tick 变化速率限制 (clamp 到 |Δ| <= MAX_DELTA_RAD)
3. NaN / Inf 拦截
4. 外部 emergency_stop 标记

不实现硬件急停, 只做纯 python 的软件层. 真 E-Stop 应由电机控制器 / 硬件按钮负责 (M5).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping


# SO101 大致范围 (rad). 保守一点, 留出安全余量.
# 若后续接入不同臂, 可从 robot registry 里读 URDF 的 <limit> 元素.
LIMITS_RAD: dict[str, tuple[float, float]] = {
    "1": (-3.14, 3.14),  # shoulder_pan
    "2": (-1.60, 1.60),  # shoulder_lift
    "3": (-1.60, 1.60),  # elbow_flex
    "4": (-1.60, 1.60),  # wrist_flex
    "5": (-3.14, 3.14),  # wrist_roll
    "6": (-1.00, 1.00),  # gripper
}

# 单 tick 内最大变化 (rad). 30Hz 下 0.18rad ≈ 5.4rad/s.
# M5 真机实测: 0.05 太紧 (dropped 持续涨), 0.10 仍偶发, 0.15 稳定.
# 服端上限 0.18 给客户端 0.15 留 20% 余量.
MAX_DELTA_RAD: float = 0.18


# Normalized-units variant for lerobot-style action sources (ACT / Pi0 /
# vision_mlp). Those policies emit values in:
#   - rotary joints:   [-100.0, +100.0]   (RANGE_M100_100)
#   - gripper (id 6):  [  0.0, +100.0]    (RANGE_0_100)
# Feeding them through LIMITS_RAD silently clamps to ±1.6 / ±3.14 on every
# frame, which looks on the UI exactly like "the arm isn't moving".
LIMITS_NORMALIZED: dict[str, tuple[float, float]] = {
    "1": (-100.0, 100.0),
    "2": (-100.0, 100.0),
    "3": (-100.0, 100.0),
    "4": (-100.0, 100.0),
    "5": (-100.0, 100.0),
    "6": (   0.0, 100.0),
}

# ~12 u/tick @ 15 Hz → 180 u/s. On a 180° servo that's ~1.8 rad/s, in the
# same ballpark as MAX_DELTA_RAD @ 30 Hz but at our slower inference rate.
MAX_DELTA_NORMALIZED: float = 12.0


@dataclass
class GateResult:
    """safety gate 输出.

    safe_joints: 最终可安全下发的关节 dict (str key "1".."6" -> float)
    clamped: 触发了哪些限位/速率保护 (诊断用)
    fatal: 是否因 NaN/Inf 或强制停机而放弃本帧
    """

    safe_joints: dict[str, float]
    clamped: list[str]
    fatal: bool = False
    reason: str | None = None


class SafetyGate:
    """单臂一个 gate 实例. 记住上一帧, 做速率限制."""

    def __init__(
        self,
        limits: Mapping[str, tuple[float, float]] | None = None,
        max_delta: float = MAX_DELTA_RAD,
    ) -> None:
        self.limits = dict(limits) if limits else dict(LIMITS_RAD)
        self.max_delta = float(max_delta)
        self._prev: dict[str, float] | None = None
        self._stopped = False

    def reset(self) -> None:
        self._prev = None
        self._stopped = False

    def emergency_stop(self, reason: str = "external_estop") -> None:
        self._stopped = True
        self._reason = reason

    def apply(self, joints: Mapping[str, float]) -> GateResult:
        """对一帧关节角度做校验 + clamp, 返回安全版本."""
        if self._stopped:
            # 紧停后所有帧都复用最后一次安全值, 关节不再前进
            frozen = self._prev or {k: 0.0 for k in self.limits}
            return GateResult(safe_joints=dict(frozen), clamped=list(frozen), fatal=True, reason="emergency_stop")

        safe: dict[str, float] = {}
        clamped: list[str] = []

        for k in ("1", "2", "3", "4", "5", "6"):
            v_raw = joints.get(k)
            if v_raw is None:
                # 缺字段, 用上次值保持
                v = (self._prev or {}).get(k, 0.0)
                clamped.append(f"{k}:missing")
                safe[k] = v
                continue

            try:
                v = float(v_raw)
            except (TypeError, ValueError):
                return GateResult(
                    safe_joints=self._prev or {k2: 0.0 for k2 in self.limits},
                    clamped=[f"{k}:nan_type"],
                    fatal=True,
                    reason=f"non-numeric value for joint {k}: {v_raw!r}",
                )

            if not math.isfinite(v):
                return GateResult(
                    safe_joints=self._prev or {k2: 0.0 for k2 in self.limits},
                    clamped=[f"{k}:nan"],
                    fatal=True,
                    reason=f"non-finite value for joint {k}",
                )

            # 1) 限位
            lo, hi = self.limits.get(k, (-math.pi, math.pi))
            if v < lo:
                v = lo
                clamped.append(f"{k}:lo")
            elif v > hi:
                v = hi
                clamped.append(f"{k}:hi")

            # 2) 速率
            if self._prev is not None and k in self._prev:
                dv = v - self._prev[k]
                if dv > self.max_delta:
                    v = self._prev[k] + self.max_delta
                    clamped.append(f"{k}:rate+")
                elif dv < -self.max_delta:
                    v = self._prev[k] - self.max_delta
                    clamped.append(f"{k}:rate-")

            safe[k] = v

        self._prev = dict(safe)
        return GateResult(safe_joints=safe, clamped=clamped, fatal=False)


class NormalizedSafetyGate(SafetyGate):
    """Same contract as SafetyGate but with defaults for lerobot-normalized units.

    Use this wherever the action source (ACT / Pi0 / vision_mlp) emits
    joint values in ±100 (or 0..100 for gripper). Behaviour is otherwise
    identical — clamp, rate-limit, NaN trap, external estop hook.
    """

    def __init__(
        self,
        limits: Mapping[str, tuple[float, float]] | None = None,
        max_delta: float = MAX_DELTA_NORMALIZED,
    ) -> None:
        super().__init__(
            limits=limits if limits is not None else LIMITS_NORMALIZED,
            max_delta=max_delta,
        )
