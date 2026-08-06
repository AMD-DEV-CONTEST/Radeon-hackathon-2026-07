"""Bunker's agent loop rebuilt on :class:`dspy.ReAct`.

The hand-written ReAct loop (``src/agent/react_loop.py``) is kept intact for
A/B comparison; this module is the DSPy-native replacement. Conversation
history is threaded through a ``dspy.History`` input field instead of
heuristic SQLite trimming (https://dspy.ai/tutorials/conversation_history/),
and the existing ``TaskPlanner`` is kept as a preceding
``dspy.ChainOfThought`` module whose plan feeds the ReAct signature.

ReAct tool-call format (next_thought / next_tool_name / next_tool_args):
https://dspy.ai/getting-started/react-and-tools/
https://dspy.ai/api/modules/ReAct/
"""

import logging
from typing import Any, Dict, List, Optional

import dspy

from ..tools.dspy_tools import build_bunker_tools
from .permission_controller import PermissionController
from .signatures import plan_task

logger = logging.getLogger(__name__)

_FALLBACK_PLAN: List[Dict[str, Any]] = [
    {
        "step": 1,
        "action": "direct_execution",
        "tool": "None",
        "rationale": "Fallback to direct execution.",
    }
]


class BunkerAgentSignature(dspy.Signature):
    """Fulfil the user's request using only the provided tools. You are Bunker, a private AI assistant running entirely on the user's local AMD Radeon GPU; all inference, document processing, and memory stay on this machine."""

    user_message: str = dspy.InputField(desc="The user's request, verbatim.")
    history: dspy.History = dspy.InputField(
        desc="Previous conversation turns as a list of {user_message, answer} dicts."
    )
    plan: list[dict] = dspy.InputField(
        desc="The step-by-step plan to follow; each step has step, action, tool, rationale."
    )
    answer: str = dspy.OutputField(desc="The final answer to show the user.")


class DspyReActAgent:
    """Tool-using agent built on ``dspy.ReAct(BunkerAgentSignature, tools=[...])``."""

    def __init__(
        self,
        permission_controller: Optional[PermissionController] = None,
        base_dir: str = "./data/documents",
        max_iters: int = 15,
        tool_registry: Any = None,
        data_flow_monitor: Any = None,
        audit_logger: Any = None,
    ):
        """Initialize the DSPy ReAct agent.

        Args:
            permission_controller: Gates dangerous tool calls from inside the
                tool bodies. Defaults to a fresh PermissionController.
            base_dir: The allowed base directory for file operations.
            max_iters: Maximum ReAct iterations (the ReAct default is 20).
            tool_registry: Optional existing registry, retained for callers
                that also need the MCP-style registry metadata.
            data_flow_monitor: Optional DataFlowMonitor forwarded to the tool
                wrappers so every tool execution records a local-only event.
            audit_logger: Optional AuditLogger forwarded to the tool wrappers
                so every tool execution is audit-logged.
        """
        self.permission_controller = permission_controller or PermissionController()
        self.tools = build_bunker_tools(
            self.permission_controller,
            base_dir=base_dir,
            data_flow_monitor=data_flow_monitor,
            audit_logger=audit_logger,
        )
        self.tool_registry = tool_registry
        self.max_iters = max_iters
        self.agent = dspy.ReAct(BunkerAgentSignature, tools=self.tools, max_iters=max_iters)

    @property
    def tool_names(self) -> List[str]:
        """The tool names exposed to the LM."""
        return [tool.name for tool in self.tools]

    def _available_tools_text(self) -> str:
        """Format the tool list for the planner prompt."""
        return "\n".join(f"- {tool.name}: {tool.desc}" for tool in self.tools)

    @staticmethod
    def _build_history(context: Optional[List[Dict]]) -> dspy.History:
        """Convert the legacy {role, content} context list into dspy.History."""
        messages: List[Dict[str, Any]] = []
        for entry in context or []:
            role = entry.get("role")
            content = entry.get("content", "")
            if role == "user":
                messages.append({"user_message": content})
            elif role == "assistant":
                messages.append({"answer": content})
        return dspy.History(messages=messages)

    @staticmethod
    def _tool_calls_from_trajectory(trajectory: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract the ordered tool calls from a ReAct trajectory."""
        calls: List[Dict[str, Any]] = []
        for key, value in trajectory.items():
            if key.startswith("tool_name_"):
                idx = key.rsplit("_", 1)[-1]
                calls.append(
                    {
                        "tool": value,
                        "args": trajectory.get(f"tool_args_{idx}", {}),
                        "thought": trajectory.get(f"thought_{idx}", ""),
                        "observation": trajectory.get(f"observation_{idx}", ""),
                    }
                )
        return calls

    def _make_plan(self, user_request: str) -> List[Dict[str, Any]]:
        """Run the preceding planner; fall back to a single-step plan."""
        try:
            prediction = plan_task(
                user_request=user_request,
                available_tools=self._available_tools_text(),
            )
            if prediction.plan:
                return prediction.plan
        except Exception as exc:
            logger.warning("Planner failed, falling back to single-step plan: %s", exc)
        return list(_FALLBACK_PLAN)

    def run(
        self,
        user_message: str,
        session_id: str = "",
        context: Optional[List[Dict]] = None,
    ) -> Dict[str, Any]:
        """Run the full ReAct loop for a single user turn.

        Args:
            user_message: The user's input.
            session_id: Optional session ID (retained for call compatibility).
            context: Previous conversation as a list of {role, content} dicts.

        Returns:
            A result dict with keys: status, response, plan, trajectory,
            tool_calls, and iterations.
        """
        plan = self._make_plan(user_message)
        history = self._build_history(context)

        try:
            prediction = self.agent(user_message=user_message, history=history, plan=plan)
        except Exception as exc:
            # Graceful degradation: malformed LM output must never crash the
            # caller (e.g. the Gradio UI) with a raw parsing exception.
            logger.error(
                "Agent ReAct loop failed for %r; returning generic fallback: %s",
                user_message,
                exc,
            )
            return {
                "status": "error",
                "response": (
                    "I couldn't process that request. The local model returned an "
                    "unexpected response; please try again."
                ),
                "plan": plan,
                "trajectory": {},
                "tool_calls": [],
                "iterations": 0,
            }

        return {
            "status": "success",
            "response": prediction.answer,
            "plan": plan,
            "trajectory": prediction.trajectory,
            "tool_calls": self._tool_calls_from_trajectory(prediction.trajectory),
            "iterations": len([k for k in prediction.trajectory if k.startswith("thought_")]),
        }
