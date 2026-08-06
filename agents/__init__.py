"""
agents/__init__.py - EduCopilot Agent Module
Exposes all agent classes for the multi-agent system.
"""

from agents.planner_agent import PlannerAgent
from agents.tracking_agent import TrackingAgent
from agents.analytics_agent import AnalyticsAgent
from agents.nba_agent import NBAAgent
from agents.content_agent import ContentAgent
from agents.eval_agent import EvalAgent

__all__ = [
    "PlannerAgent",
    "TrackingAgent",
    "AnalyticsAgent",
    "NBAAgent",
    "ContentAgent",
    "EvalAgent",
]
