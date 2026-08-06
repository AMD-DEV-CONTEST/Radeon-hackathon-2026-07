"""Interactive text-mode demo of the GraphVoice agent."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.graph_agent import GraphVoiceAgent
from database.neo4j_client import Neo4jClient
from utils.logger import setup_logging

logger = setup_logging("demo")


def check_prerequisites() -> bool:
    """Check that Neo4j is reachable."""
    print("Checking Neo4j connection...")
    if not Neo4jClient.health_check():
        print("ERROR: Cannot connect to Neo4j at bolt://localhost:7687")
        print("Make sure: docker compose up -d")
        return False
    print("Connected!")
    return True


def main():
    print("=" * 50)
    print("  GraphVoice - Interactive Text Demo")
    print("  Ask about movies, actors, directors...")
    print("  Type 'quit' or 'exit' to stop")
    print("=" * 50)
    print()

    if not check_prerequisites():
        sys.exit(1)

    print("Initializing agent...")
    agent = GraphVoiceAgent()
    print("Ready!")
    print()

    while True:
        try:
            query = input("You > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not query:
            continue
        if query.lower() in ("quit", "exit", "q"):
            print("Goodbye!")
            break

        try:
            answer = agent.process(query)
            print(f"Bot > {answer}")
            print()
        except Exception as e:
            logger.exception("Error processing query")
            print(f"Bot > 抱歉，出错了：{e}")
            print()


if __name__ == "__main__":
    main()
