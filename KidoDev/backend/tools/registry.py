"""
Tool Registry — Functions available to agents during ReAct loops.
Each tool is an async callable that returns structured data.
"""
import os
from typing import Optional, List, Dict, Any

from supabase import create_client


SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")


def _sb():
    if SUPABASE_URL and SUPABASE_KEY:
        return create_client(SUPABASE_URL, SUPABASE_KEY)
    return None


# ─── Tool Definitions ─────────────────────────────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "name": "get_student_profile",
        "description": "Fetches the student's XP, level, badge list, and lesson history from the database.",
        "parameters": ["child_id"],
    },
    {
        "name": "get_workspace_blocks",
        "description": "Returns the list of block types currently in the student's workspace.",
        "parameters": ["workspace_blocks"],
    },
    {
        "name": "get_solution_xml",
        "description": "Fetches the stored correct solution XML for the current lesson.",
        "parameters": ["lesson_id"],
    },
    {
        "name": "get_lesson_details",
        "description": "Fetches the lesson title, objective, and step-by-step instructions.",
        "parameters": ["lesson_id"],
    },
    {
        "name": "get_agent_memory",
        "description": "Retrieves long-term memory observations about this student (weak blocks, learning style, past struggles).",
        "parameters": ["child_id"],
    },
    {
        "name": "get_all_lessons",
        "description": "Returns a list of all available lessons with their class levels and objectives.",
        "parameters": [],
    },
    {
        "name": "get_completed_lessons",
        "description": "Returns all lessons the student has completed with their scores.",
        "parameters": ["child_id"],
    },
]


async def get_student_profile(child_id: str) -> Dict[str, Any]:
    sb = _sb()
    if not sb:
        return {"error": "Database not connected", "child_id": child_id}
    try:
        res = sb.table("child_profiles").select("total_xp, level, badges").eq("id", child_id).maybe_single().execute()
        if res.data:
            return res.data
        # try children table
        res2 = sb.table("children").select("total_xp, level").eq("id", child_id).maybe_single().execute()
        return res2.data or {"total_xp": 0, "level": "Bronze", "badges": []}
    except Exception as e:
        return {"error": str(e)}


async def get_workspace_blocks(workspace_blocks: List[str]) -> Dict[str, Any]:
    return {
        "block_types": workspace_blocks,
        "count": len(workspace_blocks),
        "has_event": any(b.startswith("s_when") for b in workspace_blocks),
        "has_motion": any(b in ["s_move", "s_turn_r", "s_turn_l", "s_goto", "s_glide"] for b in workspace_blocks),
        "has_loop": any(b in ["s_forever", "s_repeat", "s_repeat_until"] for b in workspace_blocks),
        "has_condition": any(b in ["s_if", "s_if_else"] for b in workspace_blocks),
    }


async def get_solution_xml(lesson_id: str) -> Dict[str, Any]:
    sb = _sb()
    if not sb:
        return {"xml": None, "error": "Database not connected"}
    try:
        res = sb.table("tutor_solutions").select("xml, message, tip") \
            .eq("lesson_id", lesson_id) \
            .order("created_at", desc=True) \
            .limit(1) \
            .execute()
        return res.data[0] if res.data else {"xml": None}
    except Exception as e:
        return {"xml": None, "error": str(e)}


async def get_lesson_details(lesson_id: str) -> Dict[str, Any]:
    sb = _sb()
    if not sb:
        return {"error": "Database not connected"}
    try:
        res = sb.table("lessons").select(
            "id, title, objective, agent_tutorial_description, agent_solve_description, steps, class_level"
        ).eq("id", lesson_id).maybe_single().execute()
        return res.data or {"error": "Lesson not found"}
    except Exception as e:
        return {"error": str(e)}


async def get_agent_memory(child_id: str) -> Dict[str, Any]:
    from memory.long_term import load_memory
    return await load_memory(child_id)


DEFAULT_LESSONS = [
    {"id": "L1P1", "title": "First Code Steps", "objective": "Basic sprite motion and sound", "class_level": 1, "order_index": 1},
    {"id": "L1P2", "title": "Loop & Repeat Magic", "objective": "Using repeat loops for efficiency", "class_level": 1, "order_index": 2},
    {"id": "L1P3", "title": "Obstacle Dodge Challenge", "objective": "If/Else conditional sensing", "class_level": 1, "order_index": 3},
    {"id": "L2P1", "title": "Multi-Sprite Animation", "objective": "Event broadcasts and timing delays", "class_level": 2, "order_index": 1},
    {"id": "L2P2", "title": "Catch the Donut Game", "objective": "Variables, scoring and color collision", "class_level": 2, "order_index": 2},
]

async def get_all_lessons() -> List[Dict[str, Any]]:
    sb = _sb()
    if sb:
        try:
            res = sb.table("lessons").select("id, title, objective, class_level, order_index") \
                .order("class_level").order("order_index").execute()
            if res.data:
                return res.data
        except Exception:
            pass
    return DEFAULT_LESSONS


async def get_completed_lessons(child_id: str) -> List[Dict[str, Any]]:
    sb = _sb()
    if not sb:
        return []
    try:
        # Try child_id column first
        res = sb.table("lesson_completions").select("lesson_id, score, badge, completed_at") \
            .eq("child_id", child_id).execute()
        if res.data:
            return res.data
        # Fallback: user_id
        res2 = sb.table("lesson_completions").select("lesson_id, score, badge, completed_at") \
            .eq("user_id", child_id).execute()
        return res2.data or []
    except Exception as e:
        return []


# ─── Dispatch ─────────────────────────────────────────────────────────────────

async def call_tool(tool_name: str, args: Dict[str, Any]) -> Any:
    """Central dispatcher — agents call this to invoke a tool."""
    if tool_name == "get_student_profile":
        return await get_student_profile(args.get("child_id", ""))
    elif tool_name == "get_workspace_blocks":
        return await get_workspace_blocks(args.get("workspace_blocks", []))
    elif tool_name == "get_solution_xml":
        return await get_solution_xml(args.get("lesson_id", ""))
    elif tool_name == "get_lesson_details":
        return await get_lesson_details(args.get("lesson_id", ""))
    elif tool_name == "get_agent_memory":
        return await get_agent_memory(args.get("child_id", ""))
    elif tool_name == "get_all_lessons":
        return await get_all_lessons()
    elif tool_name == "get_completed_lessons":
        return await get_completed_lessons(args.get("child_id", ""))
    else:
        return {"error": f"Unknown tool: {tool_name}"}
