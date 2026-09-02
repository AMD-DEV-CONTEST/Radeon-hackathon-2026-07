"""FastAPI-friendly dependency injection providers for agents."""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import Depends

from agents.base import BaseAgent
from agents.behavioral_agent import BehavioralAgent
from agents.evaluation_agent import EvaluationAgent
from agents.fact_checker_agent import FactCheckerAgent
from agents.hiring_agent import HiringAgent
from agents.planner_agent import PlannerAgent
from agents.registry import AgentRegistry, get_agent_registry
from agents.resume_agent import ResumeAgent
from agents.technical_agent import TechnicalAgent
from agents.types import AgentType


def get_registry() -> AgentRegistry:
    return get_agent_registry()


def get_agent(agent_type: AgentType) -> BaseAgent:
    return get_agent_registry().get(agent_type)


def get_resume_agent() -> ResumeAgent:
    return cast(ResumeAgent, get_agent(AgentType.RESUME))


def get_planner_agent() -> PlannerAgent:
    return cast(PlannerAgent, get_agent(AgentType.PLANNER))


def get_technical_agent() -> TechnicalAgent:
    return cast(TechnicalAgent, get_agent(AgentType.TECHNICAL))


def get_behavioral_agent() -> BehavioralAgent:
    return cast(BehavioralAgent, get_agent(AgentType.BEHAVIORAL))


def get_fact_checker_agent() -> FactCheckerAgent:
    return cast(FactCheckerAgent, get_agent(AgentType.FACT_CHECKER))


def get_evaluation_agent() -> EvaluationAgent:
    return cast(EvaluationAgent, get_agent(AgentType.EVALUATION))


def get_hiring_agent() -> HiringAgent:
    return cast(HiringAgent, get_agent(AgentType.HIRING))


AgentRegistryDep = Annotated[AgentRegistry, Depends(get_registry)]
ResumeAgentDep = Annotated[ResumeAgent, Depends(get_resume_agent)]
PlannerAgentDep = Annotated[PlannerAgent, Depends(get_planner_agent)]
TechnicalAgentDep = Annotated[TechnicalAgent, Depends(get_technical_agent)]
BehavioralAgentDep = Annotated[BehavioralAgent, Depends(get_behavioral_agent)]
FactCheckerAgentDep = Annotated[FactCheckerAgent, Depends(get_fact_checker_agent)]
EvaluationAgentDep = Annotated[EvaluationAgent, Depends(get_evaluation_agent)]
HiringAgentDep = Annotated[HiringAgent, Depends(get_hiring_agent)]
