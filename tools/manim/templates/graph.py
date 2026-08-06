from __future__ import annotations

import ast
import math

from tools.manim.templates._common import (
    optional,
    require,
    safe_number,
    safe_str_literal,
    scene_class_name,
)

MAX_TITLE_CHARS = 60
MAX_EXPR_CHARS = 120
MAX_LABEL_CHARS = 12
SAMPLE_POINTS = 60

_ALLOWED_CALLS = {
    "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "sqrt": math.sqrt, "exp": math.exp, "log": math.log, "abs": abs,
}


def _compute(node, x):
    """Whitelist-only AST evaluator. No eval()/exec() anywhere - a
    hallucinated or malicious expression can never run arbitrary code,
    it just fails the walk and the caller falls back to 0.0."""
    if isinstance(node, ast.Expression):
        return _compute(node.body, x)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError("non-numeric constant")
    if isinstance(node, ast.Name):
        if node.id == "x":
            return x
        raise ValueError(f"unknown variable: {node.id}")
    if isinstance(node, ast.BinOp):
        left, right = _compute(node.left, x), _compute(node.right, x)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            return left / right if right != 0 else 0.0
        if isinstance(node.op, ast.Pow):
            return left ** right
        if isinstance(node.op, ast.Mod):
            return left % right if right != 0 else 0.0
        raise ValueError("unsupported operator")
    if isinstance(node, ast.UnaryOp):
        val = _compute(node.operand, x)
        if isinstance(node.op, ast.USub):
            return -val
        if isinstance(node.op, ast.UAdd):
            return val
        raise ValueError("unsupported unary operator")
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name) and node.func.id in _ALLOWED_CALLS:
            args = [_compute(a, x) for a in node.args]
            return _ALLOWED_CALLS[node.func.id](*args)
        raise ValueError("disallowed function call")
    raise ValueError(f"disallowed expression element: {type(node).__name__}")


def _safe_function(expr_str: str):
    try:
        tree = ast.parse(expr_str, mode="eval")
    except Exception:
        tree = None

    def f(x):
        if tree is None:
            return 0.0
        try:
            return float(_compute(tree, x))
        except Exception:
            return 0.0

    return f


def _sample_points(expr_str: str, x_min: float, x_max: float, n: int = SAMPLE_POINTS):
    f = _safe_function(expr_str)
    if x_max <= x_min:
        x_min, x_max = -5.0, 5.0
    step = (x_max - x_min) / max(n - 1, 1)
    points = []
    for i in range(n):
        x = x_min + i * step
        y = f(x)
        if y != y or abs(y) > 1e6:  # NaN, or a blown-up value near an asymptote
            y = 0.0
        points.append((round(x, 4), round(y, 4)))
    return points


def generate(params: dict, scene_id: int = 1) -> str:
    title = str(require(params, "title"))[:MAX_TITLE_CHARS]
    expression = str(require(params, "expression"))[:MAX_EXPR_CHARS]

    x_min = safe_number(optional(params, "x_min", -5), -5)
    x_max = safe_number(optional(params, "x_max", 5), 5)
    y_min = safe_number(optional(params, "y_min", -5), -5)
    y_max = safe_number(optional(params, "y_max", 5), 5)
    if x_max <= x_min:
        x_min, x_max = -5.0, 5.0
    if y_max <= y_min:
        y_min, y_max = -5.0, 5.0

    x_label = str(optional(params, "x_label", "x"))[:MAX_LABEL_CHARS]
    y_label = str(optional(params, "y_label", "y"))[:MAX_LABEL_CHARS]

    points = _sample_points(expression, x_min, x_max)
    points_literal = repr(points)

    return f'''from manim import Scene, Axes, Text, Line, VGroup, Write, Create, UP, YELLOW, BLUE

TITLE = {safe_str_literal(title)}
X_MIN, X_MAX = {x_min}, {x_max}
Y_MIN, Y_MAX = {y_min}, {y_max}
X_LABEL = {safe_str_literal(x_label)}
Y_LABEL = {safe_str_literal(y_label)}
POINTS = {points_literal}


class {scene_class_name(scene_id)}(Scene):
    def construct(self):
        title_text = Text(TITLE or " ", font_size=40, color=YELLOW)
        title_text.to_edge(UP)
        try:
            if title_text.width > 13:
                title_text.scale_to_fit_width(13)
        except Exception:
            pass

        x_step = max((X_MAX - X_MIN) / 8, 0.1)
        y_step = max((Y_MAX - Y_MIN) / 8, 0.1)

        axes = None
        try:
            axes = Axes(
                x_range=[X_MIN, X_MAX, x_step],
                y_range=[Y_MIN, Y_MAX, y_step],
                x_length=10,
                y_length=5.5,
            )
            axes.move_to([0, -0.3, 0])
        except Exception:
            axes = None

        x_lbl = None
        y_lbl = None
        if axes is not None:
            try:
                x_lbl = axes.get_x_axis_label(X_LABEL)
            except Exception:
                x_lbl = None
            try:
                y_lbl = axes.get_y_axis_label(Y_LABEL)
            except Exception:
                y_lbl = None

        curve = None
        if axes is not None and POINTS:
            try:
                screen_points = [axes.coords_to_point(x, y) for x, y in POINTS]
                segments = VGroup()
                for a, b in zip(screen_points, screen_points[1:]):
                    segments.add(Line(a, b, color=BLUE))
                curve = segments
            except Exception:
                curve = None

        try:
            self.play(Write(title_text), run_time=1.0)
            if axes is not None:
                self.play(Create(axes), run_time=1.2)
                for lbl in (x_lbl, y_lbl):
                    if lbl is not None:
                        self.play(Write(lbl), run_time=0.4)
                if curve is not None:
                    self.play(Create(curve), run_time=1.5)
            self.wait(1.2)
        except Exception:
            self.add(title_text)
            for mobj in (axes, curve, x_lbl, y_lbl):
                if mobj is not None:
                    self.add(mobj)
            self.wait(1.0)
'''