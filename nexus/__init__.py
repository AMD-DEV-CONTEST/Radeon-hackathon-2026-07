"""
NEXUS - The Causal Reality Agent Swarm

A revolutionary AI agent system that maintains a living causal model of your development
reality and simulates temporal branches to predict, debug, and optimize outcomes before
they happen. All running locally on AMD Radeon GPUs with ROCm.
"""

__version__ = "0.1.0"
__author__ = "NEXUS Team"

from nexus.core.config import NexusConfig
from nexus.core.orchestrator import Orchestrator

__all__ = ["NexusConfig", "Orchestrator", "__version__"]
