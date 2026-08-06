from __future__ import annotations

import logging
import asyncio
import httpx
import json
import os
import urllib.error
import urllib.request
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect, status

try:
    from . import db as gateway_db
except ImportError:
    gateway_db = None
from . import auth
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

# iron_law_rounds_patched
try:
    from iron_law.context import get_rounds_from_db as _get_rounds_from_db
    from iron_law.context import assemble_leader_snapshot as _assemble_leader_snapshot
    _iron_law_available = True
except ImportError:
    _iron_law_available = False
    def _get_rounds_from_db(session_id, limit=5): return []
    def _assemble_leader_snapshot(session_id, project="omima"): return {}


HEARTBEAT_INTERVAL_SECONDS = int(os.environ.get("HEARTBEAT_INTERVAL_SSE", "30"))
MAX_EVENT_QUEUE_SIZE = int(os.environ.get("MAX_EVENT_QUEUE_SIZE", "1000"))
EVENT_REPLAY_LIMIT = int(os.environ.get("EVENT_REPLAY_LIMIT", "200"))
PUBLIC_GATEWAY_WS_URL = os.environ.get("PUBLIC_GATEWAY_WS_URL", "ws://111.228.42.18:8001")
ORCHESTRATOR_URL = os.environ.get("ORCHESTRATOR_URL", "http://127.0.0.1:8000")


logger = logging.getLogger("streaming_gateway")
AgentOutputType = Literal[
    "init",
    "thinking",
    "tool_use",
    "tool_result",
    "text",
    "warning",
    "error",
    "phase",
    "block",
    "finish",
    "done",
    "heartbeat",
]


class AgentStreamEvent(BaseModel):
    session_id: str
    msg_id: str = Field(default_factory=lambda: str(uuid4()))
    agent_id: str = "unknown"
    type: AgentOutputType
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    seq: int = 0  # monotonic per-session sequence number, assigned by publish_event


class LauncherControlMessage(BaseModel):
    msg_id: str = Field(default_factory=lambda: str(uuid4()))
    action: Literal["spawn", "signal", "status"]
    session_id: str
    agent_type: str | None = None
    command: list[str] = Field(default_factory=list)
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    cwd: str | None = None
    timeout_seconds: int | None = None
    signal: str | None = None


class LauncherEvent(BaseModel):
    model_config = {"extra": "allow"}
    msg_id: str = Field(default_factory=lambda: str(uuid4()))
    type: Literal["spawned", "stdout", "stderr", "exit", "status", "error", "register"]
    session_id: str = ""
    pid: int | None = None
    data: str | None = None
    exit_code: int | None = None
    running: bool | None = None
    uptime_seconds: int | None = None
    message: str | None = None
    display_name: str | None = None
    agents: list[dict[str, Any]] = Field(default_factory=list)


class SessionCreateRequest(BaseModel):
    session_id: str | None = None
    agent_id: str = "manual"
    agent_name: str = "manual"
    agent_type: str = "generic"
    model: str | None = None
    tools: list[str] = Field(default_factory=list)


class SessionCreateResponse(BaseModel):
    session_id: str


class SessionInviteRequest(BaseModel):
    session_id: str | None = None
    goal: str = ""
    invite: dict[str, Any] = Field(default_factory=dict)
    cost_policy: dict[str, Any] | None = None
    stage: str | None = None
    stage_round: int = 1
    max_rounds: int = 1


class SessionInviteResponse(BaseModel):
    session_id: str
    invited: list[str] = Field(default_factory=list)
    skipped: list[dict[str, Any]] = Field(default_factory=list)


class SessionMessageRequest(BaseModel):
    type: str
    session_id: str | None = None
    agent_id: str = "canvas"
    payload: dict[str, Any] = Field(default_factory=dict)
    outcome: str | None = None
    summary: str | None = None
    message: str | None = None


class ParticipantCreateRequest(BaseModel):
    machine_id: str
    agent_template_id: str
    role: Literal["leader", "reviewer", "implementer", "ops", "observer"] = "observer"
    mode: Literal["pty"] = "pty"
    initial_context: dict[str, Any] = Field(default_factory=dict)


class ParticipantCreateResponse(BaseModel):
    participant_id: str
    terminal_id: str
    pty_ws_url: str
    status: str = "summoned"


class RoundCreateRequest(BaseModel):
    round: int
    leader_instruction: str = ""


class RoundUpdateRequest(BaseModel):
    decision: str = ""  # continue|rework|reassign|deploy|accept|dismiss
    leader_review: str = ""
    deployment_opinion: str = ""
    next_action: str = ""


class TaskAssignRequest(BaseModel):
    agent_id: str
    task: dict[str, Any] = Field(default_factory=dict)


class DormAgent(BaseModel):
    agentTemplateId: str | None = None
    agentName: str
    agentType: str
    status: Literal["standby", "busy", "offline", "error"] = "standby"
    capabilities: dict[str, Any] = Field(default_factory=dict)


class DormMachine(BaseModel):
    machineId: str
    displayName: str
    location: str = "other"
    status: Literal["online", "offline", "unknown", "error"] = "unknown"
    launcherStatus: Literal["connected", "disconnected", "starting"] = "disconnected"
    agents: list[DormAgent] = Field(default_factory=list)


app = FastAPI(
    title="UnionAgents Streaming Gateway",
    version="0.1.0",
    description="Phase 3 SSE fanout and Launcher WebSocket gateway.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.middleware("http")(auth.auth_middleware)


@app.on_event("startup")
async def _startup_db() -> None:
    if gateway_db:
        try:
            pool = await gateway_db._get_pool()
            if pool:
                logger.info("Postgres persistence enabled")
        except Exception:
            pass


session_subscribers: dict[str, set[asyncio.Queue[AgentStreamEvent]]] = defaultdict(set)
session_history: dict[str, deque[AgentStreamEvent]] = defaultdict(
    lambda: deque(maxlen=EVENT_REPLAY_LIMIT)
)
session_seq_counters: dict[str, int] = defaultdict(int)
launcher_connections: dict[str, WebSocket] = {}
machine_registry: dict[str, dict[str, Any]] = {}
agent_connections: dict[str, WebSocket] = {}
agent_profiles: dict[str, dict[str, Any]] = {}
agent_status: dict[str, str] = {}
session_agents: dict[str, set[str]] = defaultdict(set)
session_ws_connections: dict[str, set[WebSocket]] = defaultdict(set)
session_status: dict[str, str] = defaultdict(lambda: "active")
session_participants: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
terminal_sessions: dict[str, dict[str, Any]] = {}
pty_bridges: dict[str, asyncio.Queue] = {}
session_rounds: dict[str, list[dict[str, Any]]] = defaultdict(list)


STATIC_MACHINES: dict[str, dict[str, Any]] = {
    "local": {
        "machineId": "local",
        "displayName": "本地电脑",
        "location": "local",
        "status": "online",
        "launcherStatus": "disconnected",
        "agents": [
            {"agentTemplateId": "reasonix-local", "agentName": "Reasonix", "agentType": "reasonix", "status": "standby", "capabilities": {"agent": "reasonix"}},
            {"agentTemplateId": "codex-local", "agentName": "Codex", "agentType": "codex", "status": "standby", "capabilities": {"agent": "codex"}},
            {"agentTemplateId": "claude-local", "agentName": "Claude", "agentType": "claude", "status": "standby", "capabilities": {"agent": "claude"}},
            {"agentTemplateId": "opencode-local", "agentName": "OpenCode", "agentType": "opencode", "status": "standby", "capabilities": {"agent": "opencode"}},
        ],
    },
    "wuying-01": {
        "machineId": "wuying-01",
        "displayName": "无影-01",
        "location": "wuying",
        "status": "online",
        "launcherStatus": "disconnected",
        "agents": [
            {"agentTemplateId": "reasonix-wuying-01", "agentName": "Reasonix", "agentType": "reasonix", "status": "standby", "capabilities": {"agent": "reasonix"}},
            {"agentTemplateId": "codex-wuying-01", "agentName": "Codex", "agentType": "codex", "status": "standby", "capabilities": {"agent": "codex"}},
        ],
    },
    "wuying-02": {
        "machineId": "wuying-02",
        "displayName": "无影-02",
        "location": "wuying",
        "status": "offline",
        "launcherStatus": "disconnected",
        "agents": [],
    },
    "jd-ecs": {
        "machineId": "jd-ecs",
        "displayName": "JD-ECS",
        "location": "jd-ecs",
        "status": "online",
        "launcherStatus": "disconnected",
        "agents": [
            {"agentTemplateId": "he-jd-ecs", "agentName": "He", "agentType": "hermes", "status": "standby", "capabilities": {"agent": "hermes"}},
        ],
    },
    "aws-hk": {
        "machineId": "aws-hk",
        "displayName": "AWS-HK",
        "location": "aws-hk",
        "status": "online",
        "launcherStatus": "disconnected",
        "agents": [
            {"agentTemplateId": "reasonix-aws-hk", "agentName": "小弟", "agentType": "reasonix", "status": "standby", "capabilities": {"agent": "reasonix", "international": True}},
        ],
    },
    "thinkbook14": {
        "machineId": "thinkbook14",
        "displayName": "ThinkBook（老何日常用机）",
        "location": "local",
        "status": "online",
        "launcherStatus": "disconnected",
        "agents": [
            {"agentTemplateId": "tcc-thinkbook14", "agentName": "桃叉叉", "agentType": "claude_code", "status": "standby", "capabilities": {"agent": "claude"}},
            {"agentTemplateId": "codex-xiaokou-ua-server", "agentName": "小寇", "agentType": "codex", "status": "standby", "capabilities": {"agent": "codex"}},
            {"agentTemplateId": "老三", "agentName": "老三", "agentType": "reasonix", "status": "standby", "capabilities": {"agent": "reasonix"}},
        ],
    },
    "taipei-ecs": {
        "machineId": "taipei-ecs",
        "displayName": "台北 ECS",
        "location": "taipei",
        "status": "online",
        "launcherStatus": "disconnected",
        "agents": [
            {"agentTemplateId": "sandbox-guardian-taipei", "agentName": "沙箱守护者", "agentType": "sandbox_guardian", "status": "standby", "capabilities": {"agent": "sandbox_guardian", "git_review": True}},
        ],
    },
}

# wake_on_knock_patched
AGENT_SPAWN_TEMPLATES: dict[str, dict] = {
    # ── JD-ECS (Linux, 内网 127.0.0.1) ──────────────────────────────────────
    "he-jd-ecs": {
        "machine_id": "jd-ecs",
        "command": [
            "/root/UnionAgents/bin/ils", "ws",
            "--agent-id", "He",
            "--agent-name", "He",
            "--agent-type", "hermes",
            "--orchestrator-url", "http://127.0.0.1:8000",
            "--gateway", "ws://127.0.0.1:8001",
        ],
        "cwd": "/root/UnionAgents",
        "env": {},
    },
    # ── ThinkBook（Windows，连公网 JD-ECS）───────────────────────────────────
    "tcc-thinkbook14": {
        "machine_id": "thinkbook14",
        "command": [
            "node", "D:\\UnionAgents\\packages\\agent\\dist\\cli.js", "run",
            "--mode", "standby",
            "--agent-name", "tcc-thinkbook14",
            "--agent-type", "claude_code",
            "--orchestrator-url", "http://111.228.42.18:8000",
            "--gateway-url", "ws://111.228.42.18:8001",
            "--workspace-root", "D:\\UnionAgents",
            "--skill", "D:\\UnionAgents\\skills\\iron-law-standard\\SKILL.md",
            "--max-concurrency", "1",
        ],
        "cwd": "D:\\UnionAgents",
        "env": {},
    },
    "codex-xiaokou-ua-server": {
        "machine_id": "thinkbook14",
        "command": [
            "node", "D:\\UnionAgents\\packages\\agent\\dist\\cli.js", "run",
            "--mode", "standby",
            "--agent-name", "codex-xiaokou-ua-server",
            "--agent-type", "codex",
            "--orchestrator-url", "http://111.228.42.18:8000",
            "--gateway-url", "ws://111.228.42.18:8001",
            "--workspace-root", "D:\\UnionAgents",
            "--skill", "D:\\UnionAgents\\skills\\iron-law-standard\\SKILL.md",
            "--max-concurrency", "1",
        ],
        "cwd": "D:\\UnionAgents",
        "env": {},
    },
    "老三": {
        "machine_id": "thinkbook14",
        "command": [
            "node", "D:\\UnionAgents\\packages\\agent\\dist\\cli.js", "run",
            "--mode", "standby",
            "--agent-name", "老三",
            "--agent-type", "reasonix",
            "--orchestrator-url", "http://111.228.42.18:8000",
            "--gateway-url", "ws://111.228.42.18:8001",
            "--workspace-root", "D:\\UnionAgents",
            "--skill", "D:\\UnionAgents\\skills\\iron-law-standard\\SKILL.md",
            "--max-concurrency", "1",
        ],
        "cwd": "D:\\UnionAgents",
        "env": {},
    },
    # ── 台北 ECS（Ubuntu，连公网 JD-ECS）────────────────────────────────────
    "sandbox-guardian-taipei": {
        "machine_id": "taipei-ecs",
        "command": [
            "python3", "/home/ubuntu/sandbox_guardian.py",
        ],
        "cwd": "/home/ubuntu",
        "env": {},
    },
}


def _spawn_template_for(agent_id: str) -> dict | None:
    tmpl = AGENT_SPAWN_TEMPLATES.get(agent_id)
    if tmpl:
        return tmpl
    profile = agent_profiles.get(agent_id) or {}
    agent_name = str(profile.get("agent_name") or "")
    if agent_name:
        return AGENT_SPAWN_TEMPLATES.get(agent_name)
    return None


def _agent_to_machine(agent_id: str) -> str | None:
    tmpl = _spawn_template_for(agent_id)
    if tmpl:
        return tmpl["machine_id"]
    for mid, machine in STATIC_MACHINES.items():
        for a in machine.get("agents", []):
            agent_name = str(a.get("agentName") or "").lower()
            profile_name = str((agent_profiles.get(agent_id) or {}).get("agent_name") or "").lower()
            if agent_name and (agent_name in agent_id.lower() or agent_name == profile_name):
                return mid
    return None


def _can_wake_agent(agent_id: str) -> bool:
    machine_id = _agent_to_machine(agent_id)
    return bool(machine_id and launcher_connections.get(machine_id) and _spawn_template_for(agent_id))


async def _wake_and_invite(machine_id: str, agent_id: str, session_id: str, invite_payload: dict) -> None:
    tmpl = _spawn_template_for(agent_id)
    if not tmpl:
        return
    launcher_ws = launcher_connections.get(machine_id)
    if not launcher_ws:
        logger.warning("wake_on_knock: launcher offline machine=%s", machine_id)
        return
    import uuid as _uuid
    try:
        await launcher_ws.send_json({
            "action": "spawn",
            "session_id": "wake-" + _uuid.uuid4().hex[:8],
            "command": tmpl["command"],
            "env": tmpl.get("env", {}),
            "cwd": tmpl.get("cwd", "/root/UnionAgents"),
        })
        logger.info("wake_on_knock: spawn sent agent=%s", agent_id)
    except Exception as exc:
        logger.warning("wake_on_knock: spawn failed: %s", exc)
        return
    for _ in range(40):
        await asyncio.sleep(0.5)
        ws = agent_connections.get(agent_id)
        if ws:
            try:
                await ws.send_json(invite_payload)
                agent_status[agent_id] = "summoned"
                session_agents[session_id].add(agent_id)
                logger.info("wake_on_knock: agent %s invited", agent_id)
            except Exception as exc:
                logger.warning("wake_on_knock: invite failed: %s", exc)
            return
    logger.warning("wake_on_knock: timeout waiting for agent %s", agent_id)




def sse_frame(event: AgentStreamEvent) -> str:
    payload = event.model_dump(mode="json")
    return f"event: agent_output\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def publish_event(event: AgentStreamEvent) -> None:
    event.seq = session_seq_counters[event.session_id]
    session_seq_counters[event.session_id] += 1
    session_history[event.session_id].append(event)
    if gateway_db:
        asyncio.create_task(gateway_db.save_event(
            event.session_id, event.seq, event.msg_id, event.agent_id,
            event.type, event.payload, event.timestamp.isoformat(),
        ))
    subscribers = list(session_subscribers[event.session_id])
    for queue in subscribers:
        if queue.full():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        await queue.put(event)


def session_event_type(message_type: str) -> str:
    mapping = {
        "agent_message": "session.message",
        "blocker": "session.blocker",
        "context_snapshot": "session.context_snapshot",
        "session_done": "session.done",
        "session_invite": "session.invite",
        "session_join": "session.join",
        "session_leave": "session.leave",
        "task_assigned": "session.task_assigned",
        "task_complete": "session.task_complete",
        "task_progress": "session.task_progress",
    }
    if message_type.startswith("session."):
        return message_type
    return mapping.get(message_type, f"session.{message_type}")


def session_event_message(message_type: str, payload: dict[str, Any]) -> str:
    if payload.get("message"):
        return str(payload["message"])
    if payload.get("content"):
        return str(payload["content"])
    if payload.get("summary"):
        return str(payload["summary"])
    if payload.get("goal"):
        return str(payload["goal"])
    return message_type


def post_orchestrator_session_event(session_id: str, message: dict[str, Any]) -> None:
    payload = dict(message)
    message_type = str(payload.get("type") or "message")
    body = json.dumps(
        {
            "event_type": session_event_type(message_type),
            "message": session_event_message(message_type, payload),
            "level": "warn" if message_type in {"blocker", "session_decline"} else "info",
            "payload": payload,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{ORCHESTRATOR_URL.rstrip('/')}/sessions/{session_id}/events",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5):
            pass
    except (urllib.error.URLError, TimeoutError):
        pass


async def publish_session_message(session_id: str, message: dict[str, Any]) -> None:
    event_type = str(message.get("type") or "message")
    payload = dict(message)
    payload.pop("type", None)
    await publish_event(
        AgentStreamEvent(
            session_id=session_id,
            agent_id=str(message.get("agent_id") or message.get("from") or "gateway"),
            type="text" if event_type in {"agent_message", "session_message"} else "phase",
            payload={"event_type": event_type, **payload},
        )
    )
    asyncio.create_task(asyncio.to_thread(post_orchestrator_session_event, session_id, message))
    if event_type == "session_done":
        session_status[session_id] = "completed"
        for agent_id in list(session_agents[session_id]):
            agent_status[agent_id] = "online_idle"
    dead: list[WebSocket] = []
    for ws in list(session_ws_connections[session_id]):
        try:
            await ws.send_json(message)
        except RuntimeError:
            dead.append(ws)
    for ws in dead:
        session_ws_connections[session_id].discard(ws)


def capabilities_match(agent_caps: dict[str, Any], required: dict[str, Any]) -> bool:
    for key, value in required.items():
        if agent_caps.get(key) != value:
            return False
    return True


def agent_type_for(agent_id: str) -> str:
    profile = agent_profiles.get(agent_id, {})
    agent_type = str(profile.get("agent_type") or "")
    caps = profile.get("capabilities") or {}
    if isinstance(caps, dict) and caps.get("agent"):
        return str(caps["agent"])
    if agent_type == "claude_code":
        return "scc" if profile.get("agent_name") == "silicon-cc" else "claude"
    return agent_type or "unknown"


def count_active_by_type(agent_type: str) -> int:
    return sum(
        1
        for agent_id, status_value in agent_status.items()
        if agent_type_for(agent_id) == agent_type
        and status_value in {"summoned", "in_session_idle", "running"}
    )


def cost_guard_snapshot(cost_policy: dict[str, Any] | None = None) -> dict[str, Any]:
    policy = cost_policy or {}
    max_by_type = policy.get("max_active_by_agent_type") or {}
    types = set(max_by_type.keys()) | {agent_type_for(agent_id) for agent_id in agent_profiles}
    return {
        agent_type: {
            "active": count_active_by_type(agent_type),
            "max": max_by_type.get(agent_type),
        }
        for agent_type in sorted(types)
    }


def template_agent_type(template_id: str) -> str:
    lowered = template_id.lower()
    if "codex" in lowered:
        return "codex"
    if "scc" in lowered:
        return "scc"
    if "claude" in lowered:
        return "claude"
    if "hermes" in lowered:
        return "hermes"
    if "opencode" in lowered:
        return "opencode"
    if "reasonix" in lowered:
        return "reasonix"
    return "generic"


def machine_snapshot() -> list[DormMachine]:
    machines = {machine_id: dict(machine) for machine_id, machine in STATIC_MACHINES.items()}
    for machine_id in launcher_connections:
        reg = machine_registry.get(machine_id, {})
        machine = machines.setdefault(
            machine_id,
            {
                "machineId": machine_id,
                "displayName": reg.get("display_name") or machine_id,
                "location": "other",
                "status": "online",
                "launcherStatus": "connected",
                "agents": [],
            },
        )
        machine["status"] = "online"
        machine["launcherStatus"] = "connected"
        # Overlay display_name + agents from register event (dynamic machines)
        if reg.get("display_name"):
            machine["displayName"] = reg["display_name"]
        if reg.get("agents"):
            machine["agents"] = reg["agents"]
            # Ensure every agent has an agentTemplateId
            for agent_entry in machine["agents"]:
                if isinstance(agent_entry, dict) and not agent_entry.get("agentTemplateId"):
                    agent_type = str(agent_entry.get("agentType") or "generic")
                    agent_name = str(agent_entry.get("agentName") or "unknown")
                    agent_entry["agentTemplateId"] = f"{agent_type}-{machine_id}-{agent_name}"

    for agent_id, profile in agent_profiles.items():
        host = str(profile.get("host_id") or profile.get("agent_name") or "")
        machine_id = "wuying-01" if "wuying" in host else "jd-ecs" if "silicon" in host else "local"
        machine = machines.setdefault(
            machine_id,
            {
                "machineId": machine_id,
                "displayName": machine_id,
                "location": "other",
                "status": "online",
                "launcherStatus": "disconnected",
                "agents": [],
            },
        )
        agent_name = str(profile.get("agent_name") or agent_id)
        agent_type = agent_type_for(agent_id)
        status_value = "standby" if agent_status.get(agent_id) == "online_idle" else "busy"
        existing = {
            str(agent.get("agentTemplateId"))
            for agent in machine.get("agents", [])
            if isinstance(agent, dict)
        }
        template_id = f"{agent_type}-{machine_id}-{agent_id[:8]}"
        if template_id not in existing:
            machine.setdefault("agents", []).append(
                {
                    "agentTemplateId": template_id,
                    "agentName": agent_name,
                    "agentType": agent_type,
                    "status": status_value,
                    "capabilities": profile.get("capabilities") or {},
                }
            )

    return [DormMachine.model_validate(machine) for machine in machines.values()]


async def record_agent_output(
    session_id: str,
    agent_id: str,
    terminal_id: str,
    stream: str,
    content: str,
    seq: int,
) -> None:
    await publish_event(
        AgentStreamEvent(
            session_id=session_id,
            agent_id=agent_id,
            type="text" if stream == "stdout" else "warning",
            payload={
                "event_type": "agent.output",
                "terminal_id": terminal_id,
                "stream": stream,
                "seq": seq,
                "content": content,
                "truncated": False,
            },
        )
    )
    asyncio.create_task(
        asyncio.to_thread(
            post_orchestrator_session_event,
            session_id,
            {
                "type": "agent.output",
                "session_id": session_id,
                "agent_id": agent_id,
                "terminal_id": terminal_id,
                "stream": stream,
                "seq": seq,
                "content": content,
                "truncated": False,
            },
        )
    )


async def publish_agent_output(
    session_id: str,
    agent_id: str,
    stream: str,
    content: str,
    seq: int = 0,
    truncated: bool = False,
    terminal_id: str | None = None,
) -> AgentStreamEvent:
    """Publish an agent.output event to SSE subscribers (Canvas).

    Used by both the agent WebSocket handler and the POST endpoint.
    """
    event = AgentStreamEvent(
        session_id=session_id,
        agent_id=agent_id,
        type="text" if stream == "stdout" else "warning",
        payload={
            "event_type": "agent.output",
            "stream": stream,
            "seq": seq,
            "content": content,
            "truncated": truncated,
            **({"terminal_id": terminal_id} if terminal_id else {}),
        },
    )
    await publish_event(event)
    # Also notify orchestrator so session events table gets the record
    asyncio.create_task(
        asyncio.to_thread(
            post_orchestrator_session_event,
            session_id,
            {
                "type": "agent.output",
                "session_id": session_id,
                "agent_id": agent_id,
                "stream": stream,
                "seq": seq,
                "content": content,
                "truncated": truncated,
                **({"terminal_id": terminal_id} if terminal_id else {}),
            },
        )
    )
    return event


def select_invite_targets(
    invite: dict[str, Any],
    cost_policy: dict[str, Any] | None = None,
) -> tuple[list[str], list[dict[str, Any]]]:
    capabilities = invite.get("capabilities") or {}
    preferred_names = invite.get("preferred_names") or []
    required_names = invite.get("required_names") or []
    explicit_min_count = "min_count" in invite and invite.get("min_count") is not None
    min_count = int(invite.get("min_count") or 1)
    if not capabilities and not required_names and not explicit_min_count:
        raise ValueError("empty invite: specify capabilities, required_names, or min_count")

    candidates: list[str] = []
    skipped: list[dict[str, Any]] = []
    for agent_id, profile in agent_profiles.items():
        name = str(profile.get("agent_name") or "")
        if required_names and name not in required_names:
            continue
        if agent_status.get(agent_id) != "online_idle":
            if required_names and _can_wake_agent(agent_id):
                candidates.append(agent_id)
                continue
            skipped.append({"agent_id": agent_id, "reason": "busy_or_offline"})
            continue
        agent_caps = profile.get("capabilities") or {}
        if capabilities and not capabilities_match(agent_caps, capabilities):
            skipped.append({"agent_id": agent_id, "reason": "capability_mismatch"})
            continue
        candidates.append(agent_id)

    name_rank = {
        str(name): index
        for index, name in enumerate([*required_names, *preferred_names])
    }
    candidates.sort(
        key=lambda agent_id: (
            name_rank.get(str(agent_profiles[agent_id].get("agent_name") or ""), 10_000),
            str(agent_profiles[agent_id].get("agent_name") or ""),
        )
    )

    max_by_type = (cost_policy or {}).get("max_active_by_agent_type") or {}
    invited_by_type: dict[str, int] = defaultdict(int)
    selected: list[str] = []
    for agent_id in candidates:
        agent_type = agent_type_for(agent_id)
        limit = max_by_type.get(agent_type)
        if limit is not None and count_active_by_type(agent_type) + invited_by_type[agent_type] >= int(limit):
            skipped.append({"agent_id": agent_id, "reason": "cost_policy_limit", "agent_type": agent_type})
            continue
        selected.append(agent_id)
        invited_by_type[agent_type] += 1
        if explicit_min_count and not required_names and len(selected) >= min_count:
            break

    return selected, skipped


async def invite_to_session(request: SessionInviteRequest) -> SessionInviteResponse:
    session_id = request.session_id or str(uuid4())
    selected, skipped = select_invite_targets(request.invite, request.cost_policy)
    invite_payload = {
        "type": "session_invite",
        "session_id": session_id,
        "conference_url": f"{PUBLIC_GATEWAY_WS_URL.rstrip('/')}/ws/sessions/{session_id}",
        "role": request.invite.get("role", "participant"),
        "required_capabilities": request.invite.get("capabilities") or {},
        "goal": request.goal,
        "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat(),
        "cost_policy": request.cost_policy or {},
        "stage": request.stage,
        "stage_round": request.stage_round,
        "max_rounds": request.max_rounds,
    }
    invited: list[str] = []
    for agent_id in selected:
        websocket = agent_connections.get(agent_id)
        if not websocket:
            machine_id = _agent_to_machine(agent_id)
            launcher_ws = launcher_connections.get(machine_id) if machine_id else None
            if launcher_ws and _spawn_template_for(agent_id):
                asyncio.create_task(_wake_and_invite(machine_id, agent_id, session_id, invite_payload))
                invited.append(agent_id)
                logger.info("wake_on_knock scheduled agent=%s machine=%s", agent_id, machine_id)
            else:
                skipped.append({"agent_id": agent_id, "reason": "disconnected"})
            continue
        await websocket.send_json(invite_payload)
        agent_status[agent_id] = "summoned"
        session_agents[session_id].add(agent_id)
        invited.append(agent_id)

    await publish_session_message(
        session_id,
        {
            "type": "session_invite",
            "agent_id": "gateway",
            "goal": request.goal,
            "invited": invited,
            "skipped": skipped,
            "cost_guard": cost_guard_snapshot(request.cost_policy),
        },
    )
    return SessionInviteResponse(session_id=session_id, invited=invited, skipped=skipped)


def launcher_event_to_agent_event(machine_id: str, event: LauncherEvent) -> AgentStreamEvent:
    if event.type == "stdout":
        return AgentStreamEvent(
            session_id=event.session_id,
            agent_id=machine_id,
            type="text",
            payload={"content": event.data or "", "stream": "stdout"},
        )
    if event.type == "stderr":
        return AgentStreamEvent(
            session_id=event.session_id,
            agent_id=machine_id,
            type="warning",
            payload={"message": event.data or "", "stream": "stderr"},
        )
    if event.type == "spawned":
        return AgentStreamEvent(
            session_id=event.session_id,
            agent_id=machine_id,
            type="phase",
            payload={"phase": "execute", "status": "start", "pid": event.pid},
        )
    if event.type == "exit":
        return AgentStreamEvent(
            session_id=event.session_id,
            agent_id=machine_id,
            type="done",
            payload={
                "usage": {"input_tokens": 0, "output_tokens": 0},
                "duration_ms": 0,
                "exit_code": event.exit_code,
            },
        )
    if event.type == "error":
        return AgentStreamEvent(
            session_id=event.session_id,
            agent_id=machine_id,
            type="error",
            payload={"message": event.message or "Launcher error", "recoverable": True},
        )
    return AgentStreamEvent(
        session_id=event.session_id,
        agent_id=machine_id,
        type="heartbeat",
        payload={"launcher": event.model_dump(mode="json")},
    )


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "streaming_gateway",
        "time": datetime.now(timezone.utc).isoformat(),
        "launchers": sorted(launcher_connections.keys()),
        "agents_online": len(agent_connections),
        "agents": [
            {
                "agent_id": agent_id,
                "agent_name": profile.get("agent_name"),
                "agent_type": agent_type_for(agent_id),
                "status": agent_status.get(agent_id),
            }
            for agent_id, profile in sorted(agent_profiles.items())
        ],
        "cost_guard": cost_guard_snapshot(),
        "sessions": [
            {
                "session_id": session_id,
                "status": session_status[session_id],
                "participants": sorted(session_agents[session_id]),
                "connections": len(session_ws_connections[session_id]),
            }
            for session_id in sorted(set(session_agents.keys()) | set(session_ws_connections.keys()))
        ],
    }


@app.post("/auth/login")
async def auth_login(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON")
    username = str(body.get("username") or "")
    password = str(body.get("password") or "")
    from .auth import login as auth_login
    token = auth_login(username, password)
    if token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    return {"token": token}


@app.post("/auth/logout")
async def auth_logout(request: Request) -> dict[str, str]:
    token = auth.extract_token(request)
    ok = await auth.logout(token)
    return {"status": "logged_out" if ok else "token_not_found"}

@app.get("/machines", response_model=list[DormMachine])
def list_machines() -> list[DormMachine]:
    return machine_snapshot()


@app.get("/machines/{machine_id}/agents", response_model=list[DormAgent])
def list_machine_agents(machine_id: str) -> list[DormAgent]:
    for machine in machine_snapshot():
        if machine.machineId == machine_id:
            return machine.agents
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Machine not found.")


@app.post("/sessions", response_model=SessionCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_session(request: SessionCreateRequest) -> SessionCreateResponse:
    session_id = request.session_id or str(uuid4())
    await publish_event(
        AgentStreamEvent(
            session_id=session_id,
            agent_id=request.agent_id,
            type="init",
            payload={
                "agent_name": request.agent_name,
                "agent_type": request.agent_type,
                "tools": request.tools,
                "model": request.model,
            },
        )
    )
    return SessionCreateResponse(session_id=session_id)


@app.post("/sessions/{session_id}/invite", response_model=SessionInviteResponse)
async def invite_session(session_id: str, request: SessionInviteRequest) -> SessionInviteResponse:
    request.session_id = session_id
    try:
        return await invite_to_session(request)
    except ValueError as err:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(err)) from err


@app.post("/sessions/invite", response_model=SessionInviteResponse)
async def invite_new_session(request: SessionInviteRequest) -> SessionInviteResponse:
    try:
        return await invite_to_session(request)
    except ValueError as err:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(err)) from err


@app.post("/sessions/{session_id}/events", status_code=status.HTTP_202_ACCEPTED)
async def append_session_event(session_id: str, event: AgentStreamEvent) -> dict[str, str]:
    if event.session_id != session_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Path session_id must match event.session_id.",
        )
    bridged_type = event.payload.get("type") or event.payload.get("event_type")
    if bridged_type:
        await publish_session_message(
            session_id,
            {
                "type": str(bridged_type),
                "session_id": session_id,
                "agent_id": event.agent_id,
                **event.payload,
            },
        )
        return {"status": "accepted"}
    await publish_event(event)
    return {"status": "accepted"}


@app.get("/sessions/{session_id}/events")
async def get_session_events(
    session_id: str,
    event_type: str | None = None,
    from_seq: int = 0,
) -> list[dict[str, Any]]:
    """Return session event history for xterm replay. Supports from_seq for incremental loads."""
    history = list(session_history.get(session_id, []))
    result = []
    for event in history:
        if event.seq < from_seq:
            continue
        if event_type:
            payload_etype = event.payload.get("event_type") or event.payload.get("type")
            if payload_etype != event_type:
                continue
        result.append(event.model_dump(mode="json"))
    return result


@app.post("/sessions/{session_id}/message", status_code=status.HTTP_202_ACCEPTED)
async def send_session_message(session_id: str, request: SessionMessageRequest) -> dict[str, str]:
    message = {
        "type": request.type,
        "session_id": session_id,
        "agent_id": request.agent_id,
        **request.payload,
    }
    if request.outcome is not None:
        message["outcome"] = request.outcome
    if request.summary is not None:
        message["summary"] = request.summary
    if request.message is not None:
        message["message"] = request.message
    await publish_session_message(session_id, message)
    return {"status": "sent"}


@app.post("/sessions/{session_id}/agent-output", status_code=status.HTTP_202_ACCEPTED)
async def post_agent_output(session_id: str, request: AgentOutputRequest) -> dict[str, Any]:
    """Accept agent output chunks via HTTP POST and fan-out via SSE.

    Designed for HTTP-based agents (polling workers) that don't use WebSocket.
    Canvas consumes these events via GET /stream/sessions/{session_id} (SSE).
    """
    if request.session_id != session_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Path session_id must match body.session_id.",
        )
    event = await publish_agent_output(
        session_id=request.session_id,
        agent_id=request.agent_id,
        stream=request.stream,
        content=request.content,
        seq=request.seq,
        truncated=request.truncated,
        terminal_id=request.terminal_id,
    )
    return {
        "status": "published",
        "msg_id": event.msg_id,
        "seq": event.seq,
    }


@app.post("/sessions/{session_id}/participants", response_model=ParticipantCreateResponse)
async def create_participant(session_id: str, request: ParticipantCreateRequest) -> ParticipantCreateResponse:
    machines = {machine.machineId: machine for machine in machine_snapshot()}
    machine = machines.get(request.machine_id)
    if machine is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Machine not found.")
    if machine.status != "online":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Machine is offline.")

    agent = next((item for item in machine.agents if item.agentTemplateId == request.agent_template_id), None)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent template not found.")
    if agent.status not in {"standby", "busy"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Agent is not available.")

    participant_id = str(uuid4())
    terminal_id = str(uuid4())
    agent_id = f"{request.machine_id}:{request.agent_template_id}"
    session_participants[session_id][participant_id] = {
        "session_id": session_id,
        "participant_id": participant_id,
        "machine_id": request.machine_id,
        "agent_template_id": request.agent_template_id,
        "agent_name": agent.agentName,
        "agent_type": agent.agentType,
        "terminal_id": terminal_id,
        "role": request.role,
        "status": "summoned",
        "initial_context": request.initial_context,
    }
    terminal_sessions[terminal_id] = {
        "session_id": session_id,
        "participant_id": participant_id,
        "machine_id": request.machine_id,
        "agent_template_id": request.agent_template_id,
        "agent_name": agent.agentName,
        "agent_type": agent.agentType,
        "role": request.role,
        "agent_id": agent_id,
        "seq": 0,
    }
    session_agents[session_id].add(agent_id)
    await publish_session_message(
        session_id,
        {
            "type": "session.participant_summoned",
            "session_id": session_id,
            "agent_id": agent_id,
            "participant_id": participant_id,
            "terminal_id": terminal_id,
            "machine_id": request.machine_id,
            "agent_template_id": request.agent_template_id,
            "agent_name": agent.agentName,
            "agent_type": agent.agentType,
            "role": request.role,
        },
    )
    return ParticipantCreateResponse(
        participant_id=participant_id,
        terminal_id=terminal_id,
        pty_ws_url=f"{PUBLIC_GATEWAY_WS_URL.rstrip('/')}/ws/pty/{agent_id}/{terminal_id}?session_id={session_id}",
    )


# ── Round management ──

@app.get("/sessions/{session_id}/rounds")
async def list_rounds(session_id: str) -> list[dict[str, Any]]:
    in_memory = session_rounds.get(session_id, [])
    if in_memory:
        return in_memory
    # DB 回落：服务重启后从持久化层恢复
    if _iron_law_available:
        db_rounds = _get_rounds_from_db(session_id)
        if db_rounds:
            session_rounds[session_id] = db_rounds
            return db_rounds
    return []


@app.post("/sessions/{session_id}/rounds", status_code=status.HTTP_201_CREATED)
async def create_round(session_id: str, request: RoundCreateRequest) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    round_record = {
        "round_id": request.round,
        "session_id": session_id,
        "leader_instruction": request.leader_instruction,
        "participant_assignments": {},
        "agent_outputs": {},
        "artifacts": [],
        "blockers": [],
        "leader_review": "",
        "deployment_opinion": "",
        "decision": "",
        "next_action": "",
        "created_at": now,
        "closed_at": "",
    }
    session_rounds[session_id].append(round_record)
    if gateway_db:
        asyncio.create_task(gateway_db.save_round(session_id, round_record))
    await publish_session_message(session_id, {
        "type": "round_created",
        "round": request.round,
        "leader_instruction": request.leader_instruction,
    })
    return round_record


@app.put("/sessions/{session_id}/rounds/{round_num}")
async def close_round(session_id: str, round_num: int, request: RoundUpdateRequest) -> dict[str, Any]:
    rounds = session_rounds.get(session_id, [])
    target = next((r for r in rounds if r["round_id"] == round_num), None)
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Round not found")
    now = datetime.now(timezone.utc).isoformat()
    target.update({
        "decision": request.decision,
        "leader_review": request.leader_review,
        "deployment_opinion": request.deployment_opinion,
        "next_action": request.next_action,
        "closed_at": now,
    })
    if gateway_db:
        asyncio.create_task(gateway_db.save_round(session_id, target))
    await publish_session_message(session_id, {
        "type": "round_closed",
        "round": round_num,
        "decision": request.decision,
        "leader_review": request.leader_review,
        "deployment_opinion": request.deployment_opinion,
        "next_action": request.next_action,
    })
    return target


# ── Task assignment ──

@app.post("/sessions/{session_id}/assign", status_code=status.HTTP_202_ACCEPTED)
async def assign_task(session_id: str, request: TaskAssignRequest) -> dict[str, str]:
    agent_ws = agent_connections.get(request.agent_id)
    if not agent_ws:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not connected")
    task_msg = {
        "type": "task_assigned",
        "session_id": session_id,
        "agent_id": request.agent_id,
        "task": request.task,
    }
    await agent_ws.send_json(task_msg)
    return {"status": "assigned", "agent_id": request.agent_id}


class AgentOutputRequest(BaseModel):
    """Agent pushes a chunk of output (stdout/stderr) to be SSE-fanned out to Canvas."""
    session_id: str
    agent_id: str
    stream: Literal["stdout", "stderr"] = "stdout"
    content: str
    seq: int = 0
    truncated: bool = False
    terminal_id: str | None = None


class TaskDispatchRequest(BaseModel):
    task_id: str
    required_capabilities: dict[str, Any] = Field(default_factory=dict)
    target_agent_id: str | None = None
    task: dict[str, Any] = Field(default_factory=dict)


@app.post("/tasks/dispatch", status_code=status.HTTP_202_ACCEPTED)
async def dispatch_task(request: TaskDispatchRequest) -> dict[str, Any]:
    """Push task_assigned to a specific agent (deterministic routing).

    Requires target_agent_id.  Broadcast-to-all-idle has been removed —
    tasks without a resolved target stay queued until the scanner
    re-dispatches them with a resolved agent.
    """
    notified: list[str] = []

    target_id = getattr(request, "target_agent_id", None)
    if not target_id:
        logger.warning(
            "dispatch_task called without target_agent_id for task %s — skipping push",
            request.task_id,
        )
        return {"notified": [], "count": 0, "reason": "no target_agent_id"}

    candidate_ids = [str(target_id)]

    for agent_id in candidate_ids:
        ws = agent_connections.get(agent_id)
        if ws is None:
            continue
        try:
            await ws.send_json({
                "type": "task_assigned",
                "task_id": request.task_id,
                "task": request.task,
            })
            notified.append(agent_id)
        except Exception:
            pass
    return {"notified": notified, "count": len(notified)}


@app.get("/stream/sessions/{session_id}")
async def stream_session(session_id: str, request: Request) -> StreamingResponse:
    queue: asyncio.Queue[AgentStreamEvent] = asyncio.Queue(maxsize=MAX_EVENT_QUEUE_SIZE)
    session_subscribers[session_id].add(queue)

    async def event_generator():
        try:
            for event in session_history[session_id]:
                yield sse_frame(event)

            while not await request.is_disconnected():
                try:
                    event = await asyncio.wait_for(
                        queue.get(),
                        timeout=HEARTBEAT_INTERVAL_SECONDS,
                    )
                except asyncio.TimeoutError:
                    event = AgentStreamEvent(
                        session_id=session_id,
                        type="heartbeat",
                        payload={},
                    )
                yield sse_frame(event)
        finally:
            session_subscribers[session_id].discard(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.websocket("/ws/launchers/{machine_id}")
async def launcher_ws(websocket: WebSocket, machine_id: str) -> None:
    # Launchers are internal system components; identity verified by machine_id registration.
    await websocket.accept()
    launcher_connections[machine_id] = websocket
    machine_registry[machine_id] = {
        "machine_id": machine_id,
        "display_name": machine_id,  # will be updated on register
        "status": "online",
        "launcher_status": "connected",
        "agents": [],
    }
    try:
        async for raw_message in websocket.iter_text():
            # Route PTY messages (stdout/stderr/exit with terminal_id) to pty_bridges
            try:
                raw_obj = json.loads(raw_message)
            except json.JSONDecodeError:
                await publish_event(
                    AgentStreamEvent(
                        session_id=f"launcher-{machine_id}",
                        agent_id=machine_id,
                        type="error",
                        payload={"message": "Invalid JSON from launcher", "recoverable": True},
                    )
                )
                continue

            # PTY routing: messages with terminal_id go to the PTY bridge
            pty_tid = raw_obj.get("terminal_id") or ""
            if pty_tid and pty_tid in pty_bridges:
                try:
                    pty_bridges[pty_tid].put_nowait(raw_obj)
                except asyncio.QueueFull:
                    pass
                continue

            try:
                launcher_event = LauncherEvent.model_validate(raw_obj)
            except ValueError:
                await publish_event(
                    AgentStreamEvent(
                        session_id=f"launcher-{machine_id}",
                        agent_id=machine_id,
                        type="error",
                        payload={"message": "Invalid launcher event JSON", "recoverable": True},
                    )
                )
                continue
            if launcher_event.type == "register":
                display_name = launcher_event.display_name or machine_id
                machine_registry[machine_id].update({
                    "status": "online",
                    "display_name": display_name,
                    "agents": launcher_event.agents,
                })
                logger.info(
                    "launcher registered machine_id=%s display=%s agents=%d",
                    machine_id, display_name, len(launcher_event.agents),
                )
                continue  # skip publish_event for register type
            await publish_event(launcher_event_to_agent_event(machine_id, launcher_event))
    except WebSocketDisconnect:
        pass
    finally:
        if launcher_connections.get(machine_id) is websocket:
            launcher_connections.pop(machine_id, None)
        if machine_id in machine_registry:
            machine_registry[machine_id]["status"] = "offline"


@app.websocket("/ws/pty/{agent_id}/{terminal_id}")
async def pty_ws(websocket: WebSocket, agent_id: str, terminal_id: str) -> None:
    if not auth.ws_auth_from_url(websocket.url):
        await websocket.close(code=4001, reason="Unauthorized")
        return
    await websocket.accept()
    session_id = websocket.query_params.get("session_id") or terminal_sessions.get(terminal_id, {}).get("session_id") or terminal_id
    terminal = terminal_sessions.setdefault(
        terminal_id,
        {
            "session_id": session_id,
            "agent_id": agent_id,
            "agent_name": agent_id,
            "agent_type": template_agent_type(agent_id),
            "seq": 0,
        },
    )
    terminal["session_id"] = session_id
    terminal["agent_id"] = agent_id
    seq = int(terminal.get("seq") or 0)

    async def send_output(stream: str, content: str) -> None:
        nonlocal seq
        seq += 1
        terminal["seq"] = seq
        await websocket.send_json({"type": stream, "data": content, "seq": seq})
        await record_agent_output(session_id, agent_id, terminal_id, stream, content, seq)

    # Try to bridge to Launcher
    machine_id = agent_id.split(":")[0] if ":" in agent_id else ""
    launcher = launcher_connections.get(machine_id)
    agent_type = terminal.get("agent_type") or template_agent_type(agent_id)

    if launcher:
        await send_output("stdout", f"PTY bridging to Launcher: {machine_id} ({agent_type})\r\n")
        await send_output("stdout", f"terminal={terminal_id}\r\n\r\n")

        # Create queue for this PTY bridge
        pty_bridges[terminal_id] = asyncio.Queue(maxsize=256)
        launcher_done = asyncio.Event()

        async def _forward_launcher_output():
            nonlocal seq
            queue = pty_bridges.get(terminal_id)
            if not queue:
                return
            while not launcher_done.is_set():
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    continue
                msg_type = msg.get("type") or ""
                if msg_type in ("stdout", "stderr"):
                    await send_output(msg_type, msg.get("data") or "")
                elif msg_type == "exit":
                    launcher_done.set()
                    await send_output("stdout", f"\r\n[PTY exited {msg.get('exit_code')}]\r\n")
                elif msg_type == "pty_error":
                    await send_output("stderr", f"\r\n[PTY error: {msg.get('message')}]\r\n")
                    launcher_done.set()

        # Spawn PTY on Launcher
        await launcher.send_json({
            "action": "pty_spawn",
            "terminal_id": terminal_id,
            "agent_type": agent_type,
        })

        forward_task = asyncio.create_task(_forward_launcher_output())

        try:
            async for message in websocket.iter_json():
                msg_type = str(message.get("type") or "")
                if msg_type == "stdin":
                    await launcher.send_json({
                        "action": "pty_stdin",
                        "terminal_id": terminal_id,
                        "data": str(message.get("data") or ""),
                    })
                elif msg_type == "close":
                    await launcher.send_json({
                        "action": "pty_signal",
                        "terminal_id": terminal_id,
                        "signal": "SIGTERM",
                    })
                    break
                elif msg_type == "resize":
                    pass  # future: forward resize
        except WebSocketDisconnect:
            pass
        finally:
            launcher_done.set()
            pty_bridges.pop(terminal_id, None)
            forward_task.cancel()
            try:
                await forward_task
            except asyncio.CancelledError:
                pass

    else:
        # Fallback: echo/smoke mode when no Launcher connected
        await send_output(
            "stdout",
            f"UnionAgents PTY bridge attached: {agent_id} terminal={terminal_id}\r\n",
        )
        await send_output(
            "stdout",
            "AW3a echo/smoke mode. No Launcher connected for this machine.\r\n",
        )
        async for message in websocket.iter_json():
            message_type = str(message.get("type") or "")
            if message_type == "stdin":
                data = str(message.get("data") or "")
                await send_output("stdout", data)
            elif message_type == "close":
                await websocket.send_json({"type": "exit", "exit_code": 0})
                break
    return  # pty_ws

# Legacy: the launcher_ws handler needs to route pty-related messages to the PTY bridge
# We hook into the existing launcher message loop to route stdout/stderr/exit to pty clients


@app.post("/launchers/{machine_id}/control", status_code=status.HTTP_202_ACCEPTED)
async def send_launcher_control(machine_id: str, message: LauncherControlMessage) -> dict[str, str]:
    websocket = launcher_connections.get(machine_id)
    if not websocket:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Launcher is offline.")
    await websocket.send_json(message.model_dump(mode="json"))
    return {"status": "sent"}




@app.get("/sessions/{session_id}/snapshot")
async def get_session_snapshot(session_id: str, project: str = "omima") -> dict:
    """Leader 启动时调用：读全局快照（目标、Agent、开放任务、事件）。
    代理到 iron-law 系统的 assemble_leader_snapshot。"""
    if _iron_law_available:
        return _assemble_leader_snapshot(session_id=session_id, project=project)
    return {"session_id": session_id, "error": "iron_law not available"}

@app.websocket("/ws/agents/{agent_id}")
async def agent_bedroom_ws(websocket: WebSocket, agent_id: str) -> None:
    # Agents are registered via orchestrator; agent_id is their identity credential.
    # No token required — HTTP API endpoints retain Bearer auth for human/admin access.
    await websocket.accept()
    agent_connections[agent_id] = websocket
    agent_status[agent_id] = "online_idle"
    agent_profiles.setdefault(agent_id, {"agent_id": agent_id})
    try:
        async for message in websocket.iter_json():
            message_type = message.get("type")
            if message_type == "identify":
                profile = {
                    "agent_id": agent_id,
                    "agent_name": message.get("agent_name") or agent_id,
                    "agent_type": message.get("agent_type") or "generic",
                    "capabilities": message.get("capabilities") or {},
                    "status": message.get("status") or "online_idle",
                    "last_seen_at": datetime.now(timezone.utc).isoformat(),
                }
                agent_profiles[agent_id] = profile
                agent_status[agent_id] = str(profile["status"])
                await websocket.send_json({"type": "gateway_ready", "agent_id": agent_id})
            elif message_type == "ping":
                await websocket.send_json({"type": "pong"})
            elif message_type == "session_join":
                session_id = str(message.get("session_id") or "")
                if session_id:
                    session_agents[session_id].add(agent_id)
                    agent_status[agent_id] = "in_session_idle"
                    await publish_session_message(session_id, {"type": "session_join", **message})
            elif message_type == "session_decline":
                session_id = str(message.get("session_id") or "")
                agent_status[agent_id] = "online_idle"
                if session_id:
                    await publish_session_message(session_id, {"type": "session_decline", **message})
            elif message_type == "status_update":
                status_value = str(message.get("status") or "online_idle")
                agent_status[agent_id] = status_value
                profile = agent_profiles.setdefault(agent_id, {"agent_id": agent_id})
                profile["status"] = status_value
                profile["last_seen_at"] = datetime.now(timezone.utc).isoformat()
            elif message_type in {"agent_message", "task_complete", "blocker", "session_leave"}:
                session_id = str(message.get("session_id") or "")
                if session_id:
                    await publish_session_message(session_id, {"agent_id": agent_id, **message})
                    if message_type == "session_leave":
                        agent_status[agent_id] = "online_idle"
                        session_agents[session_id].discard(agent_id)
            elif message_type == "agent_output":
                # Agent streams its stdout/stderr output for SSE fanout to Canvas
                session_id = str(message.get("session_id") or "")
                stream = str(message.get("stream") or "stdout")
                content = str(message.get("content") or message.get("data") or "")
                seq_val = message.get("seq")
                seq = int(seq_val) if seq_val is not None else 0
                truncated = bool(message.get("truncated", False))
                terminal_id = message.get("terminal_id")
                if session_id:
                    await publish_agent_output(
                        session_id=session_id,
                        agent_id=agent_id,
                        stream=stream,
                        content=content,
                        seq=seq,
                        truncated=truncated,
                        terminal_id=terminal_id,
                    )
    except WebSocketDisconnect:
        pass
    finally:
        if agent_connections.get(agent_id) is websocket:
            agent_connections.pop(agent_id, None)
        agent_status[agent_id] = "offline"
        # Notify orchestrator immediately so routing reflects reality
        try:
            async with httpx.AsyncClient(timeout=3.0) as hc:
                await hc.post(f"{ORCHESTRATOR_URL}/agents/{agent_id}/offline")
        except Exception:
            pass  # Best-effort; scanner handles eventual consistency


@app.websocket("/ws/sessions/{session_id}")
async def session_room_ws(websocket: WebSocket, session_id: str) -> None:
    # Conference room: agents join via session_id issued by orchestrator. No token required.
    await websocket.accept()
    session_ws_connections[session_id].add(websocket)
    session_status[session_id] = "active"
    try:
        await websocket.send_json({"type": "session_ready", "session_id": session_id})
        async for message in websocket.iter_json():
            await publish_session_message(session_id, {"session_id": session_id, **message})
    except WebSocketDisconnect:
        pass
    finally:
        session_ws_connections[session_id].discard(websocket)
