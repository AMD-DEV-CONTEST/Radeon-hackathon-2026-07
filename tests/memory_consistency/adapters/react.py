"""React adapter — drives the real ReAct agent (src.agent.core).

Delayed import of `src.agent.core` so the rest of the framework runs on
any machine without the AMD/vLLM stack.

Memory semantics match the agent architecture:
- Within a session, every new turn passes the accumulated
  [user, assistant] history — `run_agent_loop` rebuilds the three-tier
  AgentMemory from it on each call.
- Across sessions (session >= 2) the history is reset but the shared
  memory dir (AGENT_MEMORY_DIR, set by the runner to an isolated temp
  dir per scenario) persists — this exercises Tier-3 semantic memory
  (semantic_memory.json).
"""

from __future__ import annotations


class ReactAdapter:
    """Wraps src.agent.core.run_agent_loop for multi-turn testing."""

    USES_MEMORY = True

    def __init__(self, max_iterations: int = 6):
        self.max_iterations = max_iterations

    def respond(self, prompt, history, scenario_id, session, turn_index):
        from src.agent.core import run_agent_loop  # delayed: needs vLLM/ROCm

        outputs = list(run_agent_loop(prompt, history, max_iterations=self.max_iterations))
        if not outputs:
            return ""
        return outputs[-1]  # final enriched output (or direct reply)
