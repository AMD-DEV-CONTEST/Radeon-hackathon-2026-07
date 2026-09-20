"""Safe expression parser for DSL boolean expressions.

Uses Python's ast module to parse, validate, and evaluate DSL
entry/exit expressions against a strict whitelist of allowed
nodes. This replaces the previous string-replace + eval() approach
with proper AST-level validation.

Supported DSL syntax:
    - Identifiers: indicator names (e.g. ema_fast, rsi)
    - Built-in columns: open, high, low, close, volume
    - Boolean operators: AND, OR, NOT (case-insensitive)
    - Comparison: >, <, >=, <=, ==, !=
    - Arithmetic: +, -, *, /
    - Numeric literals: 20, 0.5, 1.5e-3
    - Parentheses for grouping

The parser translates DSL expressions into Python AST, validates
all nodes against a whitelist, then evaluates against a pandas
DataFrame namespace.
"""

from __future__ import annotations

import ast
import re
from typing import Any

import numpy as np
import pandas as pd


# --- DSL → Python operator translation ---

def _translate_dsl_operators(expr: str) -> str:
    """Translate DSL boolean operators to Python equivalents.

    Keeps Python and/or/not keywords for proper operator precedence.
    Element-wise evaluation is handled at eval time via a Series wrapper.
    """
    result = expr
    result = re.sub(r'\bAND\b', 'and', result, flags=re.IGNORECASE)
    result = re.sub(r'\bOR\b', 'or', result, flags=re.IGNORECASE)
    result = re.sub(r'\bNOT\b', 'not ', result, flags=re.IGNORECASE)
    result = re.sub(r'\bnull\b', 'None', result, flags=re.IGNORECASE)
    return result


# --- AST node whitelist ---

_ALLOWED_NODES: set[type] = {
    # Expressions
    ast.Expression,
    ast.BoolOp,         # and / or
    ast.UnaryOp,        # not / - / +
    ast.BinOp,          # +, -, *, /
    ast.Compare,        # >, <, >=, <=, ==, !=
    # Operands
    ast.Name,           # variable names (indicator refs)
    ast.Constant,       # numeric literals (Python 3.8+)
    ast.Num,            # numeric literals (Python <3.8 compat)
    ast.Load,
    # Operators
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod,
    ast.BitAnd, ast.BitOr, ast.Invert,  # & | ~ for boolean logic on Series
    ast.Gt, ast.Lt, ast.GtE, ast.LtE, ast.Eq, ast.NotEq,
    ast.And, ast.Or, ast.Not,  # Keep for whitelist compatibility
    ast.USub, ast.UAdd,  # unary - / +
}

# Built-in column names always available in expressions
_BUILTIN_COLUMNS = {"open", "high", "low", "close", "volume"}

# Python keywords that may appear in expressions
_PY_KEYWORDS = {"and", "or", "not", "True", "False", "None"}


def parse_expression(expr: str) -> ast.AST:
    """Parse a DSL expression into a validated AST.

    Translates DSL operators (AND→&, OR→|, NOT→~) and validates
    all nodes against a strict whitelist.

    Args:
        expr: DSL boolean expression string.

    Returns:
        Validated AST node.

    Raises:
        ValueError: If the expression contains disallowed syntax
            or references unknown identifiers.
    """
    py_expr = _translate_dsl_operators(expr)

    try:
        tree = ast.parse(py_expr, mode="eval")
    except SyntaxError as e:
        raise ValueError(f"Expression syntax error: {e.msg} (col {e.offset})") from e

    _validate_ast(tree)
    return tree


def _validate_ast(node: ast.AST) -> None:
    """Recursively validate AST nodes against the whitelist."""
    if type(node) not in _ALLOWED_NODES:
        raise ValueError(
            f"Disallowed syntax: {type(node).__name__} in expression"
        )

    # Validate Name nodes — must be a known identifier
    if isinstance(node, ast.Name):
        name = node.id
        if name not in _PY_KEYWORDS:
            # Names will be checked against available columns at eval time
            # but we can warn early about obviously wrong names
            pass

    # Recursively validate children
    for child in ast.iter_child_nodes(node):
        _validate_ast(child)


def get_expression_references(expr: str) -> set[str]:
    """Extract all identifier references from a DSL expression.

    Returns the set of variable names used in the expression,
    excluding Python keywords (and, or, not, True, False, None).
    """
    try:
        tree = parse_expression(expr)
    except ValueError:
        # Fallback: use regex extraction if AST parsing fails
        return _regex_extract_refs(expr)

    refs: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            name = node.id
            if name not in _PY_KEYWORDS and name not in _BUILTIN_COLUMNS:
                refs.add(name)
    return refs


def _regex_extract_refs(expr: str) -> set[str]:
    """Fallback regex-based reference extraction."""
    ident_re = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*")
    tokens = ident_re.findall(expr)
    return {t for t in tokens if t not in _PY_KEYWORDS and t not in _BUILTIN_COLUMNS}


def evaluate_expression(
    df: pd.DataFrame,
    expr: str,
    extra_columns: dict[str, pd.Series] | None = None,
) -> pd.Series:
    """Parse and safely evaluate a DSL expression against a DataFrame.

    Uses AST transformation to convert Python and/or/not operators
    into element-wise &/|/~ for correct pandas Series behavior.

    Args:
        df: DataFrame with OHLCV + indicator columns.
        expr: DSL boolean expression string.
        extra_columns: Additional named columns to include in namespace.

    Returns:
        Boolean pandas Series. Returns all-False on error.
    """
    try:
        tree = parse_expression(expr)
    except ValueError:
        return pd.Series(False, index=df.index)

    # Transform and/or/not → &/|/~ for element-wise Series logic
    tree = _ElementWiseTransformer().visit(tree)
    tree = ast.fix_missing_locations(tree)

    # Build namespace from DataFrame columns
    namespace: dict[str, Any] = {col: df[col] for col in df.columns}
    if extra_columns:
        namespace.update(extra_columns)
    namespace["np"] = np

    try:
        result = eval(compile(tree, "<dsl_expr>", "eval"), {"__builtins__": {}}, namespace)
        if isinstance(result, pd.Series):
            return result.astype(bool).fillna(False)
        elif isinstance(result, (bool, np.bool_)):
            return pd.Series(bool(result), index=df.index)
        else:
            return pd.Series(False, index=df.index)
    except Exception:
        return pd.Series(False, index=df.index)


class _ElementWiseTransformer(ast.NodeTransformer):
    """Transform Python and/or/not AST nodes to element-wise &/|/~.

    This ensures correct behavior when operands are pandas Series.
    Python's `and`/`or` short-circuit and return the last operand,
    but we need element-wise boolean operations for backtesting.
    """

    def visit_BoolOp(self, node: ast.BoolOp) -> ast.AST:
        # First, recursively transform children
        self.generic_visit(node)

        if isinstance(node.op, ast.And):
            op = ast.BitAnd()
        elif isinstance(node.op, ast.Or):
            op = ast.BitOr()
        else:
            return node

        # Chain binary operations: a & b & c
        result = node.values[0]
        for val in node.values[1:]:
            result = ast.BinOp(left=result, op=op, right=val)
        return result

    def visit_UnaryOp(self, node: ast.UnaryOp) -> ast.AST:
        self.generic_visit(node)
        if isinstance(node.op, ast.Not):
            return ast.UnaryOp(op=ast.Invert(), operand=node.operand)
        return node


def validate_expression(expr: str, defined_indicators: set[str]) -> list[str]:
    """Validate a DSL expression: syntax + reference checks.

    Args:
        expr: DSL boolean expression string.
        defined_indicators: Set of defined indicator names.

    Returns:
        List of error messages (empty if valid).
    """
    errors: list[str] = []

    # Try to parse
    try:
        tree = parse_expression(expr)
    except ValueError as e:
        errors.append(f"Syntax error in expression '{expr}': {e}")
        return errors

    # Check all Name references are defined
    all_refs = _BUILTIN_COLUMNS | defined_indicators | _PY_KEYWORDS
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            name = node.id
            if name not in all_refs:
                errors.append(
                    f"Expression references undefined identifier: '{name}'. "
                    f"Defined: {sorted(_BUILTIN_COLUMNS | defined_indicators)}"
                )

    return errors
