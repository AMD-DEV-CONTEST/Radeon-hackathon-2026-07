"""Agent 协作室 —— 渐进融入 Buzz（block/buzz）的多 Agent 协同能力。

Buzz 的核心理念：人类与多个 Agent 同处一个「房间」，Agent 拥有自己的身份（名称 /
角色 / 模型），彼此能看到对方发言并基于上下文协作，而非各自孤立的 harness。

本模块在 XAI 本地私有、零依赖架构下原生实现该理念的「最小可用内核」：
- Agent 身份：每个参与者有 name / role / system_prompt / color（身份即 Buzz 的 agent identity）。
- 共享对话：一轮中多个 Agent 依次发言，每人都能看到前面所有人的发言（含其他 Agent），
  即「build on each other's work」。
- 画布即共享上下文：房间可绑定画布（Canvas-as-Context，见 core/canvas/context.py），
  Agent 看得见用户正在编辑的流程图。
- 审计轨迹：每轮发言落 transcript（可持久化），天然形成「谁在何时说了什么」的可追溯记录
  （对齐 Buzz 的 signed audit log 精神，本地版以 JSON 落盘实现）。

注意：本实现不搬运 Buzz 的 Nostr/Relay/Rust 代码，只吸收其「多 Agent 同室协作」的
交互范式并适配 XAI 既有架构。ACP/MCP 桥接等协议层能力不在本模块范围。
"""

from __future__ import annotations

import os
import json
import time
import uuid
import threading
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

# 画布上下文（B5）：把房间绑定画布作为共享上下文注入各 Agent
try:
    from .canvas.context import build_canvas_context
except ImportError:  # 包内相对导入兜底
    from core.canvas.context import build_canvas_context  # type: ignore

_STORE_PATH = os.path.expanduser("~/.xai/agent_rooms.json")
_LOCK = threading.RLock()


@dataclass
class AgentDef:
    id: str
    name: str
    role: str
    system_prompt: str = ""
    color: str = "#8b5cf6"
    model: str = ""  # 可选：指定模型；留空则用当前激活模型


@dataclass
class AgentRoom:
    id: str
    name: str
    agents: List[AgentDef] = field(default_factory=list)
    transcript: List[Dict[str, Any]] = field(default_factory=list)
    canvas_id: str = ""
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "AgentRoom":
        agents = [AgentDef(**a) for a in d.get("agents", [])]
        return cls(
            id=d["id"], name=d["name"], agents=agents,
            transcript=d.get("transcript", []),
            canvas_id=d.get("canvas_id", ""),
            created_at=d.get("created_at", time.time()),
        )


class AgentRoomManager:
    """Agent 协作室管理器：内存缓存 + JSON 文件持久化（~/.xai/agent_rooms.json）。"""

    def __init__(self, store_path: str = _STORE_PATH):
        self.store_path = store_path
        self._rooms: Dict[str, AgentRoom] = {}
        self._load()

    def _load(self) -> None:
        try:
            with open(self.store_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for rd in data.get("rooms", []):
                self._rooms[rd["id"]] = AgentRoom.from_dict(rd)
        except FileNotFoundError:
            pass
        except Exception:
            pass

    def _persist(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.store_path), exist_ok=True)
            with open(self.store_path, "w", encoding="utf-8") as f:
                json.dump({"rooms": [r.to_dict() for r in self._rooms.values()]},
                          f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def list_rooms(self) -> List[AgentRoom]:
        return list(self._rooms.values())

    def get_room(self, rid: str) -> Optional[AgentRoom]:
        return self._rooms.get(rid)

    def create_room(self, name: str, agents: List[Dict[str, Any]], canvas_id: str = "") -> AgentRoom:
        rid = "room_" + uuid.uuid4().hex[:10]
        agent_objs = [
            AgentDef(
                id=a.get("id") or ("ag_" + uuid.uuid4().hex[:8]),
                name=a.get("name", "未命名 Agent"),
                role=a.get("role", "成员"),
                system_prompt=a.get("system_prompt", ""),
                color=a.get("color", "#8b5cf6"),
                model=a.get("model", ""),
            )
            for a in (agents or [])
        ]
        room = AgentRoom(id=rid, name=name, agents=agent_objs, canvas_id=canvas_id)
        with _LOCK:
            self._rooms[rid] = room
            self._persist()
        return room

    def delete_room(self, rid: str) -> bool:
        with _LOCK:
            if rid in self._rooms:
                del self._rooms[rid]
                self._persist()
                return True
        return False

    def clear_transcript(self, rid: str) -> bool:
        with _LOCK:
            room = self._rooms.get(rid)
            if not room:
                return False
            room.transcript = []
            self._persist()
            return True


# 模块级单例
default_manager = AgentRoomManager()


def _now() -> float:
    return time.time()


def run_agent_room(engine: Any, room: AgentRoom, user_text: str, manager: Any = None) -> Any:
    """多 Agent 协同一轮：各 Agent 依次基于完整上下文发言，yield 事件。

    manager: 持有该 room 的 AgentRoomManager（用于持久化）。省略时回退到模块单例
    default_manager（适用于通过 REST 路由创建的房间）。

    yield 事件：
      {"type": "agent_start", "agent": name, "role": role, "agent_id": id}
      {"type": "token", "agent": name, "text": piece}        # 流式片段（可选）
      {"type": "agent_message", "agent": name, "role": role, "agent_id": id, "text": full}
      {"type": "done"}
    """
    transcript: List[Dict[str, Any]] = [dict(m) for m in room.transcript]
    # 用户消息入转录
    transcript.append({"speaker": "user", "role": "user", "text": user_text, "ts": _now()})

    # 仅在房间显式绑定画布时注入画布上下文（不做「按房间 id 猜画布」的隐式魔法）
    canvas_ctx = build_canvas_context(room.canvas_id) if room.canvas_id else ""

    for agent in room.agents:
        # 该 Agent 的系统提示词：身份 + 角色 + 自定义人设 + 协作规则 + 画布上下文
        system = (
            f"你是「{agent.name}」，在协作房间「{room.name}」中担任：{agent.role}。\n"
            f"{agent.system_prompt}\n\n"
            "协作规则：你们多位 Agent 与用户同处一个房间，彼此能看到对方的发言。"
            "请基于上方完整上下文（含其他 Agent 的发言）给出你作为该角色的专业回应，"
            "可引用、补充或纠正他人观点，避免简单重复他人已说的结论。"
        )
        if canvas_ctx:
            system += "\n\n" + canvas_ctx

        messages: List[Dict[str, str]] = [{"role": "system", "content": system}]
        # 历史：前面所有 Agent 的发言作为 assistant 轮次
        for m in transcript[1:]:
            messages.append({"role": "assistant",
                             "content": f"[{m.get('speaker')}/{m.get('role')}] {m.get('text')}"})
        # 当前用户问题（最后一条 user 轮，驱动本轮生成）
        messages.append({"role": "user",
                         "content": f"[用户问题] {user_text}\n\n请作为「{agent.name}」（{agent.role}）给出你的专业观点。"})

        yield {"type": "agent_start", "agent": agent.name, "role": agent.role, "agent_id": agent.id}

        acc: List[str] = []
        try:
            for piece in engine._backend.stream_complete(user_text, messages=messages, max_tokens=900):
                if piece:
                    acc.append(piece)
                    yield {"type": "token", "agent": agent.name, "text": piece}
            if hasattr(engine, "record_backend_usage"):
                try:
                    engine.record_backend_usage(source="agent_room")
                except Exception:
                    pass
        except Exception as e:  # 单 Agent 失败不影响其他 Agent
            acc.append(f"[Agent {agent.name} 推理异常: {e}]")

        text = "".join(acc).strip()
        msg = {"speaker": agent.name, "role": agent.role, "agent_id": agent.id,
               "text": text, "ts": _now()}
        transcript.append(msg)
        yield {"type": "agent_message", "agent": agent.name, "role": agent.role,
               "agent_id": agent.id, "text": text}

    room.transcript = transcript
    mgr = manager or default_manager
    with _LOCK:
        mgr._persist()
    yield {"type": "done"}
