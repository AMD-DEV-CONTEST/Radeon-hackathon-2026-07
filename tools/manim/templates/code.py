from __future__ import annotations

from tools.manim.templates._common import (
    optional,
    require,
    safe_str_literal,
    scene_class_name,
)

MAX_TITLE_CHARS = 60
MAX_CODE_CHARS = 800
MAX_LANGUAGE_CHARS = 20


def generate(params: dict, scene_id: int = 1) -> str:
    title = str(require(params, "title"))[:MAX_TITLE_CHARS]
    code = str(require(params, "code"))[:MAX_CODE_CHARS]
    language = str(optional(params, "language", "python"))[:MAX_LANGUAGE_CHARS]

    return f'''from manim import Scene, Code, Paragraph, Text, Write, FadeIn, UP, DOWN, YELLOW, WHITE

TITLE = {safe_str_literal(title)}
CODE = {safe_str_literal(code, max_chars=800)}
LANGUAGE = {safe_str_literal(language)}


def _build_code_block(code_str, language):
    """Try Manim's syntax-highlighted Code mobject first; if pygments is
    missing or the Code API rejects our arguments, fall back to a plain
    monospaced Paragraph so a code scene never crashes the render."""
    try:
        return Code(
            code=code_str,
            language=language,
            background="window",
            font_size=20,
        )
    except Exception:
        try:
            lines = code_str.split("\\n") or [" "]
            return Paragraph(*lines, font_size=22, color=WHITE)
        except Exception:
            return Text(code_str[:200] or " ", font_size=20, color=WHITE)


def _fit(mobject, max_width=13, max_height=5.5):
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

        code_block = _fit(_build_code_block(CODE, LANGUAGE))
        try:
            code_block.next_to(title_text, DOWN, buff=0.6)
        except Exception:
            pass

        try:
            self.play(Write(title_text), run_time=1.0)
            self.wait(0.2)
            self.play(FadeIn(code_block), run_time=1.0)
            self.wait(2.0)
        except Exception:
            self.add(title_text, code_block)
            self.wait(1.5)
'''