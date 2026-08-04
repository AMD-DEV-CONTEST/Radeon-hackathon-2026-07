"""LaunchKart AI 2.0 — Analytics Recorder Agent"""
from __future__ import annotations
import json
from app.agents.base_agent import BaseAgent
from app.agents.analytics.prompts import SYSTEM_PROMPT, TASK_PROMPT
from app.agents.state import LaunchState

class AnalyticsRecorderAgent(BaseAgent):
    name = "analytics_agent"
    description = "Records metrics and performance data"
    phase = 6
    def get_system_prompt(self) -> str: return SYSTEM_PROMPT
    async def execute(self, state: LaunchState) -> LaunchState:
        statuses = state.get("agent_statuses", {})
        gpu_metrics = state.get("gpu_metrics", [])
        total_tokens = state.get("total_tokens", 0)
        # Compute analytics directly
        successful = sum(1 for s in statuses.values() if s.get("status") == "completed")
        failed = sum(1 for s in statuses.values() if s.get("status") == "failed")
        confidences = [s.get("confidence", 0) for s in statuses.values() if s.get("confidence")]
        avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
        durations = [s.get("duration_seconds", 0) for s in statuses.values() if s.get("duration_seconds")]
        total_dur = sum(durations)
        grade = "A" if avg_conf >= 0.8 else "B" if avg_conf >= 0.6 else "C"
        state["total_tokens"] = sum(s.get("tokens_used", 0) for s in statuses.values())
        state["total_inference_time"] = total_dur
        return state
