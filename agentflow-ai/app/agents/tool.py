from __future__ import annotations

import ast
from datetime import datetime, UTC
from typing import Any

from app.services.storage import SQLiteStorage


class SafeCalculator(ast.NodeVisitor):
    allowed = (
        ast.Expression,
        ast.BinOp,
        ast.UnaryOp,
        ast.Add,
        ast.Sub,
        ast.Mult,
        ast.Div,
        ast.Pow,
        ast.Mod,
        ast.USub,
        ast.UAdd,
        ast.Constant,
        ast.FloorDiv,
    )

    def visit(self, node: ast.AST) -> Any:
        if not isinstance(node, self.allowed):
            raise ValueError("Unsupported expression")
        return super().visit(node)

    def visit_Expression(self, node: ast.Expression) -> float:
        return self.visit(node.body)

    def visit_Constant(self, node: ast.Constant) -> float:
        if not isinstance(node.value, (int, float)):
            raise ValueError("Numbers only")
        return float(node.value)

    def visit_UnaryOp(self, node: ast.UnaryOp) -> float:
        value = self.visit(node.operand)
        if isinstance(node.op, ast.USub):
            return -value
        if isinstance(node.op, ast.UAdd):
            return value
        raise ValueError("Unsupported unary operator")

    def visit_BinOp(self, node: ast.BinOp) -> float:
        left = self.visit(node.left)
        right = self.visit(node.right)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            return left / right
        if isinstance(node.op, ast.FloorDiv):
            return left // right
        if isinstance(node.op, ast.Mod):
            return left % right
        if isinstance(node.op, ast.Pow):
            return left ** right
        raise ValueError("Unsupported operator")


class ToolAgent:
    def __init__(self, storage: SQLiteStorage) -> None:
        self.storage = storage

    def run(self, user_request: str, planner_tools: list[str]) -> list[dict[str, str]]:
        executions: list[dict[str, str]] = []
        lowered = user_request.lower()

        expression = self._extract_expression(user_request)
        if expression:
            try:
                value = SafeCalculator().visit(ast.parse(expression, mode="eval"))
                executions.append(
                    {
                        "name": "safe_calculator",
                        "input": expression,
                        "output": str(value),
                        "status": "success",
                    }
                )
            except Exception as exc:
                executions.append(
                    {
                        "name": "safe_calculator",
                        "input": expression,
                        "output": f"Calculation failed: {exc}",
                        "status": "error",
                    }
                )

        if any(keyword in lowered for keyword in ["time", "date", "today", "now"]):
            executions.append(
                {
                    "name": "clock",
                    "input": "current_datetime_utc",
                    "output": datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC"),
                    "status": "success",
                }
            )

        if any(keyword in lowered for keyword in ["documents", "files", "uploads"]) or "document_inventory" in planner_tools:
            docs = self.storage.list_documents()
            if docs:
                output = "\n".join(
                    f"- {doc['filename']} ({doc['chunk_count']} chunks, {doc['page_count']} pages)" for doc in docs[:8]
                )
            else:
                output = "No uploaded documents yet."
            executions.append(
                {
                    "name": "document_inventory",
                    "input": "list_documents",
                    "output": output,
                    "status": "success",
                }
            )

        return executions

    @staticmethod
    def _extract_expression(user_request: str) -> str | None:
        allowed = set("0123456789+-*/().% ")
        candidate = "".join(char for char in user_request if char in allowed).strip()
        if candidate and any(op in candidate for op in "+-*/%"):
            return candidate
        return None
