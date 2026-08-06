from __future__ import annotations

from typing import List

from tools.manim.templates._common import safe_str_literal, scene_class_name

MAX_HINT_CHARS = 220
MAX_TITLE_CHARS = 60
WRAP_CHARS_PER_LINE = 40


def _wrap(text: str, width: int) -> List[str]:
    words = text.split()
    lines: List[str] = []
    current = ""
    for word in words:
        candidate = (current + " " + word).strip()
        if len(candidate) > width and current:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines or [" "]


def generate_fallback_scene(visual_hint: str, scene_id: int = 1, title: str = "") -> str:
    
    hint = str(visual_hint or "").strip()[:MAX_HINT_CHARS] or "..."
    title = str(title or "").strip()[:MAX_TITLE_CHARS]
    lines = _wrap(hint, WRAP_CHARS_PER_LINE)
    lines_literal = ", ".join(safe_str_literal(line) for line in lines)

    return f'''from manim import Scene, Text, VGroup, FadeIn, UP, DOWN, WHITE, YELLOW

TITLE = {safe_str_literal(title)}
LINES = [{lines_literal}]


class {scene_class_name(scene_id)}(Scene):
    def construct(self):
        mobjects = []

        if TITLE:
            try:
                title_text = Text(TITLE, font_size=40, color=YELLOW)
                title_text.to_edge(UP)
                mobjects.append(title_text)
            except Exception:
                pass

        body = VGroup()
        for line in LINES:
            try:
                body.add(Text(line or " ", font_size=32, color=WHITE))
            except Exception:
                body.add(Text(" ", font_size=32, color=WHITE))
        try:
            body.arrange(DOWN, buff=0.3)
        except Exception:
            pass

        try:
            if body.width > 12:
                body.scale_to_fit_width(12)
            if body.height > 5:
                body.scale_to_fit_height(5)
        except Exception:
            pass

        mobjects.append(body)

        try:
            for mobj in mobjects:
                self.play(FadeIn(mobj), run_time=0.8)
            self.wait(2.0)
        except Exception:
            # Even the animation call is guarded: if literally nothing
            # else works, place the mobjects statically and move on.
            for mobj in mobjects:
                self.add(mobj)
            self.wait(1.5)
'''


if __name__ == "__main__":
    import sys

    hint = sys.argv[1] if len(sys.argv) > 1 else "Fallback test scene"
    print(generate_fallback_scene(hint, scene_id=1, title="Fallback"))