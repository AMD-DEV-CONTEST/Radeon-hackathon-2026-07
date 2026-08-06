#!/usr/bin/env python3
"""
Example: Developer Copilot
Shows tool use (python_interpreter + calculator) + code reasoning.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.core.llm import LLMEngine
from src.core.agent import Agent
from src.core.memory import MemoryManager
from src.core.tools import ToolRegistry


def main():
    print("=" * 60)
    print("RadeonAgents – Developer Copilot Demo")
    print("=" * 60)

    llm = LLMEngine(
        model_name="microsoft/Phi-3-mini-4k-instruct",
        quantize="4bit",
        device="auto",
    )
    tools = ToolRegistry(enable_python=True, enable_fs=True, enable_web=False)
    memory = MemoryManager()
    agent = Agent(llm, tools, memory, name="CoderAgent", verbose=True)

    goal = (
        "Write a clean Python function `fibonacci(n)` that returns the n-th Fibonacci number "
        "using memoization (lru_cache or a dict). Then use the python_interpreter tool to "
        "verify that fibonacci(10) == 55 and fibonacci(20) == 6765. "
        "Finally explain the time and space complexity."
    )

    print("\nGoal:", goal)
    print("\n" + "-" * 60)
    answer = agent.run(goal, use_planner=True)
    print("\n" + "=" * 60)
    print("FINAL ANSWER:\n")
    print(answer)
    print("=" * 60)


if __name__ == "__main__":
    main()
