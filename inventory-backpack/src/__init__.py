"""
Agent inference framework - async high-performance version

Unified entry: src.agent.orchestrator.Orchestrator
"""

__version__ = "2.0.0"

# Lazy import to avoid circular dependencies
def get_orchestrator():
    from .agent.orchestrator import Orchestrator
    return Orchestrator

__all__ = ["get_orchestrator"]
