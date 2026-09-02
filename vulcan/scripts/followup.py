"""Two turns where the second only makes sense given the first.

Before conversation context was carried, `vulcan chat` started every turn from
an empty conversation, so "and which one stores memory?" had no referent.
"""
from pathlib import Path

from rich.console import Console

from vulcan.agent import Agent
from vulcan.config import load

console = Console()
agent = Agent(load(), Path(".").resolve(), "planbench")

for q in ("Which module implements the semantic index?",
          "And which one stores memory?"):
    console.print(f"[bold]you>[/bold] {q}")
    console.print(f"[cyan]{agent.run(q)}[/cyan]")

console.print(f"[dim]turn 2 saw {len(agent.history)} prior messages[/dim]")
