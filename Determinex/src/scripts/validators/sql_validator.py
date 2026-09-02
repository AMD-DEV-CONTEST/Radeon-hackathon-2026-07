"""
validators/sql_validator.py — SQL syntax + optional dialect check
==================================================================
Validates SQL output via:
  1. `sqlparse` token balance check (always available — pure Python).
  2. Optional `sqlfluff parse --dialect <X>` for true grammar validation.

Supported dialects (matched against task_meta['sql_dialect']):
  postgres, mysql, sqlite, mssql, oracle, bigquery, snowflake, ansi
Default dialect when unspecified: ansi (most permissive).
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile

log = logging.getLogger("oracle.validator.sql")

_FENCE_RE = re.compile(r"^```(?:sql|postgres|postgresql|mysql)?\s*\n|\n```\s*$", flags=re.MULTILINE)

_VALID_DIALECTS = {
    "postgres",
    "mysql",
    "sqlite",
    "mssql",
    "oracle",
    "bigquery",
    "snowflake",
    "ansi",
    "tsql",
    "redshift",
}


def _strip_markdown_fences(code: str) -> str:
    return _FENCE_RE.sub("", code.strip()).strip()


def _balance_check(sql: str) -> tuple[bool, str]:
    """Cheap structural sanity: paren and quote balance."""
    paren = 0
    in_single = False
    in_double = False
    in_bt = False
    in_line_comment = False
    in_block_comment = False
    i = 0
    while i < len(sql):
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < len(sql) else ""
        if in_line_comment:
            if ch == "\n":
                in_line_comment = False
            i += 1
            continue
        if in_block_comment:
            if ch == "*" and nxt == "/":
                in_block_comment = False
                i += 2
                continue
            i += 1
            continue
        if in_single:
            if ch == "'" and nxt == "'":
                i += 2
                continue
            if ch == "'":
                in_single = False
            i += 1
            continue
        if in_double:
            if ch == '"' and nxt == '"':
                i += 2
                continue
            if ch == '"':
                in_double = False
            i += 1
            continue
        if in_bt:
            if ch == "`":
                in_bt = False
            i += 1
            continue
        if ch == "-" and nxt == "-":
            in_line_comment = True
            i += 2
            continue
        if ch == "/" and nxt == "*":
            in_block_comment = True
            i += 2
            continue
        if ch == "'":
            in_single = True
        elif ch == '"':
            in_double = True
        elif ch == "`":
            in_bt = True
        elif ch == "(":
            paren += 1
        elif ch == ")":
            paren -= 1
            if paren < 0:
                return False, "unbalanced parentheses (extra `)`)"
        i += 1
    if paren != 0:
        return False, f"unbalanced parentheses (delta {paren:+d})"
    if in_single:
        return False, "unterminated single-quoted string"
    if in_double:
        return False, "unterminated double-quoted identifier"
    if in_bt:
        return False, "unterminated backtick identifier"
    if in_block_comment:
        return False, "unterminated /* ... */ comment"
    return True, "balance check passed"


def validate(output: str, task_meta: dict) -> tuple[bool, str]:
    """
    Validate SQL.

    task_meta keys:
        sql_dialect (str):     one of _VALID_DIALECTS (default: ansi)
        require_statement (bool): require >=1 non-trivial SQL statement
        skip_sqlfluff (bool):  skip optional sqlfluff parse
    """
    sql = _strip_markdown_fences(output)
    if len(sql.strip()) < 5:
        return False, "Output too short to be valid SQL"

    ok, reason = _balance_check(sql)
    if not ok:
        return False, reason

    if task_meta.get("require_statement", True):
        normalized = re.sub(r"--[^\n]*", "", sql)
        normalized = re.sub(r"/\*.*?\*/", "", normalized, flags=re.DOTALL)
        if not re.search(
            r"\b(SELECT|INSERT|UPDATE|DELETE|CREATE|ALTER|DROP|WITH|MERGE)\b",
            normalized,
            flags=re.IGNORECASE,
        ):
            return False, "no recognizable SQL statement keyword found"

    if task_meta.get("skip_sqlfluff"):
        return True, reason

    sqlfluff = shutil.which("sqlfluff") or shutil.which("sqlfluff.exe")
    if not sqlfluff:
        return True, f"{reason} (sqlfluff unavailable)"

    dialect = task_meta.get("sql_dialect", "ansi").lower()
    if dialect not in _VALID_DIALECTS:
        return False, f"unknown sql_dialect '{dialect}'"

    with tempfile.NamedTemporaryFile("w", suffix=".sql", delete=False, encoding="utf-8") as fh:
        fh.write(sql)
        path = fh.name
    try:
        result = subprocess.run(
            [sqlfluff, "parse", "--dialect", dialect, "--format", "json", path],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0:
            return True, f"{reason} + sqlfluff/{dialect} clean"
        try:
            payload = json.loads(result.stdout or "[]")
        except json.JSONDecodeError:
            payload = []
        violations = []
        if isinstance(payload, list):
            for file_entry in payload:
                violations.extend(file_entry.get("violations", []))
        errors = [v for v in violations if str(v.get("code", "")).startswith("PRS")]
        if errors:
            first = errors[0]
            return (
                False,
                f"sqlfluff parse error {first.get('code')}: {first.get('description')} @ L{first.get('line_no')}",
            )
        return True, f"{reason} + sqlfluff/{dialect} clean (no parse errors)"
    except subprocess.TimeoutExpired:
        return False, "sqlfluff timeout"
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
