"""Prompt asset loader."""

from pathlib import Path

PROMPT_ROOT = Path(__file__).resolve().parent.parent / "prompts"


def load_prompt(name: str) -> str:
    path = (PROMPT_ROOT / name).resolve()
    if path.parent != PROMPT_ROOT.resolve():
        raise ValueError(f"Invalid prompt name: {name}")
    return path.read_text(encoding="utf-8").strip()
