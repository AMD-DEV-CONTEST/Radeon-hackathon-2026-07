from __future__ import annotations

from tools.manim.templates import comparison, code, definition, formula, graph

TEMPLATES = {
    "definition": definition.generate,
    "formula": formula.generate,
    "graph": graph.generate,
    "comparison": comparison.generate,
    "code": code.generate,
}


def generate_scene(template_name: str, params: dict, scene_id: int = 1) -> str:
    """Dispatch to the right template module and return generated source."""
    if template_name not in TEMPLATES:
        raise ValueError(
            f"Unknown template '{template_name}'. Available: {sorted(TEMPLATES)}"
        )
    return TEMPLATES[template_name](params, scene_id)