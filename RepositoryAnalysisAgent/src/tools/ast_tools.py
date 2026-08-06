"""AST tools: get_symbols and find_references."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .registry import ToolRegistry

if TYPE_CHECKING:
    from ..config import Config
    from ..index.indexer import Indexer


def register_ast_tools(
    registry: ToolRegistry,
    config: Config,
    indexer: Indexer,
) -> None:
    """Register get_symbols and find_references tools."""

    async def get_symbols(**kwargs) -> str:
        """Extract functions, classes, and methods from a Python file."""
        path = kwargs.get("path") or kwargs.get("file_path") or kwargs.get("filepath") or ""
        if not path:
            return "Error: 'path' parameter is required"

        root = config.repo_root
        target = (root / path).resolve()
        if not str(target).startswith(str(root)):
            return f"Path '{path}' is outside the repository root"

        if not target.exists():
            return f"File not found: {path}"

        symbols = indexer.parser.get_symbols(target)
        if not symbols:
            return f"No symbols found in {path} (may not be a Python file)."

        lines = [f"Symbols in {path} ({len(symbols)}):\n"]
        for sym in symbols:
            param_str = f" {sym.params}" if sym.params else ""
            lines.append(
                f"  L{sym.start_line:4d}-{sym.end_line:<4d}  "
                f"{sym.kind:8s}  {sym.name}{param_str}"
            )
        return "\n".join(lines)

    registry.register(
        name="get_symbols",
        description=(
            "Extract functions, classes, and methods from a Python file using AST parsing. "
            "Returns names, types, line ranges, and parameters. "
            "Use this to understand file structure before reading specific sections."
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path relative to the repository root.",
                },
            },
            "required": ["path"],
        },
        handler=get_symbols,
    )

    async def find_references(**kwargs) -> str:
        """Find all references to a symbol."""
        name = kwargs.get("name") or kwargs.get("symbol") or kwargs.get("query") or ""
        if not name:
            return "Error: 'name' parameter is required"

        refs = indexer.symbol_table.find_references(name)
        if not refs:
            return f"No references found for '{name}'."

        definitions = [r for r in refs if r.get("type") == "definition"]
        references = [r for r in refs if r.get("type") == "reference"]

        lines = [f"References for '{name}' ({len(refs)} total):\n"]

        if definitions:
            lines.append(f"Definitions ({len(definitions)}):")
            for d in definitions[:20]:
                lines.append(f"  {d['file_path']}:{d['line']} ({d.get('kind', 'unknown')})")

        if references:
            lines.append(f"\nUsages ({len(references)}):")
            for r in references[:30]:
                lines.append(f"  {r['file_path']}:{r['line']}")
            if len(references) > 30:
                lines.append(f"  ... and {len(references) - 30} more")

        return "\n".join(lines)

    registry.register(
        name="find_references",
        description=(
            "Find all definitions and usages of a symbol across the codebase. "
            "Uses heuristic matching (not a precise call graph). "
            "Useful for understanding impact of changes."
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "The symbol name to find references for.",
                },
            },
            "required": ["name"],
        },
        handler=find_references,
    )
