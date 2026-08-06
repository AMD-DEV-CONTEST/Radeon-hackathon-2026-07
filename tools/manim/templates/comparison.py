from __future__ import annotations

from tools.manim.templates._common import (
    optional,
    require,
    safe_str_literal,
    scene_class_name,
)

MAX_TITLE_CHARS = 60
MAX_LABEL_CHARS = 30
MAX_ITEM_CHARS = 60
MAX_ITEMS = 5


def _clean_items(value) -> list:
    if not isinstance(value, list):
        return []
    return [str(v)[:MAX_ITEM_CHARS] for v in value[:MAX_ITEMS] if str(v).strip()]


def generate(params: dict, scene_id: int = 1) -> str:
    title = str(require(params, "title"))[:MAX_TITLE_CHARS]
    left_label = str(require(params, "left_label"))[:MAX_LABEL_CHARS]
    right_label = str(require(params, "right_label"))[:MAX_LABEL_CHARS]
    left_items = _clean_items(optional(params, "left_items", []))
    right_items = _clean_items(optional(params, "right_items", []))

    left_items_literal = ", ".join(safe_str_literal(i) for i in left_items)
    right_items_literal = ", ".join(safe_str_literal(i) for i in right_items)

    return f'''from manim import (
    Scene, VGroup, Text, Line, Write, Create, FadeIn,
    UP, DOWN, LEFT, RIGHT, ORIGIN, YELLOW, BLUE, GREEN, WHITE,
)

TITLE = {safe_str_literal(title)}
LEFT_LABEL = {safe_str_literal(left_label)}
RIGHT_LABEL = {safe_str_literal(right_label)}
LEFT_ITEMS = [{left_items_literal}]
RIGHT_ITEMS = [{right_items_literal}]


def _bullet_column(label, items, color, font_size=28):
    """Build a labeled column of bullet lines; never raises even on an
    empty items list (falls back to a single placeholder line)."""
    label_text = Text(label or " ", font_size=34, color=color, weight="BOLD")
    lines = items if items else [""]
    bullets = VGroup()
    for line in lines:
        text = ("\\u2022 " + line) if line else " "
        try:
            bullets.add(Text(text, font_size=font_size, color=WHITE))
        except Exception:
            bullets.add(Text(" ", font_size=font_size, color=WHITE))
    try:
        bullets.arrange(DOWN, aligned_edge=LEFT, buff=0.35)
    except Exception:
        pass
    column = VGroup(label_text, bullets)
    try:
        column.arrange(DOWN, buff=0.5)
    except Exception:
        pass
    return column


def _fit(mobject, max_width=5.8, max_height=5.0):
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
        title_text = Text(TITLE or " ", font_size=40, color=YELLOW)
        title_text.to_edge(UP)
        try:
            if title_text.width > 13:
                title_text.scale_to_fit_width(13)
        except Exception:
            pass

        left_col = _fit(_bullet_column(LEFT_LABEL, LEFT_ITEMS, BLUE))
        right_col = _fit(_bullet_column(RIGHT_LABEL, RIGHT_ITEMS, GREEN))

        left_col.move_to(ORIGIN + LEFT * 3.3 + DOWN * 0.3)
        right_col.move_to(ORIGIN + RIGHT * 3.3 + DOWN * 0.3)

        try:
            divider = Line(UP * 2.3, DOWN * 2.3, color=WHITE)
            divider.move_to(ORIGIN + DOWN * 0.3)
        except Exception:
            divider = None

        try:
            self.play(Write(title_text), run_time=1.0)
            self.wait(0.2)
            if divider is not None:
                self.play(Create(divider), run_time=0.6)
            self.play(FadeIn(left_col, shift=RIGHT * 0.3), run_time=1.0)
            self.play(FadeIn(right_col, shift=LEFT * 0.3), run_time=1.0)
            self.wait(1.3)
        except Exception:
            self.add(title_text, left_col, right_col)
            if divider is not None:
                self.add(divider)
            self.wait(1.0)
'''