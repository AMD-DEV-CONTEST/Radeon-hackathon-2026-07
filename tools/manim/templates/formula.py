from __future__ import annotations

from tools.manim.templates._common import require, safe_str_literal, scene_class_name

MIN_STEPS = 2
MAX_STEPS = 12
MAX_TITLE_CHARS = 60
MAX_STEP_CHARS = 120


def generate(params: dict, scene_id: int = 1) -> str:
    title = require(params, "title")
    steps = params.get("steps")

    if not isinstance(steps, list) or len(steps) < MIN_STEPS:
        raise ValueError(
            f"Missing required parameter: 'steps' (list of at least {MIN_STEPS} LaTeX strings)"
        )

    # Defensive caps: never let a runaway list/length reach LaTeX or manim.
    steps = [str(s)[:MAX_STEP_CHARS] for s in steps[:MAX_STEPS]]
    title = str(title)[:MAX_TITLE_CHARS]

    steps_literal = ", ".join(safe_str_literal(s) for s in steps)

    return f'''from manim import Scene, Text, MathTex, Write, Transform, ORIGIN, BOLD, UP

TITLE = {safe_str_literal(title)}
STEPS = [{steps_literal}]


def _safe_formula(tex, font_size=48):
    """Compile as MathTex; fall back to plain Text if the LaTeX is bad
    or the LaTeX toolchain fails, so a bad step can never crash the render."""
    tex = tex if tex else " "
    try:
        return MathTex(tex, font_size=font_size)
    except Exception:
        return Text(tex, font_size=font_size)


def _fit(mobject, max_width=12.5, max_height=2.5):
    """Scale a mobject down if it would overflow the safe layout box."""
    try:
        if mobject.width > max_width:
            mobject.scale_to_fit_width(max_width)
        if mobject.height > max_height:
            mobject.scale_to_fit_height(max_height)
    except Exception:
        pass
    return mobject


class {scene_class_name(scene_id)}(Scene):
    def construct(self):
        title_text = Text(TITLE or " ", font_size=40, weight=BOLD)
        title_text.to_edge(UP)
        _fit(title_text, max_width=13, max_height=1.0)
        try:
            self.play(Write(title_text), run_time=1)
        except Exception:
            self.add(title_text)

        current = _fit(_safe_formula(STEPS[0]))
        current.move_to(ORIGIN)
        try:
            self.play(Write(current), run_time=1.5)
        except Exception:
            self.add(current)
        self.wait(1)

        for step_tex in STEPS[1:]:
            next_step = _fit(_safe_formula(step_tex))
            next_step.move_to(ORIGIN)
            try:
                self.play(Transform(current, next_step), run_time=1.5)
            except Exception:
                # If the morph itself fails for any reason, swap statically
                # instead of aborting the whole scene.
                self.remove(current)
                self.add(next_step)
            current = next_step
            self.wait(1)

        self.wait(1)
'''