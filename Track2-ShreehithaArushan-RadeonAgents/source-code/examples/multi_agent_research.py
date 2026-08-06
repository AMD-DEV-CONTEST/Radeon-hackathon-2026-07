#!/usr/bin/env python3
"""
Example: Multi-Agent Research Workflow
Demonstrates the orchestrator routing a research-style goal.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.core.llm import LLMEngine
from src.core.tools import ToolRegistry
from src.core.memory import MemoryManager
from src.multi_agent.orchestrator import MultiAgentOrchestrator


def main():
    print("=" * 60)
    print("RadeonAgents – Multi-Agent Research Demo")
    print("=" * 60)

    llm = LLMEngine(
        model_name="microsoft/Phi-3-mini-4k-instruct",
        quantize="4bit",
        device="auto",
    )
    tools = ToolRegistry(enable_python=True, enable_fs=True, enable_web=False)
    memory = MemoryManager()
    orchestrator = MultiAgentOrchestrator(llm, tools, memory, verbose=True)

    goal = (
        "Explain what hierarchical task planning is in the context of AI agents. "
        "Describe the main benefits compared to flat ReAct-style agents, "
        "and give a concrete example of how it would be used for a complex software engineering task."
    )

    print("\nGoal:", goal)
    print("\n" + "-" * 60)
    answer = orchestrator.run(goal)
    print("\n" + "=" * 60)
    print("FINAL ANSWER:\n")
    print(answer)
    print("=" * 60)


if __name__ == "__main__":
    main()
