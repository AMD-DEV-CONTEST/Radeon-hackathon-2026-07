"""DSPy signatures for Bunker's hand-written prompt templates.

Phase 2 of the DSPy integration: each class below mirrors an existing
hand-written prompt so the DSPy and hand-written behaviors can be A/B
compared. The original prompt strings are kept in comments next to their
signatures.

Class-based signature syntax:
https://dspy.ai/getting-started/class-based-signatures/
"""

import dspy


class TaskPlan(dspy.Signature):
    """Create a step-by-step plan to fulfil the user request using only the available tools."""

    user_request: str = dspy.InputField(desc="The user's query or instruction.")
    available_tools: str = dspy.InputField(
        desc="Newline-separated list of available tools as '- name: description'."
    )
    plan: list[dict] = dspy.OutputField(
        desc=(
            'The plan as a JSON list of steps, each with keys "step" (int), '
            '"action" (str), "tool" (str), and "rationale" (str).'
        )
    )


# Hand-written equivalent kept for A/B comparison (src/agent/planner.py:56):
#   system_prompt = f"""You are an AI task planner. Given a user request and a list of
#   available tools, create a step-by-step plan.
#   Output the plan as a numbered list where each item is a JSON object with the
#   following keys:
#   - "step": The step number (integer)
#   - "action": A short description of the action
#   - "tool": The primary tool to be used for this step
#   - "rationale": Why this step is necessary
#
#   Available Tools:
#   {tool_descriptions}
#
#   Example Output:
#   1. {{"step": 1, "action": "search_db", "tool": "rag_search", "rationale": "..."}}
#   2. {{"step": 2, "action": "summarize", "tool": "summarizer", "rationale": "..."}}
#   """
plan_task = dspy.ChainOfThought(TaskPlan)


class ReActStep(dspy.Signature):
    """Decide the next ReAct step: either call one tool or emit the final answer to the user."""

    user_message: str = dspy.InputField(desc="The user's request.")
    tool_descriptions: str = dspy.InputField(
        desc="Available tools, each with a name, parameters, and purpose."
    )
    observation_context: str = dspy.InputField(
        desc="Prior thoughts, actions, and observations collected so far."
    )
    thought: str = dspy.OutputField(desc="Reasoning about which step to take next.")
    next_action: str = dspy.OutputField(
        desc="The tool name to call, or the literal 'final_answer'."
    )
    action_input: dict = dspy.OutputField(
        desc="JSON parameters for the chosen tool; empty for a final answer."
    )
    final_answer: str = dspy.OutputField(
        desc="The response to show the user when next_action is 'final_answer', else empty."
    )


# Hand-written equivalent kept for A/B comparison (src/agent/react_loop.py:66):
#   SYSTEM_PROMPT = (
#       "You are Bunker, a private AI assistant running entirely on the user's local AMD Radeon GPU.\n"
#       "All your inference, document processing, and memory stays on this machine — nothing leaves.\n"
#       "\n"
#       "You have access to these tools:\n"
#       "{tool_descriptions}\n"
#       "\n"
#       "Use the ReAct format:\n"
#       "Thought: [your reasoning]\n"
#       "Action: [tool_name]\n"
#       "Action Input: [JSON parameters]\n"
#       "Observation: [tool result — filled in by system]\n"
#       "...\n"
#       "Final Answer: [your response to the user]\n"
#       "\n"
#       "Rules:\n"
#       "- Always reason before acting\n"
#       "- Never call a tool more than 3 times in one session\n"
#       "- If a tool fails, try an alternative approach\n"
#       "- Always end with Final Answer"
#   )
# The full ReAct loop is replaced by dspy.ReAct in Phase 3; this Predict
# module models the per-step decision contract only.
react_step = dspy.Predict(ReActStep)
