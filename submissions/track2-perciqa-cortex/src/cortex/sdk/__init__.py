"""Perciqa Cortex agent SDK — thin façade over cortex.node.CortexNode."""

from cortex.sdk.client import CortexClient
from cortex.sdk.exceptions import (
    CortexPublishError,
    CortexQueryError,
    CortexSDKError,
    map_node_error,
)
from cortex.sdk.llm import ScriptedReasoner, agent_step, vLLMClient
from cortex.sdk.provenance import ProvenanceHelpers

# Optional framework adapters — only available when [sdk] extras are installed.
# Guard with try/except so base imports succeed in CI and lightweight envs.
try:
    from cortex.sdk.agent import CortexAgent
    from cortex.sdk.langchain_adapter import CortexPublishTool, CortexRetriever
except ImportError:
    CortexPublishTool = None  # type: ignore[assignment,misc]
    CortexRetriever = None  # type: ignore[assignment,misc]
    CortexAgent = None  # type: ignore[assignment,misc]

try:
    from cortex.sdk.llamaindex_adapter import CortexReader
except ImportError:
    CortexReader = None  # type: ignore[assignment,misc]

__all__ = [
    "CortexAgent",
    "CortexClient",
    "CortexPublishError",
    "CortexPublishTool",
    "CortexQueryError",
    "CortexReader",
    "CortexRetriever",
    "CortexSDKError",
    "ProvenanceHelpers",
    "ScriptedReasoner",
    "agent_step",
    "map_node_error",
    "vLLMClient",
]
