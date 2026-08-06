from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from typing import List, Optional

# Regexes, not bare substrings, so e.g. "myeval(" or a variable named
# "socket_count" doesn't false-positive - each pattern is anchored to a
# real call/usage boundary.
FORBIDDEN_PATTERNS: List[str] = [
    r"__import__\s*\(",
    r"open\s*\(\s*['\"]\s*/etc",
    r"\bsubprocess\b",
    r"\bos\.system\b",
    r"\bshutil\.",
    r"\brequests\.",
    r"\burllib\b",
    r"\bsocket\.",
    r"\beval\s*\(",
    r"\bexec\s*\(",
    r"\bcompile\s*\(",
    r"\bpickle\.",
    r"\bctypes\b",
    r"\bglobals\s*\(",
    r"\b__builtins__\b",
]

SCENE_NAME_PATTERN = re.compile(r"^Scene\d+$")


@dataclass
class ValidationResult:
    ok: bool
    errors: List[str] = field(default_factory=list)
    scene_class_name: Optional[str] = None

    def __bool__(self) -> bool:
        return self.ok

    def as_message(self) -> str:
        return "OK" if self.ok else "; ".join(self.errors)


def validate_manim_code(code: str, expected_scene_id: Optional[int] = None) -> ValidationResult:
    """Never raises. Any unexpected internal error is itself reported as
    a failed validation rather than propagating - a validator that can
    crash defeats its own purpose."""
    try:
        return _validate_manim_code_impl(code, expected_scene_id)
    except Exception as e:  # last-resort safety net around the validator itself
        return ValidationResult(ok=False, errors=[f"Validator internal error: {e}"])


def _validate_manim_code_impl(code: str, expected_scene_id: Optional[int]) -> ValidationResult:
    errors: List[str] = []

    if not isinstance(code, str) or not code.strip():
        return ValidationResult(ok=False, errors=["Code is empty"])

    # 1. Must parse as valid Python.
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return ValidationResult(ok=False, errors=[f"Syntax error: {e}"])

    # 2. Forbidden patterns - collect all matches, not just the first.
    for pattern in FORBIDDEN_PATTERNS:
        if re.search(pattern, code):
            errors.append(f"Forbidden pattern found: {pattern}")

    # 3. Imports must come only from manim.
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if not alias.name.startswith("manim"):
                    errors.append(f"Non-manim import: {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if node.module is None or not node.module.startswith("manim"):
                errors.append(f"Non-manim import: {node.module}")

    # 4 & 5. Find Scene subclass(es) and check naming.
    scene_classes = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for base in node.bases:
                if isinstance(base, ast.Name) and base.id == "Scene":
                    scene_classes.append(node.name)
                    break

    if not scene_classes:
        errors.append("No class inheriting from Scene found")
    elif len(scene_classes) > 1:
        errors.append(
            f"Expected exactly one Scene subclass, found {len(scene_classes)}: {scene_classes}"
        )

    scene_name = scene_classes[0] if scene_classes else None
    if scene_name and not SCENE_NAME_PATTERN.match(scene_name):
        errors.append(
            f"Scene class name '{scene_name}' does not match required pattern 'Scene{{N}}'"
        )
    if scene_name and expected_scene_id is not None:
        expected_name = f"Scene{expected_scene_id}"
        if scene_name != expected_name:
            errors.append(f"Scene class named '{scene_name}', expected '{expected_name}'")

    return ValidationResult(ok=not errors, errors=errors, scene_class_name=scene_name)


def validate_manim_file(path: str, expected_scene_id: Optional[int] = None) -> ValidationResult:
    """Convenience wrapper: read a .py file from disk and validate it.
    File-not-found / unreadable file is reported as a validation failure,
    not an exception."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            code = f.read()
    except OSError as e:
        return ValidationResult(ok=False, errors=[f"Could not read file '{path}': {e}"])
    return validate_manim_code(code, expected_scene_id=expected_scene_id)


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m tools.manim.validator <scene.py>", file=sys.stderr)
        sys.exit(2)

    result = validate_manim_file(sys.argv[1])
    if result.ok:
        print(f"OK: {result.scene_class_name}")
        sys.exit(0)
    else:
        for err in result.errors:
            print(f"ERROR: {err}", file=sys.stderr)
        sys.exit(1)