from __future__ import annotations

from tools.manim.templates._common import (
    optional,
    require,
    safe_str_literal,
    scene_class_name,
)

MAX_TITLE_CHARS = 60
MAX_FORMULA_CHARS = 120
MAX_CONCEPT_CHARS = 160


def generate(params: dict, scene_id: int = 1) -> str:
    title = str(require(params, "title"))[:MAX_TITLE_CHARS]
    formula = str(optional(params, "formula", ""))[:MAX_FORMULA_CHARS]
    key_concept = str(optional(params, "key_concept", ""))[:MAX_CONCEPT_CHARS]

    return f'''from manim import Scene, Text, MathTex, Write, FadeIn, ORIGIN, DOWN, UP, BLUE, YELLOW, WHITE

TITLE = {safe_str_literal(title)}
FORMULA = {safe_str_literal(formula)}
KEY_CONCEPT = {safe_str_literal(key_concept)}


def _safe_formula(tex, font_size=40):
    """Compile as MathTex; fall back to plain Text if the LaTeX is bad
    or the LaTeX toolchain fails, so this can never crash the render."""
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
        title_text = Text(TITLE or " ", font_size=44, color=YELLOW)
        title_text.to_edge(UP)
        _fit(title_text, max_width=13, max_height=1.0)

        formula_mobj = _fit(_safe_formula(FORMULA))
        try:
            formula_mobj.set_color(BLUE)
        except Exception:
            pass
        formula_mobj.move_to(ORIGIN)

        show_concept = bool(KEY_CONCEPT.strip())
        concept_text = Text(KEY_CONCEPT or " ", font_size=30, color=WHITE)
        concept_text.next_to(formula_mobj, DOWN, buff=0.8)
        _fit(concept_text, max_width=13, max_height=1.2)

        try:
            self.play(Write(title_text), run_time=1.0)
            self.wait(0.3)
            self.play(FadeIn(formula_mobj, shift=UP * 0.3), run_time=1.2)
            self.wait(0.5)
            if show_concept:
                self.play(Write(concept_text), run_time=1.2)
            self.wait(1.2)
        except Exception:
            # Absolute last resort: never let an animation error kill the
            # whole render job - show a static frame with what we have.
            self.add(title_text, formula_mobj)
            if show_concept:
                self.add(concept_text)
            self.wait(1.0)
'''