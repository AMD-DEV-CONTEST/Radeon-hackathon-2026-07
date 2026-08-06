"""
Tool registry with safe, practical tools for local agents.
"""

from __future__ import annotations

import ast
import logging
import operator
import os
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# Safe math operators only
_SAFE_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _safe_eval_math(expr: str) -> str:
    """Evaluate a mathematical expression safely using AST."""
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        return f"Syntax error: {e}"

    def _eval(node):
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)):
                return node.value
            raise ValueError("Only numbers allowed")
        if isinstance(node, ast.BinOp):
            left = _eval(node.left)
            right = _eval(node.right)
            op = _SAFE_OPS.get(type(node.op))
            if op is None:
                raise ValueError(f"Operator {type(node.op)} not allowed")
            return op(left, right)
        if isinstance(node, ast.UnaryOp):
            op = _SAFE_OPS.get(type(node.op))
            if op is None:
                raise ValueError("Unary operator not allowed")
            return op(_eval(node.operand))
        raise ValueError(f"Unsupported node: {type(node)}")

    try:
        result = _eval(tree)
        return str(result)
    except Exception as e:
        return f"Evaluation error: {e}"


class ToolRegistry:
    """
    Central registry of tools available to agents.
    All tools are designed to be safe for local execution.
    """

    def __init__(
        self,
        enable_python: bool = True,
        enable_web: bool = False,
        enable_fs: bool = True,
        enable_rag: bool = True,
        rag_instance=None,
        workspace_root: str = ".",
    ):
        self.workspace_root = Path(workspace_root).resolve()
        self.rag = rag_instance
        self.tools: Dict[str, Callable[..., str]] = {}

        # Always available
        self.tools["calculator"] = self.calculator

        if enable_python:
            self.tools["python_interpreter"] = self.python_interpreter

        if enable_fs:
            self.tools["list_files"] = self.list_files
            self.tools["read_file"] = self.read_file
            self.tools["write_file"] = self.write_file

        if enable_web:
            self.tools["web_search"] = self.web_search

        if enable_rag and rag_instance is not None:
            self.tools["rag_search"] = self.rag_search

    # ------------------------------------------------------------------
    # Tool implementations
    # ------------------------------------------------------------------

    def calculator(self, expression: str) -> str:
        """Evaluate a mathematical expression. Input: math expression string."""
        expression = expression.strip().strip("`")
        return _safe_eval_math(expression)

    def python_interpreter(self, code: str) -> str:
        """
        Execute a small, restricted Python snippet.
        Only basic builtins are available. Put the final answer in a variable named `result`.
        """
        # Extremely limited sandbox for demo purposes
        allowed_builtins = {
            "abs": abs,
            "min": min,
            "max": max,
            "sum": sum,
            "len": len,
            "range": range,
            "enumerate": enumerate,
            "print": print,
            "str": str,
            "int": int,
            "float": float,
            "list": list,
            "dict": dict,
            "round": round,
            "sorted": sorted,
            "zip": zip,
        }
        local_ns: Dict[str, Any] = {}
        try:
            exec(code, {"__builtins__": allowed_builtins}, local_ns)
            if "result" in local_ns:
                return str(local_ns["result"])
            return "Code executed successfully (no `result` variable set)."
        except Exception as e:
            return f"Python error: {type(e).__name__}: {e}"

    def list_files(self, path: str = ".") -> str:
        """List files and directories. Input: relative path (default: current)."""
        try:
            target = (self.workspace_root / path).resolve()
            if not str(target).startswith(str(self.workspace_root)):
                return "Access denied: path outside workspace."
            if not target.exists():
                return f"Path does not exist: {path}"
            entries = sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
            lines = []
            for e in entries:
                prefix = "[DIR] " if e.is_dir() else "      "
                lines.append(f"{prefix}{e.name}")
            return "\n".join(lines) if lines else "(empty directory)"
        except Exception as e:
            return f"list_files error: {e}"

    def read_file(self, path: str) -> str:
        """Read a text file (max 8k characters). Input: relative path."""
        try:
            target = (self.workspace_root / path).resolve()
            if not str(target).startswith(str(self.workspace_root)):
                return "Access denied: path outside workspace."
            if not target.is_file():
                return f"Not a file: {path}"
            content = target.read_text(encoding="utf-8", errors="replace")
            if len(content) > 8000:
                content = content[:8000] + "\n\n... [truncated]"
            return content
        except Exception as e:
            return f"read_file error: {e}"

    def write_file(self, path_and_content: str) -> str:
        """
        Write content to a file.
        Input format: path|||content  (use three pipes as separator)
        """
        try:
            if "|||" not in path_and_content:
                return "Invalid format. Use: path|||content"
            path, content = path_and_content.split("|||", 1)
            path = path.strip()
            target = (self.workspace_root / path).resolve()
            if not str(target).startswith(str(self.workspace_root)):
                return "Access denied: path outside workspace."
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            return f"Successfully wrote {len(content)} characters to {path}"
        except Exception as e:
            return f"write_file error: {e}"

    def web_search(self, query: str, max_results: int = 4) -> str:
        """Search the web (requires duckduckgo-search). Input: search query."""
        try:
            from duckduckgo_search import DDGS

            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=max_results))
            if not results:
                return "No results found."
            lines = []
            for i, r in enumerate(results, 1):
                lines.append(f"{i}. {r.get('title', '')}\n   {r.get('body', '')[:300]}")
            return "\n\n".join(lines)
        except ImportError:
            return "duckduckgo-search not installed. Run: pip install duckduckgo-search"
        except Exception as e:
            return f"web_search error: {e}"

    def rag_search(self, query: str) -> str:
        """Search the local knowledge base (RAG). Input: natural language query."""
        if self.rag is None:
            return "RAG is not configured."
        try:
            docs = self.rag.query(query, k=4)
            if not docs:
                return "No relevant documents found in the knowledge base."
            return docs
        except Exception as e:
            return f"rag_search error: {e}"

    # ------------------------------------------------------------------
    # Helpers for the agent
    # ------------------------------------------------------------------

    def get_tool_descriptions(self) -> str:
        """Return a human-readable list of available tools for the system prompt."""
        descriptions = {
            "calculator": "Evaluate a mathematical expression. Input: expression string (e.g. '2**10 + 15')",
            "python_interpreter": "Run a short Python snippet. Put final answer in variable `result`. Input: code",
            "list_files": "List files/directories. Input: relative path (default '.')",
            "read_file": "Read a text file. Input: relative path",
            "write_file": "Write content to a file. Input: path|||content",
            "web_search": "Search the web. Input: query string",
            "rag_search": "Search the local document knowledge base. Input: natural language query",
        }
        lines = []
        for name in self.tools:
            desc = descriptions.get(name, "No description")
            lines.append(f"- {name}: {desc}")
        return "\n".join(lines)

    def list_tool_names(self) -> List[str]:
        return list(self.tools.keys())

    def call(self, name: str, input_str: str) -> str:
        if name not in self.tools:
            return f"Unknown tool: {name}. Available: {', '.join(self.tools)}"
        try:
            return self.tools[name](input_str)
        except Exception as e:
            logger.exception(f"Tool {name} failed")
            return f"Tool execution error: {e}"
