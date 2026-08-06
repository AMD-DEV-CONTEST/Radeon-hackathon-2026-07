from __future__ import annotations

from tools.manim.templates._common import scene_class_name
from tools.manim.templates import definition, formula, graph, comparison, code

_TEMPLATES = {
    "definition": definition,
    "formula": formula,
    "graph": graph,
    "comparison": comparison,
    "code": code,
}


def get_template(template_name: str, params: dict, scene_id: int = 1) -> tuple[str, str]:
    """Look up a template by name, generate its scene source code, and
    return (source_code, scene_class_name)."""
    module = _TEMPLATES.get(template_name)
    if module is None:
        available = ", ".join(sorted(_TEMPLATES))
        raise ValueError(f"Unknown template '{template_name}'. Available: {available}")

    source = module.generate(params, scene_id)
    scene_name = scene_class_name(scene_id)
    return source, scene_name
