from typing import TypedDict, Optional, List, Dict, Any
from pydantic import BaseModel, Field


# Pydantic models — for structured output from LLM

class Scene(BaseModel):
    id: int = Field(description="Scene ID, starting from 1")
    title: str = Field(description="Short title for the scene (3-5 words)")
    narration: str = Field(
        description="Text spoken for voiceover (1-3 sentences, conversational tone)"
    )
    visual_hint: str = Field(
        description="Detailed description of what should appear on screen (formulas, diagrams, text, animations)"
    )
    key_concepts: List[str] = Field(
        default_factory=list,
        description="Main concepts covered in this scene (for reference, not shown in video)"
    )


class ScriptOutput(BaseModel):
    title: str = Field(description="Title of the video")
    estimated_duration_sec: int = Field(
        description="Estimated total duration in seconds"
    )
    scenes: List[Scene] = Field(
        description="3-5 scenes that form the video"
    )
    thought_process: Optional[str] = Field(
        default=None,
        description="Internal reasoning of the LLM: Use this to calculate word counts, durations, and scene limits before finalizing scenes",
    )


# LangGraph state — TypedDict, shared between nodes

class AgentState(TypedDict):
    # The state of the agent. All nodes receive and return this structure.
    
    # ─── INPUT ───────────────────────────────────────────────────
    user_query: str
    conversation_id: Optional[str]
    kb_id: Optional[str]
    
    # ─── PLAN ────────────────────────────────────────────────────
    plan: Optional[List[Dict[str, Any]]]
    current_plan_step: int
    
    # ─── RESEARCH ────────────────────────────────────────────────
    research_notes: List[str]
    
    # ─── SCRIPT ──────────────────────────────────────────────────
    script: Optional[Dict[str, Any]]
    scenes: List[Dict[str, Any]]
    current_scene_idx: int
    
    # ─── CODE GENERATION ─────────────────────────────────────────
    scene_codes: Dict[int, str]          # scene_id -> Python code
    needs_retry: bool
    last_error: Optional[str]
    retries_for_current_scene: int
    used_fallback: bool
    
    # ─── RENDERING ───────────────────────────────────────────────
    scene_videos: Dict[int, str]         # scene_id -> video file path
    audio_tracks: Dict[int, Dict[str, Any]]         # scene_id -> { "path": audio file path, "duration_sec": duration }
    
    # ─── FINAL OUTPUT ────────────────────────────────────────────
    final_video_path: Optional[str]
    
    # ─── META ────────────────────────────────────────────────────
    errors: List[str]
    started_at: Optional[str]


def create_initial_state(
    user_query: str,
    conversation_id: Optional[str] = None,
    kb_id: Optional[str] = None,
) -> AgentState:
    from datetime import datetime, timezone
    
    return {
        "user_query": user_query,
        "conversation_id": conversation_id,
        "kb_id": kb_id,
        
        "plan": None,
        "current_plan_step": 0,
        
        "research_notes": [],
        
        "script": None,
        "scenes": [],
        "current_scene_idx": 0,
        
        "scene_codes": {},
        "needs_retry": False,
        "last_error": None,
        "retries_for_current_scene": 0,
        "used_fallback": False,
        
        "scene_videos": {},
        "audio_tracks": {},
        "final_video_path": None,
        
        "errors": [],
        "started_at": datetime.now(timezone.utc).isoformat(),
    }