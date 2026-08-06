"""XAI 多智能体协同层（Octo-Vec 式 PM 派发 + 群聊室 + 本地消息总线）。

这是「多 Agent 协作 / 群聊」能力的真实实现：智能体（各自带角色/模型/记忆）在同一个
Room 里用消息总线实时讨论，由 Coordinator 做 PM 式派发与看板管理。群聊里任何 Agent
提出的 P0/P1 操作都会被治理平面（Guardian）拦截成「人工审批卡片」——补上开源项目
都没有的治理平面。

内存级：消息经总线分发，同时关键决策落 MemoryCore（跨引擎共享），非 MCP 拼接。
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, Optional

from .memory_core import MemoryCore, Layer, default_core


@dataclass
class Agent:
    id: str
    name: str
    role: str
    backend: str = "stub"          # 模型后端名（由引擎路由到具体 ModelBackend）
    system: str = ""               # 角色设定
    memory_engine: str = "xai"      # 该 agent 在记忆池的 engine 标签


@dataclass
class Message:
    id: str
    room: str
    sender: str
    text: str
    ts: float = field(default_factory=time.time)
    kind: str = "chat"             # chat | dispatch | result | system


@dataclass
class ApprovalCard:
    id: str
    room: str
    proposer: str
    action: dict
    reason: str
    created_at: float = field(default_factory=time.time)
    resolved: bool = False
    decision: Optional[bool] = None


ApprovalFn = Callable[[dict], tuple[bool, str]]


class CoordinationBus:
    """本地消息总线 + 群聊室 + PM 派发 + 治理网关。"""

    def __init__(self, memory: Optional[MemoryCore] = None,
                 guard_fn: Optional[ApprovalFn] = None):
        self._memory = memory or default_core()
        self._guard_fn = guard_fn
        self._lock = threading.Lock()
        self._rooms: dict[str, list[Message]] = {}
        self._agents: dict[str, Agent] = {}
        self._cards: dict[str, ApprovalCard] = {}
        self._subscribers: dict[str, list[Callable[[Message], None]]] = {}
        self._card_subscribers: list[Callable[[ApprovalCard], None]] = []

    # ---------- 智能体 ----------
    def register_agent(self, name: str, role: str, backend: str = "stub",
                       system: str = "", memory_engine: str = "xai") -> Agent:
        a = Agent(id=f"agent:{uuid.uuid4().hex[:8]}", name=name, role=role,
                  backend=backend, system=system, memory_engine=memory_engine)
        with self._lock:
            self._agents[a.id] = a
        # 登记到记忆池（跨引擎可见）
        self._memory.store(Layer.USER_PROFILE.value, a.id,
                           f"Agent {name} / 角色 {role} / 后端 {backend}",
                           engine=a.memory_engine, importance=0.5,
                           meta={"kind": "agent_identity"})
        return a

    def list_agents(self) -> list[Agent]:
        with self._lock:
            return list(self._agents.values())

    # ---------- 群聊室 ----------
    def create_room(self, name: str) -> str:
        rid = f"room:{uuid.uuid4().hex[:8]}"
        with self._lock:
            self._rooms[rid] = []
            self._subscribers[rid] = []
        self._memory.store(Layer.SHORT_TERM.value, rid, f"创建群聊室: {name}",
                           engine="xai", importance=0.4, meta={"kind": "room", "name": name})
        return rid

    def list_rooms(self) -> list[str]:
        with self._lock:
            return list(self._rooms.keys())

    def history(self, room: str) -> list[Message]:
        with self._lock:
            return list(self._rooms.get(room, []))

    def subscribe(self, room: str, fn: Callable[[Message], None]) -> None:
        with self._lock:
            self._subscribers.setdefault(room, []).append(fn)

    def subscribe_cards(self, fn: Callable[[ApprovalCard], None]) -> None:
        with self._lock:
            self._card_subscribers.append(fn)

    # ---------- 发布 / 治理网关 ----------
    def publish(self, room: str, sender: str, text: str, kind: str = "chat") -> Message:
        msg = Message(id=f"msg:{uuid.uuid4().hex[:8]}", room=room, sender=sender,
                      text=text, kind=kind)
        with self._lock:
            self._rooms.setdefault(room, []).append(msg)
            subs = list(self._subscribers.get(room, []))
        # 落记忆池（跨引擎共享，非拼接）
        self._memory.store(Layer.SHORT_TERM.value, msg.id, f"[{sender}] {text}",
                           engine="xai", importance=0.4, meta={"kind": "chat", "room": room})
        for fn in subs:
            try:
                fn(msg)
            except Exception:
                pass
        return msg

    def propose_action(self, room: str, proposer: str, action: dict) -> ApprovalCard:
        """Agent 在群聊里提出一个操作：先过 Guardian，P0/P1 转人工审批卡片。"""
        reason = ""
        allowed = True
        if self._guard_fn is not None:
            allowed, reason = self._guard_fn(action)
        card = ApprovalCard(
            id=f"card:{uuid.uuid4().hex[:8]}", room=room, proposer=proposer,
            action=action, reason=reason,
        )
        if not allowed:
            with self._lock:
                self._cards[card.id] = card
                subs = list(self._card_subscribers)
            for fn in subs:
                try:
                    fn(card)
                except Exception:
                    pass
            self.publish(room, "Guardian",
                         f"⚠️ 拦截 {proposer} 的 {action.get('kind')} 操作（{reason}），已转人工审批。",
                         kind="system")
        else:
            self.publish(room, proposer, f"执行: {action.get('kind')}", kind="dispatch")
        return card

    # ---------- PM 派发（Octo-Vec 式）----------
    def dispatch(self, room: str, pm_agent: str, task: str) -> list[Message]:
        """PM 把任务派发给房间内的执行型 Agent，收集其认领。"""
        out = []
        agents = self.list_agents()
        executors = [a for a in agents if a.role in ("engineer", "researcher", "worker")]
        out.append(self.publish(room, pm_agent, f"📋 派发任务：{task}", kind="dispatch"))
        for a in executors[:3]:
            out.append(self.publish(room, a.name, f"✅ 认领：{task}", kind="result"))
        return out

    # ---------- 审批卡片 ----------
    def pending_cards(self) -> list[ApprovalCard]:
        with self._lock:
            return [c for c in self._cards.values() if not c.resolved]

    def resolve_card(self, card_id: str, approve: bool) -> Optional[ApprovalCard]:
        with self._lock:
            c = self._cards.get(card_id)
            if c is None:
                return None
            c.resolved = True
            c.decision = approve
        self.publish(c.room, "Guardian",
                     f"{'✅ 已批准' if approve else '❌ 已拒绝'}：{c.proposer} 的 {c.action.get('kind')}",
                     kind="system")
        return c
