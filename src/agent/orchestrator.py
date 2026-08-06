"""App-level orchestrator routing user turns between the DSPy RAG and the agent.

``src/main.py`` and the end-to-end tests drive user messages through this
single entry point instead of calling ``BunkerMultiHopRAG`` or
``DspyReActAgent`` directly. The orchestrator:

* routes each message to the document-question path (RAG) or the tool-using
  path (agent) via a DSPy ``ChainOfThought`` router with a deterministic
  heuristic fallback;
* threads every answered turn back into the conversation history so a
  follow-up referencing turn 1 is answered from context without re-running
  retrieval (https://dspy.ai/tutorials/conversation_history/);
* when a ``SessionStore`` + ``ContextManager`` are wired in, the persisted
  SQLite history is the single source of truth: every turn is written to the
  store and each call threads a bounded context rebuilt from it, so the
  in-memory ``_history`` is only a mirror and never feeds the agent twice.

Routing runs on the local LM (``dspy_runtime.BUNKER_LM``), so the
localhost-only contract is preserved: nothing is sent to a cloud model
(https://dspy.ai/getting-started/classification/).
"""

import logging
from typing import Any, Callable, Dict, List, Literal, Optional

import dspy

logger = logging.getLogger(__name__)

Intent = Literal["rag", "agent"]


class RouteRequest(dspy.Signature):
    """Decide whether a request needs document retrieval or tool execution."""

    user_message: str = dspy.InputField(desc="The user's request, verbatim.")
    available_tools: str = dspy.InputField(
        desc="Newline-separated list of available tools as '- name: description'."
    )
    intent: Literal["rag", "agent"] = dspy.OutputField(
        desc="'rag' to answer from the local documents, 'agent' to use tools."
    )


route_request = dspy.ChainOfThought(RouteRequest)

_AGENT_HINT_KEYWORDS = (
    "draft",
    "email",
    "send",
    "save",
    "write",
    "calendar",
    "schedule",
    "web search",
    "create event",
)


def heuristic_router(user_message: str) -> str:
    """Deterministic fallback: tool-flavoured requests go to the agent."""
    text = user_message.lower()
    if any(keyword in text for keyword in _AGENT_HINT_KEYWORDS):
        return "agent"
    return "rag"


class BunkerOrchestrator:
    """Routes user turns to RAG or the tool agent, threading conversation history.

    Args:
        rag: The ``BunkerMultiHopRAG`` program used for document questions.
        agent: The ``DspyReActAgent`` used for tool-using requests.
        router: Optional ``(user_message) -> "rag"|"agent"`` callable. When
            omitted the orchestrator uses the local ``route_request`` LM router
            with the ``heuristic_router`` fallback.
        available_tools: Tool list text shown to the LM router.
        session_store: Optional ``SessionStore``. When provided (with
            ``context_manager``) every turn is persisted to SQLite and the
            conversation history threaded into each call is rebuilt from the
            store, so ``_history`` never double-feeds the agent.
        context_manager: Optional ``ContextManager`` used to bound the
            persisted history to the configured token limit.
    """

    def __init__(
        self,
        rag: Optional[Any] = None,
        agent: Optional[Any] = None,
        router: Optional[Callable[[str], str]] = None,
        available_tools: str = "",
        session_store: Any = None,
        context_manager: Any = None,
    ):
        self.rag = rag
        self.agent = agent
        self.router = router
        self.available_tools = available_tools
        self.session_store = session_store
        self.context_manager = context_manager
        self._history: List[Dict[str, str]] = []

    @property
    def history(self) -> List[Dict[str, str]]:
        """Copy of the threaded conversation history as {role, content} dicts.

        When a ``session_store`` is wired in this is a flat mirror of the
        turns this instance processed; the actual per-session source of truth
        (and the context fed to the agent) lives in SQLite.
        """
        return list(self._history)

    def clear(self) -> None:
        """Reset the threaded conversation history."""
        self._history = []

    def _context_for(self, session_id: str) -> List[Dict[str, str]]:
        """Return the bounded conversation history for this turn.

        With a ``session_store`` the context is rebuilt from persisted SQLite
        rows (trimmed by ``context_manager`` to the configured token limit) so
        it survives restarts and never duplicates the in-memory mirror.
        Otherwise the in-memory ``_history`` is used (legacy behaviour).
        """
        if self.session_store is not None and session_id:
            if self.context_manager is not None:
                return self.context_manager.build_context(session_id)
            return [
                {"role": m["role"], "content": m["content"]}
                for m in self.session_store.get_messages(session_id)
            ]
        return list(self._history)

    def _persist_turn(self, session_id: str, user_message: str, answer: str) -> None:
        """Write a user/assistant turn to the persisted session (if wired)."""
        if self.session_store is None or not session_id:
            return
        self.session_store.add_message(session_id, "user", user_message)
        self.session_store.add_message(session_id, "assistant", answer)

    def _route(self, user_message: str) -> str:
        """Route a message to 'rag' or 'agent', with a heuristic fallback."""
        if self.router is not None:
            return self.router(user_message)
        try:
            prediction = route_request(
                user_message=user_message,
                available_tools=self.available_tools,
            )
            return str(prediction.intent)
        except Exception as exc:
            logger.warning("LM router failed; using heuristic fallback: %s", exc)
            return heuristic_router(user_message)

    def run(self, user_message: str, session_id: str = "") -> Dict[str, Any]:
        """Run a single user turn through the routed pipeline.

        Args:
            user_message: The user's request.
            session_id: Optional session identifier.

        Returns:
            A dict with ``intent`` and ``response`` plus path-specific details
            (``grounded``/``citations`` for RAG; ``trajectory``/``tool_calls``
            for the agent).
        """
        intent = self._route(user_message)
        result: Dict[str, Any] = {"intent": intent}
        context = self._context_for(session_id)

        if intent == "rag" and self.rag is not None:
            prediction = self.rag(question=user_message)
            answer = prediction.answer
            result.update(
                {
                    "grounded": bool(getattr(prediction, "grounded", False)),
                    "citations": int(getattr(prediction, "citation_count", 0)),
                    "queries": list(getattr(prediction, "queries", [])),
                    "notes": list(getattr(prediction, "notes", [])),
                }
            )
        else:
            # Tool-using path; also the fallback when no RAG program is wired.
            if self.agent is None:
                result["response"] = "No agent is available for this request."
                return result
            result["intent"] = "agent"
            agent_result = self.agent.run(
                user_message,
                session_id=session_id,
                context=context,
            )
            answer = agent_result["response"]
            result.update(
                {
                    "trajectory": agent_result.get("trajectory", {}),
                    "tool_calls": agent_result.get("tool_calls", []),
                }
            )

        self._persist_turn(session_id, user_message, answer)
        self._history.append({"role": "user", "content": user_message})
        self._history.append({"role": "assistant", "content": answer})
        result["response"] = answer
        return result
