"""
Core ReAct-style agent with planning, tool use, and memory.
"""

from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional

from .llm import LLMEngine
from .memory import MemoryManager
from .planner import HierarchicalPlanner
from .tools import ToolRegistry

logger = logging.getLogger(__name__)


class Agent:
    """
    Intelligent agent that can:
    - Plan complex goals
    - Reason step-by-step (ReAct)
    - Call tools
    - Maintain memory
    """

    def __init__(
        self,
        llm: LLMEngine,
        tools: ToolRegistry,
        memory: MemoryManager,
        name: str = "RadeonAgent",
        max_iterations: int = 12,
        verbose: bool = True,
    ):
        self.llm = llm
        self.tools = tools
        self.memory = memory
        self.name = name
        self.max_iterations = max_iterations
        self.verbose = verbose
        self.planner = HierarchicalPlanner(llm)

    def run(self, goal: str, use_planner: bool = True, context: str = "") -> str:
        """
        Execute a goal end-to-end.
        Returns the final answer as a string.
        """
        if self.verbose:
            print(f"\n[{self.name}] Goal received: {goal}")

        self.memory.add_message("user", goal)

        # 1. Optional hierarchical planning
        if use_planner:
            plan = self.planner.plan(goal, context=context)
            if self.verbose:
                print(f"[{self.name}] Plan ({len(plan)} steps):")
                for i, step in enumerate(plan, 1):
                    print(f"   {i}. {step}")
        else:
            plan = [goal]

        # 2. Execute each step with ReAct
        final_answer = ""
        for idx, step in enumerate(plan, 1):
            if self.verbose:
                print(f"\n[{self.name}] Executing step {idx}/{len(plan)}: {step}")
            observation = self._react_loop(step)
            final_answer = observation
            self.memory.add_message("assistant", f"Completed step: {step}\nResult: {observation[:400]}")

        # 3. Store summary in long-term memory
        summary = f"Goal: {goal}\nFinal result: {final_answer[:600]}"
        self.memory.store_long_term(summary, metadata={"type": "task_completion", "agent": self.name})

        if self.verbose:
            print(f"\n[{self.name}] Done.")
        return final_answer

    def _react_loop(self, task: str) -> str:
        """
        Classic ReAct loop: Thought → Action → Observation → ... → Final Answer
        """
        system_prompt = self._build_system_prompt()

        messages: List[Dict[str, str]] = [
            {"role": "system", "content": system_prompt},
        ]

        # Inject recent history for continuity
        recent = self.memory.get_history(last_n=6)
        for msg in recent:
            if msg["role"] in ("user", "assistant"):
                messages.append(msg)

        messages.append({"role": "user", "content": f"Current task: {task}"})

        for iteration in range(1, self.max_iterations + 1):
            if self.verbose:
                print(f"   ↳ ReAct iteration {iteration}")

            response = self.llm.generate(messages, max_new_tokens=768, temperature=0.25)
            messages.append({"role": "assistant", "content": response})

            # Check for Final Answer
            if "Final Answer:" in response:
                answer = response.split("Final Answer:")[-1].strip()
                # Clean up any trailing artifacts
                answer = re.split(r"\n(?:Thought|Action):", answer)[0].strip()
                return answer

            # Parse Action + Action Input
            action_match = re.search(r"Action:\s*([a-zA-Z0-9_]+)", response)
            input_match = re.search(
                r"Action Input:\s*(.+?)(?=\n(?:Thought|Action|Observation|Final Answer):|\Z)",
                response,
                re.DOTALL,
            )

            if action_match and input_match:
                tool_name = action_match.group(1).strip()
                tool_input = input_match.group(1).strip().strip("`\"'")

                if self.verbose:
                    print(f"      Action → {tool_name} | Input: {tool_input[:80]}...")

                observation = self.tools.call(tool_name, tool_input)
                obs_msg = f"Observation: {observation}"
                messages.append({"role": "user", "content": obs_msg})

                if self.verbose:
                    print(f"      Observation: {observation[:120]}...")
            else:
                # Model did not produce a proper Action – treat current response as answer
                if self.verbose:
                    print("      No tool call detected – treating response as final.")
                return response.strip()

        return "Reached maximum iterations without a Final Answer."

    def _build_system_prompt(self) -> str:
        tool_desc = self.tools.get_tool_descriptions()
        return f"""You are {self.name}, a highly capable AI agent running locally on an AMD Radeon GPU with ROCm.

You solve tasks using the ReAct pattern. For every step you MUST follow this exact format:

Thought: your reasoning about what to do next
Action: the tool name (must be one of the available tools)
Action Input: the input to the tool
Observation: (this will be provided to you after the tool runs)

When you have enough information to answer the task, output:

Thought: I now know the final answer
Final Answer: the complete answer to the user

Available tools:
{tool_desc}

Important rules:
- Never invent tool results. Always wait for the real Observation.
- Use tools when they help you (especially calculator, python_interpreter, rag_search, read_file).
- Be concise but complete in the Final Answer.
- You are running fully locally – protect user privacy.
"""
