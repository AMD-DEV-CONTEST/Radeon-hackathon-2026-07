"""Persist visible conversation messages to session memory."""

from buildguard.agent.state import AgentState
from buildguard.schemas.agent import AgentMessage


def save_memory(state: AgentState, memories: dict[str, list[AgentMessage]]) -> dict[str, object]:
    history = memories.setdefault(state["session_id"], [])
    history.extend(
        [
            AgentMessage(session_id=state["session_id"], role="user", content=state["user_query"]),
            AgentMessage(
                session_id=state["session_id"],
                role="assistant",
                content=state["final_response"] or "No response generated.",
            ),
        ]
    )
    return {"memory_messages": list(history)}
