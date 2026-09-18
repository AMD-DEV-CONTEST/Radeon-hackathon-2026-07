"""Session memory retrieval node."""

from buildguard.agent.state import AgentState
from buildguard.schemas.agent import AgentMessage


def retrieve_memory(
    state: AgentState, memories: dict[str, list[AgentMessage]]
) -> dict[str, object]:
    return {"memory_messages": list(memories.get(state["session_id"], []))}
