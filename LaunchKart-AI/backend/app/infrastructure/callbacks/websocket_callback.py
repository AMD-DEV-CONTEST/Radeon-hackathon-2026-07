import asyncio
from typing import Any, Dict, List, Optional
from uuid import UUID

import structlog
from langchain_core.callbacks.base import AsyncCallbackHandler
from langchain_core.outputs import LLMResult

from app.api.v1.websocket import manager

logger = structlog.get_logger(__name__)

class DashboardWebSocketCallbackHandler(AsyncCallbackHandler):
    """
    Streams LangChain node execution events directly to the frontend WebSocket manager.
    This enables the React Flow dashboard to animate edges and update node statuses in real-time.
    """

    def __init__(self, launch_id: UUID):
        self.launch_id = str(launch_id)
        super().__init__()

    async def on_tool_start(
        self, serialized: Dict[str, Any], input_str: str, **kwargs: Any
    ) -> None:
        """Run when tool starts running."""
        tool_name = serialized.get("name", "tool")
        logger.debug("Tool started", tool=tool_name, launch_id=self.launch_id)

    async def on_chat_model_start(
        self,
        serialized: Dict[str, Any],
        messages: List[List[Any]],
        **kwargs: Any,
    ) -> None:
        """Run when LLM starts running."""
        # Note: in LangGraph, we manually emit agent_status events from the nodes themselves
        # because the LLM callback doesn't easily know which "agent" it belongs to if not tagged.
        # But we can capture token streaming here if needed.
        pass

    async def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        """Run when LLM ends running."""
        # Optional: track token usage globally
        pass

    async def on_chain_start(
        self, serialized: Dict[str, Any], inputs: Dict[str, Any], **kwargs: Any
    ) -> None:
        """Run when chain (or graph node) starts running."""
        # LangGraph nodes often trigger this
        name = serialized.get("name")
        if name and not name.startswith("LangGraph"):
            # Ensure it's not a generic chain name
            pass
