#!/usr/bin/env python3
"""
Example: Personal Productivity Assistant
Demonstrates planning + reasoning for a realistic daily schedule.
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
    print("RadeonAgents – Productivity Assistant Demo")
    print("=" * 60)

    llm = LLMEngine(
        model_name="microsoft/Phi-3-mini-4k-instruct",
        quantize="4bit",
        device="auto",
    )
    print("LLM loaded:", llm.get_stats())

    tools = ToolRegistry(enable_python=True, enable_fs=True, enable_web=False)
    memory = MemoryManager()
    agent = Agent(llm, tools, memory, name="ProductivityAgent", verbose=True)

    goal = (
        "I am a software engineer. Today I have: "
        "1) a 30-minute standup at 10:00, "
        "2) a 1-hour design review at 14:00, "
        "3) need to finish reviewing a large PR, "
        "4) want to exercise for 45 minutes, "
        "5) and still have time for deep work. "
        "Create a realistic prioritized daily plan from 9:00 to 18:00 with time blocks."
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
