from __future__ import annotations
import argparse
import json
import sys
from tools.manim.validator import validate_manim_code
from tools.manim.renderer import render_scene


def cmd_validate(args: argparse.Namespace) -> int:
    try:
        with open(args.scene_path, "r", encoding="utf-8") as f:
            source = f.read()
    except OSError as e:
        print(f"Could not read {args.scene_path}: {e}", file=sys.stderr)
        return 1
    result = validate_manim_code(source)
    if result.ok:
        print("OK: scene code is valid")
        return 0
    for error in result.errors:
        print(error, file=sys.stderr)
    return 1


def cmd_render(args: argparse.Namespace) -> int:
    result = render_scene(
        args.scene_path,
        args.scene_name,
        args.output,
        quality=args.quality,
    )
    print(result.to_json())
    return 0 if result.success else 1


def cmd_render_template(args: argparse.Namespace) -> int:
    try:
        params = json.loads(args.params)
    except json.JSONDecodeError as e:
        print(f"Invalid --params JSON: {e}", file=sys.stderr)
        return 1

    try:
        from tools.manim.templates import get_template
    except ImportError as e:
        print(f"Could not load templates module: {e}", file=sys.stderr)
        return 1

    try:
        code, scene_name = get_template(args.template_name, params)
    except Exception as e:
        print(f"Template generation failed: {e}", file=sys.stderr)
        return 1

    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(code)
        temp_path = f.name

    result = render_scene(temp_path, scene_name, args.output, quality="high")
    print(result.to_json())
    return 0 if result.success else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m tools.manim.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser(
        "validate", help="Validate a Manim scene file without rendering it"
    )
    validate_parser.add_argument("scene_path", help="Path to the scene .py file")
    validate_parser.set_defaults(func=cmd_validate)

    render_parser = subparsers.add_parser("render", help="Render a scene")
    render_parser.add_argument("scene_path")
    render_parser.add_argument("scene_name")
    render_parser.add_argument("--output", required=True)
    render_parser.add_argument("--quality", default="high", choices=["low", "medium", "high"])
    render_parser.set_defaults(func=cmd_render)

    template_parser = subparsers.add_parser(
        "render-template", help="Render a scene from a template"
    )
    template_parser.add_argument("template_name")
    template_parser.add_argument("--params", required=True)
    template_parser.add_argument("--output", required=True)
    template_parser.set_defaults(func=cmd_render_template)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())