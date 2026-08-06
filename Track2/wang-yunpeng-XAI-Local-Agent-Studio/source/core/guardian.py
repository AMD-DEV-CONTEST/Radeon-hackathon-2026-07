"""P0 安全审批子代理 `xai-grok-guardian`（Codex Guardian + Claude 七层思路的落地）。

核心：危险操作前结构化风险分级闸门。
- P0（致命）：删除/覆盖重要文件、强制 push、凭证读写、rm -rf 类 —— 必须显式二次确认，
  自动模式默认拒绝，除非带 override。
- P1（高危）：网络请求、执行未审计命令、安装包 —— 记录并提示，可自动放行但留痕。
- P2（常规）：读文件、常规计算 —— 自动通过。

解决审计冲突 C1（与 reason/meta 的环路）：guardian 是 control_loop 中的一个
单向节点（被调用、返回决策），不反向调用 reason/meta，避免成环。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional


class RiskLevel(IntEnum):
    P2 = 2  # 常规
    P1 = 1  # 高危
    P0 = 0  # 致命


@dataclass
class Action:
    kind: str            # 'delete_file' | 'write_file' | 'run_command' | 'network' | 'read_file' | 'push' | 'secret'
    target: str = ""     # 文件路径 / 命令 / URL
    scope: str = "local" # local | repo | system | remote


@dataclass
class ApprovalResult:
    level: RiskLevel
    allowed: bool
    reason: str
    require_explicit: bool  # 是否需要人工显式确认


# 风险规则表：kind -> (level, 说明)。可外置为配置，此处以代码常量固化（模型无关启发式）。
RISK_RULES: dict[str, tuple[RiskLevel, str]] = {
    "delete_file": (RiskLevel.P0, "删除文件可能不可逆"),
    "overwrite_file": (RiskLevel.P0, "覆盖文件会丢失原内容"),
    "force_push": (RiskLevel.P0, "强制推送会改写远端历史"),
    "secret_write": (RiskLevel.P0, "写入凭证/密钥有泄露风险"),
    "rm_rf": (RiskLevel.P0, "递归删除系统目录极度危险"),
    "run_command": (RiskLevel.P1, "执行命令可能改变系统状态"),
    "network": (RiskLevel.P1, "网络请求可能外发数据"),
    "install_pkg": (RiskLevel.P1, "安装包引入第三方代码"),
    "read_file": (RiskLevel.P2, "只读操作低风险"),
    "compute": (RiskLevel.P2, "纯计算低风险"),
}


def classify(action: Action) -> ApprovalResult:
    """对动作做风险分级。"""
    if action.kind == "rm_rf" or "rm -rf" in action.target:
        level, reason = RISK_RULES["rm_rf"]
    else:
        level, reason = RISK_RULES.get(action.kind, (RiskLevel.P2, "未命中规则，按常规处理"))
    require_explicit = level == RiskLevel.P0
    return ApprovalResult(level=level, allowed=False, reason=reason, require_explicit=require_explicit)


def approve(action: Action, auto_mode: bool = False, override: bool = False,
            human_ok: bool = False) -> ApprovalResult:
    """审批闸门。

    - auto_mode=True 且无 override：P0 默认拒绝（安全优先），P1 记录放行，P2 通过。
    - human_ok=True：人工已确认，P0 放行。
    - override=True：显式跳过（仅用于受控测试/用户授权场景）。
    """
    res = classify(action)
    if res.level == RiskLevel.P2:
        res.allowed = True
        res.reason = "P2 常规操作自动通过"
        return res
    if res.level == RiskLevel.P1:
        # 高危：自动模式记录放行，非自动模式需提示但可在无 override 时通过
        res.allowed = True
        res.reason = "P1 高危操作：已记录并放行" + ("" if not auto_mode else "（自动模式留痕）")
        return res
    # P0 致命
    if override or human_ok:
        res.allowed = True
        res.reason = "P0 致命操作：经显式授权放行"
    else:
        res.allowed = False
        res.reason = "P0 致命操作：被拦截（需人工显式确认或 override）"
    return res


# ---------------------------------------------------------------------------
# 扩展：OpenClaw 风格 before_tool_call Hook + AgentTeams 风格治理 + 审批队列
# ---------------------------------------------------------------------------

@dataclass
class GovernancePolicy:
    """治理策略（谁能用哪个 LLM / MCP / 工具 = 策略而非约定）。

    对应 AgentTeams「可治理——谁能@谁、谁能调哪个 LLM、谁能用哪个 MCP」思想。
    """

    allowed_llms: set[str] = field(default_factory=set)      # 空 = 不限制
    allowed_mcp: set[str] = field(default_factory=set)
    allowed_tools: set[str] = field(default_factory=set)
    agent_acl: dict[str, set[str]] = field(default_factory=dict)  # agent -> 可调用 agent


@dataclass
class ApprovalTicket:
    ticket_id: str
    action: Action
    created_by: str = "system"


class ApprovalQueue:
    """人工审批队列（画布中 Human 节点的后端）。P0 动作入队等待人工确认。"""

    def __init__(self):
        self._q: dict[str, ApprovalTicket] = {}
        self._seq = 0

    def request(self, action: Action, created_by: str = "system") -> str:
        self._seq += 1
        tid = f"AP-{self._seq:04d}"
        self._q[tid] = ApprovalTicket(tid, action, created_by)
        return tid

    def resolve(self, ticket_id: str, human_ok: bool) -> ApprovalResult:
        t = self._q.pop(ticket_id, None)
        if t is None:
            raise KeyError(f"未知工单 {ticket_id}")
        return approve(t.action, human_ok=human_ok)

    def pending(self) -> list[str]:
        return list(self._q.keys())


def before_tool_call(action: Action, policy: GovernancePolicy | None = None,
                     queue: ApprovalQueue | None = None,
                     auto_mode: bool = False) -> ApprovalResult:
    """OpenClaw 风格 Hook：所有工具调用前的统一闸门。

    1) 治理检查：动作类型 / 工具是否在策略允许集合（若策略限定）。
    2) 风险分级：复用 classify/approve。
    3) P0 + 非自动模式：入审批队列并拦截（Human 节点）；否则按策略放行。
    """
    # 治理：工具白名单
    if policy is not None and policy.allowed_tools and action.kind not in policy.allowed_tools:
        return ApprovalResult(level=RiskLevel.P0, allowed=False,
                              reason=f"治理策略禁止工具 {action.kind}", require_explicit=True)
    res = classify(action)
    if res.level == RiskLevel.P0 and not auto_mode:
        if queue is not None:
            tid = queue.request(action)
            res.reason = f"P0 已入审批队列 {tid}，等待人工确认"
        res.allowed = False
        res.require_explicit = True
        return res
    return approve(action, auto_mode=auto_mode)


# ---------------------------------------------------------------------------
# 扩展：权限分级管控（痛点3：高危删除 / 系统修改指令二次确认拦截，适配企业合规）
# ---------------------------------------------------------------------------

class PermissionTier(IntEnum):
    VIEWER = 0    # 仅查看
    OPERATOR = 1  # 可执行常规操作
    ADMIN = 2     # 可审批高危 / 系统级操作


@dataclass
class PermissionPolicy:
    """企业合规权限分级：动作 kind -> 所需最低权限层级。"""
    required_tier: dict[str, PermissionTier] = field(default_factory=lambda: {
        "delete_file": PermissionTier.ADMIN,
        "rm_rf": PermissionTier.ADMIN,
        "force_push": PermissionTier.ADMIN,
        "overwrite_file": PermissionTier.ADMIN,
        "secret_write": PermissionTier.ADMIN,
        "run_command": PermissionTier.OPERATOR,
        "network": PermissionTier.OPERATOR,
        "install_pkg": PermissionTier.OPERATOR,
        "read_file": PermissionTier.VIEWER,
        "compute": PermissionTier.VIEWER,
    })


# 高危删除 / 系统修改：必须二次确认（痛点3 核心）
SECONDARY_CONFIRM_KINDS = {"delete_file", "rm_rf", "force_push", "overwrite_file", "secret_write"}


def needs_secondary_confirmation(action: Action) -> bool:
    """高危删除或 system 作用域的修改，必须二次确认。"""
    if action.kind in SECONDARY_CONFIRM_KINDS:
        return True
    if action.scope == "system" and action.kind in {"run_command", "install_pkg"}:
        return True
    return False


def guard(action: Action, permission: PermissionPolicy | None = None,
          tier: PermissionTier = PermissionTier.ADMIN,
          auto_mode: bool = False, human_ok: bool = False,
          override: bool = False, queue: ApprovalQueue | None = None) -> ApprovalResult:
    """统一权限闸门（痛点3）：分级 + 风险 + 二次确认。

    顺序：权限层级不足 -> 拦截；高危/系统修改需二次确认（入队或 human_ok）；
    否则走 risk approve。
    """
    if permission is not None:
        need = permission.required_tier.get(action.kind, PermissionTier.VIEWER)
        if tier < need and not override:
            return ApprovalResult(level=RiskLevel.P0, allowed=False,
                                  reason=f"权限不足：{action.kind} 需 {need.name}，当前 {tier.name}",
                                  require_explicit=True)
    if needs_secondary_confirmation(action) and not (human_ok or override):
        if queue is not None:
            tid = queue.request(action)
            return ApprovalResult(level=RiskLevel.P0, allowed=False,
                                  reason=f"高危操作已入审批队列 {tid}，需二次确认",
                                  require_explicit=True)
        return ApprovalResult(level=RiskLevel.P0, allowed=False,
                              reason="高危删除/系统修改指令需二次确认拦截",
                              require_explicit=True)
    return approve(action, auto_mode=auto_mode, override=override, human_ok=human_ok)
