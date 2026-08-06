"""Prompt template loading and rendering."""
from pathlib import Path

from app.config import get_resource_path


def load_template(name):
    filename = name if name.endswith(".txt") else f"{name}.txt"
    path = get_resource_path("prompts", Path(filename).name)
    if path.is_file():
        return path.read_text(encoding="utf-8")
    return ""


def render_template(template, variables):
    for key, value in variables.items():
        template = template.replace("{" + key + "}", str(value))
    return template
