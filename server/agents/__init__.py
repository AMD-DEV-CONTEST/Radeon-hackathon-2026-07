"""Agent architecture package."""

from agents.base import AgentProtocol, BaseAgent
from agents.behavioral_agent import BehavioralAgent
from agents.dependencies import (
    AgentRegistryDep,
    BehavioralAgentDep,
    EvaluationAgentDep,
    FactCheckerAgentDep,
    HiringAgentDep,
    PlannerAgentDep,
    ResumeAgentDep,
    TechnicalAgentDep,
    get_behavioral_agent,
    get_evaluation_agent,
    get_fact_checker_agent,
    get_hiring_agent,
    get_planner_agent,
    get_registry,
    get_resume_agent,
    get_technical_agent,
)
from agents.evaluation_agent import EvaluationAgent
from agents.fact_checker_agent import FactCheckerAgent
from agents.hiring_agent import HiringAgent
from agents.planner_agent import PlannerAgent
from agents.registry import AgentRegistry, get_agent_registry, reset_agent_registry
from agents.resume_agent import ResumeAgent
from agents.technical_agent import TechnicalAgent
from agents.types import AgentContext, AgentResult, AgentStatus, AgentType

__all__ = [
    "AgentContext",
    "AgentProtocol",
    "AgentRegistry",
    "AgentRegistryDep",
    "AgentResult",
    "AgentStatus",
    "AgentType",
    "BaseAgent",
    "BehavioralAgent",
    "BehavioralAgentDep",
    "EvaluationAgent",
    "EvaluationAgentDep",
    "FactCheckerAgent",
    "FactCheckerAgentDep",
    "HiringAgent",
    "HiringAgentDep",
    "PlannerAgent",
    "PlannerAgentDep",
    "ResumeAgent",
    "ResumeAgentDep",
    "TechnicalAgent",
    "TechnicalAgentDep",
    "get_agent_registry",
    "get_behavioral_agent",
    "get_evaluation_agent",
    "get_fact_checker_agent",
    "get_hiring_agent",
    "get_planner_agent",
    "get_registry",
    "get_resume_agent",
    "get_technical_agent",
    "reset_agent_registry",
]
