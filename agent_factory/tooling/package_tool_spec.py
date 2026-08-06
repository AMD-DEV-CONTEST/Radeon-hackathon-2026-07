from __future__ import annotations

import ast


PACKAGE_TOOLS_DIR = "tools"
PACKAGE_TOOL_SOURCE_FILENAME = "tool.py"
PACKAGE_TOOL_ENTRYPOINT_FUNCTION = "run"


def package_tool_manifest_path(tool_id: str) -> str:
    return f"{PACKAGE_TOOLS_DIR}/{tool_id}/manifest.json"


def package_tool_directory_path(tool_id: str) -> str:
    return f"{PACKAGE_TOOLS_DIR}/{tool_id}"


def package_tool_source_path(tool_id: str) -> str:
    return f"{PACKAGE_TOOLS_DIR}/{tool_id}/{PACKAGE_TOOL_SOURCE_FILENAME}"


def package_tool_entrypoint(tool_id: str) -> str:
    return f"python:{package_tool_source_path(tool_id)}:{PACKAGE_TOOL_ENTRYPOINT_FUNCTION}"


def is_package_tool_entrypoint(tool_id: str, entrypoint: str) -> bool:
    return entrypoint == package_tool_entrypoint(tool_id)


def validate_package_tool_entrypoint(tool_id: str, entrypoint: str) -> None:
    expected = package_tool_entrypoint(tool_id)
    if entrypoint != expected:
        raise ValueError(
            "package tool entrypoint must be canonical: "
            f"{expected}. Package tools are package-local Python files; do not use main, tool:main, "
            "python-import, or other entrypoint protocols."
        )


def validate_package_tool_source(source: str) -> ast.Module:
    tree = ast.parse(source)
    run_defs = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == PACKAGE_TOOL_ENTRYPOINT_FUNCTION]
    async_run_defs = [
        node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == PACKAGE_TOOL_ENTRYPOINT_FUNCTION
    ]
    if async_run_defs:
        raise ValueError("package tool entrypoint run must be a synchronous function, not async def")
    if not run_defs:
        raise ValueError("tool_source must define a top-level synchronous function: run(arguments, resources)")
    args = run_defs[0].args
    positional = [*args.posonlyargs, *args.args]
    if (
        len(positional) != 2
        or positional[0].arg != "arguments"
        or positional[1].arg != "resources"
        or args.vararg is not None
        or args.kwarg is not None
    ):
        raise ValueError("package tool run function must accept exactly: run(arguments, resources)")
    return tree
