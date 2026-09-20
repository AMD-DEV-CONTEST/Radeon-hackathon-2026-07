"""ReAct Agent module — Reasoning + Acting loop for the crypto trading agent.

Three-tier memory architecture:
- WorkingMemory: Short-term context (messages, tool calls) — RAM, per-session
- EpisodicMemory: Session episodes (strategies, backtests) — file-backed, per-session
- SemanticMemory: Long-term knowledge (preferences, rules) — file-backed, cross-session
- AgentMemory: Facade combining all three tiers

Exposes:
- run_agent_loop: Generator-based agent loop for Gradio chat UI
- AgentMemory: Three-tier memory facade
- AgentState: Mutable state carried across iterations
- TOOL_REGISTRY: Available tools with descriptions for the LLM
"""

from .core import run_agent_loop, AgentState
from .memory import AgentMemory, WorkingMemory, EpisodicMemory, SemanticMemory
from .tools import TOOL_REGISTRY, execute_tool
from .reward import compute_reward, RewardBreakdown, RewardConfig
from .rl_feedback import RLFeedbackLoop
from .personality import is_trading_intent, build_personality_prompt
