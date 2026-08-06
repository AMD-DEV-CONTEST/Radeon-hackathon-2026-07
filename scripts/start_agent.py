"""One-click start: Initialize the Agent and enter interactive mode."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


async def main():
    from src.agent.main import InsuranceAgent, interactive_mode

    print("Initializing Insurance RAG Agent...")
    agent = InsuranceAgent()

    try:
        agent.init_rag()
        print("RAG retriever is ready.")
    except FileNotFoundError as e:
        print(f"⚠ {e}")
        print("Running in pure LLM mode.\n")

    await interactive_mode(agent)


if __name__ == "__main__":
    asyncio.run(main())
