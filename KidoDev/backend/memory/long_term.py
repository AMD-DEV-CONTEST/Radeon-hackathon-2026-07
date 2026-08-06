"""
Long-Term Agent Memory — Supabase Backed
Persists per-child learning observations across sessions.
"""
import os
import time
from typing import Optional, List, Dict, Any

from supabase import create_client, Client

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")


def _get_client() -> Optional[Client]:
    if SUPABASE_URL and SUPABASE_KEY:
        return create_client(SUPABASE_URL, SUPABASE_KEY)
    return None


async def load_memory(child_id: str) -> Dict[str, Any]:
    """Fetch child's long-term agent memory from Supabase."""
    sb = _get_client()
    if not sb:
        return _default_memory(child_id)

    try:
        res = sb.table("agent_memory").select("*").eq("child_id", child_id).maybe_single().execute()
        if res.data:
            return res.data
    except Exception:
        pass
    return _default_memory(child_id)


async def update_memory(child_id: str, updates: Dict[str, Any]) -> bool:
    """Upsert agent memory for a child."""
    sb = _get_client()
    if not sb:
        return False

    try:
        updates["child_id"] = child_id
        updates["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        sb.table("agent_memory").upsert(updates, on_conflict="child_id").execute()
        return True
    except Exception as e:
        print(f"[LongTermMemory] update error: {e}")
        return False


async def append_observation(child_id: str, observation: str):
    """Add a new observation string to the child's memory."""
    mem = await load_memory(child_id)
    obs: List[str] = mem.get("observations", [])
    if observation not in obs:
        obs.append(observation)
        obs = obs[-20:]  # keep last 20 observations
    await update_memory(child_id, {"observations": obs})


import uuid

def _is_valid_uuid(val: Optional[str]) -> bool:
    if not val:
        return False
    try:
        uuid.UUID(str(val))
        return True
    except (ValueError, TypeError):
        return False

async def log_agent_action(
    child_id: Optional[str],
    agent_name: str,
    action: str,
    tool_used: Optional[str] = None,
    tokens_generated: int = 0,
    latency_ms: int = 0,
    gpu_type: str = "AMD MI300X",
):
    """Write an agent action to the agent_logs table for the AMD benchmark display."""
    sb = _get_client()
    if not sb:
        return
    try:
        safe_child_id = child_id if _is_valid_uuid(child_id) else None
        sb.table("agent_logs").insert({
            "child_id": safe_child_id,
            "agent_name": agent_name,
            "action": action,
            "tool_used": tool_used,
            "tokens_generated": tokens_generated,
            "latency_ms": latency_ms,
            "gpu_type": gpu_type,
        }).execute()
    except Exception as e:
        print(f"[AgentLog] insert error: {e}")


def _default_memory(child_id: str) -> Dict[str, Any]:
    return {
        "child_id": child_id,
        "observations": [],
        "learning_style": "visual",
        "weak_block_types": [],
        "strong_block_types": [],
        "last_emotion": "neutral",
        "hint_count": 0,
    }
